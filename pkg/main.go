// package main

// import (
// 	"SpeedFair_simplify/pkg/network"
// 	"SpeedFair_simplify/pkg/ofo"
// 	"SpeedFair_simplify/pkg/types"
// 	"context"
// 	"crypto/sha256"
// 	"encoding/gob"
// 	"encoding/json"
// 	"flag"
// 	"fmt"
// 	"io/ioutil"
// 	"log"
// 	"math/rand"
// 	"os"
// 	"os/signal"
// 	"runtime/pprof"
// 	"strconv"
// 	"strings"
// 	"sync"
// 	"sync/atomic"
// 	"syscall"
// 	"time"
// )

// func init() {
// 	gob.Register(&types.Transaction{})
// 	gob.Register(&types.LeaderProposal{})
// 	gob.Register(&types.ReplicaOrders{})
// 	gob.Register(&types.UpdateOrder{})
// 	gob.Register(&types.LocalOrder{})
// 	gob.Register(&types.LocalOrderFragment{})
// 	gob.Register(map[[32]byte]types.TxState{})
// }

// const (
// 	LEADER_REPLICA_ID = 0
// )

// type Config struct {
// 	Nodes map[string]string `json:"nodes"`
// }

// func main() {
// 	var (
// 		configFile  = flag.String("config", "config.json", "JSON config file for node addresses")
// 		nodeList    = flag.String("nodes", "", "Comma-separated list of node IDs to run on this instance")
// 		cpuProfile  = flag.Bool("cpuprofile", false, "Enable CPU profiling for this instance")
// 		faultCount  = flag.Uint64("f", 1, "Number of tolerated faulty replicas")
// 		gamma       = flag.Float64("gamma", 0.90, "Fairness parameter gamma")
// 		loInterval  = flag.Int("lo-interval", 150, "Interval in milliseconds for generating local orders")
// 		loSize      = flag.Int("lo-size", 200, "Maximum number of transactions in one LocalOrder")
// 		txRate      = flag.Int("tx-rate", 7000, "Transaction submission rate (tx/s)")
// 		simDuration = flag.Int("sim-duration", 30, "Simulation duration in seconds")
// 	)
// 	flag.Parse()
// 	if *cpuProfile {
// 		f, _ := os.Create(fmt.Sprintf("themis_cpu_nodes_%s.pprof", strings.Replace(*nodeList, ",", "_", -1)))
// 		if f != nil {
// 			if err := pprof.StartCPUProfile(f); err != nil {
// 				log.Fatal("could not start CPU profile: ", err)
// 			}
// 			defer pprof.StopCPUProfile()
// 		}
// 	}
// 	config, totalNodesFromConfig := readJSONConfig(*configFile)
// 	nodesToRun := parseNodeList(*nodeList)
// 	if len(nodesToRun) == 0 {
// 		log.Fatal("No nodes specified. Use -nodes flag.")
// 	}
// 	fmt.Printf("--- Starting Themis Protocol Simulation ---\n")
// 	fmt.Printf("Nodes on this instance: %v\n", nodesToRun)
// 	fmt.Printf("System params: N=%d, F=%d, Gamma=%.2f\n", totalNodesFromConfig, *faultCount, *gamma)
// 	fmt.Printf("Malicious replicas are IDs >= %d\n", totalNodesFromConfig-*faultCount)
// 	fmt.Printf("Workload params: TxRate=%d/s, LO-Interval=%dms, LO-Size=%d\n", *txRate, *loInterval, *loSize)
// 	fmt.Printf("Simulation duration: %d seconds\n\n", *simDuration)
// 	ctx, cancel := context.WithCancel(context.Background())
// 	defer cancel()
// 	shutdownSignal := make(chan os.Signal, 1)
// 	signal.Notify(shutdownSignal, os.Interrupt, syscall.SIGTERM)
// 	go func() {
// 		<-shutdownSignal
// 		log.Println("\nReceived shutdown signal, initiating graceful shutdown...")
// 		cancel()
// 	}()
// 	timeoutCtx, timeoutCancel := context.WithTimeout(ctx, time.Duration(*simDuration)*time.Second)
// 	defer timeoutCancel()
// 	runDistributedMode(timeoutCtx, nodesToRun, config, totalNodesFromConfig, *faultCount, *gamma, *loInterval, *loSize, *txRate)
// }
// func runDistributedMode(ctx context.Context, nodeIDs []uint64, config map[uint64]string, totalNodes, faultCount uint64, gamma float64, loIntervalMs, loSize, txRate int) {
// 	var wg sync.WaitGroup
// 	services := make(map[uint64]*ofo.OFOService)
// 	var servicesMu sync.Mutex
// 	maliciousThresholdID := totalNodes - faultCount
// 	for _, nodeID := range nodeIDs {
// 		wg.Add(1)
// 		go func(id uint64) {
// 			defer wg.Done()
// 			netConfig := network.NetworkConfig{ReplicaID: id, ReplicaAddr: config}
// 			net, err := network.NewDistributedNetwork(netConfig)
// 			if err != nil {
// 				log.Printf("Node %d failed to create network: %v", id, err)
// 				return
// 			}
// 			defer net.Stop()
// 			log.Printf("Node %d waiting for peers to connect...", id)
// 			if err := net.WaitForPeers(30 * time.Second); err != nil {
// 				log.Printf("FATAL: Node %d could not connect to all peers, shutting down. Error: %v", id, err)
// 				return
// 			}
// 			isMalicious := id >= maliciousThresholdID
// 			if isMalicious {
// 				log.Printf("Node %d is starting as a MALICIOUS replica.", id)
// 			}
// 			service := ofo.NewOFOService(id, totalNodes, faultCount, gamma, net, loSize, loIntervalMs, isMalicious)
// 			servicesMu.Lock()
// 			services[id] = service
// 			servicesMu.Unlock()
// 			service.Start(ctx)
// 			<-ctx.Done()
// 			log.Printf("Node %d shutting down...", id)
// 			service.Stop()
// 		}(nodeID)
// 	}
// 	var submittedTxCount int32
// 	var txSubmitterWg sync.WaitGroup
// 	txSubmitterWg.Add(1)
// 	go func() {
// 		defer txSubmitterWg.Done()
// 		var targetNet network.NetworkInterface
// 		for {
// 			servicesMu.Lock()
// 			if service, ok := services[LEADER_REPLICA_ID]; ok && service != nil {
// 				targetNet = service.Network()
// 			}
// 			servicesMu.Unlock()
// 			if targetNet != nil {
// 				break
// 			}
// 			select {
// 			case <-time.After(100 * time.Millisecond):
// 			case <-ctx.Done():
// 				return
// 			}
// 		}
// 		submitTransactions(ctx, targetNet, totalNodes, txRate, &submittedTxCount)
// 	}()
// 	var monitorWg sync.WaitGroup
// 	monitorWg.Add(1)
// 	go func() {
// 		defer monitorWg.Done()
// 		simDurationVal, _ := strconv.Atoi(flag.Lookup("sim-duration").Value.String())
// 		monitorSystem(ctx, services, &servicesMu, &submittedTxCount, simDurationVal)
// 	}()
// 	wg.Wait()
// 	txSubmitterWg.Wait()
// 	monitorWg.Wait()
// 	fmt.Println("\nAll nodes on this instance have shut down.")
// }
// func submitTransactions(ctx context.Context, net network.NetworkInterface, totalNodes uint64, txRate int, submittedCounter *int32) {
// 	if txRate <= 0 {
// 		return
// 	}
// 	interval := time.Second / time.Duration(txRate)
// 	if interval == 0 {
// 		interval = time.Nanosecond
// 	}
// 	ticker := time.NewTicker(interval)
// 	defer ticker.Stop()
// 	txCounter := 0
// 	log.Println("Transaction submission started.")
// 	for {
// 		select {
// 		case <-ticker.C:
// 			txCounter++
// 			atomic.AddInt32(submittedCounter, 1)
// 			txHash := sha256.Sum256([]byte(fmt.Sprintf("tx-%d-%d", txCounter, rand.Intn(1e9))))
// 			tx := &types.Transaction{ID: txHash, SubmissionTime: time.Now()}
// 			for i := uint64(0); i < totalNodes; i++ {
// 				net.Send(network.Message{Type: "Transaction", From: LEADER_REPLICA_ID, To: i, Payload: tx})
// 			}
// 		case <-ctx.Done():
// 			log.Println("Transaction submission stopping...")
// 			return
// 		}
// 	}
// }
// func monitorSystem(ctx context.Context, services map[uint64]*ofo.OFOService, servicesMu *sync.Mutex, submittedCounter *int32, simDuration int) {
// 	var leaderService *ofo.OFOService
// 	for {
// 		servicesMu.Lock()
// 		leaderService = services[LEADER_REPLICA_ID]
// 		servicesMu.Unlock()
// 		if leaderService != nil {
// 			break
// 		}
// 		select {
// 		case <-time.After(100 * time.Millisecond):
// 		case <-ctx.Done():
// 			return
// 		}
// 	}
// 	monitorTicker := time.NewTicker(time.Second)
// 	defer monitorTicker.Stop()
// 	startTime := time.Now()
// 	leaderCompletionChan := leaderService.GetLeaderCompletionChan()
// 	if leaderCompletionChan == nil {
// 		log.Fatal("Leader's completion channel is nil!")
// 	}
// 	log.Println("Monitoring started.")
// monitorLoop:
// 	for {
// 		select {
// 		case <-monitorTicker.C:
// 			finalized := leaderService.GetFinalizedCount()
// 			submitted := atomic.LoadInt32(submittedCounter)
// 			elapsed := time.Since(startTime).Seconds()
// 			tps := 0.0
// 			if elapsed > 0 {
// 				tps = float64(finalized) / elapsed
// 			}
// 			avgLatency, _ := leaderService.GetLatencyStats()
// 			poolSize := leaderService.GetTxPoolSize()
// 			lastOrderSize := leaderService.GetLastProposedOrderSize()
// 			fmt.Printf("\r[%.1fs] Finalized: %d | Submitted: %d | TPS: %.2f | Latency: %s | Pool: %d | LastOrder: %d",
// 				elapsed, finalized, submitted, tps, avgLatency.Round(time.Millisecond), poolSize, lastOrderSize)
// 		case <-ctx.Done():
// 			break monitorLoop
// 		}
// 	}
// 	<-ctx.Done()
// 	time.Sleep(100 * time.Millisecond)
// 	printFinalReport(startTime, leaderService.GetFinalizedCount(), int(atomic.LoadInt32(submittedCounter)), leaderService)
// }
// func printFinalReport(startTime time.Time, finalizedCount int, totalSubmitted int, leaderService *ofo.OFOService) {
// 	fmt.Println("\n\n--- FINAL RESULTS (Themis) ---")
// 	actualDuration := time.Since(startTime).Seconds()
// 	if actualDuration < 1.0 {
// 		actualDuration = 1.0
// 	}
// 	throughput := float64(finalizedCount) / actualDuration
// 	avgLatency, latencyCount := leaderService.GetLatencyStats()
// 	fmt.Printf("Total Submitted: %d\n", totalSubmitted)
// 	fmt.Printf("Total Finalized: %d\n", finalizedCount)
// 	fmt.Printf("Throughput: %.2f TPS\n", throughput)
// 	latencyStr := "N/A"
// 	if latencyCount > 0 {
// 		latencyStr = avgLatency.Round(time.Millisecond).String()
// 	}
// 	fmt.Printf("Average Latency: %s (from %d txs)\n", latencyStr, latencyCount)
// }

// // *** 核心修复: 添加缺失的辅助函数 ***
// func readJSONConfig(filename string) (map[uint64]string, uint64) {
// 	data, err := ioutil.ReadFile(filename)
// 	if err != nil {
// 		log.Fatalf("Failed to read config file %s: %v", filename, err)
// 	}
// 	var jsonConfig Config
// 	if err := json.Unmarshal(data, &jsonConfig); err != nil {
// 		log.Fatalf("Failed to parse config file: %v", err)
// 	}
// 	config := make(map[uint64]string)
// 	var maxID uint64 = 0
// 	for k, v := range jsonConfig.Nodes {
// 		id, _ := strconv.ParseUint(k, 10, 64)
// 		if id > maxID {
// 			maxID = id
// 		}
// 		config[id] = v
// 	}
// 	return config, maxID + 1
// }
// func parseNodeList(nodeList string) []uint64 {
// 	if nodeList == "" {
// 		return []uint64{}
// 	}
// 	parts := strings.Split(nodeList, ",")
// 	nodes := make([]uint64, 0, len(parts))
// 	for _, part := range parts {
// 		id, _ := strconv.ParseUint(strings.TrimSpace(part), 10, 64)
// 		nodes = append(nodes, id)
// 	}
// 	return nodes
// }

package main

import (
	"SpeedFair_simplify/pkg/network"
	"SpeedFair_simplify/pkg/ofo"
	"SpeedFair_simplify/pkg/types"
	"context"
	"encoding/binary"
	"encoding/gob"
	"encoding/json"
	"flag"
	"fmt"
	"io/ioutil"
	"log"
	"math/rand"
	"os"
	"os/signal"
	"runtime/debug"
	"runtime/pprof"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
)

func init() {
	gob.Register(&types.Transaction{})
	gob.Register(&types.LeaderProposal{})
	gob.Register(&types.ReplicaOrders{})
	gob.Register(&types.UpdateOrder{})
	gob.Register(&types.LocalOrder{})
	gob.Register(&types.LocalOrderFragment{})
	gob.Register(map[[32]byte]types.TxState{})
	gob.Register(&benchmarkReady{})
	gob.Register(&benchmarkStart{})
	gob.Register(&benchmarkVerified{})
	gob.Register(&benchmarkFinish{})
	gob.Register(&benchmarkProposalCommit{})
}

const (
	LEADER_REPLICA_ID = 0
)

type Config struct {
	Nodes map[string]string `json:"nodes"`
}

func main() {
	var (
		configFile       = flag.String("config", "config.json", "JSON config file for node addresses")
		nodeList         = flag.String("nodes", "", "Comma-separated list of node IDs to run on this instance")
		cpuProfile       = flag.Bool("cpuprofile", false, "Enable CPU profiling for this instance")
		faultCount       = flag.Uint64("f", 1, "Number of tolerated faulty replicas")
		gamma            = flag.Float64("gamma", 0.90, "Fairness parameter gamma")
		loInterval       = flag.Int("lo-interval", 150, "Interval in milliseconds for generating local orders")
		loSize           = flag.Int("lo-size", 200, "Compatibility flag; Themis sends complete unproposed receipt lists")
		byzantineCount   = flag.Int64("byzantine-count", -1, "Actual malicious ordering replicas (default: f; must be between 0 and f)")
		byzantineLODelay = flag.Duration("byzantine-lo-delay", 0, "Extra wait before each malicious report generation/send attempt, e.g. 200ms")
		txRate           = flag.Int("tx-rate", 7000, "Transaction submission rate (tx/s)")
		txSize           = flag.Int("tx-size", 512, "Canonical transaction size in bytes (minimum 16)")
		simDuration      = flag.Int("sim-duration", 30, "Simulation duration in seconds")
	)
	flag.Parse()
	if *byzantineLODelay < 0 {
		log.Fatal("byzantine-lo-delay must be non-negative")
	}
	if *txSize < 16 {
		log.Fatal("Transaction size must be at least 16 bytes.")
	}

	if *cpuProfile {
		f, _ := os.Create(fmt.Sprintf("themis_cpu_nodes_%s.pprof", strings.Replace(*nodeList, ",", "_", -1)))
		if f != nil {
			if err := pprof.StartCPUProfile(f); err != nil {
				log.Fatal("could not start CPU profile: ", err)
			}
			defer pprof.StopCPUProfile()
		}
	}

	config, totalNodesFromConfig := readJSONConfig(*configFile)
	nodesToRun := parseNodeList(*nodeList)
	if len(nodesToRun) == 0 {
		log.Fatal("No nodes specified. Use -nodes flag.")
	}
	if err := ofo.ValidateThemisParameters(totalNodesFromConfig, *faultCount, *gamma); err != nil {
		log.Fatal(err)
	}
	actualByzantine, err := resolveByzantineCount(totalNodesFromConfig, *faultCount, *byzantineCount)
	if err != nil {
		log.Fatal(err)
	}

	fmt.Printf("--- Starting Themis Protocol Simulation ---\n")
	printBenchmarkBuild()
	fmt.Printf("Nodes on this instance: %v\n", nodesToRun)
	fmt.Printf("System params: N=%d, F=%d, GammaAll=%.2f (Themis all-replica premise)\n", totalNodesFromConfig, *faultCount, *gamma)
	fmt.Printf("BENCHMARK FAULTS tolerated=%d byzantine=%d behavior=reverse lo_delay=%s\n", *faultCount, actualByzantine, *byzantineLODelay)
	fmt.Printf("Malicious replicas are IDs >= %d (count=%d)\n", totalNodesFromConfig-actualByzantine, actualByzantine)
	fmt.Printf("Workload params: TxRate=%d/s, TxSize=%dB, LO-Interval=%dms, LO-Size=%d (inactive compatibility field; complete lists)\n", *txRate, *txSize, *loInterval, *loSize)
	fmt.Printf("Simulation duration: %d seconds\n\n", *simDuration)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	shutdownSignal := make(chan os.Signal, 1)
	signal.Notify(shutdownSignal, os.Interrupt, syscall.SIGTERM)
	go func() {
		<-shutdownSignal
		log.Println("\nReceived shutdown signal, initiating graceful shutdown...")
		cancel()
	}()

	runDistributedMode(ctx, nodesToRun, config, totalNodesFromConfig, *faultCount, actualByzantine, *gamma, *loInterval, *loSize, *txRate, *txSize, *simDuration, *byzantineLODelay)
}

func runDistributedMode(rootCtx context.Context, nodeIDs []uint64, config map[uint64]string, totalNodes, faultCount, byzantineCount uint64, gamma float64, loIntervalMs, loSize, txRate, txSize, simDuration int, byzantineLODelay time.Duration) {
	ctx, cancel := context.WithCancel(rootCtx)
	defer cancel()
	var wg sync.WaitGroup
	services := make(map[uint64]*ofo.OFOService)
	var servicesMu sync.Mutex
	maliciousThresholdID := totalNodes - byzantineCount
	auth := newBenchmarkOrderAuthenticator(totalNodes, nodeIDs)
	experimentStart := make(chan struct{})
	submissionDone := make(chan struct{})
	localStarted := make(chan struct{}, len(nodeIDs))
	localInitFailed := make(chan struct{}, len(nodeIDs))
	var experimentCtx context.Context
	var experimentCancel context.CancelFunc
	var txSubmitterNet network.NetworkInterface
	isLeaderInstance := false
	for _, id := range nodeIDs {
		isLeaderInstance = isLeaderInstance || id == LEADER_REPLICA_ID
	}

	for _, nodeID := range nodeIDs {
		wg.Add(1)
		go func(id uint64) {
			defer wg.Done()
			netConfig := network.NetworkConfig{ReplicaID: id, ReplicaAddr: config}
			net, err := network.NewDistributedNetwork(netConfig)
			if err != nil {
				log.Printf("Node %d failed to create network: %v", id, err)
				localInitFailed <- struct{}{}
				return
			}
			defer net.Stop()

			log.Printf("Node %d waiting for peers to connect...", id)
			// [来源: Pkg/Main.go]
			if err := net.WaitForPeers(30 * time.Second); err != nil {
				log.Printf("FATAL: Node %d could not connect to all peers, shutting down. Error: %v", id, err)
				localInitFailed <- struct{}{}
				return
			}
			// *** 成功越过栅栏 ***
			log.Printf("Node %d: All peers connected!", id)

			isMalicious := id >= maliciousThresholdID
			if isMalicious {
				log.Printf("Node %d is starting as a MALICIOUS replica.", id)
			}

			service, err := ofo.NewOFOService(id, totalNodes, faultCount, gamma, net, loSize, loIntervalMs, isMalicious, auth)
			if err != nil {
				log.Printf("Node %d failed to create Themis service: %v", id, err)
				localInitFailed <- struct{}{}
				return
			}
			service.ByzantineLODelay = byzantineLODelay
			start := make(chan struct{})
			adapter := &benchmarkNodeAdapter{
				service: service, replicaID: id, replicaCount: totalNodes, leaderID: LEADER_REPLICA_ID,
				network: net, start: start, readySenders: make(map[uint64]bool), verified: make(map[[32]byte]*types.LeaderProposal), finished: make(chan struct{}),
			}
			if id == LEADER_REPLICA_ID {
				hosting := &benchmarkHostingAdapter{
					network: net, service: service, replicaCount: totalNodes, faultCount: faultCount, verified: make(chan network.Message, 2*totalNodes),
					leaderID: LEADER_REPLICA_ID,
				}
				adapter.hosting = hosting
				service.SetProposalSink(func(proposal *types.LeaderProposal) bool {
					select {
					case <-experimentStart:
					case <-ctx.Done():
						return false
					}
					return hosting.Propose(experimentCtx, proposal)
				})
				txSubmitterNet = net
			}
			net.Register(id, adapter.HandleMessage)
			servicesMu.Lock()
			services[id] = service
			servicesMu.Unlock()

			readyTicker := time.NewTicker(200 * time.Millisecond)
		readyLoop:
			for {
				net.Send(network.Message{Type: "BenchmarkReady", From: id, To: LEADER_REPLICA_ID, Payload: &benchmarkReady{ReplicaID: id}})
				select {
				case <-start:
					break readyLoop
				case <-readyTicker.C:
				case <-ctx.Done():
					readyTicker.Stop()
					service.Stop()
					return
				}
			}
			readyTicker.Stop()
			localStarted <- struct{}{}
			select {
			case <-experimentStart:
			case <-ctx.Done():
				service.Stop()
				return
			}
			if adapter.hosting != nil {
				service.Start(experimentCtx)
				service.Stop()
				<-submissionDone
				height, state, digest := service.CommittedContext()
				log.Printf("BENCHMARK STATE replica=%d seq=%d state=%x fragment=%x", id, height, state, digest)
				for peer := uint64(0); peer < totalNodes; peer++ {
					if peer != id && !net.Send(network.Message{Type: "BenchmarkFinish", From: id, To: peer, Payload: &benchmarkFinish{}}) {
						log.Printf("BENCHMARK INVALID: finish send failed to replica %d", peer)
					}
				}
				finishCtx, stopFinish := context.WithTimeout(ctx, 30*time.Second)
				finishedPeers := map[uint64]bool{id: true}
			finishLoop:
				for uint64(len(finishedPeers)) < totalNodes {
					select {
					case message := <-adapter.hosting.verified:
						if _, ok := message.Payload.(*benchmarkFinish); ok {
							finishedPeers[message.From] = true
						}
					case <-finishCtx.Done():
						log.Println("BENCHMARK INVALID: final state barrier did not complete")
						break finishLoop
					}
				}
				stopFinish()
			} else {
				// Match AUTIG: followers serve the leader's final prefix until Finish.
				loCtx, stopLO := context.WithTimeout(ctx, time.Duration(simDuration+30)*time.Second)
				defer stopLO()
				go func() {
					select {
					case <-adapter.finished:
						stopLO()
					case <-loCtx.Done():
					}
				}()
				service.Start(loCtx)
				service.Stop()
				select {
				case <-adapter.finished:
					if !net.Send(network.Message{Type: "BenchmarkFinish", From: id, To: LEADER_REPLICA_ID, Payload: &benchmarkFinish{}}) {
						log.Printf("BENCHMARK INVALID: finish acknowledgement failed at replica %d", id)
					}
				default:
					log.Printf("BENCHMARK INVALID: replica %d did not receive finish", id)
				}
			}
			log.Printf("Node %d shutting down...", id)
		}(nodeID)
	}

	for range nodeIDs {
		select {
		case <-localStarted:
		case <-localInitFailed:
			cancel()
			wg.Wait()
			return
		case <-ctx.Done():
			wg.Wait()
			return
		}
	}
	experimentStartTime := time.Now()
	experimentCtx, experimentCancel = context.WithDeadline(ctx, experimentStartTime.Add(time.Duration(simDuration)*time.Second))
	defer experimentCancel()
	if isLeaderInstance {
		services[LEADER_REPLICA_ID].MeasurementDeadline = experimentStartTime.Add(time.Duration(simDuration) * time.Second)
	}
	close(experimentStart)

	var submittedTxCount int32
	var failedTxSends int64
	if isLeaderInstance {
		wg.Add(1)
		go func() {
			defer wg.Done()
			defer close(submissionDone)
			submitTransactions(experimentCtx, txSubmitterNet, totalNodes, txRate, txSize, &submittedTxCount, &failedTxSends, experimentStartTime)
		}()
	}
	wg.Add(1)
	go func() {
		defer wg.Done()
		monitorSystem(experimentCtx, services, &servicesMu, isLeaderInstance, &submittedTxCount, &failedTxSends, submissionDone, experimentStartTime)
	}()

	wg.Wait()
	fmt.Println("\nAll nodes on this instance have shut down.")
}

// func runDistributedMode(ctx context.Context, nodeIDs []uint64, config map[uint64]string, totalNodes, faultCount uint64, gamma float64, loIntervalMs, loSize, txRate int) {
// 	var wg sync.WaitGroup
// 	services := make(map[uint64]*ofo.OFOService)
// 	var servicesMu sync.Mutex
// 	maliciousThresholdID := totalNodes - faultCount

// 	for _, nodeID := range nodeIDs {
// 		wg.Add(1)
// 		go func(id uint64) {
// 			defer wg.Done()
// 			netConfig := network.NetworkConfig{ReplicaID: id, ReplicaAddr: config}
// 			net, err := network.NewDistributedNetwork(netConfig)
// 			if err != nil {
// 				log.Printf("Node %d failed to create network: %v", id, err)
// 				return
// 			}
// 			defer net.Stop()

// 			log.Printf("Node %d waiting for peers to connect...", id)
// 			if err := net.WaitForPeers(30 * time.Second); err != nil {
// 				log.Printf("FATAL: Node %d could not connect to all peers, shutting down. Error: %v", id, err)
// 				return
// 			}

// 			isMalicious := id >= maliciousThresholdID
// 			if isMalicious {
// 				log.Printf("Node %d is starting as a MALICIOUS replica.", id)
// 			}
// 			service := ofo.NewOFOService(id, totalNodes, faultCount, gamma, net, loSize, loIntervalMs, isMalicious)

// 			servicesMu.Lock()
// 			services[id] = service
// 			servicesMu.Unlock()

// 			service.Start(ctx)

// 			<-ctx.Done()
// 			log.Printf("Node %d shutting down...", id)
// 			service.Stop()
// 		}(nodeID)
// 	}

// 	var submittedTxCount int32
// 	var txSubmitterWg sync.WaitGroup
// 	txSubmitterWg.Add(1)
// 	go func() {
// 		defer txSubmitterWg.Done()
// 		var targetNet network.NetworkInterface
// 		for {
// 			servicesMu.Lock()
// 			if len(services) > 0 {
// 				for _, s := range services {
// 					targetNet = s.Network()
// 					break
// 				}
// 			}
// 			servicesMu.Unlock()
// 			if targetNet != nil {
// 				break
// 			}
// 			select {
// 			case <-time.After(100 * time.Millisecond):
// 			case <-ctx.Done():
// 				return
// 			}
// 		}
// 		submitTransactions(ctx, targetNet, totalNodes, txRate, &submittedTxCount)
// 	}()

// 	var monitorWg sync.WaitGroup
// 	monitorWg.Add(1)
// 	go func() {
// 		defer monitorWg.Done()
// 		simDurationVal, _ := strconv.Atoi(flag.Lookup("sim-duration").Value.String())
// 		// <<< FIX: Corrected variable name from submittedCounter to submittedTxCount >>>
// 		monitorSystem(ctx, services, &servicesMu, &submittedTxCount, simDurationVal)
// 	}()

// 	wg.Wait()
// 	txSubmitterWg.Wait()
// 	monitorWg.Wait()
// 	fmt.Println("\nAll nodes on this instance have shut down.")
// }

func submitTransactions(ctx context.Context, net network.NetworkInterface, totalNodes uint64, txRate, txSize int, submittedCounter *int32, failedSendCounter *int64, startTime time.Time) {
	if txRate <= 0 {
		log.Println("Transaction submission rate is 0, no transactions will be submitted.")
		return
	}

	// Ticks only wake the scheduler; they do not represent individual arrivals.
	// Above 1000 tx/s, one wakeup can produce a small group of due transactions.
	interval := time.Second / time.Duration(txRate)
	if interval < time.Millisecond {
		interval = time.Millisecond
	}
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	var txCounter int64
	deadline, hasDeadline := ctx.Deadline()
	log.Println("Transaction submission started.")
	defer log.Println("Transaction submission stopping...")
	for {
		now := time.Now()
		if ctx.Err() != nil || (hasDeadline && !now.Before(deadline)) {
			return
		}
		elapsed := now.Sub(startTime)
		expected := int64(elapsed/time.Second)*int64(txRate) + int64(elapsed%time.Second)*int64(txRate)/int64(time.Second)
		if txCounter >= expected {
			select {
			case <-ticker.C:
			case <-ctx.Done():
				return
			}
			continue
		}
		for txCounter < expected {
			submittedAt := time.Now()
			if ctx.Err() != nil || (hasDeadline && !submittedAt.Before(deadline)) {
				return
			}
			// Count real submission attempts, never scheduled-but-uncreated work.
			// Keep the real timestamp so catch-up does not backdate latency.
			txCounter++
			atomic.AddInt32(submittedCounter, 1)
			canonical := make([]byte, txSize)
			binary.BigEndian.PutUint64(canonical[:8], uint64(txCounter))
			binary.BigEndian.PutUint64(canonical[8:16], rand.Uint64())

			tx := types.Transaction{
				ID:             types.TransactionID(canonical),
				CanonicalBytes: canonical,
				SubmissionTime: submittedAt,
			}

			for i := uint64(0); i < totalNodes; i++ {
				if !net.Send(network.Message{Type: "Transaction", From: LEADER_REPLICA_ID, To: i, Payload: &tx}) {
					atomic.AddInt64(failedSendCounter, 1)
				}
			}
		}
		// Recompute immediately: synchronous fanout may itself have accrued debt.
		// Finish an already-counted transaction's fanout, but never create new
		// transactions after the cutoff, even if the target has not been reached.
	}
}

func monitorSystem(ctx context.Context, services map[uint64]*ofo.OFOService, servicesMu *sync.Mutex, isLeaderInstance bool, submittedCounter *int32, failedSendCounter *int64, submissionDone <-chan struct{}, startTime time.Time) {
	if !isLeaderInstance {
		<-ctx.Done()
		return
	}
	servicesMu.Lock()
	leaderService := services[LEADER_REPLICA_ID]
	servicesMu.Unlock()
	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()
	log.Println("Leader monitor started.")
	for {
		select {
		case <-ticker.C:
			finalized, avgLatency, latencySamples := leaderService.GetMeasurementStats()
			printBenchmarkDiagnostics(leaderService, time.Since(startTime))
			submitted := atomic.LoadInt32(submittedCounter)
			elapsed := time.Since(startTime).Seconds()
			if elapsed < 1 {
				elapsed = 1
			}
			latency := "N/A"
			if latencySamples > 0 {
				latency = avgLatency.Round(time.Millisecond).String()
			}
			fmt.Printf("\r[LEADER] Time: %.1fs, Submitted: %d, Finalized: %d, TPS: %.2f, Mean Completed Latency: %s",
				elapsed, submitted, finalized, float64(finalized)/elapsed, latency)
		case <-ctx.Done():
			<-submissionDone
			deadline, _ := ctx.Deadline()
			if time.Now().Before(deadline) {
				log.Println("BENCHMARK INVALID: measurement cancelled before deadline")
				return
			}
			finalized, avgLatency, samples := leaderService.GetMeasurementStats()
			printBenchmarkDiagnostics(leaderService, time.Since(startTime))
			printFinalReport(deadline.Sub(startTime), finalized, atomic.LoadInt32(submittedCounter), atomic.LoadInt64(failedSendCounter), avgLatency, samples)
			return
		}
	}
}

func printBenchmarkBuild() {
	metadata := map[string]string{"revision": "unknown", "modified": "unknown"}
	if info, ok := debug.ReadBuildInfo(); ok {
		metadata["go_version"] = info.GoVersion
		for _, setting := range info.Settings {
			switch setting.Key {
			case "vcs.revision":
				metadata["revision"] = setting.Value
			case "vcs.modified":
				metadata["modified"] = setting.Value
			}
		}
	}
	data, _ := json.Marshal(metadata)
	fmt.Printf("THEMIS BUILD %s\n", data)
}

func printBenchmarkDiagnostics(service *ofo.OFOService, elapsed time.Duration) {
	data, _ := json.Marshal(struct {
		ElapsedSeconds float64 `json:"elapsed_seconds"`
		ofo.BenchmarkDiagnostics
	}{elapsed.Seconds(), service.GetBenchmarkDiagnostics()})
	fmt.Printf("\nTHEMIS DIAGNOSTICS %s\n", data)
}

func printFinalReport(duration time.Duration, finalizedCount int, totalSubmitted int32, failedSends int64, avgLatency time.Duration, latencySamples int64) {
	fmt.Println("\n\n--- FINAL RESULTS (Themis ordering layer) ---")
	if int64(finalizedCount) != latencySamples {
		fmt.Printf("Benchmark Result Invalid: finalized=%d latency_samples=%d\n", finalizedCount, latencySamples)
		fmt.Println("--- END FINAL RESULTS ---")
		return
	}
	seconds := duration.Seconds()
	throughput := 0.0
	offeredRate := 0.0
	if seconds > 0 {
		throughput = float64(finalizedCount) / seconds
		offeredRate = float64(totalSubmitted) / seconds
	}
	completionRatio := 0.0
	if totalSubmitted > 0 {
		completionRatio = float64(latencySamples) / float64(totalSubmitted)
	}
	latency := "N/A"
	if latencySamples > 0 {
		latency = avgLatency.Round(time.Millisecond).String()
	}
	fmt.Printf("Measurement Duration: %s\n", duration)
	fmt.Printf("Gamma Semantics: Themis all-replica premise\n")
	fmt.Printf("Total Submitted: %d\n", totalSubmitted)
	fmt.Printf("Total Finalized: %d\n", finalizedCount)
	fmt.Printf("Average TPS:     %.2f\n", throughput)
	fmt.Printf("Actual Offered Rate: %.2f\n", offeredRate)
	fmt.Printf("Locally Failed Transaction Send Attempts: %d\n", failedSends)
	fmt.Printf("Mean Completed-Transaction Latency: %s\n", latency)
	fmt.Printf("Latency Samples: %d\n", latencySamples)
	fmt.Printf("Outstanding: %d\n", int64(totalSubmitted)-latencySamples)
	fmt.Printf("Completion Ratio: %.6f\n", completionRatio)
	fmt.Println("--- END FINAL RESULTS ---")
}

func readJSONConfig(filename string) (map[uint64]string, uint64) {
	data, err := ioutil.ReadFile(filename)
	if err != nil {
		log.Fatalf("Failed to read config file %s: %v", filename, err)
	}
	var jsonConfig Config
	if err := json.Unmarshal(data, &jsonConfig); err != nil {
		log.Fatalf("Failed to parse config file: %v", err)
	}
	config := make(map[uint64]string)
	var maxID uint64 = 0
	for k, v := range jsonConfig.Nodes {
		id, _ := strconv.ParseUint(k, 10, 64)
		if id > maxID {
			maxID = id
		}
		config[id] = v
	}
	return config, maxID + 1
}

func parseNodeList(nodeList string) []uint64 {
	if nodeList == "" {
		return []uint64{}
	}
	parts := strings.Split(nodeList, ",")
	nodes := make([]uint64, 0, len(parts))
	for _, part := range parts {
		id, _ := strconv.ParseUint(strings.TrimSpace(part), 10, 64)
		nodes = append(nodes, id)
	}
	return nodes
}
