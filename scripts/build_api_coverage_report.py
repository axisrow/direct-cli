#!/usr/bin/env python3
"""Emit a machine-readable API coverage summary."""

from __future__ import annotations

import json
import importlib
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli.utils import COMMON_FIELDS
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

# Explicit allow-list for CLI ``get`` groups whose WSDL has no ``*FieldEnum``
# request param — there's nothing for the schema gate to validate. Each entry
# must justify why FieldNames validation is not applicable; any new ``get``
# command not covered by the gate AND not waived here will fail the build.
SCHEMA_GATE_WAIVERS = {
    "dictionaries": (
        "WSDL has no FieldEnum for get; FieldNames is a free-form list of "
        "dictionary names provided by the user."
    ),
}


def _common_default_field_params(
    cli_group: str, api_service: Optional[str] = None
) -> dict[str, list[str]]:
    """Return ``COMMON_FIELDS`` defaults keyed by WSDL request param."""
    entry = COMMON_FIELDS.get(cli_group)
    if entry is None and api_service is not None:
        entry = COMMON_FIELDS.get(api_service)
    if entry is None:
        return {}
    if isinstance(entry, dict):
        return {field_name: list(values) for field_name, values in entry.items()}
    return {"FieldNames": list(entry)}


def _common_field_resource_targets() -> dict[str, tuple[str, str]]:
    """Return ``COMMON_FIELDS`` resource -> (cli_group, api_service)."""
    api_to_cli = {
        api_service: cli_group
        for cli_group, api_service in CLI_TO_API_SERVICE.items()
    }
    targets = {}
    for resource in COMMON_FIELDS:
        if resource in CLI_TO_API_SERVICE:
            targets[resource] = (resource, CLI_TO_API_SERVICE[resource])
        elif resource in api_to_cli:
            targets[resource] = (api_to_cli[resource], resource)
    return targets


def _validate_common_field_defaults(fetch_wsdl_func) -> tuple[list[dict], list[dict]]:
    """Validate every ``COMMON_FIELDS`` entry against its WSDL enum."""
    mismatches = []
    capture_errors = []

    for resource, (cli_name, api_service) in sorted(
        _common_field_resource_targets().items()
    ):
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
                    "source": "COMMON_FIELDS",
                }
            )
            continue

        for request_field, actual_values in sorted(
            _common_default_field_params(resource).items()
        ):
            spec = field_specs.get(request_field)
            if spec is None:
                mismatches.append(
                    {
                        "cli_group": cli_name,
                        "api_service": api_service,
                        "operation": "get",
                        "request_field": request_field,
                        "enum_type": None,
                        "invalid_values": list(actual_values),
                        "actual_values": list(actual_values),
                        "source": "COMMON_FIELDS",
                        "resource": resource,
                    }
                )
                continue

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
                        "actual_values": list(actual_values),
                        "source": "COMMON_FIELDS",
                        "resource": resource,
                    }
                )

    return mismatches, capture_errors


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
    """Validate default CLI ``*FieldNames`` values against WSDL ``*FieldEnum``.

    Returns a result dict with five failure modes that all flip
    ``schema_parity_ok`` to ``False``:

    - ``field_name_mismatches`` — values sent by the CLI that are not in the
      corresponding WSDL ``*FieldEnum``, plus invalid values in
      ``COMMON_FIELDS`` itself.
    - ``capture_errors`` — wire-capture failed (missing required option, etc.).
    - ``uncovered_get_groups`` — CLI ``get`` commands whose WSDL declares a
      ``*FieldEnum`` but whose actual request did not exercise it (and no
      ``SCHEMA_GATE_WAIVERS`` entry justifies skipping). This catches new
      ``get`` commands added without registration in the gate.
    - ``waiver_misuse`` — waivers that no longer point at a no-enum group.
    - ``missing_field_name_params`` — ``COMMON_FIELDS`` declares a default
      ``*FieldNames`` request param, but the command default payload omits it.
    """
    if capture_get_body_func is None:
        capture_get_body_func = capture_cli_get_request_body

    mismatches, capture_errors = _validate_common_field_defaults(fetch_wsdl_func)
    missing_field_name_params = []
    validated_groups = set()
    waived_no_enum_groups = set()

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
            waived_no_enum_groups.add(cli_name)
            continue

        expected_field_params = _common_default_field_params(cli_name, api_service)

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
        missing_params = sorted(
            request_field
            for request_field in expected_field_params
            if request_field not in params
        )
        if missing_params:
            missing_field_name_params.append(
                {
                    "cli_group": cli_name,
                    "api_service": api_service,
                    "operation": "get",
                    "missing_params": missing_params,
                }
            )

        validated_any_field = False
        for request_field, spec in sorted(field_specs.items()):
            if request_field not in params:
                continue
            validated_any_field = True

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
                        "source": "wire_payload",
                    }
                )
        if validated_any_field:
            validated_groups.add(cli_name)

    expected_groups = {
        cli_name
        for cli_name in CLI_TO_API_SERVICE
        if "get" in get_cli_methods_for_service(cli_name)
    }
    error_groups = {entry["cli_group"] for entry in capture_errors}
    uncovered_get_groups = sorted(
        expected_groups
        - validated_groups
        - error_groups
        - (waived_no_enum_groups & set(SCHEMA_GATE_WAIVERS))
    )

    waiver_misuse = sorted(
        cli_name
        for cli_name in SCHEMA_GATE_WAIVERS
        if cli_name not in waived_no_enum_groups
    )

    return {
        "field_name_mismatches": mismatches,
        "capture_errors": capture_errors,
        "missing_field_name_params": missing_field_name_params,
        "uncovered_get_groups": uncovered_get_groups,
        "waiver_misuse": waiver_misuse,
        "schema_parity_ok": (
            not mismatches
            and not capture_errors
            and not missing_field_name_params
            and not uncovered_get_groups
            and not waiver_misuse
        ),
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
        "missing_field_name_params": schema_gate["missing_field_name_params"],
        "uncovered_get_groups": schema_gate["uncovered_get_groups"],
        "waiver_misuse": schema_gate["waiver_misuse"],
    }
    report["summary"]["schema_parity_ok"] = schema_gate["schema_parity_ok"]

    return report


def main() -> int:
    report = build_report()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
