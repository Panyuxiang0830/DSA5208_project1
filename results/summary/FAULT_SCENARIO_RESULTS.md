# S1-S3 Fault-Scenario Results

Run date: 30 August 2026 (UTC)

## Scope

The formal fault experiments ran the same four configurations and four
client-centric consistency tests used by the S0 baseline. Each
configuration/model pair used 500 operation sequences with each of three fixed
seeds (`20260830`, `20260831`, and `20260832`). Every scenario therefore
performed 18,012 consistency checks.

The fault was injected before the consistency matrix began. For Primary
failure and partition scenarios, the runner waited until a replacement Primary
had been elected. Consequently, these runs test operation under the stable
degraded topology; election duration is measured separately, but operations
during the election window are not sampled.

## Faults and recovery

| Scenario | Injected condition | Resulting topology | Measured election | Recovery |
|---|---|---|---:|---|
| S1 Secondary failure | stopped `mongo2` | `mongo1` Primary + `mongo3` Secondary | none (0 ms) | 1 Primary + 2 Secondaries |
| S2 Primary failure | stopped `mongo1` | `mongo2` Primary + `mongo3` Secondary | 1,825 ms | 1 Primary + 2 Secondaries |
| S3 Primary partition | disconnected `mongo1` from the Docker network | majority side: `mongo2` Primary + `mongo3` Secondary | 11,482 ms | 1 Primary + 2 Secondaries |

The longer S3 election is expected: stopping the Primary gives the remaining
members an immediate connection failure, whereas a silent network partition is
detected through heartbeats and the election timeout. MongoDB's default
`electionTimeoutMillis` is 10,000 ms.

## Aggregate consistency results

Each cell reports `violations / checks`. MW is validated once per seed after a
500-write ordered sequence, so its table denominator is three validations; all
1,500 ordered writes were also acknowledged without error.

### S1: one Secondary stopped

| Config | RYW | MR | MW | WFR |
|---|---:|---:|---:|---:|
| C1 causal, majority/majority, Primary | 0 / 1,500 | 0 / 1,500 | 0 / 3 | 0 / 1,500 |
| C2 causal, majority/majority, Secondary | 0 / 1,500 | 0 / 1,500 | 0 / 3 | 0 / 1,500 |
| C3 non-causal, w:1/local, directed Secondary | 1,035 / 1,500 (69.00%) | 0 / 1,500 | 0 / 3 | 0 / 1,500 |
| C4 non-causal, majority/majority, Primary | 0 / 1,500 | 0 / 1,500 | 0 / 3 | 0 / 1,500 |

### S2: current Primary stopped

| Config | RYW | MR | MW | WFR |
|---|---:|---:|---:|---:|
| C1 causal, majority/majority, Primary | 0 / 1,500 | 0 / 1,500 | 0 / 3 | 0 / 1,500 |
| C2 causal, majority/majority, Secondary | 0 / 1,500 | 0 / 1,500 | 0 / 3 | 0 / 1,500 |
| C3 non-causal, w:1/local, directed Secondary | 969 / 1,500 (64.60%) | 0 / 1,500 | 0 / 3 | 0 / 1,500 |
| C4 non-causal, majority/majority, Primary | 0 / 1,500 | 0 / 1,500 | 0 / 3 | 0 / 1,500 |

### S3: old Primary isolated from the majority

| Config | RYW | MR | MW | WFR |
|---|---:|---:|---:|---:|
| C1 causal, majority/majority, Primary | 0 / 1,500 | 0 / 1,500 | 0 / 3 | 0 / 1,500 |
| C2 causal, majority/majority, Secondary | 0 / 1,500 | 0 / 1,500 | 0 / 3 | 0 / 1,500 |
| C3 non-causal, w:1/local, directed Secondary | 1,049 / 1,500 (69.93%) | 0 / 1,500 | 0 / 3 | 0 / 1,500 |
| C4 non-causal, majority/majority, Primary | 0 / 1,500 | 0 / 1,500 | 0 / 3 | 0 / 1,500 |

All three selected formal runs recorded zero database-operation errors or
timeouts. C3 RYW violations occurred with every seed:

| Scenario | Seed 20260830 | Seed 20260831 | Seed 20260832 |
|---|---:|---:|---:|
| S1 | 334 / 500 | 360 / 500 | 341 / 500 |
| S2 | 251 / 500 | 348 / 500 | 370 / 500 |
| S3 | 416 / 500 | 277 / 500 | 356 / 500 |

## Interpretation against predictions

- C1 matched the prediction in every stable fault topology. Majority reads and
  writes in a causally consistent session, routed to the current Primary,
  showed all four client-centric guarantees.
- C2 also matched the prediction. Command-monitoring data confirmed that writes
  went to the new/current Primary and reads went to the surviving Secondary;
  cross-replica causal reads produced no observed violation.
- C3 repeatedly violated read-your-writes. A `w:1` acknowledgement only
  confirms the Primary's acceptance, while an immediate `local` read from the
  surviving Secondary can return a version that has not caught up.
- C3 monotonic reads had 109 violations in S0 but none in S1-S3. This is not
  evidence that the weak configuration gained an MR guarantee. Under each
  one-node fault only one reachable Secondary remained, so the directed reader
  could no longer alternate between two independently lagging replicas—the
  mechanism that exposed regressions in S0.
- Monotonic writes showed no violation in any configuration. The client issued
  writes sequentially and MongoDB routed them to one Primary, so this result was
  expected.
- WFR showed no violation, including C3. The tested failover completed before
  the workload started, and the new Primary already contained the versions
  observed by the surviving Secondary. The absence of observed violations does
  not establish a general WFR guarantee for C3.
- C4 behaved like the strong configurations in these tests because both reads
  and writes used the current Primary with majority concerns. These observations
  do not make a non-causal C4 session equivalent to a causal session in every
  possible topology and workload.

## Latency snapshot

The table reports p50/p95 latency across all successful RYW operations (both
the write and the following read). Values are milliseconds.

| Config | S0 normal | S1 Secondary down | S2 Primary down | S3 partition |
|---|---:|---:|---:|---:|
| C1 | 3.19 / 9.24 | 2.09 / 5.84 | 2.23 / 7.09 | 2.05 / 6.07 |
| C2 | 3.43 / 9.11 | 2.21 / 6.62 | 2.84 / 9.73 | 2.15 / 7.04 |
| C3 | 1.48 / 5.00 | 1.01 / 3.35 | 1.07 / 3.14 | 0.88 / 2.85 |
| C4 | 3.22 / 9.13 | 2.25 / 6.79 | 2.24 / 6.65 | 2.17 / 6.45 |

The weak C3 configuration remained fastest in this single-VM environment, but
its lower latency coincided with a 64.60%-69.93% RYW violation rate. The lower
fault-scenario latency relative to S0 should not be interpreted as a general
benefit of failure: the degraded topology had fewer competing replica processes
and all timed operations began after election completion.

## Reproducibility and selected runs

- S1 run ID:
  `s1-secondary-failure-formal-20260830T181846Z-8e657452`
- S2 run ID:
  `s2-primary-failure-formal-20260830T182320Z-f604f5eb`
- S3 selected run ID:
  `s3-primary-partition-formal-rerun-20260830T183455Z-59f3d378`

The S3 label says `formal-rerun` because the first formal S3 run exposed a
test-harness shutdown race: a background writer attempted one operation after
its shared `MongoClient` was closed. All consistency checks had completed, but
that run was excluded. The writer now receives an explicit stop signal and is
joined before the client closes; the selected rerun completed with zero errors.

Machine-readable summaries are committed in this directory. Raw JSONL operation
logs and fault-event logs are retained locally and on the experiment VM but are
excluded from Git because of their size.

## Limitations and next experiments

- All MongoDB members shared one VM, disk subsystem, Docker host, and physical
  network. The containers do not provide independent machine-level failure
  domains.
- The runner waited for a replacement Primary before starting the workload.
  A separate transition-window experiment is needed to measure request errors,
  timeouts, and latency while an election is actively occurring.
- The S3 Docker-network disconnection isolated the old Primary from both peers
  and the client. It does not test clients attached independently to both sides
  of a partition.
- With only one surviving Secondary, the fault scenarios cannot reproduce the
  cross-Secondary switching used by the S0 MR test. A targeted S4 replication
  delay or client-to-node partition is needed to stress MR under failure.
- No observed violation is not proof of a guarantee; results are limited to the
  tested topology, driver settings, workload, and seeds.
- Background-write counts are workload-support operations rather than
  consistency checks. The S3 harness fix stops that writer immediately after
  the last MR check, so total operation counts are not directly comparable with
  earlier runs; the fixed 18,012 check count is the appropriate denominator.

Relevant documentation:

- <https://www.mongodb.com/docs/manual/reference/replica-configuration/>
- <https://www.mongodb.com/docs/manual/core/read-preference-use-cases/>
- <https://docs.docker.com/reference/cli/docker/network/disconnect/>
- <https://docs.docker.com/reference/cli/docker/network/connect/>
