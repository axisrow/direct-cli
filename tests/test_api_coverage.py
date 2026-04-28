"""
API coverage tests — verify CLI coverage against Yandex Direct API v5 WSDL.

Phase 1: For each CLI service, check that all WSDL operations are covered.
Phase 2: Detect new API services not yet covered by the CLI.
Phase 3: Validate dry-run payload shape against cached WSDL request schemas.

See tests/API_COVERAGE.md for the human-readable coverage matrix and the
difference between declared strict parity and live-discovered model gaps.
"""

import json
import importlib
import importlib.util
import subprocess
import sys

import pytest
from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli.commands.reports import build_report_request
from direct_cli.wsdl_coverage import (
    CACHE_DIR,
    CLI_TO_API_SERVICE,
    CANONICAL_API_SERVICES,
    IMPORTED_XSD_REGISTRY,
    INTENTIONAL_EXTRA_METHODS,
    KNOWN_MISSING_SERVICES,
    NON_WSDL_SERVICE_POLICIES,
    RUNTIME_DEPRECATED_METHODS,
    fetch_wsdl,
    find_nested_schema_violations,
    get_cli_methods_for_service,
    get_operation_request_schema,
    get_operation_field_name_enums,
    parse_wsdl_operations,
)
from tests.api_coverage_payloads import (
    DRY_RUN_PAYLOAD_EXCLUSIONS,
    PAYLOAD_CASES,
    PAYLOAD_COVERED_COMMANDS,
)

ALLOWED_EXTRA_METHODS = set(INTENTIONAL_EXTRA_METHODS)


def _load_coverage_report_script():
    """Load the coverage report script as a module for direct unit tests."""
    script_path = CACHE_DIR.parent.parent / "scripts" / "build_api_coverage_report.py"
    spec = importlib.util.spec_from_file_location(
        "build_api_coverage_report", script_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _wsdl_with_operations(*operations):
    """Build a minimal WSDL document containing operation names."""
    body = "\n".join(
        f'        <wsdl:operation name="{operation}" />' for operation in operations
    )
    return (
        '<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/">\n'
        "    <wsdl:portType>\n"
        f"{body}\n"
        "    </wsdl:portType>\n"
        "</wsdl:definitions>\n"
    )


def _wsdl_with_get_field_enum(*values):
    """Build a minimal WSDL get request with a FieldNames enum."""
    enum_values = "\n".join(
        f'                <xsd:enumeration value="{value}" />' for value in values
    )
    return (
        '<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        'xmlns:tns="http://api.direct.yandex.com/v5/fake">\n'
        '    <wsdl:message name="getRequest">\n'
        '        <wsdl:part name="parameters" element="tns:get" />\n'
        "    </wsdl:message>\n"
        "    <wsdl:portType>\n"
        '        <wsdl:operation name="get">\n'
        '            <wsdl:input message="tns:getRequest" />\n'
        "        </wsdl:operation>\n"
        "    </wsdl:portType>\n"
        '    <xsd:schema targetNamespace="http://api.direct.yandex.com/v5/fake">\n'
        '        <xsd:simpleType name="FakeFieldEnum">\n'
        '            <xsd:restriction base="xsd:string">\n'
        f"{enum_values}\n"
        "            </xsd:restriction>\n"
        "        </xsd:simpleType>\n"
        '        <xsd:element name="get">\n'
        "            <xsd:complexType>\n"
        "                <xsd:sequence>\n"
        '                    <xsd:element name="FieldNames" '
        'type="tns:FakeFieldEnum" minOccurs="1" maxOccurs="unbounded" />\n'
        "                </xsd:sequence>\n"
        "            </xsd:complexType>\n"
        "        </xsd:element>\n"
        "    </xsd:schema>\n"
        "</wsdl:definitions>\n"
    )


def _wsdl_with_get_field_enums(field_values):
    """Build a minimal WSDL get request with several ``*FieldNames`` enums."""
    simple_types = []
    elements = []
    for field_name, values in field_values.items():
        enum_stem = field_name.removesuffix("Names")
        enum_type = f"Fake{enum_stem}Enum"
        enum_values = "\n".join(
            f'                <xsd:enumeration value="{value}" />' for value in values
        )
        simple_types.append(
            f'        <xsd:simpleType name="{enum_type}">\n'
            '            <xsd:restriction base="xsd:string">\n'
            f"{enum_values}\n"
            "            </xsd:restriction>\n"
            "        </xsd:simpleType>"
        )
        elements.append(
            f'                    <xsd:element name="{field_name}" '
            f'type="tns:{enum_type}" minOccurs="0" maxOccurs="unbounded" />'
        )

    return (
        '<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        'xmlns:tns="http://api.direct.yandex.com/v5/fake">\n'
        '    <wsdl:message name="getRequest">\n'
        '        <wsdl:part name="parameters" element="tns:get" />\n'
        "    </wsdl:message>\n"
        "    <wsdl:portType>\n"
        '        <wsdl:operation name="get">\n'
        '            <wsdl:input message="tns:getRequest" />\n'
        "        </wsdl:operation>\n"
        "    </wsdl:portType>\n"
        '    <xsd:schema targetNamespace="http://api.direct.yandex.com/v5/fake">\n'
        f"{chr(10).join(simple_types)}\n"
        '        <xsd:element name="get">\n'
        "            <xsd:complexType>\n"
        "                <xsd:sequence>\n"
        f"{chr(10).join(elements)}\n"
        "                </xsd:sequence>\n"
        "            </xsd:complexType>\n"
        "        </xsd:element>\n"
        "    </xsd:schema>\n"
        "</wsdl:definitions>\n"
    )


def _dry_run(*args: str) -> dict:
    result = CliRunner().invoke(cli, list(args) + ["--dry-run"])
    assert result.exit_code == 0, (
        f"command failed: direct {' '.join(args)} --dry-run\n"
        f"output: {result.output}\n"
        f"exception: {result.exception}"
    )
    return json.loads(result.output)


def _assert_body_matches_wsdl(body: dict, service: str, operation: str):
    # Coverage note: get_operation_request_schema resolves registered imported
    # XSD types and inherited xsd:extension fields, so nested item checks below
    # cover those schemas as long as the import is in IMPORTED_XSD_REGISTRY.
    schema = get_operation_request_schema(fetch_wsdl(service), operation)
    expected_fields = {field["name"] for field in schema["fields"]}
    required_fields = {
        field["name"] for field in schema["fields"] if field["min_occurs"] > 0
    }
    actual_fields = set(body["params"])
    assert actual_fields <= expected_fields, (
        f"{service}.{operation}: unexpected top-level params "
        f"{sorted(actual_fields - expected_fields)}"
    )
    assert required_fields <= actual_fields, (
        f"{service}.{operation}: missing required top-level params "
        f"{sorted(required_fields - actual_fields)}"
    )

    for field in schema["fields"]:
        if field["name"] not in body["params"]:
            continue
        value = body["params"][field["name"]]
        if field["max_occurs"] == "unbounded":
            assert isinstance(
                value, list
            ), f"{service}.{operation}.{field['name']} must be a list"
            if value and field["item_fields"]:
                required = {
                    item["name"]
                    for item in field["item_fields"]
                    if item["min_occurs"] > 0
                }
                assert required <= set(value[0]), (
                    f"{service}.{operation}.{field['name']} missing required item keys: "
                    f"{sorted(required - set(value[0]))}"
                )
        elif field["item_fields"] and isinstance(value, dict):
            required = {
                item["name"] for item in field["item_fields"] if item["min_occurs"] > 0
            }
            assert required <= set(value), (
                f"{service}.{operation}.{field['name']} missing required keys: "
                f"{sorted(required - set(value))}"
            )


@pytest.mark.api_coverage
class TestApiCoverage:
    """Verify CLI coverage against Yandex Direct API v5 WSDL."""

    def test_no_missing_services(self):
        covered_services = set(CLI_TO_API_SERVICE.values())
        all_known = set(CANONICAL_API_SERVICES)
        missing = all_known - covered_services
        unaccounted = missing - KNOWN_MISSING_SERVICES

        assert unaccounted == set(), (
            f"New API services detected (not in CLI and not in "
            f"KNOWN_MISSING_SERVICES): {sorted(unaccounted)}. "
            f"Add CLI commands or update KNOWN_MISSING_SERVICES."
        )

    def test_wsdl_cache_matches_canonical_service_list(self):
        cached = {path.stem for path in CACHE_DIR.glob("*.xml") if path.is_file()}
        expected = set(CANONICAL_API_SERVICES)
        assert cached == expected, (
            "WSDL cache drift detected.\n"
            f"Missing cache files: {sorted(expected - cached)}\n"
            f"Unexpected cache files: {sorted(cached - expected)}"
        )

    def test_non_wsdl_services_have_explicit_coverage_policy(self):
        for service_name, policy in sorted(NON_WSDL_SERVICE_POLICIES.items()):
            assert (
                service_name in cli.commands
            ), f"Non-WSDL service {service_name} is missing from the CLI"
            assert policy["coverage"] in (
                "contract-tests",
                "contract-tests+spec-snapshot",
            ), f"Unexpected coverage policy for non-WSDL service {service_name}: {policy}"

    def test_service_method_coverage(self):
        failures = []

        for cli_name, api_service in sorted(CLI_TO_API_SERVICE.items()):
            try:
                wsdl_xml = fetch_wsdl(api_service)
            except Exception as exc:
                failures.append(
                    f"{cli_name} -> {api_service}: WSDL fetch failed: {exc}"
                )
                continue

            api_methods = set(parse_wsdl_operations(wsdl_xml))
            cli_methods = get_cli_methods_for_service(cli_name)

            missing = api_methods - cli_methods
            extra = {
                method
                for method in (cli_methods - api_methods)
                if (cli_name, method) not in ALLOWED_EXTRA_METHODS
            }

            if missing:
                failures.append(
                    f"{cli_name} -> {api_service}: missing API methods {sorted(missing)}"
                )
            if extra:
                failures.append(
                    f"{cli_name} -> {api_service}: unexpected CLI methods {sorted(extra)}"
                )

        assert failures == [], "API coverage gaps detected:\n" + "\n".join(failures)

    @pytest.mark.parametrize(("service", "operation", "argv"), PAYLOAD_CASES)
    def test_dry_run_payload_schema_coverage(self, service, operation, argv):
        body = _dry_run(*argv)
        assert body["method"] == operation
        _assert_body_matches_wsdl(body, service, operation)

    def test_all_canonical_dry_run_commands_have_payload_coverage_or_exclusion(self):
        actual = set()
        for group_name, group in sorted(cli.commands.items()):
            if not hasattr(group, "commands"):
                continue
            for cmd_name, cmd in sorted(group.commands.items()):
                if any(
                    getattr(param, "name", None) == "dry_run" for param in cmd.params
                ):
                    actual.add(f"{group_name}.{cmd_name}")

        accounted = PAYLOAD_COVERED_COMMANDS | set(DRY_RUN_PAYLOAD_EXCLUSIONS)
        assert actual == accounted, (
            "Canonical dry-run command registry is out of date.\n"
            f"Missing accounting for: {sorted(actual - accounted)}\n"
            f"Stale registry entries: {sorted(accounted - actual)}"
        )

    def test_reports_contract_coverage(self):
        result = CliRunner().invoke(cli, ["reports", "list-types"])
        assert result.exit_code == 0, result.output
        report_types = json.loads(result.output)
        assert report_types, "reports list-types returned no report types"
        assert "CAMPAIGN_PERFORMANCE_REPORT" in report_types

        body = CliRunner(
            env={"YANDEX_DIRECT_TOKEN": "", "YANDEX_DIRECT_LOGIN": ""}
        ).invoke(
            cli,
            [
                "reports",
                "get",
                "--type",
                "campaign_performance_report",
                "--from",
                "2026-01-01",
                "--to",
                "2026-01-31",
                "--name",
                "Coverage Report",
                "--fields",
                "Date,CampaignId",
            ],
        )
        assert "Invalid value for '--type'" not in body.output

    def test_reports_request_builder_contract(self):
        request = build_report_request(
            report_type="CAMPAIGN_PERFORMANCE_REPORT",
            date_from="2026-01-01",
            date_to="2026-01-31",
            name="Coverage Report",
            fields="Date,CampaignId",
            campaign_ids="1,2",
        )
        assert request == {
            "params": {
                "SelectionCriteria": {
                    "DateFrom": "2026-01-01",
                    "DateTo": "2026-01-31",
                    "Filter": [
                        {
                            "Field": "CampaignId",
                            "Operator": "IN",
                            "Values": ["1", "2"],
                        }
                    ],
                },
                "FieldNames": ["Date", "CampaignId"],
                "ReportName": "Coverage Report",
                "ReportType": "CAMPAIGN_PERFORMANCE_REPORT",
                "DateRangeType": "CUSTOM_DATE",
                "Format": "TSV",
                "IncludeVAT": "YES",
                "IncludeDiscount": "YES",
            }
        }

    def test_reports_request_builder_adgroup_filter_and_field_normalization(self):
        request = build_report_request(
            report_type="ADGROUP_PERFORMANCE_REPORT",
            date_from="2026-02-01",
            date_to="2026-02-28",
            name="Adgroup Coverage",
            fields=" Date , AdGroupId , Clicks ",
            adgroup_ids="10, 20 ,30",
        )
        assert request["params"]["SelectionCriteria"]["Filter"] == [
            {
                "Field": "AdGroupId",
                "Operator": "IN",
                "Values": ["10", "20", "30"],
            }
        ]
        assert request["params"]["FieldNames"] == ["Date", "AdGroupId", "Clicks"]
        assert request["params"]["Format"] == "TSV"

    def test_reports_request_builder_both_campaign_and_adgroup_ids_raises(self):
        with pytest.raises(ValueError, match="mutually exclusive"):
            build_report_request(
                report_type="CUSTOM_REPORT",
                date_from="2026-03-01",
                date_to="2026-03-31",
                name="Precedence Coverage",
                fields="Date,CampaignId,AdGroupId",
                campaign_ids="1,2",
                adgroup_ids="99,100",
            )

    @pytest.mark.parametrize("output_format", ["json", "table", "csv", "tsv"])
    def test_reports_get_cli_path_sends_expected_request_body(
        self, monkeypatch, output_format
    ):
        captured = {}
        reports_module = importlib.import_module("direct_cli.commands.reports")

        class _FakeResponse:
            columns = ["Date", "CampaignId"]
            data = [["2026-01-01", "1"]]

            def __call__(self):
                return self

            def to_dicts(self):
                return [{"Date": "2026-01-01", "CampaignId": "1"}]

            def to_values(self):
                return [["2026-01-01", "1"]]

        class _FakeReports:
            def post(self, data):
                captured["body"] = data
                return _FakeResponse()

        class _FakeClient:
            def reports(self):
                return _FakeReports()

        monkeypatch.setattr(reports_module, "create_client", lambda **_: _FakeClient())

        result = CliRunner().invoke(
            cli,
            [
                "reports",
                "get",
                "--type",
                "campaign_performance_report",
                "--from",
                "2026-01-01",
                "--to",
                "2026-01-31",
                "--name",
                "Coverage Report",
                "--fields",
                " Date , CampaignId ",
                "--campaign-ids",
                "1, 2",
                "--format",
                output_format,
            ],
        )

        assert result.exit_code == 0, result.output
        assert captured["body"] == build_report_request(
            report_type="CAMPAIGN_PERFORMANCE_REPORT",
            date_from="2026-01-01",
            date_to="2026-01-31",
            name="Coverage Report",
            fields=" Date , CampaignId ",
            campaign_ids="1, 2",
        )

    def test_reports_get_cli_path_forwards_header_flags_to_create_client(
        self, monkeypatch
    ):
        """--processing-mode, --skip-*, --return-money-in-micros must reach create_client."""
        captured = {}
        reports_module = importlib.import_module("direct_cli.commands.reports")

        class _FakeResponse:
            columns = ["Date"]
            data = [["2026-01-01"]]

            def __call__(self):
                return self

            def to_dicts(self):
                return [{"Date": "2026-01-01"}]

            def to_values(self):
                return [["2026-01-01"]]

        class _FakeReports:
            def post(self, data):
                return _FakeResponse()

        class _FakeClient:
            def reports(self):
                return _FakeReports()

        def _fake_create_client(**kwargs):
            captured["kwargs"] = kwargs
            return _FakeClient()

        monkeypatch.setattr(reports_module, "create_client", _fake_create_client)

        result = CliRunner().invoke(
            cli,
            [
                "reports",
                "get",
                "--type",
                "campaign_performance_report",
                "--from",
                "2026-01-01",
                "--to",
                "2026-01-31",
                "--name",
                "Test",
                "--fields",
                "Date",
                "--processing-mode",
                "online",
                "--skip-report-header",
                "--skip-column-header",
                "--return-money-in-micros",
                "--language",
                "ru",
            ],
        )

        assert result.exit_code == 0, result.output
        assert captured["kwargs"]["processing_mode"] == "online"
        assert captured["kwargs"]["skip_report_header"] is True
        assert captured["kwargs"]["skip_column_header"] is True
        assert captured["kwargs"]["return_money_in_micros"] is True
        assert captured["kwargs"]["language"] == "ru"

    def test_api_coverage_report_script_matches_strict_parity_contract(self):
        result = subprocess.run(
            [sys.executable, "scripts/build_api_coverage_report.py"],
            cwd=CACHE_DIR.parent.parent,
            check=True,
            capture_output=True,
            text=True,
        )
        report = json.loads(result.stdout)
        assert report["summary"]["strict_parity_ok"] is True
        assert report["summary"]["live_model_parity_ok"] is True
        assert report["summary"]["schema_parity_ok"] is True
        assert report["summary"]["missing_service_methods"] == 0
        assert report["summary"]["unexpected_service_methods"] == 0
        assert sorted(report["canonical_services"]) == CANONICAL_API_SERVICES
        assert report["model_gaps"]["live_model_gap_count"] == 0
        assert report["model_gaps"]["live_discovered_missing_services"] == []
        assert report["schema"]["field_name_mismatches"] == []
        assert report["schema"]["capture_errors"] == []
        assert report["schema"]["missing_field_name_params"] == []
        assert report["schema"]["missing_common_fields"] == []
        assert report["schema"]["orphan_common_fields"] == []
        assert report["schema"]["uncovered_get_groups"] == []
        assert report["schema"]["waiver_misuse"] == []
        assert report["schema"]["runtime_deprecated_unguarded"] == []
        assert report["schema"]["nested_schema_violations"] == []

    def test_real_wsdl_field_enum_parser_for_108_services(self):
        expected = {
            "smartadtargets": {"Id", "CampaignId", "AdGroupId", "State"},
            "adextensions": {"Id", "Type", "State", "Status"},
            "businesses": {"Id", "Name", "Address", "Phone", "ProfileUrl"},
        }

        for service, expected_values in expected.items():
            fields = get_operation_field_name_enums(fetch_wsdl(service), "get")
            assert "FieldNames" in fields
            assert expected_values <= set(fields["FieldNames"]["values"])

        smart_values = set(
            get_operation_field_name_enums(fetch_wsdl("smartadtargets"), "get")[
                "FieldNames"
            ]["values"]
        )
        assert "Status" not in smart_values
        assert "ServingStatus" not in smart_values
        assert "Type" not in set(
            get_operation_field_name_enums(fetch_wsdl("businesses"), "get")[
                "FieldNames"
            ]["values"]
        )

    def test_default_fieldnames_match_wsdl_enum(self):
        report_script = _load_coverage_report_script()
        schema_gate = report_script.build_schema_gate()

        assert schema_gate["schema_parity_ok"] is True
        assert schema_gate["field_name_mismatches"] == []
        assert schema_gate["capture_errors"] == []
        assert schema_gate["missing_field_name_params"] == []
        assert schema_gate["missing_common_fields"] == []
        assert schema_gate["orphan_common_fields"] == []
        assert schema_gate["uncovered_get_groups"] == []
        assert schema_gate["waiver_misuse"] == []
        assert schema_gate["runtime_deprecated_unguarded"] == []
        assert schema_gate["nested_schema_violations"] == []

    def test_schema_gate_flags_uncovered_get_command(self, monkeypatch):
        """A new ``get`` command without coverage and without waiver fails."""
        report_script = _load_coverage_report_script()
        monkeypatch.setattr(
            report_script,
            "CLI_TO_API_SERVICE",
            {"fake": "fake"},
        )
        monkeypatch.setattr(
            report_script,
            "get_cli_methods_for_service",
            lambda cli_name: {"get"},
        )
        monkeypatch.setattr(report_script, "SCHEMA_GATE_WAIVERS", {})

        schema_gate = report_script.build_schema_gate(
            fetch_wsdl_func=lambda service: _wsdl_with_get_field_enum("Id", "Name"),
            capture_get_body_func=lambda cli_name: {
                "method": "get",
                "params": {},  # never sends FieldNames → not exercised
            },
        )

        assert schema_gate["schema_parity_ok"] is False
        assert schema_gate["uncovered_get_groups"] == ["fake"]
        assert schema_gate["field_name_mismatches"] == []
        assert schema_gate["missing_field_name_params"] == []

    def test_schema_gate_flags_missing_common_fields_for_valid_inline_payload(
        self, monkeypatch
    ):
        """Enum-backed ``get`` commands must declare defaults in COMMON_FIELDS."""
        report_script = _load_coverage_report_script()
        monkeypatch.setattr(
            report_script,
            "CLI_TO_API_SERVICE",
            {"fake": "fake"},
        )
        monkeypatch.setattr(
            report_script,
            "get_cli_methods_for_service",
            lambda cli_name: {"get"},
        )
        monkeypatch.setattr(report_script, "COMMON_FIELDS", {})
        monkeypatch.setattr(report_script, "SCHEMA_GATE_WAIVERS", {})

        schema_gate = report_script.build_schema_gate(
            fetch_wsdl_func=lambda service: _wsdl_with_get_field_enum("Id", "Name"),
            capture_get_body_func=lambda cli_name: {
                "method": "get",
                "params": {"FieldNames": ["Id", "Name"]},
            },
        )

        assert schema_gate["schema_parity_ok"] is False
        assert schema_gate["field_name_mismatches"] == []
        assert schema_gate["missing_field_name_params"] == []
        assert schema_gate["uncovered_get_groups"] == []
        assert schema_gate["missing_common_fields"] == [
            {
                "cli_group": "fake",
                "api_service": "fake",
                "operation": "get",
                "expected_request_fields": ["FieldNames"],
            }
        ]

    def test_schema_gate_validates_non_get_fieldname_operation(self, monkeypatch):
        """FieldNames validation is not limited to ``get`` operations."""
        report_script = _load_coverage_report_script()
        monkeypatch.setattr(
            report_script,
            "CLI_TO_API_SERVICE",
            {"keywordsresearch": "keywordsresearch"},
        )
        monkeypatch.setattr(
            report_script,
            "get_cli_methods_for_service",
            lambda cli_name: {"hasSearchVolume"},
        )
        monkeypatch.setattr(
            report_script,
            "COMMON_FIELDS",
            {"keywordsresearch": ["Keyword", "Bogus"]},
        )

        schema_gate = report_script.build_schema_gate(
            capture_get_body_func=lambda cli_name, operation: {
                "method": operation,
                "params": {"FieldNames": ["Keyword"]},
            },
        )

        assert schema_gate["schema_parity_ok"] is False
        assert schema_gate["field_name_mismatches"] == [
            {
                "cli_group": "keywordsresearch",
                "api_service": "keywordsresearch",
                "operation": "hasSearchVolume",
                "request_field": "FieldNames",
                "enum_type": "HasSearchVolumeFieldEnum",
                "invalid_values": ["Bogus"],
                "actual_values": ["Keyword", "Bogus"],
                "source": "COMMON_FIELDS",
                "resource": "keywordsresearch",
            }
        ]

    def test_schema_gate_waiver_required_when_no_field_enum(self, monkeypatch):
        """Service with no FieldEnum in WSDL must be explicitly waived."""
        report_script = _load_coverage_report_script()
        # Use real dictionaries WSDL: it has a get operation but no *FieldEnum.
        monkeypatch.setattr(
            report_script, "CLI_TO_API_SERVICE", {"fake": "dictionaries"}
        )
        monkeypatch.setattr(
            report_script,
            "get_cli_methods_for_service",
            lambda cli_name: {"get"},
        )
        monkeypatch.setattr(report_script, "COMMON_FIELDS", {})

        # Without waiver → uncovered
        monkeypatch.setattr(report_script, "SCHEMA_GATE_WAIVERS", {})
        gate_no_waiver = report_script.build_schema_gate(
            capture_get_body_func=lambda cli: {"method": "get", "params": {}},
        )
        assert gate_no_waiver["schema_parity_ok"] is False
        assert "fake" in gate_no_waiver["uncovered_get_groups"]

        # With waiver → passes
        monkeypatch.setattr(report_script, "SCHEMA_GATE_WAIVERS", {"fake": "no enum"})
        gate_waived = report_script.build_schema_gate(
            capture_get_body_func=lambda cli: {"method": "get", "params": {}},
        )
        assert gate_waived["schema_parity_ok"] is True
        assert gate_waived["uncovered_get_groups"] == []

    def test_schema_gate_flags_stale_waiver(self, monkeypatch):
        """A waiver for a service that DOES have FieldEnum is misuse."""
        report_script = _load_coverage_report_script()
        monkeypatch.setattr(report_script, "CLI_TO_API_SERVICE", {"fake": "fake"})
        monkeypatch.setattr(
            report_script,
            "get_cli_methods_for_service",
            lambda cli_name: {"get"},
        )
        monkeypatch.setattr(report_script, "COMMON_FIELDS", {})
        monkeypatch.setattr(report_script, "SCHEMA_GATE_WAIVERS", {"fake": "stale"})

        schema_gate = report_script.build_schema_gate(
            fetch_wsdl_func=lambda s: _wsdl_with_get_field_enum("Id", "Name"),
            capture_get_body_func=lambda cli: {
                "method": "get",
                "params": {"FieldNames": ["Id"]},
            },
        )
        assert schema_gate["schema_parity_ok"] is False
        assert schema_gate["waiver_misuse"] == ["fake"]

    def test_schema_gate_flags_missing_common_field_name_params(self, monkeypatch):
        """Multi-FieldNames defaults must all appear in the command payload."""
        report_script = _load_coverage_report_script()
        monkeypatch.setattr(report_script, "CLI_TO_API_SERVICE", {"fake": "fake"})
        monkeypatch.setattr(
            report_script,
            "get_cli_methods_for_service",
            lambda cli_name: {"get"},
        )
        monkeypatch.setattr(
            report_script,
            "COMMON_FIELDS",
            {
                "fake": {
                    "FieldNames": ["Id"],
                    "SearchFieldNames": ["Bid"],
                    "NetworkFieldNames": ["Bid"],
                }
            },
        )

        schema_gate = report_script.build_schema_gate(
            fetch_wsdl_func=lambda service: _wsdl_with_get_field_enums(
                {
                    "FieldNames": ["Id"],
                    "SearchFieldNames": ["Bid"],
                    "NetworkFieldNames": ["Bid"],
                }
            ),
            capture_get_body_func=lambda cli_name: {
                "method": "get",
                "params": {"FieldNames": ["Id"]},
            },
        )

        assert schema_gate["schema_parity_ok"] is False
        assert schema_gate["field_name_mismatches"] == []
        assert schema_gate["missing_field_name_params"] == [
            {
                "cli_group": "fake",
                "api_service": "fake",
                "operation": "get",
                "missing_params": ["NetworkFieldNames", "SearchFieldNames"],
            }
        ]

    def test_schema_gate_validates_common_fields_even_when_payload_is_valid(
        self, monkeypatch
    ):
        """Invalid ``COMMON_FIELDS`` values fail even if captured wire is clean."""
        report_script = _load_coverage_report_script()
        monkeypatch.setattr(report_script, "CLI_TO_API_SERVICE", {"fake": "fake"})
        monkeypatch.setattr(
            report_script,
            "get_cli_methods_for_service",
            lambda cli_name: {"get"},
        )
        monkeypatch.setattr(
            report_script,
            "COMMON_FIELDS",
            {"fake": {"FieldNames": ["Id", "Bogus"], "TextAdFieldNames": ["Title"]}},
        )

        schema_gate = report_script.build_schema_gate(
            fetch_wsdl_func=lambda service: _wsdl_with_get_field_enums(
                {
                    "FieldNames": ["Id"],
                    "TextAdFieldNames": ["Title"],
                }
            ),
            capture_get_body_func=lambda cli_name: {
                "method": "get",
                "params": {
                    "FieldNames": ["Id"],
                    "TextAdFieldNames": ["Title"],
                },
            },
        )

        assert schema_gate["schema_parity_ok"] is False
        assert schema_gate["missing_field_name_params"] == []
        assert schema_gate["field_name_mismatches"] == [
            {
                "cli_group": "fake",
                "api_service": "fake",
                "operation": "get",
                "request_field": "FieldNames",
                "enum_type": "FakeFieldEnum",
                "invalid_values": ["Bogus"],
                "actual_values": ["Id", "Bogus"],
                "source": "COMMON_FIELDS",
                "resource": "fake",
            }
        ]

    def test_schema_gate_validates_api_service_keyed_common_fields(self, monkeypatch):
        """``COMMON_FIELDS`` entries keyed by API service are validated too."""
        report_script = _load_coverage_report_script()
        monkeypatch.setattr(
            report_script,
            "CLI_TO_API_SERVICE",
            {"retargeting": "retargetinglists"},
        )
        monkeypatch.setattr(
            report_script,
            "get_cli_methods_for_service",
            lambda cli_name: {"get"},
        )
        monkeypatch.setattr(
            report_script,
            "COMMON_FIELDS",
            {"retargetinglists": ["Id", "Bogus"]},
        )

        schema_gate = report_script.build_schema_gate(
            fetch_wsdl_func=lambda service: _wsdl_with_get_field_enum("Id", "Name"),
            capture_get_body_func=lambda cli_name: {
                "method": "get",
                "params": {"FieldNames": ["Id"]},
            },
        )

        assert schema_gate["schema_parity_ok"] is False
        assert schema_gate["field_name_mismatches"] == [
            {
                "cli_group": "retargeting",
                "api_service": "retargetinglists",
                "operation": "get",
                "request_field": "FieldNames",
                "enum_type": "FakeFieldEnum",
                "invalid_values": ["Bogus"],
                "actual_values": ["Id", "Bogus"],
                "source": "COMMON_FIELDS",
                "resource": "retargetinglists",
            }
        ]

    def test_schema_gate_flags_orphan_common_fields_keys(self, monkeypatch):
        """Typo in COMMON_FIELDS key fails the gate as orphan."""
        report_script = _load_coverage_report_script()
        monkeypatch.setattr(report_script, "CLI_TO_API_SERVICE", {"fake": "fake"})
        monkeypatch.setattr(
            report_script,
            "get_cli_methods_for_service",
            lambda cli_name: {"get"},
        )
        # 'fake' matches CLI group; 'typoed_resource' matches nothing.
        monkeypatch.setattr(
            report_script,
            "COMMON_FIELDS",
            {"fake": ["Id"], "typoed_resource": ["Whatever"]},
        )

        schema_gate = report_script.build_schema_gate(
            fetch_wsdl_func=lambda service: _wsdl_with_get_field_enum("Id", "Name"),
            capture_get_body_func=lambda cli_name, operation: {
                "method": operation,
                "params": {"FieldNames": ["Id"]},
            },
        )

        assert schema_gate["schema_parity_ok"] is False
        assert schema_gate["orphan_common_fields"] == ["typoed_resource"]
        assert schema_gate["field_name_mismatches"] == []

    def test_schema_gate_dedupes_common_fields_and_wire_payload_mismatches(
        self, monkeypatch
    ):
        """Invalid value flagged in COMMON_FIELDS is not also reported from wire."""
        report_script = _load_coverage_report_script()
        monkeypatch.setattr(report_script, "CLI_TO_API_SERVICE", {"fake": "fake"})
        monkeypatch.setattr(
            report_script,
            "get_cli_methods_for_service",
            lambda cli_name: {"get"},
        )
        monkeypatch.setattr(
            report_script,
            "COMMON_FIELDS",
            {"fake": ["Id", "Bogus"]},
        )

        schema_gate = report_script.build_schema_gate(
            fetch_wsdl_func=lambda service: _wsdl_with_get_field_enum("Id", "Name"),
            # Wire payload echoes the invalid COMMON_FIELDS value.
            capture_get_body_func=lambda cli_name, operation: {
                "method": operation,
                "params": {"FieldNames": ["Id", "Bogus"]},
            },
        )

        assert schema_gate["schema_parity_ok"] is False
        assert len(schema_gate["field_name_mismatches"]) == 1
        assert schema_gate["field_name_mismatches"][0]["source"] == "COMMON_FIELDS"
        assert schema_gate["field_name_mismatches"][0]["invalid_values"] == ["Bogus"]

    def test_capture_operation_body_does_not_swallow_internal_typeerror(self):
        """Internal TypeError must surface, not be retried as arity mismatch."""
        report_script = _load_coverage_report_script()
        call_count = {"two_arg": 0, "one_arg": 0}

        def bad_two_arg_capture(cli_name, operation):
            call_count["two_arg"] += 1
            raise TypeError("boom from inside")

        def bad_one_arg_capture(cli_name):
            call_count["one_arg"] += 1
            raise TypeError("boom from inside one-arg")

        # Two-arg signature → arity check passes, no fallback re-call.
        with pytest.raises(TypeError, match="boom from inside"):
            report_script._capture_operation_body(bad_two_arg_capture, "fake", "get")
        assert call_count["two_arg"] == 1  # exactly one call, no silent retry

        # One-arg signature on non-get operation must raise, not silently fall
        # back to one-arg call (which would lose the operation context).
        with pytest.raises(TypeError):
            report_script._capture_operation_body(bad_one_arg_capture, "fake", "set")

        # One-arg on get → falls back to single-arg call (legacy compat).
        call_count["one_arg"] = 0
        with pytest.raises(TypeError, match="one-arg"):
            report_script._capture_operation_body(bad_one_arg_capture, "fake", "get")
        assert call_count["one_arg"] == 1

    def test_schema_gate_reports_invalid_default_fieldname(self, monkeypatch):
        report_script = _load_coverage_report_script()
        monkeypatch.setattr(report_script, "CLI_TO_API_SERVICE", {"fake": "fake"})
        monkeypatch.setattr(
            report_script,
            "get_cli_methods_for_service",
            lambda cli_name: {"get"},
        )
        monkeypatch.setattr(report_script, "COMMON_FIELDS", {})

        schema_gate = report_script.build_schema_gate(
            fetch_wsdl_func=lambda service: _wsdl_with_get_field_enum("Id", "Name"),
            capture_get_body_func=lambda cli_name: {
                "method": "get",
                "params": {"FieldNames": ["Id", "Bogus"]},
            },
        )

        assert schema_gate["schema_parity_ok"] is False
        assert schema_gate["capture_errors"] == []
        assert schema_gate["field_name_mismatches"] == [
            {
                "cli_group": "fake",
                "api_service": "fake",
                "operation": "get",
                "request_field": "FieldNames",
                "enum_type": "FakeFieldEnum",
                "invalid_values": ["Bogus"],
                "actual_values": ["Id", "Bogus"],
                "source": "wire_payload",
                "resource": "fake",
            }
        ]

    def test_api_coverage_report_exposes_live_model_gaps(self, monkeypatch):
        """Report must distinguish declared parity from live-discovered gaps."""
        report_script = _load_coverage_report_script()

        monkeypatch.setattr(
            report_script,
            "CLI_TO_API_SERVICE",
            {"campaigns": "campaigns"},
        )
        monkeypatch.setattr(
            report_script,
            "LIVE_DISCOVERED_API_SERVICES",
            ["campaigns", "dynamicfeedadtargets", "strategies"],
            raising=False,
        )
        monkeypatch.setattr(
            report_script,
            "get_cli_methods_for_service",
            lambda cli_name: {"get"},
        )

        def fake_fetch_wsdl(service, use_cache=True):
            return {
                "campaigns": _wsdl_with_operations("get"),
                "dynamicfeedadtargets": _wsdl_with_operations(
                    "add", "delete", "get", "resume", "setBids", "suspend"
                ),
                "strategies": _wsdl_with_operations(
                    "add", "archive", "get", "unarchive", "update"
                ),
            }[service]

        report = report_script.build_report(fetch_wsdl_func=fake_fetch_wsdl)

        assert report["summary"]["strict_parity_ok"] is True
        assert report["summary"]["live_model_parity_ok"] is False
        assert report["model_gaps"]["declared_wsdl_services_count"] == 1
        assert report["model_gaps"]["live_discovered_services_count"] == 3
        assert report["model_gaps"]["live_model_gap_count"] == 2
        assert report["model_gaps"]["live_discovered_missing_services"] == [
            {
                "api_service": "dynamicfeedadtargets",
                "api_methods": [
                    "add",
                    "delete",
                    "get",
                    "resume",
                    "setBids",
                    "suspend",
                ],
            },
            {
                "api_service": "strategies",
                "api_methods": [
                    "add",
                    "archive",
                    "get",
                    "unarchive",
                    "update",
                ],
            },
        ]
        assert report["model_gaps"]["live_discovered_missing_methods"] == 11

    def test_reports_get_cli_skip_report_summary_forwarded(self, monkeypatch):
        """--skip-report-summary must reach create_client as skip_report_summary=True."""
        captured = {}
        reports_module = importlib.import_module("direct_cli.commands.reports")

        class _FakeResponse:
            columns = ["Date"]

            def __call__(self):
                return self

            def to_dicts(self):
                return [{"Date": "2026-01-01"}]

            def to_values(self):
                return [["2026-01-01"]]

        class _FakeReports:
            def post(self, data):
                return _FakeResponse()

        class _FakeClient:
            def reports(self):
                return _FakeReports()

        def _fake_create_client(**kwargs):
            captured["kwargs"] = kwargs
            return _FakeClient()

        monkeypatch.setattr(reports_module, "create_client", _fake_create_client)

        result = CliRunner().invoke(
            cli,
            [
                "reports",
                "get",
                "--type",
                "campaign_performance_report",
                "--from",
                "2026-01-01",
                "--to",
                "2026-01-31",
                "--name",
                "Test",
                "--fields",
                "Date",
                "--skip-report-summary",
            ],
        )
        assert result.exit_code == 0, result.output
        assert captured["kwargs"]["skip_report_summary"] is True

    def test_reports_get_cli_include_vat_false_forwarded(self, monkeypatch):
        """--no-include-vat must produce IncludeVAT=NO in request body."""
        captured = {}
        reports_module = importlib.import_module("direct_cli.commands.reports")

        class _FakeResponse:
            columns = ["Date"]

            def __call__(self):
                return self

            def to_dicts(self):
                return [{"Date": "2026-01-01"}]

            def to_values(self):
                return [["2026-01-01"]]

        class _FakeReports:
            def post(self, data):
                captured["body"] = data
                return _FakeResponse()

        class _FakeClient:
            def reports(self):
                return _FakeReports()

        monkeypatch.setattr(reports_module, "create_client", lambda **_: _FakeClient())

        result = CliRunner().invoke(
            cli,
            [
                "reports",
                "get",
                "--type",
                "campaign_performance_report",
                "--from",
                "2026-01-01",
                "--to",
                "2026-01-31",
                "--name",
                "Test",
                "--fields",
                "Date",
                "--no-include-vat",
            ],
        )
        assert result.exit_code == 0, result.output
        assert captured["body"]["params"]["IncludeVAT"] == "NO"

    def test_reports_get_cli_include_discount_false_forwarded(self, monkeypatch):
        """--no-include-discount must produce IncludeDiscount=NO in request body."""
        captured = {}
        reports_module = importlib.import_module("direct_cli.commands.reports")

        class _FakeResponse:
            columns = ["Date"]

            def __call__(self):
                return self

            def to_dicts(self):
                return [{"Date": "2026-01-01"}]

            def to_values(self):
                return [["2026-01-01"]]

        class _FakeReports:
            def post(self, data):
                captured["body"] = data
                return _FakeResponse()

        class _FakeClient:
            def reports(self):
                return _FakeReports()

        monkeypatch.setattr(reports_module, "create_client", lambda **_: _FakeClient())

        result = CliRunner().invoke(
            cli,
            [
                "reports",
                "get",
                "--type",
                "campaign_performance_report",
                "--from",
                "2026-01-01",
                "--to",
                "2026-01-31",
                "--name",
                "Test",
                "--fields",
                "Date",
                "--no-include-discount",
            ],
        )
        assert result.exit_code == 0, result.output
        assert captured["body"]["params"]["IncludeDiscount"] == "NO"

    def test_runtime_deprecated_registry_shape(self):
        """Each entry must declare error_code, replacement, reason."""
        assert RUNTIME_DEPRECATED_METHODS, "registry must have at least one entry"
        for (group, method), meta in RUNTIME_DEPRECATED_METHODS.items():
            assert isinstance(group, str) and group
            assert isinstance(method, str) and method
            assert isinstance(meta, dict)
            assert isinstance(meta.get("error_code"), int)
            replacement = meta.get("replacement")
            assert replacement is None or (isinstance(replacement, str) and replacement)
            assert isinstance(meta.get("reason"), str) and meta["reason"]

    def test_runtime_deprecated_methods_block_invocation(self):
        """direct agencyclients add must exit non-zero with replacement hint."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "agencyclients",
                "add",
                "--login",
                "x",
                "--first-name",
                "A",
                "--last-name",
                "B",
                "--currency",
                "RUB",
            ],
        )
        assert result.exit_code != 0
        combined = result.output + (str(result.exception) if result.exception else "")
        assert "deprecated" in combined.lower() or "no longer" in combined.lower()
        assert "add-passport-organization" in combined

    def test_runtime_deprecated_methods_block_dry_run_too(self):
        """--dry-run must also be blocked (assertion runs first)."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "agencyclients",
                "add",
                "--login",
                "x",
                "--first-name",
                "A",
                "--last-name",
                "B",
                "--currency",
                "RUB",
                "--dry-run",
            ],
        )
        assert result.exit_code != 0
        combined = result.output + (str(result.exception) if result.exception else "")
        assert "add-passport-organization" in combined

    def test_schema_gate_flags_runtime_deprecated_without_cli_guard(self, monkeypatch):
        """A registry entry without a guarded Click command must fail the gate."""
        report_script = _load_coverage_report_script()
        # Fake registry pointing at a nonexistent command.
        fake_registry = {
            ("__nonexistent_group__", "__nonexistent_method__"): {
                "error_code": 9999,
                "replacement": "direct nothing",
                "reason": "test fixture",
            }
        }
        monkeypatch.setattr(report_script, "RUNTIME_DEPRECATED_METHODS", fake_registry)

        violations = report_script._validate_runtime_deprecated_methods(fake_registry)
        assert violations, "fake unguarded entry should produce a violation"
        assert violations[0]["cli_group"] == "__nonexistent_group__"
        assert violations[0]["reason"] == "CLI command not found"

    def test_schema_gate_flags_nested_payload_dry_run_failure(self, monkeypatch):
        """A payload smoke case whose dry-run fails must fail schema parity."""
        report_script = _load_coverage_report_script()
        monkeypatch.setattr(report_script, "CLI_TO_API_SERVICE", {})
        monkeypatch.setattr(report_script, "COMMON_FIELDS", {})
        payload_cases = [
            (
                "fake",
                "get",
                ["__missing_group__", "get"],
            )
        ]

        schema_gate = report_script.build_schema_gate(
            fetch_wsdl_func=lambda _service: _wsdl_with_operations("get"),
            nested_schema_payload_cases=payload_cases,
            nested_schema_exclusions={},
        )

        violations = schema_gate["nested_schema_violations"]
        assert violations
        assert violations[0]["kind"] == "dry_run_failed"
        assert schema_gate["schema_parity_ok"] is False

    def test_nested_payload_validator_flags_schema_resolution_error(self):
        """A schema resolver exception must be reported, not silently skipped."""
        report_script = _load_coverage_report_script()
        payload_cases = [
            (
                "bids",
                "set",
                [
                    "bids",
                    "set",
                    "--keyword-id",
                    "123",
                    "--bid",
                    "1500000",
                ],
            )
        ]

        def _raise_schema_error(_service):
            raise RuntimeError("schema unavailable")

        violations = report_script._validate_nested_schema_payloads(
            fetch_wsdl_func=_raise_schema_error,
            payload_cases=payload_cases,
            dry_run_payload_exclusions={},
        )

        assert violations
        assert violations[0]["kind"] == "schema_error"
        assert "schema unavailable" in violations[0]["error"]

    def test_runtime_deprecated_gate_rejects_parser_error_without_replacement(
        self, monkeypatch
    ):
        """Parser UsageError is not enough unless it is our replacement guard."""
        report_script = _load_coverage_report_script()
        fake_registry = {
            ("agencyclients", "add"): {
                "error_code": 3500,
                "replacement": "direct replacement-command",
                "reason": "test fixture",
            }
        }
        monkeypatch.setitem(
            report_script.RUNTIME_DEPRECATED_CAPTURE_FIXTURES,
            ("agencyclients", "add"),
            ["agencyclients", "add", "--bogus"],
        )

        violations = report_script._validate_runtime_deprecated_methods(fake_registry)

        assert violations
        assert {violation["mode"] for violation in violations} == {
            "normal",
            "dry_run",
        }
        assert all(
            violation["reason"] == "UsageError did not include replacement hint"
            for violation in violations
        )

    def test_imported_xsd_cache_matches_registry(self):
        """Every IMPORTED_XSD_REGISTRY namespace has a cached file (and vice versa)."""
        cache_dir = CACHE_DIR / "imports"
        assert cache_dir.is_dir(), f"imports cache directory missing: {cache_dir}"
        cached_files = {p.name for p in cache_dir.glob("*.xsd")}
        registered_files = set(IMPORTED_XSD_REGISTRY.values())
        assert cached_files == registered_files, (
            "Imported XSD cache drift detected.\n"
            f"Missing files: {sorted(registered_files - cached_files)}\n"
            f"Orphan files: {sorted(cached_files - registered_files)}"
        )

    def test_get_operation_request_schema_resolves_imports(self):
        """agencyclients.add Notification (gc:NotificationAdd) must resolve nested fields."""
        schema = get_operation_request_schema(fetch_wsdl("agencyclients"), "add")
        notification = next(
            (f for f in schema["fields"] if f["name"] == "Notification"), None
        )
        assert notification is not None, "Notification field missing"
        nested_names = {item["name"] for item in notification["item_fields"]}
        assert {
            "Email",
            "Lang",
            "EmailSubscriptions",
        } <= nested_names, (
            f"Imported gc:NotificationAdd nested fields missing: {nested_names}"
        )

    def test_get_operation_request_schema_resolves_extension_base_fields(self):
        """clients.update Clients[].* must include inherited base-type fields."""
        schema = get_operation_request_schema(fetch_wsdl("clients"), "update")
        clients_field = next(
            (f for f in schema["fields"] if f["name"] == "Clients"), None
        )
        assert clients_field is not None, "Clients field missing in update schema"
        base_field_names = {it["name"] for it in clients_field["item_fields"]}
        # Notification + Settings come from gc:ClientUpdateItem extension; if
        # the resolver fails to walk extension/@base, item_fields is small or
        # empty and the gate would silently miss invalid keys.
        assert {"Notification", "Settings"} <= base_field_names, (
            f"Inherited extension/@base fields missing from item_fields: "
            f"{base_field_names}"
        )

    def test_get_operation_request_schema_resolves_adextensiontypes_import(self):
        """adextensions.add AdExtensions[].Callout resolves imported ext:Callout."""
        schema = get_operation_request_schema(fetch_wsdl("adextensions"), "add")
        adextensions = next(
            (f for f in schema["fields"] if f["name"] == "AdExtensions"), None
        )
        assert adextensions is not None, "AdExtensions field missing"
        callout = next(
            (f for f in adextensions["item_fields"] if f["name"] == "Callout"),
            None,
        )
        assert callout is not None, "AdExtensions[].Callout field missing"
        callout_fields = {item["name"] for item in callout["item_fields"]}
        assert "CalloutText" in callout_fields

    def test_smoke_probes_advideo_returns_none_without_credentials(self, monkeypatch):
        """advideo_probe_id must gracefully return None on auth/network failure."""
        from direct_cli import _smoke_probes

        # Force create_client to raise; advideo_probe_id should still return None.
        def _raise(**_):
            raise RuntimeError("no credentials")

        monkeypatch.setattr(_smoke_probes, "create_client", _raise)
        monkeypatch.delenv("YANDEX_DIRECT_TEST_ADVIDEO_ID", raising=False)

        result = _smoke_probes.advideo_probe_id()
        assert result is None

    def test_payload_cases_validate_nested_imported_fields(self):
        """find_nested_schema_violations flags unknown keys in imported nested types."""
        schema = get_operation_request_schema(fetch_wsdl("agencyclients"), "add")
        # Synthetic body: valid top-level params + bogus nested key inside
        # the imported gc:NotificationAdd type.
        bad_body = {
            "params": {
                "Login": "x",
                "FirstName": "A",
                "LastName": "B",
                "Currency": "RUB",
                "Notification": {
                    "Email": "ops@example.com",
                    "Lang": "RU",
                    "BogusNestedKey": "should-be-flagged",
                },
            }
        }
        violations = find_nested_schema_violations(bad_body, schema)
        assert any(
            "BogusNestedKey" in v for v in violations
        ), f"Expected BogusNestedKey to be flagged, got: {violations}"


@pytest.mark.api_coverage
class TestReportsCoverage:
    """Tests for Reports API spec snapshot and CLI parity."""

    def test_reports_spec_urls_come_from_resource_mapping(self):
        """Reports docs URLs must be derived from the vendored resource mapping."""
        from direct_cli._vendor.tapi_yandex_direct.resource_mapping import (
            RESOURCE_MAPPING_V5,
        )
        from direct_cli.reports_coverage import REPORTS_SPEC_URLS

        docs_pages = RESOURCE_MAPPING_V5["reports"]["docs_pages"]
        assert REPORTS_SPEC_URLS == {
            "type": docs_pages["type"],
            "spec": docs_pages["period"],
            "fields-list": docs_pages["fields-list"],
            "headers": docs_pages["headers"],
        }
        assert all(not url.endswith(".html") for url in REPORTS_SPEC_URLS.values())

    def test_reports_cache_files_exist(self):
        """All 4 raw HTML files and spec.json must be committed."""
        from direct_cli.reports_coverage import REPORTS_CACHE_DIR

        raw_dir = REPORTS_CACHE_DIR / "raw"
        for fname in ["spec.html", "type.html", "fields-list.html", "headers.html"]:
            assert (raw_dir / fname).exists(), f"Missing cache file: raw/{fname}"
        assert (REPORTS_CACHE_DIR / "spec.json").exists(), "Missing spec.json"

    def test_reports_spec_parses_without_errors(self):
        """parse_reports_spec on cached HTML returns non-empty required sections."""
        from direct_cli.reports_coverage import fetch_reports_spec, parse_reports_spec

        raw = fetch_reports_spec(use_cache=True)
        spec = parse_reports_spec(raw)
        assert spec["report_types"], "report_types must not be empty"
        assert spec["date_range_types"], "date_range_types must not be empty"
        assert spec["processing_modes"], "processing_modes must not be empty"
        assert spec["request_headers"], "request_headers must not be empty"
        assert spec["field_compatibility"], "field_compatibility must not be empty"

    def test_cli_report_types_match_spec(self):
        """--type choices must match spec snapshot report_types."""
        from direct_cli.reports_coverage import load_cached_reports_spec
        from direct_cli.commands.reports import get as reports_get

        spec = load_cached_reports_spec()
        type_opt = next(
            (p for p in reports_get.params if p.name == "report_type"), None
        )
        assert type_opt is not None, "--type option not found"
        cli_choices = set(c.upper() for c in type_opt.type.choices)
        spec_types = set(spec["report_types"])
        assert cli_choices == spec_types, (
            f"CLI choices differ from spec.\n"
            f"CLI only: {sorted(cli_choices - spec_types)}\n"
            f"Spec only: {sorted(spec_types - cli_choices)}"
        )

    def test_cli_dry_run_flag_exists(self):
        """reports get must have --dry-run flag."""
        from direct_cli.commands.reports import get as reports_get

        names = {p.name for p in reports_get.params}
        assert "dry_run" in names, "--dry-run flag missing from reports get"

    def test_cli_processing_mode_flag_exists(self):
        """reports get must have --processing-mode flag with spec choices."""
        from direct_cli.reports_coverage import load_cached_reports_spec
        from direct_cli.commands.reports import get as reports_get

        spec = load_cached_reports_spec()
        opt = next((p for p in reports_get.params if p.name == "processing_mode"), None)
        assert opt is not None, "--processing-mode flag missing"
        cli_choices = set(opt.type.choices)
        spec_modes = set(spec["processing_modes"])
        assert (
            cli_choices == spec_modes
        ), f"--processing-mode choices differ: CLI={cli_choices}, spec={spec_modes}"

    def test_cli_request_headers_flags_exist(self):
        """CLI must expose flags for each request header from spec."""
        from direct_cli.commands.reports import get as reports_get

        expected_params = {
            "skip_report_header",
            "skip_column_header",
            "skip_report_summary",
            "return_money_in_micros",
            "language",
        }
        names = {p.name for p in reports_get.params}
        missing = expected_params - names
        assert not missing, f"Missing CLI flags: {missing}"

    def test_non_wsdl_reports_policy_updated(self):
        """NON_WSDL_SERVICE_POLICIES['reports'] must use spec-snapshot coverage."""
        from direct_cli.wsdl_coverage import NON_WSDL_SERVICE_POLICIES

        policy = NON_WSDL_SERVICE_POLICIES["reports"]
        assert (
            policy["coverage"] == "contract-tests+spec-snapshot"
        ), "reports policy must use 'contract-tests+spec-snapshot' coverage type"
        assert "spec_snapshot" in policy
        assert "drift_script" in policy
        assert "refresh_script" in policy


class TestReportsParseFilter:
    """Unit tests for _parse_filter helper."""

    def test_reports_parse_filter_basic(self):
        from direct_cli.commands.reports import _parse_filter

        result = _parse_filter("CampaignId:IN:1,2,3")
        assert result == {
            "Field": "CampaignId",
            "Operator": "IN",
            "Values": ["1", "2", "3"],
        }

    def test_reports_parse_filter_trims_whitespace(self):
        from direct_cli.commands.reports import _parse_filter

        result = _parse_filter("CampaignId : IN : 1 , 2 , 3")
        assert result == {
            "Field": "CampaignId",
            "Operator": "IN",
            "Values": ["1", "2", "3"],
        }

    def test_reports_parse_filter_single_value(self):
        from direct_cli.commands.reports import _parse_filter

        result = _parse_filter("Status:EQUALS:ENABLED")
        assert result == {
            "Field": "Status",
            "Operator": "EQUALS",
            "Values": ["ENABLED"],
        }

    def test_reports_parse_filter_invalid_format_raises(self):
        from direct_cli.commands.reports import _parse_filter

        with pytest.raises(ValueError, match="Field:Operator:Value"):
            _parse_filter("BadFormat")


class TestReportsParseOrderBy:
    """Unit tests for _parse_order_by helper."""

    def test_reports_parse_order_by_field_only(self):
        from direct_cli.commands.reports import _parse_order_by

        result = _parse_order_by("Clicks")
        assert result == {"Field": "Clicks"}

    def test_reports_parse_order_by_with_desc(self):
        from direct_cli.commands.reports import _parse_order_by

        result = _parse_order_by("Clicks:DESC")
        assert result == {"Field": "Clicks", "SortOrder": "DESC"}

    def test_reports_parse_order_by_case_insensitive(self):
        from direct_cli.commands.reports import _parse_order_by

        result = _parse_order_by("Clicks:desc")
        assert result == {"Field": "Clicks", "SortOrder": "DESC"}


class TestReportsBuildRequestExtra:
    """build_report_request scenarios not covered by TestApiCoverage."""

    def test_reports_request_builder_custom_filters(self):
        result = build_report_request(
            report_type="CAMPAIGN_PERFORMANCE_REPORT",
            date_from="2026-01-01",
            date_to="2026-01-31",
            name="Filter Report",
            fields="Date,CampaignId",
            filters=("CampaignId:IN:1,2",),
        )
        assert result["params"]["SelectionCriteria"]["Filter"] == [
            {"Field": "CampaignId", "Operator": "IN", "Values": ["1", "2"]}
        ]

    def test_reports_request_builder_filter_precedence_over_campaign_ids(self):
        result = build_report_request(
            report_type="CAMPAIGN_PERFORMANCE_REPORT",
            date_from="2026-01-01",
            date_to="2026-01-31",
            name="Precedence Report",
            fields="Date,CampaignId",
            campaign_ids="99,100",
            filters=("Status:EQUALS:ENABLED",),
        )
        # --filter wins; campaign_ids ignored
        assert result["params"]["SelectionCriteria"]["Filter"] == [
            {"Field": "Status", "Operator": "EQUALS", "Values": ["ENABLED"]}
        ]

    def test_reports_request_builder_with_order_by(self):
        result = build_report_request(
            report_type="CAMPAIGN_PERFORMANCE_REPORT",
            date_from="2026-01-01",
            date_to="2026-01-31",
            name="OrderBy Report",
            fields="Date,Clicks",
            order_by=("Clicks:DESC",),
        )
        assert result["params"]["OrderBy"] == [{"Field": "Clicks", "SortOrder": "DESC"}]

    def test_reports_request_builder_with_pagination(self):
        result = build_report_request(
            report_type="CAMPAIGN_PERFORMANCE_REPORT",
            date_from="2026-01-01",
            date_to="2026-01-31",
            name="Paginated Report",
            fields="Date,CampaignId",
            page_limit=50,
            page_offset=100,
        )
        assert result["params"]["Page"] == {"Limit": 50, "Offset": 100}

    def test_reports_request_builder_no_include_vat(self):
        result = build_report_request(
            report_type="CAMPAIGN_PERFORMANCE_REPORT",
            date_from="2026-01-01",
            date_to="2026-01-31",
            name="No VAT Report",
            fields="Date,Cost",
            include_vat=False,
        )
        assert result["params"]["IncludeVAT"] == "NO"

    def test_reports_request_builder_no_include_discount(self):
        result = build_report_request(
            report_type="CAMPAIGN_PERFORMANCE_REPORT",
            date_from="2026-01-01",
            date_to="2026-01-31",
            name="No Discount Report",
            fields="Date,Cost",
            include_discount=False,
        )
        assert result["params"]["IncludeDiscount"] == "NO"

    def test_reports_request_builder_custom_date_range_type(self):
        result = build_report_request(
            report_type="CAMPAIGN_PERFORMANCE_REPORT",
            date_from="2026-01-01",
            date_to="2026-01-31",
            name="Last 7 Days Report",
            fields="Date,CampaignId",
            date_range_type="LAST_7_DAYS",
        )
        assert result["params"]["DateRangeType"] == "LAST_7_DAYS"
