#!/usr/bin/env bash

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/cluster_control.sh"

fault_kind="none"
target=""
previous_primary=""
if [[ -f "${FAULT_STATE_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${FAULT_STATE_FILE}"
  fault_kind="${FAULT_KIND}"
  target="${TARGET_SERVICE}"
  previous_primary="${PREVIOUS_PRIMARY}"
fi

for service in "${MONGO_SERVICES[@]}"; do
  if container_running "${service}" && ! container_on_network "${service}"; then
    docker network connect --alias "${service}" "${MONGO_NETWORK}" "$(container_name "${service}")"
  fi
done

docker compose up -d --wait mongo1 mongo2 mongo3 >/dev/null
wait_for_healthy_cluster 90
new_primary="$(discover_primary)"
emit_event "cluster_restored" "${fault_kind}" "${target}" "${previous_primary}" "${new_primary}" ""
rm -f "${FAULT_STATE_FILE}"
