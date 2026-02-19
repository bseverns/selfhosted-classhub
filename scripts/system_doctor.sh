#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_CHECK="${ROOT_DIR}/scripts/validate_env_secrets.sh"
PORT_GUARD="${ROOT_DIR}/scripts/check_compose_port_exposure.py"
MIGRATION_GATE="${ROOT_DIR}/scripts/migration_gate.sh"
CONTENT_PREFLIGHT="${ROOT_DIR}/scripts/content_preflight.sh"
SMOKE_CHECK="${ROOT_DIR}/scripts/smoke_check.sh"
GOLDEN_SMOKE="${ROOT_DIR}/scripts/golden_path_smoke.sh"

COMPOSE_MODE="${COMPOSE_MODE:-prod}" # prod or dev
BRING_UP=1
BUILD_STACK=0
UP_TIMEOUT_SECONDS=180

COURSE_SLUG="${COURSE_SLUG:-piper_scratch_12_session}"
STRICT_CONTENT=0

SMOKE_MODE="${SMOKE_MODE:-golden}" # golden|strict|basic|off
SMOKE_BASE_URL="${SMOKE_BASE_URL:-}"
SMOKE_TIMEOUT_SECONDS="${SMOKE_TIMEOUT_SECONDS:-20}"
SMOKE_INSECURE_TLS="${SMOKE_INSECURE_TLS:-0}"
SMOKE_HELPER_MESSAGE="${SMOKE_HELPER_MESSAGE:-}"

usage() {
  cat <<'EOF'
Usage: bash scripts/system_doctor.sh [options]

Runs a full stack self-check:
1) env guardrails
2) port exposure guard
3) migration gate
4) content preflight
5) compose health
6) smoke checks

Options:
  --compose-mode <prod|dev>       Compose files (default: prod)
  --skip-up                       Do not run docker compose up -d
  --build                         Build images when bringing up stack
  --up-timeout-seconds <seconds>  Max wait for healthy services (default: 180)
  --course-slug <slug>            Course slug for content preflight (default: piper_scratch_12_session)
  --strict-content                Run strict global content preflight checks
  --smoke-mode <golden|strict|basic|off>
                                  golden: bootstrap fixtures + strict smoke
                                  strict: run scripts/smoke_check.sh --strict
                                  basic: run scripts/smoke_check.sh
                                  off: skip smoke step
  --base-url <url>                Override smoke base URL
  --timeout-seconds <seconds>     Curl timeout passed to smoke checks (default: 20)
  --insecure-tls                  Use curl -k for HTTPS smoke checks
  --helper-message <text>         Override helper smoke message
  -h, --help                      Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
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
    --course-slug)
      COURSE_SLUG="$2"
      shift 2
      ;;
    --strict-content)
      STRICT_CONTENT=1
      shift
      ;;
    --smoke-mode)
      SMOKE_MODE="$2"
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
    --helper-message)
      SMOKE_HELPER_MESSAGE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[doctor] unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if ! command -v docker >/dev/null 2>&1; then
  echo "[doctor] docker is required" >&2
  exit 1
fi

if [[ ! -f "${ROOT_DIR}/compose/.env" ]]; then
  echo "[doctor] missing compose/.env (copy from compose/.env.example first)" >&2
  exit 1
fi

if [[ "${COMPOSE_MODE}" == "prod" ]]; then
  COMPOSE_ARGS=(-f "${ROOT_DIR}/compose/docker-compose.yml")
elif [[ "${COMPOSE_MODE}" == "dev" ]]; then
  COMPOSE_ARGS=(-f "${ROOT_DIR}/compose/docker-compose.yml" -f "${ROOT_DIR}/compose/docker-compose.override.yml")
else
  echo "[doctor] invalid --compose-mode '${COMPOSE_MODE}' (expected prod|dev)" >&2
  exit 1
fi

case "${SMOKE_MODE}" in
  golden|strict|basic|off)
    ;;
  *)
    echo "[doctor] invalid --smoke-mode '${SMOKE_MODE}' (expected golden|strict|basic|off)" >&2
    exit 1
    ;;
esac

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
      echo "[doctor] ${container_name} ${state}"
      return 0
    fi
    sleep 2
  done
  echo "[doctor] timeout waiting for ${container_name} to become ${expected_state}" >&2
  echo "[doctor] last state: $(health_state "${container_name}")" >&2
  return 1
}

echo "[doctor] 1/6 env guardrails"
"${ENV_CHECK}"

echo "[doctor] 2/6 port exposure guard"
python3 "${PORT_GUARD}"

echo "[doctor] 3/6 migration gate"
"${MIGRATION_GATE}" --compose-mode "${COMPOSE_MODE}"

echo "[doctor] 4/6 content preflight (${COURSE_SLUG})"
if [[ "${STRICT_CONTENT}" == "1" ]]; then
  "${CONTENT_PREFLIGHT}" "${COURSE_SLUG}" --strict-global
else
  "${CONTENT_PREFLIGHT}" "${COURSE_SLUG}"
fi

echo "[doctor] 5/6 compose health"
if [[ "${BRING_UP}" == "1" ]]; then
  if [[ "${BUILD_STACK}" == "1" ]]; then
    run_compose up -d --build
  else
    run_compose up -d
  fi
fi

wait_for_container_state classhub_postgres healthy
wait_for_container_state classhub_redis healthy
wait_for_container_state classhub_web healthy
wait_for_container_state helper_web healthy
wait_for_container_state classhub_caddy running

echo "[doctor] 6/6 smoke checks (${SMOKE_MODE})"
if [[ "${SMOKE_MODE}" == "golden" ]]; then
  GOLDEN_ARGS=(
    --compose-mode "${COMPOSE_MODE}"
    --skip-up
    --course-slug "${COURSE_SLUG}"
    --timeout-seconds "${SMOKE_TIMEOUT_SECONDS}"
  )
  if [[ "${SMOKE_INSECURE_TLS}" == "1" ]]; then
    GOLDEN_ARGS+=(--insecure-tls)
  fi
  if [[ -n "${SMOKE_BASE_URL}" ]]; then
    GOLDEN_ARGS+=(--base-url "${SMOKE_BASE_URL}")
  fi
  if [[ -n "${SMOKE_HELPER_MESSAGE}" ]]; then
    GOLDEN_ARGS+=(--helper-message "${SMOKE_HELPER_MESSAGE}")
  fi
  "${GOLDEN_SMOKE}" "${GOLDEN_ARGS[@]}"
elif [[ "${SMOKE_MODE}" == "strict" ]]; then
  SMOKE_ENV=(
    "SMOKE_TIMEOUT_SECONDS=${SMOKE_TIMEOUT_SECONDS}"
    "SMOKE_INSECURE_TLS=${SMOKE_INSECURE_TLS}"
  )
  if [[ -n "${SMOKE_BASE_URL}" ]]; then
    SMOKE_ENV+=("SMOKE_BASE_URL=${SMOKE_BASE_URL}")
  fi
  if [[ -n "${SMOKE_HELPER_MESSAGE}" ]]; then
    SMOKE_ENV+=("SMOKE_HELPER_MESSAGE=${SMOKE_HELPER_MESSAGE}")
  fi
  env "${SMOKE_ENV[@]}" "${SMOKE_CHECK}" --strict
elif [[ "${SMOKE_MODE}" == "basic" ]]; then
  SMOKE_ENV=(
    "SMOKE_TIMEOUT_SECONDS=${SMOKE_TIMEOUT_SECONDS}"
    "SMOKE_INSECURE_TLS=${SMOKE_INSECURE_TLS}"
  )
  if [[ -n "${SMOKE_BASE_URL}" ]]; then
    SMOKE_ENV+=("SMOKE_BASE_URL=${SMOKE_BASE_URL}")
  fi
  if [[ -n "${SMOKE_HELPER_MESSAGE}" ]]; then
    SMOKE_ENV+=("SMOKE_HELPER_MESSAGE=${SMOKE_HELPER_MESSAGE}")
  fi
  env "${SMOKE_ENV[@]}" "${SMOKE_CHECK}"
else
  echo "[doctor] smoke checks skipped (--smoke-mode off)"
fi

echo "[doctor] ALL CHECKS PASSED"
