#!/usr/bin/env bash
#
# Pre-release preflight check — runs the network-dependent docs / cache
# health checks that used to be wired into release_pypi.sh.
#
# Run this manually before bumping the version. It is *not* wired into
# release_pypi.sh on purpose: Yandex frequently rate-limits the docs host
# with a SmartCaptcha gateway, which is an external rate-limit on our IP,
# not evidence that an URL is gone. Mixing this into the release path made
# releases non-deterministic.
#
# What this script does:
#   1. scripts/check_all_docs_urls.py
#      Hard-fails on canonical move (3xx → different path) or 404.
#      Soft-warns on 5xx or persistent captcha (likely rate-limit).
#   2. pytest TestReportsCoverage TestWsdlCacheFreshness
#      Read-only: confirms committed cache files are real content, not
#      captcha gateways.
#   3. git diff --quiet -- tests/reports_cache tests/wsdl_cache
#      Refuses to proceed with uncommitted cache changes; the maintainer
#      must commit cache refreshes deliberately.
#
# Exit status: 0 if everything passes (warnings allowed), non-zero on any
# hard failure.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

require_command() {
  local name="$1"
  if ! command -v "${name}" >/dev/null 2>&1; then
    echo "Required command not found: ${name}" >&2
    exit 1
  fi
}

require_command python3
require_command git

cd "${ROOT_DIR}"

echo "[1/3] Checking docs URLs..."
python3 scripts/check_all_docs_urls.py

echo
echo "[2/3] Verifying committed docs/WSDL cache is real content..."
python3 -m pytest tests/test_api_coverage.py::TestReportsCoverage \
                  tests/test_api_coverage.py::TestWsdlCacheFreshness -v

echo
echo "[3/3] Checking that docs/WSDL cache has no uncommitted changes..."
if ! git diff --quiet HEAD -- tests/reports_cache tests/wsdl_cache; then
  echo "ERROR: tests/reports_cache or tests/wsdl_cache has uncommitted changes."
  echo "       Run scripts/refresh_reports_cache.py separately, review the diff,"
  echo "       and commit it before releasing."
  git diff --stat -- tests/reports_cache tests/wsdl_cache
  exit 1
fi

echo
echo "Preflight passed. Safe to bump version and run scripts/release_pypi.sh."
