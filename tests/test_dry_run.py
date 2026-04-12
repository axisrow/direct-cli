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

Only commands that already implement ``--dry-run`` are covered (this is
all ``add`` / ``update`` / ``set`` / ``toggle`` write commands).
Single-action state-change commands (``delete``, ``archive``,
``unarchive``, ``suspend``, ``resume``, ``moderate``) currently don't
expose ``--dry-run`` and only send a trivial ``SelectionCriteria``
payload, so they're out of scope here.

Part of axisrow/yandex-direct-mcp-plugin#61.
"""

import json

from click.testing import CliRunner

from direct_cli.cli import cli


def _dry_run(*args: str) -> dict:
    """Invoke a CLI command with ``--dry-run`` and return the parsed body."""
    result = CliRunner().invoke(cli, list(args) + ["--dry-run"])
    assert result.exit_code == 0, (
        f"command failed: direct {' '.join(args)} --dry-run\n"
        f"output: {result.output}\n"
        f"exception: {result.exception}"
    )
    return json.loads(result.output)


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
        "Title": "T",
        "Text": "Some text",
        "Href": "https://example.com",
    }


def test_ads_add_case_insensitive_type():
    """--type is case-insensitive: ``text_ad`` and ``text-ad`` work too.

    Regression guard for axisrow/direct-cli#21 — before the fix, only the
    exact string ``TEXT_AD`` built a TextAd; any other value silently
    dropped --title/--text/--href.
    """
    for variant in ("text_ad", "Text_Ad", "text-ad", "TEXT-AD"):
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
            "Title": "T",
            "Text": "Body",
            "Href": "https://example.com",
        }, f"--type {variant!r} failed to build TextAd"


def test_ads_add_unknown_type_with_title_errors():
    """Non-TEXT_AD --type plus convenience flags fails loudly.

    Regression guard for axisrow/direct-cli#21 — before the fix, passing
    e.g. ``--type text`` (lowercase typo) silently dropped
    --title/--text/--href, the API then responded with a very confusing
    ``5008 None of the required fields were sent`` error, and users
    debugged the payload instead of the flag.
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
            "--title",
            "T",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    combined = (result.output or "") + (
        str(result.exception) if result.exception else ""
    )
    assert "TEXT_IMAGE_AD" in combined or "--json" in combined or "TEXT_AD" in combined


def test_ads_add_unknown_type_with_json_passes():
    """Non-TEXT_AD --type works when the caller supplies the nested object via --json.

    This keeps the escape hatch open for building e.g. TextImageAd,
    MobileAppAd, etc., without the CLI having to know their schemas.
    """
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "55",
        "--type",
        "TEXT_IMAGE_AD",
        "--json",
        json.dumps(
            {"TextImageAd": {"AdImageHash": "abc", "Href": "https://example.com"}}
        ),
    )
    ad = body["params"]["Ads"][0]
    assert "Type" not in ad
    assert ad["AdGroupId"] == 55
    assert ad["TextImageAd"] == {
        "AdImageHash": "abc",
        "Href": "https://example.com",
    }


def test_ads_update_payload_status_only():
    body = _dry_run("ads", "update", "--id", "999", "--status", "SUSPENDED")
    assert body["method"] == "update"
    ad = body["params"]["Ads"][0]
    assert ad == {"Id": 999, "Status": "SUSPENDED"}


def test_ads_update_extra_json_merges_into_payload():
    extra = {"TextAd": {"Title": "Updated"}}
    body = _dry_run("ads", "update", "--id", "999", "--json", json.dumps(extra))
    ad = body["params"]["Ads"][0]
    assert ad["Id"] == 999
    assert ad["TextAd"] == {"Title": "Updated"}


def test_ads_get_default_fieldnames():
    """Default FieldNames includes basic top-level fields, plus TextAdFieldNames."""
    body = _dry_run("ads", "get", "--campaign-ids", "12345")
    assert body["method"] == "get"
    assert body["params"]["FieldNames"] == [
        "Id",
        "CampaignId",
        "AdGroupId",
        "Status",
        "State",
        "Type",
    ]
    assert body["params"]["TextAdFieldNames"] == ["Title", "Title2", "Text", "Href"]


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


def test_campaigns_add_with_budget_scales_to_micro_units():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "C2",
        "--start-date",
        "2026-04-10",
        "--budget",
        "500",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["DailyBudget"] == {"Amount": 500_000_000, "Mode": "STANDARD"}


def test_campaigns_update_with_budget_scales_to_micro_units():
    body = _dry_run("campaigns", "update", "--id", "555", "--budget", "100")
    campaign = body["params"]["Campaigns"][0]
    assert campaign["Id"] == 555
    assert campaign["DailyBudget"] == {"Amount": 100_000_000, "Mode": "STANDARD"}


# ----------------------------------------------------------------------
# keywords
# ----------------------------------------------------------------------


def test_keywords_add_payload_with_bids_scales_to_micro_units():
    body = _dry_run(
        "keywords",
        "add",
        "--adgroup-id",
        "12",
        "--keyword",
        "купить пиццу",
        "--bid",
        "15",
        "--context-bid",
        "5",
    )
    assert body["method"] == "add"
    keyword = body["params"]["Keywords"][0]
    assert keyword["AdGroupId"] == 12
    assert keyword["Keyword"] == "купить пиццу"
    assert keyword["Bid"] == 15_000_000
    assert keyword["ContextBid"] == 5_000_000


def test_keywords_update_payload_status_only():
    body = _dry_run("keywords", "update", "--id", "777", "--status", "SUSPENDED")
    keyword = body["params"]["Keywords"][0]
    assert keyword == {"Id": 777, "Status": "SUSPENDED"}


# ----------------------------------------------------------------------
# bids / keywordbids
# ----------------------------------------------------------------------


def test_bids_set_scales_to_micro_units():
    body = _dry_run("bids", "set", "--campaign-id", "1", "--bid", "15")
    assert body["method"] == "set"
    bid = body["params"]["Bids"][0]
    assert bid == {"CampaignId": 1, "Bid": 15_000_000}


def test_keywordbids_set_search_and_network_scales():
    body = _dry_run(
        "keywordbids",
        "set",
        "--keyword-id",
        "42",
        "--search-bid",
        "8",
        "--network-bid",
        "3",
    )
    assert body["method"] == "set"
    bid = body["params"]["KeywordBids"][0]
    assert bid == {
        "KeywordId": 42,
        "SearchBid": 8_000_000,
        "NetworkBid": 3_000_000,
    }


# ----------------------------------------------------------------------
# bidmodifiers
# ----------------------------------------------------------------------


def test_bidmodifiers_set_payload_keeps_modifier_type():
    # NB: BidModifier ``Type`` (DEMOGRAPHICS / MOBILE / ...) is the
    # *category* of the modifier and IS a real top-level API field, so
    # it must be kept — this test does not assert ``Type not in ...``.
    body = _dry_run(
        "bidmodifiers",
        "set",
        "--campaign-id",
        "1",
        "--type",
        "MOBILE",
        "--value",
        "1.5",
    )
    assert body["method"] == "set"
    modifier = body["params"]["BidModifiers"][0]
    assert modifier == {
        "CampaignId": 1,
        "Type": "MOBILE",
        "BidModifier": 1.5,
    }


def test_bidmodifiers_toggle_enable():
    body = _dry_run("bidmodifiers", "toggle", "--id", "777", "--enabled")
    assert body["method"] == "set"
    modifier = body["params"]["BidModifiers"][0]
    assert modifier == {"Id": 777, "Enabled": "YES"}


def test_bidmodifiers_toggle_disable():
    body = _dry_run("bidmodifiers", "toggle", "--id", "777", "--disabled")
    modifier = body["params"]["BidModifiers"][0]
    assert modifier["Enabled"] == "NO"


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


# ----------------------------------------------------------------------
# retargeting
# ----------------------------------------------------------------------


def test_retargeting_add_keeps_list_type():
    # NB: ``Type`` here is the *list category*
    # (AUDIENCE_SEGMENT / PIXEL / ...), a real top-level API field —
    # not the same kind of ``Type`` as in ads/adgroups/smartadtargets.
    body = _dry_run(
        "retargeting",
        "add",
        "--name",
        "List A",
        "--type",
        "AUDIENCE_SEGMENT",
    )
    assert body["method"] == "add"
    rtg = body["params"]["RetargetingLists"][0]
    assert rtg == {"Name": "List A", "Type": "AUDIENCE_SEGMENT"}


# ----------------------------------------------------------------------
# audiencetargets
# ----------------------------------------------------------------------


def test_audiencetargets_add_scales_bid_to_micro_units():
    body = _dry_run(
        "audiencetargets",
        "add",
        "--adgroup-id",
        "100",
        "--retargeting-list-id",
        "200",
        "--bid",
        "12",
    )
    assert body["method"] == "add"
    target = body["params"]["AudienceTargets"][0]
    assert target == {
        "AdGroupId": 100,
        "RetargetingListId": 200,
        "Bid": 12_000_000,
    }


# ----------------------------------------------------------------------
# sitelinks
# ----------------------------------------------------------------------


def test_sitelinks_add_parses_links_array():
    links = [
        {"Title": "About", "Href": "https://example.com/about"},
        {"Title": "Contact", "Href": "https://example.com/contact"},
    ]
    body = _dry_run("sitelinks", "add", "--links", json.dumps(links))
    assert body["method"] == "add"
    sitelinks_set = body["params"]["SitelinksSets"][0]
    assert sitelinks_set == {"Sitelinks": links}


# ----------------------------------------------------------------------
# vcards
# ----------------------------------------------------------------------


def test_vcards_add_passes_full_json_through():
    vcard = {
        "CampaignId": 555,
        "Country": "Россия",
        "City": "Москва",
        "CompanyName": "Acme",
    }
    body = _dry_run("vcards", "add", "--json", json.dumps(vcard))
    assert body["method"] == "add"
    assert body["params"]["VCards"] == [vcard]


# ----------------------------------------------------------------------
# adextensions
# ----------------------------------------------------------------------


def test_adextensions_add_does_not_send_type_field():
    body = _dry_run(
        "adextensions",
        "add",
        "--type",
        "CALLOUT",
        "--json",
        json.dumps({"Callout": {"CalloutText": "Free shipping"}}),
    )
    assert body["method"] == "add"
    ext = body["params"]["AdExtensions"][0]
    # The API derives the extension type from the nested field name
    # (Callout / Sitelinks / Vcard / ...).  The top-level --type CLI
    # option is a UX hint and must NOT be forwarded to the request.
    assert "Type" not in ext
    assert ext == {"Callout": {"CalloutText": "Free shipping"}}


# ----------------------------------------------------------------------
# adimages
# ----------------------------------------------------------------------


def test_adimages_add_passes_full_json_through():
    image = {"ImageData": "BASE64DATA", "Name": "banner.png"}
    body = _dry_run("adimages", "add", "--json", json.dumps(image))
    assert body["method"] == "add"
    assert body["params"]["AdImages"] == [image]


# ----------------------------------------------------------------------
# dynamicads
# ----------------------------------------------------------------------


def test_dynamicads_add_payload_uses_webpages_key():
    target = {
        "Name": "Webpage A",
        "Conditions": [{"Operator": "CONTAINS", "Arguments": ["foo"]}],
    }
    body = _dry_run(
        "dynamicads",
        "add",
        "--adgroup-id",
        "33",
        "--json",
        json.dumps(target),
    )
    assert body["method"] == "add"
    webpage = body["params"]["Webpages"][0]
    assert webpage["AdGroupId"] == 33
    assert webpage["Name"] == "Webpage A"
    assert webpage["Conditions"] == target["Conditions"]


def test_dynamicads_update_merges_extra_json():
    body = _dry_run(
        "dynamicads",
        "update",
        "--id",
        "44",
        "--json",
        json.dumps({"Name": "Renamed"}),
    )
    assert body["method"] == "update"
    webpage = body["params"]["Webpages"][0]
    assert webpage == {"Id": 44, "Name": "Renamed"}


# ----------------------------------------------------------------------
# smartadtargets
# ----------------------------------------------------------------------


def test_smartadtargets_add_payload_omits_type():
    body = _dry_run(
        "smartadtargets",
        "add",
        "--adgroup-id",
        "55",
        "--type",
        "VIEWED_PRODUCT",
        "--json",
        json.dumps({"TargetingId": "VIEWED_PRODUCT"}),
    )
    assert body["method"] == "add"
    target = body["params"]["SmartAdTargets"][0]
    # Regression guard: ``Type`` is not a field on
    # ``SmartAdTargetAddItem``. The legacy ``--type`` CLI option is
    # accepted for backward compatibility but no longer forwarded;
    # callers must use --json to pass real fields like ``TargetingId``.
    assert "Type" not in target
    assert target["AdGroupId"] == 55
    assert target["TargetingId"] == "VIEWED_PRODUCT"


def test_smartadtargets_update_omits_type():
    body = _dry_run(
        "smartadtargets",
        "update",
        "--id",
        "66",
        "--json",
        json.dumps({"Bid": {"Deposit": 3_000_000, "Currency": "RUB"}}),
    )
    target = body["params"]["SmartAdTargets"][0]
    assert "Type" not in target
    assert target["Id"] == 66
    assert target["Bid"] == {"Deposit": 3_000_000, "Currency": "RUB"}


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


def test_agencyclients_add_passes_full_json_through():
    client_data = {
        "Login": "client-login",
        "Currency": "RUB",
        "Grants": [],
    }
    body = _dry_run("agencyclients", "add", "--json", json.dumps(client_data))
    assert body["method"] == "add"
    assert body["params"]["Clients"] == [client_data]


# ----------------------------------------------------------------------
# clients
# ----------------------------------------------------------------------


def test_clients_update_merges_extra_json_with_client_id():
    body = _dry_run(
        "clients",
        "update",
        "--client-id",
        "999",
        "--json",
        json.dumps({"Phone": "+70000000000"}),
    )
    assert body["method"] == "update"
    client = body["params"]["Clients"][0]
    assert client == {"ClientId": 999, "Phone": "+70000000000"}
