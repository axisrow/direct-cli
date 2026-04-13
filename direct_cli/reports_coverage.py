"""
Reports API coverage utilities for Direct CLI.

Fetches and parses Yandex Direct Reports API HTML documentation to verify
that the CLI implements all report types, fields, and headers.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Real working URLs (yandex.ru, static HTML with content in page text)
REPORTS_SPEC_URLS: dict[str, str] = {
    "type": "https://yandex.ru/dev/direct/doc/reports/type.html",
    "spec": "https://yandex.ru/dev/direct/doc/reports/period.html",
    "fields-list": "https://yandex.ru/dev/direct/doc/reports/fields-list.html",
    "headers": "https://yandex.ru/dev/direct/doc/reports/headers.html",
}

REPORTS_CACHE_DIR = Path(__file__).resolve().parent.parent / "tests" / "reports_cache"


def fetch_reports_spec(use_cache: bool = True) -> dict[str, str]:
    """Fetch HTML for each Reports spec URL.

    Args:
        use_cache: If True, read from tests/reports_cache/raw/*.html when available.

    Returns:
        Dict mapping source key to HTML string.
    """
    import requests

    raw_dir = REPORTS_CACHE_DIR / "raw"
    result: dict[str, str] = {}

    headers = {"User-Agent": "Mozilla/5.0"}
    for key, url in REPORTS_SPEC_URLS.items():
        cache_file = raw_dir / f"{key}.html"
        if use_cache and cache_file.exists():
            result[key] = cache_file.read_text(encoding="utf-8")
            continue

        resp = requests.get(url, timeout=30, headers=headers)
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


def _extract_text(html: str) -> str:
    """Strip HTML tags and return plain text."""
    from bs4 import BeautifulSoup

    return BeautifulSoup(html, "lxml").get_text(" ", strip=True)


def parse_reports_spec(raw: dict[str, str]) -> dict:
    """Parse raw HTML into a canonical spec snapshot.

    Raises:
        ValueError: if required sections cannot be extracted from the HTML.
    """
    spec: dict = {
        "report_types": [],
        "date_range_types": [],
        "formats": ["TSV"],
        "processing_modes": [],
        "request_headers": {},
        "field_compatibility": {},
    }

    # --- Report types: regex on raw HTML ---
    if "type" in raw:
        found = re.findall(
            r"\b([A-Z][A-Z_]{5,}(?:_REPORT|_PERFORMANCE_REPORT))\b",
            raw["type"],
        )
        for t in found:
            if t not in spec["report_types"]:
                spec["report_types"].append(t)

    if not spec["report_types"]:
        raise ValueError(
            "parse_reports_spec: failed to extract report_types from type.html — "
            "page structure may have changed"
        )

    # --- DateRangeType values: regex on page text ---
    if "spec" in raw:
        text = _extract_text(raw["spec"])
        found = re.findall(
            r"\b(TODAY|YESTERDAY|THIS_WEEK_MON_TODAY|THIS_WEEK_MON_SUN|"
            r"LAST_WEEK|LAST_BUSINESS_WEEK|LAST_7_DAYS|LAST_14_DAYS|"
            r"LAST_30_DAYS|LAST_3_MONTHS|LAST_5_YEARS|CUSTOM_DATE|ALL_TIME|AUTO)\b",
            text,
        )
        for t in found:
            if t not in spec["date_range_types"]:
                spec["date_range_types"].append(t)

    if not spec["date_range_types"]:
        raise ValueError(
            "parse_reports_spec: failed to extract date_range_types from spec.html — "
            "page structure may have changed"
        )

    # --- Processing modes: regex on headers page text ---
    if "headers" in raw:
        text = _extract_text(raw["headers"])
        for mode in ("auto", "online", "offline"):
            if re.search(rf"\b{mode}\b", text, re.IGNORECASE):
                if mode not in spec["processing_modes"]:
                    spec["processing_modes"].append(mode)

    if not spec["processing_modes"]:
        raise ValueError(
            "parse_reports_spec: failed to extract processing_modes from "
            "headers.html — page structure may have changed"
        )

    # --- Request headers: scan headers.html text for known header names ---
    if "headers" in raw:
        text = _extract_text(raw["headers"])
        header_map = {
            "processingMode": {"required": True, "values": spec["processing_modes"]},
            "skipReportHeader": {"required": False, "values": ["true", "false"]},
            "skipColumnHeader": {"required": False, "values": ["true", "false"]},
            "skipReportSummary": {"required": False, "values": ["true", "false"]},
            "returnMoneyInMicros": {"required": False, "values": ["true", "false"]},
            "Accept-Language": {"required": False, "values": ["ru", "en"]},
        }
        for key, meta in header_map.items():
            if key in text:
                spec["request_headers"][key] = meta

    if not spec["request_headers"]:
        raise ValueError(
            "parse_reports_spec: failed to extract request_headers from headers.html — "
            "page structure may have changed"
        )

    # --- Field compatibility: parse table from fields-list.html ---
    if "fields-list" in raw:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw["fields-list"], "lxml")
        table = soup.find("table")
        if table:
            rows = table.find_all("tr")
            if rows:
                header_cells = rows[0].find_all(["th", "td"])
                cols = [c.get_text(strip=True) for c in header_cells]
                report_type_cols = cols[1:]
                for row in rows[1:]:
                    cells = row.find_all(["td", "th"])
                    if not cells:
                        continue
                    field_name = cells[0].get_text(strip=True)
                    # Skip header rows and non-ASCII field names
                    if not field_name or not field_name.isascii():
                        continue
                    entry: dict = {"report_types": {}}
                    for i, rt in enumerate(report_type_cols):
                        if i + 1 < len(cells):
                            role = cells[i + 1].get_text(strip=True).lower()
                            if role and role not in ("—", "-", ""):
                                entry["report_types"][rt] = role
                    if entry["report_types"]:
                        spec["field_compatibility"][field_name] = entry

    if not spec["field_compatibility"]:
        raise ValueError(
            "parse_reports_spec: failed to extract field_compatibility from "
            "fields-list.html — page structure may have changed"
        )

    return spec


def refresh_reports_cache() -> dict[str, Exception]:
    """Fetch live HTML, update raw cache files, and save spec.json."""
    errors: dict[str, Exception] = {}
    try:
        raw = fetch_reports_spec(use_cache=False)
    except Exception as exc:
        return {"fetch": exc}

    spec = parse_reports_spec(raw)

    spec_file = REPORTS_CACHE_DIR / "spec.json"
    spec_file.write_text(
        json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return errors


def get_reports_coverage_policy() -> dict:
    """Return a machine-readable summary of the Reports coverage model."""
    try:
        spec = load_cached_reports_spec()
        report_types_count = len(spec.get("report_types", []))
        field_count = len(spec.get("field_compatibility", {}))
        header_count = len(spec.get("request_headers", {}))
    except Exception:
        report_types_count = 0
        field_count = 0
        header_count = 0

    return {
        "kind": "json-api",
        "coverage": "contract-tests+spec-snapshot",
        "spec_snapshot": "tests/reports_cache/spec.json",
        "raw_sources": "tests/reports_cache/raw/",
        "drift_script": "scripts/check_reports_drift.py",
        "refresh_script": "scripts/refresh_reports_cache.py",
        "spec_urls": REPORTS_SPEC_URLS,
        "summary": {
            "report_types": report_types_count,
            "fields": field_count,
            "headers": header_count,
        },
    }
