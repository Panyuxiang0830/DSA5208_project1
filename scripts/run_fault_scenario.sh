#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"

scenario="${1:-}"
iterations="${2:-500}"
seeds="${3:-20260830,20260831,20260832}"
label="${4:-formal}"

case "${scenario}" in
  S1-secondary-failure)
    injector=(./scripts/stop_secondary.sh)
    ;;
  S2-primary-failure)
    injector=(./scripts/stop_primary.sh)
    ;;
  S3-primary-partition)
    injector=(./scripts/partition_primary.sh)
    ;;
  *)
    echo "Usage: $0 {S1-secondary-failure|S2-primary-failure|S3-primary-partition} [iterations] [seeds] [label]" >&2
    exit 2
    ;;
esac

scenario_slug="$(printf '%s' "${scenario}" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9' '-')"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
event_log="results/raw/${scenario_slug}-${label}-${timestamp}-fault-events.jsonl"
mkdir -p results/raw results/summary

./scripts/restore_cluster.sh >>"${event_log}"
"${injector[@]}" | tee -a "${event_log}"

cleanup() {
  if ./scripts/restore_cluster.sh | tee -a "${event_log}"; then
    return 0
  fi
  sleep 2
  ./scripts/restore_cluster.sh | tee -a "${event_log}"
}
trap cleanup EXIT INT TERM

status=0
docker compose run --rm --no-deps \
  -e "EXPERIMENT_SCENARIO=${scenario}" \
  runner python -m experiments.run_baseline \
  --scenario "${scenario}" \
  --iterations "${iterations}" \
  --seeds "${seeds}" \
  --label "${label}" || status=$?

trap - EXIT INT TERM
if ! cleanup; then
  status=1
fi
exit "${status}"
