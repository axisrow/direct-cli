"""MOBILE_APP_AD / MOBILE_APP_IMAGE_AD payload assembly (#603)."""

from __future__ import annotations

from typing import Any, Mapping, Optional

import click

from ...i18n import t
from .base import _parse_mobile_app_features

MOBILE_APP_AD_ADD_FIELDS = {
    "title",
    "text",
    "image_hash",
    "action",
    "tracking_url",
    "age_label",
    "mobile_app_features",
    "video_extension_creative_id",
    "erir_ad_description",
}

MOBILE_APP_IMAGE_AD_ADD_FIELDS = {
    "image_hash",
    "tracking_url",
    "erir_ad_description",
}

MOBILE_APP_AD_UPDATE_FIELDS = {
    "title",
    "text",
    "image_hash",
    "clear_image_hash",
    "action",
    "tracking_url",
    "age_label",
    "mobile_app_features",
    "video_extension_creative_id",
    "erir_ad_description",
}

# MOBILE_APP_IMAGE_AD inherits WSDL ImageAdUpdateBase, whose AdImageHash is not
# nillable — no ``clear_image_hash`` here (see ads.text for the full note).
MOBILE_APP_IMAGE_UPDATE_FIELDS = {
    "image_hash",
    "tracking_url",
    "erir_ad_description",
}


def _build_mobile_app_image_ad_update(
    image_hash: Optional[str],
    erir_ad_description: Optional[str],
    tracking_url: Optional[str],
) -> dict[str, object]:
    """Build MobileAppImageAdUpdate payload from typed flags.

    No ``clear_image_hash`` path: ImageAdUpdateBase.AdImageHash is not nillable
    and the live API rejects ``null`` for this subtype (error 8000).
    """
    mobile_app_image_ad: dict[str, object] = {}

    if image_hash:
        mobile_app_image_ad["AdImageHash"] = image_hash
    if erir_ad_description:
        mobile_app_image_ad["ErirAdDescription"] = erir_ad_description
    if tracking_url:
        mobile_app_image_ad["TrackingUrl"] = tracking_url

    return mobile_app_image_ad


def _build_mobile_app_image_ad_add(
    image_hash: Optional[str],
    erir_ad_description: Optional[str],
    tracking_url: Optional[str],
) -> dict[str, object]:
    """Build MobileAppImageAdAdd payload from typed flags."""
    if not image_hash:
        raise click.UsageError(t("MOBILE_APP_IMAGE_AD requires --image-hash"))

    mobile_app_image_ad: dict[str, object] = {"AdImageHash": image_hash}
    if erir_ad_description:
        mobile_app_image_ad["ErirAdDescription"] = erir_ad_description
    if tracking_url:
        mobile_app_image_ad["TrackingUrl"] = tracking_url

    return mobile_app_image_ad


def build_mobile_app_ad_add_block(
    ad_data: dict[str, Any],
    flags: Mapping[str, Any],
    mobile: str,
) -> None:
    """Compose ``ad_data["MobileAppAd"]`` for ``ads add`` (registry handler).

    Verbatim extract of the former inline ``MOBILE_APP_AD`` branch of
    ``build_ad_object`` (epic #961, track 5). ``mobile`` is only carried for
    the uniform registry signature; MOBILE_APP_AD has no ``Mobile`` field.
    """
    title = flags.get("title")
    text = flags.get("text")
    href = flags.get("href")
    action = flags.get("action")
    image_hash = flags.get("image_hash")
    tracking_url = flags.get("tracking_url")
    age_label = flags.get("age_label")
    mobile_app_features = flags.get("mobile_app_features") or ()
    video_extension_creative_id = flags.get("video_extension_creative_id")
    erir_ad_description = flags.get("erir_ad_description")

    if href:
        raise click.UsageError(
            t("--href does not apply to MOBILE_APP_AD. Use --tracking-url instead.")
        )
    missing_fields = [
        option_name
        for option_name, value in (
            ("--title", title),
            ("--text", text),
            ("--action", action),
        )
        if not value
    ]
    if missing_fields:
        raise click.UsageError(
            t("MOBILE_APP_AD requires {arg0}").format(arg0=", ".join(missing_fields))
        )
    mobile_app_ad = {
        "Title": title,
        "Text": text,
        "Action": action.upper(),
    }
    if image_hash:
        mobile_app_ad["AdImageHash"] = image_hash
    if tracking_url:
        mobile_app_ad["TrackingUrl"] = tracking_url
    if age_label:
        mobile_app_ad["AgeLabel"] = age_label.upper()
    parsed_features = _parse_mobile_app_features(mobile_app_features)
    if parsed_features:
        mobile_app_ad["Features"] = parsed_features
    if video_extension_creative_id is not None:
        mobile_app_ad["VideoExtension"] = {"CreativeId": video_extension_creative_id}
    if erir_ad_description:
        mobile_app_ad["ErirAdDescription"] = erir_ad_description
    ad_data["MobileAppAd"] = mobile_app_ad


def build_mobile_app_ad_update_block(
    ad_data: dict[str, Any],
    flags: Mapping[str, Any],
    precomputed: Mapping[str, Any],
) -> None:
    """Compose ``ad_data["MobileAppAd"]`` for ``ads update`` (registry handler).

    Verbatim extract of the former inline ``MOBILE_APP_AD`` branch of
    ``build_ad_update_object`` (epic #961, track 5).
    """
    title = flags.get("title")
    text = flags.get("text")
    image_hash = flags.get("image_hash")
    clear_image_hash = flags.get("clear_image_hash")
    action = flags.get("action")
    tracking_url = flags.get("tracking_url")
    age_label = flags.get("age_label")
    video_extension_creative_id = flags.get("video_extension_creative_id")
    erir_ad_description = flags.get("erir_ad_description")
    parsed_mobile_app_features = precomputed["parsed_mobile_app_features"]

    mobile_app_ad = {}
    if title:
        mobile_app_ad["Title"] = title
    if text:
        mobile_app_ad["Text"] = text
    if clear_image_hash:
        mobile_app_ad["AdImageHash"] = None
    elif image_hash:
        mobile_app_ad["AdImageHash"] = image_hash
    if action:
        mobile_app_ad["Action"] = action.upper()
    if tracking_url:
        mobile_app_ad["TrackingUrl"] = tracking_url
    if parsed_mobile_app_features:
        mobile_app_ad["Features"] = parsed_mobile_app_features
    if age_label:
        mobile_app_ad["AgeLabel"] = age_label.upper()
    if video_extension_creative_id is not None:
        mobile_app_ad["VideoExtension"] = {"CreativeId": video_extension_creative_id}
    if erir_ad_description:
        mobile_app_ad["ErirAdDescription"] = erir_ad_description
    if mobile_app_ad:
        ad_data["MobileAppAd"] = mobile_app_ad


def build_mobile_app_image_ad_add_block(
    ad_data: dict[str, Any],
    flags: Mapping[str, Any],
    mobile: str,
) -> None:
    """Compose ``ad_data["MobileAppImageAd"]`` for ``ads add`` (registry handler)."""
    ad_data["MobileAppImageAd"] = _build_mobile_app_image_ad_add(
        flags.get("image_hash"),
        flags.get("erir_ad_description"),
        flags.get("tracking_url"),
    )


def build_mobile_app_image_ad_update_block(
    ad_data: dict[str, Any],
    flags: Mapping[str, Any],
    precomputed: Mapping[str, Any],
) -> None:
    """Compose ``ad_data["MobileAppImageAd"]`` for ``ads update`` (registry handler)."""
    mobile_app_image_ad = _build_mobile_app_image_ad_update(
        flags.get("image_hash"),
        flags.get("erir_ad_description"),
        flags.get("tracking_url"),
    )
    if mobile_app_image_ad:
        ad_data["MobileAppImageAd"] = mobile_app_image_ad
