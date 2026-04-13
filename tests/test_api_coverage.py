"""
API coverage tests — verify CLI coverage against Yandex Direct API v5 WSDL.

Phase 1: For each CLI service, check that all WSDL operations are covered.
Phase 2: Detect new API services not yet covered by the CLI.
Phase 3: Validate dry-run payload shape against cached WSDL request schemas.
"""

import json
import importlib
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
    CLI_ALIAS_GROUPS,
    INTENTIONAL_EXTRA_METHODS,
    KNOWN_MISSING_SERVICES,
    NON_WSDL_SERVICE_POLICIES,
    fetch_wsdl,
    get_cli_methods_for_service,
    get_operation_request_schema,
    parse_wsdl_operations,
)

ALLOWED_EXTRA_METHODS = set(INTENTIONAL_EXTRA_METHODS)

DRY_RUN_PAYLOAD_EXCLUSIONS = {
    "adextensions.add": "Requires verbose resource-specific JSON already covered by command-level dry-run tests.",
    "adgroups.add": "Requires nested add payload fixtures; tracked separately from schema smoke coverage.",
    "adgroups.update": "Requires nested update payload fixtures; tracked separately from schema smoke coverage.",
    "adimages.add": "Requires file/image upload style JSON that is better covered by command tests.",
    "ads.add": "Requires large heterogeneous ad payload variants; covered by focused dry-run tests.",
    "ads.archive": "Lifecycle alias of the same request shape family as campaigns/keywords lifecycle commands.",
    "ads.get": "Read path with rich field-selection options; payload contract differs from mutating coverage focus.",
    "ads.list": "CLI alias of ads.get.",
    "ads.resume": "Lifecycle alias in the same request-shape family as covered resume/delete actions.",
    "ads.suspend": "Lifecycle alias in the same request-shape family as covered resume/delete actions.",
    "ads.unarchive": "Lifecycle alias in the same request-shape family as covered resume/delete actions.",
    "ads.update": "Requires large heterogeneous ad payload variants; covered by focused dry-run tests.",
    "advideos.add": "Requires media payload fixture not worth duplicating in generic schema smoke coverage.",
    "audiencetargets.resume": "Same simple Ids payload family as covered delete/set-bids actions.",
    "audiencetargets.suspend": "Same simple Ids payload family as covered delete/set-bids actions.",
    "bidmodifiers.add": "Requires modifier-type-specific nested payload fixtures.",
    "bidmodifiers.delete": "Helper/legacy surface; not part of strict WSDL parity claim.",
    "bidmodifiers.set": "Requires modifier-type-specific nested payload fixtures.",
    "bidmodifiers.toggle": "Intentional CLI helper without matching WSDL method.",
    "campaigns.add": "Requires campaign-type-specific payload variants; covered by focused dry-run tests.",
    "campaigns.suspend": "Same lifecycle payload family as covered campaigns.delete/archive/resume.",
    "campaigns.unarchive": "Same lifecycle payload family as covered campaigns.delete/archive/resume.",
    "campaigns.update": "Requires campaign-type-specific payload variants; covered by focused dry-run tests.",
    "dynamicads.add": "Requires dynamic ad payload fixture with nested asset fields.",
    "dynamicads.resume": "Same simple Ids payload family as covered delete/set-bids actions.",
    "dynamicads.suspend": "Same simple Ids payload family as covered delete/set-bids actions.",
    "feeds.add": "Current WSDL schema parser treats feed source variants like required siblings; keep covered by command-level dry-run tests.",
    "keywords.add": "Requires keyword/addition payload variants; covered by focused dry-run tests.",
    "keywords.archive": "Legacy helper command preserved for compatibility.",
    "keywords.resume": "Same simple Ids payload family as covered keywords.delete/suspend.",
    "keywords.unarchive": "Legacy helper command preserved for compatibility.",
    "keywords.update": "Requires keyword update payload variants; covered by focused dry-run tests.",
    "retargeting.add": "Requires retargeting list payload fixture with nested rules.",
    "smartadtargets.resume": "Same simple Ids payload family as covered delete/set-bids actions.",
    "smartadtargets.suspend": "Same simple Ids payload family as covered delete/set-bids actions.",
    "vcards.add": "Requires large contact-card payload fixture not needed for generic schema smoke coverage.",
    "reports.get": "Reports API uses a custom TSV endpoint; payload contract is covered by test_reports_request_builder_contract.",
}

PAYLOAD_CASES = [
    (
        "agencyclients",
        "add",
        [
            "agencyclients",
            "add",
            "--json",
            '{"Login":"client-login","FirstName":"Alice","LastName":"Smith","Currency":"RUB","Notification":{}}',
        ],
    ),
    (
        "agencyclients",
        "addPassportOrganization",
        [
            "agencyclients",
            "add-passport-organization",
            "--name",
            "Org",
            "--currency",
            "RUB",
            "--notification-json",
            '{}',
        ],
    ),
    (
        "agencyclients",
        "addPassportOrganizationMember",
        [
            "agencyclients",
            "add-passport-organization-member",
            "--passport-organization-login",
            "org-login",
            "--role",
            "CHIEF",
            "--send-invite-to-json",
            '{"Email":"user@example.com"}',
        ],
    ),
    (
        "agencyclients",
        "update",
        [
            "agencyclients",
            "update",
            "--client-id",
            "99",
            "--json",
            '{"Grants":[]}',
        ],
    ),
    (
        "audiencetargets",
        "add",
        [
            "audiencetargets",
            "add",
            "--adgroup-id",
            "100",
            "--retargeting-list-id",
            "200",
            "--bid",
            "12",
        ],
    ),
    (
        "audiencetargets",
        "setBids",
        [
            "audiencetargets",
            "set-bids",
            "--id",
            "10",
            "--context-bid",
            "5",
        ],
    ),
    (
        "bids",
        "set",
        [
            "bids",
            "set",
            "--keyword-id",
            "123",
            "--bid",
            "1.5",
        ],
    ),
    (
        "bids",
        "setAuto",
        [
            "bids",
            "set-auto",
            "--keyword-id",
            "123",
            "--scope",
            "SEARCH",
        ],
    ),
    (
        "clients",
        "update",
        [
            "clients",
            "update",
            "--client-id",
            "501",
            "--json",
            '{"Email":"user@example.com"}',
        ],
    ),
    (
        "creatives",
        "add",
        [
            "creatives",
            "add",
            "--json",
            '{"VideoExtensionCreative":{"VideoId":"video-id"}}',
        ],
    ),
    (
        "feeds",
        "update",
        [
            "feeds",
            "update",
            "--id",
            "18",
            "--name",
            "Renamed feed",
        ],
    ),
    (
        "dynamictextadtargets",
        "setBids",
        [
            "dynamicads",
            "set-bids",
            "--id",
            "10",
            "--bid",
            "3",
            "--context-bid",
            "2",
        ],
    ),
    (
        "keywordbids",
        "set",
        [
            "keywordbids",
            "set",
            "--keyword-id",
            "321",
            "--search-bid",
            "1.1",
            "--network-bid",
            "0.9",
        ],
    ),
    (
        "keywordbids",
        "setAuto",
        [
            "keywordbids",
            "set-auto",
            "--keyword-id",
            "321",
            "--json",
            '{"SearchByTrafficVolume":{"TargetTrafficVolume":100}}',
        ],
    ),
    (
        "negativekeywordsharedsets",
        "add",
        [
            "negativekeywordsharedsets",
            "add",
            "--name",
            "Shared negatives",
            "--keywords",
            "cheap,free",
        ],
    ),
    (
        "negativekeywordsharedsets",
        "update",
        [
            "negativekeywordsharedsets",
            "update",
            "--id",
            "19",
            "--keywords",
            "cheap,free",
        ],
    ),
    (
        "retargetinglists",
        "update",
        [
            "retargeting",
            "update",
            "--id",
            "55",
            "--json",
            '{"Name":"Renamed"}',
        ],
    ),
    (
        "sitelinks",
        "add",
        [
            "sitelinks",
            "add",
            "--links",
            '[{"Title":"Docs","Href":"https://example.com/docs"}]',
        ],
    ),
    (
        "smartadtargets",
        "add",
        [
            "smartadtargets",
            "add",
            "--adgroup-id",
            "77",
            "--json",
            '{"Name":"Audience A","Audience":"ALL_SEGMENTS"}',
        ],
    ),
    (
        "smartadtargets",
        "update",
        [
            "smartadtargets",
            "update",
            "--id",
            "66",
            "--json",
            '{"AverageCpc":1000000}',
        ],
    ),
    (
        "smartadtargets",
        "setBids",
        [
            "smartadtargets",
            "set-bids",
            "--id",
            "11",
            "--average-cpc",
            "1.5",
        ],
    ),
    (
        "campaigns",
        "delete",
        ["campaigns", "delete", "--id", "12"],
    ),
    (
        "campaigns",
        "archive",
        ["campaigns", "archive", "--id", "12"],
    ),
    (
        "campaigns",
        "resume",
        ["campaigns", "resume", "--id", "12"],
    ),
    (
        "ads",
        "delete",
        ["ads", "delete", "--id", "7"],
    ),
    (
        "ads",
        "moderate",
        ["ads", "moderate", "--id", "7"],
    ),
    (
        "keywords",
        "delete",
        ["keywords", "delete", "--id", "8"],
    ),
    (
        "keywords",
        "suspend",
        ["keywords", "suspend", "--id", "8"],
    ),
    (
        "adgroups",
        "delete",
        ["adgroups", "delete", "--id", "14"],
    ),
    (
        "adextensions",
        "delete",
        ["adextensions", "delete", "--id", "15"],
    ),
    (
        "adimages",
        "delete",
        ["adimages", "delete", "--hash", "image-hash"],
    ),
    (
        "audiencetargets",
        "delete",
        ["audiencetargets", "delete", "--id", "16"],
    ),
    (
        "dynamictextadtargets",
        "delete",
        ["dynamicads", "delete", "--id", "17"],
    ),
    (
        "feeds",
        "delete",
        ["feeds", "delete", "--id", "18"],
    ),
    (
        "negativekeywordsharedsets",
        "delete",
        ["negativekeywordsharedsets", "delete", "--id", "19"],
    ),
    (
        "retargetinglists",
        "delete",
        ["retargeting", "delete", "--id", "20"],
    ),
    (
        "sitelinks",
        "delete",
        ["sitelinks", "delete", "--id", "21"],
    ),
    (
        "smartadtargets",
        "delete",
        ["smartadtargets", "delete", "--id", "22"],
    ),
    (
        "vcards",
        "delete",
        ["vcards", "delete", "--id", "23"],
    ),
]

PAYLOAD_COVERED_COMMANDS = {f"{argv[0]}.{argv[1]}" for _, _, argv in PAYLOAD_CASES}


def _dry_run(*args: str) -> dict:
    result = CliRunner().invoke(cli, list(args) + ["--dry-run"])
    assert result.exit_code == 0, (
        f"command failed: direct {' '.join(args)} --dry-run\n"
        f"output: {result.output}\n"
        f"exception: {result.exception}"
    )
    return json.loads(result.output)


def _assert_body_matches_wsdl(body: dict, service: str, operation: str):
    # Coverage note: this validator checks top-level param names, required flags,
    # and one level of inline-type fields. Nested validation does NOT cover types
    # declared via <xsd:import> or fields inherited through xsd:extension — see
    # `get_operation_request_schema` docstring for details. For those shapes,
    # only the CLI-level dry-run command test guards correctness.
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
            assert isinstance(value, list), (
                f"{service}.{operation}.{field['name']} must be a list"
            )
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
                item["name"]
                for item in field["item_fields"]
                if item["min_occurs"] > 0
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
        cached = {
            path.stem for path in CACHE_DIR.glob("*.xml") if path.is_file()
        }
        expected = set(CANONICAL_API_SERVICES)
        assert cached == expected, (
            "WSDL cache drift detected.\n"
            f"Missing cache files: {sorted(expected - cached)}\n"
            f"Unexpected cache files: {sorted(cached - expected)}"
        )

    def test_alias_groups_resolve_to_real_cli_groups(self):
        for alias, target in sorted(CLI_ALIAS_GROUPS.items()):
            assert alias in cli.commands, f"Missing CLI alias group: {alias}"
            assert target in cli.commands, f"Missing target CLI group for alias: {target}"
            assert cli.commands[alias] is cli.commands[target], (
                f"Alias group {alias} does not resolve to the same Click group as {target}"
            )

    def test_non_wsdl_services_have_explicit_coverage_policy(self):
        for service_name, policy in sorted(NON_WSDL_SERVICE_POLICIES.items()):
            assert service_name in cli.commands, (
                f"Non-WSDL service {service_name} is missing from the CLI"
            )
            assert policy["coverage"] in ("contract-tests", "contract-tests+spec-snapshot"), (
                f"Unexpected coverage policy for non-WSDL service {service_name}: {policy}"
            )

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
            if group_name in CLI_ALIAS_GROUPS or not hasattr(group, "commands"):
                continue
            for cmd_name, cmd in sorted(group.commands.items()):
                if any(getattr(param, "name", None) == "dry_run" for param in cmd.params):
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
            ],
        )

        assert result.exit_code == 0, result.output
        assert captured["kwargs"]["processing_mode"] == "online"
        assert captured["kwargs"]["skip_report_header"] is True
        assert captured["kwargs"]["skip_column_header"] is True
        assert captured["kwargs"]["return_money_in_micros"] is True

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
        assert report["summary"]["missing_service_methods"] == 0
        assert report["summary"]["unexpected_service_methods"] == 0
        assert sorted(report["canonical_services"]) == CANONICAL_API_SERVICES


@pytest.mark.api_coverage
class TestReportsCoverage:
    """Tests for Reports API spec snapshot and CLI parity."""

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
        assert cli_choices == spec_modes, (
            f"--processing-mode choices differ: CLI={cli_choices}, spec={spec_modes}"
        )

    def test_cli_request_headers_flags_exist(self):
        """CLI must expose flags for each request header from spec."""
        from direct_cli.commands.reports import get as reports_get
        expected_params = {
            "skip_report_header", "skip_column_header",
            "skip_report_summary", "return_money_in_micros", "language",
        }
        names = {p.name for p in reports_get.params}
        missing = expected_params - names
        assert not missing, f"Missing CLI flags: {missing}"

    def test_non_wsdl_reports_policy_updated(self):
        """NON_WSDL_SERVICE_POLICIES['reports'] must use spec-snapshot coverage."""
        from direct_cli.wsdl_coverage import NON_WSDL_SERVICE_POLICIES
        policy = NON_WSDL_SERVICE_POLICIES["reports"]
        assert policy["coverage"] == "contract-tests+spec-snapshot", (
            "reports policy must use 'contract-tests+spec-snapshot' coverage type"
        )
        assert "spec_snapshot" in policy
        assert "drift_script" in policy
        assert "refresh_script" in policy
