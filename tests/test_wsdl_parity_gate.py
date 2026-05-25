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
    CUSTOM_PERIOD_BUDGET_FIELD_OPTIONS,
    CUSTOM_PERIOD_BUDGET_FLAGS,
    EXPLORATION_BUDGET_FIELD_OPTIONS,
    EXPLORATION_BUDGET_FLAGS,
    EXPLORATION_BUDGET_STRATEGY_TYPES,
    PRIORITY_GOAL_FIELD_OPTIONS,
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
        f"{command_key}: empty payload accepted as no-op. Output: {result.output!r}"
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
        "adgroups.add DYNAMIC_TEXT_FEED_AD_GROUP + --domain-url",
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
            "DYNAMIC_TEXT_FEED_AD_GROUP",
            "--feed-id",
            "170",
            "--domain-url",
            "example.com",
        ],
        "--domain-url",
    ),
    (
        "adgroups.add DYNAMIC_TEXT_FEED_AD_GROUP + --store-url",
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
            "DYNAMIC_TEXT_FEED_AD_GROUP",
            "--feed-id",
            "170",
            "--store-url",
            "https://apps.apple.com/app/id123456789",
        ],
        "--store-url",
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
        f"{probe_id}: incompatible flag silently dropped. Output: {result.output!r}"
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
    "SourceType": {"--url", "--file-feed-path"},  # derived inside the command
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
    ("feeds", "add", "SourceType"): "Provide exactly one of --url or --file-feed-path",
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
    ("adgroups", "add", "DynamicTextFeedAdGroup"): {"--type"},
    ("adgroups", "add", "DynamicTextFeedAdGroup.FeedId"): {"--feed-id"},
    ("adgroups", "add", "DynamicTextFeedAdGroup.AutotargetingCategories"): {
        "--autotargeting-category"
    },
    ("adgroups", "add", "DynamicTextFeedAdGroup.AutotargetingCategories.Category"): {
        "--autotargeting-category"
    },
    ("adgroups", "add", "DynamicTextFeedAdGroup.AutotargetingCategories.Value"): {
        "--autotargeting-category"
    },
    ("adgroups", "add", "CpmBannerKeywordsAdGroup"): {"--type"},
    ("adgroups", "add", "CpmBannerUserProfileAdGroup"): {"--type"},
    ("adgroups", "add", "CpmVideoAdGroup"): {"--type"},
    ("adgroups", "add", "SmartAdGroup"): {"--type"},
    ("adgroups", "add", "SmartAdGroup.FeedId"): {"--feed-id"},
    ("adgroups", "add", "SmartAdGroup.AdTitleSource"): {"--ad-title-source"},
    ("adgroups", "add", "SmartAdGroup.AdBodySource"): {"--ad-body-source"},
    ("adgroups", "add", "UnifiedAdGroup"): {"--type"},
    ("adgroups", "add", "UnifiedAdGroup.OfferRetargeting"): {"--offer-retargeting"},
    ("adgroups", "add", "TextAdGroupFeedParams"): {
        "--feed-id",
        "--feed-category-ids",
    },
    ("adgroups", "add", "TextAdGroupFeedParams.FeedId"): {"--feed-id"},
    ("adgroups", "add", "TextAdGroupFeedParams.FeedCategoryIds"): {
        "--feed-category-ids"
    },
    ("adgroups", "add", "TextAdGroupFeedParams.FeedCategoryIds.Items"): {
        "--feed-category-ids"
    },
    ("adgroups", "add", "MobileAppAdGroup"): {"--type"},
    ("adgroups", "add", "MobileAppAdGroup.StoreUrl"): {"--store-url"},
    ("adgroups", "add", "MobileAppAdGroup.TargetDeviceType"): {"--target-device-types"},
    ("adgroups", "add", "MobileAppAdGroup.TargetCarrier"): {"--target-carrier"},
    ("adgroups", "add", "MobileAppAdGroup.TargetOperatingSystemVersion"): {
        "--target-operating-system-version"
    },
    ("adgroups", "add", "DynamicTextAdGroup.AutotargetingCategories"): {
        "--autotargeting-category"
    },
    ("adgroups", "add", "DynamicTextAdGroup.AutotargetingCategories.Category"): {
        "--autotargeting-category"
    },
    ("adgroups", "add", "DynamicTextAdGroup.AutotargetingCategories.Value"): {
        "--autotargeting-category"
    },
    ("adgroups", "add", "DynamicTextAdGroup.AutotargetingSettings"): {
        "--autotargeting-settings-exact",
        "--autotargeting-settings-without-brands",
    },
    ("adgroups", "add", "DynamicTextAdGroup.AutotargetingSettings.Categories"): {
        "--autotargeting-settings-exact",
        "--autotargeting-settings-narrow",
        "--autotargeting-settings-alternative",
        "--autotargeting-settings-accessory",
        "--autotargeting-settings-broader",
    },
    (
        "adgroups",
        "add",
        "DynamicTextAdGroup.AutotargetingSettings.Categories.Exact",
    ): {"--autotargeting-settings-exact"},
    (
        "adgroups",
        "add",
        "DynamicTextAdGroup.AutotargetingSettings.Categories.Narrow",
    ): {"--autotargeting-settings-narrow"},
    (
        "adgroups",
        "add",
        "DynamicTextAdGroup.AutotargetingSettings.Categories.Alternative",
    ): {"--autotargeting-settings-alternative"},
    (
        "adgroups",
        "add",
        "DynamicTextAdGroup.AutotargetingSettings.Categories.Accessory",
    ): {"--autotargeting-settings-accessory"},
    (
        "adgroups",
        "add",
        "DynamicTextAdGroup.AutotargetingSettings.Categories.Broader",
    ): {"--autotargeting-settings-broader"},
    ("adgroups", "add", "DynamicTextAdGroup.AutotargetingSettings.BrandOptions"): {
        "--autotargeting-settings-without-brands",
        "--autotargeting-settings-with-advertiser-brand",
        "--autotargeting-settings-with-competitors-brand",
    },
    (
        "adgroups",
        "add",
        "DynamicTextAdGroup.AutotargetingSettings.BrandOptions.WithoutBrands",
    ): {"--autotargeting-settings-without-brands"},
    (
        "adgroups",
        "add",
        "DynamicTextAdGroup.AutotargetingSettings.BrandOptions.WithAdvertiserBrand",
    ): {"--autotargeting-settings-with-advertiser-brand"},
    (
        "adgroups",
        "add",
        "DynamicTextAdGroup.AutotargetingSettings.BrandOptions.WithCompetitorsBrand",
    ): {"--autotargeting-settings-with-competitors-brand"},
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
    ("adgroups", "update", "MobileAppAdGroup"): {
        "--target-device-types",
        "--target-carrier",
        "--target-operating-system-version",
    },
    ("adgroups", "update", "MobileAppAdGroup.TargetDeviceType"): {
        "--target-device-types"
    },
    ("adgroups", "update", "MobileAppAdGroup.TargetCarrier"): {"--target-carrier"},
    ("adgroups", "update", "MobileAppAdGroup.TargetOperatingSystemVersion"): {
        "--target-operating-system-version"
    },
    ("adgroups", "update", "DynamicTextAdGroup"): {
        "--domain-url",
        "--autotargeting-category",
        "--autotargeting-settings-exact",
    },
    ("adgroups", "update", "DynamicTextAdGroup.DomainUrl"): {"--domain-url"},
    ("adgroups", "update", "DynamicTextAdGroup.AutotargetingCategories"): {
        "--autotargeting-category"
    },
    ("adgroups", "update", "DynamicTextAdGroup.AutotargetingCategories.Category"): {
        "--autotargeting-category"
    },
    ("adgroups", "update", "DynamicTextAdGroup.AutotargetingCategories.Value"): {
        "--autotargeting-category"
    },
    ("adgroups", "update", "DynamicTextAdGroup.AutotargetingSettings"): {
        "--autotargeting-settings-exact",
        "--autotargeting-settings-without-brands",
    },
    ("adgroups", "update", "DynamicTextAdGroup.AutotargetingSettings.Categories"): {
        "--autotargeting-settings-exact",
        "--autotargeting-settings-narrow",
        "--autotargeting-settings-alternative",
        "--autotargeting-settings-accessory",
        "--autotargeting-settings-broader",
    },
    (
        "adgroups",
        "update",
        "DynamicTextAdGroup.AutotargetingSettings.Categories.Exact",
    ): {"--autotargeting-settings-exact"},
    (
        "adgroups",
        "update",
        "DynamicTextAdGroup.AutotargetingSettings.Categories.Narrow",
    ): {"--autotargeting-settings-narrow"},
    (
        "adgroups",
        "update",
        "DynamicTextAdGroup.AutotargetingSettings.Categories.Alternative",
    ): {"--autotargeting-settings-alternative"},
    (
        "adgroups",
        "update",
        "DynamicTextAdGroup.AutotargetingSettings.Categories.Accessory",
    ): {"--autotargeting-settings-accessory"},
    (
        "adgroups",
        "update",
        "DynamicTextAdGroup.AutotargetingSettings.Categories.Broader",
    ): {"--autotargeting-settings-broader"},
    ("adgroups", "update", "DynamicTextAdGroup.AutotargetingSettings.BrandOptions"): {
        "--autotargeting-settings-without-brands",
        "--autotargeting-settings-with-advertiser-brand",
        "--autotargeting-settings-with-competitors-brand",
    },
    (
        "adgroups",
        "update",
        "DynamicTextAdGroup.AutotargetingSettings.BrandOptions.WithoutBrands",
    ): {"--autotargeting-settings-without-brands"},
    (
        "adgroups",
        "update",
        "DynamicTextAdGroup.AutotargetingSettings.BrandOptions.WithAdvertiserBrand",
    ): {"--autotargeting-settings-with-advertiser-brand"},
    (
        "adgroups",
        "update",
        "DynamicTextAdGroup.AutotargetingSettings.BrandOptions.WithCompetitorsBrand",
    ): {"--autotargeting-settings-with-competitors-brand"},
    ("adgroups", "update", "DynamicTextFeedAdGroup"): {"--dynamic-feed"},
    ("adgroups", "update", "DynamicTextFeedAdGroup.AutotargetingCategories"): {
        "--autotargeting-category"
    },
    (
        "adgroups",
        "update",
        "DynamicTextFeedAdGroup.AutotargetingCategories.Category",
    ): {"--autotargeting-category"},
    (
        "adgroups",
        "update",
        "DynamicTextFeedAdGroup.AutotargetingCategories.Value",
    ): {"--autotargeting-category"},
    ("adgroups", "update", "SmartAdGroup"): {
        "--ad-title-source",
        "--ad-body-source",
    },
    ("adgroups", "update", "SmartAdGroup.AdTitleSource"): {"--ad-title-source"},
    ("adgroups", "update", "SmartAdGroup.AdBodySource"): {"--ad-body-source"},
    ("adgroups", "update", "UnifiedAdGroup"): {"--offer-retargeting"},
    ("adgroups", "update", "UnifiedAdGroup.OfferRetargeting"): {"--offer-retargeting"},
    ("adgroups", "update", "TextAdGroupFeedParams"): {
        "--feed-id",
        "--feed-category-ids",
    },
    ("adgroups", "update", "TextAdGroupFeedParams.FeedId"): {"--feed-id"},
    ("adgroups", "update", "TextAdGroupFeedParams.FeedCategoryIds"): {
        "--feed-category-ids"
    },
    ("adgroups", "update", "TextAdGroupFeedParams.FeedCategoryIds.Items"): {
        "--feed-category-ids"
    },
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
    ("ads", "add", "TextAd.FinalUrl"): {"--final-url"},
    ("ads", "add", "TextAd.VideoExtension"): {"--video-extension-creative-id"},
    ("ads", "add", "TextAd.VideoExtension.CreativeId"): {
        "--video-extension-creative-id"
    },
    ("ads", "add", "TextAd.PriceExtension"): {
        "--price-extension-price",
        "--price-extension-old-price",
        "--price-extension-price-qualifier",
        "--price-extension-price-currency",
    },
    ("ads", "add", "TextAd.PriceExtension.Price"): {"--price-extension-price"},
    ("ads", "add", "TextAd.PriceExtension.OldPrice"): {"--price-extension-old-price"},
    ("ads", "add", "TextAd.PriceExtension.PriceQualifier"): {
        "--price-extension-price-qualifier"
    },
    ("ads", "add", "TextAd.PriceExtension.PriceCurrency"): {
        "--price-extension-price-currency"
    },
    ("ads", "add", "TextAd.BusinessId"): {"--business-id"},
    ("ads", "add", "TextAd.PreferVCardOverBusiness"): {"--prefer-vcard-over-business"},
    ("ads", "add", "TextAd.ErirAdDescription"): {"--erir-ad-description"},
    ("ads", "add", "DynamicTextAd"): {"--type"},
    ("ads", "add", "DynamicTextAd.VCardId"): {"--vcard-id"},
    ("ads", "add", "DynamicTextAd.AdImageHash"): {"--image-hash"},
    ("ads", "add", "DynamicTextAd.SitelinkSetId"): {"--sitelink-set-id"},
    ("ads", "add", "DynamicTextAd.AdExtensionIds"): {"--ad-extensions"},
    ("ads", "add", "DynamicTextAd.Text"): {"--text"},
    ("ads", "add", "MobileAppAd"): {"--type"},
    ("ads", "add", "MobileAppAd.AdImageHash"): {"--image-hash"},
    ("ads", "add", "MobileAppAd.Text"): {"--text"},
    ("ads", "add", "MobileAppAd.Title"): {"--title"},
    ("ads", "add", "MobileAppAd.TrackingUrl"): {"--tracking-url"},
    ("ads", "add", "MobileAppAd.Action"): {"--action"},
    ("ads", "add", "MobileAppAd.Features"): {"--mobile-app-feature"},
    ("ads", "add", "MobileAppAd.Features.Feature"): {"--mobile-app-feature"},
    ("ads", "add", "MobileAppAd.Features.Enabled"): {"--mobile-app-feature"},
    ("ads", "add", "MobileAppAd.AgeLabel"): {"--age-label"},
    ("ads", "add", "MobileAppAd.VideoExtension"): {"--video-extension-creative-id"},
    ("ads", "add", "MobileAppAd.VideoExtension.CreativeId"): {
        "--video-extension-creative-id"
    },
    ("ads", "add", "MobileAppAd.ErirAdDescription"): {"--erir-ad-description"},
    ("ads", "add", "MobileAppImageAd"): {"--type"},
    ("ads", "add", "MobileAppImageAd.AdImageHash"): {"--image-hash"},
    ("ads", "add", "MobileAppImageAd.ErirAdDescription"): {"--erir-ad-description"},
    ("ads", "add", "MobileAppImageAd.TrackingUrl"): {"--tracking-url"},
    ("ads", "add", "TextImageAd"): {"--type"},
    ("ads", "add", "TextImageAd.AdImageHash"): {"--image-hash"},
    ("ads", "add", "TextImageAd.ErirAdDescription"): {"--erir-ad-description"},
    ("ads", "add", "TextImageAd.FinalUrl"): {"--final-url"},
    ("ads", "add", "TextImageAd.Href"): {"--href"},
    ("ads", "add", "TextImageAd.TurboPageId"): {"--turbo-page-id"},
    ("ads", "add", "ResponsiveAd"): {"--type"},
    ("ads", "add", "ResponsiveAd.Texts"): {"--texts"},
    ("ads", "add", "ResponsiveAd.Titles"): {"--titles"},
    ("ads", "add", "ResponsiveAd.AdImageHashes"): {"--image-hashes"},
    ("ads", "add", "ResponsiveAd.VideoExtensionIds"): {"--video-extension-ids"},
    ("ads", "add", "ResponsiveAd.Href"): {"--href"},
    ("ads", "add", "ResponsiveAd.AgeLabel"): {"--age-label"},
    ("ads", "add", "ResponsiveAd.DisplayUrlPath"): {"--display-url-path"},
    ("ads", "add", "ResponsiveAd.SitelinkSetId"): {"--sitelink-set-id"},
    ("ads", "add", "ResponsiveAd.AdExtensionIds"): {"--ad-extensions"},
    ("ads", "add", "ResponsiveAd.PriceExtension"): {
        "--price-extension-price",
        "--price-extension-old-price",
        "--price-extension-price-qualifier",
        "--price-extension-price-currency",
    },
    ("ads", "add", "ResponsiveAd.PriceExtension.Price"): {"--price-extension-price"},
    ("ads", "add", "ResponsiveAd.PriceExtension.OldPrice"): {
        "--price-extension-old-price"
    },
    ("ads", "add", "ResponsiveAd.PriceExtension.PriceQualifier"): {
        "--price-extension-price-qualifier"
    },
    ("ads", "add", "ResponsiveAd.PriceExtension.PriceCurrency"): {
        "--price-extension-price-currency"
    },
    ("ads", "add", "ResponsiveAd.BusinessId"): {"--business-id"},
    ("ads", "add", "ResponsiveAd.ErirAdDescription"): {"--erir-ad-description"},
    ("ads", "add", "ShoppingAd"): {"--type"},
    ("ads", "add", "ShoppingAd.SitelinkSetId"): {"--sitelink-set-id"},
    ("ads", "add", "ShoppingAd.AdExtensionIds"): {"--ad-extensions"},
    ("ads", "add", "ShoppingAd.BusinessId"): {"--business-id"},
    ("ads", "add", "ShoppingAd.FeedId"): {"--feed-id"},
    ("ads", "add", "ShoppingAd.FeedFilterConditions"): {"--feed-filter-condition"},
    ("ads", "add", "ShoppingAd.FeedFilterConditions.Operand"): {
        "--feed-filter-condition"
    },
    ("ads", "add", "ShoppingAd.FeedFilterConditions.Operator"): {
        "--feed-filter-condition"
    },
    ("ads", "add", "ShoppingAd.FeedFilterConditions.Arguments"): {
        "--feed-filter-condition"
    },
    ("ads", "add", "ShoppingAd.TitleSources"): {"--title-sources"},
    ("ads", "add", "ShoppingAd.TextSources"): {"--text-sources"},
    ("ads", "add", "ShoppingAd.DefaultTexts"): {"--default-texts"},
    ("ads", "add", "ListingAd"): {"--type"},
    ("ads", "add", "ListingAd.SitelinkSetId"): {"--sitelink-set-id"},
    ("ads", "add", "ListingAd.AdExtensionIds"): {"--ad-extensions"},
    ("ads", "add", "ListingAd.BusinessId"): {"--business-id"},
    ("ads", "add", "ListingAd.FeedId"): {"--feed-id"},
    ("ads", "add", "ListingAd.FeedFilterConditions"): {"--feed-filter-condition"},
    ("ads", "add", "ListingAd.FeedFilterConditions.Operand"): {
        "--feed-filter-condition"
    },
    ("ads", "add", "ListingAd.FeedFilterConditions.Operator"): {
        "--feed-filter-condition"
    },
    ("ads", "add", "ListingAd.FeedFilterConditions.Arguments"): {
        "--feed-filter-condition"
    },
    ("ads", "add", "ListingAd.TitleSources"): {"--title-sources"},
    ("ads", "add", "ListingAd.TextSources"): {"--text-sources"},
    ("ads", "add", "ListingAd.DefaultTexts"): {"--default-texts"},
    ("ads", "add", "TextAdBuilderAd"): {"--type"},
    ("ads", "add", "TextAdBuilderAd.Creative"): {"--creative-id"},
    ("ads", "add", "TextAdBuilderAd.Creative.CreativeId"): {"--creative-id"},
    ("ads", "add", "TextAdBuilderAd.ErirAdDescription"): {"--erir-ad-description"},
    ("ads", "add", "TextAdBuilderAd.FinalUrl"): {"--final-url"},
    ("ads", "add", "TextAdBuilderAd.Href"): {"--href"},
    ("ads", "add", "TextAdBuilderAd.TurboPageId"): {"--turbo-page-id"},
    ("ads", "add", "MobileAppAdBuilderAd"): {"--type"},
    ("ads", "add", "MobileAppAdBuilderAd.Creative"): {"--creative-id"},
    ("ads", "add", "MobileAppAdBuilderAd.Creative.CreativeId"): {"--creative-id"},
    ("ads", "add", "MobileAppAdBuilderAd.ErirAdDescription"): {"--erir-ad-description"},
    ("ads", "add", "MobileAppAdBuilderAd.TrackingUrl"): {"--tracking-url"},
    ("ads", "add", "MobileAppCpcVideoAdBuilderAd"): {"--type"},
    ("ads", "add", "MobileAppCpcVideoAdBuilderAd.Creative"): {"--creative-id"},
    ("ads", "add", "MobileAppCpcVideoAdBuilderAd.Creative.CreativeId"): {
        "--creative-id"
    },
    ("ads", "add", "MobileAppCpcVideoAdBuilderAd.ErirAdDescription"): {
        "--erir-ad-description"
    },
    ("ads", "add", "MobileAppCpcVideoAdBuilderAd.TrackingUrl"): {"--tracking-url"},
    ("ads", "add", "CpmBannerAdBuilderAd"): {"--type"},
    ("ads", "add", "CpmBannerAdBuilderAd.Creative"): {"--creative-id"},
    ("ads", "add", "CpmBannerAdBuilderAd.Creative.CreativeId"): {"--creative-id"},
    ("ads", "add", "CpmBannerAdBuilderAd.ErirAdDescription"): {"--erir-ad-description"},
    ("ads", "add", "CpmBannerAdBuilderAd.Href"): {"--href"},
    ("ads", "add", "CpmBannerAdBuilderAd.TrackingPixels"): {"--tracking-pixels"},
    ("ads", "add", "CpmBannerAdBuilderAd.TrackingPixels.Items"): {"--tracking-pixels"},
    ("ads", "add", "CpmBannerAdBuilderAd.TurboPageId"): {"--turbo-page-id"},
    ("ads", "add", "CpcVideoAdBuilderAd"): {"--type"},
    ("ads", "add", "CpcVideoAdBuilderAd.Creative"): {"--creative-id"},
    ("ads", "add", "CpcVideoAdBuilderAd.Creative.CreativeId"): {"--creative-id"},
    ("ads", "add", "CpcVideoAdBuilderAd.ErirAdDescription"): {"--erir-ad-description"},
    ("ads", "add", "CpcVideoAdBuilderAd.Href"): {"--href"},
    ("ads", "add", "CpcVideoAdBuilderAd.TurboPageId"): {"--turbo-page-id"},
    ("ads", "add", "CpmVideoAdBuilderAd"): {"--type"},
    ("ads", "add", "CpmVideoAdBuilderAd.Creative"): {"--creative-id"},
    ("ads", "add", "CpmVideoAdBuilderAd.Creative.CreativeId"): {"--creative-id"},
    ("ads", "add", "CpmVideoAdBuilderAd.ErirAdDescription"): {"--erir-ad-description"},
    ("ads", "add", "CpmVideoAdBuilderAd.Href"): {"--href"},
    ("ads", "add", "CpmVideoAdBuilderAd.TrackingPixels"): {"--tracking-pixels"},
    ("ads", "add", "CpmVideoAdBuilderAd.TrackingPixels.Items"): {"--tracking-pixels"},
    ("ads", "add", "CpmVideoAdBuilderAd.TurboPageId"): {"--turbo-page-id"},
    ("ads", "add", "SmartAdBuilderAd"): {"--type"},
    ("ads", "add", "SmartAdBuilderAd.LogoExtensionHash"): {"--logo-extension-hash"},
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
    ("ads", "update", "TextAd.CalloutSetting.AdExtensions"): {
        "--callouts-add",
        "--callouts-remove",
        "--callouts-set",
    },
    ("ads", "update", "TextAd.CalloutSetting.AdExtensions.AdExtensionId"): {
        "--callouts-add",
        "--callouts-remove",
        "--callouts-set",
    },
    ("ads", "update", "TextAd.CalloutSetting.AdExtensions.Operation"): {
        "--callouts-add",
        "--callouts-remove",
        "--callouts-set",
    },
    ("ads", "update", "TextAd.FinalUrl"): {"--final-url"},
    ("ads", "update", "TextAd.AgeLabel"): {"--age-label"},
    ("ads", "update", "TextAd.VideoExtension"): {"--video-extension-creative-id"},
    ("ads", "update", "TextAd.VideoExtension.CreativeId"): {
        "--video-extension-creative-id"
    },
    ("ads", "update", "TextAd.PriceExtension"): {
        "--price-extension-price",
        "--price-extension-old-price",
        "--price-extension-price-qualifier",
        "--price-extension-price-currency",
    },
    ("ads", "update", "TextAd.PriceExtension.Price"): {"--price-extension-price"},
    ("ads", "update", "TextAd.PriceExtension.OldPrice"): {
        "--price-extension-old-price"
    },
    ("ads", "update", "TextAd.PriceExtension.PriceQualifier"): {
        "--price-extension-price-qualifier"
    },
    ("ads", "update", "TextAd.PriceExtension.PriceCurrency"): {
        "--price-extension-price-currency"
    },
    ("ads", "update", "TextAd.BusinessId"): {"--business-id"},
    ("ads", "update", "TextAd.PreferVCardOverBusiness"): {
        "--prefer-vcard-over-business"
    },
    ("ads", "update", "TextAd.ErirAdDescription"): {"--erir-ad-description"},
    ("ads", "update", "DynamicTextAd"): {"--type"},
    ("ads", "update", "DynamicTextAd.VCardId"): {"--vcard-id"},
    ("ads", "update", "DynamicTextAd.AdImageHash"): {"--image-hash"},
    ("ads", "update", "DynamicTextAd.SitelinkSetId"): {"--sitelink-set-id"},
    ("ads", "update", "DynamicTextAd.CalloutSetting"): {
        "--callouts-add",
        "--callouts-remove",
        "--callouts-set",
    },
    ("ads", "update", "DynamicTextAd.CalloutSetting.AdExtensions"): {
        "--callouts-add",
        "--callouts-remove",
        "--callouts-set",
    },
    ("ads", "update", "DynamicTextAd.CalloutSetting.AdExtensions.AdExtensionId"): {
        "--callouts-add",
        "--callouts-remove",
        "--callouts-set",
    },
    ("ads", "update", "DynamicTextAd.CalloutSetting.AdExtensions.Operation"): {
        "--callouts-add",
        "--callouts-remove",
        "--callouts-set",
    },
    ("ads", "update", "DynamicTextAd.Text"): {"--text"},
    ("ads", "update", "MobileAppAd"): {"--type"},
    ("ads", "update", "MobileAppAd.AdImageHash"): {"--image-hash"},
    ("ads", "update", "MobileAppAd.Text"): {"--text"},
    ("ads", "update", "MobileAppAd.Title"): {"--title"},
    ("ads", "update", "MobileAppAd.TrackingUrl"): {"--tracking-url"},
    ("ads", "update", "MobileAppAd.Action"): {"--action"},
    ("ads", "update", "MobileAppAd.ErirAdDescription"): {"--erir-ad-description"},
    ("ads", "update", "MobileAppAd.Features"): {"--mobile-app-feature"},
    ("ads", "update", "MobileAppAd.Features.Feature"): {"--mobile-app-feature"},
    ("ads", "update", "MobileAppAd.Features.Enabled"): {"--mobile-app-feature"},
    ("ads", "update", "MobileAppAd.AgeLabel"): {"--age-label"},
    ("ads", "update", "MobileAppAd.VideoExtension"): {"--video-extension-creative-id"},
    ("ads", "update", "MobileAppAd.VideoExtension.CreativeId"): {
        "--video-extension-creative-id"
    },
    ("ads", "update", "TextImageAd"): {"--type"},
    ("ads", "update", "TextImageAd.AdImageHash"): {"--image-hash"},
    ("ads", "update", "TextImageAd.ErirAdDescription"): {"--erir-ad-description"},
    ("ads", "update", "TextImageAd.FinalUrl"): {"--final-url"},
    ("ads", "update", "TextImageAd.Href"): {"--href"},
    ("ads", "update", "TextImageAd.TurboPageId"): {"--turbo-page-id"},
    ("ads", "update", "ResponsiveAd"): {"--type"},
    ("ads", "update", "ResponsiveAd.Texts"): {"--texts"},
    ("ads", "update", "ResponsiveAd.Titles"): {"--titles"},
    ("ads", "update", "ResponsiveAd.AdImageHashes"): {"--image-hashes"},
    ("ads", "update", "ResponsiveAd.AdImageHashes.Items"): {"--image-hashes"},
    ("ads", "update", "ResponsiveAd.VideoExtensionIds"): {"--video-extension-ids"},
    ("ads", "update", "ResponsiveAd.VideoExtensionIds.Items"): {
        "--video-extension-ids"
    },
    ("ads", "update", "ResponsiveAd.SitelinkSetId"): {"--sitelink-set-id"},
    ("ads", "update", "ResponsiveAd.CalloutSetting"): {
        "--callouts-add",
        "--callouts-remove",
        "--callouts-set",
    },
    ("ads", "update", "ResponsiveAd.CalloutSetting.AdExtensions"): {
        "--callouts-add",
        "--callouts-remove",
        "--callouts-set",
    },
    ("ads", "update", "ResponsiveAd.CalloutSetting.AdExtensions.AdExtensionId"): {
        "--callouts-add",
        "--callouts-remove",
        "--callouts-set",
    },
    ("ads", "update", "ResponsiveAd.CalloutSetting.AdExtensions.Operation"): {
        "--callouts-add",
        "--callouts-remove",
        "--callouts-set",
    },
    ("ads", "update", "ResponsiveAd.Href"): {"--href"},
    ("ads", "update", "ResponsiveAd.AgeLabel"): {"--age-label"},
    ("ads", "update", "ResponsiveAd.DisplayUrlPath"): {"--display-url-path"},
    ("ads", "update", "ResponsiveAd.PriceExtension"): {
        "--price-extension-price",
        "--price-extension-old-price",
        "--price-extension-price-qualifier",
        "--price-extension-price-currency",
    },
    ("ads", "update", "ResponsiveAd.PriceExtension.Price"): {"--price-extension-price"},
    ("ads", "update", "ResponsiveAd.PriceExtension.OldPrice"): {
        "--price-extension-old-price"
    },
    ("ads", "update", "ResponsiveAd.PriceExtension.PriceQualifier"): {
        "--price-extension-price-qualifier"
    },
    ("ads", "update", "ResponsiveAd.PriceExtension.PriceCurrency"): {
        "--price-extension-price-currency"
    },
    ("ads", "update", "ResponsiveAd.BusinessId"): {"--business-id"},
    ("ads", "update", "ResponsiveAd.ErirAdDescription"): {"--erir-ad-description"},
    ("ads", "update", "ShoppingAd"): {"--type"},
    ("ads", "update", "ShoppingAd.SitelinkSetId"): {"--sitelink-set-id"},
    ("ads", "update", "ShoppingAd.CalloutSetting"): {
        "--callouts-add",
        "--callouts-remove",
        "--callouts-set",
    },
    ("ads", "update", "ShoppingAd.CalloutSetting.AdExtensions"): {
        "--callouts-add",
        "--callouts-remove",
        "--callouts-set",
    },
    ("ads", "update", "ShoppingAd.CalloutSetting.AdExtensions.AdExtensionId"): {
        "--callouts-add",
        "--callouts-remove",
        "--callouts-set",
    },
    ("ads", "update", "ShoppingAd.CalloutSetting.AdExtensions.Operation"): {
        "--callouts-add",
        "--callouts-remove",
        "--callouts-set",
    },
    ("ads", "update", "ShoppingAd.BusinessId"): {"--business-id"},
    ("ads", "update", "ShoppingAd.FeedFilterConditions"): {"--feed-filter-condition"},
    ("ads", "update", "ShoppingAd.FeedFilterConditions.Items"): {
        "--feed-filter-condition"
    },
    ("ads", "update", "ShoppingAd.FeedFilterConditions.Items.Operand"): {
        "--feed-filter-condition"
    },
    ("ads", "update", "ShoppingAd.FeedFilterConditions.Items.Operator"): {
        "--feed-filter-condition"
    },
    ("ads", "update", "ShoppingAd.FeedFilterConditions.Items.Arguments"): {
        "--feed-filter-condition"
    },
    ("ads", "update", "ShoppingAd.TitleSources"): {"--title-sources"},
    ("ads", "update", "ShoppingAd.TitleSources.Items"): {"--title-sources"},
    ("ads", "update", "ShoppingAd.TextSources"): {"--text-sources"},
    ("ads", "update", "ShoppingAd.TextSources.Items"): {"--text-sources"},
    ("ads", "update", "ShoppingAd.DefaultTexts"): {"--default-texts"},
    ("ads", "update", "ListingAd"): {"--type"},
    ("ads", "update", "ListingAd.SitelinkSetId"): {"--sitelink-set-id"},
    ("ads", "update", "ListingAd.CalloutSetting"): {
        "--callouts-add",
        "--callouts-remove",
        "--callouts-set",
    },
    ("ads", "update", "ListingAd.CalloutSetting.AdExtensions"): {
        "--callouts-add",
        "--callouts-remove",
        "--callouts-set",
    },
    ("ads", "update", "ListingAd.CalloutSetting.AdExtensions.AdExtensionId"): {
        "--callouts-add",
        "--callouts-remove",
        "--callouts-set",
    },
    ("ads", "update", "ListingAd.CalloutSetting.AdExtensions.Operation"): {
        "--callouts-add",
        "--callouts-remove",
        "--callouts-set",
    },
    ("ads", "update", "ListingAd.BusinessId"): {"--business-id"},
    ("ads", "update", "ListingAd.FeedFilterConditions"): {"--feed-filter-condition"},
    ("ads", "update", "ListingAd.FeedFilterConditions.Items"): {
        "--feed-filter-condition"
    },
    ("ads", "update", "ListingAd.FeedFilterConditions.Items.Operand"): {
        "--feed-filter-condition"
    },
    ("ads", "update", "ListingAd.FeedFilterConditions.Items.Operator"): {
        "--feed-filter-condition"
    },
    ("ads", "update", "ListingAd.FeedFilterConditions.Items.Arguments"): {
        "--feed-filter-condition"
    },
    ("ads", "update", "ListingAd.TitleSources"): {"--title-sources"},
    ("ads", "update", "ListingAd.TitleSources.Items"): {"--title-sources"},
    ("ads", "update", "ListingAd.TextSources"): {"--text-sources"},
    ("ads", "update", "ListingAd.TextSources.Items"): {"--text-sources"},
    ("ads", "update", "ListingAd.DefaultTexts"): {"--default-texts"},
    ("ads", "update", "MobileAppCpcVideoAdBuilderAd"): {"--type"},
    ("ads", "update", "MobileAppCpcVideoAdBuilderAd.Creative"): {
        "--creative-id",
        "--creative-erir-ad-description",
    },
    ("ads", "update", "MobileAppCpcVideoAdBuilderAd.Creative.CreativeId"): {
        "--creative-id"
    },
    (
        "ads",
        "update",
        "MobileAppCpcVideoAdBuilderAd.Creative.ErirAdDescription",
    ): {"--creative-erir-ad-description"},
    ("ads", "update", "MobileAppCpcVideoAdBuilderAd.ErirAdDescription"): {
        "--erir-ad-description"
    },
    ("ads", "update", "MobileAppCpcVideoAdBuilderAd.TrackingUrl"): {"--tracking-url"},
    ("ads", "update", "TextAdBuilderAd"): {"--type"},
    ("ads", "update", "TextAdBuilderAd.Creative"): {
        "--creative-id",
        "--creative-erir-ad-description",
    },
    ("ads", "update", "TextAdBuilderAd.Creative.CreativeId"): {"--creative-id"},
    ("ads", "update", "TextAdBuilderAd.Creative.ErirAdDescription"): {
        "--creative-erir-ad-description"
    },
    ("ads", "update", "TextAdBuilderAd.ErirAdDescription"): {"--erir-ad-description"},
    ("ads", "update", "TextAdBuilderAd.FinalUrl"): {"--final-url"},
    ("ads", "update", "TextAdBuilderAd.Href"): {"--href"},
    ("ads", "update", "TextAdBuilderAd.TurboPageId"): {"--turbo-page-id"},
    ("ads", "update", "MobileAppAdBuilderAd"): {"--type"},
    ("ads", "update", "MobileAppAdBuilderAd.Creative"): {
        "--creative-id",
        "--creative-erir-ad-description",
    },
    ("ads", "update", "MobileAppAdBuilderAd.Creative.CreativeId"): {"--creative-id"},
    ("ads", "update", "MobileAppAdBuilderAd.Creative.ErirAdDescription"): {
        "--creative-erir-ad-description"
    },
    ("ads", "update", "MobileAppAdBuilderAd.ErirAdDescription"): {
        "--erir-ad-description"
    },
    ("ads", "update", "MobileAppAdBuilderAd.TrackingUrl"): {"--tracking-url"},
    ("ads", "update", "CpcVideoAdBuilderAd"): {"--type"},
    ("ads", "update", "CpcVideoAdBuilderAd.Creative"): {
        "--creative-id",
        "--creative-erir-ad-description",
    },
    ("ads", "update", "CpcVideoAdBuilderAd.Creative.CreativeId"): {"--creative-id"},
    ("ads", "update", "CpcVideoAdBuilderAd.Creative.ErirAdDescription"): {
        "--creative-erir-ad-description"
    },
    ("ads", "update", "CpcVideoAdBuilderAd.ErirAdDescription"): {
        "--erir-ad-description"
    },
    ("ads", "update", "CpcVideoAdBuilderAd.Href"): {"--href"},
    ("ads", "update", "CpcVideoAdBuilderAd.TurboPageId"): {"--turbo-page-id"},
    ("ads", "update", "CpmBannerAdBuilderAd"): {"--type"},
    ("ads", "update", "CpmBannerAdBuilderAd.Creative"): {
        "--creative-id",
        "--creative-erir-ad-description",
    },
    ("ads", "update", "CpmBannerAdBuilderAd.Creative.CreativeId"): {"--creative-id"},
    ("ads", "update", "CpmBannerAdBuilderAd.Creative.ErirAdDescription"): {
        "--creative-erir-ad-description"
    },
    ("ads", "update", "CpmBannerAdBuilderAd.ErirAdDescription"): {
        "--erir-ad-description"
    },
    ("ads", "update", "CpmBannerAdBuilderAd.Href"): {"--href"},
    ("ads", "update", "CpmBannerAdBuilderAd.TrackingPixels"): {"--tracking-pixels"},
    ("ads", "update", "CpmBannerAdBuilderAd.TrackingPixels.Items"): {
        "--tracking-pixels"
    },
    ("ads", "update", "CpmBannerAdBuilderAd.TurboPageId"): {"--turbo-page-id"},
    ("ads", "update", "CpmVideoAdBuilderAd"): {"--type"},
    ("ads", "update", "CpmVideoAdBuilderAd.Creative"): {
        "--creative-id",
        "--creative-erir-ad-description",
    },
    ("ads", "update", "CpmVideoAdBuilderAd.Creative.CreativeId"): {"--creative-id"},
    ("ads", "update", "CpmVideoAdBuilderAd.Creative.ErirAdDescription"): {
        "--creative-erir-ad-description"
    },
    ("ads", "update", "CpmVideoAdBuilderAd.ErirAdDescription"): {
        "--erir-ad-description"
    },
    ("ads", "update", "CpmVideoAdBuilderAd.Href"): {"--href"},
    ("ads", "update", "CpmVideoAdBuilderAd.TrackingPixels"): {"--tracking-pixels"},
    ("ads", "update", "CpmVideoAdBuilderAd.TrackingPixels.Items"): {
        "--tracking-pixels"
    },
    ("ads", "update", "CpmVideoAdBuilderAd.TurboPageId"): {"--turbo-page-id"},
    ("ads", "update", "MobileAppImageAd"): {"--type"},
    ("ads", "update", "MobileAppImageAd.AdImageHash"): {"--image-hash"},
    ("ads", "update", "MobileAppImageAd.ErirAdDescription"): {"--erir-ad-description"},
    ("ads", "update", "MobileAppImageAd.TrackingUrl"): {"--tracking-url"},
    ("ads", "update", "SmartAdBuilderAd"): {"--type"},
    ("ads", "update", "SmartAdBuilderAd.LogoExtensionHash"): {"--logo-extension-hash"},
    ("ads", "update", "SmartAdBuilderAd.ErirAdDescription"): {"--erir-ad-description"},
    ("campaigns", "add", "DailyBudget"): {"--budget"},
    ("campaigns", "add", "DailyBudget.Amount"): {"--budget"},
    ("campaigns", "add", "DailyBudget.Mode"): {"--budget"},
    ("campaigns", "add", "EndDate"): {"--end-date"},
    ("campaigns", "add", "ClientInfo"): {"--client-info"},
    ("campaigns", "add", "Notification"): {
        "--sms-events",
        "--sms-time-from",
        "--sms-time-to",
        "--notification-email",
        "--notification-check-position-interval",
        "--notification-warning-balance",
        "--notification-send-account-news",
        "--notification-send-warnings",
    },
    ("campaigns", "add", "Notification.SmsSettings"): {
        "--sms-events",
        "--sms-time-from",
        "--sms-time-to",
    },
    ("campaigns", "add", "Notification.SmsSettings.Events"): {"--sms-events"},
    ("campaigns", "add", "Notification.SmsSettings.TimeFrom"): {"--sms-time-from"},
    ("campaigns", "add", "Notification.SmsSettings.TimeTo"): {"--sms-time-to"},
    ("campaigns", "add", "Notification.EmailSettings"): {
        "--notification-email",
        "--notification-check-position-interval",
        "--notification-warning-balance",
        "--notification-send-account-news",
        "--notification-send-warnings",
    },
    ("campaigns", "add", "Notification.EmailSettings.Email"): {"--notification-email"},
    ("campaigns", "add", "Notification.EmailSettings.CheckPositionInterval"): {
        "--notification-check-position-interval"
    },
    ("campaigns", "add", "Notification.EmailSettings.WarningBalance"): {
        "--notification-warning-balance"
    },
    ("campaigns", "add", "Notification.EmailSettings.SendAccountNews"): {
        "--notification-send-account-news"
    },
    ("campaigns", "add", "Notification.EmailSettings.SendWarnings"): {
        "--notification-send-warnings"
    },
    ("campaigns", "add", "TimeZone"): {"--time-zone"},
    ("campaigns", "add", "NegativeKeywords"): {"--negative-keywords"},
    ("campaigns", "add", "NegativeKeywords.Items"): {"--negative-keywords"},
    ("campaigns", "add", "BlockedIps"): {"--blocked-ips"},
    ("campaigns", "add", "BlockedIps.Items"): {"--blocked-ips"},
    ("campaigns", "add", "ExcludedSites"): {"--excluded-sites"},
    ("campaigns", "add", "ExcludedSites.Items"): {"--excluded-sites"},
    ("campaigns", "add", "TimeTargeting"): {
        "--time-targeting-schedule",
        "--consider-working-weekends",
        "--holidays-suspend-on-holidays",
        "--holidays-bid-percent",
        "--holidays-start-hour",
        "--holidays-end-hour",
    },
    ("campaigns", "add", "TimeTargeting.Schedule"): {"--time-targeting-schedule"},
    ("campaigns", "add", "TimeTargeting.Schedule.Items"): {"--time-targeting-schedule"},
    ("campaigns", "add", "TimeTargeting.ConsiderWorkingWeekends"): {
        "--consider-working-weekends"
    },
    ("campaigns", "add", "TimeTargeting.HolidaysSchedule"): {
        "--holidays-suspend-on-holidays",
        "--holidays-bid-percent",
        "--holidays-start-hour",
        "--holidays-end-hour",
    },
    ("campaigns", "add", "TimeTargeting.HolidaysSchedule.SuspendOnHolidays"): {
        "--holidays-suspend-on-holidays"
    },
    ("campaigns", "add", "TimeTargeting.HolidaysSchedule.BidPercent"): {
        "--holidays-bid-percent"
    },
    ("campaigns", "add", "TimeTargeting.HolidaysSchedule.StartHour"): {
        "--holidays-start-hour"
    },
    ("campaigns", "add", "TimeTargeting.HolidaysSchedule.EndHour"): {
        "--holidays-end-hour"
    },
    ("campaigns", "add", "TextCampaign"): {"--type"},
    ("campaigns", "add", "TextCampaign.BiddingStrategy"): {
        "--search-strategy",
        "--network-strategy",
    },
    ("campaigns", "add", "TextCampaign.Settings"): {"--setting"},
    ("campaigns", "add", "TextCampaign.Settings.Option"): {"--setting"},
    ("campaigns", "add", "TextCampaign.Settings.Value"): {"--setting"},
    ("campaigns", "add", "TextCampaign.CounterIds"): {"--counter-ids"},
    ("campaigns", "add", "TextCampaign.CounterIds.Items"): {"--counter-ids"},
    ("campaigns", "add", "TextCampaign.RelevantKeywords"): {
        "--relevant-keywords-budget-percent",
        "--relevant-keywords-mode",
        "--relevant-keywords-optimize-goal-id",
    },
    ("campaigns", "add", "TextCampaign.RelevantKeywords.BudgetPercent"): {
        "--relevant-keywords-budget-percent"
    },
    ("campaigns", "add", "TextCampaign.RelevantKeywords.Mode"): {
        "--relevant-keywords-mode"
    },
    ("campaigns", "add", "TextCampaign.RelevantKeywords.OptimizeGoalId"): {
        "--relevant-keywords-optimize-goal-id"
    },
    ("campaigns", "add", "TextCampaign.PriorityGoals"): {"--priority-goals"},
    ("campaigns", "add", "TextCampaign.PriorityGoals.Items"): {"--priority-goals"},
    ("campaigns", "add", "TextCampaign.PriorityGoals.Items.GoalId"): {
        "--priority-goals"
    },
    ("campaigns", "add", "TextCampaign.PriorityGoals.Items.Value"): {
        "--priority-goals"
    },
    (
        "campaigns",
        "add",
        "TextCampaign.PriorityGoals.Items.IsMetrikaSourceOfValue",
    ): {"--priority-goals"},
    ("campaigns", "add", "TextCampaign.TrackingParams"): {"--tracking-params"},
    ("campaigns", "add", "TextCampaign.AttributionModel"): {"--attribution-model"},
    ("campaigns", "add", "TextCampaign.PackageBiddingStrategy"): {
        "--package-strategy-id",
        "--package-strategy-from-campaign-id",
        "--package-platform-search-result",
        "--package-platform-product-gallery",
        "--package-platform-network",
        "--package-platform-dynamic-places",
    },
    ("campaigns", "add", "TextCampaign.PackageBiddingStrategy.StrategyId"): {
        "--package-strategy-id"
    },
    (
        "campaigns",
        "add",
        "TextCampaign.PackageBiddingStrategy.StrategyFromCampaignId",
    ): {"--package-strategy-from-campaign-id"},
    ("campaigns", "add", "TextCampaign.PackageBiddingStrategy.Platforms"): {
        "--package-platform-search-result",
        "--package-platform-product-gallery",
        "--package-platform-network",
        "--package-platform-dynamic-places",
    },
    (
        "campaigns",
        "add",
        "TextCampaign.PackageBiddingStrategy.Platforms.SearchResult",
    ): {"--package-platform-search-result"},
    (
        "campaigns",
        "add",
        "TextCampaign.PackageBiddingStrategy.Platforms.ProductGallery",
    ): {"--package-platform-product-gallery"},
    ("campaigns", "add", "TextCampaign.PackageBiddingStrategy.Platforms.Network"): {
        "--package-platform-network"
    },
    (
        "campaigns",
        "add",
        "TextCampaign.PackageBiddingStrategy.Platforms.DynamicPlaces",
    ): {"--package-platform-dynamic-places"},
    ("campaigns", "add", "TextCampaign.NegativeKeywordSharedSetIds"): {
        "--negative-keyword-shared-set-ids"
    },
    ("campaigns", "add", "TextCampaign.NegativeKeywordSharedSetIds.Items"): {
        "--negative-keyword-shared-set-ids"
    },
    ("campaigns", "add", "DynamicTextCampaign.BiddingStrategy"): {
        "--search-strategy",
        "--network-strategy",
    },
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
    ("campaigns", "update", "ClientInfo"): {"--client-info"},
    ("campaigns", "update", "Notification"): {
        "--sms-events",
        "--sms-time-from",
        "--sms-time-to",
        "--notification-email",
        "--notification-check-position-interval",
        "--notification-warning-balance",
        "--notification-send-account-news",
        "--notification-send-warnings",
    },
    ("campaigns", "update", "Notification.SmsSettings"): {
        "--sms-events",
        "--sms-time-from",
        "--sms-time-to",
    },
    ("campaigns", "update", "Notification.SmsSettings.Events"): {"--sms-events"},
    ("campaigns", "update", "Notification.SmsSettings.TimeFrom"): {"--sms-time-from"},
    ("campaigns", "update", "Notification.SmsSettings.TimeTo"): {"--sms-time-to"},
    ("campaigns", "update", "Notification.EmailSettings"): {
        "--notification-email",
        "--notification-check-position-interval",
        "--notification-warning-balance",
        "--notification-send-account-news",
        "--notification-send-warnings",
    },
    ("campaigns", "update", "Notification.EmailSettings.Email"): {
        "--notification-email"
    },
    ("campaigns", "update", "Notification.EmailSettings.CheckPositionInterval"): {
        "--notification-check-position-interval"
    },
    ("campaigns", "update", "Notification.EmailSettings.WarningBalance"): {
        "--notification-warning-balance"
    },
    ("campaigns", "update", "Notification.EmailSettings.SendAccountNews"): {
        "--notification-send-account-news"
    },
    ("campaigns", "update", "Notification.EmailSettings.SendWarnings"): {
        "--notification-send-warnings"
    },
    ("campaigns", "update", "TimeZone"): {"--time-zone"},
    ("campaigns", "update", "NegativeKeywords"): {"--negative-keywords"},
    ("campaigns", "update", "NegativeKeywords.Items"): {"--negative-keywords"},
    ("campaigns", "update", "BlockedIps"): {"--blocked-ips"},
    ("campaigns", "update", "BlockedIps.Items"): {"--blocked-ips"},
    ("campaigns", "update", "ExcludedSites"): {"--excluded-sites"},
    ("campaigns", "update", "ExcludedSites.Items"): {"--excluded-sites"},
    ("campaigns", "update", "TimeTargeting"): {
        "--time-targeting-schedule",
        "--consider-working-weekends",
        "--holidays-suspend-on-holidays",
        "--holidays-bid-percent",
        "--holidays-start-hour",
        "--holidays-end-hour",
    },
    ("campaigns", "update", "TimeTargeting.Schedule"): {"--time-targeting-schedule"},
    ("campaigns", "update", "TimeTargeting.Schedule.Items"): {
        "--time-targeting-schedule"
    },
    ("campaigns", "update", "TimeTargeting.ConsiderWorkingWeekends"): {
        "--consider-working-weekends"
    },
    ("campaigns", "update", "TimeTargeting.HolidaysSchedule"): {
        "--holidays-suspend-on-holidays",
        "--holidays-bid-percent",
        "--holidays-start-hour",
        "--holidays-end-hour",
    },
    ("campaigns", "update", "TimeTargeting.HolidaysSchedule.SuspendOnHolidays"): {
        "--holidays-suspend-on-holidays"
    },
    ("campaigns", "update", "TimeTargeting.HolidaysSchedule.BidPercent"): {
        "--holidays-bid-percent"
    },
    ("campaigns", "update", "TimeTargeting.HolidaysSchedule.StartHour"): {
        "--holidays-start-hour"
    },
    ("campaigns", "update", "TimeTargeting.HolidaysSchedule.EndHour"): {
        "--holidays-end-hour"
    },
    ("campaigns", "update", "TextCampaign"): {"--type"},
    ("campaigns", "update", "TextCampaign.Settings"): {"--setting"},
    ("campaigns", "update", "TextCampaign.Settings.Option"): {"--setting"},
    ("campaigns", "update", "TextCampaign.Settings.Value"): {"--setting"},
    ("campaigns", "update", "TextCampaign.CounterIds"): {"--counter-ids"},
    ("campaigns", "update", "TextCampaign.CounterIds.Items"): {"--counter-ids"},
    ("campaigns", "update", "TextCampaign.RelevantKeywords"): {
        "--relevant-keywords-budget-percent",
        "--relevant-keywords-mode",
        "--relevant-keywords-optimize-goal-id",
    },
    ("campaigns", "update", "TextCampaign.RelevantKeywords.BudgetPercent"): {
        "--relevant-keywords-budget-percent"
    },
    ("campaigns", "update", "TextCampaign.RelevantKeywords.Mode"): {
        "--relevant-keywords-mode"
    },
    ("campaigns", "update", "TextCampaign.RelevantKeywords.OptimizeGoalId"): {
        "--relevant-keywords-optimize-goal-id"
    },
    ("campaigns", "update", "TextCampaign.PriorityGoals"): {"--priority-goals"},
    ("campaigns", "update", "TextCampaign.PriorityGoals.Items"): {"--priority-goals"},
    ("campaigns", "update", "TextCampaign.PriorityGoals.Items.GoalId"): {
        "--priority-goals"
    },
    ("campaigns", "update", "TextCampaign.PriorityGoals.Items.Value"): {
        "--priority-goals"
    },
    (
        "campaigns",
        "update",
        "TextCampaign.PriorityGoals.Items.IsMetrikaSourceOfValue",
    ): {"--priority-goals"},
    ("campaigns", "update", "TextCampaign.PriorityGoals.Items.Operation"): {
        "--priority-goals"
    },
    ("campaigns", "update", "TextCampaign.TrackingParams"): {"--tracking-params"},
    ("campaigns", "update", "TextCampaign.AttributionModel"): {"--attribution-model"},
    ("campaigns", "update", "TextCampaign.PackageBiddingStrategy"): {
        "--package-strategy-id",
        "--package-strategy-from-campaign-id",
        "--package-platform-search-result",
        "--package-platform-product-gallery",
        "--package-platform-network",
        "--package-platform-dynamic-places",
    },
    ("campaigns", "update", "TextCampaign.PackageBiddingStrategy.StrategyId"): {
        "--package-strategy-id"
    },
    (
        "campaigns",
        "update",
        "TextCampaign.PackageBiddingStrategy.StrategyFromCampaignId",
    ): {"--package-strategy-from-campaign-id"},
    ("campaigns", "update", "TextCampaign.PackageBiddingStrategy.Platforms"): {
        "--package-platform-search-result",
        "--package-platform-product-gallery",
        "--package-platform-network",
        "--package-platform-dynamic-places",
    },
    (
        "campaigns",
        "update",
        "TextCampaign.PackageBiddingStrategy.Platforms.SearchResult",
    ): {"--package-platform-search-result"},
    (
        "campaigns",
        "update",
        "TextCampaign.PackageBiddingStrategy.Platforms.ProductGallery",
    ): {"--package-platform-product-gallery"},
    (
        "campaigns",
        "update",
        "TextCampaign.PackageBiddingStrategy.Platforms.Network",
    ): {"--package-platform-network"},
    (
        "campaigns",
        "update",
        "TextCampaign.PackageBiddingStrategy.Platforms.DynamicPlaces",
    ): {"--package-platform-dynamic-places"},
    ("campaigns", "update", "TextCampaign.NegativeKeywordSharedSetIds"): {
        "--negative-keyword-shared-set-ids"
    },
    ("campaigns", "update", "TextCampaign.NegativeKeywordSharedSetIds.Items"): {
        "--negative-keyword-shared-set-ids"
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
    ("clients", "update", "Notification.EmailSubscriptions.Option"): {
        "--email-subscription"
    },
    ("clients", "update", "Notification.EmailSubscriptions.Value"): {
        "--email-subscription"
    },
    ("clients", "update", "Notification.Lang"): {"--notification-lang"},
    ("clients", "update", "Settings"): {"--setting"},
    ("clients", "update", "Settings.Option"): {"--setting"},
    ("clients", "update", "Settings.Value"): {"--setting"},
    ("clients", "update", "TinInfo"): {"--tin", "--tin-type"},
    ("clients", "update", "TinInfo.TinType"): {"--tin-type"},
    ("clients", "update", "TinInfo.Tin"): {"--tin"},
    ("clients", "update", "ErirAttributes"): {
        "--erir-organization-name",
        "--erir-organization-kpp",
        "--erir-organization-epay-number",
        "--erir-organization-reg-number",
        "--erir-organization-oksm-number",
        "--erir-organization-okved-code",
        "--erir-contract-number",
        "--erir-contract-date",
        "--erir-contract-type",
        "--erir-contract-action-type",
        "--erir-contract-subject-type",
        "--erir-contract-is-agency-payment",
        "--erir-contract-price-amount",
        "--erir-contract-price-including-vat",
        "--erir-contragent-name",
        "--erir-contragent-kpp",
        "--erir-contragent-phone",
        "--erir-contragent-epay-number",
        "--erir-contragent-reg-number",
        "--erir-contragent-oksm-number",
        "--erir-contragent-tin-type",
        "--erir-contragent-tin",
    },
    ("clients", "update", "ErirAttributes.Organization"): {
        "--erir-organization-name",
        "--erir-organization-kpp",
        "--erir-organization-epay-number",
        "--erir-organization-reg-number",
        "--erir-organization-oksm-number",
        "--erir-organization-okved-code",
    },
    ("clients", "update", "ErirAttributes.Organization.Name"): {
        "--erir-organization-name"
    },
    ("clients", "update", "ErirAttributes.Organization.EpayNumber"): {
        "--erir-organization-epay-number"
    },
    ("clients", "update", "ErirAttributes.Organization.RegNumber"): {
        "--erir-organization-reg-number"
    },
    ("clients", "update", "ErirAttributes.Organization.OksmNumber"): {
        "--erir-organization-oksm-number"
    },
    ("clients", "update", "ErirAttributes.Organization.OkvedCode"): {
        "--erir-organization-okved-code"
    },
    ("clients", "update", "ErirAttributes.Contract"): {
        "--erir-contract-number",
        "--erir-contract-date",
        "--erir-contract-type",
        "--erir-contract-action-type",
        "--erir-contract-subject-type",
        "--erir-contract-is-agency-payment",
        "--erir-contract-price-amount",
        "--erir-contract-price-including-vat",
    },
    ("clients", "update", "ErirAttributes.Contract.Number"): {"--erir-contract-number"},
    ("clients", "update", "ErirAttributes.Contract.Date"): {"--erir-contract-date"},
    ("clients", "update", "ErirAttributes.Contract.Type"): {"--erir-contract-type"},
    ("clients", "update", "ErirAttributes.Contract.ActionType"): {
        "--erir-contract-action-type"
    },
    ("clients", "update", "ErirAttributes.Contract.SubjectType"): {
        "--erir-contract-subject-type"
    },
    ("clients", "update", "ErirAttributes.Contract.IsAgencyPayment"): {
        "--erir-contract-is-agency-payment"
    },
    ("clients", "update", "ErirAttributes.Contract.Price"): {
        "--erir-contract-price-amount",
        "--erir-contract-price-including-vat",
    },
    ("clients", "update", "ErirAttributes.Contract.Price.Amount"): {
        "--erir-contract-price-amount"
    },
    ("clients", "update", "ErirAttributes.Contract.Price.IncludingVat"): {
        "--erir-contract-price-including-vat"
    },
    ("clients", "update", "ErirAttributes.Contragent"): {
        "--erir-contragent-name",
        "--erir-contragent-kpp",
        "--erir-contragent-phone",
        "--erir-contragent-epay-number",
        "--erir-contragent-reg-number",
        "--erir-contragent-oksm-number",
        "--erir-contragent-tin-type",
        "--erir-contragent-tin",
    },
    ("clients", "update", "ErirAttributes.Contragent.Name"): {"--erir-contragent-name"},
    ("clients", "update", "ErirAttributes.Contragent.Phone"): {
        "--erir-contragent-phone"
    },
    ("clients", "update", "ErirAttributes.Contragent.EpayNumber"): {
        "--erir-contragent-epay-number"
    },
    ("clients", "update", "ErirAttributes.Contragent.RegNumber"): {
        "--erir-contragent-reg-number"
    },
    ("clients", "update", "ErirAttributes.Contragent.OksmNumber"): {
        "--erir-contragent-oksm-number"
    },
    ("clients", "update", "ErirAttributes.Contragent.TinInfo"): {
        "--erir-contragent-tin-type",
        "--erir-contragent-tin",
    },
    ("clients", "update", "ErirAttributes.Contragent.TinInfo.TinType"): {
        "--erir-contragent-tin-type"
    },
    ("clients", "update", "ErirAttributes.Contragent.TinInfo.Tin"): {
        "--erir-contragent-tin"
    },
    ("dynamicads", "add", "Conditions"): {"--condition"},
    ("dynamicads", "add", "Conditions.Operand"): {"--condition"},
    ("dynamicads", "add", "Conditions.Operator"): {"--condition"},
    ("dynamicads", "add", "Conditions.Arguments"): {"--condition"},
    ("dynamicads", "add", "Bid"): {"--bid"},
    ("dynamicads", "add", "ContextBid"): {"--context-bid"},
    ("dynamicads", "add", "StrategyPriority"): {"--priority"},
    ("dynamicfeedadtargets", "add", "Conditions"): {"--condition"},
    ("dynamicfeedadtargets", "add", "Conditions.Items"): {"--condition"},
    ("dynamicfeedadtargets", "add", "Conditions.Items.Operand"): {"--condition"},
    ("dynamicfeedadtargets", "add", "Conditions.Items.Operator"): {"--condition"},
    ("dynamicfeedadtargets", "add", "Conditions.Items.Arguments"): {"--condition"},
    ("dynamicfeedadtargets", "add", "Bid"): {"--bid"},
    ("dynamicfeedadtargets", "add", "ContextBid"): {"--context-bid"},
    ("dynamicfeedadtargets", "add", "AvailableItemsOnly"): {"--available-items-only"},
    ("feeds", "add", "UrlFeed"): {"--url"},
    ("feeds", "add", "UrlFeed.Url"): {"--url"},
    ("feeds", "add", "UrlFeed.RemoveUtmTags"): {"--remove-utm-tags"},
    ("feeds", "add", "UrlFeed.Login"): {"--feed-login"},
    ("feeds", "add", "UrlFeed.Password"): {"--feed-password"},
    ("feeds", "add", "FileFeed"): {"--file-feed-path"},
    ("feeds", "add", "FileFeed.Data"): {"--file-feed-path"},
    ("feeds", "add", "FileFeed.Filename"): {
        "--file-feed-path",
        "--file-feed-filename",
    },
    ("feeds", "update", "Name"): {"--name"},
    ("feeds", "update", "UrlFeed"): {"--url"},
    ("feeds", "update", "UrlFeed.Url"): {"--url"},
    ("feeds", "update", "UrlFeed.RemoveUtmTags"): {"--remove-utm-tags"},
    ("feeds", "update", "UrlFeed.Login"): {"--feed-login", "--clear-feed-login"},
    ("feeds", "update", "UrlFeed.Password"): {
        "--feed-password",
        "--clear-feed-password",
    },
    ("feeds", "update", "FileFeed"): {"--file-feed-path"},
    ("feeds", "update", "FileFeed.Data"): {"--file-feed-path"},
    ("feeds", "update", "FileFeed.Filename"): {
        "--file-feed-path",
        "--file-feed-filename",
    },
    ("creatives", "add", "VideoExtensionCreative.VideoId"): {"--video-id"},
    ("keywords", "add", "Bid"): {"--bid"},
    ("keywords", "add", "AutotargetingSearchBidIsAuto"): {
        "--autotargeting-search-bid-is-auto"
    },
    ("keywords", "add", "ContextBid"): {"--context-bid"},
    ("keywords", "add", "StrategyPriority"): {"--priority"},
    ("keywords", "add", "AutotargetingCategories"): {"--autotargeting-category"},
    ("keywords", "add", "AutotargetingCategories.Category"): {
        "--autotargeting-category"
    },
    ("keywords", "add", "AutotargetingCategories.Value"): {"--autotargeting-category"},
    ("keywords", "add", "AutotargetingBrandOptions"): {"--autotargeting-brand-option"},
    ("keywords", "add", "AutotargetingBrandOptions.Option"): {
        "--autotargeting-brand-option"
    },
    ("keywords", "add", "AutotargetingBrandOptions.Value"): {
        "--autotargeting-brand-option"
    },
    ("keywords", "add", "AutotargetingSettings"): {
        "--autotargeting-settings-exact",
        "--autotargeting-settings-without-brands",
    },
    ("keywords", "add", "AutotargetingSettings.Categories"): {
        "--autotargeting-settings-exact",
        "--autotargeting-settings-narrow",
        "--autotargeting-settings-alternative",
        "--autotargeting-settings-accessory",
        "--autotargeting-settings-broader",
    },
    ("keywords", "add", "AutotargetingSettings.Categories.Exact"): {
        "--autotargeting-settings-exact"
    },
    ("keywords", "add", "AutotargetingSettings.Categories.Narrow"): {
        "--autotargeting-settings-narrow"
    },
    ("keywords", "add", "AutotargetingSettings.Categories.Alternative"): {
        "--autotargeting-settings-alternative"
    },
    ("keywords", "add", "AutotargetingSettings.Categories.Accessory"): {
        "--autotargeting-settings-accessory"
    },
    ("keywords", "add", "AutotargetingSettings.Categories.Broader"): {
        "--autotargeting-settings-broader"
    },
    ("keywords", "add", "AutotargetingSettings.BrandOptions"): {
        "--autotargeting-settings-without-brands",
        "--autotargeting-settings-with-advertiser-brand",
        "--autotargeting-settings-with-competitors-brand",
    },
    ("keywords", "add", "AutotargetingSettings.BrandOptions.WithoutBrands"): {
        "--autotargeting-settings-without-brands"
    },
    ("keywords", "add", "AutotargetingSettings.BrandOptions.WithAdvertiserBrand"): {
        "--autotargeting-settings-with-advertiser-brand"
    },
    ("keywords", "add", "AutotargetingSettings.BrandOptions.WithCompetitorsBrand"): {
        "--autotargeting-settings-with-competitors-brand"
    },
    ("keywords", "add", "UserParam1"): {"--user-param-1"},
    ("keywords", "add", "UserParam2"): {"--user-param-2"},
    ("keywords", "update", "Keyword"): {"--keyword"},
    ("keywords", "update", "UserParam1"): {"--user-param-1"},
    ("keywords", "update", "UserParam2"): {"--user-param-2"},
    ("keywords", "update", "AutotargetingCategories"): {"--autotargeting-category"},
    ("keywords", "update", "AutotargetingCategories.Category"): {
        "--autotargeting-category"
    },
    ("keywords", "update", "AutotargetingCategories.Value"): {
        "--autotargeting-category"
    },
    ("keywords", "update", "AutotargetingBrandOptions"): {
        "--autotargeting-brand-option"
    },
    ("keywords", "update", "AutotargetingBrandOptions.Option"): {
        "--autotargeting-brand-option"
    },
    ("keywords", "update", "AutotargetingBrandOptions.Value"): {
        "--autotargeting-brand-option"
    },
    ("keywords", "update", "AutotargetingSettings"): {
        "--autotargeting-settings-exact",
        "--autotargeting-settings-without-brands",
    },
    ("keywords", "update", "AutotargetingSettings.Categories"): {
        "--autotargeting-settings-exact",
        "--autotargeting-settings-narrow",
        "--autotargeting-settings-alternative",
        "--autotargeting-settings-accessory",
        "--autotargeting-settings-broader",
    },
    ("keywords", "update", "AutotargetingSettings.Categories.Exact"): {
        "--autotargeting-settings-exact"
    },
    ("keywords", "update", "AutotargetingSettings.Categories.Narrow"): {
        "--autotargeting-settings-narrow"
    },
    ("keywords", "update", "AutotargetingSettings.Categories.Alternative"): {
        "--autotargeting-settings-alternative"
    },
    ("keywords", "update", "AutotargetingSettings.Categories.Accessory"): {
        "--autotargeting-settings-accessory"
    },
    ("keywords", "update", "AutotargetingSettings.Categories.Broader"): {
        "--autotargeting-settings-broader"
    },
    ("keywords", "update", "AutotargetingSettings.BrandOptions"): {
        "--autotargeting-settings-without-brands",
        "--autotargeting-settings-with-advertiser-brand",
        "--autotargeting-settings-with-competitors-brand",
    },
    ("keywords", "update", "AutotargetingSettings.BrandOptions.WithoutBrands"): {
        "--autotargeting-settings-without-brands"
    },
    (
        "keywords",
        "update",
        "AutotargetingSettings.BrandOptions.WithAdvertiserBrand",
    ): {"--autotargeting-settings-with-advertiser-brand"},
    (
        "keywords",
        "update",
        "AutotargetingSettings.BrandOptions.WithCompetitorsBrand",
    ): {"--autotargeting-settings-with-competitors-brand"},
    ("negativekeywordsharedsets", "update", "Name"): {"--name"},
    ("negativekeywordsharedsets", "update", "NegativeKeywords"): {"--keywords"},
    ("audiencetargets", "add", "RetargetingListId"): {"--retargeting-list-id"},
    ("audiencetargets", "add", "InterestId"): {"--interest-id"},
    ("audiencetargets", "add", "ContextBid"): {"--bid"},
    ("audiencetargets", "add", "StrategyPriority"): {"--priority"},
    ("bids", "set", "CampaignId"): {"--campaign-id"},
    ("bids", "set", "AdGroupId"): {"--adgroup-id"},
    ("bids", "set", "KeywordId"): {"--keyword-id"},
    ("bids", "set", "Bid"): {"--bid"},
    ("bids", "set", "ContextBid"): {"--context-bid"},
    ("bids", "set", "AutotargetingSearchBidIsAuto"): {
        "--autotargeting-search-bid-is-auto"
    },
    ("bids", "set", "StrategyPriority"): {"--priority"},
    ("keywordbids", "set", "CampaignId"): {"--campaign-id"},
    ("keywordbids", "set", "AdGroupId"): {"--adgroup-id"},
    ("keywordbids", "set", "KeywordId"): {"--keyword-id"},
    ("keywordbids", "set", "SearchBid"): {"--search-bid"},
    ("keywordbids", "set", "AutotargetingSearchBidIsAuto"): {
        "--autotargeting-search-bid-is-auto"
    },
    ("keywordbids", "set", "NetworkBid"): {"--network-bid"},
    ("keywordbids", "set", "StrategyPriority"): {"--priority"},
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
    ("smartadtargets", "add", "Conditions.Items.Operand"): {"--condition"},
    ("smartadtargets", "add", "Conditions.Items.Operator"): {"--condition"},
    ("smartadtargets", "add", "Conditions.Items.Arguments"): {"--condition"},
    ("smartadtargets", "update", "Name"): {"--name"},
    ("smartadtargets", "update", "StrategyPriority"): {"--priority"},
    ("smartadtargets", "update", "AverageCpc"): {"--average-cpc"},
    ("smartadtargets", "update", "AverageCpa"): {"--average-cpa"},
    ("smartadtargets", "update", "Audience"): {"--audience"},
    ("smartadtargets", "update", "AvailableItemsOnly"): {"--available-items-only"},
    ("smartadtargets", "update", "Conditions"): {"--condition"},
    ("smartadtargets", "update", "Conditions.Items"): {"--condition"},
    ("smartadtargets", "update", "Conditions.Items.Operand"): {"--condition"},
    ("smartadtargets", "update", "Conditions.Items.Operator"): {"--condition"},
    ("smartadtargets", "update", "Conditions.Items.Arguments"): {"--condition"},
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
    ("vcards", "add", "InstantMessenger.MessengerLogin"): {"--instant-messenger-login"},
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
    OPTIONAL_FIELD_CLI_OPTIONS[
        ("strategies", "add", f"{strategy_type}.CustomPeriodBudget")
    ] = CUSTOM_PERIOD_BUDGET_FLAGS
    for wsdl_field, flag_name in CUSTOM_PERIOD_BUDGET_FIELD_OPTIONS.items():
        OPTIONAL_FIELD_CLI_OPTIONS[
            ("strategies", "add", f"{strategy_type}.CustomPeriodBudget.{wsdl_field}")
        ] = {flag_name}
    if strategy_type in EXPLORATION_BUDGET_STRATEGY_TYPES:
        OPTIONAL_FIELD_CLI_OPTIONS[
            ("strategies", "add", f"{strategy_type}.ExplorationBudget")
        ] = EXPLORATION_BUDGET_FLAGS
        for wsdl_field, flag_name in EXPLORATION_BUDGET_FIELD_OPTIONS.items():
            OPTIONAL_FIELD_CLI_OPTIONS[
                ("strategies", "add", f"{strategy_type}.ExplorationBudget.{wsdl_field}")
            ] = {flag_name}

OPTIONAL_FIELD_CLI_OPTIONS.update(
    {
        ("strategies", "add", "AttributionModel"): {"--attribution-model"},
        ("strategies", "add", "CounterIds"): {"--counter-ids"},
        ("strategies", "add", "CounterIds.Items"): {"--counter-ids"},
        ("strategies", "add", "PriorityGoals"): {"--priority-goal"},
        ("strategies", "add", "PriorityGoals.Items"): {"--priority-goal"},
        **{
            ("strategies", "add", f"PriorityGoals.Items.{wsdl_field}"): {flag_name}
            for wsdl_field, flag_name in PRIORITY_GOAL_FIELD_OPTIONS.items()
        },
    }
)

for strategy_type, options in STRATEGY_UPDATE_FIELD_OPTIONS.items():
    OPTIONAL_FIELD_CLI_OPTIONS[("strategies", "update", strategy_type)] = {"--type"}
    for param_name, wsdl_field in options.items():
        OPTIONAL_FIELD_CLI_OPTIONS[
            ("strategies", "update", f"{strategy_type}.{wsdl_field}")
        ] = {STRATEGY_FLAG_NAMES[param_name]}
    # Cached strategies WSDL does not expose this update path for bare AverageCpa.
    if strategy_type != "AverageCpa":
        OPTIONAL_FIELD_CLI_OPTIONS[
            ("strategies", "update", f"{strategy_type}.CustomPeriodBudget")
        ] = CUSTOM_PERIOD_BUDGET_FLAGS
        for wsdl_field, flag_name in CUSTOM_PERIOD_BUDGET_FIELD_OPTIONS.items():
            OPTIONAL_FIELD_CLI_OPTIONS[
                (
                    "strategies",
                    "update",
                    f"{strategy_type}.CustomPeriodBudget.{wsdl_field}",
                )
            ] = {flag_name}
    if strategy_type in EXPLORATION_BUDGET_STRATEGY_TYPES:
        OPTIONAL_FIELD_CLI_OPTIONS[
            ("strategies", "update", f"{strategy_type}.ExplorationBudget")
        ] = EXPLORATION_BUDGET_FLAGS
        for wsdl_field, flag_name in EXPLORATION_BUDGET_FIELD_OPTIONS.items():
            OPTIONAL_FIELD_CLI_OPTIONS[
                (
                    "strategies",
                    "update",
                    f"{strategy_type}.ExplorationBudget.{wsdl_field}",
                )
            ] = {flag_name}

OPTIONAL_FIELD_CLI_OPTIONS.update(
    {
        ("strategies", "update", "Name"): {"--name"},
        ("strategies", "update", "AttributionModel"): {"--attribution-model"},
        ("strategies", "update", "CounterIds"): {"--counter-ids"},
        ("strategies", "update", "CounterIds.Items"): {"--counter-ids"},
        ("strategies", "update", "PriorityGoals"): {"--priority-goal"},
        ("strategies", "update", "PriorityGoals.Items"): {"--priority-goal"},
        **{
            ("strategies", "update", f"PriorityGoals.Items.{wsdl_field}"): {flag_name}
            for wsdl_field, flag_name in PRIORITY_GOAL_FIELD_OPTIONS.items()
        },
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
        ("bidmodifiers", "add", "MobileAdjustment.OperatingSystemType"): {
            "--operating-system-type"
        },
        ("bidmodifiers", "add", "TabletAdjustment.OperatingSystemType"): {
            "--operating-system-type"
        },
    }
)

for _campaign_op in ("add", "update"):
    OPTIONAL_FIELD_CLI_OPTIONS[("campaigns", _campaign_op, "UnifiedCampaign")] = {
        "--type"
    }
    for _path in (
        "Settings",
        "Settings.Option",
        "Settings.Value",
    ):
        OPTIONAL_FIELD_CLI_OPTIONS[
            ("campaigns", _campaign_op, f"UnifiedCampaign.{_path}")
        ] = {"--setting"}
    for _path in ("CounterIds", "CounterIds.Items"):
        OPTIONAL_FIELD_CLI_OPTIONS[
            ("campaigns", _campaign_op, f"UnifiedCampaign.{_path}")
        ] = {"--counter-ids"}
    OPTIONAL_FIELD_CLI_OPTIONS[
        ("campaigns", _campaign_op, "UnifiedCampaign.TrackingParams")
    ] = {"--tracking-params"}
    OPTIONAL_FIELD_CLI_OPTIONS[
        ("campaigns", _campaign_op, "UnifiedCampaign.AttributionModel")
    ] = {"--attribution-model"}
    OPTIONAL_FIELD_CLI_OPTIONS[
        ("campaigns", _campaign_op, "UnifiedCampaign.PackageBiddingStrategy")
    ] = {
        "--package-strategy-id",
        "--package-strategy-from-campaign-id",
        "--package-platform-search-result",
        "--package-platform-product-gallery",
        "--package-platform-maps",
        "--package-platform-search-organization-list",
        "--package-platform-network",
        "--package-platform-dynamic-places",
    }
    for _path, _flag in {
        "PackageBiddingStrategy.StrategyId": "--package-strategy-id",
        "PackageBiddingStrategy.StrategyFromCampaignId": (
            "--package-strategy-from-campaign-id"
        ),
        "PackageBiddingStrategy.Platforms.SearchResult": (
            "--package-platform-search-result"
        ),
        "PackageBiddingStrategy.Platforms.ProductGallery": (
            "--package-platform-product-gallery"
        ),
        "PackageBiddingStrategy.Platforms.Maps": "--package-platform-maps",
        "PackageBiddingStrategy.Platforms.SearchOrganizationList": (
            "--package-platform-search-organization-list"
        ),
        "PackageBiddingStrategy.Platforms.Network": "--package-platform-network",
        "PackageBiddingStrategy.Platforms.DynamicPlaces": (
            "--package-platform-dynamic-places"
        ),
    }.items():
        OPTIONAL_FIELD_CLI_OPTIONS[
            ("campaigns", _campaign_op, f"UnifiedCampaign.{_path}")
        ] = {_flag}
    OPTIONAL_FIELD_CLI_OPTIONS[
        ("campaigns", _campaign_op, "UnifiedCampaign.PackageBiddingStrategy.Platforms")
    ] = {
        "--package-platform-search-result",
        "--package-platform-product-gallery",
        "--package-platform-maps",
        "--package-platform-search-organization-list",
        "--package-platform-network",
        "--package-platform-dynamic-places",
    }
    for _path in (
        "NegativeKeywordSharedSetIds",
        "NegativeKeywordSharedSetIds.Items",
    ):
        OPTIONAL_FIELD_CLI_OPTIONS[
            ("campaigns", _campaign_op, f"UnifiedCampaign.{_path}")
        ] = {"--negative-keyword-shared-set-ids"}

for _campaign_op in ("add", "update"):
    OPTIONAL_FIELD_CLI_OPTIONS[("campaigns", _campaign_op, "DynamicTextCampaign")] = {
        "--type"
    }
    for _path in (
        "Settings",
        "Settings.Option",
        "Settings.Value",
    ):
        OPTIONAL_FIELD_CLI_OPTIONS[
            ("campaigns", _campaign_op, f"DynamicTextCampaign.{_path}")
        ] = {"--setting"}
    for _path in (
        "PlacementTypes",
        "PlacementTypes.Type",
        "PlacementTypes.Value",
    ):
        OPTIONAL_FIELD_CLI_OPTIONS[
            ("campaigns", _campaign_op, f"DynamicTextCampaign.{_path}")
        ] = {
            "--dynamic-placement-search-results",
            "--dynamic-placement-product-gallery",
        }
    for _path in ("CounterIds", "CounterIds.Items"):
        OPTIONAL_FIELD_CLI_OPTIONS[
            ("campaigns", _campaign_op, f"DynamicTextCampaign.{_path}")
        ] = {"--counter-ids"}
    OPTIONAL_FIELD_CLI_OPTIONS[
        ("campaigns", _campaign_op, "DynamicTextCampaign.TrackingParams")
    ] = {"--tracking-params"}
    OPTIONAL_FIELD_CLI_OPTIONS[
        ("campaigns", _campaign_op, "DynamicTextCampaign.AttributionModel")
    ] = {"--attribution-model"}
    OPTIONAL_FIELD_CLI_OPTIONS[
        ("campaigns", _campaign_op, "DynamicTextCampaign.PackageBiddingStrategy")
    ] = {"--package-strategy-id", "--package-strategy-from-campaign-id"}
    for _path, _flag in {
        "PackageBiddingStrategy.StrategyId": "--package-strategy-id",
        "PackageBiddingStrategy.StrategyFromCampaignId": (
            "--package-strategy-from-campaign-id"
        ),
    }.items():
        OPTIONAL_FIELD_CLI_OPTIONS[
            ("campaigns", _campaign_op, f"DynamicTextCampaign.{_path}")
        ] = {_flag}
    for _path in (
        "NegativeKeywordSharedSetIds",
        "NegativeKeywordSharedSetIds.Items",
    ):
        OPTIONAL_FIELD_CLI_OPTIONS[
            ("campaigns", _campaign_op, f"DynamicTextCampaign.{_path}")
        ] = {"--negative-keyword-shared-set-ids"}

for _path in (
    "PriorityGoals",
    "PriorityGoals.Items",
    "PriorityGoals.Items.GoalId",
    "PriorityGoals.Items.Value",
    "PriorityGoals.Items.IsMetrikaSourceOfValue",
):
    OPTIONAL_FIELD_CLI_OPTIONS[("campaigns", "add", f"DynamicTextCampaign.{_path}")] = {
        "--priority-goals"
    }

for _path in (
    "PriorityGoals",
    "PriorityGoals.Items",
    "PriorityGoals.Items.GoalId",
    "PriorityGoals.Items.Value",
    "PriorityGoals.Items.IsMetrikaSourceOfValue",
    "PriorityGoals.Items.Operation",
):
    OPTIONAL_FIELD_CLI_OPTIONS[
        ("campaigns", "update", f"DynamicTextCampaign.{_path}")
    ] = {"--priority-goals"}

for _path in (
    "PriorityGoals",
    "PriorityGoals.Items",
    "PriorityGoals.Items.GoalId",
    "PriorityGoals.Items.Value",
    "PriorityGoals.Items.IsMetrikaSourceOfValue",
    "PriorityGoals.Items.Operation",
):
    OPTIONAL_FIELD_CLI_OPTIONS[("campaigns", "update", f"UnifiedCampaign.{_path}")] = {
        "--priority-goals"
    }

for _campaign_op in ("add", "update"):
    OPTIONAL_FIELD_CLI_OPTIONS[("campaigns", _campaign_op, "SmartCampaign")] = {
        "--type"
    }
    for _path in (
        "Settings",
        "Settings.Option",
        "Settings.Value",
    ):
        OPTIONAL_FIELD_CLI_OPTIONS[
            ("campaigns", _campaign_op, f"SmartCampaign.{_path}")
        ] = {"--setting"}
    OPTIONAL_FIELD_CLI_OPTIONS[
        ("campaigns", _campaign_op, "SmartCampaign.CounterId")
    ] = {"--counter-id"}
    OPTIONAL_FIELD_CLI_OPTIONS[
        ("campaigns", _campaign_op, "SmartCampaign.TrackingParams")
    ] = {"--tracking-params"}
    OPTIONAL_FIELD_CLI_OPTIONS[
        ("campaigns", _campaign_op, "SmartCampaign.AttributionModel")
    ] = {"--attribution-model"}
    OPTIONAL_FIELD_CLI_OPTIONS[
        ("campaigns", _campaign_op, "SmartCampaign.PackageBiddingStrategy")
    ] = {
        "--package-strategy-id",
        "--package-strategy-from-campaign-id",
        "--package-platform-search",
        "--package-platform-network",
    }
    for _path, _flag in {
        "PackageBiddingStrategy.StrategyId": "--package-strategy-id",
        "PackageBiddingStrategy.StrategyFromCampaignId": (
            "--package-strategy-from-campaign-id"
        ),
        "PackageBiddingStrategy.Platforms.Search": "--package-platform-search",
        "PackageBiddingStrategy.Platforms.Network": "--package-platform-network",
    }.items():
        OPTIONAL_FIELD_CLI_OPTIONS[
            ("campaigns", _campaign_op, f"SmartCampaign.{_path}")
        ] = {_flag}
    OPTIONAL_FIELD_CLI_OPTIONS[
        ("campaigns", _campaign_op, "SmartCampaign.PackageBiddingStrategy.Platforms")
    ] = {"--package-platform-search", "--package-platform-network"}

for _path in (
    "PriorityGoals",
    "PriorityGoals.Items",
    "PriorityGoals.Items.GoalId",
    "PriorityGoals.Items.Value",
    "PriorityGoals.Items.IsMetrikaSourceOfValue",
    "PriorityGoals.Items.Operation",
):
    OPTIONAL_FIELD_CLI_OPTIONS[("campaigns", "update", f"SmartCampaign.{_path}")] = {
        "--priority-goals"
    }

for _campaign_op in ("add", "update"):
    OPTIONAL_FIELD_CLI_OPTIONS[("campaigns", _campaign_op, "MobileAppCampaign")] = {
        "--type"
    }
    for _path in (
        "Settings",
        "Settings.Option",
        "Settings.Value",
    ):
        OPTIONAL_FIELD_CLI_OPTIONS[
            ("campaigns", _campaign_op, f"MobileAppCampaign.{_path}")
        ] = {"--setting"}
    for _path in (
        "NegativeKeywordSharedSetIds",
        "NegativeKeywordSharedSetIds.Items",
    ):
        OPTIONAL_FIELD_CLI_OPTIONS[
            ("campaigns", _campaign_op, f"MobileAppCampaign.{_path}")
        ] = {"--negative-keyword-shared-set-ids"}

for _campaign_op in ("add", "update"):
    OPTIONAL_FIELD_CLI_OPTIONS[("campaigns", _campaign_op, "CpmBannerCampaign")] = {
        "--type"
    }
    for _path in (
        "Settings",
        "Settings.Option",
        "Settings.Value",
    ):
        OPTIONAL_FIELD_CLI_OPTIONS[
            ("campaigns", _campaign_op, f"CpmBannerCampaign.{_path}")
        ] = {"--setting"}
    for _path in (
        "CounterIds",
        "CounterIds.Items",
    ):
        OPTIONAL_FIELD_CLI_OPTIONS[
            ("campaigns", _campaign_op, f"CpmBannerCampaign.{_path}")
        ] = {"--counter-ids"}
    OPTIONAL_FIELD_CLI_OPTIONS[
        ("campaigns", _campaign_op, "CpmBannerCampaign.FrequencyCap")
    ] = {
        "--frequency-cap-impressions",
        "--frequency-cap-period-days",
        "--frequency-cap-period-all",
    }
    OPTIONAL_FIELD_CLI_OPTIONS[
        ("campaigns", _campaign_op, "CpmBannerCampaign.FrequencyCap.Impressions")
    ] = {"--frequency-cap-impressions"}
    OPTIONAL_FIELD_CLI_OPTIONS[
        ("campaigns", _campaign_op, "CpmBannerCampaign.FrequencyCap.PeriodDays")
    ] = {"--frequency-cap-period-days", "--frequency-cap-period-all"}
    OPTIONAL_FIELD_CLI_OPTIONS[
        ("campaigns", _campaign_op, "CpmBannerCampaign.VideoTarget")
    ] = {"--video-target"}

OPTIONAL_FIELD_DEFAULT_FOLLOWUPS: dict[tuple[str, str], dict[str, str]] = {
    ("ads", "update"): {
        "issue": "#272",
        "note": "ads.update residual optional WSDL path needs typed support or N/A.",
    },
    ("audiencetargets", "add"): {
        "issue": "#302",
        "note": "target bid optional WSDL path needs typed support or N/A.",
    },
    ("bidmodifiers", "add"): {
        "issue": "#254",
        "note": "bidmodifiers.add optional WSDL path needs typed support or N/A.",
    },
    ("dynamicads", "add"): {
        "issue": "#303",
        "note": "dynamicads.add optional WSDL path needs typed support or N/A.",
    },
    ("dynamicfeedadtargets", "add"): {
        "issue": "#303",
        "note": "dynamicfeedadtargets.add optional WSDL path needs typed support or N/A.",
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
        "issue": "#304",
        "note": "smartadtargets.add optional WSDL path needs typed support or N/A.",
    },
    ("smartadtargets", "update"): {
        "issue": "#304",
        "note": "smartadtargets.update optional WSDL path needs typed support or N/A.",
    },
}

OPTIONAL_FIELD_CHILD_PREFIX_FOLLOWUPS: dict[tuple[str, str, str], dict[str, str]] = {
    ("campaigns", "add", "TextCampaign.BiddingStrategy"): {
        "status": "missing_followup",
        "issue": "#290",
        "note": "Shared campaign BiddingStrategy builder needs typed support.",
    },
    ("campaigns", "update", "TextCampaign.BiddingStrategy"): {
        "status": "missing_followup",
        "issue": "#290",
        "note": "Shared campaign BiddingStrategy builder needs typed support.",
    },
    ("campaigns", "add", "UnifiedCampaign.BiddingStrategy"): {
        "status": "missing_followup",
        "issue": "#290",
        "note": "Shared campaign BiddingStrategy builder needs typed support.",
    },
    ("campaigns", "update", "UnifiedCampaign.BiddingStrategy"): {
        "status": "missing_followup",
        "issue": "#290",
        "note": "Shared campaign BiddingStrategy builder needs typed support.",
    },
    ("campaigns", "add", "UnifiedCampaign.PriorityGoals"): {
        "status": "missing_followup",
        "issue": "#290",
        "note": (
            "UnifiedCampaign.PriorityGoals on add requires compatible "
            "UnifiedCampaign.BiddingStrategy typed support."
        ),
    },
    ("campaigns", "add", "DynamicTextCampaign.BiddingStrategy"): {
        "status": "missing_followup",
        "issue": "#290",
        "note": "Shared campaign BiddingStrategy builder needs typed support.",
    },
    ("campaigns", "update", "DynamicTextCampaign.BiddingStrategy"): {
        "status": "missing_followup",
        "issue": "#290",
        "note": "Shared campaign BiddingStrategy builder needs typed support.",
    },
    ("campaigns", "add", "SmartCampaign.BiddingStrategy"): {
        "status": "missing_followup",
        "issue": "#290",
        "note": "Shared campaign BiddingStrategy builder needs typed support.",
    },
    ("campaigns", "update", "SmartCampaign.BiddingStrategy"): {
        "status": "missing_followup",
        "issue": "#290",
        "note": "Shared campaign BiddingStrategy builder needs typed support.",
    },
    ("campaigns", "add", "SmartCampaign.PriorityGoals"): {
        "status": "missing_followup",
        "issue": "#290",
        "note": (
            "SmartCampaign.PriorityGoals on add requires compatible "
            "SmartCampaign.BiddingStrategy typed support."
        ),
    },
    ("campaigns", "add", "MobileAppCampaign.BiddingStrategy"): {
        "status": "missing_followup",
        "issue": "#290",
        "note": "Shared campaign BiddingStrategy builder needs typed support.",
    },
    ("campaigns", "update", "MobileAppCampaign.BiddingStrategy"): {
        "status": "missing_followup",
        "issue": "#290",
        "note": "Shared campaign BiddingStrategy builder needs typed support.",
    },
    ("campaigns", "add", "CpmBannerCampaign.BiddingStrategy"): {
        "status": "missing_followup",
        "issue": "#290",
        "note": "Shared campaign BiddingStrategy builder needs typed support.",
    },
    ("campaigns", "update", "CpmBannerCampaign.BiddingStrategy"): {
        "status": "missing_followup",
        "issue": "#290",
        "note": "Shared campaign BiddingStrategy builder needs typed support.",
    },
}

OPTIONAL_FIELD_CHILD_COMPONENT_FOLLOWUPS: dict[
    tuple[str, str, str], dict[str, str]
] = {}

OPTIONAL_FIELD_AUDIT: dict[tuple[str, str, str], dict[str, str]] = {
    ("keywords", "add", "AutotargetingSearchBidIsAuto"): {
        "status": "supported",
        "issue": "#289",
        "note": (
            "Single-item typed flag is supported; batch/from-file rows "
            "intentionally reject autotargeting fields."
        ),
    },
    ("keywords", "add", "StrategyPriority"): {
        "status": "supported",
        "issue": "#289",
        "note": (
            "Single-item typed flag is supported; batch/from-file rows "
            "intentionally reject autotargeting fields."
        ),
    },
    ("adgroups", "add", "DynamicTextFeedAdGroup.AutotargetingSettings"): {
        "status": "not_applicable",
        "issue": "#281",
        "note": (
            "Official adgroups.add docs for DynamicTextFeedAdGroupAdd list "
            "FeedId and AutotargetingCategories only."
        ),
    },
    ("adgroups", "update", "DynamicTextFeedAdGroup.AutotargetingSettings"): {
        "status": "not_applicable",
        "issue": "#281",
        "note": (
            "Official adgroups.update docs for DynamicTextFeedAdGroupUpdate "
            "list AutotargetingCategories only."
        ),
    },
    ("adgroups", "update", "DynamicTextFeedAdGroup.FeedId"): {
        "status": "not_applicable",
        "issue": "#281",
        "note": (
            "Official adgroups.update docs for DynamicTextFeedAdGroupUpdate "
            "do not list FeedId."
        ),
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
    ("feeds", "add", "SourceType"): [
        "feeds",
        "add",
        "--name",
        "Feed A",
        "--business-type",
        "RETAIL",
    ],
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
    assert not stale_entries, (
        f"Optional-field audit entries no longer in WSDL: {stale_entries}"
    )
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
        f"Optional-field supported entries no longer exist in WSDL: {stale_paths}"
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


def test_optional_field_child_followups_reference_real_paths() -> None:
    """Child follow-up routing must stay tied to real WSDL paths."""
    paths_by_command = _audited_wsdl_paths()
    bad_routes = []

    for (
        cli_group,
        cli_op,
        prefix,
    ), entry in OPTIONAL_FIELD_CHILD_PREFIX_FOLLOWUPS.items():
        command_key = (cli_group, cli_op)
        paths = paths_by_command.get(command_key)
        if paths is None:
            bad_routes.append((command_key, prefix, "not in COMMAND_WSDL_MAP"))
            continue
        if entry.get("status") not in OPTIONAL_FIELD_AUDIT_STATUSES:
            bad_routes.append((command_key, prefix, entry.get("status")))
        issue = entry.get("issue", "")
        if not (issue.startswith("#") and issue[1:].isdigit()):
            bad_routes.append((command_key, prefix, issue))
        if not any(path == prefix or path.startswith(f"{prefix}.") for path in paths):
            bad_routes.append((command_key, prefix, "not in WSDL paths"))

    for (
        cli_group,
        cli_op,
        component,
    ), entry in OPTIONAL_FIELD_CHILD_COMPONENT_FOLLOWUPS.items():
        command_key = (cli_group, cli_op)
        paths = paths_by_command.get(command_key)
        if paths is None:
            bad_routes.append((command_key, component, "not in COMMAND_WSDL_MAP"))
            continue
        if entry.get("status") not in OPTIONAL_FIELD_AUDIT_STATUSES:
            bad_routes.append((command_key, component, entry.get("status")))
        issue = entry.get("issue", "")
        if not (issue.startswith("#") and issue[1:].isdigit()):
            bad_routes.append((command_key, component, issue))
        if not any(component in path.split(".") for path in paths):
            bad_routes.append((command_key, component, "not in WSDL paths"))

    assert not bad_routes, (
        "Optional-field child follow-up routes must reference real paths and "
        f"valid issue ids: {bad_routes}"
    )


def test_optional_field_followups_do_not_route_to_parent_epics() -> None:
    """Milestone 18 audit rows must point at PR-sized child issues."""
    parent_epics = {"#240", "#244", "#247", "#249", "#250", "#251", "#252", "#255"}
    bad_routes = []

    for command_key, entry in OPTIONAL_FIELD_DEFAULT_FOLLOWUPS.items():
        if entry.get("issue") in parent_epics:
            bad_routes.append(("default", command_key, entry.get("issue")))

    for audit_key, entry in OPTIONAL_FIELD_AUDIT.items():
        if entry.get("issue") in parent_epics:
            bad_routes.append(("audit", audit_key, entry.get("issue")))

    for prefix_key, entry in OPTIONAL_FIELD_CHILD_PREFIX_FOLLOWUPS.items():
        if entry.get("issue") in parent_epics:
            bad_routes.append(("prefix", prefix_key, entry.get("issue")))

    for component_key, entry in OPTIONAL_FIELD_CHILD_COMPONENT_FOLLOWUPS.items():
        if entry.get("issue") in parent_epics:
            bad_routes.append(("component", component_key, entry.get("issue")))

    assert not bad_routes, (
        "Optional-field follow-up routes must point at child issues, not "
        f"parent epics: {bad_routes}"
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
