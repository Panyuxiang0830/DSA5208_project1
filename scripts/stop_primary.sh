#!/usr/bin/env bash

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/cluster_control.sh"

ensure_no_active_fault
previous_primary="$(discover_primary)"
write_fault_state "primary-stop" "${previous_primary}" "${previous_primary}"

if [[ -n "${TRANSITION_FAULT_MARKER:-}" ]]; then
  touch "${TRANSITION_FAULT_MARKER}"
fi
started_ns="$(date +%s%N)"
emit_event "fault_started" "primary-stop" "${previous_primary}" "${previous_primary}"
docker compose stop -t 0 "${previous_primary}" >/dev/null
read -r new_primary election_ms < <(
  wait_for_new_primary "${previous_primary}" "${started_ns}" 45
)
emit_event "fault_injected" "primary-stop" "${previous_primary}" "${previous_primary}" "${new_primary}" "${election_ms}"
