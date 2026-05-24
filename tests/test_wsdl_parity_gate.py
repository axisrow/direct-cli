"""
WSDL ↔ CLI parity gate — milestone 0.3.9 (issue #198).

This module enforces four invariants that arose as recurring bug patterns
in mutating CLI commands. Each invariant is a separate parametrized test
class so a failure pinpoints the offending command and pattern.

Pattern A — empty subtype no-op:
    A mutating command must refuse to send a payload that contains only
    the resource ID. ``bids set --keyword-id 5 --dry-run`` printing
    ``{KeywordId: 5}`` is a silent no-op against the live API.

Pattern B — silent data loss:
    A typed flag must either be accepted by the chosen ``--type`` or
    raise UsageError. ``ads update --type TEXT_AD --image-hash X`` must
    not silently discard ``--image-hash``.

Pattern C — WSDL ``minOccurs=1`` not validated:
    Item-level required fields in the WSDL must map onto a Click
    ``required=True`` option (or be derivable from defaults).

Pattern D — strategy enum drift:
    ``STRATEGY_TYPES`` in ``direct_cli/commands/strategies.py`` must equal
    the choice-of-one subtype names declared in ``StrategyAddItem``.

The gate now enforces these invariants directly. Regression failures should
be treated as WSDL/CLI parity breaks, not as expected milestone work.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from direct_cli import wsdl_coverage
from direct_cli.cli import cli
from direct_cli.commands.bidmodifiers import _BIDMODIFIER_TYPE_TO_NESTED
from direct_cli.commands.strategies import (
    STRATEGY_FIELD_OPTIONS,
    STRATEGY_FLAG_NAMES,
    STRATEGY_TYPES,
    STRATEGY_UPDATE_FIELD_OPTIONS,
)
from direct_cli.smoke_matrix import commands_for_category
from direct_cli.wsdl_coverage import (
    CLI_TO_API_SERVICE,
    RUNTIME_DEPRECATED_METHODS,
    fetch_cached_wsdl,
    fetch_wsdl,
    get_operation_request_schema,
    get_required_item_fields,
    iter_container_item_fields,
)

# ---------------------------------------------------------------------------
# Pattern A — empty subtype no-op
# ---------------------------------------------------------------------------

# Each entry: (command_key, argv that supplies ONLY the resource ID,
# expected substring in the rejection message). The substring must
# describe the *guard reason* ("no fields", "at least one") so that
# strict-xfail in PR 2 cannot flip green from an unrelated UsageError
# like ``Missing option '--foo'`` introduced for a different reason.
EMPTY_PAYLOAD_PROBES: list[tuple[str, list[str], str]] = [
    (
        "ads.update",
        ["ads", "update", "--id", "1", "--type", "TEXT_AD"],
        "at least one",
    ),
    (
        "adgroups.update",
        ["adgroups", "update", "--id", "1"],
        "at least one",
    ),
    (
        "bids.set",
        ["bids", "set", "--keyword-id", "1"],
        "at least one",
    ),
    (
        "keywordbids.set",
        ["keywordbids", "set", "--keyword-id", "1"],
        "at least one",
    ),
    (
        "keywords.update",
        ["keywords", "update", "--id", "1"],
        "at least one",
    ),
    (
        "strategies.update",
        ["strategies", "update", "--id", "1", "--type", "AverageCpa"],
        "at least one",
    ),
]


@pytest.mark.parametrize(
    ("command_key", "argv", "expected_error"),
    EMPTY_PAYLOAD_PROBES,
    ids=[probe[0] for probe in EMPTY_PAYLOAD_PROBES],
)
def test_empty_payload_no_op_rejected(
    command_key: str, argv: list[str], expected_error: str
) -> None:
    result = CliRunner().invoke(cli, argv + ["--dry-run"])
    assert result.exit_code != 0, (
        f"{command_key}: empty payload accepted as no-op. " f"Output: {result.output!r}"
    )
    assert expected_error.lower() in result.output.lower(), (
        f"{command_key}: rejection happened but the error message lacks the "
        f"guard substring {expected_error!r}. The command must have a real "
        f"empty-payload guard, not just any Click required-option. "
        f"Output: {result.output!r}"
    )


# ---------------------------------------------------------------------------
# Pattern B — silent data loss
# ---------------------------------------------------------------------------

# A flag that does not belong to the chosen ``--type`` must raise
# UsageError rather than be silently dropped. The expected substring
# pins the rejection reason to the per-type validation so strict-xfail
# cannot flip green from an unrelated UsageError.
SILENT_LOSS_PROBES: list[tuple[str, list[str], str]] = [
    (
        "ads.update TEXT_AD + --action",
        [
            "ads",
            "update",
            "--id",
            "1",
            "--type",
            "TEXT_AD",
            "--action",
            "INSTALL",
        ],
        "--action",
    ),
    (
        "campaigns.add TEXT_CAMPAIGN + --counter-id",
        [
            "campaigns",
            "add",
            "--name",
            "C",
            "--start-date",
            "2026-04-10",
            "--type",
            "TEXT_CAMPAIGN",
            "--counter-id",
            "123",
        ],
        "--counter-id",
    ),
    (
        "adgroups.add TEXT_AD_GROUP + --domain-url",
        [
            "adgroups",
            "add",
            "--name",
            "G",
            "--campaign-id",
            "1",
            "--region-ids",
            "225",
            "--type",
            "TEXT_AD_GROUP",
            "--domain-url",
            "example.com",
        ],
        "--domain-url",
    ),
    (
        "ads.add TEXT_AD + --action",
        [
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
        ],
        "--action",
    ),
    (
        "bidmodifiers.add MOBILE_ADJUSTMENT + --gender",
        [
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
        ],
        "--gender",
    ),
    (
        "strategies.add WbMaximumClicks + --average-cpc",
        [
            "strategies",
            "add",
            "--name",
            "S",
            "--type",
            "WbMaximumClicks",
            "--average-cpc",
            "1000000",
        ],
        "--average-cpc",
    ),
    (
        "strategies.update PayForConversionMultipleGoals + --goal-id",
        [
            "strategies",
            "update",
            "--id",
            "1",
            "--type",
            "PayForConversionMultipleGoals",
            "--goal-id",
            "123",
        ],
        "--goal-id",
    ),
    (
        "campaigns.add TEXT_CAMPAIGN + --filter-average-cpc",
        [
            "campaigns",
            "add",
            "--name",
            "T",
            "--start-date",
            "2026-06-01",
            "--type",
            "TEXT_CAMPAIGN",
            "--filter-average-cpc",
            "1000000",
        ],
        "--filter-average-cpc",
    ),
    (
        "campaigns.add DYNAMIC_TEXT_CAMPAIGN + --filter-average-cpc",
        [
            "campaigns",
            "add",
            "--name",
            "D",
            "--start-date",
            "2026-06-01",
            "--type",
            "DYNAMIC_TEXT_CAMPAIGN",
            "--filter-average-cpc",
            "1000000",
        ],
        "--filter-average-cpc",
    ),
    (
        "campaigns.add SMART_CAMPAIGN + --filter-average-cpc without AVERAGE_CPC_PER_FILTER",
        [
            "campaigns",
            "add",
            "--name",
            "S",
            "--start-date",
            "2026-06-01",
            "--type",
            "SMART_CAMPAIGN",
            "--counter-id",
            "123",
            "--network-strategy",
            "SERVING_OFF",
            "--filter-average-cpc",
            "1000000",
        ],
        "--filter-average-cpc",
    ),
    (
        "campaigns.update --tracking-params without --type",
        [
            "campaigns",
            "update",
            "--id",
            "123",
            "--tracking-params",
            "utm_source=direct",
        ],
        "--tracking-params",
    ),
    (
        "campaigns.update MOBILE_APP_CAMPAIGN + --tracking-params",
        [
            "campaigns",
            "update",
            "--id",
            "123",
            "--type",
            "MOBILE_APP_CAMPAIGN",
            "--tracking-params",
            "utm_source=direct",
        ],
        "MOBILE_APP_CAMPAIGN",
    ),
    (
        "adgroups.add DYNAMIC_TEXT_AD_GROUP + --feed-id",
        [
            "adgroups",
            "add",
            "--name",
            "G",
            "--campaign-id",
            "1",
            "--region-ids",
            "225",
            "--type",
            "DYNAMIC_TEXT_AD_GROUP",
            "--domain-url",
            "example.com",
            "--feed-id",
            "170",
        ],
        "--feed-id",
    ),
    (
        "adgroups.add SMART_AD_GROUP + --domain-url",
        [
            "adgroups",
            "add",
            "--name",
            "G",
            "--campaign-id",
            "1",
            "--region-ids",
            "225",
            "--type",
            "SMART_AD_GROUP",
            "--feed-id",
            "170",
            "--domain-url",
            "example.com",
        ],
        "--domain-url",
    ),
    (
        "ads.add TEXT_IMAGE_AD + --action",
        [
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
            "--action",
            "INSTALL",
        ],
        "--action",
    ),
    (
        "ads.add TEXT_IMAGE_AD + --tracking-url",
        [
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
            "https://track.example.com",
        ],
        "--tracking-url",
    ),
    (
        "bidmodifiers.add DEMOGRAPHICS_ADJUSTMENT + --retargeting-condition-id",
        [
            "bidmodifiers",
            "add",
            "--campaign-id",
            "1",
            "--type",
            "DEMOGRAPHICS_ADJUSTMENT",
            "--value",
            "120",
            "--gender",
            "GENDER_MALE",
            "--retargeting-condition-id",
            "99",
        ],
        "--retargeting-condition-id",
    ),
    (
        "strategies.add AverageCpa + --average-cpc",
        [
            "strategies",
            "add",
            "--name",
            "S",
            "--type",
            "AverageCpa",
            "--average-cpa",
            "4000000",
            "--goal-id",
            "123",
            "--average-cpc",
            "30000000",
        ],
        "--average-cpc",
    ),
    (
        "ads.update TEXT_IMAGE_AD + --callouts-add",
        [
            "ads",
            "update",
            "--id",
            "1",
            "--type",
            "TEXT_IMAGE_AD",
            "--callouts-add",
            "111",
        ],
        "--callouts-add",
    ),
    (
        "ads.update MOBILE_APP_AD + --callouts-set",
        [
            "ads",
            "update",
            "--id",
            "1",
            "--type",
            "MOBILE_APP_AD",
            "--callouts-set",
            "111",
        ],
        "--callouts-set",
    ),
]


@pytest.mark.parametrize(
    ("probe_id", "argv", "expected_error"),
    SILENT_LOSS_PROBES,
    ids=[probe[0] for probe in SILENT_LOSS_PROBES],
)
def test_silent_data_loss_rejected(
    probe_id: str, argv: list[str], expected_error: str
) -> None:
    result = CliRunner().invoke(cli, argv + ["--dry-run"])
    assert result.exit_code != 0, (
        f"{probe_id}: incompatible flag silently dropped. " f"Output: {result.output!r}"
    )
    assert expected_error.lower() in result.output.lower(), (
        f"{probe_id}: rejection happened but the error message does not "
        f"reference the offending flag {expected_error!r}. The command must "
        f"have per-type flag validation, not just any UsageError. "
        f"Output: {result.output!r}"
    )


# ---------------------------------------------------------------------------
# Pattern C — WSDL minOccurs=1 not validated by CLI
# ---------------------------------------------------------------------------

# Map of (cli_group, cli_op) → (api_service, wsdl_operation, container_field).
# Container is the top-level field in the WSDL request that wraps the
# repeating *Item shape — usually the plural of the resource. Listed once
# here so the parity gate can iterate every WRITE_SANDBOX mutating command
# without re-inferring the container name from the body.
COMMAND_WSDL_MAP: dict[tuple[str, str], tuple[str, str, str]] = {
    ("ads", "add"): ("ads", "add", "Ads"),
    ("ads", "update"): ("ads", "update", "Ads"),
    ("adgroups", "add"): ("adgroups", "add", "AdGroups"),
    ("adgroups", "update"): ("adgroups", "update", "AdGroups"),
    ("adextensions", "add"): ("adextensions", "add", "AdExtensions"),
    ("adimages", "add"): ("adimages", "add", "AdImages"),
    ("advideos", "add"): ("advideos", "add", "AdVideos"),
    ("audiencetargets", "add"): ("audiencetargets", "add", "AudienceTargets"),
    ("bidmodifiers", "add"): ("bidmodifiers", "add", "BidModifiers"),
    ("bidmodifiers", "set"): ("bidmodifiers", "set", "BidModifiers"),
    ("campaigns", "add"): ("campaigns", "add", "Campaigns"),
    ("campaigns", "update"): ("campaigns", "update", "Campaigns"),
    ("creatives", "add"): ("creatives", "add", "Creatives"),
    ("dynamicads", "add"): ("dynamictextadtargets", "add", "Webpages"),
    ("dynamicfeedadtargets", "add"): (
        "dynamicfeedadtargets",
        "add",
        "DynamicFeedAdTargets",
    ),
    ("feeds", "add"): ("feeds", "add", "Feeds"),
    ("feeds", "update"): ("feeds", "update", "Feeds"),
    ("keywords", "add"): ("keywords", "add", "Keywords"),
    ("keywords", "update"): ("keywords", "update", "Keywords"),
    ("negativekeywordsharedsets", "add"): (
        "negativekeywordsharedsets",
        "add",
        "NegativeKeywordSharedSets",
    ),
    ("negativekeywordsharedsets", "update"): (
        "negativekeywordsharedsets",
        "update",
        "NegativeKeywordSharedSets",
    ),
    ("retargeting", "add"): ("retargetinglists", "add", "RetargetingLists"),
    ("retargeting", "update"): ("retargetinglists", "update", "RetargetingLists"),
    ("sitelinks", "add"): ("sitelinks", "add", "SitelinksSets"),
    ("smartadtargets", "add"): ("smartadtargets", "add", "SmartAdTargets"),
    ("smartadtargets", "update"): ("smartadtargets", "update", "SmartAdTargets"),
    ("strategies", "add"): ("strategies", "add", "Strategies"),
    ("strategies", "update"): ("strategies", "update", "Strategies"),
    ("vcards", "add"): ("vcards", "add", "VCards"),
    # Commands intentionally without item-level required fields beyond
    # the wrapper. Empty value means "no WSDL required-item check".
    ("bids", "set"): ("bids", "set", "Bids"),
    ("keywordbids", "set"): ("keywordbids", "set", "KeywordBids"),
    ("clients", "update"): ("clients", "update", "Clients"),
}

# WSDL → CLI option mapping by convention. WSDL uses CamelCase, Click uses
# kebab-case. Listed manually for fields where the conversion is not
# mechanical (compound nouns, abbreviations, multi-source fields).
WSDL_FIELD_TO_CLI_OPTION: dict[str, set[str]] = {
    "AdGroupId": {"--adgroup-id", "--ad-group-id"},
    "CampaignId": {"--campaign-id"},
    "SmartTvAdjustment": {"--type"},
    "RegionIds": {"--region-ids"},
    "Name": {"--name"},
    "StartDate": {"--start-date"},
    "BusinessType": {"--business-type"},
    "SourceType": {"--url"},  # derived inside the command
    "Id": {"--id"},
    "Keyword": {"--keyword"},
    "ImageData": {"--image-data", "--image-file"},
    "BidModifier": {"--value"},
    "VideoExtensionCreative": {"--video-id"},
    "Audience": {"--audience"},
    "Sitelinks": {"--sitelink"},
    "Rules": {"--rule"},
    "NegativeKeywords": {"--keywords"},
    # vCard required block
    "Country": {"--country"},
    "City": {"--city"},
    "CompanyName": {"--company-name"},
    "WorkTime": {"--work-time"},
    "Phone": {
        "--phone-country-code",
        "--phone-city-code",
        "--phone-number",
    },
    # ads add/update typed flags introduced in issue #202
    "Title2": {"--title2"},
    "DisplayUrlPath": {"--display-url-path"},
    "Mobile": {"--mobile"},
    "VCardId": {"--vcard-id"},
    "SitelinkSetId": {"--sitelink-set-id"},
    "TurboPageId": {"--turbo-page-id"},
    "AdExtensionIds": {"--ad-extensions"},
    # ads update typed flags introduced in issue #238
    "CalloutSetting": {
        "--callouts-add",
        "--callouts-remove",
        "--callouts-set",
    },
}

# Fields whose required-ness is enforced inside the command body rather
# than via Click ``required=True``. Each entry is the substring that must
# appear in the CLI's UsageError when the field is missing — the gate
# invokes the command without the relevant flags and asserts the error.
INTERNAL_VALIDATION: dict[tuple[str, str, str], str] = {
    (
        "adimages",
        "add",
        "ImageData",
    ): "Provide exactly one of --image-data or --image-file",
    ("bidmodifiers", "set", "Id"): "Provide --id with --value",
    ("bidmodifiers", "set", "BidModifier"): "Missing option '--value'",
    ("retargeting", "add", "Rules"): "Provide at least one --rule",
    ("creatives", "add", "VideoExtensionCreative"): "Missing option '--video-id'",
    ("keywords", "add", "Keyword"): "Provide exactly one of: --keyword",
    ("keywords", "add", "AdGroupId"): "Provide exactly one of: --keyword",
    ("sitelinks", "add", "Sitelinks"): "Provide exactly one of: --sitelink",
}

# Optional-field audit status registry for issue #239. This is deliberately a
# soft gate: confirmed misses are allowed to remain in CI, but they must be
# recorded with a follow-up issue so ``minOccurs=0`` WSDL fields do not vanish
# from the release audit again.
OPTIONAL_FIELD_AUDIT_MAX_DEPTH = None
OPTIONAL_FIELD_AUDIT_REPORT = (
    Path(__file__).resolve().parent / "WSDL_OPTIONAL_FIELD_AUDIT.md"
)
OPTIONAL_FIELD_AUDIT_STATUSES = {
    "missing_followup",
    "not_applicable",
    "supported",
}

# Exact WSDL path -> CLI option coverage used by the optional-field audit.
# This intentionally avoids leaf-name heuristics: ``FeedId`` under one subtype
# must not make every other ``*.FeedId`` row look supported.
OPTIONAL_FIELD_CLI_OPTIONS: dict[tuple[str, str, str], set[str]] = {
    ("adextensions", "add", "Callout"): {"--callout-text"},
    ("adextensions", "add", "Callout.CalloutText"): {"--callout-text"},
    ("adimages", "add", "Type"): {"--type"},
    ("adgroups", "add", "DynamicTextAdGroup"): {"--type"},
    ("adgroups", "add", "DynamicTextAdGroup.DomainUrl"): {"--domain-url"},
    ("adgroups", "add", "SmartAdGroup"): {"--type"},
    ("adgroups", "add", "SmartAdGroup.FeedId"): {"--feed-id"},
    ("adgroups", "add", "SmartAdGroup.AdTitleSource"): {"--ad-title-source"},
    ("adgroups", "add", "SmartAdGroup.AdBodySource"): {"--ad-body-source"},
    ("adgroups", "add", "NegativeKeywords"): {"--negative-keywords"},
    ("adgroups", "add", "NegativeKeywords.Items"): {"--negative-keywords"},
    ("adgroups", "add", "NegativeKeywordSharedSetIds"): {
        "--negative-keyword-shared-set-ids"
    },
    ("adgroups", "add", "NegativeKeywordSharedSetIds.Items"): {
        "--negative-keyword-shared-set-ids"
    },
    ("adgroups", "add", "TrackingParams"): {"--tracking-params"},
    ("adgroups", "update", "Name"): {"--name"},
    ("adgroups", "update", "RegionIds"): {"--region-ids"},
    ("adgroups", "update", "NegativeKeywords"): {"--negative-keywords"},
    ("adgroups", "update", "NegativeKeywords.Items"): {"--negative-keywords"},
    ("adgroups", "update", "NegativeKeywordSharedSetIds"): {
        "--negative-keyword-shared-set-ids"
    },
    ("adgroups", "update", "NegativeKeywordSharedSetIds.Items"): {
        "--negative-keyword-shared-set-ids"
    },
    ("adgroups", "update", "TrackingParams"): {"--tracking-params"},
    ("ads", "add", "TextAd"): {"--type"},
    ("ads", "add", "TextAd.VCardId"): {"--vcard-id"},
    ("ads", "add", "TextAd.AdImageHash"): {"--image-hash"},
    ("ads", "add", "TextAd.SitelinkSetId"): {"--sitelink-set-id"},
    ("ads", "add", "TextAd.AdExtensionIds"): {"--ad-extensions"},
    ("ads", "add", "TextAd.Text"): {"--text"},
    ("ads", "add", "TextAd.Title"): {"--title"},
    ("ads", "add", "TextAd.Title2"): {"--title2"},
    ("ads", "add", "TextAd.Href"): {"--href"},
    ("ads", "add", "TextAd.Mobile"): {"--mobile"},
    ("ads", "add", "TextAd.DisplayUrlPath"): {"--display-url-path"},
    ("ads", "add", "TextAd.TurboPageId"): {"--turbo-page-id"},
    ("ads", "add", "MobileAppAd"): {"--type"},
    ("ads", "add", "MobileAppAd.AdImageHash"): {"--image-hash"},
    ("ads", "add", "MobileAppAd.Text"): {"--text"},
    ("ads", "add", "MobileAppAd.Title"): {"--title"},
    ("ads", "add", "MobileAppAd.TrackingUrl"): {"--tracking-url"},
    ("ads", "add", "MobileAppAd.Action"): {"--action"},
    ("ads", "add", "MobileAppAd.AgeLabel"): {"--age-label"},
    ("ads", "add", "TextImageAd"): {"--type"},
    ("ads", "add", "TextImageAd.AdImageHash"): {"--image-hash"},
    ("ads", "add", "TextImageAd.Href"): {"--href"},
    ("ads", "add", "TextImageAd.TurboPageId"): {"--turbo-page-id"},
    ("ads", "update", "TextAd"): {"--type"},
    ("ads", "update", "TextAd.VCardId"): {"--vcard-id"},
    ("ads", "update", "TextAd.AdImageHash"): {"--image-hash"},
    ("ads", "update", "TextAd.SitelinkSetId"): {"--sitelink-set-id"},
    ("ads", "update", "TextAd.Text"): {"--text"},
    ("ads", "update", "TextAd.Title"): {"--title"},
    ("ads", "update", "TextAd.Title2"): {"--title2"},
    ("ads", "update", "TextAd.Href"): {"--href"},
    ("ads", "update", "TextAd.DisplayUrlPath"): {"--display-url-path"},
    ("ads", "update", "TextAd.TurboPageId"): {"--turbo-page-id"},
    ("ads", "update", "TextAd.CalloutSetting"): {
        "--callouts-add",
        "--callouts-remove",
        "--callouts-set",
    },
    ("ads", "update", "MobileAppAd"): {"--type"},
    ("ads", "update", "MobileAppAd.AdImageHash"): {"--image-hash"},
    ("ads", "update", "MobileAppAd.Text"): {"--text"},
    ("ads", "update", "MobileAppAd.Title"): {"--title"},
    ("ads", "update", "MobileAppAd.TrackingUrl"): {"--tracking-url"},
    ("ads", "update", "MobileAppAd.Action"): {"--action"},
    ("ads", "update", "MobileAppAd.AgeLabel"): {"--age-label"},
    ("ads", "update", "TextImageAd"): {"--type"},
    ("ads", "update", "TextImageAd.AdImageHash"): {"--image-hash"},
    ("ads", "update", "TextImageAd.Href"): {"--href"},
    ("ads", "update", "TextImageAd.TurboPageId"): {"--turbo-page-id"},
    ("campaigns", "add", "DailyBudget"): {"--budget"},
    ("campaigns", "add", "DailyBudget.Amount"): {"--budget"},
    ("campaigns", "add", "DailyBudget.Mode"): {"--budget"},
    ("campaigns", "add", "EndDate"): {"--end-date"},
    ("campaigns", "add", "TextCampaign"): {"--type"},
    ("campaigns", "add", "TextCampaign.BiddingStrategy"): {
        "--search-strategy",
        "--network-strategy",
    },
    ("campaigns", "add", "TextCampaign.Settings"): {"--setting"},
    ("campaigns", "add", "TextCampaign.CounterIds"): {"--counter-ids"},
    ("campaigns", "add", "TextCampaign.PriorityGoals"): {"--priority-goals"},
    ("campaigns", "add", "TextCampaign.TrackingParams"): {"--tracking-params"},
    ("campaigns", "add", "DynamicTextCampaign"): {"--type"},
    ("campaigns", "add", "DynamicTextCampaign.BiddingStrategy"): {
        "--search-strategy",
        "--network-strategy",
    },
    ("campaigns", "add", "DynamicTextCampaign.Settings"): {"--setting"},
    ("campaigns", "add", "DynamicTextCampaign.CounterIds"): {"--counter-ids"},
    ("campaigns", "add", "DynamicTextCampaign.PriorityGoals"): {"--priority-goals"},
    ("campaigns", "add", "DynamicTextCampaign.TrackingParams"): {"--tracking-params"},
    ("campaigns", "add", "SmartCampaign"): {"--type"},
    ("campaigns", "add", "SmartCampaign.CounterId"): {"--counter-id"},
    ("campaigns", "add", "SmartCampaign.BiddingStrategy"): {
        "--search-strategy",
        "--network-strategy",
        "--filter-average-cpc",
    },
    ("campaigns", "add", "SmartCampaign.Settings"): {"--setting"},
    ("campaigns", "add", "SmartCampaign.TrackingParams"): {"--tracking-params"},
    ("campaigns", "update", "Name"): {"--name"},
    ("campaigns", "update", "DailyBudget"): {"--budget"},
    ("campaigns", "update", "DailyBudget.Amount"): {"--budget"},
    ("campaigns", "update", "DailyBudget.Mode"): {"--budget"},
    ("campaigns", "update", "StartDate"): {"--start-date"},
    ("campaigns", "update", "EndDate"): {"--end-date"},
    ("campaigns", "update", "TextCampaign"): {"--type"},
    ("campaigns", "update", "TextCampaign.TrackingParams"): {"--tracking-params"},
    ("campaigns", "update", "DynamicTextCampaign"): {"--type"},
    ("campaigns", "update", "DynamicTextCampaign.TrackingParams"): {
        "--tracking-params"
    },
    ("campaigns", "update", "SmartCampaign"): {"--type"},
    ("campaigns", "update", "SmartCampaign.TrackingParams"): {"--tracking-params"},
    ("advideos", "add", "Url"): {"--url"},
    ("advideos", "add", "VideoData"): {"--video-data", "--video-file"},
    ("advideos", "add", "Name"): {"--name"},
    ("clients", "update", "ClientInfo"): {"--client-info"},
    ("clients", "update", "Phone"): {"--phone"},
    ("clients", "update", "Notification"): {
        "--notification-email",
        "--email-subscription",
        "--notification-lang",
    },
    ("clients", "update", "Notification.Email"): {"--notification-email"},
    ("clients", "update", "Notification.EmailSubscriptions"): {"--email-subscription"},
    ("clients", "update", "Notification.Lang"): {"--notification-lang"},
    ("clients", "update", "Settings"): {"--setting"},
    ("clients", "update", "TinInfo"): {"--tin", "--tin-type"},
    ("clients", "update", "TinInfo.TinType"): {"--tin-type"},
    ("clients", "update", "TinInfo.Tin"): {"--tin"},
    ("dynamicads", "add", "Conditions"): {"--condition"},
    ("dynamicads", "add", "Conditions.Operand"): {"--condition"},
    ("dynamicads", "add", "Conditions.Operator"): {"--condition"},
    ("dynamicads", "add", "Conditions.Arguments"): {"--condition"},
    ("dynamicads", "add", "Bid"): {"--bid"},
    ("dynamicads", "add", "ContextBid"): {"--context-bid"},
    ("dynamicads", "add", "StrategyPriority"): {"--priority"},
    ("dynamicfeedadtargets", "add", "Conditions"): {"--condition"},
    ("dynamicfeedadtargets", "add", "Conditions.Items"): {"--condition"},
    ("dynamicfeedadtargets", "add", "Bid"): {"--bid"},
    ("dynamicfeedadtargets", "add", "ContextBid"): {"--context-bid"},
    ("dynamicfeedadtargets", "add", "AvailableItemsOnly"): {"--available-items-only"},
    ("feeds", "add", "UrlFeed"): {"--url"},
    ("feeds", "add", "UrlFeed.Url"): {"--url"},
    ("feeds", "update", "Name"): {"--name"},
    ("feeds", "update", "UrlFeed"): {"--url"},
    ("feeds", "update", "UrlFeed.Url"): {"--url"},
    ("creatives", "add", "VideoExtensionCreative.VideoId"): {"--video-id"},
    ("keywords", "add", "Bid"): {"--bid"},
    ("keywords", "add", "ContextBid"): {"--context-bid"},
    ("keywords", "add", "UserParam1"): {"--user-param-1"},
    ("keywords", "add", "UserParam2"): {"--user-param-2"},
    ("keywords", "update", "Keyword"): {"--keyword"},
    ("keywords", "update", "UserParam1"): {"--user-param-1"},
    ("keywords", "update", "UserParam2"): {"--user-param-2"},
    ("negativekeywordsharedsets", "update", "Name"): {"--name"},
    ("negativekeywordsharedsets", "update", "NegativeKeywords"): {"--keywords"},
    ("audiencetargets", "add", "RetargetingListId"): {"--retargeting-list-id"},
    ("audiencetargets", "add", "InterestId"): {"--interest-id"},
    ("bids", "set", "KeywordId"): {"--keyword-id"},
    ("bids", "set", "Bid"): {"--bid"},
    ("keywordbids", "set", "KeywordId"): {"--keyword-id"},
    ("keywordbids", "set", "SearchBid"): {"--search-bid"},
    ("keywordbids", "set", "NetworkBid"): {"--network-bid"},
    ("retargeting", "add", "Rules"): {"--rule"},
    ("retargeting", "add", "Type"): {"--type"},
    ("retargeting", "add", "Description"): {"--description"},
    ("retargeting", "add", "Rules.Arguments"): {"--rule"},
    ("retargeting", "add", "Rules.Arguments.MembershipLifeSpan"): {"--rule"},
    ("retargeting", "add", "Rules.Arguments.ExternalId"): {"--rule"},
    ("retargeting", "add", "Rules.Operator"): {"--rule"},
    ("retargeting", "update", "Rules"): {"--rule"},
    ("retargeting", "update", "Name"): {"--name"},
    ("retargeting", "update", "Description"): {"--description"},
    ("retargeting", "update", "Rules.Arguments"): {"--rule"},
    ("retargeting", "update", "Rules.Arguments.MembershipLifeSpan"): {"--rule"},
    ("retargeting", "update", "Rules.Arguments.ExternalId"): {"--rule"},
    ("retargeting", "update", "Rules.Operator"): {"--rule"},
    ("sitelinks", "add", "Sitelinks"): {"--sitelink"},
    ("sitelinks", "add", "Sitelinks.Title"): {"--sitelink"},
    ("sitelinks", "add", "Sitelinks.Href"): {"--sitelink"},
    ("sitelinks", "add", "Sitelinks.Description"): {"--sitelink"},
    ("sitelinks", "add", "Sitelinks.TurboPageId"): {"--sitelink"},
    ("smartadtargets", "add", "StrategyPriority"): {"--priority"},
    ("smartadtargets", "add", "AverageCpc"): {"--average-cpc"},
    ("smartadtargets", "add", "AverageCpa"): {"--average-cpa"},
    ("smartadtargets", "add", "AvailableItemsOnly"): {"--available-items-only"},
    ("smartadtargets", "add", "Conditions"): {"--condition"},
    ("smartadtargets", "add", "Conditions.Items"): {"--condition"},
    ("smartadtargets", "update", "Name"): {"--name"},
    ("smartadtargets", "update", "StrategyPriority"): {"--priority"},
    ("smartadtargets", "update", "AverageCpc"): {"--average-cpc"},
    ("smartadtargets", "update", "AverageCpa"): {"--average-cpa"},
    ("smartadtargets", "update", "Audience"): {"--audience"},
    ("smartadtargets", "update", "AvailableItemsOnly"): {"--available-items-only"},
    ("smartadtargets", "update", "Conditions"): {"--condition"},
    ("smartadtargets", "update", "Conditions.Items"): {"--condition"},
    ("vcards", "add", "Phone.CountryCode"): {"--phone-country-code"},
    ("vcards", "add", "Phone.CityCode"): {"--phone-city-code"},
    ("vcards", "add", "Phone.PhoneNumber"): {"--phone-number"},
    ("vcards", "add", "Phone.Extension"): {"--phone-extension"},
    ("vcards", "add", "InstantMessenger"): {
        "--instant-messenger-client",
        "--instant-messenger-login",
    },
    ("vcards", "add", "InstantMessenger.MessengerClient"): {
        "--instant-messenger-client"
    },
    ("vcards", "add", "InstantMessenger.MessengerLogin"): {
        "--instant-messenger-login"
    },
    ("vcards", "add", "Street"): {"--street"},
    ("vcards", "add", "House"): {"--house"},
    ("vcards", "add", "Building"): {"--building"},
    ("vcards", "add", "Apartment"): {"--apartment"},
    ("vcards", "add", "ExtraMessage"): {"--extra-message"},
    ("vcards", "add", "ContactEmail"): {"--contact-email"},
    ("vcards", "add", "Ogrn"): {"--ogrn"},
    ("vcards", "add", "MetroStationId"): {"--metro-station-id"},
    ("vcards", "add", "PointOnMap"): {
        "--point-on-map-x",
        "--point-on-map-y",
        "--point-on-map-x1",
        "--point-on-map-y1",
        "--point-on-map-x2",
        "--point-on-map-y2",
    },
    ("vcards", "add", "PointOnMap.X"): {"--point-on-map-x"},
    ("vcards", "add", "PointOnMap.Y"): {"--point-on-map-y"},
    ("vcards", "add", "PointOnMap.X1"): {"--point-on-map-x1"},
    ("vcards", "add", "PointOnMap.Y1"): {"--point-on-map-y1"},
    ("vcards", "add", "PointOnMap.X2"): {"--point-on-map-x2"},
    ("vcards", "add", "PointOnMap.Y2"): {"--point-on-map-y2"},
    ("vcards", "add", "ContactPerson"): {"--contact-person"},
}

for strategy_type, options in STRATEGY_FIELD_OPTIONS.items():
    OPTIONAL_FIELD_CLI_OPTIONS[("strategies", "add", strategy_type)] = {"--type"}
    for param_name, wsdl_field in options.items():
        OPTIONAL_FIELD_CLI_OPTIONS[
            ("strategies", "add", f"{strategy_type}.{wsdl_field}")
        ] = {STRATEGY_FLAG_NAMES[param_name]}

OPTIONAL_FIELD_CLI_OPTIONS.update(
    {
        ("strategies", "add", "AttributionModel"): {"--attribution-model"},
        ("strategies", "add", "CounterIds"): {"--counter-ids"},
        ("strategies", "add", "CounterIds.Items"): {"--counter-ids"},
        ("strategies", "add", "PriorityGoals"): {"--priority-goal"},
        ("strategies", "add", "PriorityGoals.Items"): {"--priority-goal"},
    }
)

for strategy_type, options in STRATEGY_UPDATE_FIELD_OPTIONS.items():
    OPTIONAL_FIELD_CLI_OPTIONS[("strategies", "update", strategy_type)] = {"--type"}
    for param_name, wsdl_field in options.items():
        OPTIONAL_FIELD_CLI_OPTIONS[
            ("strategies", "update", f"{strategy_type}.{wsdl_field}")
        ] = {STRATEGY_FLAG_NAMES[param_name]}

OPTIONAL_FIELD_CLI_OPTIONS.update(
    {
        ("strategies", "update", "Name"): {"--name"},
        ("strategies", "update", "AttributionModel"): {"--attribution-model"},
        ("strategies", "update", "CounterIds"): {"--counter-ids"},
        ("strategies", "update", "CounterIds.Items"): {"--counter-ids"},
        ("strategies", "update", "PriorityGoals"): {"--priority-goal"},
        ("strategies", "update", "PriorityGoals.Items"): {"--priority-goal"},
    }
)

for nested_field in _BIDMODIFIER_TYPE_TO_NESTED.values():
    OPTIONAL_FIELD_CLI_OPTIONS[("bidmodifiers", "add", nested_field)] = {"--type"}
    OPTIONAL_FIELD_CLI_OPTIONS[
        ("bidmodifiers", "add", f"{nested_field}.BidModifier")
    ] = {"--value"}

OPTIONAL_FIELD_CLI_OPTIONS.update(
    {
        ("bidmodifiers", "add", "CampaignId"): {"--campaign-id"},
        ("bidmodifiers", "add", "AdGroupId"): {"--adgroup-id"},
        ("bidmodifiers", "add", "DemographicsAdjustments.Gender"): {"--gender"},
        ("bidmodifiers", "add", "DemographicsAdjustments.Age"): {"--age"},
        ("bidmodifiers", "add", "RetargetingAdjustments.RetargetingConditionId"): {
            "--retargeting-condition-id"
        },
        ("bidmodifiers", "add", "RegionalAdjustments.RegionId"): {"--region-id"},
        ("bidmodifiers", "add", "SerpLayoutAdjustments.SerpLayout"): {"--serp-layout"},
        ("bidmodifiers", "add", "IncomeGradeAdjustments.Grade"): {"--income-grade"},
    }
)

OPTIONAL_FIELD_DEFAULT_FOLLOWUPS: dict[tuple[str, str], dict[str, str]] = {
    ("ads", "add"): {
        "issue": "#249",
        "note": "ads.add optional WSDL path needs typed support or N/A.",
    },
    ("ads", "update"): {
        "issue": "#240",
        "note": "ads.update optional WSDL path needs typed support or N/A.",
    },
    ("audiencetargets", "add"): {
        "issue": "#252",
        "note": "target bid optional WSDL path needs typed support or N/A.",
    },
    ("bidmodifiers", "add"): {
        "issue": "#254",
        "note": "bidmodifiers.add optional WSDL path needs typed support or N/A.",
    },
    ("bids", "set"): {
        "issue": "#252",
        "note": "bids.set optional WSDL path needs typed support or N/A.",
    },
    ("campaigns", "add"): {
        "issue": "#250",
        "note": "campaigns.add optional WSDL path needs typed support or N/A.",
    },
    ("campaigns", "update"): {
        "issue": "#250",
        "note": "campaigns.update optional WSDL path needs typed support or N/A.",
    },
    ("clients", "update"): {
        "issue": "#255",
        "note": "clients.update optional WSDL path needs typed support or N/A.",
    },
    ("dynamicads", "add"): {
        "issue": "#252",
        "note": "dynamicads.add optional WSDL path needs typed support or N/A.",
    },
    ("dynamicfeedadtargets", "add"): {
        "issue": "#252",
        "note": "dynamicfeedadtargets.add optional WSDL path needs typed support or N/A.",
    },
    ("feeds", "add"): {
        "issue": "#253",
        "note": "feeds.add optional WSDL path needs typed support or N/A.",
    },
    ("feeds", "update"): {
        "issue": "#253",
        "note": "feeds.update optional WSDL path needs typed support or N/A.",
    },
    ("keywordbids", "set"): {
        "issue": "#252",
        "note": "keywordbids.set optional WSDL path needs typed support or N/A.",
    },
    ("retargeting", "add"): {
        "issue": "#256",
        "note": "retargeting.add optional WSDL path needs typed support or N/A.",
    },
    ("retargeting", "update"): {
        "issue": "#256",
        "note": "retargeting.update optional WSDL path needs typed support or N/A.",
    },
    ("smartadtargets", "add"): {
        "issue": "#252",
        "note": "smartadtargets.add optional WSDL path needs typed support or N/A.",
    },
    ("smartadtargets", "update"): {
        "issue": "#252",
        "note": "smartadtargets.update optional WSDL path needs typed support or N/A.",
    },
    ("strategies", "add"): {
        "issue": "#251",
        "note": "strategies.add optional WSDL path needs typed support or N/A.",
    },
    ("strategies", "update"): {
        "issue": "#251",
        "note": "strategies.update optional WSDL path needs typed support or N/A.",
    },
}

OPTIONAL_FIELD_AUDIT: dict[tuple[str, str, str], dict[str, str]] = {
    ("adgroups", "add", "DynamicTextAdGroup.AutotargetingCategories"): {
        "status": "missing_followup",
        "issue": "#247",
        "note": "Dynamic text ad group autotargeting categories are not exposed.",
    },
    ("adgroups", "add", "DynamicTextAdGroup.AutotargetingSettings"): {
        "status": "missing_followup",
        "issue": "#247",
        "note": "Dynamic text ad group autotargeting settings are not exposed.",
    },
    ("keywords", "add", "AutotargetingCategories"): {
        "status": "missing_followup",
        "issue": "#244",
        "note": "Keyword autotargeting categories have no typed add flags.",
    },
    ("keywords", "add", "AutotargetingSearchBidIsAuto"): {
        "status": "missing_followup",
        "issue": "#244",
        "note": "Keyword autotargeting auto-search-bid has no typed add flag.",
    },
    ("keywords", "add", "StrategyPriority"): {
        "status": "missing_followup",
        "issue": "#244",
        "note": "Keyword strategy priority has no typed add flag.",
    },
    ("keywords", "add", "AutotargetingBrandOptions"): {
        "status": "missing_followup",
        "issue": "#244",
        "note": "Keyword autotargeting brand options have no typed add flags.",
    },
    ("keywords", "add", "AutotargetingSettings"): {
        "status": "missing_followup",
        "issue": "#244",
        "note": "Keyword autotargeting settings have no typed add flags.",
    },
    ("keywords", "update", "AutotargetingCategories"): {
        "status": "missing_followup",
        "issue": "#244",
        "note": "Keyword autotargeting categories have no typed update flags.",
    },
    ("keywords", "update", "AutotargetingBrandOptions"): {
        "status": "missing_followup",
        "issue": "#244",
        "note": "Keyword autotargeting brand options have no typed update flags.",
    },
    ("keywords", "update", "AutotargetingSettings"): {
        "status": "missing_followup",
        "issue": "#244",
        "note": "Keyword autotargeting settings have no typed update flags.",
    },
    ("ads", "update", "TextAd.VideoExtension"): {
        "status": "missing_followup",
        "issue": "#245",
        "note": "TEXT_AD video extension update is WSDL-supported but absent.",
    },
    ("ads", "update", "TextAd.PriceExtension"): {
        "status": "missing_followup",
        "issue": "#245",
        "note": "TEXT_AD price extension update is WSDL-supported but absent.",
    },
    ("adgroups", "add", "MobileAppAdGroup"): {
        "status": "missing_followup",
        "issue": "#247",
        "note": "Rare ad group subtype block is not exposed by --type.",
    },
    ("adgroups", "add", "DynamicTextFeedAdGroup"): {
        "status": "missing_followup",
        "issue": "#247",
        "note": "Rare ad group subtype block is not exposed by --type.",
    },
    ("adgroups", "add", "CpmBannerKeywordsAdGroup"): {
        "status": "missing_followup",
        "issue": "#247",
        "note": "Rare ad group subtype block is not exposed by --type.",
    },
    ("adgroups", "add", "CpmBannerUserProfileAdGroup"): {
        "status": "missing_followup",
        "issue": "#247",
        "note": "Rare ad group subtype block is not exposed by --type.",
    },
    ("adgroups", "add", "CpmVideoAdGroup"): {
        "status": "missing_followup",
        "issue": "#247",
        "note": "Rare ad group subtype block is not exposed by --type.",
    },
    ("adgroups", "add", "UnifiedAdGroup"): {
        "status": "missing_followup",
        "issue": "#247",
        "note": "Rare ad group subtype block is not exposed by --type.",
    },
    ("adgroups", "add", "TextAdGroupFeedParams"): {
        "status": "missing_followup",
        "issue": "#247",
        "note": "Rare ad group feed params block has no typed add flags.",
    },
    ("adgroups", "update", "MobileAppAdGroup"): {
        "status": "missing_followup",
        "issue": "#247",
        "note": "Rare ad group subtype block is not exposed by update.",
    },
    ("adgroups", "update", "DynamicTextAdGroup"): {
        "status": "missing_followup",
        "issue": "#247",
        "note": "Dynamic ad group subtype update block has no typed flags.",
    },
    ("adgroups", "update", "DynamicTextFeedAdGroup"): {
        "status": "missing_followup",
        "issue": "#247",
        "note": "Rare ad group subtype block is not exposed by update.",
    },
    ("adgroups", "update", "SmartAdGroup"): {
        "status": "missing_followup",
        "issue": "#247",
        "note": "Smart ad group subtype update block has no typed flags.",
    },
    ("adgroups", "update", "TextAdGroupFeedParams"): {
        "status": "missing_followup",
        "issue": "#247",
        "note": "Rare ad group feed params block has no typed update flags.",
    },
    ("adgroups", "update", "UnifiedAdGroup"): {
        "status": "missing_followup",
        "issue": "#247",
        "note": "Rare ad group subtype block is not exposed by update.",
    },
}


def _click_command(group_name: str, command_name: str):
    group = cli.commands.get(group_name)
    if group is None or not hasattr(group, "commands"):
        return None
    return group.commands.get(command_name)


def _click_required_options(command) -> set[str]:
    required = set()
    for param in command.params:
        if getattr(param, "required", False):
            for opt in getattr(param, "opts", []):
                required.add(opt)
    return required


@pytest.mark.parametrize(
    "command_key",
    sorted(COMMAND_WSDL_MAP),
    ids=lambda val: ".".join(val),
)
def test_wsdl_required_fields_have_cli_options(
    command_key: tuple[str, str],
) -> None:
    cli_group, cli_op = command_key
    api_service, wsdl_op, container = COMMAND_WSDL_MAP[command_key]
    schema = get_operation_request_schema(fetch_wsdl(api_service), wsdl_op)
    container_names = {field["name"] for field in schema.get("fields", [])}
    assert container in container_names, (
        f"{cli_group}.{cli_op}: COMMAND_WSDL_MAP points at container "
        f"{container!r} but the WSDL request schema for "
        f"{api_service}.{wsdl_op} only declares {sorted(container_names)}. "
        f"Fix the mapping or refresh tests/wsdl_cache/{api_service}.xml."
    )
    wsdl_required = get_required_item_fields(schema, container)
    if not wsdl_required:
        pytest.skip(f"{cli_group}.{cli_op}: WSDL declares no required item fields")

    cli_command = _click_command(cli_group, cli_op)
    assert cli_command is not None, f"CLI command not registered: {command_key}"
    cli_required = _click_required_options(cli_command)

    unmapped = [
        field for field in wsdl_required if field not in WSDL_FIELD_TO_CLI_OPTION
    ]
    assert not unmapped, (
        f"{cli_group}.{cli_op}: WSDL required field(s) {unmapped} "
        "have no entry in WSDL_FIELD_TO_CLI_OPTION. "
        "Add the mapping so the gate can check Click coverage."
    )

    missing = []
    for field in wsdl_required:
        expected_opts = WSDL_FIELD_TO_CLI_OPTION[field]
        if expected_opts & cli_required:
            continue
        # Internal-body validation counts as required-ness too. Skip the
        # field if the command is in INTERNAL_VALIDATION; the dedicated
        # ``test_internal_validation_rejects_missing_field`` exercises
        # that the error is actually raised.
        if (cli_group, cli_op, field) in INTERNAL_VALIDATION:
            continue
        missing.append((field, sorted(expected_opts)))

    assert not missing, (
        f"{cli_group}.{cli_op}: WSDL minOccurs=1 fields not marked Click required: "
        f"{missing}. Either add ``required=True`` to the option, "
        "or add a UsageError check in the command body, "
        "or update WSDL_FIELD_TO_CLI_OPTION if the option name differs."
    )


# Smoke-test that the INTERNAL_VALIDATION entries are accurate — running
# the command without the required field actually yields the documented
# error. Without this check a typo in the expected substring would let
# the parity gate falsely pass.
INTERNAL_VALIDATION_PROBES: dict[tuple[str, str, str], list[str]] = {
    ("adimages", "add", "ImageData"): ["adimages", "add", "--name", "X"],
    ("bidmodifiers", "set", "Id"): ["bidmodifiers", "set", "--value", "50"],
    ("bidmodifiers", "set", "BidModifier"): ["bidmodifiers", "set", "--id", "1"],
    ("retargeting", "add", "Rules"): ["retargeting", "add", "--name", "X"],
    ("creatives", "add", "VideoExtensionCreative"): ["creatives", "add"],
    ("keywords", "add", "Keyword"): ["keywords", "add"],
    ("keywords", "add", "AdGroupId"): ["keywords", "add"],
    ("sitelinks", "add", "Sitelinks"): ["sitelinks", "add"],
}


@pytest.mark.parametrize(
    "field_key",
    sorted(INTERNAL_VALIDATION),
    ids=lambda val: ".".join(val[:2]) + "/" + val[2],
)
def test_internal_validation_rejects_missing_field(
    field_key: tuple[str, str, str],
) -> None:
    expected_error = INTERNAL_VALIDATION[field_key]
    argv = INTERNAL_VALIDATION_PROBES[field_key]
    result = CliRunner().invoke(cli, argv + ["--dry-run"])
    assert result.exit_code != 0, (
        f"{'.'.join(field_key[:2])}: invocation {argv} unexpectedly succeeded "
        f"without the field {field_key[2]}. Output: {result.output!r}"
    )
    assert expected_error in result.output, (
        f"{'.'.join(field_key[:2])}: expected error containing "
        f"{expected_error!r} for missing {field_key[2]}, got {result.output!r}"
    )


# ---------------------------------------------------------------------------
# Pattern C2 — optional WSDL fields are visible in the audit
# ---------------------------------------------------------------------------


def _audited_wsdl_paths() -> dict[tuple[str, str], set[str]]:
    paths: dict[tuple[str, str], set[str]] = {}
    for command_key, (api_service, wsdl_op, container) in COMMAND_WSDL_MAP.items():
        schema = get_operation_request_schema(fetch_cached_wsdl(api_service), wsdl_op)
        rows = iter_container_item_fields(
            schema, container, max_depth=OPTIONAL_FIELD_AUDIT_MAX_DEPTH
        )
        paths[command_key] = {row["path"] for row in rows}
    return paths


def test_optional_field_audit_entries_reference_real_wsdl_paths() -> None:
    """Manual #239 follow-up entries must stay tied to real WSDL paths."""
    paths_by_command = _audited_wsdl_paths()
    bad_statuses = []
    stale_entries = []
    missing_issues = []

    for (cli_group, cli_op, wsdl_path), entry in OPTIONAL_FIELD_AUDIT.items():
        status = entry.get("status")
        if status not in OPTIONAL_FIELD_AUDIT_STATUSES:
            bad_statuses.append((cli_group, cli_op, wsdl_path, status))
        if wsdl_path not in paths_by_command.get((cli_group, cli_op), set()):
            stale_entries.append((cli_group, cli_op, wsdl_path))
        if status == "missing_followup":
            issue = entry.get("issue", "")
            if not (issue.startswith("#") and issue[1:].isdigit()):
                missing_issues.append((cli_group, cli_op, wsdl_path, issue))

    assert not bad_statuses, f"Invalid optional-field audit statuses: {bad_statuses}"
    assert (
        not stale_entries
    ), f"Optional-field audit entries no longer in WSDL: {stale_entries}"
    assert not missing_issues, (
        "Optional-field missing_followup entries must link a GitHub issue: "
        f"{missing_issues}"
    )


def test_optional_field_missing_followups_do_not_mask_supported_paths() -> None:
    """A stale missing override must not hide newly implemented typed support."""
    conflicts = []
    for (cli_group, cli_op, audit_path), entry in OPTIONAL_FIELD_AUDIT.items():
        if entry.get("status") != "missing_followup":
            continue
        for support_group, support_op, support_path in OPTIONAL_FIELD_CLI_OPTIONS:
            if (support_group, support_op) != (cli_group, cli_op):
                continue
            if support_path == audit_path or support_path.startswith(f"{audit_path}."):
                conflicts.append(
                    (
                        cli_group,
                        cli_op,
                        audit_path,
                        support_path,
                        entry.get("issue"),
                    )
                )

    assert not conflicts, (
        "Optional-field missing_followup entries mask supported path mappings: "
        f"{conflicts}. Remove the stale follow-up override or do not mark the "
        "path supported."
    )


def test_optional_field_supported_options_reference_click_options() -> None:
    """Path-aware supported entries must point at real Click options."""
    paths_by_command = _audited_wsdl_paths()
    stale_paths = []
    bad_options = []
    for (cli_group, cli_op, wsdl_path), options in OPTIONAL_FIELD_CLI_OPTIONS.items():
        if wsdl_path not in paths_by_command.get((cli_group, cli_op), set()):
            stale_paths.append((cli_group, cli_op, wsdl_path))
        command = _click_command(cli_group, cli_op)
        assert command is not None, f"CLI command not registered: {cli_group}.{cli_op}"
        click_options = {
            opt for param in command.params for opt in getattr(param, "opts", [])
        }
        missing = sorted(options - click_options)
        if missing:
            bad_options.append((cli_group, cli_op, wsdl_path, missing))

    assert not stale_paths, (
        "Optional-field supported entries no longer exist in WSDL: " f"{stale_paths}"
    )
    assert not bad_options, (
        "Optional-field supported entries reference missing Click options: "
        f"{bad_options}"
    )


def test_optional_field_default_followups_reference_issues() -> None:
    """Default missing classifications must be tied to real follow-up ids."""
    bad_defaults = []
    for command_key, entry in OPTIONAL_FIELD_DEFAULT_FOLLOWUPS.items():
        if command_key not in COMMAND_WSDL_MAP:
            bad_defaults.append((command_key, "not in COMMAND_WSDL_MAP"))
            continue
        issue = entry.get("issue", "")
        if not (issue.startswith("#") and issue[1:].isdigit()):
            bad_defaults.append((command_key, issue))

    assert not bad_defaults, (
        "Optional-field default follow-ups must reference command keys and "
        f"GitHub issue ids: {bad_defaults}"
    )


def test_optional_field_audit_imports_are_cache_only(monkeypatch, tmp_path) -> None:
    """Offline gates must fail on missing imported XSDs without network calls."""
    import requests

    network_calls = []

    def fail_network(url, *args, **kwargs):
        network_calls.append(url)
        raise AssertionError(f"Unexpected network call: {url}")

    monkeypatch.setattr(wsdl_coverage, "IMPORTS_CACHE_DIR", tmp_path)
    monkeypatch.setattr(requests, "get", fail_network)
    wsdl_coverage._cached_imported_xsd.cache_clear()
    try:
        with pytest.raises(FileNotFoundError):
            get_operation_request_schema(fetch_cached_wsdl("clients"), "update")
    finally:
        wsdl_coverage._cached_imported_xsd.cache_clear()

    assert not network_calls


def test_optional_field_audit_report_is_current() -> None:
    """The committed soft-audit table must match cached WSDL + audit ledger."""
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_wsdl_optional_field_audit.py",
            "--check",
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Pattern D — strategy enum drift
# ---------------------------------------------------------------------------


def _wsdl_strategy_subtype_names() -> list[str]:
    """Return choice-of-one subtype field names from ``StrategyAddItem``.

    The WSDL declares each per-strategy block as an element whose type
    is ``Strategy*AddItem`` (e.g. ``StrategyAverageCpcAddItem``). Scalar
    fields like ``Name`` / ``CounterIds`` use built-in or shared types,
    so a stable filter is "type name ends with ``AddItem``". This keeps
    the gate honest if Yandex adds a new scalar to ``StrategyAddItem``
    or renames a subtype.
    """
    schema = get_operation_request_schema(fetch_wsdl("strategies"), "add")
    strategies_field = next(
        (f for f in schema["fields"] if f["name"] == "Strategies"), None
    )
    assert strategies_field is not None, (
        "WSDL drift: strategies.add request schema has no top-level "
        "'Strategies' field. Refresh tests/wsdl_cache/strategies.xml "
        "and update the gate."
    )
    return [
        itf["name"]
        for itf in (strategies_field.get("item_fields") or [])
        if (itf.get("type") or "").endswith("AddItem")
    ]


def test_strategy_types_match_wsdl() -> None:
    wsdl_types = set(_wsdl_strategy_subtype_names())
    cli_types = set(STRATEGY_TYPES)
    bogus = cli_types - wsdl_types
    missing = wsdl_types - cli_types
    assert not bogus and not missing, (
        "STRATEGY_TYPES drift from WSDL:\n"
        f"  CLI-only (bogus): {sorted(bogus)}\n"
        f"  WSDL-only (missing): {sorted(missing)}\n"
        "Update direct_cli/commands/strategies.py to match StrategyAddItem."
    )


# ---------------------------------------------------------------------------
# Coverage check — every mutating WRITE_SANDBOX command is accounted for
# ---------------------------------------------------------------------------


def _mutating_commands() -> list[str]:
    """Return WRITE_SANDBOX commands likely to need parity gates.

    The gate is meaningful for ``add``/``update``/``set`` style operations.
    Multi-target setter variants (``set-bids``, ``set-auto``) wrap selection
    criteria differently and are evaluated by separate dry-run tests.
    """
    return [
        cmd
        for cmd in commands_for_category("WRITE_SANDBOX")
        if cmd.split(".", 1)[1] in {"add", "update", "set"}
    ]


def _is_runtime_deprecated(cli_command: str) -> bool:
    """Test whether a CLI command maps to a RUNTIME_DEPRECATED API method.

    ``RUNTIME_DEPRECATED_METHODS`` is keyed by ``(api_service, wsdl_op)``
    while CLI commands use the CLI group name. For groups whose name
    differs from the API service (e.g. CLI ``retargeting`` →
    API ``retargetinglists``) the lookup must go through
    ``CLI_TO_API_SERVICE`` first or it silently misses.
    """
    cli_group, cli_op = cli_command.split(".", 1)
    api_service = CLI_TO_API_SERVICE.get(cli_group, cli_group)
    return (api_service, cli_op) in RUNTIME_DEPRECATED_METHODS


def test_command_wsdl_map_covers_known_mutating_commands() -> None:
    """Force new mutating commands to be evaluated against the parity gate.

    Any ``add``/``update``/``set`` command in ``WRITE_SANDBOX`` that is not
    in ``COMMAND_WSDL_MAP`` slips past the WSDL ↔ CLI parity check.
    """
    declared = {f"{group}.{op}" for group, op in COMMAND_WSDL_MAP}
    relevant = {cmd for cmd in _mutating_commands() if not _is_runtime_deprecated(cmd)}
    missing = sorted(relevant - declared)
    assert not missing, (
        "New mutating commands lack a COMMAND_WSDL_MAP entry:\n"
        f"  {missing}\n"
        "Add (cli_group, cli_op) → (api_service, wsdl_op, container_field)."
    )
