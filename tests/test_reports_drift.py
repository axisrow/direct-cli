"""
Offline unit tests for check_reports_drift.py drift detection logic.
No network access — uses inline fixtures.
"""

import sys
from pathlib import Path

import pytest

# Allow importing the script module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def test_drift_detects_added_report_type():
    """Drift script must detect a new report type added to live docs."""
    import check_reports_drift as drift_module

    cached_spec = {
        "report_types": ["CAMPAIGN_PERFORMANCE_REPORT"],
        "date_range_types": ["TODAY"],
        "formats": ["TSV"],
        "processing_modes": ["auto"],
        "request_headers": {},
        "field_compatibility": {},
    }
    live_spec = {
        **cached_spec,
        "report_types": ["CAMPAIGN_PERFORMANCE_REPORT", "NEW_REPORT_TYPE"],
    }

    report = drift_module.compute_drift(cached_spec, live_spec)
    assert report["drift_count"] > 0
    sections = {d["section"] for d in report["drift"]}
    assert "report_types" in sections
    added = next(d for d in report["drift"] if d["section"] == "report_types")
    assert "NEW_REPORT_TYPE" in added["added"]


def test_drift_detects_removed_report_type():
    """Drift script must detect a report type removed from live docs."""
    import check_reports_drift as drift_module

    cached_spec = {
        "report_types": ["CAMPAIGN_PERFORMANCE_REPORT", "OLD_REPORT_TYPE"],
        "date_range_types": [],
        "formats": ["TSV"],
        "processing_modes": [],
        "request_headers": {},
        "field_compatibility": {},
    }
    live_spec = {
        **cached_spec,
        "report_types": ["CAMPAIGN_PERFORMANCE_REPORT"],
    }
    report = drift_module.compute_drift(cached_spec, live_spec)
    assert report["drift_count"] > 0
    removed_entry = next(d for d in report["drift"] if d["section"] == "report_types")
    assert "OLD_REPORT_TYPE" in removed_entry["removed"]


def test_no_drift_when_specs_match():
    """Drift script returns drift_count=0 when cached equals live."""
    import check_reports_drift as drift_module

    spec = {
        "report_types": ["CAMPAIGN_PERFORMANCE_REPORT"],
        "date_range_types": ["TODAY"],
        "formats": ["TSV"],
        "processing_modes": ["auto"],
        "request_headers": {"processingMode": {"required": True, "values": ["auto"]}},
        "field_compatibility": {"Clicks": {"report_types": {"CAMPAIGN_PERFORMANCE_REPORT": "metric"}}},
    }
    report = drift_module.compute_drift(spec, spec)
    assert report["drift_count"] == 0
    assert report["drift"] == []


def test_drift_detects_changed_field_role():
    """Drift script must detect a field role change in field_compatibility."""
    import check_reports_drift as drift_module

    cached_spec = {
        "report_types": [],
        "date_range_types": [],
        "formats": ["TSV"],
        "processing_modes": [],
        "request_headers": {},
        "field_compatibility": {
            "Clicks": {"report_types": {"CAMPAIGN_PERFORMANCE_REPORT": "metric"}}
        },
    }
    live_spec = {
        **cached_spec,
        "field_compatibility": {
            "Clicks": {"report_types": {"CAMPAIGN_PERFORMANCE_REPORT": "segment"}}
        },
    }
    report = drift_module.compute_drift(cached_spec, live_spec)
    assert report["drift_count"] > 0
    changed = next(
        d for d in report["drift"] if "field_compatibility" in d["section"]
    )
    assert changed is not None
