"""Pure ``Ads`` item builders shared by the single-flag and batch paths (#603).

``build_ad_object`` / ``build_ad_update_object`` do ``--type`` validation and
the incompatible-flag guard, then dispatch through the per-direction registries
(``_ADS_ADD_REGISTRY`` / ``_ADS_UPDATE_REGISTRY``) to the subtype-module block
handlers. Each registry entry pairs a subtype's allowed-field set with its
handler, so registering a subtype and its flags is one table edit (epic #961,
track 5). The functions take no ``ctx`` and do no I/O, and both
``ads add``/``ads update`` and the ``--from-file`` batch normalizers
(:mod:`.batch`) call them and emit byte-identical objects.
"""

from __future__ import annotations

from typing import Callable, Tuple

import click

from ...i18n import t
from .base import (
    _build_callout_setting,
    _build_price_extension,
    _parse_mobile_app_features,
    _reject_incompatible_flags,
)
from . import builder as builder
from .builder import (
    AD_BUILDER_ADD_BLOCKS,
    AD_BUILDER_ADD_TYPE_FIELDS,
    AD_BUILDER_TYPE_FIELDS,
    AD_BUILDER_UPDATE_BLOCKS,
    SMART_AD_BUILDER_ADD_FIELDS,
    SMART_AD_BUILDER_UPDATE_FIELDS,
)
from . import mobile_app as mobile_app
from .mobile_app import (
    MOBILE_APP_AD_ADD_FIELDS,
    MOBILE_APP_AD_UPDATE_FIELDS,
    MOBILE_APP_IMAGE_AD_ADD_FIELDS,
    MOBILE_APP_IMAGE_UPDATE_FIELDS,
)
from . import responsive as responsive
from .responsive import (
    RESPONSIVE_AD_ADD_FIELDS,
    RESPONSIVE_AD_UPDATE_FIELDS,
)
from . import shopping as shopping
from .shopping import (
    FEED_BASED_ADD_FIELDS,
    FEED_BASED_UPDATE_FIELDS,
)
from . import text as text
from .text import (
    DYNAMIC_TEXT_AD_ADD_FIELDS,
    DYNAMIC_TEXT_AD_UPDATE_FIELDS,
    TEXT_AD_ADD_FIELDS,
    TEXT_AD_UPDATE_FIELDS,
    TEXT_IMAGE_AD_ADD_FIELDS,
    TEXT_IMAGE_AD_UPDATE_FIELDS,
)

# dest-name -> CLI flag label, used by the incompatible-flag guard and by the
# batch row normalizer (issue #562). Module-level so both the single-flag
# command and the --from-file path share one source of truth.
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

# The add registry: --type -> (allowed fields, handler). A handler is called
# ``handler(ad_data, flags, mobile)`` — ``flags`` is the raw dest-keyed dict,
# ``mobile`` the resolved ``--mobile`` default ("NO") — and writes its subtype
# block into ``ad_data`` itself. Multi-type families (the six AdBuilder* and
# the two feed-based subtypes) register one handler per type via the factories
# in their modules.
_ADS_ADD_REGISTRY: dict[str, Tuple[set, Callable]] = {
    "TEXT_AD": (TEXT_AD_ADD_FIELDS, text.build_text_ad_add_block),
    "TEXT_IMAGE_AD": (TEXT_IMAGE_AD_ADD_FIELDS, text.build_text_image_ad_add_block),
    "RESPONSIVE_AD": (
        RESPONSIVE_AD_ADD_FIELDS,
        responsive.build_responsive_ad_add_block,
    ),
    "DYNAMIC_TEXT_AD": (
        DYNAMIC_TEXT_AD_ADD_FIELDS,
        text.build_dynamic_text_ad_add_block,
    ),
    "MOBILE_APP_AD": (
        MOBILE_APP_AD_ADD_FIELDS,
        mobile_app.build_mobile_app_ad_add_block,
    ),
    "MOBILE_APP_IMAGE_AD": (
        MOBILE_APP_IMAGE_AD_ADD_FIELDS,
        mobile_app.build_mobile_app_image_ad_add_block,
    ),
    "SMART_AD_BUILDER_AD": (
        SMART_AD_BUILDER_ADD_FIELDS,
        builder.smart_ad_builder_ad_add_block,
    ),
    **{
        ad_type: (
            AD_BUILDER_ADD_TYPE_FIELDS[ad_type],
            builder.ad_builder_ad_add_block(ad_type, AD_BUILDER_ADD_BLOCKS[ad_type]),
        )
        for ad_type in AD_BUILDER_ADD_BLOCKS
    },
    **{
        ad_type: (
            FEED_BASED_ADD_FIELDS,
            shopping.feed_based_ad_add_block(field_name),
        )
        for ad_type, field_name in (
            ("SHOPPING_AD", "ShoppingAd"),
            ("LISTING_AD", "ListingAd"),
        )
    },
}

_ADS_ADD_SUPPORTED_TYPES = frozenset(_ADS_ADD_REGISTRY)


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


# The update registry: --type -> (allowed fields, handler). A handler is called
# ``handler(ad_data, flags, precomputed)`` — ``precomputed`` carries the
# cross-subtype values assembled once before dispatch (``callout_setting``,
# ``price_extension``, ``parsed_mobile_app_features``). Each handler writes its
# subtype block into ``ad_data`` only when the block is non-empty (an update
# may legitimately touch nothing in its own subtype).
_ADS_UPDATE_REGISTRY: dict[str, Tuple[set, Callable]] = {
    "TEXT_AD": (TEXT_AD_UPDATE_FIELDS, text.build_text_ad_update_block),
    "TEXT_IMAGE_AD": (
        TEXT_IMAGE_AD_UPDATE_FIELDS,
        text.build_text_image_ad_update_block,
    ),
    "RESPONSIVE_AD": (
        RESPONSIVE_AD_UPDATE_FIELDS,
        responsive.build_responsive_ad_update_block,
    ),
    "DYNAMIC_TEXT_AD": (
        DYNAMIC_TEXT_AD_UPDATE_FIELDS,
        text.build_dynamic_text_ad_update_block,
    ),
    "MOBILE_APP_AD": (
        MOBILE_APP_AD_UPDATE_FIELDS,
        mobile_app.build_mobile_app_ad_update_block,
    ),
    "MOBILE_APP_IMAGE_AD": (
        MOBILE_APP_IMAGE_UPDATE_FIELDS,
        mobile_app.build_mobile_app_image_ad_update_block,
    ),
    "SMART_AD_BUILDER_AD": (
        SMART_AD_BUILDER_UPDATE_FIELDS,
        builder.smart_ad_builder_ad_update_block,
    ),
    **{
        ad_type: (
            AD_BUILDER_TYPE_FIELDS[ad_type],
            builder.ad_builder_ad_update_block(AD_BUILDER_UPDATE_BLOCKS[ad_type]),
        )
        for ad_type in AD_BUILDER_UPDATE_BLOCKS
    },
    **{
        ad_type: (
            FEED_BASED_UPDATE_FIELDS,
            shopping.feed_based_ad_update_block(field_name),
        )
        for ad_type, field_name in (
            ("SHOPPING_AD", "ShoppingAd"),
            ("LISTING_AD", "ListingAd"),
        )
    },
}

_ADS_UPDATE_TYPE_FIELDS = {
    ad_type: fields for ad_type, (fields, _handler) in _ADS_UPDATE_REGISTRY.items()
}
_ADS_UPDATE_SUPPORTED_TYPES = frozenset(_ADS_UPDATE_REGISTRY)


def build_ad_object(*, adgroup_id, ad_type, mobile_provided, flags, flag_for=None):
    """Build a single ``Ads`` item dict from flag values (issue #562).

    Pure (no ``ctx``, no I/O): performs ``--type`` validation, the
    incompatible-flag guard, and dispatches to the registered per-subtype
    handler, returning ``{"AdGroupId": ..., "<SubType>": {...}}``. Both the
    single-flag ``ads add`` command and the ``--from-file`` batch normalizer
    call it so they emit byte-identical objects.

    ``flags`` is keyed by the command's dest var names (``image_hash``,
    ``mobile_app_features``, ...); missing keys default to ``None``.
    ``mobile_provided`` is the explicitly-passed ``--mobile`` value (``None``
    when the flag was not given), already resolved by the caller (it needs
    ``ctx``).
    """
    flag_for = flag_for if flag_for is not None else _ADS_ADD_FLAG_FOR

    ad_type_norm = (ad_type or "TEXT_AD").upper().replace("-", "_")
    registry_entry = _ADS_ADD_REGISTRY.get(ad_type_norm)
    if registry_entry is None:
        raise click.UsageError(
            t(
                "Invalid value for '--type': {ad_type!r} is not one of "
                "'TEXT_AD', 'TEXT_IMAGE_AD', 'MOBILE_APP_AD', "
                "'DYNAMIC_TEXT_AD', 'MOBILE_APP_IMAGE_AD', 'RESPONSIVE_AD', "
                "'SHOPPING_AD', 'LISTING_AD', 'SMART_AD_BUILDER_AD', "
                "'TEXT_AD_BUILDER_AD', 'MOBILE_APP_AD_BUILDER_AD', "
                "'MOBILE_APP_CPC_VIDEO_AD_BUILDER_AD', "
                "'CPC_VIDEO_AD_BUILDER_AD', 'CPM_BANNER_AD_BUILDER_AD', "
                "'CPM_VIDEO_AD_BUILDER_AD'."
            ).format(ad_type=ad_type)
        )
    fields, handler = registry_entry

    # `provided` is `flags` with the explicit --mobile value (the command passes
    # mobile separately; a batch row pops it out). _reject_incompatible_flags
    # skips None/() values and absent keys alike, so a sparse dict is fine.
    provided = {**flags, "mobile": mobile_provided}
    _reject_incompatible_flags(ad_type_norm, fields, provided, flag_for)

    # --mobile defaults to "NO" in the payload.
    mobile = mobile_provided or "NO"

    ad_data = {"AdGroupId": adgroup_id}
    handler(ad_data, flags, mobile)
    return ad_data


def build_ad_update_object(*, ad_id, ad_type, flags, flag_for=None):
    """Build a single ``Ads`` update item dict from flag values (issue #563).

    Pure (no ``ctx``, no I/O): performs ``--type`` validation, the
    incompatible-flag / "does not convert between subtypes" guard, dispatch to
    the registered per-subtype handler, and the empty-subtype no-op guard,
    returning ``{"Id": ..., "<SubType>": {...}}``. Both the single-flag
    ``ads update`` command and the ``--from-file`` batch normalizer call it so
    they emit byte-identical objects.

    ``flags`` is keyed by the command's dest var names (``image_hash``,
    ``clear_image_hash``, ``mobile_app_features``, ...); missing keys default to
    ``None``. The caller is responsible for the ``--status`` rejection and the
    ``--image-hash``/``--clear-image-hash`` mutex (those have command-level
    wording).
    """
    flag_for = flag_for if flag_for is not None else _ADS_UPDATE_FLAG_FOR

    ad_type_norm = ad_type.upper().replace("-", "_")
    registry_entry = _ADS_UPDATE_REGISTRY.get(ad_type_norm)
    if registry_entry is None:
        raise click.UsageError(
            t(
                "Invalid value for '--type': {ad_type!r} is not one of "
                "'TEXT_AD', 'TEXT_IMAGE_AD', 'MOBILE_APP_AD', "
                "'DYNAMIC_TEXT_AD', 'MOBILE_APP_IMAGE_AD', 'RESPONSIVE_AD', "
                "'SHOPPING_AD', 'LISTING_AD', 'SMART_AD_BUILDER_AD', "
                "'TEXT_AD_BUILDER_AD', 'MOBILE_APP_AD_BUILDER_AD', "
                "'MOBILE_APP_CPC_VIDEO_AD_BUILDER_AD', "
                "'CPC_VIDEO_AD_BUILDER_AD', 'CPM_BANNER_AD_BUILDER_AD', "
                "'CPM_VIDEO_AD_BUILDER_AD'."
            ).format(ad_type=ad_type)
        )
    fields, handler = registry_entry

    # Same normalization the historical inline guard dict applied.
    provided = {key: flags.get(key) for key in _ADS_UPDATE_FLAG_FOR}
    provided["clear_image_hash"] = provided.get("clear_image_hash") or None
    provided["mobile_app_features"] = provided.get("mobile_app_features") or ()
    provided["feed_filter_conditions"] = provided.get("feed_filter_conditions") or ()
    try:
        _reject_incompatible_flags(ad_type_norm, fields, provided, flag_for)
    except click.UsageError as exc:
        raise click.UsageError(
            t(
                "{arg0} --type selects the existing ad subtype update "
                "block; it does not convert an ad between subtypes."
            ).format(arg0=exc.message)
        )

    # Validate up-front so SET vs ADD/REMOVE mutex errors raise UsageError
    # before any payload work, bypassing the generic ``except Exception``
    # net wrapped around the network call below.
    precomputed = {
        "callout_setting": _build_callout_setting(
            flags.get("callouts_add"),
            flags.get("callouts_remove"),
            flags.get("callouts_set"),
        ),
        "price_extension": _build_price_extension(
            flags.get("price_extension_price"),
            flags.get("price_extension_old_price"),
            flags.get("price_extension_price_qualifier"),
            flags.get("price_extension_price_currency"),
        ),
        "parsed_mobile_app_features": _parse_mobile_app_features(
            flags.get("mobile_app_features") or ()
        ),
    }

    ad_data = {"Id": ad_id}
    handler(ad_data, flags, precomputed)

    # Reject empty-subtype no-ops: ``{Id: N}`` with no subtype block
    # is a silent no-op on the live API (issue #198 H1).
    if len(ad_data) == 1:
        raise click.UsageError(
            t(
                "ads update requires at least one updatable field for "
                "--type {ad_type_norm}."
            ).format(ad_type_norm=ad_type_norm)
        )

    return ad_data
