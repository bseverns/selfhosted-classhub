#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/compose/.env"

STRICT=0
if [[ "${1:-}" == "--strict" ]]; then
  STRICT=1
fi

derive_base_url() {
  local domain
  domain="$(env_file_value DOMAIN)"

  if [[ -n "${domain}" ]]; then
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

BASE_URL="${SMOKE_BASE_URL:-$(env_file_value SMOKE_BASE_URL)}"
BASE_URL="${BASE_URL:-$(derive_base_url)}"
DISPLAY_NAME="${SMOKE_DISPLAY_NAME:-$(env_file_value SMOKE_DISPLAY_NAME)}"
DISPLAY_NAME="${DISPLAY_NAME:-Smoke Student}"
CLASS_CODE="${SMOKE_CLASS_CODE:-$(env_file_value SMOKE_CLASS_CODE)}"
TEACHER_USERNAME="${SMOKE_TEACHER_USERNAME:-$(env_file_value SMOKE_TEACHER_USERNAME)}"
TEACHER_PASSWORD="${SMOKE_TEACHER_PASSWORD:-$(env_file_value SMOKE_TEACHER_PASSWORD)}"
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
trap 'rm -f "${COOKIE_JAR}" "${TMP_JOIN}" "${TMP_HELPER}" "${TMP_HEADERS}" "${TMP_TEACH}"' EXIT

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
require_field_if_strict "${TEACHER_USERNAME}" "SMOKE_TEACHER_USERNAME"
require_field_if_strict "${TEACHER_PASSWORD}" "SMOKE_TEACHER_PASSWORD"

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

  code="$(curl "${CURL_FLAGS[@]}" -o "${TMP_HELPER}" -w "%{http_code}" \
    -c "${COOKIE_JAR}" -b "${COOKIE_JAR}" \
    -H "Content-Type: application/json" \
    -H "X-CSRFToken: ${CSRF_TOKEN}" \
    -H "Referer: ${BASE_URL}/" \
    --data '{"message":"Give one short Scratch hint about moving a sprite.","context":"smoke","topics":"scratch"}' \
    "${BASE_URL}/helper/chat")"
  [[ "${code}" == "200" ]] || fail "/helper/chat returned ${code}: $(cat "${TMP_HELPER}")"
  grep -Eq '"text"[[:space:]]*:' "${TMP_HELPER}" || fail "/helper/chat response missing text field: $(cat "${TMP_HELPER}")"
  echo "[smoke] /helper/chat OK"
fi

if [[ -n "${TEACHER_USERNAME}" && -n "${TEACHER_PASSWORD}" ]]; then
  curl "${CURL_FLAGS[@]}" -c "${COOKIE_JAR}" -b "${COOKIE_JAR}" "${BASE_URL}/admin/login/?next=/teach" >/dev/null
  CSRF_TOKEN="$(awk '$6=="csrftoken"{print $7}' "${COOKIE_JAR}" | tail -n1)"
  [[ -n "${CSRF_TOKEN}" ]] || fail "unable to get csrftoken for teacher login"

  code="$(curl "${CURL_FLAGS[@]}" -D "${TMP_HEADERS}" -o /dev/null -w "%{http_code}" \
    -c "${COOKIE_JAR}" -b "${COOKIE_JAR}" \
    -H "Referer: ${BASE_URL}/admin/login/?next=/teach" \
    -X POST \
    --data-urlencode "csrfmiddlewaretoken=${CSRF_TOKEN}" \
    --data-urlencode "username=${TEACHER_USERNAME}" \
    --data-urlencode "password=${TEACHER_PASSWORD}" \
    --data-urlencode "next=/teach" \
    "${BASE_URL}/admin/login/?next=/teach")"
  [[ "${code}" == "302" || "${code}" == "303" ]] || fail "teacher login returned ${code}"

  code="$(curl "${CURL_FLAGS[@]}" -o "${TMP_TEACH}" -w "%{http_code}" -c "${COOKIE_JAR}" -b "${COOKIE_JAR}" "${BASE_URL}/teach")"
  [[ "${code}" == "200" ]] || fail "/teach returned ${code} after login"
  echo "[smoke] teacher login + /teach OK"
fi

echo "[smoke] ALL CHECKS PASSED"
