"""Golden / characterization tests for ``build_adgroup_update_object`` (issue #565).

Mirrors ``test_ads_build_ad_update_object.py`` for the ``adgroups update`` path.
The subtype-dispatch body of ``adgroups update`` (the mixed-subtype reject
guard, per-subtype assembly, the ``--dynamic-feed`` routing, and the
empty-payload no-op guard) is extracted into a reusable, ctx-free
``build_adgroup_update_object`` so the single-flag command and the new
``--from-file`` batch normalizer emit byte-identical ad-group-update objects.
These tests freeze the CURRENT behavior: each expected ``adgroup_data`` is the
exact payload today's ``adgroups update --dry-run`` produces, asserted against
BOTH the direct function call and the CLI path. Any drift in either fails.

The conftest autouse fixture pins ``YANDEX_DIRECT_CLI_LOCALE=en``.
"""

import json

import pytest
from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli.commands.adgroups import build_adgroup_update_object


def _cli_adgroup(*argv):
    result = CliRunner().invoke(cli, ["adgroups", "update", *argv, "--dry-run"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["params"]["AdGroups"][0]


# Each case: (label, cli_argv, build_kwargs, expected_adgroup_data).
# build_kwargs feeds build_adgroup_update_object directly: adgroup_id and flags
# (dest-name-keyed, only the non-default values).
_CASES = [
    (
        "name",
        ["--id", "5", "--name", "New"],
        dict(adgroup_id=5, flags={"name": "New"}),
        {"Id": 5, "Name": "New"},
    ),
    (
        "status",
        ["--id", "5", "--status", "SUSPENDED"],
        dict(adgroup_id=5, flags={"status": "SUSPENDED"}),
        {"Id": 5, "Status": "SUSPENDED"},
    ),
    (
        "region",
        ["--id", "5", "--region-ids", "225,1"],
        dict(adgroup_id=5, flags={"region_ids": "225,1"}),
        {"Id": 5, "RegionIds": [225, 1]},
    ),
    (
        "negative_keywords",
        ["--id", "5", "--negative-keywords", "a,b"],
        dict(adgroup_id=5, flags={"negative_keywords": "a,b"}),
        {"Id": 5, "NegativeKeywords": {"Items": ["a", "b"]}},
    ),
    (
        "dynamic_text",
        ["--id", "5", "--domain-url", "https://e.example"],
        dict(adgroup_id=5, flags={"domain_url": "https://e.example"}),
        {"Id": 5, "DynamicTextAdGroup": {"DomainUrl": "https://e.example"}},
    ),
    (
        "dynamic_feed",
        ["--id", "5", "--dynamic-feed", "--autotargeting-category", "EXACT=YES"],
        dict(
            adgroup_id=5,
            flags={"dynamic_feed": True, "autotargeting_categories": ("EXACT=YES",)},
        ),
        {
            "Id": 5,
            "DynamicTextFeedAdGroup": {
                "AutotargetingCategories": [{"Category": "EXACT", "Value": "YES"}]
            },
        },
    ),
    (
        "mobile",
        ["--id", "5", "--target-carrier", "WI_FI_ONLY"],
        dict(adgroup_id=5, flags={"target_carrier": "WI_FI_ONLY"}),
        {"Id": 5, "MobileAppAdGroup": {"TargetCarrier": "WI_FI_ONLY"}},
    ),
    (
        "smart",
        ["--id", "5", "--ad-title-source", "FEED"],
        dict(adgroup_id=5, flags={"ad_title_source": "FEED"}),
        {"Id": 5, "SmartAdGroup": {"AdTitleSource": "FEED"}},
    ),
    (
        "text_feed",
        ["--id", "5", "--feed-id", "7", "--feed-category-ids", "1,2"],
        dict(adgroup_id=5, flags={"feed_id": 7, "feed_category_ids": "1,2"}),
        {
            "Id": 5,
            "TextAdGroupFeedParams": {
                "FeedId": 7,
                "FeedCategoryIds": {"Items": [1, 2]},
            },
        },
    ),
    (
        "unified",
        ["--id", "5", "--offer-retargeting", "YES"],
        dict(adgroup_id=5, flags={"offer_retargeting": "YES"}),
        {"Id": 5, "UnifiedAdGroup": {"OfferRetargeting": "YES"}},
    ),
    (
        "tracking",
        ["--id", "5", "--tracking-params", "utm=1"],
        dict(adgroup_id=5, flags={"tracking_params": "utm=1"}),
        {"Id": 5, "TrackingParams": "utm=1"},
    ),
]


@pytest.mark.parametrize(
    "label,argv,kwargs,expected", _CASES, ids=[c[0] for c in _CASES]
)
def test_build_adgroup_update_object_matches_golden(label, argv, kwargs, expected):
    assert build_adgroup_update_object(**kwargs) == expected


@pytest.mark.parametrize(
    "label,argv,kwargs,expected", _CASES, ids=[c[0] for c in _CASES]
)
def test_adgroups_update_cli_matches_golden(label, argv, kwargs, expected):
    assert _cli_adgroup(*argv) == expected
