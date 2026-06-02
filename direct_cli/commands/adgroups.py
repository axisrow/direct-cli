"""
Ad Groups commands
"""

from typing import Any, Optional

import click

from ..api import client_from_ctx, create_client
from ..i18n import t
from ..output import format_output, handle_api_errors
from ..utils import (
    add_criteria_csv,
    get_default_fields,
    parse_csv_strings,
    parse_ids,
)

_TRACKING_PARAMS_MAX_LENGTH = 1024
_SUPPORTED_ADGROUP_TYPES = (
    "TEXT_AD_GROUP",
    "DYNAMIC_TEXT_AD_GROUP",
    "DYNAMIC_TEXT_FEED_AD_GROUP",
    "CPM_BANNER_KEYWORDS_AD_GROUP",
    "CPM_BANNER_USER_PROFILE_AD_GROUP",
    "CPM_VIDEO_AD_GROUP",
    "SMART_AD_GROUP",
    "UNIFIED_AD_GROUP",
    "MOBILE_APP_AD_GROUP",
)
_NEGATIVE_KEYWORDS_UNSUPPORTED_ADGROUP_TYPES = {
    "CPM_BANNER_USER_PROFILE_AD_GROUP",
    "CPM_VIDEO_AD_GROUP",
}
_TARGET_DEVICE_TYPES = ("DEVICE_TYPE_MOBILE", "DEVICE_TYPE_TABLET")
_TARGET_CARRIERS = ("WI_FI_ONLY", "WI_FI_AND_CELLULAR")
_AUTOTARGETING_CATEGORIES = (
    "EXACT",
    "ALTERNATIVE",
    "COMPETITOR",
    "BROADER",
    "ACCESSORY",
)
_YES_NO_VALUES = ("YES", "NO")
_AUTOTARGETING_CATEGORY_HELP = (
    "DynamicTextAdGroup/DynamicTextFeedAdGroup.AutotargetingCategories item "
    "as CATEGORY=YES|NO. Categories: " + ", ".join(_AUTOTARGETING_CATEGORIES)
)
_AUTOTARGETING_SETTINGS_FLAGS = {
    "--autotargeting-settings-exact",
    "--autotargeting-settings-narrow",
    "--autotargeting-settings-alternative",
    "--autotargeting-settings-accessory",
    "--autotargeting-settings-broader",
    "--autotargeting-settings-without-brands",
    "--autotargeting-settings-with-advertiser-brand",
    "--autotargeting-settings-with-competitors-brand",
}
_DYNAMIC_TEXT_ADGROUP_FLAGS = {
    "--domain-url",
    "--autotargeting-category",
    *_AUTOTARGETING_SETTINGS_FLAGS,
}
_DYNAMIC_TEXT_FEED_ADGROUP_FLAGS = {
    "--feed-id",
    "--autotargeting-category",
}
_TEXT_ADGROUP_FEED_PARAMS_FLAGS = {
    "--feed-id",
    "--feed-category-ids",
}


@click.group()
def adgroups():
    """Manage ad groups"""


def _validate_tracking_params(tracking_params: Optional[str]) -> None:
    """Validate AdGroup*.TrackingParams documented API constraints."""
    if (
        tracking_params is not None
        and len(tracking_params) > _TRACKING_PARAMS_MAX_LENGTH
    ):
        raise click.UsageError(
            t(
                "--tracking-params must be at most {_TRACKING_PARAMS_MAX_LENGTH} characters"
            ).format(_TRACKING_PARAMS_MAX_LENGTH=_TRACKING_PARAMS_MAX_LENGTH)
        )


def _reject_unsupported_negative_keywords(
    group_type: str,
    *,
    negative_keywords: Optional[str],
    negative_keyword_shared_set_ids: Optional[str],
) -> None:
    """Reject negative keyword flags for ad group types that docs disallow."""
    if group_type not in _NEGATIVE_KEYWORDS_UNSUPPORTED_ADGROUP_TYPES:
        return

    unsupported_flags = []
    if negative_keywords is not None:
        unsupported_flags.append("--negative-keywords")
    if negative_keyword_shared_set_ids is not None:
        unsupported_flags.append("--negative-keyword-shared-set-ids")

    if unsupported_flags:
        raise click.UsageError(
            t("{arg0} is not compatible with --type {group_type}.").format(
                arg0=", ".join(unsupported_flags), group_type=group_type
            )
        )


def _parse_ids_option(value: Optional[str], option_name: str) -> Optional[list[int]]:
    """Parse comma-separated IDs and report bad input as a Click usage error."""
    try:
        return parse_ids(value)
    except ValueError as exc:
        raise click.UsageError(
            t("{option_name}: {exc}").format(option_name=option_name, exc=exc)
        ) from exc


def _normalize_enum_token(value: str) -> str:
    """Normalize enum-like CLI tokens to Yandex Direct uppercase constants."""
    return value.strip().upper().replace("-", "_")


def _parse_enum_value(
    value: Optional[str], option_name: str, allowed_values: tuple[str, ...]
) -> Optional[str]:
    """Parse a single enum-like token and report bad input as UsageError."""
    if not value:
        return None

    normalized = _normalize_enum_token(value)
    if not normalized:
        return None

    if normalized not in allowed_values:
        raise click.UsageError(
            t(
                "{option_name} has invalid value {value!r}; allowed values: {arg0}"
            ).format(
                option_name=option_name, value=value, arg0=", ".join(allowed_values)
            )
        )
    return normalized


def _parse_enum_csv(
    value: Optional[str], option_name: str, allowed_values: tuple[str, ...]
) -> Optional[list[str]]:
    """Parse comma-separated enum-like tokens and report bad input as UsageError."""
    parsed = parse_csv_strings(value)
    if not parsed:
        return None

    normalized_values = []
    for item in parsed:
        normalized = _normalize_enum_token(item)
        if normalized not in allowed_values:
            raise click.UsageError(
                t(
                    "{option_name} has invalid value {item!r}; allowed values: {arg0}"
                ).format(
                    option_name=option_name, item=item, arg0=", ".join(allowed_values)
                )
            )
        normalized_values.append(normalized)
    return normalized_values


def _build_mobile_app_adgroup(
    *,
    store_url: Optional[str] = None,
    target_device_types: Optional[str] = None,
    target_carrier: Optional[str] = None,
    target_operating_system_version: Optional[str] = None,
    require_all_fields: bool = False,
) -> Optional[dict[str, object]]:
    """Build the MobileAppAdGroup block shared by add/update."""
    parsed_device_types = _parse_enum_csv(
        target_device_types, "--target-device-types", _TARGET_DEVICE_TYPES
    )
    parsed_carrier = _parse_enum_value(
        target_carrier, "--target-carrier", _TARGET_CARRIERS
    )

    if require_all_fields:
        missing = []
        if not store_url:
            missing.append("--store-url")
        if not parsed_device_types:
            missing.append("--target-device-types")
        if not parsed_carrier:
            missing.append("--target-carrier")
        if not target_operating_system_version:
            missing.append("--target-operating-system-version")
        if missing:
            raise click.UsageError(
                t("{arg0} required for MOBILE_APP_AD_GROUP").format(
                    arg0=", ".join(missing)
                )
            )

    mobile_app_adgroup: dict[str, object] = {}
    if store_url:
        mobile_app_adgroup["StoreUrl"] = store_url
    if parsed_device_types:
        mobile_app_adgroup["TargetDeviceType"] = parsed_device_types
    if parsed_carrier:
        mobile_app_adgroup["TargetCarrier"] = parsed_carrier
    if target_operating_system_version:
        mobile_app_adgroup["TargetOperatingSystemVersion"] = (
            target_operating_system_version
        )

    return mobile_app_adgroup or None


def _parse_autotargeting_categories(
    raw_values: tuple[str, ...],
) -> Optional[list[dict[str, str]]]:
    """Parse DynamicTextAdGroup.AutotargetingCategories CLI items."""
    if not raw_values:
        return None

    allowed_categories = ", ".join(_AUTOTARGETING_CATEGORIES)
    items = []
    for raw_value in raw_values:
        category_raw, separator, value_raw = raw_value.strip().partition("=")
        if not separator:
            raise click.UsageError(
                t(
                    "--autotargeting-category expects CATEGORY=YES|NO "
                    "(for example EXACT=YES)"
                )
            )

        category = _normalize_enum_token(category_raw)
        value = _normalize_enum_token(value_raw)
        if category not in _AUTOTARGETING_CATEGORIES:
            raise click.UsageError(
                t(
                    "Invalid --autotargeting-category category {category_raw!r}; allowed: {allowed_categories}"
                ).format(
                    category_raw=category_raw, allowed_categories=allowed_categories
                )
            )
        if value not in {"YES", "NO"}:
            raise click.UsageError(
                t(
                    "Invalid --autotargeting-category value {value_raw!r}; expected YES or NO"
                ).format(value_raw=value_raw)
            )
        items.append({"Category": category, "Value": value})

    return items


def _build_autotargeting_settings(
    *,
    exact: Optional[str],
    narrow: Optional[str],
    alternative: Optional[str],
    accessory: Optional[str],
    broader: Optional[str],
    without_brands: Optional[str],
    with_advertiser_brand: Optional[str],
    with_competitors_brand: Optional[str],
) -> Optional[dict[str, dict[str, str]]]:
    """Build DynamicTextAdGroup.AutotargetingSettings from typed flags."""
    categories = {}
    for field_name, value in (
        ("Exact", exact),
        ("Narrow", narrow),
        ("Alternative", alternative),
        ("Accessory", accessory),
        ("Broader", broader),
    ):
        if value is not None:
            categories[field_name] = value.upper()

    brand_options = {}
    for field_name, value in (
        ("WithoutBrands", without_brands),
        ("WithAdvertiserBrand", with_advertiser_brand),
        ("WithCompetitorsBrand", with_competitors_brand),
    ):
        if value is not None:
            brand_options[field_name] = value.upper()

    settings = {}
    if categories:
        settings["Categories"] = categories
    if brand_options:
        settings["BrandOptions"] = brand_options

    return settings or None


def _reject_legacy_autotargeting_mix(
    settings: Optional[dict[str, dict[str, str]]],
    categories: tuple[str, ...],
) -> None:
    """Reject ambiguous legacy AutotargetingCategories + Settings payloads."""
    if settings is not None and categories:
        raise click.UsageError(
            t(
                "AutotargetingSettings flags cannot be combined with legacy "
                "--autotargeting-category flags."
            )
        )


def _build_dynamic_text_adgroup(
    *,
    domain_url: Optional[str],
    autotargeting_categories: tuple[str, ...],
    autotargeting_settings_exact: Optional[str],
    autotargeting_settings_narrow: Optional[str],
    autotargeting_settings_alternative: Optional[str],
    autotargeting_settings_accessory: Optional[str],
    autotargeting_settings_broader: Optional[str],
    autotargeting_settings_without_brands: Optional[str],
    autotargeting_settings_with_advertiser_brand: Optional[str],
    autotargeting_settings_with_competitors_brand: Optional[str],
    force_domain_url: bool = False,
) -> Optional[dict[str, object]]:
    """Build the DynamicTextAdGroup block shared by add/update."""
    parsed_categories = _parse_autotargeting_categories(autotargeting_categories)
    autotargeting_settings = _build_autotargeting_settings(
        exact=autotargeting_settings_exact,
        narrow=autotargeting_settings_narrow,
        alternative=autotargeting_settings_alternative,
        accessory=autotargeting_settings_accessory,
        broader=autotargeting_settings_broader,
        without_brands=autotargeting_settings_without_brands,
        with_advertiser_brand=autotargeting_settings_with_advertiser_brand,
        with_competitors_brand=autotargeting_settings_with_competitors_brand,
    )
    _reject_legacy_autotargeting_mix(
        settings=autotargeting_settings,
        categories=autotargeting_categories,
    )

    has_dynamic_fields = bool(domain_url or parsed_categories or autotargeting_settings)
    if (force_domain_url or has_dynamic_fields) and not domain_url:
        raise click.UsageError(t("--domain-url is required for DYNAMIC_TEXT_AD_GROUP"))

    dynamic_text_adgroup: dict[str, object] = {}
    if domain_url:
        dynamic_text_adgroup["DomainUrl"] = domain_url
    if parsed_categories:
        dynamic_text_adgroup["AutotargetingCategories"] = parsed_categories
    if autotargeting_settings:
        dynamic_text_adgroup["AutotargetingSettings"] = autotargeting_settings

    return dynamic_text_adgroup or None


def _build_dynamic_text_feed_adgroup(
    *,
    feed_id: Optional[int] = None,
    autotargeting_categories: tuple[str, ...],
    require_feed_id: bool = False,
) -> Optional[dict[str, object]]:
    """Build the DynamicTextFeedAdGroup block shared by add/update."""
    parsed_categories = _parse_autotargeting_categories(autotargeting_categories)

    if require_feed_id and feed_id is None:
        raise click.UsageError(
            t("--feed-id is required for DYNAMIC_TEXT_FEED_AD_GROUP")
        )

    dynamic_text_feed_adgroup: dict[str, object] = {}
    if feed_id is not None:
        dynamic_text_feed_adgroup["FeedId"] = feed_id
    if parsed_categories:
        dynamic_text_feed_adgroup["AutotargetingCategories"] = parsed_categories

    return dynamic_text_feed_adgroup or None


def _build_text_adgroup_feed_params(
    *,
    feed_id: Optional[int],
    feed_category_ids: Optional[str],
) -> Optional[dict[str, object]]:
    """Build TextAdGroupFeedParams from typed feed flags."""
    parsed_feed_category_ids = _parse_ids_option(
        feed_category_ids,
        "--feed-category-ids",
    )

    if feed_id is None and parsed_feed_category_ids:
        raise click.UsageError(
            t("--feed-id is required when --feed-category-ids is used")
        )
    if feed_id is None:
        return None

    feed_params: dict[str, object] = {"FeedId": feed_id}
    if parsed_feed_category_ids:
        feed_params["FeedCategoryIds"] = {"Items": parsed_feed_category_ids}
    return feed_params


def _reject_incompatible_flags(
    group_type: str,
    allowed_flags: set[str],
    provided_flags: dict[str, object],
) -> None:
    """Reject subtype-specific flags that do not apply to ``group_type``."""
    incompatible = [
        flag
        for flag, value in provided_flags.items()
        if value not in (None, ()) and flag not in allowed_flags
    ]
    if incompatible:
        raise click.UsageError(
            t("{arg0} is not compatible with --type {group_type}.").format(
                arg0=", ".join(sorted(incompatible)), group_type=group_type
            )
        )


def _provided_flags(provided_flags: dict[str, object]) -> list[str]:
    """Return CLI flags that were explicitly provided with meaningful values."""
    return sorted(
        flag for flag, value in provided_flags.items() if value not in (None, ())
    )


def _reject_mixed_update_subtype_flags(
    subtype_flags: dict[str, dict[str, object]],
) -> None:
    """Reject update payloads that would target multiple ad group subtypes."""
    provided_by_subtype = [
        (subtype_name, provided_flags)
        for subtype_name, flags in subtype_flags.items()
        if (provided_flags := _provided_flags(flags))
    ]
    if len(provided_by_subtype) > 1:
        first_subtype, first_flags = provided_by_subtype[0]
        second_subtype, second_flags = provided_by_subtype[1]
        raise click.UsageError(
            t(
                "{first_subtype} update flags ({arg0}) cannot be combined with {second_subtype} update flags ({arg1})."
            ).format(
                first_subtype=first_subtype,
                arg0=", ".join(first_flags),
                second_subtype=second_subtype,
                arg1=", ".join(second_flags),
            )
        )


def _uses_unified_adgroup_endpoint(body: dict[str, Any]) -> bool:
    """Return whether an adgroups add/update payload must use API v501."""
    params = body.get("params")
    if not isinstance(params, dict):
        return False

    adgroups_payload = params.get("AdGroups")
    if not isinstance(adgroups_payload, list):
        return False

    # Yandex docs require v501 for unified performance ad groups even though
    # the v5 WSDL declares UnifiedAdGroup. CLI add/update commands currently
    # build a single AdGroups item, so the nested block is enough to route.
    return any(
        isinstance(adgroup, dict) and "UnifiedAdGroup" in adgroup
        for adgroup in adgroups_payload
    )


def _post_adgroups(client: Any, body: dict[str, Any]) -> Any:
    """Post adgroups payloads to the documented API version."""
    if _uses_unified_adgroup_endpoint(body):
        return client.adgroups_v501().post(data=body)
    return client.adgroups().post(data=body)


@adgroups.command()
@click.option("--ids", help="Comma-separated ad group IDs")
@click.option("--campaign-ids", help="Comma-separated campaign IDs")
@click.option("--status", help="Filter by status")
@click.option("--statuses", help="Comma-separated statuses")
@click.option("--types", help="Filter by types")
@click.option("--tag-ids", help="Comma-separated tag IDs")
@click.option("--tags", help="Comma-separated tag names")
@click.option("--app-icon-statuses", help="Comma-separated app icon statuses")
@click.option("--serving-statuses", help="Comma-separated serving statuses")
@click.option(
    "--negative-keyword-shared-set-ids",
    help="Comma-separated negative keyword shared set IDs",
)
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.option(
    "--autotargeting-settings-brand-options-field-names",
    help=(
        "Comma-separated AutotargetingSettingsBrandOptionsFieldNames "
        "(e.g. WithoutBrands,WithAdvertiserBrand,WithCompetitorsBrand). "
        "Sent as separate top-level request parameter per the "
        "AdGroupsGetRequest WSDL."
    ),
)
@click.option(
    "--autotargeting-settings-categories-field-names",
    help=(
        "Comma-separated AutotargetingSettingsCategoriesFieldNames "
        "(e.g. Exact,Narrow,Alternative,Accessory,Broader). "
        "Sent as separate top-level request parameter per the "
        "AdGroupsGetRequest WSDL."
    ),
)
@click.option(
    "--dynamic-text-ad-group-field-names",
    help=(
        "Comma-separated DynamicTextAdGroupFieldNames "
        "(e.g. AutotargetingSettings,DomainUrl). "
        "Sent as separate top-level request parameter per the "
        "AdGroupsGetRequest WSDL."
    ),
)
@click.option(
    "--dynamic-text-feed-ad-group-field-names",
    help=(
        "Comma-separated DynamicTextFeedAdGroupFieldNames "
        "(e.g. Source,FeedId,SourceType). "
        "Sent as separate top-level request parameter per the "
        "AdGroupsGetRequest WSDL."
    ),
)
@click.option(
    "--mobile-app-ad-group-field-names",
    help=(
        "Comma-separated MobileAppAdGroupFieldNames "
        "(e.g. StoreUrl,TargetDeviceType,AppOperatingSystemType). "
        "Sent as separate top-level request parameter per the "
        "AdGroupsGetRequest WSDL."
    ),
)
@click.option(
    "--smart-ad-group-field-names",
    help=(
        "Comma-separated SmartAdGroupFieldNames "
        "(e.g. FeedId,AdTitleSource,AdBodySource). "
        "Sent as separate top-level request parameter per the "
        "AdGroupsGetRequest WSDL."
    ),
)
@click.option(
    "--text-ad-group-feed-params-field-names",
    help=(
        "Comma-separated TextAdGroupFeedParamsFieldNames "
        "(e.g. FeedId,FeedCategoryIds). "
        "Sent as separate top-level request parameter per the "
        "AdGroupsGetRequest WSDL."
    ),
)
@click.option(
    "--unified-ad-group-field-names",
    help=(
        "Comma-separated UnifiedAdGroupFieldNames (e.g. OfferRetargeting). "
        "Sent as separate top-level request parameter per the "
        "AdGroupsGetRequest WSDL."
    ),
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def get(
    ctx,
    ids,
    campaign_ids,
    status,
    statuses,
    types,
    tag_ids,
    tags,
    app_icon_statuses,
    serving_statuses,
    negative_keyword_shared_set_ids,
    limit,
    fetch_all,
    output_format,
    output,
    fields,
    autotargeting_settings_brand_options_field_names,
    autotargeting_settings_categories_field_names,
    dynamic_text_ad_group_field_names,
    dynamic_text_feed_ad_group_field_names,
    mobile_app_ad_group_field_names,
    smart_ad_group_field_names,
    text_ad_group_feed_params_field_names,
    unified_ad_group_field_names,
    dry_run,
):
    """Get ad groups"""
    if status and statuses:
        raise click.UsageError(t("--status and --statuses are mutually exclusive"))

    client = client_from_ctx(ctx, create_client)

    field_names = fields.split(",") if fields else get_default_fields("adgroups")

    raw_nested = (
        (
            "AutotargetingSettingsBrandOptionsFieldNames",
            autotargeting_settings_brand_options_field_names,
        ),
        (
            "AutotargetingSettingsCategoriesFieldNames",
            autotargeting_settings_categories_field_names,
        ),
        (
            "DynamicTextAdGroupFieldNames",
            dynamic_text_ad_group_field_names,
        ),
        (
            "DynamicTextFeedAdGroupFieldNames",
            dynamic_text_feed_ad_group_field_names,
        ),
        ("MobileAppAdGroupFieldNames", mobile_app_ad_group_field_names),
        ("SmartAdGroupFieldNames", smart_ad_group_field_names),
        (
            "TextAdGroupFeedParamsFieldNames",
            text_ad_group_feed_params_field_names,
        ),
        ("UnifiedAdGroupFieldNames", unified_ad_group_field_names),
    )
    parsed_nested = {}
    for wsdl_key, raw_value in raw_nested:
        parsed = parse_csv_strings(raw_value)
        if raw_value is not None and not parsed:
            raise click.UsageError(
                t("Provide a non-empty comma-separated {wsdl_key} list.").format(
                    wsdl_key=wsdl_key
                )
            )
        if parsed:
            parsed_nested[wsdl_key] = parsed

    criteria = {}
    if ids:
        criteria["Ids"] = parse_ids(ids)
    if campaign_ids:
        criteria["CampaignIds"] = parse_ids(campaign_ids)
    if status:
        criteria["Statuses"] = [status]
    add_criteria_csv(criteria, "Statuses", statuses, upper=True)
    if types:
        criteria["Types"] = types.split(",")
    add_criteria_csv(criteria, "TagIds", tag_ids, integers=True)
    add_criteria_csv(criteria, "Tags", tags)
    add_criteria_csv(criteria, "AppIconStatuses", app_icon_statuses, upper=True)
    add_criteria_csv(criteria, "ServingStatuses", serving_statuses, upper=True)
    add_criteria_csv(
        criteria,
        "NegativeKeywordSharedSetIds",
        negative_keyword_shared_set_ids,
        integers=True,
    )

    params = {"SelectionCriteria": criteria, "FieldNames": field_names}
    params.update(parsed_nested)

    if limit:
        params["Page"] = {"Limit": limit}

    body = {"method": "get", "params": params}

    if dry_run:
        format_output(body, "json", None)
        return

    result = client.adgroups().post(data=body)

    if fetch_all:
        items = []
        for item in result().iter_items():
            items.append(item)
        format_output(items, output_format, output)
    else:
        data = result().extract()
        format_output(data, output_format, output)


@adgroups.command()
@click.option("--name", required=True, help="Ad group name")
@click.option("--campaign-id", required=True, type=int, help="Campaign ID")
@click.option(
    "--type",
    "group_type",
    default="TEXT_AD_GROUP",
    help=(
        "Ad group type: TEXT_AD_GROUP, DYNAMIC_TEXT_AD_GROUP, "
        "DYNAMIC_TEXT_FEED_AD_GROUP, CPM_BANNER_KEYWORDS_AD_GROUP, "
        "CPM_BANNER_USER_PROFILE_AD_GROUP, CPM_VIDEO_AD_GROUP, "
        "SMART_AD_GROUP, UNIFIED_AD_GROUP, or MOBILE_APP_AD_GROUP"
    ),
)
@click.option(
    "--region-ids",
    required=True,
    help="Comma-separated region IDs (WSDL AdGroupAddItem.RegionIds minOccurs=1)",
)
@click.option("--domain-url", help="Dynamic text ad group domain URL")
@click.option(
    "--autotargeting-category",
    "autotargeting_categories",
    multiple=True,
    help=_AUTOTARGETING_CATEGORY_HELP,
)
@click.option(
    "--autotargeting-settings-exact",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="DynamicTextAdGroup.AutotargetingSettings.Categories.Exact value",
)
@click.option(
    "--autotargeting-settings-narrow",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="DynamicTextAdGroup.AutotargetingSettings.Categories.Narrow value",
)
@click.option(
    "--autotargeting-settings-alternative",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="DynamicTextAdGroup.AutotargetingSettings.Categories.Alternative value",
)
@click.option(
    "--autotargeting-settings-accessory",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="DynamicTextAdGroup.AutotargetingSettings.Categories.Accessory value",
)
@click.option(
    "--autotargeting-settings-broader",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="DynamicTextAdGroup.AutotargetingSettings.Categories.Broader value",
)
@click.option(
    "--autotargeting-settings-without-brands",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="DynamicTextAdGroup.AutotargetingSettings.BrandOptions.WithoutBrands value",
)
@click.option(
    "--autotargeting-settings-with-advertiser-brand",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help=(
        "DynamicTextAdGroup.AutotargetingSettings.BrandOptions."
        "WithAdvertiserBrand value"
    ),
)
@click.option(
    "--autotargeting-settings-with-competitors-brand",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help=(
        "DynamicTextAdGroup.AutotargetingSettings.BrandOptions."
        "WithCompetitorsBrand value"
    ),
)
@click.option(
    "--feed-id",
    type=int,
    help=(
        "TextAdGroupFeedParams.FeedId, SmartAdGroup.FeedId, or "
        "DynamicTextFeedAdGroup.FeedId; required for SMART_AD_GROUP and "
        "DYNAMIC_TEXT_FEED_AD_GROUP"
    ),
)
@click.option(
    "--feed-category-ids",
    help="Comma-separated TextAdGroupFeedParams.FeedCategoryIds item IDs",
)
@click.option("--ad-title-source", help="Smart ad group title source")
@click.option("--ad-body-source", help="Smart ad group body source")
@click.option(
    "--offer-retargeting",
    type=click.Choice(_YES_NO_VALUES, case_sensitive=False),
    help="UnifiedAdGroup.OfferRetargeting value: YES or NO",
)
@click.option(
    "--store-url",
    help="Mobile app ad group app store URL for MobileAppAdGroup.StoreUrl",
)
@click.option(
    "--target-device-types",
    help=(
        "Comma-separated MobileAppAdGroup.TargetDeviceType values: "
        "DEVICE_TYPE_MOBILE, DEVICE_TYPE_TABLET"
    ),
)
@click.option(
    "--target-carrier",
    help=("MobileAppAdGroup.TargetCarrier value: WI_FI_ONLY or WI_FI_AND_CELLULAR"),
)
@click.option(
    "--target-operating-system-version",
    help="Minimum OS version for MobileAppAdGroup.TargetOperatingSystemVersion",
)
@click.option(
    "--negative-keywords",
    help=(
        "Comma-separated ad-group negative keywords for NegativeKeywords.Items; "
        "not compatible with CPM user-profile or video groups"
    ),
)
@click.option(
    "--negative-keyword-shared-set-ids",
    help=(
        "Comma-separated negative keyword shared set IDs for "
        "NegativeKeywordSharedSetIds.Items; not compatible with CPM "
        "user-profile or video groups"
    ),
)
@click.option(
    "--tracking-params",
    "tracking_params",
    help=(
        "Tracking params query-string for AdGroupAddItem.TrackingParams "
        "(max 1024 chars)"
    ),
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def add(
    ctx,
    name,
    campaign_id,
    group_type,
    region_ids,
    domain_url,
    autotargeting_categories,
    autotargeting_settings_exact,
    autotargeting_settings_narrow,
    autotargeting_settings_alternative,
    autotargeting_settings_accessory,
    autotargeting_settings_broader,
    autotargeting_settings_without_brands,
    autotargeting_settings_with_advertiser_brand,
    autotargeting_settings_with_competitors_brand,
    feed_id,
    feed_category_ids,
    ad_title_source,
    ad_body_source,
    offer_retargeting,
    store_url,
    target_device_types,
    target_carrier,
    target_operating_system_version,
    negative_keywords,
    negative_keyword_shared_set_ids,
    tracking_params,
    dry_run,
):
    """Add new ad group"""
    _validate_tracking_params(tracking_params)

    group_type_norm = (group_type or "TEXT_AD_GROUP").upper().replace("-", "_")
    if group_type_norm not in _SUPPORTED_ADGROUP_TYPES:
        raise click.UsageError(
            t(
                "Invalid value for '--type': {group_type!r} is not one of {arg0}."
            ).format(
                group_type=group_type,
                arg0=", ".join(repr(value) for value in _SUPPORTED_ADGROUP_TYPES),
            )
        )
    allowed_flags_by_type = {
        "TEXT_AD_GROUP": _TEXT_ADGROUP_FEED_PARAMS_FLAGS,
        "DYNAMIC_TEXT_AD_GROUP": _DYNAMIC_TEXT_ADGROUP_FLAGS,
        "DYNAMIC_TEXT_FEED_AD_GROUP": _DYNAMIC_TEXT_FEED_ADGROUP_FLAGS,
        "CPM_BANNER_KEYWORDS_AD_GROUP": set(),
        "CPM_BANNER_USER_PROFILE_AD_GROUP": set(),
        "CPM_VIDEO_AD_GROUP": set(),
        "SMART_AD_GROUP": {"--feed-id", "--ad-title-source", "--ad-body-source"},
        "UNIFIED_AD_GROUP": {"--offer-retargeting"},
        "MOBILE_APP_AD_GROUP": {
            "--store-url",
            "--target-device-types",
            "--target-carrier",
            "--target-operating-system-version",
        },
    }
    _reject_incompatible_flags(
        group_type_norm,
        allowed_flags_by_type[group_type_norm],
        {
            "--domain-url": domain_url,
            "--autotargeting-category": autotargeting_categories,
            "--autotargeting-settings-exact": autotargeting_settings_exact,
            "--autotargeting-settings-narrow": autotargeting_settings_narrow,
            "--autotargeting-settings-alternative": (
                autotargeting_settings_alternative
            ),
            "--autotargeting-settings-accessory": (autotargeting_settings_accessory),
            "--autotargeting-settings-broader": autotargeting_settings_broader,
            "--autotargeting-settings-without-brands": (
                autotargeting_settings_without_brands
            ),
            "--autotargeting-settings-with-advertiser-brand": (
                autotargeting_settings_with_advertiser_brand
            ),
            "--autotargeting-settings-with-competitors-brand": (
                autotargeting_settings_with_competitors_brand
            ),
            "--feed-id": feed_id,
            "--feed-category-ids": feed_category_ids,
            "--ad-title-source": ad_title_source,
            "--ad-body-source": ad_body_source,
            "--offer-retargeting": offer_retargeting,
            "--store-url": store_url,
            "--target-device-types": target_device_types,
            "--target-carrier": target_carrier,
            "--target-operating-system-version": target_operating_system_version,
        },
    )
    _reject_unsupported_negative_keywords(
        group_type_norm,
        negative_keywords=negative_keywords,
        negative_keyword_shared_set_ids=negative_keyword_shared_set_ids,
    )

    adgroup_data = {"Name": name, "CampaignId": campaign_id}

    if region_ids:
        adgroup_data["RegionIds"] = _parse_ids_option(region_ids, "--region-ids")
    parsed_negative_keywords = parse_csv_strings(negative_keywords)
    if parsed_negative_keywords:
        adgroup_data["NegativeKeywords"] = {"Items": parsed_negative_keywords}
    parsed_negative_keyword_shared_set_ids = _parse_ids_option(
        negative_keyword_shared_set_ids,
        "--negative-keyword-shared-set-ids",
    )
    if parsed_negative_keyword_shared_set_ids:
        adgroup_data["NegativeKeywordSharedSetIds"] = {
            "Items": parsed_negative_keyword_shared_set_ids
        }
    if tracking_params:
        adgroup_data["TrackingParams"] = tracking_params
    if group_type_norm == "TEXT_AD_GROUP":
        text_adgroup_feed_params = _build_text_adgroup_feed_params(
            feed_id=feed_id,
            feed_category_ids=feed_category_ids,
        )
        if text_adgroup_feed_params:
            adgroup_data["TextAdGroupFeedParams"] = text_adgroup_feed_params
    elif group_type_norm == "DYNAMIC_TEXT_AD_GROUP":
        dynamic_text_adgroup = _build_dynamic_text_adgroup(
            domain_url=domain_url,
            autotargeting_categories=autotargeting_categories,
            autotargeting_settings_exact=autotargeting_settings_exact,
            autotargeting_settings_narrow=autotargeting_settings_narrow,
            autotargeting_settings_alternative=autotargeting_settings_alternative,
            autotargeting_settings_accessory=autotargeting_settings_accessory,
            autotargeting_settings_broader=autotargeting_settings_broader,
            autotargeting_settings_without_brands=(
                autotargeting_settings_without_brands
            ),
            autotargeting_settings_with_advertiser_brand=(
                autotargeting_settings_with_advertiser_brand
            ),
            autotargeting_settings_with_competitors_brand=(
                autotargeting_settings_with_competitors_brand
            ),
            force_domain_url=True,
        )
        if dynamic_text_adgroup:
            adgroup_data["DynamicTextAdGroup"] = dynamic_text_adgroup
    elif group_type_norm == "DYNAMIC_TEXT_FEED_AD_GROUP":
        dynamic_text_feed_adgroup = _build_dynamic_text_feed_adgroup(
            feed_id=feed_id,
            autotargeting_categories=autotargeting_categories,
            require_feed_id=True,
        )
        if dynamic_text_feed_adgroup:
            adgroup_data["DynamicTextFeedAdGroup"] = dynamic_text_feed_adgroup
    elif group_type_norm == "CPM_BANNER_KEYWORDS_AD_GROUP":
        adgroup_data["CpmBannerKeywordsAdGroup"] = {}
    elif group_type_norm == "CPM_BANNER_USER_PROFILE_AD_GROUP":
        adgroup_data["CpmBannerUserProfileAdGroup"] = {}
    elif group_type_norm == "CPM_VIDEO_AD_GROUP":
        adgroup_data["CpmVideoAdGroup"] = {}
    elif group_type_norm == "SMART_AD_GROUP":
        if feed_id is None:
            raise click.UsageError(t("--feed-id is required for SMART_AD_GROUP"))
        smart_ad_group = {"FeedId": feed_id}
        if ad_title_source:
            smart_ad_group["AdTitleSource"] = ad_title_source
        if ad_body_source:
            smart_ad_group["AdBodySource"] = ad_body_source
        adgroup_data["SmartAdGroup"] = smart_ad_group
    elif group_type_norm == "UNIFIED_AD_GROUP":
        if offer_retargeting is None:
            raise click.UsageError(
                t("--offer-retargeting is required for UNIFIED_AD_GROUP")
            )
        adgroup_data["UnifiedAdGroup"] = {"OfferRetargeting": offer_retargeting.upper()}
    elif group_type_norm == "MOBILE_APP_AD_GROUP":
        mobile_app_adgroup = _build_mobile_app_adgroup(
            store_url=store_url,
            target_device_types=target_device_types,
            target_carrier=target_carrier,
            target_operating_system_version=target_operating_system_version,
            require_all_fields=True,
        )
        if mobile_app_adgroup:
            adgroup_data["MobileAppAdGroup"] = mobile_app_adgroup

    body = {"method": "add", "params": {"AdGroups": [adgroup_data]}}

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = _post_adgroups(client, body)
    format_output(result().extract(), "json", None)


@adgroups.command()
@click.option("--id", "adgroup_id", required=True, type=int, help="Ad group ID")
@click.option("--name", help="New ad group name")
@click.option("--status", help="New status")
@click.option("--region-ids", help="Comma-separated region IDs")
@click.option(
    "--domain-url",
    help="DynamicTextAdGroup.DomainUrl; required for DynamicTextAdGroup updates",
)
@click.option(
    "--dynamic-feed",
    is_flag=True,
    help=("Build DynamicTextFeedAdGroup update block for --autotargeting-category"),
)
@click.option(
    "--negative-keywords",
    help="Comma-separated ad-group negative keywords for NegativeKeywords.Items",
)
@click.option(
    "--negative-keyword-shared-set-ids",
    help=(
        "Comma-separated negative keyword shared set IDs for "
        "NegativeKeywordSharedSetIds.Items"
    ),
)
@click.option(
    "--tracking-params",
    "tracking_params",
    help=(
        "Tracking params query-string for AdGroupUpdateItem.TrackingParams "
        "(max 1024 chars)"
    ),
)
@click.option(
    "--feed-id",
    type=int,
    help="TextAdGroupFeedParams.FeedId update value",
)
@click.option(
    "--feed-category-ids",
    help="Comma-separated TextAdGroupFeedParams.FeedCategoryIds item IDs",
)
@click.option("--ad-title-source", help="SmartAdGroup.AdTitleSource update value")
@click.option("--ad-body-source", help="SmartAdGroup.AdBodySource update value")
@click.option(
    "--offer-retargeting",
    type=click.Choice(_YES_NO_VALUES, case_sensitive=False),
    help="UnifiedAdGroup.OfferRetargeting update value: YES or NO",
)
@click.option(
    "--target-device-types",
    help=(
        "Comma-separated MobileAppAdGroup.TargetDeviceType values: "
        "DEVICE_TYPE_MOBILE, DEVICE_TYPE_TABLET"
    ),
)
@click.option(
    "--target-carrier",
    help=("MobileAppAdGroup.TargetCarrier value: WI_FI_ONLY or WI_FI_AND_CELLULAR"),
)
@click.option(
    "--target-operating-system-version",
    help="Minimum OS version for MobileAppAdGroup.TargetOperatingSystemVersion",
)
@click.option(
    "--autotargeting-category",
    "autotargeting_categories",
    multiple=True,
    help=_AUTOTARGETING_CATEGORY_HELP,
)
@click.option(
    "--autotargeting-settings-exact",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="DynamicTextAdGroup.AutotargetingSettings.Categories.Exact value",
)
@click.option(
    "--autotargeting-settings-narrow",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="DynamicTextAdGroup.AutotargetingSettings.Categories.Narrow value",
)
@click.option(
    "--autotargeting-settings-alternative",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="DynamicTextAdGroup.AutotargetingSettings.Categories.Alternative value",
)
@click.option(
    "--autotargeting-settings-accessory",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="DynamicTextAdGroup.AutotargetingSettings.Categories.Accessory value",
)
@click.option(
    "--autotargeting-settings-broader",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="DynamicTextAdGroup.AutotargetingSettings.Categories.Broader value",
)
@click.option(
    "--autotargeting-settings-without-brands",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="DynamicTextAdGroup.AutotargetingSettings.BrandOptions.WithoutBrands value",
)
@click.option(
    "--autotargeting-settings-with-advertiser-brand",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help=(
        "DynamicTextAdGroup.AutotargetingSettings.BrandOptions."
        "WithAdvertiserBrand value"
    ),
)
@click.option(
    "--autotargeting-settings-with-competitors-brand",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help=(
        "DynamicTextAdGroup.AutotargetingSettings.BrandOptions."
        "WithCompetitorsBrand value"
    ),
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def update(
    ctx,
    adgroup_id,
    name,
    status,
    region_ids,
    domain_url,
    dynamic_feed,
    negative_keywords,
    negative_keyword_shared_set_ids,
    tracking_params,
    feed_id,
    feed_category_ids,
    ad_title_source,
    ad_body_source,
    offer_retargeting,
    target_device_types,
    target_carrier,
    target_operating_system_version,
    autotargeting_categories,
    autotargeting_settings_exact,
    autotargeting_settings_narrow,
    autotargeting_settings_alternative,
    autotargeting_settings_accessory,
    autotargeting_settings_broader,
    autotargeting_settings_without_brands,
    autotargeting_settings_with_advertiser_brand,
    autotargeting_settings_with_competitors_brand,
    dry_run,
):
    """Update ad group"""
    _validate_tracking_params(tracking_params)
    autotargeting_settings_flags = {
        "--autotargeting-settings-exact": autotargeting_settings_exact,
        "--autotargeting-settings-narrow": autotargeting_settings_narrow,
        "--autotargeting-settings-alternative": autotargeting_settings_alternative,
        "--autotargeting-settings-accessory": autotargeting_settings_accessory,
        "--autotargeting-settings-broader": autotargeting_settings_broader,
        "--autotargeting-settings-without-brands": (
            autotargeting_settings_without_brands
        ),
        "--autotargeting-settings-with-advertiser-brand": (
            autotargeting_settings_with_advertiser_brand
        ),
        "--autotargeting-settings-with-competitors-brand": (
            autotargeting_settings_with_competitors_brand
        ),
    }
    dynamic_text_flags = {
        "--domain-url": domain_url,
        **autotargeting_settings_flags,
    }
    dynamic_feed_flags = {"--dynamic-feed": True if dynamic_feed else None}
    if dynamic_feed:
        dynamic_feed_flags["--autotargeting-category"] = autotargeting_categories
    else:
        dynamic_text_flags["--autotargeting-category"] = autotargeting_categories

    _reject_mixed_update_subtype_flags(
        {
            "DynamicTextAdGroup": dynamic_text_flags,
            "DynamicTextFeedAdGroup": dynamic_feed_flags,
            "MobileAppAdGroup": {
                "--target-device-types": target_device_types,
                "--target-carrier": target_carrier,
                "--target-operating-system-version": (target_operating_system_version),
            },
            "SmartAdGroup": {
                "--ad-title-source": ad_title_source,
                "--ad-body-source": ad_body_source,
            },
            "TextAdGroupFeedParams": {
                "--feed-id": feed_id,
                "--feed-category-ids": feed_category_ids,
            },
            "UnifiedAdGroup": {
                "--offer-retargeting": offer_retargeting,
            },
        }
    )

    adgroup_data = {"Id": adgroup_id}

    if name:
        adgroup_data["Name"] = name

    if status:
        adgroup_data["Status"] = status
    if region_ids:
        adgroup_data["RegionIds"] = _parse_ids_option(region_ids, "--region-ids")
    parsed_negative_keywords = parse_csv_strings(negative_keywords)
    if parsed_negative_keywords:
        adgroup_data["NegativeKeywords"] = {"Items": parsed_negative_keywords}
    parsed_negative_keyword_shared_set_ids = _parse_ids_option(
        negative_keyword_shared_set_ids, "--negative-keyword-shared-set-ids"
    )
    if parsed_negative_keyword_shared_set_ids:
        adgroup_data["NegativeKeywordSharedSetIds"] = {
            "Items": parsed_negative_keyword_shared_set_ids
        }
    if tracking_params:
        adgroup_data["TrackingParams"] = tracking_params
    if dynamic_feed:
        if not autotargeting_categories:
            raise click.UsageError(
                t("--dynamic-feed requires --autotargeting-category")
            )
        dynamic_text_feed_adgroup = _build_dynamic_text_feed_adgroup(
            autotargeting_categories=autotargeting_categories,
        )
        if dynamic_text_feed_adgroup:
            adgroup_data["DynamicTextFeedAdGroup"] = dynamic_text_feed_adgroup
    else:
        dynamic_text_adgroup = _build_dynamic_text_adgroup(
            domain_url=domain_url,
            autotargeting_categories=autotargeting_categories,
            autotargeting_settings_exact=autotargeting_settings_exact,
            autotargeting_settings_narrow=autotargeting_settings_narrow,
            autotargeting_settings_alternative=autotargeting_settings_alternative,
            autotargeting_settings_accessory=autotargeting_settings_accessory,
            autotargeting_settings_broader=autotargeting_settings_broader,
            autotargeting_settings_without_brands=(
                autotargeting_settings_without_brands
            ),
            autotargeting_settings_with_advertiser_brand=(
                autotargeting_settings_with_advertiser_brand
            ),
            autotargeting_settings_with_competitors_brand=(
                autotargeting_settings_with_competitors_brand
            ),
        )
        if dynamic_text_adgroup:
            adgroup_data["DynamicTextAdGroup"] = dynamic_text_adgroup
    mobile_app_adgroup = _build_mobile_app_adgroup(
        target_device_types=target_device_types,
        target_carrier=target_carrier,
        target_operating_system_version=target_operating_system_version,
    )
    if mobile_app_adgroup:
        adgroup_data["MobileAppAdGroup"] = mobile_app_adgroup
    text_adgroup_feed_params = _build_text_adgroup_feed_params(
        feed_id=feed_id,
        feed_category_ids=feed_category_ids,
    )
    if text_adgroup_feed_params:
        adgroup_data["TextAdGroupFeedParams"] = text_adgroup_feed_params
    smart_adgroup = {}
    if ad_title_source:
        smart_adgroup["AdTitleSource"] = ad_title_source
    if ad_body_source:
        smart_adgroup["AdBodySource"] = ad_body_source
    if smart_adgroup:
        adgroup_data["SmartAdGroup"] = smart_adgroup
    if offer_retargeting is not None:
        adgroup_data["UnifiedAdGroup"] = {"OfferRetargeting": offer_retargeting.upper()}

    # Reject empty-payload no-op (issue #198 H5).
    if len(adgroup_data) == 1:
        raise click.UsageError(
            t(
                "adgroups update requires at least one updatable field "
                "(--name, --status, --region-ids, --negative-keywords, "
                "--negative-keyword-shared-set-ids, --tracking-params, "
                "--domain-url, --dynamic-feed, --autotargeting-category, "
                "--autotargeting-settings-* flags, --target-device-types, "
                "--target-carrier, --target-operating-system-version, "
                "--feed-id, --feed-category-ids, --ad-title-source, "
                "--ad-body-source, or --offer-retargeting)."
            )
        )

    body = {"method": "update", "params": {"AdGroups": [adgroup_data]}}

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = _post_adgroups(client, body)
    format_output(result().extract(), "json", None)


@adgroups.command()
@click.option("--id", "adgroup_id", required=True, type=int, help="Ad group ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def delete(ctx, adgroup_id, dry_run):
    """Delete ad group"""
    body = {
        "method": "delete",
        "params": {"SelectionCriteria": {"Ids": [adgroup_id]}},
    }

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = client.adgroups().post(data=body)
    format_output(result().extract(), "json", None)
