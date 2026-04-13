"""
Reports API coverage utilities for Direct CLI.

Fetches and parses Yandex Direct Reports API HTML documentation to verify
that the CLI implements all report types, fields, and headers.
"""

from __future__ import annotations

import json
from pathlib import Path

REPORTS_SPEC_URLS: dict[str, str] = {
    "spec": "https://yandex.com/dev/direct/doc/en/reports/spec",
    "type": "https://yandex.com/dev/direct/doc/en/reports/type",
    "fields-list": "https://yandex.com/dev/direct/doc/en/reports/fields-list",
    "headers": "https://yandex.com/dev/direct/doc/en/reports/headers",
}

REPORTS_CACHE_DIR = Path(__file__).resolve().parent.parent / "tests" / "reports_cache"


def fetch_reports_spec(use_cache: bool = True) -> dict[str, str]:
    """Fetch HTML for each Reports spec URL.

    Args:
        use_cache: If True, read from tests/reports_cache/raw/*.html when available.

    Returns:
        Dict mapping source key (e.g. "spec", "type") to HTML string.
    """
    import requests

    raw_dir = REPORTS_CACHE_DIR / "raw"
    result: dict[str, str] = {}

    for key, url in REPORTS_SPEC_URLS.items():
        cache_file = raw_dir / f"{key}.html"
        if use_cache and cache_file.exists():
            result[key] = cache_file.read_text(encoding="utf-8")
            continue

        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        html = resp.text

        raw_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(html, encoding="utf-8")
        result[key] = html

    return result


def load_cached_reports_spec() -> dict:
    """Load the canonical spec snapshot from tests/reports_cache/spec.json."""
    spec_file = REPORTS_CACHE_DIR / "spec.json"
    return json.loads(spec_file.read_text(encoding="utf-8"))
