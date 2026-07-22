"""Dry-run payload tests for ``bids``, ``keywordbids`` and ``bidmodifiers``.

Split out of the historical monolithic ``tests/test_dry_run.py`` (issue #604).
See :mod:`tests.test_dry_run_shared` for the shared invocation helpers and
``tests/test_dry_run.py`` for the rationale behind the whole suite.
"""

import pytest
from click.testing import CliRunner

from direct_cli.cli import cli
from tests.test_dry_run_shared import _dry_run, _ids_csv, _read_dry_run, _rejected


def test_bids_set_payload():
    body = _dry_run("bids", "set", "--keyword-id", "1", "--bid", "15000000")
    assert body["method"] == "set"
    bid = body["params"]["Bids"][0]
    assert bid == {"KeywordId": 1, "Bid": 15000000}


def test_bids_set_campaign_context_auto_priority_payload():
    body = _dry_run(
        "bids",
        "set",
        "--campaign-id",
        "123",
        "--context-bid",
        "9000000",
        "--autotargeting-search-bid-is-auto",
        "yes",
        "--priority",
        "high",
    )
    assert body["params"]["Bids"][0] == {
        "CampaignId": 123,
        "ContextBid": 9000000,
        "AutotargetingSearchBidIsAuto": "YES",
        "StrategyPriority": "HIGH",
    }


def test_bids_set_adgroup_context_payload():
    body = _dry_run(
        "bids",
        "set",
        "--adgroup-id",
        "456",
        "--context-bid",
        "7000000",
    )
    assert body["params"]["Bids"][0] == {"AdGroupId": 456, "ContextBid": 7000000}


def test_bids_set_requires_exactly_one_selector():
    result = CliRunner().invoke(
        cli,
        [
            "bids",
            "set",
            "--campaign-id",
            "1",
            "--keyword-id",
            "2",
            "--bid",
            "15000000",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "exactly one selector" in result.output


def test_keywordbids_set_search_and_network():
    body = _dry_run(
        "keywordbids",
        "set",
        "--keyword-id",
        "42",
        "--search-bid",
        "8000000",
        "--network-bid",
        "3000000",
    )
    assert body["method"] == "set"
    bid = body["params"]["KeywordBids"][0]
    assert bid == {
        "KeywordId": 42,
        "SearchBid": 8000000,
        "NetworkBid": 3000000,
    }


def test_keywordbids_set_campaign_auto_priority_payload():
    body = _dry_run(
        "keywordbids",
        "set",
        "--campaign-id",
        "123",
        "--autotargeting-search-bid-is-auto",
        "no",
        "--priority",
        "normal",
    )
    assert body["params"]["KeywordBids"][0] == {
        "CampaignId": 123,
        "AutotargetingSearchBidIsAuto": "NO",
        "StrategyPriority": "NORMAL",
    }


def test_keywordbids_set_adgroup_network_payload():
    body = _dry_run(
        "keywordbids",
        "set",
        "--adgroup-id",
        "456",
        "--network-bid",
        "3000000",
    )
    assert body["params"]["KeywordBids"][0] == {
        "AdGroupId": 456,
        "NetworkBid": 3000000,
    }


def test_keywordbids_set_requires_exactly_one_selector():
    result = CliRunner().invoke(
        cli,
        [
            "keywordbids",
            "set",
            "--campaign-id",
            "1",
            "--keyword-id",
            "2",
            "--search-bid",
            "15000000",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "exactly one selector" in result.output


def test_bidmodifiers_set_rejects_legacy_campaign_type_shape():
    result = _rejected(
        "bidmodifiers",
        "set",
        "--campaign-id",
        "1",
        "--type",
        "MOBILE_ADJUSTMENT",
        "--value",
        "150",
    )

    assert "legacy --campaign-id/--type shape is not supported" in result.output


def test_bidmodifiers_set_with_id_builds_correct_payload():
    """Correct API shape: ``--id N --value V`` builds ``{"Id": N, "BidModifier": V}``.

    This is the shape Yandex Direct's ``bidmodifiers/set`` actually
    accepts (the legacy ``CampaignId + Type`` shape is rejected with
    ``required field Id is omitted``).  Regression guard for
    axisrow/direct-cli#23 to make sure the --id path stays correct
    and doesn't leak CampaignId/Type.
    """
    body = _dry_run(
        "bidmodifiers",
        "set",
        "--id",
        "42",
        "--value",
        "150",
    )
    modifier = body["params"]["BidModifiers"][0]
    assert modifier == {"Id": 42, "BidModifier": 150}
    assert "CampaignId" not in modifier
    assert "Type" not in modifier


def test_bidmodifiers_set_id_and_legacy_flags_are_mutex():
    """Mixing --id with --campaign-id/--type is rejected up front.

    Legacy flags are now hidden + eagerly rejected by Click callback, so
    they fail before mutex evaluation. The legacy-shape error message
    still surfaces, which is the contract: legacy flags are never
    acceptable, even alongside the correct --id form.
    """
    result = CliRunner().invoke(
        cli,
        [
            "bidmodifiers",
            "set",
            "--id",
            "42",
            "--campaign-id",
            "1",
            "--type",
            "MOBILE_ADJUSTMENT",
            "--value",
            "150",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    combined = (result.output or "") + (
        str(result.exception) if result.exception else ""
    )
    assert "legacy --campaign-id/--type shape is not supported" in combined


def test_bidmodifiers_set_without_any_key_errors():
    """Neither --id nor the legacy pair → clear UsageError, not a broken payload."""
    result = CliRunner().invoke(
        cli,
        [
            "bidmodifiers",
            "set",
            "--value",
            "150",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    combined = (result.output or "") + (
        str(result.exception) if result.exception else ""
    )
    assert "Provide --id with --value" in combined


def test_bidmodifiers_add_mobile_uses_nested_object():
    body = _dry_run(
        "bidmodifiers",
        "add",
        "--campaign-id",
        "1",
        "--type",
        "MOBILE_ADJUSTMENT",
        "--value",
        "120",
    )
    assert body["method"] == "add"
    modifier = body["params"]["BidModifiers"][0]
    assert "Type" not in modifier
    assert modifier["CampaignId"] == 1
    assert modifier["MobileAdjustment"] == {"BidModifier": 120}


def test_bidmodifiers_add_mobile_operating_system_type():
    body = _dry_run(
        "bidmodifiers",
        "add",
        "--campaign-id",
        "1",
        "--type",
        "MOBILE_ADJUSTMENT",
        "--value",
        "120",
        "--operating-system-type",
        "ios",
    )

    modifier = body["params"]["BidModifiers"][0]
    assert modifier["MobileAdjustment"] == {
        "BidModifier": 120,
        "OperatingSystemType": "IOS",
    }


def test_bidmodifiers_add_tablet_operating_system_type():
    body = _dry_run(
        "bidmodifiers",
        "add",
        "--campaign-id",
        "1",
        "--type",
        "TABLET_ADJUSTMENT",
        "--value",
        "120",
        "--operating-system-type",
        "ANDROID",
    )

    modifier = body["params"]["BidModifiers"][0]
    assert modifier["TabletAdjustment"] == {
        "BidModifier": 120,
        "OperatingSystemType": "ANDROID",
    }


def test_bidmodifiers_add_rejects_incompatible_extra_flags():
    mobile_result = _rejected(
        "bidmodifiers",
        "add",
        "--campaign-id",
        "1",
        "--type",
        "MOBILE_ADJUSTMENT",
        "--value",
        "120",
        "--gender",
        "GENDER_MALE",
    )
    demographics_result = _rejected(
        "bidmodifiers",
        "add",
        "--campaign-id",
        "1",
        "--type",
        "DEMOGRAPHICS_ADJUSTMENT",
        "--value",
        "120",
        "--retargeting-condition-id",
        "123",
    )
    desktop_result = _rejected(
        "bidmodifiers",
        "add",
        "--campaign-id",
        "1",
        "--type",
        "DESKTOP_ADJUSTMENT",
        "--value",
        "120",
        "--operating-system-type",
        "IOS",
    )

    assert (
        "--gender is not compatible with --type MOBILE_ADJUSTMENT"
        in mobile_result.output
    )
    assert (
        "--retargeting-condition-id is not compatible with --type "
        "DEMOGRAPHICS_ADJUSTMENT"
    ) in demographics_result.output
    assert (
        "--operating-system-type is not compatible with --type DESKTOP_ADJUSTMENT"
    ) in desktop_result.output


def test_bidmodifiers_add_income_grade_uses_wsdl_grade_field():
    body = _dry_run(
        "bidmodifiers",
        "add",
        "--campaign-id",
        "1",
        "--type",
        "INCOME_GRADE_ADJUSTMENT",
        "--value",
        "120",
        "--income-grade",
        "HIGH",
    )

    modifier = body["params"]["BidModifiers"][0]
    assert modifier["IncomeGradeAdjustments"] == [{"BidModifier": 120, "Grade": "HIGH"}]


def test_bidmodifiers_add_smart_tv_uses_wsdl_subtype():
    body = _dry_run(
        "bidmodifiers",
        "add",
        "--campaign-id",
        "1",
        "--type",
        "SMART_TV_ADJUSTMENT",
        "--value",
        "120",
    )

    modifier = body["params"]["BidModifiers"][0]
    assert modifier["SmartTvAdjustment"] == {"BidModifier": 120}


class TestBidModifiersAddPluralFields:
    """WSDL BidModifierAddItem uses plural array fields for 5 adjustment types."""

    def test_demographics_plural(self):
        body = _dry_run(
            "bidmodifiers",
            "add",
            "--campaign-id",
            "123",
            "--type",
            "DEMOGRAPHICS_ADJUSTMENT",
            "--value",
            "150",
            "--gender",
            "GENDER_MALE",
            "--age",
            "AGE_25_34",
        )
        item = body["params"]["BidModifiers"][0]
        assert "DemographicsAdjustments" in item, f"got keys: {list(item.keys())}"
        assert "DemographicsAdjustment" not in item
        assert isinstance(item["DemographicsAdjustments"], list)
        assert item["DemographicsAdjustments"][0]["BidModifier"] == 150

    def test_retargeting_plural(self):
        body = _dry_run(
            "bidmodifiers",
            "add",
            "--campaign-id",
            "123",
            "--type",
            "RETARGETING_ADJUSTMENT",
            "--value",
            "120",
            "--retargeting-condition-id",
            "456",
        )
        item = body["params"]["BidModifiers"][0]
        assert "RetargetingAdjustments" in item, f"got keys: {list(item.keys())}"
        assert isinstance(item["RetargetingAdjustments"], list)

    def test_regional_plural(self):
        body = _dry_run(
            "bidmodifiers",
            "add",
            "--campaign-id",
            "123",
            "--type",
            "REGIONAL_ADJUSTMENT",
            "--value",
            "110",
            "--region-id",
            "1",
        )
        item = body["params"]["BidModifiers"][0]
        assert "RegionalAdjustments" in item, f"got keys: {list(item.keys())}"
        assert isinstance(item["RegionalAdjustments"], list)

    def test_serp_layout_plural(self):
        body = _dry_run(
            "bidmodifiers",
            "add",
            "--campaign-id",
            "123",
            "--type",
            "SERP_LAYOUT_ADJUSTMENT",
            "--value",
            "105",
            "--serp-layout",
            "PREMIUMBLOCK",
        )
        item = body["params"]["BidModifiers"][0]
        assert "SerpLayoutAdjustments" in item, f"got keys: {list(item.keys())}"
        assert item["SerpLayoutAdjustments"] == [
            {"BidModifier": 105, "SerpLayout": "PREMIUMBLOCK"}
        ]

    def test_income_grade_plural(self):
        body = _dry_run(
            "bidmodifiers",
            "add",
            "--campaign-id",
            "123",
            "--type",
            "INCOME_GRADE_ADJUSTMENT",
            "--value",
            "103",
            "--income-grade",
            "VERY_HIGH",
        )
        item = body["params"]["BidModifiers"][0]
        assert "IncomeGradeAdjustments" in item, f"got keys: {list(item.keys())}"
        assert item["IncomeGradeAdjustments"] == [
            {"BidModifier": 103, "Grade": "VERY_HIGH"}
        ]

    def test_mobile_singular(self):
        """MobileAdjustment stays singular — regression guard."""
        body = _dry_run(
            "bidmodifiers",
            "add",
            "--campaign-id",
            "123",
            "--type",
            "MOBILE_ADJUSTMENT",
            "--value",
            "130",
        )
        item = body["params"]["BidModifiers"][0]
        assert "MobileAdjustment" in item
        assert isinstance(item["MobileAdjustment"], dict)


def test_bids_set_auto_requires_scope():
    result = CliRunner().invoke(
        cli,
        ["bids", "set-auto", "--keyword-id", "1", "--dry-run"],
    )
    assert result.exit_code != 0
    assert "Scope" in result.output or "scope" in result.output


def test_bids_set_auto_payload_uses_bids_array():
    body = _dry_run(
        "bids",
        "set-auto",
        "--keyword-id",
        "1",
        "--max-bid",
        "20000000",
        "--position",
        "PREMIUMBLOCK",
        "--increase-percent",
        "15",
        "--calculate-by",
        "POSITION",
        "--context-coverage",
        "50",
        "--scope",
        "SEARCH",
    )
    item = body["params"]["Bids"][0]
    assert item == {
        "KeywordId": 1,
        "MaxBid": 20000000,
        "Position": "PREMIUMBLOCK",
        "IncreasePercent": 15,
        "CalculateBy": "POSITION",
        "ContextCoverage": 50,
        "Scope": ["SEARCH"],
    }


def test_bids_set_auto_requires_exactly_one_selector():
    # Live API (verified): CampaignId/AdGroupId/KeywordId are mutually
    # exclusive in setAuto; passing two must fail before the request is built.
    result = CliRunner().invoke(
        cli,
        [
            "bids",
            "set-auto",
            "--campaign-id",
            "1",
            "--keyword-id",
            "2",
            "--scope",
            "SEARCH",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "exactly one selector" in result.output


def test_bids_set_auto_requires_a_selector():
    result = CliRunner().invoke(
        cli,
        ["bids", "set-auto", "--scope", "SEARCH", "--dry-run"],
    )
    assert result.exit_code != 0
    assert "exactly one selector" in result.output


def test_bids_get_requires_selection_criteria():
    # Live API error 4001: "The SelectionCriteria structure must specify at
    # least one of the parameters: KeywordIds, AdGroupIds, CampaignIds".
    result = CliRunner().invoke(
        cli,
        ["bids", "get", "--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )
    assert result.exit_code != 0
    assert "--campaign-ids" in result.output


def test_bids_get_with_campaign_ids_builds_criteria():
    body = _read_dry_run("bids", "get", "--campaign-ids", "1,2")
    assert body["params"]["SelectionCriteria"] == {"CampaignIds": [1, 2]}


def test_keywordbids_get_requires_selection_criteria():
    result = CliRunner().invoke(
        cli,
        ["keywordbids", "get", "--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )
    assert result.exit_code != 0
    assert "--keyword-ids" in result.output


def test_keywordbids_get_rejects_over_10_campaign_ids():
    result = CliRunner().invoke(
        cli,
        ["keywordbids", "get", "--campaign-ids", _ids_csv(11), "--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )
    assert result.exit_code == 2, result.output
    assert "more than 10 elements" in result.output
    assert "keywordbids get" in result.output


def test_keywordbids_get_rejects_over_1000_adgroup_ids():
    result = CliRunner().invoke(
        cli,
        ["keywordbids", "get", "--adgroup-ids", _ids_csv(1001), "--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )
    assert result.exit_code == 2, result.output
    assert "more than 1000 elements" in result.output


def test_keywordbids_get_rejects_over_10000_keyword_ids():
    result = CliRunner().invoke(
        cli,
        ["keywordbids", "get", "--keyword-ids", _ids_csv(10001), "--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )
    assert result.exit_code == 2, result.output
    assert "more than 10000 elements" in result.output


def test_keywordbids_get_allows_exactly_10_campaign_ids():
    body = _read_dry_run("keywordbids", "get", "--campaign-ids", _ids_csv(10))
    assert len(body["params"]["SelectionCriteria"]["CampaignIds"]) == 10


def test_keywordbids_set_auto_payload_uses_bidding_rule():
    body = _dry_run(
        "keywordbids",
        "set-auto",
        "--keyword-id",
        "321",
        "--target-traffic-volume",
        "100",
        "--increase-percent",
        "10",
        "--bid-ceiling",
        "12500000",
    )
    item = body["params"]["KeywordBids"][0]
    assert item == {
        "KeywordId": 321,
        "BiddingRule": {
            "SearchByTrafficVolume": {
                "TargetTrafficVolume": 100,
                "IncreasePercent": 10,
                "BidCeiling": 12500000,
            }
        },
    }


def test_keywordbids_set_auto_supports_target_coverage():
    body = _dry_run(
        "keywordbids",
        "set-auto",
        "--keyword-id",
        "321",
        "--target-coverage",
        "50",
    )
    assert body["params"]["KeywordBids"][0] == {
        "KeywordId": 321,
        "BiddingRule": {"NetworkByCoverage": {"TargetCoverage": 50}},
    }


def test_keywordbids_get_default_field_names_payload():
    # KeywordBidsGetRequest (WSDL tests/wsdl_cache/keywordbids.xml) carries
    # three independent top-level FieldNames-style parameters: ``FieldNames``
    # (KeywordBidFieldEnum), ``SearchFieldNames`` (KeywordBidSearchFieldEnum),
    # ``NetworkFieldNames`` (KeywordBidNetworkFieldEnum). The defaults from
    # ``COMMON_FIELDS["keywordbids"]`` must round-trip when no flags are
    # passed.
    body = _read_dry_run(
        "keywordbids",
        "get",
        "--keyword-ids",
        "123",
    )

    params = body["params"]
    assert "FieldNames" in params
    assert "SearchFieldNames" in params
    assert "NetworkFieldNames" in params
    # Defaults from COMMON_FIELDS — Bid is in both nested projections.
    assert params["SearchFieldNames"] == ["Bid"]
    assert params["NetworkFieldNames"] == ["Bid"]


def test_keywordbids_get_overrides_search_and_network_field_names():
    body = _read_dry_run(
        "keywordbids",
        "get",
        "--keyword-ids",
        "123",
        "--search-field-names",
        "Bid,AuctionBids",
        "--network-field-names",
        "Bid,Coverage",
    )

    params = body["params"]
    assert params["SearchFieldNames"] == ["Bid", "AuctionBids"]
    assert params["NetworkFieldNames"] == ["Bid", "Coverage"]


def test_keywordbids_get_overrides_top_level_field_names():
    body = _read_dry_run(
        "keywordbids",
        "get",
        "--keyword-ids",
        "123",
        "--fields",
        "KeywordId,AdGroupId",
    )

    assert body["params"]["FieldNames"] == ["KeywordId", "AdGroupId"]


def test_keywordbids_get_help_exposes_field_names_options():
    result = CliRunner().invoke(cli, ["keywordbids", "get", "--help"])

    assert result.exit_code == 0
    assert "--fields" in result.output
    assert "--search-field-names" in result.output
    assert "--network-field-names" in result.output


def test_keywordbids_get_rejects_empty_search_field_names():
    result = CliRunner().invoke(
        cli,
        ["keywordbids", "get", "--search-field-names", ",", "--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )

    assert result.exit_code != 0
    assert "Provide a non-empty comma-separated SearchFieldNames list." in result.output


def test_keywordbids_get_rejects_empty_network_field_names():
    result = CliRunner().invoke(
        cli,
        ["keywordbids", "get", "--network-field-names", ",", "--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )

    assert result.exit_code != 0
    assert (
        "Provide a non-empty comma-separated NetworkFieldNames list." in result.output
    )


def test_keywordbids_get_rejects_empty_fields():
    result = CliRunner().invoke(
        cli,
        ["keywordbids", "get", "--fields", ",", "--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )

    assert result.exit_code != 0
    assert "Provide a non-empty comma-separated FieldNames list." in result.output


_BIDMODIFIERS_GET_NESTED_FIELD_FLAGS = [
    (
        "--ad-group-adjustment-field-names",
        "AdGroupAdjustmentFieldNames",
        "BidModifier",
    ),
    (
        "--demographics-adjustment-field-names",
        "DemographicsAdjustmentFieldNames",
        "BidModifier,Age,Gender",
    ),
    (
        "--desktop-adjustment-field-names",
        "DesktopAdjustmentFieldNames",
        "BidModifier",
    ),
    (
        "--desktop-only-adjustment-field-names",
        "DesktopOnlyAdjustmentFieldNames",
        "BidModifier",
    ),
    (
        "--income-grade-adjustment-field-names",
        "IncomeGradeAdjustmentFieldNames",
        "BidModifier,IncomeGrade",
    ),
    (
        "--mobile-adjustment-field-names",
        "MobileAdjustmentFieldNames",
        "BidModifier,OperatingSystemType",
    ),
    (
        "--regional-adjustment-field-names",
        "RegionalAdjustmentFieldNames",
        "BidModifier,RegionId",
    ),
    (
        "--retargeting-adjustment-field-names",
        "RetargetingAdjustmentFieldNames",
        "BidModifier,RetargetingConditionId",
    ),
    (
        "--serp-layout-adjustment-field-names",
        "SerpLayoutAdjustmentFieldNames",
        "BidModifier,SerpLayout",
    ),
    (
        "--smart-ad-adjustment-field-names",
        "SmartAdAdjustmentFieldNames",
        "BidModifier",
    ),
    (
        "--smart-tv-adjustment-field-names",
        "SmartTvAdjustmentFieldNames",
        "BidModifier",
    ),
    (
        "--tablet-adjustment-field-names",
        "TabletAdjustmentFieldNames",
        "BidModifier",
    ),
    (
        "--video-adjustment-field-names",
        "VideoAdjustmentFieldNames",
        "BidModifier",
    ),
]


def test_bidmodifiers_get_nested_field_names_payload():
    # BidModifiersGetRequest (WSDL tests/wsdl_cache/bidmodifiers.xml)
    # declares thirteen nested top-level *FieldNames parameters separate
    # from FieldNames, one per adjustment subtype.
    # Verified against live production API on 2026-05-28: Yandex accepts
    # SmartTvAdjustmentFieldNames (not mentioned in the current public
    # docs — #408 carries the api-status:docs-drift label).
    argv = ["bidmodifiers", "get", "--campaign-ids", "1"]
    expected = {}
    for flag, wsdl_key, sample in _BIDMODIFIERS_GET_NESTED_FIELD_FLAGS:
        argv.extend([flag, sample])
        expected[wsdl_key] = sample.split(",")

    body = _read_dry_run(*argv)

    for wsdl_key, values in expected.items():
        assert body["params"][wsdl_key] == values


def test_bidmodifiers_get_omits_nested_field_names_by_default():
    body = _read_dry_run("bidmodifiers", "get", "--campaign-ids", "1")

    for _, wsdl_key, _ in _BIDMODIFIERS_GET_NESTED_FIELD_FLAGS:
        assert wsdl_key not in body["params"]


def test_bidmodifiers_get_help_exposes_nested_field_names():
    result = CliRunner().invoke(cli, ["bidmodifiers", "get", "--help"])

    assert result.exit_code == 0
    for flag, _, _ in _BIDMODIFIERS_GET_NESTED_FIELD_FLAGS:
        assert flag in result.output


@pytest.mark.parametrize(
    "flag,wsdl_key",
    [(flag, key) for flag, key, _ in _BIDMODIFIERS_GET_NESTED_FIELD_FLAGS],
)
def test_bidmodifiers_get_rejects_empty_nested_field_names_csv(flag, wsdl_key):
    result = CliRunner().invoke(
        cli,
        ["bidmodifiers", "get", "--campaign-ids", "1", flag, ",", "--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )

    assert result.exit_code != 0
    assert f"Provide a non-empty comma-separated {wsdl_key} list." in result.output


def test_bids_set_positive_campaign_id_selector_still_builds_payload():
    # Guard the exactly-one-of selector: a positive id must pass the IntRange
    # check AND the one-of logic and land in the payload.
    body = _dry_run("bids", "set", "--campaign-id", "77", "--bid", "100000000")
    assert body["params"]["Bids"][0]["CampaignId"] == 77


def test_keywordbids_set_positive_adgroup_id_selector_still_builds_payload():
    body = _dry_run(
        "keywordbids", "set", "--adgroup-id", "42", "--search-bid", "100000000"
    )
    assert body["params"]["KeywordBids"][0]["AdGroupId"] == 42
