#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/compose/.env"

STRICT=0
if [[ "${1:-}" == "--strict" ]]; then
  STRICT=1
fi

derive_base_url() {
  local caddyfile_template
  local domain
  caddyfile_template="$(env_file_value CADDYFILE_TEMPLATE)"
  domain="$(env_file_value DOMAIN)"

  if [[ "${caddyfile_template}" == "Caddyfile.local" ]]; then
    echo "http://localhost"
  elif [[ -n "${domain}" ]]; then
    echo "https://${domain}"
  else
    echo "http://localhost"
  fi
}

env_file_value() {
  local key="$1"
  if [[ ! -f "${ENV_FILE}" ]]; then
    echo ""
    return 0
  fi
  local raw
  raw="$(grep -E "^${key}=" "${ENV_FILE}" | tail -n1 | cut -d= -f2- || true)"
  raw="${raw%\"}"
  raw="${raw#\"}"
  raw="${raw%\'}"
  raw="${raw#\'}"
  echo "${raw}"
}

EXPLICIT_BASE_URL="${SMOKE_BASE_URL:-}"
ENV_BASE_URL="$(env_file_value SMOKE_BASE_URL)"
CADDYFILE_TEMPLATE="$(env_file_value CADDYFILE_TEMPLATE)"

if [[ -n "${EXPLICIT_BASE_URL}" ]]; then
  BASE_URL="${EXPLICIT_BASE_URL}"
elif [[ "${CADDYFILE_TEMPLATE}" == "Caddyfile.local" ]]; then
  # In local routing mode we should probe the local stack, not placeholder domains.
  BASE_URL="http://localhost"
elif [[ -n "${ENV_BASE_URL}" ]]; then
  BASE_URL="${ENV_BASE_URL}"
else
  BASE_URL="$(derive_base_url)"
fi
DISPLAY_NAME="${SMOKE_DISPLAY_NAME:-$(env_file_value SMOKE_DISPLAY_NAME)}"
DISPLAY_NAME="${DISPLAY_NAME:-Smoke Student}"
HELPER_MESSAGE="${SMOKE_HELPER_MESSAGE:-$(env_file_value SMOKE_HELPER_MESSAGE)}"
HELPER_MESSAGE="${HELPER_MESSAGE:-Give one short Scratch hint about moving a sprite.}"
CLASS_CODE="${SMOKE_CLASS_CODE:-$(env_file_value SMOKE_CLASS_CODE)}"
TEACHER_USERNAME="${SMOKE_TEACHER_USERNAME:-$(env_file_value SMOKE_TEACHER_USERNAME)}"
TEACHER_PASSWORD="${SMOKE_TEACHER_PASSWORD:-$(env_file_value SMOKE_TEACHER_PASSWORD)}"
TEACHER_SESSION_KEY="${SMOKE_TEACHER_SESSION_KEY:-$(env_file_value SMOKE_TEACHER_SESSION_KEY)}"
TIMEOUT_SECONDS="${SMOKE_TIMEOUT_SECONDS:-$(env_file_value SMOKE_TIMEOUT_SECONDS)}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-20}"

INSECURE_TLS="${SMOKE_INSECURE_TLS:-$(env_file_value SMOKE_INSECURE_TLS)}"
INSECURE_TLS="${INSECURE_TLS:-0}"

CURL_FLAGS=(-sS --max-time "${TIMEOUT_SECONDS}")
if [[ "${INSECURE_TLS}" == "1" ]]; then
  CURL_FLAGS+=(-k)
fi

COOKIE_JAR="$(mktemp)"
TMP_JOIN="$(mktemp)"
TMP_HELPER="$(mktemp)"
TMP_HEADERS="$(mktemp)"
TMP_TEACH="$(mktemp)"
TMP_STUDENT_PAGE="$(mktemp)"
TMP_LOGIN="$(mktemp)"
trap 'rm -f "${COOKIE_JAR}" "${TMP_JOIN}" "${TMP_HELPER}" "${TMP_HEADERS}" "${TMP_TEACH}" "${TMP_STUDENT_PAGE}" "${TMP_LOGIN}"' EXIT

fail() {
  echo "[smoke] FAIL: $*" >&2
  exit 1
}

require_field_if_strict() {
  local value="$1"
  local field_name="$2"
  if [[ "${STRICT}" == "1" && -z "${value}" ]]; then
    fail "missing ${field_name} (set ${field_name})"
  fi
}

http_code() {
  local url="$1"
  curl "${CURL_FLAGS[@]}" -o /dev/null -w "%{http_code}" "$url"
}

echo "[smoke] base url: ${BASE_URL}"

code="$(http_code "${BASE_URL}/healthz")"
[[ "${code}" == "200" ]] || fail "/healthz returned ${code}"
echo "[smoke] /healthz OK"

code="$(http_code "${BASE_URL}/helper/healthz")"
[[ "${code}" == "200" ]] || fail "/helper/healthz returned ${code}"
echo "[smoke] /helper/healthz OK"

require_field_if_strict "${CLASS_CODE}" "SMOKE_CLASS_CODE"
if [[ -n "${TEACHER_SESSION_KEY}" ]]; then
  require_field_if_strict "${TEACHER_SESSION_KEY}" "SMOKE_TEACHER_SESSION_KEY"
else
  require_field_if_strict "${TEACHER_USERNAME}" "SMOKE_TEACHER_USERNAME"
  require_field_if_strict "${TEACHER_PASSWORD}" "SMOKE_TEACHER_PASSWORD"
fi

if [[ -n "${CLASS_CODE}" ]]; then
  curl "${CURL_FLAGS[@]}" -c "${COOKIE_JAR}" -b "${COOKIE_JAR}" "${BASE_URL}/" >/dev/null
  CSRF_TOKEN="$(awk '$6=="csrftoken"{print $7}' "${COOKIE_JAR}" | tail -n1)"
  [[ -n "${CSRF_TOKEN}" ]] || fail "unable to get csrftoken for student join"

  JOIN_PAYLOAD="$(printf '{"class_code":"%s","display_name":"%s"}' "${CLASS_CODE}" "${DISPLAY_NAME}")"
  code="$(curl "${CURL_FLAGS[@]}" -o "${TMP_JOIN}" -w "%{http_code}" \
    -c "${COOKIE_JAR}" -b "${COOKIE_JAR}" \
    -H "Content-Type: application/json" \
    -H "X-CSRFToken: ${CSRF_TOKEN}" \
    -H "Referer: ${BASE_URL}/" \
    --data "${JOIN_PAYLOAD}" \
    "${BASE_URL}/join")"
  [[ "${code}" == "200" ]] || fail "/join returned ${code}: $(cat "${TMP_JOIN}")"
  grep -Eq '"ok"[[:space:]]*:[[:space:]]*true' "${TMP_JOIN}" || fail "/join response missing ok=true: $(cat "${TMP_JOIN}")"
  echo "[smoke] /join OK"

  code="$(curl "${CURL_FLAGS[@]}" -o "${TMP_STUDENT_PAGE}" -w "%{http_code}" \
    -c "${COOKIE_JAR}" -b "${COOKIE_JAR}" \
    "${BASE_URL}/student")"
  [[ "${code}" == "200" ]] || fail "/student returned ${code}"

  SCOPE_TOKEN="$(
    grep -oE 'data-helper-scope-token="[^"]*"' "${TMP_STUDENT_PAGE}" | head -n1 | sed -E 's/^data-helper-scope-token="(.*)"$/\1/'
  )"

  if [[ -n "${SCOPE_TOKEN}" ]]; then
    HELPER_PAYLOAD="$(printf '{"message":"%s","scope_token":"%s"}' "${HELPER_MESSAGE}" "${SCOPE_TOKEN}")"
  else
    HELPER_PAYLOAD="$(printf '{"message":"%s","context":"smoke","topics":"scratch"}' "${HELPER_MESSAGE}")"
  fi

  code="$(curl "${CURL_FLAGS[@]}" -o "${TMP_HELPER}" -w "%{http_code}" \
    -c "${COOKIE_JAR}" -b "${COOKIE_JAR}" \
    -H "Content-Type: application/json" \
    -H "X-CSRFToken: ${CSRF_TOKEN}" \
    -H "Referer: ${BASE_URL}/" \
    --data "${HELPER_PAYLOAD}" \
    "${BASE_URL}/helper/chat")"
  [[ "${code}" == "200" ]] || fail "/helper/chat returned ${code}: $(cat "${TMP_HELPER}")"
  grep -Eq '"text"[[:space:]]*:' "${TMP_HELPER}" || fail "/helper/chat response missing text field: $(cat "${TMP_HELPER}")"
  echo "[smoke] /helper/chat OK"
fi

if [[ -n "${TEACHER_SESSION_KEY}" || ( -n "${TEACHER_USERNAME}" && -n "${TEACHER_PASSWORD}" ) ]]; then
  if [[ -n "${TEACHER_SESSION_KEY}" ]]; then
    code="$(curl "${CURL_FLAGS[@]}" -o "${TMP_TEACH}" -w "%{http_code}" -b "sessionid=${TEACHER_SESSION_KEY}" "${BASE_URL}/teach")"
    [[ "${code}" == "200" ]] || fail "/teach returned ${code} with supplied teacher session"
    echo "[smoke] teacher session + /teach OK"
  else
    curl "${CURL_FLAGS[@]}" -c "${COOKIE_JAR}" -b "${COOKIE_JAR}" "${BASE_URL}/admin/login/?next=/teach" >/dev/null
    CSRF_TOKEN="$(awk '$6=="csrftoken"{print $7}' "${COOKIE_JAR}" | tail -n1)"
    [[ -n "${CSRF_TOKEN}" ]] || fail "unable to get csrftoken for teacher login"

    login_code="$(curl "${CURL_FLAGS[@]}" -D "${TMP_HEADERS}" -o "${TMP_LOGIN}" -w "%{http_code}" \
      -c "${COOKIE_JAR}" -b "${COOKIE_JAR}" \
      -H "Referer: ${BASE_URL}/admin/login/?next=/teach" \
      -X POST \
      --data-urlencode "csrfmiddlewaretoken=${CSRF_TOKEN}" \
      --data-urlencode "username=${TEACHER_USERNAME}" \
      --data-urlencode "password=${TEACHER_PASSWORD}" \
      --data-urlencode "next=/teach" \
      "${BASE_URL}/admin/login/?next=/teach")"
    if [[ "${login_code}" != "200" && "${login_code}" != "302" && "${login_code}" != "303" ]]; then
      fail "teacher login returned ${login_code}: $(cat "${TMP_LOGIN}")"
    fi

    code="$(curl "${CURL_FLAGS[@]}" -o "${TMP_TEACH}" -w "%{http_code}" -c "${COOKIE_JAR}" -b "${COOKIE_JAR}" "${BASE_URL}/teach")"
    [[ "${code}" == "200" ]] || fail "/teach returned ${code} after login attempt (login status ${login_code}): $(cat "${TMP_LOGIN}")"
    echo "[smoke] teacher login + /teach OK"
  fi
fi

echo "[smoke] ALL CHECKS PASSED"
