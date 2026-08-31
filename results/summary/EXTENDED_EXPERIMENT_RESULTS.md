# Transition-Window and Replication-Lag Results

Run date: 31 August 2026 (UTC)

## Scope

These experiments address two limitations of the original S0-S3 runs:

1. The original Primary-failure workloads began only after election completed.
   T1 and T2 instead issue read-your-writes (RYW) request pairs continuously
   before, during, and after the election.
2. A one-node failure leaves only one readable Secondary, which makes
   cross-Secondary monotonic-read regressions difficult to expose. S4 keeps
   both Secondaries readable but pauses oplog application on one of them.

All selected runs use seeds `20260830`, `20260831`, and `20260832`. T1 and T2
run for 35 seconds per seed and execute C1-C4 concurrently. S4 runs 500
sequences per model and seed for C3, the deliberately weak configuration.

## Transition-window design

Each configuration owns one logical client and document. The client repeatedly:

1. writes an increasing version;
2. waits for the configured acknowledgement; and
3. immediately reads the same document.

An observed version below the last acknowledged version is an RYW violation.
Each operation is labelled `pre-fault`, `election`, or `post-election` using
monotonic time and shared marker files. `fault_started` is emitted immediately
before the Primary is stopped or disconnected, after role discovery has
finished. `fault_injected` records the replacement Primary and election time.

The first formal attempt labelled the target-discovery interval as part of the
election. It was excluded from the selected results. The `formal-rerun` results
below use the corrected marker and a longer window that contains all three
phases in every seed.

## Transition-window aggregate results

Each violation cell reports `violations / successful checks`. Errors are
database-operation errors or timeouts and are not counted as successful
consistency checks.

### T1: current Primary stopped

| Config | RYW violations / checks | Rate | Operation errors |
|---|---:|---:|---:|
| C1 causal, majority/majority, Primary | 0 / 2,045 | 0.00% | 9 |
| C2 causal, majority/majority, Secondary | 0 / 2,123 | 0.00% | 9 |
| C3 non-causal, w:1/local, directed Secondary | 2,420 / 3,422 | 70.72% | 7 |
| C4 non-causal, majority/majority, Primary | 0 / 2,045 | 0.00% | 9 |

Across all configurations T1 produced 9,635 checks, 2,420 violations, and 34
operation errors. Every error occurred during the election phase. Measured
election times were 12,945 ms, 16,048 ms, and 5,008 ms (mean 11,334 ms).

### T2: current Primary partitioned from the Docker network

| Config | RYW violations / checks | Rate | Operation errors |
|---|---:|---:|---:|
| C1 causal, majority/majority, Primary | 0 / 2,451 | 0.00% | 15 |
| C2 causal, majority/majority, Secondary | 0 / 2,471 | 0.00% | 15 |
| C3 non-causal, w:1/local, directed Secondary | 2,532 / 3,628 | 69.79% | 15 |
| C4 non-causal, majority/majority, Primary | 0 / 2,423 | 0.00% | 15 |

Across all configurations T2 produced 10,974 checks, 2,532 violations, and 60
operation errors. Again, all errors occurred during the election phase.
Election times were 12,055 ms, 16,844 ms, and 16,225 ms (mean 15,041 ms).
The silent partition generally took longer to detect than a stopped process.

### C3 by phase

| Scenario | Pre-fault | Election | Post-election |
|---|---:|---:|---:|
| T1 Primary stopped | 771 / 993 (77.64%) | 537 / 701 (76.60%) | 1,112 / 1,728 (64.35%) |
| T2 Primary partitioned | 849 / 1,075 (78.98%) | 413 / 550 (75.09%) | 1,270 / 2,003 (63.40%) |

C3 already violates RYW before the fault because `w:1` does not wait for
replication and an immediate `local` Secondary read can be stale. The election
does not create this weakness; it adds a temporary availability cost. C1, C2,
and C4 showed no RYW violation in any phase, although their requests could fail
briefly while no writable Primary was available.

## S4 controlled replication lag

S4 starts the replica set with the test-only MongoDB parameter
`enableTestCommands=1`, chooses a current Secondary, and enables the
`rsSyncApplyStop` failpoint. The Secondary remains healthy and readable, but it
does not apply new oplog entries. The ordinary C3 model matrix then alternates
reads between the paused and current Secondary. Cleanup disables the failpoint,
waits for replication to catch up, and force-recreates the normal containers
without test commands enabled.

| Model | Violations / checks | Rate | Operation errors |
|---|---:|---:|---:|
| Read-your-writes | 1,250 / 1,500 | 83.33% | 0 |
| Monotonic reads | 747 / 1,500 | 49.80% | 0 |
| Monotonic writes | 0 / 3 validations | 0.00% | 0 |
| Writes-follow-reads | 750 / 1,500 | 50.00% | 0 |
| **Total** | **2,747 / 4,503** | **61.00%** | **0** |

The paused `mongo2` was 38 seconds behind at the end of the workload. After
the failpoint was disabled it caught up to within one second for three
consecutive checks in 27,051 ms. Catch-up can be faster than the measured lag
because MongoDB can replay stored oplog entries faster than real time.

The near-50% MR rate follows directly from alternating reads between one frozen
and one current Secondary: after seeing a newer version, the next read from the
frozen node regresses. WFR also reaches 50% because every alternate causal read
comes from the frozen copy and can lack the parent version required by the
dependent write. MW remains intact because sequential writes are routed to the
single Primary. This demonstrates that the four client-centric guarantees are
distinct properties rather than one linear strength ordering.

## Interpretation against predictions

- C1 and C2 matched the causal-session prediction in all selected transition
  runs: successful operations preserved RYW across Primary changes.
- C4 also preserved RYW in this workload because both majority reads and writes
  use the Primary. This observation is narrower than a general causal-session
  guarantee.
- C3 repeatedly violated RYW in every phase and violated RYW, MR, and WFR under
  controlled lag. This matches the prediction for `w:1`, `local`, non-causal
  Secondary reads.
- Election changes availability and latency independently of consistency. The
  client may receive an error instead of a stale successful result while no
  Primary is writable.
- The S4 MW result supports the prediction that Primary serialization preserves
  one client's sequential writes in the tested driver configuration.

## Selected run IDs

- T1 seed `20260830`: `t1-primary-stop-transition-formal-rerun-20260831T082101Z-6cad906c`
- T1 seed `20260831`: `t1-primary-stop-transition-formal-rerun-20260831T082238Z-867b572c`
- T1 seed `20260832`: `t1-primary-stop-transition-formal-rerun-20260831T082410Z-ae94f015`
- T2 seed `20260830`: `t2-primary-partition-transition-formal-rerun-20260831T082543Z-0609280f`
- T2 seed `20260831`: `t2-primary-partition-transition-formal-rerun-20260831T082655Z-b9f2cd1b`
- T2 seed `20260832`: `t2-primary-partition-transition-formal-rerun-20260831T082810Z-ceb526e5`
- S4: `s4-secondary-replication-lag-formal-20260831T081523Z-85b1e3b3`

Machine-readable summaries are committed in this directory. Raw JSONL logs
remain on the experiment VM and in the local ignored `results/raw/` directory.

## Limitations

- The transition workload focuses on RYW so that all four configurations can
  issue the same short request pair concurrently. The other three models are
  exercised in S4 and in the existing S0-S3 matrix, not in the election window.
- T1/T2 phase markers are shared across four threads, so an operation that spans
  a boundary records both its start and end phase but is grouped by start phase.
- `rsSyncApplyStop` is a deliberately extreme, test-only lag mechanism. It is
  useful for exposing consistency behaviour but is not a production setting or
  a model of a particular network latency distribution.
- All nodes and the client share one VM, Docker host, disk, and physical network.
- Three deterministic seeds provide repeatability but do not exhaust all
  schedules, failure timings, driver retry policies, or topologies.
