#!/usr/bin/env bash
# Test all read-only (safe) direct-cli commands against the real Yandex Direct API.
# Usage: ./scripts/test_safe_commands.sh
# Requires .env with YANDEX_DIRECT_TOKEN and YANDEX_DIRECT_LOGIN in project root.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$ROOT_DIR/.env"

PASS=0
FAIL=0
KNOWN=0
CAMPAIGN_ID=""
ADGROUP_ID=""

# ─── Colors ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

# ─── Load .env ────────────────────────────────────────────────────────────────
if [ -f "$ENV_FILE" ]; then
  set +u
  # shellcheck disable=SC2046
  export $(grep -v '^#' "$ENV_FILE" | grep -v '^$' | xargs)
  set -u
fi

if [ -z "${YANDEX_DIRECT_TOKEN:-}" ] || [ -z "${YANDEX_DIRECT_LOGIN:-}" ]; then
  echo -e "${RED}ERROR:${RESET} YANDEX_DIRECT_TOKEN and YANDEX_DIRECT_LOGIN must be set."
  echo "       Put them in .env or export them before running this script."
  exit 1
fi

echo -e "${BOLD}direct-cli safe commands test${RESET}"
echo "Login: $YANDEX_DIRECT_LOGIN"
echo "Token: ${YANDEX_DIRECT_TOKEN:0:8}..."
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

# Known-bug skip: prints [BUG #N] and counts separately, does not affect FAIL
skip_bug() {
  local issue="$1"
  local name="$2"
  echo -e "  ${CYAN}[BUG #$issue]${RESET} $name — см. github.com/axisrow/direct-cli/issues/$issue"
  ((KNOWN++)) || true
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
run_test "adextensions get (env auth)"             direct adextensions get
# sitelinks/vcards/feeds/negativekeywordsharedsets require --ids; pass a dummy to verify the API call works
run_test "sitelinks get --ids (env auth)"          direct sitelinks get --ids 1
run_test "vcards get --ids (env auth)"             direct vcards get --ids 1
run_test "leads get --turbo-page-ids (env auth)" direct leads get --turbo-page-ids 1 --limit 1
run_test "clients get (env auth)"                  direct clients get
# agencyclients requires agency account — tracked in #73
echo -e "  ${CYAN}[BUG #73]${RESET} agencyclients get — требует агентский аккаунт (sandbox)"
((KNOWN++)) || true
run_test "feeds get --ids (env auth)"          direct feeds get --ids 1
run_test "creatives get (env auth)"                direct creatives get
# businesses requires Ids/Name/Url in SelectionCriteria
run_test "businesses get --ids (env auth)"         direct businesses get --ids 1 --fields Id,Name,Type
# turbopages and smartadtargets need correct field names
run_test "turbopages get (env auth)"               direct turbopages get --fields Id,Name,Href
run_test "negativekeywordsharedsets get (env)"     direct negativekeywordsharedsets get --ids 1
run_test "smartadtargets get (env auth)"           direct smartadtargets get --fields Id,AdGroupId,CampaignId
run_test "dictionaries list-names (env auth)"      direct dictionaries list-names
run_test "changes check-dictionaries (env auth)"   direct changes check-dictionaries
run_test "reports list-types (env auth)"           direct reports list-types

if [ -n "$CAMPAIGN_ID" ]; then
  run_test "changes check-campaigns (env auth)"    direct changes check-campaigns --timestamp 2026-04-23T00:00:00
  run_test "dynamicads get (env auth)"             direct dynamicads get --adgroup-ids "${ADGROUP_ID:-0}"
else
  echo -e "  ${YELLOW}[SKIP]${RESET} changes check-campaigns / dynamicads get — нет campaign ID"
fi

run_test "keywordsresearch has-search-volume (env auth)" direct keywordsresearch has-search-volume --keywords "купить велосипед" --region-ids 213

echo ""

# ─── Section B: Auth via CLI flags ───────────────────────────────────────────
echo -e "${BOLD}=== B. Аутентификация через CLI-флаги ===${RESET}"
echo ""

T="$YANDEX_DIRECT_TOKEN"
L="$YANDEX_DIRECT_LOGIN"

run_test "campaigns get (flag auth)"          direct --token "$T" --login "$L" campaigns get
run_test "clients get (flag auth)"            direct --token "$T" --login "$L" clients get
run_test "dictionaries list-names (flag auth)" direct --token "$T" --login "$L" dictionaries list-names
run_test "reports list-types (flag auth)"     direct --token "$T" --login "$L" reports list-types

if [ -n "$CAMPAIGN_ID" ]; then
  run_test "adgroups get (flag auth)"         direct --token "$T" --login "$L" adgroups get --campaign-ids "$CAMPAIGN_ID"
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
if [ "$KNOWN" -gt 0 ]; then
  echo -e "${CYAN}Пропущено (known bugs): $KNOWN${RESET}"
fi
echo -e "${BOLD}=========================================${RESET}"

[ "$FAIL" -eq 0 ] && exit 0 || exit 1
