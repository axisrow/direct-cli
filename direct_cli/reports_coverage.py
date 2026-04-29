"""
Reports API coverage utilities for Direct CLI.

Fetches and parses Yandex Direct Reports API HTML documentation to verify
that the CLI implements all report types, fields, and headers.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .utils import get_docs_pages

_REPORTS_DOCS_PAGES = get_docs_pages("reports")
_REQUIRED_DOCS_KEYS = ("type", "period", "fields-list", "headers")
_missing_docs_keys = [k for k in _REQUIRED_DOCS_KEYS if k not in _REPORTS_DOCS_PAGES]
if _missing_docs_keys:
    raise RuntimeError(
        "reports docs_pages mapping missing required keys "
        f"{_missing_docs_keys}; vendored resource_mapping.py is out of sync"
    )
REPORTS_SPEC_URLS: dict[str, str] = {
    "type": _REPORTS_DOCS_PAGES["type"],
    "period": _REPORTS_DOCS_PAGES["period"],
    "spec": "https://yandex.ru/dev/direct/doc/reports/spec.html",
    "fields-list": _REPORTS_DOCS_PAGES["fields-list"],
    "headers": _REPORTS_DOCS_PAGES["headers"],
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
        "report_definition_fields": {},
        "selection_criteria_fields": {},
        "filter_fields": {},
        "filter_operators": [],
        "order_by_fields": {},
        "order_by_sort_orders": [],
        "attribution_models": [],
        "field_compatibility": {},
        "field_usage": {},
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

    # --- DateRangeType values: regex on period page text ---
    if "period" in raw:
        text = _extract_text(raw["period"])
        found = re.findall(
            r"\b(TODAY|YESTERDAY|THIS_WEEK_MON_TODAY|THIS_WEEK_MON_SUN|"
            r"LAST_WEEK|LAST_BUSINESS_WEEK|LAST_7_DAYS|LAST_14_DAYS|"
            r"LAST_30_DAYS|LAST_3_MONTHS|LAST_5_YEARS|CUSTOM_DATE|ALL_TIME|AUTO|"
            r"LAST_3_DAYS|LAST_5_DAYS|LAST_90_DAYS|LAST_365_DAYS|"
            r"THIS_WEEK_SUN_TODAY|LAST_WEEK_SUN_SAT|THIS_MONTH|LAST_MONTH)\b",
            text,
        )
        for t in found:
            if t not in spec["date_range_types"]:
                spec["date_range_types"].append(t)

    if not spec["date_range_types"]:
        raise ValueError(
            "parse_reports_spec: failed to extract date_range_types from period.html — "
            "page structure may have changed"
        )

    # --- ReportDefinition/SelectionCriteria metadata from spec.html ---
    if "spec" in raw:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw["spec"], "lxml")
        table = soup.find("table")
        section = None
        if table:
            for row in table.find_all("tr"):
                cells = [
                    c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])
                ]
                if len(cells) < 4:
                    continue
                name, type_name, description, required = cells[:4]
                if name.startswith("Структура "):
                    section = name.replace("Структура ", "", 1)
                    continue
                if name == "Параметр" or not name:
                    continue
                entry = {
                    "type": type_name,
                    "required": required == "Да",
                    "description": description,
                }
                if section == "ReportDefinition":
                    spec["report_definition_fields"][name] = entry
                elif section == "SelectionCriteria":
                    spec["selection_criteria_fields"][name] = entry
                elif section == "FilterItem":
                    spec["filter_fields"][name] = entry
                    if name == "Operator":
                        spec["filter_operators"] = sorted(
                            set(
                                re.findall(
                                    r"\b(EQUALS|NOT_EQUALS|IN|NOT_IN|LESS_THAN|"
                                    r"GREATER_THAN|STARTS_WITH_IGNORE_CASE|"
                                    r"DOES_NOT_START_WITH_IGNORE_CASE|"
                                    r"STARTS_WITH_ANY_IGNORE_CASE|"
                                    r"DOES_NOT_START_WITH_ALL_IGNORE_CASE)\b",
                                    description,
                                )
                            )
                        )
                elif section == "OrderBy":
                    spec["order_by_fields"][name] = entry
                    if name == "SortOrder":
                        spec["order_by_sort_orders"] = sorted(
                            set(re.findall(r"\b(ASCENDING|DESCENDING)\b", description))
                        )

        spec["attribution_models"] = sorted(
            set(re.findall(r"\b(FC|LC|LSC|LYDC|FCCD|LSCCD|LYDCCD|AUTO)\b", raw["spec"]))
        )

    required_report_fields = {"SelectionCriteria", "Goals", "AttributionModels"}
    if not required_report_fields <= set(spec["report_definition_fields"]):
        raise ValueError(
            "parse_reports_spec: failed to extract ReportDefinition fields from "
            "spec.html — page structure may have changed"
        )
    if not spec["filter_operators"]:
        raise ValueError(
            "parse_reports_spec: failed to extract FilterOperatorEnum from "
            "spec.html — page structure may have changed"
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
                header_rows = []
                for row in rows[:3]:
                    cells = [
                        c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])
                    ]
                    if cells and "Имя поля" in cells:
                        header_rows.append(cells)
                        break
                if not header_rows:
                    raise ValueError("fields-list table header row not found")
                cols = header_rows[0]
                usage_cols = cols[1:4]
                report_type_cols = cols[4:]
                for row in rows[2:]:
                    cells = row.find_all(["td", "th"])
                    if not cells:
                        continue
                    values = [c.get_text(" ", strip=True) for c in cells]
                    field_name = values[0]
                    # Skip header rows and non-ASCII field names
                    if (
                        not field_name
                        or not field_name.isascii()
                        or field_name == "Имя поля"
                    ):
                        continue
                    entry: dict = {"report_types": {}}
                    usage = {}
                    for i, col in enumerate(usage_cols, start=1):
                        marker = values[i] if i < len(values) else ""
                        usage[col] = marker == "+"
                    spec["field_usage"][field_name] = usage
                    for i, rt in enumerate(report_type_cols):
                        cell_index = i + 4
                        if cell_index < len(values):
                            role = values[cell_index].lower()
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

    try:
        spec = parse_reports_spec(raw)
    except Exception as exc:
        return {"parse": exc}

    spec_file = REPORTS_CACHE_DIR / "spec.json"
    try:
        spec_file.write_text(
            json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as exc:
        return {"write": exc}

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
