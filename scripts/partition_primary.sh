#!/usr/bin/env bash

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/cluster_control.sh"

ensure_no_active_fault
previous_primary="$(discover_primary)"
target_container="$(container_name "${previous_primary}")"
write_fault_state "primary-partition" "${previous_primary}" "${previous_primary}"

started_ns="$(date +%s%N)"
docker network disconnect "${MONGO_NETWORK}" "${target_container}"
read -r new_primary election_ms < <(
  wait_for_new_primary "${previous_primary}" "${started_ns}" 45
)
emit_event "fault_injected" "primary-partition" "${previous_primary}" "${previous_primary}" "${new_primary}" "${election_ms}"
