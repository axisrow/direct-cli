#!/usr/bin/env python3
"""Compare cached WSDL files with the live Yandex Direct API."""

from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from direct_cli.wsdl_coverage import (
    CACHE_DIR,
    CANONICAL_API_SERVICES,
    IMPORTED_XSD_REGISTRY,
    fetch_imported_xsd,
    fetch_wsdl,
)


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

    xsd_drift = []
    xsd_missing_cache = []
    for namespace, filename in sorted(IMPORTED_XSD_REGISTRY.items()):
        cache_file = CACHE_DIR / "imports" / filename
        if not cache_file.exists():
            xsd_missing_cache.append(
                {
                    "namespace": namespace,
                    "cache_path": str(cache_file),
                }
            )
            continue
        cached = cache_file.read_text(encoding="utf-8")
        live = fetch_imported_xsd(namespace, use_cache=False)
        if cached != live:
            diff = list(
                difflib.unified_diff(
                    cached.splitlines(),
                    live.splitlines(),
                    fromfile=f"cached/imports/{filename}",
                    tofile=f"live/imports/{filename}",
                    lineterm="",
                )
            )
            xsd_drift.append(
                {
                    "namespace": namespace,
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
        "imported_xsd_checked": len(IMPORTED_XSD_REGISTRY),
        "imported_xsd_missing_cache_count": len(xsd_missing_cache),
        "imported_xsd_missing_cache": xsd_missing_cache,
        "imported_xsd_drift_count": len(xsd_drift),
        "imported_xsd_drift": xsd_drift,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return (
        1
        if (drift or missing_cache or xsd_drift or xsd_missing_cache)
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
