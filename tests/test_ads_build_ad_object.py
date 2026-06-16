"""Golden / characterization tests for ``build_ad_object`` (issue #562).

The ~226-line flag→object dispatch of ``ads add`` is extracted into a reusable
``build_ad_object`` so the single-flag command and the new ``--from-file`` batch
normalizer emit byte-identical ad objects. These tests freeze the CURRENT
behavior: each expected ``ad_data`` is the exact payload today's ``ads add
--dry-run`` produces, asserted against BOTH the direct function call and the CLI
path. Any drift in either fails.

The conftest autouse fixture pins ``YANDEX_DIRECT_CLI_LOCALE=en``.
"""

import json

import pytest
from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli.commands.ads import build_ad_object


def _cli_ad(*argv):
    result = CliRunner().invoke(cli, ["ads", "add", *argv, "--dry-run"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["params"]["Ads"][0]


# Each case: (label, cli_argv, build_kwargs, expected_ad_data).
# build_kwargs feeds build_ad_object directly: adgroup_id, ad_type,
# mobile_provided, and flags (dest-name-keyed, only the non-None values).
_CASES = [
    (
        "text_ad",
        [
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
        ],
        dict(
            adgroup_id=12345,
            ad_type="TEXT_AD",
            mobile_provided=None,
            flags={"title": "T", "text": "Some text", "href": "https://example.com"},
        ),
        {
            "AdGroupId": 12345,
            "TextAd": {
                "Mobile": "NO",
                "Title": "T",
                "Text": "Some text",
                "Href": "https://example.com",
            },
        },
    ),
    (
        "dynamic_text_ad",
        ["--adgroup-id", "12345", "--type", "DYNAMIC_TEXT_AD", "--text", "Dyn text"],
        dict(
            adgroup_id=12345,
            ad_type="DYNAMIC_TEXT_AD",
            mobile_provided=None,
            flags={"text": "Dyn text"},
        ),
        {"AdGroupId": 12345, "DynamicTextAd": {"Text": "Dyn text"}},
    ),
    (
        "text_image_ad",
        [
            "--adgroup-id",
            "12345",
            "--type",
            "TEXT_IMAGE_AD",
            "--image-hash",
            "hhh",
            "--href",
            "https://example.com",
        ],
        dict(
            adgroup_id=12345,
            ad_type="TEXT_IMAGE_AD",
            mobile_provided=None,
            flags={"image_hash": "hhh", "href": "https://example.com"},
        ),
        {
            "AdGroupId": 12345,
            "TextImageAd": {"AdImageHash": "hhh", "Href": "https://example.com"},
        },
    ),
    (
        "mobile_app_ad",
        [
            "--adgroup-id",
            "12345",
            "--type",
            "MOBILE_APP_AD",
            "--title",
            "Install app",
            "--text",
            "App promo",
            "--action",
            "DOWNLOAD",
        ],
        dict(
            adgroup_id=12345,
            ad_type="MOBILE_APP_AD",
            mobile_provided=None,
            flags={"title": "Install app", "text": "App promo", "action": "DOWNLOAD"},
        ),
        {
            "AdGroupId": 12345,
            "MobileAppAd": {
                "Title": "Install app",
                "Text": "App promo",
                "Action": "DOWNLOAD",
            },
        },
    ),
    (
        "mobile_app_image_ad",
        [
            "--adgroup-id",
            "12345",
            "--type",
            "MOBILE_APP_IMAGE_AD",
            "--image-hash",
            "mmm",
        ],
        dict(
            adgroup_id=12345,
            ad_type="MOBILE_APP_IMAGE_AD",
            mobile_provided=None,
            flags={"image_hash": "mmm"},
        ),
        {"AdGroupId": 12345, "MobileAppImageAd": {"AdImageHash": "mmm"}},
    ),
    (
        "smart_ad_builder_ad",
        [
            "--adgroup-id",
            "12345",
            "--type",
            "SMART_AD_BUILDER_AD",
            "--logo-extension-hash",
            "logo",
        ],
        dict(
            adgroup_id=12345,
            ad_type="SMART_AD_BUILDER_AD",
            mobile_provided=None,
            flags={"logo_extension_hash": "logo"},
        ),
        {"AdGroupId": 12345, "SmartAdBuilderAd": {"LogoExtensionHash": "logo"}},
    ),
    (
        "ad_builder_text",
        [
            "--adgroup-id",
            "12345",
            "--type",
            "TEXT_AD_BUILDER_AD",
            "--creative-id",
            "777",
            "--href",
            "https://example.com",
        ],
        dict(
            adgroup_id=12345,
            ad_type="TEXT_AD_BUILDER_AD",
            mobile_provided=None,
            flags={"creative_id": 777, "href": "https://example.com"},
        ),
        {
            "AdGroupId": 12345,
            "TextAdBuilderAd": {
                "Creative": {"CreativeId": 777},
                "Href": "https://example.com",
            },
        },
    ),
]


@pytest.mark.parametrize(
    "label,argv,kwargs,expected", _CASES, ids=[c[0] for c in _CASES]
)
def test_build_ad_object_matches_golden(label, argv, kwargs, expected):
    assert build_ad_object(**kwargs) == expected


@pytest.mark.parametrize(
    "label,argv,kwargs,expected", _CASES, ids=[c[0] for c in _CASES]
)
def test_ads_add_cli_matches_golden(label, argv, kwargs, expected):
    assert _cli_ad(*argv) == expected
