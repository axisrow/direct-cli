#!/usr/bin/env python3
"""Compare cached Reports spec with live Yandex Direct documentation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from direct_cli.reports_coverage import (
    fetch_reports_spec,
    load_cached_reports_spec,
    parse_reports_spec,
)


def _load_cached() -> dict:
    """Load the committed spec.json snapshot."""
    return load_cached_reports_spec()


def _fetch_live() -> dict:
    """Fetch and parse the live documentation."""
    raw = fetch_reports_spec(use_cache=False)
    return parse_reports_spec(raw)


def _diff_list(section: str, cached: list, live: list) -> list:
    """Return drift entries for a list section."""
    cached_set = set(cached)
    live_set = set(live)
    added = sorted(live_set - cached_set)
    removed = sorted(cached_set - live_set)
    if added or removed:
        return [{"section": section, "added": added, "removed": removed}]
    return []


def _diff_field_compatibility(cached: dict, live: dict) -> list:
    """Return drift entries for field_compatibility."""
    drifts = []
    all_fields = set(cached) | set(live)
    for field in sorted(all_fields):
        c_entry = cached.get(field, {}).get("report_types", {})
        l_entry = live.get(field, {}).get("report_types", {})
        if c_entry != l_entry:
            all_rts = set(c_entry) | set(l_entry)
            changed = {}
            for rt in sorted(all_rts):
                c_role = c_entry.get(rt)
                l_role = l_entry.get(rt)
                if c_role != l_role:
                    changed[rt] = {"cached": c_role, "live": l_role}
            if changed:
                drifts.append({
                    "section": f"field_compatibility.{field}",
                    "changed": changed,
                })
    return drifts


def compute_drift(cached: dict, live: dict) -> dict:
    """Compare two spec dicts and return a drift report."""
    drift = []

    for list_key in ("report_types", "date_range_types", "formats", "processing_modes"):
        drift.extend(_diff_list(list_key, cached.get(list_key, []), live.get(list_key, [])))

    drift.extend(
        _diff_field_compatibility(
            cached.get("field_compatibility", {}),
            live.get("field_compatibility", {}),
        )
    )

    return {
        "sources_checked": len(live),
        "missing_cache_count": 0,
        "drift_count": len(drift),
        "drift": drift,
    }


def main() -> int:
    try:
        cached = _load_cached()
    except Exception as exc:
        print(json.dumps({"error": f"Cannot load cached spec: {exc}"}, indent=2))
        return 1

    try:
        live = _fetch_live()
    except Exception as exc:
        print(json.dumps({"error": f"Cannot fetch live spec: {exc}"}, indent=2))
        return 1

    report = compute_drift(cached, live)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if report["drift_count"] > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
