#!/usr/bin/env python3
"""Refresh cached WSDL files for all Yandex Direct API v5 services.

Usage:
    python scripts/refresh_wsdl_cache.py

Fetches fresh WSDL XML from https://api.direct.yandex.com/v5/{service}?wsdl
and overwrites files in tests/wsdl_cache/.

Run periodically (e.g. monthly) or when suspecting the API has changed.
"""

import sys
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from direct_cli.wsdl_coverage import refresh_all_caches, CANONICAL_API_SERVICES


def main():
    print(f"Refreshing WSDL cache for {len(CANONICAL_API_SERVICES)} services...")
    errors = refresh_all_caches()

    if errors:
        print("\nFailed services:")
        for service, exc in sorted(errors.items()):
            print(f"  {service}: {exc}")
        print(f"\n{len(CANONICAL_API_SERVICES) - len(errors)} succeeded, {len(errors)} failed.")
        sys.exit(1)
    else:
        print(f"All {len(CANONICAL_API_SERVICES)} services refreshed successfully.")


if __name__ == "__main__":
    main()
