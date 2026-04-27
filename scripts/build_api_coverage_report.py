#!/usr/bin/env python3
"""Emit a machine-readable API coverage summary."""

from __future__ import annotations

import json
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli.wsdl_coverage import (
    CLI_TO_API_SERVICE,
    INTENTIONAL_EXTRA_METHODS,
    LIVE_DISCOVERED_API_SERVICES,
    get_api_coverage_policy,
    fetch_wsdl,
    fetch_live_wsdl,
    get_cli_methods_for_service,
    get_operation_field_name_enums,
    parse_wsdl_operations,
)

GET_CAPTURE_OPTION_FIXTURES = {
    "dynamicfeedadtargets": ["--ids", "1"],
    "leads": ["--turbo-page-ids", "1"],
}


def _fetch_wsdl(fetch_func, service: str) -> str:
    """Fetch WSDL for a given service."""
    return fetch_func(service)


def _build_model_gaps(report: dict, live_fetch_wsdl_func) -> dict:
    """Compare the declared coverage model to the live-discovered API surface."""
    api_to_cli = {
        api_service: cli_name
        for cli_name, api_service in sorted(CLI_TO_API_SERVICE.items())
    }
    declared_services = set(api_to_cli)
    declared_methods = {
        service["api_service"]: set(service["api_methods"])
        for service in report["services"]
    }

    # Seed with declared (cached WSDL) methods; only live-fetch undeclared services.
    # Gap detection will NOT catch new methods added to already-declared services.
    live_methods_by_service = {
        api_service: set(methods)
        for api_service, methods in sorted(declared_methods.items())
    }
    live_discovery_errors = []
    for api_service in sorted(LIVE_DISCOVERED_API_SERVICES):
        if api_service in declared_services:
            continue
        try:
            live_methods_by_service[api_service] = set(
                parse_wsdl_operations(_fetch_wsdl(live_fetch_wsdl_func, api_service))
            )
        except Exception as exc:
            live_methods_by_service[api_service] = set()
            live_discovery_errors.append(
                {
                    "api_service": api_service,
                    "error": str(exc),
                }
            )

    missing_services = []
    missing_method_entries = []
    for api_service, live_methods in sorted(live_methods_by_service.items()):
        if api_service not in declared_services:
            missing_services.append(
                {
                    "api_service": api_service,
                    "api_methods": sorted(live_methods),
                }
            )
            if live_methods:
                missing_method_entries.append(
                    {
                        "api_service": api_service,
                        "missing_methods": sorted(live_methods),
                    }
                )
            continue

        cli_name = api_to_cli[api_service]
        cli_methods = set(get_cli_methods_for_service(cli_name))
        missing_methods = sorted(live_methods - cli_methods)
        if missing_methods:
            missing_method_entries.append(
                {
                    "api_service": api_service,
                    "cli_group": cli_name,
                    "missing_methods": missing_methods,
                }
            )

    declared_method_count = sum(len(methods) for methods in declared_methods.values())
    live_method_count = sum(
        len(methods) for methods in live_methods_by_service.values()
    )
    missing_method_count = sum(
        len(entry["missing_methods"]) for entry in missing_method_entries
    )

    return {
        "declared_wsdl_services_count": len(declared_services),
        "declared_wsdl_methods_count": declared_method_count,
        "live_discovered_services_count": len(LIVE_DISCOVERED_API_SERVICES),
        "total_known_methods_count": live_method_count,
        "live_discovered_missing_services": missing_services,
        "live_discovered_missing_methods": missing_method_count,
        "live_discovered_missing_method_entries": missing_method_entries,
        "live_discovery_errors": live_discovery_errors,
        "live_model_gap_count": len(missing_services)
        + len(
            [
                entry
                for entry in missing_method_entries
                if entry["api_service"] in declared_services
            ]
        ),
        "live_model_parity_ok": (
            not missing_services
            and not missing_method_entries
            and not live_discovery_errors
        ),
    }


class _CapturedResponse:
    """Minimal tapi-like response object for CLI request capture."""

    def __call__(self):
        return self

    def extract(self):
        return {}

    def iter_items(self):
        return iter(())


class _CapturedService:
    """Fake service executor that records posted request bodies."""

    def __init__(self, captured: dict):
        self._captured = captured

    def post(self, data):
        self._captured["body"] = data
        return _CapturedResponse()


class _CapturedClient:
    """Fake Direct client exposing any service requested by a command module."""

    def __init__(self, captured: dict):
        self._captured = captured

    def __getattr__(self, name):
        return lambda: _CapturedService(self._captured)


def _command_supports_option(
    group_name: str, command_name: str, param_name: str
) -> bool:
    """Return whether a Click command exposes a parameter by internal name."""
    command = cli.commands[group_name].commands[command_name]
    return any(getattr(param, "name", None) == param_name for param in command.params)


def capture_cli_get_request_body(cli_group: str) -> dict:
    """Invoke ``direct <group> get`` with a fake client and return the body."""
    module = importlib.import_module(f"direct_cli.commands.{cli_group}")
    original_create_client = module.create_client
    captured = {}

    try:
        module.create_client = lambda **_: _CapturedClient(captured)
        argv = [cli_group, "get"]
        argv.extend(GET_CAPTURE_OPTION_FIXTURES.get(cli_group, []))
        if _command_supports_option(cli_group, "get", "limit"):
            argv.extend(["--limit", "1"])
        if _command_supports_option(cli_group, "get", "output_format"):
            argv.extend(["--format", "json"])

        result = CliRunner().invoke(cli, argv)
    finally:
        module.create_client = original_create_client

    if result.exit_code != 0:
        raise RuntimeError(
            f"direct {' '.join(argv)} failed with exit {result.exit_code}: "
            f"{result.output.strip()}"
        )
    if "body" not in captured:
        raise RuntimeError(f"direct {' '.join(argv)} did not send a request body")

    return captured["body"]


def build_schema_gate(fetch_wsdl_func=fetch_wsdl, capture_get_body_func=None) -> dict:
    """Validate default CLI ``*FieldNames`` values against WSDL ``*FieldEnum``."""
    if capture_get_body_func is None:
        capture_get_body_func = capture_cli_get_request_body

    mismatches = []
    capture_errors = []

    for cli_name, api_service in sorted(CLI_TO_API_SERVICE.items()):
        if "get" not in get_cli_methods_for_service(cli_name):
            continue

        try:
            wsdl_xml = _fetch_wsdl(fetch_wsdl_func, api_service)
            field_specs = get_operation_field_name_enums(wsdl_xml, "get")
        except Exception as exc:
            capture_errors.append(
                {
                    "cli_group": cli_name,
                    "api_service": api_service,
                    "operation": "get",
                    "error": str(exc),
                }
            )
            continue

        if not field_specs:
            continue

        try:
            body = capture_get_body_func(cli_name)
        except Exception as exc:
            capture_errors.append(
                {
                    "cli_group": cli_name,
                    "api_service": api_service,
                    "operation": "get",
                    "error": str(exc),
                }
            )
            continue

        params = body.get("params", {})
        for request_field, spec in sorted(field_specs.items()):
            if request_field not in params:
                continue

            actual_values = params[request_field]
            if not isinstance(actual_values, list):
                actual_values = [actual_values]

            allowed_values = set(spec["values"])
            invalid_values = sorted(
                value for value in actual_values if value not in allowed_values
            )
            if invalid_values:
                mismatches.append(
                    {
                        "cli_group": cli_name,
                        "api_service": api_service,
                        "operation": "get",
                        "request_field": request_field,
                        "enum_type": spec["enum_type"],
                        "invalid_values": invalid_values,
                        "actual_values": actual_values,
                    }
                )

    return {
        "field_name_mismatches": mismatches,
        "capture_errors": capture_errors,
        "schema_parity_ok": not mismatches and not capture_errors,
    }


def build_report(fetch_wsdl_func=fetch_wsdl, live_fetch_wsdl_func=None) -> dict:
    if live_fetch_wsdl_func is None:
        live_fetch_wsdl_func = (
            fetch_live_wsdl if fetch_wsdl_func is fetch_wsdl else fetch_wsdl_func
        )

    report = {
        "policy": get_api_coverage_policy(),
        "summary": {
            "services_checked": 0,
            "missing_service_methods": 0,
            "unexpected_service_methods": 0,
            "strict_parity_ok": True,
            "live_model_parity_ok": True,
            "schema_parity_ok": True,
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
        api_methods = sorted(
            parse_wsdl_operations(_fetch_wsdl(fetch_wsdl_func, api_service))
        )
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
    from direct_cli.reports_coverage import (
        get_reports_coverage_policy,
        load_cached_reports_spec,
    )
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

    report["model_gaps"] = _build_model_gaps(report, live_fetch_wsdl_func)
    report["summary"]["live_model_parity_ok"] = report["model_gaps"][
        "live_model_parity_ok"
    ]

    schema_gate = build_schema_gate(fetch_wsdl_func=fetch_wsdl_func)
    report["schema"] = {
        "field_name_mismatches": schema_gate["field_name_mismatches"],
        "capture_errors": schema_gate["capture_errors"],
    }
    report["summary"]["schema_parity_ok"] = schema_gate["schema_parity_ok"]

    return report


def main() -> int:
    report = build_report()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
