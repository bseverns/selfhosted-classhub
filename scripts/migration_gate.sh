#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ROOT_DIR}/compose/docker-compose.yml"
ENV_FILE="${ROOT_DIR}/compose/.env"

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

run_compose() {
  docker compose -f "${COMPOSE_FILE}" "$@"
}

echo "[migration-gate] checking classhub migrations are committed"
run_compose run --rm --no-deps classhub_web python manage.py makemigrations --check --dry-run

echo "[migration-gate] checking helper migrations are committed"
run_compose run --rm --no-deps helper_web python manage.py makemigrations --check --dry-run

echo "[migration-gate] OK"
