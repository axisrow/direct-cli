"""Unit tests for the shared autotargeting helpers (direct_cli/_autotargeting.py).

These lock in the **intentional asymmetry** between ad groups and keywords:
ad groups treat only ``--autotargeting-category`` as legacy (there is no
``--autotargeting-brand-option`` flag for ad groups), while keywords treat both
``--autotargeting-category`` and ``--autotargeting-brand-option`` as legacy.
"""

import pytest
from click import UsageError

from direct_cli import i18n
from direct_cli._autotargeting import (
    AUTOTARGETING_BRAND_OPTIONS,
    AUTOTARGETING_CATEGORIES,
    build_autotargeting_settings,
    normalize_enum_token,
    parse_autotargeting_brand_options,
    parse_autotargeting_categories,
    reject_legacy_autotargeting_mix,
)


@pytest.fixture(autouse=True)
def _pin_english_locale():
    """These helpers are called directly (not via the CLI), so t() uses the
    process-level active locale (default Russian). Pin English to assert the
    stable English source strings, then restore."""
    previous = i18n.get_active_locale()
    i18n.set_active_locale("en")
    try:
        yield
    finally:
        i18n.set_active_locale(previous)


def test_normalize_enum_token_uppercases_and_replaces_hyphen():
    assert normalize_enum_token(" with-advertiser-brand ") == "WITH_ADVERTISER_BRAND"


def test_parse_autotargeting_categories_none_for_empty():
    assert parse_autotargeting_categories(()) is None


def test_parse_autotargeting_categories_valid_uppercases_and_trims():
    result = parse_autotargeting_categories((" exact=yes ", "ALTERNATIVE=no"))
    assert result == [
        {"Category": "EXACT", "Value": "YES"},
        {"Category": "ALTERNATIVE", "Value": "NO"},
    ]


def test_parse_autotargeting_categories_requires_equals():
    with pytest.raises(UsageError):
        parse_autotargeting_categories(("EXACT",))


def test_parse_autotargeting_categories_rejects_unknown_category():
    with pytest.raises(UsageError):
        parse_autotargeting_categories(("BOGUS=YES",))


def test_parse_autotargeting_categories_rejects_bad_value():
    with pytest.raises(UsageError):
        parse_autotargeting_categories(("EXACT=MAYBE",))


def test_parse_autotargeting_categories_hyphen_normalization_still_rejects_garbage():
    # The unified normalization maps "-" -> "_"; a hyphenated garbage token is
    # still rejected (behavior-preserving vs the old inline .strip().upper()).
    with pytest.raises(UsageError):
        parse_autotargeting_categories(("EX-ACT=YES",))


def test_parse_autotargeting_brand_options_none_for_empty():
    assert parse_autotargeting_brand_options(()) is None


def test_parse_autotargeting_brand_options_valid():
    result = parse_autotargeting_brand_options(("without_brands=yes",))
    assert result == [{"Option": "WITHOUT_BRANDS", "Value": "YES"}]


def test_parse_autotargeting_brand_options_normalizes_hyphen_to_underscore():
    # Brand-option constants contain underscores (WITHOUT_BRANDS), so unifying
    # on normalize_enum_token intentionally accepts the hyphenated spelling that
    # the old flat .strip().upper() rejected. Lock the loosening in as deliberate
    # (the symmetric category case stays rejected: EX-ACT has no underscore form).
    result = parse_autotargeting_brand_options(("WITHOUT-BRANDS=YES",))
    assert result == [{"Option": "WITHOUT_BRANDS", "Value": "YES"}]


def test_parse_autotargeting_brand_options_rejects_unknown_option():
    with pytest.raises(UsageError):
        parse_autotargeting_brand_options(("UNKNOWN=YES",))


def test_parse_autotargeting_brand_options_rejects_bad_value():
    with pytest.raises(UsageError):
        parse_autotargeting_brand_options(("WITHOUT_BRANDS=MAYBE",))


def test_build_autotargeting_settings_none_when_all_none():
    assert (
        build_autotargeting_settings(
            exact=None,
            narrow=None,
            alternative=None,
            accessory=None,
            broader=None,
            without_brands=None,
            with_advertiser_brand=None,
            with_competitors_brand=None,
        )
        is None
    )


def test_build_autotargeting_settings_categories_and_brand_options():
    result = build_autotargeting_settings(
        exact="yes",
        narrow=None,
        alternative=None,
        accessory=None,
        broader=None,
        without_brands="no",
        with_advertiser_brand=None,
        with_competitors_brand=None,
    )
    assert result == {
        "Categories": {"Exact": "YES"},
        "BrandOptions": {"WithoutBrands": "NO"},
    }


def test_reject_legacy_mix_returns_when_no_settings():
    # No settings -> nothing to conflict with, regardless of legacy candidates.
    reject_legacy_autotargeting_mix(
        None,
        legacy_candidates=[("--autotargeting-category", True)],
    )


def test_reject_legacy_mix_adgroups_category_only_raises_fixed_message():
    settings = {"Categories": {"Exact": "YES"}}
    with pytest.raises(UsageError) as exc:
        reject_legacy_autotargeting_mix(
            settings,
            legacy_candidates=[("--autotargeting-category", True)],
        )
    assert exc.value.format_message() == (
        "AutotargetingSettings flags cannot be combined with legacy "
        "--autotargeting-category flags."
    )


def test_reject_legacy_mix_adgroups_no_category_does_not_raise():
    settings = {"Categories": {"Exact": "YES"}}
    reject_legacy_autotargeting_mix(
        settings,
        legacy_candidates=[("--autotargeting-category", False)],
    )


def test_reject_legacy_mix_keywords_category_only_matches_adgroups_text():
    # keywords declares both candidates but supplies only category: the rendered
    # message must equal the ad-groups fixed message.
    settings = {"Categories": {"Exact": "YES"}}
    with pytest.raises(UsageError) as exc:
        reject_legacy_autotargeting_mix(
            settings,
            legacy_candidates=[
                ("--autotargeting-category", True),
                ("--autotargeting-brand-option", False),
            ],
        )
    assert exc.value.format_message() == (
        "AutotargetingSettings flags cannot be combined with legacy "
        "--autotargeting-category flags."
    )


def test_reject_legacy_mix_keywords_brand_option_only_is_legacy():
    # The crux of the intentional asymmetry: for keywords, --autotargeting-brand-option
    # IS legacy and conflicts with AutotargetingSettings.
    settings = {"BrandOptions": {"WithoutBrands": "YES"}}
    with pytest.raises(UsageError) as exc:
        reject_legacy_autotargeting_mix(
            settings,
            legacy_candidates=[
                ("--autotargeting-category", False),
                ("--autotargeting-brand-option", True),
            ],
        )
    assert exc.value.format_message() == (
        "AutotargetingSettings flags cannot be combined with legacy "
        "--autotargeting-brand-option flags."
    )


def test_reject_legacy_mix_keywords_both_joins_flag_names():
    settings = {"Categories": {"Exact": "YES"}}
    with pytest.raises(UsageError) as exc:
        reject_legacy_autotargeting_mix(
            settings,
            legacy_candidates=[
                ("--autotargeting-category", True),
                ("--autotargeting-brand-option", True),
            ],
        )
    assert exc.value.format_message() == (
        "AutotargetingSettings flags cannot be combined with legacy "
        "--autotargeting-category, --autotargeting-brand-option flags."
    )


def test_category_and_brand_option_constants_are_uppercase_enums():
    assert AUTOTARGETING_CATEGORIES == (
        "EXACT",
        "ALTERNATIVE",
        "COMPETITOR",
        "BROADER",
        "ACCESSORY",
    )
    assert AUTOTARGETING_BRAND_OPTIONS == (
        "WITHOUT_BRANDS",
        "WITH_ADVERTISER_BRAND",
    )
