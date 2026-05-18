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
  if ! python3 -m direct_cli.cli auth status 2>/dev/null | grep -q '^has_token=yes$'; then
    echo "ERROR: no credentials." >&2
    echo "       Use 'direct auth login', put .env, or export YANDEX_DIRECT_TOKEN+YANDEX_DIRECT_LOGIN." >&2
    exit 1
  fi
  eval "$(python3 -c '
from direct_cli.auth import get_credentials
token, login = get_credentials(None, None)
print(f"export YANDEX_DIRECT_TOKEN={token}")
print(f"export YANDEX_DIRECT_LOGIN={login}")
')"
fi

cd "$ROOT_DIR"
python3 scripts/sandbox_write_live.py "$@"
