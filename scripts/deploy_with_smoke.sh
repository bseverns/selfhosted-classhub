#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/compose/docker-compose.yml"
MIGRATION_GATE="${ROOT_DIR}/scripts/migration_gate.sh"
SMOKE_CHECK="${ROOT_DIR}/scripts/smoke_check.sh"
GOLDEN_SMOKE="${ROOT_DIR}/scripts/golden_path_smoke.sh"
ENV_CHECK="${ROOT_DIR}/scripts/validate_env_secrets.sh"
LAST_GOOD_FILE="${ROOT_DIR}/.deploy/last_good_ref"

if ! command -v docker >/dev/null 2>&1; then
  echo "[deploy] docker is required" >&2
  exit 1
fi

if [[ ! -f "${COMPOSE_FILE}" ]]; then
  echo "[deploy] missing compose file: ${COMPOSE_FILE}" >&2
  exit 1
fi

if [[ ! -f "${ROOT_DIR}/compose/.env" ]]; then
  echo "[deploy] missing compose/.env (copy from compose/.env.example first)" >&2
  exit 1
fi

if [[ ! -f "${ROOT_DIR}/compose/Caddyfile" ]]; then
  echo "[deploy] note: compose/Caddyfile is optional when using CADDYFILE_TEMPLATE in compose/.env"
fi

if [[ ! -x "${ENV_CHECK}" ]]; then
  echo "[deploy] missing or non-executable env check script: ${ENV_CHECK}" >&2
  exit 1
fi

run_compose() {
  docker compose -f "${COMPOSE_FILE}" "$@"
}

env_file_value() {
  local key="$1"
  local raw
  raw="$(grep -E "^${key}=" "${ROOT_DIR}/compose/.env" | tail -n1 | cut -d= -f2- || true)"
  raw="${raw%\"}"
  raw="${raw#\"}"
  raw="${raw%\'}"
  raw="${raw#\'}"
  echo "${raw}"
}

rollback_if_configured() {
  if [[ -n "${ROLLBACK_CMD:-}" ]]; then
    echo "[deploy] smoke failed; running rollback command"
    echo "[deploy] ROLLBACK_CMD=${ROLLBACK_CMD}"
    bash -lc "${ROLLBACK_CMD}"
  else
    echo "[deploy] smoke failed; no ROLLBACK_CMD configured"
    echo "[deploy] last recorded good ref (if any): $(cat "${LAST_GOOD_FILE}" 2>/dev/null || echo '<none>')"
  fi
}

echo "[deploy] validating compose/.env secrets and routing settings"
"${ENV_CHECK}"

echo "[deploy] running migration gate"
"${MIGRATION_GATE}"

echo "[deploy] launching production compose (docker-compose.yml only)"
run_compose up -d --build

template_from_env="$(env_file_value CADDYFILE_TEMPLATE)"
template_from_env="${template_from_env:-Caddyfile.local}"
EXPECTED_CADDYFILE="${ROOT_DIR}/compose/${template_from_env}"

if [[ ! -f "${EXPECTED_CADDYFILE}" ]]; then
  echo "[deploy] expected caddy template file not found: ${EXPECTED_CADDYFILE}" >&2
  exit 1
fi

ACTUAL_CADDYFILE="$(docker inspect classhub_caddy --format '{{range .Mounts}}{{if eq .Destination "/etc/caddy/Caddyfile"}}{{.Source}}{{end}}{{end}}' 2>/dev/null || true)"

if [[ -z "${ACTUAL_CADDYFILE}" ]]; then
  echo "[deploy] unable to resolve classhub_caddy mount source" >&2
  rollback_if_configured
  exit 1
fi

if [[ "${ACTUAL_CADDYFILE}" != "${EXPECTED_CADDYFILE}" ]]; then
  echo "[deploy] caddy config guardrail failed" >&2
  echo "[deploy] expected: ${EXPECTED_CADDYFILE}" >&2
  echo "[deploy] actual:   ${ACTUAL_CADDYFILE}" >&2
  rollback_if_configured
  exit 1
fi

echo "[deploy] caddy mount guardrail OK"

SMOKE_MODE="${DEPLOY_SMOKE_MODE:-strict}"
if [[ "${SMOKE_MODE}" == "golden" ]]; then
  set +e
  "${GOLDEN_SMOKE}" --compose-mode prod --skip-up
  smoke_status=$?
  set -e
elif [[ "${SMOKE_MODE}" == "strict" ]]; then
  set +e
  "${SMOKE_CHECK}" --strict
  smoke_status=$?
  set -e
else
  set +e
  "${SMOKE_CHECK}"
  smoke_status=$?
  set -e
fi

if [[ ${smoke_status} -ne 0 ]]; then
  rollback_if_configured
  exit ${smoke_status}
fi

mkdir -p "$(dirname "${LAST_GOOD_FILE}")"
git -C "${ROOT_DIR}" rev-parse HEAD > "${LAST_GOOD_FILE}" 2>/dev/null || true

echo "[deploy] SUCCESS"
