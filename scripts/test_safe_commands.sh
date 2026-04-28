#!/usr/bin/env bash
# Test all read-only (safe) direct-cli commands against the real Yandex Direct API.
# Usage: ./scripts/test_safe_commands.sh
# Credentials: loads .env if present, otherwise uses auth profile from direct auth login.
#
# Resource-ID probes:
#   YANDEX_DIRECT_TEST_ADVIDEO_ID — override the AdVideo ID used by the
#     advideos.get probe (otherwise discovered via creatives.get; see
#     direct_cli._smoke_probes.advideo_probe_id). When no probe ID is found,
#     the advideos.get test is skipped, never falsely passed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$ROOT_DIR/.env"

PASS=0
FAIL=0
CAMPAIGN_ID=""
ADGROUP_ID=""

# ─── Colors ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
RESET='\033[0m'

# ─── Credentials ──────────────────────────────────────────────────────────────
AUTH_SOURCE=""

if [ -f "$ENV_FILE" ]; then
  set +u
  # shellcheck disable=SC2046
  export $(grep -v '^#' "$ENV_FILE" | grep -v '^$' | xargs)
  set -u
  AUTH_SOURCE="env"
fi

# Fallback: if .env didn't provide credentials, try auth profile
if [ -z "${YANDEX_DIRECT_TOKEN:-}" ]; then
  if direct auth status >/dev/null 2>&1; then
    AUTH_SOURCE="profile"
  else
    echo -e "${RED}ERROR:${RESET} No credentials found."
    echo "       Use 'direct auth login', put .env, or export YANDEX_DIRECT_TOKEN."
    exit 1
  fi
fi

if [ "$AUTH_SOURCE" = "profile" ]; then
  AUTH_LOGIN=$(direct auth status 2>&1 | grep '^login=' | cut -d= -f2)
  AUTH_TOKEN_HINT="(auth profile)"
else
  AUTH_LOGIN="${YANDEX_DIRECT_LOGIN:-}"
  AUTH_TOKEN_HINT="${YANDEX_DIRECT_TOKEN:0:8}..."
fi

echo -e "${BOLD}direct-cli safe commands test${RESET}"
echo "Source: $AUTH_SOURCE"
echo "Login: $AUTH_LOGIN"
echo "Token: $AUTH_TOKEN_HINT"
python3 - <<'PY'
from direct_cli.smoke_matrix import SAFE, commands_for_category

print(f"SAFE matrix commands: {len(commands_for_category(SAFE))}")
PY
echo ""

# ─── Helpers ─────────────────────────────────────────────────────────────────
run_test() {
  local name="$1"
  shift
  local output exit_code
  output=$("$@" 2>&1) && exit_code=0 || exit_code=$?
  if [ "$exit_code" -eq 0 ]; then
    echo -e "  ${GREEN}[PASS]${RESET} $name"
    ((PASS++)) || true
  else
    echo -e "  ${RED}[FAIL]${RESET} $name"
    echo "$output" | head -3 | sed 's/^/         /'
    ((FAIL++)) || true
  fi
}

is_agency_access_denied() {
  local output="$1"
  grep -Eiq "403|error_code=54|Access denied|No rights to access the agency service" <<<"$output"
}

run_agencyclients_sandbox_get() {
  local name="agencyclients get --sandbox"
  local output exit_code
  local args=(direct --sandbox)
  local has_dedicated_token=0
  local agency_login_provided=0

  if [ -n "${YANDEX_DIRECT_AGENCY_TOKEN:-}" ]; then
    has_dedicated_token=1
    args+=(--token "$YANDEX_DIRECT_AGENCY_TOKEN")
    if [ -n "${YANDEX_DIRECT_AGENCY_LOGIN:-}" ]; then
      args+=(--login "$YANDEX_DIRECT_AGENCY_LOGIN")
      agency_login_provided=1
    fi
  fi

  args+=(agencyclients get --archived NO --limit 1 --format json)
  if [ "$has_dedicated_token" -eq 1 ] && [ "$agency_login_provided" -eq 0 ]; then
    # Prevent the agency token from inheriting the regular YANDEX_DIRECT_LOGIN
    # from .env — that mismatch would trigger a real API error and a false FAIL.
    output=$(env -u YANDEX_DIRECT_LOGIN "${args[@]}" 2>&1) && exit_code=0 || exit_code=$?
  else
    output=$("${args[@]}" 2>&1) && exit_code=0 || exit_code=$?
  fi

  if [ "$exit_code" -eq 0 ]; then
    echo -e "  ${GREEN}[PASS]${RESET} $name"
    ((PASS++)) || true
  elif [ "$has_dedicated_token" -eq 0 ] && is_agency_access_denied "$output"; then
    echo -e "  ${YELLOW}[SKIP]${RESET} $name — no agency sandbox credentials"
  else
    echo -e "  ${RED}[FAIL]${RESET} $name"
    echo "$output" | head -3 | sed 's/^/         /'
    ((FAIL++)) || true
  fi
}

run_advideos_probe_get() {
  local name="advideos get --ids (env auth)"
  local advideo_id output exit_code

  advideo_id=$(python3 -m direct_cli._smoke_probes advideo 2>/dev/null) && exit_code=0 || exit_code=$?
  if [ "$exit_code" -ne 0 ] || [ -z "$advideo_id" ]; then
    echo -e "  ${YELLOW}[SKIP]${RESET} $name — no accepted video ID found"
    return
  fi

  output=$(direct advideos get --ids "$advideo_id" 2>&1) && exit_code=0 || exit_code=$?
  if [ "$exit_code" -eq 0 ]; then
    echo -e "  ${GREEN}[PASS]${RESET} $name"
    ((PASS++)) || true
  else
    echo -e "  ${RED}[FAIL]${RESET} $name"
    echo "$output" | head -3 | sed 's/^/         /'
    ((FAIL++)) || true
  fi
}

# ─── Section A: Auth via env variables (no CLI flags) ────────────────────────
echo -e "${BOLD}=== A. Аутентификация через env-переменные ===${RESET}"
echo ""

echo -e "  ${YELLOW}[INFO]${RESET} Получаем campaign ID для зависимых тестов..."
CAMPAIGNS_JSON=$(direct campaigns get 2>&1) && CAMPS_OK=0 || CAMPS_OK=$?

if [ "$CAMPS_OK" -eq 0 ]; then
  echo -e "  ${GREEN}[PASS]${RESET} campaigns get (env auth)"
  ((PASS++)) || true
  # Output is a JSON array of campaign objects
  CAMPAIGN_ID=$(echo "$CAMPAIGNS_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
# Output is a flat array
if isinstance(data, list) and data:
    print(data[0].get('Id', ''))
elif isinstance(data, dict):
    campaigns = data.get('result', {}).get('Campaigns', data.get('Campaigns', []))
    if campaigns:
        print(campaigns[0].get('Id', ''))
" 2>/dev/null || true)
else
  echo -e "  ${RED}[FAIL]${RESET} campaigns get (env auth)"
  echo "$CAMPAIGNS_JSON" | head -3 | sed 's/^/         /'
  ((FAIL++)) || true
fi

if [ -n "$CAMPAIGN_ID" ]; then
  echo -e "  ${YELLOW}[INFO]${RESET} Используем campaign ID: $CAMPAIGN_ID"

  # Try to get an adgroup ID for audiencetargets test
  ADGROUPS_JSON=$(direct adgroups get --campaign-ids "$CAMPAIGN_ID" 2>/dev/null) || true
  ADGROUP_ID=$(echo "$ADGROUPS_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
if isinstance(data, list) and data:
    print(data[0].get('Id', ''))
elif isinstance(data, dict):
    groups = data.get('result', {}).get('AdGroups', data.get('AdGroups', []))
    if groups:
        print(groups[0].get('Id', ''))
" 2>/dev/null || true)
fi

echo ""

# Commands that need campaign ID
if [ -n "$CAMPAIGN_ID" ]; then
  run_test "adgroups get (env auth)"      direct adgroups get     --campaign-ids "$CAMPAIGN_ID"
  run_test "ads get (env auth)"           direct ads get          --campaign-ids "$CAMPAIGN_ID"
  run_test "keywords get (env auth)"      direct keywords get     --campaign-ids "$CAMPAIGN_ID"
  run_test "bids get (env auth)"          direct bids get         --campaign-ids "$CAMPAIGN_ID"
  run_test "keywordbids get (env auth)"   direct keywordbids get  --campaign-ids "$CAMPAIGN_ID"
  run_test "bidmodifiers get (env auth)"  direct bidmodifiers get --campaign-ids "$CAMPAIGN_ID"
else
  echo -e "  ${YELLOW}[SKIP]${RESET} adgroups/ads/keywords/bids/keywordbids/bidmodifiers — нет campaign ID"
  FAIL=$((FAIL + 6))
fi

# Commands that need adgroup ID
if [ -n "$ADGROUP_ID" ]; then
  run_test "audiencetargets get (env auth)" direct audiencetargets get --adgroup-ids "$ADGROUP_ID"
else
  echo -e "  ${YELLOW}[SKIP]${RESET} audiencetargets get — нет adgroup ID"
fi

# Commands with no required IDs
run_test "retargeting get (env auth)"              direct retargeting get
run_test "adimages get (env auth)"                 direct adimages get
run_advideos_probe_get
run_test "adextensions get (env auth)"             direct adextensions get
# sitelinks/vcards/feeds/negativekeywordsharedsets require --ids; pass a dummy to verify the API call works
run_test "sitelinks get --ids (env auth)"          direct sitelinks get --ids 1
run_test "vcards get --ids (env auth)"             direct vcards get --ids 1
run_test "leads get --turbo-page-ids (env auth)" direct leads get --turbo-page-ids 1 --limit 1
run_test "clients get (env auth)"                  direct clients get
run_agencyclients_sandbox_get
run_test "feeds get --ids (env auth)"          direct feeds get --ids 1
run_test "creatives get (env auth)"                direct creatives get
# businesses requires Ids/Name/Url in SelectionCriteria
run_test "businesses get --ids (env auth)"         direct businesses get --ids 1 --fields Id,Name,Type
run_test "strategies get (env auth)"               direct strategies get --limit 1 --fields Id,Name,Type,StatusArchived
# turbopages and smartadtargets need correct field names
run_test "turbopages get (env auth)"               direct turbopages get --fields Id,Name,Href
run_test "negativekeywordsharedsets get (env)"     direct negativekeywordsharedsets get --ids 1
run_test "smartadtargets get (env auth)"           direct smartadtargets get --fields Id,AdGroupId,CampaignId
run_test "dynamicfeedadtargets get --ids (env)"    direct dynamicfeedadtargets get --ids 1
run_test "dictionaries list-names (env auth)"      direct dictionaries list-names
run_test "changes check-dictionaries (env auth)"   direct changes check-dictionaries
run_test "reports list-types (env auth)"           direct reports list-types
run_test "reports get (env auth)"                  direct reports get --type campaign_performance_report --from 2026-01-01 --to 2026-01-01 --name "Smoke Safe Report" --fields Date,CampaignId
run_test "balance (env auth)"                      direct balance

if [ -n "$CAMPAIGN_ID" ]; then
  run_test "changes check-campaigns (env auth)"    direct changes check-campaigns --timestamp 2026-04-23T00:00:00
  run_test "dynamicads get (env auth)"             direct dynamicads get --adgroup-ids "${ADGROUP_ID:-0}"
  run_test "v4goals get-stat-goals (env auth)"     direct v4goals get-stat-goals --campaign-ids "$CAMPAIGN_ID"
  run_test "v4goals get-retargeting-goals (env auth)" direct v4goals get-retargeting-goals --campaign-ids "$CAMPAIGN_ID"
else
  echo -e "  ${YELLOW}[SKIP]${RESET} changes check-campaigns / dynamicads get / v4goals — нет campaign ID"
fi

run_test "keywordsresearch has-search-volume (env auth)" direct keywordsresearch has-search-volume --keywords "купить велосипед" --region-ids 213
run_test "keywordsresearch deduplicate (env auth)" direct keywordsresearch deduplicate --keywords "купить велосипед,купить велосипед"

echo ""

# ─── Section B: Auth via CLI flags ───────────────────────────────────────────
echo -e "${BOLD}=== B. Аутентификация через CLI-флаги ===${RESET}"
echo ""

if [ -n "${YANDEX_DIRECT_TOKEN:-}" ]; then
  T="$YANDEX_DIRECT_TOKEN"
  L="${YANDEX_DIRECT_LOGIN:-}"

  run_test "campaigns get (flag auth)"          direct --token "$T" --login "$L" campaigns get
  run_test "clients get (flag auth)"            direct --token "$T" --login "$L" clients get
  run_test "dictionaries list-names (flag auth)" direct --token "$T" --login "$L" dictionaries list-names
  run_test "reports list-types (flag auth)"     direct --token "$T" --login "$L" reports list-types

  if [ -n "$CAMPAIGN_ID" ]; then
    run_test "adgroups get (flag auth)"         direct --token "$T" --login "$L" adgroups get --campaign-ids "$CAMPAIGN_ID"
  fi
else
  echo -e "  ${YELLOW}[SKIP]${RESET} Секция B — нет YANDEX_DIRECT_TOKEN в env (используется auth profile)"
fi

echo ""

# ─── Summary ─────────────────────────────────────────────────────────────────
echo -e "${BOLD}=========================================${RESET}"
TOTAL=$((PASS + FAIL))
if [ "$FAIL" -eq 0 ]; then
  echo -e "${GREEN}Результаты: $PASS/$TOTAL PASS${RESET}"
else
  echo -e "${RED}Результаты: $PASS PASS, $FAIL FAIL (из $TOTAL)${RESET}"
fi
echo -e "${BOLD}=========================================${RESET}"

[ "$FAIL" -eq 0 ] && exit 0 || exit 1
