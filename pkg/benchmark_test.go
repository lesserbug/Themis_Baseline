package main

import (
	"SpeedFair_simplify/pkg/network"
	"SpeedFair_simplify/pkg/ofo"
	"SpeedFair_simplify/pkg/types"
	"context"
	"testing"
	"time"
)

type benchmarkTestNetwork struct{ send func(network.Message) bool }

func (n *benchmarkTestNetwork) Register(uint64, func(network.Message)) {}
func (n *benchmarkTestNetwork) Send(m network.Message) bool            { return n.send(m) }
func (n *benchmarkTestNetwork) Stop()                                  {}
func (n *benchmarkTestNetwork) WaitForPeers(time.Duration) error       { return nil }

func TestGeneratorCatchesUpBeforeCutoff(t *testing.T) {
	var submitted int32
	var failed int64
	var calls int
	var lastSubmission time.Time
	net := &benchmarkTestNetwork{send: func(m network.Message) bool {
		calls++
		tx := m.Payload.(*types.Transaction)
		if tx.SubmissionTime.Before(lastSubmission) {
			t.Error("backdated submission")
		}
		lastSubmission = tx.SubmissionTime
		if calls == 1 {
			time.Sleep(200 * time.Millisecond)
		}
		return true
	}}
	start := time.Now()
	deadline := start.Add(600 * time.Millisecond)
	ctx, cancel := context.WithDeadline(context.Background(), deadline)
	defer cancel()
	submitTransactions(ctx, net, 1, 100, 16, &submitted, &failed, start)
	if submitted < 50 || submitted > 60 || failed != 0 {
		t.Fatalf("submitted=%d failed=%d; generator did not catch up", submitted, failed)
	}
	if !lastSubmission.Before(deadline) {
		t.Fatal("generated after deadline")
	}
}

func TestHostingWaitsForDistinctMatchingAcknowledgements(t *testing.T) {
	net := &benchmarkTestNetwork{send: func(network.Message) bool { return true }}
	auth := newBenchmarkOrderAuthenticator(5, []uint64{0, 1, 2, 3, 4})
	service, err := ofo.NewOFOService(0, 5, 1, 1, net, 20, 10, false, auth)
	if err != nil {
		t.Fatal(err)
	}
	defer service.Stop()
	canonical := []byte("benchmark quorum test")
	a := types.TransactionID(canonical)
	service.HandleMessage(network.Message{Payload: &types.Transaction{ID: a, CanonicalBytes: canonical, SubmissionTime: time.Now()}})
	proposal := &types.LeaderProposal{BlockHeight: 1, Graph: &types.DependencyGraph{Nodes: map[[32]byte]bool{a: true}, Edges: map[[32]byte][][32]byte{}}, TxStates: map[[32]byte]types.TxState{a: types.StateSolid}, Proof: &types.LocalOrderFragment{}}
	for id := uint64(0); id < 4; id++ {
		local := &types.LocalOrder{ReplicaID: id, Sequence: 1, OrderedTxs: [][32]byte{a}}
		local.Signature, _ = auth.SignReplica(id, types.LocalOrderDigest(local))
		proposal.Proof.ReplicaOrders = append(proposal.Proof.ReplicaOrders, &types.ReplicaOrders{ReplicaID: id, Sequence: 1, NewTxOrder: local})
	}
	adapter := &benchmarkHostingAdapter{network: net, service: service, replicaCount: 5, faultCount: 1, verified: make(chan network.Message, 10)}
	digest := types.LeaderProposalDigest(proposal)
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	done := make(chan bool, 1)
	go func() { done <- adapter.Propose(ctx, proposal) }()
	// Leader plus two distinct followers is below n-f. Duplicates and other digests do not help.
	for _, id := range []uint64{1, 1, 2} {
		adapter.verified <- network.Message{From: id, Payload: &benchmarkVerified{Digest: digest, Accepted: true}}
	}
	adapter.verified <- network.Message{From: 3, Payload: &benchmarkVerified{Accepted: true}}
	select {
	case <-done:
		t.Fatal("committed below quorum")
	case <-time.After(30 * time.Millisecond):
	}
	if service.GetFinalizedCount() != 0 {
		t.Fatal("finalized before verification quorum")
	}
	adapter.verified <- network.Message{From: 3, Payload: &benchmarkVerified{Digest: digest, Accepted: true}}
	if !<-done || service.GetFinalizedCount() != 1 {
		t.Fatal("failed to commit matching quorum")
	}
}
