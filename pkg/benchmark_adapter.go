package main

import (
	"SpeedFair_simplify/pkg/network"
	"SpeedFair_simplify/pkg/ofo"
	"SpeedFair_simplify/pkg/types"
	"context"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/binary"
	"fmt"
	"log"
	"sync"
)

type benchmarkOrderAuthenticator struct {
	public  map[uint64]ed25519.PublicKey
	private map[uint64]ed25519.PrivateKey
}

func newBenchmarkOrderAuthenticator(replicaCount uint64, localReplicas []uint64) *benchmarkOrderAuthenticator {
	auth := &benchmarkOrderAuthenticator{
		public:  make(map[uint64]ed25519.PublicKey, replicaCount),
		private: make(map[uint64]ed25519.PrivateKey, len(localReplicas)),
	}
	local := make(map[uint64]bool, len(localReplicas))
	for _, replicaID := range localReplicas {
		local[replicaID] = true
	}
	for replicaID := uint64(0); replicaID < replicaCount; replicaID++ {
		var encoded [8]byte
		binary.BigEndian.PutUint64(encoded[:], replicaID)
		seedMaterial := append([]byte("Themis/benchmark-ed25519-key/v1"), encoded[:]...)
		seed := sha256.Sum256(seedMaterial)
		privateKey := ed25519.NewKeyFromSeed(seed[:])
		auth.public[replicaID] = append(ed25519.PublicKey(nil), privateKey.Public().(ed25519.PublicKey)...)
		if local[replicaID] {
			auth.private[replicaID] = privateKey
		}
	}
	return auth
}

func (auth *benchmarkOrderAuthenticator) SignReplica(replicaID uint64, digest [32]byte) ([]byte, error) {
	key := auth.private[replicaID]
	if len(key) != ed25519.PrivateKeySize {
		return nil, fmt.Errorf("no benchmark signing key for replica %d", replicaID)
	}
	return ed25519.Sign(key, digest[:]), nil
}

func (auth *benchmarkOrderAuthenticator) VerifyReplica(replicaID uint64, digest [32]byte, signature []byte) bool {
	key := auth.public[replicaID]
	return len(key) == ed25519.PublicKeySize && ed25519.Verify(key, digest[:], signature)
}

type benchmarkReady struct {
	ReplicaID uint64
}

type benchmarkStart struct{}
type benchmarkFinish struct{}
type benchmarkVerified struct {
	Digest   [32]byte
	Accepted bool
}

type benchmarkProposalCommit struct {
	Height uint64
	Digest [32]byte
}

type benchmarkNodeAdapter struct {
	service      *ofo.OFOService
	replicaID    uint64
	replicaCount uint64
	leaderID     uint64
	network      network.NetworkInterface
	start        chan struct{}
	startOnce    sync.Once
	readyMu      sync.Mutex
	readySenders map[uint64]bool
	started      bool
	hosting      *benchmarkHostingAdapter
	finished     chan struct{}
	verifiedMu   sync.Mutex
	verified     map[[32]byte]*types.LeaderProposal
}

func (adapter *benchmarkNodeAdapter) HandleMessage(message network.Message) {
	switch payload := message.Payload.(type) {
	case *benchmarkReady:
		if adapter.replicaID != adapter.leaderID || message.From != payload.ReplicaID || payload.ReplicaID >= adapter.replicaCount {
			return
		}
		adapter.readyMu.Lock()
		alreadyStarted := adapter.started
		start := false
		if !adapter.started {
			adapter.readySenders[payload.ReplicaID] = true
			if uint64(len(adapter.readySenders)) == adapter.replicaCount {
				adapter.started = true
				start = true
			}
		}
		adapter.readyMu.Unlock()
		if alreadyStarted {
			if payload.ReplicaID != adapter.leaderID {
				adapter.network.Send(network.Message{Type: "BenchmarkStart", From: adapter.leaderID, To: payload.ReplicaID, Payload: &benchmarkStart{}})
			}
			return
		}
		if !start {
			return
		}
		for replicaID := uint64(0); replicaID < adapter.replicaCount; replicaID++ {
			if replicaID == adapter.leaderID {
				continue
			}
			adapter.network.Send(network.Message{Type: "BenchmarkStart", From: adapter.leaderID, To: replicaID, Payload: &benchmarkStart{}})
		}
		// All remote Start messages have been sent before the leader can begin
		// submitting transactions on those same FIFO connections.
		adapter.startOnce.Do(func() { close(adapter.start) })
		return
	case *benchmarkStart:
		if message.From == adapter.leaderID {
			adapter.startOnce.Do(func() { close(adapter.start) })
		}
	case *benchmarkVerified:
		if adapter.hosting != nil && message.From < adapter.replicaCount {
			adapter.hosting.verified <- message
		}
	case *benchmarkFinish:
		if adapter.hosting != nil && message.From < adapter.replicaCount {
			adapter.hosting.verified <- message
		} else if message.From == adapter.leaderID {
			height, state, digest := adapter.service.CommittedContext()
			log.Printf("BENCHMARK STATE replica=%d seq=%d state=%x fragment=%x", adapter.replicaID, height, state, digest)
			close(adapter.finished)
		}
	case *types.LeaderProposal:
		if message.Type != "ThemisCandidate" || message.From != adapter.leaderID {
			return
		}
		accepted := adapter.service.VerifyProposal(payload)
		digest := types.LeaderProposalDigest(payload)
		if accepted {
			adapter.verifiedMu.Lock()
			adapter.verified[digest] = payload
			adapter.verifiedMu.Unlock()
		} else {
			log.Printf("BENCHMARK FOLLOWER REJECTED CANDIDATE: replica=%d height=%d", adapter.replicaID, payload.BlockHeight)
		}
		if !adapter.network.Send(network.Message{Type: "BenchmarkVerified", From: adapter.replicaID, To: adapter.leaderID, Payload: &benchmarkVerified{Digest: digest, Accepted: accepted}}) {
			log.Printf("BENCHMARK INVALID: verification acknowledgement send failed at replica %d", adapter.replicaID)
		}
	case *benchmarkProposalCommit:
		if message.From != adapter.leaderID {
			return
		}
		adapter.verifiedMu.Lock()
		proposal := adapter.verified[payload.Digest]
		delete(adapter.verified, payload.Digest)
		adapter.verifiedMu.Unlock()
		committed := proposal != nil && proposal.BlockHeight == payload.Height && adapter.service.CommitVerifiedProposal(proposal)
		if !committed {
			log.Printf("BENCHMARK HOSTING COMMIT REJECTED: replica=%d height=%d", adapter.replicaID, payload.Height)
		}
	default:
		adapter.service.HandleMessage(message)
	}
}

// This gate matches AUTIG's n-f verification acknowledgements; it is not BFT consensus.
type benchmarkHostingAdapter struct {
	mu           sync.Mutex
	network      network.NetworkInterface
	service      *ofo.OFOService
	replicaCount uint64
	faultCount   uint64
	leaderID     uint64
	verified     chan network.Message
}

func (adapter *benchmarkHostingAdapter) Propose(ctx context.Context, proposal *types.LeaderProposal) bool {
	adapter.mu.Lock()
	defer adapter.mu.Unlock()
	if ctx.Err() != nil || proposal == nil {
		return false
	}
	if !adapter.service.VerifyProposal(proposal) {
		log.Printf("BENCHMARK LEADER REJECTED LOCAL CANDIDATE: height=%d", proposal.BlockHeight)
		return false
	}
	digest := types.LeaderProposalDigest(proposal)
	for replicaID := uint64(0); replicaID < adapter.replicaCount; replicaID++ {
		if replicaID == adapter.leaderID {
			continue
		}
		if !adapter.network.Send(network.Message{Type: "ThemisCandidate", From: adapter.leaderID, To: replicaID, Payload: proposal}) {
			log.Printf("BENCHMARK CANDIDATE SEND FAILURE: to replica %d", replicaID)
			return false
		}
	}
	accepted := map[uint64]bool{adapter.leaderID: true}
	for uint64(len(accepted)) < adapter.replicaCount-adapter.faultCount {
		select {
		case message := <-adapter.verified:
			ack := message.Payload.(*benchmarkVerified)
			if ack.Digest != digest || message.From >= adapter.replicaCount || accepted[message.From] {
				continue
			}
			if !ack.Accepted {
				log.Printf("BENCHMARK INVALID: candidate rejected by replica %d", message.From)
				return false
			}
			accepted[message.From] = true
		case <-ctx.Done():
			return false
		}
	}
	if ctx.Err() != nil {
		return false
	}
	if !adapter.service.CommitVerifiedProposal(proposal) {
		log.Printf("BENCHMARK HOSTING LEADER COMMIT REJECTED: height=%d", proposal.BlockHeight)
		return false
	}
	for replicaID := uint64(0); replicaID < adapter.replicaCount; replicaID++ {
		if replicaID == adapter.leaderID {
			continue
		}
		if !adapter.network.Send(network.Message{
			Type: "BenchmarkThemisCommit", From: adapter.leaderID, To: replicaID,
			Payload: &benchmarkProposalCommit{Height: proposal.BlockHeight, Digest: digest},
		}) {
			log.Printf("BENCHMARK COMMIT SEND FAILURE: to replica %d", replicaID)
		}
	}
	return true
}
