"""Golden / characterization tests for ``build_adgroup_object`` (issue #564).

Mirrors ``test_ads_build_ad_object.py`` for the ``adgroups add`` path. The
flag→object dispatch of ``adgroups add`` (type validation, the
incompatible-flag guard, per-subtype assembly, region IDs, negative keywords)
is extracted into a reusable, ctx-free ``build_adgroup_object`` so the
single-flag command and the new ``--from-file`` batch normalizer emit
byte-identical ad-group objects. These tests freeze the CURRENT behavior: each
expected ``adgroup_data`` is the exact payload today's ``adgroups add
--dry-run`` produces, asserted against BOTH the direct function call and the CLI
path. Any drift in either fails.

The conftest autouse fixture pins ``YANDEX_DIRECT_CLI_LOCALE=en``.
"""

import json

import pytest
from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli.commands.adgroups import build_adgroup_object


def _cli_adgroup(*argv):
    result = CliRunner().invoke(cli, ["adgroups", "add", *argv, "--dry-run"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["params"]["AdGroups"][0]


_COMMON = ["--name", "G", "--campaign-id", "12", "--region-ids", "225"]

# Each case: (label, cli_argv (after _COMMON), build_kwargs, expected_adgroup_data).
# build_kwargs feeds build_adgroup_object directly: campaign_id, name,
# group_type, flags (dest-name-keyed, only the non-default values).
_CASES = [
    (
        "text",
        ["--type", "TEXT_AD_GROUP"],
        dict(
            campaign_id=12,
            name="G",
            group_type="TEXT_AD_GROUP",
            flags={"region_ids": "225"},
        ),
        {"Name": "G", "CampaignId": 12, "RegionIds": [225]},
    ),
    (
        "text_feed",
        ["--type", "TEXT_AD_GROUP", "--feed-id", "7", "--feed-category-ids", "1,2"],
        dict(
            campaign_id=12,
            name="G",
            group_type="TEXT_AD_GROUP",
            flags={"region_ids": "225", "feed_id": 7, "feed_category_ids": "1,2"},
        ),
        {
            "Name": "G",
            "CampaignId": 12,
            "RegionIds": [225],
            "TextAdGroupFeedParams": {
                "FeedId": 7,
                "FeedCategoryIds": {"Items": [1, 2]},
            },
        },
    ),
    (
        "dynamic_text",
        ["--type", "DYNAMIC_TEXT_AD_GROUP", "--domain-url", "https://e.example"],
        dict(
            campaign_id=12,
            name="G",
            group_type="DYNAMIC_TEXT_AD_GROUP",
            flags={"region_ids": "225", "domain_url": "https://e.example"},
        ),
        {
            "Name": "G",
            "CampaignId": 12,
            "RegionIds": [225],
            "DynamicTextAdGroup": {"DomainUrl": "https://e.example"},
        },
    ),
    (
        "dynamic_feed",
        ["--type", "DYNAMIC_TEXT_FEED_AD_GROUP", "--feed-id", "7"],
        dict(
            campaign_id=12,
            name="G",
            group_type="DYNAMIC_TEXT_FEED_AD_GROUP",
            flags={"region_ids": "225", "feed_id": 7},
        ),
        {
            "Name": "G",
            "CampaignId": 12,
            "RegionIds": [225],
            "DynamicTextFeedAdGroup": {"FeedId": 7},
        },
    ),
    (
        "cpm_keywords",
        ["--type", "CPM_BANNER_KEYWORDS_AD_GROUP"],
        dict(
            campaign_id=12,
            name="G",
            group_type="CPM_BANNER_KEYWORDS_AD_GROUP",
            flags={"region_ids": "225"},
        ),
        {
            "Name": "G",
            "CampaignId": 12,
            "RegionIds": [225],
            "CpmBannerKeywordsAdGroup": {},
        },
    ),
    (
        "smart",
        ["--type", "SMART_AD_GROUP", "--feed-id", "7"],
        dict(
            campaign_id=12,
            name="G",
            group_type="SMART_AD_GROUP",
            flags={"region_ids": "225", "feed_id": 7},
        ),
        {
            "Name": "G",
            "CampaignId": 12,
            "RegionIds": [225],
            "SmartAdGroup": {"FeedId": 7},
        },
    ),
    (
        "unified",
        ["--type", "UNIFIED_AD_GROUP", "--offer-retargeting", "YES"],
        dict(
            campaign_id=12,
            name="G",
            group_type="UNIFIED_AD_GROUP",
            flags={"region_ids": "225", "offer_retargeting": "YES"},
        ),
        {
            "Name": "G",
            "CampaignId": 12,
            "RegionIds": [225],
            "UnifiedAdGroup": {"OfferRetargeting": "YES"},
        },
    ),
    (
        "mobile",
        [
            "--type",
            "MOBILE_APP_AD_GROUP",
            "--store-url",
            "https://s.example",
            "--target-device-types",
            "DEVICE_TYPE_MOBILE",
            "--target-carrier",
            "WI_FI_ONLY",
            "--target-operating-system-version",
            "12",
        ],
        dict(
            campaign_id=12,
            name="G",
            group_type="MOBILE_APP_AD_GROUP",
            flags={
                "region_ids": "225",
                "store_url": "https://s.example",
                "target_device_types": "DEVICE_TYPE_MOBILE",
                "target_carrier": "WI_FI_ONLY",
                "target_operating_system_version": "12",
            },
        ),
        {
            "Name": "G",
            "CampaignId": 12,
            "RegionIds": [225],
            "MobileAppAdGroup": {
                "StoreUrl": "https://s.example",
                "TargetDeviceType": ["DEVICE_TYPE_MOBILE"],
                "TargetCarrier": "WI_FI_ONLY",
                "TargetOperatingSystemVersion": "12",
            },
        },
    ),
    (
        "negative_keywords",
        ["--type", "TEXT_AD_GROUP", "--negative-keywords", "a,b"],
        dict(
            campaign_id=12,
            name="G",
            group_type="TEXT_AD_GROUP",
            flags={"region_ids": "225", "negative_keywords": "a,b"},
        ),
        {
            "Name": "G",
            "CampaignId": 12,
            "RegionIds": [225],
            "NegativeKeywords": {"Items": ["a", "b"]},
        },
    ),
]


@pytest.mark.parametrize(
    "label,argv,kwargs,expected", _CASES, ids=[c[0] for c in _CASES]
)
def test_build_adgroup_object_matches_golden(label, argv, kwargs, expected):
    assert build_adgroup_object(**kwargs) == expected


@pytest.mark.parametrize(
    "label,argv,kwargs,expected", _CASES, ids=[c[0] for c in _CASES]
)
def test_adgroups_add_cli_matches_golden(label, argv, kwargs, expected):
    assert _cli_adgroup(*_COMMON, *argv) == expected
