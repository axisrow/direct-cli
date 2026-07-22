"""Shared validation and payload helpers for every ``ads`` subtype (#603).

These helpers are subtype-agnostic: the incompatible-flag guard used by both
``build_ad_object`` and ``build_ad_update_object``, the callout-setting builder
shared by all text-like update payloads, and the CSV/ID parsers used across
subtype modules. Type-specific assembly lives in the sibling modules
(:mod:`.text`, :mod:`.responsive`, :mod:`.shopping`, :mod:`.mobile_app`,
:mod:`.builder`).
"""

from __future__ import annotations

from typing import Optional

import click

from ...i18n import t
from ...utils import parse_csv_strings, parse_ids

MOBILE_APP_FEATURES = ("PRICE", "ICON", "CUSTOMER_RATING", "RATINGS")


def _reject_incompatible_flags(
    ad_type: str,
    allowed_fields: set[str],
    provided: dict[str, object],
    flag_for: dict[str, str],
) -> None:
    """Reject typed flags that do not belong to the selected ad subtype."""
    incompatible = [
        flag_for[name]
        for name, value in provided.items()
        if value is not None and value != () and name not in allowed_fields
    ]
    if incompatible:
        allowed_flags = ", ".join(sorted(flag_for[name] for name in allowed_fields))
        raise click.UsageError(
            t(
                "{arg0} is not compatible with --type {ad_type}. "
                "Allowed flags for {ad_type}: {allowed_flags}."
            ).format(
                arg0=", ".join(incompatible),
                ad_type=ad_type,
                allowed_flags=allowed_flags,
            )
        )


def _build_callout_setting(callouts_add, callouts_remove, callouts_set):
    """Build AdExtensionSetting for text-like ad update payloads.

    SET is mutually exclusive with ADD/REMOVE per WSDL OperationEnum
    semantics. Returns None when no callout flag was provided.
    """
    if callouts_set and (callouts_add or callouts_remove):
        raise click.UsageError(
            t(
                "--callouts-set is mutually exclusive with "
                "--callouts-add / --callouts-remove. "
                "Use --callouts-set to replace the full callout list, "
                "or --callouts-add / --callouts-remove for incremental edits."
            )
        )
    items = []
    for csv_value, op in (
        (callouts_set, "SET"),
        (callouts_add, "ADD"),
        (callouts_remove, "REMOVE"),
    ):
        if csv_value is None:
            continue
        try:
            ids = parse_ids(csv_value)
        except ValueError as exc:
            raise click.UsageError(
                t("--callouts-{arg0}: {exc}").format(arg0=op.lower(), exc=exc)
            )
        if not ids:
            raise click.UsageError(
                t(
                    "--callouts-{arg0} must contain at least one ad extension ID."
                ).format(arg0=op.lower())
            )
        for ad_ext_id in ids:
            items.append({"AdExtensionId": ad_ext_id, "Operation": op})
    if not items:
        return None
    return {"AdExtensions": items}


def _build_price_extension(
    price_extension_price,
    price_extension_old_price,
    price_extension_price_qualifier,
    price_extension_price_currency,
):
    """Build TextAd.PriceExtension update payload from typed flags."""
    price_extension = {}
    if price_extension_price is not None:
        price_extension["Price"] = price_extension_price
    if price_extension_old_price is not None:
        price_extension["OldPrice"] = price_extension_old_price
    if price_extension_price_qualifier:
        price_extension["PriceQualifier"] = price_extension_price_qualifier.upper()
    if price_extension_price_currency:
        price_extension["PriceCurrency"] = price_extension_price_currency.upper()
    return price_extension or None


def _build_price_extension_add(
    price_extension_price,
    price_extension_old_price,
    price_extension_price_qualifier,
    price_extension_price_currency,
    container_name="TextAd",
):
    """Build PriceExtension add payload for an ad subtype from typed flags."""
    provided = (
        price_extension_price is not None
        or price_extension_old_price is not None
        or price_extension_price_qualifier
        or price_extension_price_currency
    )
    if not provided:
        return None

    missing = []
    if price_extension_price is None:
        missing.append("--price-extension-price")
    if not price_extension_price_qualifier:
        missing.append("--price-extension-price-qualifier")
    if not price_extension_price_currency:
        missing.append("--price-extension-price-currency")
    if missing:
        raise click.UsageError(
            t("{container_name}.PriceExtension add requires {arg0}").format(
                container_name=container_name, arg0=", ".join(missing)
            )
        )

    price_extension = {
        "Price": price_extension_price,
        "PriceQualifier": price_extension_price_qualifier.upper(),
        "PriceCurrency": price_extension_price_currency.upper(),
    }
    if price_extension_old_price is not None:
        price_extension["OldPrice"] = price_extension_old_price
    return price_extension


def _parse_required_csv_strings(
    csv_value: Optional[str], flag_name: str
) -> Optional[list[str]]:
    """Parse a comma-separated string list that must not be empty if present."""
    if csv_value is None:
        return None
    values = parse_csv_strings(csv_value)
    if not values:
        raise click.UsageError(
            t("{flag_name} must contain at least one value.").format(
                flag_name=flag_name
            )
        )
    return values


def _parse_required_ids(
    csv_value: Optional[str], flag_name: str
) -> Optional[list[int]]:
    """Parse a comma-separated integer list that must not be empty if present."""
    if csv_value is None:
        return None
    try:
        ids = parse_ids(csv_value)
    except ValueError as exc:
        raise click.UsageError(
            t("{flag_name}: {exc}").format(flag_name=flag_name, exc=exc)
        )
    if not ids:
        raise click.UsageError(
            t("{flag_name} must contain at least one ID.").format(flag_name=flag_name)
        )
    return ids


def _parse_mobile_app_features(
    raw_values: tuple[str, ...],
) -> Optional[list[dict[str, str]]]:
    """Parse repeatable MobileAppAd.Features items as FEATURE=YES|NO."""
    if not raw_values:
        return None

    items: list[dict[str, str]] = []
    allowed_features = ", ".join(MOBILE_APP_FEATURES)
    for raw_value in raw_values:
        feature_raw, separator, enabled_raw = raw_value.strip().partition("=")
        if not separator:
            raise click.UsageError(
                t(
                    "--mobile-app-feature expects FEATURE=YES|NO "
                    "(for example PRICE=YES)."
                )
            )

        feature = feature_raw.strip().upper()
        enabled = enabled_raw.strip().upper()
        if feature not in MOBILE_APP_FEATURES:
            raise click.UsageError(
                t(
                    "Invalid --mobile-app-feature feature {feature_raw!r}; "
                    "allowed: {allowed_features}."
                ).format(feature_raw=feature_raw, allowed_features=allowed_features)
            )
        if enabled not in {"YES", "NO"}:
            raise click.UsageError(
                t(
                    "Invalid --mobile-app-feature value {enabled_raw!r}; "
                    "expected YES or NO."
                ).format(enabled_raw=enabled_raw)
            )

        items.append({"Feature": feature, "Enabled": enabled})

    return items


__all__ = [
    "MOBILE_APP_FEATURES",
    "_build_callout_setting",
    "_build_price_extension",
    "_build_price_extension_add",
    "_parse_mobile_app_features",
    "_parse_required_csv_strings",
    "_parse_required_ids",
    "_reject_incompatible_flags",
]
