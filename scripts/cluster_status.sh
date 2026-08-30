#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

docker compose exec -T mongo1 mongosh --quiet --eval '
const status = rs.status();
printjson(status.members.map((member) => ({
  name: member.name,
  state: member.stateStr,
  health: member.health,
  optimeDate: member.optimeDate
})));
'

