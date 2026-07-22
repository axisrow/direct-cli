"""RESPONSIVE_AD payload assembly (#603)."""

from __future__ import annotations

from typing import Any, Optional

from .base import _parse_required_csv_strings, _parse_required_ids

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
