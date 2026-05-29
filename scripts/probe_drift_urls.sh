#!/usr/bin/env bash
# Ad-hoc probe for the 4 docs URLs that preflight flagged as GONE (#128/#460).
# Classifies each candidate as OK / 404 / CAPTCHA so we can tell a real
# docs move apart from a Yandex SmartCaptcha IP rate-limit.
#
# Exit status: 0 if at least one candidate per resource resolved to a clean
# (non-captcha) status, 3 if any resource is still fully captcha-gated.
# Not wired into CI — manual diagnostic only.
#
# Deliberate exception to the CLAUDE.md "No URL literals outside the registry"
# rule (#426): this script probes *candidate* docs paths that are, by
# definition, NOT yet in the registry — that's the whole point of finding the
# canonical URL. It performs read-only HTTP probes, never writes to any cache,
# and is never imported by tests or CI, so it cannot poison the docs cache.
set -u
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

# Candidate paths per resource, most-likely first.
declare -a RESOURCES=(dynamicads dynamicfeedadtargets smartadtargets vcards)
candidates_for() {
  case "$1" in
    dynamicads)            echo "ru/dynamictextadtargets/dynamictextadtargets ru/dynamicads/dynamicads ru/dynamictextadtargets" ;;
    dynamicfeedadtargets)  echo "ru/dynamicfeedadtargets/dynamicfeedadtargets ru/dynamicfeedadtargets ru/feedadtargets/feedadtargets" ;;
    smartadtargets)        echo "ru/smartadtargets/smartadtargets ru/smartadtargets ru/smartadtargets/smartadtarget" ;;
    vcards)                echo "ru/vcards/vcards ru/vcards ru/vcard/vcard" ;;
  esac
}

classify() {
  local url="$1" code loc size
  code=$(curl -s -o /tmp/drift.html -D /tmp/drift.hdr -w "%{http_code}" -A "$UA" "$url")
  loc=$(grep -i '^location:' /tmp/drift.hdr | tail -1 | tr -d '\r' | awk '{print $2}')
  size=$(wc -c </tmp/drift.html | tr -d ' ')
  if echo "$loc" | grep -qi 'captcha'; then echo "CAPTCHA"
  elif [ "$code" = "200" ] && [ "$size" -gt 30000 ]; then echo "OK"
  elif [ "$code" = "404" ] || [ "$code" = "410" ]; then echo "GONE"
  else echo "$code"; fi
}

echo "=== drift probe $(date -u +%H:%M:%SZ) ==="
any_captcha=0
for res in "${RESOURCES[@]}"; do
  resolved=""
  for path in $(candidates_for "$res"); do
    url="https://yandex.ru/dev/direct/doc/$path"
    status=$(classify "$url")
    printf '  %-24s %-8s %s\n' "$res" "$status" "$url"
    if [ "$status" = "OK" ]; then resolved="$url"; break; fi
    if [ "$status" = "CAPTCHA" ]; then any_captcha=1; fi
  done
  if [ -n "$resolved" ]; then echo "  -> RESOLVED $res: $resolved"; fi
done

if [ "$any_captcha" = "1" ]; then
  echo "STATUS: still captcha-gated on at least one resource"
  exit 3
fi
echo "STATUS: no captcha — results are authoritative"
exit 0
