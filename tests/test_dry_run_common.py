"""Cross-cutting dry-run tests: generic ``get`` semantics, reports, micro-rubles
validation and API error-hint enrichment.

Split out of the historical monolithic ``tests/test_dry_run.py`` (issue #604).
See :mod:`tests.test_dry_run_shared` for the shared invocation helpers and
``tests/test_dry_run.py`` for the rationale behind the whole suite.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner, Result

from direct_cli.cli import cli
from tests.test_dry_run_shared import _dry_run, _failing_run, _read_dry_run, _rejected


def test_make_get_command_dry_run_needs_no_credentials():
    """``make_get_command`` builds the client *after* the ``--dry-run`` guard
    (same as the lifecycle factory and CLAUDE.md's "print request JSON without
    calling the API"), so a migrated ``get --dry-run`` prints its payload with
    no credentials configured. ``_dry_run`` invokes with an empty env and
    asserts exit code 0, so it fails if credential resolution creeps back in.
    """
    for argv in (
        ["advideos", "get", "--ids", "1"],
        ["businesses", "get"],
        ["vcards", "get"],
        ["negativekeywordsharedsets", "get"],
        ["turbopages", "get"],
    ):
        body = _dry_run(*argv)
        assert body["method"] == "get", argv


def test_get_selection_criteria_new_typed_flags_payloads():
    """Focused payload coverage for WSDL SelectionCriteria flags added for #146."""
    cases = [
        (
            (
                "adextensions",
                "get",
                "--states",
                "ON",
                "--statuses",
                "ACCEPTED",
                "--modified-since",
                "2026-04-14T00:00:00",
            ),
            {
                "States": ["ON"],
                "Statuses": ["ACCEPTED"],
                "ModifiedSince": "2026-04-14T00:00:00",
            },
        ),
        (
            (
                "adgroups",
                "get",
                "--statuses",
                "ACCEPTED",
                "--tag-ids",
                "1,2",
                "--tags",
                "a,b",
                "--app-icon-statuses",
                "ACCEPTED",
                "--serving-statuses",
                "ELIGIBLE",
                "--negative-keyword-shared-set-ids",
                "3,4",
            ),
            {
                "Statuses": ["ACCEPTED"],
                "TagIds": [1, 2],
                "Tags": ["a", "b"],
                "AppIconStatuses": ["ACCEPTED"],
                "ServingStatuses": ["ELIGIBLE"],
                "NegativeKeywordSharedSetIds": [3, 4],
            },
        ),
        (
            (
                "adimages",
                "get",
                "--image-hashes",
                "hash-a,hash-b",
                "--associated",
                "YES",
            ),
            {"AdImageHashes": ["hash-a", "hash-b"], "Associated": "YES"},
        ),
        (
            (
                "ads",
                "get",
                "--states",
                "ON",
                "--statuses",
                "ACCEPTED",
                "--types",
                "TEXT_AD",
                "--mobile",
                "NO",
                "--vcard-ids",
                "1",
                "--sitelink-set-ids",
                "2",
                "--image-hashes",
                "h",
                "--vcard-moderation-statuses",
                "ACCEPTED",
                "--sitelinks-moderation-statuses",
                "ACCEPTED",
                "--image-moderation-statuses",
                "ACCEPTED",
                "--adextension-ids",
                "3",
            ),
            {
                "States": ["ON"],
                "Statuses": ["ACCEPTED"],
                "Types": ["TEXT_AD"],
                "Mobile": "NO",
                "VCardIds": [1],
                "SitelinkSetIds": [2],
                "AdImageHashes": ["h"],
                "VCardModerationStatuses": ["ACCEPTED"],
                "SitelinksModerationStatuses": ["ACCEPTED"],
                "AdImageModerationStatuses": ["ACCEPTED"],
                "AdExtensionIds": [3],
            },
        ),
        (
            (
                "audiencetargets",
                "get",
                "--retargeting-list-ids",
                "10",
                "--interest-ids",
                "20",
                "--states",
                "ON",
            ),
            {"RetargetingListIds": [10], "InterestIds": [20], "States": ["ON"]},
        ),
        (
            ("bidmodifiers", "get", "--ids", "1", "--types", "MOBILE_ADJUSTMENT"),
            {"Ids": [1], "Types": ["MOBILE_ADJUSTMENT"]},
        ),
        (
            ("bids", "get", "--serving-statuses", "ELIGIBLE"),
            {"ServingStatuses": ["ELIGIBLE"]},
        ),
        (
            ("keywordbids", "get", "--serving-statuses", "ELIGIBLE"),
            {"ServingStatuses": ["ELIGIBLE"]},
        ),
        (
            (
                "campaigns",
                "get",
                "--states",
                "ON",
                "--statuses",
                "ACCEPTED",
                "--payment-statuses",
                "ALLOWED",
            ),
            {
                "States": ["ON"],
                "Statuses": ["ACCEPTED"],
                "StatusesPayment": ["ALLOWED"],
            },
        ),
        (
            ("creatives", "get", "--types", "VIDEO_EXTENSION_CREATIVE"),
            {"Types": ["VIDEO_EXTENSION_CREATIVE"]},
        ),
        (
            ("dynamicads", "get", "--campaign-ids", "1", "--states", "ON"),
            {"CampaignIds": [1], "States": ["ON"]},
        ),
        (
            ("dynamicfeedadtargets", "get", "--states", "ON"),
            {"States": ["ON"]},
        ),
        (
            (
                "keywords",
                "get",
                "--states",
                "ON",
                "--statuses",
                "ACCEPTED",
                "--modified-since",
                "2026-04-14T00:00:00",
                "--serving-statuses",
                "ELIGIBLE",
            ),
            {
                "States": ["ON"],
                "Statuses": ["ACCEPTED"],
                "ModifiedSince": "2026-04-14T00:00:00",
                "ServingStatuses": ["ELIGIBLE"],
            },
        ),
        (
            (
                "leads",
                "get",
                "--turbo-page-ids",
                "1",
                "--datetime-from",
                "2026-04-14T00:00:00",
                "--datetime-to",
                "2026-04-15T00:00:00",
            ),
            {
                "TurboPageIds": [1],
                "DateTimeFrom": "2026-04-14T00:00:00",
                "DateTimeTo": "2026-04-15T00:00:00",
            },
        ),
        (
            ("smartadtargets", "get", "--campaign-ids", "1", "--states", "ON"),
            {"CampaignIds": [1], "States": ["ON"]},
        ),
        (
            ("turbopages", "get", "--bound-with-hrefs", "https://example.com"),
            {"BoundWithHrefs": ["https://example.com"]},
        ),
    ]
    for argv, expected in cases:
        body = _read_dry_run(*argv)
        criteria = body["params"].get("SelectionCriteria", {})
        for key, value in expected.items():
            assert criteria[key] == value


def test_fields_whitespace_is_trimmed_after_csv_dedup():
    """B2a (#497): --fields with surrounding spaces now trims via parse_csv_strings.

    Before the dedup these field names were sent untrimmed (e.g. ``[" Name"]``);
    parse_csv_strings strips whitespace and drops empty items.
    """
    body = _read_dry_run("adimages", "get", "--fields", "Id, Name ")
    assert body["params"]["FieldNames"] == ["Id", "Name"]

    body = _read_dry_run(
        "bids", "get", "--campaign-ids", "1", "--fields", " Bid , CampaignId "
    )
    assert body["params"]["FieldNames"] == ["Bid", "CampaignId"]


def test_states_whitespace_is_trimmed_and_uppercased_after_csv_dedup():
    """B2a (#497): --states trims + uppercases via parse_csv_upper."""
    body = _read_dry_run(
        "dynamicads", "get", "--adgroup-ids", "1", "--states", " active , suspended "
    )
    assert body["params"]["SelectionCriteria"]["States"] == ["ACTIVE", "SUSPENDED"]


def test_get_status_and_statuses_are_mutually_exclusive():
    """Legacy --status must not be silently overwritten by --statuses."""
    for command in ("adgroups", "ads", "campaigns", "keywords"):
        result = CliRunner().invoke(
            cli,
            [
                command,
                "get",
                "--status",
                "ACCEPTED",
                "--statuses",
                "REJECTED",
                "--dry-run",
            ],
            env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
        )
        assert result.exit_code != 0
        assert "--status and --statuses are mutually exclusive" in result.output


def test_optional_ids_criteria_get_omits_empty_selection_criteria():
    for command in (
        "businesses",
        "feeds",
        "negativekeywordsharedsets",
        "sitelinks",
        "vcards",
        # retargeting GetRequest.SelectionCriteria is minOccurs=0 (optional), so
        # a no-filter call is valid and now omits the empty criteria — it also
        # gained --dry-run in #498 (B3c).
        "retargeting",
    ):
        body = _read_dry_run(command, "get")
        assert "SelectionCriteria" not in body["params"]


def _reports_get_result(*extra_args: str) -> Result:
    return CliRunner().invoke(
        cli,
        [
            "reports",
            "get",
            "--type",
            "CAMPAIGN_PERFORMANCE_REPORT",
            "--from",
            "2026-01-01",
            "--to",
            "2026-01-31",
            "--name",
            "Dry Run Report",
            "--fields",
            "Date,CampaignId,Clicks",
            *extra_args,
            "--dry-run",
        ],
    )


def test_reports_get_goals_and_attribution_models_dry_run():
    result = _reports_get_result(
        "--goals",
        "123,456",
        "--attribution-models",
        "fc,auto",
    )
    assert result.exit_code == 0, result.output
    body = json.loads(result.output)["body"]
    assert body["params"]["Goals"] == ["123", "456"]
    assert body["params"]["AttributionModels"] == ["FC", "AUTO"]


def test_reports_get_rejects_invalid_goals_and_attribution_models():
    invalid_goal = _reports_get_result("--goals", "0")
    assert invalid_goal.exit_code != 0
    assert "Invalid goal ID" in invalid_goal.output

    invalid_model = _reports_get_result("--attribution-models", "BAD")
    assert invalid_model.exit_code != 0
    assert "Invalid attribution model" in invalid_model.output


def test_reports_get_filter_validation_dry_run():
    invalid = _reports_get_result("--filter", "Goals:IN:123")
    assert invalid.exit_code != 0
    assert "not a filter field" in invalid.output

    valid = _reports_get_result("--filter", "Clicks:GREATER_THAN:0")
    assert valid.exit_code == 0, valid.output
    body = json.loads(valid.output)["body"]
    assert body["params"]["SelectionCriteria"]["Filter"] == [
        {"Field": "Clicks", "Operator": "GREATER_THAN", "Values": ["0"]}
    ]


def test_reports_get_type_rejects_unknown_value():
    """``reports get --type`` is validated by click.Choice against REPORT_TYPES.

    Regression guard for axisrow/direct-cli#25 — previously ``REPORT_TYPES``
    was defined at module level but never wired into the option, so
    typos like ``CAMPAING_REPORT`` silently reached the API.
    """
    result = CliRunner().invoke(
        cli,
        [
            "reports",
            "get",
            "--type",
            "CAMPAING_REPORT",
            "--from",
            "2026-01-01",
            "--to",
            "2026-01-31",
            "--name",
            "X",
            "--fields",
            "Date",
        ],
    )
    assert result.exit_code != 0
    assert "Invalid value for '--type'" in result.output


def test_reports_get_type_is_case_insensitive():
    """Valid enum spelling in lowercase is accepted.

    click.Choice(..., case_sensitive=False) on REPORT_TYPES normalizes
    the input — users can type ``campaign_performance_report``.
    """
    with patch("direct_cli.auth.get_active_profile", return_value=None):
        result = CliRunner(
            env={"YANDEX_DIRECT_TOKEN": "", "YANDEX_DIRECT_LOGIN": ""},
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
                "X",
                "--fields",
                "Date",
            ],
        )
    # Force a missing-token failure so this unit test cannot make a real
    # reports request when a developer/CI environment has credentials set.
    # What we care about is that Click's parameter parser did NOT reject
    # the lowercase enum value.
    assert "Invalid value for '--type'" not in result.output
    assert result.exit_code != 0


def test_reports_get_mode_option_removed():
    """The dead ``--mode`` option is no longer accepted.

    Regression guard for axisrow/direct-cli#25 — previously ``--mode``
    was declared with ``default="auto"`` and a helpful-looking help
    string, but the function body never read it; the underlying
    ``create_client`` hardcodes ``processing_mode="auto"``. Users
    passing ``--mode offline`` got zero effect. The option was
    removed so the dead code stops misleading callers.
    """
    result = CliRunner().invoke(
        cli,
        [
            "reports",
            "get",
            "--type",
            "CAMPAIGN_PERFORMANCE_REPORT",
            "--from",
            "2026-01-01",
            "--to",
            "2026-01-31",
            "--name",
            "X",
            "--fields",
            "Date",
            "--mode",
            "offline",
        ],
    )
    assert result.exit_code != 0
    assert "no such option" in result.output.lower() or "--mode" in result.output


_SELECTION_CRITERIA_REQUIRED_GET_COMMANDS = (
    "adgroups",
    "ads",
    "keywords",
    "strategies",
    "creatives",
    "dynamicads",
    "smartadtargets",
    "audiencetargets",
)


@pytest.mark.parametrize("command", _SELECTION_CRITERIA_REQUIRED_GET_COMMANDS)
def test_get_requires_selection_criteria(command):
    result = CliRunner().invoke(
        cli,
        [command, "get", "--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )
    assert result.exit_code != 0, (
        f"direct {command} get --dry-run unexpectedly succeeded with no filter\n"
        f"output: {result.output}"
    )
    # The guard is a Click UsageError (exit 2), not an API Abort (exit 1).
    assert result.exit_code == 2


@pytest.mark.parametrize("command", _SELECTION_CRITERIA_REQUIRED_GET_COMMANDS)
def test_get_with_filter_keeps_selection_criteria(command):
    # With a filter present the payload still carries SelectionCriteria — the
    # guard only rejects the empty case, the populated payload is unchanged.
    body = _read_dry_run(command, "get", "--ids", "1,2")
    assert body["params"]["SelectionCriteria"] == {"Ids": [1, 2]}


def test_reports_get_dry_run_outputs_request():
    """--dry-run prints headers + body with expected keys."""
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
            "Dry Run Report",
            "--fields",
            "Date,CampaignId",
            "--processing-mode",
            "online",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert "headers" in data
    assert "body" in data
    assert data["headers"]["processingMode"] == "online"
    assert data["headers"]["skipReportHeader"] == "true"
    assert data["headers"]["skipReportSummary"] == "true"
    body_params = data["body"]["params"]
    assert body_params["ReportType"] == "CAMPAIGN_PERFORMANCE_REPORT"
    assert body_params["DateRangeType"] == "CUSTOM_DATE"
    assert "SelectionCriteria" in body_params


def test_reports_get_dry_run_no_skip_header_summary_opt_out():
    """--no-skip-report-* omits default skip headers from dry-run output."""
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
            "Dry Run Report",
            "--fields",
            "Date,CampaignId",
            "--no-skip-report-header",
            "--no-skip-report-summary",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert "skipReportHeader" not in data["headers"]
    assert "skipReportSummary" not in data["headers"]
    assert "skipColumnHeader" not in data["headers"]


@pytest.mark.parametrize(
    "resource,flag,wsdl_key",
    [
        (
            "keywords",
            "--autotargeting-settings-brand-options-field-names",
            "AutotargetingSettingsBrandOptionsFieldNames",
        ),
        ("adgroups", "--smart-ad-group-field-names", "SmartAdGroupFieldNames"),
    ],
)
def test_get_empty_nested_field_names_precedes_criteria_limit(resource, flag, wsdl_key):
    """For the two ``get`` commands with BOTH criteria-limits and nested
    ``*FieldNames`` (keywords, adgroups), an over-limit array AND an empty nested
    CSV at once reports the nested error, not the array-limit error — pinning the
    make_get_command check order against the pre-factory hand-rolled order (#588).
    """
    over_limit = ",".join(str(i) for i in range(1, 12))  # 11 CampaignIds > limit 10
    result = CliRunner().invoke(
        cli,
        [resource, "get", "--campaign-ids", over_limit, flag, ",", "--dry-run"],
    )

    assert result.exit_code != 0
    assert (
        f"Provide a non-empty comma-separated {wsdl_key} list." in result.output
    ), f"{resource}: expected the nested error to win, got: {result.output}"


def test_micro_rubles_rejects_small_value():
    result = _failing_run("bids", "set", "--keyword-id", "1", "--bid", "15")
    assert result.exit_code != 0
    assert "seems too low for micro-rubles" in result.output
    assert "Did you mean 15000000?" in result.output


def test_micro_rubles_accepts_valid_value():
    body = _dry_run("bids", "set", "--keyword-id", "1", "--bid", "15000000")
    assert body["params"]["Bids"][0]["Bid"] == 15000000


def test_micro_rubles_rejects_float():
    result = _failing_run("bids", "set", "--keyword-id", "1", "--bid", "3.0")
    assert result.exit_code != 0


def test_micro_rubles_rejects_negative():
    result = _failing_run("bids", "set", "--keyword-id", "1", "--bid", "-1")
    assert result.exit_code != 0
    assert "non-negative" in result.output


def test_direct_money_flags_use_micro_rubles_only():
    forbidden_type = "RUBLES_TO_MICRO" + "_RUBLES"
    forbidden_snippets = (
        forbidden_type,
        'Decimal("' + "1000000" + '")',
        "human-readable " + "money",
        "converted to " + "API " + "long",
        "multiplied by " + "1,000,000",
    )
    root = Path(__file__).resolve().parents[1]

    for relative_path in (
        "direct_cli/commands/ads.py",
        "direct_cli/commands/campaigns.py",
        "direct_cli/utils.py",
    ):
        content = (root / relative_path).read_text()
        for snippet in forbidden_snippets:
            assert snippet not in content


def test_raise_for_api_result_errors_adds_8300_hint():
    from direct_cli.output import raise_for_api_result_errors, DirectAPIResultError

    data = {"Errors": [{"Code": 8300, "Message": "Operation cannot be performed"}]}
    with pytest.raises(DirectAPIResultError) as exc:
        raise_for_api_result_errors(data)
    msg = str(exc.value)
    assert "Code 8300 on delete/moderate" in msg
    assert "Status=UNKNOWN" in msg
    assert "archived/unarchived" in msg


def test_raise_for_api_result_errors_8300_hint_only_when_8300_present():
    from direct_cli.output import raise_for_api_result_errors, DirectAPIResultError

    data = {"Errors": [{"Code": 8000, "Message": "other"}]}
    with pytest.raises(DirectAPIResultError) as exc:
        raise_for_api_result_errors(data)
    assert "Code 8300" not in str(exc.value)


def test_raise_for_api_result_errors_8300_hint_has_no_url_literal():
    # CLAUDE.md: no URL literals outside the registry. The hint must not embed one.
    from direct_cli.output import raise_for_api_result_errors, DirectAPIResultError

    data = {"Errors": [{"Code": 8300, "Message": "x"}]}
    with pytest.raises(DirectAPIResultError) as exc:
        raise_for_api_result_errors(data)
    assert "https://" not in str(exc.value)


def test_raise_for_api_result_errors_adds_5005_adimagehash_hint():
    from direct_cli.output import raise_for_api_result_errors, DirectAPIResultError

    data = {
        "Errors": [
            {
                "Code": 5005,
                "Message": "Field set incorrectly",
                "Details": "adImageHash=<[<null>]>",
            }
        ]
    }
    with pytest.raises(DirectAPIResultError) as exc:
        raise_for_api_result_errors(data)
    msg = str(exc.value)
    assert "AdImageHash" in msg
    assert "--image-hash" in msg


def test_raise_for_api_result_errors_5005_hint_only_when_adimagehash_present():
    # 5005 is the generic "Field set incorrectly"; the AdImageHash hint must not
    # fire for an unrelated field.
    from direct_cli.output import raise_for_api_result_errors, DirectAPIResultError

    data = {
        "Errors": [
            {"Code": 5005, "Message": "Field set incorrectly", "Details": "Title=..."}
        ]
    }
    with pytest.raises(DirectAPIResultError) as exc:
        raise_for_api_result_errors(data)
    assert "--image-hash" not in str(exc.value)


def test_raise_for_api_result_errors_5005_hint_has_no_url_literal():
    # CLAUDE.md: no URL literals outside the registry. The hint must not embed one.
    from direct_cli.output import raise_for_api_result_errors, DirectAPIResultError

    data = {"Errors": [{"Code": 5005, "Details": "adImageHash=<[<null>]>"}]}
    with pytest.raises(DirectAPIResultError) as exc:
        raise_for_api_result_errors(data)
    assert "https://" not in str(exc.value)


_POSITIVE_ID_MUTATION_SELECTORS = [
    ("campaigns", "update", "--id"),
    ("feeds", "update", "--id"),
    ("strategies", "update", "--id"),
    ("retargeting", "update", "--id"),
    ("smartadtargets", "update", "--id"),
    ("smartadtargets", "add", "--adgroup-id"),
    ("negativekeywordsharedsets", "update", "--id"),
    ("audiencetargets", "add", "--adgroup-id"),
    ("dynamicads", "add", "--adgroup-id"),
    ("dynamicfeedadtargets", "add", "--adgroup-id"),
    ("vcards", "add", "--campaign-id"),
    ("keywords", "add", "--adgroup-id"),
    ("bidmodifiers", "set", "--id"),
    ("agencyclients", "update", "--client-id"),
]


_POSITIVE_ID_BID_SELECTORS = [
    ("bids", "set", "--campaign-id"),
    ("bids", "set", "--adgroup-id"),
    ("bids", "set", "--keyword-id"),
    ("bids", "set-auto", "--campaign-id"),
    ("bids", "set-auto", "--adgroup-id"),
    ("bids", "set-auto", "--keyword-id"),
    ("keywordbids", "set", "--campaign-id"),
    ("keywordbids", "set", "--adgroup-id"),
    ("keywordbids", "set", "--keyword-id"),
    ("keywordbids", "set-auto", "--campaign-id"),
    ("keywordbids", "set-auto", "--adgroup-id"),
    ("keywordbids", "set-auto", "--keyword-id"),
    ("smartadtargets", "set-bids", "--id"),
    ("smartadtargets", "set-bids", "--adgroup-id"),
    ("smartadtargets", "set-bids", "--campaign-id"),
    ("audiencetargets", "set-bids", "--id"),
    ("audiencetargets", "set-bids", "--adgroup-id"),
    ("audiencetargets", "set-bids", "--campaign-id"),
    ("dynamicads", "set-bids", "--id"),
    ("dynamicads", "set-bids", "--adgroup-id"),
    ("dynamicads", "set-bids", "--campaign-id"),
    ("dynamicfeedadtargets", "set-bids", "--id"),
    ("dynamicfeedadtargets", "set-bids", "--adgroup-id"),
    ("dynamicfeedadtargets", "set-bids", "--campaign-id"),
    ("bidmodifiers", "add", "--campaign-id"),
    ("bidmodifiers", "add", "--adgroup-id"),
]


@pytest.mark.parametrize("bad", ["0", "-1"])
@pytest.mark.parametrize(
    "resource,verb,flag",
    _POSITIVE_ID_MUTATION_SELECTORS + _POSITIVE_ID_BID_SELECTORS,
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_mutation_object_id_selector_rejects_non_positive(resource, verb, flag, bad):
    result = _rejected(resource, verb, flag, bad)
    assert result.exit_code == 2, result.output
    assert "is not in the range" in result.output
