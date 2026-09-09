# Themis ordering-layer baseline

Paper: *Themis: Fast, Strong Order-Fairness in Byzantine Consensus*,
[ePrint 2021/1465](https://eprint.iacr.org/2021/1465), revision dated
2022-11-29, linked from the author's CCS 2023 publication page. The implementation
uses FairPropose, FairUpdate and FairFinalize (Figures 1-3), without SNARKs.

The fixed-leader hosting adapter matches AUTIG's benchmark boundary: it waits
for verification acknowledgements from n-f distinct replicas, including the
leader, before simulating commit. These control messages are not a BFT quorum
certificate. Latency ends at leader-side final ordering after this gate; it
excludes real hosting consensus and follower commit-notification delivery.

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

Themis retains n=7, f=1, gamma=0.9: AUTIG's current n=5, f=1, gamma=0.9 does
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

Fault injection retains the existing reversed receipt orders at the last f
replicas; it is not general Byzantine behavior. Predictable benchmark Ed25519
keys simulate authentication cost, not real key isolation. Hosting BFT,
view-change, SNARK-Themis and the optional early-solid-prefix optimization are
outside this implementation's scope.

## Unresolved paper interpretation

Partial-list pair weighting remains unchanged pending clarification. With
n=5, f=1, gamma=1 and lists [A,B], [B,A], [A], [B], the current common-presence
count yields two solid vertices without an edge, inconsistent with Lemma B.1.
The lemma counts lists containing at least one of the pair, but the prose Weight
notation does not explicitly define absent entries. No speculative absent-entry
votes have been added, and capped-list omission must not be equated with
non-receipt. This limitation prevents claiming complete paper fidelity for
partial-receipt workloads; the benchmark fixes do not resolve it.

Regression tests:

```text
go test ./...
python -m unittest discover -s benchmark -p 'test_*.py'
```
