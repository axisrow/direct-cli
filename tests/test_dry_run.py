"""Dry-run payload tests for direct-cli write commands.

These tests use the ``--dry-run`` flag to verify the JSON request body
that direct-cli builds for every mutating command, **without** making any
HTTP calls. They run in the default pytest set (no markers, no token
needed) and complete in well under a second.

Why this file exists
--------------------

Until this PR, direct-cli had **zero** test coverage for write
operations. The Type-field bug in ``ads add`` (sending an explicit
top-level ``"Type"`` key that the Yandex Direct API rejects) shipped to
production specifically because no one had ever exercised an ``add``
command against a real API; the only mutating command anyone happened
to try was ``ads add``, and only after a user reported the failure
through the MCP plugin (axisrow/yandex-direct-mcp-plugin#60).

The audit that motivated this file (axisrow/yandex-direct-mcp-plugin#61)
counted **44 mutating commands across 28 services with 0% coverage**.
This file closes that gap by exercising every write command that has
a ``--dry-run`` flag and asserting the exact request body shape.

Two more occurrences of the same Type bug were found by this audit and
fixed alongside these tests:

* ``adgroups add`` — confirmed against the official Yandex Direct API
  v5 docs (https://yandex.ru/dev/direct/doc/ref-v5/adgroups/add.html);
  ``AdGroupAddItem`` has no top-level ``Type``.
* ``smartadtargets add`` / ``smartadtargets update`` — the legacy
  ``--type`` CLI option doesn't map to any real ``SmartAdTargetAddItem``
  field (real fields are ``TargetingId``, ``Bid``, ``Priority``).

Each test for an ``add`` command includes a regression assertion that
``"Type"`` is **not** present at the top level of the resource item, so
that re-introducing the bug breaks CI immediately.

Coverage scope
--------------

The suite covers both payload-building write commands (``add``,
``update``, ``set``) and the main single-action lifecycle
commands that now expose ``--dry-run`` (``delete``,
``suspend``, ``resume``, ``moderate``, ``archive``,
``unarchive``) so that trivial
``SelectionCriteria`` regressions are also caught in CI.

Part of axisrow/yandex-direct-mcp-plugin#61.
"""

import base64
import json
from unittest.mock import patch

from click.testing import CliRunner, Result

from direct_cli.cli import cli
from direct_cli.utils import get_default_fields


def _dry_run(*args: str) -> dict:
    """Invoke a CLI command with ``--dry-run`` and return the parsed body."""
    result = CliRunner().invoke(cli, list(args) + ["--dry-run"])
    assert result.exit_code == 0, (
        f"command failed: direct {' '.join(args)} --dry-run\n"
        f"output: {result.output}\n"
        f"exception: {result.exception}"
    )
    return json.loads(result.output)


def _read_dry_run(*args: str) -> dict:
    """Invoke a read command dry-run with dummy credentials."""
    result = CliRunner().invoke(
        cli,
        list(args) + ["--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )
    assert result.exit_code == 0, (
        f"command failed: direct {' '.join(args)} --dry-run\n"
        f"output: {result.output}\n"
        f"exception: {result.exception}"
    )
    return json.loads(result.output)


def _rejected(*args: str) -> Result:
    """Invoke a CLI command expecting Click-level rejection."""
    result = CliRunner().invoke(cli, list(args) + ["--dry-run"])
    assert result.exit_code != 0, (
        f"command unexpectedly succeeded: direct {' '.join(args)} --dry-run\n"
        f"output: {result.output}"
    )
    return result


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
    ):
        body = _read_dry_run(command, "get")
        assert "SelectionCriteria" not in body["params"]


def test_advideos_get_ids_required():
    result = CliRunner().invoke(cli, ["advideos", "get", "--dry-run"])
    assert result.exit_code != 0
    assert "Missing option '--ids'" in result.output


def test_campaigns_get_text_campaign_fields_dry_run():
    body = _read_dry_run(
        "campaigns",
        "get",
        "--fields",
        "Id,Name,State",
        "--text-campaign-fields",
        "BiddingStrategy",
    )

    assert body["params"]["FieldNames"] == ["Id", "Name", "State"]
    assert body["params"]["TextCampaignFieldNames"] == ["BiddingStrategy"]


def test_campaigns_get_campaign_specific_fields_dry_run():
    body = _read_dry_run(
        "campaigns",
        "get",
        "--text-campaign-fields",
        "BiddingStrategy,PriorityGoals",
        "--mobile-app-campaign-fields",
        "Settings,BiddingStrategy",
        "--dynamic-text-campaign-fields",
        "BiddingStrategy,Settings",
        "--cpm-banner-campaign-fields",
        "BiddingStrategy,Settings",
        "--smart-campaign-fields",
        "BiddingStrategy,Settings",
        "--unified-campaign-fields",
        "BiddingStrategy,PriorityGoals",
    )

    params = body["params"]
    assert params["TextCampaignFieldNames"] == ["BiddingStrategy", "PriorityGoals"]
    assert params["MobileAppCampaignFieldNames"] == ["Settings", "BiddingStrategy"]
    assert params["DynamicTextCampaignFieldNames"] == ["BiddingStrategy", "Settings"]
    assert params["CpmBannerCampaignFieldNames"] == ["BiddingStrategy", "Settings"]
    assert params["SmartCampaignFieldNames"] == ["BiddingStrategy", "Settings"]
    assert params["UnifiedCampaignFieldNames"] == ["BiddingStrategy", "PriorityGoals"]


def test_campaigns_get_strategy_placement_fields_dry_run():
    body = _read_dry_run(
        "campaigns",
        "get",
        "--text-campaign-search-strategy-placement-types-fields",
        "SearchResults,ProductGallery",
        "--dynamic-text-campaign-search-strategy-placement-types-fields",
        "SearchResults,DynamicPlaces",
        "--unified-campaign-search-strategy-placement-types-fields",
        "SearchResults,Maps,SearchOrganizationList",
        "--unified-campaign-package-bidding-strategy-platforms-fields",
        "SearchResult,Network",
    )

    params = body["params"]
    assert params["TextCampaignSearchStrategyPlacementTypesFieldNames"] == [
        "SearchResults",
        "ProductGallery",
    ]
    assert params["DynamicTextCampaignSearchStrategyPlacementTypesFieldNames"] == [
        "SearchResults",
        "DynamicPlaces",
    ]
    assert params["UnifiedCampaignSearchStrategyPlacementTypesFieldNames"] == [
        "SearchResults",
        "Maps",
        "SearchOrganizationList",
    ]
    assert params["UnifiedCampaignPackageBiddingStrategyPlatformsFieldNames"] == [
        "SearchResult",
        "Network",
    ]


def test_campaigns_get_omits_campaign_specific_fields_by_default():
    body = _read_dry_run("campaigns", "get", "--fields", "Id,Name,State")

    omitted_keys = {
        "TextCampaignFieldNames",
        "TextCampaignSearchStrategyPlacementTypesFieldNames",
        "MobileAppCampaignFieldNames",
        "DynamicTextCampaignFieldNames",
        "DynamicTextCampaignSearchStrategyPlacementTypesFieldNames",
        "CpmBannerCampaignFieldNames",
        "SmartCampaignFieldNames",
        "UnifiedCampaignFieldNames",
        "UnifiedCampaignSearchStrategyPlacementTypesFieldNames",
        "UnifiedCampaignPackageBiddingStrategyPlatformsFieldNames",
    }
    assert body["params"]["FieldNames"] == ["Id", "Name", "State"]
    assert omitted_keys.isdisjoint(body["params"])


def test_campaigns_get_rejects_empty_fields_csv():
    result = CliRunner().invoke(
        cli,
        ["campaigns", "get", "--fields", ",", "--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )

    assert result.exit_code != 0
    assert "--fields must contain at least one value" in result.output


def test_campaigns_get_rejects_empty_campaign_specific_fields_csv():
    result = CliRunner().invoke(
        cli,
        [
            "campaigns",
            "get",
            "--fields",
            "Id",
            "--text-campaign-fields",
            ",",
            "--dry-run",
        ],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )

    assert result.exit_code != 0
    assert "--text-campaign-fields must contain at least one value" in result.output


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


# ----------------------------------------------------------------------
# ads
# ----------------------------------------------------------------------


def test_ads_add_text_ad_payload_omits_type():
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "TEXT_AD",
        "--title",
        "T",
        "--text",
        "Some text",
        "--href",
        "https://example.com",
    )
    assert body["method"] == "add"
    ad = body["params"]["Ads"][0]
    # Regression guard for axisrow/yandex-direct-mcp-plugin#60:
    # the Yandex Direct API rejects an explicit top-level Type field;
    # the type is inferred from TextAd / MobileAppAd / DynamicTextAd / ...
    assert "Type" not in ad
    assert ad["AdGroupId"] == 12345
    assert ad["TextAd"] == {
        "Mobile": "NO",
        "Title": "T",
        "Text": "Some text",
        "Href": "https://example.com",
    }


def test_ads_add_text_ad_accepts_wsdl_image_hash():
    image_hash = "ygqa6jmlkgsbz7vnewp0"
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "TEXT_AD",
        "--title",
        "T",
        "--text",
        "Some text",
        "--href",
        "https://example.com",
        "--image-hash",
        image_hash,
    )

    ad = body["params"]["Ads"][0]
    assert ad["TextAd"]["AdImageHash"] == image_hash


def test_ads_add_rejects_incompatible_subtype_flags():
    text_ad = _rejected(
        "ads",
        "add",
        "--adgroup-id",
        "1",
        "--type",
        "TEXT_AD",
        "--title",
        "T",
        "--text",
        "Body",
        "--href",
        "https://example.com",
        "--action",
        "INSTALL",
    )
    text_image = _rejected(
        "ads",
        "add",
        "--adgroup-id",
        "1",
        "--type",
        "TEXT_IMAGE_AD",
        "--image-hash",
        "hash",
        "--href",
        "https://example.com",
        "--tracking-url",
        "https://tracker.example.com",
    )

    assert "--action is not compatible with --type TEXT_AD" in text_ad.output
    assert (
        "--tracking-url is not compatible with --type TEXT_IMAGE_AD"
        in text_image.output
    )


def test_ads_add_default_type_builds_textad():
    """Without --type, convenience flags still build a TextAd payload."""
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--title",
        "T",
        "--text",
        "Some text",
        "--href",
        "https://example.com",
    )
    ad = body["params"]["Ads"][0]
    assert "Type" not in ad
    assert ad["TextAd"] == {
        "Mobile": "NO",
        "Title": "T",
        "Text": "Some text",
        "Href": "https://example.com",
    }


def test_ads_add_case_insensitive_type():
    """--type is case-insensitive for canonical enum spellings.

    Regression guard for axisrow/direct-cli#21 — before the fix, only the
    exact string ``TEXT_AD`` built a TextAd; any other value silently
    dropped --title/--text/--href.
    """
    for variant in ("text_ad", "Text_Ad"):
        body = _dry_run(
            "ads",
            "add",
            "--adgroup-id",
            "1",
            "--type",
            variant,
            "--title",
            "T",
            "--text",
            "Body",
            "--href",
            "https://example.com",
        )
        ad = body["params"]["Ads"][0]
        assert ad.get("TextAd") == {
            "Mobile": "NO",
            "Title": "T",
            "Text": "Body",
            "Href": "https://example.com",
        }, f"--type {variant!r} failed to build TextAd"


def test_ads_add_invalid_type_is_rejected_by_choice():
    result = CliRunner().invoke(
        cli,
        [
            "ads",
            "add",
            "--adgroup-id",
            "1",
            "--type",
            "text",
            "--title",
            "T",
            "--text",
            "Body",
            "--href",
            "https://example.com",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "Invalid value for '--type'" in result.output


def test_ads_add_text_image_uses_typed_flags():
    image_hash = "ygqa6jmlkgsbz7vnewp0"
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "55",
        "--type",
        "TEXT_IMAGE_AD",
        "--image-hash",
        image_hash,
        "--href",
        "https://example.com",
    )
    ad = body["params"]["Ads"][0]
    assert "Type" not in ad
    assert ad["AdGroupId"] == 55
    assert ad["TextImageAd"] == {
        "AdImageHash": image_hash,
        "Href": "https://example.com",
    }


def test_ads_add_text_ad_with_title2_and_display_url_path():
    """Issue #202: --title2 and --display-url-path map to TextAd fields."""
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "TEXT_AD",
        "--title",
        "T",
        "--text",
        "Body text long enough",
        "--href",
        "https://example.com",
        "--title2",
        "Second headline",
        "--display-url-path",
        "deals",
    )
    text_ad = body["params"]["Ads"][0]["TextAd"]
    assert text_ad["Title2"] == "Second headline"
    assert text_ad["DisplayUrlPath"] == "deals"


def test_ads_add_text_ad_with_mobile_yes():
    """Issue #202: --mobile YES overrides the default ``Mobile: NO``."""
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "TEXT_AD",
        "--title",
        "T",
        "--text",
        "Body text long enough",
        "--href",
        "https://example.com",
        "--mobile",
        "YES",
    )
    assert body["params"]["Ads"][0]["TextAd"]["Mobile"] == "YES"


def test_ads_add_text_ad_default_mobile_is_no():
    """Default ``Mobile: NO`` is preserved when --mobile is omitted (regression)."""
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "TEXT_AD",
        "--title",
        "T",
        "--text",
        "Body text long enough",
        "--href",
        "https://example.com",
    )
    assert body["params"]["Ads"][0]["TextAd"]["Mobile"] == "NO"


def test_ads_add_text_ad_with_vcard_sitelink_extensions():
    """Issue #202: VCardId, SitelinkSetId, AdExtensionIds map from typed flags."""
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "TEXT_AD",
        "--title",
        "T",
        "--text",
        "Body text long enough",
        "--href",
        "https://example.com",
        "--vcard-id",
        "111",
        "--sitelink-set-id",
        "222",
        "--ad-extensions",
        "444,555",
    )
    text_ad = body["params"]["Ads"][0]["TextAd"]
    assert text_ad["VCardId"] == 111
    assert text_ad["SitelinkSetId"] == 222
    assert text_ad["AdExtensionIds"] == [444, 555]


def test_ads_add_text_ad_with_turbo_page_id():
    """Issue #202: --turbo-page-id maps to TextAd.TurboPageId."""
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "TEXT_AD",
        "--title",
        "T",
        "--text",
        "Body text long enough",
        "--href",
        "https://example.com",
        "--turbo-page-id",
        "333",
    )
    assert body["params"]["Ads"][0]["TextAd"]["TurboPageId"] == 333


def test_ads_add_text_image_ad_with_turbo_page_id():
    """Issue #202: --turbo-page-id is also valid for TEXT_IMAGE_AD."""
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "55",
        "--type",
        "TEXT_IMAGE_AD",
        "--image-hash",
        "abcdefghij",
        "--href",
        "https://example.com",
        "--turbo-page-id",
        "777",
    )
    assert body["params"]["Ads"][0]["TextImageAd"]["TurboPageId"] == 777


def test_ads_add_rejects_title2_on_text_image_ad():
    """Issue #202 (Pattern B): --title2 belongs to TEXT_AD only."""
    result = CliRunner().invoke(
        cli,
        [
            "ads",
            "add",
            "--adgroup-id",
            "1",
            "--type",
            "TEXT_IMAGE_AD",
            "--image-hash",
            "abcdefghij",
            "--href",
            "https://example.com",
            "--title2",
            "X",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "--title2 is not compatible with --type TEXT_IMAGE_AD" in result.output


def test_ads_add_rejects_ad_extensions_on_mobile_app_ad():
    """Issue #202 (Pattern B): --ad-extensions is TEXT_AD-only."""
    result = CliRunner().invoke(
        cli,
        [
            "ads",
            "add",
            "--adgroup-id",
            "1",
            "--type",
            "MOBILE_APP_AD",
            "--title",
            "T",
            "--text",
            "Body",
            "--action",
            "INSTALL",
            "--ad-extensions",
            "1,2",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert (
        "--ad-extensions is not compatible with --type MOBILE_APP_AD" in result.output
    )


def test_ads_add_rejects_mobile_yes_on_text_image_ad():
    """Explicit --mobile YES on a non-TEXT_AD subtype is silent data loss."""
    result = CliRunner().invoke(
        cli,
        [
            "ads",
            "add",
            "--adgroup-id",
            "1",
            "--type",
            "TEXT_IMAGE_AD",
            "--image-hash",
            "abcdefghij",
            "--href",
            "https://example.com",
            "--mobile",
            "YES",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "--mobile is not compatible with --type TEXT_IMAGE_AD" in result.output


def test_ads_add_rejects_explicit_mobile_no_on_text_image_ad():
    """Even explicit --mobile NO on a non-TEXT_AD subtype must be rejected.

    The Click default for --mobile is ``NO``, but per WSDL parity (#198 H2),
    a typed flag does not silently drop based on its value — passing the flag
    explicitly on an incompatible subtype must raise UsageError.
    """
    result = CliRunner().invoke(
        cli,
        [
            "ads",
            "add",
            "--adgroup-id",
            "1",
            "--type",
            "TEXT_IMAGE_AD",
            "--image-hash",
            "abcdefghij",
            "--href",
            "https://example.com",
            "--mobile",
            "NO",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "--mobile is not compatible with --type TEXT_IMAGE_AD" in result.output


def test_ads_add_text_image_ad_default_mobile_does_not_leak():
    """Regression: omitting --mobile must NOT trigger the Pattern B guard.

    Click fills --mobile with its default ``NO`` on every invocation, so the
    guard's per-subtype check must distinguish "explicitly passed" from
    "default" via ``ctx.get_parameter_source``.
    """
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "1",
        "--type",
        "TEXT_IMAGE_AD",
        "--image-hash",
        "abcdefghij",
        "--href",
        "https://example.com",
    )
    ad = body["params"]["Ads"][0]
    assert ad["TextImageAd"] == {
        "AdImageHash": "abcdefghij",
        "Href": "https://example.com",
    }
    assert "Mobile" not in ad["TextImageAd"]


def test_ads_update_rejects_status_flag():
    """``--status`` is not part of WSDL ``AdUpdateItem`` (regression for #183).

    Status changes must go through ``ads suspend/resume/archive/unarchive``.
    Verify the flag now fails loudly via ``click.UsageError`` and that no
    request body containing a top-level ``Status`` key is emitted.
    """
    result = CliRunner().invoke(
        cli,
        [
            "ads",
            "update",
            "--id",
            "1",
            "--type",
            "TEXT_AD",
            "--status",
            "SUSPENDED",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "not supported by WSDL AdUpdateItem" in result.output
    assert '"Status"' not in result.output


def test_ads_update_text_ad_flags_build_nested_textad():
    """TextAd subtype: --title/--text/--href produce TextAd block only."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_AD",
        "--title",
        "Updated",
        "--text",
        "Body",
        "--href",
        "https://example.com",
    )
    ad = body["params"]["Ads"][0]
    assert ad["Id"] == 999
    assert ad["TextAd"] == {
        "Title": "Updated",
        "Text": "Body",
        "Href": "https://example.com",
    }
    assert "TextImageAd" not in ad


def test_ads_update_text_ad_image_hash_builds_nested_textad():
    """TextAd subtype: --image-hash produces TextAd.AdImageHash."""
    image_hash = "ygqa6jmlkgsbz7vnewp0"
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_AD",
        "--image-hash",
        image_hash,
    )
    ad = body["params"]["Ads"][0]
    assert ad["Id"] == 999
    assert ad["TextAd"] == {"AdImageHash": image_hash}
    assert "TextImageAd" not in ad


def test_ads_update_image_hash_builds_nested_textimagead():
    """TextImageAd subtype: --image-hash produces TextImageAd block only."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_IMAGE_AD",
        "--image-hash",
        "ygqa6jmlkgsbz7vnewp0",
    )
    ad = body["params"]["Ads"][0]
    assert ad["Id"] == 999
    assert ad["TextImageAd"] == {"AdImageHash": "ygqa6jmlkgsbz7vnewp0"}
    assert "TextAd" not in ad


def test_ads_update_incompatible_flag_explains_existing_subtype():
    result = CliRunner().invoke(
        cli,
        [
            "ads",
            "update",
            "--id",
            "999",
            "--type",
            "TEXT_AD",
            "--action",
            "INSTALL",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "--action is not compatible with --type TEXT_AD" in result.output
    assert "does not convert an ad between subtypes" in result.output
    assert "Allowed flags for TEXT_AD" in result.output
    assert "--image-hash" in result.output


def test_ads_update_text_ad_with_title2_and_display_url_path():
    """Issue #202: update can set TextAd.Title2 and TextAd.DisplayUrlPath."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_AD",
        "--title2",
        "Updated second",
        "--display-url-path",
        "newpath",
    )
    ad = body["params"]["Ads"][0]
    assert ad["Id"] == 999
    assert ad["TextAd"] == {
        "Title2": "Updated second",
        "DisplayUrlPath": "newpath",
    }
    assert "Mobile" not in ad["TextAd"]


def test_ads_update_text_ad_with_vcard_sitelink():
    """Issue #202: update sets VCardId and SitelinkSetId in nested TextAd."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_AD",
        "--vcard-id",
        "111",
        "--sitelink-set-id",
        "222",
    )
    text_ad = body["params"]["Ads"][0]["TextAd"]
    assert text_ad == {"VCardId": 111, "SitelinkSetId": 222}


def test_ads_update_text_ad_with_turbo_page_id():
    """Issue #202: update sets TurboPageId in TextAd."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_AD",
        "--turbo-page-id",
        "555",
    )
    assert body["params"]["Ads"][0]["TextAd"] == {"TurboPageId": 555}


def test_ads_update_text_image_ad_with_turbo_page_id():
    """Issue #202: update sets TurboPageId in TextImageAd."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_IMAGE_AD",
        "--turbo-page-id",
        "555",
    )
    assert body["params"]["Ads"][0]["TextImageAd"] == {"TurboPageId": 555}


def test_ads_update_rejects_mobile_flag():
    """Issue #202: --mobile is not exposed on update (TextAdUpdate lacks Mobile)."""
    result = CliRunner().invoke(
        cli,
        [
            "ads",
            "update",
            "--id",
            "999",
            "--type",
            "TEXT_AD",
            "--mobile",
            "YES",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    # Click formats this message differently across versions: 8.1 says
    # "No such option: --mobile" while 8.2+ writes "No such option '--mobile'".
    # Match the stable substring.
    assert "No such option" in result.output and "--mobile" in result.output


def test_ads_update_rejects_ad_extensions_flag():
    """Issue #202: --ad-extensions is not exposed on update.

    TextAdUpdateBase uses ``CalloutSetting`` (managed via
    ``--callouts-add`` / ``--callouts-remove`` / ``--callouts-set`` since
    #238), not the ``AdExtensionIds`` flat array exposed on ``ads add``.
    """
    result = CliRunner().invoke(
        cli,
        [
            "ads",
            "update",
            "--id",
            "999",
            "--type",
            "TEXT_AD",
            "--ad-extensions",
            "1,2",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "No such option" in result.output and "--ad-extensions" in result.output


def test_ads_update_callouts_add_only():
    """Issue #238: --callouts-add builds CalloutSetting with ADD ops."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_AD",
        "--callouts-add",
        "111,222",
    )
    assert body["params"]["Ads"][0]["TextAd"] == {
        "CalloutSetting": {
            "AdExtensions": [
                {"AdExtensionId": 111, "Operation": "ADD"},
                {"AdExtensionId": 222, "Operation": "ADD"},
            ]
        }
    }


def test_ads_update_callouts_remove_only():
    """Issue #238: --callouts-remove builds CalloutSetting with REMOVE ops."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_AD",
        "--callouts-remove",
        "333",
    )
    text_ad = body["params"]["Ads"][0]["TextAd"]
    assert text_ad["CalloutSetting"]["AdExtensions"] == [
        {"AdExtensionId": 333, "Operation": "REMOVE"},
    ]


def test_ads_update_callouts_set_only():
    """Issue #238: --callouts-set replaces the full list with Operation=SET."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_AD",
        "--callouts-set",
        "111,222,333",
    )
    items = body["params"]["Ads"][0]["TextAd"]["CalloutSetting"]["AdExtensions"]
    assert items == [
        {"AdExtensionId": 111, "Operation": "SET"},
        {"AdExtensionId": 222, "Operation": "SET"},
        {"AdExtensionId": 333, "Operation": "SET"},
    ]


def test_ads_update_callouts_add_and_remove_combined():
    """Issue #238: ADD and REMOVE coexist in one request; SET cannot mix in."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_AD",
        "--callouts-add",
        "111",
        "--callouts-remove",
        "222,333",
    )
    items = body["params"]["Ads"][0]["TextAd"]["CalloutSetting"]["AdExtensions"]
    # Deterministic order from _build_callout_setting iteration:
    # SET first (absent here), then ADD, then REMOVE.
    assert items == [
        {"AdExtensionId": 111, "Operation": "ADD"},
        {"AdExtensionId": 222, "Operation": "REMOVE"},
        {"AdExtensionId": 333, "Operation": "REMOVE"},
    ]


def test_ads_update_callouts_set_conflicts_with_add():
    """Issue #238: --callouts-set is mutex with --callouts-add (UsageError)."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_AD",
        "--callouts-set",
        "111",
        "--callouts-add",
        "222",
    )
    assert result.exit_code == 2
    assert "--callouts-set is mutually exclusive" in result.output


def test_ads_update_callouts_set_conflicts_with_remove():
    """Issue #238: --callouts-set is mutex with --callouts-remove (UsageError)."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_AD",
        "--callouts-set",
        "111",
        "--callouts-remove",
        "222",
    )
    assert result.exit_code == 2
    assert "--callouts-set is mutually exclusive" in result.output


def test_ads_update_callouts_rejected_for_text_image_ad():
    """Issue #238 (Pattern B): callouts flags are TEXT_AD-only."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_IMAGE_AD",
        "--callouts-add",
        "111",
    )
    assert "--callouts-add is not compatible with --type TEXT_IMAGE_AD" in result.output


def test_ads_update_callouts_rejected_for_mobile_app_ad():
    """Issue #238 (Pattern B): callouts flags are TEXT_AD-only."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "MOBILE_APP_AD",
        "--callouts-set",
        "111",
    )
    assert "--callouts-set is not compatible with --type MOBILE_APP_AD" in result.output


def test_ads_update_callouts_empty_string_rejected():
    """Issue #238: empty CSV must raise UsageError, not silently no-op."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_AD",
        "--callouts-add",
        "",
    )
    assert result.exit_code != 0
    assert "must contain at least one ad extension ID" in result.output


def test_ads_update_callouts_invalid_id_rejected_with_usage_error():
    """Issue #238: non-integer CSV item must raise UsageError (exit 2),
    not surface ValueError as a traceback through the generic except.
    """
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_AD",
        "--callouts-add",
        "123,bad",
    )
    assert result.exit_code == 2
    assert "--callouts-add" in result.output
    assert "Invalid ID" in result.output
    assert "Traceback" not in result.output


def test_ads_update_text_ad_video_extension_payload():
    """Issue #245: TEXT_AD update exposes VideoExtension.CreativeId."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_AD",
        "--video-extension-creative-id",
        "777",
    )
    assert body["params"]["Ads"][0] == {
        "Id": 999,
        "TextAd": {"VideoExtension": {"CreativeId": 777}},
    }


def test_ads_update_text_ad_price_extension_payload():
    """Issue #245: TEXT_AD update exposes PriceExtension fields."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_AD",
        "--price-extension-price",
        "123450000",
        "--price-extension-old-price",
        "150000000",
        "--price-extension-price-qualifier",
        "from",
        "--price-extension-price-currency",
        "rub",
    )
    assert body["params"]["Ads"][0] == {
        "Id": 999,
        "TextAd": {
            "PriceExtension": {
                "Price": 123450000,
                "OldPrice": 150000000,
                "PriceQualifier": "FROM",
                "PriceCurrency": "RUB",
            }
        },
    }


def test_ads_update_text_ad_price_extension_partial_payload():
    """PriceExtensionUpdateItem children are optional in WSDL update."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_AD",
        "--price-extension-price-currency",
        "USD",
    )
    assert body["params"]["Ads"][0] == {
        "Id": 999,
        "TextAd": {"PriceExtension": {"PriceCurrency": "USD"}},
    }


def test_ads_update_text_ad_extension_flags_rejected_for_text_image_ad():
    """Issue #245: TEXT_AD extension flags must not silently drop by subtype."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_IMAGE_AD",
        "--video-extension-creative-id",
        "777",
    )
    assert (
        "--video-extension-creative-id is not compatible with --type TEXT_IMAGE_AD"
        in result.output
    )


def test_ads_update_text_ad_price_extension_flags_rejected_for_mobile_app_ad():
    """Issue #245: PriceExtension flags are TEXT_AD-only in this patch scope."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "MOBILE_APP_AD",
        "--price-extension-price",
        "123450000",
    )
    assert (
        "--price-extension-price is not compatible with --type MOBILE_APP_AD"
        in result.output
    )


def test_ads_update_text_ad_extension_flags_count_as_updatable_fields():
    """Issue #245: extension-only updates must not trip the no-op guard."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_AD",
        "--price-extension-price-qualifier",
        "NONE",
    )
    assert body["params"]["Ads"][0] == {
        "Id": 999,
        "TextAd": {"PriceExtension": {"PriceQualifier": "NONE"}},
    }


def test_ads_update_rejects_title2_on_text_image_ad():
    """Issue #202 (Pattern B): --title2 is TEXT_AD-only in update too."""
    result = CliRunner().invoke(
        cli,
        [
            "ads",
            "update",
            "--id",
            "999",
            "--type",
            "TEXT_IMAGE_AD",
            "--title2",
            "X",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "--title2 is not compatible with --type TEXT_IMAGE_AD" in result.output


def test_ads_get_default_fieldnames():
    """Default FieldNames includes basic top-level fields, plus TextAdFieldNames."""
    body = _dry_run("ads", "get", "--campaign-ids", "12345")
    assert body["method"] == "get"
    assert body["params"]["FieldNames"] == get_default_fields("ads", "FieldNames")
    assert body["params"]["TextAdFieldNames"] == get_default_fields(
        "ads", "TextAdFieldNames"
    )


def test_ads_get_with_fields_overrides_defaults():
    """--fields and --text-ad-fields override the defaults."""
    body = _dry_run(
        "ads",
        "get",
        "--campaign-ids",
        "12345",
        "--fields",
        "Id,State",
        "--text-ad-fields",
        "Title",
    )
    assert body["params"]["FieldNames"] == ["Id", "State"]
    assert body["params"]["TextAdFieldNames"] == ["Title"]


def test_ads_get_with_ids_and_status():
    """Multiple selection criteria are combined correctly."""
    body = _dry_run(
        "ads", "get", "--ids", "1,2,3", "--status", "ACCEPTED", "--limit", "10"
    )
    assert body["params"]["SelectionCriteria"] == {
        "Ids": [1, 2, 3],
        "Statuses": ["ACCEPTED"],
    }
    assert body["params"]["Page"] == {"Limit": 10}
    assert "TextAdFieldNames" in body["params"]


# ----------------------------------------------------------------------
# adgroups
# ----------------------------------------------------------------------


def test_adgroups_add_payload_omits_type():
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Group A",
        "--campaign-id",
        "111",
        "--region-ids",
        "1,225",
    )
    assert body["method"] == "add"
    group = body["params"]["AdGroups"][0]
    # Regression guard: AdGroupAddItem has no top-level Type field;
    # the group type is inferred from MobileAppAdGroup / DynamicTextAdGroup
    # / SmartAdGroup / ... sub-objects exactly like Ads.
    # See https://yandex.ru/dev/direct/doc/ref-v5/adgroups/add.html
    assert "Type" not in group
    assert group["Name"] == "Group A"
    assert group["CampaignId"] == 111
    assert group["RegionIds"] == [1, 225]


def test_adgroups_add_tracking_params_payload():
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Group A",
        "--campaign-id",
        "111",
        "--region-ids",
        "1,225",
        "--tracking-params",
        "utm_source=direct",
    )
    group = body["params"]["AdGroups"][0]
    assert group["TrackingParams"] == "utm_source=direct"
    assert "DynamicTextAdGroup" not in group
    assert "SmartAdGroup" not in group


def test_adgroups_add_negative_keywords_payload():
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Group A",
        "--campaign-id",
        "111",
        "--region-ids",
        "1,225",
        "--negative-keywords",
        "word1, word2",
    )
    group = body["params"]["AdGroups"][0]
    assert group["NegativeKeywords"] == {"Items": ["word1", "word2"]}


def test_adgroups_add_negative_keyword_shared_set_ids_payload():
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Group A",
        "--campaign-id",
        "111",
        "--region-ids",
        "1,225",
        "--negative-keyword-shared-set-ids",
        "10,11",
    )
    group = body["params"]["AdGroups"][0]
    assert group["NegativeKeywordSharedSetIds"] == {"Items": [10, 11]}


def test_adgroups_add_negative_keyword_shared_set_ids_rejects_invalid_id():
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Group A",
        "--campaign-id",
        "111",
        "--region-ids",
        "1,225",
        "--negative-keyword-shared-set-ids",
        "10,nope",
    )
    assert "--negative-keyword-shared-set-ids: Invalid ID: 'nope'" in result.output
    assert "Traceback" not in result.output


def test_adgroups_add_case_insensitive_default_type():
    """``--type text_ad_group`` (lowercase) still builds a valid payload.

    Regression guard for axisrow/direct-cli#23 — before the fix the CLI
    accepted --type as a free-form string and silently discarded it,
    so users typing the lowercase variant got the default text payload
    without error. Normalization now makes lowercase an explicit
    supported spelling.
    """
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Group A",
        "--campaign-id",
        "111",
        "--region-ids",
        "225",
        "--type",
        "text_ad_group",
    )
    group = body["params"]["AdGroups"][0]
    assert "Type" not in group
    assert group["CampaignId"] == 111


def test_adgroups_add_dynamic_payload_omits_type():
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Dynamic Group",
        "--campaign-id",
        "111",
        "--type",
        "DYNAMIC_TEXT_AD_GROUP",
        "--region-ids",
        "1,225",
        "--domain-url",
        "example.com",
    )
    group = body["params"]["AdGroups"][0]
    assert "Type" not in group
    assert group["RegionIds"] == [1, 225]
    assert group["DynamicTextAdGroup"] == {"DomainUrl": "example.com"}


def test_adgroups_add_dynamic_autotargeting_categories_payload():
    """Issue #280: dynamic add supports legacy AutotargetingCategories."""
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Dynamic Group",
        "--campaign-id",
        "111",
        "--type",
        "DYNAMIC_TEXT_AD_GROUP",
        "--region-ids",
        "1,225",
        "--domain-url",
        "example.com",
        "--autotargeting-category",
        "exact=yes",
        "--autotargeting-category",
        "BROADER=NO",
    )
    group = body["params"]["AdGroups"][0]
    assert group["DynamicTextAdGroup"] == {
        "DomainUrl": "example.com",
        "AutotargetingCategories": [
            {"Category": "EXACT", "Value": "YES"},
            {"Category": "BROADER", "Value": "NO"},
        ],
    }


def test_adgroups_add_dynamic_autotargeting_settings_payload():
    """Issue #280: dynamic add supports AutotargetingSettings flags."""
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Dynamic Group",
        "--campaign-id",
        "111",
        "--type",
        "DYNAMIC_TEXT_AD_GROUP",
        "--region-ids",
        "1,225",
        "--domain-url",
        "example.com",
        "--autotargeting-settings-exact",
        "yes",
        "--autotargeting-settings-narrow",
        "no",
        "--autotargeting-settings-without-brands",
        "YES",
        "--autotargeting-settings-with-competitors-brand",
        "no",
    )
    group = body["params"]["AdGroups"][0]
    assert group["DynamicTextAdGroup"] == {
        "DomainUrl": "example.com",
        "AutotargetingSettings": {
            "Categories": {
                "Exact": "YES",
                "Narrow": "NO",
            },
            "BrandOptions": {
                "WithoutBrands": "YES",
                "WithCompetitorsBrand": "NO",
            },
        },
    }


def test_adgroups_add_dynamic_autotargeting_rejects_invalid_category():
    """Issue #280: AutotargetingCategories uses the documented enum."""
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Dynamic Group",
        "--campaign-id",
        "111",
        "--type",
        "DYNAMIC_TEXT_AD_GROUP",
        "--region-ids",
        "225",
        "--domain-url",
        "example.com",
        "--autotargeting-category",
        "NARROW=YES",
    )
    assert "Invalid --autotargeting-category category 'NARROW'" in result.output
    assert "EXACT, ALTERNATIVE, COMPETITOR, BROADER, ACCESSORY" in result.output


def test_adgroups_add_dynamic_autotargeting_rejects_legacy_mix():
    """Issue #280: legacy categories and AutotargetingSettings cannot mix."""
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Dynamic Group",
        "--campaign-id",
        "111",
        "--type",
        "DYNAMIC_TEXT_AD_GROUP",
        "--region-ids",
        "225",
        "--domain-url",
        "example.com",
        "--autotargeting-category",
        "EXACT=YES",
        "--autotargeting-settings-exact",
        "YES",
    )
    assert "AutotargetingSettings flags cannot be combined" in result.output


def test_adgroups_add_smart_payload_omits_type():
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Smart Group",
        "--campaign-id",
        "111",
        "--type",
        "SMART_AD_GROUP",
        "--region-ids",
        "1,225",
        "--feed-id",
        "77",
        "--ad-title-source",
        "FEED_NAME",
        "--ad-body-source",
        "FEED_NAME",
    )
    group = body["params"]["AdGroups"][0]
    assert "Type" not in group
    assert group["SmartAdGroup"] == {
        "FeedId": 77,
        "AdTitleSource": "FEED_NAME",
        "AdBodySource": "FEED_NAME",
    }


def test_adgroups_add_mobile_app_payload_omits_type():
    """Issue #279: add builds top-level MobileAppAdGroup payload."""
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Mobile App Group",
        "--campaign-id",
        "111",
        "--type",
        "MOBILE_APP_AD_GROUP",
        "--region-ids",
        "1,225",
        "--store-url",
        "https://apps.apple.com/app/id123456789",
        "--target-device-types",
        "device-type-mobile,DEVICE_TYPE_TABLET",
        "--target-carrier",
        "wi-fi-and-cellular",
        "--target-operating-system-version",
        "14.0",
    )
    group = body["params"]["AdGroups"][0]
    assert "Type" not in group
    assert group["MobileAppAdGroup"] == {
        "StoreUrl": "https://apps.apple.com/app/id123456789",
        "TargetDeviceType": ["DEVICE_TYPE_MOBILE", "DEVICE_TYPE_TABLET"],
        "TargetCarrier": "WI_FI_AND_CELLULAR",
        "TargetOperatingSystemVersion": "14.0",
    }


def test_adgroups_add_mobile_app_requires_documented_fields():
    """Issue #279: WSDL minOccurs=1 mobile add fields are locally required."""
    required_options = [
        ("--store-url", "https://apps.apple.com/app/id123456789"),
        ("--target-device-types", "DEVICE_TYPE_MOBILE"),
        ("--target-carrier", "WI_FI_ONLY"),
        ("--target-operating-system-version", "14.0"),
    ]

    for missing_option, _ in required_options:
        args = [
            "adgroups",
            "add",
            "--name",
            "Mobile App Group",
            "--campaign-id",
            "111",
            "--type",
            "MOBILE_APP_AD_GROUP",
            "--region-ids",
            "225",
        ]
        for option, value in required_options:
            if option != missing_option:
                args.extend([option, value])

        result = _rejected(*args)
        assert missing_option in result.output
        assert "required for MOBILE_APP_AD_GROUP" in result.output


def test_adgroups_add_mobile_app_rejects_invalid_device_type():
    """Issue #279: TargetDeviceType is validated against the API enum."""
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Mobile App Group",
        "--campaign-id",
        "111",
        "--type",
        "MOBILE_APP_AD_GROUP",
        "--region-ids",
        "225",
        "--store-url",
        "https://apps.apple.com/app/id123456789",
        "--target-device-types",
        "DEVICE_TYPE_DESKTOP",
        "--target-carrier",
        "WI_FI_ONLY",
        "--target-operating-system-version",
        "14.0",
    )
    assert "--target-device-types has invalid value 'DEVICE_TYPE_DESKTOP'" in (
        result.output
    )
    assert "DEVICE_TYPE_MOBILE, DEVICE_TYPE_TABLET" in result.output


def test_adgroups_add_rejects_incompatible_subtype_flags():
    text_result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Group A",
        "--campaign-id",
        "111",
        "--region-ids",
        "225",
        "--type",
        "TEXT_AD_GROUP",
        "--domain-url",
        "example.com",
    )
    dynamic_result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Dynamic Group",
        "--campaign-id",
        "111",
        "--region-ids",
        "225",
        "--type",
        "DYNAMIC_TEXT_AD_GROUP",
        "--domain-url",
        "example.com",
        "--feed-id",
        "77",
    )
    smart_result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Smart Group",
        "--campaign-id",
        "111",
        "--region-ids",
        "225",
        "--type",
        "SMART_AD_GROUP",
        "--feed-id",
        "77",
        "--domain-url",
        "example.com",
    )
    text_autotargeting_result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Group A",
        "--campaign-id",
        "111",
        "--region-ids",
        "225",
        "--type",
        "TEXT_AD_GROUP",
        "--autotargeting-category",
        "EXACT=YES",
    )
    text_mobile_result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Group A",
        "--campaign-id",
        "111",
        "--region-ids",
        "225",
        "--type",
        "TEXT_AD_GROUP",
        "--store-url",
        "https://apps.apple.com/app/id123456789",
    )
    mobile_result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Mobile App Group",
        "--campaign-id",
        "111",
        "--region-ids",
        "225",
        "--type",
        "MOBILE_APP_AD_GROUP",
        "--store-url",
        "https://apps.apple.com/app/id123456789",
        "--target-device-types",
        "DEVICE_TYPE_MOBILE",
        "--target-carrier",
        "WI_FI_ONLY",
        "--target-operating-system-version",
        "14.0",
        "--feed-id",
        "77",
    )

    assert (
        "--domain-url is not compatible with --type TEXT_AD_GROUP" in text_result.output
    )
    assert (
        "--feed-id is not compatible with --type DYNAMIC_TEXT_AD_GROUP"
        in dynamic_result.output
    )
    assert (
        "--domain-url is not compatible with --type SMART_AD_GROUP"
        in smart_result.output
    )
    assert (
        "--autotargeting-category is not compatible with --type TEXT_AD_GROUP"
        in text_autotargeting_result.output
    )
    assert (
        "--store-url is not compatible with --type TEXT_AD_GROUP"
        in text_mobile_result.output
    )
    assert (
        "--feed-id is not compatible with --type MOBILE_APP_AD_GROUP"
        in mobile_result.output
    )


def test_adgroups_update_payload_name_only():
    body = _dry_run("adgroups", "update", "--id", "222", "--name", "Renamed")
    assert body["method"] == "update"
    group = body["params"]["AdGroups"][0]
    assert group == {"Id": 222, "Name": "Renamed"}


def test_adgroups_update_tracking_params_payload():
    body = _dry_run(
        "adgroups",
        "update",
        "--id",
        "222",
        "--tracking-params",
        "utm_source=direct",
    )
    group = body["params"]["AdGroups"][0]
    assert group == {"Id": 222, "TrackingParams": "utm_source=direct"}


def test_adgroups_update_dynamic_domain_url_payload_without_type():
    """Issue #280: update sets top-level DynamicTextAdGroup without --type."""
    body = _dry_run(
        "adgroups",
        "update",
        "--id",
        "222",
        "--domain-url",
        "example.com",
    )
    group = body["params"]["AdGroups"][0]
    assert group == {"Id": 222, "DynamicTextAdGroup": {"DomainUrl": "example.com"}}


def test_adgroups_update_dynamic_autotargeting_categories_payload():
    """Issue #280: update includes DynamicTextAdGroup.AutotargetingCategories."""
    body = _dry_run(
        "adgroups",
        "update",
        "--id",
        "222",
        "--domain-url",
        "example.com",
        "--autotargeting-category",
        "ALTERNATIVE=YES",
        "--autotargeting-category",
        "competitor=no",
    )
    group = body["params"]["AdGroups"][0]
    assert group == {
        "Id": 222,
        "DynamicTextAdGroup": {
            "DomainUrl": "example.com",
            "AutotargetingCategories": [
                {"Category": "ALTERNATIVE", "Value": "YES"},
                {"Category": "COMPETITOR", "Value": "NO"},
            ],
        },
    }


def test_adgroups_update_dynamic_autotargeting_settings_payload():
    """Issue #280: update includes DynamicTextAdGroup.AutotargetingSettings."""
    body = _dry_run(
        "adgroups",
        "update",
        "--id",
        "222",
        "--domain-url",
        "example.com",
        "--autotargeting-settings-alternative",
        "YES",
        "--autotargeting-settings-accessory",
        "no",
        "--autotargeting-settings-broader",
        "yes",
        "--autotargeting-settings-with-advertiser-brand",
        "NO",
    )
    group = body["params"]["AdGroups"][0]
    assert group == {
        "Id": 222,
        "DynamicTextAdGroup": {
            "DomainUrl": "example.com",
            "AutotargetingSettings": {
                "Categories": {
                    "Alternative": "YES",
                    "Accessory": "NO",
                    "Broader": "YES",
                },
                "BrandOptions": {
                    "WithAdvertiserBrand": "NO",
                },
            },
        },
    }


def test_adgroups_update_dynamic_autotargeting_requires_domain_url():
    """Issue #280: DynamicTextAdGroupUpdate.DomainUrl is required by docs/WSDL."""
    result = _rejected(
        "adgroups",
        "update",
        "--id",
        "222",
        "--autotargeting-category",
        "EXACT=YES",
    )
    assert "--domain-url is required for DYNAMIC_TEXT_AD_GROUP" in result.output


def test_adgroups_update_dynamic_autotargeting_rejects_legacy_mix():
    """Issue #280: legacy categories and AutotargetingSettings cannot mix."""
    result = _rejected(
        "adgroups",
        "update",
        "--id",
        "222",
        "--domain-url",
        "example.com",
        "--autotargeting-category",
        "EXACT=YES",
        "--autotargeting-settings-exact",
        "YES",
    )
    assert "AutotargetingSettings flags cannot be combined" in result.output


def test_adgroups_update_mobile_app_payload_without_type():
    """Issue #279: update sets top-level MobileAppAdGroup without --type."""
    body = _dry_run(
        "adgroups",
        "update",
        "--id",
        "222",
        "--target-device-types",
        "device-type-tablet",
        "--target-carrier",
        "wi-fi-only",
        "--target-operating-system-version",
        "13.0",
    )
    group = body["params"]["AdGroups"][0]
    assert group == {
        "Id": 222,
        "MobileAppAdGroup": {
            "TargetDeviceType": ["DEVICE_TYPE_TABLET"],
            "TargetCarrier": "WI_FI_ONLY",
            "TargetOperatingSystemVersion": "13.0",
        },
    }


def test_adgroups_update_mobile_app_rejects_invalid_carrier():
    """Issue #279: TargetCarrier is validated against the API enum."""
    result = _rejected(
        "adgroups",
        "update",
        "--id",
        "222",
        "--target-carrier",
        "CELLULAR_ONLY",
    )
    assert "--target-carrier has invalid value 'CELLULAR_ONLY'" in result.output
    assert "WI_FI_ONLY or WI_FI_AND_CELLULAR" not in result.output
    assert "WI_FI_ONLY, WI_FI_AND_CELLULAR" in result.output


def test_adgroups_update_negative_keywords_payload():
    body = _dry_run(
        "adgroups",
        "update",
        "--id",
        "222",
        "--negative-keywords",
        "word1, word2",
    )
    group = body["params"]["AdGroups"][0]
    assert group == {"Id": 222, "NegativeKeywords": {"Items": ["word1", "word2"]}}


def test_adgroups_update_negative_keyword_shared_set_ids_payload():
    body = _dry_run(
        "adgroups",
        "update",
        "--id",
        "222",
        "--negative-keyword-shared-set-ids",
        "10,11",
    )
    group = body["params"]["AdGroups"][0]
    assert group == {"Id": 222, "NegativeKeywordSharedSetIds": {"Items": [10, 11]}}


def test_adgroups_update_negative_keyword_shared_set_ids_rejects_invalid_id():
    result = _rejected(
        "adgroups",
        "update",
        "--id",
        "222",
        "--negative-keyword-shared-set-ids",
        "10,nope",
    )
    assert "--negative-keyword-shared-set-ids: Invalid ID: 'nope'" in result.output
    assert "Traceback" not in result.output


def test_adgroups_update_region_ids_rejects_invalid_id():
    result = _rejected(
        "adgroups",
        "update",
        "--id",
        "222",
        "--region-ids",
        "225,nope",
    )
    assert "--region-ids: Invalid ID: 'nope'" in result.output
    assert "Traceback" not in result.output


def test_adgroups_add_tracking_params_accepts_1024_chars():
    tracking_params = "x" * 1024
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Group A",
        "--campaign-id",
        "111",
        "--region-ids",
        "225",
        "--tracking-params",
        tracking_params,
    )
    group = body["params"]["AdGroups"][0]
    assert group["TrackingParams"] == tracking_params


def test_adgroups_add_tracking_params_rejects_1025_chars():
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Group A",
        "--campaign-id",
        "111",
        "--region-ids",
        "225",
        "--tracking-params",
        "x" * 1025,
    )
    assert "--tracking-params must be at most 1024 characters" in result.output


def test_adgroups_update_tracking_params_rejects_1025_chars():
    result = _rejected(
        "adgroups",
        "update",
        "--id",
        "222",
        "--tracking-params",
        "x" * 1025,
    )
    assert "--tracking-params must be at most 1024 characters" in result.output


def test_adgroups_update_without_tracking_params_or_other_fields_rejected():
    result = _rejected("adgroups", "update", "--id", "222")
    assert "--tracking-params" in result.output
    assert "--negative-keywords" in result.output
    assert "--negative-keyword-shared-set-ids" in result.output
    assert "--domain-url" in result.output
    assert "--autotargeting-category" in result.output
    assert "--autotargeting-settings-* flags" in result.output
    assert "--target-device-types" in result.output
    assert "--target-carrier" in result.output
    assert "--target-operating-system-version" in result.output
    assert "requires at least one updatable field" in result.output


# ----------------------------------------------------------------------
# campaigns
# ----------------------------------------------------------------------


def test_campaigns_add_default_text_campaign_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "C1",
        "--start-date",
        "2026-04-10",
    )
    assert body["method"] == "add"
    campaign = body["params"]["Campaigns"][0]
    assert campaign["Name"] == "C1"
    assert campaign["StartDate"] == "2026-04-10"
    assert "TextCampaign" in campaign
    # CLI currently always builds a TextCampaign and never sets a
    # top-level Type — confirm both invariants.
    assert "Type" not in campaign


def test_campaigns_add_with_budget():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "C2",
        "--start-date",
        "2026-04-10",
        "--budget",
        "500000000",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["DailyBudget"] == {"Amount": 500000000, "Mode": "STANDARD"}


def test_campaigns_update_with_budget():
    body = _dry_run("campaigns", "update", "--id", "555", "--budget", "100000000")
    campaign = body["params"]["Campaigns"][0]
    assert campaign["Id"] == 555
    assert campaign["DailyBudget"] == {"Amount": 100000000, "Mode": "STANDARD"}


def test_campaigns_add_case_insensitive_text_type():
    """``--type text_campaign`` (lowercase) builds a TextCampaign.

    Regression guard for axisrow/direct-cli#23 — before the fix --type
    was silently ignored and the CLI always built a TextCampaign
    anyway, which masked typos like ``--type text_campaing``.
    """
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "C-case",
        "--start-date",
        "2026-04-10",
        "--type",
        "text_campaign",
    )
    campaign = body["params"]["Campaigns"][0]
    assert "TextCampaign" in campaign
    assert "Type" not in campaign


def test_campaigns_add_dynamic_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "C-dynamic",
        "--start-date",
        "2026-04-10",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--setting",
        "ADD_METRICA_TAG=NO",
        "--search-strategy",
        "HIGHEST_POSITION",
        "--network-strategy",
        "SERVING_OFF",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["DynamicTextCampaign"] == {
        "BiddingStrategy": {
            "Search": {"BiddingStrategyType": "HIGHEST_POSITION"},
            "Network": {"BiddingStrategyType": "SERVING_OFF"},
        },
        "Settings": [{"Option": "ADD_METRICA_TAG", "Value": "NO"}],
    }


def test_campaigns_add_smart_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "C-smart",
        "--start-date",
        "2026-04-10",
        "--type",
        "SMART_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPC_PER_FILTER",
        "--filter-average-cpc",
        "1000000",
        "--counter-id",
        "123",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["SmartCampaign"] == {
        "BiddingStrategy": {
            "Search": {"BiddingStrategyType": "SERVING_OFF"},
            "Network": {
                "BiddingStrategyType": "AVERAGE_CPC_PER_FILTER",
                "AverageCpcPerFilter": {"FilterAverageCpc": 1000000},
            },
        },
        "CounterId": 123,
    }


def test_campaigns_add_smart_requires_filter_average_cpc():
    result = CliRunner().invoke(
        cli,
        [
            "campaigns",
            "add",
            "--name",
            "C-bad",
            "--start-date",
            "2026-04-10",
            "--type",
            "SMART_CAMPAIGN",
            "--counter-id",
            "42",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    combined = (result.output or "") + (
        str(result.exception) if result.exception else ""
    )
    assert "--filter-average-cpc" in combined or "AVERAGE_CPC_PER_FILTER" in combined


def test_campaigns_add_rejects_incompatible_subtype_flags():
    text_result = _rejected(
        "campaigns",
        "add",
        "--name",
        "C-text",
        "--start-date",
        "2026-04-10",
        "--type",
        "TEXT_CAMPAIGN",
        "--counter-id",
        "123",
    )
    smart_result = _rejected(
        "campaigns",
        "add",
        "--name",
        "C-smart",
        "--start-date",
        "2026-04-10",
        "--type",
        "SMART_CAMPAIGN",
        "--counter-id",
        "123",
        "--network-strategy",
        "SERVING_OFF",
        "--filter-average-cpc",
        "1000000",
    )

    assert (
        "--counter-id is not compatible with --type TEXT_CAMPAIGN" in text_result.output
    )
    assert "AVERAGE_CPC_PER_FILTER" in smart_result.output


# ----------------------------------------------------------------------
# campaigns add: CPA strategy / Notification / TimeTargeting (issue #204)
# ----------------------------------------------------------------------


def _cpa_base_args():
    return [
        "campaigns",
        "add",
        "--name",
        "CPA Campaign",
        "--start-date",
        "2026-06-01",
        "--type",
        "TEXT_CAMPAIGN",
    ]


def test_campaigns_add_average_cpa_search_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPA",
        "--network-strategy",
        "SERVING_OFF",
        "--goal-id",
        "1234567",
        "--average-cpa",
        "500000000",
        "--bid-ceiling",
        "1000000000",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    search = text["BiddingStrategy"]["Search"]
    assert search["BiddingStrategyType"] == "AVERAGE_CPA"
    assert search["AverageCpa"] == {
        "AverageCpa": 500000000,
        "GoalId": 1234567,
        "BidCeiling": 1000000000,
    }


def test_campaigns_add_pay_for_conversion_crr_search_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--network-strategy",
        "SERVING_OFF",
        "--goal-id",
        "555",
        "--crr",
        "8",
    )
    search = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"]["Search"]
    assert search["BiddingStrategyType"] == "PAY_FOR_CONVERSION_CRR"
    # WSDL StrategyPayForConversionCrrAdd: Crr + GoalId both minOccurs=1.
    assert search["PayForConversionCrr"] == {"Crr": 8, "GoalId": 555}


def test_campaigns_add_priority_goals_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--network-strategy",
        "SERVING_OFF",
        "--priority-goals",
        "1234567:80,9876543:20",
        "--bid-ceiling",
        "1000000000",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text["PriorityGoals"] == {
        "Items": [
            {"GoalId": 1234567, "Value": 80},
            {"GoalId": 9876543, "Value": 20},
        ]
    }
    search = text["BiddingStrategy"]["Search"]
    assert search["BiddingStrategyType"] == "AVERAGE_CPA_MULTIPLE_GOALS"
    assert search["AverageCpaMultipleGoals"] == {"BidCeiling": 1000000000}


def test_campaigns_add_counter_ids_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--counter-ids",
        "111,222,333",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text["CounterIds"] == [111, 222, 333]


def test_campaigns_add_notification_payload():
    notification = (
        '{"SmsSettings":{"Events":["FINISHED"],"TimeFrom":"09:00","TimeTo":"18:00"},'
        '"EmailSettings":{"Email":"ops@example.com","SendWarnings":"YES"}}'
    )
    body = _dry_run(*_cpa_base_args(), "--notification", notification)
    campaign = body["params"]["Campaigns"][0]
    assert campaign["Notification"] == {
        "SmsSettings": {
            "Events": ["FINISHED"],
            "TimeFrom": "09:00",
            "TimeTo": "18:00",
        },
        "EmailSettings": {
            "Email": "ops@example.com",
            "SendWarnings": "YES",
        },
    }
    # Lives at campaign level, sibling of TextCampaign.
    assert "Notification" not in campaign["TextCampaign"]


def test_campaigns_add_time_targeting_payload():
    tt = (
        '{"Schedule":["1A0123456789ABCDEFGHIJKL"],'
        '"ConsiderWorkingWeekends":"YES",'
        '"HolidaysSchedule":{"SuspendOnHolidays":"NO","BidPercent":50,'
        '"StartHour":10,"EndHour":20}}'
    )
    body = _dry_run(*_cpa_base_args(), "--time-targeting", tt)
    campaign = body["params"]["Campaigns"][0]
    assert campaign["TimeTargeting"] == {
        "Schedule": ["1A0123456789ABCDEFGHIJKL"],
        "ConsiderWorkingWeekends": "YES",
        "HolidaysSchedule": {
            "SuspendOnHolidays": "NO",
            "BidPercent": 50,
            "StartHour": 10,
            "EndHour": 20,
        },
    }
    assert "TimeTargeting" not in campaign["TextCampaign"]


def test_campaigns_add_text_tracking_params_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--tracking-params",
        "utm_source=direct&utm_campaign={campaign_id}",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text["TrackingParams"] == "utm_source=direct&utm_campaign={campaign_id}"


def test_campaigns_add_dynamic_tracking_params_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Track",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--tracking-params",
        "utm_source=direct&utm_medium=cpc",
    )
    dyn = body["params"]["Campaigns"][0]["DynamicTextCampaign"]
    assert dyn["TrackingParams"] == "utm_source=direct&utm_medium=cpc"


def test_campaigns_add_smart_tracking_params_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Smart Track",
        "--start-date",
        "2026-06-01",
        "--type",
        "SMART_CAMPAIGN",
        "--counter-id",
        "111",
        "--filter-average-cpc",
        "5000000",
        "--tracking-params",
        "utm_source=direct",
    )
    smart = body["params"]["Campaigns"][0]["SmartCampaign"]
    assert smart["TrackingParams"] == "utm_source=direct"


def test_campaigns_add_tracking_params_on_unsupported_type_rejected():
    # MOBILE_APP_CAMPAIGN is not in supported_types for `campaigns add`,
    # so the add guard rejects the type itself before --tracking-params
    # is evaluated. We assert the supported-types message so the test
    # documents this behaviour.
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "X",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--tracking-params",
        "utm_source=direct",
    )
    assert "MOBILE_APP_CAMPAIGN" in result.output


def test_campaigns_update_text_tracking_params_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "TEXT_CAMPAIGN",
        "--tracking-params",
        "utm_source=direct&utm_campaign={campaign_id}",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["Id"] == 123
    assert campaign["TextCampaign"] == {
        "TrackingParams": "utm_source=direct&utm_campaign={campaign_id}",
    }


def test_campaigns_update_dynamic_tracking_params_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--tracking-params",
        "utm_source=direct",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["DynamicTextCampaign"] == {"TrackingParams": "utm_source=direct"}


def test_campaigns_update_smart_tracking_params_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "SMART_CAMPAIGN",
        "--tracking-params",
        "utm_source=direct",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["SmartCampaign"] == {"TrackingParams": "utm_source=direct"}


def test_campaigns_update_tracking_params_without_type_rejected():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--tracking-params",
        "utm_source=direct",
    )
    assert "--tracking-params" in result.output
    assert "--type" in result.output


def test_campaigns_update_unsupported_type_rejected():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--tracking-params",
        "utm_source=direct",
    )
    assert "MOBILE_APP_CAMPAIGN" in result.output


def test_campaigns_update_backward_compat_no_type():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--name",
        "Renamed",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {"Id": 123, "Name": "Renamed"}


def test_campaigns_update_type_without_subtype_fields_rejected():
    # --type without any subtype-specific value must not silently
    # build an empty TextCampaign/DynamicTextCampaign/SmartCampaign block.
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "TEXT_CAMPAIGN",
    )
    assert "TEXT_CAMPAIGN" in result.output


def test_campaigns_add_dynamic_text_campaign_with_cpa():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn CPA",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA",
        "--network-strategy",
        "SERVING_OFF",
        "--goal-id",
        "42",
        "--average-cpa",
        "200000000",
        "--counter-ids",
        "555",
    )
    dyn = body["params"]["Campaigns"][0]["DynamicTextCampaign"]
    search = dyn["BiddingStrategy"]["Search"]
    assert search["BiddingStrategyType"] == "AVERAGE_CPA"
    assert search["AverageCpa"] == {"AverageCpa": 200000000, "GoalId": 42}
    assert dyn["CounterIds"] == [555]


def test_campaigns_add_smart_campaign_keeps_counter_id_singular():
    """Regression: SMART_CAMPAIGN still uses singular --counter-id."""
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Smart",
        "--start-date",
        "2026-06-01",
        "--type",
        "SMART_CAMPAIGN",
        "--counter-id",
        "987",
        "--network-strategy",
        "AVERAGE_CPC_PER_FILTER",
        "--filter-average-cpc",
        "1000000",
    )
    smart = body["params"]["Campaigns"][0]["SmartCampaign"]
    assert smart["CounterId"] == 987
    assert "CounterIds" not in smart


def test_campaigns_add_rejects_average_cpa_for_highest_position():
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "HIGHEST_POSITION",
        "--network-strategy",
        "SERVING_OFF",
        "--average-cpa",
        "100000000",
    )
    assert "--average-cpa" in result.output and "CPA-shaped" in result.output


def test_campaigns_add_rejects_goal_id_for_highest_position():
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "HIGHEST_POSITION",
        "--network-strategy",
        "SERVING_OFF",
        "--goal-id",
        "1",
    )
    assert "--goal-id" in result.output or "CPA-shaped" in result.output


def test_campaigns_add_rejects_priority_goals_for_single_goal_strategy():
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPA",
        "--network-strategy",
        "SERVING_OFF",
        "--goal-id",
        "1",
        "--average-cpa",
        "100000000",
        "--priority-goals",
        "1:50,2:50",
    )
    assert "--priority-goals" in result.output and "MULTIPLE_GOALS" in result.output


def test_campaigns_add_rejects_priority_goals_bad_shape_missing_weight():
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--network-strategy",
        "SERVING_OFF",
        "--priority-goals",
        "1:",
    )
    assert "--priority-goals" in result.output


def test_campaigns_add_rejects_priority_goals_non_integer():
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--network-strategy",
        "SERVING_OFF",
        "--priority-goals",
        "abc:80",
    )
    assert "--priority-goals" in result.output
    assert "must be integers" in result.output


def test_campaigns_add_rejects_priority_goals_no_separator():
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--network-strategy",
        "SERVING_OFF",
        "--priority-goals",
        "1:80,broken",
    )
    assert "--priority-goals" in result.output


def test_campaigns_add_rejects_notification_bad_json():
    result = _rejected(*_cpa_base_args(), "--notification", "not-json")
    assert "--notification" in result.output


def test_campaigns_add_rejects_notification_unknown_top_level_key():
    result = _rejected(*_cpa_base_args(), "--notification", '{"Foo":1}')
    assert "--notification" in result.output and "unknown key" in result.output


def test_campaigns_add_rejects_notification_empty_object():
    result = _rejected(*_cpa_base_args(), "--notification", "{}")
    assert "non-empty" in result.output


def test_campaigns_add_rejects_notification_unknown_sms_key():
    result = _rejected(
        *_cpa_base_args(),
        "--notification",
        '{"SmsSettings":{"Foo":1}}',
    )
    assert "SmsSettings" in result.output and "unknown key" in result.output


def test_campaigns_add_rejects_notification_unknown_email_key():
    result = _rejected(
        *_cpa_base_args(),
        "--notification",
        '{"EmailSettings":{"Foo":1}}',
    )
    assert "EmailSettings" in result.output and "unknown key" in result.output


def test_campaigns_add_rejects_time_targeting_bad_json():
    result = _rejected(*_cpa_base_args(), "--time-targeting", "x")
    assert "--time-targeting" in result.output


def test_campaigns_add_rejects_time_targeting_unknown_key():
    result = _rejected(
        *_cpa_base_args(),
        "--time-targeting",
        '{"Foo":1}',
    )
    assert "--time-targeting" in result.output and "unknown key" in result.output


def test_campaigns_add_rejects_time_targeting_empty():
    result = _rejected(*_cpa_base_args(), "--time-targeting", "{}")
    assert "non-empty" in result.output


def test_campaigns_add_rejects_time_targeting_unknown_holidays_key():
    result = _rejected(
        *_cpa_base_args(),
        "--time-targeting",
        '{"HolidaysSchedule":{"Foo":1}}',
    )
    assert "HolidaysSchedule" in result.output and "unknown key" in result.output


def test_campaigns_add_rejects_counter_ids_for_smart_campaign():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Smart no counter-ids",
        "--start-date",
        "2026-06-01",
        "--type",
        "SMART_CAMPAIGN",
        "--counter-id",
        "987",
        "--network-strategy",
        "AVERAGE_CPC_PER_FILTER",
        "--filter-average-cpc",
        "1000000",
        "--counter-ids",
        "111",
    )
    assert "--counter-ids" in result.output and "SMART_CAMPAIGN" in result.output


def test_campaigns_add_rejects_counter_ids_empty():
    result = _rejected(*_cpa_base_args(), "--counter-ids", "")
    assert "--counter-ids" in result.output


def test_campaigns_add_rejects_bid_ceiling_for_pay_for_conversion_crr():
    """WSDL StrategyPayForConversionCrrAdd has no BidCeiling field."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--network-strategy",
        "SERVING_OFF",
        "--goal-id",
        "1",
        "--crr",
        "8",
        "--bid-ceiling",
        "1000000",
    )
    assert "--bid-ceiling" in result.output
    assert "PayForConversionCrr" in result.output


def test_campaigns_add_rejects_bid_ceiling_for_pay_for_conversion_multiple_goals():
    """WSDL StrategyPayForConversionMultipleGoalsAdd has no BidCeiling field."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "PAY_FOR_CONVERSION_MULTIPLE_GOALS",
        "--network-strategy",
        "SERVING_OFF",
        "--priority-goals",
        "1:50,2:50",
        "--bid-ceiling",
        "1000000",
    )
    assert "--bid-ceiling" in result.output
    assert "PayForConversionMultipleGoals" in result.output


def test_campaigns_add_rejects_pay_for_conversion_crr_without_crr():
    """PayForConversionCrr.Crr is minOccurs=1 — CLI must demand --crr."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--network-strategy",
        "SERVING_OFF",
        "--goal-id",
        "1",
    )
    assert "--crr" in result.output
    assert "PayForConversionCrr" in result.output


def test_campaigns_add_rejects_pay_for_conversion_crr_without_goal_id():
    """PayForConversionCrr.GoalId is minOccurs=1."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--network-strategy",
        "SERVING_OFF",
        "--crr",
        "8",
    )
    assert "--goal-id" in result.output


def test_campaigns_add_rejects_average_cpa_strategy_without_required_fields():
    """StrategyAverageCpaAdd: AverageCpa + GoalId both minOccurs=1."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPA",
        "--network-strategy",
        "SERVING_OFF",
    )
    out = result.output
    assert "--average-cpa" in out and "--goal-id" in out


def test_campaigns_add_rejects_multiple_goals_strategy_without_priority_goals():
    """StrategyAverageCpaMultipleGoals requires PriorityGoals at WSDL."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--network-strategy",
        "SERVING_OFF",
    )
    assert "--priority-goals" in result.output


def test_campaigns_add_rejects_crr_for_average_cpa():
    """--crr is only valid for PAY_FOR_CONVERSION_CRR."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPA",
        "--network-strategy",
        "SERVING_OFF",
        "--goal-id",
        "1",
        "--average-cpa",
        "100000",
        "--crr",
        "8",
    )
    assert "--crr" in result.output and "PayForConversionCrr" in result.output


def test_campaigns_add_rejects_text_campaign_with_per_campaign_network_strategy():
    """Per-Campaign/Per-Filter exist only on SmartCampaign; rejecting them
    for TEXT_CAMPAIGN prevents emitting WSDL-invalid keys."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "HIGHEST_POSITION",
        "--network-strategy",
        "AVERAGE_CPA_PER_CAMPAIGN",
        "--goal-id",
        "1",
        "--average-cpa",
        "100000",
    )
    # Without --network-strategy in the typed-subtype map, --average-cpa
    # has no CPA-shaped strategy to land on → CLI rejects.
    assert "CPA-shaped" in result.output


# ----------------------------------------------------------------------
# keywords
# ----------------------------------------------------------------------


def test_keywords_add_payload_with_bids():
    body = _dry_run(
        "keywords",
        "add",
        "--adgroup-id",
        "12",
        "--keyword",
        "купить пиццу",
        "--bid",
        "15000000",
        "--context-bid",
        "5000000",
    )
    assert body["method"] == "add"
    keyword = body["params"]["Keywords"][0]
    assert keyword["AdGroupId"] == 12
    assert keyword["Keyword"] == "купить пиццу"
    assert keyword["Bid"] == 15000000
    assert keyword["ContextBid"] == 5000000


def test_keywords_add_payload_with_scalar_autotargeting_fields():
    body = _dry_run(
        "keywords",
        "add",
        "--adgroup-id",
        "12",
        "--keyword",
        "---autotargeting",
        "--autotargeting-search-bid-is-auto",
        "yes",
        "--priority",
        "high",
    )
    keyword = body["params"]["Keywords"][0]
    assert keyword == {
        "AdGroupId": 12,
        "Keyword": "---autotargeting",
        "AutotargetingSearchBidIsAuto": "YES",
        "StrategyPriority": "HIGH",
    }


def test_keywords_add_payload_with_autotargeting_categories():
    body = _dry_run(
        "keywords",
        "add",
        "--adgroup-id",
        "12",
        "--keyword",
        "---autotargeting",
        "--autotargeting-category",
        "exact=yes",
        "--autotargeting-category",
        "BROADER=NO",
    )
    keyword = body["params"]["Keywords"][0]
    assert keyword == {
        "AdGroupId": 12,
        "Keyword": "---autotargeting",
        "AutotargetingCategories": [
            {"Category": "EXACT", "Value": "YES"},
            {"Category": "BROADER", "Value": "NO"},
        ],
    }


def test_keywords_add_payload_with_autotargeting_brand_options():
    body = _dry_run(
        "keywords",
        "add",
        "--adgroup-id",
        "12",
        "--keyword",
        "---autotargeting",
        "--autotargeting-brand-option",
        "without_brands=yes",
        "--autotargeting-brand-option",
        "WITH_ADVERTISER_BRAND=NO",
    )
    keyword = body["params"]["Keywords"][0]
    assert keyword == {
        "AdGroupId": 12,
        "Keyword": "---autotargeting",
        "AutotargetingBrandOptions": [
            {"Option": "WITHOUT_BRANDS", "Value": "YES"},
            {"Option": "WITH_ADVERTISER_BRAND", "Value": "NO"},
        ],
    }


def test_keywords_add_payload_with_autotargeting_settings():
    body = _dry_run(
        "keywords",
        "add",
        "--adgroup-id",
        "12",
        "--keyword",
        "---autotargeting",
        "--autotargeting-settings-exact",
        "yes",
        "--autotargeting-settings-narrow",
        "no",
        "--autotargeting-settings-without-brands",
        "YES",
        "--autotargeting-settings-with-competitors-brand",
        "no",
    )
    keyword = body["params"]["Keywords"][0]
    assert keyword == {
        "AdGroupId": 12,
        "Keyword": "---autotargeting",
        "AutotargetingSettings": {
            "Categories": {
                "Exact": "YES",
                "Narrow": "NO",
            },
            "BrandOptions": {
                "WithoutBrands": "YES",
                "WithCompetitorsBrand": "NO",
            },
        },
    }


def test_keywords_add_rejects_scalar_autotargeting_flags_in_batch_mode(tmp_path):
    path = _write_jsonl(tmp_path, [{"Keyword": "kw", "AdGroupId": 100}])
    for flag, value in (
        ("--priority", "HIGH"),
        ("--autotargeting-search-bid-is-auto", "YES"),
        ("--autotargeting-category", "EXACT=YES"),
        ("--autotargeting-brand-option", "WITHOUT_BRANDS=YES"),
        ("--autotargeting-settings-exact", "YES"),
    ):
        result = CliRunner().invoke(
            cli,
            [
                "keywords",
                "add",
                "--from-file",
                path,
                flag,
                value,
                "--dry-run",
            ],
        )
        assert result.exit_code != 0
        assert "single-item mode" in result.output
        assert flag in result.output


def test_keywords_add_rejects_single_item_flags_in_batch_mode(tmp_path):
    path = _write_jsonl(tmp_path, [{"Keyword": "kw", "AdGroupId": 100}])
    result = CliRunner().invoke(
        cli,
        [
            "keywords",
            "add",
            "--from-file",
            path,
            "--bid",
            "15000000",
            "--context-bid",
            "5000000",
            "--user-param-1",
            "segment-a",
            "--user-param-2",
            "segment-b",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "single-item mode" in result.output
    assert "--bid" in result.output
    assert "--context-bid" in result.output
    assert "--user-param-1" in result.output
    assert "--user-param-2" in result.output


def test_keywords_update_payload_keyword_text():
    body = _dry_run("keywords", "update", "--id", "777", "--keyword", "new text")
    keyword = body["params"]["Keywords"][0]
    assert keyword == {"Id": 777, "Keyword": "new text"}


def test_keywords_update_payload_user_params():
    body = _dry_run(
        "keywords",
        "update",
        "--id",
        "777",
        "--user-param-1",
        "seg-a",
        "--user-param-2",
        "seg-b",
    )
    keyword = body["params"]["Keywords"][0]
    assert keyword == {"Id": 777, "UserParam1": "seg-a", "UserParam2": "seg-b"}


def test_keywords_update_rejects_noop_payload():
    result = CliRunner().invoke(
        cli,
        [
            "keywords",
            "update",
            "--id",
            "777",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "requires at least one updatable field" in result.output
    assert "--autotargeting-settings-* flags" in result.output


def test_keywords_update_payload_with_autotargeting_categories():
    body = _dry_run(
        "keywords",
        "update",
        "--id",
        "777",
        "--autotargeting-category",
        "ALTERNATIVE=YES",
        "--autotargeting-category",
        "competitor=no",
    )
    keyword = body["params"]["Keywords"][0]
    assert keyword == {
        "Id": 777,
        "AutotargetingCategories": [
            {"Category": "ALTERNATIVE", "Value": "YES"},
            {"Category": "COMPETITOR", "Value": "NO"},
        ],
    }


def test_keywords_update_payload_with_autotargeting_brand_options():
    body = _dry_run(
        "keywords",
        "update",
        "--id",
        "777",
        "--autotargeting-brand-option",
        "WITHOUT_BRANDS=NO",
        "--autotargeting-brand-option",
        "with_advertiser_brand=yes",
    )
    keyword = body["params"]["Keywords"][0]
    assert keyword == {
        "Id": 777,
        "AutotargetingBrandOptions": [
            {"Option": "WITHOUT_BRANDS", "Value": "NO"},
            {"Option": "WITH_ADVERTISER_BRAND", "Value": "YES"},
        ],
    }


def test_keywords_update_payload_with_autotargeting_settings():
    body = _dry_run(
        "keywords",
        "update",
        "--id",
        "777",
        "--autotargeting-settings-alternative",
        "YES",
        "--autotargeting-settings-accessory",
        "no",
        "--autotargeting-settings-broader",
        "yes",
        "--autotargeting-settings-with-advertiser-brand",
        "NO",
    )
    keyword = body["params"]["Keywords"][0]
    assert keyword == {
        "Id": 777,
        "AutotargetingSettings": {
            "Categories": {
                "Alternative": "YES",
                "Accessory": "NO",
                "Broader": "YES",
            },
            "BrandOptions": {
                "WithAdvertiserBrand": "NO",
            },
        },
    }


def test_keywords_autotargeting_settings_rejects_legacy_category_mix():
    result = CliRunner().invoke(
        cli,
        [
            "keywords",
            "add",
            "--adgroup-id",
            "12",
            "--keyword",
            "---autotargeting",
            "--autotargeting-category",
            "EXACT=YES",
            "--autotargeting-settings-exact",
            "YES",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "cannot be combined" in result.output
    assert "--autotargeting-category" in result.output


def test_keywords_autotargeting_settings_rejects_legacy_brand_option_mix():
    result = CliRunner().invoke(
        cli,
        [
            "keywords",
            "update",
            "--id",
            "777",
            "--autotargeting-brand-option",
            "WITHOUT_BRANDS=YES",
            "--autotargeting-settings-without-brands",
            "YES",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "cannot be combined" in result.output
    assert "--autotargeting-brand-option" in result.output


def test_keywords_autotargeting_category_requires_category_value_pair():
    result = CliRunner().invoke(
        cli,
        [
            "keywords",
            "add",
            "--adgroup-id",
            "12",
            "--keyword",
            "---autotargeting",
            "--autotargeting-category",
            "EXACT",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "CATEGORY=YES|NO" in result.output


def test_keywords_autotargeting_category_rejects_unknown_category():
    result = CliRunner().invoke(
        cli,
        [
            "keywords",
            "update",
            "--id",
            "777",
            "--autotargeting-category",
            "UNKNOWN=YES",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "Invalid --autotargeting-category category" in result.output
    assert "EXACT" in result.output


def test_keywords_autotargeting_category_rejects_unknown_value():
    result = CliRunner().invoke(
        cli,
        [
            "keywords",
            "update",
            "--id",
            "777",
            "--autotargeting-category",
            "EXACT=MAYBE",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "expected YES or NO" in result.output


def test_keywords_autotargeting_brand_option_requires_option_value_pair():
    result = CliRunner().invoke(
        cli,
        [
            "keywords",
            "add",
            "--adgroup-id",
            "12",
            "--keyword",
            "---autotargeting",
            "--autotargeting-brand-option",
            "WITHOUT_BRANDS",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "OPTION=YES|NO" in result.output


def test_keywords_autotargeting_brand_option_rejects_unknown_option():
    result = CliRunner().invoke(
        cli,
        [
            "keywords",
            "update",
            "--id",
            "777",
            "--autotargeting-brand-option",
            "WITH_COMPETITORS_BRAND=YES",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "Invalid --autotargeting-brand-option option" in result.output
    assert "WITHOUT_BRANDS" in result.output


def test_keywords_autotargeting_brand_option_rejects_unknown_value():
    result = CliRunner().invoke(
        cli,
        [
            "keywords",
            "update",
            "--id",
            "777",
            "--autotargeting-brand-option",
            "WITHOUT_BRANDS=MAYBE",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "expected YES or NO" in result.output


# ----------------------------------------------------------------------
# keywords add: batch mode (issue #203)
# ----------------------------------------------------------------------


def _write_jsonl(tmp_path, rows):
    path = tmp_path / "keywords.jsonl"
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return str(path)


def test_keywords_add_payload_batch_from_jsonl(tmp_path):
    path = _write_jsonl(
        tmp_path,
        [
            {"Keyword": "buy laptop", "AdGroupId": 100, "Bid": 10000000},
            {"Keyword": "buy desktop", "AdGroupId": 100},
            {"Keyword": "купить тест", "AdGroupId": 200, "UserParam1": "src=a"},
        ],
    )
    body = _dry_run("keywords", "add", "--from-file", path)
    assert body["chunks"] == 1
    assert body["totalItems"] == 3
    assert body["chunkSize"] == 10
    keywords = body["firstChunk"]["params"]["Keywords"]
    assert body["firstChunk"]["method"] == "add"
    assert keywords[0] == {
        "Keyword": "buy laptop",
        "AdGroupId": 100,
        "Bid": 10000000,
    }
    assert keywords[2] == {
        "Keyword": "купить тест",
        "AdGroupId": 200,
        "UserParam1": "src=a",
    }


def test_keywords_add_payload_batch_inline():
    inline = json.dumps(
        [
            {"Keyword": "kw-a", "AdGroupId": 1},
            {"Keyword": "kw-b", "AdGroupId": 1, "ContextBid": 5000000},
        ]
    )
    body = _dry_run("keywords", "add", "--keywords-json", inline)
    assert body["totalItems"] == 2
    assert body["chunks"] == 1
    assert body["firstChunk"]["params"]["Keywords"][1]["ContextBid"] == 5000000


def test_keywords_add_payload_batch_chunks_at_10(tmp_path):
    rows = [{"Keyword": f"kw-{i}", "AdGroupId": 1} for i in range(25)]
    path = _write_jsonl(tmp_path, rows)
    body = _dry_run("keywords", "add", "--from-file", path)
    assert body["chunks"] == 3
    assert body["totalItems"] == 25
    first_chunk = body["firstChunk"]["params"]["Keywords"]
    assert len(first_chunk) == 10
    assert [k["Keyword"] for k in first_chunk] == [f"kw-{i}" for i in range(10)]


def test_keywords_add_payload_adgroup_override(tmp_path):
    path = _write_jsonl(
        tmp_path,
        [
            {"Keyword": "kw-default"},
            {"Keyword": "kw-override", "AdGroupId": 200},
        ],
    )
    body = _dry_run("keywords", "add", "--adgroup-id", "100", "--from-file", path)
    items = body["firstChunk"]["params"]["Keywords"]
    assert items[0] == {"Keyword": "kw-default", "AdGroupId": 100}
    assert items[1] == {"Keyword": "kw-override", "AdGroupId": 200}


def test_keywords_add_payload_micro_rubles_in_row(tmp_path):
    path = _write_jsonl(
        tmp_path,
        [{"Keyword": "kw", "AdGroupId": 1, "Bid": 15000000}],
    )
    body = _dry_run("keywords", "add", "--from-file", path)
    assert body["firstChunk"]["params"]["Keywords"][0]["Bid"] == 15000000


def test_keywords_add_rejects_unknown_field_in_row(tmp_path):
    path = _write_jsonl(
        tmp_path,
        [{"Keyword": "kw", "AdGroupId": 1, "Foo": "bar"}],
    )
    result = _rejected("keywords", "add", "--from-file", path)
    assert "Unknown field 'Foo' in keyword row 1" in result.output


def test_keywords_add_rejects_autotargeting_row_fields_in_batch(tmp_path):
    deferred_fields = {
        "AutotargetingSearchBidIsAuto": ("YES", "--autotargeting-search-bid-is-auto"),
        "StrategyPriority": ("HIGH", "--priority"),
        "AutotargetingCategories": (
            [{"Category": "EXACT", "Value": "YES"}],
            "--autotargeting-category",
        ),
        "AutotargetingBrandOptions": (
            [{"Option": "WITHOUT_BRANDS", "Value": "YES"}],
            "--autotargeting-brand-option",
        ),
        "AutotargetingSettings": (
            {"Categories": {"Exact": "YES"}},
            "--autotargeting-settings-* flags",
        ),
    }

    for field, (value, expected_flag) in deferred_fields.items():
        path = _write_jsonl(
            tmp_path,
            [{"Keyword": "kw", "AdGroupId": 1, field: value}],
        )
        result = _rejected("keywords", "add", "--from-file", path)
        assert f"field '{field}' is intentionally unsupported" in result.output
        assert "batch mode" in result.output
        assert expected_flag in result.output


def test_keywords_add_rejects_autotargeting_inline_batch_row():
    inline = json.dumps(
        [
            {
                "Keyword": "kw",
                "AdGroupId": 1,
                "AutotargetingSearchBidIsAuto": "YES",
            }
        ]
    )
    result = _rejected("keywords", "add", "--keywords-json", inline)
    assert "AutotargetingSearchBidIsAuto" in result.output
    assert "intentionally unsupported in batch mode" in result.output


def test_keywords_add_rejects_invalid_jsonl(tmp_path):
    path = tmp_path / "broken.jsonl"
    path.write_text(
        '{"Keyword": "ok", "AdGroupId": 1}\n{"Keyword": broken\n',
        encoding="utf-8",
    )
    result = _rejected("keywords", "add", "--from-file", str(path))
    assert "Row 2: invalid JSON" in result.output


def test_keywords_add_rejects_empty_file(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("\n   \n", encoding="utf-8")
    result = _rejected("keywords", "add", "--from-file", str(path))
    assert "Input contains no keyword rows" in result.output


def test_keywords_add_rejects_empty_json_array():
    result = _rejected("keywords", "add", "--keywords-json", "[]")
    assert "Input contains no keyword rows" in result.output


def test_keywords_add_rejects_non_object_row_in_inline():
    result = _rejected("keywords", "add", "--keywords-json", "[1, 2, 3]")
    assert "Row 1" in result.output
    assert "expected JSON object" in result.output


def test_keywords_add_rejects_mutex(tmp_path):
    path = _write_jsonl(tmp_path, [{"Keyword": "kw", "AdGroupId": 1}])
    result = _rejected(
        "keywords",
        "add",
        "--keyword",
        "x",
        "--adgroup-id",
        "1",
        "--from-file",
        path,
    )
    assert "Provide exactly one of" in result.output


def test_keywords_add_rejects_mutex_file_and_inline(tmp_path):
    path = _write_jsonl(tmp_path, [{"Keyword": "kw", "AdGroupId": 1}])
    result = _rejected(
        "keywords",
        "add",
        "--from-file",
        path,
        "--keywords-json",
        "[]",
    )
    assert "Provide exactly one of" in result.output


def test_keywords_add_rejects_missing_required_in_row(tmp_path):
    path = _write_jsonl(tmp_path, [{"Keyword": "kw"}])
    result = _rejected("keywords", "add", "--from-file", path)
    assert "Row 1" in result.output
    assert "AdGroupId" in result.output


def test_keywords_add_rejects_too_low_bid_in_row(tmp_path):
    path = _write_jsonl(
        tmp_path,
        [{"Keyword": "kw", "AdGroupId": 1, "Bid": 50000}],
    )
    result = _rejected("keywords", "add", "--from-file", path)
    assert "Row 1 field 'Bid'" in result.output


def test_keywords_add_rejects_non_json_format_in_batch(tmp_path):
    path = _write_jsonl(tmp_path, [{"Keyword": "kw", "AdGroupId": 1}])
    result = _rejected(
        "keywords",
        "add",
        "--from-file",
        path,
        "--format",
        "table",
    )
    assert "batch mode" in result.output


def test_keywords_add_rejects_no_mode():
    result = _rejected("keywords", "add")
    assert "Provide exactly one of" in result.output


def test_keywords_add_single_still_raises_on_item_error(monkeypatch):
    """Single-mode (non-batch) must still bubble item-level Errors."""
    import importlib

    keywords_module = importlib.import_module("direct_cli.commands.keywords")
    from direct_cli.output import DirectAPIResultError

    class _StubExtract:
        def extract(self):
            return {
                "AddResults": [{"Id": 0, "Errors": [{"Code": 8500, "Message": "bad"}]}]
            }

    class _StubResult:
        def __call__(self):
            return _StubExtract()

    class _StubKeywords:
        def post(self, data):
            return _StubResult()

    class _StubClient:
        def keywords(self):
            return _StubKeywords()

    monkeypatch.setattr(keywords_module, "create_client", lambda **_: _StubClient())
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--token",
            "T",
            "--login",
            "L",
            "keywords",
            "add",
            "--adgroup-id",
            "1",
            "--keyword",
            "kw",
        ],
    )
    assert result.exit_code != 0
    # Single-mode goes through format_output → raise_for_api_result_errors,
    # which DirectAPIResultError-then-Abort. CLI surfaces it via print_error.
    assert "Yandex Direct API returned errors" in result.output or isinstance(
        result.exception, DirectAPIResultError
    )


def test_keywords_add_rejects_bool_in_row(tmp_path):
    """JSON booleans must NOT be silently coerced to 1/0 for int/micro fields."""
    path = _write_jsonl(tmp_path, [{"Keyword": "kw", "AdGroupId": True}])
    result = _rejected("keywords", "add", "--from-file", path)
    assert "Row 1 field 'AdGroupId'" in result.output
    assert "bool" in result.output


def test_keywords_add_empty_string_keyword_counts_as_mode():
    """`--keyword ''` must register as mode-provided, not fall through to
    'Provide exactly one of' (mode-detection uses `is not None`, not
    truthiness)."""
    body = _dry_run("keywords", "add", "--keyword", "", "--adgroup-id", "1")
    assert body["params"]["Keywords"][0] == {"AdGroupId": 1, "Keyword": ""}


def test_keywords_add_batch_warns_when_over_200_per_adgroup(tmp_path):
    """Pre-flight warning when input has >200 keywords for the same AdGroupId
    (Yandex Direct limit)."""
    rows = [{"Keyword": f"kw-{i}", "AdGroupId": 1} for i in range(201)]
    rows.append({"Keyword": "ok", "AdGroupId": 2})
    path = _write_jsonl(tmp_path, rows)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["keywords", "add", "--from-file", str(path), "--dry-run"],
    )
    assert result.exit_code == 0
    assert "exceeds the Yandex Direct limit of 200" in result.output
    assert "AdGroupId=1: 201 keywords (1 over the limit)" in result.output
    # AdGroupId=2 is within the limit; must NOT be flagged.
    assert "AdGroupId=2" not in result.output


def test_keywords_add_batch_no_warning_under_200(tmp_path):
    """No warning when every adgroup is within the 200-keyword limit."""
    rows = [{"Keyword": f"kw-{i}", "AdGroupId": 1} for i in range(150)]
    path = _write_jsonl(tmp_path, rows)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["keywords", "add", "--from-file", str(path), "--dry-run"],
    )
    assert result.exit_code == 0
    assert "exceeds the Yandex Direct limit" not in result.output


def test_keywords_add_batch_partial_success_on_failure(tmp_path, monkeypatch):
    """If a later chunk raises, already-created Ids must be surfaced to the
    user (via stderr) so a retry doesn't create duplicates."""
    import importlib

    keywords_module = importlib.import_module("direct_cli.commands.keywords")

    rows = [{"Keyword": f"kw-{i}", "AdGroupId": 1} for i in range(15)]
    path = _write_jsonl(tmp_path, rows)

    call_count = {"n": 0}

    class _StubExtract:
        def extract(self):
            return {"AddResults": [{"Id": i + 1} for i in range(10)]}

    class _StubResult:
        def __call__(self):
            return _StubExtract()

    class _StubKeywords:
        def post(self, data):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _StubResult()
            raise RuntimeError("network blip on second chunk")

    class _StubClient:
        def keywords(self):
            return _StubKeywords()

    monkeypatch.setattr(keywords_module, "create_client", lambda **_: _StubClient())
    # CliRunner's default mixes stderr into result.output, which is what
    # we want here — the partial-results message goes to stderr but lands
    # in the combined output buffer regardless of Click version.
    result = CliRunner().invoke(
        cli,
        [
            "--token",
            "T",
            "--login",
            "L",
            "keywords",
            "add",
            "--from-file",
            str(path),
        ],
    )
    assert result.exit_code != 0
    assert "Partial success before failure" in result.output
    assert '"Id": 1' in result.output
    assert '"Id": 10' in result.output


# ----------------------------------------------------------------------
# bids / keywordbids
# ----------------------------------------------------------------------


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


# ----------------------------------------------------------------------
# bidmodifiers
# ----------------------------------------------------------------------


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


# ----------------------------------------------------------------------
# feeds
# ----------------------------------------------------------------------


def test_feeds_add_payload_uses_nested_urlfeed():
    body = _dry_run(
        "feeds",
        "add",
        "--name",
        "Feed A",
        "--url",
        "https://example.com/feed.xml",
        "--business-type",
        "RETAIL",
    )
    assert body["method"] == "add"
    feed = body["params"]["Feeds"][0]
    # The API requires Name, BusinessType (minOccurs=1 in WSDL), SourceType
    # discriminator, and the nested UrlFeed/FileFeed object carrying the URL.
    assert feed == {
        "Name": "Feed A",
        "BusinessType": "RETAIL",
        "SourceType": "URL",
        "UrlFeed": {"Url": "https://example.com/feed.xml"},
    }


def test_feeds_add_payload_accepts_urlfeed_details():
    body = _dry_run(
        "feeds",
        "add",
        "--name",
        "Feed A",
        "--url",
        "https://example.com/feed.xml",
        "--business-type",
        "RETAIL",
        "--remove-utm-tags",
        "yes",
        "--feed-login",
        "feedbot",
        "--feed-password",
        "secret",
    )
    feed = body["params"]["Feeds"][0]
    assert feed["SourceType"] == "URL"
    assert feed["UrlFeed"] == {
        "Url": "https://example.com/feed.xml",
        "RemoveUtmTags": "YES",
        "Login": "feedbot",
        "Password": "secret",
    }


def test_feeds_add_payload_accepts_filefeed_upload(tmp_path):
    feed_path = tmp_path / "feed.xml"
    feed_bytes = b"<yml_catalog><shop /></yml_catalog>"
    feed_path.write_bytes(feed_bytes)

    body = _dry_run(
        "feeds",
        "add",
        "--name",
        "Feed A",
        "--file-feed-path",
        str(feed_path),
        "--business-type",
        "retail",
    )
    feed = body["params"]["Feeds"][0]
    assert feed == {
        "Name": "Feed A",
        "BusinessType": "RETAIL",
        "SourceType": "FILE",
        "FileFeed": {
            "Data": base64.b64encode(feed_bytes).decode("ascii"),
            "Filename": "feed.xml",
        },
    }


def test_feeds_add_payload_accepts_filefeed_filename_override(tmp_path):
    feed_path = tmp_path / "source.tmp"
    feed_path.write_bytes(b"id,name\n1,chair\n")

    body = _dry_run(
        "feeds",
        "add",
        "--name",
        "Feed A",
        "--file-feed-path",
        str(feed_path),
        "--file-feed-filename",
        "products.csv",
        "--business-type",
        "RETAIL",
    )
    feed = body["params"]["Feeds"][0]
    assert feed["SourceType"] == "FILE"
    assert feed["FileFeed"]["Filename"] == "products.csv"


def test_feeds_add_rejects_url_and_filefeed_mix(tmp_path):
    feed_path = tmp_path / "feed.xml"
    feed_path.write_text("<feed />", encoding="utf-8")

    result = _rejected(
        "feeds",
        "add",
        "--name",
        "Feed A",
        "--url",
        "https://example.com/feed.xml",
        "--file-feed-path",
        str(feed_path),
        "--business-type",
        "RETAIL",
    )
    assert "Use either --url or --file-feed-path" in result.output


def test_feeds_add_rejects_filefeed_filename_without_path():
    result = _rejected(
        "feeds",
        "add",
        "--name",
        "Feed A",
        "--file-feed-filename",
        "feed.xml",
        "--business-type",
        "RETAIL",
    )
    assert "--file-feed-filename requires --file-feed-path" in result.output


def test_feeds_add_rejects_overlong_filefeed_filename(tmp_path):
    feed_path = tmp_path / "feed.xml"
    feed_path.write_text("<feed />", encoding="utf-8")

    result = _rejected(
        "feeds",
        "add",
        "--name",
        "Feed A",
        "--file-feed-path",
        str(feed_path),
        "--file-feed-filename",
        "x" * 256,
        "--business-type",
        "RETAIL",
    )
    assert "FileFeed.Filename must be at most 255 characters" in result.output


def test_feeds_add_rejects_oversized_filefeed_before_reading(tmp_path):
    feed_path = tmp_path / "huge-feed.xml"
    with feed_path.open("wb") as fh:
        fh.truncate((50 * 1024 * 1024) + 1)

    result = _rejected(
        "feeds",
        "add",
        "--name",
        "Feed A",
        "--file-feed-path",
        str(feed_path),
        "--business-type",
        "RETAIL",
    )
    assert "FileFeed.Data must be at most 50 MiB" in result.output


def test_feeds_update_payload_changes_url():
    body = _dry_run(
        "feeds",
        "update",
        "--id",
        "9",
        "--url",
        "https://example.com/feed-v2.xml",
    )
    feed = body["params"]["Feeds"][0]
    assert feed == {"Id": 9, "UrlFeed": {"Url": "https://example.com/feed-v2.xml"}}


def test_feeds_update_payload_accepts_urlfeed_details():
    body = _dry_run(
        "feeds",
        "update",
        "--id",
        "9",
        "--remove-utm-tags",
        "no",
        "--feed-login",
        "feedbot",
        "--feed-password",
        "secret",
    )
    feed = body["params"]["Feeds"][0]
    assert feed == {
        "Id": 9,
        "UrlFeed": {
            "RemoveUtmTags": "NO",
            "Login": "feedbot",
            "Password": "secret",
        },
    }


def test_feeds_update_payload_can_clear_urlfeed_credentials():
    body = _dry_run(
        "feeds",
        "update",
        "--id",
        "9",
        "--clear-feed-login",
        "--clear-feed-password",
    )
    feed = body["params"]["Feeds"][0]
    assert feed == {"Id": 9, "UrlFeed": {"Login": None, "Password": None}}


def test_feeds_update_payload_accepts_filefeed_upload(tmp_path):
    feed_path = tmp_path / "feed.yml"
    feed_bytes = b"offer: 1\n"
    feed_path.write_bytes(feed_bytes)

    body = _dry_run(
        "feeds",
        "update",
        "--id",
        "9",
        "--file-feed-path",
        str(feed_path),
    )
    feed = body["params"]["Feeds"][0]
    assert feed == {
        "Id": 9,
        "FileFeed": {
            "Data": base64.b64encode(feed_bytes).decode("ascii"),
            "Filename": "feed.yml",
        },
    }


def test_feeds_update_rejects_urlfeed_and_filefeed_mix(tmp_path):
    feed_path = tmp_path / "feed.xml"
    feed_path.write_text("<feed />", encoding="utf-8")

    result = _rejected(
        "feeds",
        "update",
        "--id",
        "9",
        "--file-feed-path",
        str(feed_path),
        "--remove-utm-tags",
        "YES",
    )
    assert "FileFeed options cannot be combined with UrlFeed options" in result.output


def test_feeds_update_rejects_setting_and_clearing_login():
    result = CliRunner().invoke(
        cli,
        [
            "feeds",
            "update",
            "--id",
            "9",
            "--feed-login",
            "feedbot",
            "--clear-feed-login",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    combined = (result.output or "") + (
        str(result.exception) if result.exception else ""
    )
    assert "Use either --feed-login or --clear-feed-login" in combined


def test_feeds_update_without_fields_errors():
    result = CliRunner().invoke(
        cli,
        [
            "feeds",
            "update",
            "--id",
            "9",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    combined = (result.output or "") + (
        str(result.exception) if result.exception else ""
    )
    assert "--name" in combined
    assert "--url" in combined
    assert "--file-feed-path" in combined
    assert "--remove-utm-tags" in combined
    assert "--clear-feed-login" in combined


# ----------------------------------------------------------------------
# retargeting
# ----------------------------------------------------------------------


def test_retargeting_add_keeps_list_type():
    # NB: ``Type`` here is the *list category* and IS a real top-level
    # API field, unlike the --type hint on ads/adgroups/smartadtargets.
    # The only two valid values per Yandex Direct docs are ``RETARGETING``
    # and ``AUDIENCE`` (verified against
    # https://yandex.ru/dev/direct/doc/ref-v5/retargetinglists/add.html).
    # This test previously asserted ``AUDIENCE_SEGMENT``, which is not
    # a real enum value — the drift was fixed together with the
    # click.Choice validation added in axisrow/direct-cli#25.
    body = _dry_run(
        "retargeting",
        "add",
        "--name",
        "List A",
        "--type",
        "AUDIENCE",
        "--rule",
        "ALL:12345:30|67890:7",
    )
    assert body["method"] == "add"
    rtg = body["params"]["RetargetingLists"][0]
    assert rtg == {
        "Name": "List A",
        "Type": "AUDIENCE",
        "Rules": [
            {
                "Operator": "ALL",
                "Arguments": [
                    {"ExternalId": 12345, "MembershipLifeSpan": 30},
                    {"ExternalId": 67890, "MembershipLifeSpan": 7},
                ],
            }
        ],
    }


def test_retargeting_add_description_payload():
    body = _dry_run(
        "retargeting",
        "add",
        "--name",
        "List A",
        "--description",
        "High intent users",
        "--rule",
        "ALL:12345:30",
    )
    rtg = body["params"]["RetargetingLists"][0]
    assert rtg["Description"] == "High intent users"


def test_retargeting_add_empty_description_payload():
    body = _dry_run(
        "retargeting",
        "add",
        "--name",
        "List A",
        "--description",
        "",
        "--rule",
        "ALL:12345:30",
    )
    rtg = body["params"]["RetargetingLists"][0]
    assert rtg["Description"] == ""


def test_retargeting_add_description_accepts_4096_chars():
    description = "x" * 4096
    body = _dry_run(
        "retargeting",
        "add",
        "--name",
        "List A",
        "--description",
        description,
        "--rule",
        "ALL:12345:30",
    )
    rtg = body["params"]["RetargetingLists"][0]
    assert rtg["Description"] == description


def test_retargeting_add_description_rejects_4097_chars():
    result = _rejected(
        "retargeting",
        "add",
        "--name",
        "List A",
        "--description",
        "x" * 4097,
        "--rule",
        "ALL:12345:30",
    )
    assert "--description must be at most 4096 characters" in result.output


def test_retargeting_add_default_type_is_retargeting():
    """Without ``--type`` the CLI defaults to the API's default RETARGETING.

    Regression guard for axisrow/direct-cli#25 — before the fix ``--type``
    was required=True with no validation. Now it's optional and
    defaults to the same value the API picks when Type is omitted.
    """
    body = _dry_run("retargeting", "add", "--name", "List B", "--rule", "ALL:12345")
    rtg = body["params"]["RetargetingLists"][0]
    assert rtg["Type"] == "RETARGETING"


def test_retargeting_add_unknown_type_is_rejected_by_choice():
    """``click.Choice`` rejects typos / non-enum values up front.

    Regression guard for axisrow/direct-cli#25 — before the fix a
    typo like ``--type AUDIENCE_SEGMENT`` was forwarded verbatim to
    the API, which rejected it with a vague error.
    """
    result = CliRunner().invoke(
        cli,
        [
            "retargeting",
            "add",
            "--name",
            "List bad",
            "--type",
            "AUDIENCE_SEGMENT",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    combined = (result.output or "") + (
        str(result.exception) if result.exception else ""
    )
    assert "AUDIENCE_SEGMENT" in combined or "retargeting" in combined.lower()


# ----------------------------------------------------------------------
# audiencetargets
# ----------------------------------------------------------------------


def test_audiencetargets_add_context_bid():
    body = _dry_run(
        "audiencetargets",
        "add",
        "--adgroup-id",
        "100",
        "--retargeting-list-id",
        "200",
        "--bid",
        "12000000",
        "--priority",
        "high",
    )
    assert body["method"] == "add"
    target = body["params"]["AudienceTargets"][0]
    assert target == {
        "AdGroupId": 100,
        "RetargetingListId": 200,
        "ContextBid": 12000000,
        "StrategyPriority": "HIGH",
    }


def test_audiencetargets_add_rejects_invalid_priority():
    result = _rejected(
        "audiencetargets",
        "add",
        "--adgroup-id",
        "100",
        "--retargeting-list-id",
        "200",
        "--priority",
        "MAX",
    )

    assert "Invalid value for '--priority'" in result.output


def test_audiencetargets_add_accepts_interest_id():
    body = _dry_run(
        "audiencetargets",
        "add",
        "--adgroup-id",
        "100",
        "--interest-id",
        "300",
    )
    assert body["params"]["AudienceTargets"][0] == {
        "AdGroupId": 100,
        "InterestId": 300,
    }


def test_audiencetargets_set_bids_uses_bids_array():
    body = _dry_run(
        "audiencetargets",
        "set-bids",
        "--id",
        "101",
        "--context-bid",
        "7000000",
        "--priority",
        "LOW",
    )
    assert body["method"] == "setBids"
    item = body["params"]["Bids"][0]
    assert item == {
        "Id": 101,
        "ContextBid": 7000000,
        "StrategyPriority": "LOW",
    }


# ----------------------------------------------------------------------
# sitelinks
# ----------------------------------------------------------------------


def test_sitelinks_add_parses_links_array():
    body = _dry_run(
        "sitelinks",
        "add",
        "--sitelink",
        "About|https://example.com/about",
        "--sitelink",
        "Contact|https://example.com/contact",
    )
    assert body["method"] == "add"
    sitelinks_set = body["params"]["SitelinksSets"][0]
    assert sitelinks_set == {
        "Sitelinks": [
            {"Title": "About", "Href": "https://example.com/about"},
            {"Title": "Contact", "Href": "https://example.com/contact"},
        ]
    }


def test_sitelinks_add_supports_escaped_pipe_in_href():
    """UTM templates with literal '|' must round-trip via '\\|'. See #221."""
    body = _dry_run(
        "sitelinks",
        "add",
        "--sitelink",
        (
            "Главная|https://example.com/?utm_content=cid"
            "\\|{campaign_id}\\|gid\\|{gbid}|Узнать больше"
        ),
    )
    sitelink = body["params"]["SitelinksSets"][0]["Sitelinks"][0]
    assert sitelink == {
        "Title": "Главная",
        "Href": "https://example.com/?utm_content=cid|{campaign_id}|gid|{gbid}",
        "Description": "Узнать больше",
    }


def test_sitelinks_add_pipe_spec_turbo_page_id():
    """Issue #257: --sitelink exposes Sitelinks.TurboPageId."""
    body = _dry_run(
        "sitelinks",
        "add",
        "--sitelink",
        "Docs|https://example.com/docs|API docs|12345",
    )
    sitelink = body["params"]["SitelinksSets"][0]["Sitelinks"][0]
    assert sitelink == {
        "Title": "Docs",
        "Href": "https://example.com/docs",
        "Description": "API docs",
        "TurboPageId": 12345,
    }


def test_sitelinks_add_pipe_spec_turbo_page_id_without_href():
    """Yandex API allows Href or TurboPageId on a sitelink."""
    body = _dry_run(
        "sitelinks",
        "add",
        "--sitelink",
        "Turbo||Turbo page|12345",
    )
    sitelink = body["params"]["SitelinksSets"][0]["Sitelinks"][0]
    assert sitelink == {
        "Title": "Turbo",
        "Description": "Turbo page",
        "TurboPageId": 12345,
    }


def test_sitelinks_add_pipe_spec_turbo_page_id_without_href_or_description():
    body = _dry_run(
        "sitelinks",
        "add",
        "--sitelink",
        "Turbo|||12345",
    )
    sitelink = body["params"]["SitelinksSets"][0]["Sitelinks"][0]
    assert sitelink == {"Title": "Turbo", "TurboPageId": 12345}


def test_sitelinks_add_pipe_spec_turbo_page_id_invalid_rejected():
    result = _rejected(
        "sitelinks",
        "add",
        "--sitelink",
        "Docs|https://example.com/docs|API docs|not-an-id",
    )
    assert "TurboPageId must be an integer" in result.output


def test_sitelinks_add_pipe_spec_invalid_raises():
    """Unescaped '|' overflowing the 3-part shape must error with a hint."""
    result = _rejected(
        "sitelinks",
        "add",
        "--sitelink",
        "Главная|https://example.com/?utm=cid|{cid}|gid|{gbid}|Узнать",
    )
    assert "Invalid sitelink" in result.output
    assert "\\|" in result.output


def test_sitelinks_add_from_inline_json():
    body = _dry_run(
        "sitelinks",
        "add",
        "--sitelink-json",
        json.dumps(
            [
                {
                    "Title": "Главная",
                    "Href": "https://example.com/?utm=cid|{cid}",
                    "Description": "Узнать",
                },
                {"Title": "Контакты", "Href": "https://example.com/contact"},
            ]
        ),
    )
    assert body["params"]["SitelinksSets"][0]["Sitelinks"] == [
        {
            "Title": "Главная",
            "Href": "https://example.com/?utm=cid|{cid}",
            "Description": "Узнать",
        },
        {"Title": "Контакты", "Href": "https://example.com/contact"},
    ]


def test_sitelinks_add_from_inline_json_turbo_page_id_without_href():
    body = _dry_run(
        "sitelinks",
        "add",
        "--sitelink-json",
        json.dumps([{"Title": "Turbo", "TurboPageId": 12345}]),
    )
    assert body["params"]["SitelinksSets"][0]["Sitelinks"] == [
        {"Title": "Turbo", "TurboPageId": 12345}
    ]


def test_sitelinks_add_from_inline_json_turbo_page_id_string_coerced():
    body = _dry_run(
        "sitelinks",
        "add",
        "--sitelink-json",
        json.dumps([{"Title": "Turbo", "TurboPageId": "12345"}]),
    )
    assert body["params"]["SitelinksSets"][0]["Sitelinks"] == [
        {"Title": "Turbo", "TurboPageId": 12345}
    ]


def test_sitelinks_add_from_inline_json_turbo_page_id_invalid_rejected():
    result = _rejected(
        "sitelinks",
        "add",
        "--sitelink-json",
        json.dumps([{"Title": "Turbo", "TurboPageId": "not-an-id"}]),
    )
    assert "'TurboPageId' must be an integer" in result.output


def test_sitelinks_add_from_inline_json_turbo_page_id_bool_rejected():
    result = _rejected(
        "sitelinks",
        "add",
        "--sitelink-json",
        json.dumps([{"Title": "Turbo", "TurboPageId": False}]),
    )
    assert "'TurboPageId' must be an integer" in result.output


def test_sitelinks_add_from_inline_json_turbo_page_id_float_rejected():
    result = _rejected(
        "sitelinks",
        "add",
        "--sitelink-json",
        json.dumps([{"Title": "Turbo", "TurboPageId": 12.5}]),
    )
    assert "'TurboPageId' must be an integer" in result.output


def test_sitelinks_add_from_file_jsonl(tmp_path):
    jsonl_path = tmp_path / "sitelinks.jsonl"
    jsonl_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "Title": "Главная",
                        "Href": "https://example.com/?utm=cid|{cid}",
                    }
                ),
                "",
                json.dumps(
                    {
                        "Title": "Контакты",
                        "Href": "https://example.com/contact",
                        "Description": "Связаться",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    body = _dry_run(
        "sitelinks",
        "add",
        "--sitelinks-from-file",
        str(jsonl_path),
    )
    assert body["params"]["SitelinksSets"][0]["Sitelinks"] == [
        {"Title": "Главная", "Href": "https://example.com/?utm=cid|{cid}"},
        {
            "Title": "Контакты",
            "Href": "https://example.com/contact",
            "Description": "Связаться",
        },
    ]


def test_sitelinks_add_mixed_sources_rejected():
    result = _rejected(
        "sitelinks",
        "add",
        "--sitelink",
        "About|https://example.com/about",
        "--sitelink-json",
        '[{"Title":"X","Href":"https://example.com/"}]',
    )
    assert "mutually exclusive" in result.output


def test_sitelinks_add_no_source_rejected():
    result = _rejected("sitelinks", "add")
    assert "Provide exactly one of" in result.output


def test_sitelinks_add_json_missing_href_rejected():
    result = _rejected(
        "sitelinks",
        "add",
        "--sitelink-json",
        '[{"Title":"Главная"}]',
    )
    assert "Sitelink #1" in result.output
    assert "Href" in result.output
    assert "TurboPageId" in result.output


def test_sitelinks_add_json_not_array_rejected():
    result = _rejected(
        "sitelinks",
        "add",
        "--sitelink-json",
        '{"Title":"X","Href":"https://example.com/"}',
    )
    assert "must be a JSON array" in result.output


def test_sitelinks_add_rejects_unknown_field():
    """Typo in a JSON key must fail loudly, not silently drop. See PR #223."""
    result = _rejected(
        "sitelinks",
        "add",
        "--sitelink-json",
        json.dumps(
            [
                {
                    "Title": "Главная",
                    "Href": "https://example.com/",
                    "Decsription": "typo",
                }
            ]
        ),
    )
    assert "Unknown field 'Decsription'" in result.output
    assert "sitelink #1" in result.output


def test_sitelinks_add_empty_json_rejected():
    """`--sitelink-json ''` is provided-but-invalid, not absent. See PR #223."""
    result = _rejected("sitelinks", "add", "--sitelink-json", "")
    assert "invalid JSON" in result.output


# ----------------------------------------------------------------------
# vcards
# ----------------------------------------------------------------------


def test_vcards_add_uses_typed_flags():
    body = _dry_run(
        "vcards",
        "add",
        "--campaign-id",
        "555",
        "--country",
        "Россия",
        "--city",
        "Москва",
        "--company-name",
        "Acme",
        "--work-time",
        "1#5#9#0#18#0",
        "--phone-country-code",
        "+7",
        "--phone-city-code",
        "495",
        "--phone-number",
        "1234567",
    )
    assert body["method"] == "add"
    assert body["params"]["VCards"] == [
        {
            "CampaignId": 555,
            "Country": "Россия",
            "City": "Москва",
            "CompanyName": "Acme",
            "WorkTime": "1#5#9#0#18#0",
            "Phone": {
                "CountryCode": "+7",
                "CityCode": "495",
                "PhoneNumber": "1234567",
            },
        }
    ]


def test_vcards_add_instant_messenger_payload():
    body = _dry_run(
        "vcards",
        "add",
        "--campaign-id",
        "555",
        "--country",
        "Россия",
        "--city",
        "Москва",
        "--company-name",
        "Acme",
        "--work-time",
        "1#5#9#0#18#0",
        "--phone-country-code",
        "+7",
        "--phone-city-code",
        "495",
        "--phone-number",
        "1234567",
        "--instant-messenger-client",
        "telegram",
        "--instant-messenger-login",
        "acme_support",
    )
    vcard = body["params"]["VCards"][0]
    assert vcard["InstantMessenger"] == {
        "MessengerClient": "telegram",
        "MessengerLogin": "acme_support",
    }


def test_vcards_add_instant_messenger_partial_rejected():
    result = _rejected(
        "vcards",
        "add",
        "--campaign-id",
        "555",
        "--country",
        "Россия",
        "--city",
        "Москва",
        "--company-name",
        "Acme",
        "--work-time",
        "1#5#9#0#18#0",
        "--phone-country-code",
        "+7",
        "--phone-city-code",
        "495",
        "--phone-number",
        "1234567",
        "--instant-messenger-client",
        "telegram",
    )
    assert "--instant-messenger-client and --instant-messenger-login" in result.output
    assert result.exit_code == 2


def test_vcards_add_point_on_map_payload():
    body = _dry_run(
        "vcards",
        "add",
        "--campaign-id",
        "555",
        "--country",
        "Россия",
        "--city",
        "Москва",
        "--company-name",
        "Acme",
        "--work-time",
        "1#5#9#0#18#0",
        "--phone-country-code",
        "+7",
        "--phone-city-code",
        "495",
        "--phone-number",
        "1234567",
        "--point-on-map-x",
        "37.6173",
        "--point-on-map-y",
        "55.7558",
        "--point-on-map-x1",
        "37.60",
        "--point-on-map-y1",
        "55.74",
        "--point-on-map-x2",
        "37.63",
        "--point-on-map-y2",
        "55.77",
    )
    vcard = body["params"]["VCards"][0]
    assert vcard["PointOnMap"] == {
        "X": 37.6173,
        "Y": 55.7558,
        "X1": 37.60,
        "Y1": 55.74,
        "X2": 37.63,
        "Y2": 55.77,
    }


def test_vcards_add_point_on_map_partial_rejected():
    result = _rejected(
        "vcards",
        "add",
        "--campaign-id",
        "555",
        "--country",
        "Россия",
        "--city",
        "Москва",
        "--company-name",
        "Acme",
        "--work-time",
        "1#5#9#0#18#0",
        "--phone-country-code",
        "+7",
        "--phone-city-code",
        "495",
        "--phone-number",
        "1234567",
        "--point-on-map-x",
        "37.6173",
    )
    assert "PointOnMap requires all coordinate flags" in result.output
    assert "--point-on-map-y" in result.output
    assert result.exit_code == 2


# ----------------------------------------------------------------------
# adextensions
# ----------------------------------------------------------------------


def test_adextensions_add_does_not_send_type_field():
    body = _dry_run(
        "adextensions",
        "add",
        "--callout-text",
        "Free shipping",
    )
    assert body["method"] == "add"
    ext = body["params"]["AdExtensions"][0]
    # The API derives the extension type from the nested field name
    # (Callout).  AdExtensionAddItem only supports Callout per WSDL.
    assert "Type" not in ext
    assert ext == {"Callout": {"CalloutText": "Free shipping"}}


# ----------------------------------------------------------------------
# reports (no dry-run — test CLI-parser-level validation only)
# ----------------------------------------------------------------------


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


# ----------------------------------------------------------------------
# adimages
# ----------------------------------------------------------------------


def test_adimages_add_uses_typed_flags():
    image = {"ImageData": "BASE64DATA", "Name": "banner.png", "Type": "ICON"}
    body = _dry_run(
        "adimages",
        "add",
        "--name",
        "banner.png",
        "--image-data",
        "BASE64DATA",
        "--type",
        "ICON",
    )
    assert body["method"] == "add"
    assert body["params"]["AdImages"] == [image]


# ----------------------------------------------------------------------
# dynamicads
# ----------------------------------------------------------------------


def test_dynamicads_add_payload_uses_webpages_key():
    body = _dry_run(
        "dynamicads",
        "add",
        "--adgroup-id",
        "33",
        "--name",
        "Webpage A",
        "--condition",
        "URL:CONTAINS_ANY:foo|bar",
        "--condition",
        "PAGE_CONTENT:CONTAINS:baz",
        "--bid",
        "3000000",
        "--context-bid",
        "2000000",
        "--priority",
        "HIGH",
    )
    assert body["method"] == "add"
    webpage = body["params"]["Webpages"][0]
    assert webpage["AdGroupId"] == 33
    assert webpage["Name"] == "Webpage A"
    assert webpage["Conditions"] == [
        {"Operand": "URL", "Operator": "CONTAINS_ANY", "Arguments": ["foo", "bar"]},
        {"Operand": "PAGE_CONTENT", "Operator": "CONTAINS", "Arguments": ["baz"]},
    ]
    assert webpage["Bid"] == 3000000
    assert webpage["ContextBid"] == 2000000
    assert webpage["StrategyPriority"] == "HIGH"


def test_dynamicads_set_bids_uses_bids_array():
    body = _dry_run(
        "dynamicads",
        "set-bids",
        "--id",
        "44",
        "--bid",
        "3000000",
        "--context-bid",
        "2000000",
        "--priority",
        "LOW",
    )
    assert body["method"] == "setBids"
    item = body["params"]["Bids"][0]
    assert item == {
        "Id": 44,
        "Bid": 3000000,
        "ContextBid": 2000000,
        "StrategyPriority": "LOW",
    }


# ----------------------------------------------------------------------
# smartadtargets
# ----------------------------------------------------------------------


def test_smartadtargets_add_uses_typed_flags():
    body = _dry_run(
        "smartadtargets",
        "add",
        "--adgroup-id",
        "55",
        "--name",
        "Audience A",
        "--audience",
        "ALL_SEGMENTS",
        "--condition",
        "CATEGORY_ID:EQUALS:42",
        "--average-cpc",
        "3000000",
        "--average-cpa",
        "4000000",
        "--priority",
        "HIGH",
        "--available-items-only",
        "YES",
    )
    assert body["method"] == "add"
    target = body["params"]["SmartAdTargets"][0]
    assert target == {
        "AdGroupId": 55,
        "Name": "Audience A",
        "Audience": "ALL_SEGMENTS",
        "Conditions": {
            "Items": [
                {
                    "Operand": "CATEGORY_ID",
                    "Operator": "EQUALS",
                    "Arguments": ["42"],
                }
            ]
        },
        "AverageCpc": 3000000,
        "AverageCpa": 4000000,
        "StrategyPriority": "HIGH",
        "AvailableItemsOnly": "YES",
    }


def test_smartadtargets_update_uses_typed_flags():
    body = _dry_run(
        "smartadtargets",
        "update",
        "--id",
        "66",
        "--name",
        "Audience B",
        "--audience",
        "ALL_SEGMENTS",
        "--condition",
        "CATEGORY_ID:EQUALS:42",
        "--average-cpc",
        "3000000",
        "--average-cpa",
        "4000000",
        "--priority",
        "HIGH",
        "--available-items-only",
        "NO",
    )
    target = body["params"]["SmartAdTargets"][0]
    assert target == {
        "Id": 66,
        "Name": "Audience B",
        "Audience": "ALL_SEGMENTS",
        "Conditions": {
            "Items": [
                {
                    "Operand": "CATEGORY_ID",
                    "Operator": "EQUALS",
                    "Arguments": ["42"],
                }
            ]
        },
        "AverageCpc": 3000000,
        "AverageCpa": 4000000,
        "StrategyPriority": "HIGH",
        "AvailableItemsOnly": "NO",
    }


def test_smartadtargets_update_without_fields_errors():
    result = CliRunner().invoke(
        cli,
        [
            "smartadtargets",
            "update",
            "--id",
            "66",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    combined = (result.output or "") + (
        str(result.exception) if result.exception else ""
    )
    assert "Provide at least one field to update" in combined


# ----------------------------------------------------------------------
# negativekeywordsharedsets
# ----------------------------------------------------------------------


def test_negativekeywordsharedsets_add_splits_keywords():
    body = _dry_run(
        "negativekeywordsharedsets",
        "add",
        "--name",
        "Set A",
        "--keywords",
        "купить, продам , скачать",
    )
    assert body["method"] == "add"
    nks = body["params"]["NegativeKeywordSharedSets"][0]
    assert nks == {
        "Name": "Set A",
        "NegativeKeywords": ["купить", "продам", "скачать"],
    }


def test_negativekeywordsharedsets_update_keywords():
    body = _dry_run(
        "negativekeywordsharedsets",
        "update",
        "--id",
        "12",
        "--keywords",
        "слово,фраза",
    )
    nks = body["params"]["NegativeKeywordSharedSets"][0]
    assert nks == {"Id": 12, "NegativeKeywords": ["слово", "фраза"]}


# ----------------------------------------------------------------------
# agencyclients
# ----------------------------------------------------------------------


def test_agencyclients_add_is_runtime_deprecated_even_for_dry_run():
    result = CliRunner().invoke(
        cli,
        [
            "agencyclients",
            "add",
            "--login",
            "client-login",
            "--first-name",
            "Alice",
            "--last-name",
            "Smith",
            "--currency",
            "RUB",
            "--notification-email",
            "ops@example.com",
            "--notification-lang",
            "RU",
            "--send-account-news",
            "--no-send-warnings",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "add-passport-organization" in result.output


# ----------------------------------------------------------------------
# clients
# ----------------------------------------------------------------------


def test_clients_update_payload_matches_wsdl_contract():
    body = _dry_run(
        "clients",
        "update",
        "--client-info",
        "Important client",
        "--phone",
        "+70000000000",
        "--notification-email",
        "user@example.com",
        "--notification-lang",
        "EN",
        "--email-subscription",
        "RECEIVE_RECOMMENDATIONS=YES",
        "--setting",
        "DISPLAY_STORE_RATING=NO",
        "--tin-type",
        "LEGAL",
        "--tin",
        "1234567890",
    )
    assert body["method"] == "update"
    client = body["params"]["Clients"][0]
    assert client == {
        "ClientInfo": "Important client",
        "Phone": "+70000000000",
        "Notification": {
            "Email": "user@example.com",
            "Lang": "EN",
            "EmailSubscriptions": [
                {"Option": "RECEIVE_RECOMMENDATIONS", "Value": "YES"}
            ],
        },
        "Settings": [{"Option": "DISPLAY_STORE_RATING", "Value": "NO"}],
        "TinInfo": {"TinType": "LEGAL", "Tin": "1234567890"},
    }
    assert "ClientId" not in client
    assert "Email" not in client
    assert "Fax" not in client
    assert "City" not in client


def test_clients_update_rejects_legacy_flags():
    for flag, value in (
        ("--client-id", "999"),
        ("--email", "user@example.com"),
        ("--fax", "+70000000001"),
        ("--city", "Moscow"),
    ):
        result = CliRunner().invoke(
            cli,
            ["clients", "update", flag, value, "--phone", "+70000000000", "--dry-run"],
        )
        assert result.exit_code != 0
        assert "No such option" in result.output
        assert flag in result.output


def test_clients_update_requires_at_least_one_field():
    result = CliRunner().invoke(cli, ["clients", "update", "--dry-run"])
    assert result.exit_code != 0
    assert "Provide at least one field to update" in result.output


def test_clients_update_notification_only_payload():
    body = _dry_run(
        "clients",
        "update",
        "--notification-email",
        "user@example.com",
        "--notification-lang",
        "EN",
        "--email-subscription",
        "TRACK_POSITION_CHANGES=NO",
    )
    assert body["params"]["Clients"][0] == {
        "Notification": {
            "Email": "user@example.com",
            "Lang": "EN",
            "EmailSubscriptions": [{"Option": "TRACK_POSITION_CHANGES", "Value": "NO"}],
        }
    }


def test_clients_update_repeated_subscription_and_setting_items():
    body = _dry_run(
        "clients",
        "update",
        "--email-subscription",
        "RECEIVE_RECOMMENDATIONS=YES",
        "--email-subscription",
        "TRACK_POSITION_CHANGES=NO",
        "--setting",
        "DISPLAY_STORE_RATING=NO",
        "--setting",
        "CORRECT_TYPOS_AUTOMATICALLY=YES",
    )
    assert body["params"]["Clients"][0] == {
        "Notification": {
            "EmailSubscriptions": [
                {"Option": "RECEIVE_RECOMMENDATIONS", "Value": "YES"},
                {"Option": "TRACK_POSITION_CHANGES", "Value": "NO"},
            ],
        },
        "Settings": [
            {"Option": "DISPLAY_STORE_RATING", "Value": "NO"},
            {"Option": "CORRECT_TYPOS_AUTOMATICALLY", "Value": "YES"},
        ],
    }


def test_clients_update_erir_organization_payload():
    body = _dry_run(
        "clients",
        "update",
        "--erir-organization-name",
        "Advertiser LLC",
        "--erir-organization-kpp",
        "770101001",
        "--erir-organization-epay-number",
        "epay123",
        "--erir-organization-reg-number",
        "1027700132195",
        "--erir-organization-oksm-number",
        "643",
        "--erir-organization-okved-code",
        "62.01",
    )
    assert body["params"]["Clients"][0] == {
        "ErirAttributes": {
            "Organization": {
                "Name": "Advertiser LLC",
                "Kpp": "770101001",
                "EpayNumber": "epay123",
                "RegNumber": "1027700132195",
                "OksmNumber": "643",
                "OkvedCode": "62.01",
            }
        }
    }


def test_clients_update_erir_contract_payload():
    body = _dry_run(
        "clients",
        "update",
        "--erir-contract-number",
        "C-2026-01",
        "--erir-contract-date",
        "2026-01-15",
        "--erir-contract-type",
        "contract",
        "--erir-contract-action-type",
        "commercial",
        "--erir-contract-subject-type",
        "representation",
        "--erir-contract-is-agency-payment",
        "no",
        "--erir-contract-price-amount",
        "120000.5",
        "--erir-contract-price-including-vat",
        "yes",
    )
    assert body["params"]["Clients"][0] == {
        "ErirAttributes": {
            "Contract": {
                "Number": "C-2026-01",
                "Date": "2026-01-15",
                "Type": "CONTRACT",
                "ActionType": "COMMERCIAL",
                "SubjectType": "REPRESENTATION",
                "IsAgencyPayment": "NO",
                "Price": {"Amount": 120000.5, "IncludingVat": "YES"},
            }
        }
    }


def test_clients_update_erir_contract_partial_payload():
    body = _dry_run(
        "clients",
        "update",
        "--erir-contract-number",
        "C-2026-01",
    )
    assert body["params"]["Clients"][0] == {
        "ErirAttributes": {"Contract": {"Number": "C-2026-01"}}
    }


def test_clients_update_erir_contract_price_requires_amount_and_vat():
    for args, missing in (
        (
            [
                "clients",
                "update",
                "--erir-contract-price-amount",
                "120000.5",
                "--dry-run",
            ],
            "--erir-contract-price-including-vat",
        ),
        (
            [
                "clients",
                "update",
                "--erir-contract-price-including-vat",
                "YES",
                "--dry-run",
            ],
            "--erir-contract-price-amount",
        ),
    ):
        result = CliRunner().invoke(cli, args)
        assert result.exit_code != 0
        assert "ErirAttributes.Contract.Price requires" in result.output
        assert missing in result.output


def test_clients_update_erir_contract_price_rejects_non_finite_amount():
    for value in ("nan", "inf", "-inf"):
        result = CliRunner().invoke(
            cli,
            [
                "clients",
                "update",
                "--erir-contract-price-amount",
                value,
                "--erir-contract-price-including-vat",
                "YES",
                "--dry-run",
            ],
        )
        assert result.exit_code != 0
        assert "--erir-contract-price-amount must be a positive decimal amount" in (
            result.output
        )


def test_clients_update_erir_contragent_payload():
    body = _dry_run(
        "clients",
        "update",
        "--erir-contragent-name",
        "Counterparty LLC",
        "--erir-contragent-kpp",
        "770201001",
        "--erir-contragent-phone",
        "+70000000001",
        "--erir-contragent-epay-number",
        "epay456",
        "--erir-contragent-reg-number",
        "1027700132196",
        "--erir-contragent-oksm-number",
        "643",
        "--erir-contragent-tin-type",
        "LEGAL",
        "--erir-contragent-tin",
        "1234567890",
    )
    assert body["params"]["Clients"][0] == {
        "ErirAttributes": {
            "Contragent": {
                "Name": "Counterparty LLC",
                "Kpp": "770201001",
                "Phone": "+70000000001",
                "EpayNumber": "epay456",
                "RegNumber": "1027700132196",
                "OksmNumber": "643",
                "TinInfo": {"TinType": "LEGAL", "Tin": "1234567890"},
            }
        }
    }


def test_clients_update_erir_contragent_tin_info_partial_payload():
    body = _dry_run(
        "clients",
        "update",
        "--erir-contragent-tin-type",
        "LEGAL",
    )
    assert body["params"]["Clients"][0] == {
        "ErirAttributes": {"Contragent": {"TinInfo": {"TinType": "LEGAL"}}}
    }


def test_clients_update_erir_contragent_rejects_invalid_tin_type():
    result = CliRunner().invoke(
        cli,
        [
            "clients",
            "update",
            "--erir-contragent-tin-type",
            "UNKNOWN",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "Invalid tin type" in result.output
    assert "--erir-contragent-tin-type" in result.output


def test_clients_update_rejects_invalid_subscription_or_setting():
    invalid_cases = [
        [
            "clients",
            "update",
            "--email-subscription",
            "UNKNOWN=YES",
            "--dry-run",
        ],
        [
            "clients",
            "update",
            "--setting",
            "DISPLAY_STORE_RATING=yes",
            "--dry-run",
        ],
    ]
    for args in invalid_cases:
        result = CliRunner().invoke(cli, args)
        assert result.exit_code != 0
        assert "Error:" in result.output


class TestAdvideosDryRun:
    def test_add_by_url(self):
        body = _dry_run(
            "advideos",
            "add",
            "--url",
            "https://example.com/video.mp4",
            "--name",
            "Test Video",
        )
        assert body["method"] == "add"
        item = body["params"]["AdVideos"][0]
        assert item["Url"] == "https://example.com/video.mp4"
        assert item["Name"] == "Test Video"
        assert "Type" not in item

    def test_add_requires_url_or_data(self):
        from click.testing import CliRunner
        from direct_cli.cli import cli

        result = CliRunner().invoke(cli, ["advideos", "add", "--dry-run"])
        assert result.exit_code != 0


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


# ----------------------------------------------------------------------
# wsdl coverage gap closures
# ----------------------------------------------------------------------


def test_agencyclients_add_runtime_deprecated_without_dry_run():
    result = CliRunner().invoke(
        cli,
        [
            "agencyclients",
            "add",
            "--login",
            "client-login",
            "--first-name",
            "Alice",
            "--last-name",
            "Smith",
            "--currency",
            "RUB",
        ],
    )
    assert result.exit_code != 0
    assert "add-passport-organization" in result.output


def test_agencyclients_add_passport_organization_payload():
    body = _dry_run(
        "agencyclients",
        "add-passport-organization",
        "--name",
        "Org",
        "--currency",
        "RUB",
        "--notification-email",
        "ops@example.com",
        "--notification-lang",
        "EN",
        "--no-send-account-news",
        "--send-warnings",
    )
    assert body["method"] == "addPassportOrganization"
    assert body["params"] == {
        "Name": "Org",
        "Currency": "RUB",
        "Notification": {
            "Email": "ops@example.com",
            "Lang": "EN",
            "EmailSubscriptions": [
                {"Option": "RECEIVE_RECOMMENDATIONS", "Value": "NO"},
                {"Option": "TRACK_POSITION_CHANGES", "Value": "YES"},
            ],
        },
    }


def test_agencyclients_add_passport_organization_member_payload():
    body = _dry_run(
        "agencyclients",
        "add-passport-organization-member",
        "--passport-organization-login",
        "org-login",
        "--role",
        "CHIEF",
        "--invite-email",
        "user@example.com",
    )
    assert body["method"] == "addPassportOrganizationMember"
    assert body["params"] == {
        "PassportOrganizationLogin": "org-login",
        "Role": "CHIEF",
        "SendInviteTo": {"Email": "user@example.com"},
    }


def test_agencyclients_update_payload_matches_wsdl_contract():
    body = _dry_run(
        "agencyclients",
        "update",
        "--client-id",
        "42",
        "--client-info",
        "Agency client",
        "--phone",
        "+70000000000",
        "--notification-email",
        "user@example.com",
        "--notification-lang",
        "EN",
        "--email-subscription",
        "TRACK_MANAGED_CAMPAIGNS=YES",
        "--setting",
        "CORRECT_TYPOS_AUTOMATICALLY=NO",
        "--tin-type",
        "INDIVIDUAL",
        "--tin",
        "1234567890",
        "--grant",
        "EDIT_CAMPAIGNS=YES",
        "--grant",
        "IMPORT_XLS=NO",
    )
    item = body["params"]["Clients"][0]
    assert item == {
        "ClientId": 42,
        "ClientInfo": "Agency client",
        "Phone": "+70000000000",
        "Notification": {
            "Email": "user@example.com",
            "Lang": "EN",
            "EmailSubscriptions": [
                {"Option": "TRACK_MANAGED_CAMPAIGNS", "Value": "YES"}
            ],
        },
        "Settings": [{"Option": "CORRECT_TYPOS_AUTOMATICALLY", "Value": "NO"}],
        "TinInfo": {"TinType": "INDIVIDUAL", "Tin": "1234567890"},
        "Grants": [
            {"Privilege": "EDIT_CAMPAIGNS", "Value": "YES"},
            {"Privilege": "IMPORT_XLS", "Value": "NO"},
        ],
    }
    assert "Email" not in item


def test_agencyclients_update_rejects_bare_grant():
    result = CliRunner().invoke(
        cli,
        [
            "agencyclients",
            "update",
            "--client-id",
            "1",
            "--grant",
            "EDIT_CAMPAIGNS",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "Expected format: OPTION=YES|NO" in result.output


def test_agencyclients_update_rejects_legacy_email_flag():
    result = CliRunner().invoke(
        cli,
        [
            "agencyclients",
            "update",
            "--client-id",
            "1",
            "--email",
            "user@example.com",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "No such option" in result.output
    assert "--email" in result.output


def test_agencyclients_update_clear_grants_emits_empty_list():
    body = _dry_run(
        "agencyclients",
        "update",
        "--client-id",
        "42",
        "--clear-grants",
    )
    assert body["params"]["Clients"][0] == {"ClientId": 42, "Grants": []}


def test_agencyclients_update_requires_at_least_one_update_field():
    result = CliRunner().invoke(
        cli,
        ["agencyclients", "update", "--client-id", "1", "--dry-run"],
    )
    assert result.exit_code != 0
    assert "Provide at least one field to update" in result.output


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


def test_creatives_add_payload_uses_creatives_array():
    body = _dry_run(
        "creatives",
        "add",
        "--video-id",
        "video-id",
    )
    assert body["method"] == "add"
    assert body["params"]["Creatives"] == [
        {"VideoExtensionCreative": {"VideoId": "video-id"}}
    ]


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


def test_retargeting_update_payload_uses_lists_array():
    body = _dry_run(
        "retargeting",
        "update",
        "--id",
        "55",
        "--name",
        "Renamed",
        "--rule",
        "ANY:12345:30",
    )
    assert body["method"] == "update"
    assert body["params"]["RetargetingLists"][0] == {
        "Id": 55,
        "Name": "Renamed",
        "Rules": [
            {
                "Operator": "ANY",
                "Arguments": [{"ExternalId": 12345, "MembershipLifeSpan": 30}],
            }
        ],
    }


def test_retargeting_update_description_payload():
    body = _dry_run(
        "retargeting",
        "update",
        "--id",
        "55",
        "--description",
        "Updated note",
    )
    assert body["params"]["RetargetingLists"][0] == {
        "Id": 55,
        "Description": "Updated note",
    }


def test_retargeting_update_empty_description_payload():
    body = _dry_run("retargeting", "update", "--id", "55", "--description", "")
    assert body["params"]["RetargetingLists"][0] == {"Id": 55, "Description": ""}


def test_retargeting_update_description_rejects_4097_chars():
    result = _rejected(
        "retargeting",
        "update",
        "--id",
        "55",
        "--description",
        "x" * 4097,
    )
    assert "--description must be at most 4096 characters" in result.output


def test_smartadtargets_set_bids_payload_uses_average_cpc():
    body = _dry_run(
        "smartadtargets",
        "set-bids",
        "--id",
        "11",
        "--average-cpc",
        "1500000",
        "--average-cpa",
        "2500000",
        "--priority",
        "LOW",
    )
    assert body["method"] == "setBids"
    assert body["params"]["Bids"][0] == {
        "Id": 11,
        "AverageCpc": 1500000,
        "AverageCpa": 2500000,
        "StrategyPriority": "LOW",
    }


def test_campaigns_delete_dry_run_payload():
    body = _dry_run("campaigns", "delete", "--id", "42")
    assert body == {
        "method": "delete",
        "params": {"SelectionCriteria": {"Ids": [42]}},
    }


def test_ads_moderate_dry_run_payload():
    body = _dry_run("ads", "moderate", "--id", "99")
    assert body == {
        "method": "moderate",
        "params": {"SelectionCriteria": {"Ids": [99]}},
    }


def test_keywords_suspend_dry_run_payload():
    body = _dry_run("keywords", "suspend", "--id", "77")
    assert body == {
        "method": "suspend",
        "params": {"SelectionCriteria": {"Ids": [77]}},
    }


def test_adgroups_delete_dry_run_payload():
    body = _dry_run("adgroups", "delete", "--id", "55")
    assert body == {
        "method": "delete",
        "params": {"SelectionCriteria": {"Ids": [55]}},
    }


def test_adimages_delete_dry_run_payload():
    body = _dry_run("adimages", "delete", "--hash", "image-hash")
    assert body == {
        "method": "delete",
        "params": {"SelectionCriteria": {"AdImageHashes": ["image-hash"]}},
    }


def test_smartadtargets_delete_dry_run_payload():
    body = _dry_run("smartadtargets", "delete", "--id", "88")
    assert body == {
        "method": "delete",
        "params": {"SelectionCriteria": {"Ids": [88]}},
    }


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


# ----------------------------------------------------------------------
# dynamicfeedadtargets
# ----------------------------------------------------------------------


def test_dynamicfeedadtargets_add_payload():
    body = _dry_run(
        "dynamicfeedadtargets",
        "add",
        "--adgroup-id",
        "123",
        "--name",
        "Test Target",
        "--condition",
        "CATEGORY:EQUALS_ANY:shoes|boots",
        "--bid",
        "1500000",
    )
    assert body["method"] == "add"
    target = body["params"]["DynamicFeedAdTargets"][0]
    assert target["AdGroupId"] == 123
    assert target["Name"] == "Test Target"
    assert target["Conditions"] == {
        "Items": [
            {
                "Operand": "CATEGORY",
                "Operator": "EQUALS_ANY",
                "Arguments": ["shoes", "boots"],
            }
        ]
    }
    assert target["Bid"] == 1500000


def test_dynamicfeedadtargets_delete_payload():
    body = _dry_run("dynamicfeedadtargets", "delete", "--id", "42")
    assert body == {
        "method": "delete",
        "params": {"SelectionCriteria": {"Ids": [42]}},
    }


def test_dynamicfeedadtargets_suspend_payload():
    body = _dry_run("dynamicfeedadtargets", "suspend", "--id", "42")
    assert body == {
        "method": "suspend",
        "params": {"SelectionCriteria": {"Ids": [42]}},
    }


def test_dynamicfeedadtargets_resume_payload():
    body = _dry_run("dynamicfeedadtargets", "resume", "--id", "42")
    assert body == {
        "method": "resume",
        "params": {"SelectionCriteria": {"Ids": [42]}},
    }


def test_dynamicfeedadtargets_set_bids_payload():
    body = _dry_run(
        "dynamicfeedadtargets",
        "set-bids",
        "--id",
        "55",
        "--bid",
        "2000000",
    )
    assert body["method"] == "setBids"
    bid = body["params"]["Bids"][0]
    assert bid["Id"] == 55
    assert bid["Bid"] == 2000000


# ----------------------------------------------------------------------
# strategies
# ----------------------------------------------------------------------


def test_strategies_add_payload():
    body = _dry_run(
        "strategies",
        "add",
        "--name",
        "My Strategy",
        "--type",
        "AverageCpc",
        "--average-cpc",
        "1000000",
        "--priority-goal",
        "123:2000000",
    )
    assert body["method"] == "add"
    s = body["params"]["Strategies"][0]
    assert s["Name"] == "My Strategy"
    assert s["AverageCpc"]["AverageCpc"] == 1000000
    assert s["PriorityGoals"]["Items"] == [{"GoalId": 123, "Value": 2000000}]


def test_strategies_add_no_type_key_at_root():
    body = _dry_run(
        "strategies",
        "add",
        "--name",
        "My Strategy",
        "--type",
        "WbMaximumClicks",
    )
    s = body["params"]["Strategies"][0]
    assert "Type" not in s
    assert "WbMaximumClicks" in s


def test_strategies_update_payload():
    body = _dry_run(
        "strategies",
        "update",
        "--id",
        "77",
        "--name",
        "Updated",
        "--type",
        "AverageCpc",
        "--average-cpc",
        "1500000",
    )
    assert body["method"] == "update"
    s = body["params"]["Strategies"][0]
    assert s["Id"] == 77
    assert s["Name"] == "Updated"
    assert s["AverageCpc"]["AverageCpc"] == 1500000


def test_strategies_update_requires_type_for_strategy_specific_fields():
    result = _failing_run(
        "strategies",
        "update",
        "--id",
        "77",
        "--average-cpc",
        "1500000",
        "--dry-run",
    )
    assert result.exit_code != 0
    assert "Provide --type when setting strategy-specific fields" in result.output


def test_strategies_update_average_cpc_per_filter_maps_to_filter_average_cpc():
    body = _dry_run(
        "strategies",
        "update",
        "--id",
        "42",
        "--type",
        "AverageCpcPerFilter",
        "--average-cpc",
        "30000000",
    )
    s = body["params"]["Strategies"][0]
    assert s["AverageCpcPerFilter"] == {"FilterAverageCpc": 30000000}


def test_strategies_update_pay_for_conversion_maps_average_cpa_to_cpa():
    body = _dry_run(
        "strategies",
        "update",
        "--id",
        "42",
        "--type",
        "PayForConversion",
        "--average-cpa",
        "4000000",
        "--goal-id",
        "123",
    )
    s = body["params"]["Strategies"][0]
    assert s["PayForConversion"] == {"Cpa": 4000000, "GoalId": 123}


def test_strategies_update_average_cpa_without_goal_id_is_allowed():
    body = _dry_run(
        "strategies",
        "update",
        "--id",
        "42",
        "--type",
        "AverageCpa",
        "--average-cpa",
        "4000000",
    )
    s = body["params"]["Strategies"][0]
    assert s["AverageCpa"] == {"AverageCpa": 4000000}
    assert "GoalId" not in s["AverageCpa"]


def test_strategies_archive_payload():
    body = _dry_run("strategies", "archive", "--id", "10")
    assert body == {
        "method": "archive",
        "params": {"SelectionCriteria": {"Ids": [10]}},
    }


def test_strategies_unarchive_payload():
    body = _dry_run("strategies", "unarchive", "--id", "10")
    assert body == {
        "method": "unarchive",
        "params": {"SelectionCriteria": {"Ids": [10]}},
    }


# ----------------------------------------------------------------------
# MICRO_RUBLES validation
# ----------------------------------------------------------------------


def _failing_run(*args: str) -> Result:
    """Invoke a CLI command expected to fail, returning the result."""
    return CliRunner().invoke(cli, list(args))


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
