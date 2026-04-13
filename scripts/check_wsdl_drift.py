#!/usr/bin/env python3
"""Compare cached WSDL files with the live Yandex Direct API."""

from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from direct_cli.wsdl_coverage import CANONICAL_API_SERVICES, CACHE_DIR, fetch_wsdl


def main() -> int:
    drift = []
    missing_cache = []

    for service in CANONICAL_API_SERVICES:
        cache_file = CACHE_DIR / f"{service}.xml"
        if not cache_file.exists():
            missing_cache.append(
                {
                    "service": service,
                    "cache_path": str(cache_file),
                }
            )
            continue
        cached = cache_file.read_text(encoding="utf-8")
        live = fetch_wsdl(service, use_cache=False)
        if cached != live:
            diff = list(
                difflib.unified_diff(
                    cached.splitlines(),
                    live.splitlines(),
                    fromfile=f"cached/{service}.xml",
                    tofile=f"live/{service}.xml",
                    lineterm="",
                )
            )
            drift.append(
                {
                    "service": service,
                    "cache_path": str(cache_file),
                    "diff_preview": diff[:50],
                }
            )

    report = {
        "services_checked": len(CANONICAL_API_SERVICES),
        "missing_cache_count": len(missing_cache),
        "missing_cache": missing_cache,
        "drift_count": len(drift),
        "drift": drift,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if (drift or missing_cache) else 0


if __name__ == "__main__":
    raise SystemExit(main())
