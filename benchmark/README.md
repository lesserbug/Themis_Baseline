# Themis ordering-layer baseline

For single-machine construction/verification computation (without deployment),
see [local microbenchmarks](MICROBENCHMARKS.md). These preserve native Themis
boundaries and are separate from the hosting/throughput experiments below.

Paper: *Themis: Fast, Strong Order-Fairness in Byzantine Consensus*,
[ePrint 2021/1465](https://eprint.iacr.org/2021/1465), revision dated
2022-11-29, linked from the author's CCS 2023 publication page. The implementation
uses FairPropose, FairUpdate and FairFinalize (Figures 1-3), without SNARKs.

The fixed-leader hosting adapter matches AUTIG's benchmark boundary: it waits
for verification acknowledgements from n-f distinct replicas, including the
leader, before simulating commit. These control messages are not a BFT quorum
certificate. Latency ends at leader-side final ordering after this gate; it
excludes real hosting consensus and follower commit-notification delivery.

At cutoff the leader cancels its pipeline independently of the local-order
ticker, so a blocked evidence enqueue can exit. Uncommitted proposal graph
construction, updates and comparison check cancellation cooperatively; partial
results are discarded without changing the committed prefix or counting a
verification failure. In-progress commits and follower verification still finish
before the final-state barrier. This does not impose a hard bound on all cleanup
work or change the measurement window, quorum, graph rules or queue capacities.

An exhausted leader evidence queue now logs `BENCHMARK INVALID` and cancels the
ordering pipeline instead of blocking the single network worker that also
delivers verification acknowledgements. This is a measurement validity guard,
not a new congestion-control protocol: such a run must not supply a throughput
point. It does not make overload sustainable; cleanup still uses the existing
deadline and finish barrier. No evidence replacement/coalescing policy is used
in valid runs. Keep invalid attempts in the experiment record.

The generator uses AUTIG's cumulative floor(rate * elapsed_seconds) pacing,
real submission timestamps, and synchronous fanout to every replica. It catches
up only before the leader's deadline and finishes the fanout of an already
counted submission. TCP writes have the same five-second deadline as AUTIG.
Submission and finalization counters use the fixed leader measurement window.
Followers serve the final prefix until a finish barrier; shutdown time is
excluded. Every replica must report the same committed height, state digest and
last proposal digest. Verification, send and final-state failures invalidate a
run.

- `configured_offered_rate`: requested transaction rate, not multiplied by n.
- `actual_offered_rate`: submission attempts initiated / measurement seconds;
  this is not confirmation that every replica received each transaction.
- `average_tps`: transactions finalized within that same window / seconds.
- `offered_rate_tolerance`: diagnostic only. Out-of-tolerance runs retain a
  warning and `offered_rate_within_tolerance=false`; use actual offered rate
  as the load axis. A finalization plateau does not fail this check.

Report `outstanding`, `completion_ratio` and `latency_samples` with completed-only
mean latency. Unfinished transactions are censored at cutoff. The generator
shares the leader process, synchronous fanout can limit load, and transport
queues can delay receipt. No asynchronous client enqueue count is used as proof
of offered load. Transactions are retained without the former silent 50,000
entry pool limit; memory can therefore grow under sustained overload, as with
AUTIG's retained workload.

## Parameters and comparison

Run `fab local`, `fab remote`, and `fab logs` using `benchmark/settings.json`.
No AWS resources are created by the local task. The instance type and region
now match AUTIG's current defaults (`m5.xlarge`, `us-east-1`); deployment uses
Go 1.22.12 on both sides. Keep client placement, replica count, faults, payload,
duration and repetitions aligned when comparing results.

The local example uses n=7, f=1, gamma=0.9: n=5, f=1, gamma=0.9 does
not satisfy Themis's strict n*(2*gamma-1)>4*f constraint. For a comparison using
these Themis parameters, also configure AUTIG with seven replicas. This change
does not edit AUTIG. Themis gamma is an all-replica premise, whereas AUTIG's
gamma uses honest-replica semantics; equal numeric gamma does not mean identical
fairness thresholds.

`lo_interval` remains the evidence reporting interval. `lo_size` is accepted
for command compatibility but does not truncate Themis's complete List_i of
unproposed receipts. Independent per-replica truncation can prevent any
transaction from becoming solid. AUTIG's size-limited incremental LocalOrder
has different semantics. Thus the two systems do not have an identical effective
batch size; report this difference. No replacement batching algorithm or graph
performance optimization was added.

This is not a claim that the original Themis evaluation had no size parameter.
The authors evaluated proposal **blocksize beta** (50 and 400); see the author's
[Themis chapter, Section 6.5.1, printed p.153](https://mahimnakelkar.github.io/dissertation.pdf#page=171).
That proposal transaction count is not implemented as a configurable bound here,
and must not be equated with a per-replica `lo_size` truncation. Actual complete
list size and proposal graph size still affect this implementation's cost.
`batchReadyChanSize=256` counts queued evidence batches, not transactions;
each collected batch contains n-f replica reports. Fairness batches arising
from Condorcet cycles are a further, separate meaning of the word "batch".

## Byzantine-count experiments

`-f F` is the protocol fault bound. `-byzantine-count b` independently selects
the last b replica IDs (`n-b` through `n-1`) to reverse their complete fresh
and Update receipt orders. They still sign, send, verify and acknowledge normally.
Omitting the CLI flag (default -1), or omitting/using null for `byzantine_count`
in settings, preserves the old b=F behavior. Explicit zero selects no attackers.
Require 0 <= b <= F; this flag does not change graph thresholds or hosting quorum.
The fixed leader ID 0 stays honest in these experiments.

`benchmark.local.byzantine_count` accepts one integer or null.
`benchmark.remote.byzantine_count` accepts a list (or a scalar for one value).
The remote matrix is expanded over nodes, rate and byzantine_count, with every
combination validated before contacting AWS. The current remote settings use:

```json
"nodes": [20],
"faults": 4,
"gamma": 1.0,
"byzantine_count": [0, 1, 2, 3, 4]
```

At these settings, n-F=16 evidence senders, n-2F=12 solid presence, edge threshold
ceil(n*(1-gamma)+F+1)=5 and n-F=16 hosting acknowledgements all remain fixed.
The collector accepts any first n-F valid distinct senders; a particular round
need not include all b attackers. It does not wait for a fixed sender roster.
Raw startup logs report `BENCHMARK FAULTS`; JSON records resolved
`byzantine_count`, `attack_model=reverse`, and `fault_metadata`. Run IDs include b.

This measures receipt-order reversal with an honest leader, not arbitrary
Byzantine behavior, withholding, delay injection or complete BFT recovery.
For comparison with UTIG's reversal-only experiment, use its
`byzantine_lo_delay_ms=0`. A flat throughput curve is possible, especially below
saturation; report latency, completion ratio and actual offered rate too.
Keep n, F, gamma, workload and interval fixed while varying b. Different gamma
semantics across the protocols still need to be stated.

## Minimal diagnostics and run identity

`fab remote` prints setup/run progress, one compact result line (n, F, b,
interval, repeat, target/actual input, TPS, completed-transaction latency,
completion ratio and outstanding count), and the saved JSON path. It does not
dump per-node states or diagnostics to the terminal. All JSON fields and raw
node logs remain saved. Remote Git/build output is saved under
`logs/build-<unique-id>/node<id>.log`; a failed build raises an error with that
path. Benchmark failures and offered-rate warnings remain visible. `fab logs`
is still the explicit command for printing detailed saved log data.

Raw logs and result JSON now share a unique run ID including reporting interval;
repeat sweeps do not overwrite raw logs. JSON retains `log_paths`, executable
`build_metadata` (Go version, embedded VCS revision and dirty flag when available),
and `diagnostics_samples`. Check that remote binaries used the intended revision;
`fab remote` builds the configured remote Git branch, not unsaved local edits.
Unknown revision or a dirty build is not evidence of an exact reproducible source
revision. Archive source changes as well if using such a build.

The leader emits one diagnostic snapshot per second and one at report time:

- `list_ids_total/list_count` and `list_ids_max`: mean/max generated fresh list
  size at the leader, including empty lists; not all replicas and not a size cap.
- `evidence_queue`, `batch_queue`, `deferred_proposals`, `receipt_pool`:
  instantaneous samples; receipt pool also includes deferred transactions.
- `build_ns_total/build_count`, `build_ns_max`: build time including attempts
  that return no proposal. `build_nil` includes no-progress, invalidated evidence
  and cancellation; it must not be interpreted as only stale evidence or bugs.
- `collector_rejected`: all validation rejections, not just stale sequences.
- `hosting_ns_total/hosting_count`: full synchronous hosting-call time, including
  leader verification, transport, waiting for quorum and commit work.
- `proposals_accepted`: successful hosting calls; differences between samples
  give proposal cadence. In-flight calls are not timed until they return.

Snapshots are observational, non-atomic and may extend into cleanup. Their final
sample is not a new measurement cutoff. Existing throughput/latency counters
retain the fixed cutoff. These lightweight counters add measurement overhead;
the graph algorithms, signature checks, complete lists and quorum remain unchanged.

For a deadline-focused experiment plan and remaining fidelity limits, see
[DEADLINE_PLAN.md](DEADLINE_PLAN.md).

Fault injection retains the existing reversed receipt orders at the last f
replicas; it is not general Byzantine behavior. Predictable benchmark Ed25519
keys simulate authentication cost, not real key isolation. Hosting BFT,
view-change, SNARK-Themis and the optional early-solid-prefix optimization are
outside this implementation's scope.

## Paper weighting correction (2026-09-13)

The author's [dissertation, Ch. 6, printed p.138](https://mahimnakelkar.github.io/dissertation.pdf#page=156)
explicitly includes an ordering vote A before B when only A is present.
FairPropose and FairUpdate now count this vote; neither-transaction-present
contributes nothing. Earlier versions counted only common-presence pairs.
That was a correctness defect, not an inherent performance limitation of Themis.
Regression counterexamples and an exhaustive two-transaction receipt check are
in `pkg/ofo/paper_conformance_test.go`. Deferred test fixtures also now use
receipt patterns that remain incomplete under the corrected definition.
Old partial-receipt performance and microbenchmark results require reevaluation;
do not merge measurements across this correction. Capped-list omission must
still not be equated with non-receipt. This correction does not establish full
HotStuff/protocol fidelity. See [the audit](THEMIS_PAPER_AUDIT_2026-09-13.md).

Regression tests:

```text
go test ./...
python -m unittest discover -s benchmark -p 'test_*.py'
```
