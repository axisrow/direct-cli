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
``update``, ``set``, ``toggle``) and the main single-action lifecycle
commands that now expose ``--dry-run`` (``delete``, ``archive``,
``unarchive``, ``suspend``, ``resume``, ``moderate``) so that trivial
``SelectionCriteria`` regressions are also caught in CI.

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
            "Mobile": "NO",
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
    for bad_type in ("TEXT_IMAGE_AD", "text"):
        result = CliRunner().invoke(
            cli,
            [
                "ads",
                "add",
                "--adgroup-id",
                "1",
                "--type",
                bad_type,
                "--title",
                "T",
                "--dry-run",
            ],
        )
        assert result.exit_code != 0, f"--type {bad_type!r} should have errored"
        combined = (result.output or "") + (
            str(result.exception) if result.exception else ""
        )
        assert (
            bad_type in combined or "--json" in combined or "TEXT_AD" in combined
        ), f"--type {bad_type!r} error message missing expected content"


def test_ads_add_unknown_type_with_json_passes():
    """Non-TEXT_AD --type works when the caller supplies the nested object via --json.

    This keeps the escape hatch open for building e.g. TextImageAd,
    MobileAppAd, etc., without the CLI having to know their schemas.

    Note on ``AdImageHash``: this is a format-plausible placeholder
    (20 lowercase alphanumeric characters — the shape Yandex Direct
    returns from ``adimages add``).  This is a dry-run test: the hash
    is never sent to any API, so the concrete value is irrelevant; we
    just pick something that looks like a real hash instead of
    obvious filler text.
    """
    image_hash = "ygqa6jmlkgsbz7vnewp0"
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "55",
        "--type",
        "TEXT_IMAGE_AD",
        "--json",
        json.dumps(
            {
                "TextImageAd": {
                    "AdImageHash": image_hash,
                    "Href": "https://example.com",
                }
            }
        ),
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


def test_adgroups_add_unsupported_type_errors():
    """Non-TEXT_AD_GROUP --type fails loudly.

    Regression guard for axisrow/direct-cli#23 — before the fix the CLI
    silently discarded --type and built a TEXT_AD_GROUP regardless, so
    a user asking for ``--type MOBILE_APP_AD_GROUP`` got a text ad group
    with no warning. Now the CLI fails loudly with a UsageError that
    points at --json as the escape hatch.
    """
    result = CliRunner().invoke(
        cli,
        [
            "adgroups",
            "add",
            "--name",
            "Group A",
            "--campaign-id",
            "111",
            "--type",
            "MOBILE_APP_AD_GROUP",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    combined = (result.output or "") + (
        str(result.exception) if result.exception else ""
    )
    assert "MOBILE_APP_AD_GROUP" in combined or "--json" in combined


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


def test_campaigns_add_case_insensitive_text_type():
    """``--type text_campaign`` (lowercase/dashed) builds a TextCampaign.

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
        "text-campaign",
    )
    campaign = body["params"]["Campaigns"][0]
    assert "TextCampaign" in campaign
    assert "Type" not in campaign


def test_campaigns_add_unsupported_type_errors():
    """Non-TEXT_CAMPAIGN --type fails loudly.

    Regression guard for axisrow/direct-cli#23 — before the fix the CLI
    silently dropped --type and always created a TextCampaign, so
    ``--type MOBILE_APP_CAMPAIGN`` produced a text campaign with no
    warning. Now it raises a UsageError pointing at --json.
    """
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
            "MOBILE_APP_CAMPAIGN",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    combined = (result.output or "") + (
        str(result.exception) if result.exception else ""
    )
    assert "MOBILE_APP_CAMPAIGN" in combined or "--json" in combined


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
    body = _dry_run("bids", "set", "--keyword-id", "1", "--bid", "15")
    assert body["method"] == "set"
    bid = body["params"]["Bids"][0]
    assert bid == {"KeywordId": 1, "Bid": 15_000_000}


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
        "1.5",
    )
    assert body["method"] == "set"
    modifier = body["params"]["BidModifiers"][0]
    assert modifier == {
        "CampaignId": 1,
        "Type": "MOBILE_ADJUSTMENT",
        "BidModifier": 1.5,
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
        "1.5",
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
    assert modifier == {"Id": 42, "BidModifier": 150.0}
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


def test_bidmodifiers_toggle_enable():
    body = _dry_run(
        "bidmodifiers", "toggle",
        "--campaign-id", "777",
        "--type", "DEMOGRAPHICS_ADJUSTMENT",
        "--enabled",
    )
    assert body["method"] == "toggle"
    item = body["params"]["BidModifierToggleItems"][0]
    assert item == {"CampaignId": 777, "Type": "DEMOGRAPHICS_ADJUSTMENT", "Enabled": "YES"}


def test_bidmodifiers_toggle_disable():
    body = _dry_run(
        "bidmodifiers", "toggle",
        "--campaign-id", "777",
        "--type", "DEMOGRAPHICS_ADJUSTMENT",
        "--disabled",
    )
    item = body["params"]["BidModifierToggleItems"][0]
    assert item == {"CampaignId": 777, "Type": "DEMOGRAPHICS_ADJUSTMENT", "Enabled": "NO"}


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


def test_feeds_add_url_and_json_urlfeed_conflict_errors():
    """Passing both --url and --json '{"UrlFeed":{...}}' fails loudly.

    Regression guard for axisrow/direct-cli#23 — before the fix
    ``feed_data.update(extra)`` would silently replace the UrlFeed
    object built from --url with the one from --json, so the --url
    value vanished from the request with no warning.
    """
    result = CliRunner().invoke(
        cli,
        [
            "feeds",
            "add",
            "--name",
            "F-conflict",
            "--url",
            "https://a.example.com/feed.xml",
            "--json",
            json.dumps({"UrlFeed": {"Url": "https://b.example.com/feed.xml"}}),
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    combined = (result.output or "") + (
        str(result.exception) if result.exception else ""
    )
    assert "exactly one" in combined or "UrlFeed" in combined


def test_feeds_update_url_and_json_urlfeed_conflict_errors():
    """Same collision check as ``feeds add`` — mirror for ``feeds update``."""
    result = CliRunner().invoke(
        cli,
        [
            "feeds",
            "update",
            "--id",
            "9",
            "--url",
            "https://a.example.com/feed.xml",
            "--json",
            json.dumps({"UrlFeed": {"Url": "https://b.example.com/feed.xml"}}),
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    combined = (result.output or "") + (
        str(result.exception) if result.exception else ""
    )
    assert "exactly one" in combined or "UrlFeed" in combined


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
    )
    assert body["method"] == "add"
    rtg = body["params"]["RetargetingLists"][0]
    assert rtg == {"Name": "List A", "Type": "AUDIENCE"}


def test_retargeting_add_default_type_is_retargeting():
    """Without ``--type`` the CLI defaults to the API's default RETARGETING.

    Regression guard for axisrow/direct-cli#25 — before the fix ``--type``
    was required=True with no validation. Now it's optional and
    defaults to the same value the API picks when Type is omitted.
    """
    body = _dry_run("retargeting", "add", "--name", "List B")
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


def test_audiencetargets_add_scales_context_bid_to_micro_units():
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
        "ContextBid": 12_000_000,
    }


def test_audiencetargets_set_bids_uses_bids_array():
    body = _dry_run(
        "audiencetargets",
        "set-bids",
        "--id",
        "101",
        "--context-bid",
        "7",
    )
    assert body["method"] == "setBids"
    item = body["params"]["Bids"][0]
    assert item == {"Id": 101, "ContextBid": 7_000_000}


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


def test_adextensions_add_type_is_now_optional():
    """``--type`` is no longer ``required=True`` on ``adextensions add``.

    Regression guard for axisrow/direct-cli#25 — before the fix ``--type``
    was required but immediately discarded. Users should be able to
    pass just ``--json`` (which carries the real payload and determines
    the extension type via its nested field name).
    """
    body = _dry_run(
        "adextensions",
        "add",
        "--json",
        json.dumps({"Sitelinks": [{"Title": "T", "Href": "https://a"}]}),
    )
    ext = body["params"]["AdExtensions"][0]
    assert "Type" not in ext
    assert ext == {"Sitelinks": [{"Title": "T", "Href": "https://a"}]}


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


def test_dynamicads_set_bids_uses_bids_array():
    body = _dry_run(
        "dynamicads",
        "set-bids",
        "--id",
        "44",
        "--bid",
        "3",
        "--context-bid",
        "2",
    )
    assert body["method"] == "setBids"
    item = body["params"]["Bids"][0]
    assert item == {"Id": 44, "Bid": 3_000_000, "ContextBid": 2_000_000}


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
        json.dumps({"Name": "Audience A", "Audience": "ALL_SEGMENTS"}),
    )
    assert body["method"] == "add"
    target = body["params"]["SmartAdTargets"][0]
    assert "Type" not in target
    assert target["AdGroupId"] == 55
    assert target["Name"] == "Audience A"
    assert target["Audience"] == "ALL_SEGMENTS"


def test_smartadtargets_update_omits_type():
    body = _dry_run(
        "smartadtargets",
        "update",
        "--id",
        "66",
        "--json",
        json.dumps({"AverageCpc": 3_000_000}),
    )
    target = body["params"]["SmartAdTargets"][0]
    assert "Type" not in target
    assert target["Id"] == 66
    assert target["AverageCpc"] == 3_000_000


def test_smartadtargets_add_type_is_now_optional():
    """``--type`` is no longer ``required=True`` on ``smartadtargets add``.

    Regression guard for axisrow/direct-cli#23 — before the fix
    ``--type`` was both required and immediately discarded, which
    forced every caller to pass a value that did nothing.  It is now
    optional, so passing only --json is enough.
    """
    body = _dry_run(
        "smartadtargets",
        "add",
        "--adgroup-id",
        "55",
        "--json",
        json.dumps({"Name": "Audience A", "Audience": "ALL_SEGMENTS"}),
    )
    target = body["params"]["SmartAdTargets"][0]
    assert "Type" not in target
    assert target["AdGroupId"] == 55
    assert target["Name"] == "Audience A"
    assert target["Audience"] == "ALL_SEGMENTS"


def test_smartadtargets_add_without_fields_errors():
    """Without --json (or any real fields), ``add`` fails loudly.

    Regression guard for axisrow/direct-cli#23 — before the fix the CLI
    happily sent ``{"AdGroupId": N}`` to the API and the user saw an
    opaque "required field missing" response.  The CLI now catches
    this up front with a UsageError that names the missing fields.
    """
    result = CliRunner().invoke(
        cli,
        [
            "smartadtargets",
            "add",
            "--adgroup-id",
            "55",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    combined = (result.output or "") + (
        str(result.exception) if result.exception else ""
    )
    assert "--json" in combined or "Audience" in combined or "Name" in combined


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
        "FirstName": "Alice",
        "LastName": "Smith",
        "Currency": "RUB",
        "Notification": {},
        "Grants": [],
    }
    body = _dry_run("agencyclients", "add", "--json", json.dumps(client_data))
    assert body["method"] == "add"
    assert body["params"] == client_data


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


class TestAdvideosDryRun:
    def test_add_by_url(self):
        body = _dry_run(
            "advideos", "add",
            "--url", "https://example.com/video.mp4",
            "--name", "Test Video",
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
            "bidmodifiers", "add",
            "--campaign-id", "123",
            "--type", "DEMOGRAPHICS_ADJUSTMENT",
            "--value", "150",
            "--json", '{"Gender": "GENDER_MALE", "Age": "AGE_25_34"}',
        )
        item = body["params"]["BidModifiers"][0]
        assert "DemographicsAdjustments" in item, f"got keys: {list(item.keys())}"
        assert "DemographicsAdjustment" not in item
        assert isinstance(item["DemographicsAdjustments"], list)
        assert item["DemographicsAdjustments"][0]["BidModifier"] == 150

    def test_retargeting_plural(self):
        body = _dry_run(
            "bidmodifiers", "add",
            "--campaign-id", "123",
            "--type", "RETARGETING_ADJUSTMENT",
            "--value", "120",
            "--json", '{"RetargetingConditionId": 456}',
        )
        item = body["params"]["BidModifiers"][0]
        assert "RetargetingAdjustments" in item, f"got keys: {list(item.keys())}"
        assert isinstance(item["RetargetingAdjustments"], list)

    def test_regional_plural(self):
        body = _dry_run(
            "bidmodifiers", "add",
            "--campaign-id", "123",
            "--type", "REGIONAL_ADJUSTMENT",
            "--value", "110",
            "--json", '{"RegionId": 1}',
        )
        item = body["params"]["BidModifiers"][0]
        assert "RegionalAdjustments" in item, f"got keys: {list(item.keys())}"
        assert isinstance(item["RegionalAdjustments"], list)

    def test_mobile_singular(self):
        """MobileAdjustment stays singular — regression guard."""
        body = _dry_run(
            "bidmodifiers", "add",
            "--campaign-id", "123",
            "--type", "MOBILE_ADJUSTMENT",
            "--value", "130",
        )
        item = body["params"]["BidModifiers"][0]
        assert "MobileAdjustment" in item
        assert isinstance(item["MobileAdjustment"], dict)


# ----------------------------------------------------------------------
# wsdl coverage gap closures
# ----------------------------------------------------------------------


def test_agencyclients_add_payload_uses_top_level_fields():
    body = _dry_run(
        "agencyclients",
        "add",
        "--json",
        '{"Login":"client-login","FirstName":"Alice","LastName":"Smith","Currency":"RUB","Notification":{}}',
    )
    assert body["method"] == "add"
    assert body["params"]["Login"] == "client-login"
    assert "Notification" in body["params"]
    assert "Clients" not in body["params"]


def test_agencyclients_add_passport_organization_payload():
    body = _dry_run(
        "agencyclients",
        "add-passport-organization",
        "--name",
        "Org",
        "--currency",
        "RUB",
        "--notification-json",
        '{}',
    )
    assert body["method"] == "addPassportOrganization"
    assert body["params"] == {
        "Name": "Org",
        "Currency": "RUB",
        "Notification": {},
    }


def test_agencyclients_add_passport_organization_member_payload():
    body = _dry_run(
        "agencyclients",
        "add-passport-organization-member",
        "--passport-organization-login",
        "org-login",
        "--role",
        "CHIEF",
        "--send-invite-to-json",
        '{"Email":"user@example.com"}',
    )
    assert body["method"] == "addPassportOrganizationMember"
    assert body["params"] == {
        "PassportOrganizationLogin": "org-login",
        "Role": "CHIEF",
        "SendInviteTo": {"Email": "user@example.com"},
    }


def test_agencyclients_update_payload_uses_clients_array():
    body = _dry_run(
        "agencyclients",
        "update",
        "--client-id",
        "42",
        "--json",
        '{"Grants":[]}',
    )
    item = body["params"]["Clients"][0]
    assert item == {"ClientId": 42, "Grants": []}


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
        "--scope",
        "SEARCH",
    )
    item = body["params"]["Bids"][0]
    assert item == {"KeywordId": 1, "Scope": ["SEARCH"]}


def test_creatives_add_payload_uses_creatives_array():
    body = _dry_run(
        "creatives",
        "add",
        "--json",
        '{"VideoExtensionCreative":{"VideoId":"video-id"}}',
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
        "--json",
        '{"SearchByTrafficVolume":{"TargetTrafficVolume":100}}',
    )
    item = body["params"]["KeywordBids"][0]
    assert item == {
        "KeywordId": 321,
        "BiddingRule": {"SearchByTrafficVolume": {"TargetTrafficVolume": 100}},
    }


def test_retargeting_update_payload_uses_lists_array():
    body = _dry_run(
        "retargeting",
        "update",
        "--id",
        "55",
        "--json",
        '{"Name":"Renamed"}',
    )
    assert body["method"] == "update"
    assert body["params"]["RetargetingLists"][0] == {"Id": 55, "Name": "Renamed"}


def test_smartadtargets_set_bids_payload_uses_average_cpc():
    body = _dry_run(
        "smartadtargets",
        "set-bids",
        "--id",
        "11",
        "--average-cpc",
        "1.5",
    )
    assert body["method"] == "setBids"
    assert body["params"]["Bids"][0] == {"Id": 11, "AverageCpc": 1_500_000}


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
