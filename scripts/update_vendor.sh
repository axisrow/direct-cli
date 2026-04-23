#!/usr/bin/env bash
# Update vendored tapi-yandex-direct from axisrow fork if a new version is available.
# Compares __version__ in the vendored copy vs. the fork's main branch.
# If versions differ: clones, copies files, commits.

set -euo pipefail

FORK_URL="https://github.com/axisrow/tapi-yandex-direct.git"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR_DIR="${ROOT_DIR}/direct_cli/_vendor/tapi_yandex_direct"
VENDOR_INIT="${VENDOR_DIR}/__init__.py"

smoke_vendor_import() {
  (
    cd "${ROOT_DIR}"
    python3 -c "from direct_cli._vendor.tapi_yandex_direct import YandexDirect; YandexDirect(access_token='test-token')"
  )
}

# --- Read current vendored version ---
if [[ ! -f "${VENDOR_INIT}" ]]; then
  echo "ERROR: Vendor directory not found: ${VENDOR_DIR}"
  exit 1
fi

CURRENT_VERSION=$(grep -m1 '__version__' "${VENDOR_INIT}" | sed "s/.*= *['\"]//;s/['\"].*//")
echo "Current vendored version: ${CURRENT_VERSION}"

# --- Clone fork into temp dir ---
TMP_DIR=$(mktemp -d)
trap 'rm -rf "${TMP_DIR}"' EXIT

git clone --quiet --depth 1 "${FORK_URL}" "${TMP_DIR}/fork"

FORK_VERSION=$(grep -m1 '__version__' "${TMP_DIR}/fork/tapi_yandex_direct/__init__.py" | sed "s/.*= *['\"]//;s/['\"].*//")
echo "Fork version: ${FORK_VERSION}"

# --- Compare ---
if [[ "${CURRENT_VERSION}" == "${FORK_VERSION}" ]]; then
  echo "Vendor up to date (${CURRENT_VERSION}), nothing to do."
  smoke_vendor_import
  exit 0
fi

echo "Updating vendor: ${CURRENT_VERSION} -> ${FORK_VERSION}"

# --- Copy files ---
cp "${TMP_DIR}/fork/tapi_yandex_direct/__init__.py"        "${VENDOR_DIR}/"
cp "${TMP_DIR}/fork/tapi_yandex_direct/tapi_yandex_direct.py" "${VENDOR_DIR}/"
cp "${TMP_DIR}/fork/tapi_yandex_direct/resource_mapping.py" "${VENDOR_DIR}/"
cp "${TMP_DIR}/fork/tapi_yandex_direct/exceptions.py"       "${VENDOR_DIR}/"

python3 "${ROOT_DIR}/scripts/patch_vendor_imports.py" "${VENDOR_DIR}"
smoke_vendor_import

# --- Commit ---
cd "${ROOT_DIR}"
git add direct_cli/_vendor/tapi_yandex_direct/
git commit -m "chore(vendor): update tapi-yandex-direct to ${FORK_VERSION}"

echo "Done: vendored tapi-yandex-direct updated to ${FORK_VERSION}."
