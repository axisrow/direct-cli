#!/usr/bin/env python3
"""Emit a machine-readable API coverage summary."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from direct_cli.wsdl_coverage import (
    CLI_TO_API_SERVICE,
    INTENTIONAL_EXTRA_METHODS,
    get_api_coverage_policy,
    fetch_wsdl,
    get_cli_methods_for_service,
    parse_wsdl_operations,
)


def main() -> int:
    report = {
        "policy": get_api_coverage_policy(),
        "summary": {
            "services_checked": 0,
            "missing_service_methods": 0,
            "unexpected_service_methods": 0,
            "strict_parity_ok": True,
        },
        "canonical_services": sorted(CLI_TO_API_SERVICE.values()),
        "non_wsdl_services": get_api_coverage_policy()["non_wsdl_services"],
        "cli_helpers": {
            f"{service}.{method}": reason
            for (service, method), reason in sorted(INTENTIONAL_EXTRA_METHODS.items())
        },
        "services": [],
    }

    for cli_name, api_service in sorted(CLI_TO_API_SERVICE.items()):
        api_methods = sorted(parse_wsdl_operations(fetch_wsdl(api_service)))
        cli_methods = sorted(get_cli_methods_for_service(cli_name))
        missing_methods = sorted(set(api_methods) - set(cli_methods))
        extra_methods = sorted(
            method
            for method in (set(cli_methods) - set(api_methods))
            if (cli_name, method) not in INTENTIONAL_EXTRA_METHODS
        )
        report["services"].append(
            {
                "cli_group": cli_name,
                "api_service": api_service,
                "api_methods": api_methods,
                "cli_methods": cli_methods,
                "missing_methods": missing_methods,
                "extra_methods": extra_methods,
                "allowed_extra_methods": {
                    method: INTENTIONAL_EXTRA_METHODS[(cli_name, method)]
                    for method in sorted(set(cli_methods) - set(api_methods))
                    if (cli_name, method) in INTENTIONAL_EXTRA_METHODS
                },
            }
        )
        report["summary"]["services_checked"] += 1
        report["summary"]["missing_service_methods"] += len(missing_methods)
        report["summary"]["unexpected_service_methods"] += len(extra_methods)

    report["summary"]["strict_parity_ok"] = (
        report["summary"]["missing_service_methods"] == 0
        and report["summary"]["unexpected_service_methods"] == 0
    )

    # Reports section
    from direct_cli.reports_coverage import get_reports_coverage_policy, load_cached_reports_spec
    from direct_cli.commands.reports import _load_report_types
    reports_policy = get_reports_coverage_policy()
    try:
        spec = load_cached_reports_spec()
        cli_types = set(t.upper() for t in _load_report_types())
        spec_types = set(t.upper() for t in spec.get("report_types", []))
        cli_types_match = cli_types == spec_types
        cli_headers_covered = bool(spec.get("request_headers"))
    except Exception:
        cli_types_match = False
        cli_headers_covered = False

    report["reports"] = {
        "policy": reports_policy,
        "summary": {
            "report_types": reports_policy["summary"]["report_types"],
            "fields": reports_policy["summary"]["fields"],
            "headers": reports_policy["summary"]["headers"],
            "cli_report_types_match": cli_types_match,
            "cli_headers_covered": cli_headers_covered,
        },
    }
    report["summary"]["strict_parity_ok"] = (
        report["summary"]["strict_parity_ok"]
        and cli_types_match
        and cli_headers_covered
    )

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
