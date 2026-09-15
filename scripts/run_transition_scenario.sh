#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_ROOT}"

scenario="${1:-}"
seed="${2:-20260830}"
label="${3:-pilot}"
duration_seconds="${4:-25}"
pre_fault_seconds="${5:-3}"
configs="${6:-C1,C2,C3,C4}"

case "${scenario}" in
  T1-primary-stop-transition)
    injector=(./scripts/stop_primary.sh)
    ;;
  T2-primary-partition-transition)
    injector=(./scripts/partition_primary.sh)
    ;;
  *)
    echo "Usage: $0 {T1-primary-stop-transition|T2-primary-partition-transition} [seed] [label] [duration_seconds] [pre_fault_seconds] [configs]" >&2
    exit 2
    ;;
esac

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
scenario_slug="$(printf '%s' "${scenario}" | tr '[:upper:]' '[:lower:]')"
prefix="results/raw/${scenario_slug}-${label}-${seed}-${timestamp}"
ready_file="${prefix}.ready"
fault_marker="${prefix}.fault"
elected_marker="${prefix}.elected"
event_log="${prefix}-fault-events.jsonl"
runner_log="${prefix}-runner.log"
runner_pid=""
mkdir -p results/raw results/summary
rm -f "${ready_file}" "${fault_marker}" "${elected_marker}"

./scripts/restore_cluster.sh >>"${event_log}"

cleanup() {
  local cleanup_status=0
  if [[ -n "${runner_pid}" ]] && kill -0 "${runner_pid}" 2>/dev/null; then
    kill "${runner_pid}" 2>/dev/null || true
    wait "${runner_pid}" 2>/dev/null || true
  fi
  if ! ./scripts/restore_cluster.sh | tee -a "${event_log}"; then
    cleanup_status=1
  fi
  rm -f "${ready_file}" "${fault_marker}" "${elected_marker}"
  return "${cleanup_status}"
}
trap cleanup EXIT INT TERM

docker compose run --rm --no-deps \
  -e "EXPERIMENT_SCENARIO=${scenario}" \
  runner python -m experiments.transition_window \
  --scenario "${scenario}" \
  --configs "${configs}" \
  --seed "${seed}" \
  --label "${label}" \
  --duration-seconds "${duration_seconds}" \
  --ready-file "${ready_file}" \
  --fault-marker "${fault_marker}" \
  --elected-marker "${elected_marker}" \
  >"${runner_log}" 2>&1 &
runner_pid=$!

deadline=$((SECONDS + 45))
while [[ ! -f "${ready_file}" ]]; do
  if ! kill -0 "${runner_pid}" 2>/dev/null; then
    wait "${runner_pid}" || true
    cat "${runner_log}" >&2
    echo "Transition runner exited before becoming ready." >&2
    exit 1
  fi
  if ((SECONDS >= deadline)); then
    echo "Transition runner did not become ready within 45s." >&2
    exit 1
  fi
  sleep 0.1
done

sleep "${pre_fault_seconds}"
printf '{"event":"fault_requested","kind":"%s","seed":%s,"timestamp":"%s"}\n' \
  "${scenario}" "${seed}" "$(date -u +%Y-%m-%dT%H:%M:%S.%3NZ)" | tee -a "${event_log}"
TRANSITION_FAULT_MARKER="${fault_marker}" "${injector[@]}" | tee -a "${event_log}"
touch "${elected_marker}"

status=0
wait "${runner_pid}" || status=$?
runner_pid=""
cat "${runner_log}"

trap - EXIT INT TERM
if ! cleanup; then
  status=1
fi
exit "${status}"
