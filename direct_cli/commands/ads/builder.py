"""*_AD_BUILDER_AD and SMART_AD_BUILDER_AD payload assembly (#603).

The six ``*AdBuilderAd`` subtypes share one WSDL shape (a ``Creative`` block plus
a destination field set that varies per subtype), so a single pair of builders
covers them; ``SMART_AD_BUILDER_AD`` is a separate WSDL type with its own pair.
"""

from __future__ import annotations

from typing import Optional

import click

from ...i18n import t
from .base import _parse_required_csv_strings

AD_BUILDER_BASE_UPDATE_FIELDS = {
    "creative_id",
    "creative_erir_ad_description",
    "erir_ad_description",
}

AD_BUILDER_TYPE_FIELDS = {
    "TEXT_AD_BUILDER_AD": AD_BUILDER_BASE_UPDATE_FIELDS
    | {"final_url", "href", "turbo_page_id"},
    "MOBILE_APP_AD_BUILDER_AD": AD_BUILDER_BASE_UPDATE_FIELDS | {"tracking_url"},
    "MOBILE_APP_CPC_VIDEO_AD_BUILDER_AD": AD_BUILDER_BASE_UPDATE_FIELDS
    | {"tracking_url"},
    "CPC_VIDEO_AD_BUILDER_AD": AD_BUILDER_BASE_UPDATE_FIELDS
    | {"href", "turbo_page_id"},
    "CPM_BANNER_AD_BUILDER_AD": AD_BUILDER_BASE_UPDATE_FIELDS
    | {"href", "tracking_pixels", "turbo_page_id"},
    "CPM_VIDEO_AD_BUILDER_AD": AD_BUILDER_BASE_UPDATE_FIELDS
    | {"href", "tracking_pixels", "turbo_page_id"},
}

AD_BUILDER_UPDATE_BLOCKS = {
    "TEXT_AD_BUILDER_AD": "TextAdBuilderAd",
    "MOBILE_APP_AD_BUILDER_AD": "MobileAppAdBuilderAd",
    "MOBILE_APP_CPC_VIDEO_AD_BUILDER_AD": "MobileAppCpcVideoAdBuilderAd",
    "CPC_VIDEO_AD_BUILDER_AD": "CpcVideoAdBuilderAd",
    "CPM_BANNER_AD_BUILDER_AD": "CpmBannerAdBuilderAd",
    "CPM_VIDEO_AD_BUILDER_AD": "CpmVideoAdBuilderAd",
}

AD_BUILDER_ADD_BLOCKS = {
    "TEXT_AD_BUILDER_AD": "TextAdBuilderAd",
    "MOBILE_APP_AD_BUILDER_AD": "MobileAppAdBuilderAd",
    "MOBILE_APP_CPC_VIDEO_AD_BUILDER_AD": "MobileAppCpcVideoAdBuilderAd",
    "CPC_VIDEO_AD_BUILDER_AD": "CpcVideoAdBuilderAd",
    "CPM_BANNER_AD_BUILDER_AD": "CpmBannerAdBuilderAd",
    "CPM_VIDEO_AD_BUILDER_AD": "CpmVideoAdBuilderAd",
}

AD_BUILDER_ADD_BASE_FIELDS = {"creative_id", "erir_ad_description"}

AD_BUILDER_ADD_TYPE_FIELDS = {
    "TEXT_AD_BUILDER_AD": AD_BUILDER_ADD_BASE_FIELDS
    | {"final_url", "href", "turbo_page_id"},
    "MOBILE_APP_AD_BUILDER_AD": AD_BUILDER_ADD_BASE_FIELDS | {"tracking_url"},
    "MOBILE_APP_CPC_VIDEO_AD_BUILDER_AD": AD_BUILDER_ADD_BASE_FIELDS | {"tracking_url"},
    "CPC_VIDEO_AD_BUILDER_AD": AD_BUILDER_ADD_BASE_FIELDS | {"href", "turbo_page_id"},
    "CPM_BANNER_AD_BUILDER_AD": AD_BUILDER_ADD_BASE_FIELDS
    | {"href", "tracking_pixels", "turbo_page_id"},
    "CPM_VIDEO_AD_BUILDER_AD": AD_BUILDER_ADD_BASE_FIELDS
    | {"href", "tracking_pixels", "turbo_page_id"},
}

AD_BUILDER_ADD_DESTINATION_TYPES = {
    "TEXT_AD_BUILDER_AD",
    "CPC_VIDEO_AD_BUILDER_AD",
    "CPM_BANNER_AD_BUILDER_AD",
    "CPM_VIDEO_AD_BUILDER_AD",
}

SMART_AD_BUILDER_ADD_FIELDS = {"logo_extension_hash"}

SMART_AD_BUILDER_UPDATE_FIELDS = {
    "logo_extension_hash",
    "erir_ad_description",
}


def _build_ad_builder_update(
    creative_id: Optional[int],
    creative_erir_ad_description: Optional[str],
    erir_ad_description: Optional[str],
    final_url: Optional[str],
    href: Optional[str],
    turbo_page_id: Optional[int],
    tracking_url: Optional[str],
    tracking_pixels: Optional[str],
) -> dict[str, object]:
    """Build an AdBuilder*Update payload from typed flags."""
    ad_payload: dict[str, object] = {}

    if creative_erir_ad_description and creative_id is None:
        raise click.UsageError(
            t("--creative-erir-ad-description requires --creative-id.")
        )
    if creative_id is not None:
        creative: dict[str, object] = {"CreativeId": creative_id}
        if creative_erir_ad_description:
            creative["ErirAdDescription"] = creative_erir_ad_description
        ad_payload["Creative"] = creative

    if erir_ad_description:
        ad_payload["ErirAdDescription"] = erir_ad_description
    if final_url:
        ad_payload["FinalUrl"] = final_url
    if href:
        ad_payload["Href"] = href
    if turbo_page_id is not None:
        ad_payload["TurboPageId"] = turbo_page_id
    if tracking_url:
        ad_payload["TrackingUrl"] = tracking_url

    parsed_tracking_pixels = _parse_required_csv_strings(
        tracking_pixels, "--tracking-pixels"
    )
    if parsed_tracking_pixels:
        ad_payload["TrackingPixels"] = {"Items": parsed_tracking_pixels}

    return ad_payload


def _build_ad_builder_add(
    creative_id: Optional[int],
    erir_ad_description: Optional[str],
    final_url: Optional[str],
    href: Optional[str],
    turbo_page_id: Optional[int],
    tracking_url: Optional[str],
    tracking_pixels: Optional[str],
    ad_type: str,
    container_name: str,
) -> dict[str, object]:
    """Build an AdBuilder*Add payload from typed flags."""
    if creative_id is None:
        raise click.UsageError(
            t("{container_name} requires --creative-id.").format(
                container_name=container_name
            )
        )
    if (
        ad_type in AD_BUILDER_ADD_DESTINATION_TYPES
        and not href
        and turbo_page_id is None
    ):
        raise click.UsageError(
            t("{container_name} requires either --href or --turbo-page-id.").format(
                container_name=container_name
            )
        )

    ad_payload: dict[str, object] = {"Creative": {"CreativeId": creative_id}}

    if erir_ad_description:
        ad_payload["ErirAdDescription"] = erir_ad_description
    if final_url:
        ad_payload["FinalUrl"] = final_url
    if href:
        ad_payload["Href"] = href
    if turbo_page_id is not None:
        ad_payload["TurboPageId"] = turbo_page_id
    if tracking_url:
        ad_payload["TrackingUrl"] = tracking_url

    parsed_tracking_pixels = _parse_required_csv_strings(
        tracking_pixels, "--tracking-pixels"
    )
    if parsed_tracking_pixels:
        ad_payload["TrackingPixels"] = {"Items": parsed_tracking_pixels}

    return ad_payload


def _build_smart_ad_builder_ad_add(
    logo_extension_hash: Optional[str],
) -> dict[str, object]:
    """Build SmartAdBuilderAdAdd payload from typed flags."""
    smart_ad_builder_ad: dict[str, object] = {}

    if logo_extension_hash:
        smart_ad_builder_ad["LogoExtensionHash"] = logo_extension_hash

    return smart_ad_builder_ad


def _build_smart_ad_builder_ad_update(
    logo_extension_hash: Optional[str],
    erir_ad_description: Optional[str],
) -> dict[str, object]:
    """Build SmartAdBuilderAdUpdate payload from typed flags."""
    smart_ad_builder_ad: dict[str, object] = {}

    if logo_extension_hash:
        smart_ad_builder_ad["LogoExtensionHash"] = logo_extension_hash
    if erir_ad_description:
        smart_ad_builder_ad["ErirAdDescription"] = erir_ad_description

    return smart_ad_builder_ad
