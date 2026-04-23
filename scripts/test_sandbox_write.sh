#!/usr/bin/env bash
# Run WRITE_SANDBOX commands against the live Yandex Direct sandbox API.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$ROOT_DIR/.env"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

if [[ -z "${YANDEX_DIRECT_TOKEN:-}" ]] || [[ -z "${YANDEX_DIRECT_LOGIN:-}" ]]; then
  echo "ERROR: YANDEX_DIRECT_TOKEN and YANDEX_DIRECT_LOGIN are required." >&2
  exit 1
fi

cd "$ROOT_DIR"
python3 scripts/sandbox_write_live.py "$@"
