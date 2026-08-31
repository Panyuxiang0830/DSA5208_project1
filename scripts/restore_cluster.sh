#!/usr/bin/env bash

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/cluster_control.sh"

fault_kind="none"
target=""
previous_primary=""
recovery_started_ns=""
if [[ -f "${FAULT_STATE_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${FAULT_STATE_FILE}"
  fault_kind="${FAULT_KIND}"
  target="${TARGET_SERVICE}"
  previous_primary="${PREVIOUS_PRIMARY}"
fi

if [[ "${fault_kind}" == "secondary-replication-pause" ]] && container_running "${target}"; then
  recovery_started_ns="$(date +%s%N)"
  docker exec "$(container_name "${target}")" mongosh --quiet --eval '
    const result = db.adminCommand({
      configureFailPoint: "rsSyncApplyStop",
      mode: "off"
    });
    if (result.ok !== 1) quit(1);
  ' >/dev/null
fi

for service in "${MONGO_SERVICES[@]}"; do
  if container_running "${service}" && ! container_on_network "${service}"; then
    docker network connect --alias "${service}" "${MONGO_NETWORK}" "$(container_name "${service}")"
  fi
done

docker compose up -d --wait mongo1 mongo2 mongo3 >/dev/null
wait_for_healthy_cluster 90
recovery_ms=""
if [[ "${fault_kind}" == "secondary-replication-pause" ]]; then
  if [[ -z "${recovery_started_ns}" ]]; then
    recovery_started_ns="$(date +%s%N)"
  fi
  wait_for_replication_caught_up 120 1
  recovery_ended_ns="$(date +%s%N)"
  recovery_ms=$(((recovery_ended_ns - recovery_started_ns) / 1000000))
fi
new_primary="$(discover_primary)"
emit_event "cluster_restored" "${fault_kind}" "${target}" "${previous_primary}" "${new_primary}" "" "${recovery_ms}"
rm -f "${FAULT_STATE_FILE}"
