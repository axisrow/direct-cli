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


def parse_reports_spec(raw: dict[str, str]) -> dict:
    """Parse raw HTML into a canonical spec snapshot."""
    from bs4 import BeautifulSoup

    spec: dict = {
        "report_types": [],
        "date_range_types": [],
        "formats": ["TSV"],
        "processing_modes": [],
        "request_headers": {},
        "field_compatibility": {},
    }

    # --- Parse report types from type.html ---
    if "type" in raw:
        soup = BeautifulSoup(raw["type"], "lxml")
        for code in soup.find_all("code"):
            text = code.get_text(strip=True)
            if text.isupper() and "_REPORT" in text:
                if text not in spec["report_types"]:
                    spec["report_types"].append(text)

    # --- Parse date_range_types and processing_modes from spec.html ---
    if "spec" in raw:
        soup = BeautifulSoup(raw["spec"], "lxml")
        in_date_range = False
        in_processing = False
        for tag in soup.find_all(["h2", "h3", "h4", "code", "td"]):
            text = tag.get_text(strip=True)
            if "DateRangeType" in text:
                in_date_range = True
                in_processing = False
            elif "ProcessingMode" in text:
                in_processing = True
                in_date_range = False
            elif tag.name == "code" and in_date_range:
                val = text.strip()
                if val.isupper() and val and val not in spec["date_range_types"]:
                    spec["date_range_types"].append(val)
            elif tag.name == "code" and in_processing:
                val = text.strip().lower()
                if (
                    val in ("auto", "online", "offline")
                    and val not in spec["processing_modes"]
                ):
                    spec["processing_modes"].append(val)

    # Fallback: hardcoded canonical values if parse found nothing
    if not spec["date_range_types"]:
        spec["date_range_types"] = [
            "TODAY",
            "YESTERDAY",
            "THIS_WEEK_MON_TODAY",
            "THIS_WEEK_MON_SUN",
            "LAST_WEEK",
            "LAST_BUSINESS_WEEK",
            "LAST_14_DAYS",
            "LAST_30_DAYS",
            "LAST_3_MONTHS",
            "LAST_5_YEARS",
            "CUSTOM_DATE",
            "ALL_TIME",
            "AUTO",
        ]
    if not spec["processing_modes"]:
        spec["processing_modes"] = ["auto", "online", "offline"]

    # --- Parse request_headers from headers.html ---
    if "headers" in raw:
        soup = BeautifulSoup(raw["headers"], "lxml")
        header_map = {
            "processingMode": {"required": True, "values": spec["processing_modes"]},
            "skipReportHeader": {"required": False, "values": ["true", "false"]},
            "skipColumnHeader": {"required": False, "values": ["true", "false"]},
            "skipReportSummary": {"required": False, "values": ["true", "false"]},
            "returnMoneyInMicros": {"required": False, "values": ["true", "false"]},
            "Accept-Language": {"required": False, "values": ["ru", "en"]},
        }
        body_text = soup.get_text()
        for key in list(header_map.keys()):
            if key in body_text:
                spec["request_headers"][key] = header_map[key]
        if not spec["request_headers"]:
            spec["request_headers"] = header_map

    # --- Parse field_compatibility from fields-list.html ---
    if "fields-list" in raw:
        soup = BeautifulSoup(raw["fields-list"], "lxml")
        table = soup.find("table")
        if table:
            headers_row = table.find("tr")
            if headers_row:
                cols = [
                    th.get_text(strip=True) for th in headers_row.find_all(["th", "td"])
                ]
                report_type_cols = cols[1:]
                for row in table.find_all("tr")[1:]:
                    cells = row.find_all(["td", "th"])
                    if not cells:
                        continue
                    field_name = cells[0].get_text(strip=True)
                    if not field_name:
                        continue
                    entry: dict = {"report_types": {}}
                    for i, rt in enumerate(report_type_cols):
                        if i + 1 < len(cells):
                            role = cells[i + 1].get_text(strip=True).lower()
                            if role and role != "—" and role != "-":
                                entry["report_types"][rt] = role
                    if entry["report_types"]:
                        spec["field_compatibility"][field_name] = entry

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
