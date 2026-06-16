"""Golden / characterization tests for ``build_ad_update_object`` (issue #563).

Mirrors ``test_ads_build_ad_object.py`` for the ``ads update`` path. The
subtype-dispatch body of ``ads update`` (type validation, the
incompatible-flag/"does not convert between subtypes" guard, per-subtype
assembly, and the empty-subtype no-op guard) is extracted into a reusable
``build_ad_update_object`` so the single-flag command and the new
``--from-file`` batch normalizer emit byte-identical ad-update objects. These
tests freeze the CURRENT behavior: each expected ``ad_data`` is the exact
payload today's ``ads update --dry-run`` produces, asserted against BOTH the
direct function call and the CLI path. Any drift in either fails.

The conftest autouse fixture pins ``YANDEX_DIRECT_CLI_LOCALE=en``.
"""

import json

import pytest
from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli.commands.ads import build_ad_update_object


def _cli_ad(*argv):
    result = CliRunner().invoke(cli, ["ads", "update", *argv, "--dry-run"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["params"]["Ads"][0]


# Each case: (label, cli_argv, build_kwargs, expected_ad_data).
# build_kwargs feeds build_ad_update_object directly: ad_id, ad_type, and flags
# (dest-name-keyed, only the non-None values).
_CASES = [
    (
        "text_ad_title",
        ["--id", "5", "--type", "TEXT_AD", "--title", "NewT"],
        dict(ad_id=5, ad_type="TEXT_AD", flags={"title": "NewT"}),
        {"Id": 5, "TextAd": {"Title": "NewT"}},
    ),
    (
        "text_ad_clear_image",
        ["--id", "5", "--type", "TEXT_AD", "--clear-image-hash"],
        dict(ad_id=5, ad_type="TEXT_AD", flags={"clear_image_hash": True}),
        {"Id": 5, "TextAd": {"AdImageHash": None}},
    ),
    (
        "text_ad_callouts_add",
        ["--id", "5", "--type", "TEXT_AD", "--callouts-add", "1,2"],
        dict(ad_id=5, ad_type="TEXT_AD", flags={"callouts_add": "1,2"}),
        {
            "Id": 5,
            "TextAd": {
                "CalloutSetting": {
                    "AdExtensions": [
                        {"AdExtensionId": 1, "Operation": "ADD"},
                        {"AdExtensionId": 2, "Operation": "ADD"},
                    ]
                }
            },
        },
    ),
    (
        "text_ad_price",
        [
            "--id",
            "5",
            "--type",
            "TEXT_AD",
            "--price-extension-price",
            "12500000",
            "--price-extension-price-qualifier",
            "FROM",
            "--price-extension-price-currency",
            "RUB",
        ],
        dict(
            ad_id=5,
            ad_type="TEXT_AD",
            flags={
                "price_extension_price": 12500000,
                "price_extension_price_qualifier": "FROM",
                "price_extension_price_currency": "RUB",
            },
        ),
        {
            "Id": 5,
            "TextAd": {
                "PriceExtension": {
                    "Price": 12500000,
                    "PriceQualifier": "FROM",
                    "PriceCurrency": "RUB",
                }
            },
        },
    ),
    (
        "dynamic_text_ad",
        ["--id", "5", "--type", "DYNAMIC_TEXT_AD", "--text", "Dyn"],
        dict(ad_id=5, ad_type="DYNAMIC_TEXT_AD", flags={"text": "Dyn"}),
        {"Id": 5, "DynamicTextAd": {"Text": "Dyn"}},
    ),
    (
        "text_image_ad",
        ["--id", "5", "--type", "TEXT_IMAGE_AD", "--image-hash", "hhh"],
        dict(ad_id=5, ad_type="TEXT_IMAGE_AD", flags={"image_hash": "hhh"}),
        {"Id": 5, "TextImageAd": {"AdImageHash": "hhh"}},
    ),
    (
        "mobile_app_ad_clear",
        ["--id", "5", "--type", "MOBILE_APP_AD", "--clear-image-hash"],
        dict(ad_id=5, ad_type="MOBILE_APP_AD", flags={"clear_image_hash": True}),
        {"Id": 5, "MobileAppAd": {"AdImageHash": None}},
    ),
    (
        "mobile_app_image_ad",
        ["--id", "5", "--type", "MOBILE_APP_IMAGE_AD", "--image-hash", "mmm"],
        dict(ad_id=5, ad_type="MOBILE_APP_IMAGE_AD", flags={"image_hash": "mmm"}),
        {"Id": 5, "MobileAppImageAd": {"AdImageHash": "mmm"}},
    ),
    (
        "responsive_ad",
        ["--id", "5", "--type", "RESPONSIVE_AD", "--href", "https://e.example"],
        dict(ad_id=5, ad_type="RESPONSIVE_AD", flags={"href": "https://e.example"}),
        {"Id": 5, "ResponsiveAd": {"Href": "https://e.example"}},
    ),
    (
        "shopping_ad",
        ["--id", "5", "--type", "SHOPPING_AD", "--title-sources", "FEED"],
        dict(ad_id=5, ad_type="SHOPPING_AD", flags={"title_sources": "FEED"}),
        {"Id": 5, "ShoppingAd": {"TitleSources": {"Items": ["FEED"]}}},
    ),
    (
        "smart_ad_builder",
        ["--id", "5", "--type", "SMART_AD_BUILDER_AD", "--logo-extension-hash", "logo"],
        dict(
            ad_id=5,
            ad_type="SMART_AD_BUILDER_AD",
            flags={"logo_extension_hash": "logo"},
        ),
        {"Id": 5, "SmartAdBuilderAd": {"LogoExtensionHash": "logo"}},
    ),
    (
        "ad_builder_text",
        ["--id", "5", "--type", "TEXT_AD_BUILDER_AD", "--creative-id", "777"],
        dict(ad_id=5, ad_type="TEXT_AD_BUILDER_AD", flags={"creative_id": 777}),
        {"Id": 5, "TextAdBuilderAd": {"Creative": {"CreativeId": 777}}},
    ),
]


@pytest.mark.parametrize(
    "label,argv,kwargs,expected", _CASES, ids=[c[0] for c in _CASES]
)
def test_build_ad_update_object_matches_golden(label, argv, kwargs, expected):
    assert build_ad_update_object(**kwargs) == expected


@pytest.mark.parametrize(
    "label,argv,kwargs,expected", _CASES, ids=[c[0] for c in _CASES]
)
def test_ads_update_cli_matches_golden(label, argv, kwargs, expected):
    assert _cli_ad(*argv) == expected
