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


def test_ads_add_text_ad_optional_extension_fields_payload():
    """Issue #273: TEXT_AD add optional extension fields are top-level TextAd."""
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
        "--final-url",
        "https://final.example.com",
        "--video-extension-creative-id",
        "0",
        "--price-extension-price",
        "123.45",
        "--price-extension-old-price",
        "234.56",
        "--price-extension-price-qualifier",
        "from",
        "--price-extension-price-currency",
        "rub",
        "--business-id",
        "0",
        "--prefer-vcard-over-business",
        "yes",
        "--erir-ad-description",
        "Text ad object",
    )
    text_ad = body["params"]["Ads"][0]["TextAd"]
    assert text_ad["FinalUrl"] == "https://final.example.com"
    assert text_ad["VideoExtension"] == {"CreativeId": 0}
    assert text_ad["PriceExtension"] == {
        "Price": 123450000,
        "OldPrice": 234560000,
        "PriceQualifier": "FROM",
        "PriceCurrency": "RUB",
    }
    assert text_ad["BusinessId"] == 0
    assert text_ad["PreferVCardOverBusiness"] == "YES"
    assert text_ad["ErirAdDescription"] == "Text ad object"


def test_ads_add_text_ad_price_extension_requires_mandatory_fields():
    """Issue #273: PriceExtensionAddItem has required nested fields."""
    result = _rejected(
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
        "--price-extension-old-price",
        "234.56",
    )
    assert "TextAd.PriceExtension add requires" in result.output
    assert "--price-extension-price" in result.output
    assert "--price-extension-price-qualifier" in result.output
    assert "--price-extension-price-currency" in result.output


def test_ads_add_text_ad_optional_extension_flags_reject_other_subtypes():
    """Issue #273: TEXT_AD add flags must not silently drop on other subtypes."""
    text_image = _rejected(
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
        "--prefer-vcard-over-business",
        "YES",
    )
    mobile_app = _rejected(
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
        "--price-extension-price",
        "123.45",
    )
    assert (
        "--prefer-vcard-over-business is not compatible with --type TEXT_IMAGE_AD"
        in text_image.output
    )
    assert "--price-extension-price is not compatible with --type MOBILE_APP_AD" in (
        mobile_app.output
    )


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


def test_ads_add_text_image_ad_cleanup_fields_payload():
    """Issue #278: TEXT_IMAGE_AD add supports residual optional fields."""
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "55",
        "--type",
        "TEXT_IMAGE_AD",
        "--image-hash",
        "abcdefghij",
        "--turbo-page-id",
        "0",
        "--final-url",
        "https://final.example.com",
        "--erir-ad-description",
        "Image ad object",
    )
    assert body["params"]["Ads"][0]["TextImageAd"] == {
        "AdImageHash": "abcdefghij",
        "ErirAdDescription": "Image ad object",
        "FinalUrl": "https://final.example.com",
        "TurboPageId": 0,
    }


def test_ads_add_text_image_ad_requires_image_hash():
    """Issue #278: TextImageAdAdd.AdImageHash is required by the WSDL."""
    result = _rejected(
        "ads",
        "add",
        "--adgroup-id",
        "55",
        "--type",
        "TEXT_IMAGE_AD",
        "--href",
        "https://example.com",
    )
    assert "TEXT_IMAGE_AD requires --image-hash" in result.output


def test_ads_add_text_image_ad_requires_href_or_turbo_page_id():
    """Issue #278: TextImageAd add needs a destination flag."""
    result = _rejected(
        "ads",
        "add",
        "--adgroup-id",
        "55",
        "--type",
        "TEXT_IMAGE_AD",
        "--image-hash",
        "abcdefghij",
    )
    assert "TEXT_IMAGE_AD requires either --href or --turbo-page-id." in result.output


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


def test_ads_add_dynamic_text_ad_payload():
    """Issue #277: DYNAMIC_TEXT_AD add builds DynamicTextAdAdd fields."""
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "DYNAMIC_TEXT_AD",
        "--text",
        "Dynamic ad text",
        "--image-hash",
        "abcdefghij",
        "--vcard-id",
        "0",
        "--sitelink-set-id",
        "0",
        "--ad-extensions",
        "333,444",
    )
    assert body["params"]["Ads"][0] == {
        "AdGroupId": 12345,
        "DynamicTextAd": {
            "Text": "Dynamic ad text",
            "AdImageHash": "abcdefghij",
            "VCardId": 0,
            "SitelinkSetId": 0,
            "AdExtensionIds": [333, 444],
        },
    }


def test_ads_add_dynamic_text_ad_requires_text():
    """Issue #277: DynamicTextAdAdd.Text is required by the WSDL."""
    result = _rejected(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "DYNAMIC_TEXT_AD",
    )
    assert "DYNAMIC_TEXT_AD requires --text" in result.output


def test_ads_add_dynamic_text_ad_rejects_other_subtype_flags():
    """Issue #277: DYNAMIC_TEXT_AD add must not silently drop other flags."""
    result = _rejected(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "DYNAMIC_TEXT_AD",
        "--text",
        "Dynamic ad text",
        "--href",
        "https://example.com",
    )
    assert "--href is not compatible with --type DYNAMIC_TEXT_AD" in result.output


def test_ads_add_mobile_app_ad_optional_fields_payload():
    """Issue #277: MOBILE_APP_AD add supports compact optional app fields."""
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "MOBILE_APP_AD",
        "--title",
        "Install app",
        "--text",
        "App promo text",
        "--action",
        "download",
        "--image-hash",
        "abcdefghij",
        "--tracking-url",
        "https://track.example.com",
        "--age-label",
        "age_18",
        "--mobile-app-feature",
        "PRICE=YES",
        "--mobile-app-feature",
        "CUSTOMER_RATING=NO",
        "--video-extension-creative-id",
        "0",
        "--erir-ad-description",
        "Mobile app object",
    )
    assert body["params"]["Ads"][0] == {
        "AdGroupId": 12345,
        "MobileAppAd": {
            "Title": "Install app",
            "Text": "App promo text",
            "Action": "DOWNLOAD",
            "AdImageHash": "abcdefghij",
            "TrackingUrl": "https://track.example.com",
            "AgeLabel": "AGE_18",
            "Features": [
                {"Feature": "PRICE", "Enabled": "YES"},
                {"Feature": "CUSTOMER_RATING", "Enabled": "NO"},
            ],
            "VideoExtension": {"CreativeId": 0},
            "ErirAdDescription": "Mobile app object",
        },
    }


def test_ads_add_mobile_app_ad_feature_validation():
    """Issue #277: MobileAppAd.Features keeps the typed FEATURE=YES|NO grammar."""
    result = _rejected(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "MOBILE_APP_AD",
        "--title",
        "Install app",
        "--text",
        "App promo text",
        "--action",
        "INSTALL",
        "--mobile-app-feature",
        "PRICE=MAYBE",
    )
    assert "Invalid --mobile-app-feature value" in result.output


def test_ads_add_mobile_app_image_ad_payload():
    """Issue #277: MOBILE_APP_IMAGE_AD add builds MobileAppImageAdAdd."""
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "MOBILE_APP_IMAGE_AD",
        "--image-hash",
        "abcdefghij",
        "--tracking-url",
        "https://track.example.com",
        "--erir-ad-description",
        "Mobile image object",
    )
    assert body["params"]["Ads"][0] == {
        "AdGroupId": 12345,
        "MobileAppImageAd": {
            "AdImageHash": "abcdefghij",
            "TrackingUrl": "https://track.example.com",
            "ErirAdDescription": "Mobile image object",
        },
    }


def test_ads_add_mobile_app_image_ad_requires_image_hash():
    """Issue #277: MobileAppImageAdAdd.AdImageHash is required by the WSDL."""
    result = _rejected(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "MOBILE_APP_IMAGE_AD",
    )
    assert "MOBILE_APP_IMAGE_AD requires --image-hash" in result.output


def test_ads_add_mobile_app_image_ad_rejects_other_subtype_flags():
    """Issue #277: MOBILE_APP_IMAGE_AD add must reject unrelated typed flags."""
    result = _rejected(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "MOBILE_APP_IMAGE_AD",
        "--image-hash",
        "abcdefghij",
        "--title",
        "Install app",
    )
    assert "--title is not compatible with --type MOBILE_APP_IMAGE_AD" in result.output


def test_ads_add_responsive_ad_payload():
    """Issue #274: RESPONSIVE_AD add builds the documented ResponsiveAd block."""
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "RESPONSIVE_AD",
        "--texts",
        "Text one,Text two",
        "--titles",
        "Title one,Title two",
        "--image-hashes",
        "hash-one,hash-two",
        "--video-extension-ids",
        "101,102",
        "--sitelink-set-id",
        "0",
        "--ad-extensions",
        "333,444",
        "--href",
        "https://example.com",
        "--age-label",
        "age_18",
        "--display-url-path",
        "deals",
        "--price-extension-price",
        "123.45",
        "--price-extension-old-price",
        "150.00",
        "--price-extension-price-qualifier",
        "from",
        "--price-extension-price-currency",
        "rub",
        "--business-id",
        "0",
        "--erir-ad-description",
        "Promoted object",
    )
    ad = body["params"]["Ads"][0]
    assert "Type" not in ad
    assert ad == {
        "AdGroupId": 12345,
        "ResponsiveAd": {
            "Texts": ["Text one", "Text two"],
            "Titles": ["Title one", "Title two"],
            "AdImageHashes": ["hash-one", "hash-two"],
            "VideoExtensionIds": [101, 102],
            "SitelinkSetId": 0,
            "AdExtensionIds": [333, 444],
            "Href": "https://example.com",
            "AgeLabel": "AGE_18",
            "DisplayUrlPath": "deals",
            "PriceExtension": {
                "Price": 123450000,
                "OldPrice": 150000000,
                "PriceQualifier": "FROM",
                "PriceCurrency": "RUB",
            },
            "BusinessId": 0,
            "ErirAdDescription": "Promoted object",
        },
    }


def test_ads_add_responsive_ad_requires_texts_and_titles():
    """Issue #274: ResponsiveAdAdd requires Texts and Titles."""
    result = _rejected(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "RESPONSIVE_AD",
        "--texts",
        "Text one",
    )
    assert "RESPONSIVE_AD requires --titles" in result.output


def test_ads_add_responsive_ad_empty_texts_rejected():
    """Issue #274: explicit empty list flags are rejected locally."""
    result = _rejected(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "RESPONSIVE_AD",
        "--texts",
        "",
        "--titles",
        "Title one",
        "--href",
        "https://example.com",
    )
    assert "--texts must contain at least one value." in result.output


def test_ads_add_responsive_ad_requires_href_or_business_id():
    """Issue #274: ResponsiveAdAdd requires Href, BusinessId, or both."""
    result = _rejected(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "RESPONSIVE_AD",
        "--texts",
        "Text one",
        "--titles",
        "Title one",
    )
    assert "RESPONSIVE_AD requires either --href or --business-id." in result.output


def test_ads_add_responsive_ad_accepts_business_id_without_href():
    """Issue #274: BusinessId alone satisfies the ResponsiveAd destination rule."""
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "RESPONSIVE_AD",
        "--texts",
        "Text one",
        "--titles",
        "Title one",
        "--business-id",
        "777",
    )
    assert body["params"]["Ads"][0]["ResponsiveAd"] == {
        "Texts": ["Text one"],
        "Titles": ["Title one"],
        "BusinessId": 777,
    }


def test_ads_add_responsive_ad_price_extension_requires_mandatory_fields():
    """Issue #274: ResponsiveAd.PriceExtension add has required children."""
    result = _rejected(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "RESPONSIVE_AD",
        "--texts",
        "Text one",
        "--titles",
        "Title one",
        "--href",
        "https://example.com",
        "--price-extension-old-price",
        "150.00",
    )
    assert "ResponsiveAd.PriceExtension add requires" in result.output
    assert "--price-extension-price" in result.output
    assert "--price-extension-price-qualifier" in result.output
    assert "--price-extension-price-currency" in result.output


def test_ads_add_responsive_ad_rejects_other_subtype_flags():
    """Issue #274: RESPONSIVE_AD add flags must honor subtype allow-lists."""
    result = _rejected(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "RESPONSIVE_AD",
        "--texts",
        "Text one",
        "--titles",
        "Title one",
        "--href",
        "https://example.com",
        "--video-extension-creative-id",
        "777",
    )
    assert (
        "--video-extension-creative-id is not compatible with --type RESPONSIVE_AD"
        in result.output
    )


def test_ads_add_shopping_ad_payload():
    """Issue #275: SHOPPING_AD add builds the documented ShoppingAd block."""
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "SHOPPING_AD",
        "--feed-id",
        "170",
        "--default-texts",
        "Default product text",
        "--sitelink-set-id",
        "0",
        "--ad-extensions",
        "333,444",
        "--business-id",
        "0",
        "--feed-filter-condition",
        "CATEGORY:EQUALS_ANY:shoes|boots",
        "--feed-filter-condition",
        "PRICE:GREATER_THAN:100",
        "--title-sources",
        "NAME,BRAND",
        "--text-sources",
        "DESCRIPTION",
    )
    ad = body["params"]["Ads"][0]
    assert "Type" not in ad
    assert ad == {
        "AdGroupId": 12345,
        "ShoppingAd": {
            "FeedId": 170,
            "DefaultTexts": ["Default product text"],
            "SitelinkSetId": 0,
            "AdExtensionIds": [333, 444],
            "BusinessId": 0,
            "FeedFilterConditions": [
                {
                    "Operand": "CATEGORY",
                    "Operator": "EQUALS_ANY",
                    "Arguments": ["shoes", "boots"],
                },
                {
                    "Operand": "PRICE",
                    "Operator": "GREATER_THAN",
                    "Arguments": ["100"],
                },
            ],
            "TitleSources": ["NAME", "BRAND"],
            "TextSources": ["DESCRIPTION"],
        },
    }


def test_ads_add_listing_ad_payload():
    """Issue #275: LISTING_AD add builds the documented ListingAd block."""
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "LISTING_AD",
        "--feed-id",
        "171",
        "--default-texts",
        "Default listing text",
        "--feed-filter-condition",
        "CATEGORY:EQUALS_ANY:appliances",
        "--title-sources",
        "TITLE",
        "--text-sources",
        "DESCRIPTION",
    )
    assert body["params"]["Ads"][0] == {
        "AdGroupId": 12345,
        "ListingAd": {
            "FeedId": 171,
            "DefaultTexts": ["Default listing text"],
            "FeedFilterConditions": [
                {
                    "Operand": "CATEGORY",
                    "Operator": "EQUALS_ANY",
                    "Arguments": ["appliances"],
                }
            ],
            "TitleSources": ["TITLE"],
            "TextSources": ["DESCRIPTION"],
        },
    }


def test_ads_add_shopping_ad_requires_feed_id_and_default_texts():
    """Issue #275: documented ShoppingAdAdd required fields are local errors."""
    result = _rejected(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "SHOPPING_AD",
    )
    assert "ShoppingAd requires --feed-id, --default-texts" in result.output


def test_ads_add_listing_ad_default_texts_preserves_commas():
    """Issue #275: DefaultTexts is one raw text value, not a CSV list."""
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "LISTING_AD",
        "--feed-id",
        "171",
        "--default-texts",
        "Sale, today",
    )
    assert body["params"]["Ads"][0]["ListingAd"]["DefaultTexts"] == ["Sale, today"]


def test_ads_add_listing_ad_empty_default_texts_rejected():
    """Issue #275: required DefaultTexts must be a meaningful text value."""
    result = _rejected(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "LISTING_AD",
        "--feed-id",
        "171",
        "--default-texts",
        "",
    )
    assert "--default-texts must contain a value." in result.output


def test_ads_add_shopping_ad_rejects_invalid_feed_filter_condition():
    """Issue #275: feed filter conditions keep the typed grammar."""
    result = _rejected(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "SHOPPING_AD",
        "--feed-id",
        "170",
        "--default-texts",
        "Default product text",
        "--feed-filter-condition",
        "CATEGORY",
    )
    assert "--feed-filter-condition: Invalid condition" in result.output
    assert "Expected format: OPERAND:OPERATOR:ARG1|ARG2" in result.output


def test_ads_add_listing_ad_rejects_other_subtype_flags():
    """Issue #275: LISTING_AD add flags must honor subtype allow-lists."""
    result = _rejected(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "LISTING_AD",
        "--feed-id",
        "171",
        "--default-texts",
        "Default listing text",
        "--href",
        "https://example.com",
    )
    assert "--href is not compatible with --type LISTING_AD" in result.output


def test_ads_add_text_ad_builder_ad_payload():
    """Issue #276: TEXT_AD_BUILDER_AD add builds TextAdBuilderAd block."""
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "TEXT_AD_BUILDER_AD",
        "--creative-id",
        "111",
        "--erir-ad-description",
        "Ad object",
        "--final-url",
        "https://final.example.com",
        "--href",
        "https://example.com",
        "--turbo-page-id",
        "222",
    )
    ad = body["params"]["Ads"][0]
    assert "Type" not in ad
    assert ad == {
        "AdGroupId": 12345,
        "TextAdBuilderAd": {
            "Creative": {"CreativeId": 111},
            "ErirAdDescription": "Ad object",
            "FinalUrl": "https://final.example.com",
            "Href": "https://example.com",
            "TurboPageId": 222,
        },
    }


def test_ads_add_mobile_app_ad_builder_ad_payload():
    """Issue #276: MOBILE_APP_AD_BUILDER_AD add supports TrackingUrl."""
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "MOBILE_APP_AD_BUILDER_AD",
        "--creative-id",
        "111",
        "--tracking-url",
        "https://track.example.com",
        "--erir-ad-description",
        "Mobile builder",
    )
    assert body["params"]["Ads"][0] == {
        "AdGroupId": 12345,
        "MobileAppAdBuilderAd": {
            "Creative": {"CreativeId": 111},
            "ErirAdDescription": "Mobile builder",
            "TrackingUrl": "https://track.example.com",
        },
    }


def test_ads_add_mobile_app_cpc_video_ad_builder_ad_payload():
    """Issue #276: MOBILE_APP_CPC_VIDEO_AD_BUILDER_AD uses its own block."""
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "MOBILE_APP_CPC_VIDEO_AD_BUILDER_AD",
        "--creative-id",
        "111",
        "--tracking-url",
        "https://track.example.com",
    )
    assert body["params"]["Ads"][0] == {
        "AdGroupId": 12345,
        "MobileAppCpcVideoAdBuilderAd": {
            "Creative": {"CreativeId": 111},
            "TrackingUrl": "https://track.example.com",
        },
    }


def test_ads_add_cpc_video_ad_builder_ad_payload():
    """Issue #276: CPC_VIDEO_AD_BUILDER_AD supports href and TurboPageId."""
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "CPC_VIDEO_AD_BUILDER_AD",
        "--creative-id",
        "111",
        "--href",
        "https://example.com",
        "--turbo-page-id",
        "222",
    )
    assert body["params"]["Ads"][0] == {
        "AdGroupId": 12345,
        "CpcVideoAdBuilderAd": {
            "Creative": {"CreativeId": 111},
            "Href": "https://example.com",
            "TurboPageId": 222,
        },
    }


def test_ads_add_cpm_banner_ad_builder_ad_payload():
    """Issue #276: CPM_BANNER_AD_BUILDER_AD wraps TrackingPixels.Items."""
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "CPM_BANNER_AD_BUILDER_AD",
        "--creative-id",
        "111",
        "--href",
        "https://example.com",
        "--tracking-pixels",
        "https://pixel.example.com/a,https://pixel.example.com/b",
        "--turbo-page-id",
        "222",
    )
    assert body["params"]["Ads"][0] == {
        "AdGroupId": 12345,
        "CpmBannerAdBuilderAd": {
            "Creative": {"CreativeId": 111},
            "Href": "https://example.com",
            "TrackingPixels": {
                "Items": [
                    "https://pixel.example.com/a",
                    "https://pixel.example.com/b",
                ]
            },
            "TurboPageId": 222,
        },
    }


def test_ads_add_cpm_video_ad_builder_ad_payload():
    """Issue #276: CPM_VIDEO_AD_BUILDER_AD wraps TrackingPixels.Items."""
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "CPM_VIDEO_AD_BUILDER_AD",
        "--creative-id",
        "0",
        "--tracking-pixels",
        "https://pixel.example.com/a",
        "--turbo-page-id",
        "0",
    )
    assert body["params"]["Ads"][0] == {
        "AdGroupId": 12345,
        "CpmVideoAdBuilderAd": {
            "Creative": {"CreativeId": 0},
            "TrackingPixels": {"Items": ["https://pixel.example.com/a"]},
            "TurboPageId": 0,
        },
    }


def test_ads_add_smart_ad_builder_ad_payload():
    """Issue #278: SMART_AD_BUILDER_AD add supports LogoExtensionHash."""
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "SMART_AD_BUILDER_AD",
        "--logo-extension-hash",
        "logoabcdefghijklmnop",
    )
    assert body["params"]["Ads"][0] == {
        "AdGroupId": 12345,
        "SmartAdBuilderAd": {
            "LogoExtensionHash": "logoabcdefghijklmnop",
        },
    }


def test_ads_add_smart_ad_builder_ad_rejects_erir_description():
    """Issue #278: SmartAdBuilderAdAdd exposes LogoExtensionHash only."""
    result = _rejected(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "SMART_AD_BUILDER_AD",
        "--erir-ad-description",
        "Smart builder ad",
    )
    assert (
        "--erir-ad-description is not compatible with --type SMART_AD_BUILDER_AD"
        in result.output
    )


def test_ads_add_ad_builder_requires_creative_id():
    """Issue #276: AdBuilderAddBase.Creative is required."""
    result = _rejected(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "TEXT_AD_BUILDER_AD",
        "--href",
        "https://example.com",
    )
    assert "TextAdBuilderAd requires --creative-id." in result.output


def test_ads_add_ad_builder_destination_required():
    """Issue #276: web AdBuilder subtypes require Href, TurboPageId, or both."""
    result = _rejected(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "CPM_BANNER_AD_BUILDER_AD",
        "--creative-id",
        "111",
    )
    assert (
        "CpmBannerAdBuilderAd requires either --href or --turbo-page-id."
        in result.output
    )


def test_ads_add_ad_builder_empty_tracking_pixels_rejected():
    """Issue #276: explicit empty TrackingPixels list is rejected locally."""
    result = _rejected(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "CPM_VIDEO_AD_BUILDER_AD",
        "--creative-id",
        "111",
        "--turbo-page-id",
        "222",
        "--tracking-pixels",
        "",
    )
    assert "--tracking-pixels must contain at least one value." in result.output


def test_ads_add_ad_builder_rejects_other_subtype_flags():
    """Issue #276: AdBuilder add flags must honor subtype allow-lists."""
    result = _rejected(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "MOBILE_APP_AD_BUILDER_AD",
        "--creative-id",
        "111",
        "--href",
        "https://example.com",
    )
    assert "--href is not compatible with --type MOBILE_APP_AD_BUILDER_AD" in (
        result.output
    )


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


def test_ads_update_dynamic_text_ad_payload():
    """Issue #267: DYNAMIC_TEXT_AD update builds DynamicTextAd block only."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "DYNAMIC_TEXT_AD",
        "--text",
        "Updated dynamic text",
        "--vcard-id",
        "111",
        "--image-hash",
        "ygqa6jmlkgsbz7vnewp0",
        "--sitelink-set-id",
        "222",
        "--callouts-add",
        "333",
        "--callouts-remove",
        "444",
    )
    ad = body["params"]["Ads"][0]
    assert ad == {
        "Id": 999,
        "DynamicTextAd": {
            "VCardId": 111,
            "AdImageHash": "ygqa6jmlkgsbz7vnewp0",
            "SitelinkSetId": 222,
            "CalloutSetting": {
                "AdExtensions": [
                    {"AdExtensionId": 333, "Operation": "ADD"},
                    {"AdExtensionId": 444, "Operation": "REMOVE"},
                ]
            },
            "Text": "Updated dynamic text",
        },
    }
    assert "TextAd" not in ad


def test_ads_update_dynamic_text_ad_callouts_set_payload():
    """Issue #267: DynamicTextAd.CalloutSetting supports SET operation."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "DYNAMIC_TEXT_AD",
        "--callouts-set",
        "111,222",
    )
    assert body["params"]["Ads"][0] == {
        "Id": 999,
        "DynamicTextAd": {
            "CalloutSetting": {
                "AdExtensions": [
                    {"AdExtensionId": 111, "Operation": "SET"},
                    {"AdExtensionId": 222, "Operation": "SET"},
                ]
            }
        },
    }


def test_ads_update_dynamic_text_ad_rejects_text_ad_only_flag():
    """Issue #267: --type DYNAMIC_TEXT_AD cannot silently drop TextAd fields."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "DYNAMIC_TEXT_AD",
        "--title2",
        "Text ad only",
    )
    assert "--title2 is not compatible with --type DYNAMIC_TEXT_AD" in result.output
    assert "does not convert an ad between subtypes" in result.output


def test_ads_update_dynamic_text_ad_noop_rejected():
    """Issue #267: DYNAMIC_TEXT_AD update without fields stays a no-op error."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "DYNAMIC_TEXT_AD",
    )
    assert (
        "ads update requires at least one updatable field for --type DYNAMIC_TEXT_AD"
        in result.output
    )


def test_ads_update_dynamic_text_ad_zero_ids_are_not_silently_dropped():
    """Issue #267: integer flags use presence, not truthiness, in the payload."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "DYNAMIC_TEXT_AD",
        "--vcard-id",
        "0",
        "--sitelink-set-id",
        "0",
    )
    assert body["params"]["Ads"][0] == {
        "Id": 999,
        "DynamicTextAd": {"VCardId": 0, "SitelinkSetId": 0},
    }


def test_ads_update_responsive_ad_payload():
    """Issue #268: RESPONSIVE_AD update builds the documented ResponsiveAd block."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "RESPONSIVE_AD",
        "--texts",
        "Text one,Text two",
        "--titles",
        "Title one,Title two",
        "--image-hashes",
        "hash-one,hash-two",
        "--video-extension-ids",
        "101,102",
        "--sitelink-set-id",
        "222",
        "--callouts-add",
        "333",
        "--callouts-remove",
        "444",
        "--href",
        "https://example.com",
        "--age-label",
        "age_18",
        "--display-url-path",
        "deals",
        "--price-extension-price",
        "123.45",
        "--price-extension-old-price",
        "150.00",
        "--price-extension-price-qualifier",
        "from",
        "--price-extension-price-currency",
        "rub",
        "--business-id",
        "555",
        "--erir-ad-description",
        "Promoted object",
    )
    ad = body["params"]["Ads"][0]
    assert ad == {
        "Id": 999,
        "ResponsiveAd": {
            "Texts": ["Text one", "Text two"],
            "Titles": ["Title one", "Title two"],
            "AdImageHashes": {"Items": ["hash-one", "hash-two"]},
            "VideoExtensionIds": {"Items": [101, 102]},
            "SitelinkSetId": 222,
            "CalloutSetting": {
                "AdExtensions": [
                    {"AdExtensionId": 333, "Operation": "ADD"},
                    {"AdExtensionId": 444, "Operation": "REMOVE"},
                ]
            },
            "Href": "https://example.com",
            "AgeLabel": "AGE_18",
            "DisplayUrlPath": "deals",
            "PriceExtension": {
                "Price": 123450000,
                "OldPrice": 150000000,
                "PriceQualifier": "FROM",
                "PriceCurrency": "RUB",
            },
            "BusinessId": 555,
            "ErirAdDescription": "Promoted object",
        },
    }
    assert "TextAd" not in ad


def test_ads_update_responsive_ad_rejects_text_ad_only_flag():
    """Issue #268: RESPONSIVE_AD must not silently drop TextAd-only flags."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "RESPONSIVE_AD",
        "--text",
        "Singular text belongs to other subtypes",
    )
    assert "--text is not compatible with --type RESPONSIVE_AD" in result.output
    assert "does not convert an ad between subtypes" in result.output


def test_ads_update_responsive_ad_empty_texts_rejected():
    """Issue #268: explicit empty list flags do not create no-op updates."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "RESPONSIVE_AD",
        "--texts",
        "",
    )
    assert "--texts must contain at least one value." in result.output


def test_ads_update_responsive_ad_noop_rejected():
    """Issue #268: RESPONSIVE_AD update without fields stays a no-op error."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "RESPONSIVE_AD",
    )
    assert (
        "ads update requires at least one updatable field for --type RESPONSIVE_AD"
        in result.output
    )


def test_ads_update_responsive_ad_zero_ids_are_not_silently_dropped():
    """Issue #268: nullable long flags use presence, not truthiness."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "RESPONSIVE_AD",
        "--sitelink-set-id",
        "0",
        "--business-id",
        "0",
    )
    assert body["params"]["Ads"][0] == {
        "Id": 999,
        "ResponsiveAd": {"SitelinkSetId": 0, "BusinessId": 0},
    }


def test_ads_update_shopping_ad_payload():
    """Issue #269: SHOPPING_AD update builds the documented ShoppingAd block."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "SHOPPING_AD",
        "--sitelink-set-id",
        "222",
        "--callouts-add",
        "333",
        "--business-id",
        "555",
        "--feed-filter-condition",
        "CATEGORY:EQUALS_ANY:shoes|boots",
        "--feed-filter-condition",
        "PRICE:GREATER_THAN:100",
        "--title-sources",
        "NAME,BRAND",
        "--text-sources",
        "DESCRIPTION",
        "--default-texts",
        "Default one,Default two",
    )
    ad = body["params"]["Ads"][0]
    assert ad == {
        "Id": 999,
        "ShoppingAd": {
            "SitelinkSetId": 222,
            "CalloutSetting": {
                "AdExtensions": [{"AdExtensionId": 333, "Operation": "ADD"}]
            },
            "BusinessId": 555,
            "FeedFilterConditions": {
                "Items": [
                    {
                        "Operand": "CATEGORY",
                        "Operator": "EQUALS_ANY",
                        "Arguments": ["shoes", "boots"],
                    },
                    {
                        "Operand": "PRICE",
                        "Operator": "GREATER_THAN",
                        "Arguments": ["100"],
                    },
                ]
            },
            "TitleSources": {"Items": ["NAME", "BRAND"]},
            "TextSources": {"Items": ["DESCRIPTION"]},
            "DefaultTexts": ["Default one", "Default two"],
        },
    }
    assert "ListingAd" not in ad


def test_ads_update_listing_ad_payload():
    """Issue #269: LISTING_AD update builds the documented ListingAd block."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "LISTING_AD",
        "--callouts-set",
        "333,444",
        "--feed-filter-condition",
        "CATEGORY:EQUALS_ANY:appliances",
        "--title-sources",
        "TITLE",
        "--text-sources",
        "DESCRIPTION",
        "--default-texts",
        "Fallback text",
    )
    assert body["params"]["Ads"][0] == {
        "Id": 999,
        "ListingAd": {
            "CalloutSetting": {
                "AdExtensions": [
                    {"AdExtensionId": 333, "Operation": "SET"},
                    {"AdExtensionId": 444, "Operation": "SET"},
                ]
            },
            "FeedFilterConditions": {
                "Items": [
                    {
                        "Operand": "CATEGORY",
                        "Operator": "EQUALS_ANY",
                        "Arguments": ["appliances"],
                    }
                ]
            },
            "TitleSources": {"Items": ["TITLE"]},
            "TextSources": {"Items": ["DESCRIPTION"]},
            "DefaultTexts": ["Fallback text"],
        },
    }


def test_ads_update_shopping_ad_rejects_unrelated_flag():
    """Issue #269: SHOPPING_AD must not silently drop unrelated subtype flags."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "SHOPPING_AD",
        "--href",
        "https://example.com",
    )
    assert "--href is not compatible with --type SHOPPING_AD" in result.output
    assert "does not convert an ad between subtypes" in result.output


def test_ads_update_listing_ad_noop_rejected():
    """Issue #269: LISTING_AD update without fields stays a no-op error."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "LISTING_AD",
    )
    assert (
        "ads update requires at least one updatable field for --type LISTING_AD"
        in result.output
    )


def test_ads_update_shopping_ad_empty_sources_rejected():
    """Issue #269: explicit empty source lists do not create no-op updates."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "SHOPPING_AD",
        "--title-sources",
        "",
    )
    assert "--title-sources must contain at least one value." in result.output


def test_ads_update_listing_ad_invalid_feed_filter_condition_rejected():
    """Issue #269: feed filter conditions keep the existing typed grammar."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "LISTING_AD",
        "--feed-filter-condition",
        "CATEGORY",
    )
    assert "--feed-filter-condition: Invalid condition" in result.output
    assert "Expected format: OPERAND:OPERATOR:ARG1|ARG2" in result.output


def test_ads_update_shopping_ad_zero_ids_are_not_silently_dropped():
    """Issue #269: nullable long flags use presence, not truthiness."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "SHOPPING_AD",
        "--sitelink-set-id",
        "0",
        "--business-id",
        "0",
    )
    assert body["params"]["Ads"][0] == {
        "Id": 999,
        "ShoppingAd": {"SitelinkSetId": 0, "BusinessId": 0},
    }


def test_ads_update_text_ad_builder_ad_payload():
    """Issue #270: TEXT_AD_BUILDER_AD update builds TextAdBuilderAd block."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_AD_BUILDER_AD",
        "--creative-id",
        "111",
        "--creative-erir-ad-description",
        "Creative object",
        "--erir-ad-description",
        "Ad object",
        "--final-url",
        "https://final.example.com",
        "--href",
        "https://example.com",
        "--turbo-page-id",
        "222",
    )
    ad = body["params"]["Ads"][0]
    assert ad == {
        "Id": 999,
        "TextAdBuilderAd": {
            "Creative": {
                "CreativeId": 111,
                "ErirAdDescription": "Creative object",
            },
            "ErirAdDescription": "Ad object",
            "FinalUrl": "https://final.example.com",
            "Href": "https://example.com",
            "TurboPageId": 222,
        },
    }
    assert "TextAd" not in ad


def test_ads_update_mobile_app_ad_builder_ad_payload():
    """Issue #270: MOBILE_APP_AD_BUILDER_AD update supports TrackingUrl."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "MOBILE_APP_AD_BUILDER_AD",
        "--creative-id",
        "111",
        "--tracking-url",
        "https://track.example.com",
        "--erir-ad-description",
        "Mobile builder",
    )
    assert body["params"]["Ads"][0] == {
        "Id": 999,
        "MobileAppAdBuilderAd": {
            "Creative": {"CreativeId": 111},
            "ErirAdDescription": "Mobile builder",
            "TrackingUrl": "https://track.example.com",
        },
    }


def test_ads_update_mobile_app_cpc_video_ad_builder_ad_payload():
    """Issue #270: MOBILE_APP_CPC_VIDEO_AD_BUILDER_AD uses its own block."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "MOBILE_APP_CPC_VIDEO_AD_BUILDER_AD",
        "--creative-id",
        "111",
        "--tracking-url",
        "https://track.example.com",
    )
    assert body["params"]["Ads"][0] == {
        "Id": 999,
        "MobileAppCpcVideoAdBuilderAd": {
            "Creative": {"CreativeId": 111},
            "TrackingUrl": "https://track.example.com",
        },
    }


def test_ads_update_cpc_video_ad_builder_ad_payload():
    """Issue #270: CPC_VIDEO_AD_BUILDER_AD supports href and TurboPageId."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "CPC_VIDEO_AD_BUILDER_AD",
        "--creative-id",
        "111",
        "--href",
        "https://example.com",
        "--turbo-page-id",
        "222",
    )
    assert body["params"]["Ads"][0] == {
        "Id": 999,
        "CpcVideoAdBuilderAd": {
            "Creative": {"CreativeId": 111},
            "Href": "https://example.com",
            "TurboPageId": 222,
        },
    }


def test_ads_update_cpm_banner_ad_builder_ad_payload():
    """Issue #270: CPM_BANNER_AD_BUILDER_AD wraps TrackingPixels.Items."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "CPM_BANNER_AD_BUILDER_AD",
        "--creative-id",
        "111",
        "--href",
        "https://example.com",
        "--tracking-pixels",
        "https://pixel.example.com/a,https://pixel.example.com/b",
        "--turbo-page-id",
        "222",
    )
    assert body["params"]["Ads"][0] == {
        "Id": 999,
        "CpmBannerAdBuilderAd": {
            "Creative": {"CreativeId": 111},
            "Href": "https://example.com",
            "TrackingPixels": {
                "Items": [
                    "https://pixel.example.com/a",
                    "https://pixel.example.com/b",
                ]
            },
            "TurboPageId": 222,
        },
    }


def test_ads_update_cpm_video_ad_builder_ad_payload():
    """Issue #270: CPM_VIDEO_AD_BUILDER_AD wraps TrackingPixels.Items."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "CPM_VIDEO_AD_BUILDER_AD",
        "--creative-id",
        "111",
        "--tracking-pixels",
        "https://pixel.example.com/a",
    )
    assert body["params"]["Ads"][0] == {
        "Id": 999,
        "CpmVideoAdBuilderAd": {
            "Creative": {"CreativeId": 111},
            "TrackingPixels": {"Items": ["https://pixel.example.com/a"]},
        },
    }


def test_ads_update_ad_builder_creative_erir_requires_creative_id():
    """Issue #270: nested Creative.ErirAdDescription requires CreativeId."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_AD_BUILDER_AD",
        "--creative-erir-ad-description",
        "Creative object",
    )
    assert "--creative-erir-ad-description requires --creative-id" in result.output


def test_ads_update_ad_builder_rejects_unrelated_flag():
    """Issue #270: AdBuilder subtypes must not silently drop unrelated flags."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "MOBILE_APP_AD_BUILDER_AD",
        "--href",
        "https://example.com",
    )
    assert (
        "--href is not compatible with --type MOBILE_APP_AD_BUILDER_AD" in result.output
    )
    assert "does not convert an ad between subtypes" in result.output


def test_ads_update_ad_builder_empty_tracking_pixels_rejected():
    """Issue #270: explicit empty TrackingPixels does not create a no-op."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "CPM_VIDEO_AD_BUILDER_AD",
        "--tracking-pixels",
        "",
    )
    assert "--tracking-pixels must contain at least one value." in result.output


def test_ads_update_ad_builder_noop_rejected():
    """Issue #270: AdBuilder update without fields stays a no-op error."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "CPM_BANNER_AD_BUILDER_AD",
    )
    assert (
        "ads update requires at least one updatable field for "
        "--type CPM_BANNER_AD_BUILDER_AD"
    ) in result.output


def test_ads_update_ad_builder_zero_ids_are_not_silently_dropped():
    """Issue #270: nullable long flags use presence, not truthiness."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_AD_BUILDER_AD",
        "--creative-id",
        "0",
        "--turbo-page-id",
        "0",
    )
    assert body["params"]["Ads"][0] == {
        "Id": 999,
        "TextAdBuilderAd": {
            "Creative": {"CreativeId": 0},
            "TurboPageId": 0,
        },
    }


def test_ads_update_mobile_app_image_ad_payload():
    """Issue #271: MOBILE_APP_IMAGE_AD update builds MobileAppImageAd block."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "MOBILE_APP_IMAGE_AD",
        "--image-hash",
        "abcdefghijklmnopqrst",
        "--tracking-url",
        "https://track.example.com",
        "--erir-ad-description",
        "Mobile image ad",
    )
    ad = body["params"]["Ads"][0]
    assert ad == {
        "Id": 999,
        "MobileAppImageAd": {
            "AdImageHash": "abcdefghijklmnopqrst",
            "ErirAdDescription": "Mobile image ad",
            "TrackingUrl": "https://track.example.com",
        },
    }
    assert "MobileAppAd" not in ad


def test_ads_update_smart_ad_builder_ad_payload():
    """Issue #271: SMART_AD_BUILDER_AD update supports compact fields."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "SMART_AD_BUILDER_AD",
        "--logo-extension-hash",
        "logoabcdefghijklmnop",
        "--erir-ad-description",
        "Smart builder ad",
    )
    assert body["params"]["Ads"][0] == {
        "Id": 999,
        "SmartAdBuilderAd": {
            "LogoExtensionHash": "logoabcdefghijklmnop",
            "ErirAdDescription": "Smart builder ad",
        },
    }


def test_ads_update_mobile_app_image_rejects_unrelated_flag():
    """Issue #271: MobileAppImageAd must not silently drop unrelated flags."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "MOBILE_APP_IMAGE_AD",
        "--href",
        "https://example.com",
    )
    assert "--href is not compatible with --type MOBILE_APP_IMAGE_AD" in result.output
    assert "does not convert an ad between subtypes" in result.output


def test_ads_update_smart_ad_builder_rejects_unrelated_flag():
    """Issue #271: SmartAdBuilderAd has no Creative block in ads.update."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "SMART_AD_BUILDER_AD",
        "--creative-id",
        "111",
    )
    assert (
        "--creative-id is not compatible with --type SMART_AD_BUILDER_AD"
        in result.output
    )
    assert "does not convert an ad between subtypes" in result.output


def test_ads_update_mobile_app_image_noop_rejected():
    """Issue #271: MobileAppImageAd update without fields stays a no-op error."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "MOBILE_APP_IMAGE_AD",
    )
    assert (
        "ads update requires at least one updatable field for "
        "--type MOBILE_APP_IMAGE_AD"
    ) in result.output


def test_ads_update_smart_ad_builder_noop_rejected():
    """Issue #271: SmartAdBuilderAd update without fields stays a no-op error."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "SMART_AD_BUILDER_AD",
    )
    assert (
        "ads update requires at least one updatable field for "
        "--type SMART_AD_BUILDER_AD"
    ) in result.output


def test_ads_update_text_ad_residual_optional_payload():
    """Issue #272: residual TextAdUpdate fields build top-level TextAd keys."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_AD",
        "--final-url",
        "https://final.example.com",
        "--age-label",
        "age_18",
        "--business-id",
        "0",
        "--prefer-vcard-over-business",
        "yes",
        "--erir-ad-description",
        "Text ad object",
    )
    assert body["params"]["Ads"][0] == {
        "Id": 999,
        "TextAd": {
            "FinalUrl": "https://final.example.com",
            "AgeLabel": "AGE_18",
            "BusinessId": 0,
            "PreferVCardOverBusiness": "YES",
            "ErirAdDescription": "Text ad object",
        },
    }


def test_ads_update_text_image_ad_residual_optional_payload():
    """Issue #272: TextImageAdUpdate supports FinalUrl and ErirAdDescription."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_IMAGE_AD",
        "--final-url",
        "https://final.example.com",
        "--erir-ad-description",
        "Image ad object",
        "--turbo-page-id",
        "0",
    )
    assert body["params"]["Ads"][0] == {
        "Id": 999,
        "TextImageAd": {
            "FinalUrl": "https://final.example.com",
            "ErirAdDescription": "Image ad object",
            "TurboPageId": 0,
        },
    }


def test_ads_update_mobile_app_ad_residual_optional_payload():
    """Issue #272: MobileAppAdUpdate supports Features, VideoExtension, and ERIR."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "MOBILE_APP_AD",
        "--mobile-app-feature",
        "PRICE=YES",
        "--mobile-app-feature",
        "ratings=no",
        "--video-extension-creative-id",
        "0",
        "--erir-ad-description",
        "Mobile app object",
    )
    assert body["params"]["Ads"][0] == {
        "Id": 999,
        "MobileAppAd": {
            "Features": [
                {"Feature": "PRICE", "Enabled": "YES"},
                {"Feature": "RATINGS", "Enabled": "NO"},
            ],
            "VideoExtension": {"CreativeId": 0},
            "ErirAdDescription": "Mobile app object",
        },
    }


def test_ads_update_mobile_app_feature_invalid_format_rejected():
    """Issue #272: MobileAppAd.Features uses explicit FEATURE=YES|NO grammar."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "MOBILE_APP_AD",
        "--mobile-app-feature",
        "PRICE",
    )
    assert "--mobile-app-feature expects FEATURE=YES|NO" in result.output


def test_ads_update_mobile_app_feature_invalid_value_rejected():
    """Issue #272: MobileAppAd.Features validates YesNoEnum values locally."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "MOBILE_APP_AD",
        "--mobile-app-feature",
        "PRICE=MAYBE",
    )
    assert "Invalid --mobile-app-feature value" in result.output


def test_ads_update_residual_flags_reject_unrelated_subtypes():
    """Issue #272: residual typed flags still honor per-subtype allow-lists."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_AD",
        "--mobile-app-feature",
        "PRICE=YES",
    )
    assert "--mobile-app-feature is not compatible with --type TEXT_AD" in (
        result.output
    )
    assert "does not convert an ad between subtypes" in result.output


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
        "123.45",
        "--price-extension-old-price",
        "150.00",
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


def test_ads_update_text_ad_price_extension_rejects_fractional_cents():
    """PriceExtension money input is human-readable with two decimal places."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_AD",
        "--price-extension-price",
        "123.456",
    )
    assert "--price-extension-price must have at most two decimal places" in (
        result.output
    )


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
        "123.45",
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


def test_adgroups_add_text_feed_params_payload():
    """Issue #284: text ad group feed params use a typed top-level block."""
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Text Feed Group",
        "--campaign-id",
        "111",
        "--region-ids",
        "1,225",
        "--feed-id",
        "170",
        "--feed-category-ids",
        "10,11",
    )
    group = body["params"]["AdGroups"][0]
    assert "Type" not in group
    assert group["TextAdGroupFeedParams"] == {
        "FeedId": 170,
        "FeedCategoryIds": {"Items": [10, 11]},
    }


def test_adgroups_add_text_feed_params_feed_id_only_payload():
    """Issue #284: category IDs are optional; omitted means all categories."""
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Text Feed Group",
        "--campaign-id",
        "111",
        "--region-ids",
        "225",
        "--feed-id",
        "170",
    )
    group = body["params"]["AdGroups"][0]
    assert group["TextAdGroupFeedParams"] == {"FeedId": 170}


def test_adgroups_add_text_feed_params_requires_feed_id_for_categories():
    """Issue #284: FeedId is required when TextAdGroupFeedParams is sent."""
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Text Feed Group",
        "--campaign-id",
        "111",
        "--region-ids",
        "225",
        "--feed-category-ids",
        "10",
    )
    assert "--feed-id is required when --feed-category-ids is used" in result.output


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


def test_adgroups_add_dynamic_feed_payload_omits_type():
    """Issue #281: dynamic feed add sets top-level DynamicTextFeedAdGroup."""
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Dynamic Feed Group",
        "--campaign-id",
        "111",
        "--type",
        "DYNAMIC_TEXT_FEED_AD_GROUP",
        "--region-ids",
        "1,225",
        "--feed-id",
        "170",
    )
    group = body["params"]["AdGroups"][0]
    assert "Type" not in group
    assert group["RegionIds"] == [1, 225]
    assert group["DynamicTextFeedAdGroup"] == {"FeedId": 170}


def test_adgroups_add_dynamic_feed_autotargeting_categories_payload():
    """Issue #281: dynamic feed add supports documented categories."""
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Dynamic Feed Group",
        "--campaign-id",
        "111",
        "--type",
        "DYNAMIC_TEXT_FEED_AD_GROUP",
        "--region-ids",
        "1,225",
        "--feed-id",
        "170",
        "--autotargeting-category",
        "exact=yes",
        "--autotargeting-category",
        "ACCESSORY=NO",
    )
    group = body["params"]["AdGroups"][0]
    assert group["DynamicTextFeedAdGroup"] == {
        "FeedId": 170,
        "AutotargetingCategories": [
            {"Category": "EXACT", "Value": "YES"},
            {"Category": "ACCESSORY", "Value": "NO"},
        ],
    }


def test_adgroups_add_dynamic_feed_requires_feed_id():
    """Issue #281: add docs require DynamicTextFeedAdGroup.FeedId."""
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Dynamic Feed Group",
        "--campaign-id",
        "111",
        "--type",
        "DYNAMIC_TEXT_FEED_AD_GROUP",
        "--region-ids",
        "225",
    )
    assert "--feed-id is required for DYNAMIC_TEXT_FEED_AD_GROUP" in result.output


def test_adgroups_add_dynamic_feed_rejects_undocumented_settings():
    """Issue #281: feed subtype only exposes docs-backed category flags."""
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Dynamic Feed Group",
        "--campaign-id",
        "111",
        "--type",
        "DYNAMIC_TEXT_FEED_AD_GROUP",
        "--region-ids",
        "225",
        "--feed-id",
        "170",
        "--autotargeting-settings-exact",
        "YES",
    )
    assert (
        "--autotargeting-settings-exact is not compatible with --type "
        "DYNAMIC_TEXT_FEED_AD_GROUP"
    ) in result.output


def test_adgroups_add_cpm_banner_keywords_payload_omits_type():
    """Issue #282: CPM banner keyword subtype sends an empty block."""
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "CPM Keywords Group",
        "--campaign-id",
        "111",
        "--type",
        "CPM_BANNER_KEYWORDS_AD_GROUP",
        "--region-ids",
        "1,225",
    )
    group = body["params"]["AdGroups"][0]
    assert "Type" not in group
    assert group["RegionIds"] == [1, 225]
    assert group["CpmBannerKeywordsAdGroup"] == {}


def test_adgroups_add_cpm_banner_keywords_accepts_negative_keywords():
    """Issue #282: CPM banner keyword groups still accept negative keywords."""
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "CPM Keywords Group",
        "--campaign-id",
        "111",
        "--type",
        "CPM_BANNER_KEYWORDS_AD_GROUP",
        "--region-ids",
        "225",
        "--negative-keywords",
        "used,repair",
        "--negative-keyword-shared-set-ids",
        "10",
    )
    group = body["params"]["AdGroups"][0]
    assert group["CpmBannerKeywordsAdGroup"] == {}
    assert group["NegativeKeywords"] == {"Items": ["used", "repair"]}
    assert group["NegativeKeywordSharedSetIds"] == {"Items": [10]}


def test_adgroups_add_cpm_banner_user_profile_payload_omits_type():
    """Issue #282: CPM user-profile subtype sends an empty block."""
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "CPM User Profile Group",
        "--campaign-id",
        "111",
        "--type",
        "CPM_BANNER_USER_PROFILE_AD_GROUP",
        "--region-ids",
        "1,225",
    )
    group = body["params"]["AdGroups"][0]
    assert "Type" not in group
    assert group["RegionIds"] == [1, 225]
    assert group["CpmBannerUserProfileAdGroup"] == {}


def test_adgroups_add_cpm_user_profile_rejects_empty_negative_keyword_flag():
    """Issue #282: disallowed negative keyword flags reject even empty values."""
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "CPM User Profile Group",
        "--campaign-id",
        "111",
        "--type",
        "CPM_BANNER_USER_PROFILE_AD_GROUP",
        "--region-ids",
        "225",
        "--negative-keywords",
        "",
    )
    assert (
        "--negative-keywords is not compatible with --type "
        "CPM_BANNER_USER_PROFILE_AD_GROUP"
    ) in result.output


def test_adgroups_add_cpm_video_payload_omits_type():
    """Issue #282: CPM video subtype sends an empty block."""
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "CPM Video Group",
        "--campaign-id",
        "111",
        "--type",
        "CPM_VIDEO_AD_GROUP",
        "--region-ids",
        "1,225",
    )
    group = body["params"]["AdGroups"][0]
    assert "Type" not in group
    assert group["RegionIds"] == [1, 225]
    assert group["CpmVideoAdGroup"] == {}


def test_adgroups_add_cpm_user_profile_rejects_negative_keywords():
    """Issue #282: docs disallow negative keywords for user-profile CPM groups."""
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "CPM User Profile Group",
        "--campaign-id",
        "111",
        "--type",
        "CPM_BANNER_USER_PROFILE_AD_GROUP",
        "--region-ids",
        "225",
        "--negative-keywords",
        "used",
    )
    assert (
        "--negative-keywords is not compatible with --type "
        "CPM_BANNER_USER_PROFILE_AD_GROUP"
    ) in result.output


def test_adgroups_add_cpm_video_rejects_negative_keyword_shared_sets():
    """Issue #282: docs disallow negative keyword sets for CPM video groups."""
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "CPM Video Group",
        "--campaign-id",
        "111",
        "--type",
        "CPM_VIDEO_AD_GROUP",
        "--region-ids",
        "225",
        "--negative-keyword-shared-set-ids",
        "10",
    )
    assert (
        "--negative-keyword-shared-set-ids is not compatible with --type "
        "CPM_VIDEO_AD_GROUP"
    ) in result.output


def test_adgroups_add_cpm_video_rejects_negative_keyword_shared_sets_before_parse():
    """Issue #282: type incompatibility wins over shared-set ID parsing."""
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "CPM Video Group",
        "--campaign-id",
        "111",
        "--type",
        "CPM_VIDEO_AD_GROUP",
        "--region-ids",
        "225",
        "--negative-keyword-shared-set-ids",
        "notanumber",
    )
    assert (
        "--negative-keyword-shared-set-ids is not compatible with --type "
        "CPM_VIDEO_AD_GROUP"
    ) in result.output
    assert "Invalid ID" not in result.output


def test_adgroups_add_unified_payload_omits_type():
    """Issue #283: unified ad group sends top-level UnifiedAdGroup."""
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Unified Group",
        "--campaign-id",
        "111",
        "--type",
        "UNIFIED_AD_GROUP",
        "--region-ids",
        "1,225",
        "--offer-retargeting",
        "yes",
    )
    group = body["params"]["AdGroups"][0]
    assert "Type" not in group
    assert group["RegionIds"] == [1, 225]
    assert group["UnifiedAdGroup"] == {"OfferRetargeting": "YES"}


def test_adgroups_add_unified_requires_offer_retargeting():
    """Issue #283: UnifiedAdGroupAdd.OfferRetargeting is required."""
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Unified Group",
        "--campaign-id",
        "111",
        "--type",
        "UNIFIED_AD_GROUP",
        "--region-ids",
        "225",
    )
    assert "--offer-retargeting is required for UNIFIED_AD_GROUP" in result.output


def test_adgroups_add_rejects_unified_flag_for_text_group():
    """Issue #283: UnifiedAdGroup flags must not leak into other types."""
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Text Group",
        "--campaign-id",
        "111",
        "--type",
        "TEXT_AD_GROUP",
        "--region-ids",
        "225",
        "--offer-retargeting",
        "YES",
    )
    assert "--offer-retargeting is not compatible with --type TEXT_AD_GROUP" in (
        result.output
    )


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
    cpm_result = _rejected(
        "adgroups",
        "add",
        "--name",
        "CPM Keywords Group",
        "--campaign-id",
        "111",
        "--region-ids",
        "225",
        "--type",
        "CPM_BANNER_KEYWORDS_AD_GROUP",
        "--domain-url",
        "example.com",
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
    assert (
        "--domain-url is not compatible with --type CPM_BANNER_KEYWORDS_AD_GROUP"
        in cpm_result.output
    )


def test_adgroups_add_rejects_text_feed_category_ids_for_dynamic_group():
    """Issue #284: TextAdGroupFeedParams flags apply only to TEXT_AD_GROUP."""
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
        "--feed-category-ids",
        "10",
    )
    assert (
        "--feed-category-ids is not compatible with --type DYNAMIC_TEXT_AD_GROUP"
        in result.output
    )


def test_adgroups_add_rejects_text_feed_category_ids_for_smart_group():
    """Issue #284: TextAdGroupFeedParams category IDs do not apply to smart."""
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Smart Group",
        "--campaign-id",
        "111",
        "--type",
        "SMART_AD_GROUP",
        "--region-ids",
        "225",
        "--feed-id",
        "170",
        "--feed-category-ids",
        "10",
    )
    assert (
        "--feed-category-ids is not compatible with --type SMART_AD_GROUP"
        in result.output
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


def test_adgroups_update_text_feed_params_payload_without_type():
    """Issue #284: update sets top-level TextAdGroupFeedParams without --type."""
    body = _dry_run(
        "adgroups",
        "update",
        "--id",
        "222",
        "--feed-id",
        "170",
        "--feed-category-ids",
        "10,11",
    )
    group = body["params"]["AdGroups"][0]
    assert group == {
        "Id": 222,
        "TextAdGroupFeedParams": {
            "FeedId": 170,
            "FeedCategoryIds": {"Items": [10, 11]},
        },
    }


def test_adgroups_update_text_feed_params_feed_id_only_payload():
    """Issue #284: TextAdGroupFeedParamsUpdate can update just FeedId."""
    body = _dry_run(
        "adgroups",
        "update",
        "--id",
        "222",
        "--feed-id",
        "170",
    )
    group = body["params"]["AdGroups"][0]
    assert group == {"Id": 222, "TextAdGroupFeedParams": {"FeedId": 170}}


def test_adgroups_update_text_feed_params_requires_feed_id_for_categories():
    """Issue #284: update cannot send category IDs without FeedId."""
    result = _rejected(
        "adgroups",
        "update",
        "--id",
        "222",
        "--feed-category-ids",
        "10",
    )
    assert "--feed-id is required when --feed-category-ids is used" in result.output


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


def test_adgroups_update_dynamic_feed_autotargeting_categories_payload():
    """Issue #281: update targets DynamicTextFeedAdGroup with --dynamic-feed."""
    body = _dry_run(
        "adgroups",
        "update",
        "--id",
        "222",
        "--dynamic-feed",
        "--autotargeting-category",
        "ALTERNATIVE=YES",
        "--autotargeting-category",
        "competitor=no",
    )
    group = body["params"]["AdGroups"][0]
    assert group == {
        "Id": 222,
        "DynamicTextFeedAdGroup": {
            "AutotargetingCategories": [
                {"Category": "ALTERNATIVE", "Value": "YES"},
                {"Category": "COMPETITOR", "Value": "NO"},
            ],
        },
    }


def test_adgroups_update_dynamic_feed_requires_category():
    """Issue #281: --dynamic-feed must not be silently ignored."""
    result = _rejected("adgroups", "update", "--id", "222", "--dynamic-feed")
    assert "--dynamic-feed requires --autotargeting-category" in result.output


def test_adgroups_update_rejects_mixed_dynamic_text_and_feed_subtype_flags():
    """Issue #281: update must not emit both dynamic subtype blocks."""
    result = _rejected(
        "adgroups",
        "update",
        "--id",
        "222",
        "--dynamic-feed",
        "--autotargeting-category",
        "EXACT=YES",
        "--domain-url",
        "example.com",
    )
    assert "DynamicTextAdGroup update flags" in result.output
    assert "--domain-url" in result.output
    assert "DynamicTextFeedAdGroup update flags" in result.output
    assert "--dynamic-feed" in result.output


def test_adgroups_update_rejects_mixed_dynamic_feed_and_mobile_subtype_flags():
    """Issue #281: update must not mix feed subtype with mobile app fields."""
    result = _rejected(
        "adgroups",
        "update",
        "--id",
        "222",
        "--dynamic-feed",
        "--autotargeting-category",
        "EXACT=YES",
        "--target-device-types",
        "DEVICE_TYPE_MOBILE",
    )
    assert "DynamicTextFeedAdGroup update flags" in result.output
    assert "--dynamic-feed" in result.output
    assert "MobileAppAdGroup update flags" in result.output
    assert "--target-device-types" in result.output


def test_adgroups_update_rejects_mixed_dynamic_and_mobile_subtype_flags():
    """Issue #280: update must not emit two subtype blocks in one item."""
    result = _rejected(
        "adgroups",
        "update",
        "--id",
        "222",
        "--domain-url",
        "example.com",
        "--target-device-types",
        "DEVICE_TYPE_MOBILE",
    )
    assert "DynamicTextAdGroup update flags" in result.output
    assert "--domain-url" in result.output
    assert "MobileAppAdGroup update flags" in result.output
    assert "--target-device-types" in result.output


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


def test_adgroups_update_smart_payload_without_type():
    """Issue #283: update sets top-level SmartAdGroup without --type."""
    body = _dry_run(
        "adgroups",
        "update",
        "--id",
        "222",
        "--ad-title-source",
        "name",
        "--ad-body-source",
        "description",
    )
    group = body["params"]["AdGroups"][0]
    assert group == {
        "Id": 222,
        "SmartAdGroup": {
            "AdTitleSource": "name",
            "AdBodySource": "description",
        },
    }


def test_adgroups_update_unified_payload_without_type():
    """Issue #283: update sets top-level UnifiedAdGroup without --type."""
    body = _dry_run(
        "adgroups",
        "update",
        "--id",
        "222",
        "--offer-retargeting",
        "no",
    )
    group = body["params"]["AdGroups"][0]
    assert group == {
        "Id": 222,
        "UnifiedAdGroup": {"OfferRetargeting": "NO"},
    }


def test_adgroups_update_rejects_mixed_smart_and_unified_subtype_flags():
    """Issue #283: update must not emit SmartAdGroup and UnifiedAdGroup."""
    result = _rejected(
        "adgroups",
        "update",
        "--id",
        "222",
        "--ad-title-source",
        "name",
        "--offer-retargeting",
        "YES",
    )
    assert "SmartAdGroup update flags" in result.output
    assert "--ad-title-source" in result.output
    assert "UnifiedAdGroup update flags" in result.output
    assert "--offer-retargeting" in result.output


def test_adgroups_update_rejects_mixed_text_feed_and_smart_subtype_flags():
    """Issue #284: update must not emit TextAdGroupFeedParams and SmartAdGroup."""
    result = _rejected(
        "adgroups",
        "update",
        "--id",
        "222",
        "--feed-id",
        "170",
        "--ad-title-source",
        "name",
    )
    assert "TextAdGroupFeedParams update flags" in result.output
    assert "--feed-id" in result.output
    assert "SmartAdGroup update flags" in result.output
    assert "--ad-title-source" in result.output


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
    assert "--dynamic-feed" in result.output
    assert "--autotargeting-category" in result.output
    assert "--autotargeting-settings-* flags" in result.output
    assert "--target-device-types" in result.output
    assert "--target-carrier" in result.output
    assert "--target-operating-system-version" in result.output
    assert "--ad-title-source" in result.output
    assert "--ad-body-source" in result.output
    assert "--offer-retargeting" in result.output
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


def test_campaigns_add_smart_campaign_optional_controls_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Smart Controls",
        "--start-date",
        "2026-06-01",
        "--type",
        "SMART_CAMPAIGN",
        "--counter-id",
        "123",
        "--filter-average-cpc",
        "1000000",
        "--setting",
        "ADD_TO_FAVORITES=YES",
        "--tracking-params",
        "utm_source=direct",
        "--attribution-model",
        "AUTO",
    )
    smart = body["params"]["Campaigns"][0]["SmartCampaign"]
    assert smart == {
        "CounterId": 123,
        "BiddingStrategy": {
            "Search": {"BiddingStrategyType": "SERVING_OFF"},
            "Network": {
                "BiddingStrategyType": "AVERAGE_CPC_PER_FILTER",
                "AverageCpcPerFilter": {"FilterAverageCpc": 1000000},
            },
        },
        "Settings": [{"Option": "ADD_TO_FAVORITES", "Value": "YES"}],
        "AttributionModel": "AUTO",
        "TrackingParams": "utm_source=direct",
    }


def test_campaigns_add_smart_package_bidding_strategy_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Smart Package",
        "--start-date",
        "2026-06-01",
        "--type",
        "SMART_CAMPAIGN",
        "--counter-id",
        "123",
        "--package-strategy-id",
        "700",
        "--package-platform-search",
        "YES",
        "--package-platform-network",
        "NO",
    )
    smart = body["params"]["Campaigns"][0]["SmartCampaign"]
    assert "BiddingStrategy" not in smart
    assert smart == {
        "CounterId": 123,
        "PackageBiddingStrategy": {
            "StrategyId": 700,
            "Platforms": {"Search": "YES", "Network": "NO"},
        },
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


def test_campaigns_add_rejects_smart_priority_goals_without_bidding_strategy():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Smart Bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "SMART_CAMPAIGN",
        "--counter-id",
        "123",
        "--filter-average-cpc",
        "1000000",
        "--priority-goals",
        "1234567:80,9876543:20",
    )
    assert "SmartCampaign.PriorityGoals" in result.output
    assert "#290" in result.output


# ----------------------------------------------------------------------
# campaigns add: SmartCampaign.BiddingStrategy.Search families (issue #367)
#
# Documentation source: the cached SOAP WSDL at
# ``tests/wsdl_cache/campaigns.xml`` is the canonical, version-pinned
# source of truth for the Yandex Direct v5 SmartCampaign request shape.
# The public Yandex docs URLs (``yandex.ru/dev/direct/doc/ref-v5/
# campaigns/SmartCampaignAdd.html``, ``yandex.com/dev/direct/doc/
# objects/strategies.html``, etc.) returned HTTP 404 during the
# implementation of #367 — confirmed manually with WebFetch — so this
# block deliberately cites the WSDL line ranges below as the official
# evidence trail.
#
# WSDL ref: tests/wsdl_cache/campaigns.xml lines 1401-1481
# (``Strategy*Add`` add-side subtypes), 851-929 (``Strategy*`` get-side
# subtypes used by update — these carry ``BudgetType``), 1789-1820
# (``SmartCampaignStrategyAddBase`` / ``SmartCampaignSearchStrategyAdd``
# containers), 1965-1978 (``CustomPeriodBudget`` /
# ``ExplorationBudget``), 396-410
# (``SmartCampaignSearchStrategyTypeEnum``).
# ----------------------------------------------------------------------


def _smart_search_base():
    return [
        "campaigns",
        "add",
        "--name",
        "Smart Search",
        "--start-date",
        "2026-06-01",
        "--type",
        "SMART_CAMPAIGN",
        "--counter-id",
        "123",
        # Network defaults to AVERAGE_CPC_PER_FILTER + filter-average-cpc
        # (this PR's scope is Search; Network is owned by #368).
        "--filter-average-cpc",
        "1000000",
    ]


def test_campaigns_add_smart_search_average_cpc_per_campaign_payload():
    # CLI takes rubles (5 = 5_000_000 micro-rubles).
    body = _dry_run(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        "--smart-search-average-cpc",
        "5",
        "--smart-search-bid-ceiling",
        "9",
        "--smart-search-weekly-spend-limit",
        "50",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPC_PER_CAMPAIGN",
        "AverageCpcPerCampaign": {
            "AverageCpc": 5000000,
            "WeeklySpendLimit": 50000000,
            "BidCeiling": 9000000,
        },
    }


def test_campaigns_add_smart_search_average_cpc_per_filter_payload():
    body = _dry_run(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_CPC_PER_FILTER",
        "--smart-search-filter-average-cpc",
        "3",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPC_PER_FILTER",
        "AverageCpcPerFilter": {"FilterAverageCpc": 3000000},
    }


def test_campaigns_add_smart_search_average_cpc_per_filter_minimal_payload():
    # WSDL: StrategyAverageCpcPerFilterAdd.FilterAverageCpc is minOccurs=0,
    # so an empty payload subtype block is legal.
    body = _dry_run(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_CPC_PER_FILTER",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {"BiddingStrategyType": "AVERAGE_CPC_PER_FILTER"}


def test_campaigns_add_smart_search_average_cpa_per_campaign_payload():
    body = _dry_run(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_CPA_PER_CAMPAIGN",
        "--smart-search-average-cpa",
        "4",
        "--smart-search-goal-id",
        "111",
        "--smart-search-bid-ceiling",
        "9",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPA_PER_CAMPAIGN",
        "AverageCpaPerCampaign": {
            "AverageCpa": 4000000,
            "GoalId": 111,
            "BidCeiling": 9000000,
        },
    }


def test_campaigns_add_smart_search_average_cpa_per_filter_payload():
    body = _dry_run(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_CPA_PER_FILTER",
        "--smart-search-filter-average-cpa",
        "4.5",
        "--smart-search-goal-id",
        "222",
        "--smart-search-cp-spend-limit",
        "100",
        "--smart-search-cp-start-date",
        "2026-06-01",
        "--smart-search-cp-end-date",
        "2026-06-30",
        "--smart-search-cp-auto-continue",
        "YES",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPA_PER_FILTER",
        "AverageCpaPerFilter": {
            "FilterAverageCpa": 4500000,
            "GoalId": 222,
            "CustomPeriodBudget": {
                "SpendLimit": 100000000,
                "StartDate": "2026-06-01",
                "EndDate": "2026-06-30",
                "AutoContinue": "YES",
            },
        },
    }


def test_campaigns_add_smart_search_pay_for_conversion_per_campaign_payload():
    body = _dry_run(
        *_smart_search_base(),
        "--search-strategy",
        "PAY_FOR_CONVERSION_PER_CAMPAIGN",
        "--smart-search-cpa",
        "6",
        "--smart-search-goal-id",
        "333",
        "--smart-search-weekly-spend-limit",
        "50",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_PER_CAMPAIGN",
        "PayForConversionPerCampaign": {
            "Cpa": 6000000,
            "GoalId": 333,
            "WeeklySpendLimit": 50000000,
        },
    }


def test_campaigns_add_smart_search_pay_for_conversion_per_filter_payload():
    body = _dry_run(
        *_smart_search_base(),
        "--search-strategy",
        "PAY_FOR_CONVERSION_PER_FILTER",
        "--smart-search-cpa",
        "5.5",
        "--smart-search-goal-id",
        "444",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_PER_FILTER",
        "PayForConversionPerFilter": {"Cpa": 5500000, "GoalId": 444},
    }


def test_campaigns_add_smart_search_average_roi_payload():
    body = _dry_run(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_ROI",
        "--smart-search-reserve-return",
        "30",
        "--smart-search-roi-coef",
        "1.5",
        "--smart-search-goal-id",
        "555",
        "--smart-search-profitability",
        "0.2",
        "--smart-search-bid-ceiling",
        "10",
        "--smart-search-exploration-min",
        "20",
        "--smart-search-exploration-min-custom",
        "YES",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_ROI",
        "AverageRoi": {
            "ReserveReturn": 30,
            "RoiCoef": 1500000,
            "GoalId": 555,
            "BidCeiling": 10000000,
            "Profitability": 200000,
            "ExplorationBudget": {
                "MinimumExplorationBudget": 20000000,
                "IsMinimumExplorationBudgetCustom": "YES",
            },
        },
    }


def test_campaigns_add_smart_search_average_crr_payload():
    body = _dry_run(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_CRR",
        "--smart-search-crr",
        "25",
        "--smart-search-goal-id",
        "666",
        "--smart-search-weekly-spend-limit",
        "40",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CRR",
        "AverageCrr": {
            "Crr": 25,
            "GoalId": 666,
            "WeeklySpendLimit": 40000000,
        },
    }


def test_campaigns_add_smart_search_pay_for_conversion_crr_payload():
    body = _dry_run(
        *_smart_search_base(),
        "--search-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--smart-search-crr",
        "15",
        "--smart-search-goal-id",
        "777",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_CRR",
        "PayForConversionCrr": {"Crr": 15, "GoalId": 777},
    }


def test_campaigns_add_smart_search_serving_off_payload():
    body = _dry_run(
        *_smart_search_base(),
        "--search-strategy",
        "SERVING_OFF",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {"BiddingStrategyType": "SERVING_OFF"}


def test_campaigns_add_smart_search_default_serving_off_payload():
    # No --search-strategy at all → SERVING_OFF default; preserved from
    # pre-#367 behavior.
    body = _dry_run(*_smart_search_base())
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {"BiddingStrategyType": "SERVING_OFF"}


def test_campaigns_add_smart_search_requires_average_cpc():
    result = _rejected(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
    )
    assert "--smart-search-average-cpc" in result.output


def test_campaigns_add_smart_search_requires_filter_average_cpa_and_goal():
    result = _rejected(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_CPA_PER_FILTER",
    )
    assert "--smart-search-filter-average-cpa" in result.output
    assert "--smart-search-goal-id" in result.output


def test_campaigns_add_smart_search_rejects_wrong_subtype_flag():
    # --smart-search-average-cpa belongs only to AverageCpaPerCampaign;
    # using it with AVERAGE_CPC_PER_CAMPAIGN must raise.
    result = _rejected(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        "--smart-search-average-cpc",
        "5",
        "--smart-search-average-cpa",
        "4",
    )
    assert "--smart-search-average-cpa" in result.output


def test_campaigns_add_smart_search_rejects_bid_ceiling_on_crr():
    # WSDL StrategyAverageCrrAdd has no BidCeiling field.
    result = _rejected(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_CRR",
        "--smart-search-crr",
        "15",
        "--smart-search-goal-id",
        "777",
        "--smart-search-bid-ceiling",
        "10",
    )
    assert "--smart-search-bid-ceiling" in result.output


def test_campaigns_add_smart_search_rejects_exploration_on_cpc_per_campaign():
    # WSDL StrategyAverageCpcPerCampaignAdd has no ExplorationBudget.
    result = _rejected(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        "--smart-search-average-cpc",
        "5",
        "--smart-search-exploration-min",
        "1",
        "--smart-search-exploration-min-custom",
        "YES",
    )
    assert "ExplorationBudget" in result.output


def test_campaigns_add_smart_search_rejects_partial_custom_period_budget():
    result = _rejected(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        "--smart-search-average-cpc",
        "5",
        "--smart-search-cp-spend-limit",
        "100",
        # Missing start-date / end-date / auto-continue.
    )
    assert "CustomPeriodBudget" in result.output


def test_campaigns_add_smart_search_rejects_partial_exploration_budget():
    result = _rejected(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_ROI",
        "--smart-search-reserve-return",
        "30",
        "--smart-search-roi-coef",
        "1.5",
        "--smart-search-goal-id",
        "555",
        "--smart-search-exploration-min",
        "20",
        # missing --smart-search-exploration-min-custom
    )
    assert "ExplorationBudget" in result.output


def test_campaigns_add_smart_search_rejects_detail_without_strategy():
    # When --search-strategy is omitted but typed flags are present, the
    # builder must fail rather than silently picking SERVING_OFF.
    result = _rejected(
        *_smart_search_base(),
        "--smart-search-average-cpc",
        "5",
    )
    assert "SmartCampaign search detail flags" in result.output


def test_campaigns_add_smart_search_rejects_serving_off_with_details():
    result = _rejected(
        *_smart_search_base(),
        "--search-strategy",
        "SERVING_OFF",
        "--smart-search-average-cpc",
        "5",
    )
    assert "SERVING_OFF" in result.output


def test_campaigns_add_smart_search_rejects_invalid_strategy():
    result = _rejected(
        *_smart_search_base(),
        "--search-strategy",
        "BOGUS_STRATEGY",
    )
    assert "SMART_CAMPAIGN" in result.output


# ----------------------------------------------------------------------
# campaigns update: SmartCampaign.BiddingStrategy.Search families (#367)
# ----------------------------------------------------------------------


def test_campaigns_update_smart_search_average_cpc_per_campaign_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        "--smart-search-average-cpc",
        "5",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 55,
        "SmartCampaign": {
            "BiddingStrategy": {
                "Search": {
                    "BiddingStrategyType": "AVERAGE_CPC_PER_CAMPAIGN",
                    "AverageCpcPerCampaign": {"AverageCpc": 5000000},
                }
            }
        },
    }


def test_campaigns_update_smart_search_average_cpc_per_filter_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPC_PER_FILTER",
        "--smart-search-filter-average-cpc",
        "3",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPC_PER_FILTER",
        "AverageCpcPerFilter": {"FilterAverageCpc": 3000000},
    }


def test_campaigns_update_smart_search_average_cpa_per_campaign_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA_PER_CAMPAIGN",
        "--smart-search-average-cpa",
        "4",
        "--smart-search-goal-id",
        "111",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPA_PER_CAMPAIGN",
        "AverageCpaPerCampaign": {"AverageCpa": 4000000, "GoalId": 111},
    }


def test_campaigns_update_smart_search_average_cpa_per_filter_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA_PER_FILTER",
        "--smart-search-filter-average-cpa",
        "4.5",
        "--smart-search-goal-id",
        "222",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPA_PER_FILTER",
        "AverageCpaPerFilter": {"FilterAverageCpa": 4500000, "GoalId": 222},
    }


def test_campaigns_update_smart_search_pay_for_conversion_per_campaign_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--search-strategy",
        "PAY_FOR_CONVERSION_PER_CAMPAIGN",
        "--smart-search-cpa",
        "6",
        "--smart-search-goal-id",
        "333",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_PER_CAMPAIGN",
        "PayForConversionPerCampaign": {"Cpa": 6000000, "GoalId": 333},
    }


def test_campaigns_update_smart_search_pay_for_conversion_per_filter_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--search-strategy",
        "PAY_FOR_CONVERSION_PER_FILTER",
        "--smart-search-cpa",
        "5.5",
        "--smart-search-goal-id",
        "444",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_PER_FILTER",
        "PayForConversionPerFilter": {"Cpa": 5500000, "GoalId": 444},
    }


def test_campaigns_update_smart_search_average_roi_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_ROI",
        "--smart-search-reserve-return",
        "30",
        "--smart-search-roi-coef",
        "1.5",
        "--smart-search-goal-id",
        "555",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_ROI",
        "AverageRoi": {
            "ReserveReturn": 30,
            "RoiCoef": 1500000,
            "GoalId": 555,
        },
    }


def test_campaigns_update_smart_search_average_crr_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CRR",
        "--smart-search-crr",
        "25",
        "--smart-search-goal-id",
        "666",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CRR",
        "AverageCrr": {"Crr": 25, "GoalId": 666},
    }


def test_campaigns_update_smart_search_pay_for_conversion_crr_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--search-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--smart-search-crr",
        "15",
        "--smart-search-goal-id",
        "777",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_CRR",
        "PayForConversionCrr": {"Crr": 15, "GoalId": 777},
    }


def test_campaigns_update_smart_search_partial_field_no_required_check():
    # On update, WSDL minOccurs=1 required-field validation is skipped so
    # users can change a single field. The builder must still accept the
    # subtype without rejecting (matches CpmBanner / MobileApp update
    # semantics).
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA_PER_CAMPAIGN",
        # Only --smart-search-average-cpa, no --smart-search-goal-id
        "--smart-search-average-cpa",
        "4",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPA_PER_CAMPAIGN",
        "AverageCpaPerCampaign": {"AverageCpa": 4000000},
    }


def test_campaigns_update_smart_search_omits_bidding_strategy_when_unused():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--counter-id",
        "123",
    )
    smart = body["params"]["Campaigns"][0]["SmartCampaign"]
    assert "BiddingStrategy" not in smart
    assert smart == {"CounterId": 123}


def test_campaigns_update_smart_search_rejects_package_with_search_flags():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--package-strategy-id",
        "700",
        "--search-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        "--smart-search-average-cpc",
        "5",
    )
    assert "PackageBiddingStrategy" in result.output


def test_campaigns_update_smart_search_rejects_detail_without_strategy():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--smart-search-average-cpc",
        "5",
    )
    assert "SmartCampaign search detail flags" in result.output


def test_campaigns_add_rejects_smart_search_with_package_strategy():
    # Regression for codex adversarial review: --smart-search-* flags must
    # not be silently dropped when PackageBiddingStrategy is in use.
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Smart Package + Search bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "SMART_CAMPAIGN",
        "--counter-id",
        "123",
        "--package-strategy-id",
        "700",
        "--package-platform-search",
        "YES",
        "--package-platform-network",
        "YES",
        "--smart-search-average-cpc",
        "5",
    )
    assert "PackageBiddingStrategy" in result.output
    assert "--smart-search-average-cpc" in result.output


def test_campaigns_update_smart_search_budget_type_weekly_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        "--smart-search-weekly-spend-limit",
        "40",
        "--smart-search-budget-type",
        "WEEKLY_BUDGET",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPC_PER_CAMPAIGN",
        "AverageCpcPerCampaign": {
            "WeeklySpendLimit": 40000000,
            "CustomPeriodBudget": None,
            "BudgetType": "WEEKLY_BUDGET",
        },
    }


def test_campaigns_update_smart_search_budget_type_custom_period_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA_PER_FILTER",
        "--smart-search-cp-spend-limit",
        "100",
        "--smart-search-cp-start-date",
        "2026-06-01",
        "--smart-search-cp-end-date",
        "2026-06-30",
        "--smart-search-cp-auto-continue",
        "YES",
        "--smart-search-budget-type",
        "CUSTOM_PERIOD_BUDGET",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPA_PER_FILTER",
        "AverageCpaPerFilter": {
            "CustomPeriodBudget": {
                "SpendLimit": 100000000,
                "StartDate": "2026-06-01",
                "EndDate": "2026-06-30",
                "AutoContinue": "YES",
            },
            "WeeklySpendLimit": None,
            "BudgetType": "CUSTOM_PERIOD_BUDGET",
        },
    }


def test_campaigns_update_smart_search_budget_type_rejects_inconsistency():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        # WEEKLY_BUDGET but no --smart-search-weekly-spend-limit
        "--smart-search-budget-type",
        "WEEKLY_BUDGET",
    )
    assert "--smart-search-weekly-spend-limit" in result.output


def test_campaigns_add_smart_search_budget_type_is_update_only():
    result = _rejected(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        "--smart-search-average-cpc",
        "5",
        "--smart-search-budget-type",
        "WEEKLY_BUDGET",
    )
    # The add command doesn't even register the flag (mirrors how
    # --mobile-search-budget-type is update-only). Click rejects it as
    # "No such option".
    assert (
        "--smart-search-budget-type" in result.output
        or "No such option" in result.output
    )


def test_campaigns_add_rejects_smart_package_without_required_platforms():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Smart Package Bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "SMART_CAMPAIGN",
        "--counter-id",
        "123",
        "--package-strategy-id",
        "700",
    )
    assert "--package-platform-search" in result.output
    assert "--package-platform-network" in result.output


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
        "1234567:80:YES,9876543:20",
        "--bid-ceiling",
        "1000000000",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text["PriorityGoals"] == {
        "Items": [
            {"GoalId": 1234567, "Value": 80, "IsMetrikaSourceOfValue": "YES"},
            {"GoalId": 9876543, "Value": 20},
        ]
    }
    search = text["BiddingStrategy"]["Search"]
    assert search["BiddingStrategyType"] == "AVERAGE_CPA_MULTIPLE_GOALS"
    assert search["AverageCpaMultipleGoals"] == {"BidCeiling": 1000000000}


def test_campaigns_add_text_search_placement_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "HIGHEST_POSITION",
        "--search-placement-search-results",
        "YES",
        "--search-placement-product-gallery",
        "NO",
        "--search-placement-dynamic-places",
        "YES",
    )
    search = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"]["Search"]
    assert search == {
        "BiddingStrategyType": "HIGHEST_POSITION",
        "PlacementTypes": {
            "SearchResults": "YES",
            "ProductGallery": "NO",
            "DynamicPlaces": "YES",
        },
    }


def test_campaigns_update_text_search_placement_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "TEXT_CAMPAIGN",
        "--search-strategy",
        "SERVING_OFF",
        "--search-placement-product-gallery",
        "NO",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text["BiddingStrategy"]["Search"] == {
        "BiddingStrategyType": "SERVING_OFF",
        "PlacementTypes": {"ProductGallery": "NO"},
    }


def test_campaigns_add_text_search_placement_requires_strategy():
    result = _rejected(
        *_cpa_base_args(),
        "--search-placement-search-results",
        "YES",
    )
    assert (
        "TextCampaign search placement flags require --search-strategy" in result.output
    )


def test_campaigns_add_text_search_rejects_unknown_strategy():
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "BROKEN",
    )
    assert "--search-strategy for TEXT_CAMPAIGN must be one of" in result.output


def test_campaigns_add_counter_ids_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--counter-ids",
        "111,222,333",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text["CounterIds"] == {"Items": [111, 222, 333]}


def test_campaigns_add_text_campaign_optional_controls_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--setting",
        "ADD_METRICA_TAG=YES",
        "--relevant-keywords-budget-percent",
        "40",
        "--relevant-keywords-mode",
        "optimal",
        "--relevant-keywords-optimize-goal-id",
        "0",
        "--attribution-model",
        "auto",
        "--negative-keyword-shared-set-ids",
        "10,11,12",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text["Settings"] == [{"Option": "ADD_METRICA_TAG", "Value": "YES"}]
    assert text["RelevantKeywords"] == {
        "BudgetPercent": 40,
        "Mode": "OPTIMAL",
        "OptimizeGoalId": 0,
    }
    assert text["AttributionModel"] == "AUTO"
    assert text["NegativeKeywordSharedSetIds"] == {"Items": [10, 11, 12]}


def test_campaigns_add_text_package_bidding_strategy_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--counter-ids",
        "111,222",
        "--attribution-model",
        "AUTO",
        "--package-strategy-id",
        "700",
        "--package-platform-search-result",
        "YES",
        "--package-platform-product-gallery",
        "NO",
        "--package-platform-network",
        "YES",
        "--package-platform-dynamic-places",
        "NO",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert "BiddingStrategy" not in text
    assert text["CounterIds"] == {"Items": [111, 222]}
    assert text["AttributionModel"] == "AUTO"
    assert text["PackageBiddingStrategy"] == {
        "StrategyId": 700,
        "Platforms": {
            "SearchResult": "YES",
            "ProductGallery": "NO",
            "Network": "YES",
            "DynamicPlaces": "NO",
        },
    }


def test_campaigns_add_unified_campaign_optional_controls_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Unified",
        "--start-date",
        "2026-06-01",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--setting",
        "ADD_METRICA_TAG=YES",
        "--counter-ids",
        "111,222",
        "--tracking-params",
        "utm_source=direct",
        "--attribution-model",
        "AUTO",
        "--negative-keyword-shared-set-ids",
        "10,11",
    )
    unified = body["params"]["Campaigns"][0]["UnifiedCampaign"]
    assert unified == {
        "Settings": [{"Option": "ADD_METRICA_TAG", "Value": "YES"}],
        "BiddingStrategy": {
            "Search": {"BiddingStrategyType": "HIGHEST_POSITION"},
            "Network": {"BiddingStrategyType": "SERVING_OFF"},
        },
        "CounterIds": {"Items": [111, 222]},
        "AttributionModel": "AUTO",
        "NegativeKeywordSharedSetIds": {"Items": [10, 11]},
        "TrackingParams": "utm_source=direct",
    }


def test_campaigns_add_unified_package_bidding_strategy_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Unified Package",
        "--start-date",
        "2026-06-01",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--package-strategy-id",
        "700",
        "--package-platform-search-result",
        "YES",
        "--package-platform-product-gallery",
        "NO",
        "--package-platform-maps",
        "YES",
        "--package-platform-search-organization-list",
        "NO",
        "--package-platform-network",
        "YES",
        "--package-platform-dynamic-places",
        "NO",
    )
    unified = body["params"]["Campaigns"][0]["UnifiedCampaign"]
    assert "BiddingStrategy" not in unified
    assert unified == {
        "Settings": [],
        "PackageBiddingStrategy": {
            "StrategyId": 700,
            "Platforms": {
                "SearchResult": "YES",
                "ProductGallery": "NO",
                "Maps": "YES",
                "SearchOrganizationList": "NO",
                "Network": "YES",
                "DynamicPlaces": "NO",
            },
        },
    }


def test_campaigns_update_text_campaign_optional_controls_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "TEXT_CAMPAIGN",
        "--setting",
        "ADD_METRICA_TAG=NO",
        "--counter-ids",
        "111,222",
        "--priority-goals",
        "1234567:80:YES,9876543:20",
        "--relevant-keywords-mode",
        "maximum",
        "--relevant-keywords-optimize-goal-id",
        "0",
        "--attribution-model",
        "AUTO",
        "--negative-keyword-shared-set-ids",
        "10,11",
        "--tracking-params",
        "utm_source=direct",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 123,
        "TextCampaign": {
            "Settings": [{"Option": "ADD_METRICA_TAG", "Value": "NO"}],
            "CounterIds": {"Items": [111, 222]},
            "PriorityGoals": {
                "Items": [
                    {
                        "GoalId": 1234567,
                        "Value": 80,
                        "IsMetrikaSourceOfValue": "YES",
                        "Operation": "SET",
                    },
                    {"GoalId": 9876543, "Value": 20, "Operation": "SET"},
                ]
            },
            "RelevantKeywords": {
                "Mode": "MAXIMUM",
                "OptimizeGoalId": 0,
            },
            "AttributionModel": "AUTO",
            "NegativeKeywordSharedSetIds": {"Items": [10, 11]},
            "TrackingParams": "utm_source=direct",
        },
    }


def test_campaigns_update_unified_campaign_optional_controls_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--setting",
        "ADD_METRICA_TAG=NO",
        "--counter-ids",
        "111,222",
        "--priority-goals",
        "1234567:80:YES,9876543:20",
        "--tracking-params",
        "utm_source=direct",
        "--attribution-model",
        "AUTO",
        "--negative-keyword-shared-set-ids",
        "10,11",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 123,
        "UnifiedCampaign": {
            "Settings": [{"Option": "ADD_METRICA_TAG", "Value": "NO"}],
            "CounterIds": {"Items": [111, 222]},
            "PriorityGoals": {
                "Items": [
                    {
                        "GoalId": 1234567,
                        "Value": 80,
                        "IsMetrikaSourceOfValue": "YES",
                        "Operation": "SET",
                    },
                    {"GoalId": 9876543, "Value": 20, "Operation": "SET"},
                ]
            },
            "AttributionModel": "AUTO",
            "NegativeKeywordSharedSetIds": {"Items": [10, 11]},
            "TrackingParams": "utm_source=direct",
        },
    }


def test_campaigns_update_text_package_bidding_strategy_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "TEXT_CAMPAIGN",
        "--counter-ids",
        "111",
        "--attribution-model",
        "LC",
        "--package-strategy-from-campaign-id",
        "456",
        "--package-platform-search-result",
        "YES",
        "--package-platform-product-gallery",
        "YES",
        "--package-platform-network",
        "NO",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text == {
        "CounterIds": {"Items": [111]},
        "AttributionModel": "LC",
        "PackageBiddingStrategy": {
            "StrategyFromCampaignId": 456,
            "Platforms": {
                "SearchResult": "YES",
                "ProductGallery": "YES",
                "Network": "NO",
            },
        },
    }


def test_campaigns_update_unified_package_bidding_strategy_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--package-strategy-from-campaign-id",
        "456",
        "--package-platform-search-result",
        "YES",
        "--package-platform-product-gallery",
        "YES",
        "--package-platform-maps",
        "NO",
        "--package-platform-search-organization-list",
        "YES",
        "--package-platform-network",
        "NO",
    )
    unified = body["params"]["Campaigns"][0]["UnifiedCampaign"]
    assert unified == {
        "PackageBiddingStrategy": {
            "StrategyFromCampaignId": 456,
            "Platforms": {
                "SearchResult": "YES",
                "ProductGallery": "YES",
                "Maps": "NO",
                "SearchOrganizationList": "YES",
                "Network": "NO",
            },
        },
    }


def test_campaigns_add_dynamic_campaign_optional_controls_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dynamic Controls",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--setting",
        "ADD_METRICA_TAG=YES",
        "--dynamic-placement-search-results",
        "YES",
        "--dynamic-placement-product-gallery",
        "NO",
        "--counter-ids",
        "111,222",
        "--tracking-params",
        "utm_source=direct",
        "--attribution-model",
        "AUTO",
        "--negative-keyword-shared-set-ids",
        "10,11",
    )
    dynamic = body["params"]["Campaigns"][0]["DynamicTextCampaign"]
    assert dynamic == {
        "Settings": [{"Option": "ADD_METRICA_TAG", "Value": "YES"}],
        "BiddingStrategy": {
            "Search": {"BiddingStrategyType": "HIGHEST_POSITION"},
            "Network": {"BiddingStrategyType": "SERVING_OFF"},
        },
        "CounterIds": {"Items": [111, 222]},
        "PlacementTypes": [
            {"Type": "SEARCH_RESULTS", "Value": "YES"},
            {"Type": "PRODUCT_GALLERY", "Value": "NO"},
        ],
        "AttributionModel": "AUTO",
        "NegativeKeywordSharedSetIds": {"Items": [10, 11]},
        "TrackingParams": "utm_source=direct",
    }


def test_campaigns_update_dynamic_campaign_optional_controls_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--setting",
        "ADD_METRICA_TAG=NO",
        "--dynamic-placement-search-results",
        "NO",
        "--dynamic-placement-product-gallery",
        "YES",
        "--counter-ids",
        "111,222",
        "--priority-goals",
        "1234567:80:YES,9876543:20",
        "--tracking-params",
        "utm_source=direct",
        "--attribution-model",
        "LC",
        "--negative-keyword-shared-set-ids",
        "10,11",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 123,
        "DynamicTextCampaign": {
            "Settings": [{"Option": "ADD_METRICA_TAG", "Value": "NO"}],
            "PlacementTypes": [
                {"Type": "SEARCH_RESULTS", "Value": "NO"},
                {"Type": "PRODUCT_GALLERY", "Value": "YES"},
            ],
            "CounterIds": {"Items": [111, 222]},
            "PriorityGoals": {
                "Items": [
                    {
                        "GoalId": 1234567,
                        "Value": 80,
                        "IsMetrikaSourceOfValue": "YES",
                        "Operation": "SET",
                    },
                    {"GoalId": 9876543, "Value": 20, "Operation": "SET"},
                ]
            },
            "AttributionModel": "LC",
            "NegativeKeywordSharedSetIds": {"Items": [10, 11]},
            "TrackingParams": "utm_source=direct",
        },
    }


def test_campaigns_add_dynamic_package_bidding_strategy_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dynamic Package",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--package-strategy-id",
        "700",
    )
    dynamic = body["params"]["Campaigns"][0]["DynamicTextCampaign"]
    assert "BiddingStrategy" not in dynamic
    assert dynamic == {
        "Settings": [],
        "PackageBiddingStrategy": {"StrategyId": 700},
    }


def test_campaigns_update_dynamic_package_bidding_strategy_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--package-strategy-from-campaign-id",
        "456",
    )
    dynamic = body["params"]["Campaigns"][0]["DynamicTextCampaign"]
    assert dynamic == {
        "PackageBiddingStrategy": {"StrategyFromCampaignId": 456},
    }


def test_campaigns_add_rejects_dynamic_package_platforms():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Dynamic Package",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--package-strategy-id",
        "700",
        "--package-platform-search-result",
        "YES",
    )
    assert "--package-platform-search-result" in result.output
    assert "DYNAMIC_TEXT_CAMPAIGN" in result.output


def test_campaigns_add_notification_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--sms-events",
        "FINISHED,moderation",
        "--sms-time-from",
        "09:00",
        "--sms-time-to",
        "18:00",
        "--notification-email",
        "ops@example.com",
        "--notification-check-position-interval",
        "15",
        "--notification-warning-balance",
        "20",
        "--notification-send-account-news",
        "no",
        "--notification-send-warnings",
        "YES",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["Notification"] == {
        "SmsSettings": {
            "Events": ["FINISHED", "MODERATION"],
            "TimeFrom": "09:00",
            "TimeTo": "18:00",
        },
        "EmailSettings": {
            "Email": "ops@example.com",
            "CheckPositionInterval": 15,
            "WarningBalance": 20,
            "SendAccountNews": "NO",
            "SendWarnings": "YES",
        },
    }
    # Lives at campaign level, sibling of TextCampaign.
    assert "Notification" not in campaign["TextCampaign"]


def test_campaigns_add_time_targeting_payload():
    schedule_row = "1,0,0,50,50,100,100,150,200,200,150,100,100,80,70,100,100,100,50,50,40,30,0,0,0"
    body = _dry_run(
        *_cpa_base_args(),
        "--time-targeting-schedule",
        schedule_row,
        "--consider-working-weekends",
        "YES",
        "--holidays-suspend-on-holidays",
        "no",
        "--holidays-bid-percent",
        "50",
        "--holidays-start-hour",
        "10",
        "--holidays-end-hour",
        "20",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["TimeTargeting"] == {
        "Schedule": {"Items": [schedule_row]},
        "ConsiderWorkingWeekends": "YES",
        "HolidaysSchedule": {
            "SuspendOnHolidays": "NO",
            "BidPercent": 50,
            "StartHour": 10,
            "EndHour": 20,
        },
    }
    assert "TimeTargeting" not in campaign["TextCampaign"]


def test_campaigns_add_campaign_level_controls_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--client-info",
        "Client A",
        "--time-zone",
        "Europe/Moscow",
        "--negative-keywords",
        "used,repair",
        "--blocked-ips",
        "192.0.2.1,198.51.100.2",
        "--excluded-sites",
        "example.com,example.net",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["ClientInfo"] == "Client A"
    assert campaign["TimeZone"] == "Europe/Moscow"
    assert campaign["NegativeKeywords"] == {"Items": ["used", "repair"]}
    assert campaign["BlockedIps"] == {"Items": ["192.0.2.1", "198.51.100.2"]}
    assert campaign["ExcludedSites"] == {"Items": ["example.com", "example.net"]}


def test_campaigns_update_campaign_level_controls_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--client-info",
        "Client B",
        "--sms-events",
        "FINISHED",
        "--notification-email",
        "ops@example.com",
        "--notification-send-warnings",
        "NO",
        "--time-zone",
        "Asia/Bangkok",
        "--negative-keywords",
        "used",
        "--blocked-ips",
        "192.0.2.1",
        "--excluded-sites",
        "example.com",
        "--time-targeting-schedule",
        "1A0123456789ABCDEFGHIJKL",
        "--consider-working-weekends",
        "NO",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 123,
        "ClientInfo": "Client B",
        "Notification": {
            "SmsSettings": {"Events": ["FINISHED"]},
            "EmailSettings": {
                "Email": "ops@example.com",
                "SendWarnings": "NO",
            },
        },
        "TimeZone": "Asia/Bangkok",
        "NegativeKeywords": {"Items": ["used"]},
        "BlockedIps": {"Items": ["192.0.2.1"]},
        "ExcludedSites": {"Items": ["example.com"]},
        "TimeTargeting": {
            "Schedule": {"Items": ["1A0123456789ABCDEFGHIJKL"]},
            "ConsiderWorkingWeekends": "NO",
        },
    }


def test_campaigns_time_targeting_requires_consider_working_weekends():
    result = _rejected(
        *_cpa_base_args(),
        "--time-targeting-schedule",
        "1A0123456789ABCDEFGHIJKL",
    )
    assert "--consider-working-weekends" in result.output


def test_campaigns_holidays_requires_suspend_on_holidays():
    result = _rejected(
        *_cpa_base_args(),
        "--consider-working-weekends",
        "YES",
        "--holidays-bid-percent",
        "50",
    )
    assert "--holidays-suspend-on-holidays" in result.output


def test_campaigns_rejects_invalid_sms_events():
    result = _rejected(*_cpa_base_args(), "--sms-events", "BROKEN")
    assert "--sms-events" in result.output
    assert "invalid value" in result.output


def test_campaigns_rejects_empty_negative_keywords():
    result = _rejected(*_cpa_base_args(), "--negative-keywords", ",")
    assert "--negative-keywords" in result.output


def test_campaigns_rejects_too_long_client_info():
    result = _rejected(*_cpa_base_args(), "--client-info", "x" * 256)
    assert "--client-info must be at most 255 characters" in result.output


def test_campaigns_rejects_invalid_notification_interval():
    result = _rejected(
        *_cpa_base_args(),
        "--notification-check-position-interval",
        "10",
    )
    assert "--notification-check-position-interval" in result.output


def test_campaigns_rejects_invalid_sms_time_step():
    result = _rejected(*_cpa_base_args(), "--sms-time-from", "09:10")
    assert "--sms-time-from" in result.output


def test_campaigns_rejects_non_canonical_sms_time_format():
    result = _rejected(*_cpa_base_args(), "--sms-time-from", "9:00")
    assert "--sms-time-from" in result.output
    assert "HH:MM" in result.output


def test_campaigns_rejects_legacy_notification_blob_with_guidance():
    result = _rejected(*_cpa_base_args(), "--notification", "{}")
    assert "--notification is no longer accepted" in result.output
    assert "--notification-email" in result.output


def test_campaigns_update_rejects_legacy_notification_blob_with_guidance():
    result = _rejected("campaigns", "update", "--id", "123", "--notification", "{}")
    assert "--notification is no longer accepted" in result.output
    assert "--notification-email" in result.output


def test_campaigns_rejects_legacy_time_targeting_blob_with_guidance():
    result = _rejected(*_cpa_base_args(), "--time-targeting", "{}")
    assert "--time-targeting is no longer accepted" in result.output
    assert "--time-targeting-schedule" in result.output


def test_campaigns_rejects_too_many_blocked_ips():
    result = _rejected(
        *_cpa_base_args(),
        "--blocked-ips",
        ",".join(f"192.0.2.{index}" for index in range(26)),
    )
    assert "--blocked-ips must contain at most 25 items" in result.output


def test_campaigns_rejects_holidays_bid_percent_with_suspend_yes():
    result = _rejected(
        *_cpa_base_args(),
        "--consider-working-weekends",
        "YES",
        "--holidays-suspend-on-holidays",
        "YES",
        "--holidays-bid-percent",
        "50",
    )
    assert "--holidays-bid-percent" in result.output


def test_campaigns_add_rejects_relevant_keywords_without_budget_percent():
    result = _rejected(*_cpa_base_args(), "--relevant-keywords-mode", "OPTIMAL")
    assert "--relevant-keywords-budget-percent" in result.output


def test_campaigns_add_rejects_package_strategy_without_required_platforms():
    result = _rejected(*_cpa_base_args(), "--package-strategy-id", "700")
    assert "--package-platform-search-result" in result.output
    assert "--package-platform-product-gallery" in result.output
    assert "--package-platform-network" in result.output


def test_campaigns_add_rejects_package_strategy_with_strategy_inputs():
    result = _rejected(
        *_cpa_base_args(),
        "--package-strategy-id",
        "700",
        "--package-platform-search-result",
        "YES",
        "--package-platform-product-gallery",
        "YES",
        "--package-platform-network",
        "YES",
        "--search-strategy",
        "AVERAGE_CPA",
    )
    assert "PackageBiddingStrategy cannot be combined" in result.output
    assert "--search-strategy" in result.output


def test_campaigns_add_rejects_unified_package_strategy_with_counter_ids():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Unified Package Conflict",
        "--start-date",
        "2026-06-01",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--package-strategy-id",
        "700",
        "--package-platform-search-result",
        "YES",
        "--package-platform-product-gallery",
        "YES",
        "--package-platform-network",
        "YES",
        "--counter-ids",
        "111",
    )
    assert "UnifiedCampaign.PackageBiddingStrategy cannot be combined" in result.output
    assert "--counter-ids" in result.output


def test_campaigns_add_rejects_unified_priority_goals_without_bidding_strategy():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Unified Goals",
        "--start-date",
        "2026-06-01",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--priority-goals",
        "1:50,2:50",
    )
    assert "UnifiedCampaign.PriorityGoals" in result.output
    assert "BiddingStrategy" in result.output
    assert "#290" in result.output


def test_campaigns_update_rejects_unified_package_strategy_with_priority_goals():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--package-strategy-id",
        "700",
        "--priority-goals",
        "1:50",
    )
    assert "UnifiedCampaign.PackageBiddingStrategy cannot be combined" in result.output
    assert "--priority-goals" in result.output


def test_campaigns_add_rejects_unified_client_info():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Unified",
        "--start-date",
        "2026-06-01",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--client-info",
        "Client A",
    )
    assert "UnifiedCampaign cannot be combined" in result.output
    assert "--client-info" in result.output


def test_campaigns_update_rejects_unified_notification():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--tracking-params",
        "utm_source=direct",
        "--notification-send-warnings",
        "YES",
    )
    assert "UnifiedCampaign cannot be combined" in result.output
    assert "--notification-send-warnings" in result.output


def test_campaigns_add_unified_allows_supported_email_notification_fields():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Unified Email",
        "--start-date",
        "2026-06-01",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--tracking-params",
        "utm_source=direct",
        "--notification-email",
        "ops@example.com",
        "--notification-send-account-news",
        "YES",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["Notification"] == {
        "EmailSettings": {
            "Email": "ops@example.com",
            "SendAccountNews": "YES",
        }
    }


def test_campaigns_update_unified_allows_supported_email_notification_fields():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--tracking-params",
        "utm_source=direct",
        "--notification-email",
        "ops@example.com",
        "--notification-send-account-news",
        "NO",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["Notification"] == {
        "EmailSettings": {
            "Email": "ops@example.com",
            "SendAccountNews": "NO",
        }
    }


def test_campaigns_add_rejects_unified_sms_notification():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Unified SMS",
        "--start-date",
        "2026-06-01",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--tracking-params",
        "utm_source=direct",
        "--sms-events",
        "FINISHED",
    )
    assert "UnifiedCampaign cannot be combined" in result.output
    assert "--sms-events" in result.output


def test_campaigns_rejects_too_many_negative_keyword_shared_set_ids():
    result = _rejected(
        *_cpa_base_args(),
        "--negative-keyword-shared-set-ids",
        "10,11,12,13",
    )
    assert (
        "--negative-keyword-shared-set-ids must contain at most 3 items"
        in result.output
    )


def test_campaigns_update_text_subtype_fields_require_type():
    result = _rejected("campaigns", "update", "--id", "123", "--counter-ids", "111")
    assert "--counter-ids requires --type" in result.output


def test_campaigns_update_rejects_partial_package_platforms():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "TEXT_CAMPAIGN",
        "--package-platform-dynamic-places",
        "YES",
    )
    assert "--package-platform-search-result" in result.output


def test_campaigns_help_exposes_typed_campaign_level_flags_not_json_blobs():
    for command in ("add", "update"):
        result = CliRunner().invoke(cli, ["campaigns", command, "--help"])
        assert result.exit_code == 0
        assert "--notification " not in result.output
        assert "--time-targeting " not in result.output
        assert "--notification-email" in result.output
        assert "--time-targeting-schedule" in result.output
        assert "--negative-keywords" in result.output
        assert "--blocked-ips" in result.output
        assert "--excluded-sites" in result.output


def test_campaigns_help_exposes_text_and_unified_campaign_optional_flags():
    for command in ("add", "update"):
        result = CliRunner().invoke(cli, ["campaigns", command, "--help"])
        assert result.exit_code == 0
        assert "--counter-ids" in result.output
        assert "--priority-goals" in result.output
        assert "--relevant-keywords-budget-percent" in result.output
        assert "--attribution-model" in result.output
        assert "--package-strategy-id" in result.output
        assert "--package-platform-search-result" in result.output
        assert "--package-platform-maps" in result.output
        assert "--package-platform-search-organization-list" in result.output
        assert "--negative-keyword-shared-set-ids" in result.output


def test_campaigns_help_exposes_cpm_banner_optional_flags():
    for command in ("add", "update"):
        result = CliRunner().invoke(cli, ["campaigns", command, "--help"])
        assert result.exit_code == 0
        assert "--average-cpm" in result.output
        assert "--average-cpv" in result.output
        assert "--strategy-spend-limit" in result.output
        assert "--strategy-start-date" in result.output
        assert "--strategy-end-date" in result.output
        assert "--strategy-auto-continue" in result.output
        assert "--frequency-cap-impressions" in result.output
        assert "--frequency-cap-period-days" in result.output
        assert "--frequency-cap-period-all" in result.output
        assert "--video-target" in result.output


def test_campaigns_help_exposes_mobile_app_search_strategy_flags():
    common_flags = {
        "--mobile-search-weekly-spend-limit",
        "--mobile-search-bid-ceiling",
        "--mobile-search-custom-period-spend-limit",
        "--mobile-search-custom-period-start-date",
        "--mobile-search-custom-period-end-date",
        "--mobile-search-custom-period-auto-continue",
        "--mobile-search-average-cpc",
        "--mobile-search-average-cpi",
        "--mobile-search-clicks-per-week",
    }
    for command in ("add", "update"):
        result = CliRunner().invoke(cli, ["campaigns", command, "--help"])
        assert result.exit_code == 0
        for flag in common_flags:
            assert flag in result.output
    add_help = CliRunner().invoke(cli, ["campaigns", "add", "--help"]).output
    update_help = CliRunner().invoke(cli, ["campaigns", "update", "--help"]).output
    assert "--mobile-search-budget-type" not in add_help
    assert "--mobile-search-budget-type" in update_help


def test_campaigns_help_exposes_mobile_app_network_strategy_flags():
    common_flags = {
        "--mobile-network-weekly-spend-limit",
        "--mobile-network-bid-ceiling",
        "--mobile-network-custom-period-spend-limit",
        "--mobile-network-custom-period-start-date",
        "--mobile-network-custom-period-end-date",
        "--mobile-network-custom-period-auto-continue",
        "--mobile-network-average-cpc",
        "--mobile-network-average-cpi",
        "--mobile-network-clicks-per-week",
        "--mobile-network-limit-percent",
    }
    for command in ("add", "update"):
        result = CliRunner().invoke(cli, ["campaigns", command, "--help"])
        assert result.exit_code == 0
        for flag in common_flags:
            assert flag in result.output
    add_help = CliRunner().invoke(cli, ["campaigns", "add", "--help"]).output
    update_help = CliRunner().invoke(cli, ["campaigns", "update", "--help"]).output
    assert "--mobile-network-budget-type" not in add_help
    assert "--mobile-network-budget-type" in update_help


def test_campaigns_help_exposes_text_search_placement_flags():
    placement_flags = {
        "--search-placement-search-results",
        "--search-placement-product-gallery",
        "--search-placement-dynamic-places",
    }
    out_of_scope_flags = {
        "--search-weekly-spend-limit",
        "--search-budget-type",
        "--search-average-cpa",
        "--search-crr",
    }
    for command in ("add", "update"):
        result = CliRunner().invoke(cli, ["campaigns", command, "--help"])
        assert result.exit_code == 0
        for flag in placement_flags:
            assert flag in result.output
        for flag in out_of_scope_flags:
            assert flag not in result.output


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


def test_campaigns_add_mobile_app_campaign_optional_controls_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Mobile App Controls",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--setting",
        "ADD_TO_FAVORITES=YES",
        "--negative-keyword-shared-set-ids",
        "10,11",
    )
    mobile = body["params"]["Campaigns"][0]["MobileAppCampaign"]
    assert mobile == {
        "BiddingStrategy": {
            "Search": {"BiddingStrategyType": "HIGHEST_POSITION"},
            "Network": {"BiddingStrategyType": "SERVING_OFF"},
        },
        "Settings": [{"Option": "ADD_TO_FAVORITES", "Value": "YES"}],
        "NegativeKeywordSharedSetIds": {"Items": [10, 11]},
    }


def test_campaigns_add_mobile_app_average_cpi_search_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Mobile App CPI",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPI",
        "--mobile-search-average-cpi",
        "5",
        "--mobile-search-weekly-spend-limit",
        "1000",
        "--mobile-search-bid-ceiling",
        "12.5",
    )
    mobile = body["params"]["Campaigns"][0]["MobileAppCampaign"]
    assert mobile["BiddingStrategy"] == {
        "Search": {
            "BiddingStrategyType": "AVERAGE_CPI",
            "AverageCpi": {
                "AverageCpi": 5000000,
                "WeeklySpendLimit": 1000000000,
                "BidCeiling": 12500000,
            },
        },
        "Network": {"BiddingStrategyType": "SERVING_OFF"},
    }


def test_campaigns_add_mobile_app_weekly_click_package_search_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Mobile App Click Package",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--search-strategy",
        "WEEKLY_CLICK_PACKAGE",
        "--mobile-search-clicks-per-week",
        "100",
        "--mobile-search-average-cpc",
        "7.25",
    )
    search = body["params"]["Campaigns"][0]["MobileAppCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "WEEKLY_CLICK_PACKAGE",
        "WeeklyClickPackage": {
            "ClicksPerWeek": 100,
            "AverageCpc": 7250000,
        },
    }


def test_campaigns_add_mobile_app_wb_maximum_clicks_custom_period_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Mobile App Custom Period",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--mobile-search-custom-period-spend-limit",
        "1000",
        "--mobile-search-custom-period-start-date",
        "2026-06-01",
        "--mobile-search-custom-period-end-date",
        "2026-06-30",
        "--mobile-search-custom-period-auto-continue",
        "NO",
    )
    search = body["params"]["Campaigns"][0]["MobileAppCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
        "WbMaximumClicks": {
            "CustomPeriodBudget": {
                "SpendLimit": 1000000000,
                "StartDate": "2026-06-01",
                "EndDate": "2026-06-30",
                "AutoContinue": "NO",
            }
        },
    }


def test_campaigns_update_mobile_app_rejects_impressions_below_search_strategy():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--search-strategy",
        "IMPRESSIONS_BELOW_SEARCH",
    )
    assert "IMPRESSIONS_BELOW_SEARCH is disabled" in result.output


def test_campaigns_add_mobile_app_rejects_missing_required_search_field():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Mobile App Missing CPI",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--search-strategy",
        "PAY_FOR_INSTALL",
    )
    assert "PAY_FOR_INSTALL requires --mobile-search-average-cpi" in result.output


def test_campaigns_add_mobile_app_rejects_search_detail_without_strategy():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Mobile App Detail",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--mobile-search-average-cpc",
        "5",
    )
    assert "MobileAppCampaign search detail flags require --search-strategy" in (
        result.output
    )


def test_campaigns_add_mobile_app_rejects_partial_custom_period_budget():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Mobile App Partial Custom Period",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPC",
        "--mobile-search-average-cpc",
        "5",
        "--mobile-search-custom-period-spend-limit",
        "1000",
    )
    assert "CustomPeriodBudget requires all custom-period flags" in result.output
    assert "--mobile-search-custom-period-start-date" in result.output


def test_campaigns_add_mobile_app_rejects_weekly_click_package_bid_conflict():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Mobile App Click Conflict",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--search-strategy",
        "WEEKLY_CLICK_PACKAGE",
        "--mobile-search-clicks-per-week",
        "100",
        "--mobile-search-average-cpc",
        "7.25",
        "--mobile-search-bid-ceiling",
        "10",
    )
    assert "cannot combine --mobile-search-average-cpc" in result.output


def test_campaigns_add_mobile_app_average_cpi_network_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Mobile App Network CPI",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPI",
        "--mobile-network-average-cpi",
        "5",
        "--mobile-network-weekly-spend-limit",
        "1000",
        "--mobile-network-bid-ceiling",
        "12.5",
    )
    mobile = body["params"]["Campaigns"][0]["MobileAppCampaign"]
    assert mobile["BiddingStrategy"] == {
        "Search": {"BiddingStrategyType": "HIGHEST_POSITION"},
        "Network": {
            "BiddingStrategyType": "AVERAGE_CPI",
            "AverageCpi": {
                "AverageCpi": 5000000,
                "WeeklySpendLimit": 1000000000,
                "BidCeiling": 12500000,
            },
        },
    }


def test_campaigns_add_mobile_app_network_default_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Mobile App Network Default",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--network-strategy",
        "NETWORK_DEFAULT",
        "--mobile-network-limit-percent",
        "30",
    )
    network = body["params"]["Campaigns"][0]["MobileAppCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "NETWORK_DEFAULT",
        "NetworkDefault": {"LimitPercent": 30},
    }


def test_campaigns_add_mobile_app_network_wb_maximum_clicks_custom_period_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Mobile App Network Custom Period",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--mobile-network-custom-period-spend-limit",
        "1000",
        "--mobile-network-custom-period-start-date",
        "2026-06-01",
        "--mobile-network-custom-period-end-date",
        "2026-06-30",
        "--mobile-network-custom-period-auto-continue",
        "NO",
    )
    network = body["params"]["Campaigns"][0]["MobileAppCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
        "WbMaximumClicks": {
            "CustomPeriodBudget": {
                "SpendLimit": 1000000000,
                "StartDate": "2026-06-01",
                "EndDate": "2026-06-30",
                "AutoContinue": "NO",
            }
        },
    }


def test_campaigns_add_mobile_app_average_cpi_network_custom_period_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Mobile App Network CPI Custom Period",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPI",
        "--mobile-network-average-cpi",
        "5",
        "--mobile-network-custom-period-spend-limit",
        "1000",
        "--mobile-network-custom-period-start-date",
        "2026-06-01",
        "--mobile-network-custom-period-end-date",
        "2026-06-30",
        "--mobile-network-custom-period-auto-continue",
        "YES",
    )
    network = body["params"]["Campaigns"][0]["MobileAppCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPI",
        "AverageCpi": {
            "AverageCpi": 5000000,
            "CustomPeriodBudget": {
                "SpendLimit": 1000000000,
                "StartDate": "2026-06-01",
                "EndDate": "2026-06-30",
                "AutoContinue": "YES",
            },
        },
    }


def test_campaigns_add_mobile_app_rejects_missing_required_network_field():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Mobile App Missing Network CPI",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--network-strategy",
        "PAY_FOR_INSTALL",
    )
    assert "PAY_FOR_INSTALL requires --mobile-network-average-cpi" in result.output


def test_campaigns_add_mobile_app_rejects_network_detail_without_strategy():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Mobile App Network Detail",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--mobile-network-average-cpc",
        "5",
    )
    assert "MobileAppCampaign network detail flags require --network-strategy" in (
        result.output
    )


def test_campaigns_add_mobile_app_rejects_network_default_non_limit_detail():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Mobile App Network Default Detail",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--network-strategy",
        "NETWORK_DEFAULT",
        "--mobile-network-average-cpc",
        "5",
    )
    assert "NETWORK_DEFAULT does not accept --mobile-network-average-cpc" in (
        result.output
    )


def test_campaigns_add_mobile_app_rejects_network_default_limit_percent_step():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Mobile App Network Default Limit",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--network-strategy",
        "NETWORK_DEFAULT",
        "--mobile-network-limit-percent",
        "25",
    )
    assert "must be a multiple of 10 from 10 to 100" in result.output


def test_campaigns_add_mobile_app_rejects_network_weekly_click_package_bid_conflict():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Mobile App Network Click Conflict",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--network-strategy",
        "WEEKLY_CLICK_PACKAGE",
        "--mobile-network-clicks-per-week",
        "100",
        "--mobile-network-average-cpc",
        "7.25",
        "--mobile-network-bid-ceiling",
        "10",
    )
    assert "cannot combine --mobile-network-average-cpc" in result.output


def test_campaigns_add_cpm_banner_campaign_optional_controls_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "CPM Banner Controls",
        "--start-date",
        "2026-06-01",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--setting",
        "ADD_METRICA_TAG=YES",
        "--counter-ids",
        "111,222",
        "--frequency-cap-impressions",
        "5",
        "--frequency-cap-period-days",
        "7",
        "--video-target",
        "VIEWS",
    )
    cpm = body["params"]["Campaigns"][0]["CpmBannerCampaign"]
    assert cpm == {
        "BiddingStrategy": {
            "Search": {"BiddingStrategyType": "SERVING_OFF"},
            "Network": {"BiddingStrategyType": "MANUAL_CPM"},
        },
        "Settings": [{"Option": "ADD_METRICA_TAG", "Value": "YES"}],
        "CounterIds": {"Items": [111, 222]},
        "FrequencyCap": {"Impressions": 5, "PeriodDays": 7},
        "VideoTarget": "VIEWS",
    }


def test_campaigns_add_cpm_banner_wb_maximum_impressions_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "CPM Banner Strategy",
        "--start-date",
        "2026-06-01",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_IMPRESSIONS",
        "--average-cpm",
        "120.5",
        "--strategy-spend-limit",
        "1000.25",
    )
    cpm = body["params"]["Campaigns"][0]["CpmBannerCampaign"]
    assert cpm["BiddingStrategy"] == {
        "Search": {"BiddingStrategyType": "SERVING_OFF"},
        "Network": {
            "BiddingStrategyType": "WB_MAXIMUM_IMPRESSIONS",
            "WbMaximumImpressions": {
                "AverageCpm": 120500000,
                "SpendLimit": 1000250000,
            },
        },
    }


def test_campaigns_add_cpm_banner_cp_average_cpv_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "CPM Banner CPV",
        "--start-date",
        "2026-06-01",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--network-strategy",
        "CP_AVERAGE_CPV",
        "--average-cpv",
        "5",
        "--strategy-spend-limit",
        "1000",
        "--strategy-start-date",
        "2026-06-01",
        "--strategy-end-date",
        "2026-06-30",
        "--strategy-auto-continue",
        "YES",
    )
    network = body["params"]["Campaigns"][0]["CpmBannerCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "CP_AVERAGE_CPV",
        "CpAverageCpv": {
            "AverageCpv": 5000000,
            "SpendLimit": 1000000000,
            "StartDate": "2026-06-01",
            "EndDate": "2026-06-30",
            "AutoContinue": "YES",
        },
    }


def test_campaigns_add_cpm_banner_campaign_frequency_cap_all_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "CPM Banner Controls",
        "--start-date",
        "2026-06-01",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--frequency-cap-impressions",
        "5",
        "--frequency-cap-period-all",
    )
    cpm = body["params"]["Campaigns"][0]["CpmBannerCampaign"]
    assert cpm["FrequencyCap"] == {"Impressions": 5, "PeriodDays": None}


def test_campaigns_add_rejects_partial_frequency_cap():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "CPM Banner Controls",
        "--start-date",
        "2026-06-01",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--frequency-cap-impressions",
        "5",
    )
    assert "--frequency-cap-impressions" in result.output
    assert "--frequency-cap-period-days" in result.output


def test_campaigns_add_cpm_banner_rejects_bidding_strategy_flags():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "CPM Banner Controls",
        "--start-date",
        "2026-06-01",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_IMPRESSIONS",
        "--average-cpm",
        "120",
        "--average-cpv",
        "5",
        "--strategy-spend-limit",
        "1000",
    )
    assert "WB_MAXIMUM_IMPRESSIONS does not accept --average-cpv" in result.output


def test_campaigns_add_cpm_banner_rejects_missing_strategy_fields():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "CPM Banner Controls",
        "--start-date",
        "2026-06-01",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--network-strategy",
        "CP_MAXIMUM_IMPRESSIONS",
        "--average-cpm",
        "120",
        "--strategy-spend-limit",
        "1000",
    )
    assert "CP_MAXIMUM_IMPRESSIONS requires" in result.output
    assert "--strategy-start-date" in result.output
    assert "--strategy-end-date" in result.output
    assert "--strategy-auto-continue" in result.output


def test_campaigns_add_unified_tracking_params_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Unified Track",
        "--start-date",
        "2026-06-01",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--tracking-params",
        "utm_source=direct&utm_medium=cpc",
    )
    unified = body["params"]["Campaigns"][0]["UnifiedCampaign"]
    assert unified["TrackingParams"] == "utm_source=direct&utm_medium=cpc"


def test_campaigns_add_tracking_params_on_unsupported_type_rejected():
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
    assert "--tracking-params" in result.output
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


def test_campaigns_update_smart_campaign_optional_controls_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "SMART_CAMPAIGN",
        "--setting",
        "ADD_TO_FAVORITES=YES",
        "--counter-id",
        "456",
        "--priority-goals",
        "1234567:80:YES,9876543:20:NO",
        "--attribution-model",
        "AUTO",
        "--tracking-params",
        "utm_source=direct",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["SmartCampaign"] == {
        "Settings": [{"Option": "ADD_TO_FAVORITES", "Value": "YES"}],
        "CounterId": 456,
        "PriorityGoals": {
            "Items": [
                {
                    "GoalId": 1234567,
                    "Value": 80,
                    "IsMetrikaSourceOfValue": "YES",
                    "Operation": "SET",
                },
                {
                    "GoalId": 9876543,
                    "Value": 20,
                    "IsMetrikaSourceOfValue": "NO",
                    "Operation": "SET",
                },
            ]
        },
        "AttributionModel": "AUTO",
        "TrackingParams": "utm_source=direct",
    }


def test_campaigns_update_mobile_app_campaign_optional_controls_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--setting",
        "ENABLE_AUTOFOCUS=NO",
        "--negative-keyword-shared-set-ids",
        "10,11",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 123,
        "MobileAppCampaign": {
            "Settings": [{"Option": "ENABLE_AUTOFOCUS", "Value": "NO"}],
            "NegativeKeywordSharedSetIds": {"Items": [10, 11]},
        },
    }


def test_campaigns_update_mobile_app_wb_maximum_clicks_search_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--mobile-search-custom-period-spend-limit",
        "1000",
        "--mobile-search-custom-period-start-date",
        "2026-06-01",
        "--mobile-search-custom-period-end-date",
        "2026-06-30",
        "--mobile-search-custom-period-auto-continue",
        "YES",
        "--mobile-search-budget-type",
        "CUSTOM_PERIOD_BUDGET",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 123,
        "MobileAppCampaign": {
            "BiddingStrategy": {
                "Search": {
                    "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
                    "WbMaximumClicks": {
                        "CustomPeriodBudget": {
                            "SpendLimit": 1000000000,
                            "StartDate": "2026-06-01",
                            "EndDate": "2026-06-30",
                            "AutoContinue": "YES",
                        },
                        "WeeklySpendLimit": None,
                        "BudgetType": "CUSTOM_PERIOD_BUDGET",
                    },
                }
            }
        },
    }


def test_campaigns_update_mobile_app_average_cpc_weekly_budget_clears_custom_period():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPC",
        "--mobile-search-average-cpc",
        "5",
        "--mobile-search-weekly-spend-limit",
        "1000",
        "--mobile-search-budget-type",
        "WEEKLY_BUDGET",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 123,
        "MobileAppCampaign": {
            "BiddingStrategy": {
                "Search": {
                    "BiddingStrategyType": "AVERAGE_CPC",
                    "AverageCpc": {
                        "AverageCpc": 5000000,
                        "WeeklySpendLimit": 1000000000,
                        "CustomPeriodBudget": None,
                        "BudgetType": "WEEKLY_BUDGET",
                    },
                }
            }
        },
    }


def test_campaigns_update_mobile_app_rejects_budget_type_without_matching_budget():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--mobile-search-budget-type",
        "WEEKLY_BUDGET",
    )
    assert "WEEKLY_BUDGET requires --mobile-search-weekly-spend-limit" in (
        result.output
    )


def test_campaigns_update_mobile_app_rejects_budget_type_without_supported_strategy():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPI",
        "--mobile-search-budget-type",
        "WEEKLY_BUDGET",
    )
    assert "AVERAGE_CPI does not accept --mobile-search-budget-type" in result.output


def test_campaigns_update_mobile_app_wb_maximum_clicks_network_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--mobile-network-custom-period-spend-limit",
        "1000",
        "--mobile-network-custom-period-start-date",
        "2026-06-01",
        "--mobile-network-custom-period-end-date",
        "2026-06-30",
        "--mobile-network-custom-period-auto-continue",
        "YES",
        "--mobile-network-budget-type",
        "CUSTOM_PERIOD_BUDGET",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 123,
        "MobileAppCampaign": {
            "BiddingStrategy": {
                "Network": {
                    "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
                    "WbMaximumClicks": {
                        "CustomPeriodBudget": {
                            "SpendLimit": 1000000000,
                            "StartDate": "2026-06-01",
                            "EndDate": "2026-06-30",
                            "AutoContinue": "YES",
                        },
                        "WeeklySpendLimit": None,
                        "BudgetType": "CUSTOM_PERIOD_BUDGET",
                    },
                }
            }
        },
    }


def test_campaigns_update_mobile_app_average_cpc_network_weekly_budget_clears_custom_period():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPC",
        "--mobile-network-average-cpc",
        "5",
        "--mobile-network-weekly-spend-limit",
        "1000",
        "--mobile-network-budget-type",
        "WEEKLY_BUDGET",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 123,
        "MobileAppCampaign": {
            "BiddingStrategy": {
                "Network": {
                    "BiddingStrategyType": "AVERAGE_CPC",
                    "AverageCpc": {
                        "AverageCpc": 5000000,
                        "WeeklySpendLimit": 1000000000,
                        "CustomPeriodBudget": None,
                        "BudgetType": "WEEKLY_BUDGET",
                    },
                }
            }
        },
    }


def test_campaigns_update_mobile_app_average_cpi_network_custom_period_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPI",
        "--mobile-network-average-cpi",
        "5",
        "--mobile-network-custom-period-spend-limit",
        "1000",
        "--mobile-network-custom-period-start-date",
        "2026-06-01",
        "--mobile-network-custom-period-end-date",
        "2026-06-30",
        "--mobile-network-custom-period-auto-continue",
        "YES",
        "--mobile-network-budget-type",
        "CUSTOM_PERIOD_BUDGET",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 123,
        "MobileAppCampaign": {
            "BiddingStrategy": {
                "Network": {
                    "BiddingStrategyType": "AVERAGE_CPI",
                    "AverageCpi": {
                        "AverageCpi": 5000000,
                        "CustomPeriodBudget": {
                            "SpendLimit": 1000000000,
                            "StartDate": "2026-06-01",
                            "EndDate": "2026-06-30",
                            "AutoContinue": "YES",
                        },
                        "WeeklySpendLimit": None,
                        "BudgetType": "CUSTOM_PERIOD_BUDGET",
                    },
                }
            }
        },
    }


def test_campaigns_update_mobile_app_rejects_network_budget_type_without_matching_budget():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--mobile-network-budget-type",
        "WEEKLY_BUDGET",
    )
    assert "WEEKLY_BUDGET requires --mobile-network-weekly-spend-limit" in (
        result.output
    )


def test_campaigns_update_mobile_app_rejects_network_budget_type_without_supported_strategy():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--network-strategy",
        "WEEKLY_CLICK_PACKAGE",
        "--mobile-network-budget-type",
        "WEEKLY_BUDGET",
    )
    assert "WEEKLY_CLICK_PACKAGE does not accept --mobile-network-budget-type" in (
        result.output
    )


def test_campaigns_update_cpm_banner_campaign_optional_controls_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--setting",
        "ADD_METRICA_TAG=YES",
        "--counter-ids",
        "111,222",
        "--frequency-cap-impressions",
        "5",
        "--frequency-cap-period-days",
        "7",
        "--video-target",
        "CLICKS",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 123,
        "CpmBannerCampaign": {
            "Settings": [{"Option": "ADD_METRICA_TAG", "Value": "YES"}],
            "CounterIds": {"Items": [111, 222]},
            "FrequencyCap": {"Impressions": 5, "PeriodDays": 7},
            "VideoTarget": "CLICKS",
        },
    }


def test_campaigns_update_cpm_banner_strategy_search_only_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--search-strategy",
        "SERVING_OFF",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 123,
        "CpmBannerCampaign": {
            "BiddingStrategy": {
                "Search": {"BiddingStrategyType": "SERVING_OFF"},
            },
        },
    }


def test_campaigns_update_cpm_banner_wb_decreased_price_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--network-strategy",
        "WB_DECREASED_PRICE_FOR_REPEATED_IMPRESSIONS",
        "--average-cpm",
        "120",
        "--strategy-spend-limit",
        "1000",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 123,
        "CpmBannerCampaign": {
            "BiddingStrategy": {
                "Network": {
                    "BiddingStrategyType": (
                        "WB_DECREASED_PRICE_FOR_REPEATED_IMPRESSIONS"
                    ),
                    "WbDecreasedPriceForRepeatedImpressions": {
                        "AverageCpm": 120000000,
                        "SpendLimit": 1000000000,
                    },
                },
            },
        },
    }


def test_campaigns_update_cpm_banner_campaign_frequency_cap_all_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--frequency-cap-impressions",
        "5",
        "--frequency-cap-period-all",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 123,
        "CpmBannerCampaign": {
            "FrequencyCap": {"Impressions": 5, "PeriodDays": None},
        },
    }


def test_campaigns_update_rejects_partial_frequency_cap():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--frequency-cap-period-days",
        "7",
    )
    assert "--frequency-cap-impressions" in result.output
    assert "--frequency-cap-period-days" in result.output


def test_campaigns_update_cpm_banner_strategy_details_require_network_strategy():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--average-cpm",
        "120",
        "--strategy-spend-limit",
        "1000",
    )
    assert "strategy detail flags require --network-strategy" in result.output


def test_campaigns_update_rejects_conflicting_frequency_cap_period_flags():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--frequency-cap-impressions",
        "5",
        "--frequency-cap-period-days",
        "7",
        "--frequency-cap-period-all",
    )
    assert "--frequency-cap-period-days" in result.output
    assert "--frequency-cap-period-all" in result.output


def test_campaigns_update_smart_package_bidding_strategy_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "SMART_CAMPAIGN",
        "--package-strategy-from-campaign-id",
        "700",
        "--package-platform-search",
        "YES",
        "--package-platform-network",
        "NO",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["SmartCampaign"] == {
        "PackageBiddingStrategy": {
            "StrategyFromCampaignId": 700,
            "Platforms": {"Search": "YES", "Network": "NO"},
        },
    }


def test_campaigns_update_rejects_smart_text_package_platforms():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "SMART_CAMPAIGN",
        "--package-platform-search-result",
        "YES",
    )
    assert "--package-platform-search-result" in result.output
    assert "SMART_CAMPAIGN" in result.output


def test_campaigns_update_unified_tracking_params_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--tracking-params",
        "utm_source=direct",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["UnifiedCampaign"] == {"TrackingParams": "utm_source=direct"}


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


def test_campaigns_update_tracking_params_on_cpm_banner_rejected():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--tracking-params",
        "utm_source=direct",
    )
    assert "--tracking-params" in result.output
    assert "CPM_BANNER_CAMPAIGN" in result.output


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
    assert dyn["CounterIds"] == {"Items": [555]}


# --- Issue #365: DynamicTextCampaign.BiddingStrategy.Network ---


def test_campaigns_add_dynamic_text_network_default_payload():
    """#365: NETWORK_DEFAULT emits NetworkDefault.LimitPercent only."""
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net Default",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "NETWORK_DEFAULT",
        "--dyn-network-limit-percent",
        "40",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "NETWORK_DEFAULT",
        "NetworkDefault": {"LimitPercent": 40},
    }


def test_campaigns_add_dynamic_text_network_maximum_coverage_payload():
    """#365: MAXIMUM_COVERAGE accepts no detail block."""
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net Max Coverage",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "MAXIMUM_COVERAGE",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {"BiddingStrategyType": "MAXIMUM_COVERAGE"}


def test_campaigns_add_dynamic_text_network_wb_maximum_clicks_weekly_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net WbClicks Weekly",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--dyn-network-weekly-spend-limit",
        "1000",
        "--dyn-network-bid-ceiling",
        "100",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
        "WbMaximumClicks": {
            "WeeklySpendLimit": 1000000000,
            "BidCeiling": 100000000,
        },
    }


def test_campaigns_add_dynamic_text_network_wb_maximum_clicks_custom_period_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net WbClicks CP",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--dyn-network-custom-period-spend-limit",
        "5000",
        "--dyn-network-custom-period-start-date",
        "2026-06-01",
        "--dyn-network-custom-period-end-date",
        "2026-06-30",
        "--dyn-network-custom-period-auto-continue",
        "NO",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
        "WbMaximumClicks": {
            "CustomPeriodBudget": {
                "SpendLimit": 5000000000,
                "StartDate": "2026-06-01",
                "EndDate": "2026-06-30",
                "AutoContinue": "NO",
            }
        },
    }


def test_campaigns_add_dynamic_text_network_wb_maximum_conversion_rate_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net WbConvRate",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--dyn-network-goal-id",
        "77",
        "--dyn-network-weekly-spend-limit",
        "2000",
        "--dyn-network-bid-ceiling",
        "50",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WB_MAXIMUM_CONVERSION_RATE",
        "WbMaximumConversionRate": {
            "GoalId": 77,
            "WeeklySpendLimit": 2000000000,
            "BidCeiling": 50000000,
        },
    }


def test_campaigns_add_dynamic_text_network_average_cpc_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net AvgCpc",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPC",
        "--dyn-network-average-cpc",
        "7",
        "--dyn-network-weekly-spend-limit",
        "500",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPC",
        "AverageCpc": {
            "AverageCpc": 7000000,
            "WeeklySpendLimit": 500000000,
        },
    }


def test_campaigns_add_dynamic_text_network_average_cpa_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net AvgCpa",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPA",
        "--dyn-network-average-cpa",
        "150",
        "--dyn-network-goal-id",
        "12",
        "--dyn-network-bid-ceiling",
        "20",
        "--dyn-network-exploration-budget",
        "300",
        "--dyn-network-exploration-budget-custom",
        "YES",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPA",
        "AverageCpa": {
            "AverageCpa": 150000000,
            "GoalId": 12,
            "BidCeiling": 20000000,
            "ExplorationBudget": {
                "MinimumExplorationBudget": 300000000,
                "IsMinimumExplorationBudgetCustom": "YES",
            },
        },
    }


def test_campaigns_add_dynamic_text_network_pay_for_conversion_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net PayForConv",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "PAY_FOR_CONVERSION",
        "--dyn-network-cpa",
        "300",
        "--dyn-network-goal-id",
        "55",
        "--dyn-network-weekly-spend-limit",
        "2500",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION",
        "PayForConversion": {
            "Cpa": 300000000,
            "GoalId": 55,
            "WeeklySpendLimit": 2500000000,
        },
    }


def test_campaigns_add_dynamic_text_network_average_roi_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net AvgRoi",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_ROI",
        "--dyn-network-reserve-return",
        "60",
        "--dyn-network-roi-coef",
        "150",
        "--dyn-network-goal-id",
        "88",
        "--dyn-network-profitability",
        "25",
        "--dyn-network-bid-ceiling",
        "12",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_ROI",
        "AverageRoi": {
            "ReserveReturn": 60,
            "RoiCoef": 150,
            "GoalId": 88,
            "BidCeiling": 12000000,
            "Profitability": 25,
        },
    }


def test_campaigns_add_dynamic_text_network_average_crr_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net AvgCrr",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CRR",
        "--dyn-network-crr",
        "30",
        "--dyn-network-goal-id",
        "61",
        "--dyn-network-weekly-spend-limit",
        "800",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CRR",
        "AverageCrr": {
            "Crr": 30,
            "GoalId": 61,
            "WeeklySpendLimit": 800000000,
        },
    }


def test_campaigns_add_dynamic_text_network_pay_for_conversion_crr_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net P4CCrr",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--dyn-network-crr",
        "25",
        "--dyn-network-goal-id",
        "44",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_CRR",
        "PayForConversionCrr": {
            "Crr": 25,
            "GoalId": 44,
        },
    }


def test_campaigns_add_dynamic_text_network_weekly_click_package_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net WeeklyClick",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "WEEKLY_CLICK_PACKAGE",
        "--dyn-network-clicks-per-week",
        "200",
        "--dyn-network-average-cpc",
        "3",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WEEKLY_CLICK_PACKAGE",
        "WeeklyClickPackage": {
            "AverageCpc": 3000000,
            "ClicksPerWeek": 200,
        },
    }


def test_campaigns_add_dynamic_text_network_serving_off_payload():
    """#365: SERVING_OFF (and no flags) is the implicit default."""
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net Off",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {"BiddingStrategyType": "SERVING_OFF"}


def test_campaigns_add_dynamic_text_network_rejects_detail_without_strategy():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Dyn Missing Strategy",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--dyn-network-average-cpc",
        "5",
    )
    assert (
        "DynamicTextCampaign network detail flags require --network-strategy"
        in result.output
    )


def test_campaigns_add_dynamic_text_network_rejects_average_cpc_for_average_cpa():
    """#365: WSDL field-support gate — AverageCpa subtype has no AverageCpc."""
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Dyn Bad Field",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPA",
        "--dyn-network-average-cpa",
        "100",
        "--dyn-network-goal-id",
        "1",
        "--dyn-network-average-cpc",
        "5",
    )
    assert "AVERAGE_CPA does not accept --dyn-network-average-cpc" in result.output


def test_campaigns_add_dynamic_text_network_rejects_average_cpa_required_fields():
    """#365: WSDL minOccurs=1 gate — AverageCpa needs AverageCpa+GoalId."""
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Dyn Missing Req",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPA",
    )
    assert "AVERAGE_CPA requires" in result.output
    assert "--dyn-network-average-cpa" in result.output
    assert "--dyn-network-goal-id" in result.output


def test_campaigns_add_dynamic_text_network_rejects_average_roi_required_fields():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Dyn Roi Missing",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_ROI",
        "--dyn-network-reserve-return",
        "10",
    )
    assert "AVERAGE_ROI requires" in result.output
    assert "--dyn-network-roi-coef" in result.output
    assert "--dyn-network-goal-id" in result.output


def test_campaigns_add_dynamic_text_network_rejects_maximum_coverage_with_details():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Dyn MaxCov Bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "MAXIMUM_COVERAGE",
        "--dyn-network-bid-ceiling",
        "10",
    )
    assert (
        "MAXIMUM_COVERAGE does not accept DynamicTextCampaign network detail flags"
        in result.output
    )


def test_campaigns_add_dynamic_text_network_rejects_limit_percent_off_step():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Dyn LimitPct Bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "NETWORK_DEFAULT",
        "--dyn-network-limit-percent",
        "25",
    )
    assert "must be a multiple of 10" in result.output


def test_campaigns_add_dynamic_text_network_rejects_partial_custom_period():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Dyn CP Partial",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--dyn-network-custom-period-spend-limit",
        "100",
    )
    assert (
        "DynamicTextCampaign CustomPeriodBudget requires all custom-period flags"
        in result.output
    )


def test_campaigns_add_dynamic_text_network_weekly_click_package_combined_ceilings_payload():
    """#365: WSDL StrategyWeeklyClickPackageAdd allows AverageCpc + BidCeiling."""
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn WCP Combo",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "WEEKLY_CLICK_PACKAGE",
        "--dyn-network-clicks-per-week",
        "100",
        "--dyn-network-average-cpc",
        "5",
        "--dyn-network-bid-ceiling",
        "10",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WEEKLY_CLICK_PACKAGE",
        "WeeklyClickPackage": {
            "AverageCpc": 5000000,
            "BidCeiling": 10000000,
            "ClicksPerWeek": 100,
        },
    }


def test_campaigns_add_dynamic_text_network_rejects_partial_exploration_budget():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Dyn ExpBudget Partial",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPA",
        "--dyn-network-average-cpa",
        "100",
        "--dyn-network-goal-id",
        "1",
        "--dyn-network-exploration-budget",
        "100",
    )
    assert "DynamicTextCampaign ExplorationBudget requires both" in result.output


def test_campaigns_update_dynamic_text_network_average_cpc_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "999",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPC",
        "--dyn-network-average-cpc",
        "8",
        "--dyn-network-weekly-spend-limit",
        "1500",
    )
    dyn = body["params"]["Campaigns"][0]["DynamicTextCampaign"]
    assert dyn["BiddingStrategy"] == {
        "Network": {
            "BiddingStrategyType": "AVERAGE_CPC",
            "AverageCpc": {
                "AverageCpc": 8000000,
                "WeeklySpendLimit": 1500000000,
            },
        }
    }


def test_campaigns_update_dynamic_text_network_budget_type_weekly_payload():
    """#365: BudgetType WEEKLY_BUDGET nulls CustomPeriodBudget."""
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "1001",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--dyn-network-weekly-spend-limit",
        "300",
        "--dyn-network-budget-type",
        "WEEKLY_BUDGET",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
        "WbMaximumClicks": {
            "WeeklySpendLimit": 300000000,
            "CustomPeriodBudget": None,
            "BudgetType": "WEEKLY_BUDGET",
        },
    }


def test_campaigns_update_dynamic_text_network_budget_type_custom_period_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "1002",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPC",
        "--dyn-network-average-cpc",
        "5",
        "--dyn-network-custom-period-spend-limit",
        "1000",
        "--dyn-network-custom-period-start-date",
        "2026-07-01",
        "--dyn-network-custom-period-end-date",
        "2026-07-31",
        "--dyn-network-custom-period-auto-continue",
        "YES",
        "--dyn-network-budget-type",
        "CUSTOM_PERIOD_BUDGET",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPC",
        "AverageCpc": {
            "AverageCpc": 5000000,
            "CustomPeriodBudget": {
                "SpendLimit": 1000000000,
                "StartDate": "2026-07-01",
                "EndDate": "2026-07-31",
                "AutoContinue": "YES",
            },
            "WeeklySpendLimit": None,
            "BudgetType": "CUSTOM_PERIOD_BUDGET",
        },
    }


def test_campaigns_update_dynamic_text_network_rejects_budget_type_without_weekly():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "1003",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--dyn-network-budget-type",
        "WEEKLY_BUDGET",
    )
    assert "--dyn-network-budget-type WEEKLY_BUDGET requires" in result.output


def test_campaigns_update_dynamic_text_network_rejects_partial_strategy():
    """#365: partial update with only --network-strategy still must emit a block."""
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "2001",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "SERVING_OFF",
    )
    dyn = body["params"]["Campaigns"][0]["DynamicTextCampaign"]
    assert dyn["BiddingStrategy"]["Network"] == {"BiddingStrategyType": "SERVING_OFF"}


def test_campaigns_update_dynamic_text_network_default_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "2002",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "NETWORK_DEFAULT",
        "--dyn-network-limit-percent",
        "50",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "NETWORK_DEFAULT",
        "NetworkDefault": {"LimitPercent": 50},
    }


def test_campaigns_update_dynamic_text_network_wb_maximum_clicks_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "2003",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--dyn-network-weekly-spend-limit",
        "700",
        "--dyn-network-bid-ceiling",
        "20",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
        "WbMaximumClicks": {
            "WeeklySpendLimit": 700000000,
            "BidCeiling": 20000000,
        },
    }


def test_campaigns_update_dynamic_text_network_wb_maximum_conversion_rate_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "2004",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--dyn-network-goal-id",
        "111",
        "--dyn-network-weekly-spend-limit",
        "1200",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WB_MAXIMUM_CONVERSION_RATE",
        "WbMaximumConversionRate": {
            "GoalId": 111,
            "WeeklySpendLimit": 1200000000,
        },
    }


def test_campaigns_update_dynamic_text_network_average_cpa_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "2005",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPA",
        "--dyn-network-average-cpa",
        "180",
        "--dyn-network-goal-id",
        "22",
        "--dyn-network-bid-ceiling",
        "15",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPA",
        "AverageCpa": {
            "AverageCpa": 180000000,
            "GoalId": 22,
            "BidCeiling": 15000000,
        },
    }


def test_campaigns_update_dynamic_text_network_pay_for_conversion_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "2006",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "PAY_FOR_CONVERSION",
        "--dyn-network-cpa",
        "250",
        "--dyn-network-goal-id",
        "33",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION",
        "PayForConversion": {
            "Cpa": 250000000,
            "GoalId": 33,
        },
    }


def test_campaigns_update_dynamic_text_network_average_roi_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "2007",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_ROI",
        "--dyn-network-reserve-return",
        "40",
        "--dyn-network-roi-coef",
        "120",
        "--dyn-network-goal-id",
        "44",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_ROI",
        "AverageRoi": {
            "ReserveReturn": 40,
            "RoiCoef": 120,
            "GoalId": 44,
        },
    }


def test_campaigns_update_dynamic_text_network_average_crr_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "2008",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CRR",
        "--dyn-network-crr",
        "20",
        "--dyn-network-goal-id",
        "55",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CRR",
        "AverageCrr": {
            "Crr": 20,
            "GoalId": 55,
        },
    }


def test_campaigns_update_dynamic_text_network_pay_for_conversion_crr_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "2009",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--dyn-network-crr",
        "15",
        "--dyn-network-goal-id",
        "66",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_CRR",
        "PayForConversionCrr": {
            "Crr": 15,
            "GoalId": 66,
        },
    }


def test_campaigns_update_dynamic_text_network_weekly_click_package_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "2010",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "WEEKLY_CLICK_PACKAGE",
        "--dyn-network-clicks-per-week",
        "350",
        "--dyn-network-bid-ceiling",
        "8",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WEEKLY_CLICK_PACKAGE",
        "WeeklyClickPackage": {
            "ClicksPerWeek": 350,
            "BidCeiling": 8000000,
        },
    }


def test_campaigns_update_dynamic_text_network_maximum_coverage_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "2011",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "MAXIMUM_COVERAGE",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {"BiddingStrategyType": "MAXIMUM_COVERAGE"}


def test_campaigns_add_dynamic_text_network_wb_maximum_clicks_bare_payload():
    """#365: WSDL StrategyMaximumClicksAdd has only minOccurs=0 fields.

    WeeklySpendLimit/BidCeiling/CustomPeriodBudget are all optional
    per the cached WSDL (StrategyWeeklyBudgetAddBase line 1333). The
    bare ``--network-strategy WB_MAXIMUM_CLICKS`` add request must
    therefore round-trip with no nested block.
    """
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net WbClicks Bare",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {"BiddingStrategyType": "WB_MAXIMUM_CLICKS"}


def test_campaigns_add_dynamic_text_network_wb_maximum_conversion_rate_only_goal_payload():
    """#365: only GoalId is WSDL-required for WbMaximumConversionRate."""
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net WbConv MinGoal",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--dyn-network-goal-id",
        "9",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WB_MAXIMUM_CONVERSION_RATE",
        "WbMaximumConversionRate": {"GoalId": 9},
    }


def test_campaigns_add_dynamic_text_network_rejects_reserve_return_over_100():
    """#365: --dyn-network-reserve-return is constrained to 0..100."""
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Dyn Roi Bad Reserve",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_ROI",
        "--dyn-network-reserve-return",
        "150",
        "--dyn-network-roi-coef",
        "1",
        "--dyn-network-goal-id",
        "1",
    )
    assert "Invalid value for '--dyn-network-reserve-return'" in result.output


def test_campaigns_add_dynamic_text_network_rejects_wb_maximum_conversion_rate_without_goal():
    """#365: WSDL minOccurs=1 GoalId on WbMaximumConversionRate is enforced."""
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Dyn WbConv Missing Goal",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--dyn-network-weekly-spend-limit",
        "1000",
    )
    assert "WB_MAXIMUM_CONVERSION_RATE requires --dyn-network-goal-id" in result.output


def test_campaigns_add_dynamic_text_network_rejects_dyn_flag_for_text_campaign():
    """#365: --dyn-network-* must be DynamicText-only (silent-data-loss gate)."""
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Text Bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "TEXT_CAMPAIGN",
        "--dyn-network-limit-percent",
        "30",
    )
    assert (
        "--dyn-network-limit-percent is not compatible with --type TEXT_CAMPAIGN"
        in result.output
    )


def test_campaigns_add_dynamic_text_network_rejects_invalid_enum_value():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Dyn Bad Enum",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "NOT_A_REAL_STRATEGY",
    )
    assert (
        "--network-strategy for DYNAMIC_TEXT_CAMPAIGN must be one of" in result.output
    )


def test_campaigns_add_dynamic_text_network_rejects_package_with_network_flag():
    """#365: PackageBiddingStrategy must not coexist with --dyn-network-*."""
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Dyn Pkg + Net",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--package-strategy-id",
        "111",
        "--dyn-network-limit-percent",
        "20",
    )
    assert "DynamicTextCampaign.PackageBiddingStrategy cannot be combined with" in (
        result.output
    )
    assert "--dyn-network-limit-percent" in result.output


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
# campaigns add/update: TextCampaign.BiddingStrategy.Search subtypes
# Issue #361 — typed flags for all 12 strategy families.
# WSDL: tests/wsdl_cache/campaigns.xml TextCampaignStrategyAddBase
# (lines 1581-1608) + Strategy*Add types (lines 1333-1509).
# ----------------------------------------------------------------------


def _text_search_extract(body: dict) -> dict:
    return body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"]["Search"]


def _text_search_update(*extra: str) -> dict:
    return _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "TEXT_CAMPAIGN",
        *extra,
    )


def test_campaigns_add_text_search_wb_maximum_clicks_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--text-search-weekly-spend-limit",
        "300",
        "--bid-ceiling",
        "5000000",
    )
    search = _text_search_extract(body)
    assert search["BiddingStrategyType"] == "WB_MAXIMUM_CLICKS"
    assert search["WbMaximumClicks"] == {
        "WeeklySpendLimit": 300000000,
        "BidCeiling": 5000000,
    }


def test_campaigns_add_text_search_wb_maximum_conversion_rate_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--goal-id",
        "555",
        "--text-search-weekly-spend-limit",
        "200",
    )
    search = _text_search_extract(body)
    assert search["BiddingStrategyType"] == "WB_MAXIMUM_CONVERSION_RATE"
    assert search["WbMaximumConversionRate"] == {
        "GoalId": 555,
        "WeeklySpendLimit": 200000000,
    }


def test_campaigns_add_text_search_wb_maximum_conversion_rate_requires_goal_id():
    """StrategyMaximumConversionRateAdd.GoalId is WSDL minOccurs=1."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--text-search-weekly-spend-limit",
        "100",
    )
    assert "--goal-id" in result.output
    assert "WbMaximumConversionRate" in result.output


def test_campaigns_add_text_search_wb_maximum_clicks_requires_weekly_spend_limit():
    """Yandex docs: WeeklySpendLimit is required for WB_MAXIMUM_CLICKS."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
    )
    assert "--text-search-weekly-spend-limit" in result.output


def test_campaigns_add_text_search_wb_max_conv_rate_requires_weekly_spend_limit():
    """Yandex docs: WeeklySpendLimit is required for WB_MAXIMUM_CONVERSION_RATE."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--goal-id",
        "1",
    )
    assert "--text-search-weekly-spend-limit" in result.output


def test_campaigns_add_text_search_wb_max_clicks_with_custom_period_payload():
    """CustomPeriodBudget satisfies the WeeklySpendLimit requirement
    for WB_MAXIMUM_CLICKS on add, per Yandex docs (alternate budget
    slice)."""
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--text-search-custom-period-spend-limit",
        "300",
        "--text-search-custom-period-start-date",
        "2026-07-01",
        "--text-search-custom-period-end-date",
        "2026-07-31",
        "--text-search-custom-period-auto-continue",
        "NO",
    )
    search = _text_search_extract(body)
    assert search["WbMaximumClicks"] == {
        "CustomPeriodBudget": {
            "SpendLimit": 300000000,
            "StartDate": "2026-07-01",
            "EndDate": "2026-07-31",
            "AutoContinue": "NO",
        }
    }


def test_campaigns_add_text_search_wb_max_conv_rate_custom_period_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--goal-id",
        "42",
        "--text-search-custom-period-spend-limit",
        "200",
        "--text-search-custom-period-start-date",
        "2026-09-01",
        "--text-search-custom-period-end-date",
        "2026-09-30",
        "--text-search-custom-period-auto-continue",
        "YES",
    )
    search = _text_search_extract(body)
    assert search["WbMaximumConversionRate"] == {
        "GoalId": 42,
        "CustomPeriodBudget": {
            "SpendLimit": 200000000,
            "StartDate": "2026-09-01",
            "EndDate": "2026-09-30",
            "AutoContinue": "YES",
        },
    }


def test_campaigns_add_text_search_average_cpc_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPC",
        "--text-search-average-cpc",
        "12",
        "--text-search-weekly-spend-limit",
        "1000",
    )
    search = _text_search_extract(body)
    assert search["BiddingStrategyType"] == "AVERAGE_CPC"
    assert search["AverageCpc"] == {
        "AverageCpc": 12000000,
        "WeeklySpendLimit": 1000000000,
    }


def test_campaigns_add_text_search_average_cpc_requires_average_cpc():
    """StrategyAverageCpcAdd.AverageCpc is WSDL minOccurs=1."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPC",
    )
    assert "--text-search-average-cpc" in result.output


def test_campaigns_add_text_search_pay_for_conversion_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "PAY_FOR_CONVERSION",
        "--text-search-pay-cpa",
        "150",
        "--goal-id",
        "777",
    )
    search = _text_search_extract(body)
    assert search["BiddingStrategyType"] == "PAY_FOR_CONVERSION"
    assert search["PayForConversion"] == {"Cpa": 150000000, "GoalId": 777}


def test_campaigns_add_text_search_pay_for_conversion_requires_cpa_and_goal_id():
    """StrategyPayForConversionAdd: Cpa + GoalId both minOccurs=1."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "PAY_FOR_CONVERSION",
    )
    out = result.output
    assert "--text-search-pay-cpa" in out and "--goal-id" in out


def test_campaigns_add_text_search_weekly_click_package_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "WEEKLY_CLICK_PACKAGE",
        "--text-search-clicks-per-week",
        "1000",
        "--text-search-average-cpc",
        "5",
    )
    search = _text_search_extract(body)
    assert search["BiddingStrategyType"] == "WEEKLY_CLICK_PACKAGE"
    assert search["WeeklyClickPackage"] == {
        "ClicksPerWeek": 1000,
        "AverageCpc": 5000000,
    }


def test_campaigns_add_text_search_weekly_click_package_requires_clicks_per_week():
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "WEEKLY_CLICK_PACKAGE",
    )
    assert "--text-search-clicks-per-week" in result.output


def test_campaigns_add_text_search_weekly_click_package_rejects_cpc_with_bid_ceiling():
    """WEEKLY_CLICK_PACKAGE cannot combine AverageCpc with BidCeiling."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "WEEKLY_CLICK_PACKAGE",
        "--text-search-clicks-per-week",
        "100",
        "--text-search-average-cpc",
        "10",
        "--bid-ceiling",
        "500000",
    )
    assert "WEEKLY_CLICK_PACKAGE" in result.output


def test_campaigns_add_text_search_average_roi_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_ROI",
        "--text-search-reserve-return",
        "30",
        "--text-search-roi-coef",
        "1",
        "--goal-id",
        "42",
        "--text-search-weekly-spend-limit",
        "500",
        "--text-search-profitability",
        "20",
    )
    search = _text_search_extract(body)
    assert search["BiddingStrategyType"] == "AVERAGE_ROI"
    # RoiCoef and Profitability are percent × 1,000,000 per Yandex docs.
    assert search["AverageRoi"] == {
        "ReserveReturn": 30,
        "RoiCoef": 1000000,
        "GoalId": 42,
        "Profitability": 20000000,
        "WeeklySpendLimit": 500000000,
    }


def test_campaigns_add_text_search_average_roi_rejects_non_decimal_reserve_return():
    """Yandex docs: ReserveReturn must be a multiple of 10."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_ROI",
        "--text-search-reserve-return",
        "37",
        "--text-search-roi-coef",
        "100",
        "--goal-id",
        "1",
    )
    assert "--text-search-reserve-return" in result.output
    assert "multiple of 10" in result.output


def test_campaigns_add_text_search_average_roi_accepts_zero_reserve_return():
    """ReserveReturn=0 is a documented valid value."""
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_ROI",
        "--text-search-reserve-return",
        "0",
        "--text-search-roi-coef",
        "1",
        "--goal-id",
        "1",
    )
    search = _text_search_extract(body)
    assert search["AverageRoi"]["ReserveReturn"] == 0
    assert search["AverageRoi"]["RoiCoef"] == 1000000


def test_campaigns_add_text_search_average_roi_requires_reserve_return_and_roi():
    """StrategyAverageRoiAdd: ReserveReturn + RoiCoef + GoalId minOccurs=1."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_ROI",
    )
    out = result.output
    assert "--text-search-reserve-return" in out
    assert "--text-search-roi-coef" in out
    assert "--goal-id" in out


def test_campaigns_add_text_search_average_crr_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CRR",
        "--crr",
        "12",
        "--goal-id",
        "100",
        "--text-search-weekly-spend-limit",
        "400",
    )
    search = _text_search_extract(body)
    assert search["BiddingStrategyType"] == "AVERAGE_CRR"
    assert search["AverageCrr"] == {
        "Crr": 12,
        "GoalId": 100,
        "WeeklySpendLimit": 400000000,
    }


def test_campaigns_add_text_search_average_crr_requires_crr_and_goal_id():
    """StrategyAverageCrrAdd: Crr + GoalId minOccurs=1."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CRR",
    )
    out = result.output
    assert "--crr" in out and "--goal-id" in out


def test_campaigns_add_text_search_max_profit_payload():
    """MAX_PROFIT requires PriorityGoals per Yandex docs even though
    StrategyMaxProfitAdd has no minOccurs=1 WSDL fields."""
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "MAX_PROFIT",
        "--priority-goals",
        "1:500",
        "--text-search-weekly-spend-limit",
        "1000",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text["PriorityGoals"] == {"Items": [{"GoalId": 1, "Value": 500}]}
    search = text["BiddingStrategy"]["Search"]
    assert search["BiddingStrategyType"] == "MAX_PROFIT"
    assert search["MaxProfit"] == {"WeeklySpendLimit": 1000000000}


def test_campaigns_add_text_search_max_profit_rejects_without_priority_goals():
    """Yandex docs: MAX_PROFIT must be combined with PriorityGoals."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "MAX_PROFIT",
    )
    assert "--priority-goals" in result.output
    assert "MaxProfit" in result.output


def test_campaigns_add_text_search_average_cpa_multiple_goals_with_exploration():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--priority-goals",
        "111:60,222:40",
        "--bid-ceiling",
        "200000000",
        "--text-search-exploration-min-budget",
        "50",
        "--text-search-exploration-is-custom",
        "YES",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text["PriorityGoals"] == {
        "Items": [
            {"GoalId": 111, "Value": 60},
            {"GoalId": 222, "Value": 40},
        ]
    }
    search = text["BiddingStrategy"]["Search"]
    assert search["BiddingStrategyType"] == "AVERAGE_CPA_MULTIPLE_GOALS"
    assert search["AverageCpaMultipleGoals"] == {
        "BidCeiling": 200000000,
        "ExplorationBudget": {
            "MinimumExplorationBudget": 50000000,
            "IsMinimumExplorationBudgetCustom": "YES",
        },
    }


def test_campaigns_add_text_search_average_cpa_multi_goals_requires_two_items():
    """Per docs *_MULTIPLE_GOALS strategies require ≥2 priority goals."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--priority-goals",
        "111:100",
    )
    assert "at least 2" in result.output


def test_campaigns_add_text_search_pay_conv_multi_goals_requires_two_items():
    """Per docs PAY_FOR_CONVERSION_MULTIPLE_GOALS requires ≥2 priority goals."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "PAY_FOR_CONVERSION_MULTIPLE_GOALS",
        "--priority-goals",
        "111:100",
    )
    assert "at least 2" in result.output


def test_campaigns_add_text_search_pay_for_conversion_multiple_goals_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "PAY_FOR_CONVERSION_MULTIPLE_GOALS",
        "--priority-goals",
        "1:50,2:50",
        "--text-search-weekly-spend-limit",
        "700",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text["PriorityGoals"] == {
        "Items": [
            {"GoalId": 1, "Value": 50},
            {"GoalId": 2, "Value": 50},
        ]
    }
    search = text["BiddingStrategy"]["Search"]
    assert search["PayForConversionMultipleGoals"] == {
        "WeeklySpendLimit": 700000000,
    }


def test_campaigns_add_text_search_custom_period_budget_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPC",
        "--text-search-average-cpc",
        "10",
        "--text-search-custom-period-spend-limit",
        "500",
        "--text-search-custom-period-start-date",
        "2026-07-01",
        "--text-search-custom-period-end-date",
        "2026-07-31",
        "--text-search-custom-period-auto-continue",
        "NO",
    )
    search = _text_search_extract(body)
    assert search["AverageCpc"] == {
        "AverageCpc": 10000000,
        "CustomPeriodBudget": {
            "SpendLimit": 500000000,
            "StartDate": "2026-07-01",
            "EndDate": "2026-07-31",
            "AutoContinue": "NO",
        },
    }


def test_campaigns_add_text_search_custom_period_partial_rejected():
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPC",
        "--text-search-average-cpc",
        "10",
        "--text-search-custom-period-spend-limit",
        "500",
        "--text-search-custom-period-start-date",
        "2026-07-01",
    )
    assert "CustomPeriodBudget" in result.output


def test_campaigns_add_text_search_custom_period_weekly_conflict_rejected():
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPC",
        "--text-search-average-cpc",
        "10",
        "--text-search-weekly-spend-limit",
        "100",
        "--text-search-custom-period-spend-limit",
        "500",
        "--text-search-custom-period-start-date",
        "2026-07-01",
        "--text-search-custom-period-end-date",
        "2026-07-31",
        "--text-search-custom-period-auto-continue",
        "NO",
    )
    assert "weekly-spend-limit" in result.output


def test_campaigns_add_text_search_exploration_partial_rejected():
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPA",
        "--average-cpa",
        "100000000",
        "--goal-id",
        "1",
        "--text-search-exploration-min-budget",
        "50",
    )
    assert "ExplorationBudget" in result.output


def test_campaigns_add_text_search_exploration_is_custom_no_rejected():
    """Yandex docs: IsMinimumExplorationBudgetCustom=NO makes the API error."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPA",
        "--average-cpa",
        "100000000",
        "--goal-id",
        "1",
        "--text-search-exploration-min-budget",
        "50",
        "--text-search-exploration-is-custom",
        "NO",
    )
    assert "IsMinimumExplorationBudgetCustom" in result.output
    assert "YES" in result.output


def test_campaigns_add_text_search_silent_data_loss_invariant():
    """text-search-* flag attached to an unsupported subtype must raise."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPC",
        "--text-search-average-cpc",
        "10",
        "--text-search-reserve-return",
        "30",
    )
    assert "--text-search-reserve-return" in result.output
    assert "AverageCpc" in result.output


def test_campaigns_add_text_search_budget_type_add_only_rejected():
    """--text-search-budget-type is update-only per WSDL Strategy*Add."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPC",
        "--text-search-average-cpc",
        "10",
        "--text-search-budget-type",
        "WEEKLY_BUDGET",
    )
    assert "--text-search-budget-type" in result.output


def test_campaigns_update_text_search_average_cpa_payload():
    body = _text_search_update(
        "--search-strategy",
        "AVERAGE_CPA",
        "--average-cpa",
        "100000000",
        "--goal-id",
        "9",
        "--bid-ceiling",
        "500000000",
    )
    search = _text_search_extract(body)
    assert search["BiddingStrategyType"] == "AVERAGE_CPA"
    assert search["AverageCpa"] == {
        "AverageCpa": 100000000,
        "GoalId": 9,
        "BidCeiling": 500000000,
    }


def test_campaigns_update_text_search_pay_for_conversion_payload():
    body = _text_search_update(
        "--search-strategy",
        "PAY_FOR_CONVERSION",
        "--text-search-pay-cpa",
        "200",
        "--goal-id",
        "11",
        "--text-search-weekly-spend-limit",
        "1500",
    )
    search = _text_search_extract(body)
    assert search["BiddingStrategyType"] == "PAY_FOR_CONVERSION"
    assert search["PayForConversion"] == {
        "Cpa": 200000000,
        "GoalId": 11,
        "WeeklySpendLimit": 1500000000,
    }


def test_campaigns_update_text_search_budget_type_switch_payload():
    """Update-only BudgetType switch from WEEKLY_BUDGET → CUSTOM_PERIOD_BUDGET."""
    body = _text_search_update(
        "--search-strategy",
        "AVERAGE_CPC",
        "--text-search-average-cpc",
        "8",
        "--text-search-custom-period-spend-limit",
        "1200",
        "--text-search-custom-period-start-date",
        "2026-08-01",
        "--text-search-custom-period-end-date",
        "2026-08-31",
        "--text-search-custom-period-auto-continue",
        "YES",
        "--text-search-budget-type",
        "CUSTOM_PERIOD_BUDGET",
    )
    search = _text_search_extract(body)
    assert search["BiddingStrategyType"] == "AVERAGE_CPC"
    assert search["AverageCpc"] == {
        "AverageCpc": 8000000,
        "WeeklySpendLimit": None,
        "CustomPeriodBudget": {
            "SpendLimit": 1200000000,
            "StartDate": "2026-08-01",
            "EndDate": "2026-08-31",
            "AutoContinue": "YES",
        },
        "BudgetType": "CUSTOM_PERIOD_BUDGET",
    }


def test_campaigns_update_text_search_max_profit_with_weekly_spend_payload():
    """Switching to MAX_PROFIT on update requires --priority-goals per docs;
    additional optional fields land in the subtype block."""
    body = _text_search_update(
        "--search-strategy",
        "MAX_PROFIT",
        "--priority-goals",
        "9:1000",
        "--text-search-weekly-spend-limit",
        "999",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text["PriorityGoals"] == {
        "Items": [{"GoalId": 9, "Value": 1000, "Operation": "SET"}]
    }
    search = text["BiddingStrategy"]["Search"]
    assert search["MaxProfit"] == {"WeeklySpendLimit": 999000000}


def test_campaigns_update_text_search_max_profit_requires_priority_goals():
    """Switching --search-strategy MAX_PROFIT on update without
    --priority-goals is rejected per the Yandex docs."""
    result = CliRunner().invoke(
        cli,
        [
            "campaigns",
            "update",
            "--id",
            "123",
            "--type",
            "TEXT_CAMPAIGN",
            "--search-strategy",
            "MAX_PROFIT",
            "--text-search-weekly-spend-limit",
            "999",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "--priority-goals" in result.output
    assert "MaxProfit" in result.output


def test_campaigns_update_text_search_average_roi_payload():
    """Switching to AVERAGE_ROI on update requires all
    minOccurs=1 fields per Yandex docs (ReserveReturn + RoiCoef +
    GoalId); additional optional fields land in the subtype block.
    RoiCoef and Profitability are percent × 1,000,000 on the wire."""
    body = _text_search_update(
        "--search-strategy",
        "AVERAGE_ROI",
        "--text-search-reserve-return",
        "20",
        "--text-search-roi-coef",
        "1",
        "--goal-id",
        "42",
        "--text-search-profitability",
        "25",
    )
    search = _text_search_extract(body)
    assert search["AverageRoi"] == {
        "ReserveReturn": 20,
        "RoiCoef": 1000000,
        "GoalId": 42,
        "Profitability": 25000000,
    }


def test_campaigns_update_text_search_average_roi_rejects_partial():
    """Switching --search-strategy AVERAGE_ROI without RoiCoef/GoalId/
    ReserveReturn is a documented invalid update — CLI must reject."""
    result = CliRunner().invoke(
        cli,
        [
            "campaigns",
            "update",
            "--id",
            "123",
            "--type",
            "TEXT_CAMPAIGN",
            "--search-strategy",
            "AVERAGE_ROI",
            "--text-search-profitability",
            "25",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "--text-search-reserve-return" in result.output
    assert "--text-search-roi-coef" in result.output
    assert "--goal-id" in result.output


def test_campaigns_update_text_search_priority_goals_independent_of_strategy():
    """PriorityGoalsUpdateSetting on update is independent of BiddingStrategy."""
    body = _text_search_update(
        "--priority-goals",
        "1:80,2:20",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    # On update PriorityGoals uses the UpdateSetting shape (with
    # Operation=SET, see _priority_goals_update_items).
    assert text["PriorityGoals"] == {
        "Items": [
            {"GoalId": 1, "Value": 80, "Operation": "SET"},
            {"GoalId": 2, "Value": 20, "Operation": "SET"},
        ]
    }
    # And no BiddingStrategy is emitted, matching legacy behavior.
    assert "BiddingStrategy" not in text


def test_campaigns_update_text_search_detail_without_strategy_rejected():
    result = CliRunner().invoke(
        cli,
        [
            "campaigns",
            "update",
            "--id",
            "123",
            "--type",
            "TEXT_CAMPAIGN",
            "--text-search-weekly-spend-limit",
            "100",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "--search-strategy" in result.output


def test_campaigns_update_text_search_average_cpc_payload():
    body = _text_search_update(
        "--search-strategy",
        "AVERAGE_CPC",
        "--text-search-average-cpc",
        "9",
        "--text-search-weekly-spend-limit",
        "300",
    )
    search = _text_search_extract(body)
    assert search["AverageCpc"] == {
        "AverageCpc": 9000000,
        "WeeklySpendLimit": 300000000,
    }


def test_campaigns_update_text_search_average_crr_payload():
    body = _text_search_update(
        "--search-strategy",
        "AVERAGE_CRR",
        "--crr",
        "15",
        "--goal-id",
        "5",
    )
    search = _text_search_extract(body)
    assert search["AverageCrr"] == {"Crr": 15, "GoalId": 5}


def test_campaigns_update_text_search_average_crr_rejects_partial():
    """Switching --search-strategy AVERAGE_CRR without Crr/GoalId is
    a documented invalid update — CLI must reject."""
    result = CliRunner().invoke(
        cli,
        [
            "campaigns",
            "update",
            "--id",
            "123",
            "--type",
            "TEXT_CAMPAIGN",
            "--search-strategy",
            "AVERAGE_CRR",
            "--text-search-weekly-spend-limit",
            "100",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "--crr" in result.output
    assert "--goal-id" in result.output


def test_campaigns_update_text_search_pay_for_conversion_crr_payload():
    body = _text_search_update(
        "--search-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--crr",
        "10",
        "--goal-id",
        "3",
    )
    search = _text_search_extract(body)
    assert search["PayForConversionCrr"] == {"Crr": 10, "GoalId": 3}


def test_campaigns_update_text_search_pay_conv_crr_rejects_partial():
    """Switching --search-strategy PAY_FOR_CONVERSION_CRR without
    Crr/GoalId is a documented invalid update — CLI must reject."""
    result = CliRunner().invoke(
        cli,
        [
            "campaigns",
            "update",
            "--id",
            "123",
            "--type",
            "TEXT_CAMPAIGN",
            "--search-strategy",
            "PAY_FOR_CONVERSION_CRR",
            "--text-search-weekly-spend-limit",
            "100",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "--crr" in result.output
    assert "--goal-id" in result.output


def test_campaigns_update_text_search_weekly_click_package_payload():
    body = _text_search_update(
        "--search-strategy",
        "WEEKLY_CLICK_PACKAGE",
        "--text-search-clicks-per-week",
        "1500",
        "--text-search-average-cpc",
        "4",
    )
    search = _text_search_extract(body)
    assert search["WeeklyClickPackage"] == {
        "ClicksPerWeek": 1500,
        "AverageCpc": 4000000,
    }


def test_campaigns_update_text_search_average_cpa_multiple_goals_payload():
    body = _text_search_update(
        "--search-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--priority-goals",
        "100:60,200:40",
        "--bid-ceiling",
        "5000000",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    # On update PriorityGoals uses the UpdateSetting shape; the
    # BiddingStrategy carries the subtype container.
    assert text["PriorityGoals"] == {
        "Items": [
            {"GoalId": 100, "Value": 60, "Operation": "SET"},
            {"GoalId": 200, "Value": 40, "Operation": "SET"},
        ]
    }
    search = text["BiddingStrategy"]["Search"]
    assert search["AverageCpaMultipleGoals"] == {"BidCeiling": 5000000}


def test_campaigns_update_text_search_pay_for_conversion_multiple_goals_payload():
    body = _text_search_update(
        "--search-strategy",
        "PAY_FOR_CONVERSION_MULTIPLE_GOALS",
        "--priority-goals",
        "1:60,2:40",
        "--text-search-weekly-spend-limit",
        "800",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text["PriorityGoals"] == {
        "Items": [
            {"GoalId": 1, "Value": 60, "Operation": "SET"},
            {"GoalId": 2, "Value": 40, "Operation": "SET"},
        ]
    }
    search = text["BiddingStrategy"]["Search"]
    assert search["PayForConversionMultipleGoals"] == {
        "WeeklySpendLimit": 800000000,
    }


def test_campaigns_update_text_search_max_profit_with_priority_goals_payload():
    body = _text_search_update(
        "--search-strategy",
        "MAX_PROFIT",
        "--priority-goals",
        "9:1000",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text["PriorityGoals"] == {
        "Items": [{"GoalId": 9, "Value": 1000, "Operation": "SET"}]
    }
    search = text["BiddingStrategy"]["Search"]
    assert search["MaxProfit"] == {}


def test_campaigns_update_text_search_wb_maximum_clicks_partial_payload():
    """Update WSDL ``StrategyMaximumClicks`` declares every field as
    minOccurs=0, so patching only ``BidCeiling`` on a WB_MAXIMUM_CLICKS
    campaign must succeed."""
    body = _text_search_update(
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--bid-ceiling",
        "750000",
    )
    search = _text_search_extract(body)
    assert search["BiddingStrategyType"] == "WB_MAXIMUM_CLICKS"
    assert search["WbMaximumClicks"] == {"BidCeiling": 750000}


def test_campaigns_update_text_search_wb_max_conv_rate_partial_payload():
    """Update path treats every ``StrategyMaximumConversionRate`` field
    as optional EXCEPT the docs-required ``GoalId`` on strategy switch."""
    body = _text_search_update(
        "--search-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--goal-id",
        "42",
        "--bid-ceiling",
        "400000",
    )
    search = _text_search_extract(body)
    assert search["WbMaximumConversionRate"] == {
        "GoalId": 42,
        "BidCeiling": 400000,
    }


def test_campaigns_update_text_search_wb_maximum_clicks_rejects_budget_type():
    """Yandex update docs: WbMaximumClicks does not declare BudgetType."""
    result = CliRunner().invoke(
        cli,
        [
            "campaigns",
            "update",
            "--id",
            "123",
            "--type",
            "TEXT_CAMPAIGN",
            "--search-strategy",
            "WB_MAXIMUM_CLICKS",
            "--text-search-weekly-spend-limit",
            "400",
            "--text-search-budget-type",
            "WEEKLY_BUDGET",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "--text-search-budget-type" in result.output
    assert "WbMaximumClicks" in result.output


def test_campaigns_update_text_search_wb_max_conv_rate_rejects_budget_type():
    """Yandex update docs: WbMaximumConversionRate does not declare BudgetType."""
    result = CliRunner().invoke(
        cli,
        [
            "campaigns",
            "update",
            "--id",
            "123",
            "--type",
            "TEXT_CAMPAIGN",
            "--search-strategy",
            "WB_MAXIMUM_CONVERSION_RATE",
            "--goal-id",
            "8",
            "--text-search-weekly-spend-limit",
            "250",
            "--text-search-budget-type",
            "WEEKLY_BUDGET",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "--text-search-budget-type" in result.output


def test_campaigns_add_text_network_strategy_without_detail_flags_payload():
    """``--network-strategy AVERAGE_CPA`` without typed CPA flags must
    serialize Network as ``{BiddingStrategyType: AVERAGE_CPA}`` (matches
    pre-#361 behavior — the legacy network-side subtype block is
    intentionally not built because ``_NETWORK_STRATEGY_TO_WSDL_SUBTYPE``
    is empty until #290 wires Network branches)."""
    body = _dry_run(
        *_cpa_base_args(),
        "--network-strategy",
        "AVERAGE_CPA",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {"BiddingStrategyType": "AVERAGE_CPA"}


def test_campaigns_add_text_network_cpa_with_detail_flags_rejected():
    """``--network-strategy AVERAGE_CPA --average-cpa ...`` must be
    rejected: the Network-side CPA flag path is not in #361 scope, so
    typed CPA flags only apply to Search subtypes."""
    result = _rejected(
        *_cpa_base_args(),
        "--network-strategy",
        "AVERAGE_CPA",
        "--average-cpa",
        "100000000",
        "--goal-id",
        "1",
    )
    assert "--average-cpa" in result.output
    assert "CPA-shaped" in result.output


def test_campaigns_update_text_search_average_cpa_multi_goals_rejects_budget_type():
    """Yandex update docs: AverageCpaMultipleGoals does not declare BudgetType."""
    result = CliRunner().invoke(
        cli,
        [
            "campaigns",
            "update",
            "--id",
            "123",
            "--type",
            "TEXT_CAMPAIGN",
            "--search-strategy",
            "AVERAGE_CPA_MULTIPLE_GOALS",
            "--priority-goals",
            "1:60,2:40",
            "--text-search-budget-type",
            "WEEKLY_BUDGET",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "--text-search-budget-type" in result.output


def test_campaigns_add_text_search_rejects_with_package_bidding_strategy():
    """text-search-* flag input must not silently disappear when the user
    opts into PackageBiddingStrategy — the conflict has to surface."""
    result = _rejected(
        *_cpa_base_args(),
        "--package-strategy-id",
        "700",
        "--package-platform-search-result",
        "YES",
        "--package-platform-product-gallery",
        "NO",
        "--package-platform-network",
        "YES",
        "--package-platform-dynamic-places",
        "NO",
        "--text-search-weekly-spend-limit",
        "100",
    )
    assert "PackageBiddingStrategy" in result.output
    assert "--text-search-weekly-spend-limit" in result.output


def test_campaigns_update_text_search_rejects_with_package_bidding_strategy():
    result = CliRunner().invoke(
        cli,
        [
            "campaigns",
            "update",
            "--id",
            "123",
            "--type",
            "TEXT_CAMPAIGN",
            "--package-strategy-id",
            "700",
            "--text-search-weekly-spend-limit",
            "100",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "PackageBiddingStrategy" in result.output
    assert "--text-search-weekly-spend-limit" in result.output


def test_campaigns_update_text_search_rejects_budget_type_with_package_strategy():
    result = CliRunner().invoke(
        cli,
        [
            "campaigns",
            "update",
            "--id",
            "123",
            "--type",
            "TEXT_CAMPAIGN",
            "--package-strategy-id",
            "700",
            "--text-search-budget-type",
            "WEEKLY_BUDGET",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "PackageBiddingStrategy" in result.output
    assert "--text-search-budget-type" in result.output


def test_campaigns_text_search_flags_rejected_for_other_campaign_types():
    """text-search-* flags must NOT be accepted under --type != TEXT_CAMPAIGN."""
    result = CliRunner().invoke(
        cli,
        [
            "campaigns",
            "add",
            "--name",
            "C",
            "--start-date",
            "2026-06-01",
            "--type",
            "DYNAMIC_TEXT_CAMPAIGN",
            "--text-search-weekly-spend-limit",
            "100",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert (
        "DYNAMIC_TEXT_CAMPAIGN" in result.output
        or "--text-search-weekly-spend-limit" in result.output
    )


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


def test_adextensions_get_callout_field_names_payload():
    body = _read_dry_run(
        "adextensions",
        "get",
        "--types",
        "CALLOUT",
        "--fields",
        "Id,Type,State,Status",
        "--callout-field-names",
        "CalloutText",
    )

    assert body["params"]["SelectionCriteria"] == {"Types": ["CALLOUT"]}
    assert body["params"]["FieldNames"] == ["Id", "Type", "State", "Status"]
    assert "CalloutText" not in body["params"]["FieldNames"]
    assert body["params"]["CalloutFieldNames"] == ["CalloutText"]


def test_adextensions_get_help_exposes_callout_field_names():
    result = CliRunner().invoke(cli, ["adextensions", "get", "--help"])

    assert result.exit_code == 0
    assert "--callout-field-names" in result.output


def test_adextensions_get_rejects_empty_callout_field_names():
    result = CliRunner().invoke(
        cli,
        [
            "adextensions",
            "get",
            "--callout-field-names",
            ",",
            "--dry-run",
        ],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )

    assert result.exit_code != 0
    assert (
        "Provide a non-empty comma-separated CalloutFieldNames list." in result.output
    )


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


def test_strategies_add_priority_goal_metrika_source_payload():
    body = _dry_run(
        "strategies",
        "add",
        "--name",
        "CRR Strategy",
        "--type",
        "AverageCrr",
        "--average-crr",
        "10",
        "--goal-id",
        "123",
        "--priority-goal",
        "123:2000000:YES",
        "--priority-goal",
        "456:1000000:no",
    )
    s = body["params"]["Strategies"][0]
    assert s["PriorityGoals"]["Items"] == [
        {
            "GoalId": 123,
            "Value": 2000000,
            "IsMetrikaSourceOfValue": "YES",
        },
        {
            "GoalId": 456,
            "Value": 1000000,
            "IsMetrikaSourceOfValue": "NO",
        },
    ]


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


def test_strategies_update_priority_goal_metrika_source_payload():
    body = _dry_run(
        "strategies",
        "update",
        "--id",
        "77",
        "--priority-goal",
        "123:2000000:YES",
    )
    s = body["params"]["Strategies"][0]
    assert s == {
        "Id": 77,
        "PriorityGoals": {
            "Items": [
                {
                    "GoalId": 123,
                    "Value": 2000000,
                    "IsMetrikaSourceOfValue": "YES",
                }
            ]
        },
    }


def test_strategies_rejects_invalid_priority_goal_metrika_source():
    result = _failing_run(
        "strategies",
        "update",
        "--id",
        "77",
        "--priority-goal",
        "123:2000000:MAYBE",
        "--dry-run",
    )
    assert result.exit_code != 0
    assert "IsMetrikaSourceOfValue must be YES or NO" in result.output


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


def test_strategies_add_custom_period_budget_payload():
    body = _dry_run(
        "strategies",
        "add",
        "--name",
        "Custom Period",
        "--type",
        "WbMaximumClicks",
        "--custom-period-spend-limit",
        "1000000000",
        "--custom-period-start-date",
        "2026-06-01",
        "--custom-period-end-date",
        "2026-06-30",
        "--custom-period-auto-continue",
        "yes",
    )
    s = body["params"]["Strategies"][0]
    assert s["WbMaximumClicks"] == {
        "CustomPeriodBudget": {
            "SpendLimit": 1000000000,
            "StartDate": "2026-06-01",
            "EndDate": "2026-06-30",
            "AutoContinue": "YES",
        }
    }


def test_strategies_update_custom_period_budget_payload():
    body = _dry_run(
        "strategies",
        "update",
        "--id",
        "42",
        "--type",
        "AverageCpc",
        "--custom-period-spend-limit",
        "500000000",
        "--custom-period-start-date",
        "2026-07-01",
        "--custom-period-end-date",
        "2026-07-31",
        "--custom-period-auto-continue",
        "no",
    )
    s = body["params"]["Strategies"][0]
    assert s["Id"] == 42
    assert s["AverageCpc"] == {
        "CustomPeriodBudget": {
            "SpendLimit": 500000000,
            "StartDate": "2026-07-01",
            "EndDate": "2026-07-31",
            "AutoContinue": "NO",
        }
    }


def test_strategies_custom_period_budget_requires_all_fields():
    result = _failing_run(
        "strategies",
        "add",
        "--name",
        "Custom Period",
        "--type",
        "WbMaximumClicks",
        "--custom-period-spend-limit",
        "1000000000",
        "--dry-run",
    )
    assert result.exit_code != 0
    assert "CustomPeriodBudget requires" in result.output
    assert "--custom-period-start-date" in result.output
    assert "--custom-period-end-date" in result.output
    assert "--custom-period-auto-continue" in result.output


def test_strategies_update_custom_period_budget_requires_type():
    result = _failing_run(
        "strategies",
        "update",
        "--id",
        "42",
        "--custom-period-spend-limit",
        "1000000000",
        "--custom-period-start-date",
        "2026-06-01",
        "--custom-period-end-date",
        "2026-06-30",
        "--custom-period-auto-continue",
        "YES",
        "--dry-run",
    )
    assert result.exit_code != 0
    assert "Provide --type when setting strategy-specific fields" in result.output


def test_strategies_update_average_cpa_rejects_custom_period_budget():
    result = _failing_run(
        "strategies",
        "update",
        "--id",
        "42",
        "--type",
        "AverageCpa",
        "--custom-period-spend-limit",
        "1000000000",
        "--custom-period-start-date",
        "2026-06-01",
        "--custom-period-end-date",
        "2026-06-30",
        "--custom-period-auto-continue",
        "YES",
        "--dry-run",
    )
    assert result.exit_code != 0
    assert (
        "--custom-period-* flags are not valid for --type AverageCpa "
        "on strategies update."
    ) in result.output


def test_strategies_custom_period_budget_rejects_weekly_spend_limit():
    result = _failing_run(
        "strategies",
        "add",
        "--name",
        "Custom Period",
        "--type",
        "WbMaximumClicks",
        "--weekly-spend-limit",
        "900000000",
        "--custom-period-spend-limit",
        "1000000000",
        "--custom-period-start-date",
        "2026-06-01",
        "--custom-period-end-date",
        "2026-06-30",
        "--custom-period-auto-continue",
        "YES",
        "--dry-run",
    )
    assert result.exit_code != 0
    assert (
        "--weekly-spend-limit cannot be combined with --custom-period-* flags"
        in result.output
    )


def test_strategies_add_exploration_budget_payload():
    body = _dry_run(
        "strategies",
        "add",
        "--name",
        "Exploration",
        "--type",
        "AverageCpa",
        "--average-cpa",
        "4000000",
        "--goal-id",
        "123",
        "--minimum-exploration-budget",
        "200000000",
    )
    s = body["params"]["Strategies"][0]
    assert s["AverageCpa"]["ExplorationBudget"] == {
        "MinimumExplorationBudget": 200000000,
        "IsMinimumExplorationBudgetCustom": "YES",
    }


def test_strategies_update_exploration_budget_payload_accepts_zero():
    body = _dry_run(
        "strategies",
        "update",
        "--id",
        "42",
        "--type",
        "MaxProfit",
        "--minimum-exploration-budget",
        "0",
    )
    s = body["params"]["Strategies"][0]
    assert s["MaxProfit"] == {
        "ExplorationBudget": {
            "MinimumExplorationBudget": 0,
            "IsMinimumExplorationBudgetCustom": "YES",
        }
    }


def test_strategies_exploration_budget_requires_type():
    result = _failing_run(
        "strategies",
        "update",
        "--id",
        "42",
        "--minimum-exploration-budget",
        "200000000",
        "--dry-run",
    )
    assert result.exit_code != 0
    assert "Provide --type when setting strategy-specific fields" in result.output


def test_strategies_exploration_budget_rejects_unsupported_type():
    result = _failing_run(
        "strategies",
        "update",
        "--id",
        "42",
        "--type",
        "AverageCpc",
        "--minimum-exploration-budget",
        "200000000",
        "--dry-run",
    )
    assert result.exit_code != 0
    assert (
        "--minimum-exploration-budget is not valid for --type AverageCpc."
        in result.output
    )


def test_strategies_exploration_budget_rejects_value_above_weekly_budget():
    result = _failing_run(
        "strategies",
        "add",
        "--name",
        "Exploration",
        "--type",
        "AverageCpa",
        "--average-cpa",
        "4000000",
        "--goal-id",
        "123",
        "--weekly-spend-limit",
        "100000000",
        "--minimum-exploration-budget",
        "200000000",
        "--dry-run",
    )
    assert result.exit_code != 0
    assert (
        "--minimum-exploration-budget must be less than or equal to "
        "--weekly-spend-limit"
    ) in result.output


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


# --- Issue #362: DynamicTextCampaign.BiddingStrategy.Search ---


def test_campaigns_add_dynamic_text_search_legacy_average_cpa_still_works():
    """#362 back-compat: legacy --average-cpa / --goal-id still drive
    DynamicTextCampaign Search AVERAGE_CPA when no --dyn-search-* flag
    is given. Mirrors the pre-#362 behavior of apply_cpa_strategy_fields.
    """
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn legacy CPA",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA",
        "--network-strategy",
        "SERVING_OFF",
        "--average-cpa",
        "200000000",
        "--goal-id",
        "42",
    )
    dyn = body["params"]["Campaigns"][0]["DynamicTextCampaign"]
    search = dyn["BiddingStrategy"]["Search"]
    assert search["BiddingStrategyType"] == "AVERAGE_CPA"
    assert search["AverageCpa"] == {"AverageCpa": 200000000, "GoalId": 42}


def test_campaigns_add_dynamic_text_search_highest_position_payload():
    """#362: HIGHEST_POSITION is the legacy default and accepts no
    Strategy*Add block.
    """
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Search Highest",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "HIGHEST_POSITION",
        "--network-strategy",
        "SERVING_OFF",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {"BiddingStrategyType": "HIGHEST_POSITION"}


def test_campaigns_add_dynamic_text_search_serving_off_payload():
    """#362: SERVING_OFF is enum-only, no Strategy*Add block."""
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Search Off",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "SERVING_OFF",
        "--network-strategy",
        "SERVING_OFF",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {"BiddingStrategyType": "SERVING_OFF"}


def test_campaigns_add_dynamic_text_search_impressions_below_search_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Search Below",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "IMPRESSIONS_BELOW_SEARCH",
        "--network-strategy",
        "SERVING_OFF",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {"BiddingStrategyType": "IMPRESSIONS_BELOW_SEARCH"}


def test_campaigns_add_dynamic_text_search_placement_types_payload():
    """#362: PlacementTypes (SearchResults/ProductGallery/DynamicPlaces)
    serialised as nested dict on the Search block.
    """
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Search Placement",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "HIGHEST_POSITION",
        "--network-strategy",
        "SERVING_OFF",
        "--search-placement-search-results",
        "YES",
        "--search-placement-product-gallery",
        "NO",
        "--search-placement-dynamic-places",
        "YES",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "HIGHEST_POSITION",
        "PlacementTypes": {
            "SearchResults": "YES",
            "ProductGallery": "NO",
            "DynamicPlaces": "YES",
        },
    }


def test_campaigns_add_dynamic_text_search_wb_maximum_clicks_weekly_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Search WbClicks Weekly",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-weekly-spend-limit",
        "1000",
        "--dyn-search-bid-ceiling",
        "100",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
        "WbMaximumClicks": {
            "WeeklySpendLimit": 1000000000,
            "BidCeiling": 100000000,
        },
    }


def test_campaigns_add_dynamic_text_search_wb_maximum_clicks_custom_period_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Search WbClicks CP",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-custom-period-spend-limit",
        "5000",
        "--dyn-search-custom-period-start-date",
        "2026-06-01",
        "--dyn-search-custom-period-end-date",
        "2026-06-30",
        "--dyn-search-custom-period-auto-continue",
        "YES",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
        "WbMaximumClicks": {
            "CustomPeriodBudget": {
                "SpendLimit": 5000000000,
                "StartDate": "2026-06-01",
                "EndDate": "2026-06-30",
                "AutoContinue": "YES",
            },
        },
    }


def test_campaigns_add_dynamic_text_search_wb_maximum_conversion_rate_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Search Wb Conv",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-goal-id",
        "42",
        "--dyn-search-weekly-spend-limit",
        "2000",
        "--dyn-search-bid-ceiling",
        "150",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "WB_MAXIMUM_CONVERSION_RATE",
        "WbMaximumConversionRate": {
            "GoalId": 42,
            "WeeklySpendLimit": 2000000000,
            "BidCeiling": 150000000,
        },
    }


def test_campaigns_add_dynamic_text_search_average_cpc_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Search AvgCpc",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPC",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-average-cpc",
        "8",
        "--dyn-search-weekly-spend-limit",
        "1500",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPC",
        "AverageCpc": {
            "AverageCpc": 8000000,
            "WeeklySpendLimit": 1500000000,
        },
    }


def test_campaigns_add_dynamic_text_search_average_cpa_with_exploration_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Search AvgCpa",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-average-cpa",
        "200",
        "--dyn-search-goal-id",
        "42",
        "--dyn-search-bid-ceiling",
        "50",
        "--dyn-search-exploration-budget",
        "100",
        "--dyn-search-exploration-budget-custom",
        "YES",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPA",
        "AverageCpa": {
            "AverageCpa": 200000000,
            "GoalId": 42,
            "BidCeiling": 50000000,
            "ExplorationBudget": {
                "MinimumExplorationBudget": 100000000,
                "IsMinimumExplorationBudgetCustom": "YES",
            },
        },
    }


def test_campaigns_add_dynamic_text_search_pay_for_conversion_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Search PayConv",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "PAY_FOR_CONVERSION",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-cpa",
        "300",
        "--dyn-search-goal-id",
        "42",
        "--dyn-search-weekly-spend-limit",
        "1000",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION",
        "PayForConversion": {
            "Cpa": 300000000,
            "GoalId": 42,
            "WeeklySpendLimit": 1000000000,
        },
    }


def test_campaigns_add_dynamic_text_search_average_roi_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Search Roi",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_ROI",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-reserve-return",
        "20",
        "--dyn-search-roi-coef",
        "150",
        "--dyn-search-goal-id",
        "42",
        "--dyn-search-profitability",
        "25",
        "--dyn-search-weekly-spend-limit",
        "2000",
        "--dyn-search-bid-ceiling",
        "100",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_ROI",
        "AverageRoi": {
            "ReserveReturn": 20,
            "RoiCoef": 150,
            "GoalId": 42,
            "Profitability": 25,
            "WeeklySpendLimit": 2000000000,
            "BidCeiling": 100000000,
        },
    }


def test_campaigns_add_dynamic_text_search_average_crr_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Search AvgCrr",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CRR",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-crr",
        "10",
        "--dyn-search-goal-id",
        "42",
        "--dyn-search-weekly-spend-limit",
        "1500",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CRR",
        "AverageCrr": {
            "Crr": 10,
            "GoalId": 42,
            "WeeklySpendLimit": 1500000000,
        },
    }


def test_campaigns_add_dynamic_text_search_pay_for_conversion_crr_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Search PayConvCrr",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-crr",
        "15",
        "--dyn-search-goal-id",
        "42",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_CRR",
        "PayForConversionCrr": {
            "Crr": 15,
            "GoalId": 42,
        },
    }


def test_campaigns_add_dynamic_text_search_weekly_click_package_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Search WCP",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "WEEKLY_CLICK_PACKAGE",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-clicks-per-week",
        "100",
        "--dyn-search-bid-ceiling",
        "50",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "WEEKLY_CLICK_PACKAGE",
        "WeeklyClickPackage": {
            "ClicksPerWeek": 100,
            "BidCeiling": 50000000,
        },
    }


def test_campaigns_add_dynamic_text_search_rejects_partial_exploration_budget():
    """#362: ExplorationBudget requires both subfields together."""
    result = _failing_run(
        "campaigns",
        "add",
        "--name",
        "Bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-average-cpa",
        "100",
        "--dyn-search-goal-id",
        "42",
        "--dyn-search-exploration-budget",
        "50",
    )
    assert result.exit_code != 0
    assert "ExplorationBudget" in result.output


def test_campaigns_add_dynamic_text_search_rejects_partial_custom_period():
    """#362: CustomPeriodBudget requires all four subfields together."""
    result = _failing_run(
        "campaigns",
        "add",
        "--name",
        "Bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-custom-period-spend-limit",
        "100",
        "--dyn-search-custom-period-start-date",
        "2026-06-01",
    )
    assert result.exit_code != 0
    assert "CustomPeriodBudget" in result.output


def test_campaigns_add_dynamic_text_search_rejects_weekly_and_custom_period_combo():
    """#362: WeeklySpendLimit and CustomPeriodBudget are mutually exclusive."""
    result = _failing_run(
        "campaigns",
        "add",
        "--name",
        "Bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-weekly-spend-limit",
        "1000",
        "--dyn-search-custom-period-spend-limit",
        "1000",
        "--dyn-search-custom-period-start-date",
        "2026-06-01",
        "--dyn-search-custom-period-end-date",
        "2026-06-30",
        "--dyn-search-custom-period-auto-continue",
        "YES",
    )
    assert result.exit_code != 0
    assert "cannot be combined" in result.output


def test_campaigns_add_dynamic_text_search_rejects_field_for_wrong_subtype():
    """#362: silent-data-loss invariant — typed flag rejected when not
    declared on the chosen Strategy*Add subtype."""
    result = _failing_run(
        "campaigns",
        "add",
        "--name",
        "Bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-average-cpa",
        "100",
        "--dyn-search-goal-id",
        "42",
        "--dyn-search-clicks-per-week",
        "500",
    )
    assert result.exit_code != 0
    assert "does not accept --dyn-search-clicks-per-week" in result.output


def test_campaigns_add_dynamic_text_search_rejects_legacy_flag_combo():
    """#362: combining legacy --average-cpa with --dyn-search-* is blocked."""
    result = _failing_run(
        "campaigns",
        "add",
        "--name",
        "Bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-average-cpa",
        "100",
        "--dyn-search-goal-id",
        "42",
        "--average-cpa",
        "200000000",
    )
    assert result.exit_code != 0
    assert "cannot be combined with the legacy CPA-shape flags" in result.output


def test_campaigns_add_dynamic_text_search_required_average_cpa_when_typed_used():
    """#362: minOccurs=1 enforcement on add path when typed flags engaged."""
    result = _failing_run(
        "campaigns",
        "add",
        "--name",
        "Bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-bid-ceiling",
        "100",
    )
    assert result.exit_code != 0
    assert "AVERAGE_CPA requires" in result.output


def test_campaigns_add_dynamic_text_search_rejects_serving_off_with_details():
    """#362: SERVING_OFF / HIGHEST_POSITION / IMPRESSIONS_BELOW_SEARCH
    do not accept Strategy*Add fields.
    """
    result = _failing_run(
        "campaigns",
        "add",
        "--name",
        "Bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "SERVING_OFF",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-weekly-spend-limit",
        "1000",
    )
    assert result.exit_code != 0
    assert "SERVING_OFF does not accept" in result.output


def test_campaigns_add_dynamic_text_search_rejects_detail_without_search_strategy():
    """#362: --dyn-search-* without --search-strategy raises UsageError."""
    result = _failing_run(
        "campaigns",
        "add",
        "--name",
        "Bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-weekly-spend-limit",
        "1000",
    )
    assert result.exit_code != 0
    assert "require --search-strategy" in result.output


def test_campaigns_add_dynamic_text_search_rejects_budget_type_on_add():
    """#362: --dyn-search-budget-type is update-only — not available on add.
    (It is intentionally not declared on the ``add`` decorator stack.)
    """
    result = _failing_run(
        "campaigns",
        "add",
        "--name",
        "Bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-weekly-spend-limit",
        "1000",
        "--dyn-search-budget-type",
        "WEEKLY_BUDGET",
    )
    assert result.exit_code != 0


# --- Update path ---


def test_campaigns_update_dynamic_text_search_average_cpc_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "999",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPC",
        "--dyn-search-average-cpc",
        "8",
        "--dyn-search-weekly-spend-limit",
        "1500",
    )
    dyn = body["params"]["Campaigns"][0]["DynamicTextCampaign"]
    assert dyn["BiddingStrategy"] == {
        "Search": {
            "BiddingStrategyType": "AVERAGE_CPC",
            "AverageCpc": {
                "AverageCpc": 8000000,
                "WeeklySpendLimit": 1500000000,
            },
        }
    }


def test_campaigns_update_dynamic_text_search_placement_only_payload():
    """#362: placement-only update — Search is emitted with PlacementTypes
    but no Strategy*Add block.
    """
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "1001",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "HIGHEST_POSITION",
        "--search-placement-search-results",
        "YES",
        "--search-placement-product-gallery",
        "NO",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "HIGHEST_POSITION",
        "PlacementTypes": {
            "SearchResults": "YES",
            "ProductGallery": "NO",
        },
    }


def test_campaigns_update_dynamic_text_search_budget_type_weekly_payload():
    """#362: BudgetType WEEKLY_BUDGET nulls CustomPeriodBudget."""
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "2002",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--dyn-search-weekly-spend-limit",
        "300",
        "--dyn-search-budget-type",
        "WEEKLY_BUDGET",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
        "WbMaximumClicks": {
            "WeeklySpendLimit": 300000000,
            "CustomPeriodBudget": None,
            "BudgetType": "WEEKLY_BUDGET",
        },
    }


def test_campaigns_update_dynamic_text_search_budget_type_custom_period_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "2003",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA",
        "--dyn-search-custom-period-spend-limit",
        "1000",
        "--dyn-search-custom-period-start-date",
        "2026-06-01",
        "--dyn-search-custom-period-end-date",
        "2026-06-30",
        "--dyn-search-custom-period-auto-continue",
        "YES",
        "--dyn-search-budget-type",
        "CUSTOM_PERIOD_BUDGET",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPA",
        "AverageCpa": {
            "CustomPeriodBudget": {
                "SpendLimit": 1000000000,
                "StartDate": "2026-06-01",
                "EndDate": "2026-06-30",
                "AutoContinue": "YES",
            },
            "WeeklySpendLimit": None,
            "BudgetType": "CUSTOM_PERIOD_BUDGET",
        },
    }


def test_campaigns_update_dynamic_text_search_strategy_only_leaves_bs_unset():
    """#362: with neither search-strategy nor any typed flag, the update
    payload omits BiddingStrategy entirely.
    """
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "7007",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--tracking-params",
        "utm_source=test",
    )
    dyn = body["params"]["Campaigns"][0]["DynamicTextCampaign"]
    assert "BiddingStrategy" not in dyn
    assert dyn["TrackingParams"] == "utm_source=test"


def test_campaigns_update_dynamic_text_search_rejects_budget_type_without_weekly():
    result = _failing_run(
        "campaigns",
        "update",
        "--id",
        "1",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--dyn-search-budget-type",
        "WEEKLY_BUDGET",
    )
    assert result.exit_code != 0
    assert "requires --dyn-search-weekly-spend-limit" in result.output


def test_campaigns_update_dynamic_text_search_rejects_partial_strategy_switch():
    """#362: switching --search-strategy on update without required typed
    flags is allowed (mirroring Network builder semantics) — only field-
    support validation runs. Sanity check that field-support fires.
    """
    result = _failing_run(
        "campaigns",
        "update",
        "--id",
        "1",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA",
        "--dyn-search-clicks-per-week",
        "10",
    )
    assert result.exit_code != 0
    assert "does not accept --dyn-search-clicks-per-week" in result.output
