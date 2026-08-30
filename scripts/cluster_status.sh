#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib/cluster_control.sh"

target="$(discover_primary || choose_secondary)"
docker compose exec -T "${target}" mongosh --quiet --eval '
const status = rs.status();
printjson(status.members.map((member) => ({
  name: member.name,
  state: member.stateStr,
  health: member.health,
  optimeDate: member.optimeDate
})));
'
