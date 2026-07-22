"""Ads commands — the thin CLI router for the ``direct ads`` group (#603).

This module owns only the Click surface: the group, the ``get``/``add``/``update``
options and their request tails, and the lifecycle subcommands. Payload assembly
lives in the sibling modules — :mod:`.objects` (``build_ad_object`` /
``build_ad_update_object``), :mod:`.batch` (``--from-file`` / ``--ads-json`` rows)
and the per-subtype builders in :mod:`.text`, :mod:`.responsive`, :mod:`.shopping`,
:mod:`.mobile_app` and :mod:`.builder`.
"""

from typing import Any

import click

from ...api import client_from_ctx
from ... import api as _api
from ...i18n import t
from ...output import format_output, handle_api_errors
from .._execute import execute_request
from .._lifecycle import register_lifecycle_commands
from ...utils import (
    add_criteria_csv,
    build_common_params,
    enforce_criteria_array_limits,
    get_default_fields,
    MICRO_RUBLES,
    parse_csv_strings,
    parse_ids,
    parse_nested_field_names,
)
from .batch import _bulk_add_ads, _bulk_update_ads
from .objects import (
    _ADS_ADD_FLAG_FOR,
    _ADS_UPDATE_FLAG_FOR,
    build_ad_object,
    build_ad_update_object,
)

# Yandex Direct ads.get caps SelectionCriteria arrays at runtime (the WSDL
# declares them maxOccurs="unbounded"). Live measurement 2026-06-17 via sandbox:
# --campaign-ids ×11 → 4001 "Exceed the maximum number of IDs per array
# SelectionCriteria.CampaignIds"; --adgroup-ids ×10001 → 4001 ".AdGroupIds"
# (N=1000 accepted); --vcard-ids ×11 (with anchor --campaign-ids 1) → 4001
# ".VCardIds"; --sitelink-set-ids ×11 (with anchor) → 4001 ".SitelinkSetIds".
# Ids and AdExtensionIds accepted at N=10000.
ADS_GET_CRITERIA_LIMITS = {
    "CampaignIds": 10,
    "AdGroupIds": 1000,
    "VCardIds": 10,
    "SitelinkSetIds": 10,
}

# Re-export for API coverage script patchability. The script imports the
# ``ads`` package and patches ``module.create_client``; by making this module's
# ``create_client`` an alias to the API module's, the package can re-export it
# and the patch sees the same object that ``execute_request`` uses.
create_client = _api.create_client


@click.group()
def ads():
    """Manage ads"""


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
@handle_api_errors
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

    field_names = parse_csv_strings(fields) or get_default_fields("ads", "FieldNames")

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
    parsed_nested = parse_nested_field_names(raw_nested)
    parsed_nested.setdefault(
        "TextAdFieldNames", get_default_fields("ads", "TextAdFieldNames")
    )

    criteria: dict[str, Any] = {}
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

    enforce_criteria_array_limits(
        criteria, ADS_GET_CRITERIA_LIMITS, command_name="ads get"
    )

    if not criteria:
        raise click.UsageError(t("Provide at least one typed filter"))

    params = build_common_params(
        criteria=criteria, field_names=field_names, limit=limit
    )
    params.update(parsed_nested)

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


@ads.command()
@click.option(
    "--adgroup-id",
    type=click.IntRange(min=1),
    help=(
        "Ad group ID (required in single-item mode; "
        "batch default in --from-file mode)"
    ),
)
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
        "Ad image hash (TEXT_AD / TEXT_IMAGE_AD / MOBILE_APP_AD / "
        "DYNAMIC_TEXT_AD / MOBILE_APP_IMAGE_AD)"
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
    help=(
        "ShoppingAd/ListingAd.DefaultTexts value "
        "(required for SHOPPING_AD/LISTING_AD)"
    ),
)
@click.option(
    "--from-file",
    "from_file",
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to a JSONL file (one flag-form ad object per line) for batch add",
)
@click.option(
    "--ads-json",
    "ads_json",
    help="Inline JSON array of flag-form ad objects for batch add",
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
    from_file,
    ads_json,
    dry_run,
):
    """Add one or many ads.

    Single-item mode uses typed flags (--type, --title, ...). Batch mode reads
    flag-form rows from --from-file (JSONL, one object per line) or --ads-json
    (inline JSON array); each row is the same flag set keyed by the kebab flag
    name without the leading dashes (e.g. {"type":"TEXT_AD","title":"...",
    "text":"...","href":"...","adgroup-id":1}). --adgroup-id is the batch
    default and may be overridden per row.
    """
    flags_local = {
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

    modes_used = sum(1 for v in (from_file, ads_json) if v is not None)
    if modes_used > 1:
        raise click.UsageError(
            t(
                "Provide at most one of: --from-file or --ads-json \u2014 "
                "they are mutually exclusive."
            )
        )
    batch_mode = modes_used > 0

    mobile_source = ctx.get_parameter_source("mobile")
    mobile_explicit = (
        mobile_source != click.core.ParameterSource.DEFAULT if mobile_source else False
    )
    mobile_provided = mobile if mobile_explicit else None

    if batch_mode:
        batch_incompatible = {
            label: (mobile_provided if dest == "mobile" else flags_local.get(dest))
            for dest, label in _ADS_ADD_FLAG_FOR.items()
        }
        # --type carries a Click default ("TEXT_AD"); only count it as provided
        # when the operator actually passed it.
        type_source = ctx.get_parameter_source("ad_type")
        type_explicit = (
            type_source != click.core.ParameterSource.DEFAULT if type_source else False
        )
        if type_explicit:
            batch_incompatible["--type"] = ad_type
        unsupported = sorted(
            label
            for label, value in batch_incompatible.items()
            if value not in (None, ())
        )
        if unsupported:
            raise click.UsageError(
                t("{arg0} supported only with single-item mode").format(
                    arg0=", ".join(unsupported)
                )
            )
        _bulk_add_ads(
            ctx,
            adgroup_id=adgroup_id,
            from_file=from_file,
            ads_json=ads_json,
            dry_run=dry_run,
        )
        return

    if adgroup_id is None:
        raise click.UsageError(t("Missing option '--adgroup-id'."))

    ad_data = build_ad_object(
        adgroup_id=adgroup_id,
        ad_type=ad_type,
        mobile_provided=mobile_provided,
        flags=flags_local,
        flag_for=_ADS_ADD_FLAG_FOR,
    )

    body = {"method": "add", "params": {"Ads": [ad_data]}}

    execute_request(ctx, "ads", body, dry_run, create_client)


@ads.command()
@click.option(
    "--id",
    "ad_id",
    type=click.IntRange(min=1),
    help="Ad ID (required in single-item mode; per row in --from-file mode)",
)
@click.option(
    "--type",
    "ad_type",
    help=(
        "Ad subtype: TEXT_AD | TEXT_IMAGE_AD | MOBILE_APP_AD | "
        "DYNAMIC_TEXT_AD | MOBILE_APP_IMAGE_AD | RESPONSIVE_AD | "
        "SHOPPING_AD | LISTING_AD | SMART_AD_BUILDER_AD | TEXT_AD_BUILDER_AD | "
        "MOBILE_APP_AD_BUILDER_AD | MOBILE_APP_CPC_VIDEO_AD_BUILDER_AD | "
        "CPC_VIDEO_AD_BUILDER_AD | CPM_BANNER_AD_BUILDER_AD | "
        "CPM_VIDEO_AD_BUILDER_AD "
        "(required in single-item mode; per row in --from-file mode)"
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
    "--clear-image-hash",
    is_flag=True,
    help=(
        "Set AdImageHash to null to remove the image (TEXT_AD / DYNAMIC_TEXT_AD / "
        "MOBILE_APP_AD). Not available for TEXT_IMAGE_AD / MOBILE_APP_IMAGE_AD: "
        "their AdImageHash is not nillable and the API rejects null. "
        "Note: if the ad has a server-side carousel image, Yandex rejects the "
        "reset with Error 5005 (carousel images are not exposed by Ads.update "
        "and can only be removed in the Direct web interface); replace it with a "
        "different --image-hash instead."
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
@click.option(
    "--from-file",
    "from_file",
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to a JSONL file (one flag-form ad-update object per line) for batch update",
)
@click.option(
    "--ads-json",
    "ads_json",
    help="Inline JSON array of flag-form ad-update objects for batch update",
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
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
    clear_image_hash,
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
    from_file,
    ads_json,
    dry_run,
):
    """Update one or many ads.

    Single-item mode uses typed flags (--id, --type, ...). Batch mode reads
    flag-form rows from --from-file (JSONL, one object per line) or --ads-json
    (inline JSON array); each row is the same flag set keyed by the kebab flag
    name without the leading dashes (e.g. {"id":5,"type":"TEXT_AD",
    "title":"New"}). Each row carries its own "id".
    """
    if status:
        raise click.UsageError(
            t(
                "Use 'direct ads suspend/resume/archive/unarchive' to change status. "
                "The --status flag is not supported by WSDL AdUpdateItem."
            )
        )

    flags_local = {
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

    modes_used = sum(1 for v in (from_file, ads_json) if v is not None)
    if modes_used > 1:
        raise click.UsageError(
            t(
                "Provide at most one of: --from-file or --ads-json — "
                "they are mutually exclusive."
            )
        )
    batch_mode = modes_used > 0

    if batch_mode:
        batch_incompatible = {
            label: flags_local.get(dest) for dest, label in _ADS_UPDATE_FLAG_FOR.items()
        }
        # --type/--id have no Click default, so an absent flag is None; in batch
        # mode the operator passes them per row, not on the command line.
        if ad_type is not None:
            batch_incompatible["--type"] = ad_type
        if ad_id is not None:
            batch_incompatible["--id"] = ad_id
        unsupported = sorted(
            label
            for label, value in batch_incompatible.items()
            if value not in (None, ())
        )
        if unsupported:
            raise click.UsageError(
                t("{arg0} supported only with single-item mode").format(
                    arg0=", ".join(unsupported)
                )
            )
        _bulk_update_ads(
            ctx,
            from_file=from_file,
            ads_json=ads_json,
            dry_run=dry_run,
        )
        return

    if ad_id is None:
        raise click.UsageError(t("Missing option '--id'."))

    if ad_type is None:
        raise click.UsageError(t("Missing option '--type'."))

    if image_hash and clear_image_hash:
        raise click.UsageError(
            t("Use either --image-hash or --clear-image-hash, not both")
        )

    ad_data = build_ad_update_object(
        ad_id=ad_id,
        ad_type=ad_type,
        flags=flags_local,
        flag_for=_ADS_UPDATE_FLAG_FOR,
    )

    body = {"method": "update", "params": {"Ads": [ad_data]}}

    execute_request(ctx, "ads", body, dry_run, create_client)


register_lifecycle_commands(
    ads,
    "ad_id",
    "Ad ID",
    create_client,
    [
        ("delete", "Delete ad"),
        ("archive", "Archive ad"),
        ("unarchive", "Unarchive ad"),
        ("suspend", "Suspend ad"),
        ("resume", "Resume ad"),
        ("moderate", "Moderate ad"),
    ],
)
