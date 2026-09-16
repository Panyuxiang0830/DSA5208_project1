#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"

label="${1:-noncausal-remote-v2}"
iterations="${2:-500}"
seeds="${3:-20260830,20260831,20260832}"
configs="C5,C6,C8"

has_summary() {
  compgen -G "results/summary/$1" >/dev/null
}

run_once() {
  local pattern="$1"
  shift
  if has_summary "${pattern}"; then
    printf 'SKIP existing result: %s\n' "${pattern}"
    return 0
  fi
  "$@"
}

# C3 is deliberately not rerun: its existing GCP results provide the w:1/local
# corner of the same directed-Secondary matrix. Only the three missing corners
# are generated here.
run_once "s0-normal-${label}-????????T??????Z-*.summary.json" \
  docker compose run --rm --no-deps runner \
  python -m experiments.run_baseline \
  --scenario S0-normal --configs "${configs}" \
  --iterations "${iterations}" --seeds "${seeds}" --label "${label}"

for scenario in S1-secondary-failure S2-primary-failure S3-primary-partition; do
  scenario_slug="$(printf '%s' "${scenario}" | tr '[:upper:]' '[:lower:]')"
  run_once "${scenario_slug}-${label}-????????T??????Z-*.summary.json" \
    ./scripts/run_fault_scenario.sh \
    "${scenario}" "${iterations}" "${seeds}" "${label}" "${configs}"
done

for scenario in T1-primary-stop-transition T2-primary-partition-transition; do
  scenario_slug="$(printf '%s' "${scenario}" | tr '[:upper:]' '[:lower:]')"
  for seed in 20260830 20260831 20260832; do
    transition_label="${label}-seed-${seed}"
    run_once "${scenario_slug}-${transition_label}-????????T??????Z-*.summary.json" \
      ./scripts/run_transition_scenario.sh \
      "${scenario}" "${seed}" "${transition_label}" 35 3 "${configs}"
  done
done

run_once "s4-secondary-replication-lag-${label}-????????T??????Z-*.summary.json" \
  ./scripts/run_replication_lag_scenario.sh \
  "${iterations}" "${seeds}" "${label}" "${configs}"

./scripts/restore_cluster.sh
./scripts/cluster_status.sh
