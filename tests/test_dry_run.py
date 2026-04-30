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


def test_ads_update_payload_status_only():
    body = _dry_run("ads", "update", "--id", "999", "--status", "SUSPENDED")
    assert body["method"] == "update"
    ad = body["params"]["Ads"][0]
    assert ad == {"Id": 999, "Status": "SUSPENDED"}


def test_ads_update_typed_fields_build_nested_objects():
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--title",
        "Updated",
        "--text",
        "Body",
        "--href",
        "https://example.com",
        "--image-hash",
        "ygqa6jmlkgsbz7vnewp0",
    )
    ad = body["params"]["Ads"][0]
    assert ad["Id"] == 999
    assert ad["TextAd"] == {
        "Title": "Updated",
        "Text": "Body",
        "Href": "https://example.com",
    }
    assert ad["TextImageAd"] == {"AdImageHash": "ygqa6jmlkgsbz7vnewp0"}


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


def test_adgroups_update_payload_name_only():
    body = _dry_run("adgroups", "update", "--id", "222", "--name", "Renamed")
    assert body["method"] == "update"
    group = body["params"]["AdGroups"][0]
    assert group == {"Id": 222, "Name": "Renamed"}


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
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    combined = (result.output or "") + (
        str(result.exception) if result.exception else ""
    )
    assert "--filter-average-cpc" in combined or "AVERAGE_CPC_PER_FILTER" in combined


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


# ----------------------------------------------------------------------
# bids / keywordbids
# ----------------------------------------------------------------------


def test_bids_set_payload():
    body = _dry_run("bids", "set", "--keyword-id", "1", "--bid", "15000000")
    assert body["method"] == "set"
    bid = body["params"]["Bids"][0]
    assert bid == {"KeywordId": 1, "Bid": 15000000}


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


# ----------------------------------------------------------------------
# bidmodifiers
# ----------------------------------------------------------------------


def test_bidmodifiers_set_legacy_payload_keeps_modifier_type():
    """Legacy (broken-by-design) ``bidmodifiers set`` path.

    The API rejects this shape with ``required field Id is omitted``
    — see ``TestWriteBidModifiersSet.test_set_without_id_is_rejected``.
    It is preserved only so that existing integration cassette keeps
    passing; new callers should use ``--id`` (see test below).

    Regression guard: the enum is the same as ``bidmodifiers add``
    (``MOBILE_ADJUSTMENT``), not the short form ``MOBILE`` that an
    older version of this test asserted — the cassette actually
    sends ``MOBILE_ADJUSTMENT``, and click.Choice now enforces the
    full enum form.
    """
    body = _dry_run(
        "bidmodifiers",
        "set",
        "--campaign-id",
        "1",
        "--type",
        "MOBILE_ADJUSTMENT",
        "--value",
        "150",
    )
    assert body["method"] == "set"
    modifier = body["params"]["BidModifiers"][0]
    assert modifier == {
        "CampaignId": 1,
        "Type": "MOBILE_ADJUSTMENT",
        "BidModifier": 150,
    }


def test_bidmodifiers_set_legacy_type_is_case_insensitive():
    """Legacy path: ``--type mobile_adjustment`` (lowercase) is accepted.

    click.Choice(..., case_sensitive=False) normalizes to the canonical
    uppercase form, so users can't get a silent typo drop.  Regression
    guard for axisrow/direct-cli#23.
    """
    body = _dry_run(
        "bidmodifiers",
        "set",
        "--campaign-id",
        "1",
        "--type",
        "mobile_adjustment",
        "--value",
        "150",
    )
    modifier = body["params"]["BidModifiers"][0]
    assert modifier["Type"] == "MOBILE_ADJUSTMENT"


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

    Without this guard, a caller combining the two shapes would end up
    with a confusing payload that the API rejects in a non-obvious way.
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
    assert "mutually exclusive" in combined or "--id" in combined


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
    assert "--id" in combined or "--campaign-id" in combined


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
    )
    assert body["method"] == "add"
    feed = body["params"]["Feeds"][0]
    # The API requires both the SourceType discriminator and the nested
    # UrlFeed/FileFeed/BusinessType object that carries the URL or data.
    assert feed == {
        "Name": "Feed A",
        "SourceType": "URL",
        "UrlFeed": {"Url": "https://example.com/feed.xml"},
    }


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
    assert "--name" in combined or "--url" in combined


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
        "HIGH",
    )
    assert body["method"] == "add"
    target = body["params"]["AudienceTargets"][0]
    assert target == {
        "AdGroupId": 100,
        "RetargetingListId": 200,
        "ContextBid": 12000000,
        "StrategyPriority": "HIGH",
    }


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
        assert f"No such option: {flag}" in result.output


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
            {"BidModifier": 103, "IncomeGrade": "VERY_HIGH"}
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
    assert "No such option: --email" in result.output


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
        "--bid",
        "1500000",
    )
    assert body["method"] == "add"
    target = body["params"]["DynamicFeedAdTargets"][0]
    assert target["AdGroupId"] == 123
    assert target["Name"] == "Test Target"
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
        "--params",
        '{"AverageCpc": 1000000}',
    )
    assert body["method"] == "add"
    s = body["params"]["Strategies"][0]
    assert s["Name"] == "My Strategy"
    assert "AverageCpc" in s


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
    )
    assert body["method"] == "update"
    s = body["params"]["Strategies"][0]
    assert s["Id"] == 77
    assert s["Name"] == "Updated"


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
