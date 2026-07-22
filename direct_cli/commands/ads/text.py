"""TEXT_AD / TEXT_IMAGE_AD / DYNAMIC_TEXT_AD payload assembly (#603).

Holds the per-subtype update field allow-lists and the payload builders for the
text family. ``TEXT_AD`` and ``DYNAMIC_TEXT_AD`` share WSDL ``TextAdUpdateBase``
(nillable ``AdImageHash``); ``TEXT_IMAGE_AD`` inherits ``ImageAdUpdateBase``,
whose ``AdImageHash`` is *not* nillable — see the note on
:data:`TEXT_IMAGE_AD_UPDATE_FIELDS`.
"""

from __future__ import annotations

from typing import Any, Optional

import click

from ...i18n import t
from .base import _parse_required_ids

DYNAMIC_TEXT_AD_ADD_FIELDS = {
    "text",
    "image_hash",
    "vcard_id",
    "sitelink_set_id",
    "ad_extensions",
}

TEXT_AD_UPDATE_FIELDS = {
    "title",
    "text",
    "href",
    "image_hash",
    "clear_image_hash",
    "title2",
    "display_url_path",
    "vcard_id",
    "sitelink_set_id",
    "turbo_page_id",
    "callouts_add",
    "callouts_remove",
    "callouts_set",
    "video_extension_creative_id",
    "price_extension_price",
    "price_extension_old_price",
    "price_extension_price_qualifier",
    "price_extension_price_currency",
    "final_url",
    "age_label",
    "business_id",
    "prefer_vcard_over_business",
    "erir_ad_description",
}

DYNAMIC_TEXT_AD_UPDATE_FIELDS = {
    "text",
    "image_hash",
    "clear_image_hash",
    "vcard_id",
    "sitelink_set_id",
    "callouts_add",
    "callouts_remove",
    "callouts_set",
}

# NOTE: TEXT_IMAGE_AD / MOBILE_APP_IMAGE_AD share WSDL ImageAdUpdateBase, whose
# AdImageHash is NOT nillable (unlike TextAdUpdateBase / MobileAppAdBase). The
# live API rejects ``AdImageHash: null`` for these two subtypes with error 8000
# ("AdImageHash cannot have the null value"), so --clear-image-hash is
# deliberately absent here — the parity gate rejects it as an incompatible flag.
TEXT_IMAGE_AD_UPDATE_FIELDS = {
    "image_hash",
    "final_url",
    "href",
    "turbo_page_id",
    "erir_ad_description",
}

TEXT_AD_ADD_FIELDS = {
    "title",
    "text",
    "href",
    "image_hash",
    "title2",
    "display_url_path",
    "mobile",
    "vcard_id",
    "sitelink_set_id",
    "turbo_page_id",
    "ad_extensions",
    "final_url",
    "video_extension_creative_id",
    "price_extension_price",
    "price_extension_old_price",
    "price_extension_price_qualifier",
    "price_extension_price_currency",
    "business_id",
    "prefer_vcard_over_business",
    "erir_ad_description",
}

TEXT_IMAGE_AD_ADD_FIELDS = {
    "href",
    "image_hash",
    "turbo_page_id",
    "final_url",
    "erir_ad_description",
}


def _build_text_ad_update_base(
    vcard_id: Optional[int],
    image_hash: Optional[str],
    sitelink_set_id: Optional[int],
    callout_setting: Optional[dict[str, Any]],
    clear_image_hash: bool = False,
) -> dict[str, object]:
    """Build fields inherited from WSDL TextAdUpdateBase."""
    text_ad_base: dict[str, object] = {}
    if vcard_id is not None:
        text_ad_base["VCardId"] = vcard_id
    if clear_image_hash:
        text_ad_base["AdImageHash"] = None
    elif image_hash:
        text_ad_base["AdImageHash"] = image_hash
    if sitelink_set_id is not None:
        text_ad_base["SitelinkSetId"] = sitelink_set_id
    if callout_setting:
        text_ad_base["CalloutSetting"] = callout_setting
    return text_ad_base


def _build_dynamic_text_ad_add(
    text: Optional[str],
    image_hash: Optional[str],
    vcard_id: Optional[int],
    sitelink_set_id: Optional[int],
    ad_extensions: Optional[str],
) -> dict[str, object]:
    """Build DynamicTextAdAdd payload from typed flags."""
    if not text:
        raise click.UsageError(t("DYNAMIC_TEXT_AD requires --text"))

    dynamic_text_ad: dict[str, object] = {"Text": text}
    if image_hash:
        dynamic_text_ad["AdImageHash"] = image_hash
    if vcard_id is not None:
        dynamic_text_ad["VCardId"] = vcard_id
    if sitelink_set_id is not None:
        dynamic_text_ad["SitelinkSetId"] = sitelink_set_id
    parsed_ad_extensions = _parse_required_ids(ad_extensions, "--ad-extensions")
    if parsed_ad_extensions:
        dynamic_text_ad["AdExtensionIds"] = parsed_ad_extensions

    return dynamic_text_ad
