#!/usr/bin/env python3
"""Measure live SelectionCriteria array caps for read-get commands (#571).

For each (command, flag) pair, probes at N=10/100/1000/10000 and records the
largest N that ``direct --sandbox --profile default <cmd> get --<flag>
"1,2,...,N" --limit 1`` accepts. Synthetic IDs are sufficient — the API
checks array length before existence (confirmed on prod ads.get).

**Manual tool, not part of CI.** Re-run only when Yandex Direct is suspected
of changing a cap, then update the matching ``*_GET_CRITERIA_LIMITS``
constant + its docstring transcript. Constants in command modules are the
source of truth; this script and its JSON output are scratch.

Usage:
    python scripts/measure_criteria_limits.py             # all targets
    python scripts/measure_criteria_limits.py campaigns   # one command
    python scripts/measure_criteria_limits.py ads --flag campaign-ids

Output: writes scripts/_criteria_limits_results.json incrementally so re-runs
resume after rate limits. Cap=null in the JSON means "accepted at N=10000 —
treat as uncapped".
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

RESULTS_PATH = Path(__file__).parent / "_criteria_limits_results.json"
SLEEP_BETWEEN_CALLS = 1.0
# Operator's `direct auth` profile to drive the sandbox from. Override via
# YANDEX_DIRECT_MEASURE_PROFILE if the operator has no profile literally named
# "default" (else `direct` errors out before the first probe).
SANDBOX_PROFILE = os.environ.get("YANDEX_DIRECT_MEASURE_PROFILE", "default")

# (command, flag, criteria_key). Order: cheapest first.
TARGETS = [
    ("campaigns", "ids", "Ids"),
    ("strategies", "ids", "Ids"),
    ("sitelinks", "ids", "Ids"),
    ("vcards", "ids", "Ids"),
    ("adextensions", "ids", "Ids"),
    ("bids", "campaign-ids", "CampaignIds"),
    ("bids", "adgroup-ids", "AdGroupIds"),
    ("bids", "keyword-ids", "KeywordIds"),
    ("bidmodifiers", "ids", "Ids"),
    ("bidmodifiers", "campaign-ids", "CampaignIds"),
    ("bidmodifiers", "adgroup-ids", "AdGroupIds"),
    ("keywords", "ids", "Ids"),
    ("keywords", "campaign-ids", "CampaignIds"),
    ("keywords", "adgroup-ids", "AdGroupIds"),
    ("dynamicfeedadtargets", "ids", "Ids"),
    ("dynamicfeedadtargets", "campaign-ids", "CampaignIds"),
    ("dynamicfeedadtargets", "adgroup-ids", "AdGroupIds"),
    ("audiencetargets", "ids", "Ids"),
    ("audiencetargets", "campaign-ids", "CampaignIds"),
    ("audiencetargets", "adgroup-ids", "AdGroupIds"),
    ("audiencetargets", "retargeting-list-ids", "RetargetingListIds"),
    ("audiencetargets", "interest-ids", "InterestIds"),
    ("ads", "ids", "Ids"),
    ("ads", "campaign-ids", "CampaignIds"),
    ("ads", "adgroup-ids", "AdGroupIds"),
    ("ads", "vcard-ids", "VCardIds"),
    ("ads", "sitelink-set-ids", "SitelinkSetIds"),
    ("ads", "ad-extension-ids", "AdExtensionIds"),
    ("adgroups", "ids", "Ids"),
    ("adgroups", "campaign-ids", "CampaignIds"),
    ("adgroups", "tag-ids", "TagIds"),
    ("adgroups", "negative-keyword-shared-set-ids", "NegativeKeywordSharedSetIds"),
]


def load_results() -> dict:
    if RESULTS_PATH.exists():
        return json.loads(RESULTS_PATH.read_text())
    return {}


def save_results(results: dict) -> None:
    RESULTS_PATH.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")


def call_api(cmd: str, flag: str, n: int) -> tuple[bool, str]:
    """Return (accepted, stderr_tail). accepted=False iff 4001 detected."""
    ids = ",".join(str(i) for i in range(1, n + 1))
    proc = subprocess.run(
        [
            "direct",
            "--sandbox",
            "--profile",
            SANDBOX_PROFILE,
            cmd,
            "get",
            f"--{flag}",
            ids,
            "--limit",
            "1",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    combined = (proc.stdout + proc.stderr).strip()
    is_4001 = "error_code=4001" in combined
    return (not is_4001, combined[-200:])


def measure(cmd: str, flag: str) -> dict:
    """Probe at 10/100/1000/10000. Cap = highest accepted N.

    No binary refinement: Yandex documents only round-power caps, and the
    constant only needs the conservative ceiling we can prove. If 10000
    accepted, treat as uncapped.
    """
    print(f"  Probing {cmd} --{flag}...", flush=True)
    probes = [10, 100, 1000, 10000]
    last_accept = 0
    first_reject = None
    transcript_lines = []
    for n in probes:
        accepted, _ = call_api(cmd, flag, n)
        verdict = "OK" if accepted else "4001"
        transcript_lines.append(f"N={n} -> {verdict}")
        print(f"    N={n} -> {verdict}", flush=True)
        time.sleep(SLEEP_BETWEEN_CALLS)
        if accepted:
            last_accept = n
        else:
            first_reject = n
            break
    transcript = "; ".join(transcript_lines)
    if first_reject is None:
        return {
            "cap": None,
            "status": "uncapped",
            "transcript": transcript + " (accepted at N=10000)",
        }
    if last_accept == 0:
        # N=10 rejected → real cap is in [1, 9]. Refine with N=2, N=5 to
        # bracket. Live-needed: dynamicfeedadtargets.CampaignIds caps at 2
        # (matches dynamicads/smartadtargets from #555).
        for n in (2, 5):
            accepted, _ = call_api(cmd, flag, n)
            verdict = "OK" if accepted else "4001"
            transcript_lines.append(f"N={n} -> {verdict}")
            print(f"    refine N={n} -> {verdict}", flush=True)
            time.sleep(SLEEP_BETWEEN_CALLS)
            if accepted:
                last_accept = n
            else:
                first_reject = n
                break
        transcript = "; ".join(transcript_lines)
    return {
        "cap": last_accept,
        "status": "capped",
        "transcript": transcript,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", nargs="?", help="Limit to one command")
    ap.add_argument("--flag", help="With --command, limit to one flag")
    ap.add_argument("--force", action="store_true", help="Re-measure even if cached")
    args = ap.parse_args()

    results = load_results()
    selected = TARGETS
    if args.command:
        selected = [t for t in selected if t[0] == args.command]
        if args.flag:
            selected = [t for t in selected if t[1] == args.flag]
    if not selected:
        print("No targets matched.", file=sys.stderr)
        return 2

    for cmd, flag, criteria_key in selected:
        key = f"{cmd}.{criteria_key}"
        if not args.force and key in results:
            print(f"[skip cached] {key} -> {results[key].get('cap')}")
            continue
        print(f"[measure] {key}")
        # Catch-all is intentional: subprocess/timeout/parse failures must
        # not abort the whole sweep — record and continue.
        try:
            result = measure(cmd, flag)
        except Exception as exc:  # noqa: PIE786
            result = {"cap": None, "status": "error", "transcript": str(exc)}
        results[key] = {
            "command": cmd,
            "flag": flag,
            "criteria_key": criteria_key,
            **result,
        }
        save_results(results)
        print(
            f"  -> cap={result.get('cap')} status={result.get('status')}",
            flush=True,
        )
    print(f"\nResults saved to {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
