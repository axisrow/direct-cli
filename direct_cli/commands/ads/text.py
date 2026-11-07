"""TEXT_AD / TEXT_IMAGE_AD / DYNAMIC_TEXT_AD payload assembly (#603).

Holds the per-subtype update field allow-lists and the payload builders for the
text family. ``TEXT_AD`` and ``DYNAMIC_TEXT_AD`` share WSDL ``TextAdUpdateBase``
(nillable ``AdImageHash``); ``TEXT_IMAGE_AD`` inherits ``ImageAdUpdateBase``,
whose ``AdImageHash`` is *not* nillable — see the note on
:data:`TEXT_IMAGE_AD_UPDATE_FIELDS`.

The ``build_*_block`` functions are the registry handlers the dispatcher
(:mod:`.objects`) calls (epic #961, track 5); each owns one subtype's whole
add/update block and writes it into ``ad_data`` itself.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

import click

from ...i18n import t
from ...utils import parse_ids
from .base import (
    _build_price_extension_add,
    _parse_required_ids,
)

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


def build_text_ad_add_block(
    ad_data: dict[str, Any],
    flags: Mapping[str, Any],
    mobile: str,
) -> None:
    """Compose ``ad_data["TextAd"]`` for ``ads add`` (registry handler).

    Verbatim extract of the former inline ``TEXT_AD`` branch of
    ``build_ad_object`` (epic #961, track 5).
    """
    title = flags.get("title")
    text = flags.get("text")
    href = flags.get("href")
    image_hash = flags.get("image_hash")
    title2 = flags.get("title2")
    display_url_path = flags.get("display_url_path")
    vcard_id = flags.get("vcard_id")
    sitelink_set_id = flags.get("sitelink_set_id")
    turbo_page_id = flags.get("turbo_page_id")
    ad_extensions = flags.get("ad_extensions")
    final_url = flags.get("final_url")
    video_extension_creative_id = flags.get("video_extension_creative_id")
    price_extension_price = flags.get("price_extension_price")
    price_extension_old_price = flags.get("price_extension_old_price")
    price_extension_price_qualifier = flags.get("price_extension_price_qualifier")
    price_extension_price_currency = flags.get("price_extension_price_currency")
    business_id = flags.get("business_id")
    prefer_vcard_over_business = flags.get("prefer_vcard_over_business")
    erir_ad_description = flags.get("erir_ad_description")

    missing_fields = [
        option_name
        for option_name, value in (
            ("--title", title),
            ("--text", text),
            ("--href", href),
        )
        if not value
    ]
    if missing_fields:
        raise click.UsageError(
            t("TEXT_AD requires {arg0}").format(arg0=", ".join(missing_fields))
        )
    text_ad = {
        "Mobile": mobile.upper(),
        "Title": title,
        "Text": text,
        "Href": href,
    }
    if image_hash:
        text_ad["AdImageHash"] = image_hash
    if title2:
        text_ad["Title2"] = title2
    if display_url_path:
        text_ad["DisplayUrlPath"] = display_url_path
    if vcard_id:
        text_ad["VCardId"] = vcard_id
    if sitelink_set_id:
        text_ad["SitelinkSetId"] = sitelink_set_id
    if turbo_page_id:
        text_ad["TurboPageId"] = turbo_page_id
    if ad_extensions:
        text_ad["AdExtensionIds"] = parse_ids(ad_extensions)
    if final_url:
        text_ad["FinalUrl"] = final_url
    if video_extension_creative_id is not None:
        text_ad["VideoExtension"] = {"CreativeId": video_extension_creative_id}
    price_extension = _build_price_extension_add(
        price_extension_price,
        price_extension_old_price,
        price_extension_price_qualifier,
        price_extension_price_currency,
    )
    if price_extension:
        text_ad["PriceExtension"] = price_extension
    if business_id is not None:
        text_ad["BusinessId"] = business_id
    if prefer_vcard_over_business:
        text_ad["PreferVCardOverBusiness"] = prefer_vcard_over_business.upper()
    if erir_ad_description:
        text_ad["ErirAdDescription"] = erir_ad_description
    ad_data["TextAd"] = text_ad


def build_text_image_ad_add_block(
    ad_data: dict[str, Any],
    flags: Mapping[str, Any],
    mobile: str,
) -> None:
    """Compose ``ad_data["TextImageAd"]`` for ``ads add`` (registry handler).

    Verbatim extract of the former inline ``TEXT_IMAGE_AD`` branch of
    ``build_ad_object`` (epic #961, track 5).
    """
    href = flags.get("href")
    image_hash = flags.get("image_hash")
    turbo_page_id = flags.get("turbo_page_id")
    final_url = flags.get("final_url")
    erir_ad_description = flags.get("erir_ad_description")
    title = flags.get("title")
    text = flags.get("text")

    if title or text:
        raise click.UsageError(
            t(
                "--title/--text are only valid for TEXT_AD. "
                "For TEXT_IMAGE_AD, use --image-hash and "
                "--href / --turbo-page-id."
            )
        )
    if not image_hash:
        raise click.UsageError(t("TEXT_IMAGE_AD requires --image-hash"))
    if not href and turbo_page_id is None:
        raise click.UsageError(
            t("TEXT_IMAGE_AD requires either --href or --turbo-page-id.")
        )
    text_image_ad = {"AdImageHash": image_hash}
    if erir_ad_description:
        text_image_ad["ErirAdDescription"] = erir_ad_description
    if final_url:
        text_image_ad["FinalUrl"] = final_url
    if href:
        text_image_ad["Href"] = href
    if turbo_page_id is not None:
        text_image_ad["TurboPageId"] = turbo_page_id
    ad_data["TextImageAd"] = text_image_ad


def build_dynamic_text_ad_add_block(
    ad_data: dict[str, Any],
    flags: Mapping[str, Any],
    mobile: str,
) -> None:
    """Compose ``ad_data["DynamicTextAd"]`` for ``ads add`` (registry handler)."""
    ad_data["DynamicTextAd"] = _build_dynamic_text_ad_add(
        flags.get("text"),
        flags.get("image_hash"),
        flags.get("vcard_id"),
        flags.get("sitelink_set_id"),
        flags.get("ad_extensions"),
    )


def build_text_ad_update_block(
    ad_data: dict[str, Any],
    flags: Mapping[str, Any],
    precomputed: Mapping[str, Any],
) -> None:
    """Compose ``ad_data["TextAd"]`` for ``ads update`` (registry handler).

    Verbatim extract of the former inline ``TEXT_AD`` branch of
    ``build_ad_update_object`` (epic #961, track 5).
    """
    vcard_id = flags.get("vcard_id")
    image_hash = flags.get("image_hash")
    sitelink_set_id = flags.get("sitelink_set_id")
    clear_image_hash = flags.get("clear_image_hash")
    title = flags.get("title")
    text = flags.get("text")
    href = flags.get("href")
    title2 = flags.get("title2")
    final_url = flags.get("final_url")
    display_url_path = flags.get("display_url_path")
    age_label = flags.get("age_label")
    turbo_page_id = flags.get("turbo_page_id")
    video_extension_creative_id = flags.get("video_extension_creative_id")
    business_id = flags.get("business_id")
    prefer_vcard_over_business = flags.get("prefer_vcard_over_business")
    erir_ad_description = flags.get("erir_ad_description")
    callout_setting = precomputed["callout_setting"]
    price_extension = precomputed["price_extension"]

    text_ad = _build_text_ad_update_base(
        vcard_id,
        image_hash,
        sitelink_set_id,
        callout_setting,
        clear_image_hash=clear_image_hash,
    )
    if title:
        text_ad["Title"] = title
    if text:
        text_ad["Text"] = text
    if href:
        text_ad["Href"] = href
    if title2:
        text_ad["Title2"] = title2
    if final_url:
        text_ad["FinalUrl"] = final_url
    if display_url_path:
        text_ad["DisplayUrlPath"] = display_url_path
    if age_label:
        text_ad["AgeLabel"] = age_label.upper()
    if turbo_page_id is not None:
        text_ad["TurboPageId"] = turbo_page_id
    if video_extension_creative_id is not None:
        text_ad["VideoExtension"] = {"CreativeId": video_extension_creative_id}
    if price_extension:
        text_ad["PriceExtension"] = price_extension
    if business_id is not None:
        text_ad["BusinessId"] = business_id
    if prefer_vcard_over_business:
        text_ad["PreferVCardOverBusiness"] = prefer_vcard_over_business.upper()
    if erir_ad_description:
        text_ad["ErirAdDescription"] = erir_ad_description
    if text_ad:
        ad_data["TextAd"] = text_ad


def build_dynamic_text_ad_update_block(
    ad_data: dict[str, Any],
    flags: Mapping[str, Any],
    precomputed: Mapping[str, Any],
) -> None:
    """Compose ``ad_data["DynamicTextAd"]`` for ``ads update`` (registry handler).

    Verbatim extract of the former inline ``DYNAMIC_TEXT_AD`` branch of
    ``build_ad_update_object`` (epic #961, track 5).
    """
    dynamic_text_ad = _build_text_ad_update_base(
        flags.get("vcard_id"),
        flags.get("image_hash"),
        flags.get("sitelink_set_id"),
        precomputed["callout_setting"],
        clear_image_hash=flags.get("clear_image_hash"),
    )
    text = flags.get("text")
    if text:
        dynamic_text_ad["Text"] = text
    if dynamic_text_ad:
        ad_data["DynamicTextAd"] = dynamic_text_ad


def build_text_image_ad_update_block(
    ad_data: dict[str, Any],
    flags: Mapping[str, Any],
    precomputed: Mapping[str, Any],
) -> None:
    """Compose ``ad_data["TextImageAd"]`` for ``ads update`` (registry handler).

    Verbatim extract of the former inline ``TEXT_IMAGE_AD`` branch of
    ``build_ad_update_object`` (epic #961, track 5).
    """
    image_hash = flags.get("image_hash")
    final_url = flags.get("final_url")
    href = flags.get("href")
    turbo_page_id = flags.get("turbo_page_id")
    erir_ad_description = flags.get("erir_ad_description")

    text_image_ad = {}
    # No clear_image_hash: ImageAdUpdateBase.AdImageHash is not nillable;
    # the live API rejects null for this subtype (error 8000).
    if image_hash:
        text_image_ad["AdImageHash"] = image_hash
    if final_url:
        text_image_ad["FinalUrl"] = final_url
    if href:
        text_image_ad["Href"] = href
    if turbo_page_id is not None:
        text_image_ad["TurboPageId"] = turbo_page_id
    if erir_ad_description:
        text_image_ad["ErirAdDescription"] = erir_ad_description
    if text_image_ad:
        ad_data["TextImageAd"] = text_image_ad
