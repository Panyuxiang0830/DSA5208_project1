#!/usr/bin/env bash

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/cluster_control.sh"

ensure_no_active_fault
previous_primary="$(discover_primary)"
target="$(choose_secondary "${1:-}")"
write_fault_state "secondary-replication-pause" "${target}" "${previous_primary}"

docker exec "$(container_name "${target}")" mongosh --quiet --eval '
  const result = db.adminCommand({
    configureFailPoint: "rsSyncApplyStop",
    mode: "alwaysOn"
  });
  if (result.ok !== 1) quit(1);
' >/dev/null

emit_event "fault_injected" "secondary-replication-pause" "${target}" \
  "${previous_primary}" "${previous_primary}" "0"
