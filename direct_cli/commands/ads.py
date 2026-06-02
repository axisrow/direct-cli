"""
Ads commands
"""

from typing import Optional

import click

from ..api import client_from_ctx, create_client
from ..i18n import t
from ..output import format_output, handle_api_errors, print_error
from ..utils import (
    add_criteria_csv,
    get_default_fields,
    MICRO_RUBLES,
    parse_condition_specs,
    parse_csv_strings,
    parse_ids,
)


@click.group()
def ads():
    """Manage ads"""


def _parse_field_names_option(
    wsdl_key: str, raw_value: Optional[str]
) -> Optional[list[str]]:
    """Parse a field-name projection and reject explicitly empty CSV."""
    parsed = parse_csv_strings(raw_value)
    if raw_value is not None and not parsed:
        raise click.UsageError(
            t("Provide a non-empty comma-separated {wsdl_key} list.").format(
                wsdl_key=wsdl_key
            )
        )
    return parsed


MOBILE_APP_FEATURES = ("PRICE", "ICON", "CUSTOMER_RATING", "RATINGS")

FEED_BASED_UPDATE_FIELDS = {
    "sitelink_set_id",
    "callouts_add",
    "callouts_remove",
    "callouts_set",
    "business_id",
    "feed_filter_conditions",
    "title_sources",
    "text_sources",
    "default_texts",
}

FEED_BASED_ADD_FIELDS = {
    "sitelink_set_id",
    "ad_extensions",
    "business_id",
    "feed_id",
    "feed_filter_conditions",
    "title_sources",
    "text_sources",
    "default_texts",
}

DYNAMIC_TEXT_AD_ADD_FIELDS = {
    "text",
    "image_hash",
    "vcard_id",
    "sitelink_set_id",
    "ad_extensions",
}

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

SMART_AD_BUILDER_ADD_FIELDS = {"logo_extension_hash"}


TEXT_AD_UPDATE_FIELDS = {
    "title",
    "text",
    "href",
    "image_hash",
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

MOBILE_APP_AD_UPDATE_FIELDS = {
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

TEXT_IMAGE_AD_UPDATE_FIELDS = {
    "image_hash",
    "final_url",
    "href",
    "turbo_page_id",
    "erir_ad_description",
}

MOBILE_APP_IMAGE_UPDATE_FIELDS = {
    "image_hash",
    "tracking_url",
    "erir_ad_description",
}

SMART_AD_BUILDER_UPDATE_FIELDS = {
    "logo_extension_hash",
    "erir_ad_description",
}

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
                "{arg0} is not compatible with --type {ad_type}. Allowed flags for {ad_type}: {allowed_flags}."
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


def _build_text_ad_update_base(
    vcard_id: Optional[int],
    image_hash: Optional[str],
    sitelink_set_id: Optional[int],
    callout_setting: Optional[dict[str, object]],
) -> dict[str, object]:
    """Build fields inherited from WSDL TextAdUpdateBase."""
    text_ad_base: dict[str, object] = {}
    if vcard_id is not None:
        text_ad_base["VCardId"] = vcard_id
    if image_hash:
        text_ad_base["AdImageHash"] = image_hash
    if sitelink_set_id is not None:
        text_ad_base["SitelinkSetId"] = sitelink_set_id
    if callout_setting:
        text_ad_base["CalloutSetting"] = callout_setting
    return text_ad_base


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
                    "Invalid --mobile-app-feature feature {feature_raw!r}; allowed: {allowed_features}."
                ).format(feature_raw=feature_raw, allowed_features=allowed_features)
            )
        if enabled not in {"YES", "NO"}:
            raise click.UsageError(
                t(
                    "Invalid --mobile-app-feature value {enabled_raw!r}; expected YES or NO."
                ).format(enabled_raw=enabled_raw)
            )

        items.append({"Feature": feature, "Enabled": enabled})

    return items


def _build_responsive_ad_update(
    texts: Optional[str],
    titles: Optional[str],
    image_hashes: Optional[str],
    video_extension_ids: Optional[str],
    sitelink_set_id: Optional[int],
    callout_setting: Optional[dict[str, object]],
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


def _build_feed_based_ad_update(
    sitelink_set_id: Optional[int],
    callout_setting: Optional[dict[str, object]],
    business_id: Optional[int],
    feed_filter_conditions: tuple[str, ...],
    title_sources: Optional[str],
    text_sources: Optional[str],
    default_texts: Optional[str],
) -> dict[str, object]:
    """Build ShoppingAdUpdate / ListingAdUpdate payload from typed flags."""
    ad_payload: dict[str, object] = {}

    if sitelink_set_id is not None:
        ad_payload["SitelinkSetId"] = sitelink_set_id
    if callout_setting:
        ad_payload["CalloutSetting"] = callout_setting
    if business_id is not None:
        ad_payload["BusinessId"] = business_id
    if feed_filter_conditions:
        try:
            parsed_conditions = parse_condition_specs(list(feed_filter_conditions))
        except ValueError as exc:
            raise click.UsageError(t("--feed-filter-condition: {exc}").format(exc=exc))
        if parsed_conditions:
            ad_payload["FeedFilterConditions"] = {"Items": parsed_conditions}

    parsed_title_sources = _parse_required_csv_strings(title_sources, "--title-sources")
    if parsed_title_sources:
        ad_payload["TitleSources"] = {"Items": parsed_title_sources}
    parsed_text_sources = _parse_required_csv_strings(text_sources, "--text-sources")
    if parsed_text_sources:
        ad_payload["TextSources"] = {"Items": parsed_text_sources}
    parsed_default_texts = _parse_required_csv_strings(default_texts, "--default-texts")
    if parsed_default_texts:
        ad_payload["DefaultTexts"] = parsed_default_texts

    return ad_payload


def _build_feed_based_ad_add(
    feed_id: Optional[int],
    default_texts: Optional[str],
    sitelink_set_id: Optional[int],
    ad_extensions: Optional[str],
    business_id: Optional[int],
    feed_filter_conditions: tuple[str, ...],
    title_sources: Optional[str],
    text_sources: Optional[str],
    container_name: str,
) -> dict[str, object]:
    """Build ShoppingAdAdd / ListingAdAdd payload from typed flags."""
    missing_fields = []
    if feed_id is None:
        missing_fields.append("--feed-id")
    if default_texts is None:
        missing_fields.append("--default-texts")
    if missing_fields:
        raise click.UsageError(
            t("{container_name} requires {arg0}").format(
                container_name=container_name, arg0=", ".join(missing_fields)
            )
        )

    default_text = default_texts.strip() if default_texts else ""
    if not default_text:
        raise click.UsageError(t("--default-texts must contain a value."))

    ad_payload: dict[str, object] = {
        "FeedId": feed_id,
        "DefaultTexts": [default_text],
    }

    if sitelink_set_id is not None:
        ad_payload["SitelinkSetId"] = sitelink_set_id
    parsed_ad_extensions = _parse_required_ids(ad_extensions, "--ad-extensions")
    if parsed_ad_extensions:
        ad_payload["AdExtensionIds"] = parsed_ad_extensions
    if business_id is not None:
        ad_payload["BusinessId"] = business_id
    if feed_filter_conditions:
        if len(feed_filter_conditions) > 30:
            raise click.UsageError(
                t(
                    "{container_name}.FeedFilterConditions accepts at most 30 filters."
                ).format(container_name=container_name)
            )
        try:
            parsed_conditions = parse_condition_specs(list(feed_filter_conditions))
        except ValueError as exc:
            raise click.UsageError(t("--feed-filter-condition: {exc}").format(exc=exc))
        if parsed_conditions:
            ad_payload["FeedFilterConditions"] = parsed_conditions

    parsed_title_sources = _parse_required_csv_strings(title_sources, "--title-sources")
    if parsed_title_sources:
        ad_payload["TitleSources"] = parsed_title_sources
    parsed_text_sources = _parse_required_csv_strings(text_sources, "--text-sources")
    if parsed_text_sources:
        ad_payload["TextSources"] = parsed_text_sources

    return ad_payload


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


def _build_mobile_app_image_ad_update(
    image_hash: Optional[str],
    erir_ad_description: Optional[str],
    tracking_url: Optional[str],
) -> dict[str, object]:
    """Build MobileAppImageAdUpdate payload from typed flags."""
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


@ads.command()
@click.option("--ids", help="Comma-separated ad IDs")
@click.option("--campaign-ids", help="Comma-separated campaign IDs")
@click.option("--adgroup-ids", help="Comma-separated ad group IDs")
@click.option("--status", help="Filter by status")
@click.option("--statuses", help="Comma-separated statuses")
@click.option("--states", help="Comma-separated states")
@click.option("--types", help="Comma-separated ad types")
@click.option("--mobile", type=click.Choice(["YES", "NO"], case_sensitive=False))
@click.option("--vcard-ids", help="Comma-separated vCard IDs")
@click.option("--sitelink-set-ids", help="Comma-separated sitelink set IDs")
@click.option("--image-hashes", help="Comma-separated ad image hashes")
@click.option(
    "--vcard-moderation-statuses", help="Comma-separated vCard moderation statuses"
)
@click.option(
    "--sitelinks-moderation-statuses",
    help="Comma-separated sitelinks moderation statuses",
)
@click.option(
    "--image-moderation-statuses", help="Comma-separated image moderation statuses"
)
@click.option("--adextension-ids", help="Comma-separated ad extension IDs")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated top-level field names")
@click.option(
    "--cpc-video-ad-builder-ad-field-names",
    help=(
        "Comma-separated CpcVideoAdBuilderAdFieldNames "
        "(e.g. CreativeId,Href). Sent as separate top-level request "
        "parameter per the AdsGetRequest WSDL."
    ),
)
@click.option(
    "--cpm-banner-ad-builder-ad-field-names",
    help=(
        "Comma-separated CpmBannerAdBuilderAdFieldNames "
        "(e.g. CreativeId,Href). Sent as separate top-level request "
        "parameter per the AdsGetRequest WSDL."
    ),
)
@click.option(
    "--cpm-video-ad-builder-ad-field-names",
    help=(
        "Comma-separated CpmVideoAdBuilderAdFieldNames "
        "(e.g. CreativeId,Href). Sent as separate top-level request "
        "parameter per the AdsGetRequest WSDL."
    ),
)
@click.option(
    "--dynamic-text-ad-field-names",
    help=(
        "Comma-separated DynamicTextAdFieldNames (e.g. Title,Text,Href). "
        "Sent as separate top-level request parameter per the "
        "AdsGetRequest WSDL."
    ),
)
@click.option(
    "--listing-ad-field-names",
    help=(
        "Comma-separated ListingAdFieldNames (e.g. Title,Text,Href). "
        "Sent as separate top-level request parameter per the "
        "AdsGetRequest WSDL."
    ),
)
@click.option(
    "--mobile-app-ad-builder-ad-field-names",
    help=(
        "Comma-separated MobileAppAdBuilderAdFieldNames "
        "(e.g. CreativeId,TrackingUrl). Sent as separate top-level "
        "request parameter per the AdsGetRequest WSDL."
    ),
)
@click.option(
    "--mobile-app-ad-field-names",
    help=(
        "Comma-separated MobileAppAdFieldNames (e.g. Title,Text,TrackingUrl). "
        "Sent as separate top-level request parameter per the "
        "AdsGetRequest WSDL."
    ),
)
@click.option(
    "--mobile-app-cpc-video-ad-builder-ad-field-names",
    help=(
        "Comma-separated MobileAppCpcVideoAdBuilderAdFieldNames "
        "(e.g. CreativeId,TrackingUrl). Sent as separate top-level "
        "request parameter per the AdsGetRequest WSDL."
    ),
)
@click.option(
    "--mobile-app-image-ad-field-names",
    help=(
        "Comma-separated MobileAppImageAdFieldNames (e.g. ImageHash,TrackingUrl). "
        "Sent as separate top-level request parameter per the "
        "AdsGetRequest WSDL."
    ),
)
@click.option(
    "--responsive-ad-field-names",
    help=(
        "Comma-separated ResponsiveAdFieldNames (e.g. Titles,Texts,Href). "
        "Sent as separate top-level request parameter per the "
        "AdsGetRequest WSDL."
    ),
)
@click.option(
    "--shopping-ad-field-names",
    help=(
        "Comma-separated ShoppingAdFieldNames (e.g. Titles,Texts,Href). "
        "Sent as separate top-level request parameter per the "
        "AdsGetRequest WSDL."
    ),
)
@click.option(
    "--smart-ad-builder-ad-field-names",
    help=(
        "Comma-separated SmartAdBuilderAdFieldNames (e.g. CreativeId). "
        "Sent as separate top-level request parameter per the "
        "AdsGetRequest WSDL."
    ),
)
@click.option(
    "--text-ad-builder-ad-field-names",
    help=(
        "Comma-separated TextAdBuilderAdFieldNames (e.g. CreativeId,Href). "
        "Sent as separate top-level request parameter per the "
        "AdsGetRequest WSDL."
    ),
)
@click.option(
    "--text-ad-field-names",
    help=(
        "Comma-separated TextAdFieldNames (e.g. Title,Text,Href). "
        "Sent as separate top-level request parameter per the "
        "AdsGetRequest WSDL."
    ),
)
@click.option(
    "--text-ad-price-extension-field-names",
    help=(
        "Comma-separated TextAdPriceExtensionFieldNames "
        "(e.g. Price,OldPrice,PriceQualifier). Sent as separate top-level "
        "request parameter per the AdsGetRequest WSDL."
    ),
)
@click.option(
    "--text-image-ad-field-names",
    help=(
        "Comma-separated TextImageAdFieldNames (e.g. Href,ImageHash). "
        "Sent as separate top-level request parameter per the "
        "AdsGetRequest WSDL."
    ),
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def get(
    ctx,
    ids,
    campaign_ids,
    adgroup_ids,
    status,
    statuses,
    states,
    types,
    mobile,
    vcard_ids,
    sitelink_set_ids,
    image_hashes,
    vcard_moderation_statuses,
    sitelinks_moderation_statuses,
    image_moderation_statuses,
    adextension_ids,
    limit,
    fetch_all,
    output_format,
    output,
    fields,
    cpc_video_ad_builder_ad_field_names,
    cpm_banner_ad_builder_ad_field_names,
    cpm_video_ad_builder_ad_field_names,
    dynamic_text_ad_field_names,
    listing_ad_field_names,
    mobile_app_ad_builder_ad_field_names,
    mobile_app_ad_field_names,
    mobile_app_cpc_video_ad_builder_ad_field_names,
    mobile_app_image_ad_field_names,
    responsive_ad_field_names,
    shopping_ad_field_names,
    smart_ad_builder_ad_field_names,
    text_ad_builder_ad_field_names,
    text_ad_field_names,
    text_ad_price_extension_field_names,
    text_image_ad_field_names,
    dry_run,
):
    """Get ads"""
    if status and statuses:
        raise click.UsageError(t("--status and --statuses are mutually exclusive"))

    try:
        field_names = (
            fields.split(",") if fields else get_default_fields("ads", "FieldNames")
        )

        raw_nested = (
            (
                "CpcVideoAdBuilderAdFieldNames",
                cpc_video_ad_builder_ad_field_names,
            ),
            (
                "CpmBannerAdBuilderAdFieldNames",
                cpm_banner_ad_builder_ad_field_names,
            ),
            (
                "CpmVideoAdBuilderAdFieldNames",
                cpm_video_ad_builder_ad_field_names,
            ),
            ("DynamicTextAdFieldNames", dynamic_text_ad_field_names),
            ("ListingAdFieldNames", listing_ad_field_names),
            ("MobileAppAdBuilderAdFieldNames", mobile_app_ad_builder_ad_field_names),
            ("MobileAppAdFieldNames", mobile_app_ad_field_names),
            (
                "MobileAppCpcVideoAdBuilderAdFieldNames",
                mobile_app_cpc_video_ad_builder_ad_field_names,
            ),
            ("MobileAppImageAdFieldNames", mobile_app_image_ad_field_names),
            ("ResponsiveAdFieldNames", responsive_ad_field_names),
            ("ShoppingAdFieldNames", shopping_ad_field_names),
            ("SmartAdBuilderAdFieldNames", smart_ad_builder_ad_field_names),
            ("TextAdBuilderAdFieldNames", text_ad_builder_ad_field_names),
            ("TextAdFieldNames", text_ad_field_names),
            (
                "TextAdPriceExtensionFieldNames",
                text_ad_price_extension_field_names,
            ),
            ("TextImageAdFieldNames", text_image_ad_field_names),
        )
        parsed_nested = {}
        for wsdl_key, raw_value in raw_nested:
            parsed = _parse_field_names_option(wsdl_key, raw_value)
            if parsed:
                parsed_nested[wsdl_key] = parsed
        parsed_nested.setdefault(
            "TextAdFieldNames", get_default_fields("ads", "TextAdFieldNames")
        )

        criteria = {}
        if ids:
            criteria["Ids"] = parse_ids(ids)
        if campaign_ids:
            criteria["CampaignIds"] = parse_ids(campaign_ids)
        if adgroup_ids:
            criteria["AdGroupIds"] = parse_ids(adgroup_ids)
        if status:
            criteria["Statuses"] = [status]
        add_criteria_csv(criteria, "Statuses", statuses, upper=True)
        add_criteria_csv(criteria, "States", states, upper=True)
        add_criteria_csv(criteria, "Types", types, upper=True)
        if mobile:
            criteria["Mobile"] = mobile.upper()
        add_criteria_csv(criteria, "VCardIds", vcard_ids, integers=True)
        add_criteria_csv(criteria, "SitelinkSetIds", sitelink_set_ids, integers=True)
        add_criteria_csv(criteria, "AdImageHashes", image_hashes)
        add_criteria_csv(
            criteria, "VCardModerationStatuses", vcard_moderation_statuses, upper=True
        )
        add_criteria_csv(
            criteria,
            "SitelinksModerationStatuses",
            sitelinks_moderation_statuses,
            upper=True,
        )
        add_criteria_csv(
            criteria, "AdImageModerationStatuses", image_moderation_statuses, upper=True
        )
        add_criteria_csv(criteria, "AdExtensionIds", adextension_ids, integers=True)

        params = {
            "SelectionCriteria": criteria,
            "FieldNames": field_names,
        }
        params.update(parsed_nested)

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        if dry_run:
            format_output(body, "json", None)
            return

        client = client_from_ctx(ctx, create_client)

        result = client.ads().post(data=body)

        if fetch_all:
            items = []
            for item in result().iter_items():
                items.append(item)
            format_output(items, output_format, output)
        else:
            data = result().extract()
            format_output(data, output_format, output)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@ads.command()
@click.option("--adgroup-id", required=True, type=int, help="Ad group ID")
@click.option(
    "--type",
    "ad_type",
    default="TEXT_AD",
    help=(
        "Ad type: TEXT_AD | TEXT_IMAGE_AD | MOBILE_APP_AD | DYNAMIC_TEXT_AD | "
        "MOBILE_APP_IMAGE_AD | RESPONSIVE_AD | SHOPPING_AD | LISTING_AD | "
        "SMART_AD_BUILDER_AD | TEXT_AD_BUILDER_AD | "
        "MOBILE_APP_AD_BUILDER_AD | MOBILE_APP_CPC_VIDEO_AD_BUILDER_AD | "
        "CPC_VIDEO_AD_BUILDER_AD | CPM_BANNER_AD_BUILDER_AD | "
        "CPM_VIDEO_AD_BUILDER_AD"
    ),
)
@click.option("--title", help="Ad title (TEXT_AD / MOBILE_APP_AD)")
@click.option("--text", help="Ad text (TEXT_AD / MOBILE_APP_AD / DYNAMIC_TEXT_AD)")
@click.option("--titles", help="Comma-separated ResponsiveAd.Titles values")
@click.option("--texts", help="Comma-separated ResponsiveAd.Texts values")
@click.option(
    "--href",
    help=(
        "Ad URL (TEXT_AD / TEXT_IMAGE_AD / RESPONSIVE_AD / TEXT_AD_BUILDER_AD / "
        "CPC_VIDEO_AD_BUILDER_AD / CPM_BANNER_AD_BUILDER_AD / "
        "CPM_VIDEO_AD_BUILDER_AD)"
    ),
)
@click.option(
    "--image-hash",
    help=(
        "Ad image hash (TEXT_IMAGE_AD / MOBILE_APP_AD / DYNAMIC_TEXT_AD / "
        "MOBILE_APP_IMAGE_AD)"
    ),
)
@click.option(
    "--image-hashes",
    help="Comma-separated ResponsiveAd.AdImageHashes values",
)
@click.option(
    "--action",
    help="MOBILE_APP_AD call-to-action (MobileAppAdActionEnum, e.g. INSTALL)",
)
@click.option(
    "--tracking-url",
    help=(
        "Tracking URL (MOBILE_APP_AD / MOBILE_APP_AD_BUILDER_AD / "
        "MOBILE_APP_CPC_VIDEO_AD_BUILDER_AD / MOBILE_APP_IMAGE_AD)"
    ),
)
@click.option(
    "--age-label",
    help="Age label (MOBILE_APP_AD MobAppAgeLabelEnum / RESPONSIVE_AD AgeLabelEnum)",
)
@click.option(
    "--mobile-app-feature",
    "mobile_app_features",
    multiple=True,
    help=(
        "Repeatable MobileAppAd.Features item as FEATURE=YES|NO "
        "(PRICE, ICON, CUSTOMER_RATING, RATINGS)"
    ),
)
@click.option("--title2", help="Second headline (TEXT_AD)")
@click.option("--display-url-path", help="Display URL path (TEXT_AD / RESPONSIVE_AD)")
@click.option(
    "--mobile",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    default="NO",
    help="Mobile-targeted flag (TEXT_AD)",
)
@click.option("--vcard-id", type=int, help="VCard ID (TEXT_AD / DYNAMIC_TEXT_AD)")
@click.option(
    "--sitelink-set-id",
    type=int,
    help=(
        "Sitelink set ID "
        "(TEXT_AD / DYNAMIC_TEXT_AD / RESPONSIVE_AD / SHOPPING_AD / LISTING_AD)"
    ),
)
@click.option(
    "--turbo-page-id",
    type=int,
    help=(
        "Turbo page ID (TEXT_AD / TEXT_IMAGE_AD / TEXT_AD_BUILDER_AD / "
        "CPC_VIDEO_AD_BUILDER_AD / CPM_BANNER_AD_BUILDER_AD / "
        "CPM_VIDEO_AD_BUILDER_AD)"
    ),
)
@click.option(
    "--ad-extensions",
    help=(
        "Comma-separated ad extension IDs "
        "(TEXT_AD / DYNAMIC_TEXT_AD / RESPONSIVE_AD / SHOPPING_AD / LISTING_AD)"
    ),
)
@click.option(
    "--final-url",
    help="FinalUrl (TEXT_AD / TEXT_IMAGE_AD / TEXT_AD_BUILDER_AD)",
)
@click.option(
    "--video-extension-creative-id",
    type=int,
    help="TextAd/MobileAppAd.VideoExtension.CreativeId (TEXT_AD / MOBILE_APP_AD)",
)
@click.option(
    "--price-extension-price",
    type=MICRO_RUBLES,
    help=(
        "TextAd/ResponsiveAd.PriceExtension.Price in micro-rubles. "
        "Required whenever any PriceExtension flag is used."
    ),
)
@click.option(
    "--price-extension-old-price",
    type=MICRO_RUBLES,
    help=(
        "TextAd/ResponsiveAd.PriceExtension.OldPrice in micro-rubles. "
        "Optional; if supplied, PriceExtension add also requires "
        "--price-extension-price, --price-extension-price-qualifier, "
        "and --price-extension-price-currency."
    ),
)
@click.option(
    "--price-extension-price-qualifier",
    type=click.Choice(["FROM", "UP_TO", "NONE"], case_sensitive=False),
    help=(
        "TextAd/ResponsiveAd.PriceExtension.PriceQualifier: FROM, UP_TO, or NONE. "
        "Required whenever any PriceExtension flag is used."
    ),
)
@click.option(
    "--price-extension-price-currency",
    type=click.Choice(
        ["RUB", "UAH", "BYN", "USD", "EUR", "KZT", "TRY", "CHF", "UZS"],
        case_sensitive=False,
    ),
    help=(
        "TextAd/ResponsiveAd.PriceExtension.PriceCurrency enum value. "
        "Required whenever any PriceExtension flag is used."
    ),
)
@click.option(
    "--video-extension-ids",
    help="Comma-separated ResponsiveAd.VideoExtensionIds values",
)
@click.option(
    "--business-id",
    type=int,
    help="BusinessId (TEXT_AD / RESPONSIVE_AD / SHOPPING_AD / LISTING_AD)",
)
@click.option(
    "--prefer-vcard-over-business",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="TextAd.PreferVCardOverBusiness value: YES or NO",
)
@click.option(
    "--erir-ad-description",
    help=(
        "ErirAdDescription (TEXT_AD / TEXT_IMAGE_AD / MOBILE_APP_AD / "
        "MOBILE_APP_IMAGE_AD / RESPONSIVE_AD / non-SMART AdBuilder add subtypes)"
    ),
)
@click.option(
    "--creative-id",
    type=int,
    help="AdBuilder Creative.CreativeId for non-SMART AdBuilder add subtypes",
)
@click.option(
    "--tracking-pixels",
    help="Comma-separated AdBuilder TrackingPixels.Items values",
)
@click.option(
    "--logo-extension-hash",
    help="SmartAdBuilderAd.LogoExtensionHash (SMART_AD_BUILDER_AD)",
)
@click.option(
    "--feed-id",
    type=int,
    help="ShoppingAd/ListingAd.FeedId (SHOPPING_AD / LISTING_AD)",
)
@click.option(
    "--feed-filter-condition",
    "feed_filter_conditions",
    multiple=True,
    help=(
        "Repeatable ShoppingAd/ListingAd.FeedFilterConditions item as "
        "OPERAND:OPERATOR:ARG1|ARG2"
    ),
)
@click.option(
    "--title-sources",
    help="Comma-separated ShoppingAd/ListingAd.TitleSources values",
)
@click.option(
    "--text-sources",
    help="Comma-separated ShoppingAd/ListingAd.TextSources values",
)
@click.option(
    "--default-texts",
    help="ShoppingAd/ListingAd.DefaultTexts value (required for SHOPPING_AD/LISTING_AD)",
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def add(
    ctx,
    adgroup_id,
    ad_type,
    title,
    text,
    titles,
    texts,
    href,
    image_hash,
    image_hashes,
    action,
    tracking_url,
    age_label,
    mobile_app_features,
    title2,
    display_url_path,
    mobile,
    vcard_id,
    sitelink_set_id,
    turbo_page_id,
    ad_extensions,
    final_url,
    video_extension_creative_id,
    price_extension_price,
    price_extension_old_price,
    price_extension_price_qualifier,
    price_extension_price_currency,
    video_extension_ids,
    business_id,
    prefer_vcard_over_business,
    erir_ad_description,
    creative_id,
    tracking_pixels,
    logo_extension_hash,
    feed_id,
    feed_filter_conditions,
    title_sources,
    text_sources,
    default_texts,
    dry_run,
):
    """Add new ad"""
    ad_type_norm = (ad_type or "TEXT_AD").upper().replace("-", "_")
    supported_types = {
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
    if ad_type_norm not in supported_types:
        raise click.UsageError(
            t(
                "Invalid value for '--type': {ad_type!r} is not one of 'TEXT_AD', 'TEXT_IMAGE_AD', 'MOBILE_APP_AD', 'DYNAMIC_TEXT_AD', 'MOBILE_APP_IMAGE_AD', 'RESPONSIVE_AD', 'SHOPPING_AD', 'LISTING_AD', 'SMART_AD_BUILDER_AD', 'TEXT_AD_BUILDER_AD', 'MOBILE_APP_AD_BUILDER_AD', 'MOBILE_APP_CPC_VIDEO_AD_BUILDER_AD', 'CPC_VIDEO_AD_BUILDER_AD', 'CPM_BANNER_AD_BUILDER_AD', 'CPM_VIDEO_AD_BUILDER_AD'."
            ).format(ad_type=ad_type)
        )

    # --mobile has a Click default of "NO" so the value is always present
    # in the payload, but the per-subtype guard must reject any explicit
    # use of --mobile on non-TEXT_AD subtypes — including --mobile NO —
    # to avoid silent data loss (issue #198 H2 / #202).
    mobile_source = ctx.get_parameter_source("mobile")
    mobile_explicit = (
        mobile_source != click.core.ParameterSource.DEFAULT if mobile_source else False
    )
    mobile_provided = mobile if mobile_explicit else None

    type_fields = {
        "TEXT_AD": {
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
        },
        "TEXT_IMAGE_AD": {
            "href",
            "image_hash",
            "turbo_page_id",
            "final_url",
            "erir_ad_description",
        },
        "RESPONSIVE_AD": {
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
        },
        "SHOPPING_AD": FEED_BASED_ADD_FIELDS,
        "LISTING_AD": FEED_BASED_ADD_FIELDS,
        **AD_BUILDER_ADD_TYPE_FIELDS,
        "DYNAMIC_TEXT_AD": DYNAMIC_TEXT_AD_ADD_FIELDS,
        "MOBILE_APP_AD": MOBILE_APP_AD_ADD_FIELDS,
        "MOBILE_APP_IMAGE_AD": MOBILE_APP_IMAGE_AD_ADD_FIELDS,
        "SMART_AD_BUILDER_AD": SMART_AD_BUILDER_ADD_FIELDS,
    }
    provided = {
        "title": title,
        "text": text,
        "titles": titles,
        "texts": texts,
        "href": href,
        "image_hash": image_hash,
        "image_hashes": image_hashes,
        "action": action,
        "tracking_url": tracking_url,
        "age_label": age_label,
        "mobile_app_features": mobile_app_features,
        "title2": title2,
        "display_url_path": display_url_path,
        "mobile": mobile_provided,
        "vcard_id": vcard_id,
        "sitelink_set_id": sitelink_set_id,
        "turbo_page_id": turbo_page_id,
        "ad_extensions": ad_extensions,
        "final_url": final_url,
        "video_extension_creative_id": video_extension_creative_id,
        "price_extension_price": price_extension_price,
        "price_extension_old_price": price_extension_old_price,
        "price_extension_price_qualifier": price_extension_price_qualifier,
        "price_extension_price_currency": price_extension_price_currency,
        "video_extension_ids": video_extension_ids,
        "business_id": business_id,
        "prefer_vcard_over_business": prefer_vcard_over_business,
        "erir_ad_description": erir_ad_description,
        "creative_id": creative_id,
        "tracking_pixels": tracking_pixels,
        "logo_extension_hash": logo_extension_hash,
        "feed_id": feed_id,
        "feed_filter_conditions": feed_filter_conditions,
        "title_sources": title_sources,
        "text_sources": text_sources,
        "default_texts": default_texts,
    }
    flag_for = {
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
    _reject_incompatible_flags(
        ad_type_norm, type_fields[ad_type_norm], provided, flag_for
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
        responsive_ad = {
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

    body = {"method": "add", "params": {"Ads": [ad_data]}}

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = client.ads().post(data=body)
    format_output(result().extract(), "json", None)


@ads.command()
@click.option("--id", "ad_id", required=True, type=int, help="Ad ID")
@click.option(
    "--type",
    "ad_type",
    required=True,
    help=(
        "Ad subtype: TEXT_AD | TEXT_IMAGE_AD | MOBILE_APP_AD | "
        "DYNAMIC_TEXT_AD | MOBILE_APP_IMAGE_AD | RESPONSIVE_AD | "
        "SHOPPING_AD | LISTING_AD | SMART_AD_BUILDER_AD | TEXT_AD_BUILDER_AD | "
        "MOBILE_APP_AD_BUILDER_AD | MOBILE_APP_CPC_VIDEO_AD_BUILDER_AD | "
        "CPC_VIDEO_AD_BUILDER_AD | CPM_BANNER_AD_BUILDER_AD | "
        "CPM_VIDEO_AD_BUILDER_AD"
    ),
)
@click.option(
    "--status",
    help=(
        "Deprecated: not part of WSDL AdUpdateItem. "
        "Use 'direct ads suspend/resume/archive/unarchive' instead."
    ),
)
@click.option("--title", help="Title (TEXT_AD / MOBILE_APP_AD)")
@click.option("--text", help="Text (TEXT_AD / MOBILE_APP_AD / DYNAMIC_TEXT_AD)")
@click.option("--titles", help="Comma-separated ResponsiveAd.Titles values")
@click.option("--texts", help="Comma-separated ResponsiveAd.Texts values")
@click.option(
    "--href",
    help=(
        "URL (TEXT_AD / TEXT_IMAGE_AD / RESPONSIVE_AD / "
        "TEXT_AD_BUILDER_AD / CPC_VIDEO_AD_BUILDER_AD / "
        "CPM_BANNER_AD_BUILDER_AD / CPM_VIDEO_AD_BUILDER_AD)"
    ),
)
@click.option(
    "--image-hash",
    help=(
        "Image hash (TEXT_AD / TEXT_IMAGE_AD / MOBILE_APP_AD / "
        "DYNAMIC_TEXT_AD / MOBILE_APP_IMAGE_AD)"
    ),
)
@click.option(
    "--image-hashes",
    help="Comma-separated ResponsiveAd.AdImageHashes.Items values",
)
@click.option(
    "--action",
    help="MOBILE_APP_AD call-to-action (MobileAppAdActionEnum, e.g. INSTALL)",
)
@click.option(
    "--tracking-url",
    help=(
        "Tracking URL (MOBILE_APP_AD / MOBILE_APP_AD_BUILDER_AD / "
        "MOBILE_APP_CPC_VIDEO_AD_BUILDER_AD / MOBILE_APP_IMAGE_AD)"
    ),
)
@click.option(
    "--age-label",
    help=(
        "Age label (TEXT_AD / RESPONSIVE_AD AgeLabelEnum; "
        "MOBILE_APP_AD MobAppAgeLabelEnum)"
    ),
)
@click.option(
    "--mobile-app-feature",
    "mobile_app_features",
    multiple=True,
    help=(
        "Repeatable MobileAppAd.Features item as FEATURE=YES|NO. "
        "Features: PRICE, ICON, CUSTOMER_RATING, RATINGS."
    ),
)
@click.option("--title2", help="Second headline (TEXT_AD)")
@click.option("--display-url-path", help="Display URL path (TEXT_AD / RESPONSIVE_AD)")
@click.option("--vcard-id", type=int, help="VCard ID (TEXT_AD / DYNAMIC_TEXT_AD)")
@click.option(
    "--sitelink-set-id",
    type=int,
    help=(
        "Sitelink set ID "
        "(TEXT_AD / DYNAMIC_TEXT_AD / RESPONSIVE_AD / SHOPPING_AD / LISTING_AD)"
    ),
)
@click.option(
    "--turbo-page-id",
    type=int,
    help=(
        "Turbo page ID (TEXT_AD / TEXT_IMAGE_AD / TEXT_AD_BUILDER_AD / "
        "CPC_VIDEO_AD_BUILDER_AD / CPM_BANNER_AD_BUILDER_AD / "
        "CPM_VIDEO_AD_BUILDER_AD)"
    ),
)
@click.option(
    "--callouts-add",
    help=(
        "Comma-separated CALLOUT ad-extension IDs to attach "
        "(Operation=ADD). TEXT_AD / DYNAMIC_TEXT_AD / RESPONSIVE_AD / "
        "SHOPPING_AD / LISTING_AD only."
    ),
)
@click.option(
    "--callouts-remove",
    help=(
        "Comma-separated CALLOUT ad-extension IDs to detach "
        "(Operation=REMOVE). TEXT_AD / DYNAMIC_TEXT_AD / RESPONSIVE_AD / "
        "SHOPPING_AD / LISTING_AD only."
    ),
)
@click.option(
    "--callouts-set",
    help=(
        "Comma-separated CALLOUT ad-extension IDs that REPLACE the ad's "
        "current callout list (Operation=SET). Mutually exclusive with "
        "--callouts-add / --callouts-remove. TEXT_AD / DYNAMIC_TEXT_AD / "
        "RESPONSIVE_AD / SHOPPING_AD / LISTING_AD only."
    ),
)
@click.option(
    "--video-extension-creative-id",
    type=int,
    help=(
        "Video extension CreativeId for TextAd/MobileAppAd.VideoExtension. "
        "TEXT_AD / MOBILE_APP_AD only."
    ),
)
@click.option(
    "--video-extension-ids",
    help="Comma-separated ResponsiveAd.VideoExtensionIds.Items values",
)
@click.option(
    "--price-extension-price",
    type=MICRO_RUBLES,
    help=("PriceExtension.Price in micro-rubles. TEXT_AD / RESPONSIVE_AD only."),
)
@click.option(
    "--price-extension-old-price",
    type=MICRO_RUBLES,
    help=("PriceExtension.OldPrice in micro-rubles. TEXT_AD / RESPONSIVE_AD only."),
)
@click.option(
    "--price-extension-price-qualifier",
    type=click.Choice(["FROM", "UP_TO", "NONE"], case_sensitive=False),
    help=(
        "PriceExtension.PriceQualifier: FROM, UP_TO, or NONE. "
        "TEXT_AD / RESPONSIVE_AD only."
    ),
)
@click.option(
    "--price-extension-price-currency",
    type=click.Choice(
        ["RUB", "UAH", "BYN", "USD", "EUR", "KZT", "TRY", "CHF", "UZS"],
        case_sensitive=False,
    ),
    help="PriceExtension.PriceCurrency enum value. TEXT_AD / RESPONSIVE_AD only.",
)
@click.option(
    "--business-id",
    type=int,
    help="BusinessId (TEXT_AD / RESPONSIVE_AD / SHOPPING_AD / LISTING_AD)",
)
@click.option(
    "--prefer-vcard-over-business",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="TextAd.PreferVCardOverBusiness value: YES or NO",
)
@click.option(
    "--erir-ad-description",
    help=(
        "ErirAdDescription for TEXT_AD, TEXT_IMAGE_AD, MOBILE_APP_AD, "
        "RESPONSIVE_AD, MOBILE_APP_IMAGE_AD, SMART_AD_BUILDER_AD, "
        "and AdBuilder update subtypes"
    ),
)
@click.option(
    "--logo-extension-hash",
    help="SmartAdBuilderAd.LogoExtensionHash",
)
@click.option(
    "--creative-id",
    type=int,
    help="AdBuilder Creative.CreativeId for AdBuilder update subtypes",
)
@click.option(
    "--creative-erir-ad-description",
    help="AdBuilder Creative.ErirAdDescription; requires --creative-id",
)
@click.option(
    "--final-url",
    help="FinalUrl (TEXT_AD / TEXT_IMAGE_AD / TEXT_AD_BUILDER_AD)",
)
@click.option(
    "--tracking-pixels",
    help="Comma-separated AdBuilder TrackingPixels.Items values",
)
@click.option(
    "--feed-filter-condition",
    "feed_filter_conditions",
    multiple=True,
    help=(
        "Repeatable ShoppingAd/ListingAd FeedFilterConditions item as "
        "OPERAND:OPERATOR:ARG1|ARG2"
    ),
)
@click.option(
    "--title-sources",
    help="Comma-separated ShoppingAd/ListingAd.TitleSources.Items values",
)
@click.option(
    "--text-sources",
    help="Comma-separated ShoppingAd/ListingAd.TextSources.Items values",
)
@click.option(
    "--default-texts",
    help="Comma-separated ShoppingAd/ListingAd.DefaultTexts values",
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def update(
    ctx,
    ad_id,
    ad_type,
    status,
    title,
    text,
    titles,
    texts,
    href,
    image_hash,
    image_hashes,
    action,
    tracking_url,
    age_label,
    mobile_app_features,
    title2,
    display_url_path,
    vcard_id,
    sitelink_set_id,
    turbo_page_id,
    callouts_add,
    callouts_remove,
    callouts_set,
    video_extension_creative_id,
    video_extension_ids,
    price_extension_price,
    price_extension_old_price,
    price_extension_price_qualifier,
    price_extension_price_currency,
    business_id,
    prefer_vcard_over_business,
    erir_ad_description,
    logo_extension_hash,
    creative_id,
    creative_erir_ad_description,
    final_url,
    tracking_pixels,
    feed_filter_conditions,
    title_sources,
    text_sources,
    default_texts,
    dry_run,
):
    """Update ad"""
    if status:
        raise click.UsageError(
            t(
                "Use 'direct ads suspend/resume/archive/unarchive' to change status. "
                "The --status flag is not supported by WSDL AdUpdateItem."
            )
        )

    ad_type_norm = ad_type.upper().replace("-", "_")
    supported_types = {
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
    if ad_type_norm not in supported_types:
        raise click.UsageError(
            t(
                "Invalid value for '--type': {ad_type!r} is not one of 'TEXT_AD', 'TEXT_IMAGE_AD', 'MOBILE_APP_AD', 'DYNAMIC_TEXT_AD', 'MOBILE_APP_IMAGE_AD', 'RESPONSIVE_AD', 'SHOPPING_AD', 'LISTING_AD', 'SMART_AD_BUILDER_AD', 'TEXT_AD_BUILDER_AD', 'MOBILE_APP_AD_BUILDER_AD', 'MOBILE_APP_CPC_VIDEO_AD_BUILDER_AD', 'CPC_VIDEO_AD_BUILDER_AD', 'CPM_BANNER_AD_BUILDER_AD', 'CPM_VIDEO_AD_BUILDER_AD'."
            ).format(ad_type=ad_type)
        )

    # Per-WSDL-subtype field allow-list: each --type accepts only the
    # options that map to fields inside its AdUpdateItem subtype. A flag
    # outside the allow-list would be silently dropped by the loop below;
    # reject up front so the user sees the conflict instead of a no-op
    # (issue #198 H2).
    type_fields = {
        "TEXT_AD": TEXT_AD_UPDATE_FIELDS,
        "DYNAMIC_TEXT_AD": {
            "text",
            "image_hash",
            "vcard_id",
            "sitelink_set_id",
            "callouts_add",
            "callouts_remove",
            "callouts_set",
        },
        "TEXT_IMAGE_AD": TEXT_IMAGE_AD_UPDATE_FIELDS,
        "MOBILE_APP_AD": MOBILE_APP_AD_UPDATE_FIELDS,
        "MOBILE_APP_IMAGE_AD": MOBILE_APP_IMAGE_UPDATE_FIELDS,
        "RESPONSIVE_AD": {
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
        },
        "SHOPPING_AD": FEED_BASED_UPDATE_FIELDS,
        "LISTING_AD": FEED_BASED_UPDATE_FIELDS,
        "SMART_AD_BUILDER_AD": SMART_AD_BUILDER_UPDATE_FIELDS,
        **AD_BUILDER_TYPE_FIELDS,
    }
    provided = {
        "title": title,
        "text": text,
        "titles": titles,
        "texts": texts,
        "href": href,
        "image_hash": image_hash,
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
    flag_for = {
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
    try:
        _reject_incompatible_flags(
            ad_type_norm, type_fields[ad_type_norm], provided, flag_for
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
        )
        if text:
            dynamic_text_ad["Text"] = text
        if dynamic_text_ad:
            ad_data["DynamicTextAd"] = dynamic_text_ad
    elif ad_type_norm == "TEXT_IMAGE_AD":
        text_image_ad = {}
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
        if image_hash:
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

    try:
        body = {"method": "update", "params": {"Ads": [ad_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = client_from_ctx(ctx, create_client)

        result = client.ads().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@ads.command()
@click.option("--id", "ad_id", required=True, type=int, help="Ad ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def delete(ctx, ad_id, dry_run):
    """Delete ad"""
    body = {"method": "delete", "params": {"SelectionCriteria": {"Ids": [ad_id]}}}

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = client.ads().post(data=body)
    format_output(result().extract(), "json", None)


@ads.command()
@click.option("--id", "ad_id", required=True, type=int, help="Ad ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def archive(ctx, ad_id, dry_run):
    """Archive ad"""
    body = {"method": "archive", "params": {"SelectionCriteria": {"Ids": [ad_id]}}}

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = client.ads().post(data=body)
    format_output(result().extract(), "json", None)


@ads.command()
@click.option("--id", "ad_id", required=True, type=int, help="Ad ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def unarchive(ctx, ad_id, dry_run):
    """Unarchive ad"""
    body = {
        "method": "unarchive",
        "params": {"SelectionCriteria": {"Ids": [ad_id]}},
    }

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = client.ads().post(data=body)
    format_output(result().extract(), "json", None)


@ads.command()
@click.option("--id", "ad_id", required=True, type=int, help="Ad ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def suspend(ctx, ad_id, dry_run):
    """Suspend ad"""
    body = {"method": "suspend", "params": {"SelectionCriteria": {"Ids": [ad_id]}}}

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = client.ads().post(data=body)
    format_output(result().extract(), "json", None)


@ads.command()
@click.option("--id", "ad_id", required=True, type=int, help="Ad ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def resume(ctx, ad_id, dry_run):
    """Resume ad"""
    body = {"method": "resume", "params": {"SelectionCriteria": {"Ids": [ad_id]}}}

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = client.ads().post(data=body)
    format_output(result().extract(), "json", None)


@ads.command()
@click.option("--id", "ad_id", required=True, type=int, help="Ad ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def moderate(ctx, ad_id, dry_run):
    """Moderate ad"""
    body = {"method": "moderate", "params": {"SelectionCriteria": {"Ids": [ad_id]}}}

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = client.ads().post(data=body)
    format_output(result().extract(), "json", None)
