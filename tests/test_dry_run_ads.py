"""Dry-run payload tests for ``ads``, ``adimages``, ``advideos`` and ``creatives``.

Split out of the historical monolithic ``tests/test_dry_run.py`` (issue #604).
See :mod:`tests.test_dry_run_shared` for the shared invocation helpers and
``tests/test_dry_run.py`` for the rationale behind the whole suite.
"""

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli.utils import get_default_fields
from tests.test_dry_run_shared import _dry_run, _read_dry_run, _rejected, _write_jsonl


def test_advideos_get_ids_required():
    result = CliRunner().invoke(cli, ["advideos", "get", "--dry-run"])
    assert result.exit_code != 0
    assert "Missing option '--ids'" in result.output


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
        "123450000",
        "--price-extension-old-price",
        "234560000",
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
        "234560000",
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
        "123450000",
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
        "123450000",
        "--price-extension-old-price",
        "150000000",
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
        "150000000",
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


@pytest.mark.parametrize(
    "ad_type, block",
    [
        ("TEXT_AD", "TextAd"),
        ("DYNAMIC_TEXT_AD", "DynamicTextAd"),
        ("MOBILE_APP_AD", "MobileAppAd"),
    ],
)
def test_ads_update_clear_image_hash_sends_null(ad_type, block):
    """--clear-image-hash sends AdImageHash=null to reset the image (issue #552)."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        ad_type,
        "--clear-image-hash",
    )
    ad = body["params"]["Ads"][0]
    assert ad["Id"] == 999
    assert ad[block] == {"AdImageHash": None}


@pytest.mark.parametrize("ad_type", ["TEXT_IMAGE_AD", "MOBILE_APP_IMAGE_AD"])
def test_ads_update_clear_image_hash_rejected_for_non_nillable_subtype(ad_type):
    """ImageAdUpdateBase.AdImageHash is not nillable; the live API rejects null
    (error 8000). The flag must be refused for these subtypes, not silently sent."""
    result = CliRunner().invoke(
        cli,
        [
            "ads",
            "update",
            "--id",
            "999",
            "--type",
            ad_type,
            "--clear-image-hash",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert f"--clear-image-hash is not compatible with --type {ad_type}" in (
        result.output
    )


def test_ads_update_clear_image_hash_counts_as_updatable_field():
    """--clear-image-hash alone is a real change, not an empty-subtype no-op."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_AD",
        "--clear-image-hash",
    )
    ad = body["params"]["Ads"][0]
    assert ad == {"Id": 999, "TextAd": {"AdImageHash": None}}


def test_ads_update_clear_image_hash_rejects_image_hash():
    """--image-hash and --clear-image-hash are mutually exclusive."""
    result = CliRunner().invoke(
        cli,
        [
            "ads",
            "update",
            "--id",
            "999",
            "--type",
            "TEXT_AD",
            "--image-hash",
            "abc",
            "--clear-image-hash",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "--image-hash or --clear-image-hash" in result.output


def test_ads_update_clear_image_hash_rejected_for_incompatible_type():
    """--clear-image-hash on a subtype without AdImageHash must raise, not drop."""
    result = CliRunner().invoke(
        cli,
        [
            "ads",
            "update",
            "--id",
            "999",
            "--type",
            "RESPONSIVE_AD",
            "--clear-image-hash",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "--clear-image-hash is not compatible with --type RESPONSIVE_AD" in (
        result.output
    )


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
        "123450000",
        "--price-extension-old-price",
        "150000000",
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
        "123450000",
        "--price-extension-old-price",
        "150000000",
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


def test_ads_update_text_ad_price_extension_rejects_decimal_rubles():
    """PriceExtension money input is API-native micro-rubles."""
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
    assert "Expected integer (micro-rubles)" in result.output


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
        "123450000",
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


ADS_GET_NESTED_FIELD_NAME_OPTIONS = [
    ("--cpc-video-ad-builder-ad-field-names", "CpcVideoAdBuilderAdFieldNames"),
    ("--cpm-banner-ad-builder-ad-field-names", "CpmBannerAdBuilderAdFieldNames"),
    ("--cpm-video-ad-builder-ad-field-names", "CpmVideoAdBuilderAdFieldNames"),
    ("--dynamic-text-ad-field-names", "DynamicTextAdFieldNames"),
    ("--listing-ad-field-names", "ListingAdFieldNames"),
    ("--mobile-app-ad-builder-ad-field-names", "MobileAppAdBuilderAdFieldNames"),
    ("--mobile-app-ad-field-names", "MobileAppAdFieldNames"),
    (
        "--mobile-app-cpc-video-ad-builder-ad-field-names",
        "MobileAppCpcVideoAdBuilderAdFieldNames",
    ),
    ("--mobile-app-image-ad-field-names", "MobileAppImageAdFieldNames"),
    ("--responsive-ad-field-names", "ResponsiveAdFieldNames"),
    ("--shopping-ad-field-names", "ShoppingAdFieldNames"),
    ("--smart-ad-builder-ad-field-names", "SmartAdBuilderAdFieldNames"),
    ("--text-ad-builder-ad-field-names", "TextAdBuilderAdFieldNames"),
    ("--text-ad-field-names", "TextAdFieldNames"),
    ("--text-ad-price-extension-field-names", "TextAdPriceExtensionFieldNames"),
    ("--text-image-ad-field-names", "TextImageAdFieldNames"),
]


def test_ads_get_default_fieldnames():
    """Default FieldNames includes basic top-level fields, plus TextAdFieldNames."""
    body = _dry_run("ads", "get", "--campaign-ids", "12345")
    assert body["method"] == "get"
    assert body["params"]["FieldNames"] == get_default_fields("ads", "FieldNames")
    assert body["params"]["TextAdFieldNames"] == get_default_fields(
        "ads", "TextAdFieldNames"
    )


def test_ads_get_with_fields_overrides_defaults():
    """--fields and --text-ad-field-names override the defaults."""
    body = _dry_run(
        "ads",
        "get",
        "--campaign-ids",
        "12345",
        "--fields",
        "Id,State",
        "--text-ad-field-names",
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


def test_ads_get_nested_field_names_payload():
    """Nested AdsGetRequest FieldNames options are sent independently."""
    body = _dry_run(
        "ads",
        "get",
        "--campaign-ids",
        "12345",
        "--dynamic-text-ad-field-names",
        "Title,Text,Href",
        "--responsive-ad-field-names",
        "Titles,Texts",
        "--text-ad-price-extension-field-names",
        "Price,OldPrice",
    )

    params = body["params"]
    assert params["DynamicTextAdFieldNames"] == ["Title", "Text", "Href"]
    assert params["ResponsiveAdFieldNames"] == ["Titles", "Texts"]
    assert params["TextAdPriceExtensionFieldNames"] == ["Price", "OldPrice"]


def test_ads_get_default_omits_non_text_nested_field_names():
    """Unspecified nested projections are omitted so Yandex applies defaults."""
    body = _dry_run("ads", "get", "--campaign-ids", "12345")

    assert "DynamicTextAdFieldNames" not in body["params"]
    assert "ResponsiveAdFieldNames" not in body["params"]
    # TextAdFieldNames existed before the rename and keeps its default payload.
    assert body["params"]["TextAdFieldNames"] == get_default_fields(
        "ads", "TextAdFieldNames"
    )


def test_ads_get_help_exposes_nested_field_names_options():
    result = CliRunner().invoke(cli, ["ads", "get", "--help"])

    assert result.exit_code == 0
    for flag, _ in ADS_GET_NESTED_FIELD_NAME_OPTIONS:
        assert flag in result.output
    assert "--text-ad-fields" not in result.output


@pytest.mark.parametrize("flag,wsdl_key", ADS_GET_NESTED_FIELD_NAME_OPTIONS)
def test_ads_get_rejects_empty_nested_field_names(flag, wsdl_key):
    result = CliRunner().invoke(cli, ["ads", "get", flag, ",", "--dry-run"])

    assert result.exit_code != 0
    assert f"Provide a non-empty comma-separated {wsdl_key} list." in result.output


def test_ads_get_legacy_text_ad_fields_alias_removed():
    result = CliRunner().invoke(
        cli, ["ads", "get", "--campaign-ids", "12345", "--text-ad-fields", "Title"]
    )

    assert result.exit_code != 0
    assert "No such option" in result.output
    assert "--text-ad-fields" in result.output


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


def test_ads_get_empty_field_names_raises_usage_error_not_abort():
    result = CliRunner().invoke(
        cli,
        ["ads", "get", "--ids", "1", "--text-ad-field-names", ",", "--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )
    assert result.exit_code == 2
    assert "Aborted!" not in result.output


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


def test_ads_moderate_dry_run_payload():
    body = _dry_run("ads", "moderate", "--id", "99")
    assert body == {
        "method": "moderate",
        "params": {"SelectionCriteria": {"Ids": [99]}},
    }


def test_adimages_delete_dry_run_payload():
    body = _dry_run("adimages", "delete", "--hash", "image-hash")
    assert body == {
        "method": "delete",
        "params": {"SelectionCriteria": {"AdImageHashes": ["image-hash"]}},
    }


def test_creatives_get_nested_field_names_payload():
    # CreativesGetRequest (WSDL tests/wsdl_cache/creatives.xml) declares four
    # nested top-level *FieldNames parameters separate from FieldNames:
    # CpcVideoCreativeFieldNames (CpcVideoCreativeFieldEnum: Duration),
    # CpmVideoCreativeFieldNames (CpmVideoCreativeFieldEnum: Duration),
    # SmartCreativeFieldNames (SmartCreativeFieldEnum: CreativeGroupId,
    # CreativeGroupName, BusinessType), and
    # VideoExtensionCreativeFieldNames (VideoExtensionCreativeFieldEnum:
    # Duration).
    body = _read_dry_run(
        "creatives",
        "get",
        "--ids",
        "1",
        "--cpc-video-creative-field-names",
        "Duration",
        "--cpm-video-creative-field-names",
        "Duration",
        "--smart-creative-field-names",
        "CreativeGroupId,CreativeGroupName,BusinessType",
        "--video-extension-creative-field-names",
        "Duration",
    )

    params = body["params"]
    assert params["CpcVideoCreativeFieldNames"] == ["Duration"]
    assert params["CpmVideoCreativeFieldNames"] == ["Duration"]
    assert params["SmartCreativeFieldNames"] == [
        "CreativeGroupId",
        "CreativeGroupName",
        "BusinessType",
    ]
    assert params["VideoExtensionCreativeFieldNames"] == ["Duration"]


def test_creatives_get_omits_nested_field_names_by_default():
    body = _read_dry_run("creatives", "get", "--ids", "1")

    for key in (
        "CpcVideoCreativeFieldNames",
        "CpmVideoCreativeFieldNames",
        "SmartCreativeFieldNames",
        "VideoExtensionCreativeFieldNames",
    ):
        assert key not in body["params"]


def test_creatives_get_help_exposes_nested_field_names():
    result = CliRunner().invoke(cli, ["creatives", "get", "--help"])

    assert result.exit_code == 0
    for flag in (
        "--cpc-video-creative-field-names",
        "--cpm-video-creative-field-names",
        "--smart-creative-field-names",
        "--video-extension-creative-field-names",
    ):
        assert flag in result.output


@pytest.mark.parametrize(
    "flag,wsdl_key",
    [
        ("--cpc-video-creative-field-names", "CpcVideoCreativeFieldNames"),
        ("--cpm-video-creative-field-names", "CpmVideoCreativeFieldNames"),
        ("--smart-creative-field-names", "SmartCreativeFieldNames"),
        (
            "--video-extension-creative-field-names",
            "VideoExtensionCreativeFieldNames",
        ),
    ],
)
def test_creatives_get_rejects_empty_nested_field_names_csv(flag, wsdl_key):
    result = CliRunner().invoke(
        cli,
        ["creatives", "get", flag, ",", "--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )

    assert result.exit_code != 0
    assert f"Provide a non-empty comma-separated {wsdl_key} list." in result.output


@pytest.mark.parametrize("bad", ["0", "-5"])
def test_ads_delete_rejects_non_positive_id(bad):
    result = _rejected("ads", "delete", "--id", bad)
    assert result.exit_code == 2, result.output


def test_ads_delete_allows_positive_id():
    body = _dry_run("ads", "delete", "--id", "5")
    assert body["params"]["SelectionCriteria"]["Ids"] == [5]


def test_ads_add_rejects_zero_adgroup_id():
    result = _rejected(
        "ads",
        "add",
        "--adgroup-id",
        "0",
        "--type",
        "TEXT_AD",
        "--title",
        "T",
        "--text",
        "X",
        "--href",
        "http://a.b",
    )
    assert result.exit_code == 2, result.output


def test_ads_update_rejects_zero_id():
    result = _rejected(
        "ads", "update", "--id", "0", "--type", "TEXT_AD", "--title", "N"
    )
    assert result.exit_code == 2, result.output


def test_adimages_delete_still_accepts_hash_string():
    # Regression guard: the ad-image lifecycle uses --hash (str), which must NOT
    # be retyped to IntRange — a hash is not a positive integer.
    body = _dry_run("adimages", "delete", "--hash", "abc123hash")
    assert body["params"]["SelectionCriteria"]["AdImageHashes"] == ["abc123hash"]


def test_ads_add_batch_from_jsonl(tmp_path):
    rows = [
        {
            "type": "TEXT_AD",
            "title": "T1",
            "text": "Body 1",
            "href": "https://a.example",
            "adgroup-id": 111,
        },
        {
            "type": "MOBILE_APP_AD",
            "title": "App",
            "text": "Promo",
            "action": "DOWNLOAD",
            "adgroup-id": 222,
        },
    ]
    path = _write_jsonl(tmp_path, rows)
    body = _dry_run("ads", "add", "--from-file", path)
    assert body["chunks"] == 1
    assert body["totalItems"] == 2
    assert body["chunkSize"] == 100
    assert body["firstChunk"]["method"] == "add"
    ads = body["firstChunk"]["params"]["Ads"]
    # Row -> build_ad_object yields the same object as the single-flag path.
    assert ads[0] == {
        "AdGroupId": 111,
        "TextAd": {
            "Mobile": "NO",
            "Title": "T1",
            "Text": "Body 1",
            "Href": "https://a.example",
        },
    }
    assert ads[1]["MobileAppAd"]["Action"] == "DOWNLOAD"


def test_ads_add_batch_inline():
    arr = json.dumps(
        [
            {
                "type": "TEXT_AD",
                "title": "T",
                "text": "B",
                "href": "https://a.example",
                "adgroup-id": 1,
            },
        ]
    )
    body = _dry_run("ads", "add", "--ads-json", arr)
    assert body["totalItems"] == 1
    assert "TextAd" in body["firstChunk"]["params"]["Ads"][0]


def test_ads_add_batch_chunks_at_100(tmp_path):
    rows = [
        {
            "type": "TEXT_AD",
            "title": f"T{i}",
            "text": "B",
            "href": "https://a.example",
            "adgroup-id": 1,
        }
        for i in range(250)
    ]
    path = _write_jsonl(tmp_path, rows)
    body = _dry_run("ads", "add", "--from-file", path)
    assert body["chunks"] == 3
    assert body["totalItems"] == 250
    assert len(body["firstChunk"]["params"]["Ads"]) == 100


def test_ads_add_batch_adgroup_default_and_override(tmp_path):
    rows = [
        {"type": "TEXT_AD", "title": "T", "text": "B", "href": "https://a.example"},
        {
            "type": "TEXT_AD",
            "title": "T",
            "text": "B",
            "href": "https://a.example",
            "adgroup-id": 999,
        },
    ]
    path = _write_jsonl(tmp_path, rows)
    body = _dry_run("ads", "add", "--adgroup-id", "5", "--from-file", path)
    ads = body["firstChunk"]["params"]["Ads"]
    assert ads[0]["AdGroupId"] == 5
    assert ads[1]["AdGroupId"] == 999


def test_ads_add_batch_rejects_unknown_field(tmp_path):
    path = _write_jsonl(tmp_path, [{"type": "TEXT_AD", "foo": "bar", "adgroup-id": 1}])
    result = _rejected("ads", "add", "--from-file", path)
    assert "Unknown field 'foo' in ad row 1" in result.output


def test_ads_add_batch_rejects_non_object_row(tmp_path):
    path = _write_jsonl(tmp_path, [[1, 2, 3]])
    result = _rejected("ads", "add", "--from-file", path)
    assert "Ad row 1" in result.output
    assert "expected JSON object" in result.output


def test_ads_add_batch_rejects_empty_file(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("\n", encoding="utf-8")
    result = _rejected("ads", "add", "--from-file", str(path))
    assert "Input contains no ad rows" in result.output


def test_ads_add_batch_rejects_invalid_json(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"type":"TEXT_AD"}\nnot json\n', encoding="utf-8")
    result = _rejected("ads", "add", "--from-file", str(path))
    assert "Row 2: invalid JSON" in result.output


def test_ads_add_batch_rejects_incompatible_flag_per_row(tmp_path):
    # --action is not valid for TEXT_AD; the per-row guard wraps the message.
    path = _write_jsonl(
        tmp_path,
        [
            {
                "type": "TEXT_AD",
                "title": "T",
                "text": "B",
                "href": "https://a.example",
                "action": "INSTALL",
                "adgroup-id": 1,
            }
        ],
    )
    result = _rejected("ads", "add", "--from-file", path)
    assert "Ad row 1:" in result.output
    assert "--action" in result.output


def test_ads_add_batch_rejects_missing_required_field_per_row(tmp_path):
    path = _write_jsonl(
        tmp_path, [{"type": "TEXT_AD", "title": "T", "text": "B", "adgroup-id": 1}]
    )
    result = _rejected("ads", "add", "--from-file", path)
    assert "Ad row 1:" in result.output
    assert "TEXT_AD requires --href" in result.output


def test_ads_add_batch_rejects_invalid_type_per_row(tmp_path):
    path = _write_jsonl(tmp_path, [{"type": "NOPE", "adgroup-id": 1}])
    result = _rejected("ads", "add", "--from-file", path)
    assert "Ad row 1:" in result.output
    assert "Invalid value for '--type'" in result.output


def test_ads_add_batch_rejects_missing_adgroup_in_row(tmp_path):
    path = _write_jsonl(
        tmp_path,
        [{"type": "TEXT_AD", "title": "T", "text": "B", "href": "https://a.example"}],
    )
    result = _rejected("ads", "add", "--from-file", path)
    assert "Ad row 1:" in result.output
    assert "adgroup-id" in result.output


def test_ads_add_batch_rejects_mutex(tmp_path):
    path = _write_jsonl(tmp_path, [{"type": "TEXT_AD", "adgroup-id": 1}])
    result = _rejected("ads", "add", "--from-file", path, "--ads-json", "[]")
    assert "mutually exclusive" in result.output


def test_ads_add_batch_rejects_single_flag_in_batch(tmp_path):
    path = _write_jsonl(tmp_path, [{"type": "TEXT_AD", "adgroup-id": 1}])
    result = _rejected("ads", "add", "--from-file", path, "--title", "X")
    assert "--title supported only with single-item mode" in result.output


def test_ads_add_single_still_requires_adgroup_id():
    result = _rejected(
        "ads",
        "add",
        "--type",
        "TEXT_AD",
        "--title",
        "T",
        "--text",
        "B",
        "--href",
        "https://a.example",
    )
    assert "Missing option '--adgroup-id'." in result.output


def test_ads_add_batch_rejects_non_positive_adgroup_id_in_row(tmp_path):
    # IntRange(min=1) must apply per row, same as single --adgroup-id.
    path = _write_jsonl(tmp_path, [{"type": "TEXT_AD", "adgroup-id": -5}])
    result = _rejected("ads", "add", "--from-file", path)
    assert "Ad row 1 field 'adgroup-id'" in result.output
    assert "x>=1" in result.output


def test_ads_add_batch_coerces_micro_rubles_like_single(tmp_path):
    # A bare float must be rejected (MICRO_RUBLES is int micro-rubles), exactly
    # like `--price-extension-price 12.5` in single mode — not forwarded raw.
    path = _write_jsonl(
        tmp_path,
        [
            {
                "type": "TEXT_AD",
                "title": "T",
                "text": "B",
                "href": "http://x",
                "price-extension-price": 12.5,
                "price-extension-price-qualifier": "FROM",
                "price-extension-price-currency": "RUB",
                "adgroup-id": 1,
            }
        ],
    )
    result = _rejected("ads", "add", "--from-file", path)
    assert "Ad row 1 field 'price-extension-price'" in result.output


def test_ads_add_batch_valid_micro_rubles_passes_through(tmp_path):
    path = _write_jsonl(
        tmp_path,
        [
            {
                "type": "TEXT_AD",
                "title": "T",
                "text": "B",
                "href": "http://x",
                "price-extension-price": 12500000,
                "price-extension-price-qualifier": "FROM",
                "price-extension-price-currency": "RUB",
                "adgroup-id": 1,
            }
        ],
    )
    body = _dry_run("ads", "add", "--from-file", path)
    ad = body["firstChunk"]["params"]["Ads"][0]
    assert ad["TextAd"]["PriceExtension"]["Price"] == 12500000


def test_ads_add_batch_rejects_bool_for_typed_field(tmp_path):
    path = _write_jsonl(tmp_path, [{"type": "TEXT_AD", "adgroup-id": True}])
    result = _rejected("ads", "add", "--from-file", path)
    assert "Ad row 1 field 'adgroup-id'" in result.output
    assert "bool" in result.output


def test_ads_add_batch_rejects_invalid_choice_in_row(tmp_path):
    # --mobile is a YES/NO Choice; an invalid value must be rejected per row.
    path = _write_jsonl(
        tmp_path,
        [
            {
                "type": "TEXT_AD",
                "title": "T",
                "text": "B",
                "href": "http://x",
                "mobile": "MAYBE",
                "adgroup-id": 1,
            }
        ],
    )
    result = _rejected("ads", "add", "--from-file", path)
    assert "Ad row 1 field 'mobile'" in result.output


def test_ads_add_batch_rejects_float_adgroup_id(tmp_path):
    # A JSON float must NOT be silently truncated to int (1.9 -> 1); Click
    # rejects the "1.9" token, so the row is rejected — same as single mode.
    path = _write_jsonl(tmp_path, [{"type": "TEXT_AD", "adgroup-id": 1.9}])
    result = _rejected("ads", "add", "--from-file", path)
    assert "Ad row 1 field 'adgroup-id'" in result.output


def test_ads_add_batch_rejects_float_int_id(tmp_path):
    path = _write_jsonl(
        tmp_path,
        [
            {
                "type": "TEXT_AD",
                "title": "T",
                "text": "B",
                "href": "http://x",
                "vcard-id": 1.9,
                "adgroup-id": 1,
            }
        ],
    )
    result = _rejected("ads", "add", "--from-file", path)
    assert "Ad row 1 field 'vcard-id'" in result.output


def test_ads_add_batch_rejects_float_micro_rubles(tmp_path):
    path = _write_jsonl(
        tmp_path,
        [
            {
                "type": "TEXT_AD",
                "title": "T",
                "text": "B",
                "href": "http://x",
                "price-extension-price": 12500000.9,
                "price-extension-price-qualifier": "FROM",
                "price-extension-price-currency": "RUB",
                "adgroup-id": 1,
            }
        ],
    )
    result = _rejected("ads", "add", "--from-file", path)
    assert "Ad row 1 field 'price-extension-price'" in result.output


def test_ads_add_batch_accepts_genuine_int_ids(tmp_path):
    # A genuine JSON int still passes through unchanged.
    path = _write_jsonl(
        tmp_path,
        [
            {
                "type": "TEXT_AD",
                "title": "T",
                "text": "B",
                "href": "http://x",
                "vcard-id": 555,
                "adgroup-id": 7,
            }
        ],
    )
    body = _dry_run("ads", "add", "--from-file", path)
    ad = body["firstChunk"]["params"]["Ads"][0]
    assert ad["AdGroupId"] == 7
    assert ad["TextAd"]["VCardId"] == 555


def test_ads_add_batch_stringifies_scalar_string_field(tmp_path):
    # A JSON int for a string field becomes "123" — same as the CLI token would,
    # not a raw int in the payload.
    path = _write_jsonl(
        tmp_path,
        [
            {
                "type": "TEXT_AD",
                "title": 123,
                "text": "B",
                "href": "http://x",
                "adgroup-id": 1,
            }
        ],
    )
    body = _dry_run("ads", "add", "--from-file", path)
    assert body["firstChunk"]["params"]["Ads"][0]["TextAd"]["Title"] == "123"


def test_ads_add_batch_rejects_object_for_string_field(tmp_path):
    path = _write_jsonl(
        tmp_path,
        [
            {
                "type": "TEXT_AD",
                "title": {"bad": 1},
                "text": "B",
                "href": "http://x",
                "adgroup-id": 1,
            }
        ],
    )
    result = _rejected("ads", "add", "--from-file", path)
    assert "Ad row 1 field 'title'" in result.output
    assert "scalar" in result.output


@pytest.mark.parametrize("bad", [None, [1], {"a": 1}])
def test_ads_add_batch_rejects_non_scalar_typed_field(tmp_path, bad):
    # null / list / object for a scalar field must be a clean UsageError, not an
    # uncaught TypeError from int().
    path = _write_jsonl(tmp_path, [{"type": "TEXT_AD", "adgroup-id": bad}])
    result = _rejected("ads", "add", "--from-file", path)
    assert "Ad row 1 field 'adgroup-id'" in result.output
    assert "scalar" in result.output


def test_ads_add_batch_rejects_non_list_multi_value(tmp_path):
    path = _write_jsonl(
        tmp_path,
        [
            {
                "type": "MOBILE_APP_AD",
                "title": "T",
                "text": "B",
                "action": "DOWNLOAD",
                "mobile-app-feature": 5,
                "adgroup-id": 1,
            }
        ],
    )
    result = _rejected("ads", "add", "--from-file", path)
    assert "Ad row 1 field 'mobile-app-feature'" in result.output
    assert "array of strings" in result.output


def test_ads_update_batch_from_jsonl(tmp_path):
    rows = [
        {"id": 5, "type": "TEXT_AD", "title": "New title"},
        {"id": 6, "type": "DYNAMIC_TEXT_AD", "text": "Dyn"},
    ]
    path = _write_jsonl(tmp_path, rows)
    body = _dry_run("ads", "update", "--from-file", path)
    assert body["chunks"] == 1
    assert body["totalItems"] == 2
    assert body["chunkSize"] == 100
    assert body["firstChunk"]["method"] == "update"
    ads = body["firstChunk"]["params"]["Ads"]
    # Row -> build_ad_update_object yields the same object as the single path.
    assert ads[0] == {"Id": 5, "TextAd": {"Title": "New title"}}
    assert ads[1] == {"Id": 6, "DynamicTextAd": {"Text": "Dyn"}}


def test_ads_update_batch_inline():
    arr = json.dumps([{"id": 5, "type": "TEXT_AD", "title": "T"}])
    body = _dry_run("ads", "update", "--ads-json", arr)
    assert body["totalItems"] == 1
    assert body["firstChunk"]["params"]["Ads"][0] == {
        "Id": 5,
        "TextAd": {"Title": "T"},
    }


def test_ads_update_batch_chunks_at_100(tmp_path):
    rows = [{"id": i + 1, "type": "TEXT_AD", "title": f"T{i}"} for i in range(250)]
    path = _write_jsonl(tmp_path, rows)
    body = _dry_run("ads", "update", "--from-file", path)
    assert body["chunks"] == 3
    assert body["totalItems"] == 250
    assert len(body["firstChunk"]["params"]["Ads"]) == 100


def test_ads_update_batch_clear_image_hash_per_row(tmp_path):
    rows = [
        {"id": 5, "type": "TEXT_AD", "clear-image-hash": True},
        {"id": 6, "type": "TEXT_AD", "image-hash": "hhh"},
    ]
    path = _write_jsonl(tmp_path, rows)
    body = _dry_run("ads", "update", "--from-file", path)
    ads = body["firstChunk"]["params"]["Ads"]
    assert ads[0] == {"Id": 5, "TextAd": {"AdImageHash": None}}
    assert ads[1] == {"Id": 6, "TextAd": {"AdImageHash": "hhh"}}


def test_ads_update_batch_clear_image_hash_false_is_noop(tmp_path):
    # clear-image-hash:false is the flag-absent state; without another field the
    # row is an empty-subtype no-op and must be rejected.
    path = _write_jsonl(
        tmp_path, [{"id": 5, "type": "TEXT_AD", "clear-image-hash": False}]
    )
    result = _rejected("ads", "update", "--from-file", path)
    assert "Ad update row 1" in result.output
    assert "at least one updatable field" in result.output


def test_ads_update_batch_rejects_unknown_field(tmp_path):
    path = _write_jsonl(tmp_path, [{"id": 5, "type": "TEXT_AD", "foo": "bar"}])
    result = _rejected("ads", "update", "--from-file", path)
    assert "Unknown field 'foo' in ad update row 1" in result.output


def test_ads_update_batch_rejects_non_object_row(tmp_path):
    path = _write_jsonl(tmp_path, [[1, 2, 3]])
    result = _rejected("ads", "update", "--from-file", path)
    assert "Ad update row 1" in result.output
    assert "expected JSON object" in result.output


def test_ads_update_batch_rejects_empty_file(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("\n", encoding="utf-8")
    result = _rejected("ads", "update", "--from-file", str(path))
    assert "Input contains no ad rows" in result.output


def test_ads_update_batch_rejects_invalid_json(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"id":5,"type":"TEXT_AD","title":"T"}\nnope\n', encoding="utf-8")
    result = _rejected("ads", "update", "--from-file", str(path))
    assert "Row 2: invalid JSON" in result.output


def test_ads_update_batch_rejects_missing_id_in_row(tmp_path):
    path = _write_jsonl(tmp_path, [{"type": "TEXT_AD", "title": "T"}])
    result = _rejected("ads", "update", "--from-file", path)
    assert "Ad update row 1" in result.output
    assert "missing required 'id'" in result.output


def test_ads_update_batch_rejects_missing_type_in_row(tmp_path):
    path = _write_jsonl(tmp_path, [{"id": 5, "title": "T"}])
    result = _rejected("ads", "update", "--from-file", path)
    assert "Ad update row 1" in result.output
    assert "missing required 'type'" in result.output


def test_ads_update_batch_rejects_non_positive_id_in_row(tmp_path):
    # IntRange(min=1) must apply per row, same as single --id.
    path = _write_jsonl(tmp_path, [{"id": -5, "type": "TEXT_AD", "title": "T"}])
    result = _rejected("ads", "update", "--from-file", path)
    assert "Ad update row 1 field 'id'" in result.output
    assert "x>=1" in result.output


def test_ads_update_batch_rejects_float_id_in_row(tmp_path):
    # A bare float must be rejected (IntRange), not truncated to an int.
    path = _write_jsonl(tmp_path, [{"id": 5.9, "type": "TEXT_AD", "title": "T"}])
    result = _rejected("ads", "update", "--from-file", path)
    assert "Ad update row 1 field 'id'" in result.output


def test_ads_update_batch_coerces_micro_rubles_like_single(tmp_path):
    # A bare float must be rejected (MICRO_RUBLES is int micro-rubles), exactly
    # like `--price-extension-price 12.5` in single mode — not forwarded raw.
    path = _write_jsonl(
        tmp_path,
        [
            {
                "id": 5,
                "type": "TEXT_AD",
                "price-extension-price": 12.5,
                "price-extension-price-qualifier": "FROM",
                "price-extension-price-currency": "RUB",
            }
        ],
    )
    result = _rejected("ads", "update", "--from-file", path)
    assert "Ad update row 1 field 'price-extension-price'" in result.output


def test_ads_update_batch_valid_micro_rubles_passes_through(tmp_path):
    path = _write_jsonl(
        tmp_path,
        [
            {
                "id": 5,
                "type": "TEXT_AD",
                "price-extension-price": 12500000,
                "price-extension-price-qualifier": "FROM",
                "price-extension-price-currency": "RUB",
            }
        ],
    )
    body = _dry_run("ads", "update", "--from-file", path)
    ad = body["firstChunk"]["params"]["Ads"][0]
    assert ad["TextAd"]["PriceExtension"]["Price"] == 12500000


def test_ads_update_batch_rejects_incompatible_flag_per_row(tmp_path):
    # --action is not valid for TEXT_AD; the per-row guard wraps the message.
    path = _write_jsonl(tmp_path, [{"id": 5, "type": "TEXT_AD", "action": "DOWNLOAD"}])
    result = _rejected("ads", "update", "--from-file", path)
    assert "Ad update row 1" in result.output


def test_ads_update_batch_rejects_invalid_type_per_row(tmp_path):
    path = _write_jsonl(tmp_path, [{"id": 5, "type": "NOPE", "title": "T"}])
    result = _rejected("ads", "update", "--from-file", path)
    assert "Ad update row 1" in result.output
    assert "Invalid value for '--type'" in result.output


def test_ads_update_batch_rejects_empty_subtype_per_row(tmp_path):
    path = _write_jsonl(tmp_path, [{"id": 5, "type": "TEXT_AD"}])
    result = _rejected("ads", "update", "--from-file", path)
    assert "Ad update row 1" in result.output
    assert "at least one updatable field" in result.output


def test_ads_update_batch_rejects_image_hash_clear_mutex_per_row(tmp_path):
    path = _write_jsonl(
        tmp_path,
        [{"id": 5, "type": "TEXT_AD", "image-hash": "hhh", "clear-image-hash": True}],
    )
    result = _rejected("ads", "update", "--from-file", path)
    assert "Ad update row 1" in result.output
    assert "clear-image-hash" in result.output


def test_ads_update_batch_rejects_non_bool_clear_image_hash(tmp_path):
    path = _write_jsonl(
        tmp_path, [{"id": 5, "type": "TEXT_AD", "clear-image-hash": "yes"}]
    )
    result = _rejected("ads", "update", "--from-file", path)
    assert "Ad update row 1 field 'clear-image-hash'" in result.output
    assert "boolean" in result.output


def test_ads_update_batch_rejects_mutex(tmp_path):
    path = _write_jsonl(tmp_path, [{"id": 5, "type": "TEXT_AD", "title": "T"}])
    result = _rejected("ads", "update", "--from-file", path, "--ads-json", "[]")
    assert "mutually exclusive" in result.output


def test_ads_update_batch_rejects_single_flag_in_batch(tmp_path):
    path = _write_jsonl(tmp_path, [{"id": 5, "type": "TEXT_AD", "title": "T"}])
    result = _rejected("ads", "update", "--from-file", path, "--title", "X")
    assert "--title supported only with single-item mode" in result.output


def test_ads_update_batch_rejects_id_flag_in_batch(tmp_path):
    path = _write_jsonl(tmp_path, [{"id": 5, "type": "TEXT_AD", "title": "T"}])
    result = _rejected("ads", "update", "--from-file", path, "--id", "9")
    assert "--id supported only with single-item mode" in result.output


def test_ads_update_single_still_requires_id():
    result = _rejected("ads", "update", "--type", "TEXT_AD", "--title", "T")
    assert "Missing option '--id'." in result.output


def test_ads_update_batch_rejects_non_scalar_id(tmp_path):
    path = _write_jsonl(tmp_path, [{"id": [5], "type": "TEXT_AD", "title": "T"}])
    result = _rejected("ads", "update", "--from-file", path)
    assert "Ad update row 1 field 'id'" in result.output
    assert "expected a scalar" in result.output
