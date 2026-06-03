"""Shared autotargeting CLI helpers for ad groups and keywords.

``adgroups`` (DynamicTextAdGroup/DynamicTextFeedAdGroup) and ``keywords`` both
parse the same AutotargetingCategories / AutotargetingSettings CLI surface.
The helpers used to be duplicated in each command module and had drifted
(category-token normalization, and which legacy flags conflict with the typed
``AutotargetingSettings`` flags). This module is the single source of truth.

The legacy-mix guard models an **intentional** asymmetry explicitly via
``legacy_candidates``: ``adgroups`` treats only ``--autotargeting-category`` as
legacy (it has no ``--autotargeting-brand-option`` flag at all), while
``keywords`` treats both ``--autotargeting-category`` and
``--autotargeting-brand-option`` as legacy.

Token normalization is unified on :func:`normalize_enum_token` for both
categories and brand options. For categories this is behavior-preserving (the
constants are single words with no ``_``, so ``-``->``_`` only ever touches
already-invalid tokens). For brand options it is a deliberate *loosening*: the
constants contain underscores (``WITHOUT_BRANDS``), so the hyphenated spelling
(``WITHOUT-BRANDS``) — rejected by the old flat ``.strip().upper()`` — is now
accepted, making every autotargeting enum normalize identically.
"""

from typing import Dict, List, Optional, Sequence, Tuple

import click

from .i18n import t

AUTOTARGETING_CATEGORIES = (
    "EXACT",
    "ALTERNATIVE",
    "COMPETITOR",
    "BROADER",
    "ACCESSORY",
)
AUTOTARGETING_BRAND_OPTIONS = (
    "WITHOUT_BRANDS",
    "WITH_ADVERTISER_BRAND",
)


def normalize_enum_token(value: str) -> str:
    """Normalize enum-like CLI tokens to Yandex Direct uppercase constants."""
    return value.strip().upper().replace("-", "_")


def parse_autotargeting_categories(
    raw_values: Tuple[str, ...],
) -> Optional[List[Dict[str, str]]]:
    """Parse AutotargetingCategories CLI items (CATEGORY=YES|NO)."""
    if not raw_values:
        return None

    allowed_categories = ", ".join(AUTOTARGETING_CATEGORIES)
    items: List[Dict[str, str]] = []
    for raw_value in raw_values:
        category_raw, separator, value_raw = raw_value.strip().partition("=")
        if not separator:
            raise click.UsageError(
                t(
                    "--autotargeting-category expects CATEGORY=YES|NO "
                    "(for example EXACT=YES)"
                )
            )

        category = normalize_enum_token(category_raw)
        value = normalize_enum_token(value_raw)
        if category not in AUTOTARGETING_CATEGORIES:
            raise click.UsageError(
                t(
                    "Invalid --autotargeting-category category {category_raw!r}; "
                    "allowed: {allowed_categories}"
                ).format(
                    category_raw=category_raw, allowed_categories=allowed_categories
                )
            )
        if value not in {"YES", "NO"}:
            raise click.UsageError(
                t(
                    "Invalid --autotargeting-category value {value_raw!r}; "
                    "expected YES or NO"
                ).format(value_raw=value_raw)
            )
        items.append({"Category": category, "Value": value})

    return items


def parse_autotargeting_brand_options(
    raw_values: Tuple[str, ...],
) -> Optional[List[Dict[str, str]]]:
    """Parse AutotargetingSettings BrandOptions CLI items (OPTION=YES|NO)."""
    if not raw_values:
        return None

    allowed_options = ", ".join(AUTOTARGETING_BRAND_OPTIONS)
    items: List[Dict[str, str]] = []
    for raw_value in raw_values:
        option_raw, separator, value_raw = raw_value.strip().partition("=")
        if not separator:
            raise click.UsageError(
                t(
                    "--autotargeting-brand-option expects OPTION=YES|NO "
                    "(for example WITHOUT_BRANDS=YES)"
                )
            )

        option = normalize_enum_token(option_raw)
        value = normalize_enum_token(value_raw)
        if option not in AUTOTARGETING_BRAND_OPTIONS:
            raise click.UsageError(
                t(
                    "Invalid --autotargeting-brand-option option {option_raw!r}; "
                    "allowed: {allowed_options}"
                ).format(option_raw=option_raw, allowed_options=allowed_options)
            )
        if value not in {"YES", "NO"}:
            raise click.UsageError(
                t(
                    "Invalid --autotargeting-brand-option value {value_raw!r}; "
                    "expected YES or NO"
                ).format(value_raw=value_raw)
            )

        items.append({"Option": option, "Value": value})

    return items


def build_autotargeting_settings(
    *,
    exact: Optional[str],
    narrow: Optional[str],
    alternative: Optional[str],
    accessory: Optional[str],
    broader: Optional[str],
    without_brands: Optional[str],
    with_advertiser_brand: Optional[str],
    with_competitors_brand: Optional[str],
) -> Optional[Dict[str, Dict[str, str]]]:
    """Build AutotargetingSettings (Categories + BrandOptions) from typed flags."""
    categories: Dict[str, str] = {}
    for field_name, value in (
        ("Exact", exact),
        ("Narrow", narrow),
        ("Alternative", alternative),
        ("Accessory", accessory),
        ("Broader", broader),
    ):
        if value is not None:
            categories[field_name] = value.upper()

    brand_options: Dict[str, str] = {}
    for field_name, value in (
        ("WithoutBrands", without_brands),
        ("WithAdvertiserBrand", with_advertiser_brand),
        ("WithCompetitorsBrand", with_competitors_brand),
    ):
        if value is not None:
            brand_options[field_name] = value.upper()

    settings: Dict[str, Dict[str, str]] = {}
    if categories:
        settings["Categories"] = categories
    if brand_options:
        settings["BrandOptions"] = brand_options

    return settings or None


def reject_legacy_autotargeting_mix(
    settings: Optional[Dict[str, Dict[str, str]]],
    *,
    legacy_candidates: Sequence[Tuple[str, bool]],
) -> None:
    """Reject typed AutotargetingSettings combined with legacy autotargeting flags.

    ``legacy_candidates`` is an ordered ``(flag_name, supplied)`` sequence that
    declares which flags count as legacy for the calling resource. Ad groups
    declare only ``--autotargeting-category``; keywords declare both
    ``--autotargeting-category`` and ``--autotargeting-brand-option``. The
    error message preserves both original source strings so every translation
    catalog entry stays referenced and the rendered output is unchanged.
    """
    if settings is None:
        return

    declared = [flag for flag, _ in legacy_candidates]
    supplied = [flag for flag, present in legacy_candidates if present]
    if not supplied:
        return

    if declared == ["--autotargeting-category"]:
        raise click.UsageError(
            t(
                "AutotargetingSettings flags cannot be combined with legacy "
                "--autotargeting-category flags."
            )
        )

    raise click.UsageError(
        t(
            "AutotargetingSettings flags cannot be combined with legacy {arg0} flags."
        ).format(arg0=", ".join(supplied))
    )
