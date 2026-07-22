"""Pure ``Ads`` item builders shared by the single-flag and batch paths (#603).

``build_ad_object`` / ``build_ad_update_object`` do ``--type`` validation, the
incompatible-flag guard and the per-subtype dispatch, delegating payload assembly
to the subtype modules. They take no ``ctx`` and do no I/O, so both
``ads add``/``ads update`` and the ``--from-file`` batch normalizers
(:mod:`.batch`) call them and emit byte-identical objects.
"""

from __future__ import annotations

from typing import Any

import click

from ...i18n import t
from ...utils import parse_ids
from .base import (
    _build_callout_setting,
    _build_price_extension,
    _build_price_extension_add,
    _parse_mobile_app_features,
    _parse_required_csv_strings,
    _parse_required_ids,
    _reject_incompatible_flags,
)
from .builder import (
    AD_BUILDER_ADD_BLOCKS,
    AD_BUILDER_ADD_TYPE_FIELDS,
    AD_BUILDER_TYPE_FIELDS,
    AD_BUILDER_UPDATE_BLOCKS,
    SMART_AD_BUILDER_ADD_FIELDS,
    SMART_AD_BUILDER_UPDATE_FIELDS,
    _build_ad_builder_add,
    _build_ad_builder_update,
    _build_smart_ad_builder_ad_add,
    _build_smart_ad_builder_ad_update,
)
from .mobile_app import (
    MOBILE_APP_AD_ADD_FIELDS,
    MOBILE_APP_AD_UPDATE_FIELDS,
    MOBILE_APP_IMAGE_AD_ADD_FIELDS,
    MOBILE_APP_IMAGE_UPDATE_FIELDS,
    _build_mobile_app_image_ad_add,
    _build_mobile_app_image_ad_update,
)
from .responsive import (
    RESPONSIVE_AD_ADD_FIELDS,
    RESPONSIVE_AD_UPDATE_FIELDS,
    _build_responsive_ad_update,
)
from .shopping import (
    FEED_BASED_ADD_FIELDS,
    FEED_BASED_UPDATE_FIELDS,
    _build_feed_based_ad_add,
    _build_feed_based_ad_update,
)
from .text import (
    DYNAMIC_TEXT_AD_ADD_FIELDS,
    DYNAMIC_TEXT_AD_UPDATE_FIELDS,
    TEXT_AD_ADD_FIELDS,
    TEXT_AD_UPDATE_FIELDS,
    TEXT_IMAGE_AD_ADD_FIELDS,
    TEXT_IMAGE_AD_UPDATE_FIELDS,
    _build_dynamic_text_ad_add,
    _build_text_ad_update_base,
)

# dest-name -> CLI flag label, used by build_ad_object's incompatible-flag
# guard and by the batch row normalizer (issue #562). Module-level so both the
# single-flag command and the --from-file path share one source of truth.
_ADS_ADD_FLAG_FOR = {
    "title": "--title",
    "text": "--text",
    "titles": "--titles",
    "texts": "--texts",
    "href": "--href",
    "image_hash": "--image-hash",
    "image_hashes": "--image-hashes",
    "action": "--action",
    "tracking_url": "--tracking-url",
    "age_label": "--age-label",
    "mobile_app_features": "--mobile-app-feature",
    "title2": "--title2",
    "display_url_path": "--display-url-path",
    "mobile": "--mobile",
    "vcard_id": "--vcard-id",
    "sitelink_set_id": "--sitelink-set-id",
    "turbo_page_id": "--turbo-page-id",
    "ad_extensions": "--ad-extensions",
    "final_url": "--final-url",
    "video_extension_creative_id": "--video-extension-creative-id",
    "price_extension_price": "--price-extension-price",
    "price_extension_old_price": "--price-extension-old-price",
    "price_extension_price_qualifier": "--price-extension-price-qualifier",
    "price_extension_price_currency": "--price-extension-price-currency",
    "video_extension_ids": "--video-extension-ids",
    "business_id": "--business-id",
    "prefer_vcard_over_business": "--prefer-vcard-over-business",
    "erir_ad_description": "--erir-ad-description",
    "creative_id": "--creative-id",
    "tracking_pixels": "--tracking-pixels",
    "logo_extension_hash": "--logo-extension-hash",
    "feed_id": "--feed-id",
    "feed_filter_conditions": "--feed-filter-condition",
    "title_sources": "--title-sources",
    "text_sources": "--text-sources",
    "default_texts": "--default-texts",
}


# Static lookup tables for build_ad_object — hoisted to module level so they are
# allocated once at import, not rebuilt per ad (it runs once per row in batch).
_ADS_ADD_SUPPORTED_TYPES = frozenset(
    {
        "TEXT_AD",
        "TEXT_IMAGE_AD",
        "MOBILE_APP_AD",
        "DYNAMIC_TEXT_AD",
        "MOBILE_APP_IMAGE_AD",
        "RESPONSIVE_AD",
        "SHOPPING_AD",
        "LISTING_AD",
        "SMART_AD_BUILDER_AD",
        *AD_BUILDER_ADD_BLOCKS,
    }
)
_ADS_ADD_TYPE_FIELDS = {
    "TEXT_AD": TEXT_AD_ADD_FIELDS,
    "TEXT_IMAGE_AD": TEXT_IMAGE_AD_ADD_FIELDS,
    "RESPONSIVE_AD": RESPONSIVE_AD_ADD_FIELDS,
    "SHOPPING_AD": FEED_BASED_ADD_FIELDS,
    "LISTING_AD": FEED_BASED_ADD_FIELDS,
    **AD_BUILDER_ADD_TYPE_FIELDS,
    "DYNAMIC_TEXT_AD": DYNAMIC_TEXT_AD_ADD_FIELDS,
    "MOBILE_APP_AD": MOBILE_APP_AD_ADD_FIELDS,
    "MOBILE_APP_IMAGE_AD": MOBILE_APP_IMAGE_AD_ADD_FIELDS,
    "SMART_AD_BUILDER_AD": SMART_AD_BUILDER_ADD_FIELDS,
}


def build_ad_object(*, adgroup_id, ad_type, mobile_provided, flags, flag_for=None):
    """Build a single ``Ads`` item dict from flag values (issue #562).

    Pure (no ``ctx``, no I/O): performs ``--type`` validation, the
    incompatible-flag guard, per-subtype dispatch, and per-subtype required-field
    checks, returning ``{"AdGroupId": ..., "<SubType>": {...}}``. Both the
    single-flag ``ads add`` command and the ``--from-file`` batch normalizer call
    it so they emit byte-identical objects.

    ``flags`` is keyed by the command's dest var names (``image_hash``,
    ``mobile_app_features``, ...); missing keys default to ``None``.
    ``mobile_provided`` is the explicitly-passed ``--mobile`` value (``None`` when
    the flag was not given), already resolved by the caller (it needs ``ctx``).
    """
    flag_for = flag_for if flag_for is not None else _ADS_ADD_FLAG_FOR

    # Unpack flags into locals so the dispatch body below is byte-identical to
    # the historical inline command body.
    title = flags.get("title")
    text = flags.get("text")
    titles = flags.get("titles")
    texts = flags.get("texts")
    href = flags.get("href")
    image_hash = flags.get("image_hash")
    image_hashes = flags.get("image_hashes")
    action = flags.get("action")
    tracking_url = flags.get("tracking_url")
    age_label = flags.get("age_label")
    mobile_app_features = flags.get("mobile_app_features") or ()
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
    video_extension_ids = flags.get("video_extension_ids")
    business_id = flags.get("business_id")
    prefer_vcard_over_business = flags.get("prefer_vcard_over_business")
    erir_ad_description = flags.get("erir_ad_description")
    creative_id = flags.get("creative_id")
    tracking_pixels = flags.get("tracking_pixels")
    logo_extension_hash = flags.get("logo_extension_hash")
    feed_id = flags.get("feed_id")
    feed_filter_conditions = flags.get("feed_filter_conditions") or ()
    title_sources = flags.get("title_sources")
    text_sources = flags.get("text_sources")
    default_texts = flags.get("default_texts")
    # --mobile defaults to "NO" in the payload; the guard only sees it when
    # explicitly provided (mobile_provided).
    mobile = mobile_provided or "NO"

    ad_type_norm = (ad_type or "TEXT_AD").upper().replace("-", "_")
    if ad_type_norm not in _ADS_ADD_SUPPORTED_TYPES:
        raise click.UsageError(
            t(
                "Invalid value for '--type': {ad_type!r} is not one of 'TEXT_AD', 'TEXT_IMAGE_AD', 'MOBILE_APP_AD', 'DYNAMIC_TEXT_AD', 'MOBILE_APP_IMAGE_AD', 'RESPONSIVE_AD', 'SHOPPING_AD', 'LISTING_AD', 'SMART_AD_BUILDER_AD', 'TEXT_AD_BUILDER_AD', 'MOBILE_APP_AD_BUILDER_AD', 'MOBILE_APP_CPC_VIDEO_AD_BUILDER_AD', 'CPC_VIDEO_AD_BUILDER_AD', 'CPM_BANNER_AD_BUILDER_AD', 'CPM_VIDEO_AD_BUILDER_AD'."
            ).format(ad_type=ad_type)
        )

    # `provided` is `flags` with the explicit --mobile value (the command passes
    # mobile separately; a batch row pops it out). _reject_incompatible_flags
    # skips None/() values and absent keys alike, so a sparse dict is fine.
    provided = {**flags, "mobile": mobile_provided}
    _reject_incompatible_flags(
        ad_type_norm, _ADS_ADD_TYPE_FIELDS[ad_type_norm], provided, flag_for
    )

    ad_data = {"AdGroupId": adgroup_id}
    if ad_type_norm == "TEXT_AD":
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
    elif ad_type_norm == "DYNAMIC_TEXT_AD":
        ad_data["DynamicTextAd"] = _build_dynamic_text_ad_add(
            text,
            image_hash,
            vcard_id,
            sitelink_set_id,
            ad_extensions,
        )
    elif ad_type_norm == "TEXT_IMAGE_AD":
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
    elif ad_type_norm == "RESPONSIVE_AD":
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
                t("RESPONSIVE_AD requires {arg0}").format(
                    arg0=", ".join(missing_fields)
                )
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
        parsed_image_hashes = _parse_required_csv_strings(
            image_hashes, "--image-hashes"
        )
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
    elif ad_type_norm in {"SHOPPING_AD", "LISTING_AD"}:
        field_name = "ShoppingAd" if ad_type_norm == "SHOPPING_AD" else "ListingAd"
        ad_data[field_name] = _build_feed_based_ad_add(
            feed_id,
            default_texts,
            sitelink_set_id,
            ad_extensions,
            business_id,
            feed_filter_conditions,
            title_sources,
            text_sources,
            field_name,
        )
    elif ad_type_norm in AD_BUILDER_ADD_BLOCKS:
        field_name = AD_BUILDER_ADD_BLOCKS[ad_type_norm]
        ad_data[field_name] = _build_ad_builder_add(
            creative_id,
            erir_ad_description,
            final_url,
            href,
            turbo_page_id,
            tracking_url,
            tracking_pixels,
            ad_type_norm,
            field_name,
        )
    elif ad_type_norm == "MOBILE_APP_AD":
        if href:
            raise click.UsageError(
                t(
                    "--href does not apply to MOBILE_APP_AD. "
                    "Use --tracking-url instead."
                )
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
                t("MOBILE_APP_AD requires {arg0}").format(
                    arg0=", ".join(missing_fields)
                )
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
            mobile_app_ad["VideoExtension"] = {
                "CreativeId": video_extension_creative_id
            }
        if erir_ad_description:
            mobile_app_ad["ErirAdDescription"] = erir_ad_description
        ad_data["MobileAppAd"] = mobile_app_ad
    elif ad_type_norm == "MOBILE_APP_IMAGE_AD":
        ad_data["MobileAppImageAd"] = _build_mobile_app_image_ad_add(
            image_hash,
            erir_ad_description,
            tracking_url,
        )
    elif ad_type_norm == "SMART_AD_BUILDER_AD":
        ad_data["SmartAdBuilderAd"] = _build_smart_ad_builder_ad_add(
            logo_extension_hash,
        )

    return ad_data


# dest -> "--flag" map for the `ads update` flag set (mirrors _ADS_ADD_FLAG_FOR).
# Hoisted to module level so build_ad_update_object and the batch normalizer
# share one source of truth.
_ADS_UPDATE_FLAG_FOR = {
    "title": "--title",
    "text": "--text",
    "titles": "--titles",
    "texts": "--texts",
    "href": "--href",
    "image_hash": "--image-hash",
    "clear_image_hash": "--clear-image-hash",
    "image_hashes": "--image-hashes",
    "action": "--action",
    "tracking_url": "--tracking-url",
    "age_label": "--age-label",
    "mobile_app_features": "--mobile-app-feature",
    "title2": "--title2",
    "display_url_path": "--display-url-path",
    "vcard_id": "--vcard-id",
    "sitelink_set_id": "--sitelink-set-id",
    "turbo_page_id": "--turbo-page-id",
    "callouts_add": "--callouts-add",
    "callouts_remove": "--callouts-remove",
    "callouts_set": "--callouts-set",
    "video_extension_creative_id": "--video-extension-creative-id",
    "video_extension_ids": "--video-extension-ids",
    "price_extension_price": "--price-extension-price",
    "price_extension_old_price": "--price-extension-old-price",
    "price_extension_price_qualifier": "--price-extension-price-qualifier",
    "price_extension_price_currency": "--price-extension-price-currency",
    "business_id": "--business-id",
    "prefer_vcard_over_business": "--prefer-vcard-over-business",
    "erir_ad_description": "--erir-ad-description",
    "logo_extension_hash": "--logo-extension-hash",
    "creative_id": "--creative-id",
    "creative_erir_ad_description": "--creative-erir-ad-description",
    "final_url": "--final-url",
    "tracking_pixels": "--tracking-pixels",
    "feed_filter_conditions": "--feed-filter-condition",
    "title_sources": "--title-sources",
    "text_sources": "--text-sources",
    "default_texts": "--default-texts",
}


def _ads_update_type_fields():
    """Per-WSDL-subtype field allow-list for ``ads update``.

    Built once at import (not per ad) so the batch path, which runs this once per
    row, does not rebuild the dict. Each ``--type`` accepts only the options that
    map to fields inside its ``AdUpdateItem`` subtype; a flag outside the
    allow-list would be silently dropped, so the caller rejects it up front
    (issue #198 H2).
    """
    return {
        "TEXT_AD": TEXT_AD_UPDATE_FIELDS,
        "DYNAMIC_TEXT_AD": DYNAMIC_TEXT_AD_UPDATE_FIELDS,
        "TEXT_IMAGE_AD": TEXT_IMAGE_AD_UPDATE_FIELDS,
        "MOBILE_APP_AD": MOBILE_APP_AD_UPDATE_FIELDS,
        "MOBILE_APP_IMAGE_AD": MOBILE_APP_IMAGE_UPDATE_FIELDS,
        "RESPONSIVE_AD": RESPONSIVE_AD_UPDATE_FIELDS,
        "SHOPPING_AD": FEED_BASED_UPDATE_FIELDS,
        "LISTING_AD": FEED_BASED_UPDATE_FIELDS,
        "SMART_AD_BUILDER_AD": SMART_AD_BUILDER_UPDATE_FIELDS,
        **AD_BUILDER_TYPE_FIELDS,
    }


_ADS_UPDATE_TYPE_FIELDS = _ads_update_type_fields()
_ADS_UPDATE_SUPPORTED_TYPES = frozenset(
    {
        "TEXT_AD",
        "TEXT_IMAGE_AD",
        "MOBILE_APP_AD",
        "MOBILE_APP_IMAGE_AD",
        "DYNAMIC_TEXT_AD",
        "RESPONSIVE_AD",
        "SHOPPING_AD",
        "LISTING_AD",
        "SMART_AD_BUILDER_AD",
        *AD_BUILDER_UPDATE_BLOCKS,
    }
)


def build_ad_update_object(*, ad_id, ad_type, flags, flag_for=None):
    """Build a single ``Ads`` update item dict from flag values (issue #563).

    Pure (no ``ctx``, no I/O): performs ``--type`` validation, the
    incompatible-flag / "does not convert between subtypes" guard, per-subtype
    assembly, and the empty-subtype no-op guard, returning
    ``{"Id": ..., "<SubType>": {...}}``. Both the single-flag ``ads update``
    command and the ``--from-file`` batch normalizer call it so they emit
    byte-identical objects.

    ``flags`` is keyed by the command's dest var names (``image_hash``,
    ``clear_image_hash``, ``mobile_app_features``, ...); missing keys default to
    ``None``. The caller is responsible for the ``--status`` rejection and the
    ``--image-hash``/``--clear-image-hash`` mutex (those have command-level
    wording).
    """
    flag_for = flag_for if flag_for is not None else _ADS_UPDATE_FLAG_FOR

    # Unpack flags into locals so the dispatch body below is byte-identical to
    # the historical inline command body.
    title = flags.get("title")
    text = flags.get("text")
    titles = flags.get("titles")
    texts = flags.get("texts")
    href = flags.get("href")
    image_hash = flags.get("image_hash")
    clear_image_hash = flags.get("clear_image_hash")
    image_hashes = flags.get("image_hashes")
    action = flags.get("action")
    tracking_url = flags.get("tracking_url")
    age_label = flags.get("age_label")
    mobile_app_features = flags.get("mobile_app_features") or ()
    title2 = flags.get("title2")
    display_url_path = flags.get("display_url_path")
    vcard_id = flags.get("vcard_id")
    sitelink_set_id = flags.get("sitelink_set_id")
    turbo_page_id = flags.get("turbo_page_id")
    callouts_add = flags.get("callouts_add")
    callouts_remove = flags.get("callouts_remove")
    callouts_set = flags.get("callouts_set")
    video_extension_creative_id = flags.get("video_extension_creative_id")
    video_extension_ids = flags.get("video_extension_ids")
    price_extension_price = flags.get("price_extension_price")
    price_extension_old_price = flags.get("price_extension_old_price")
    price_extension_price_qualifier = flags.get("price_extension_price_qualifier")
    price_extension_price_currency = flags.get("price_extension_price_currency")
    business_id = flags.get("business_id")
    prefer_vcard_over_business = flags.get("prefer_vcard_over_business")
    erir_ad_description = flags.get("erir_ad_description")
    logo_extension_hash = flags.get("logo_extension_hash")
    creative_id = flags.get("creative_id")
    creative_erir_ad_description = flags.get("creative_erir_ad_description")
    final_url = flags.get("final_url")
    tracking_pixels = flags.get("tracking_pixels")
    feed_filter_conditions = flags.get("feed_filter_conditions") or ()
    title_sources = flags.get("title_sources")
    text_sources = flags.get("text_sources")
    default_texts = flags.get("default_texts")

    ad_type_norm = ad_type.upper().replace("-", "_")
    if ad_type_norm not in _ADS_UPDATE_SUPPORTED_TYPES:
        raise click.UsageError(
            t(
                "Invalid value for '--type': {ad_type!r} is not one of 'TEXT_AD', 'TEXT_IMAGE_AD', 'MOBILE_APP_AD', 'DYNAMIC_TEXT_AD', 'MOBILE_APP_IMAGE_AD', 'RESPONSIVE_AD', 'SHOPPING_AD', 'LISTING_AD', 'SMART_AD_BUILDER_AD', 'TEXT_AD_BUILDER_AD', 'MOBILE_APP_AD_BUILDER_AD', 'MOBILE_APP_CPC_VIDEO_AD_BUILDER_AD', 'CPC_VIDEO_AD_BUILDER_AD', 'CPM_BANNER_AD_BUILDER_AD', 'CPM_VIDEO_AD_BUILDER_AD'."
            ).format(ad_type=ad_type)
        )

    provided = {
        "title": title,
        "text": text,
        "titles": titles,
        "texts": texts,
        "href": href,
        "image_hash": image_hash,
        "clear_image_hash": clear_image_hash or None,
        "image_hashes": image_hashes,
        "action": action,
        "tracking_url": tracking_url,
        "age_label": age_label,
        "mobile_app_features": mobile_app_features,
        "title2": title2,
        "display_url_path": display_url_path,
        "vcard_id": vcard_id,
        "sitelink_set_id": sitelink_set_id,
        "turbo_page_id": turbo_page_id,
        "callouts_add": callouts_add,
        "callouts_remove": callouts_remove,
        "callouts_set": callouts_set,
        "video_extension_creative_id": video_extension_creative_id,
        "video_extension_ids": video_extension_ids,
        "price_extension_price": price_extension_price,
        "price_extension_old_price": price_extension_old_price,
        "price_extension_price_qualifier": price_extension_price_qualifier,
        "price_extension_price_currency": price_extension_price_currency,
        "business_id": business_id,
        "prefer_vcard_over_business": prefer_vcard_over_business,
        "erir_ad_description": erir_ad_description,
        "logo_extension_hash": logo_extension_hash,
        "creative_id": creative_id,
        "creative_erir_ad_description": creative_erir_ad_description,
        "final_url": final_url,
        "tracking_pixels": tracking_pixels,
        "feed_filter_conditions": feed_filter_conditions,
        "title_sources": title_sources,
        "text_sources": text_sources,
        "default_texts": default_texts,
    }
    try:
        _reject_incompatible_flags(
            ad_type_norm, _ADS_UPDATE_TYPE_FIELDS[ad_type_norm], provided, flag_for
        )
    except click.UsageError as exc:
        raise click.UsageError(
            t(
                "{arg0} --type selects the existing ad subtype update block; it does not convert an ad between subtypes."
            ).format(arg0=exc.message)
        )

    # Validate up-front so SET vs ADD/REMOVE mutex errors raise UsageError
    # before any payload work, bypassing the generic ``except Exception``
    # net wrapped around the network call below.
    callout_setting = _build_callout_setting(
        callouts_add, callouts_remove, callouts_set
    )
    price_extension = _build_price_extension(
        price_extension_price,
        price_extension_old_price,
        price_extension_price_qualifier,
        price_extension_price_currency,
    )
    parsed_mobile_app_features = _parse_mobile_app_features(mobile_app_features)

    ad_data = {"Id": ad_id}

    if ad_type_norm == "TEXT_AD":
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
    elif ad_type_norm == "DYNAMIC_TEXT_AD":
        dynamic_text_ad = _build_text_ad_update_base(
            vcard_id,
            image_hash,
            sitelink_set_id,
            callout_setting,
            clear_image_hash=clear_image_hash,
        )
        if text:
            dynamic_text_ad["Text"] = text
        if dynamic_text_ad:
            ad_data["DynamicTextAd"] = dynamic_text_ad
    elif ad_type_norm == "TEXT_IMAGE_AD":
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
    elif ad_type_norm == "MOBILE_APP_AD":
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
            mobile_app_ad["VideoExtension"] = {
                "CreativeId": video_extension_creative_id
            }
        if erir_ad_description:
            mobile_app_ad["ErirAdDescription"] = erir_ad_description
        if mobile_app_ad:
            ad_data["MobileAppAd"] = mobile_app_ad
    elif ad_type_norm == "MOBILE_APP_IMAGE_AD":
        mobile_app_image_ad = _build_mobile_app_image_ad_update(
            image_hash,
            erir_ad_description,
            tracking_url,
        )
        if mobile_app_image_ad:
            ad_data["MobileAppImageAd"] = mobile_app_image_ad
    elif ad_type_norm == "RESPONSIVE_AD":
        responsive_ad = _build_responsive_ad_update(
            texts,
            titles,
            image_hashes,
            video_extension_ids,
            sitelink_set_id,
            callout_setting,
            href,
            age_label,
            display_url_path,
            price_extension,
            business_id,
            erir_ad_description,
        )
        if responsive_ad:
            ad_data["ResponsiveAd"] = responsive_ad
    elif ad_type_norm in {"SHOPPING_AD", "LISTING_AD"}:
        feed_based_ad = _build_feed_based_ad_update(
            sitelink_set_id,
            callout_setting,
            business_id,
            feed_filter_conditions,
            title_sources,
            text_sources,
            default_texts,
        )
        if feed_based_ad:
            field_name = "ShoppingAd" if ad_type_norm == "SHOPPING_AD" else "ListingAd"
            ad_data[field_name] = feed_based_ad
    elif ad_type_norm == "SMART_AD_BUILDER_AD":
        smart_ad_builder_ad = _build_smart_ad_builder_ad_update(
            logo_extension_hash,
            erir_ad_description,
        )
        if smart_ad_builder_ad:
            ad_data["SmartAdBuilderAd"] = smart_ad_builder_ad
    elif ad_type_norm in AD_BUILDER_UPDATE_BLOCKS:
        ad_builder_ad = _build_ad_builder_update(
            creative_id,
            creative_erir_ad_description,
            erir_ad_description,
            final_url,
            href,
            turbo_page_id,
            tracking_url,
            tracking_pixels,
        )
        if ad_builder_ad:
            ad_data[AD_BUILDER_UPDATE_BLOCKS[ad_type_norm]] = ad_builder_ad

    # Reject empty-subtype no-ops: ``{Id: N}`` with no subtype block
    # is a silent no-op on the live API (issue #198 H1).
    if len(ad_data) == 1:
        raise click.UsageError(
            t(
                "ads update requires at least one updatable field for --type {ad_type_norm}."
            ).format(ad_type_norm=ad_type_norm)
        )

    return ad_data
