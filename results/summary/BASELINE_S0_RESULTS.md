# S0 Normal-Operation Baseline Results

Run date: 30 August 2026 (UTC)

## Scope

The formal baseline ran all four client-centric consistency experiments against
all four planned MongoDB configurations while all three replica-set members were
healthy. Each configuration/model pair used 500 operation sequences with each
of three fixed seeds (`20260830`, `20260831`, and `20260832`).

The suite executed 60,012 MongoDB operations and 18,012 consistency checks. No
operation failed or timed out.

## Aggregate observations

| Config | Read-your-writes | Monotonic reads | Monotonic writes | Writes-follow-reads |
|---|---:|---:|---:|---:|
| C1 causal, majority/majority, primary | 0 / 1,500 | 0 / 1,500 | 0 across 1,500 ordered writes | 0 / 1,500 |
| C2 causal, majority/majority, secondary | 0 / 1,500 | 0 / 1,500 | 0 across 1,500 ordered writes | 0 / 1,500 |
| C3 non-causal, w:1/local, directed secondary | 1,141 / 1,500 (76.07%) | 109 / 1,500 (7.27%) | 0 across 1,500 ordered writes | 0 / 1,500 |
| C4 non-causal, majority/majority, primary | 0 / 1,500 | 0 / 1,500 | 0 across 1,500 ordered writes | 0 / 1,500 |

The C3 violations were reproduced with every seed:

| Seed | RYW violations | MR violations |
|---:|---:|---:|
| 20260830 | 357 / 500 | 43 / 500 |
| 20260831 | 335 / 500 | 21 / 500 |
| 20260832 | 449 / 500 | 45 / 500 |

## Routing validation

Command monitoring confirmed that C2 reads were split approximately evenly
between `mongo2` and `mongo3`, while its writes went to `mongo1`, the Primary.
C3 deliberately alternated reads between the two Secondaries. C1 and C4 read
from the Primary.

This routing evidence matters: the C2 result exercises cross-replica causal
reads rather than accidentally reading only from the Primary, and the C3 result
does not depend on a single Secondary.

## Interpretation

- C1 agrees with the prediction. A causally consistent session with majority
  read and write concerns showed all four client-centric guarantees.
- C2 also agrees with the prediction. Secondary reads waited for the session's
  causal dependencies and showed no violation, at the cost of higher latency in
  some operations.
- C3 demonstrated both stale read-after-write results and non-monotonic reads.
  The RYW failures were direct observations of version `v-1` or older after the
  client's write of version `v` had already received `w:1` acknowledgement.
- C3 monotonic writes still held because MongoDB sends writes to the Primary and
  the logical client issued them sequentially.
- C3 writes-follow-reads did not fail during normal operation. The result does
  not establish a guarantee: without rollback or failover, the Primary normally
  already contains the version observed on a Secondary, so the conditional
  dependent write succeeds. Fault scenarios are required to test the predicted
  vulnerability more strongly.
- C4 passed under normal operation because reads and writes both used the
  Primary with majority concerns. This observation must not be generalized into
  a full causal-session guarantee under failover or cross-replica reads.

MongoDB documents that causally consistent sessions guarantee these operation
relationships only for majority reads and majority writes. MongoDB also notes
that replication to Secondaries is asynchronous and that reads from different
Secondaries can be stale or non-monotonic:

- <https://www.mongodb.com/docs/manual/core/read-isolation-consistency-recency/>
- <https://www.mongodb.com/docs/languages/python/pymongo-driver/current/crud/transactions/#causal-consistency>
- <https://www.mongodb.com/docs/manual/core/read-preference-use-cases/>

## Latency snapshot

The following values aggregate all successful operations within each model; they
are not limited to the final consistency check operation.

| Config/model | p50 (ms) | p95 (ms) |
|---|---:|---:|
| C1 RYW | 3.19 | 9.24 |
| C2 RYW | 3.43 | 9.11 |
| C3 RYW | 1.48 | 5.00 |
| C4 RYW | 3.22 | 9.13 |
| C1 WFR | 7.17 | 19.37 |
| C2 WFR | 8.37 | 42.27 |
| C3 WFR | 3.69 | 13.54 |
| C4 WFR | 7.08 | 20.92 |

The weak C3 configuration was faster in this single-VM deployment, but it
allowed observable RYW and MR violations. C2's cross-replica causal WFR workload
had the highest p95 in this run.

## Result files

- The machine-readable formal summary is stored beside this document.
- The 41 MB raw JSONL log is intentionally excluded from Git and retained on the
  experiment VM and the local project workspace.
- Every raw operation includes its run/config/model/seed identifiers, logical
  versions, latency, status, consistency decision, and serving replica when
  available.

Formal run ID:
`baseline-s0-formal-20260830T154711Z-3c931c32`

## Limitations

- All members were Docker containers on one VM, so host-level failures and
  inter-machine clock/network effects were absent.
- This baseline used healthy nodes and low network latency; it does not replace
  the required Primary failure, Secondary failure, and network partition tests.
- Absence of a violation is not proof of a guarantee. It is evidence limited to
  the tested workload, seeds, topology, and duration.
- The monotonic-writes checker validates the complete acknowledged history after
  each 500-write sequence; its denominator is therefore reported as ordered
  writes rather than as three final validation queries.
