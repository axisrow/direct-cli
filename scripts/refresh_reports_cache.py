#!/usr/bin/env python3
"""Refresh cached Reports spec files from Yandex Direct documentation.

Usage:
    python scripts/refresh_reports_cache.py

Fetches fresh HTML from Yandex Direct Reports documentation pages and
overwrites files in tests/reports_cache/raw/. Also regenerates spec.json.

Run manually when refreshing the committed cache after the scheduled
reports drift monitor reports a live API change, or when intentionally
updating the cached fixtures.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from direct_cli.reports_coverage import REPORTS_SPEC_URLS, refresh_reports_cache


def main() -> int:
    print(f"Refreshing Reports spec cache for {len(REPORTS_SPEC_URLS)} sources...")
    errors = refresh_reports_cache()

    if errors:
        print("\nFailed sources:")
        for source, exc in sorted(errors.items()):
            print(f"  {source}: {exc}")
        succeeded = len(REPORTS_SPEC_URLS) - len(errors)
        print(f"\n{succeeded} succeeded, {len(errors)} failed.")
        return 1
    else:
        print(f"All {len(REPORTS_SPEC_URLS)} sources refreshed successfully.")
        print("spec.json updated.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
