#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${PROJECT_ROOT}"

MONGO_NETWORK="${MONGO_NETWORK:-dsa5208-mongo-net}"
FAULT_STATE_DIR="${PROJECT_ROOT}/.fault-state"
FAULT_STATE_FILE="${FAULT_STATE_DIR}/active.env"
MONGO_SERVICES=(mongo1 mongo2 mongo3)

timestamp_utc() {
  date -u +%Y-%m-%dT%H:%M:%S.%3NZ
}

container_id() {
  docker compose ps -q "$1"
}

container_name() {
  local id
  id="$(container_id "$1")"
  if [[ -z "${id}" ]]; then
    return 1
  fi
  docker inspect -f '{{.Name}}' "${id}" | sed 's#^/##'
}

container_running() {
  local id
  id="$(container_id "$1")"
  [[ -n "${id}" ]] && [[ "$(docker inspect -f '{{.State.Running}}' "${id}")" == "true" ]]
}

container_on_network() {
  local name
  name="$(container_name "$1")"
  docker inspect -f '{{range $key, $value := .NetworkSettings.Networks}}{{println $key}}{{end}}' "${name}" \
    | grep -Fxq "${MONGO_NETWORK}"
}

service_role() {
  local service="$1"
  if ! container_running "${service}"; then
    printf 'DOWN\n'
    return
  fi

  local name
  name="$(container_name "${service}")"
  docker exec "${name}" mongosh --quiet --eval '
    try {
      const hello = db.hello();
      if (hello.isWritablePrimary) print("PRIMARY");
      else if (hello.secondary) print("SECONDARY");
      else print("OTHER");
    } catch (error) {
      print("UNREACHABLE");
    }
  ' 2>/dev/null | tail -n 1
}

discover_primary() {
  local service role
  for service in "${MONGO_SERVICES[@]}"; do
    role="$(service_role "${service}")"
    if [[ "${role}" == "PRIMARY" ]]; then
      printf '%s\n' "${service}"
      return 0
    fi
  done
  return 1
}

discover_primary_excluding() {
  local excluded="$1"
  local service role
  for service in "${MONGO_SERVICES[@]}"; do
    [[ "${service}" == "${excluded}" ]] && continue
    role="$(service_role "${service}")"
    if [[ "${role}" == "PRIMARY" ]]; then
      printf '%s\n' "${service}"
      return 0
    fi
  done
  return 1
}

choose_secondary() {
  local requested="${1:-}"
  local service role
  if [[ -n "${requested}" ]]; then
    role="$(service_role "${requested}")"
    if [[ "${role}" != "SECONDARY" ]]; then
      echo "Requested target ${requested} is ${role}, not SECONDARY." >&2
      return 1
    fi
    printf '%s\n' "${requested}"
    return
  fi

  for service in "${MONGO_SERVICES[@]}"; do
    role="$(service_role "${service}")"
    if [[ "${role}" == "SECONDARY" ]]; then
      printf '%s\n' "${service}"
      return 0
    fi
  done
  return 1
}

ensure_no_active_fault() {
  if [[ -f "${FAULT_STATE_FILE}" ]]; then
    echo "An active fault is already recorded in ${FAULT_STATE_FILE}. Restore first." >&2
    return 1
  fi
}

write_fault_state() {
  local kind="$1"
  local target="$2"
  local previous_primary="$3"
  mkdir -p "${FAULT_STATE_DIR}"
  {
    printf 'FAULT_KIND=%q\n' "${kind}"
    printf 'TARGET_SERVICE=%q\n' "${target}"
    printf 'PREVIOUS_PRIMARY=%q\n' "${previous_primary}"
    printf 'STARTED_AT=%q\n' "$(timestamp_utc)"
  } >"${FAULT_STATE_FILE}"
}

emit_event() {
  local event="$1"
  local kind="$2"
  local target="$3"
  local previous_primary="$4"
  local new_primary="${5:-}"
  local election_ms="${6:-}"
  printf '{"event":"%s","kind":"%s","target":"%s","previous_primary":"%s","new_primary":"%s","election_ms":"%s","timestamp":"%s"}\n' \
    "${event}" "${kind}" "${target}" "${previous_primary}" "${new_primary}" "${election_ms}" "$(timestamp_utc)"
}

wait_for_new_primary() {
  local previous_primary="$1"
  local started_ns="$2"
  local timeout_seconds="${3:-45}"
  local deadline=$((SECONDS + timeout_seconds))
  local new_primary now_ns election_ms

  while ((SECONDS < deadline)); do
    if new_primary="$(discover_primary_excluding "${previous_primary}")"; then
      now_ns="$(date +%s%N)"
      election_ms=$(((now_ns - started_ns) / 1000000))
      printf '%s %s\n' "${new_primary}" "${election_ms}"
      return 0
    fi
    sleep 0.25
  done

  echo "No replacement Primary elected within ${timeout_seconds}s." >&2
  return 1
}

wait_for_healthy_cluster() {
  local timeout_seconds="${1:-90}"
  local deadline=$((SECONDS + timeout_seconds))
  local service role primary_count secondary_count stable_checks
  stable_checks=0

  while ((SECONDS < deadline)); do
    primary_count=0
    secondary_count=0
    for service in "${MONGO_SERVICES[@]}"; do
      role="$(service_role "${service}")"
      [[ "${role}" == "PRIMARY" ]] && primary_count=$((primary_count + 1))
      [[ "${role}" == "SECONDARY" ]] && secondary_count=$((secondary_count + 1))
    done
    if [[ "${primary_count}" -eq 1 && "${secondary_count}" -eq 2 ]]; then
      stable_checks=$((stable_checks + 1))
      if [[ "${stable_checks}" -ge 3 ]]; then
        return 0
      fi
    else
      stable_checks=0
    fi
    sleep 1
  done

  echo "Cluster did not recover to one Primary and two Secondaries." >&2
  for service in "${MONGO_SERVICES[@]}"; do
    printf '%s=%s\n' "${service}" "$(service_role "${service}")" >&2
  done
  return 1
}
