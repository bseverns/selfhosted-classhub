#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/compose/.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "[env-check] missing compose/.env (copy from compose/.env.example first)" >&2
  exit 1
fi

env_file_value() {
  local key="$1"
  local raw
  raw="$(grep -E "^${key}=" "${ENV_FILE}" | tail -n1 | cut -d= -f2- || true)"
  raw="${raw%\"}"
  raw="${raw#\"}"
  raw="${raw%\'}"
  raw="${raw#\'}"
  echo "${raw}"
}

fail() {
  echo "[env-check] FAIL: $*" >&2
  exit 1
}

contains_icase() {
  local haystack="$1"
  local needle="$2"
  if [[ "${haystack,,}" == *"${needle,,}"* ]]; then
    return 0
  fi
  return 1
}

is_unsafe_secret() {
  local v="$1"
  local lower="${v,,}"

  if [[ -z "${v}" ]]; then
    return 0
  fi

  if [[ "${#v}" -lt 16 ]]; then
    return 0
  fi

  local blocked=(
    "replace_me"
    "replace_me_strong"
    "change_me"
    "changeme"
    "dev-secret"
    "secret"
    "password"
    "__set_me__"
    "example"
  )

  local token
  for token in "${blocked[@]}"; do
    if contains_icase "${lower}" "${token}"; then
      return 0
    fi
  done

  if [[ "${lower}" == django-insecure* ]]; then
    return 0
  fi

  return 1
}

require_nonempty() {
  local key="$1"
  local val
  val="$(env_file_value "${key}")"
  if [[ -z "${val}" ]]; then
    fail "${key} is empty or missing"
  fi
}

require_strong_secret() {
  local key="$1"
  local min_len="$2"
  local val
  val="$(env_file_value "${key}")"
  if [[ -z "${val}" ]]; then
    fail "${key} is empty or missing"
  fi
  if [[ "${#val}" -lt "${min_len}" ]]; then
    fail "${key} must be at least ${min_len} characters"
  fi
  if is_unsafe_secret "${val}"; then
    fail "${key} looks like a placeholder/default value"
  fi
}

DJANGO_DEBUG="$(env_file_value DJANGO_DEBUG)"
DJANGO_DEBUG="${DJANGO_DEBUG:-0}"

require_nonempty "POSTGRES_DB"
require_nonempty "POSTGRES_USER"
require_strong_secret "POSTGRES_PASSWORD" 16
require_strong_secret "MINIO_ROOT_PASSWORD" 16
require_nonempty "MINIO_ROOT_USER"

if [[ "${DJANGO_DEBUG}" == "0" ]]; then
  require_strong_secret "DJANGO_SECRET_KEY" 32
  ADMIN_2FA_REQUIRED="$(env_file_value DJANGO_ADMIN_2FA_REQUIRED)"
  ADMIN_2FA_REQUIRED="${ADMIN_2FA_REQUIRED:-1}"
  if [[ "${ADMIN_2FA_REQUIRED}" != "1" ]]; then
    fail "DJANGO_ADMIN_2FA_REQUIRED must be 1 when DJANGO_DEBUG=0"
  fi
else
  if [[ -z "$(env_file_value DJANGO_SECRET_KEY)" ]]; then
    fail "DJANGO_SECRET_KEY is required even in debug mode"
  fi
fi

HELPER_LLM_BACKEND="$(env_file_value HELPER_LLM_BACKEND)"
if [[ "${HELPER_LLM_BACKEND,,}" == "openai" ]]; then
  require_strong_secret "OPENAI_API_KEY" 20
fi

CADDYFILE_TEMPLATE="$(env_file_value CADDYFILE_TEMPLATE)"
if [[ "${CADDYFILE_TEMPLATE}" != "Caddyfile.local" && "${CADDYFILE_TEMPLATE}" != "Caddyfile.domain" ]]; then
  fail "CADDYFILE_TEMPLATE must be Caddyfile.local or Caddyfile.domain"
fi

if [[ "${CADDYFILE_TEMPLATE}" == "Caddyfile.domain" ]]; then
  DOMAIN_VAL="$(env_file_value DOMAIN)"
  if [[ -z "${DOMAIN_VAL}" ]]; then
    fail "DOMAIN is required when using Caddyfile.domain"
  fi
  if contains_icase "${DOMAIN_VAL}" "example.org" || contains_icase "${DOMAIN_VAL}" "example.com"; then
    fail "DOMAIN appears to be a placeholder: ${DOMAIN_VAL}"
  fi
fi

echo "[env-check] OK"
