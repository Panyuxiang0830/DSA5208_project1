#!/usr/bin/env bash

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/cluster_control.sh"

ensure_no_active_fault
previous_primary="$(discover_primary)"
target="$(choose_secondary "${1:-}")"
write_fault_state "secondary-stop" "${target}" "${previous_primary}"

docker compose stop -t 0 "${target}" >/dev/null
emit_event "fault_injected" "secondary-stop" "${target}" "${previous_primary}" "${previous_primary}" "0"
