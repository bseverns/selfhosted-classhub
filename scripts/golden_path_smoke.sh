#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SMOKE_SCRIPT="${ROOT_DIR}/scripts/smoke_check.sh"

COURSE_SLUG="${COURSE_SLUG:-piper_scratch_12_session}"
CLASS_NAME="${CLASS_NAME:-Smoke Validation Class}"
TEACHER_USERNAME="${TEACHER_USERNAME:-smoke_teacher}"
TEACHER_EMAIL="${TEACHER_EMAIL:-smoke_teacher@example.org}"
TEACHER_PASSWORD="${TEACHER_PASSWORD:-Sm0keTeacherPass123!}"
HELPER_MESSAGE="${SMOKE_HELPER_MESSAGE:-Help me with AP calculus limits.}"

COMPOSE_MODE="${COMPOSE_MODE:-prod}" # prod or dev
BRING_UP=1
BUILD_STACK=0
UP_TIMEOUT_SECONDS=180

SMOKE_BASE_URL="${SMOKE_BASE_URL:-}"
SMOKE_TIMEOUT_SECONDS="${SMOKE_TIMEOUT_SECONDS:-20}"
SMOKE_INSECURE_TLS="${SMOKE_INSECURE_TLS:-0}"

usage() {
  cat <<'EOF'
Usage: bash scripts/golden_path_smoke.sh [options]

Options:
  --course-slug <slug>            Course slug to import (default: piper_scratch_12_session)
  --class-name <name>             Class name to upsert for smoke flow
  --teacher-username <username>   Teacher username for smoke login
  --teacher-email <email>         Teacher email for smoke login
  --teacher-password <password>   Teacher password for smoke login
  --helper-message <text>         Message used for /helper/chat check
  --base-url <url>                Override smoke base URL
  --timeout-seconds <seconds>     Curl timeout for smoke_check.sh (default: 20)
  --insecure-tls                  Use curl -k for HTTPS checks
  --compose-mode <prod|dev>       Compose files (default: prod)
  --skip-up                       Do not run docker compose up -d
  --build                         Build images when bringing up stack
  --up-timeout-seconds <seconds>  Max wait for healthy services after up (default: 180)
  -h, --help                      Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --course-slug)
      COURSE_SLUG="$2"
      shift 2
      ;;
    --class-name)
      CLASS_NAME="$2"
      shift 2
      ;;
    --teacher-username)
      TEACHER_USERNAME="$2"
      shift 2
      ;;
    --teacher-email)
      TEACHER_EMAIL="$2"
      shift 2
      ;;
    --teacher-password)
      TEACHER_PASSWORD="$2"
      shift 2
      ;;
    --helper-message)
      HELPER_MESSAGE="$2"
      shift 2
      ;;
    --base-url)
      SMOKE_BASE_URL="$2"
      shift 2
      ;;
    --timeout-seconds)
      SMOKE_TIMEOUT_SECONDS="$2"
      shift 2
      ;;
    --insecure-tls)
      SMOKE_INSECURE_TLS=1
      shift
      ;;
    --compose-mode)
      COMPOSE_MODE="$2"
      shift 2
      ;;
    --skip-up)
      BRING_UP=0
      shift
      ;;
    --build)
      BUILD_STACK=1
      shift
      ;;
    --up-timeout-seconds)
      UP_TIMEOUT_SECONDS="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[golden-smoke] unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if ! command -v docker >/dev/null 2>&1; then
  echo "[golden-smoke] docker is required" >&2
  exit 1
fi

if [[ "${COMPOSE_MODE}" == "prod" ]]; then
  COMPOSE_ARGS=(-f "${ROOT_DIR}/compose/docker-compose.yml")
elif [[ "${COMPOSE_MODE}" == "dev" ]]; then
  COMPOSE_ARGS=(-f "${ROOT_DIR}/compose/docker-compose.yml" -f "${ROOT_DIR}/compose/docker-compose.override.yml")
else
  echo "[golden-smoke] invalid --compose-mode '${COMPOSE_MODE}' (expected prod|dev)" >&2
  exit 1
fi

run_compose() {
  docker compose "${COMPOSE_ARGS[@]}" "$@"
}

health_state() {
  local container_name="$1"
  docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container_name}" 2>/dev/null || true
}

wait_for_container_state() {
  local container_name="$1"
  local expected_state="$2"
  local deadline
  deadline=$((SECONDS + UP_TIMEOUT_SECONDS))
  while (( SECONDS < deadline )); do
    local state
    state="$(health_state "${container_name}")"
    if [[ "${state}" == "${expected_state}" ]]; then
      echo "[golden-smoke] ${container_name} ${state}"
      return 0
    fi
    sleep 2
  done
  echo "[golden-smoke] timeout waiting for ${container_name} to become ${expected_state}" >&2
  echo "[golden-smoke] last state: $(health_state "${container_name}")" >&2
  return 1
}

if [[ "${BRING_UP}" == "1" ]]; then
  echo "[golden-smoke] starting stack (compose mode: ${COMPOSE_MODE})"
  if [[ "${BUILD_STACK}" == "1" ]]; then
    run_compose up -d --build
  else
    run_compose up -d
  fi

  wait_for_container_state classhub_postgres healthy
  wait_for_container_state classhub_redis healthy
  wait_for_container_state classhub_web healthy
  wait_for_container_state helper_web healthy
  wait_for_container_state classhub_caddy running
fi

echo "[golden-smoke] upserting course/class fixtures"
run_compose exec -T classhub_web \
  python manage.py import_coursepack \
  --course-slug "${COURSE_SLUG}" \
  --class-name "${CLASS_NAME}" \
  --create-class \
  --replace

CLASS_CODE="$(
  run_compose exec -T \
    -e SMOKE_CLASS_NAME="${CLASS_NAME}" \
    classhub_web \
    python manage.py shell -c \
    "import os; from hub.models import Class; print(Class.objects.get(name=os.environ['SMOKE_CLASS_NAME']).join_code)"
)"

CLASS_CODE="$(echo "${CLASS_CODE}" | tr -d '\r' | tail -n1)"
if [[ -z "${CLASS_CODE}" ]]; then
  echo "[golden-smoke] failed to resolve class code for class '${CLASS_NAME}'" >&2
  exit 1
fi

echo "[golden-smoke] ensuring teacher account"
TEACHER_EXISTS="$(
  run_compose exec -T \
    -e SMOKE_TEACHER_USERNAME="${TEACHER_USERNAME}" \
    classhub_web \
    python manage.py shell -c \
    "import os; from django.contrib.auth import get_user_model; print('1' if get_user_model().objects.filter(username=os.environ['SMOKE_TEACHER_USERNAME']).exists() else '0')"
)"
TEACHER_EXISTS="$(echo "${TEACHER_EXISTS}" | tr -d '\r' | tail -n1)"

if [[ "${TEACHER_EXISTS}" == "1" ]]; then
  run_compose exec -T classhub_web \
    python manage.py create_teacher \
    --username "${TEACHER_USERNAME}" \
    --email "${TEACHER_EMAIL}" \
    --password "${TEACHER_PASSWORD}" \
    --active \
    --update
else
  run_compose exec -T classhub_web \
    python manage.py create_teacher \
    --username "${TEACHER_USERNAME}" \
    --email "${TEACHER_EMAIL}" \
    --password "${TEACHER_PASSWORD}" \
    --active
fi

echo "[golden-smoke] running strict smoke checks"
SMOKE_ENV=(
  "SMOKE_CLASS_CODE=${CLASS_CODE}"
  "SMOKE_TEACHER_USERNAME=${TEACHER_USERNAME}"
  "SMOKE_TEACHER_PASSWORD=${TEACHER_PASSWORD}"
  "SMOKE_TIMEOUT_SECONDS=${SMOKE_TIMEOUT_SECONDS}"
  "SMOKE_INSECURE_TLS=${SMOKE_INSECURE_TLS}"
  "SMOKE_HELPER_MESSAGE=${HELPER_MESSAGE}"
)
if [[ -n "${SMOKE_BASE_URL}" ]]; then
  SMOKE_ENV+=("SMOKE_BASE_URL=${SMOKE_BASE_URL}")
fi

env "${SMOKE_ENV[@]}" "${SMOKE_SCRIPT}" --strict

echo "[golden-smoke] PASS class_code=${CLASS_CODE} teacher=${TEACHER_USERNAME}"
