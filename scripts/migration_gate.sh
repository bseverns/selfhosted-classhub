#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/compose/docker-compose.yml"
COMPOSE_OVERRIDE="${ROOT_DIR}/compose/docker-compose.override.yml"
ENV_FILE="${ROOT_DIR}/compose/.env"
COMPOSE_MODE="${COMPOSE_MODE:-prod}" # prod or dev

usage() {
  cat <<'EOF'
Usage: bash scripts/migration_gate.sh [--compose-mode prod|dev]
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --compose-mode)
      COMPOSE_MODE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[migration-gate] unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if ! command -v docker >/dev/null 2>&1; then
  echo "[migration-gate] docker is required" >&2
  exit 1
fi

if [[ ! -f "${COMPOSE_FILE}" ]]; then
  echo "[migration-gate] missing compose file: ${COMPOSE_FILE}" >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "[migration-gate] missing compose/.env (copy from compose/.env.example first)" >&2
  exit 1
fi

if [[ "${COMPOSE_MODE}" == "prod" ]]; then
  COMPOSE_ARGS=(-f "${COMPOSE_FILE}")
elif [[ "${COMPOSE_MODE}" == "dev" ]]; then
  if [[ ! -f "${COMPOSE_OVERRIDE}" ]]; then
    echo "[migration-gate] compose override missing: ${COMPOSE_OVERRIDE}" >&2
    exit 1
  fi
  COMPOSE_ARGS=(-f "${COMPOSE_FILE}" -f "${COMPOSE_OVERRIDE}")
else
  echo "[migration-gate] invalid --compose-mode '${COMPOSE_MODE}' (expected prod|dev)" >&2
  exit 1
fi

run_compose() {
  docker compose "${COMPOSE_ARGS[@]}" "$@"
}

echo "[migration-gate] checking classhub migrations are committed"
run_compose run --rm --no-deps classhub_web python manage.py makemigrations --check --dry-run

echo "[migration-gate] checking helper migrations are committed"
run_compose run --rm --no-deps helper_web python manage.py makemigrations --check --dry-run

echo "[migration-gate] OK"
