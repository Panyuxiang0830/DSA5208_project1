# DSA5208 Project 1

This repository contains a reproducible three-node MongoDB Replica Set used to
study client-centric consistency under normal operation, node failure, and
network partitions.

The project plan is in [PROJECT_PLAN.md](PROJECT_PLAN.md).
The current cloud environment is recorded in [DEPLOYMENT.md](DEPLOYMENT.md).
The first normal-operation results are in
[results/summary/BASELINE_S0_RESULTS.md](results/summary/BASELINE_S0_RESULTS.md).
The formal node-failure and network-partition results are in
[results/summary/FAULT_SCENARIO_RESULTS.md](results/summary/FAULT_SCENARIO_RESULTS.md).
The election-window and controlled replication-lag results are in
[results/summary/EXTENDED_EXPERIMENT_RESULTS.md](results/summary/EXTENDED_EXPERIMENT_RESULTS.md).
Report-ready PNG and SVG charts are in
[results/figures/](results/figures/).

## Architecture

```text
Google Cloud Ubuntu VM
|
+-- mongo1: MongoDB replica-set member
+-- mongo2: MongoDB replica-set member
+-- mongo3: MongoDB replica-set member
+-- runner: disposable Python/PyMongo experiment container
```

MongoDB elects one member as Primary and the other two members become
Secondaries. All members are data-bearing voting nodes; no arbiter is used.

## Security boundary

This is a course experiment configuration, not a production deployment.

- MongoDB ports bind only to `127.0.0.1` on the VM.
- Do not add a Google Cloud firewall rule exposing ports 27017-27019.
- Team access should use SSH to the VM.
- The Replica Set currently has no database authentication because it is
  isolated behind the VM and Docker private network. Authentication can be
  added after the baseline experiments if required.

## Recommended initial VM

- Ubuntu 24.04 LTS
- 2 vCPU and 8 GB RAM (for functional experiments)
- 30 GB persistent disk
- Only TCP port 22 exposed to trusted sources

Each MongoDB container is initially limited to 1536 MB RAM with a 0.5 GB
WiredTiger cache. These values can be changed in `.env` and must be recorded in
the report if changed.

## Start the Replica Set

Requirements:

- Docker Engine
- Docker Compose v2 (`docker compose`)

On a fresh Ubuntu 24.04 VM, install the requirements with:

```bash
./scripts/bootstrap-ubuntu.sh
```

Reconnect once after the script finishes so the Docker group membership takes
effect.

Run:

```bash
cp .env.example .env
docker compose pull
docker compose up -d --wait mongo1 mongo2 mongo3
docker compose run --rm mongo-init
./scripts/cluster_status.sh
```

The expected healthy state is one `PRIMARY` and two `SECONDARY` members.

## Run the deployment smoke test

Build the Python runner and execute a majority write followed by a causally
consistent majority read:

```bash
docker compose build runner
docker compose run --rm --no-deps runner
```

The command returns JSON containing `"ok": true`, the elected Primary, and all
three replica-set hosts.

## Run the normal-operation consistency baseline

Run a 20-sequence pilot for all four configurations and all four client-centric
consistency models:

```bash
docker compose run --rm --no-deps runner \
  python -m experiments.run_baseline \
  --iterations 20 \
  --seeds 20260830 \
  --label pilot
```

Run the planned 500-sequence baseline with three deterministic seeds:

```bash
docker compose run --rm --no-deps runner \
  python -m experiments.run_baseline \
  --iterations 500 \
  --seeds 20260830,20260831,20260832 \
  --label formal
```

Raw JSONL logs are written to `results/raw/` and are ignored by Git by default.
Machine-readable summaries are written to `results/summary/`. Each operation
records the effective configuration, logical version, latency, outcome,
consistency check, and the MongoDB member that served the command when known.

## Run the fault scenarios

The fault wrapper first restores a healthy Replica Set, injects one fault,
runs the same configuration/model matrix, and restores all three members before
exiting. Its exit trap also attempts recovery if the experiment is interrupted.

Run short pilots:

```bash
./scripts/run_fault_scenario.sh S1-secondary-failure 20 20260830 pilot
./scripts/run_fault_scenario.sh S2-primary-failure 20 20260830 pilot
./scripts/run_fault_scenario.sh S3-primary-partition 20 20260830 pilot
```

Run a formal scenario with 500 sequences and three deterministic seeds:

```bash
./scripts/run_fault_scenario.sh S1-secondary-failure \
  500 20260830,20260831,20260832 formal
```

Replace the scenario name with `S2-primary-failure` or
`S3-primary-partition` for the other formal runs. S1 stops one Secondary. S2
stops the current Primary and waits for a new election. S3 disconnects the
current Primary from the Docker network and waits for the majority partition to
elect a new Primary. Fault and recovery events are saved alongside the raw
JSONL results in `results/raw/`.

To recover the cluster manually after an interrupted run:

```bash
./scripts/restore_cluster.sh
./scripts/cluster_status.sh
```

## Run the transition-window experiments

These wrappers continuously run an RYW write/read pair for C1-C4 while the
current Primary is stopped or partitioned. Each selected formal run lasts 35
seconds so it includes pre-fault, election, and post-election operations.

```bash
./scripts/run_transition_scenario.sh \
  T1-primary-stop-transition 20260830 formal 35 3

./scripts/run_transition_scenario.sh \
  T2-primary-partition-transition 20260830 formal 35 3
```

Repeat with seeds `20260831` and `20260832`. The last argument is the number of
seconds to run before requesting the fault. Fault discovery, actual fault
start, completed election, and cluster restoration are written to a companion
fault-event JSONL file.

## Run the S4 replication-lag experiment

S4 pauses oplog application on one readable Secondary, runs all four models
under C3, measures the resulting lag, waits for catch-up, and returns the
containers to the normal command line:

```bash
./scripts/run_replication_lag_scenario.sh \
  500 20260830,20260831,20260832 formal
```

This scenario uses `compose.s4.yaml` to enable MongoDB test commands and the
`rsSyncApplyStop` failpoint. It is strictly an experiment configuration and
must not be used in production. The cleanup trap disables the failpoint even
when the workload exits with an error.

## Stop and restart

Stop containers while preserving database volumes:

```bash
docker compose stop
```

Restart them:

```bash
docker compose start
```

Remove containers and the private network while retaining named volumes:

```bash
docker compose down
```

Deleting volumes destroys the experimental database. Only use the following
command when intentionally resetting all data:

```bash
docker compose down --volumes
```

## Versions

- MongoDB image: `mongo:8.0.29`
- Python runner image: `python:3.12-slim`
- PyMongo: `4.17.0`

After the first deployment, record `docker version`, `docker compose version`,
the MongoDB image digest, the Ubuntu version, and the Google Cloud VM type.

## Final reports

- [English PDF](output/pdf/DSA5208_Project1_Report_EN.pdf)
- [中文 PDF](output/pdf/DSA5208_Project1_Report_ZH.pdf)

Regenerate both editions from the recorded summaries and figures with:

```bash
python3 -m pip install -r report/requirements.txt
python3 report/generate_reports.py
```
