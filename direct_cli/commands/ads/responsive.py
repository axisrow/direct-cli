"""RESPONSIVE_AD payload assembly (#603)."""

from __future__ import annotations

from typing import Any, Mapping, Optional

import click

from ...i18n import t
from ...utils import parse_ids
from .base import (
    _build_price_extension_add,
    _parse_required_csv_strings,
    _parse_required_ids,
)

RESPONSIVE_AD_ADD_FIELDS = {
    "texts",
    "titles",
    "href",
    "age_label",
    "display_url_path",
    "image_hashes",
    "sitelink_set_id",
    "ad_extensions",
    "video_extension_ids",
    "price_extension_price",
    "price_extension_old_price",
    "price_extension_price_qualifier",
    "price_extension_price_currency",
    "business_id",
    "erir_ad_description",
}

RESPONSIVE_AD_UPDATE_FIELDS = {
    "texts",
    "titles",
    "image_hashes",
    "video_extension_ids",
    "sitelink_set_id",
    "callouts_add",
    "callouts_remove",
    "callouts_set",
    "href",
    "age_label",
    "display_url_path",
    "price_extension_price",
    "price_extension_old_price",
    "price_extension_price_qualifier",
    "price_extension_price_currency",
    "business_id",
    "erir_ad_description",
}


def _build_responsive_ad_update(
    texts: Optional[str],
    titles: Optional[str],
    image_hashes: Optional[str],
    video_extension_ids: Optional[str],
    sitelink_set_id: Optional[int],
    callout_setting: Optional[dict[str, Any]],
    href: Optional[str],
    age_label: Optional[str],
    display_url_path: Optional[str],
    price_extension: Optional[dict[str, object]],
    business_id: Optional[int],
    erir_ad_description: Optional[str],
) -> dict[str, object]:
    """Build ResponsiveAdUpdate payload from typed flags."""
    responsive_ad: dict[str, object] = {}

    parsed_texts = _parse_required_csv_strings(texts, "--texts")
    if parsed_texts:
        responsive_ad["Texts"] = parsed_texts
    parsed_titles = _parse_required_csv_strings(titles, "--titles")
    if parsed_titles:
        responsive_ad["Titles"] = parsed_titles
    parsed_image_hashes = _parse_required_csv_strings(image_hashes, "--image-hashes")
    if parsed_image_hashes:
        responsive_ad["AdImageHashes"] = {"Items": parsed_image_hashes}
    parsed_video_extension_ids = _parse_required_ids(
        video_extension_ids, "--video-extension-ids"
    )
    if parsed_video_extension_ids:
        responsive_ad["VideoExtensionIds"] = {"Items": parsed_video_extension_ids}
    if sitelink_set_id is not None:
        responsive_ad["SitelinkSetId"] = sitelink_set_id
    if callout_setting:
        responsive_ad["CalloutSetting"] = callout_setting
    if href:
        responsive_ad["Href"] = href
    if age_label:
        responsive_ad["AgeLabel"] = age_label.upper()
    if display_url_path:
        responsive_ad["DisplayUrlPath"] = display_url_path
    if price_extension:
        responsive_ad["PriceExtension"] = price_extension
    if business_id is not None:
        responsive_ad["BusinessId"] = business_id
    if erir_ad_description:
        responsive_ad["ErirAdDescription"] = erir_ad_description

    return responsive_ad


def build_responsive_ad_add_block(
    ad_data: dict[str, Any],
    flags: Mapping[str, Any],
    mobile: str,
) -> None:
    """Compose ``ad_data["ResponsiveAd"]`` for ``ads add`` (registry handler).

    Verbatim extract of the former inline ``RESPONSIVE_AD`` branch of
    ``build_ad_object`` (epic #961, track 5).
    """
    texts = flags.get("texts")
    titles = flags.get("titles")
    href = flags.get("href")
    business_id = flags.get("business_id")
    image_hashes = flags.get("image_hashes")
    video_extension_ids = flags.get("video_extension_ids")
    sitelink_set_id = flags.get("sitelink_set_id")
    ad_extensions = flags.get("ad_extensions")
    age_label = flags.get("age_label")
    display_url_path = flags.get("display_url_path")
    price_extension_price = flags.get("price_extension_price")
    price_extension_old_price = flags.get("price_extension_old_price")
    price_extension_price_qualifier = flags.get("price_extension_price_qualifier")
    price_extension_price_currency = flags.get("price_extension_price_currency")
    erir_ad_description = flags.get("erir_ad_description")

    missing_fields = [
        option_name
        for option_name, value in (
            ("--texts", texts),
            ("--titles", titles),
        )
        if value is None
    ]
    if missing_fields:
        raise click.UsageError(
            t("RESPONSIVE_AD requires {arg0}").format(arg0=", ".join(missing_fields))
        )
    if not href and business_id is None:
        raise click.UsageError(
            t("RESPONSIVE_AD requires either --href or --business-id.")
        )

    parsed_texts = _parse_required_csv_strings(texts, "--texts")
    parsed_titles = _parse_required_csv_strings(titles, "--titles")
    responsive_ad: dict[str, Any] = {
        "Texts": parsed_texts,
        "Titles": parsed_titles,
    }
    parsed_image_hashes = _parse_required_csv_strings(image_hashes, "--image-hashes")
    if parsed_image_hashes:
        responsive_ad["AdImageHashes"] = parsed_image_hashes
    parsed_video_extension_ids = _parse_required_ids(
        video_extension_ids, "--video-extension-ids"
    )
    if parsed_video_extension_ids:
        responsive_ad["VideoExtensionIds"] = parsed_video_extension_ids
    if sitelink_set_id is not None:
        responsive_ad["SitelinkSetId"] = sitelink_set_id
    if ad_extensions:
        responsive_ad["AdExtensionIds"] = parse_ids(ad_extensions)
    if href:
        responsive_ad["Href"] = href
    if age_label:
        responsive_ad["AgeLabel"] = age_label.upper()
    if display_url_path:
        responsive_ad["DisplayUrlPath"] = display_url_path
    price_extension = _build_price_extension_add(
        price_extension_price,
        price_extension_old_price,
        price_extension_price_qualifier,
        price_extension_price_currency,
        container_name="ResponsiveAd",
    )
    if price_extension:
        responsive_ad["PriceExtension"] = price_extension
    if business_id is not None:
        responsive_ad["BusinessId"] = business_id
    if erir_ad_description:
        responsive_ad["ErirAdDescription"] = erir_ad_description
    ad_data["ResponsiveAd"] = responsive_ad


def build_responsive_ad_update_block(
    ad_data: dict[str, Any],
    flags: Mapping[str, Any],
    precomputed: Mapping[str, Any],
) -> None:
    """Compose ``ad_data["ResponsiveAd"]`` for ``ads update`` (registry handler).

    Thin wrapper over :func:`_build_responsive_ad_update`, moved here from the
    former inline ``RESPONSIVE_AD`` branch of ``build_ad_update_object``
    (epic #961, track 5).
    """
    responsive_ad = _build_responsive_ad_update(
        flags.get("texts"),
        flags.get("titles"),
        flags.get("image_hashes"),
        flags.get("video_extension_ids"),
        flags.get("sitelink_set_id"),
        precomputed["callout_setting"],
        flags.get("href"),
        flags.get("age_label"),
        flags.get("display_url_path"),
        precomputed["price_extension"],
        flags.get("business_id"),
        flags.get("erir_ad_description"),
    )
    if responsive_ad:
        ad_data["ResponsiveAd"] = responsive_ad
