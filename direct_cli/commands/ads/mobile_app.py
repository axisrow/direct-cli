"""MOBILE_APP_AD / MOBILE_APP_IMAGE_AD payload assembly (#603)."""

from __future__ import annotations

from typing import Optional

import click

from ...i18n import t

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
