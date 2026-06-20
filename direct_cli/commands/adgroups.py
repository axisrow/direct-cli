"""
Ad Groups commands
"""

from typing import Any, Optional

import click

from ..api import client_from_ctx, create_client
from ..i18n import t
from ..output import format_output, handle_api_errors
from . import _batch
from ._get import make_get_command
from ._lifecycle import make_lifecycle_command
from ..utils import (
    add_criteria_csv,
    parse_csv_strings,
    parse_ids,
)

from .._autotargeting import (
    AUTOTARGETING_CATEGORIES,
    build_autotargeting_settings,
    normalize_enum_token,
    parse_autotargeting_categories,
    reject_legacy_autotargeting_mix,
)
from .._flag_validation import reject_incompatible_flags

# Yandex Direct adgroups.get caps SelectionCriteria arrays at runtime (the WSDL
# declares them maxOccurs="unbounded"). Live measurement 2026-06-17 via sandbox:
# --campaign-ids ×11 → 4001 "Exceed the maximum number of IDs per array
# SelectionCriteria.CampaignIds"; --negative-keyword-shared-set-ids ×11 (with
# anchor --campaign-ids 1) → 4001 ".NegativeKeywordSharedSetIds". Ids and TagIds
# accepted at N=10000.
ADGROUPS_GET_CRITERIA_LIMITS = {"CampaignIds": 10, "NegativeKeywordSharedSetIds": 10}

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
_YES_NO_VALUES = ("YES", "NO")
_AUTOTARGETING_CATEGORY_HELP = (
    "DynamicTextAdGroup/DynamicTextFeedAdGroup.AutotargetingCategories item "
    "as CATEGORY=YES|NO. Categories: " + ", ".join(AUTOTARGETING_CATEGORIES)
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


def _require_nonempty_ids_option(
    value: Optional[str], option_name: str
) -> Optional[list[int]]:
    """Parse CSV IDs; reject an explicitly-provided empty/whitespace value.

    ``None`` means the option was omitted -> return ``None`` (the caller decides
    whether the field is required). A provided-but-empty string (``""``,
    whitespace, or bare ``","``) is a user error, not an omission: silently
    dropping it would build a body without the field (issue #570) -- for
    ``RegionIds`` that strips a WSDL ``minOccurs=1`` field. Raise ``UsageError``
    instead so the mistake surfaces locally rather than at the live API.
    """
    if value is None:
        return None
    # An all-blank value ("", "   ", ",", ", ,") carries no real ID. Left to
    # _parse_ids_option it would either vanish ("" -> parse_ids None) or report a
    # confusing "Invalid ID: ''" (int("") on a blank segment). Collapse every
    # all-blank form into one clear empty-value error instead.
    if not any(part.strip() for part in value.split(",")):
        raise click.UsageError(
            t("{option_name} must not be empty.").format(option_name=option_name)
        )
    return _parse_ids_option(value, option_name)  # reuses bad-int UsageError


def _parse_enum_value(
    value: Optional[str], option_name: str, allowed_values: tuple[str, ...]
) -> Optional[str]:
    """Parse a single enum-like token and report bad input as UsageError."""
    if not value:
        return None

    normalized = normalize_enum_token(value)
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
        normalized = normalize_enum_token(item)
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
    parsed_categories = parse_autotargeting_categories(autotargeting_categories)
    autotargeting_settings = build_autotargeting_settings(
        exact=autotargeting_settings_exact,
        narrow=autotargeting_settings_narrow,
        alternative=autotargeting_settings_alternative,
        accessory=autotargeting_settings_accessory,
        broader=autotargeting_settings_broader,
        without_brands=autotargeting_settings_without_brands,
        with_advertiser_brand=autotargeting_settings_with_advertiser_brand,
        with_competitors_brand=autotargeting_settings_with_competitors_brand,
    )
    reject_legacy_autotargeting_mix(
        autotargeting_settings,
        legacy_candidates=[
            ("--autotargeting-category", bool(autotargeting_categories)),
        ],
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
    parsed_categories = parse_autotargeting_categories(autotargeting_categories)

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
    parsed_feed_category_ids = _require_nonempty_ids_option(
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


def _provided_flags(provided_flags: dict[str, object]) -> list[str]:
    """Return CLI flags that were explicitly provided with meaningful values."""
    return sorted(
        flag for flag, value in provided_flags.items() if value not in (None, ())
    )


def _reject_mixed_update_subtype_flags(
    subtype_flags: dict[str, dict[str, Any]],
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
    # the v5 WSDL declares UnifiedAdGroup. This routes the WHOLE body to v501
    # when any item is unified; batch `adgroups add` therefore refuses to mix
    # unified and non-unified groups in one run (see _bulk_add_adgroups) so a
    # mixed body never reaches the wrong endpoint.
    return any(
        isinstance(adgroup, dict) and "UnifiedAdGroup" in adgroup
        for adgroup in adgroups_payload
    )


def _post_adgroups(client: Any, body: dict[str, Any]) -> Any:
    """Post adgroups payloads to the documented API version."""
    if _uses_unified_adgroup_endpoint(body):
        return client.adgroups_v501().post(data=body)
    return client.adgroups().post(data=body)


def _adgroups_get_criteria(
    ids=None,
    campaign_ids=None,
    status=None,
    statuses=None,
    types=None,
    tag_ids=None,
    tags=None,
    app_icon_statuses=None,
    serving_statuses=None,
    negative_keyword_shared_set_ids=None,
    **_,
):
    """SelectionCriteria for ``adgroups get``: optional Ids/CampaignIds, a
    singular ``--status`` or upper-cased ``--statuses`` (mutually exclusive),
    upper-cased Types/AppIconStatuses/ServingStatuses, plain Tags, and integer
    TagIds/NegativeKeywordSharedSetIds."""
    if status and statuses:
        raise click.UsageError(t("--status and --statuses are mutually exclusive"))
    criteria = {}
    if ids:
        criteria["Ids"] = parse_ids(ids)
    if campaign_ids:
        criteria["CampaignIds"] = parse_ids(campaign_ids)
    if status:
        criteria["Statuses"] = [status]
    add_criteria_csv(criteria, "Statuses", statuses, upper=True)
    add_criteria_csv(criteria, "Types", types, upper=True)
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
    return criteria


get = make_get_command(
    adgroups,
    create_client,
    default_fields_key="adgroups",
    help_text="Get ad groups",
    ids_help="Comma-separated ad group IDs",
    extra_options=(
        click.option("--campaign-ids", help="Comma-separated campaign IDs"),
        click.option("--status", help="Filter by status"),
        click.option("--statuses", help="Comma-separated statuses"),
        click.option("--types", help="Filter by types"),
        click.option("--tag-ids", help="Comma-separated tag IDs"),
        click.option("--tags", help="Comma-separated tag names"),
        click.option("--app-icon-statuses", help="Comma-separated app icon statuses"),
        click.option("--serving-statuses", help="Comma-separated serving statuses"),
        click.option(
            "--negative-keyword-shared-set-ids",
            help="Comma-separated negative keyword shared set IDs",
        ),
    ),
    criteria_builder=_adgroups_get_criteria,
    criteria_limits=ADGROUPS_GET_CRITERIA_LIMITS,
    require_criteria_message="Provide at least one typed filter",
    nested_field_options=(
        (
            "--autotargeting-settings-brand-options-field-names",
            "AutotargetingSettingsBrandOptionsFieldNames",
            "Comma-separated AutotargetingSettingsBrandOptionsFieldNames "
            "(e.g. WithoutBrands,WithAdvertiserBrand,WithCompetitorsBrand). "
            "Sent as separate top-level request parameter per the "
            "AdGroupsGetRequest WSDL.",
        ),
        (
            "--autotargeting-settings-categories-field-names",
            "AutotargetingSettingsCategoriesFieldNames",
            "Comma-separated AutotargetingSettingsCategoriesFieldNames "
            "(e.g. Exact,Narrow,Alternative,Accessory,Broader). "
            "Sent as separate top-level request parameter per the "
            "AdGroupsGetRequest WSDL.",
        ),
        (
            "--dynamic-text-ad-group-field-names",
            "DynamicTextAdGroupFieldNames",
            "Comma-separated DynamicTextAdGroupFieldNames "
            "(e.g. AutotargetingSettings,DomainUrl). "
            "Sent as separate top-level request parameter per the "
            "AdGroupsGetRequest WSDL.",
        ),
        (
            "--dynamic-text-feed-ad-group-field-names",
            "DynamicTextFeedAdGroupFieldNames",
            "Comma-separated DynamicTextFeedAdGroupFieldNames "
            "(e.g. Source,FeedId,SourceType). "
            "Sent as separate top-level request parameter per the "
            "AdGroupsGetRequest WSDL.",
        ),
        (
            "--mobile-app-ad-group-field-names",
            "MobileAppAdGroupFieldNames",
            "Comma-separated MobileAppAdGroupFieldNames "
            "(e.g. StoreUrl,TargetDeviceType,AppOperatingSystemType). "
            "Sent as separate top-level request parameter per the "
            "AdGroupsGetRequest WSDL.",
        ),
        (
            "--smart-ad-group-field-names",
            "SmartAdGroupFieldNames",
            "Comma-separated SmartAdGroupFieldNames "
            "(e.g. FeedId,AdTitleSource,AdBodySource). "
            "Sent as separate top-level request parameter per the "
            "AdGroupsGetRequest WSDL.",
        ),
        (
            "--text-ad-group-feed-params-field-names",
            "TextAdGroupFeedParamsFieldNames",
            "Comma-separated TextAdGroupFeedParamsFieldNames "
            "(e.g. FeedId,FeedCategoryIds). "
            "Sent as separate top-level request parameter per the "
            "AdGroupsGetRequest WSDL.",
        ),
        (
            "--unified-ad-group-field-names",
            "UnifiedAdGroupFieldNames",
            "Comma-separated UnifiedAdGroupFieldNames (e.g. OfferRetargeting). "
            "Sent as separate top-level request parameter per the "
            "AdGroupsGetRequest WSDL.",
        ),
    ),
)


# dest -> "--flag" map for the `adgroups add` flag set. Hoisted to module level
# so build_adgroup_object and the batch normalizer share one source of truth.
_ADGROUPS_ADD_FLAG_FOR = {
    "region_ids": "--region-ids",
    "domain_url": "--domain-url",
    "autotargeting_categories": "--autotargeting-category",
    "autotargeting_settings_exact": "--autotargeting-settings-exact",
    "autotargeting_settings_narrow": "--autotargeting-settings-narrow",
    "autotargeting_settings_alternative": "--autotargeting-settings-alternative",
    "autotargeting_settings_accessory": "--autotargeting-settings-accessory",
    "autotargeting_settings_broader": "--autotargeting-settings-broader",
    "autotargeting_settings_without_brands": "--autotargeting-settings-without-brands",
    "autotargeting_settings_with_advertiser_brand": (
        "--autotargeting-settings-with-advertiser-brand"
    ),
    "autotargeting_settings_with_competitors_brand": (
        "--autotargeting-settings-with-competitors-brand"
    ),
    "feed_id": "--feed-id",
    "feed_category_ids": "--feed-category-ids",
    "ad_title_source": "--ad-title-source",
    "ad_body_source": "--ad-body-source",
    "offer_retargeting": "--offer-retargeting",
    "store_url": "--store-url",
    "target_device_types": "--target-device-types",
    "target_carrier": "--target-carrier",
    "target_operating_system_version": "--target-operating-system-version",
    "negative_keywords": "--negative-keywords",
    "negative_keyword_shared_set_ids": "--negative-keyword-shared-set-ids",
    "tracking_params": "--tracking-params",
}


def build_adgroup_object(*, campaign_id, name, group_type, flags):
    """Build a single ``AdGroups`` add item dict from flag values (issue #564).

    Pure (no ``ctx``, no I/O): performs ``--type`` validation, the
    incompatible-flag guard, the negative-keyword compatibility check, and the
    per-subtype assembly, returning ``{"Name": ..., "CampaignId": ..., ...}``.
    Both the single-flag ``adgroups add`` command and the ``--from-file`` batch
    normalizer call it so they emit byte-identical objects.

    ``flags`` is keyed by the command's dest var names (``region_ids``,
    ``domain_url``, ...); missing keys default to ``None`` (``multiple=True``
    flags default to ``()``).
    """
    # Unpack flags into locals so the dispatch body below is byte-identical to
    # the historical inline command body.
    region_ids = flags.get("region_ids")
    domain_url = flags.get("domain_url")
    autotargeting_categories = flags.get("autotargeting_categories") or ()
    autotargeting_settings_exact = flags.get("autotargeting_settings_exact")
    autotargeting_settings_narrow = flags.get("autotargeting_settings_narrow")
    autotargeting_settings_alternative = flags.get("autotargeting_settings_alternative")
    autotargeting_settings_accessory = flags.get("autotargeting_settings_accessory")
    autotargeting_settings_broader = flags.get("autotargeting_settings_broader")
    autotargeting_settings_without_brands = flags.get(
        "autotargeting_settings_without_brands"
    )
    autotargeting_settings_with_advertiser_brand = flags.get(
        "autotargeting_settings_with_advertiser_brand"
    )
    autotargeting_settings_with_competitors_brand = flags.get(
        "autotargeting_settings_with_competitors_brand"
    )
    feed_id = flags.get("feed_id")
    feed_category_ids = flags.get("feed_category_ids")
    ad_title_source = flags.get("ad_title_source")
    ad_body_source = flags.get("ad_body_source")
    offer_retargeting = flags.get("offer_retargeting")
    store_url = flags.get("store_url")
    target_device_types = flags.get("target_device_types")
    target_carrier = flags.get("target_carrier")
    target_operating_system_version = flags.get("target_operating_system_version")
    negative_keywords = flags.get("negative_keywords")
    negative_keyword_shared_set_ids = flags.get("negative_keyword_shared_set_ids")
    tracking_params = flags.get("tracking_params")

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
    reject_incompatible_flags(
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
        message="{arg0} is not compatible with --type {group_type}.",
        type_value=group_type_norm,
        type_field="group_type",
    )
    _reject_unsupported_negative_keywords(
        group_type_norm,
        negative_keywords=negative_keywords,
        negative_keyword_shared_set_ids=negative_keyword_shared_set_ids,
    )

    adgroup_data = {"Name": name, "CampaignId": campaign_id}

    parsed_region_ids = _require_nonempty_ids_option(region_ids, "--region-ids")
    if parsed_region_ids is not None:
        adgroup_data["RegionIds"] = parsed_region_ids
    parsed_negative_keywords = parse_csv_strings(negative_keywords)
    if parsed_negative_keywords:
        adgroup_data["NegativeKeywords"] = {"Items": parsed_negative_keywords}
    parsed_negative_keyword_shared_set_ids = _require_nonempty_ids_option(
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

    return adgroup_data


# Documented per-call limit for adgroups.add is 1000 (Yandex docs, adgroups/add
# page); the WSDL declares the AdGroups array unbounded. ADGROUPS_ADD_MAX_BATCH
# is a conservative CHUNK SIZE (not the ceiling): a partial failure rolls back
# at most this many ad groups.
ADGROUPS_ADD_MAX_BATCH = 100

# Batch row keys are the kebab flag names without the leading "--" plus "name",
# "campaign-id", and "type"; map them to build_adgroup_object's dest names.
_ADGROUPS_ROW_KEY_TO_DEST = {
    label[2:]: dest for dest, label in _ADGROUPS_ADD_FLAG_FOR.items()
}
_ADGROUPS_ROW_ALLOWED_KEYS = frozenset(
    {"name", "campaign-id", "type", *_ADGROUPS_ROW_KEY_TO_DEST}
)
# Repeatable flags accept a JSON list of the existing micro-format strings; keep
# in sync with the `multiple=True` add options (--autotargeting-category).
_ADGROUPS_ROW_MULTI_KEYS = {"autotargeting-category"}


def _adgroups_add_param_types():
    """Map each ``adgroups add`` row key (kebab, no ``--``) to its Click ParamType.

    Built lazily from the registered command so a batch row is coerced through
    the *exact same* type as the single-flag path (issue #564): e.g.
    ``--campaign-id`` (IntRange(min=1)) or ``--feed-id`` (int) gets the identical
    conversion/validation, so batch and single produce byte-identical payloads
    instead of forwarding raw JSON. Boolean flags are excluded.
    """
    types = {}
    for param in add.params:
        if not isinstance(param, click.Option):
            continue
        key = param.opts[0].lstrip("-")
        # click.STRING is the no-op default; only typed options need coercion.
        # Inert keys that aren't row fields (--dry-run, --from-file) still land
        # here but are unreachable: _ADGROUPS_ROW_ALLOWED_KEYS rejects them
        # before coercion. Mirrors ads `_ads_add_param_types`.
        if param.type is not click.STRING:
            types[key] = param.type
    return types


_ADGROUPS_ROW_PARAM_TYPES = None


def _coerce_adgroup_row_field(key, value, row_index):
    """Coerce one scalar batch-row value to its single-flag form (issue #564).

    Mirrors ``ads`` ``_coerce_ad_row_field``: rejects JSON arrays/objects/``null``
    for any scalar field, stringifies JSON int/float/bool scalars, then runs
    typed fields through their single-flag Click type so batch and single emit
    byte-identical payloads (``"campaign-id": 1.9`` is rejected, not truncated;
    ``"campaign-id": null`` / ``[1]`` raise a clear ``Ad group row N field``
    error instead of an uncaught ``TypeError``).
    """
    global _ADGROUPS_ROW_PARAM_TYPES
    if _ADGROUPS_ROW_PARAM_TYPES is None:
        _ADGROUPS_ROW_PARAM_TYPES = _adgroups_add_param_types()
    param_type = _ADGROUPS_ROW_PARAM_TYPES.get(key)

    if value is None or isinstance(value, (list, dict)):
        raise click.UsageError(
            t(
                "Ad group row {row_index} field {key!r}: expected a scalar, "
                "got {arg0}"
            ).format(row_index=row_index, key=key, arg0=type(value).__name__)
        )

    token = str(value)

    if param_type is None:
        return token

    if isinstance(value, bool):
        raise click.UsageError(
            t(
                "Ad group row {row_index} field {key!r}: expected {arg0}, got bool"
            ).format(row_index=row_index, key=key, arg0=param_type.name)
        )
    try:
        return param_type.convert(token, None, None)
    except click.exceptions.BadParameter as exc:
        raise click.UsageError(
            t("Ad group row {row_index} field {key!r}: {arg0}").format(
                row_index=row_index, key=key, arg0=exc.format_message()
            )
        )


def _normalize_adgroup_row(row, row_index, default_campaign_id):
    """Translate one flag-form batch row into a built ad-group object.

    The row keys are kebab flag names without "--" plus ``name``, ``campaign-id``
    (or the batch default), and ``type``. Each typed field is coerced through its
    single-flag Click type so batch and single emit byte-identical payloads.
    Unknown keys are rejected; ``build_adgroup_object`` does the subtype
    validation, its UsageError re-raised under an ``Ad group row N`` prefix.
    """
    if not isinstance(row, dict):
        raise click.UsageError(
            t("Ad group row {row_index}: expected JSON object, got {arg0}").format(
                row_index=row_index, arg0=type(row).__name__
            )
        )

    unknown = sorted(set(row) - _ADGROUPS_ROW_ALLOWED_KEYS)
    if unknown:
        raise click.UsageError(
            t(
                "Unknown field {arg0!r} in ad group row {row_index}; allowed: {allowed}"
            ).format(
                arg0=unknown[0],
                row_index=row_index,
                allowed=", ".join(sorted(_ADGROUPS_ROW_ALLOWED_KEYS)),
            )
        )

    if "campaign-id" in row:
        campaign_id = _coerce_adgroup_row_field(
            "campaign-id", row["campaign-id"], row_index
        )
    else:
        campaign_id = default_campaign_id
    if campaign_id is None:
        raise click.UsageError(
            t(
                "Ad group row {row_index}: missing 'campaign-id' and no default "
                "--campaign-id provided"
            ).format(row_index=row_index)
        )

    if "name" not in row:
        raise click.UsageError(
            t("Ad group row {row_index}: missing required 'name'").format(
                row_index=row_index
            )
        )
    name = _coerce_adgroup_row_field("name", row["name"], row_index)

    # RegionIds is WSDL minOccurs=1; the single command requires --region-ids,
    # so require it per row too — otherwise a batch row would build a body
    # missing a required field and send it to the live API.
    if "region-ids" not in row:
        raise click.UsageError(
            t("Ad group row {row_index}: missing required 'region-ids'").format(
                row_index=row_index
            )
        )

    group_type = row.get("type")

    flags = {}
    for key, dest in _ADGROUPS_ROW_KEY_TO_DEST.items():
        if key not in row:
            continue
        value = row[key]
        if key in _ADGROUPS_ROW_MULTI_KEYS:
            # A repeatable flag (--autotargeting-category) is a JSON list of the
            # existing micro-format strings; reject anything else with row/field
            # context instead of crashing downstream.
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                raise click.UsageError(
                    t(
                        "Ad group row {row_index} field {key!r}: expected a JSON "
                        "array of strings"
                    ).format(row_index=row_index, key=key)
                )
            value = tuple(value)
        else:
            value = _coerce_adgroup_row_field(key, value, row_index)
        flags[dest] = value

    try:
        return build_adgroup_object(
            campaign_id=campaign_id,
            name=name,
            group_type=group_type,
            flags=flags,
        )
    except click.UsageError as exc:
        raise click.UsageError(
            t("Ad group row {row_index}: {arg0}").format(
                row_index=row_index, arg0=exc.format_message()
            )
        )


def _bulk_add_adgroups(ctx, *, campaign_id, from_file, adgroups_json, dry_run):
    if from_file is not None:
        raw_rows = _batch.load_jsonl_rows(from_file)
    else:
        raw_rows = _batch.load_inline_rows(
            adgroups_json or "",
            invalid_json_key="--adgroups-json: invalid JSON: {arg0}",
            not_array_key="--adgroups-json must be a JSON array of ad group objects",
        )

    if not raw_rows:
        raise click.UsageError(t("Input contains no ad group rows."))

    items = [
        _normalize_adgroup_row(row, idx, campaign_id)
        for idx, row in enumerate(raw_rows, start=1)
    ]

    # _post_adgroups routes the WHOLE body to API v501 when ANY ad group in it
    # is a UnifiedAdGroup (unified performance groups require v501). A chunk that
    # mixes unified and non-unified groups would route the non-unified ones to
    # v501 too, so refuse the mix up front rather than send to the wrong endpoint
    # (the single-item path never built a multi-item body, so this is new with
    # batch mode). Same philosophy as _reject_mixed_update_subtype_flags.
    has_unified = any("UnifiedAdGroup" in item for item in items)
    has_non_unified = any("UnifiedAdGroup" not in item for item in items)
    if has_unified and has_non_unified:
        raise click.UsageError(
            t(
                "A batch may not mix UNIFIED_AD_GROUP with other ad group types "
                "(unified groups use a different API endpoint). Split them into "
                "separate --from-file runs."
            )
        )

    _batch.send_batch(
        ctx,
        resource="adgroups",
        method="add",
        payload_key="AdGroups",
        items=items,
        max_batch=ADGROUPS_ADD_MAX_BATCH,
        create_client=create_client,
        dry_run=dry_run,
        noun="ad groups",
        post=_post_adgroups,
    )


@adgroups.command()
@click.option("--name", help="Ad group name (required in single-item mode)")
@click.option(
    "--campaign-id",
    type=click.IntRange(min=1),
    help="Campaign ID (required in single-item mode; batch default in --from-file mode)",
)
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
    help=(
        "Comma-separated region IDs (WSDL AdGroupAddItem.RegionIds minOccurs=1; "
        "required in single-item mode, per row in --from-file mode)"
    ),
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
@click.option(
    "--from-file",
    "from_file",
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to a JSONL file (one flag-form ad-group object per line) for batch add",
)
@click.option(
    "--adgroups-json",
    "adgroups_json",
    help="Inline JSON array of flag-form ad-group objects for batch add",
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
    from_file,
    adgroups_json,
    dry_run,
):
    """Add one or many ad groups.

    Single-item mode uses typed flags (--name, --campaign-id, --type, ...).
    Batch mode reads flag-form rows from --from-file (JSONL, one object per line)
    or --adgroups-json (inline JSON array); each row is the same flag set keyed
    by the kebab flag name without the leading dashes (e.g.
    {"name":"G","campaign-id":12,"region-ids":"225","type":"TEXT_AD_GROUP"}).
    --campaign-id is the batch default and may be overridden per row.
    """
    flags_local = {
        "region_ids": region_ids,
        "domain_url": domain_url,
        "autotargeting_categories": autotargeting_categories,
        "autotargeting_settings_exact": autotargeting_settings_exact,
        "autotargeting_settings_narrow": autotargeting_settings_narrow,
        "autotargeting_settings_alternative": autotargeting_settings_alternative,
        "autotargeting_settings_accessory": autotargeting_settings_accessory,
        "autotargeting_settings_broader": autotargeting_settings_broader,
        "autotargeting_settings_without_brands": autotargeting_settings_without_brands,
        "autotargeting_settings_with_advertiser_brand": (
            autotargeting_settings_with_advertiser_brand
        ),
        "autotargeting_settings_with_competitors_brand": (
            autotargeting_settings_with_competitors_brand
        ),
        "feed_id": feed_id,
        "feed_category_ids": feed_category_ids,
        "ad_title_source": ad_title_source,
        "ad_body_source": ad_body_source,
        "offer_retargeting": offer_retargeting,
        "store_url": store_url,
        "target_device_types": target_device_types,
        "target_carrier": target_carrier,
        "target_operating_system_version": target_operating_system_version,
        "negative_keywords": negative_keywords,
        "negative_keyword_shared_set_ids": negative_keyword_shared_set_ids,
        "tracking_params": tracking_params,
    }

    modes_used = sum(1 for v in (from_file, adgroups_json) if v is not None)
    if modes_used > 1:
        raise click.UsageError(
            t(
                "Provide at most one of: --from-file or --adgroups-json — "
                "they are mutually exclusive."
            )
        )
    batch_mode = modes_used > 0

    if batch_mode:
        batch_incompatible = {
            "--name": name,
            **{
                label: flags_local.get(dest)
                for dest, label in _ADGROUPS_ADD_FLAG_FOR.items()
            },
        }
        # --type carries a Click default ("TEXT_AD_GROUP"); only count it as
        # provided when the operator actually passed it.
        type_source = ctx.get_parameter_source("group_type")
        type_explicit = (
            type_source != click.core.ParameterSource.DEFAULT if type_source else False
        )
        if type_explicit:
            batch_incompatible["--type"] = group_type
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
        _bulk_add_adgroups(
            ctx,
            campaign_id=campaign_id,
            from_file=from_file,
            adgroups_json=adgroups_json,
            dry_run=dry_run,
        )
        return

    if name is None:
        raise click.UsageError(t("Missing option '--name'."))
    if campaign_id is None:
        raise click.UsageError(t("Missing option '--campaign-id'."))
    if region_ids is None:
        raise click.UsageError(t("Missing option '--region-ids'."))

    adgroup_data = build_adgroup_object(
        campaign_id=campaign_id,
        name=name,
        group_type=group_type,
        flags=flags_local,
    )

    body = {"method": "add", "params": {"AdGroups": [adgroup_data]}}

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = _post_adgroups(client, body)
    format_output(result().extract(), "json", None)


# dest -> "--flag" map for the `adgroups update` flag set. Hoisted to module
# level so build_adgroup_update_object and the batch normalizer share one source
# of truth.
_ADGROUPS_UPDATE_FLAG_FOR = {
    "name": "--name",
    "status": "--status",
    "region_ids": "--region-ids",
    "domain_url": "--domain-url",
    "dynamic_feed": "--dynamic-feed",
    "negative_keywords": "--negative-keywords",
    "negative_keyword_shared_set_ids": "--negative-keyword-shared-set-ids",
    "tracking_params": "--tracking-params",
    "feed_id": "--feed-id",
    "feed_category_ids": "--feed-category-ids",
    "ad_title_source": "--ad-title-source",
    "ad_body_source": "--ad-body-source",
    "offer_retargeting": "--offer-retargeting",
    "target_device_types": "--target-device-types",
    "target_carrier": "--target-carrier",
    "target_operating_system_version": "--target-operating-system-version",
    "autotargeting_categories": "--autotargeting-category",
    "autotargeting_settings_exact": "--autotargeting-settings-exact",
    "autotargeting_settings_narrow": "--autotargeting-settings-narrow",
    "autotargeting_settings_alternative": "--autotargeting-settings-alternative",
    "autotargeting_settings_accessory": "--autotargeting-settings-accessory",
    "autotargeting_settings_broader": "--autotargeting-settings-broader",
    "autotargeting_settings_without_brands": "--autotargeting-settings-without-brands",
    "autotargeting_settings_with_advertiser_brand": (
        "--autotargeting-settings-with-advertiser-brand"
    ),
    "autotargeting_settings_with_competitors_brand": (
        "--autotargeting-settings-with-competitors-brand"
    ),
}

# Documented per-call limit for adgroups.update is 1000 (Yandex docs); the WSDL
# declares the AdGroups array unbounded. ADGROUPS_UPDATE_MAX_BATCH is a
# conservative CHUNK SIZE (not the ceiling): a partial failure rolls back at
# most this many ad groups.
ADGROUPS_UPDATE_MAX_BATCH = 100


def build_adgroup_update_object(*, adgroup_id, flags):
    """Build a single ``AdGroups`` update item dict from flag values (issue #565).

    Pure (no ``ctx``, no I/O): performs the mixed-subtype reject guard, the
    per-subtype assembly (including the ``--dynamic-feed`` routing between
    DynamicTextAdGroup and DynamicTextFeedAdGroup), and the empty-payload no-op
    guard, returning ``{"Id": ..., ...}``. Both the single-flag ``adgroups
    update`` command and the ``--from-file`` batch normalizer call it so they
    emit byte-identical objects.

    ``flags`` is keyed by the command's dest var names (``name``, ``domain_url``,
    ``dynamic_feed``, ...); missing keys default to ``None`` (``multiple=True``
    flags default to ``()``).
    """

    # Unpack flags into locals so the dispatch body below is byte-identical to
    # the historical inline command body.
    name = flags.get("name")
    status = flags.get("status")
    region_ids = flags.get("region_ids")
    domain_url = flags.get("domain_url")
    dynamic_feed = flags.get("dynamic_feed")
    negative_keywords = flags.get("negative_keywords")
    negative_keyword_shared_set_ids = flags.get("negative_keyword_shared_set_ids")
    tracking_params = flags.get("tracking_params")
    feed_id = flags.get("feed_id")
    feed_category_ids = flags.get("feed_category_ids")
    ad_title_source = flags.get("ad_title_source")
    ad_body_source = flags.get("ad_body_source")
    offer_retargeting = flags.get("offer_retargeting")
    target_device_types = flags.get("target_device_types")
    target_carrier = flags.get("target_carrier")
    target_operating_system_version = flags.get("target_operating_system_version")
    autotargeting_categories = flags.get("autotargeting_categories") or ()
    autotargeting_settings_exact = flags.get("autotargeting_settings_exact")
    autotargeting_settings_narrow = flags.get("autotargeting_settings_narrow")
    autotargeting_settings_alternative = flags.get("autotargeting_settings_alternative")
    autotargeting_settings_accessory = flags.get("autotargeting_settings_accessory")
    autotargeting_settings_broader = flags.get("autotargeting_settings_broader")
    autotargeting_settings_without_brands = flags.get(
        "autotargeting_settings_without_brands"
    )
    autotargeting_settings_with_advertiser_brand = flags.get(
        "autotargeting_settings_with_advertiser_brand"
    )
    autotargeting_settings_with_competitors_brand = flags.get(
        "autotargeting_settings_with_competitors_brand"
    )

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
    dynamic_feed_flags: dict[str, Any] = {
        "--dynamic-feed": True if dynamic_feed else None
    }
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
    parsed_region_ids = _require_nonempty_ids_option(region_ids, "--region-ids")
    if parsed_region_ids is not None:
        adgroup_data["RegionIds"] = parsed_region_ids
    parsed_negative_keywords = parse_csv_strings(negative_keywords)
    if parsed_negative_keywords:
        adgroup_data["NegativeKeywords"] = {"Items": parsed_negative_keywords}
    parsed_negative_keyword_shared_set_ids = _require_nonempty_ids_option(
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

    return adgroup_data


# Batch row keys are the kebab flag names without the leading "--" plus "id";
# map them to build_adgroup_update_object's dest names.
_ADGROUPS_UPDATE_ROW_KEY_TO_DEST = {
    label[2:]: dest for dest, label in _ADGROUPS_UPDATE_FLAG_FOR.items()
}
_ADGROUPS_UPDATE_ROW_ALLOWED_KEYS = frozenset({"id", *_ADGROUPS_UPDATE_ROW_KEY_TO_DEST})
# Repeatable flags accept a JSON list of micro-format strings; keep in sync with
# the `multiple=True` update options (--autotargeting-category).
_ADGROUPS_UPDATE_ROW_MULTI_KEYS = {"autotargeting-category"}
# --dynamic-feed is a boolean flag (is_flag=True): a row expresses it as a JSON
# bool, not a string token, so it bypasses _coerce_adgroup_update_row_field.
_ADGROUPS_UPDATE_ROW_BOOL_KEYS = {"dynamic-feed"}


def _adgroups_update_param_types():
    """Map each ``adgroups update`` row key (kebab, no ``--``) to its Click type.

    Built lazily from the registered command so a batch row is coerced through
    the *exact same* type as the single-flag path (issue #565): e.g. ``--id``
    (IntRange(min=1)) or ``--feed-id`` (int) gets the identical
    conversion/validation, so batch and single produce byte-identical payloads.
    Boolean flags (``--dynamic-feed``) are handled as JSON bools, not here.
    """
    types = {}
    for param in update.params:
        if not isinstance(param, click.Option):
            continue
        if param.is_flag:
            continue
        key = param.opts[0].lstrip("-")
        if param.type is not click.STRING:
            types[key] = param.type
    return types


_ADGROUPS_UPDATE_ROW_PARAM_TYPES = None


def _coerce_adgroup_update_row_field(key, value, row_index):
    """Coerce one scalar batch-row value to its single-flag form (issue #565).

    Mirrors ``ads`` ``_coerce_ad_update_row_field``: rejects JSON
    arrays/objects/``null`` for any scalar field, stringifies JSON int/float/bool
    scalars, then runs typed fields through their single-flag Click type so batch
    and single emit byte-identical payloads (``"id": 1.9`` is rejected, not
    truncated; ``"id": null`` / ``[1]`` raise a clear ``Ad group update row N
    field`` error instead of an uncaught ``TypeError``).
    """
    global _ADGROUPS_UPDATE_ROW_PARAM_TYPES
    if _ADGROUPS_UPDATE_ROW_PARAM_TYPES is None:
        _ADGROUPS_UPDATE_ROW_PARAM_TYPES = _adgroups_update_param_types()
    param_type = _ADGROUPS_UPDATE_ROW_PARAM_TYPES.get(key)

    if value is None or isinstance(value, (list, dict)):
        raise click.UsageError(
            t(
                "Ad group update row {row_index} field {key!r}: expected a "
                "scalar, got {arg0}"
            ).format(row_index=row_index, key=key, arg0=type(value).__name__)
        )

    token = str(value)

    if param_type is None:
        return token

    if isinstance(value, bool):
        raise click.UsageError(
            t(
                "Ad group update row {row_index} field {key!r}: expected {arg0}, "
                "got bool"
            ).format(row_index=row_index, key=key, arg0=param_type.name)
        )
    try:
        return param_type.convert(token, None, None)
    except click.exceptions.BadParameter as exc:
        raise click.UsageError(
            t("Ad group update row {row_index} field {key!r}: {arg0}").format(
                row_index=row_index, key=key, arg0=exc.format_message()
            )
        )


def _normalize_adgroup_update_row(row, row_index):
    """Translate one flag-form batch row into a built ad-group-update object.

    The row keys are kebab flag names without "--" plus ``id`` (required, the
    update target). Each typed field is coerced through its single-flag Click
    type so batch and single emit byte-identical payloads. Unknown keys are
    rejected; ``build_adgroup_update_object`` does the subtype validation, its
    UsageError re-raised under an ``Ad group update row N`` prefix.
    """
    if not isinstance(row, dict):
        raise click.UsageError(
            t(
                "Ad group update row {row_index}: expected JSON object, got {arg0}"
            ).format(row_index=row_index, arg0=type(row).__name__)
        )

    unknown = sorted(set(row) - _ADGROUPS_UPDATE_ROW_ALLOWED_KEYS)
    if unknown:
        raise click.UsageError(
            t(
                "Unknown field {arg0!r} in ad group update row {row_index}; "
                "allowed: {allowed}"
            ).format(
                arg0=unknown[0],
                row_index=row_index,
                allowed=", ".join(sorted(_ADGROUPS_UPDATE_ROW_ALLOWED_KEYS)),
            )
        )

    if "id" not in row:
        raise click.UsageError(
            t("Ad group update row {row_index}: missing required 'id'").format(
                row_index=row_index
            )
        )
    adgroup_id = _coerce_adgroup_update_row_field("id", row["id"], row_index)

    flags = {}
    for key, dest in _ADGROUPS_UPDATE_ROW_KEY_TO_DEST.items():
        if key not in row:
            continue
        value = row[key]
        if key in _ADGROUPS_UPDATE_ROW_BOOL_KEYS:
            # A boolean flag (--dynamic-feed) is a JSON bool in a row.
            if not isinstance(value, bool):
                raise click.UsageError(
                    t(
                        "Ad group update row {row_index} field {key!r}: expected "
                        "a JSON boolean"
                    ).format(row_index=row_index, key=key)
                )
            if not value:
                continue
        elif key in _ADGROUPS_UPDATE_ROW_MULTI_KEYS:
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                raise click.UsageError(
                    t(
                        "Ad group update row {row_index} field {key!r}: expected "
                        "a JSON array of strings"
                    ).format(row_index=row_index, key=key)
                )
            value = tuple(value)
        else:
            value = _coerce_adgroup_update_row_field(key, value, row_index)
        flags[dest] = value

    try:
        return build_adgroup_update_object(
            adgroup_id=adgroup_id,
            flags=flags,
        )
    except click.UsageError as exc:
        raise click.UsageError(
            t("Ad group update row {row_index}: {arg0}").format(
                row_index=row_index, arg0=exc.format_message()
            )
        )


def _bulk_update_adgroups(ctx, *, from_file, adgroups_json, dry_run):
    if from_file is not None:
        raw_rows = _batch.load_jsonl_rows(from_file)
    else:
        raw_rows = _batch.load_inline_rows(
            adgroups_json or "",
            invalid_json_key="--adgroups-json: invalid JSON: {arg0}",
            not_array_key="--adgroups-json must be a JSON array of ad group objects",
        )

    if not raw_rows:
        raise click.UsageError(t("Input contains no ad group rows."))

    items = [
        _normalize_adgroup_update_row(row, idx)
        for idx, row in enumerate(raw_rows, start=1)
    ]

    # _post_adgroups routes the WHOLE body to API v501 when ANY ad group is a
    # UnifiedAdGroup. A chunk that mixes unified and non-unified groups would
    # route the non-unified ones to v501 too, so refuse the mix up front (the
    # single-item path never built a multi-item body, so this is new with batch
    # mode). Same philosophy as _reject_mixed_update_subtype_flags.
    has_unified = any("UnifiedAdGroup" in item for item in items)
    has_non_unified = any("UnifiedAdGroup" not in item for item in items)
    if has_unified and has_non_unified:
        raise click.UsageError(
            t(
                "A batch may not mix UNIFIED_AD_GROUP with other ad group types "
                "(unified groups use a different API endpoint). Split them into "
                "separate --from-file runs."
            )
        )

    _batch.send_batch(
        ctx,
        resource="adgroups",
        method="update",
        payload_key="AdGroups",
        items=items,
        max_batch=ADGROUPS_UPDATE_MAX_BATCH,
        create_client=create_client,
        dry_run=dry_run,
        noun="ad groups",
        result_key="UpdateResults",
        post=_post_adgroups,
    )


@adgroups.command()
@click.option(
    "--id",
    "adgroup_id",
    type=click.IntRange(min=1),
    help="Ad group ID (required in single-item mode; per row in --from-file mode)",
)
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
@click.option(
    "--from-file",
    "from_file",
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help=(
        "Path to a JSONL file (one flag-form ad-group-update object per line) "
        "for batch update"
    ),
)
@click.option(
    "--adgroups-json",
    "adgroups_json",
    help="Inline JSON array of flag-form ad-group-update objects for batch update",
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
    from_file,
    adgroups_json,
    dry_run,
):
    """Update one or many ad groups.

    Single-item mode uses typed flags (--id, --name, ...). Batch mode reads
    flag-form rows from --from-file (JSONL, one object per line) or
    --adgroups-json (inline JSON array); each row is the same flag set keyed by
    the kebab flag name without the leading dashes plus its own "id" (e.g.
    {"id":5,"name":"New"}).
    """
    flags_local = {
        "name": name,
        "status": status,
        "region_ids": region_ids,
        "domain_url": domain_url,
        "dynamic_feed": True if dynamic_feed else None,
        "negative_keywords": negative_keywords,
        "negative_keyword_shared_set_ids": negative_keyword_shared_set_ids,
        "tracking_params": tracking_params,
        "feed_id": feed_id,
        "feed_category_ids": feed_category_ids,
        "ad_title_source": ad_title_source,
        "ad_body_source": ad_body_source,
        "offer_retargeting": offer_retargeting,
        "target_device_types": target_device_types,
        "target_carrier": target_carrier,
        "target_operating_system_version": target_operating_system_version,
        "autotargeting_categories": autotargeting_categories,
        "autotargeting_settings_exact": autotargeting_settings_exact,
        "autotargeting_settings_narrow": autotargeting_settings_narrow,
        "autotargeting_settings_alternative": autotargeting_settings_alternative,
        "autotargeting_settings_accessory": autotargeting_settings_accessory,
        "autotargeting_settings_broader": autotargeting_settings_broader,
        "autotargeting_settings_without_brands": autotargeting_settings_without_brands,
        "autotargeting_settings_with_advertiser_brand": (
            autotargeting_settings_with_advertiser_brand
        ),
        "autotargeting_settings_with_competitors_brand": (
            autotargeting_settings_with_competitors_brand
        ),
    }

    modes_used = sum(1 for v in (from_file, adgroups_json) if v is not None)
    if modes_used > 1:
        raise click.UsageError(
            t(
                "Provide at most one of: --from-file or --adgroups-json — "
                "they are mutually exclusive."
            )
        )
    batch_mode = modes_used > 0

    if batch_mode:
        batch_incompatible = {
            label: flags_local.get(dest)
            for dest, label in _ADGROUPS_UPDATE_FLAG_FOR.items()
        }
        if adgroup_id is not None:
            batch_incompatible["--id"] = adgroup_id
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
        _bulk_update_adgroups(
            ctx,
            from_file=from_file,
            adgroups_json=adgroups_json,
            dry_run=dry_run,
        )
        return

    if adgroup_id is None:
        raise click.UsageError(t("Missing option '--id'."))

    adgroup_data = build_adgroup_update_object(
        adgroup_id=adgroup_id,
        flags=flags_local,
    )

    body = {"method": "update", "params": {"AdGroups": [adgroup_data]}}

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = _post_adgroups(client, body)
    format_output(result().extract(), "json", None)


delete = make_lifecycle_command(
    adgroups, "delete", "Delete ad group", "adgroup_id", "Ad group ID", create_client
)
