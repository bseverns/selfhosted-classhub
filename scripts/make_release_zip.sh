#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${ROOT_DIR}/dist"
STAMP="$(date +%Y%m%d_%H%M%S)"
GIT_SHA="$(git -C "${ROOT_DIR}" rev-parse --short HEAD 2>/dev/null || echo "nogit")"

DEFAULT_OUT="${OUT_DIR}/classhub_release_${STAMP}_${GIT_SHA}.zip"
OUT_PATH="${1:-${DEFAULT_OUT}}"

if ! command -v zip >/dev/null 2>&1; then
  echo "zip is required (install zip package)." >&2
  exit 1
fi

mkdir -p "$(dirname "${OUT_PATH}")"
OUT_ABS="$(cd "$(dirname "${OUT_PATH}")" && pwd)/$(basename "${OUT_PATH}")"

cd "${ROOT_DIR}"
zip -r "${OUT_ABS}" . \
  -x ".git/*" \
  -x ".venv/*" \
  -x "media/*" \
  -x "*/media/*" \
  -x "staticfiles/*" \
  -x "*/staticfiles/*" \
  -x "__MACOSX/*" \
  -x "*/__pycache__/*" \
  -x "*.pyc" \
  -x ".DS_Store" \
  -x "*/.DS_Store" \
  -x "dist/*"

echo "Release zip created: ${OUT_ABS}"
