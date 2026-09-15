#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"
# shellcheck disable=SC1091
source "${PROJECT_ROOT}/scripts/lib/cluster_control.sh"

iterations="${1:-500}"
seeds="${2:-20260830,20260831,20260832}"
label="${3:-formal}"
configs="${4:-C2,C3,C5,C6,C7,C8}"
scenario="S4-secondary-replication-lag"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
event_log="results/raw/s4-secondary-replication-lag-${label}-${timestamp}-fault-events.jsonl"
mkdir -p results/raw results/summary

export COMPOSE_FILE="${PROJECT_ROOT}/compose.yaml:${PROJECT_ROOT}/compose.s4.yaml"
./scripts/restore_cluster.sh >>"${event_log}"
./scripts/pause_secondary_replication.sh | tee -a "${event_log}"

# shellcheck disable=SC1090
source .fault-state/active.env
lagged_target="${TARGET_SERVICE}"

cleanup() {
  local cleanup_status=0
  if ! ./scripts/restore_cluster.sh | tee -a "${event_log}"; then
    cleanup_status=1
  fi

  # Return to the normal MongoDB command line without test commands enabled.
  unset COMPOSE_FILE
  if ! docker compose up -d --wait --force-recreate mongo1 mongo2 mongo3 >/dev/null; then
    cleanup_status=1
  elif ! wait_for_healthy_cluster 90; then
    cleanup_status=1
  fi
  return "${cleanup_status}"
}
trap cleanup EXIT INT TERM

status=0
docker compose run --rm --no-deps \
  -e "EXPERIMENT_SCENARIO=${scenario}" \
  -e "EXPERIMENT_TARGET_SECONDARY=${lagged_target}" \
  runner python -m experiments.run_baseline \
  --scenario "${scenario}" \
  --configs "${configs}" \
  --iterations "${iterations}" \
  --seeds "${seeds}" \
  --label "${label}" || status=$?

lag_seconds="$(replication_lag_seconds "${lagged_target}")"
printf '{"event":"lag_observed","kind":"secondary-replication-pause","target":"%s","lag_seconds":%s,"timestamp":"%s"}\n' \
  "${lagged_target}" "${lag_seconds}" "$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)" | tee -a "${event_log}"

trap - EXIT INT TERM
if ! cleanup; then
  status=1
fi
exit "${status}"
