"""
Campaigns commands
"""

import re
from typing import Dict, List, Optional, Sequence

import click

from ..api import client_from_ctx, create_client
from ..i18n import t
from ..output import format_output, handle_api_errors
from ..utils import (
    build_selection_criteria,
    build_common_params,
    add_criteria_csv,
    get_default_fields,
    MICRO_RUBLES,
    parse_ids,
    parse_csv_strings,
    parse_priority_goals_spec,
    parse_setting_specs,
)
from .._bidding_strategy import (
    BUDGET_TYPES,
    TEXT_CAMPAIGN_NETWORK_STRATEGY_TO_WSDL_SUBTYPE,
    UNIFIED_CAMPAIGN_NETWORK_STRATEGY_TO_WSDL_SUBTYPE,
    _TEXT_CAMPAIGN_SEARCH_STRATEGY_TO_WSDL_SUBTYPE,
    _TEXT_NETWORK_AVERAGE_CPA_SUBTYPES,
    _TEXT_NETWORK_BID_CEILING_SUBTYPES,
    _TEXT_NETWORK_CRR_SUBTYPES,
    _TEXT_NETWORK_GOAL_ID_SUBTYPES,
    _TEXT_NETWORK_REQUIRES_PRIORITY_GOALS,
    _TEXT_SEARCH_SUPPORTS_AVERAGE_CPA,
    _TEXT_SEARCH_SUPPORTS_BID_CEILING,
    _TEXT_SEARCH_SUPPORTS_CRR,
    _TEXT_SEARCH_SUPPORTS_GOAL_ID,
    _UNIFIED_CAMPAIGN_SEARCH_STRATEGY_TO_WSDL_SUBTYPE,
    _UNIFIED_NETWORK_AVERAGE_CPA_SUBTYPES,
    _UNIFIED_NETWORK_BID_CEILING_SUBTYPES,
    _UNIFIED_NETWORK_CRR_SUBTYPES,
    _UNIFIED_NETWORK_GOAL_ID_SUBTYPES,
    _UNIFIED_NETWORK_REQUIRES_PRIORITY_GOALS,
    _UNIFIED_SEARCH_REQUIRES_PRIORITY_GOALS,
    _UNIFIED_SEARCH_SUPPORTS_AVERAGE_CPA,
    _UNIFIED_SEARCH_SUPPORTS_BID_CEILING,
    _UNIFIED_SEARCH_SUPPORTS_CRR,
    _UNIFIED_SEARCH_SUPPORTS_GOAL_ID,
    get_bidding_strategy_builder,
)
from .._flag_validation import reject_incompatible_flags

SMS_EVENTS = {"MONITORING", "MODERATION", "MONEY_IN", "MONEY_OUT", "FINISHED"}
YES_NO = ["YES", "NO"]
ATTRIBUTION_MODELS = ["FC", "LC", "LSC", "LYDC", "FCCD", "LSCCD", "LYDCCD", "AUTO"]
RELEVANT_KEYWORDS_MODES = ["MINIMUM", "OPTIMAL", "MAXIMUM"]
VIDEO_TARGETS = ["VIEWS", "CLICKS"]
CLIENT_INFO_MAX_LENGTH = 255
BLOCKED_IPS_MAX_ITEMS = 25
EXCLUDED_SITES_MAX_ITEMS = 1000
EXCLUDED_SITE_MAX_LENGTH = 255
TIME_TARGETING_SCHEDULE_MAX_ITEMS = 7
NEGATIVE_KEYWORD_SHARED_SET_IDS_MAX_ITEMS = 3
HH_MM_RE = re.compile(r"^(?:[01]\d|2[0-3]):(?:00|15|30|45)$")
_DEPRECATED_CAMPAIGNS_STRUCTURED_OPTIONS = {
    "notification": (
        "--notification is no longer accepted on 'campaigns add/update'; "
        "use typed flags such as --sms-events, --notification-email, "
        "and --notification-send-warnings."
    ),
    "time_targeting": (
        "--time-targeting is no longer accepted on 'campaigns add/update'; "
        "use typed flags such as --time-targeting-schedule, "
        "--consider-working-weekends, and --holidays-suspend-on-holidays."
    ),
}


def _deprecated_campaigns_structured_option(ctx, param, value):
    if value is not None:
        raise click.UsageError(_DEPRECATED_CAMPAIGNS_STRUCTURED_OPTIONS[param.name])


@click.group()
def campaigns():
    """Manage campaigns"""


def _parse_csv_option(option_name: str, value: Optional[str]) -> Optional[List[str]]:
    """Parse a CSV option and reject explicitly empty input."""
    parsed = parse_csv_strings(value)
    if value is not None and not parsed:
        raise click.UsageError(
            t("{option_name} must contain at least one value").format(
                option_name=option_name
            )
        )
    return parsed


def _array_of_string_option(
    option_name: str,
    value: Optional[str],
    *,
    max_items: Optional[int] = None,
    max_item_length: Optional[int] = None,
) -> Optional[dict]:
    """Build a WSDL ArrayOfString payload from a comma-separated flag."""
    parsed = _parse_csv_option(option_name, value)
    if parsed and max_items is not None and len(parsed) > max_items:
        raise click.UsageError(
            t("{option_name} must contain at most {max_items} items").format(
                option_name=option_name, max_items=max_items
            )
        )
    if parsed and max_item_length is not None:
        too_long = [item for item in parsed if len(item) > max_item_length]
        if too_long:
            raise click.UsageError(
                t(
                    "{option_name} items must be at most {max_item_length} characters"
                ).format(option_name=option_name, max_item_length=max_item_length)
            )
    return {"Items": parsed} if parsed else None


def _array_of_integer_option(
    option_name: str,
    value: Optional[str],
    *,
    max_items: Optional[int] = None,
) -> Optional[dict]:
    """Build a WSDL ArrayOfInteger/ArrayOfLong payload from CSV IDs."""
    if value is None:
        return None
    parsed = parse_ids(value)
    if not parsed:
        raise click.UsageError(
            t("{option_name} must contain at least one integer").format(
                option_name=option_name
            )
        )
    if max_items is not None and len(parsed) > max_items:
        raise click.UsageError(
            t("{option_name} must contain at most {max_items} items").format(
                option_name=option_name, max_items=max_items
            )
        )
    return {"Items": parsed}


def _time_targeting_schedule_option(values: Sequence[str]) -> Optional[dict]:
    """Build TimeTargeting.Schedule without splitting comma-bearing rows."""
    if not values:
        return None
    items = [value.strip() for value in values if value.strip()]
    if len(items) != len(values):
        raise click.UsageError(
            t("--time-targeting-schedule must contain at least one value")
        )
    if len(items) > TIME_TARGETING_SCHEDULE_MAX_ITEMS:
        raise click.UsageError(
            t(
                "--time-targeting-schedule must contain at most {TIME_TARGETING_SCHEDULE_MAX_ITEMS} items"
            ).format(
                TIME_TARGETING_SCHEDULE_MAX_ITEMS=TIME_TARGETING_SCHEDULE_MAX_ITEMS
            )
        )
    return {"Items": items}


def _upper_yes_no(value: Optional[str]) -> Optional[str]:
    """Normalize Click YesNoEnum values."""
    return value.upper() if value is not None else None


def _validate_max_length(
    option_name: str,
    value: Optional[str],
    max_length: int,
) -> Optional[str]:
    """Reject string options longer than the documented maximum."""
    if value is not None and len(value) > max_length:
        raise click.UsageError(
            t("{option_name} must be at most {max_length} characters").format(
                option_name=option_name, max_length=max_length
            )
        )
    return value


def _validate_sms_time(option_name: str, value: Optional[str]) -> Optional[str]:
    """Validate documented HH:MM values with 15-minute steps."""
    if value is None:
        return None
    if not HH_MM_RE.fullmatch(value):
        raise click.UsageError(
            t("{option_name} must use HH:MM with minutes 00, 15, 30, or 45").format(
                option_name=option_name
            )
        )
    return value


def _build_notification(
    sms_events: Optional[str],
    sms_time_from: Optional[str],
    sms_time_to: Optional[str],
    notification_email: Optional[str],
    notification_check_position_interval: Optional[str],
    notification_warning_balance: Optional[int],
    notification_send_account_news: Optional[str],
    notification_send_warnings: Optional[str],
) -> Optional[dict]:
    """Build CampaignBase.Notification from typed flags."""
    notification: Dict[str, dict] = {}

    sms_settings: dict = {}
    parsed_sms_events = _parse_csv_option("--sms-events", sms_events)
    if parsed_sms_events:
        normalized_events = [event.upper() for event in parsed_sms_events]
        invalid = sorted(set(normalized_events) - SMS_EVENTS)
        if invalid:
            raise click.UsageError(
                t(
                    "--sms-events contains invalid value(s) {invalid}; allowed: {arg0}"
                ).format(invalid=invalid, arg0=sorted(SMS_EVENTS))
            )
        sms_settings["Events"] = normalized_events
    validated_sms_time_from = _validate_sms_time("--sms-time-from", sms_time_from)
    if validated_sms_time_from:
        sms_settings["TimeFrom"] = validated_sms_time_from
    validated_sms_time_to = _validate_sms_time("--sms-time-to", sms_time_to)
    if validated_sms_time_to:
        sms_settings["TimeTo"] = validated_sms_time_to
    if sms_settings:
        notification["SmsSettings"] = sms_settings

    email_settings: dict = {}
    if notification_email:
        email_settings["Email"] = notification_email
    if notification_check_position_interval is not None:
        email_settings["CheckPositionInterval"] = int(
            notification_check_position_interval
        )
    if notification_warning_balance is not None:
        email_settings["WarningBalance"] = notification_warning_balance
    send_account_news = _upper_yes_no(notification_send_account_news)
    if send_account_news is not None:
        email_settings["SendAccountNews"] = send_account_news
    send_warnings = _upper_yes_no(notification_send_warnings)
    if send_warnings is not None:
        email_settings["SendWarnings"] = send_warnings
    if email_settings:
        notification["EmailSettings"] = email_settings

    return notification or None


def _build_time_targeting(
    time_targeting_schedule: Sequence[str],
    consider_working_weekends: Optional[str],
    holidays_suspend_on_holidays: Optional[str],
    holidays_bid_percent: Optional[int],
    holidays_start_hour: Optional[int],
    holidays_end_hour: Optional[int],
) -> Optional[dict]:
    """Build CampaignAddItem/UpdateItem.TimeTargeting from typed flags."""
    schedule = _time_targeting_schedule_option(time_targeting_schedule)
    has_holidays = any(
        value is not None
        for value in (
            holidays_suspend_on_holidays,
            holidays_bid_percent,
            holidays_start_hour,
            holidays_end_hour,
        )
    )
    has_time_targeting = (
        schedule is not None or consider_working_weekends is not None or has_holidays
    )
    if not has_time_targeting:
        return None
    if consider_working_weekends is None:
        raise click.UsageError(
            t(
                "TimeTargeting requires --consider-working-weekends when any "
                "time-targeting flag is provided."
            )
        )

    time_targeting: dict = {
        "ConsiderWorkingWeekends": consider_working_weekends.upper()
    }
    if schedule is not None:
        time_targeting["Schedule"] = schedule

    if has_holidays:
        if holidays_suspend_on_holidays is None:
            raise click.UsageError(
                t(
                    "TimeTargeting.HolidaysSchedule requires "
                    "--holidays-suspend-on-holidays when any --holidays-* flag "
                    "is provided."
                )
            )
        suspend_on_holidays = holidays_suspend_on_holidays.upper()
        if suspend_on_holidays == "YES" and any(
            value is not None
            for value in (
                holidays_bid_percent,
                holidays_start_hour,
                holidays_end_hour,
            )
        ):
            raise click.UsageError(
                t(
                    "--holidays-bid-percent, --holidays-start-hour, and "
                    "--holidays-end-hour can be provided only when "
                    "--holidays-suspend-on-holidays is NO."
                )
            )
        if holidays_bid_percent is not None and holidays_bid_percent % 10 != 0:
            raise click.UsageError(t("--holidays-bid-percent must be a multiple of 10"))
        holidays: dict = {"SuspendOnHolidays": suspend_on_holidays}
        if holidays_bid_percent is not None:
            holidays["BidPercent"] = holidays_bid_percent
        if holidays_start_hour is not None:
            holidays["StartHour"] = holidays_start_hour
        if holidays_end_hour is not None:
            holidays["EndHour"] = holidays_end_hour
        time_targeting["HolidaysSchedule"] = holidays

    return time_targeting


def _build_relevant_keywords(
    budget_percent: Optional[int],
    mode: Optional[str],
    optimize_goal_id: Optional[int],
    *,
    require_budget_percent: bool,
) -> Optional[dict]:
    """Build TextCampaign.RelevantKeywords from typed flags."""
    if budget_percent is None and mode is None and optimize_goal_id is None:
        return None
    if require_budget_percent and budget_percent is None:
        raise click.UsageError(
            t(
                "--relevant-keywords-budget-percent is required when adding "
                "TextCampaign.RelevantKeywords"
            )
        )
    relevant_keywords: dict = {}
    if budget_percent is not None:
        relevant_keywords["BudgetPercent"] = budget_percent
    if mode is not None:
        relevant_keywords["Mode"] = mode.upper()
    if optimize_goal_id is not None:
        relevant_keywords["OptimizeGoalId"] = optimize_goal_id
    return relevant_keywords


def _build_dynamic_placement_types(
    search_results: Optional[str],
    product_gallery: Optional[str],
) -> Optional[List[dict]]:
    """Build DynamicTextCampaign.PlacementTypes from explicit YES/NO flags."""
    if search_results is None and product_gallery is None:
        return None

    placement_types = []
    for placement_type, value in (
        ("SEARCH_RESULTS", search_results),
        ("PRODUCT_GALLERY", product_gallery),
    ):
        if value is not None:
            placement_types.append({"Type": placement_type, "Value": value.upper()})
    return placement_types


def _build_frequency_cap(
    impressions: Optional[int],
    period_days: Optional[int],
    period_all: bool,
) -> Optional[dict]:
    """Build CpmBannerCampaign.FrequencyCap from paired typed flags."""
    if impressions is None and period_days is None and not period_all:
        return None
    if period_days is not None and period_all:
        raise click.UsageError(
            t(
                "--frequency-cap-period-days and --frequency-cap-period-all "
                "are mutually exclusive"
            )
        )
    if impressions is None:
        raise click.UsageError(
            t(
                "--frequency-cap-impressions is required with "
                "--frequency-cap-period-days or --frequency-cap-period-all"
            )
        )
    if period_days is None and not period_all:
        raise click.UsageError(
            t(
                "--frequency-cap-impressions requires --frequency-cap-period-days "
                "or --frequency-cap-period-all"
            )
        )
    return {
        "Impressions": impressions,
        "PeriodDays": None if period_all else period_days,
    }


def _build_package_bidding_strategy(
    strategy_id: Optional[int],
    strategy_from_campaign_id: Optional[int],
    search_result: Optional[str],
    product_gallery: Optional[str],
    maps: Optional[str],
    search_organization_list: Optional[str],
    network: Optional[str],
    dynamic_places: Optional[str],
    *,
    campaign_label: str,
    require_platforms: bool,
) -> Optional[dict]:
    """Build Campaign.PackageBiddingStrategy from typed flags."""
    values = (
        strategy_id,
        strategy_from_campaign_id,
        search_result,
        product_gallery,
        maps,
        search_organization_list,
        network,
        dynamic_places,
    )
    if not any(value is not None for value in values):
        return None

    has_platform_flags = any(
        value is not None
        for value in (
            search_result,
            product_gallery,
            maps,
            search_organization_list,
            network,
            dynamic_places,
        )
    )
    if (require_platforms or has_platform_flags) and (
        search_result is None or product_gallery is None or network is None
    ):
        raise click.UsageError(
            t(
                "{campaign_label}.PackageBiddingStrategy requires --package-platform-search-result, --package-platform-product-gallery, and --package-platform-network"
            ).format(campaign_label=campaign_label)
        )

    package_strategy: dict = {}
    if strategy_id is not None:
        package_strategy["StrategyId"] = strategy_id
    if strategy_from_campaign_id is not None:
        package_strategy["StrategyFromCampaignId"] = strategy_from_campaign_id

    platform_values = {
        "SearchResult": search_result,
        "ProductGallery": product_gallery,
        "Maps": maps,
        "SearchOrganizationList": search_organization_list,
        "Network": network,
        "DynamicPlaces": dynamic_places,
    }
    platforms = {
        key: value.upper()
        for key, value in platform_values.items()
        if value is not None
    }
    if platforms:
        package_strategy["Platforms"] = platforms

    return package_strategy


def _build_smart_package_bidding_strategy(
    strategy_id: Optional[int],
    strategy_from_campaign_id: Optional[int],
    search: Optional[str],
    network: Optional[str],
    *,
    require_platforms: bool,
) -> Optional[dict]:
    """Build SmartCampaign.PackageBiddingStrategy from typed flags."""
    values = (strategy_id, strategy_from_campaign_id, search, network)
    if not any(value is not None for value in values):
        return None

    has_platform_flags = search is not None or network is not None
    if (require_platforms or has_platform_flags) and (
        search is None or network is None
    ):
        raise click.UsageError(
            t(
                "SmartCampaign.PackageBiddingStrategy requires "
                "--package-platform-search and --package-platform-network"
            )
        )

    package_strategy: dict = {}
    if strategy_id is not None:
        package_strategy["StrategyId"] = strategy_id
    if strategy_from_campaign_id is not None:
        package_strategy["StrategyFromCampaignId"] = strategy_from_campaign_id
    if search is not None or network is not None:
        assert search is not None
        assert network is not None
        package_strategy["Platforms"] = {
            "Search": search.upper(),
            "Network": network.upper(),
        }

    return package_strategy


def _priority_goals_update_items(
    priority_goals_items: Optional[List[dict]],
) -> Optional[List[dict]]:
    """Add the WSDL-required SET operation for campaign priority goal updates."""
    if priority_goals_items is None:
        return None
    return [dict(item, Operation="SET") for item in priority_goals_items]


def _route_cpa_flag(
    value,
    search_subtype,
    network_subtype,
    search_support: set,
    network_support: set,
    default: str,
):
    """Route a shared CPA flag to the Search/Network sides of a campaign's
    bidding strategy, based on which side's chosen subtype declares the WSDL
    field. Returns ``(search_value, network_value)``.

    ``default`` is the fallback side ("search" or "network") used when neither
    side's subtype accepts the field — it preserves the canonical error path
    (e.g. ``--average-cpa`` with ``HIGHEST_POSITION`` still surfaces the
    "CPA-shaped strategy required" error from the chosen side's builder).

    Shared verbatim by the TextCampaign and UnifiedCampaign add-payload
    routing (#361/#364/#366); previously an identical inline closure in each.
    """
    if value is None:
        return (None, None)
    s_ok = search_subtype in search_support
    n_ok = network_subtype in network_support
    if s_ok and n_ok:
        return (value, value)
    if s_ok:
        return (value, None)
    if n_ok:
        return (None, value)
    if default == "network":
        return (None, value)
    return (value, None)


@campaigns.command()
@click.option("--ids", help="Comma-separated campaign IDs")
@click.option("--status", help="Filter by status (ACTIVE, SUSPENDED, etc.)")
@click.option("--statuses", help="Comma-separated statuses")
@click.option("--types", help="Filter by types (TEXT_CAMPAIGN, etc.)")
@click.option("--states", help="Comma-separated states")
@click.option("--payment-statuses", help="Comma-separated payment statuses")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option(
    "--format",
    "output_format",
    default="json",
    help="Output format (json/table/csv/tsv)",
)
@click.option("--output", help="Output file")
@click.option(
    "--fields", help="Comma-separated field names (default: all common fields)"
)
@click.option(
    "--text-campaign-field-names",
    help=(
        "Comma-separated TextCampaignFieldNames "
        "(e.g. CounterIds,Settings,BiddingStrategy,PriorityGoals). "
        "Sent as separate top-level request parameter per the "
        "CampaignsGetRequest WSDL."
    ),
)
@click.option(
    "--text-campaign-search-strategy-placement-types-field-names",
    help=(
        "Comma-separated TextCampaignSearchStrategyPlacementTypesFieldNames "
        "(e.g. SearchResults,ProductGallery,DynamicPlaces). "
        "Sent as separate top-level request parameter per the "
        "CampaignsGetRequest WSDL."
    ),
)
@click.option(
    "--mobile-app-campaign-field-names",
    help=(
        "Comma-separated MobileAppCampaignFieldNames "
        "(e.g. Settings,BiddingStrategy,NegativeKeywordSharedSetIds). "
        "Sent as separate top-level request parameter per the "
        "CampaignsGetRequest WSDL."
    ),
)
@click.option(
    "--dynamic-text-campaign-field-names",
    help=(
        "Comma-separated DynamicTextCampaignFieldNames "
        "(e.g. PlacementTypes,CounterIds,Settings,BiddingStrategy). "
        "Sent as separate top-level request parameter per the "
        "CampaignsGetRequest WSDL."
    ),
)
@click.option(
    "--dynamic-text-campaign-search-strategy-placement-types-field-names",
    help=(
        "Comma-separated "
        "DynamicTextCampaignSearchStrategyPlacementTypesFieldNames "
        "(e.g. SearchResults,ProductGallery,DynamicPlaces). "
        "Sent as separate top-level request parameter per the "
        "CampaignsGetRequest WSDL."
    ),
)
@click.option(
    "--cpm-banner-campaign-field-names",
    help=(
        "Comma-separated CpmBannerCampaignFieldNames "
        "(e.g. CounterIds,FrequencyCap,Settings,BiddingStrategy). "
        "Sent as separate top-level request parameter per the "
        "CampaignsGetRequest WSDL."
    ),
)
@click.option(
    "--smart-campaign-field-names",
    help=(
        "Comma-separated SmartCampaignFieldNames "
        "(e.g. CounterId,Settings,BiddingStrategy,PriorityGoals). "
        "Sent as separate top-level request parameter per the "
        "CampaignsGetRequest WSDL."
    ),
)
@click.option(
    "--unified-campaign-field-names",
    help=(
        "Comma-separated UnifiedCampaignFieldNames "
        "(e.g. CounterIds,Settings,BiddingStrategy,PriorityGoals). "
        "Sent as separate top-level request parameter per the "
        "CampaignsGetRequest WSDL."
    ),
)
@click.option(
    "--unified-campaign-search-strategy-placement-types-field-names",
    help=(
        "Comma-separated "
        "UnifiedCampaignSearchStrategyPlacementTypesFieldNames "
        "(e.g. SearchResults,ProductGallery,Maps,SearchOrganizationList). "
        "Sent as separate top-level request parameter per the "
        "CampaignsGetRequest WSDL."
    ),
)
@click.option(
    "--unified-campaign-package-bidding-strategy-platforms-field-names",
    help=(
        "Comma-separated "
        "UnifiedCampaignPackageBiddingStrategyPlatformsFieldNames "
        "(e.g. SearchResult,ProductGallery,Maps,Network). "
        "Sent as separate top-level request parameter per the "
        "CampaignsGetRequest WSDL."
    ),
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def get(
    ctx,
    ids,
    status,
    statuses,
    types,
    states,
    payment_statuses,
    limit,
    fetch_all,
    output_format,
    output,
    fields,
    text_campaign_field_names,
    text_campaign_search_strategy_placement_types_field_names,
    mobile_app_campaign_field_names,
    dynamic_text_campaign_field_names,
    dynamic_text_campaign_search_strategy_placement_types_field_names,
    cpm_banner_campaign_field_names,
    smart_campaign_field_names,
    unified_campaign_field_names,
    unified_campaign_search_strategy_placement_types_field_names,
    unified_campaign_package_bidding_strategy_platforms_field_names,
    dry_run,
):
    """Get campaigns"""
    if status and statuses:
        raise click.UsageError(t("--status and --statuses are mutually exclusive"))

    client = client_from_ctx(ctx, create_client)

    # Parse field names
    field_names = (
        _parse_csv_option("--fields", fields)
        if fields is not None
        else get_default_fields("campaigns")
    )

    # Build selection criteria
    criteria = build_selection_criteria(ids=parse_ids(ids), status=status, types=types)
    if criteria is None:
        criteria = {}
    add_criteria_csv(criteria, "Statuses", statuses, upper=True)
    add_criteria_csv(criteria, "States", states, upper=True)
    add_criteria_csv(criteria, "StatusesPayment", payment_statuses, upper=True)

    # Build params
    params = build_common_params(
        criteria=criteria, field_names=field_names, limit=limit
    )
    selector_options = {
        "TextCampaignFieldNames": (
            "--text-campaign-field-names",
            text_campaign_field_names,
        ),
        "TextCampaignSearchStrategyPlacementTypesFieldNames": (
            "--text-campaign-search-strategy-placement-types-field-names",
            text_campaign_search_strategy_placement_types_field_names,
        ),
        "MobileAppCampaignFieldNames": (
            "--mobile-app-campaign-field-names",
            mobile_app_campaign_field_names,
        ),
        "DynamicTextCampaignFieldNames": (
            "--dynamic-text-campaign-field-names",
            dynamic_text_campaign_field_names,
        ),
        "DynamicTextCampaignSearchStrategyPlacementTypesFieldNames": (
            "--dynamic-text-campaign-search-strategy-placement-types-field-names",
            dynamic_text_campaign_search_strategy_placement_types_field_names,
        ),
        "CpmBannerCampaignFieldNames": (
            "--cpm-banner-campaign-field-names",
            cpm_banner_campaign_field_names,
        ),
        "SmartCampaignFieldNames": (
            "--smart-campaign-field-names",
            smart_campaign_field_names,
        ),
        "UnifiedCampaignFieldNames": (
            "--unified-campaign-field-names",
            unified_campaign_field_names,
        ),
        "UnifiedCampaignSearchStrategyPlacementTypesFieldNames": (
            "--unified-campaign-search-strategy-placement-types-field-names",
            unified_campaign_search_strategy_placement_types_field_names,
        ),
        "UnifiedCampaignPackageBiddingStrategyPlatformsFieldNames": (
            "--unified-campaign-package-bidding-strategy-platforms-field-names",
            unified_campaign_package_bidding_strategy_platforms_field_names,
        ),
    }
    for request_key, (option_name, value) in selector_options.items():
        parsed = _parse_csv_option(option_name, value)
        if parsed:
            params[request_key] = parsed

    body = {"method": "get", "params": params}

    if dry_run:
        format_output(body, "json", None)
        return

    result = client.campaigns().post(data=body)

    if fetch_all:
        # Get all pages
        items = []
        for item in result().iter_items():
            items.append(item)
        format_output(items, output_format, output)
    else:
        data = result().extract()
        format_output(data, output_format, output)


@campaigns.command()
@click.option("--name", required=True, help="Campaign name")
@click.option("--start-date", required=True, help="Start date (YYYY-MM-DD)")
@click.option(
    "--type",
    "campaign_type",
    default="TEXT_CAMPAIGN",
    help="Campaign type",
)
@click.option("--budget", type=MICRO_RUBLES, help="Daily budget in micro-rubles")
@click.option("--end-date", help="End date (YYYY-MM-DD)")
@click.option(
    "--setting",
    "settings",
    multiple=True,
    help="Campaign setting spec: OPTION=VALUE",
)
@click.option("--search-strategy", help="Search bidding strategy type")
@click.option("--network-strategy", help="Network bidding strategy type")
@click.option(
    "--search-placement-search-results",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=(
        "TextCampaign/UnifiedCampaign/DynamicTextCampaign Search "
        "PlacementTypes.SearchResults"
    ),
)
@click.option(
    "--search-placement-product-gallery",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=(
        "TextCampaign/UnifiedCampaign/DynamicTextCampaign Search "
        "PlacementTypes.ProductGallery"
    ),
)
@click.option(
    "--search-placement-dynamic-places",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=(
        "TextCampaign/UnifiedCampaign/DynamicTextCampaign Search "
        "PlacementTypes.DynamicPlaces"
    ),
)
@click.option(
    "--filter-average-cpc",
    type=MICRO_RUBLES,
    help="Smart campaign filter average CPC in micro-rubles",
)
@click.option("--counter-id", type=int, help="Smart campaign counter ID")
@click.option(
    "--counter-ids",
    help=(
        "Comma-separated Metrika counter IDs "
        "(TextCampaign/UnifiedCampaign/DynamicTextCampaign/"
        "CpmBannerCampaign.CounterIds.Items)"
    ),
)
@click.option(
    "--dynamic-placement-search-results",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="DynamicTextCampaign.PlacementTypes SEARCH_RESULTS: YES or NO",
)
@click.option(
    "--dynamic-placement-product-gallery",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="DynamicTextCampaign.PlacementTypes PRODUCT_GALLERY: YES or NO",
)
@click.option(
    "--goal-id",
    type=int,
    help=(
        "Single Metrika goal ID for AVERAGE_CPA / PAY_FOR_CONVERSION_CRR / "
        "AVERAGE_CPA_PER_CAMPAIGN / AVERAGE_CPA_PER_FILTER strategies"
    ),
)
@click.option(
    "--priority-goals",
    help=(
        "Comma-separated goal_id:value[:YES|NO] pairs for "
        "TextCampaign/UnifiedCampaign/DynamicTextCampaign.PriorityGoals "
        "(required for AVERAGE_CPA_MULTIPLE_GOALS / "
        "PAY_FOR_CONVERSION_MULTIPLE_GOALS); also accepted on "
        "SmartCampaign.PriorityGoals (#369) as a campaign-level "
        "setting independent of the SmartCampaign.BiddingStrategy "
        "subtype. Value is in micro-currency "
        "(advertiser currency × 1,000,000), matching the API contract "
        "and other money flags (--budget, --average-cpa)."
    ),
)
@click.option(
    "--relevant-keywords-budget-percent",
    type=click.IntRange(1, 100),
    help="TextCampaign.RelevantKeywords.BudgetPercent",
)
@click.option(
    "--relevant-keywords-mode",
    type=click.Choice(RELEVANT_KEYWORDS_MODES, case_sensitive=False),
    help="TextCampaign.RelevantKeywords.Mode",
)
@click.option(
    "--relevant-keywords-optimize-goal-id",
    type=int,
    help="TextCampaign.RelevantKeywords.OptimizeGoalId",
)
@click.option(
    "--attribution-model",
    type=click.Choice(ATTRIBUTION_MODELS, case_sensitive=False),
    help=(
        "TextCampaign/UnifiedCampaign/DynamicTextCampaign/SmartCampaign."
        "AttributionModel"
    ),
)
@click.option(
    "--package-strategy-id",
    type=int,
    help=(
        "TextCampaign/UnifiedCampaign/DynamicTextCampaign/SmartCampaign."
        "PackageBiddingStrategy.StrategyId"
    ),
)
@click.option(
    "--package-strategy-from-campaign-id",
    type=int,
    help=(
        "TextCampaign/UnifiedCampaign/DynamicTextCampaign/SmartCampaign."
        "PackageBiddingStrategy.StrategyFromCampaignId"
    ),
)
@click.option(
    "--package-platform-search",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="SmartCampaign.PackageBiddingStrategy.Platforms.Search",
)
@click.option(
    "--package-platform-search-result",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="TextCampaign/UnifiedCampaign.PackageBiddingStrategy.Platforms.SearchResult",
)
@click.option(
    "--package-platform-product-gallery",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="TextCampaign/UnifiedCampaign.PackageBiddingStrategy.Platforms.ProductGallery",
)
@click.option(
    "--package-platform-maps",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="UnifiedCampaign.PackageBiddingStrategy.Platforms.Maps",
)
@click.option(
    "--package-platform-search-organization-list",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="UnifiedCampaign.PackageBiddingStrategy.Platforms.SearchOrganizationList",
)
@click.option(
    "--package-platform-network",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=(
        "TextCampaign/UnifiedCampaign/SmartCampaign."
        "PackageBiddingStrategy.Platforms.Network"
    ),
)
@click.option(
    "--package-platform-dynamic-places",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=(
        "TextCampaign/UnifiedCampaign.PackageBiddingStrategy.Platforms.DynamicPlaces"
    ),
)
@click.option(
    "--negative-keyword-shared-set-ids",
    help=(
        "Comma-separated "
        "TextCampaign/UnifiedCampaign/DynamicTextCampaign/MobileAppCampaign."
        "NegativeKeywordSharedSetIds.Items"
    ),
)
@click.option(
    "--frequency-cap-impressions",
    type=click.IntRange(1),
    help="CpmBannerCampaign.FrequencyCap.Impressions",
)
@click.option(
    "--frequency-cap-period-days",
    type=click.IntRange(1, 30),
    help="CpmBannerCampaign.FrequencyCap.PeriodDays, 1-30",
)
@click.option(
    "--frequency-cap-period-all",
    is_flag=True,
    help="Set CpmBannerCampaign.FrequencyCap.PeriodDays to null",
)
@click.option(
    "--video-target",
    type=click.Choice(VIDEO_TARGETS, case_sensitive=False),
    help="CpmBannerCampaign.VideoTarget: VIEWS or CLICKS",
)
@click.option(
    "--average-cpm",
    type=MICRO_RUBLES,
    help="CpmBannerCampaign strategy AverageCpm in micro-rubles",
)
@click.option(
    "--average-cpv",
    type=MICRO_RUBLES,
    help="CpmBannerCampaign strategy AverageCpv in micro-rubles",
)
@click.option(
    "--strategy-spend-limit",
    type=MICRO_RUBLES,
    help="CpmBannerCampaign strategy SpendLimit in micro-rubles",
)
@click.option("--strategy-start-date", help="CpmBannerCampaign strategy StartDate")
@click.option("--strategy-end-date", help="CpmBannerCampaign strategy EndDate")
@click.option(
    "--strategy-auto-continue",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="CpmBannerCampaign strategy AutoContinue: YES or NO",
)
@click.option(
    "--mobile-search-weekly-spend-limit",
    type=MICRO_RUBLES,
    help="MobileAppCampaign Search strategy WeeklySpendLimit in micro-rubles",
)
@click.option(
    "--mobile-search-bid-ceiling",
    type=MICRO_RUBLES,
    help="MobileAppCampaign Search strategy BidCeiling in micro-rubles",
)
@click.option(
    "--mobile-search-custom-period-spend-limit",
    type=MICRO_RUBLES,
    help="MobileAppCampaign Search CustomPeriodBudget.SpendLimit in micro-rubles",
)
@click.option(
    "--mobile-search-custom-period-start-date",
    help="MobileAppCampaign Search CustomPeriodBudget.StartDate",
)
@click.option(
    "--mobile-search-custom-period-end-date",
    help="MobileAppCampaign Search CustomPeriodBudget.EndDate",
)
@click.option(
    "--mobile-search-custom-period-auto-continue",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="MobileAppCampaign Search CustomPeriodBudget.AutoContinue: YES or NO",
)
@click.option(
    "--mobile-search-average-cpc",
    type=MICRO_RUBLES,
    help="MobileAppCampaign Search strategy AverageCpc in micro-rubles",
)
@click.option(
    "--mobile-search-average-cpi",
    type=MICRO_RUBLES,
    help="MobileAppCampaign Search strategy AverageCpi in micro-rubles",
)
@click.option(
    "--mobile-search-clicks-per-week",
    type=click.IntRange(1),
    help="MobileAppCampaign Search strategy ClicksPerWeek",
)
@click.option(
    "--mobile-network-weekly-spend-limit",
    type=MICRO_RUBLES,
    help="MobileAppCampaign Network strategy WeeklySpendLimit in micro-rubles",
)
@click.option(
    "--mobile-network-bid-ceiling",
    type=MICRO_RUBLES,
    help="MobileAppCampaign Network strategy BidCeiling in micro-rubles",
)
@click.option(
    "--mobile-network-custom-period-spend-limit",
    type=MICRO_RUBLES,
    help="MobileAppCampaign Network CustomPeriodBudget.SpendLimit in micro-rubles",
)
@click.option(
    "--mobile-network-custom-period-start-date",
    help="MobileAppCampaign Network CustomPeriodBudget.StartDate",
)
@click.option(
    "--mobile-network-custom-period-end-date",
    help="MobileAppCampaign Network CustomPeriodBudget.EndDate",
)
@click.option(
    "--mobile-network-custom-period-auto-continue",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="MobileAppCampaign Network CustomPeriodBudget.AutoContinue: YES or NO",
)
@click.option(
    "--mobile-network-average-cpc",
    type=MICRO_RUBLES,
    help="MobileAppCampaign Network strategy AverageCpc in micro-rubles",
)
@click.option(
    "--mobile-network-average-cpi",
    type=MICRO_RUBLES,
    help="MobileAppCampaign Network strategy AverageCpi in micro-rubles",
)
@click.option(
    "--mobile-network-clicks-per-week",
    type=click.IntRange(1),
    help="MobileAppCampaign Network strategy ClicksPerWeek",
)
@click.option(
    "--mobile-network-limit-percent",
    type=click.IntRange(10, 100),
    help="MobileAppCampaign NetworkDefault.LimitPercent, 10-100 by tens",
)
@click.option(
    "--dyn-network-weekly-spend-limit",
    type=MICRO_RUBLES,
    help="DynamicTextCampaign Network strategy WeeklySpendLimit in micro-rubles",
)
@click.option(
    "--dyn-network-bid-ceiling",
    type=MICRO_RUBLES,
    help="DynamicTextCampaign Network strategy BidCeiling in micro-rubles",
)
@click.option(
    "--dyn-network-custom-period-spend-limit",
    type=MICRO_RUBLES,
    help="DynamicTextCampaign Network CustomPeriodBudget.SpendLimit in micro-rubles",
)
@click.option(
    "--dyn-network-custom-period-start-date",
    help="DynamicTextCampaign Network CustomPeriodBudget.StartDate",
)
@click.option(
    "--dyn-network-custom-period-end-date",
    help="DynamicTextCampaign Network CustomPeriodBudget.EndDate",
)
@click.option(
    "--dyn-network-custom-period-auto-continue",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="DynamicTextCampaign Network CustomPeriodBudget.AutoContinue: YES or NO",
)
@click.option(
    "--dyn-network-average-cpc",
    type=MICRO_RUBLES,
    help="DynamicTextCampaign Network strategy AverageCpc in micro-rubles",
)
@click.option(
    "--dyn-network-average-cpa",
    type=MICRO_RUBLES,
    help="DynamicTextCampaign Network AverageCpa.AverageCpa in micro-rubles",
)
@click.option(
    "--dyn-network-cpa",
    type=MICRO_RUBLES,
    help="DynamicTextCampaign Network PayForConversion.Cpa in micro-rubles",
)
@click.option(
    "--dyn-network-goal-id",
    type=int,
    help="DynamicTextCampaign Network strategy GoalId (Metrika goal)",
)
@click.option(
    "--dyn-network-crr",
    type=click.IntRange(1, 1000),
    help="DynamicTextCampaign Network Crr percentage (AverageCrr/PayForConversionCrr)",
)
@click.option(
    "--dyn-network-clicks-per-week",
    type=click.IntRange(1),
    help="DynamicTextCampaign Network WeeklyClickPackage.ClicksPerWeek",
)
@click.option(
    "--dyn-network-limit-percent",
    type=click.IntRange(10, 100),
    help="DynamicTextCampaign NetworkDefault.LimitPercent, 10-100 by tens",
)
@click.option(
    "--dyn-network-reserve-return",
    type=click.IntRange(0, 100),
    help="DynamicTextCampaign Network AverageRoi.ReserveReturn percentage (0-100)",
)
@click.option(
    "--dyn-network-roi-coef",
    type=click.IntRange(0),
    help="DynamicTextCampaign Network AverageRoi.RoiCoef",
)
@click.option(
    "--dyn-network-profitability",
    type=click.IntRange(0),
    help="DynamicTextCampaign Network AverageRoi.Profitability",
)
@click.option(
    "--dyn-network-exploration-budget",
    type=MICRO_RUBLES,
    help=(
        "DynamicTextCampaign Network "
        "ExplorationBudget.MinimumExplorationBudget in micro-rubles"
    ),
)
@click.option(
    "--dyn-network-exploration-budget-custom",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=(
        "DynamicTextCampaign Network "
        "ExplorationBudget.IsMinimumExplorationBudgetCustom: YES or NO"
    ),
)
# DynamicTextCampaign.BiddingStrategy.Search typed flags (#362). Mirrors
# DynamicTextCampaignStrategyAddBase (WSDL line 1712-1733) plus
# DynamicTextCampaignSearchStrategyAdd PlacementTypes (line 1741-1752).
@click.option(
    "--dyn-search-weekly-spend-limit",
    type=MICRO_RUBLES,
    help="DynamicTextCampaign Search strategy WeeklySpendLimit in micro-rubles",
)
@click.option(
    "--dyn-search-bid-ceiling",
    type=MICRO_RUBLES,
    help="DynamicTextCampaign Search strategy BidCeiling in micro-rubles",
)
@click.option(
    "--dyn-search-custom-period-spend-limit",
    type=MICRO_RUBLES,
    help="DynamicTextCampaign Search CustomPeriodBudget.SpendLimit in micro-rubles",
)
@click.option(
    "--dyn-search-custom-period-start-date",
    help="DynamicTextCampaign Search CustomPeriodBudget.StartDate",
)
@click.option(
    "--dyn-search-custom-period-end-date",
    help="DynamicTextCampaign Search CustomPeriodBudget.EndDate",
)
@click.option(
    "--dyn-search-custom-period-auto-continue",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="DynamicTextCampaign Search CustomPeriodBudget.AutoContinue: YES or NO",
)
@click.option(
    "--dyn-search-average-cpc",
    type=MICRO_RUBLES,
    help="DynamicTextCampaign Search strategy AverageCpc in micro-rubles",
)
@click.option(
    "--dyn-search-average-cpa",
    type=MICRO_RUBLES,
    help="DynamicTextCampaign Search AverageCpa.AverageCpa in micro-rubles",
)
@click.option(
    "--dyn-search-cpa",
    type=MICRO_RUBLES,
    help="DynamicTextCampaign Search PayForConversion.Cpa in micro-rubles",
)
@click.option(
    "--dyn-search-goal-id",
    type=int,
    help="DynamicTextCampaign Search strategy GoalId (Metrika goal)",
)
@click.option(
    "--dyn-search-crr",
    type=click.IntRange(1, 1000),
    help="DynamicTextCampaign Search Crr percentage (AverageCrr/PayForConversionCrr)",
)
@click.option(
    "--dyn-search-clicks-per-week",
    type=click.IntRange(1),
    help="DynamicTextCampaign Search WeeklyClickPackage.ClicksPerWeek",
)
@click.option(
    "--dyn-search-reserve-return",
    type=click.IntRange(0, 100),
    help="DynamicTextCampaign Search AverageRoi.ReserveReturn percentage (0-100)",
)
@click.option(
    "--dyn-search-roi-coef",
    type=click.IntRange(0),
    help="DynamicTextCampaign Search AverageRoi.RoiCoef",
)
@click.option(
    "--dyn-search-profitability",
    type=click.IntRange(0),
    help="DynamicTextCampaign Search AverageRoi.Profitability",
)
@click.option(
    "--dyn-search-exploration-budget",
    type=MICRO_RUBLES,
    help=(
        "DynamicTextCampaign Search "
        "ExplorationBudget.MinimumExplorationBudget in micro-rubles"
    ),
)
@click.option(
    "--dyn-search-exploration-budget-custom",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=(
        "DynamicTextCampaign Search "
        "ExplorationBudget.IsMinimumExplorationBudgetCustom: YES or NO"
    ),
)
@click.option(
    "--smart-search-average-cpc",
    type=MICRO_RUBLES,
    help=(
        "SmartCampaign Search StrategyAverageCpcPerCampaignAdd.AverageCpc "
        "in micro-rubles (#367)"
    ),
)
@click.option(
    "--smart-search-filter-average-cpc",
    type=MICRO_RUBLES,
    help=(
        "SmartCampaign Search StrategyAverageCpcPerFilterAdd.FilterAverageCpc "
        "in micro-rubles (#367)"
    ),
)
@click.option(
    "--smart-search-average-cpa",
    type=MICRO_RUBLES,
    help=(
        "SmartCampaign Search StrategyAverageCpaPerCampaignAdd.AverageCpa "
        "in micro-rubles (#367)"
    ),
)
@click.option(
    "--smart-search-filter-average-cpa",
    type=MICRO_RUBLES,
    help=(
        "SmartCampaign Search StrategyAverageCpaPerFilterAdd.FilterAverageCpa "
        "in micro-rubles (#367)"
    ),
)
@click.option(
    "--smart-search-cpa",
    type=MICRO_RUBLES,
    help=(
        "SmartCampaign Search PayForConversion[Per{Campaign,Filter}].Cpa "
        "in micro-rubles (#367)"
    ),
)
@click.option(
    "--smart-search-goal-id",
    type=int,
    help="SmartCampaign Search Strategy*Add.GoalId Metrika goal ID (#367)",
)
@click.option(
    "--smart-search-weekly-spend-limit",
    type=MICRO_RUBLES,
    help="SmartCampaign Search Strategy*Add.WeeklySpendLimit in micro-rubles (#367)",
)
@click.option(
    "--smart-search-bid-ceiling",
    type=MICRO_RUBLES,
    help="SmartCampaign Search Strategy*Add.BidCeiling in micro-rubles (#367)",
)
@click.option(
    "--smart-search-reserve-return",
    type=int,
    help="SmartCampaign Search StrategyAverageRoiAdd.ReserveReturn (#367)",
)
@click.option(
    "--smart-search-roi-coef",
    type=MICRO_RUBLES,
    help="SmartCampaign Search StrategyAverageRoiAdd.RoiCoef in micro-rubles (#367)",
)
@click.option(
    "--smart-search-profitability",
    type=MICRO_RUBLES,
    help=(
        "SmartCampaign Search StrategyAverageRoiAdd.Profitability in "
        "micro-rubles (#367)"
    ),
)
@click.option(
    "--smart-search-crr",
    type=int,
    help=(
        "SmartCampaign Search StrategyAverageCrrAdd.Crr / "
        "StrategyPayForConversionCrrAdd.Crr percentage (#367)"
    ),
)
@click.option(
    "--smart-search-cp-spend-limit",
    type=MICRO_RUBLES,
    help=("SmartCampaign Search CustomPeriodBudget.SpendLimit in micro-rubles (#367)"),
)
@click.option(
    "--smart-search-cp-start-date",
    help="SmartCampaign Search CustomPeriodBudget.StartDate (#367)",
)
@click.option(
    "--smart-search-cp-end-date",
    help="SmartCampaign Search CustomPeriodBudget.EndDate (#367)",
)
@click.option(
    "--smart-search-cp-auto-continue",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="SmartCampaign Search CustomPeriodBudget.AutoContinue: YES or NO (#367)",
)
@click.option(
    "--smart-search-exploration-min",
    type=MICRO_RUBLES,
    help=(
        "SmartCampaign Search ExplorationBudget.MinimumExplorationBudget "
        "in micro-rubles (#367)"
    ),
)
@click.option(
    "--smart-search-exploration-min-custom",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=(
        "SmartCampaign Search ExplorationBudget.IsMinimumExplorationBudgetCustom: "
        "YES or NO (#367)"
    ),
)
@click.option(
    "--smart-network-average-cpc",
    type=MICRO_RUBLES,
    help=(
        "SmartCampaign Network StrategyAverageCpcPerCampaignAdd.AverageCpc "
        "in micro-rubles (#368)"
    ),
)
@click.option(
    "--smart-network-filter-average-cpc",
    type=MICRO_RUBLES,
    help=(
        "SmartCampaign Network StrategyAverageCpcPerFilterAdd.FilterAverageCpc "
        "in micro-rubles (#368)"
    ),
)
@click.option(
    "--smart-network-average-cpa",
    type=MICRO_RUBLES,
    help=(
        "SmartCampaign Network StrategyAverageCpaPerCampaignAdd.AverageCpa "
        "in micro-rubles (#368)"
    ),
)
@click.option(
    "--smart-network-filter-average-cpa",
    type=MICRO_RUBLES,
    help=(
        "SmartCampaign Network StrategyAverageCpaPerFilterAdd.FilterAverageCpa "
        "in micro-rubles (#368)"
    ),
)
@click.option(
    "--smart-network-cpa",
    type=MICRO_RUBLES,
    help=(
        "SmartCampaign Network PayForConversion[Per{Campaign,Filter}].Cpa "
        "in micro-rubles (#368)"
    ),
)
@click.option(
    "--smart-network-goal-id",
    type=int,
    help="SmartCampaign Network Strategy*Add.GoalId Metrika goal ID (#368)",
)
@click.option(
    "--smart-network-weekly-spend-limit",
    type=MICRO_RUBLES,
    help="SmartCampaign Network Strategy*Add.WeeklySpendLimit in micro-rubles (#368)",
)
@click.option(
    "--smart-network-bid-ceiling",
    type=MICRO_RUBLES,
    help="SmartCampaign Network Strategy*Add.BidCeiling in micro-rubles (#368)",
)
@click.option(
    "--smart-network-reserve-return",
    type=int,
    help="SmartCampaign Network StrategyAverageRoiAdd.ReserveReturn (#368)",
)
@click.option(
    "--smart-network-roi-coef",
    type=MICRO_RUBLES,
    help="SmartCampaign Network StrategyAverageRoiAdd.RoiCoef in micro-rubles (#368)",
)
@click.option(
    "--smart-network-profitability",
    type=MICRO_RUBLES,
    help=(
        "SmartCampaign Network StrategyAverageRoiAdd.Profitability in "
        "micro-rubles (#368)"
    ),
)
@click.option(
    "--smart-network-crr",
    type=int,
    help=(
        "SmartCampaign Network StrategyAverageCrrAdd.Crr / "
        "StrategyPayForConversionCrrAdd.Crr percentage (#368)"
    ),
)
@click.option(
    "--smart-network-limit-percent",
    type=click.IntRange(10, 100),
    help=(
        "SmartCampaign Network StrategyNetworkDefaultAdd.LimitPercent, "
        "10-100 by tens (#368)"
    ),
)
@click.option(
    "--smart-network-cp-spend-limit",
    type=MICRO_RUBLES,
    help=("SmartCampaign Network CustomPeriodBudget.SpendLimit in micro-rubles (#368)"),
)
@click.option(
    "--smart-network-cp-start-date",
    help="SmartCampaign Network CustomPeriodBudget.StartDate (#368)",
)
@click.option(
    "--smart-network-cp-end-date",
    help="SmartCampaign Network CustomPeriodBudget.EndDate (#368)",
)
@click.option(
    "--smart-network-cp-auto-continue",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="SmartCampaign Network CustomPeriodBudget.AutoContinue: YES or NO (#368)",
)
@click.option(
    "--smart-network-exploration-min",
    type=MICRO_RUBLES,
    help=(
        "SmartCampaign Network ExplorationBudget.MinimumExplorationBudget "
        "in micro-rubles (#368)"
    ),
)
@click.option(
    "--smart-network-exploration-min-custom",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=(
        "SmartCampaign Network ExplorationBudget.IsMinimumExplorationBudgetCustom: "
        "YES or NO (#368)"
    ),
)
@click.option(
    "--average-cpa",
    type=MICRO_RUBLES,
    help="Target CPA in micro-rubles (AVERAGE_CPA)",
)
@click.option(
    "--crr",
    type=int,
    help=(
        "CRR (cost revenue ratio) percentage for "
        "PAY_FOR_CONVERSION_CRR — WSDL StrategyPayForConversionCrrAdd.Crr"
    ),
)
@click.option(
    "--bid-ceiling",
    type=MICRO_RUBLES,
    help="Bid ceiling in micro-rubles for the chosen CPA strategy",
)
@click.option(
    "--text-search-weekly-spend-limit",
    type=MICRO_RUBLES,
    help="TextCampaign Search strategy WeeklySpendLimit in micro-rubles",
)
@click.option(
    "--text-search-custom-period-spend-limit",
    type=MICRO_RUBLES,
    help="TextCampaign Search CustomPeriodBudget.SpendLimit in micro-rubles",
)
@click.option(
    "--text-search-custom-period-start-date",
    help="TextCampaign Search CustomPeriodBudget.StartDate",
)
@click.option(
    "--text-search-custom-period-end-date",
    help="TextCampaign Search CustomPeriodBudget.EndDate",
)
@click.option(
    "--text-search-custom-period-auto-continue",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="TextCampaign Search CustomPeriodBudget.AutoContinue: YES or NO",
)
@click.option(
    "--text-search-average-cpc",
    type=MICRO_RUBLES,
    help="TextCampaign Search strategy AverageCpc in micro-rubles",
)
@click.option(
    "--text-search-pay-cpa",
    type=MICRO_RUBLES,
    help="TextCampaign Search StrategyPayForConversionAdd.Cpa in micro-rubles",
)
@click.option(
    "--text-search-clicks-per-week",
    type=click.IntRange(1),
    help="TextCampaign Search WEEKLY_CLICK_PACKAGE ClicksPerWeek",
)
@click.option(
    "--text-search-reserve-return",
    type=click.IntRange(0, 100),
    help=(
        "TextCampaign Search AVERAGE_ROI ReserveReturn percentage "
        "(0-100, multiple of 10)"
    ),
)
@click.option(
    "--text-search-roi-coef",
    type=MICRO_RUBLES,
    help=(
        "TextCampaign Search AVERAGE_ROI RoiCoef as a ratio (sales profit "
        "/ promotion costs), supplied directly in micro-rubles wire format "
        "(e.g. a 1.0 ratio is 1000000)."
    ),
)
@click.option(
    "--text-search-profitability",
    type=MICRO_RUBLES,
    help=(
        "TextCampaign Search AVERAGE_ROI Profitability percentage, "
        "supplied directly in micro-rubles wire format "
        "(e.g. 20% is 20000000)."
    ),
)
@click.option(
    "--text-search-exploration-min-budget",
    type=MICRO_RUBLES,
    help="TextCampaign Search ExplorationBudget.MinimumExplorationBudget in micro-rubles",
)
@click.option(
    "--text-search-exploration-is-custom",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=(
        "TextCampaign Search ExplorationBudget."
        "IsMinimumExplorationBudgetCustom: YES or NO"
    ),
)
# UnifiedCampaign.BiddingStrategy.Search typed flags (issue #363). Mirrors
# the TextCampaign Search flag set (#361/#388) plus two extra PlacementTypes
# fields declared only by UnifiedCampaignSearchStrategyPlacementTypes
# (WSDL tests/wsdl_cache/campaigns.xml L172-180 and L636-644). UnifiedCampaign
# does NOT carry WeeklyClickPackage / AverageRoi subtypes (WSDL L1631-1654),
# so the corresponding clicks-per-week / reserve-return / roi-coef /
# profitability flags are intentionally absent.
@click.option(
    "--unified-search-placement-maps",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="UnifiedCampaign Search PlacementTypes.Maps (#363)",
)
@click.option(
    "--unified-search-placement-search-organization-list",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=("UnifiedCampaign Search PlacementTypes.SearchOrganizationList (#363)"),
)
@click.option(
    "--unified-search-weekly-spend-limit",
    type=MICRO_RUBLES,
    help="UnifiedCampaign Search strategy WeeklySpendLimit in micro-rubles (#363)",
)
@click.option(
    "--unified-search-custom-period-spend-limit",
    type=MICRO_RUBLES,
    help="UnifiedCampaign Search CustomPeriodBudget.SpendLimit in micro-rubles (#363)",
)
@click.option(
    "--unified-search-custom-period-start-date",
    help="UnifiedCampaign Search CustomPeriodBudget.StartDate (#363)",
)
@click.option(
    "--unified-search-custom-period-end-date",
    help="UnifiedCampaign Search CustomPeriodBudget.EndDate (#363)",
)
@click.option(
    "--unified-search-custom-period-auto-continue",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="UnifiedCampaign Search CustomPeriodBudget.AutoContinue: YES or NO (#363)",
)
@click.option(
    "--unified-search-average-cpc",
    type=MICRO_RUBLES,
    help="UnifiedCampaign Search strategy AverageCpc in micro-rubles (#363)",
)
@click.option(
    "--unified-search-pay-cpa",
    type=MICRO_RUBLES,
    help="UnifiedCampaign Search StrategyPayForConversionAdd.Cpa in micro-rubles (#363)",
)
@click.option(
    "--unified-search-exploration-min-budget",
    type=MICRO_RUBLES,
    help=(
        "UnifiedCampaign Search ExplorationBudget.MinimumExplorationBudget "
        "in micro-rubles (#363)"
    ),
)
@click.option(
    "--unified-search-exploration-is-custom",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=(
        "UnifiedCampaign Search ExplorationBudget."
        "IsMinimumExplorationBudgetCustom: YES or NO (#363)"
    ),
)
@click.option(
    "--text-network-weekly-spend-limit",
    type=MICRO_RUBLES,
    help="TextCampaign Network strategy WeeklySpendLimit in micro-rubles (#364)",
)
@click.option(
    "--text-network-custom-period-spend-limit",
    type=MICRO_RUBLES,
    help="TextCampaign Network CustomPeriodBudget.SpendLimit in micro-rubles (#364)",
)
@click.option(
    "--text-network-custom-period-start-date",
    help="TextCampaign Network CustomPeriodBudget.StartDate (#364)",
)
@click.option(
    "--text-network-custom-period-end-date",
    help="TextCampaign Network CustomPeriodBudget.EndDate (#364)",
)
@click.option(
    "--text-network-custom-period-auto-continue",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=("TextCampaign Network CustomPeriodBudget.AutoContinue: YES or NO (#364)"),
)
@click.option(
    "--text-network-average-cpc",
    type=MICRO_RUBLES,
    help="TextCampaign Network strategy AverageCpc in micro-rubles (#364)",
)
@click.option(
    "--text-network-pay-cpa",
    type=MICRO_RUBLES,
    help="TextCampaign Network StrategyPayForConversionAdd.Cpa in micro-rubles (#364)",
)
@click.option(
    "--text-network-clicks-per-week",
    type=click.IntRange(1),
    help="TextCampaign Network WEEKLY_CLICK_PACKAGE ClicksPerWeek (#364)",
)
@click.option(
    "--text-network-reserve-return",
    type=click.IntRange(0, 100),
    help=(
        "TextCampaign Network AVERAGE_ROI ReserveReturn percentage "
        "(0-100, multiple of 10) (#364)"
    ),
)
@click.option(
    "--text-network-roi-coef",
    type=MICRO_RUBLES,
    help=(
        "TextCampaign Network AVERAGE_ROI RoiCoef as a ratio (sales profit "
        "/ promotion costs), supplied directly in micro-rubles wire format "
        "(e.g. a 1.0 ratio is 1000000) (#364)."
    ),
)
@click.option(
    "--text-network-profitability",
    type=MICRO_RUBLES,
    help=(
        "TextCampaign Network AVERAGE_ROI Profitability percentage, "
        "supplied directly in micro-rubles wire format "
        "(e.g. 20% is 20000000) (#364)."
    ),
)
@click.option(
    "--text-network-exploration-min-budget",
    type=MICRO_RUBLES,
    help=(
        "TextCampaign Network ExplorationBudget.MinimumExplorationBudget "
        "in micro-rubles (#364)"
    ),
)
@click.option(
    "--text-network-exploration-is-custom",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=(
        "TextCampaign Network ExplorationBudget."
        "IsMinimumExplorationBudgetCustom: YES or NO (#364)"
    ),
)
@click.option(
    "--text-network-limit-percent",
    type=click.IntRange(10, 100),
    help=("TextCampaign Network NetworkDefault.LimitPercent, 10-100 by tens (#364)"),
)
# UnifiedCampaign.BiddingStrategy.Network typed flags (#366). Mirrors
# UnifiedCampaignStrategyAddBase (WSDL line 1631-1654) — 10 settable
# Strategy*Add subtypes; the WSDL has NO AverageRoi / WeeklyClickPackage /
# NetworkDefault subtype on Unified.Network, unlike TextCampaign.Network.
@click.option(
    "--unified-network-weekly-spend-limit",
    type=MICRO_RUBLES,
    help="UnifiedCampaign Network strategy WeeklySpendLimit in micro-rubles (#366)",
)
@click.option(
    "--unified-network-custom-period-spend-limit",
    type=MICRO_RUBLES,
    help="UnifiedCampaign Network CustomPeriodBudget.SpendLimit in micro-rubles (#366)",
)
@click.option(
    "--unified-network-custom-period-start-date",
    help="UnifiedCampaign Network CustomPeriodBudget.StartDate (#366)",
)
@click.option(
    "--unified-network-custom-period-end-date",
    help="UnifiedCampaign Network CustomPeriodBudget.EndDate (#366)",
)
@click.option(
    "--unified-network-custom-period-auto-continue",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=("UnifiedCampaign Network CustomPeriodBudget.AutoContinue: YES or NO (#366)"),
)
@click.option(
    "--unified-network-average-cpc",
    type=MICRO_RUBLES,
    help="UnifiedCampaign Network StrategyAverageCpcAdd.AverageCpc in micro-rubles (#366)",
)
@click.option(
    "--unified-network-cpa",
    type=MICRO_RUBLES,
    help=(
        "UnifiedCampaign Network StrategyPayForConversionAdd.Cpa in micro-rubles (#366)"
    ),
)
@click.option(
    "--unified-network-exploration-min-budget",
    type=MICRO_RUBLES,
    help=(
        "UnifiedCampaign Network ExplorationBudget.MinimumExplorationBudget "
        "in micro-rubles (#366)"
    ),
)
@click.option(
    "--unified-network-exploration-is-custom",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=(
        "UnifiedCampaign Network ExplorationBudget."
        "IsMinimumExplorationBudgetCustom: YES or NO (#366)"
    ),
)
@click.option(
    "--notification",
    default=None,
    expose_value=False,
    callback=_deprecated_campaigns_structured_option,
    is_eager=True,
    hidden=True,
    help="Removed: use typed Notification flags",
)
@click.option(
    "--time-targeting",
    default=None,
    expose_value=False,
    callback=_deprecated_campaigns_structured_option,
    is_eager=True,
    hidden=True,
    help="Removed: use typed TimeTargeting flags",
)
@click.option(
    "--client-info",
    help="CampaignBase.ClientInfo client name, max 255 characters",
)
@click.option(
    "--sms-events",
    help="Comma-separated Notification.SmsSettings.Events values",
)
@click.option("--sms-time-from", help="Notification.SmsSettings.TimeFrom")
@click.option("--sms-time-to", help="Notification.SmsSettings.TimeTo")
@click.option("--notification-email", help="Notification.EmailSettings.Email")
@click.option(
    "--notification-check-position-interval",
    type=click.Choice(["15", "30", "60"]),
    help="Notification.EmailSettings.CheckPositionInterval",
)
@click.option(
    "--notification-warning-balance",
    type=click.IntRange(1, 50),
    help="Notification.EmailSettings.WarningBalance",
)
@click.option(
    "--notification-send-account-news",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="Notification.EmailSettings.SendAccountNews: YES or NO",
)
@click.option(
    "--notification-send-warnings",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="Notification.EmailSettings.SendWarnings: YES or NO",
)
@click.option("--time-zone", help="CampaignBase.TimeZone")
@click.option("--negative-keywords", help="Comma-separated NegativeKeywords.Items")
@click.option("--blocked-ips", help="Comma-separated BlockedIps.Items")
@click.option("--excluded-sites", help="Comma-separated ExcludedSites.Items")
@click.option(
    "--time-targeting-schedule",
    multiple=True,
    help="Repeatable TimeTargeting.Schedule.Items row",
)
@click.option(
    "--consider-working-weekends",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="TimeTargeting.ConsiderWorkingWeekends: YES or NO",
)
@click.option(
    "--holidays-suspend-on-holidays",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="TimeTargeting.HolidaysSchedule.SuspendOnHolidays: YES or NO",
)
@click.option(
    "--holidays-bid-percent",
    type=click.IntRange(0, 200),
    help="TimeTargeting.HolidaysSchedule.BidPercent",
)
@click.option(
    "--holidays-start-hour",
    type=click.IntRange(0, 23),
    help="TimeTargeting.HolidaysSchedule.StartHour",
)
@click.option(
    "--holidays-end-hour",
    type=click.IntRange(0, 24),
    help="TimeTargeting.HolidaysSchedule.EndHour",
)
@click.option(
    "--tracking-params",
    "tracking_params",
    help=(
        "Tracking params query-string for "
        "TextCampaign/UnifiedCampaign/DynamicTextCampaign/SmartCampaign."
        "TrackingParams "
        '(e.g. "utm_source=direct&utm_campaign={campaign_id}")'
    ),
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def add(
    ctx,
    name,
    start_date,
    campaign_type,
    budget,
    end_date,
    settings,
    search_strategy,
    network_strategy,
    search_placement_search_results,
    search_placement_product_gallery,
    search_placement_dynamic_places,
    filter_average_cpc,
    counter_id,
    counter_ids,
    dynamic_placement_search_results,
    dynamic_placement_product_gallery,
    goal_id,
    priority_goals,
    relevant_keywords_budget_percent,
    relevant_keywords_mode,
    relevant_keywords_optimize_goal_id,
    attribution_model,
    package_strategy_id,
    package_strategy_from_campaign_id,
    package_platform_search,
    package_platform_search_result,
    package_platform_product_gallery,
    package_platform_maps,
    package_platform_search_organization_list,
    package_platform_network,
    package_platform_dynamic_places,
    negative_keyword_shared_set_ids,
    frequency_cap_impressions,
    frequency_cap_period_days,
    frequency_cap_period_all,
    video_target,
    average_cpm,
    average_cpv,
    strategy_spend_limit,
    strategy_start_date,
    strategy_end_date,
    strategy_auto_continue,
    mobile_search_weekly_spend_limit,
    mobile_search_bid_ceiling,
    mobile_search_custom_period_spend_limit,
    mobile_search_custom_period_start_date,
    mobile_search_custom_period_end_date,
    mobile_search_custom_period_auto_continue,
    mobile_search_average_cpc,
    mobile_search_average_cpi,
    mobile_search_clicks_per_week,
    mobile_network_weekly_spend_limit,
    mobile_network_bid_ceiling,
    mobile_network_custom_period_spend_limit,
    mobile_network_custom_period_start_date,
    mobile_network_custom_period_end_date,
    mobile_network_custom_period_auto_continue,
    mobile_network_average_cpc,
    mobile_network_average_cpi,
    mobile_network_clicks_per_week,
    mobile_network_limit_percent,
    dyn_network_weekly_spend_limit,
    dyn_network_bid_ceiling,
    dyn_network_custom_period_spend_limit,
    dyn_network_custom_period_start_date,
    dyn_network_custom_period_end_date,
    dyn_network_custom_period_auto_continue,
    dyn_network_average_cpc,
    dyn_network_average_cpa,
    dyn_network_cpa,
    dyn_network_goal_id,
    dyn_network_crr,
    dyn_network_clicks_per_week,
    dyn_network_limit_percent,
    dyn_network_reserve_return,
    dyn_network_roi_coef,
    dyn_network_profitability,
    dyn_network_exploration_budget,
    dyn_network_exploration_budget_custom,
    dyn_search_weekly_spend_limit,
    dyn_search_bid_ceiling,
    dyn_search_custom_period_spend_limit,
    dyn_search_custom_period_start_date,
    dyn_search_custom_period_end_date,
    dyn_search_custom_period_auto_continue,
    dyn_search_average_cpc,
    dyn_search_average_cpa,
    dyn_search_cpa,
    dyn_search_goal_id,
    dyn_search_crr,
    dyn_search_clicks_per_week,
    dyn_search_reserve_return,
    dyn_search_roi_coef,
    dyn_search_profitability,
    dyn_search_exploration_budget,
    dyn_search_exploration_budget_custom,
    smart_search_average_cpc,
    smart_search_filter_average_cpc,
    smart_search_average_cpa,
    smart_search_filter_average_cpa,
    smart_search_cpa,
    smart_search_goal_id,
    smart_search_weekly_spend_limit,
    smart_search_bid_ceiling,
    smart_search_reserve_return,
    smart_search_roi_coef,
    smart_search_profitability,
    smart_search_crr,
    smart_search_cp_spend_limit,
    smart_search_cp_start_date,
    smart_search_cp_end_date,
    smart_search_cp_auto_continue,
    smart_search_exploration_min,
    smart_search_exploration_min_custom,
    smart_network_average_cpc,
    smart_network_filter_average_cpc,
    smart_network_average_cpa,
    smart_network_filter_average_cpa,
    smart_network_cpa,
    smart_network_goal_id,
    smart_network_weekly_spend_limit,
    smart_network_bid_ceiling,
    smart_network_reserve_return,
    smart_network_roi_coef,
    smart_network_profitability,
    smart_network_crr,
    smart_network_limit_percent,
    smart_network_cp_spend_limit,
    smart_network_cp_start_date,
    smart_network_cp_end_date,
    smart_network_cp_auto_continue,
    smart_network_exploration_min,
    smart_network_exploration_min_custom,
    average_cpa,
    crr,
    bid_ceiling,
    text_search_weekly_spend_limit,
    text_search_custom_period_spend_limit,
    text_search_custom_period_start_date,
    text_search_custom_period_end_date,
    text_search_custom_period_auto_continue,
    text_search_average_cpc,
    text_search_pay_cpa,
    text_search_clicks_per_week,
    text_search_reserve_return,
    text_search_roi_coef,
    text_search_profitability,
    text_search_exploration_min_budget,
    text_search_exploration_is_custom,
    unified_search_placement_maps,
    unified_search_placement_search_organization_list,
    unified_search_weekly_spend_limit,
    unified_search_custom_period_spend_limit,
    unified_search_custom_period_start_date,
    unified_search_custom_period_end_date,
    unified_search_custom_period_auto_continue,
    unified_search_average_cpc,
    unified_search_pay_cpa,
    unified_search_exploration_min_budget,
    unified_search_exploration_is_custom,
    text_network_weekly_spend_limit,
    text_network_custom_period_spend_limit,
    text_network_custom_period_start_date,
    text_network_custom_period_end_date,
    text_network_custom_period_auto_continue,
    text_network_average_cpc,
    text_network_pay_cpa,
    text_network_clicks_per_week,
    text_network_reserve_return,
    text_network_roi_coef,
    text_network_profitability,
    text_network_exploration_min_budget,
    text_network_exploration_is_custom,
    text_network_limit_percent,
    unified_network_weekly_spend_limit,
    unified_network_custom_period_spend_limit,
    unified_network_custom_period_start_date,
    unified_network_custom_period_end_date,
    unified_network_custom_period_auto_continue,
    unified_network_average_cpc,
    unified_network_cpa,
    unified_network_exploration_min_budget,
    unified_network_exploration_is_custom,
    client_info,
    sms_events,
    sms_time_from,
    sms_time_to,
    notification_email,
    notification_check_position_interval,
    notification_warning_balance,
    notification_send_account_news,
    notification_send_warnings,
    time_zone,
    negative_keywords,
    blocked_ips,
    excluded_sites,
    time_targeting_schedule,
    consider_working_weekends,
    holidays_suspend_on_holidays,
    holidays_bid_percent,
    holidays_start_hour,
    holidays_end_hour,
    tracking_params,
    dry_run,
):
    """Add new campaign"""
    campaign_type_norm = (campaign_type or "TEXT_CAMPAIGN").upper().replace("-", "_")
    supported_types = {
        "TEXT_CAMPAIGN",
        "UNIFIED_CAMPAIGN",
        "DYNAMIC_TEXT_CAMPAIGN",
        "SMART_CAMPAIGN",
        "MOBILE_APP_CAMPAIGN",
        "CPM_BANNER_CAMPAIGN",
    }
    if campaign_type_norm not in supported_types:
        raise click.UsageError(
            t(
                "Invalid value for '--type': {campaign_type!r} is not one of 'TEXT_CAMPAIGN', 'UNIFIED_CAMPAIGN', 'DYNAMIC_TEXT_CAMPAIGN', 'SMART_CAMPAIGN', 'MOBILE_APP_CAMPAIGN', 'CPM_BANNER_CAMPAIGN'."
            ).format(campaign_type=campaign_type)
        )

    # Shared flags for TextCampaign / DynamicTextCampaign:
    # WSDL CounterIds, PriorityGoals, AverageCpa, BidCeiling, GoalId
    # are declared on both AddItems (CounterIds on
    # TextCampaign/DynamicTextCampaign, AverageCpa/GoalId/BidCeiling
    # inside Strategy*Add subtypes). SmartCampaign carries
    # singular CounterId only (no CounterIds, no PriorityGoals on
    # SmartCampaignAddItem.PriorityGoals path is allowed too, but
    # SmartCampaignStrategyAdd.AverageCpa lives via
    # AverageCpaPerCampaign/AverageCpaPerFilter — out of scope here).
    text_dynamic_extras = {
        "--counter-ids",
        "--goal-id",
        "--priority-goals",
        "--average-cpa",
        "--crr",
        "--bid-ceiling",
    }
    # TextCampaign Search strategy detail flags (issue #361). Only
    # accepted under --type TEXT_CAMPAIGN; other campaign types must
    # reject them as silent-data-loss invariants.
    text_search_extras = {
        "--text-search-weekly-spend-limit",
        "--text-search-custom-period-spend-limit",
        "--text-search-custom-period-start-date",
        "--text-search-custom-period-end-date",
        "--text-search-custom-period-auto-continue",
        "--text-search-average-cpc",
        "--text-search-pay-cpa",
        "--text-search-clicks-per-week",
        "--text-search-reserve-return",
        "--text-search-roi-coef",
        "--text-search-profitability",
        "--text-search-exploration-min-budget",
        "--text-search-exploration-is-custom",
    }
    # TextCampaign Network strategy detail flags (issue #364). Only
    # accepted under --type TEXT_CAMPAIGN; other campaign types must
    # reject them as silent-data-loss invariants.
    text_network_extras = {
        "--text-network-weekly-spend-limit",
        "--text-network-custom-period-spend-limit",
        "--text-network-custom-period-start-date",
        "--text-network-custom-period-end-date",
        "--text-network-custom-period-auto-continue",
        "--text-network-average-cpc",
        "--text-network-pay-cpa",
        "--text-network-clicks-per-week",
        "--text-network-reserve-return",
        "--text-network-roi-coef",
        "--text-network-profitability",
        "--text-network-exploration-min-budget",
        "--text-network-exploration-is-custom",
        "--text-network-limit-percent",
    }
    allowed_flags_by_type = {
        "TEXT_CAMPAIGN": {
            "--setting",
            "--search-strategy",
            "--network-strategy",
            "--search-placement-search-results",
            "--search-placement-product-gallery",
            "--search-placement-dynamic-places",
            "--tracking-params",
            "--relevant-keywords-budget-percent",
            "--relevant-keywords-mode",
            "--relevant-keywords-optimize-goal-id",
            "--attribution-model",
            "--package-strategy-id",
            "--package-strategy-from-campaign-id",
            "--package-platform-search-result",
            "--package-platform-product-gallery",
            "--package-platform-network",
            "--package-platform-dynamic-places",
            "--negative-keyword-shared-set-ids",
        }
        | text_dynamic_extras
        | text_search_extras
        | text_network_extras,
        "UNIFIED_CAMPAIGN": {
            "--setting",
            "--counter-ids",
            "--priority-goals",
            "--tracking-params",
            "--attribution-model",
            "--package-strategy-id",
            "--package-strategy-from-campaign-id",
            "--package-platform-search-result",
            "--package-platform-product-gallery",
            "--package-platform-maps",
            "--package-platform-search-organization-list",
            "--package-platform-network",
            "--package-platform-dynamic-places",
            "--negative-keyword-shared-set-ids",
            # UnifiedCampaign.BiddingStrategy.Network typed flags (#366).
            "--network-strategy",
            "--unified-network-weekly-spend-limit",
            "--unified-network-custom-period-spend-limit",
            "--unified-network-custom-period-start-date",
            "--unified-network-custom-period-end-date",
            "--unified-network-custom-period-auto-continue",
            "--unified-network-average-cpc",
            "--unified-network-cpa",
            "--unified-network-exploration-min-budget",
            "--unified-network-exploration-is-custom",
            # UnifiedCampaign.BiddingStrategy.Search typed flags (#363).
            "--search-strategy",
            "--search-placement-search-results",
            "--search-placement-product-gallery",
            "--search-placement-dynamic-places",
            # Shared legacy CPA flags routed to Unified.Network/Search.
            "--goal-id",
            "--average-cpa",
            "--crr",
            "--bid-ceiling",
            "--unified-search-placement-maps",
            "--unified-search-placement-search-organization-list",
            "--unified-search-weekly-spend-limit",
            "--unified-search-custom-period-spend-limit",
            "--unified-search-custom-period-start-date",
            "--unified-search-custom-period-end-date",
            "--unified-search-custom-period-auto-continue",
            "--unified-search-average-cpc",
            "--unified-search-pay-cpa",
            "--unified-search-exploration-min-budget",
            "--unified-search-exploration-is-custom",
        },
        "DYNAMIC_TEXT_CAMPAIGN": {
            "--setting",
            "--search-strategy",
            "--network-strategy",
            "--search-placement-search-results",
            "--search-placement-product-gallery",
            "--search-placement-dynamic-places",
            "--tracking-params",
            "--dynamic-placement-search-results",
            "--dynamic-placement-product-gallery",
            "--attribution-model",
            "--package-strategy-id",
            "--package-strategy-from-campaign-id",
            "--negative-keyword-shared-set-ids",
            # DynamicTextCampaign.BiddingStrategy.Network typed flags (#365).
            "--dyn-network-weekly-spend-limit",
            "--dyn-network-bid-ceiling",
            "--dyn-network-custom-period-spend-limit",
            "--dyn-network-custom-period-start-date",
            "--dyn-network-custom-period-end-date",
            "--dyn-network-custom-period-auto-continue",
            "--dyn-network-average-cpc",
            "--dyn-network-average-cpa",
            "--dyn-network-cpa",
            "--dyn-network-goal-id",
            "--dyn-network-crr",
            "--dyn-network-clicks-per-week",
            "--dyn-network-limit-percent",
            "--dyn-network-reserve-return",
            "--dyn-network-roi-coef",
            "--dyn-network-profitability",
            "--dyn-network-exploration-budget",
            "--dyn-network-exploration-budget-custom",
            # DynamicTextCampaign.BiddingStrategy.Search typed flags (#362).
            "--dyn-search-weekly-spend-limit",
            "--dyn-search-bid-ceiling",
            "--dyn-search-custom-period-spend-limit",
            "--dyn-search-custom-period-start-date",
            "--dyn-search-custom-period-end-date",
            "--dyn-search-custom-period-auto-continue",
            "--dyn-search-average-cpc",
            "--dyn-search-average-cpa",
            "--dyn-search-cpa",
            "--dyn-search-goal-id",
            "--dyn-search-crr",
            "--dyn-search-clicks-per-week",
            "--dyn-search-reserve-return",
            "--dyn-search-roi-coef",
            "--dyn-search-profitability",
            "--dyn-search-exploration-budget",
            "--dyn-search-exploration-budget-custom",
        }
        | text_dynamic_extras,
        "SMART_CAMPAIGN": {
            "--setting",
            "--search-strategy",
            "--network-strategy",
            "--filter-average-cpc",
            "--counter-id",
            "--priority-goals",
            "--tracking-params",
            "--attribution-model",
            "--package-strategy-id",
            "--package-strategy-from-campaign-id",
            "--package-platform-search",
            "--package-platform-network",
            # SmartCampaign.BiddingStrategy.Search typed flags (#367)
            "--smart-search-average-cpc",
            "--smart-search-filter-average-cpc",
            "--smart-search-average-cpa",
            "--smart-search-filter-average-cpa",
            "--smart-search-cpa",
            "--smart-search-goal-id",
            "--smart-search-weekly-spend-limit",
            "--smart-search-bid-ceiling",
            "--smart-search-reserve-return",
            "--smart-search-roi-coef",
            "--smart-search-profitability",
            "--smart-search-crr",
            "--smart-search-cp-spend-limit",
            "--smart-search-cp-start-date",
            "--smart-search-cp-end-date",
            "--smart-search-cp-auto-continue",
            "--smart-search-exploration-min",
            "--smart-search-exploration-min-custom",
            # SmartCampaign.BiddingStrategy.Network typed flags (#368)
            "--smart-network-average-cpc",
            "--smart-network-filter-average-cpc",
            "--smart-network-average-cpa",
            "--smart-network-filter-average-cpa",
            "--smart-network-cpa",
            "--smart-network-goal-id",
            "--smart-network-weekly-spend-limit",
            "--smart-network-bid-ceiling",
            "--smart-network-reserve-return",
            "--smart-network-roi-coef",
            "--smart-network-profitability",
            "--smart-network-crr",
            "--smart-network-limit-percent",
            "--smart-network-cp-spend-limit",
            "--smart-network-cp-start-date",
            "--smart-network-cp-end-date",
            "--smart-network-cp-auto-continue",
            "--smart-network-exploration-min",
            "--smart-network-exploration-min-custom",
        },
        "MOBILE_APP_CAMPAIGN": {
            "--setting",
            "--search-strategy",
            "--network-strategy",
            "--mobile-search-weekly-spend-limit",
            "--mobile-search-bid-ceiling",
            "--mobile-search-custom-period-spend-limit",
            "--mobile-search-custom-period-start-date",
            "--mobile-search-custom-period-end-date",
            "--mobile-search-custom-period-auto-continue",
            "--mobile-search-average-cpc",
            "--mobile-search-average-cpi",
            "--mobile-search-clicks-per-week",
            "--mobile-network-weekly-spend-limit",
            "--mobile-network-bid-ceiling",
            "--mobile-network-custom-period-spend-limit",
            "--mobile-network-custom-period-start-date",
            "--mobile-network-custom-period-end-date",
            "--mobile-network-custom-period-auto-continue",
            "--mobile-network-average-cpc",
            "--mobile-network-average-cpi",
            "--mobile-network-clicks-per-week",
            "--mobile-network-limit-percent",
            "--negative-keyword-shared-set-ids",
        },
        "CPM_BANNER_CAMPAIGN": {
            "--setting",
            "--counter-ids",
            "--frequency-cap-impressions",
            "--frequency-cap-period-days",
            "--frequency-cap-period-all",
            "--video-target",
            "--search-strategy",
            "--network-strategy",
            "--average-cpm",
            "--average-cpv",
            "--strategy-spend-limit",
            "--strategy-start-date",
            "--strategy-end-date",
            "--strategy-auto-continue",
        },
    }
    reject_incompatible_flags(
        allowed_flags_by_type[campaign_type_norm],
        {
            "--setting": list(settings) or None,
            "--search-strategy": search_strategy,
            "--network-strategy": network_strategy,
            "--search-placement-search-results": search_placement_search_results,
            "--search-placement-product-gallery": (search_placement_product_gallery),
            "--search-placement-dynamic-places": search_placement_dynamic_places,
            "--filter-average-cpc": filter_average_cpc,
            "--counter-id": counter_id,
            "--counter-ids": counter_ids,
            "--dynamic-placement-search-results": dynamic_placement_search_results,
            "--dynamic-placement-product-gallery": (dynamic_placement_product_gallery),
            "--goal-id": goal_id,
            "--priority-goals": priority_goals,
            "--relevant-keywords-budget-percent": relevant_keywords_budget_percent,
            "--relevant-keywords-mode": relevant_keywords_mode,
            "--relevant-keywords-optimize-goal-id": (
                relevant_keywords_optimize_goal_id
            ),
            "--attribution-model": attribution_model,
            "--package-strategy-id": package_strategy_id,
            "--package-strategy-from-campaign-id": (package_strategy_from_campaign_id),
            "--package-platform-search": package_platform_search,
            "--package-platform-search-result": package_platform_search_result,
            "--package-platform-product-gallery": (package_platform_product_gallery),
            "--package-platform-maps": package_platform_maps,
            "--package-platform-search-organization-list": (
                package_platform_search_organization_list
            ),
            "--package-platform-network": package_platform_network,
            "--package-platform-dynamic-places": package_platform_dynamic_places,
            "--negative-keyword-shared-set-ids": negative_keyword_shared_set_ids,
            "--frequency-cap-impressions": frequency_cap_impressions,
            "--frequency-cap-period-days": frequency_cap_period_days,
            "--frequency-cap-period-all": frequency_cap_period_all or None,
            "--video-target": video_target,
            "--average-cpm": average_cpm,
            "--average-cpv": average_cpv,
            "--strategy-spend-limit": strategy_spend_limit,
            "--strategy-start-date": strategy_start_date,
            "--strategy-end-date": strategy_end_date,
            "--strategy-auto-continue": strategy_auto_continue,
            "--mobile-search-weekly-spend-limit": (mobile_search_weekly_spend_limit),
            "--mobile-search-bid-ceiling": mobile_search_bid_ceiling,
            "--mobile-search-custom-period-spend-limit": (
                mobile_search_custom_period_spend_limit
            ),
            "--mobile-search-custom-period-start-date": (
                mobile_search_custom_period_start_date
            ),
            "--mobile-search-custom-period-end-date": (
                mobile_search_custom_period_end_date
            ),
            "--mobile-search-custom-period-auto-continue": (
                mobile_search_custom_period_auto_continue
            ),
            "--mobile-search-average-cpc": mobile_search_average_cpc,
            "--mobile-search-average-cpi": mobile_search_average_cpi,
            "--mobile-search-clicks-per-week": mobile_search_clicks_per_week,
            "--mobile-network-weekly-spend-limit": (mobile_network_weekly_spend_limit),
            "--mobile-network-bid-ceiling": mobile_network_bid_ceiling,
            "--mobile-network-custom-period-spend-limit": (
                mobile_network_custom_period_spend_limit
            ),
            "--mobile-network-custom-period-start-date": (
                mobile_network_custom_period_start_date
            ),
            "--mobile-network-custom-period-end-date": (
                mobile_network_custom_period_end_date
            ),
            "--mobile-network-custom-period-auto-continue": (
                mobile_network_custom_period_auto_continue
            ),
            "--mobile-network-average-cpc": mobile_network_average_cpc,
            "--mobile-network-average-cpi": mobile_network_average_cpi,
            "--mobile-network-clicks-per-week": mobile_network_clicks_per_week,
            "--mobile-network-limit-percent": mobile_network_limit_percent,
            "--dyn-network-weekly-spend-limit": dyn_network_weekly_spend_limit,
            "--dyn-network-bid-ceiling": dyn_network_bid_ceiling,
            "--dyn-network-custom-period-spend-limit": (
                dyn_network_custom_period_spend_limit
            ),
            "--dyn-network-custom-period-start-date": (
                dyn_network_custom_period_start_date
            ),
            "--dyn-network-custom-period-end-date": (
                dyn_network_custom_period_end_date
            ),
            "--dyn-network-custom-period-auto-continue": (
                dyn_network_custom_period_auto_continue
            ),
            "--dyn-network-average-cpc": dyn_network_average_cpc,
            "--dyn-network-average-cpa": dyn_network_average_cpa,
            "--dyn-network-cpa": dyn_network_cpa,
            "--dyn-network-goal-id": dyn_network_goal_id,
            "--dyn-network-crr": dyn_network_crr,
            "--dyn-network-clicks-per-week": dyn_network_clicks_per_week,
            "--dyn-network-limit-percent": dyn_network_limit_percent,
            "--dyn-network-reserve-return": dyn_network_reserve_return,
            "--dyn-network-roi-coef": dyn_network_roi_coef,
            "--dyn-network-profitability": dyn_network_profitability,
            "--dyn-network-exploration-budget": dyn_network_exploration_budget,
            "--dyn-network-exploration-budget-custom": (
                dyn_network_exploration_budget_custom
            ),
            # DynamicTextCampaign.BiddingStrategy.Search typed flags (#362)
            "--dyn-search-weekly-spend-limit": dyn_search_weekly_spend_limit,
            "--dyn-search-bid-ceiling": dyn_search_bid_ceiling,
            "--dyn-search-custom-period-spend-limit": (
                dyn_search_custom_period_spend_limit
            ),
            "--dyn-search-custom-period-start-date": (
                dyn_search_custom_period_start_date
            ),
            "--dyn-search-custom-period-end-date": (dyn_search_custom_period_end_date),
            "--dyn-search-custom-period-auto-continue": (
                dyn_search_custom_period_auto_continue
            ),
            "--dyn-search-average-cpc": dyn_search_average_cpc,
            "--dyn-search-average-cpa": dyn_search_average_cpa,
            "--dyn-search-cpa": dyn_search_cpa,
            "--dyn-search-goal-id": dyn_search_goal_id,
            "--dyn-search-crr": dyn_search_crr,
            "--dyn-search-clicks-per-week": dyn_search_clicks_per_week,
            "--dyn-search-reserve-return": dyn_search_reserve_return,
            "--dyn-search-roi-coef": dyn_search_roi_coef,
            "--dyn-search-profitability": dyn_search_profitability,
            "--dyn-search-exploration-budget": dyn_search_exploration_budget,
            "--dyn-search-exploration-budget-custom": (
                dyn_search_exploration_budget_custom
            ),
            # SmartCampaign.BiddingStrategy.Search typed flags (#367)
            "--smart-search-average-cpc": smart_search_average_cpc,
            "--smart-search-filter-average-cpc": smart_search_filter_average_cpc,
            "--smart-search-average-cpa": smart_search_average_cpa,
            "--smart-search-filter-average-cpa": smart_search_filter_average_cpa,
            "--smart-search-cpa": smart_search_cpa,
            "--smart-search-goal-id": smart_search_goal_id,
            "--smart-search-weekly-spend-limit": smart_search_weekly_spend_limit,
            "--smart-search-bid-ceiling": smart_search_bid_ceiling,
            "--smart-search-reserve-return": smart_search_reserve_return,
            "--smart-search-roi-coef": smart_search_roi_coef,
            "--smart-search-profitability": smart_search_profitability,
            "--smart-search-crr": smart_search_crr,
            "--smart-search-cp-spend-limit": smart_search_cp_spend_limit,
            "--smart-search-cp-start-date": smart_search_cp_start_date,
            "--smart-search-cp-end-date": smart_search_cp_end_date,
            "--smart-search-cp-auto-continue": smart_search_cp_auto_continue,
            "--smart-search-exploration-min": smart_search_exploration_min,
            "--smart-search-exploration-min-custom": (
                smart_search_exploration_min_custom
            ),
            # SmartCampaign.BiddingStrategy.Network typed flags (#368)
            "--smart-network-average-cpc": smart_network_average_cpc,
            "--smart-network-filter-average-cpc": (smart_network_filter_average_cpc),
            "--smart-network-average-cpa": smart_network_average_cpa,
            "--smart-network-filter-average-cpa": (smart_network_filter_average_cpa),
            "--smart-network-cpa": smart_network_cpa,
            "--smart-network-goal-id": smart_network_goal_id,
            "--smart-network-weekly-spend-limit": (smart_network_weekly_spend_limit),
            "--smart-network-bid-ceiling": smart_network_bid_ceiling,
            "--smart-network-reserve-return": smart_network_reserve_return,
            "--smart-network-roi-coef": smart_network_roi_coef,
            "--smart-network-profitability": smart_network_profitability,
            "--smart-network-crr": smart_network_crr,
            "--smart-network-limit-percent": smart_network_limit_percent,
            "--smart-network-cp-spend-limit": smart_network_cp_spend_limit,
            "--smart-network-cp-start-date": smart_network_cp_start_date,
            "--smart-network-cp-end-date": smart_network_cp_end_date,
            "--smart-network-cp-auto-continue": (smart_network_cp_auto_continue),
            "--smart-network-exploration-min": (smart_network_exploration_min),
            "--smart-network-exploration-min-custom": (
                smart_network_exploration_min_custom
            ),
            "--average-cpa": average_cpa,
            "--crr": crr,
            "--bid-ceiling": bid_ceiling,
            "--text-search-weekly-spend-limit": (text_search_weekly_spend_limit),
            "--text-search-custom-period-spend-limit": (
                text_search_custom_period_spend_limit
            ),
            "--text-search-custom-period-start-date": (
                text_search_custom_period_start_date
            ),
            "--text-search-custom-period-end-date": (
                text_search_custom_period_end_date
            ),
            "--text-search-custom-period-auto-continue": (
                text_search_custom_period_auto_continue
            ),
            "--text-search-average-cpc": text_search_average_cpc,
            "--text-search-pay-cpa": text_search_pay_cpa,
            "--text-search-clicks-per-week": text_search_clicks_per_week,
            "--text-search-reserve-return": text_search_reserve_return,
            "--text-search-roi-coef": text_search_roi_coef,
            "--text-search-profitability": text_search_profitability,
            "--text-search-exploration-min-budget": (
                text_search_exploration_min_budget
            ),
            "--text-search-exploration-is-custom": (text_search_exploration_is_custom),
            # UnifiedCampaign.BiddingStrategy.Search typed flags (#363).
            "--unified-search-placement-maps": unified_search_placement_maps,
            "--unified-search-placement-search-organization-list": (
                unified_search_placement_search_organization_list
            ),
            "--unified-search-weekly-spend-limit": (unified_search_weekly_spend_limit),
            "--unified-search-custom-period-spend-limit": (
                unified_search_custom_period_spend_limit
            ),
            "--unified-search-custom-period-start-date": (
                unified_search_custom_period_start_date
            ),
            "--unified-search-custom-period-end-date": (
                unified_search_custom_period_end_date
            ),
            "--unified-search-custom-period-auto-continue": (
                unified_search_custom_period_auto_continue
            ),
            "--unified-search-average-cpc": unified_search_average_cpc,
            "--unified-search-pay-cpa": unified_search_pay_cpa,
            "--unified-search-exploration-min-budget": (
                unified_search_exploration_min_budget
            ),
            "--unified-search-exploration-is-custom": (
                unified_search_exploration_is_custom
            ),
            "--text-network-weekly-spend-limit": (text_network_weekly_spend_limit),
            "--text-network-custom-period-spend-limit": (
                text_network_custom_period_spend_limit
            ),
            "--text-network-custom-period-start-date": (
                text_network_custom_period_start_date
            ),
            "--text-network-custom-period-end-date": (
                text_network_custom_period_end_date
            ),
            "--text-network-custom-period-auto-continue": (
                text_network_custom_period_auto_continue
            ),
            "--text-network-average-cpc": text_network_average_cpc,
            "--text-network-pay-cpa": text_network_pay_cpa,
            "--text-network-clicks-per-week": text_network_clicks_per_week,
            "--text-network-reserve-return": text_network_reserve_return,
            "--text-network-roi-coef": text_network_roi_coef,
            "--text-network-profitability": text_network_profitability,
            "--text-network-exploration-min-budget": (
                text_network_exploration_min_budget
            ),
            "--text-network-exploration-is-custom": (
                text_network_exploration_is_custom
            ),
            "--text-network-limit-percent": text_network_limit_percent,
            # UnifiedCampaign Network strategy detail flags (#366).
            # Only accepted under --type UNIFIED_CAMPAIGN; other campaign
            # types must reject them as silent-data-loss invariants.
            "--unified-network-weekly-spend-limit": (
                unified_network_weekly_spend_limit
            ),
            "--unified-network-custom-period-spend-limit": (
                unified_network_custom_period_spend_limit
            ),
            "--unified-network-custom-period-start-date": (
                unified_network_custom_period_start_date
            ),
            "--unified-network-custom-period-end-date": (
                unified_network_custom_period_end_date
            ),
            "--unified-network-custom-period-auto-continue": (
                unified_network_custom_period_auto_continue
            ),
            "--unified-network-average-cpc": unified_network_average_cpc,
            "--unified-network-cpa": unified_network_cpa,
            "--unified-network-exploration-min-budget": (
                unified_network_exploration_min_budget
            ),
            "--unified-network-exploration-is-custom": (
                unified_network_exploration_is_custom
            ),
            "--tracking-params": tracking_params,
        },
        message="{arg0} is not compatible with --type {command_type}.",
        type_value=campaign_type_norm,
        type_field="command_type",
    )

    # Build cross-cutting structured inputs from typed flags up front so
    # any UsageError fires before we start composing the payload.
    notification_obj = _build_notification(
        sms_events,
        sms_time_from,
        sms_time_to,
        notification_email,
        notification_check_position_interval,
        notification_warning_balance,
        notification_send_account_news,
        notification_send_warnings,
    )
    time_targeting_obj = _build_time_targeting(
        time_targeting_schedule,
        consider_working_weekends,
        holidays_suspend_on_holidays,
        holidays_bid_percent,
        holidays_start_hour,
        holidays_end_hour,
    )
    client_info_obj = _validate_max_length(
        "--client-info",
        client_info,
        CLIENT_INFO_MAX_LENGTH,
    )
    negative_keywords_obj = _array_of_string_option(
        "--negative-keywords", negative_keywords
    )
    blocked_ips_obj = _array_of_string_option(
        "--blocked-ips",
        blocked_ips,
        max_items=BLOCKED_IPS_MAX_ITEMS,
    )
    excluded_sites_obj = _array_of_string_option(
        "--excluded-sites",
        excluded_sites,
        max_items=EXCLUDED_SITES_MAX_ITEMS,
        max_item_length=EXCLUDED_SITE_MAX_LENGTH,
    )

    counter_ids_obj = _array_of_integer_option("--counter-ids", counter_ids)
    dynamic_placement_types = _build_dynamic_placement_types(
        dynamic_placement_search_results,
        dynamic_placement_product_gallery,
    )
    frequency_cap_obj = _build_frequency_cap(
        frequency_cap_impressions,
        frequency_cap_period_days,
        frequency_cap_period_all,
    )

    priority_goals_items = parse_priority_goals_spec(priority_goals)
    relevant_keywords_obj = _build_relevant_keywords(
        relevant_keywords_budget_percent,
        relevant_keywords_mode,
        relevant_keywords_optimize_goal_id,
        require_budget_percent=True,
    )
    package_bidding_strategy_obj = None
    smart_package_bidding_strategy_obj = None
    if campaign_type_norm == "SMART_CAMPAIGN":
        smart_package_bidding_strategy_obj = _build_smart_package_bidding_strategy(
            package_strategy_id,
            package_strategy_from_campaign_id,
            package_platform_search,
            package_platform_network,
            require_platforms=True,
        )
    else:
        package_label = (
            "UnifiedCampaign"
            if campaign_type_norm == "UNIFIED_CAMPAIGN"
            else (
                "DynamicTextCampaign"
                if campaign_type_norm == "DYNAMIC_TEXT_CAMPAIGN"
                else "TextCampaign"
            )
        )
        package_bidding_strategy_obj = _build_package_bidding_strategy(
            package_strategy_id,
            package_strategy_from_campaign_id,
            package_platform_search_result,
            package_platform_product_gallery,
            package_platform_maps,
            package_platform_search_organization_list,
            package_platform_network,
            package_platform_dynamic_places,
            campaign_label=package_label,
            require_platforms=campaign_type_norm
            in {"TEXT_CAMPAIGN", "UNIFIED_CAMPAIGN"},
        )
    negative_keyword_shared_set_ids_obj = _array_of_integer_option(
        "--negative-keyword-shared-set-ids",
        negative_keyword_shared_set_ids,
        max_items=NEGATIVE_KEYWORD_SHARED_SET_IDS_MAX_ITEMS,
    )
    if package_bidding_strategy_obj is not None:
        package_incompatible = {
            "--search-strategy": search_strategy,
            "--network-strategy": network_strategy,
            "--search-placement-search-results": search_placement_search_results,
            "--search-placement-product-gallery": (search_placement_product_gallery),
            "--search-placement-dynamic-places": search_placement_dynamic_places,
            "--goal-id": goal_id,
            "--average-cpa": average_cpa,
            "--crr": crr,
            "--bid-ceiling": bid_ceiling,
        }
        # Issue #373: ``UnifiedCampaignAddItem.PriorityGoals`` and
        # ``UnifiedCampaignAddItem.PackageBiddingStrategy`` are
        # declared as independent ``minOccurs=0`` siblings on the
        # WSDL (``tests/wsdl_cache/campaigns.xml`` lines 2160-2172,
        # no ``xsd:choice`` wrapper) — same shape as
        # ``SmartCampaignAddItem`` (lines 2202-2214) where the same
        # mutex was lifted in #369/#392. Allow the combination on
        # UnifiedCampaign; the other non-Smart package campaign
        # types (TextCampaign, DynamicTextCampaign) keep the mutex
        # until their own follow-up issues land.
        if campaign_type_norm != "UNIFIED_CAMPAIGN":
            package_incompatible["--priority-goals"] = priority_goals
        if campaign_type_norm == "TEXT_CAMPAIGN":
            # Issue #361: every typed Search-strategy detail flag must
            # also conflict with PackageBiddingStrategy on TEXT_CAMPAIGN,
            # otherwise text-search-* input would silently disappear
            # when the user opts into a package strategy.
            # Issue #364: same applies to --text-network-* flags.
            package_incompatible.update(
                {
                    "--text-search-weekly-spend-limit": (
                        text_search_weekly_spend_limit
                    ),
                    "--text-search-custom-period-spend-limit": (
                        text_search_custom_period_spend_limit
                    ),
                    "--text-search-custom-period-start-date": (
                        text_search_custom_period_start_date
                    ),
                    "--text-search-custom-period-end-date": (
                        text_search_custom_period_end_date
                    ),
                    "--text-search-custom-period-auto-continue": (
                        text_search_custom_period_auto_continue
                    ),
                    "--text-search-average-cpc": text_search_average_cpc,
                    "--text-search-pay-cpa": text_search_pay_cpa,
                    "--text-search-clicks-per-week": (text_search_clicks_per_week),
                    "--text-search-reserve-return": (text_search_reserve_return),
                    "--text-search-roi-coef": text_search_roi_coef,
                    "--text-search-profitability": text_search_profitability,
                    "--text-search-exploration-min-budget": (
                        text_search_exploration_min_budget
                    ),
                    "--text-search-exploration-is-custom": (
                        text_search_exploration_is_custom
                    ),
                    "--text-network-weekly-spend-limit": (
                        text_network_weekly_spend_limit
                    ),
                    "--text-network-custom-period-spend-limit": (
                        text_network_custom_period_spend_limit
                    ),
                    "--text-network-custom-period-start-date": (
                        text_network_custom_period_start_date
                    ),
                    "--text-network-custom-period-end-date": (
                        text_network_custom_period_end_date
                    ),
                    "--text-network-custom-period-auto-continue": (
                        text_network_custom_period_auto_continue
                    ),
                    "--text-network-average-cpc": text_network_average_cpc,
                    "--text-network-pay-cpa": text_network_pay_cpa,
                    "--text-network-clicks-per-week": (text_network_clicks_per_week),
                    "--text-network-reserve-return": (text_network_reserve_return),
                    "--text-network-roi-coef": text_network_roi_coef,
                    "--text-network-profitability": text_network_profitability,
                    "--text-network-exploration-min-budget": (
                        text_network_exploration_min_budget
                    ),
                    "--text-network-exploration-is-custom": (
                        text_network_exploration_is_custom
                    ),
                    "--text-network-limit-percent": (text_network_limit_percent),
                }
            )
        if campaign_type_norm == "UNIFIED_CAMPAIGN":
            # Issue #363: every typed UnifiedCampaign Search-strategy
            # detail flag must also conflict with PackageBiddingStrategy
            # on add, otherwise --unified-search-* input would silently
            # disappear when the user opts into a package strategy.
            package_incompatible.update(
                {
                    "--counter-ids": counter_ids,
                    "--attribution-model": attribution_model,
                    # Issue #366: UnifiedCampaign.BiddingStrategy.Network
                    # typed flags must conflict with PackageBiddingStrategy
                    # on add so user input is never silently dropped when
                    # the user opts into a package strategy (mirrors the
                    # update-path conflict map and the TEXT_CAMPAIGN /
                    # DYNAMIC_TEXT_CAMPAIGN behaviours).
                    "--unified-network-weekly-spend-limit": (
                        unified_network_weekly_spend_limit
                    ),
                    "--unified-network-custom-period-spend-limit": (
                        unified_network_custom_period_spend_limit
                    ),
                    "--unified-network-custom-period-start-date": (
                        unified_network_custom_period_start_date
                    ),
                    "--unified-network-custom-period-end-date": (
                        unified_network_custom_period_end_date
                    ),
                    "--unified-network-custom-period-auto-continue": (
                        unified_network_custom_period_auto_continue
                    ),
                    "--unified-network-average-cpc": (unified_network_average_cpc),
                    "--unified-network-cpa": unified_network_cpa,
                    "--unified-network-exploration-min-budget": (
                        unified_network_exploration_min_budget
                    ),
                    "--unified-network-exploration-is-custom": (
                        unified_network_exploration_is_custom
                    ),
                    # Issue #363: UnifiedCampaign.BiddingStrategy.Search
                    # typed flags also conflict with PackageBiddingStrategy.
                    "--unified-search-placement-maps": (unified_search_placement_maps),
                    "--unified-search-placement-search-organization-list": (
                        unified_search_placement_search_organization_list
                    ),
                    "--unified-search-weekly-spend-limit": (
                        unified_search_weekly_spend_limit
                    ),
                    "--unified-search-custom-period-spend-limit": (
                        unified_search_custom_period_spend_limit
                    ),
                    "--unified-search-custom-period-start-date": (
                        unified_search_custom_period_start_date
                    ),
                    "--unified-search-custom-period-end-date": (
                        unified_search_custom_period_end_date
                    ),
                    "--unified-search-custom-period-auto-continue": (
                        unified_search_custom_period_auto_continue
                    ),
                    "--unified-search-average-cpc": (unified_search_average_cpc),
                    "--unified-search-pay-cpa": unified_search_pay_cpa,
                    "--unified-search-exploration-min-budget": (
                        unified_search_exploration_min_budget
                    ),
                    "--unified-search-exploration-is-custom": (
                        unified_search_exploration_is_custom
                    ),
                }
            )
        if campaign_type_norm == "DYNAMIC_TEXT_CAMPAIGN":
            package_incompatible.update(
                {
                    "--dyn-network-weekly-spend-limit": (
                        dyn_network_weekly_spend_limit
                    ),
                    "--dyn-network-bid-ceiling": dyn_network_bid_ceiling,
                    "--dyn-network-custom-period-spend-limit": (
                        dyn_network_custom_period_spend_limit
                    ),
                    "--dyn-network-custom-period-start-date": (
                        dyn_network_custom_period_start_date
                    ),
                    "--dyn-network-custom-period-end-date": (
                        dyn_network_custom_period_end_date
                    ),
                    "--dyn-network-custom-period-auto-continue": (
                        dyn_network_custom_period_auto_continue
                    ),
                    "--dyn-network-average-cpc": dyn_network_average_cpc,
                    "--dyn-network-average-cpa": dyn_network_average_cpa,
                    "--dyn-network-cpa": dyn_network_cpa,
                    "--dyn-network-goal-id": dyn_network_goal_id,
                    "--dyn-network-crr": dyn_network_crr,
                    "--dyn-network-clicks-per-week": (dyn_network_clicks_per_week),
                    "--dyn-network-limit-percent": dyn_network_limit_percent,
                    "--dyn-network-reserve-return": (dyn_network_reserve_return),
                    "--dyn-network-roi-coef": dyn_network_roi_coef,
                    "--dyn-network-profitability": dyn_network_profitability,
                    "--dyn-network-exploration-budget": (
                        dyn_network_exploration_budget
                    ),
                    "--dyn-network-exploration-budget-custom": (
                        dyn_network_exploration_budget_custom
                    ),
                    # DynamicTextCampaign Search typed flags (#362).
                    # ``--search-strategy`` and ``--search-placement-*``
                    # are already in the base ``package_incompatible``
                    # map above; the per-DYN extension only adds the
                    # new ``--dyn-search-*`` detail flags so they can
                    # never be silently dropped when PackageBidding-
                    # Strategy wins (same pattern as TEXT_CAMPAIGN
                    # text-search-* — see #361/#388).
                    "--dyn-search-weekly-spend-limit": (dyn_search_weekly_spend_limit),
                    "--dyn-search-bid-ceiling": dyn_search_bid_ceiling,
                    "--dyn-search-custom-period-spend-limit": (
                        dyn_search_custom_period_spend_limit
                    ),
                    "--dyn-search-custom-period-start-date": (
                        dyn_search_custom_period_start_date
                    ),
                    "--dyn-search-custom-period-end-date": (
                        dyn_search_custom_period_end_date
                    ),
                    "--dyn-search-custom-period-auto-continue": (
                        dyn_search_custom_period_auto_continue
                    ),
                    "--dyn-search-average-cpc": dyn_search_average_cpc,
                    "--dyn-search-average-cpa": dyn_search_average_cpa,
                    "--dyn-search-cpa": dyn_search_cpa,
                    "--dyn-search-goal-id": dyn_search_goal_id,
                    "--dyn-search-crr": dyn_search_crr,
                    "--dyn-search-clicks-per-week": (dyn_search_clicks_per_week),
                    "--dyn-search-reserve-return": dyn_search_reserve_return,
                    "--dyn-search-roi-coef": dyn_search_roi_coef,
                    "--dyn-search-profitability": dyn_search_profitability,
                    "--dyn-search-exploration-budget": (dyn_search_exploration_budget),
                    "--dyn-search-exploration-budget-custom": (
                        dyn_search_exploration_budget_custom
                    ),
                }
            )
        provided = [
            flag for flag, value in package_incompatible.items() if value is not None
        ]
        if provided:
            raise click.UsageError(
                t(
                    "{package_label}.PackageBiddingStrategy cannot be combined with {arg0}"
                ).format(package_label=package_label, arg0=", ".join(sorted(provided)))
            )
    if smart_package_bidding_strategy_obj is not None:
        # SmartCampaign.PriorityGoals (#369) is a top-level sibling on
        # SmartCampaignAddItem (WSDL line 2209) independent of the
        # BiddingStrategy / PackageBiddingStrategy choice — both
        # PriorityGoals and PackageBiddingStrategy are declared as
        # ``minOccurs=0`` siblings on SmartCampaignAddItem (no
        # ``xsd:choice``), so combining --priority-goals with
        # PackageBiddingStrategy is WSDL-valid and intentionally
        # allowed.
        smart_package_incompatible = {
            "--search-strategy": search_strategy,
            "--network-strategy": network_strategy,
            "--filter-average-cpc": filter_average_cpc,
            "--attribution-model": attribution_model,
            # SmartCampaign.BiddingStrategy.Search typed flags (#367) —
            # mutually exclusive with PackageBiddingStrategy. Without these
            # entries the add path silently drops user input.
            "--smart-search-average-cpc": smart_search_average_cpc,
            "--smart-search-filter-average-cpc": smart_search_filter_average_cpc,
            "--smart-search-average-cpa": smart_search_average_cpa,
            "--smart-search-filter-average-cpa": smart_search_filter_average_cpa,
            "--smart-search-cpa": smart_search_cpa,
            "--smart-search-goal-id": smart_search_goal_id,
            "--smart-search-weekly-spend-limit": smart_search_weekly_spend_limit,
            "--smart-search-bid-ceiling": smart_search_bid_ceiling,
            "--smart-search-reserve-return": smart_search_reserve_return,
            "--smart-search-roi-coef": smart_search_roi_coef,
            "--smart-search-profitability": smart_search_profitability,
            "--smart-search-crr": smart_search_crr,
            "--smart-search-cp-spend-limit": smart_search_cp_spend_limit,
            "--smart-search-cp-start-date": smart_search_cp_start_date,
            "--smart-search-cp-end-date": smart_search_cp_end_date,
            "--smart-search-cp-auto-continue": smart_search_cp_auto_continue,
            "--smart-search-exploration-min": smart_search_exploration_min,
            "--smart-search-exploration-min-custom": (
                smart_search_exploration_min_custom
            ),
            # SmartCampaign.BiddingStrategy.Network typed flags (#368) —
            # same mutex contract as Search. Without these entries the
            # package path silently drops user-provided Network flags.
            "--smart-network-average-cpc": smart_network_average_cpc,
            "--smart-network-filter-average-cpc": (smart_network_filter_average_cpc),
            "--smart-network-average-cpa": smart_network_average_cpa,
            "--smart-network-filter-average-cpa": (smart_network_filter_average_cpa),
            "--smart-network-cpa": smart_network_cpa,
            "--smart-network-goal-id": smart_network_goal_id,
            "--smart-network-weekly-spend-limit": (smart_network_weekly_spend_limit),
            "--smart-network-bid-ceiling": smart_network_bid_ceiling,
            "--smart-network-reserve-return": smart_network_reserve_return,
            "--smart-network-roi-coef": smart_network_roi_coef,
            "--smart-network-profitability": smart_network_profitability,
            "--smart-network-crr": smart_network_crr,
            "--smart-network-limit-percent": smart_network_limit_percent,
            "--smart-network-cp-spend-limit": smart_network_cp_spend_limit,
            "--smart-network-cp-start-date": smart_network_cp_start_date,
            "--smart-network-cp-end-date": smart_network_cp_end_date,
            "--smart-network-cp-auto-continue": (smart_network_cp_auto_continue),
            "--smart-network-exploration-min": (smart_network_exploration_min),
            "--smart-network-exploration-min-custom": (
                smart_network_exploration_min_custom
            ),
        }
        provided = [
            flag
            for flag, value in smart_package_incompatible.items()
            if value is not None
        ]
        if provided:
            raise click.UsageError(
                t(
                    "SmartCampaign.PackageBiddingStrategy cannot be combined with {arg0}"
                ).format(arg0=", ".join(sorted(provided)))
            )

    if campaign_type_norm == "UNIFIED_CAMPAIGN":
        unified_campaign_level_conflicts = {
            "--client-info": client_info_obj,
            "--sms-events": sms_events,
            "--sms-time-from": sms_time_from,
            "--sms-time-to": sms_time_to,
            "--notification-check-position-interval": (
                notification_check_position_interval
            ),
            "--notification-warning-balance": notification_warning_balance,
            "--notification-send-warnings": notification_send_warnings,
        }
        provided = [
            flag
            for flag, value in unified_campaign_level_conflicts.items()
            if value is not None
        ]
        if provided:
            raise click.UsageError(
                t("UnifiedCampaign cannot be combined with {arg0}").format(
                    arg0=", ".join(sorted(provided))
                )
            )
        if priority_goals is not None:
            # Issue #373: ``UnifiedCampaignAddItem.PriorityGoals``
            # (WSDL ``tests/wsdl_cache/campaigns.xml`` line 2165) is a
            # top-level sibling declared as ``minOccurs=0`` alongside
            # ``BiddingStrategy`` (line 2162, also ``minOccurs=0``) and
            # ``PackageBiddingStrategy`` (line 2168, ``minOccurs=0``)
            # on a plain ``xsd:sequence`` — no ``xsd:choice``. Per
            # the canonical WSDL the user MAY supply PriorityGoals
            # alone, with PackageBiddingStrategy, or with a
            # per-side BiddingStrategy. The only documented
            # constraint surfaced by this CLI is on the per-side
            # BiddingStrategy subtypes themselves
            # (``_bidding_strategy.py``): when the user explicitly
            # selects a per-side strategy whose subtype is NOT in
            # the multi-goal / MaxProfit set, ``--priority-goals``
            # would be silently dropped by the subtype builder, so
            # reject up-front with a clear message. When no per-side
            # strategy is chosen, the items flow straight to the
            # parent PriorityGoals sibling and the builders fall
            # back to their HIGHEST_POSITION / SERVING_OFF defaults.
            _unified_network_subtype = (
                UNIFIED_CAMPAIGN_NETWORK_STRATEGY_TO_WSDL_SUBTYPE.get(
                    (network_strategy or "").upper()
                )
            )
            _unified_search_subtype = (
                _UNIFIED_CAMPAIGN_SEARCH_STRATEGY_TO_WSDL_SUBTYPE.get(
                    (search_strategy or "").upper()
                )
            )
            _network_allows = (
                _unified_network_subtype in _UNIFIED_NETWORK_REQUIRES_PRIORITY_GOALS
            )
            _search_allows = (
                _unified_search_subtype in _UNIFIED_SEARCH_REQUIRES_PRIORITY_GOALS
            )
            _network_chosen = network_strategy is not None
            _search_chosen = search_strategy is not None
            # Only reject when EVERY explicitly chosen per-side
            # strategy is incompatible. PriorityGoals on the
            # parent sibling is still emitted (line 3550-3551),
            # so a single compatible side is enough — and the
            # standalone case (no per-side strategy at all) is
            # also valid per the WSDL.
            _both_explicit_and_incompatible = (
                _network_chosen
                and _search_chosen
                and not _network_allows
                and not _search_allows
            )
            _only_network_explicit_and_incompatible = (
                _network_chosen and not _search_chosen and not _network_allows
            )
            _only_search_explicit_and_incompatible = (
                _search_chosen and not _network_chosen and not _search_allows
            )
            if (
                _both_explicit_and_incompatible
                or _only_network_explicit_and_incompatible
                or _only_search_explicit_and_incompatible
            ):
                raise click.UsageError(
                    t(
                        "--priority-goals on UnifiedCampaign is only valid with --network-strategy or --search-strategy in {{AVERAGE_CPA_MULTIPLE_GOALS, PAY_FOR_CONVERSION_MULTIPLE_GOALS, MAX_PROFIT}}; got --network-strategy={network_strategy!r}, --search-strategy={search_strategy!r}"
                    ).format(
                        network_strategy=network_strategy,
                        search_strategy=search_strategy,
                    )
                )
    if campaign_type_norm in {"MOBILE_APP_CAMPAIGN", "CPM_BANNER_CAMPAIGN"}:
        strategy_followup_flags = {
            "--goal-id": goal_id,
            "--priority-goals": priority_goals,
            "--average-cpa": average_cpa,
            "--crr": crr,
            "--bid-ceiling": bid_ceiling,
        }
        provided = [
            flag for flag, value in strategy_followup_flags.items() if value is not None
        ]
        if provided:
            raise click.UsageError(
                t(
                    "{campaign_type_norm} BiddingStrategy typed parameters are tracked in #290; got {arg0}"
                ).format(
                    campaign_type_norm=campaign_type_norm,
                    arg0=", ".join(sorted(provided)),
                )
            )

    campaign_data = {"Name": name, "StartDate": start_date}
    parsed_settings = parse_setting_specs(list(settings))
    if campaign_type_norm == "TEXT_CAMPAIGN":
        text_block = {"Settings": parsed_settings or []}
        if package_bidding_strategy_obj is not None:
            text_block["PackageBiddingStrategy"] = package_bidding_strategy_obj
        else:
            # Route shared inputs (``--priority-goals`` and the legacy
            # CPA flags ``--goal-id``/``--average-cpa``/``--crr``/
            # ``--bid-ceiling``) per-side, per-flag based on the actual
            # WSDL field-support sets. A flag is forwarded to a side
            # only when that side's chosen subtype accepts the flag's
            # WSDL field. When neither side accepts the flag we still
            # forward to Search so the Search builder produces the
            # canonical "CPA-shaped strategy required" error message
            # users have relied on since #361. Issue #361/#364.
            _search_subtype_for_routing = (
                _TEXT_CAMPAIGN_SEARCH_STRATEGY_TO_WSDL_SUBTYPE.get(
                    (search_strategy or "").upper()
                )
            )
            _network_subtype_for_routing = (
                TEXT_CAMPAIGN_NETWORK_STRATEGY_TO_WSDL_SUBTYPE.get(
                    (network_strategy or "").upper()
                )
            )

            def _route(value, search_support: set, network_support: set, default: str):
                """Route a shared CPA flag for TextCampaign add (thin wrapper
                over the module-level ``_route_cpa_flag``, binding this block's
                Search/Network routing subtypes)."""
                return _route_cpa_flag(
                    value,
                    _search_subtype_for_routing,
                    _network_subtype_for_routing,
                    search_support,
                    network_support,
                    default,
                )

            _search_goal_id, _network_goal_id = _route(
                goal_id,
                _TEXT_SEARCH_SUPPORTS_GOAL_ID,
                _TEXT_NETWORK_GOAL_ID_SUBTYPES,
                default="search",
            )
            _search_average_cpa, _network_average_cpa = _route(
                average_cpa,
                _TEXT_SEARCH_SUPPORTS_AVERAGE_CPA,
                _TEXT_NETWORK_AVERAGE_CPA_SUBTYPES,
                default="search",
            )
            _search_crr, _network_crr = _route(
                crr,
                _TEXT_SEARCH_SUPPORTS_CRR,
                _TEXT_NETWORK_CRR_SUBTYPES,
                default="search",
            )
            _search_bid_ceiling, _network_bid_ceiling = _route(
                bid_ceiling,
                _TEXT_SEARCH_SUPPORTS_BID_CEILING,
                _TEXT_NETWORK_BID_CEILING_SUBTYPES,
                default="search",
            )

            # PriorityGoals is the single
            # ``TextCampaignAddItem.PriorityGoals`` sibling on the
            # parent block (WSDL minOccurs=0), but each side's builder
            # must see it for its own required-field check whenever its
            # strategy belongs to the multi-goals family. When BOTH
            # sides pick a multi-goals strategy the same items satisfy
            # both builders simultaneously; the Search builder writes
            # ``sub_campaign_block["PriorityGoals"]`` first, and the
            # Network builder is invoked second with the same items so
            # its required-field check passes (the parent placement is
            # idempotent — same value either way).
            _multi_goal_subtypes = _TEXT_NETWORK_REQUIRES_PRIORITY_GOALS
            _search_uses_priority_goals = (
                _search_subtype_for_routing in _multi_goal_subtypes
            )
            _network_uses_priority_goals = (
                _network_subtype_for_routing in _multi_goal_subtypes
            )
            if _search_uses_priority_goals or _network_uses_priority_goals:
                _search_priority_goals_items = (
                    priority_goals_items if _search_uses_priority_goals else None
                )
                _network_priority_goals_items = (
                    priority_goals_items if _network_uses_priority_goals else None
                )
            else:
                # Neither side accepts ``--priority-goals``. Forward to
                # Search so the canonical "AVERAGE_CPA_MULTIPLE_GOALS /
                # ..." error surfaces from the Search builder
                # (preserves pre-#364 behavior on misuse).
                _search_priority_goals_items = priority_goals_items
                _network_priority_goals_items = None
            # Issue #361: full typed-flag support for all 12 strategy
            # families on TextCampaign.BiddingStrategy.Search. The
            # branch="search" builder owns the entire Search payload
            # (subtype block, PlacementTypes, PriorityGoals sibling
            # placement). The legacy branch="priority_goals" builder
            # is kept only for DYNAMIC_TEXT_CAMPAIGN.
            search_builder = get_bidding_strategy_builder(
                "TEXT_CAMPAIGN", "add", "search"
            )
            if search_builder is not None:
                text_search = search_builder(
                    search_strategy=search_strategy,
                    search_placement_search_results=(search_placement_search_results),
                    search_placement_product_gallery=(search_placement_product_gallery),
                    search_placement_dynamic_places=(search_placement_dynamic_places),
                    goal_id=_search_goal_id,
                    average_cpa=_search_average_cpa,
                    crr=_search_crr,
                    bid_ceiling=_search_bid_ceiling,
                    weekly_spend_limit=text_search_weekly_spend_limit,
                    custom_period_spend_limit=(text_search_custom_period_spend_limit),
                    custom_period_start_date=(text_search_custom_period_start_date),
                    custom_period_end_date=text_search_custom_period_end_date,
                    custom_period_auto_continue=(
                        text_search_custom_period_auto_continue
                    ),
                    budget_type=None,
                    average_cpc=text_search_average_cpc,
                    pay_cpa=text_search_pay_cpa,
                    clicks_per_week=text_search_clicks_per_week,
                    reserve_return=text_search_reserve_return,
                    roi_coef=text_search_roi_coef,
                    profitability=text_search_profitability,
                    exploration_min_budget=(text_search_exploration_min_budget),
                    exploration_is_custom=(text_search_exploration_is_custom),
                    priority_goals_items=_search_priority_goals_items,
                    sub_campaign_block=text_block,
                    include_default=True,
                    is_update=False,
                )
            else:
                text_search = {
                    "BiddingStrategyType": (
                        (search_strategy or "HIGHEST_POSITION").upper()
                    )
                }
            # Issue #364: full typed-flag support for all 13 strategy
            # families on TextCampaign.BiddingStrategy.Network. The
            # branch="network" builder owns the entire Network payload
            # (subtype block, NetworkDefault.LimitPercent, PriorityGoals
            # sibling placement). include_default=True keeps the legacy
            # default of SERVING_OFF when no network flag is provided
            # so the WSDL ``TextCampaignNetworkStrategyAdd.BiddingStrategyType``
            # minOccurs=1 contract is satisfied on add without forcing
            # the user to specify Network.
            network_builder = get_bidding_strategy_builder(
                "TEXT_CAMPAIGN", "add", "network"
            )
            if network_builder is not None:
                text_network = network_builder(
                    network_strategy=network_strategy,
                    goal_id=_network_goal_id,
                    average_cpa=_network_average_cpa,
                    crr=_network_crr,
                    bid_ceiling=_network_bid_ceiling,
                    weekly_spend_limit=text_network_weekly_spend_limit,
                    custom_period_spend_limit=(text_network_custom_period_spend_limit),
                    custom_period_start_date=(text_network_custom_period_start_date),
                    custom_period_end_date=text_network_custom_period_end_date,
                    custom_period_auto_continue=(
                        text_network_custom_period_auto_continue
                    ),
                    budget_type=None,
                    average_cpc=text_network_average_cpc,
                    pay_cpa=text_network_pay_cpa,
                    clicks_per_week=text_network_clicks_per_week,
                    reserve_return=text_network_reserve_return,
                    roi_coef=text_network_roi_coef,
                    profitability=text_network_profitability,
                    exploration_min_budget=(text_network_exploration_min_budget),
                    exploration_is_custom=(text_network_exploration_is_custom),
                    limit_percent=text_network_limit_percent,
                    priority_goals_items=_network_priority_goals_items,
                    sub_campaign_block=text_block,
                    include_default=True,
                    is_update=False,
                )
            else:
                text_network = {
                    "BiddingStrategyType": (network_strategy or "SERVING_OFF")
                }
            text_block["BiddingStrategy"] = {
                "Search": text_search,
                "Network": text_network,
            }
        if counter_ids_obj is not None:
            text_block["CounterIds"] = counter_ids_obj
        if relevant_keywords_obj is not None:
            text_block["RelevantKeywords"] = relevant_keywords_obj
        if attribution_model:
            text_block["AttributionModel"] = attribution_model.upper()
        if negative_keyword_shared_set_ids_obj is not None:
            text_block["NegativeKeywordSharedSetIds"] = (
                negative_keyword_shared_set_ids_obj
            )
        if tracking_params:
            text_block["TrackingParams"] = tracking_params
        campaign_data["TextCampaign"] = text_block
    elif campaign_type_norm == "UNIFIED_CAMPAIGN":
        unified_block: Dict[str, object] = {"Settings": parsed_settings or []}
        if package_bidding_strategy_obj is not None:
            unified_block["PackageBiddingStrategy"] = package_bidding_strategy_obj
        else:
            # Issue #366 + #363: full typed-flag support for the 10
            # strategy subtype families on both
            # UnifiedCampaign.BiddingStrategy.Network (#366) and
            # UnifiedCampaign.BiddingStrategy.Search (#363). Mirrors
            # the TextCampaign pattern: shared legacy CPA flags
            # (``--goal-id``/``--average-cpa``/``--crr``/``--bid-ceiling``)
            # are routed per-side based on which subtype actually
            # accepts the WSDL field. include_default=True keeps the
            # legacy defaults (HIGHEST_POSITION for Search,
            # SERVING_OFF for Network) when neither side is provided.
            _u_search_subtype_for_routing = (
                _UNIFIED_CAMPAIGN_SEARCH_STRATEGY_TO_WSDL_SUBTYPE.get(
                    (search_strategy or "").upper()
                )
            )
            _u_network_subtype_for_routing = (
                UNIFIED_CAMPAIGN_NETWORK_STRATEGY_TO_WSDL_SUBTYPE.get(
                    (network_strategy or "").upper()
                )
            )

            def _u_route(
                value, search_support: set, network_support: set, default: str
            ):
                """Route a shared CPA flag for UnifiedCampaign add (thin wrapper
                over the module-level ``_route_cpa_flag``)."""
                return _route_cpa_flag(
                    value,
                    _u_search_subtype_for_routing,
                    _u_network_subtype_for_routing,
                    search_support,
                    network_support,
                    default,
                )

            # Default-side routing for unrecognized flag/strategy
            # combinations: prefer the side whose strategy was
            # explicitly chosen so the rejection comes from the
            # builder the user is actually targeting. When neither
            # side is explicitly chosen, fall back to Search to keep
            # the canonical "CPA-shaped strategy required" error.
            _u_default_side = (
                "network"
                if network_strategy is not None and search_strategy is None
                else "search"
            )
            _u_search_goal_id, _u_network_goal_id = _u_route(
                goal_id,
                _UNIFIED_SEARCH_SUPPORTS_GOAL_ID,
                _UNIFIED_NETWORK_GOAL_ID_SUBTYPES,
                default=_u_default_side,
            )
            _u_search_average_cpa, _u_network_average_cpa = _u_route(
                average_cpa,
                _UNIFIED_SEARCH_SUPPORTS_AVERAGE_CPA,
                _UNIFIED_NETWORK_AVERAGE_CPA_SUBTYPES,
                default=_u_default_side,
            )
            _u_search_crr, _u_network_crr = _u_route(
                crr,
                _UNIFIED_SEARCH_SUPPORTS_CRR,
                _UNIFIED_NETWORK_CRR_SUBTYPES,
                default=_u_default_side,
            )
            _u_search_bid_ceiling, _u_network_bid_ceiling = _u_route(
                bid_ceiling,
                _UNIFIED_SEARCH_SUPPORTS_BID_CEILING,
                _UNIFIED_NETWORK_BID_CEILING_SUBTYPES,
                default=_u_default_side,
            )

            # PriorityGoals: route to whichever side accepts it.
            # When BOTH sides chose a multi-goal/MaxProfit subtype the
            # same items satisfy both builders (the parent placement
            # via ``sub_campaign_block`` is idempotent). When the
            # user supplies PriorityGoals without explicitly choosing
            # either side's strategy (#373: WSDL-valid standalone
            # case), suppress per-side wiring entirely — PriorityGoals
            # lands on the parent ``UnifiedCampaign.PriorityGoals``
            # sibling further below and the builders fall back to
            # the HIGHEST_POSITION / SERVING_OFF defaults. The
            # upstream guard already raises a clear error when a
            # per-side strategy was explicitly chosen with a subtype
            # outside the multi-goal / MaxProfit set.
            _u_search_uses_priority_goals = (
                _u_search_subtype_for_routing in _UNIFIED_SEARCH_REQUIRES_PRIORITY_GOALS
            )
            _u_network_uses_priority_goals = (
                _u_network_subtype_for_routing
                in _UNIFIED_NETWORK_REQUIRES_PRIORITY_GOALS
            )
            _u_search_priority_goals_items = (
                priority_goals_items if _u_search_uses_priority_goals else None
            )
            _u_network_priority_goals_items = (
                priority_goals_items if _u_network_uses_priority_goals else None
            )

            unified_search_builder = get_bidding_strategy_builder(
                "UNIFIED_CAMPAIGN", "add", "search"
            )
            if unified_search_builder is not None:
                unified_search = unified_search_builder(
                    search_strategy=search_strategy,
                    search_placement_search_results=(search_placement_search_results),
                    search_placement_product_gallery=(search_placement_product_gallery),
                    search_placement_dynamic_places=(search_placement_dynamic_places),
                    search_placement_maps=unified_search_placement_maps,
                    search_placement_search_organization_list=(
                        unified_search_placement_search_organization_list
                    ),
                    goal_id=_u_search_goal_id,
                    average_cpa=_u_search_average_cpa,
                    crr=_u_search_crr,
                    bid_ceiling=_u_search_bid_ceiling,
                    weekly_spend_limit=unified_search_weekly_spend_limit,
                    custom_period_spend_limit=(
                        unified_search_custom_period_spend_limit
                    ),
                    custom_period_start_date=(unified_search_custom_period_start_date),
                    custom_period_end_date=(unified_search_custom_period_end_date),
                    custom_period_auto_continue=(
                        unified_search_custom_period_auto_continue
                    ),
                    budget_type=None,
                    average_cpc=unified_search_average_cpc,
                    pay_cpa=unified_search_pay_cpa,
                    exploration_min_budget=(unified_search_exploration_min_budget),
                    exploration_is_custom=(unified_search_exploration_is_custom),
                    priority_goals_items=_u_search_priority_goals_items,
                    sub_campaign_block=unified_block,
                    include_default=True,
                    is_update=False,
                )
            else:
                unified_search = {"BiddingStrategyType": "HIGHEST_POSITION"}
            unified_network_builder = get_bidding_strategy_builder(
                "UNIFIED_CAMPAIGN", "add", "network"
            )
            if unified_network_builder is not None:
                unified_network = unified_network_builder(
                    network_strategy=network_strategy,
                    goal_id=_u_network_goal_id,
                    average_cpa=_u_network_average_cpa,
                    crr=_u_network_crr,
                    bid_ceiling=_u_network_bid_ceiling,
                    weekly_spend_limit=unified_network_weekly_spend_limit,
                    custom_period_spend_limit=(
                        unified_network_custom_period_spend_limit
                    ),
                    custom_period_start_date=(unified_network_custom_period_start_date),
                    custom_period_end_date=(unified_network_custom_period_end_date),
                    custom_period_auto_continue=(
                        unified_network_custom_period_auto_continue
                    ),
                    budget_type=None,
                    average_cpc=unified_network_average_cpc,
                    cpa=unified_network_cpa,
                    exploration_min_budget=(unified_network_exploration_min_budget),
                    exploration_is_custom=(unified_network_exploration_is_custom),
                    priority_goals_items=_u_network_priority_goals_items,
                    sub_campaign_block=unified_block,
                    include_default=True,
                    is_update=False,
                )
            else:
                unified_network = {
                    "BiddingStrategyType": (network_strategy or "SERVING_OFF")
                }
            unified_block["BiddingStrategy"] = {
                "Search": unified_search,
                "Network": unified_network,
            }
        if counter_ids_obj is not None:
            unified_block["CounterIds"] = counter_ids_obj
        if priority_goals_items is not None:
            unified_block["PriorityGoals"] = {"Items": priority_goals_items}
        if attribution_model:
            unified_block["AttributionModel"] = attribution_model.upper()
        if negative_keyword_shared_set_ids_obj is not None:
            unified_block["NegativeKeywordSharedSetIds"] = (
                negative_keyword_shared_set_ids_obj
            )
        if tracking_params:
            unified_block["TrackingParams"] = tracking_params
        campaign_data["UnifiedCampaign"] = unified_block
    elif campaign_type_norm == "DYNAMIC_TEXT_CAMPAIGN":
        dyn_block: Dict[str, object] = {"Settings": parsed_settings or []}
        if package_bidding_strategy_obj is not None:
            dyn_block["PackageBiddingStrategy"] = package_bidding_strategy_obj
        else:
            # DynamicTextCampaign.BiddingStrategy.Network — typed
            # builder (#365). Returns full Network dict including
            # nested Strategy*Add subtype block. include_default=True
            # mirrors the WSDL minOccurs=1 contract on add.
            network_builder = get_bidding_strategy_builder(
                "DYNAMIC_TEXT_CAMPAIGN", "add", "network"
            )
            if network_builder is not None:
                dyn_network_block = network_builder(
                    network_strategy,
                    dyn_network_weekly_spend_limit,
                    dyn_network_bid_ceiling,
                    dyn_network_custom_period_spend_limit,
                    dyn_network_custom_period_start_date,
                    dyn_network_custom_period_end_date,
                    dyn_network_custom_period_auto_continue,
                    dyn_network_average_cpc,
                    dyn_network_average_cpa,
                    dyn_network_cpa,
                    dyn_network_goal_id,
                    dyn_network_crr,
                    dyn_network_clicks_per_week,
                    dyn_network_limit_percent,
                    dyn_network_reserve_return,
                    dyn_network_roi_coef,
                    dyn_network_profitability,
                    dyn_network_exploration_budget,
                    dyn_network_exploration_budget_custom,
                    budget_type=None,
                    include_default=True,
                    is_update=False,
                )
            else:
                dyn_network_block = {
                    "BiddingStrategyType": (network_strategy or "SERVING_OFF")
                }
            # DynamicTextCampaign.BiddingStrategy.Search typed builder
            # (#362). Returns the full Search dict including nested
            # Strategy*Add subtype block and PlacementTypes.
            # ``include_default=True`` mirrors the WSDL minOccurs=1
            # contract on add.
            _dyn_search_typed_for_required = any(
                value is not None
                for value in (
                    dyn_search_weekly_spend_limit,
                    dyn_search_bid_ceiling,
                    dyn_search_custom_period_spend_limit,
                    dyn_search_custom_period_start_date,
                    dyn_search_custom_period_end_date,
                    dyn_search_custom_period_auto_continue,
                    dyn_search_average_cpc,
                    dyn_search_average_cpa,
                    dyn_search_cpa,
                    dyn_search_goal_id,
                    dyn_search_crr,
                    dyn_search_clicks_per_week,
                    dyn_search_reserve_return,
                    dyn_search_roi_coef,
                    dyn_search_profitability,
                    dyn_search_exploration_budget,
                    dyn_search_exploration_budget_custom,
                )
            )
            # The legacy ``apply_cpa_strategy_fields`` builder (called
            # below) fills only the CPA-shape subtypes that overlap
            # with TextCampaign: ``AVERAGE_CPA`` and
            # ``PAY_FOR_CONVERSION_CRR``. For every other strategy the
            # new builder is the sole writer, so the WSDL minOccurs=1
            # required-field check must run on add — strategy-only
            # creates of e.g. AVERAGE_CPC / AVERAGE_ROI must NOT emit
            # an empty Strategy*Add block (the API would reject it).
            _legacy_search_subtypes = {
                "AVERAGE_CPA",
                "PAY_FOR_CONVERSION_CRR",
            }
            _strategy_normalized = (search_strategy or "").upper()
            _legacy_can_fill = (
                _strategy_normalized in _legacy_search_subtypes
                and not _dyn_search_typed_for_required
            )
            dyn_search_builder = get_bidding_strategy_builder(
                "DYNAMIC_TEXT_CAMPAIGN", "add", "search"
            )
            if dyn_search_builder is not None:
                dyn_search_block = dyn_search_builder(
                    search_strategy,
                    search_placement_search_results,
                    search_placement_product_gallery,
                    search_placement_dynamic_places,
                    dyn_search_weekly_spend_limit,
                    dyn_search_bid_ceiling,
                    dyn_search_custom_period_spend_limit,
                    dyn_search_custom_period_start_date,
                    dyn_search_custom_period_end_date,
                    dyn_search_custom_period_auto_continue,
                    dyn_search_average_cpc,
                    dyn_search_average_cpa,
                    dyn_search_cpa,
                    dyn_search_goal_id,
                    dyn_search_crr,
                    dyn_search_clicks_per_week,
                    dyn_search_reserve_return,
                    dyn_search_roi_coef,
                    dyn_search_profitability,
                    dyn_search_exploration_budget,
                    dyn_search_exploration_budget_custom,
                    budget_type=None,
                    include_default=True,
                    # Relax the WSDL minOccurs=1 check only when the
                    # legacy ``apply_cpa_strategy_fields`` path can
                    # fill the subtype (AVERAGE_CPA /
                    # PAY_FOR_CONVERSION_CRR) AND the user has not
                    # opted into the typed --dyn-search-* shape. For
                    # every other strategy the new builder enforces.
                    is_update=_legacy_can_fill,
                )
            else:
                dyn_search_block = {
                    "BiddingStrategyType": (search_strategy or "HIGHEST_POSITION")
                }
            dyn_block["BiddingStrategy"] = {
                "Search": dyn_search_block,
                "Network": dyn_network_block,
            }
            # If the user provided any new typed --dyn-search-* flag
            # (#362), the canonical Search payload has already been
            # built. Block combining with the legacy CPA-shape flags
            # (--average-cpa / --goal-id / --crr / --bid-ceiling)
            # to keep the WSDL contract unambiguous, then skip the
            # legacy apply_cpa_strategy_fields path so it does not
            # overwrite the canonical block on Search.
            dyn_search_typed_provided = _dyn_search_typed_for_required
            if dyn_search_typed_provided:
                legacy_provided = [
                    flag
                    for flag, value in (
                        ("--average-cpa", average_cpa),
                        ("--goal-id", goal_id),
                        ("--crr", crr),
                        ("--bid-ceiling", bid_ceiling),
                    )
                    if value is not None
                ]
                if legacy_provided:
                    raise click.UsageError(
                        t(
                            "DynamicTextCampaign Search typed flags (--dyn-search-*) cannot be combined with the legacy CPA-shape flags {arg0}; use the matching --dyn-search-* equivalent"
                        ).format(arg0=", ".join(sorted(legacy_provided)))
                    )
            # WSDL DynamicTextCampaignAddItem.PriorityGoals (line 2186)
            # is an optional sub-campaign field independent of the
            # BiddingStrategy subtype — same shape as Unified/Smart.
            # DynamicTextCampaignStrategyAddBase declares 9 subtypes
            # and neither DynamicTextCampaign{Search,Network}StrategyTypeEnum
            # includes AVERAGE_CPA_MULTIPLE_GOALS or
            # PAY_FOR_CONVERSION_MULTIPLE_GOALS, so PriorityGoals
            # always belongs on the parent block. The legacy builder
            # is still called with priority_goals_items=None for its
            # other job — placing AverageCpa/GoalId/Crr/BidCeiling
            # into the AVERAGE_CPA / PAY_FOR_CONVERSION_CRR subtype
            # block (issue #397).
            priority_goals_builder = get_bidding_strategy_builder(
                "DYNAMIC_TEXT_CAMPAIGN", "add", "priority_goals"
            )
            if priority_goals_builder is not None and not dyn_search_typed_provided:
                priority_goals_builder(
                    dyn_block["BiddingStrategy"],
                    search_strategy=search_strategy,
                    network_strategy=network_strategy,
                    goal_id=goal_id,
                    average_cpa=average_cpa,
                    crr=crr,
                    bid_ceiling=bid_ceiling,
                    priority_goals_items=None,
                    sub_campaign_block=dyn_block,
                )
            if priority_goals_items is not None:
                dyn_block["PriorityGoals"] = {"Items": priority_goals_items}
        if counter_ids_obj is not None:
            dyn_block["CounterIds"] = counter_ids_obj
        if dynamic_placement_types is not None:
            dyn_block["PlacementTypes"] = dynamic_placement_types
        if attribution_model:
            dyn_block["AttributionModel"] = attribution_model.upper()
        if negative_keyword_shared_set_ids_obj is not None:
            dyn_block["NegativeKeywordSharedSetIds"] = (
                negative_keyword_shared_set_ids_obj
            )
        if tracking_params:
            dyn_block["TrackingParams"] = tracking_params
        campaign_data["DynamicTextCampaign"] = dyn_block
    elif campaign_type_norm == "SMART_CAMPAIGN":
        # WSDL SmartCampaignAddItem.CounterId is minOccurs=1
        # (issue #198 H6).
        if counter_id is None:
            raise click.UsageError(
                t(
                    "--counter-id is required for SMART_CAMPAIGN "
                    "(WSDL SmartCampaignAddItem.CounterId minOccurs=1)"
                )
            )
        smart_campaign: Dict[str, object] = {"CounterId": counter_id}
        if smart_package_bidding_strategy_obj is not None:
            smart_campaign["PackageBiddingStrategy"] = (
                smart_package_bidding_strategy_obj
            )
        else:
            # SmartCampaign.BiddingStrategy.Search via shared builder (#367).
            # Returns ONLY the Search block. Network is built by a
            # separate registered builder (#368).
            smart_search_builder = get_bidding_strategy_builder(
                "SMART_CAMPAIGN", "add", "search"
            )
            if smart_search_builder is not None:
                search_block = smart_search_builder(
                    search_strategy,
                    smart_search_average_cpc,
                    smart_search_filter_average_cpc,
                    smart_search_average_cpa,
                    smart_search_filter_average_cpa,
                    smart_search_cpa,
                    smart_search_goal_id,
                    smart_search_weekly_spend_limit,
                    smart_search_bid_ceiling,
                    smart_search_reserve_return,
                    smart_search_roi_coef,
                    smart_search_profitability,
                    smart_search_crr,
                    smart_search_cp_spend_limit,
                    smart_search_cp_start_date,
                    smart_search_cp_end_date,
                    smart_search_cp_auto_continue,
                    smart_search_exploration_min,
                    smart_search_exploration_min_custom,
                    # --smart-search-budget-type is update-only, not
                    # available on the add Click command. Pass None.
                    None,
                    include_default=True,
                    is_update=False,
                )
            else:
                search_block = {"BiddingStrategyType": search_strategy or "SERVING_OFF"}
            # SmartCampaign.BiddingStrategy.Network via shared builder (#368).
            # The pre-#368 legacy contract is preserved exactly when the
            # user passes only --network-strategy (or nothing) + the
            # legacy --filter-average-cpc; mixing legacy with the typed
            # --smart-network-* surface raises UsageError so we never
            # silently drop user intent.
            smart_network_typed_values = {
                "--smart-network-average-cpc": smart_network_average_cpc,
                "--smart-network-filter-average-cpc": (
                    smart_network_filter_average_cpc
                ),
                "--smart-network-average-cpa": smart_network_average_cpa,
                "--smart-network-filter-average-cpa": (
                    smart_network_filter_average_cpa
                ),
                "--smart-network-cpa": smart_network_cpa,
                "--smart-network-goal-id": smart_network_goal_id,
                "--smart-network-weekly-spend-limit": (
                    smart_network_weekly_spend_limit
                ),
                "--smart-network-bid-ceiling": smart_network_bid_ceiling,
                "--smart-network-reserve-return": (smart_network_reserve_return),
                "--smart-network-roi-coef": smart_network_roi_coef,
                "--smart-network-profitability": smart_network_profitability,
                "--smart-network-crr": smart_network_crr,
                "--smart-network-limit-percent": smart_network_limit_percent,
                "--smart-network-cp-spend-limit": (smart_network_cp_spend_limit),
                "--smart-network-cp-start-date": (smart_network_cp_start_date),
                "--smart-network-cp-end-date": smart_network_cp_end_date,
                "--smart-network-cp-auto-continue": (smart_network_cp_auto_continue),
                "--smart-network-exploration-min": (smart_network_exploration_min),
                "--smart-network-exploration-min-custom": (
                    smart_network_exploration_min_custom
                ),
            }
            smart_network_typed_provided = [
                flag
                for flag, value in smart_network_typed_values.items()
                if value is not None
            ]
            if filter_average_cpc is not None and smart_network_typed_provided:
                raise click.UsageError(
                    t(
                        "--filter-average-cpc cannot be combined with typed "
                        "--smart-network-* flags; use "
                        "--smart-network-filter-average-cpc instead"
                    )
                )
            # Bridge the legacy --filter-average-cpc flag onto the new
            # typed Network builder. Only valid when network strategy is
            # AVERAGE_CPC_PER_FILTER (the historic default).
            effective_filter_average_cpc = smart_network_filter_average_cpc
            if filter_average_cpc is not None:
                legacy_strategy = (network_strategy or "AVERAGE_CPC_PER_FILTER").upper()
                if legacy_strategy != "AVERAGE_CPC_PER_FILTER":
                    raise click.UsageError(
                        t(
                            "--filter-average-cpc is only valid for "
                            "SMART_CAMPAIGN with AVERAGE_CPC_PER_FILTER "
                            "network strategy"
                        )
                    )
                effective_filter_average_cpc = filter_average_cpc
            effective_network_strategy = network_strategy
            if (
                effective_network_strategy is None
                and filter_average_cpc is None
                and not smart_network_typed_provided
            ):
                # Pre-#368 default: AVERAGE_CPC_PER_FILTER without any
                # FilterAverageCpc value (legitimate per WSDL, since
                # StrategyAverageCpcPerFilterAdd.FilterAverageCpc is
                # minOccurs=0). Kept as a back-compat hard default.
                effective_network_strategy = "AVERAGE_CPC_PER_FILTER"
            if effective_network_strategy is None and filter_average_cpc is not None:
                effective_network_strategy = "AVERAGE_CPC_PER_FILTER"
            smart_network_builder = get_bidding_strategy_builder(
                "SMART_CAMPAIGN", "add", "network"
            )
            network_block: Optional[dict]
            if smart_network_builder is not None:
                network_block = smart_network_builder(
                    effective_network_strategy,
                    smart_network_average_cpc,
                    effective_filter_average_cpc,
                    smart_network_average_cpa,
                    smart_network_filter_average_cpa,
                    smart_network_cpa,
                    smart_network_goal_id,
                    smart_network_weekly_spend_limit,
                    smart_network_bid_ceiling,
                    smart_network_reserve_return,
                    smart_network_roi_coef,
                    smart_network_profitability,
                    smart_network_crr,
                    smart_network_limit_percent,
                    smart_network_cp_spend_limit,
                    smart_network_cp_start_date,
                    smart_network_cp_end_date,
                    smart_network_cp_auto_continue,
                    smart_network_exploration_min,
                    smart_network_exploration_min_custom,
                    # --smart-network-budget-type is update-only, not
                    # available on the add Click command. Pass None.
                    None,
                    include_default=True,
                    is_update=False,
                )
            else:
                network_block = {
                    "BiddingStrategyType": (
                        effective_network_strategy or "AVERAGE_CPC_PER_FILTER"
                    )
                }
            assert network_block is not None
            smart_campaign["BiddingStrategy"] = {
                "Search": search_block,
                "Network": network_block,
            }
        if parsed_settings:
            smart_campaign["Settings"] = parsed_settings
        # SmartCampaignAddItem.PriorityGoals (#369) — top-level sibling on
        # the SmartCampaign block (WSDL tests/wsdl_cache/campaigns.xml
        # line 2209: ``PriorityGoalsArray`` minOccurs=0 maxOccurs=1).
        # Unlike Text/DynamicText, PriorityGoals on SmartCampaign is NOT
        # constrained to *_MULTIPLE_GOALS subtypes (no such subtypes exist
        # in SmartCampaignSearch/NetworkStrategyTypeEnum, lines 396-426):
        # it is an independent campaign-level setting accepted with any
        # SmartCampaign.BiddingStrategy. PackageBiddingStrategy already
        # excludes --priority-goals via the shared guard above.
        if priority_goals_items is not None:
            smart_campaign["PriorityGoals"] = {"Items": priority_goals_items}
        if attribution_model:
            smart_campaign["AttributionModel"] = attribution_model.upper()
        if tracking_params:
            smart_campaign["TrackingParams"] = tracking_params
        campaign_data["SmartCampaign"] = smart_campaign
    elif campaign_type_norm == "MOBILE_APP_CAMPAIGN":
        mobile_builder = get_bidding_strategy_builder(
            "MOBILE_APP_CAMPAIGN", "add", "full"
        )
        if mobile_builder is not None:
            mobile_bidding_strategy = mobile_builder(
                search_strategy,
                mobile_search_weekly_spend_limit,
                mobile_search_bid_ceiling,
                mobile_search_custom_period_spend_limit,
                mobile_search_custom_period_start_date,
                mobile_search_custom_period_end_date,
                mobile_search_custom_period_auto_continue,
                mobile_search_average_cpc,
                mobile_search_average_cpi,
                mobile_search_clicks_per_week,
                None,
                network_strategy,
                mobile_network_weekly_spend_limit,
                mobile_network_bid_ceiling,
                mobile_network_custom_period_spend_limit,
                mobile_network_custom_period_start_date,
                mobile_network_custom_period_end_date,
                mobile_network_custom_period_auto_continue,
                mobile_network_average_cpc,
                mobile_network_average_cpi,
                mobile_network_clicks_per_week,
                mobile_network_limit_percent,
                None,
                include_defaults=True,
                is_update=False,
            )
        else:
            mobile_bidding_strategy = {
                "Search": {
                    "BiddingStrategyType": (
                        (search_strategy or "HIGHEST_POSITION").upper()
                    )
                },
                "Network": {
                    "BiddingStrategyType": ((network_strategy or "SERVING_OFF").upper())
                },
            }
        mobile_campaign: Dict[str, object] = {
            "BiddingStrategy": mobile_bidding_strategy
        }
        if parsed_settings:
            mobile_campaign["Settings"] = parsed_settings
        if negative_keyword_shared_set_ids_obj is not None:
            mobile_campaign["NegativeKeywordSharedSetIds"] = (
                negative_keyword_shared_set_ids_obj
            )
        campaign_data["MobileAppCampaign"] = mobile_campaign
    elif campaign_type_norm == "CPM_BANNER_CAMPAIGN":
        cpm_builder = get_bidding_strategy_builder("CPM_BANNER_CAMPAIGN", "add", "full")
        if cpm_builder is not None:
            cpm_bidding_strategy = cpm_builder(
                search_strategy,
                network_strategy,
                average_cpm,
                average_cpv,
                strategy_spend_limit,
                strategy_start_date,
                strategy_end_date,
                strategy_auto_continue,
                include_defaults=True,
            )
        else:
            cpm_bidding_strategy = {
                "Search": {
                    "BiddingStrategyType": ((search_strategy or "SERVING_OFF").upper())
                },
                "Network": {
                    "BiddingStrategyType": ((network_strategy or "MANUAL_CPM").upper())
                },
            }
        cpm_campaign: Dict[str, object] = {"BiddingStrategy": cpm_bidding_strategy}
        if parsed_settings:
            cpm_campaign["Settings"] = parsed_settings
        if counter_ids_obj is not None:
            cpm_campaign["CounterIds"] = counter_ids_obj
        if frequency_cap_obj is not None:
            cpm_campaign["FrequencyCap"] = frequency_cap_obj
        if video_target:
            cpm_campaign["VideoTarget"] = video_target.upper()
        campaign_data["CpmBannerCampaign"] = cpm_campaign

    if budget:
        campaign_data["DailyBudget"] = {
            "Amount": budget,
            "Mode": "STANDARD",
        }

    if end_date:
        campaign_data["EndDate"] = end_date

    # Campaign-level fields are siblings of the subtype block.
    if client_info_obj:
        campaign_data["ClientInfo"] = client_info_obj
    if notification_obj is not None:
        campaign_data["Notification"] = notification_obj
    if time_zone:
        campaign_data["TimeZone"] = time_zone
    if negative_keywords_obj is not None:
        campaign_data["NegativeKeywords"] = negative_keywords_obj
    if blocked_ips_obj is not None:
        campaign_data["BlockedIps"] = blocked_ips_obj
    if excluded_sites_obj is not None:
        campaign_data["ExcludedSites"] = excluded_sites_obj
    if time_targeting_obj is not None:
        campaign_data["TimeTargeting"] = time_targeting_obj

    body = {"method": "add", "params": {"Campaigns": [campaign_data]}}

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = client.campaigns().post(data=body)
    format_output(result().extract(), "json", None)


@campaigns.command()
@click.option("--id", "campaign_id", required=True, type=int, help="Campaign ID")
@click.option("--name", help="New campaign name")
@click.option("--status", help="New status")
@click.option("--budget", type=MICRO_RUBLES, help="New daily budget in micro-rubles")
@click.option("--start-date", help="New start date (YYYY-MM-DD)")
@click.option("--end-date", help="New end date (YYYY-MM-DD)")
@click.option(
    "--setting",
    "settings",
    multiple=True,
    help="Campaign subtype Settings spec: OPTION=VALUE",
)
@click.option("--search-strategy", help="Search bidding strategy type")
@click.option("--network-strategy", help="Network bidding strategy type")
@click.option(
    "--search-placement-search-results",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=(
        "TextCampaign/UnifiedCampaign/DynamicTextCampaign Search "
        "PlacementTypes.SearchResults"
    ),
)
@click.option(
    "--search-placement-product-gallery",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=(
        "TextCampaign/UnifiedCampaign/DynamicTextCampaign Search "
        "PlacementTypes.ProductGallery"
    ),
)
@click.option(
    "--search-placement-dynamic-places",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=(
        "TextCampaign/UnifiedCampaign/DynamicTextCampaign Search "
        "PlacementTypes.DynamicPlaces"
    ),
)
@click.option("--counter-id", type=int, help="SmartCampaign.CounterId")
@click.option(
    "--counter-ids",
    help=(
        "Comma-separated TextCampaign/UnifiedCampaign/DynamicTextCampaign/"
        "CpmBannerCampaign.CounterIds.Items"
    ),
)
@click.option(
    "--dynamic-placement-search-results",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="DynamicTextCampaign.PlacementTypes SEARCH_RESULTS: YES or NO",
)
@click.option(
    "--dynamic-placement-product-gallery",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="DynamicTextCampaign.PlacementTypes PRODUCT_GALLERY: YES or NO",
)
@click.option(
    "--priority-goals",
    help=(
        "Comma-separated "
        "TextCampaign/UnifiedCampaign/DynamicTextCampaign/SmartCampaign."
        "PriorityGoals "
        "goal_id:value[:YES|NO] pairs. Value is in micro-currency "
        "(advertiser currency × 1,000,000), matching the API contract "
        "and other money flags."
    ),
)
@click.option(
    "--relevant-keywords-budget-percent",
    type=click.IntRange(1, 100),
    help="TextCampaign.RelevantKeywords.BudgetPercent",
)
@click.option(
    "--relevant-keywords-mode",
    type=click.Choice(RELEVANT_KEYWORDS_MODES, case_sensitive=False),
    help="TextCampaign.RelevantKeywords.Mode",
)
@click.option(
    "--relevant-keywords-optimize-goal-id",
    type=int,
    help="TextCampaign.RelevantKeywords.OptimizeGoalId",
)
@click.option(
    "--attribution-model",
    type=click.Choice(ATTRIBUTION_MODELS, case_sensitive=False),
    help=(
        "TextCampaign/UnifiedCampaign/DynamicTextCampaign/SmartCampaign."
        "AttributionModel"
    ),
)
@click.option(
    "--package-strategy-id",
    type=int,
    help=(
        "TextCampaign/UnifiedCampaign/DynamicTextCampaign/SmartCampaign."
        "PackageBiddingStrategy.StrategyId"
    ),
)
@click.option(
    "--package-strategy-from-campaign-id",
    type=int,
    help=(
        "TextCampaign/UnifiedCampaign/DynamicTextCampaign/SmartCampaign."
        "PackageBiddingStrategy.StrategyFromCampaignId"
    ),
)
@click.option(
    "--package-platform-search",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="SmartCampaign.PackageBiddingStrategy.Platforms.Search",
)
@click.option(
    "--package-platform-search-result",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="TextCampaign/UnifiedCampaign.PackageBiddingStrategy.Platforms.SearchResult",
)
@click.option(
    "--package-platform-product-gallery",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="TextCampaign/UnifiedCampaign.PackageBiddingStrategy.Platforms.ProductGallery",
)
@click.option(
    "--package-platform-maps",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="UnifiedCampaign.PackageBiddingStrategy.Platforms.Maps",
)
@click.option(
    "--package-platform-search-organization-list",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="UnifiedCampaign.PackageBiddingStrategy.Platforms.SearchOrganizationList",
)
@click.option(
    "--package-platform-network",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=(
        "TextCampaign/UnifiedCampaign/SmartCampaign."
        "PackageBiddingStrategy.Platforms.Network"
    ),
)
@click.option(
    "--package-platform-dynamic-places",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=(
        "TextCampaign/UnifiedCampaign.PackageBiddingStrategy.Platforms.DynamicPlaces"
    ),
)
@click.option(
    "--negative-keyword-shared-set-ids",
    help=(
        "Comma-separated "
        "TextCampaign/UnifiedCampaign/DynamicTextCampaign/MobileAppCampaign."
        "NegativeKeywordSharedSetIds.Items"
    ),
)
@click.option(
    "--frequency-cap-impressions",
    type=click.IntRange(1),
    help="CpmBannerCampaign.FrequencyCap.Impressions",
)
@click.option(
    "--frequency-cap-period-days",
    type=click.IntRange(1, 30),
    help="CpmBannerCampaign.FrequencyCap.PeriodDays, 1-30",
)
@click.option(
    "--frequency-cap-period-all",
    is_flag=True,
    help="Set CpmBannerCampaign.FrequencyCap.PeriodDays to null",
)
@click.option(
    "--video-target",
    type=click.Choice(VIDEO_TARGETS, case_sensitive=False),
    help="CpmBannerCampaign.VideoTarget: VIEWS or CLICKS",
)
@click.option(
    "--average-cpm",
    type=MICRO_RUBLES,
    help="CpmBannerCampaign strategy AverageCpm in micro-rubles",
)
@click.option(
    "--average-cpv",
    type=MICRO_RUBLES,
    help="CpmBannerCampaign strategy AverageCpv in micro-rubles",
)
@click.option(
    "--strategy-spend-limit",
    type=MICRO_RUBLES,
    help="CpmBannerCampaign strategy SpendLimit in micro-rubles",
)
@click.option("--strategy-start-date", help="CpmBannerCampaign strategy StartDate")
@click.option("--strategy-end-date", help="CpmBannerCampaign strategy EndDate")
@click.option(
    "--strategy-auto-continue",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="CpmBannerCampaign strategy AutoContinue: YES or NO",
)
@click.option(
    "--mobile-search-weekly-spend-limit",
    type=MICRO_RUBLES,
    help="MobileAppCampaign Search strategy WeeklySpendLimit in micro-rubles",
)
@click.option(
    "--mobile-search-bid-ceiling",
    type=MICRO_RUBLES,
    help="MobileAppCampaign Search strategy BidCeiling in micro-rubles",
)
@click.option(
    "--mobile-search-custom-period-spend-limit",
    type=MICRO_RUBLES,
    help="MobileAppCampaign Search CustomPeriodBudget.SpendLimit in micro-rubles",
)
@click.option(
    "--mobile-search-custom-period-start-date",
    help="MobileAppCampaign Search CustomPeriodBudget.StartDate",
)
@click.option(
    "--mobile-search-custom-period-end-date",
    help="MobileAppCampaign Search CustomPeriodBudget.EndDate",
)
@click.option(
    "--mobile-search-custom-period-auto-continue",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="MobileAppCampaign Search CustomPeriodBudget.AutoContinue: YES or NO",
)
@click.option(
    "--mobile-search-average-cpc",
    type=MICRO_RUBLES,
    help="MobileAppCampaign Search strategy AverageCpc in micro-rubles",
)
@click.option(
    "--mobile-search-average-cpi",
    type=MICRO_RUBLES,
    help="MobileAppCampaign Search strategy AverageCpi in micro-rubles",
)
@click.option(
    "--mobile-search-clicks-per-week",
    type=click.IntRange(1),
    help="MobileAppCampaign Search strategy ClicksPerWeek",
)
@click.option(
    "--mobile-search-budget-type",
    type=click.Choice(BUDGET_TYPES, case_sensitive=False),
    help="MobileAppCampaign Search strategy BudgetType for update",
)
@click.option(
    "--mobile-network-weekly-spend-limit",
    type=MICRO_RUBLES,
    help="MobileAppCampaign Network strategy WeeklySpendLimit in micro-rubles",
)
@click.option(
    "--mobile-network-bid-ceiling",
    type=MICRO_RUBLES,
    help="MobileAppCampaign Network strategy BidCeiling in micro-rubles",
)
@click.option(
    "--mobile-network-custom-period-spend-limit",
    type=MICRO_RUBLES,
    help="MobileAppCampaign Network CustomPeriodBudget.SpendLimit in micro-rubles",
)
@click.option(
    "--mobile-network-custom-period-start-date",
    help="MobileAppCampaign Network CustomPeriodBudget.StartDate",
)
@click.option(
    "--mobile-network-custom-period-end-date",
    help="MobileAppCampaign Network CustomPeriodBudget.EndDate",
)
@click.option(
    "--mobile-network-custom-period-auto-continue",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="MobileAppCampaign Network CustomPeriodBudget.AutoContinue: YES or NO",
)
@click.option(
    "--mobile-network-average-cpc",
    type=MICRO_RUBLES,
    help="MobileAppCampaign Network strategy AverageCpc in micro-rubles",
)
@click.option(
    "--mobile-network-average-cpi",
    type=MICRO_RUBLES,
    help="MobileAppCampaign Network strategy AverageCpi in micro-rubles",
)
@click.option(
    "--mobile-network-clicks-per-week",
    type=click.IntRange(1),
    help="MobileAppCampaign Network strategy ClicksPerWeek",
)
@click.option(
    "--mobile-network-limit-percent",
    type=click.IntRange(10, 100),
    help="MobileAppCampaign NetworkDefault.LimitPercent, 10-100 by tens",
)
@click.option(
    "--mobile-network-budget-type",
    type=click.Choice(BUDGET_TYPES, case_sensitive=False),
    help="MobileAppCampaign Network strategy BudgetType for update",
)
@click.option(
    "--goal-id",
    type=int,
    help="Single Metrika goal ID for CPA-shaped Search strategies",
)
@click.option(
    "--average-cpa",
    type=MICRO_RUBLES,
    help="Target CPA in micro-rubles for AVERAGE_CPA Search strategy",
)
@click.option(
    "--crr",
    type=int,
    help="CRR percentage for AVERAGE_CRR / PAY_FOR_CONVERSION_CRR strategies",
)
@click.option(
    "--bid-ceiling",
    type=MICRO_RUBLES,
    help="Bid ceiling in micro-rubles for the chosen Search strategy",
)
@click.option(
    "--text-search-weekly-spend-limit",
    type=MICRO_RUBLES,
    help="TextCampaign Search strategy WeeklySpendLimit in micro-rubles",
)
@click.option(
    "--text-search-custom-period-spend-limit",
    type=MICRO_RUBLES,
    help="TextCampaign Search CustomPeriodBudget.SpendLimit in micro-rubles",
)
@click.option(
    "--text-search-custom-period-start-date",
    help="TextCampaign Search CustomPeriodBudget.StartDate",
)
@click.option(
    "--text-search-custom-period-end-date",
    help="TextCampaign Search CustomPeriodBudget.EndDate",
)
@click.option(
    "--text-search-custom-period-auto-continue",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="TextCampaign Search CustomPeriodBudget.AutoContinue: YES or NO",
)
@click.option(
    "--text-search-budget-type",
    type=click.Choice(BUDGET_TYPES, case_sensitive=False),
    help="TextCampaign Search strategy BudgetType for update",
)
@click.option(
    "--text-search-average-cpc",
    type=MICRO_RUBLES,
    help="TextCampaign Search strategy AverageCpc in micro-rubles",
)
@click.option(
    "--text-search-pay-cpa",
    type=MICRO_RUBLES,
    help="TextCampaign Search StrategyPayForConversionAdd.Cpa in micro-rubles",
)
@click.option(
    "--text-search-clicks-per-week",
    type=click.IntRange(1),
    help="TextCampaign Search WEEKLY_CLICK_PACKAGE ClicksPerWeek",
)
@click.option(
    "--text-search-reserve-return",
    type=click.IntRange(0, 100),
    help=(
        "TextCampaign Search AVERAGE_ROI ReserveReturn percentage "
        "(0-100, multiple of 10)"
    ),
)
@click.option(
    "--text-search-roi-coef",
    type=MICRO_RUBLES,
    help=(
        "TextCampaign Search AVERAGE_ROI RoiCoef as a ratio (sales profit "
        "/ promotion costs), supplied directly in micro-rubles wire format "
        "(e.g. a 1.0 ratio is 1000000)."
    ),
)
@click.option(
    "--text-search-profitability",
    type=MICRO_RUBLES,
    help=(
        "TextCampaign Search AVERAGE_ROI Profitability percentage, "
        "supplied directly in micro-rubles wire format "
        "(e.g. 20% is 20000000)."
    ),
)
@click.option(
    "--text-search-exploration-min-budget",
    type=MICRO_RUBLES,
    help="TextCampaign Search ExplorationBudget.MinimumExplorationBudget in micro-rubles",
)
@click.option(
    "--text-search-exploration-is-custom",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=(
        "TextCampaign Search ExplorationBudget."
        "IsMinimumExplorationBudgetCustom: YES or NO"
    ),
)
# UnifiedCampaign.BiddingStrategy.Search typed flags (issue #363) — update
# variant. Same set as add() plus the update-only --unified-search-budget-type
# switch (WSDL BudgetType is declared on get/update-side Strategy* types
# only — campaigns.xml L789-957).
@click.option(
    "--unified-search-placement-maps",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="UnifiedCampaign Search PlacementTypes.Maps (#363)",
)
@click.option(
    "--unified-search-placement-search-organization-list",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=("UnifiedCampaign Search PlacementTypes.SearchOrganizationList (#363)"),
)
@click.option(
    "--unified-search-weekly-spend-limit",
    type=MICRO_RUBLES,
    help="UnifiedCampaign Search strategy WeeklySpendLimit in micro-rubles (#363)",
)
@click.option(
    "--unified-search-custom-period-spend-limit",
    type=MICRO_RUBLES,
    help="UnifiedCampaign Search CustomPeriodBudget.SpendLimit in micro-rubles (#363)",
)
@click.option(
    "--unified-search-custom-period-start-date",
    help="UnifiedCampaign Search CustomPeriodBudget.StartDate (#363)",
)
@click.option(
    "--unified-search-custom-period-end-date",
    help="UnifiedCampaign Search CustomPeriodBudget.EndDate (#363)",
)
@click.option(
    "--unified-search-custom-period-auto-continue",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="UnifiedCampaign Search CustomPeriodBudget.AutoContinue: YES or NO (#363)",
)
@click.option(
    "--unified-search-budget-type",
    type=click.Choice(BUDGET_TYPES, case_sensitive=False),
    help="UnifiedCampaign Search strategy BudgetType for update (#363)",
)
@click.option(
    "--unified-search-average-cpc",
    type=MICRO_RUBLES,
    help="UnifiedCampaign Search strategy AverageCpc in micro-rubles (#363)",
)
@click.option(
    "--unified-search-pay-cpa",
    type=MICRO_RUBLES,
    help="UnifiedCampaign Search StrategyPayForConversionAdd.Cpa in micro-rubles (#363)",
)
@click.option(
    "--unified-search-exploration-min-budget",
    type=MICRO_RUBLES,
    help=(
        "UnifiedCampaign Search ExplorationBudget.MinimumExplorationBudget "
        "in micro-rubles (#363)"
    ),
)
@click.option(
    "--unified-search-exploration-is-custom",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=(
        "UnifiedCampaign Search ExplorationBudget."
        "IsMinimumExplorationBudgetCustom: YES or NO (#363)"
    ),
)
@click.option(
    "--text-network-weekly-spend-limit",
    type=MICRO_RUBLES,
    help="TextCampaign Network strategy WeeklySpendLimit in micro-rubles (#364)",
)
@click.option(
    "--text-network-custom-period-spend-limit",
    type=MICRO_RUBLES,
    help="TextCampaign Network CustomPeriodBudget.SpendLimit in micro-rubles (#364)",
)
@click.option(
    "--text-network-custom-period-start-date",
    help="TextCampaign Network CustomPeriodBudget.StartDate (#364)",
)
@click.option(
    "--text-network-custom-period-end-date",
    help="TextCampaign Network CustomPeriodBudget.EndDate (#364)",
)
@click.option(
    "--text-network-custom-period-auto-continue",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=("TextCampaign Network CustomPeriodBudget.AutoContinue: YES or NO (#364)"),
)
@click.option(
    "--text-network-budget-type",
    type=click.Choice(BUDGET_TYPES, case_sensitive=False),
    help="TextCampaign Network strategy BudgetType for update (#364)",
)
@click.option(
    "--text-network-average-cpc",
    type=MICRO_RUBLES,
    help="TextCampaign Network strategy AverageCpc in micro-rubles (#364)",
)
@click.option(
    "--text-network-pay-cpa",
    type=MICRO_RUBLES,
    help="TextCampaign Network StrategyPayForConversionAdd.Cpa in micro-rubles (#364)",
)
@click.option(
    "--text-network-clicks-per-week",
    type=click.IntRange(1),
    help="TextCampaign Network WEEKLY_CLICK_PACKAGE ClicksPerWeek (#364)",
)
@click.option(
    "--text-network-reserve-return",
    type=click.IntRange(0, 100),
    help=(
        "TextCampaign Network AVERAGE_ROI ReserveReturn percentage "
        "(0-100, multiple of 10) (#364)"
    ),
)
@click.option(
    "--text-network-roi-coef",
    type=MICRO_RUBLES,
    help=(
        "TextCampaign Network AVERAGE_ROI RoiCoef as a ratio (sales profit "
        "/ promotion costs), supplied directly in micro-rubles wire format "
        "(e.g. a 1.0 ratio is 1000000) (#364)."
    ),
)
@click.option(
    "--text-network-profitability",
    type=MICRO_RUBLES,
    help=(
        "TextCampaign Network AVERAGE_ROI Profitability percentage, "
        "supplied directly in micro-rubles wire format "
        "(e.g. 20% is 20000000) (#364)."
    ),
)
@click.option(
    "--text-network-exploration-min-budget",
    type=MICRO_RUBLES,
    help=(
        "TextCampaign Network ExplorationBudget.MinimumExplorationBudget "
        "in micro-rubles (#364)"
    ),
)
@click.option(
    "--text-network-exploration-is-custom",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=(
        "TextCampaign Network ExplorationBudget."
        "IsMinimumExplorationBudgetCustom: YES or NO (#364)"
    ),
)
@click.option(
    "--text-network-limit-percent",
    type=click.IntRange(10, 100),
    help=("TextCampaign Network NetworkDefault.LimitPercent, 10-100 by tens (#364)"),
)
# UnifiedCampaign.BiddingStrategy.Network typed flags on update (#366).
@click.option(
    "--unified-network-weekly-spend-limit",
    type=MICRO_RUBLES,
    help="UnifiedCampaign Network strategy WeeklySpendLimit in micro-rubles (#366)",
)
@click.option(
    "--unified-network-custom-period-spend-limit",
    type=MICRO_RUBLES,
    help="UnifiedCampaign Network CustomPeriodBudget.SpendLimit in micro-rubles (#366)",
)
@click.option(
    "--unified-network-custom-period-start-date",
    help="UnifiedCampaign Network CustomPeriodBudget.StartDate (#366)",
)
@click.option(
    "--unified-network-custom-period-end-date",
    help="UnifiedCampaign Network CustomPeriodBudget.EndDate (#366)",
)
@click.option(
    "--unified-network-custom-period-auto-continue",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=("UnifiedCampaign Network CustomPeriodBudget.AutoContinue: YES or NO (#366)"),
)
@click.option(
    "--unified-network-average-cpc",
    type=MICRO_RUBLES,
    help="UnifiedCampaign Network StrategyAverageCpcAdd.AverageCpc in micro-rubles (#366)",
)
@click.option(
    "--unified-network-cpa",
    type=MICRO_RUBLES,
    help=(
        "UnifiedCampaign Network StrategyPayForConversionAdd.Cpa in micro-rubles (#366)"
    ),
)
@click.option(
    "--unified-network-exploration-min-budget",
    type=MICRO_RUBLES,
    help=(
        "UnifiedCampaign Network ExplorationBudget.MinimumExplorationBudget "
        "in micro-rubles (#366)"
    ),
)
@click.option(
    "--unified-network-exploration-is-custom",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=(
        "UnifiedCampaign Network ExplorationBudget."
        "IsMinimumExplorationBudgetCustom: YES or NO (#366)"
    ),
)
@click.option(
    "--unified-network-budget-type",
    type=click.Choice(BUDGET_TYPES, case_sensitive=False),
    help="UnifiedCampaign Network strategy BudgetType for update (#366)",
)
@click.option(
    "--dyn-network-weekly-spend-limit",
    type=MICRO_RUBLES,
    help="DynamicTextCampaign Network strategy WeeklySpendLimit in micro-rubles",
)
@click.option(
    "--dyn-network-bid-ceiling",
    type=MICRO_RUBLES,
    help="DynamicTextCampaign Network strategy BidCeiling in micro-rubles",
)
@click.option(
    "--dyn-network-custom-period-spend-limit",
    type=MICRO_RUBLES,
    help="DynamicTextCampaign Network CustomPeriodBudget.SpendLimit in micro-rubles",
)
@click.option(
    "--dyn-network-custom-period-start-date",
    help="DynamicTextCampaign Network CustomPeriodBudget.StartDate",
)
@click.option(
    "--dyn-network-custom-period-end-date",
    help="DynamicTextCampaign Network CustomPeriodBudget.EndDate",
)
@click.option(
    "--dyn-network-custom-period-auto-continue",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="DynamicTextCampaign Network CustomPeriodBudget.AutoContinue: YES or NO",
)
@click.option(
    "--dyn-network-average-cpc",
    type=MICRO_RUBLES,
    help="DynamicTextCampaign Network strategy AverageCpc in micro-rubles",
)
@click.option(
    "--dyn-network-average-cpa",
    type=MICRO_RUBLES,
    help="DynamicTextCampaign Network AverageCpa.AverageCpa in micro-rubles",
)
@click.option(
    "--dyn-network-cpa",
    type=MICRO_RUBLES,
    help="DynamicTextCampaign Network PayForConversion.Cpa in micro-rubles",
)
@click.option(
    "--dyn-network-goal-id",
    type=int,
    help="DynamicTextCampaign Network strategy GoalId",
)
@click.option(
    "--dyn-network-crr",
    type=click.IntRange(1, 1000),
    help="DynamicTextCampaign Network Crr percentage",
)
@click.option(
    "--dyn-network-clicks-per-week",
    type=click.IntRange(1),
    help="DynamicTextCampaign Network WeeklyClickPackage.ClicksPerWeek",
)
@click.option(
    "--dyn-network-limit-percent",
    type=click.IntRange(10, 100),
    help="DynamicTextCampaign NetworkDefault.LimitPercent, 10-100 by tens",
)
@click.option(
    "--dyn-network-reserve-return",
    type=click.IntRange(0, 100),
    help="DynamicTextCampaign Network AverageRoi.ReserveReturn percentage (0-100)",
)
@click.option(
    "--dyn-network-roi-coef",
    type=click.IntRange(0),
    help="DynamicTextCampaign Network AverageRoi.RoiCoef",
)
@click.option(
    "--dyn-network-profitability",
    type=click.IntRange(0),
    help="DynamicTextCampaign Network AverageRoi.Profitability",
)
@click.option(
    "--dyn-network-exploration-budget",
    type=MICRO_RUBLES,
    help=(
        "DynamicTextCampaign Network "
        "ExplorationBudget.MinimumExplorationBudget in micro-rubles"
    ),
)
@click.option(
    "--dyn-network-exploration-budget-custom",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=(
        "DynamicTextCampaign Network "
        "ExplorationBudget.IsMinimumExplorationBudgetCustom: YES or NO"
    ),
)
@click.option(
    "--dyn-network-budget-type",
    type=click.Choice(BUDGET_TYPES, case_sensitive=False),
    help="DynamicTextCampaign Network strategy BudgetType for update",
)
# DynamicTextCampaign.BiddingStrategy.Search typed flags on update (#362).
@click.option(
    "--dyn-search-weekly-spend-limit",
    type=MICRO_RUBLES,
    help="DynamicTextCampaign Search strategy WeeklySpendLimit in micro-rubles",
)
@click.option(
    "--dyn-search-bid-ceiling",
    type=MICRO_RUBLES,
    help="DynamicTextCampaign Search strategy BidCeiling in micro-rubles",
)
@click.option(
    "--dyn-search-custom-period-spend-limit",
    type=MICRO_RUBLES,
    help="DynamicTextCampaign Search CustomPeriodBudget.SpendLimit in micro-rubles",
)
@click.option(
    "--dyn-search-custom-period-start-date",
    help="DynamicTextCampaign Search CustomPeriodBudget.StartDate",
)
@click.option(
    "--dyn-search-custom-period-end-date",
    help="DynamicTextCampaign Search CustomPeriodBudget.EndDate",
)
@click.option(
    "--dyn-search-custom-period-auto-continue",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="DynamicTextCampaign Search CustomPeriodBudget.AutoContinue: YES or NO",
)
@click.option(
    "--dyn-search-average-cpc",
    type=MICRO_RUBLES,
    help="DynamicTextCampaign Search strategy AverageCpc in micro-rubles",
)
@click.option(
    "--dyn-search-average-cpa",
    type=MICRO_RUBLES,
    help="DynamicTextCampaign Search AverageCpa.AverageCpa in micro-rubles",
)
@click.option(
    "--dyn-search-cpa",
    type=MICRO_RUBLES,
    help="DynamicTextCampaign Search PayForConversion.Cpa in micro-rubles",
)
@click.option(
    "--dyn-search-goal-id",
    type=int,
    help="DynamicTextCampaign Search strategy GoalId",
)
@click.option(
    "--dyn-search-crr",
    type=click.IntRange(1, 1000),
    help="DynamicTextCampaign Search Crr percentage",
)
@click.option(
    "--dyn-search-clicks-per-week",
    type=click.IntRange(1),
    help="DynamicTextCampaign Search WeeklyClickPackage.ClicksPerWeek",
)
@click.option(
    "--dyn-search-reserve-return",
    type=click.IntRange(0, 100),
    help="DynamicTextCampaign Search AverageRoi.ReserveReturn percentage (0-100)",
)
@click.option(
    "--dyn-search-roi-coef",
    type=click.IntRange(0),
    help="DynamicTextCampaign Search AverageRoi.RoiCoef",
)
@click.option(
    "--dyn-search-profitability",
    type=click.IntRange(0),
    help="DynamicTextCampaign Search AverageRoi.Profitability",
)
@click.option(
    "--dyn-search-exploration-budget",
    type=MICRO_RUBLES,
    help=(
        "DynamicTextCampaign Search "
        "ExplorationBudget.MinimumExplorationBudget in micro-rubles"
    ),
)
@click.option(
    "--dyn-search-exploration-budget-custom",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=(
        "DynamicTextCampaign Search "
        "ExplorationBudget.IsMinimumExplorationBudgetCustom: YES or NO"
    ),
)
@click.option(
    "--dyn-search-budget-type",
    type=click.Choice(BUDGET_TYPES, case_sensitive=False),
    help="DynamicTextCampaign Search strategy BudgetType for update",
)
@click.option(
    "--smart-search-average-cpc",
    type=MICRO_RUBLES,
    help=(
        "SmartCampaign Search StrategyAverageCpcPerCampaign.AverageCpc "
        "in micro-rubles (#367)"
    ),
)
@click.option(
    "--smart-search-filter-average-cpc",
    type=MICRO_RUBLES,
    help=(
        "SmartCampaign Search StrategyAverageCpcPerFilter.FilterAverageCpc "
        "in micro-rubles (#367)"
    ),
)
@click.option(
    "--smart-search-average-cpa",
    type=MICRO_RUBLES,
    help=(
        "SmartCampaign Search StrategyAverageCpaPerCampaign.AverageCpa "
        "in micro-rubles (#367)"
    ),
)
@click.option(
    "--smart-search-filter-average-cpa",
    type=MICRO_RUBLES,
    help=(
        "SmartCampaign Search StrategyAverageCpaPerFilter.FilterAverageCpa "
        "in micro-rubles (#367)"
    ),
)
@click.option(
    "--smart-search-cpa",
    type=MICRO_RUBLES,
    help=(
        "SmartCampaign Search PayForConversion[Per{Campaign,Filter}].Cpa "
        "in micro-rubles (#367)"
    ),
)
@click.option(
    "--smart-search-goal-id",
    type=int,
    help="SmartCampaign Search Strategy*.GoalId Metrika goal ID (#367)",
)
@click.option(
    "--smart-search-weekly-spend-limit",
    type=MICRO_RUBLES,
    help="SmartCampaign Search Strategy*.WeeklySpendLimit in micro-rubles (#367)",
)
@click.option(
    "--smart-search-bid-ceiling",
    type=MICRO_RUBLES,
    help="SmartCampaign Search Strategy*.BidCeiling in micro-rubles (#367)",
)
@click.option(
    "--smart-search-reserve-return",
    type=int,
    help="SmartCampaign Search StrategyAverageRoi.ReserveReturn (#367)",
)
@click.option(
    "--smart-search-roi-coef",
    type=MICRO_RUBLES,
    help="SmartCampaign Search StrategyAverageRoi.RoiCoef in micro-rubles (#367)",
)
@click.option(
    "--smart-search-profitability",
    type=MICRO_RUBLES,
    help=(
        "SmartCampaign Search StrategyAverageRoi.Profitability in micro-rubles (#367)"
    ),
)
@click.option(
    "--smart-search-crr",
    type=int,
    help=(
        "SmartCampaign Search StrategyAverageCrr.Crr / "
        "StrategyPayForConversionCrr.Crr percentage (#367)"
    ),
)
@click.option(
    "--smart-search-cp-spend-limit",
    type=MICRO_RUBLES,
    help=("SmartCampaign Search CustomPeriodBudget.SpendLimit in micro-rubles (#367)"),
)
@click.option(
    "--smart-search-cp-start-date",
    help="SmartCampaign Search CustomPeriodBudget.StartDate (#367)",
)
@click.option(
    "--smart-search-cp-end-date",
    help="SmartCampaign Search CustomPeriodBudget.EndDate (#367)",
)
@click.option(
    "--smart-search-cp-auto-continue",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="SmartCampaign Search CustomPeriodBudget.AutoContinue: YES or NO (#367)",
)
@click.option(
    "--smart-search-exploration-min",
    type=MICRO_RUBLES,
    help=(
        "SmartCampaign Search ExplorationBudget.MinimumExplorationBudget "
        "in micro-rubles (#367)"
    ),
)
@click.option(
    "--smart-search-exploration-min-custom",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=(
        "SmartCampaign Search ExplorationBudget.IsMinimumExplorationBudgetCustom: "
        "YES or NO (#367)"
    ),
)
@click.option(
    "--smart-search-budget-type",
    type=click.Choice(BUDGET_TYPES, case_sensitive=False),
    help=(
        "SmartCampaign Search Strategy*.BudgetType (update-only WSDL field "
        "on get-side Strategy*; campaigns.xml 858-929) (#367)"
    ),
)
@click.option(
    "--smart-network-average-cpc",
    type=MICRO_RUBLES,
    help=(
        "SmartCampaign Network StrategyAverageCpcPerCampaign.AverageCpc "
        "in micro-rubles (#368)"
    ),
)
@click.option(
    "--smart-network-filter-average-cpc",
    type=MICRO_RUBLES,
    help=(
        "SmartCampaign Network StrategyAverageCpcPerFilter.FilterAverageCpc "
        "in micro-rubles (#368)"
    ),
)
@click.option(
    "--smart-network-average-cpa",
    type=MICRO_RUBLES,
    help=(
        "SmartCampaign Network StrategyAverageCpaPerCampaign.AverageCpa "
        "in micro-rubles (#368)"
    ),
)
@click.option(
    "--smart-network-filter-average-cpa",
    type=MICRO_RUBLES,
    help=(
        "SmartCampaign Network StrategyAverageCpaPerFilter.FilterAverageCpa "
        "in micro-rubles (#368)"
    ),
)
@click.option(
    "--smart-network-cpa",
    type=MICRO_RUBLES,
    help=(
        "SmartCampaign Network PayForConversion[Per{Campaign,Filter}].Cpa "
        "in micro-rubles (#368)"
    ),
)
@click.option(
    "--smart-network-goal-id",
    type=int,
    help="SmartCampaign Network Strategy*.GoalId Metrika goal ID (#368)",
)
@click.option(
    "--smart-network-weekly-spend-limit",
    type=MICRO_RUBLES,
    help="SmartCampaign Network Strategy*.WeeklySpendLimit in micro-rubles (#368)",
)
@click.option(
    "--smart-network-bid-ceiling",
    type=MICRO_RUBLES,
    help="SmartCampaign Network Strategy*.BidCeiling in micro-rubles (#368)",
)
@click.option(
    "--smart-network-reserve-return",
    type=int,
    help="SmartCampaign Network StrategyAverageRoi.ReserveReturn (#368)",
)
@click.option(
    "--smart-network-roi-coef",
    type=MICRO_RUBLES,
    help="SmartCampaign Network StrategyAverageRoi.RoiCoef in micro-rubles (#368)",
)
@click.option(
    "--smart-network-profitability",
    type=MICRO_RUBLES,
    help=(
        "SmartCampaign Network StrategyAverageRoi.Profitability in micro-rubles (#368)"
    ),
)
@click.option(
    "--smart-network-crr",
    type=int,
    help=(
        "SmartCampaign Network StrategyAverageCrr.Crr / "
        "StrategyPayForConversionCrr.Crr percentage (#368)"
    ),
)
@click.option(
    "--smart-network-limit-percent",
    type=click.IntRange(10, 100),
    help=(
        "SmartCampaign Network StrategyNetworkDefault.LimitPercent, "
        "10-100 by tens (#368)"
    ),
)
@click.option(
    "--smart-network-cp-spend-limit",
    type=MICRO_RUBLES,
    help=("SmartCampaign Network CustomPeriodBudget.SpendLimit in micro-rubles (#368)"),
)
@click.option(
    "--smart-network-cp-start-date",
    help="SmartCampaign Network CustomPeriodBudget.StartDate (#368)",
)
@click.option(
    "--smart-network-cp-end-date",
    help="SmartCampaign Network CustomPeriodBudget.EndDate (#368)",
)
@click.option(
    "--smart-network-cp-auto-continue",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="SmartCampaign Network CustomPeriodBudget.AutoContinue: YES or NO (#368)",
)
@click.option(
    "--smart-network-exploration-min",
    type=MICRO_RUBLES,
    help=(
        "SmartCampaign Network ExplorationBudget.MinimumExplorationBudget "
        "in micro-rubles (#368)"
    ),
)
@click.option(
    "--smart-network-exploration-min-custom",
    type=click.Choice(YES_NO, case_sensitive=False),
    help=(
        "SmartCampaign Network ExplorationBudget.IsMinimumExplorationBudgetCustom: "
        "YES or NO (#368)"
    ),
)
@click.option(
    "--smart-network-budget-type",
    type=click.Choice(BUDGET_TYPES, case_sensitive=False),
    help=(
        "SmartCampaign Network Strategy*.BudgetType (update-only WSDL field "
        "on get-side Strategy*; campaigns.xml 858-929) (#368)"
    ),
)
@click.option(
    "--notification",
    default=None,
    expose_value=False,
    callback=_deprecated_campaigns_structured_option,
    is_eager=True,
    hidden=True,
    help="Removed: use typed Notification flags",
)
@click.option(
    "--time-targeting",
    default=None,
    expose_value=False,
    callback=_deprecated_campaigns_structured_option,
    is_eager=True,
    hidden=True,
    help="Removed: use typed TimeTargeting flags",
)
@click.option(
    "--client-info",
    help="CampaignBase.ClientInfo client name, max 255 characters",
)
@click.option(
    "--sms-events",
    help="Comma-separated Notification.SmsSettings.Events values",
)
@click.option("--sms-time-from", help="Notification.SmsSettings.TimeFrom")
@click.option("--sms-time-to", help="Notification.SmsSettings.TimeTo")
@click.option("--notification-email", help="Notification.EmailSettings.Email")
@click.option(
    "--notification-check-position-interval",
    type=click.Choice(["15", "30", "60"]),
    help="Notification.EmailSettings.CheckPositionInterval",
)
@click.option(
    "--notification-warning-balance",
    type=click.IntRange(1, 50),
    help="Notification.EmailSettings.WarningBalance",
)
@click.option(
    "--notification-send-account-news",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="Notification.EmailSettings.SendAccountNews: YES or NO",
)
@click.option(
    "--notification-send-warnings",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="Notification.EmailSettings.SendWarnings: YES or NO",
)
@click.option("--time-zone", help="CampaignBase.TimeZone")
@click.option("--negative-keywords", help="Comma-separated NegativeKeywords.Items")
@click.option("--blocked-ips", help="Comma-separated BlockedIps.Items")
@click.option("--excluded-sites", help="Comma-separated ExcludedSites.Items")
@click.option(
    "--time-targeting-schedule",
    multiple=True,
    help="Repeatable TimeTargeting.Schedule.Items row",
)
@click.option(
    "--consider-working-weekends",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="TimeTargeting.ConsiderWorkingWeekends: YES or NO",
)
@click.option(
    "--holidays-suspend-on-holidays",
    type=click.Choice(YES_NO, case_sensitive=False),
    help="TimeTargeting.HolidaysSchedule.SuspendOnHolidays: YES or NO",
)
@click.option(
    "--holidays-bid-percent",
    type=click.IntRange(0, 200),
    help="TimeTargeting.HolidaysSchedule.BidPercent",
)
@click.option(
    "--holidays-start-hour",
    type=click.IntRange(0, 23),
    help="TimeTargeting.HolidaysSchedule.StartHour",
)
@click.option(
    "--holidays-end-hour",
    type=click.IntRange(0, 24),
    help="TimeTargeting.HolidaysSchedule.EndHour",
)
@click.option(
    "--type",
    "campaign_type",
    help=(
        "Campaign subtype "
        "(TEXT_CAMPAIGN | UNIFIED_CAMPAIGN | "
        "DYNAMIC_TEXT_CAMPAIGN | SMART_CAMPAIGN | "
        "MOBILE_APP_CAMPAIGN | CPM_BANNER_CAMPAIGN). "
        "Required when updating subtype-specific fields."
    ),
)
@click.option(
    "--tracking-params",
    "tracking_params",
    help=(
        "Tracking params query-string for "
        "TextCampaign/UnifiedCampaign/DynamicTextCampaign/SmartCampaign."
        "TrackingParams"
    ),
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def update(
    ctx,
    campaign_id,
    name,
    status,
    budget,
    start_date,
    end_date,
    settings,
    search_strategy,
    network_strategy,
    search_placement_search_results,
    search_placement_product_gallery,
    search_placement_dynamic_places,
    counter_id,
    counter_ids,
    dynamic_placement_search_results,
    dynamic_placement_product_gallery,
    priority_goals,
    relevant_keywords_budget_percent,
    relevant_keywords_mode,
    relevant_keywords_optimize_goal_id,
    attribution_model,
    package_strategy_id,
    package_strategy_from_campaign_id,
    package_platform_search,
    package_platform_search_result,
    package_platform_product_gallery,
    package_platform_maps,
    package_platform_search_organization_list,
    package_platform_network,
    package_platform_dynamic_places,
    negative_keyword_shared_set_ids,
    frequency_cap_impressions,
    frequency_cap_period_days,
    frequency_cap_period_all,
    video_target,
    average_cpm,
    average_cpv,
    strategy_spend_limit,
    strategy_start_date,
    strategy_end_date,
    strategy_auto_continue,
    mobile_search_weekly_spend_limit,
    mobile_search_bid_ceiling,
    mobile_search_custom_period_spend_limit,
    mobile_search_custom_period_start_date,
    mobile_search_custom_period_end_date,
    mobile_search_custom_period_auto_continue,
    mobile_search_average_cpc,
    mobile_search_average_cpi,
    mobile_search_clicks_per_week,
    mobile_search_budget_type,
    mobile_network_weekly_spend_limit,
    mobile_network_bid_ceiling,
    mobile_network_custom_period_spend_limit,
    mobile_network_custom_period_start_date,
    mobile_network_custom_period_end_date,
    mobile_network_custom_period_auto_continue,
    mobile_network_average_cpc,
    mobile_network_average_cpi,
    mobile_network_clicks_per_week,
    mobile_network_limit_percent,
    mobile_network_budget_type,
    goal_id,
    average_cpa,
    crr,
    bid_ceiling,
    text_search_weekly_spend_limit,
    text_search_custom_period_spend_limit,
    text_search_custom_period_start_date,
    text_search_custom_period_end_date,
    text_search_custom_period_auto_continue,
    text_search_budget_type,
    text_search_average_cpc,
    text_search_pay_cpa,
    text_search_clicks_per_week,
    text_search_reserve_return,
    text_search_roi_coef,
    text_search_profitability,
    text_search_exploration_min_budget,
    text_search_exploration_is_custom,
    unified_search_placement_maps,
    unified_search_placement_search_organization_list,
    unified_search_weekly_spend_limit,
    unified_search_custom_period_spend_limit,
    unified_search_custom_period_start_date,
    unified_search_custom_period_end_date,
    unified_search_custom_period_auto_continue,
    unified_search_budget_type,
    unified_search_average_cpc,
    unified_search_pay_cpa,
    unified_search_exploration_min_budget,
    unified_search_exploration_is_custom,
    text_network_weekly_spend_limit,
    text_network_custom_period_spend_limit,
    text_network_custom_period_start_date,
    text_network_custom_period_end_date,
    text_network_custom_period_auto_continue,
    text_network_budget_type,
    text_network_average_cpc,
    text_network_pay_cpa,
    text_network_clicks_per_week,
    text_network_reserve_return,
    text_network_roi_coef,
    text_network_profitability,
    text_network_exploration_min_budget,
    text_network_exploration_is_custom,
    text_network_limit_percent,
    unified_network_weekly_spend_limit,
    unified_network_custom_period_spend_limit,
    unified_network_custom_period_start_date,
    unified_network_custom_period_end_date,
    unified_network_custom_period_auto_continue,
    unified_network_average_cpc,
    unified_network_cpa,
    unified_network_exploration_min_budget,
    unified_network_exploration_is_custom,
    unified_network_budget_type,
    dyn_network_weekly_spend_limit,
    dyn_network_bid_ceiling,
    dyn_network_custom_period_spend_limit,
    dyn_network_custom_period_start_date,
    dyn_network_custom_period_end_date,
    dyn_network_custom_period_auto_continue,
    dyn_network_average_cpc,
    dyn_network_average_cpa,
    dyn_network_cpa,
    dyn_network_goal_id,
    dyn_network_crr,
    dyn_network_clicks_per_week,
    dyn_network_limit_percent,
    dyn_network_reserve_return,
    dyn_network_roi_coef,
    dyn_network_profitability,
    dyn_network_exploration_budget,
    dyn_network_exploration_budget_custom,
    dyn_network_budget_type,
    dyn_search_weekly_spend_limit,
    dyn_search_bid_ceiling,
    dyn_search_custom_period_spend_limit,
    dyn_search_custom_period_start_date,
    dyn_search_custom_period_end_date,
    dyn_search_custom_period_auto_continue,
    dyn_search_average_cpc,
    dyn_search_average_cpa,
    dyn_search_cpa,
    dyn_search_goal_id,
    dyn_search_crr,
    dyn_search_clicks_per_week,
    dyn_search_reserve_return,
    dyn_search_roi_coef,
    dyn_search_profitability,
    dyn_search_exploration_budget,
    dyn_search_exploration_budget_custom,
    dyn_search_budget_type,
    smart_search_average_cpc,
    smart_search_filter_average_cpc,
    smart_search_average_cpa,
    smart_search_filter_average_cpa,
    smart_search_cpa,
    smart_search_goal_id,
    smart_search_weekly_spend_limit,
    smart_search_bid_ceiling,
    smart_search_reserve_return,
    smart_search_roi_coef,
    smart_search_profitability,
    smart_search_crr,
    smart_search_cp_spend_limit,
    smart_search_cp_start_date,
    smart_search_cp_end_date,
    smart_search_cp_auto_continue,
    smart_search_exploration_min,
    smart_search_exploration_min_custom,
    smart_search_budget_type,
    smart_network_average_cpc,
    smart_network_filter_average_cpc,
    smart_network_average_cpa,
    smart_network_filter_average_cpa,
    smart_network_cpa,
    smart_network_goal_id,
    smart_network_weekly_spend_limit,
    smart_network_bid_ceiling,
    smart_network_reserve_return,
    smart_network_roi_coef,
    smart_network_profitability,
    smart_network_crr,
    smart_network_limit_percent,
    smart_network_cp_spend_limit,
    smart_network_cp_start_date,
    smart_network_cp_end_date,
    smart_network_cp_auto_continue,
    smart_network_exploration_min,
    smart_network_exploration_min_custom,
    smart_network_budget_type,
    client_info,
    sms_events,
    sms_time_from,
    sms_time_to,
    notification_email,
    notification_check_position_interval,
    notification_warning_balance,
    notification_send_account_news,
    notification_send_warnings,
    time_zone,
    negative_keywords,
    blocked_ips,
    excluded_sites,
    time_targeting_schedule,
    consider_working_weekends,
    holidays_suspend_on_holidays,
    holidays_bid_percent,
    holidays_start_hour,
    holidays_end_hour,
    campaign_type,
    tracking_params,
    dry_run,
):
    """Update campaign"""
    campaign_data = {"Id": campaign_id}

    if name:
        campaign_data["Name"] = name

    if status:
        campaign_data["Status"] = status

    if budget:
        campaign_data["DailyBudget"] = {
            "Amount": budget,
            "Mode": "STANDARD",
        }
    if start_date:
        campaign_data["StartDate"] = start_date
    if end_date:
        campaign_data["EndDate"] = end_date
    notification_obj = _build_notification(
        sms_events,
        sms_time_from,
        sms_time_to,
        notification_email,
        notification_check_position_interval,
        notification_warning_balance,
        notification_send_account_news,
        notification_send_warnings,
    )
    time_targeting_obj = _build_time_targeting(
        time_targeting_schedule,
        consider_working_weekends,
        holidays_suspend_on_holidays,
        holidays_bid_percent,
        holidays_start_hour,
        holidays_end_hour,
    )
    client_info_obj = _validate_max_length(
        "--client-info",
        client_info,
        CLIENT_INFO_MAX_LENGTH,
    )
    negative_keywords_obj = _array_of_string_option(
        "--negative-keywords", negative_keywords
    )
    blocked_ips_obj = _array_of_string_option(
        "--blocked-ips",
        blocked_ips,
        max_items=BLOCKED_IPS_MAX_ITEMS,
    )
    excluded_sites_obj = _array_of_string_option(
        "--excluded-sites",
        excluded_sites,
        max_items=EXCLUDED_SITES_MAX_ITEMS,
        max_item_length=EXCLUDED_SITE_MAX_LENGTH,
    )
    if client_info_obj:
        campaign_data["ClientInfo"] = client_info_obj
    if notification_obj is not None:
        campaign_data["Notification"] = notification_obj
    if time_zone:
        campaign_data["TimeZone"] = time_zone
    if negative_keywords_obj is not None:
        campaign_data["NegativeKeywords"] = negative_keywords_obj
    if blocked_ips_obj is not None:
        campaign_data["BlockedIps"] = blocked_ips_obj
    if excluded_sites_obj is not None:
        campaign_data["ExcludedSites"] = excluded_sites_obj
    if time_targeting_obj is not None:
        campaign_data["TimeTargeting"] = time_targeting_obj

    subtype_supported = {
        "TEXT_CAMPAIGN",
        "UNIFIED_CAMPAIGN",
        "DYNAMIC_TEXT_CAMPAIGN",
        "SMART_CAMPAIGN",
        "MOBILE_APP_CAMPAIGN",
        "CPM_BANNER_CAMPAIGN",
    }
    campaign_type_norm = (
        campaign_type.upper().replace("-", "_") if campaign_type else None
    )
    subtype_flag_values = {
        "--setting": list(settings) or None,
        "--search-strategy": search_strategy,
        "--network-strategy": network_strategy,
        "--search-placement-search-results": search_placement_search_results,
        "--search-placement-product-gallery": search_placement_product_gallery,
        "--search-placement-dynamic-places": search_placement_dynamic_places,
        "--counter-id": counter_id,
        "--counter-ids": counter_ids,
        "--dynamic-placement-search-results": dynamic_placement_search_results,
        "--dynamic-placement-product-gallery": dynamic_placement_product_gallery,
        "--priority-goals": priority_goals,
        "--relevant-keywords-budget-percent": relevant_keywords_budget_percent,
        "--relevant-keywords-mode": relevant_keywords_mode,
        "--relevant-keywords-optimize-goal-id": (relevant_keywords_optimize_goal_id),
        "--attribution-model": attribution_model,
        "--package-strategy-id": package_strategy_id,
        "--package-strategy-from-campaign-id": package_strategy_from_campaign_id,
        "--package-platform-search": package_platform_search,
        "--package-platform-search-result": package_platform_search_result,
        "--package-platform-product-gallery": package_platform_product_gallery,
        "--package-platform-maps": package_platform_maps,
        "--package-platform-search-organization-list": (
            package_platform_search_organization_list
        ),
        "--package-platform-network": package_platform_network,
        "--package-platform-dynamic-places": package_platform_dynamic_places,
        "--negative-keyword-shared-set-ids": negative_keyword_shared_set_ids,
        "--frequency-cap-impressions": frequency_cap_impressions,
        "--frequency-cap-period-days": frequency_cap_period_days,
        "--frequency-cap-period-all": frequency_cap_period_all or None,
        "--video-target": video_target,
        "--average-cpm": average_cpm,
        "--average-cpv": average_cpv,
        "--strategy-spend-limit": strategy_spend_limit,
        "--strategy-start-date": strategy_start_date,
        "--strategy-end-date": strategy_end_date,
        "--strategy-auto-continue": strategy_auto_continue,
        "--mobile-search-weekly-spend-limit": (mobile_search_weekly_spend_limit),
        "--mobile-search-bid-ceiling": mobile_search_bid_ceiling,
        "--mobile-search-custom-period-spend-limit": (
            mobile_search_custom_period_spend_limit
        ),
        "--mobile-search-custom-period-start-date": (
            mobile_search_custom_period_start_date
        ),
        "--mobile-search-custom-period-end-date": (
            mobile_search_custom_period_end_date
        ),
        "--mobile-search-custom-period-auto-continue": (
            mobile_search_custom_period_auto_continue
        ),
        "--mobile-search-average-cpc": mobile_search_average_cpc,
        "--mobile-search-average-cpi": mobile_search_average_cpi,
        "--mobile-search-clicks-per-week": mobile_search_clicks_per_week,
        "--mobile-search-budget-type": mobile_search_budget_type,
        "--mobile-network-weekly-spend-limit": (mobile_network_weekly_spend_limit),
        "--mobile-network-bid-ceiling": mobile_network_bid_ceiling,
        "--mobile-network-custom-period-spend-limit": (
            mobile_network_custom_period_spend_limit
        ),
        "--mobile-network-custom-period-start-date": (
            mobile_network_custom_period_start_date
        ),
        "--mobile-network-custom-period-end-date": (
            mobile_network_custom_period_end_date
        ),
        "--mobile-network-custom-period-auto-continue": (
            mobile_network_custom_period_auto_continue
        ),
        "--mobile-network-average-cpc": mobile_network_average_cpc,
        "--mobile-network-average-cpi": mobile_network_average_cpi,
        "--mobile-network-clicks-per-week": mobile_network_clicks_per_week,
        "--mobile-network-limit-percent": mobile_network_limit_percent,
        "--mobile-network-budget-type": mobile_network_budget_type,
        "--goal-id": goal_id,
        "--average-cpa": average_cpa,
        "--crr": crr,
        "--bid-ceiling": bid_ceiling,
        "--text-search-weekly-spend-limit": text_search_weekly_spend_limit,
        "--text-search-custom-period-spend-limit": (
            text_search_custom_period_spend_limit
        ),
        "--text-search-custom-period-start-date": (
            text_search_custom_period_start_date
        ),
        "--text-search-custom-period-end-date": (text_search_custom_period_end_date),
        "--text-search-custom-period-auto-continue": (
            text_search_custom_period_auto_continue
        ),
        "--text-search-budget-type": text_search_budget_type,
        "--text-search-average-cpc": text_search_average_cpc,
        "--text-search-pay-cpa": text_search_pay_cpa,
        "--text-search-clicks-per-week": text_search_clicks_per_week,
        "--text-search-reserve-return": text_search_reserve_return,
        "--text-search-roi-coef": text_search_roi_coef,
        "--text-search-profitability": text_search_profitability,
        "--text-search-exploration-min-budget": (text_search_exploration_min_budget),
        "--text-search-exploration-is-custom": (text_search_exploration_is_custom),
        # UnifiedCampaign.BiddingStrategy.Search typed flags (#363).
        "--unified-search-placement-maps": unified_search_placement_maps,
        "--unified-search-placement-search-organization-list": (
            unified_search_placement_search_organization_list
        ),
        "--unified-search-weekly-spend-limit": (unified_search_weekly_spend_limit),
        "--unified-search-custom-period-spend-limit": (
            unified_search_custom_period_spend_limit
        ),
        "--unified-search-custom-period-start-date": (
            unified_search_custom_period_start_date
        ),
        "--unified-search-custom-period-end-date": (
            unified_search_custom_period_end_date
        ),
        "--unified-search-custom-period-auto-continue": (
            unified_search_custom_period_auto_continue
        ),
        "--unified-search-budget-type": unified_search_budget_type,
        "--unified-search-average-cpc": unified_search_average_cpc,
        "--unified-search-pay-cpa": unified_search_pay_cpa,
        "--unified-search-exploration-min-budget": (
            unified_search_exploration_min_budget
        ),
        "--unified-search-exploration-is-custom": (
            unified_search_exploration_is_custom
        ),
        "--text-network-weekly-spend-limit": (text_network_weekly_spend_limit),
        "--text-network-custom-period-spend-limit": (
            text_network_custom_period_spend_limit
        ),
        "--text-network-custom-period-start-date": (
            text_network_custom_period_start_date
        ),
        "--text-network-custom-period-end-date": (text_network_custom_period_end_date),
        "--text-network-custom-period-auto-continue": (
            text_network_custom_period_auto_continue
        ),
        "--text-network-budget-type": text_network_budget_type,
        "--text-network-average-cpc": text_network_average_cpc,
        "--text-network-pay-cpa": text_network_pay_cpa,
        "--text-network-clicks-per-week": text_network_clicks_per_week,
        "--text-network-reserve-return": text_network_reserve_return,
        "--text-network-roi-coef": text_network_roi_coef,
        "--text-network-profitability": text_network_profitability,
        "--text-network-exploration-min-budget": (text_network_exploration_min_budget),
        "--text-network-exploration-is-custom": (text_network_exploration_is_custom),
        "--text-network-limit-percent": text_network_limit_percent,
        "--dyn-network-weekly-spend-limit": dyn_network_weekly_spend_limit,
        "--dyn-network-bid-ceiling": dyn_network_bid_ceiling,
        "--dyn-network-custom-period-spend-limit": (
            dyn_network_custom_period_spend_limit
        ),
        "--dyn-network-custom-period-start-date": (
            dyn_network_custom_period_start_date
        ),
        "--dyn-network-custom-period-end-date": (dyn_network_custom_period_end_date),
        "--dyn-network-custom-period-auto-continue": (
            dyn_network_custom_period_auto_continue
        ),
        "--dyn-network-average-cpc": dyn_network_average_cpc,
        "--dyn-network-average-cpa": dyn_network_average_cpa,
        "--dyn-network-cpa": dyn_network_cpa,
        "--dyn-network-goal-id": dyn_network_goal_id,
        "--dyn-network-crr": dyn_network_crr,
        "--dyn-network-clicks-per-week": dyn_network_clicks_per_week,
        "--dyn-network-limit-percent": dyn_network_limit_percent,
        "--dyn-network-reserve-return": dyn_network_reserve_return,
        "--dyn-network-roi-coef": dyn_network_roi_coef,
        "--dyn-network-profitability": dyn_network_profitability,
        "--dyn-network-exploration-budget": dyn_network_exploration_budget,
        "--dyn-network-exploration-budget-custom": (
            dyn_network_exploration_budget_custom
        ),
        "--dyn-network-budget-type": dyn_network_budget_type,
        # DynamicTextCampaign.BiddingStrategy.Search typed flags (#362)
        "--dyn-search-weekly-spend-limit": dyn_search_weekly_spend_limit,
        "--dyn-search-bid-ceiling": dyn_search_bid_ceiling,
        "--dyn-search-custom-period-spend-limit": (
            dyn_search_custom_period_spend_limit
        ),
        "--dyn-search-custom-period-start-date": (dyn_search_custom_period_start_date),
        "--dyn-search-custom-period-end-date": (dyn_search_custom_period_end_date),
        "--dyn-search-custom-period-auto-continue": (
            dyn_search_custom_period_auto_continue
        ),
        "--dyn-search-average-cpc": dyn_search_average_cpc,
        "--dyn-search-average-cpa": dyn_search_average_cpa,
        "--dyn-search-cpa": dyn_search_cpa,
        "--dyn-search-goal-id": dyn_search_goal_id,
        "--dyn-search-crr": dyn_search_crr,
        "--dyn-search-clicks-per-week": dyn_search_clicks_per_week,
        "--dyn-search-reserve-return": dyn_search_reserve_return,
        "--dyn-search-roi-coef": dyn_search_roi_coef,
        "--dyn-search-profitability": dyn_search_profitability,
        "--dyn-search-exploration-budget": dyn_search_exploration_budget,
        "--dyn-search-exploration-budget-custom": (
            dyn_search_exploration_budget_custom
        ),
        "--dyn-search-budget-type": dyn_search_budget_type,
        # SmartCampaign.BiddingStrategy.Search typed flags (#367)
        "--smart-search-average-cpc": smart_search_average_cpc,
        "--smart-search-filter-average-cpc": smart_search_filter_average_cpc,
        "--smart-search-average-cpa": smart_search_average_cpa,
        "--smart-search-filter-average-cpa": smart_search_filter_average_cpa,
        "--smart-search-cpa": smart_search_cpa,
        "--smart-search-goal-id": smart_search_goal_id,
        "--smart-search-weekly-spend-limit": smart_search_weekly_spend_limit,
        "--smart-search-bid-ceiling": smart_search_bid_ceiling,
        "--smart-search-reserve-return": smart_search_reserve_return,
        "--smart-search-roi-coef": smart_search_roi_coef,
        "--smart-search-profitability": smart_search_profitability,
        "--smart-search-crr": smart_search_crr,
        "--smart-search-cp-spend-limit": smart_search_cp_spend_limit,
        "--smart-search-cp-start-date": smart_search_cp_start_date,
        "--smart-search-cp-end-date": smart_search_cp_end_date,
        "--smart-search-cp-auto-continue": smart_search_cp_auto_continue,
        "--smart-search-exploration-min": smart_search_exploration_min,
        "--smart-search-exploration-min-custom": (smart_search_exploration_min_custom),
        "--smart-search-budget-type": smart_search_budget_type,
        # SmartCampaign.BiddingStrategy.Network typed flags (#368)
        "--smart-network-average-cpc": smart_network_average_cpc,
        "--smart-network-filter-average-cpc": smart_network_filter_average_cpc,
        "--smart-network-average-cpa": smart_network_average_cpa,
        "--smart-network-filter-average-cpa": (smart_network_filter_average_cpa),
        "--smart-network-cpa": smart_network_cpa,
        "--smart-network-goal-id": smart_network_goal_id,
        "--smart-network-weekly-spend-limit": smart_network_weekly_spend_limit,
        "--smart-network-bid-ceiling": smart_network_bid_ceiling,
        "--smart-network-reserve-return": smart_network_reserve_return,
        "--smart-network-roi-coef": smart_network_roi_coef,
        "--smart-network-profitability": smart_network_profitability,
        "--smart-network-crr": smart_network_crr,
        "--smart-network-limit-percent": smart_network_limit_percent,
        "--smart-network-cp-spend-limit": smart_network_cp_spend_limit,
        "--smart-network-cp-start-date": smart_network_cp_start_date,
        "--smart-network-cp-end-date": smart_network_cp_end_date,
        "--smart-network-cp-auto-continue": smart_network_cp_auto_continue,
        "--smart-network-exploration-min": smart_network_exploration_min,
        "--smart-network-exploration-min-custom": (
            smart_network_exploration_min_custom
        ),
        "--smart-network-budget-type": smart_network_budget_type,
        # UnifiedCampaign.BiddingStrategy.Network typed flags (#366).
        "--unified-network-weekly-spend-limit": (unified_network_weekly_spend_limit),
        "--unified-network-custom-period-spend-limit": (
            unified_network_custom_period_spend_limit
        ),
        "--unified-network-custom-period-start-date": (
            unified_network_custom_period_start_date
        ),
        "--unified-network-custom-period-end-date": (
            unified_network_custom_period_end_date
        ),
        "--unified-network-custom-period-auto-continue": (
            unified_network_custom_period_auto_continue
        ),
        "--unified-network-average-cpc": unified_network_average_cpc,
        "--unified-network-cpa": unified_network_cpa,
        "--unified-network-exploration-min-budget": (
            unified_network_exploration_min_budget
        ),
        "--unified-network-exploration-is-custom": (
            unified_network_exploration_is_custom
        ),
        "--unified-network-budget-type": unified_network_budget_type,
        "--tracking-params": tracking_params,
    }
    subtype_flags_provided = [
        flag for flag, value in subtype_flag_values.items() if value is not None
    ]
    if campaign_type_norm is not None and campaign_type_norm not in subtype_supported:
        raise click.UsageError(
            t(
                "Invalid value for '--type': {campaign_type!r} is not one of 'TEXT_CAMPAIGN', 'UNIFIED_CAMPAIGN', 'DYNAMIC_TEXT_CAMPAIGN', 'SMART_CAMPAIGN', 'MOBILE_APP_CAMPAIGN', 'CPM_BANNER_CAMPAIGN'."
            ).format(campaign_type=campaign_type)
        )
    if subtype_flags_provided and campaign_type_norm is None:
        raise click.UsageError(
            t(
                "{arg0} requires --type (TEXT_CAMPAIGN | UNIFIED_CAMPAIGN | DYNAMIC_TEXT_CAMPAIGN | SMART_CAMPAIGN | MOBILE_APP_CAMPAIGN | CPM_BANNER_CAMPAIGN)."
            ).format(arg0=", ".join(sorted(subtype_flags_provided)))
        )
    if campaign_type_norm is not None:
        text_campaign_flags = {
            "--setting",
            "--search-strategy",
            "--network-strategy",
            "--search-placement-search-results",
            "--search-placement-product-gallery",
            "--search-placement-dynamic-places",
            "--counter-ids",
            "--priority-goals",
            "--relevant-keywords-budget-percent",
            "--relevant-keywords-mode",
            "--relevant-keywords-optimize-goal-id",
            "--attribution-model",
            "--package-strategy-id",
            "--package-strategy-from-campaign-id",
            "--package-platform-search-result",
            "--package-platform-product-gallery",
            "--package-platform-network",
            "--package-platform-dynamic-places",
            "--negative-keyword-shared-set-ids",
            "--tracking-params",
            # Legacy CPA flags (also accepted on add, see #361 / #290).
            "--goal-id",
            "--average-cpa",
            "--crr",
            "--bid-ceiling",
            # Issue #361: TextCampaign Search strategy detail flags
            "--text-search-weekly-spend-limit",
            "--text-search-custom-period-spend-limit",
            "--text-search-custom-period-start-date",
            "--text-search-custom-period-end-date",
            "--text-search-custom-period-auto-continue",
            "--text-search-budget-type",
            "--text-search-average-cpc",
            "--text-search-pay-cpa",
            "--text-search-clicks-per-week",
            "--text-search-reserve-return",
            "--text-search-roi-coef",
            "--text-search-profitability",
            "--text-search-exploration-min-budget",
            "--text-search-exploration-is-custom",
            # Issue #364: TextCampaign Network strategy detail flags
            "--text-network-weekly-spend-limit",
            "--text-network-custom-period-spend-limit",
            "--text-network-custom-period-start-date",
            "--text-network-custom-period-end-date",
            "--text-network-custom-period-auto-continue",
            "--text-network-budget-type",
            "--text-network-average-cpc",
            "--text-network-pay-cpa",
            "--text-network-clicks-per-week",
            "--text-network-reserve-return",
            "--text-network-roi-coef",
            "--text-network-profitability",
            "--text-network-exploration-min-budget",
            "--text-network-exploration-is-custom",
            "--text-network-limit-percent",
        }
        dynamic_campaign_flags = {
            "--setting",
            "--counter-ids",
            "--dynamic-placement-search-results",
            "--dynamic-placement-product-gallery",
            "--priority-goals",
            "--attribution-model",
            "--package-strategy-id",
            "--package-strategy-from-campaign-id",
            "--negative-keyword-shared-set-ids",
            "--tracking-params",
            # DynamicTextCampaign.BiddingStrategy.Network on update (#365).
            "--network-strategy",
            "--dyn-network-weekly-spend-limit",
            "--dyn-network-bid-ceiling",
            "--dyn-network-custom-period-spend-limit",
            "--dyn-network-custom-period-start-date",
            "--dyn-network-custom-period-end-date",
            "--dyn-network-custom-period-auto-continue",
            "--dyn-network-average-cpc",
            "--dyn-network-average-cpa",
            "--dyn-network-cpa",
            "--dyn-network-goal-id",
            "--dyn-network-crr",
            "--dyn-network-clicks-per-week",
            "--dyn-network-limit-percent",
            "--dyn-network-reserve-return",
            "--dyn-network-roi-coef",
            "--dyn-network-profitability",
            "--dyn-network-exploration-budget",
            "--dyn-network-exploration-budget-custom",
            "--dyn-network-budget-type",
            # DynamicTextCampaign.BiddingStrategy.Search on update (#362).
            "--search-strategy",
            "--search-placement-search-results",
            "--search-placement-product-gallery",
            "--search-placement-dynamic-places",
            "--dyn-search-weekly-spend-limit",
            "--dyn-search-bid-ceiling",
            "--dyn-search-custom-period-spend-limit",
            "--dyn-search-custom-period-start-date",
            "--dyn-search-custom-period-end-date",
            "--dyn-search-custom-period-auto-continue",
            "--dyn-search-average-cpc",
            "--dyn-search-average-cpa",
            "--dyn-search-cpa",
            "--dyn-search-goal-id",
            "--dyn-search-crr",
            "--dyn-search-clicks-per-week",
            "--dyn-search-reserve-return",
            "--dyn-search-roi-coef",
            "--dyn-search-profitability",
            "--dyn-search-exploration-budget",
            "--dyn-search-exploration-budget-custom",
            "--dyn-search-budget-type",
        }
        unified_campaign_flags = {
            "--setting",
            "--counter-ids",
            "--priority-goals",
            "--attribution-model",
            "--package-strategy-id",
            "--package-strategy-from-campaign-id",
            "--package-platform-search-result",
            "--package-platform-product-gallery",
            "--package-platform-maps",
            "--package-platform-search-organization-list",
            "--package-platform-network",
            "--package-platform-dynamic-places",
            "--negative-keyword-shared-set-ids",
            "--tracking-params",
            # UnifiedCampaign.BiddingStrategy.Network on update (#366).
            "--network-strategy",
            "--unified-network-weekly-spend-limit",
            "--unified-network-custom-period-spend-limit",
            "--unified-network-custom-period-start-date",
            "--unified-network-custom-period-end-date",
            "--unified-network-custom-period-auto-continue",
            "--unified-network-average-cpc",
            "--unified-network-cpa",
            "--unified-network-exploration-min-budget",
            "--unified-network-exploration-is-custom",
            "--unified-network-budget-type",
            # UnifiedCampaign.BiddingStrategy.Search typed flags (#363).
            "--search-strategy",
            "--search-placement-search-results",
            "--search-placement-product-gallery",
            "--search-placement-dynamic-places",
            # Shared legacy CPA flags routed to Unified.Network/Search.
            "--goal-id",
            "--average-cpa",
            "--crr",
            "--bid-ceiling",
            "--unified-search-placement-maps",
            "--unified-search-placement-search-organization-list",
            "--unified-search-weekly-spend-limit",
            "--unified-search-custom-period-spend-limit",
            "--unified-search-custom-period-start-date",
            "--unified-search-custom-period-end-date",
            "--unified-search-custom-period-auto-continue",
            "--unified-search-budget-type",
            "--unified-search-average-cpc",
            "--unified-search-pay-cpa",
            "--unified-search-exploration-min-budget",
            "--unified-search-exploration-is-custom",
        }
        smart_campaign_flags = {
            "--setting",
            "--counter-id",
            "--priority-goals",
            "--attribution-model",
            "--package-strategy-id",
            "--package-strategy-from-campaign-id",
            "--package-platform-search",
            "--package-platform-network",
            "--tracking-params",
            "--search-strategy",
            "--network-strategy",
            # SmartCampaign.BiddingStrategy.Search typed flags (#367)
            "--smart-search-average-cpc",
            "--smart-search-filter-average-cpc",
            "--smart-search-average-cpa",
            "--smart-search-filter-average-cpa",
            "--smart-search-cpa",
            "--smart-search-goal-id",
            "--smart-search-weekly-spend-limit",
            "--smart-search-bid-ceiling",
            "--smart-search-reserve-return",
            "--smart-search-roi-coef",
            "--smart-search-profitability",
            "--smart-search-crr",
            "--smart-search-cp-spend-limit",
            "--smart-search-cp-start-date",
            "--smart-search-cp-end-date",
            "--smart-search-cp-auto-continue",
            "--smart-search-exploration-min",
            "--smart-search-exploration-min-custom",
            "--smart-search-budget-type",
            # SmartCampaign.BiddingStrategy.Network typed flags (#368)
            "--smart-network-average-cpc",
            "--smart-network-filter-average-cpc",
            "--smart-network-average-cpa",
            "--smart-network-filter-average-cpa",
            "--smart-network-cpa",
            "--smart-network-goal-id",
            "--smart-network-weekly-spend-limit",
            "--smart-network-bid-ceiling",
            "--smart-network-reserve-return",
            "--smart-network-roi-coef",
            "--smart-network-profitability",
            "--smart-network-crr",
            "--smart-network-limit-percent",
            "--smart-network-cp-spend-limit",
            "--smart-network-cp-start-date",
            "--smart-network-cp-end-date",
            "--smart-network-cp-auto-continue",
            "--smart-network-exploration-min",
            "--smart-network-exploration-min-custom",
            "--smart-network-budget-type",
        }
        mobile_app_campaign_flags = {
            "--setting",
            "--search-strategy",
            "--network-strategy",
            "--mobile-search-weekly-spend-limit",
            "--mobile-search-bid-ceiling",
            "--mobile-search-custom-period-spend-limit",
            "--mobile-search-custom-period-start-date",
            "--mobile-search-custom-period-end-date",
            "--mobile-search-custom-period-auto-continue",
            "--mobile-search-average-cpc",
            "--mobile-search-average-cpi",
            "--mobile-search-clicks-per-week",
            "--mobile-search-budget-type",
            "--mobile-network-weekly-spend-limit",
            "--mobile-network-bid-ceiling",
            "--mobile-network-custom-period-spend-limit",
            "--mobile-network-custom-period-start-date",
            "--mobile-network-custom-period-end-date",
            "--mobile-network-custom-period-auto-continue",
            "--mobile-network-average-cpc",
            "--mobile-network-average-cpi",
            "--mobile-network-clicks-per-week",
            "--mobile-network-limit-percent",
            "--mobile-network-budget-type",
            "--negative-keyword-shared-set-ids",
        }
        cpm_banner_campaign_flags = {
            "--setting",
            "--search-strategy",
            "--network-strategy",
            "--counter-ids",
            "--frequency-cap-impressions",
            "--frequency-cap-period-days",
            "--frequency-cap-period-all",
            "--video-target",
            "--average-cpm",
            "--average-cpv",
            "--strategy-spend-limit",
            "--strategy-start-date",
            "--strategy-end-date",
            "--strategy-auto-continue",
        }
        allowed_subtype_flags_by_type = {
            "TEXT_CAMPAIGN": text_campaign_flags,
            "UNIFIED_CAMPAIGN": unified_campaign_flags,
            "DYNAMIC_TEXT_CAMPAIGN": dynamic_campaign_flags,
            "SMART_CAMPAIGN": smart_campaign_flags,
            "MOBILE_APP_CAMPAIGN": mobile_app_campaign_flags,
            "CPM_BANNER_CAMPAIGN": cpm_banner_campaign_flags,
        }
        reject_incompatible_flags(
            allowed_subtype_flags_by_type[campaign_type_norm],
            subtype_flag_values,
            message="{arg0} is not compatible with --type {command_type}.",
            type_value=campaign_type_norm,
            type_field="command_type",
        )
        if campaign_type_norm == "UNIFIED_CAMPAIGN":
            unified_campaign_level_conflicts = {
                "--client-info": client_info_obj,
                "--sms-events": sms_events,
                "--sms-time-from": sms_time_from,
                "--sms-time-to": sms_time_to,
                "--notification-check-position-interval": (
                    notification_check_position_interval
                ),
                "--notification-warning-balance": notification_warning_balance,
                "--notification-send-warnings": notification_send_warnings,
            }
            provided = [
                flag
                for flag, value in unified_campaign_level_conflicts.items()
                if value is not None
            ]
            if provided:
                raise click.UsageError(
                    t("UnifiedCampaign cannot be combined with {arg0}").format(
                        arg0=", ".join(sorted(provided))
                    )
                )
        sub_block: Dict[str, object] = {}
        if campaign_type_norm in {
            "TEXT_CAMPAIGN",
            "UNIFIED_CAMPAIGN",
            "DYNAMIC_TEXT_CAMPAIGN",
        }:
            is_unified = campaign_type_norm == "UNIFIED_CAMPAIGN"
            is_dynamic = campaign_type_norm == "DYNAMIC_TEXT_CAMPAIGN"
            package_label = (
                "UnifiedCampaign"
                if is_unified
                else "DynamicTextCampaign" if is_dynamic else "TextCampaign"
            )
            parsed_settings = parse_setting_specs(list(settings))
            if parsed_settings:
                sub_block["Settings"] = parsed_settings
            if is_dynamic:
                dynamic_placement_types = _build_dynamic_placement_types(
                    dynamic_placement_search_results,
                    dynamic_placement_product_gallery,
                )
                if dynamic_placement_types is not None:
                    sub_block["PlacementTypes"] = dynamic_placement_types
            counter_ids_obj = _array_of_integer_option("--counter-ids", counter_ids)
            if counter_ids_obj is not None:
                sub_block["CounterIds"] = counter_ids_obj
            priority_goals_items = _priority_goals_update_items(
                parse_priority_goals_spec(priority_goals)
            )
            if priority_goals_items is not None:
                sub_block["PriorityGoals"] = {"Items": priority_goals_items}
            if not is_unified and not is_dynamic:
                relevant_keywords_obj = _build_relevant_keywords(
                    relevant_keywords_budget_percent,
                    relevant_keywords_mode,
                    relevant_keywords_optimize_goal_id,
                    require_budget_percent=False,
                )
                if relevant_keywords_obj is not None:
                    sub_block["RelevantKeywords"] = relevant_keywords_obj
            if attribution_model:
                sub_block["AttributionModel"] = attribution_model.upper()
            package_bidding_strategy_obj = _build_package_bidding_strategy(
                package_strategy_id,
                package_strategy_from_campaign_id,
                package_platform_search_result,
                package_platform_product_gallery,
                package_platform_maps,
                package_platform_search_organization_list,
                package_platform_network,
                package_platform_dynamic_places,
                campaign_label=package_label,
                require_platforms=False,
            )
            if package_bidding_strategy_obj is not None:
                package_incompatible: Dict[str, object] = {}
                # Issue #373: ``UnifiedCampaignUpdateItem.PriorityGoals``
                # (WSDL ``tests/wsdl_cache/campaigns.xml`` line 2259) is a
                # nillable sibling of ``UnifiedCampaignUpdateItem.
                # PackageBiddingStrategy`` (line 2260-2262) on the same
                # ``xsd:sequence`` (no ``xsd:choice``). Mirrors the
                # SmartCampaign precedent (#369/#392). Other non-Smart
                # package campaign types (TextCampaign,
                # DynamicTextCampaign) keep the mutex until their own
                # follow-up issues land.
                if not is_unified:
                    package_incompatible["--priority-goals"] = priority_goals
                if not is_unified and not is_dynamic:
                    package_incompatible.update(
                        {
                            "--search-strategy": search_strategy,
                            "--search-placement-search-results": (
                                search_placement_search_results
                            ),
                            "--search-placement-product-gallery": (
                                search_placement_product_gallery
                            ),
                            "--search-placement-dynamic-places": (
                                search_placement_dynamic_places
                            ),
                            # Issue #361: TextCampaign Search-strategy
                            # detail flags and the legacy CPA flags must
                            # also conflict with PackageBiddingStrategy
                            # on update so user input is never silently
                            # dropped.
                            "--goal-id": goal_id,
                            "--average-cpa": average_cpa,
                            "--crr": crr,
                            "--bid-ceiling": bid_ceiling,
                            "--text-search-weekly-spend-limit": (
                                text_search_weekly_spend_limit
                            ),
                            "--text-search-custom-period-spend-limit": (
                                text_search_custom_period_spend_limit
                            ),
                            "--text-search-custom-period-start-date": (
                                text_search_custom_period_start_date
                            ),
                            "--text-search-custom-period-end-date": (
                                text_search_custom_period_end_date
                            ),
                            "--text-search-custom-period-auto-continue": (
                                text_search_custom_period_auto_continue
                            ),
                            "--text-search-budget-type": (text_search_budget_type),
                            "--text-search-average-cpc": (text_search_average_cpc),
                            "--text-search-pay-cpa": text_search_pay_cpa,
                            "--text-search-clicks-per-week": (
                                text_search_clicks_per_week
                            ),
                            "--text-search-reserve-return": (
                                text_search_reserve_return
                            ),
                            "--text-search-roi-coef": text_search_roi_coef,
                            "--text-search-profitability": (text_search_profitability),
                            "--text-search-exploration-min-budget": (
                                text_search_exploration_min_budget
                            ),
                            "--text-search-exploration-is-custom": (
                                text_search_exploration_is_custom
                            ),
                            # Issue #364: TextCampaign Network typed
                            # flags must conflict with PackageBidding-
                            # Strategy on update for the same reason.
                            "--network-strategy": network_strategy,
                            "--text-network-weekly-spend-limit": (
                                text_network_weekly_spend_limit
                            ),
                            "--text-network-custom-period-spend-limit": (
                                text_network_custom_period_spend_limit
                            ),
                            "--text-network-custom-period-start-date": (
                                text_network_custom_period_start_date
                            ),
                            "--text-network-custom-period-end-date": (
                                text_network_custom_period_end_date
                            ),
                            "--text-network-custom-period-auto-continue": (
                                text_network_custom_period_auto_continue
                            ),
                            "--text-network-budget-type": (text_network_budget_type),
                            "--text-network-average-cpc": (text_network_average_cpc),
                            "--text-network-pay-cpa": text_network_pay_cpa,
                            "--text-network-clicks-per-week": (
                                text_network_clicks_per_week
                            ),
                            "--text-network-reserve-return": (
                                text_network_reserve_return
                            ),
                            "--text-network-roi-coef": text_network_roi_coef,
                            "--text-network-profitability": (
                                text_network_profitability
                            ),
                            "--text-network-exploration-min-budget": (
                                text_network_exploration_min_budget
                            ),
                            "--text-network-exploration-is-custom": (
                                text_network_exploration_is_custom
                            ),
                            "--text-network-limit-percent": (
                                text_network_limit_percent
                            ),
                        }
                    )
                if is_unified:
                    package_incompatible.update(
                        {
                            "--counter-ids": counter_ids,
                            "--attribution-model": attribution_model,
                            # UnifiedCampaign.BiddingStrategy.Network
                            # typed flags must conflict with
                            # PackageBiddingStrategy on update (#366) —
                            # mirror DynamicTextCampaign behavior.
                            "--network-strategy": network_strategy,
                            "--unified-network-weekly-spend-limit": (
                                unified_network_weekly_spend_limit
                            ),
                            "--unified-network-custom-period-spend-limit": (
                                unified_network_custom_period_spend_limit
                            ),
                            "--unified-network-custom-period-start-date": (
                                unified_network_custom_period_start_date
                            ),
                            "--unified-network-custom-period-end-date": (
                                unified_network_custom_period_end_date
                            ),
                            "--unified-network-custom-period-auto-continue": (
                                unified_network_custom_period_auto_continue
                            ),
                            "--unified-network-average-cpc": (
                                unified_network_average_cpc
                            ),
                            "--unified-network-cpa": unified_network_cpa,
                            "--unified-network-exploration-min-budget": (
                                unified_network_exploration_min_budget
                            ),
                            "--unified-network-exploration-is-custom": (
                                unified_network_exploration_is_custom
                            ),
                            "--unified-network-budget-type": (
                                unified_network_budget_type
                            ),
                            # UnifiedCampaign.BiddingStrategy.Search typed
                            # flags (#363) — mutually exclusive with
                            # PackageBiddingStrategy on update.
                            "--search-strategy": search_strategy,
                            "--search-placement-search-results": (
                                search_placement_search_results
                            ),
                            "--search-placement-product-gallery": (
                                search_placement_product_gallery
                            ),
                            "--search-placement-dynamic-places": (
                                search_placement_dynamic_places
                            ),
                            "--goal-id": goal_id,
                            "--average-cpa": average_cpa,
                            "--crr": crr,
                            "--bid-ceiling": bid_ceiling,
                            "--unified-search-placement-maps": (
                                unified_search_placement_maps
                            ),
                            "--unified-search-placement-search-organization-list": (
                                unified_search_placement_search_organization_list
                            ),
                            "--unified-search-weekly-spend-limit": (
                                unified_search_weekly_spend_limit
                            ),
                            "--unified-search-custom-period-spend-limit": (
                                unified_search_custom_period_spend_limit
                            ),
                            "--unified-search-custom-period-start-date": (
                                unified_search_custom_period_start_date
                            ),
                            "--unified-search-custom-period-end-date": (
                                unified_search_custom_period_end_date
                            ),
                            "--unified-search-custom-period-auto-continue": (
                                unified_search_custom_period_auto_continue
                            ),
                            "--unified-search-budget-type": (
                                unified_search_budget_type
                            ),
                            "--unified-search-average-cpc": (
                                unified_search_average_cpc
                            ),
                            "--unified-search-pay-cpa": unified_search_pay_cpa,
                            "--unified-search-exploration-min-budget": (
                                unified_search_exploration_min_budget
                            ),
                            "--unified-search-exploration-is-custom": (
                                unified_search_exploration_is_custom
                            ),
                        }
                    )
                if is_dynamic:
                    package_incompatible.update(
                        {
                            "--network-strategy": network_strategy,
                            "--dyn-network-weekly-spend-limit": (
                                dyn_network_weekly_spend_limit
                            ),
                            "--dyn-network-bid-ceiling": (dyn_network_bid_ceiling),
                            "--dyn-network-custom-period-spend-limit": (
                                dyn_network_custom_period_spend_limit
                            ),
                            "--dyn-network-custom-period-start-date": (
                                dyn_network_custom_period_start_date
                            ),
                            "--dyn-network-custom-period-end-date": (
                                dyn_network_custom_period_end_date
                            ),
                            "--dyn-network-custom-period-auto-continue": (
                                dyn_network_custom_period_auto_continue
                            ),
                            "--dyn-network-average-cpc": (dyn_network_average_cpc),
                            "--dyn-network-average-cpa": (dyn_network_average_cpa),
                            "--dyn-network-cpa": dyn_network_cpa,
                            "--dyn-network-goal-id": dyn_network_goal_id,
                            "--dyn-network-crr": dyn_network_crr,
                            "--dyn-network-clicks-per-week": (
                                dyn_network_clicks_per_week
                            ),
                            "--dyn-network-limit-percent": (dyn_network_limit_percent),
                            "--dyn-network-reserve-return": (
                                dyn_network_reserve_return
                            ),
                            "--dyn-network-roi-coef": dyn_network_roi_coef,
                            "--dyn-network-profitability": (dyn_network_profitability),
                            "--dyn-network-exploration-budget": (
                                dyn_network_exploration_budget
                            ),
                            "--dyn-network-exploration-budget-custom": (
                                dyn_network_exploration_budget_custom
                            ),
                            "--dyn-network-budget-type": (dyn_network_budget_type),
                            # DynamicTextCampaign Search typed flags (#362).
                            "--search-strategy": search_strategy,
                            "--search-placement-search-results": (
                                search_placement_search_results
                            ),
                            "--search-placement-product-gallery": (
                                search_placement_product_gallery
                            ),
                            "--search-placement-dynamic-places": (
                                search_placement_dynamic_places
                            ),
                            "--dyn-search-weekly-spend-limit": (
                                dyn_search_weekly_spend_limit
                            ),
                            "--dyn-search-bid-ceiling": dyn_search_bid_ceiling,
                            "--dyn-search-custom-period-spend-limit": (
                                dyn_search_custom_period_spend_limit
                            ),
                            "--dyn-search-custom-period-start-date": (
                                dyn_search_custom_period_start_date
                            ),
                            "--dyn-search-custom-period-end-date": (
                                dyn_search_custom_period_end_date
                            ),
                            "--dyn-search-custom-period-auto-continue": (
                                dyn_search_custom_period_auto_continue
                            ),
                            "--dyn-search-average-cpc": dyn_search_average_cpc,
                            "--dyn-search-average-cpa": dyn_search_average_cpa,
                            "--dyn-search-cpa": dyn_search_cpa,
                            "--dyn-search-goal-id": dyn_search_goal_id,
                            "--dyn-search-crr": dyn_search_crr,
                            "--dyn-search-clicks-per-week": (
                                dyn_search_clicks_per_week
                            ),
                            "--dyn-search-reserve-return": (dyn_search_reserve_return),
                            "--dyn-search-roi-coef": dyn_search_roi_coef,
                            "--dyn-search-profitability": (dyn_search_profitability),
                            "--dyn-search-exploration-budget": (
                                dyn_search_exploration_budget
                            ),
                            "--dyn-search-exploration-budget-custom": (
                                dyn_search_exploration_budget_custom
                            ),
                            "--dyn-search-budget-type": dyn_search_budget_type,
                        }
                    )
                provided = [
                    flag
                    for flag, value in package_incompatible.items()
                    if value is not None
                ]
                if provided:
                    raise click.UsageError(
                        t(
                            "{package_label}.PackageBiddingStrategy cannot be combined with {arg0}"
                        ).format(
                            package_label=package_label,
                            arg0=", ".join(sorted(provided)),
                        )
                    )
                sub_block["PackageBiddingStrategy"] = package_bidding_strategy_obj
            elif is_unified:
                # UnifiedCampaign.BiddingStrategy update — Network (#366)
                # and Search (#363). Shared legacy CPA flags are routed
                # per-side based on which subtype actually accepts the
                # WSDL field (mirrors the add path and TextCampaign
                # update). include_default=False: with neither
                # --network-strategy / --search-strategy nor any
                # --unified-{network,search}-* / shared CPA flag the
                # corresponding side is left untouched (returns None).
                _u_search_subtype_for_routing_up = (
                    _UNIFIED_CAMPAIGN_SEARCH_STRATEGY_TO_WSDL_SUBTYPE.get(
                        (search_strategy or "").upper()
                    )
                )
                _u_network_subtype_for_routing_up = (
                    UNIFIED_CAMPAIGN_NETWORK_STRATEGY_TO_WSDL_SUBTYPE.get(
                        (network_strategy or "").upper()
                    )
                )

                def _u_route_update(
                    value,
                    search_support: set,
                    network_support: set,
                    default: str,
                ):
                    if value is None:
                        return (None, None)
                    s_ok = _u_search_subtype_for_routing_up in search_support
                    n_ok = _u_network_subtype_for_routing_up in network_support
                    if s_ok and n_ok:
                        return (value, value)
                    if s_ok:
                        return (value, None)
                    if n_ok:
                        return (None, value)
                    if default == "network":
                        return (None, value)
                    return (value, None)

                _u_default_side_up = (
                    "network"
                    if network_strategy is not None and search_strategy is None
                    else "search"
                )
                _u_search_goal_id_up, _u_network_goal_id_up = _u_route_update(
                    goal_id,
                    _UNIFIED_SEARCH_SUPPORTS_GOAL_ID,
                    _UNIFIED_NETWORK_GOAL_ID_SUBTYPES,
                    default=_u_default_side_up,
                )
                (
                    _u_search_average_cpa_up,
                    _u_network_average_cpa_up,
                ) = _u_route_update(
                    average_cpa,
                    _UNIFIED_SEARCH_SUPPORTS_AVERAGE_CPA,
                    _UNIFIED_NETWORK_AVERAGE_CPA_SUBTYPES,
                    default=_u_default_side_up,
                )
                _u_search_crr_up, _u_network_crr_up = _u_route_update(
                    crr,
                    _UNIFIED_SEARCH_SUPPORTS_CRR,
                    _UNIFIED_NETWORK_CRR_SUBTYPES,
                    default=_u_default_side_up,
                )
                (
                    _u_search_bid_ceiling_up,
                    _u_network_bid_ceiling_up,
                ) = _u_route_update(
                    bid_ceiling,
                    _UNIFIED_SEARCH_SUPPORTS_BID_CEILING,
                    _UNIFIED_NETWORK_BID_CEILING_SUBTYPES,
                    default=_u_default_side_up,
                )

                # PriorityGoals: route to whichever side accepts it
                # for the chosen subtype. The Network builder writes
                # via sub_campaign_block; the Search builder does
                # not write on update (PriorityGoals placement on
                # update is owned by #373).
                _u_search_uses_pg_up = (
                    _u_search_subtype_for_routing_up
                    in _UNIFIED_SEARCH_REQUIRES_PRIORITY_GOALS
                )
                _u_network_uses_pg_up = (
                    _u_network_subtype_for_routing_up
                    in _UNIFIED_NETWORK_REQUIRES_PRIORITY_GOALS
                )
                if _u_search_uses_pg_up or _u_network_uses_pg_up:
                    _u_search_pg_items_up = (
                        priority_goals_items if _u_search_uses_pg_up else None
                    )
                    _u_network_pg_items_up = (
                        priority_goals_items if _u_network_uses_pg_up else None
                    )
                else:
                    _u_search_pg_items_up = None
                    _u_network_pg_items_up = priority_goals_items

                unified_network_builder = get_bidding_strategy_builder(
                    "UNIFIED_CAMPAIGN", "update", "network"
                )
                if unified_network_builder is not None:
                    unified_network_block = unified_network_builder(
                        network_strategy=network_strategy,
                        goal_id=_u_network_goal_id_up,
                        average_cpa=_u_network_average_cpa_up,
                        crr=_u_network_crr_up,
                        bid_ceiling=_u_network_bid_ceiling_up,
                        weekly_spend_limit=(unified_network_weekly_spend_limit),
                        custom_period_spend_limit=(
                            unified_network_custom_period_spend_limit
                        ),
                        custom_period_start_date=(
                            unified_network_custom_period_start_date
                        ),
                        custom_period_end_date=(unified_network_custom_period_end_date),
                        custom_period_auto_continue=(
                            unified_network_custom_period_auto_continue
                        ),
                        budget_type=unified_network_budget_type,
                        average_cpc=unified_network_average_cpc,
                        cpa=unified_network_cpa,
                        exploration_min_budget=(unified_network_exploration_min_budget),
                        exploration_is_custom=(unified_network_exploration_is_custom),
                        priority_goals_items=_u_network_pg_items_up,
                        sub_campaign_block=sub_block,
                        include_default=False,
                        is_update=True,
                    )
                else:
                    unified_network_block = (
                        {"BiddingStrategyType": network_strategy.upper()}
                        if network_strategy is not None
                        else None
                    )

                unified_search_builder = get_bidding_strategy_builder(
                    "UNIFIED_CAMPAIGN", "update", "search"
                )
                unified_search_block = None
                if unified_search_builder is not None:
                    unified_search_block = unified_search_builder(
                        search_strategy=search_strategy,
                        search_placement_search_results=(
                            search_placement_search_results
                        ),
                        search_placement_product_gallery=(
                            search_placement_product_gallery
                        ),
                        search_placement_dynamic_places=(
                            search_placement_dynamic_places
                        ),
                        search_placement_maps=unified_search_placement_maps,
                        search_placement_search_organization_list=(
                            unified_search_placement_search_organization_list
                        ),
                        goal_id=_u_search_goal_id_up,
                        average_cpa=_u_search_average_cpa_up,
                        crr=_u_search_crr_up,
                        bid_ceiling=_u_search_bid_ceiling_up,
                        weekly_spend_limit=unified_search_weekly_spend_limit,
                        custom_period_spend_limit=(
                            unified_search_custom_period_spend_limit
                        ),
                        custom_period_start_date=(
                            unified_search_custom_period_start_date
                        ),
                        custom_period_end_date=(unified_search_custom_period_end_date),
                        custom_period_auto_continue=(
                            unified_search_custom_period_auto_continue
                        ),
                        budget_type=unified_search_budget_type,
                        average_cpc=unified_search_average_cpc,
                        pay_cpa=unified_search_pay_cpa,
                        exploration_min_budget=(unified_search_exploration_min_budget),
                        exploration_is_custom=(unified_search_exploration_is_custom),
                        priority_goals_items=_u_search_pg_items_up,
                        sub_campaign_block=sub_block,
                        include_default=False,
                        is_update=True,
                    )
                else:
                    unified_search_block = (
                        {"BiddingStrategyType": search_strategy.upper()}
                        if search_strategy is not None
                        else None
                    )

                if (
                    unified_network_block is not None
                    or unified_search_block is not None
                ):
                    bs_u: Dict[str, object] = {}
                    if unified_search_block is not None:
                        bs_u["Search"] = unified_search_block
                    if unified_network_block is not None:
                        bs_u["Network"] = unified_network_block
                    sub_block["BiddingStrategy"] = bs_u
            elif is_dynamic:
                # DynamicTextCampaign.BiddingStrategy.Network update
                # (#365). Build via shared builder; include_default
                # is False so an absent --network-strategy with no
                # detail flags leaves BiddingStrategy untouched.
                dyn_network_builder = get_bidding_strategy_builder(
                    "DYNAMIC_TEXT_CAMPAIGN", "update", "network"
                )
                if dyn_network_builder is not None:
                    dyn_network_block = dyn_network_builder(
                        network_strategy,
                        dyn_network_weekly_spend_limit,
                        dyn_network_bid_ceiling,
                        dyn_network_custom_period_spend_limit,
                        dyn_network_custom_period_start_date,
                        dyn_network_custom_period_end_date,
                        dyn_network_custom_period_auto_continue,
                        dyn_network_average_cpc,
                        dyn_network_average_cpa,
                        dyn_network_cpa,
                        dyn_network_goal_id,
                        dyn_network_crr,
                        dyn_network_clicks_per_week,
                        dyn_network_limit_percent,
                        dyn_network_reserve_return,
                        dyn_network_roi_coef,
                        dyn_network_profitability,
                        dyn_network_exploration_budget,
                        dyn_network_exploration_budget_custom,
                        dyn_network_budget_type,
                        include_default=False,
                        is_update=True,
                    )
                else:
                    dyn_network_block = (
                        {"BiddingStrategyType": network_strategy.upper()}
                        if network_strategy is not None
                        else None
                    )
                # DynamicTextCampaign.BiddingStrategy.Search update
                # (#362). The branch="search" builder owns the entire
                # Search payload (PlacementTypes + subtype block).
                # include_default=False: with neither --search-strategy
                # nor any --dyn-search-* detail flag, Search is left
                # untouched (returns None).
                dyn_search_builder = get_bidding_strategy_builder(
                    "DYNAMIC_TEXT_CAMPAIGN", "update", "search"
                )
                if dyn_search_builder is not None:
                    dyn_search_block = dyn_search_builder(
                        search_strategy,
                        search_placement_search_results,
                        search_placement_product_gallery,
                        search_placement_dynamic_places,
                        dyn_search_weekly_spend_limit,
                        dyn_search_bid_ceiling,
                        dyn_search_custom_period_spend_limit,
                        dyn_search_custom_period_start_date,
                        dyn_search_custom_period_end_date,
                        dyn_search_custom_period_auto_continue,
                        dyn_search_average_cpc,
                        dyn_search_average_cpa,
                        dyn_search_cpa,
                        dyn_search_goal_id,
                        dyn_search_crr,
                        dyn_search_clicks_per_week,
                        dyn_search_reserve_return,
                        dyn_search_roi_coef,
                        dyn_search_profitability,
                        dyn_search_exploration_budget,
                        dyn_search_exploration_budget_custom,
                        dyn_search_budget_type,
                        include_default=False,
                        is_update=True,
                    )
                else:
                    dyn_search_block = (
                        {"BiddingStrategyType": search_strategy.upper()}
                        if search_strategy is not None
                        else None
                    )
                if dyn_network_block is not None or dyn_search_block is not None:
                    bs: Dict[str, object] = {}
                    if dyn_search_block is not None:
                        bs["Search"] = dyn_search_block
                    if dyn_network_block is not None:
                        bs["Network"] = dyn_network_block
                    sub_block["BiddingStrategy"] = bs
            elif not is_unified and not is_dynamic:
                # Issue #361/#364: full typed-flag support for the 12
                # strategy families on TextCampaign.BiddingStrategy on
                # update. The branch="search" / branch="network"
                # builders own each half of the Bidding Strategy. The
                # shared legacy CPA flags and ``--priority-goals`` are
                # routed per-side, per-flag against the actual WSDL
                # field-support sets (mirrors the add path).
                _search_subtype_for_routing = (
                    _TEXT_CAMPAIGN_SEARCH_STRATEGY_TO_WSDL_SUBTYPE.get(
                        (search_strategy or "").upper()
                    )
                )
                _network_subtype_for_routing = (
                    TEXT_CAMPAIGN_NETWORK_STRATEGY_TO_WSDL_SUBTYPE.get(
                        (network_strategy or "").upper()
                    )
                )

                def _route_update(
                    value,
                    search_support: set,
                    network_support: set,
                    default: str,
                ):
                    if value is None:
                        return (None, None)
                    s_ok = _search_subtype_for_routing in search_support
                    n_ok = _network_subtype_for_routing in network_support
                    if s_ok and n_ok:
                        return (value, value)
                    if s_ok:
                        return (value, None)
                    if n_ok:
                        return (None, value)
                    if default == "network":
                        return (None, value)
                    return (value, None)

                _search_goal_id, _network_goal_id = _route_update(
                    goal_id,
                    _TEXT_SEARCH_SUPPORTS_GOAL_ID,
                    _TEXT_NETWORK_GOAL_ID_SUBTYPES,
                    default="search",
                )
                _search_average_cpa, _network_average_cpa = _route_update(
                    average_cpa,
                    _TEXT_SEARCH_SUPPORTS_AVERAGE_CPA,
                    _TEXT_NETWORK_AVERAGE_CPA_SUBTYPES,
                    default="search",
                )
                _search_crr, _network_crr = _route_update(
                    crr,
                    _TEXT_SEARCH_SUPPORTS_CRR,
                    _TEXT_NETWORK_CRR_SUBTYPES,
                    default="search",
                )
                _search_bid_ceiling, _network_bid_ceiling = _route_update(
                    bid_ceiling,
                    _TEXT_SEARCH_SUPPORTS_BID_CEILING,
                    _TEXT_NETWORK_BID_CEILING_SUBTYPES,
                    default="search",
                )

                # PriorityGoals routing on update mirrors add: both
                # sides may simultaneously belong to the multi-goals
                # family and must each see the items for their own
                # required-field check (the parent placement on update
                # is handled by the dedicated PriorityGoalsUpdateSetting
                # shape earlier in this branch, so the builders only
                # validate scope without writing to sub_block here).
                _multi_goal_subtypes = _TEXT_NETWORK_REQUIRES_PRIORITY_GOALS
                _search_uses_priority_goals = (
                    _search_subtype_for_routing in _multi_goal_subtypes
                )
                _network_uses_priority_goals = (
                    _network_subtype_for_routing in _multi_goal_subtypes
                )
                if _search_uses_priority_goals or _network_uses_priority_goals:
                    _search_priority_goals_items = (
                        priority_goals_items if _search_uses_priority_goals else None
                    )
                    _network_priority_goals_items = (
                        priority_goals_items if _network_uses_priority_goals else None
                    )
                else:
                    _search_priority_goals_items = priority_goals_items
                    _network_priority_goals_items = None

                search_builder = get_bidding_strategy_builder(
                    "TEXT_CAMPAIGN", "update", "search"
                )
                if search_builder is not None:
                    text_search = search_builder(
                        search_strategy=search_strategy,
                        search_placement_search_results=(
                            search_placement_search_results
                        ),
                        search_placement_product_gallery=(
                            search_placement_product_gallery
                        ),
                        search_placement_dynamic_places=(
                            search_placement_dynamic_places
                        ),
                        goal_id=_search_goal_id,
                        average_cpa=_search_average_cpa,
                        crr=_search_crr,
                        bid_ceiling=_search_bid_ceiling,
                        weekly_spend_limit=text_search_weekly_spend_limit,
                        custom_period_spend_limit=(
                            text_search_custom_period_spend_limit
                        ),
                        custom_period_start_date=(text_search_custom_period_start_date),
                        custom_period_end_date=(text_search_custom_period_end_date),
                        custom_period_auto_continue=(
                            text_search_custom_period_auto_continue
                        ),
                        budget_type=text_search_budget_type,
                        average_cpc=text_search_average_cpc,
                        pay_cpa=text_search_pay_cpa,
                        clicks_per_week=text_search_clicks_per_week,
                        reserve_return=text_search_reserve_return,
                        roi_coef=text_search_roi_coef,
                        profitability=text_search_profitability,
                        exploration_min_budget=(text_search_exploration_min_budget),
                        exploration_is_custom=(text_search_exploration_is_custom),
                        priority_goals_items=_search_priority_goals_items,
                        sub_campaign_block=sub_block,
                        include_default=False,
                        is_update=True,
                    )
                else:
                    text_search = (
                        {"BiddingStrategyType": (search_strategy.upper())}
                        if search_strategy is not None
                        else None
                    )

                network_builder = get_bidding_strategy_builder(
                    "TEXT_CAMPAIGN", "update", "network"
                )
                if network_builder is not None:
                    text_network = network_builder(
                        network_strategy=network_strategy,
                        goal_id=_network_goal_id,
                        average_cpa=_network_average_cpa,
                        crr=_network_crr,
                        bid_ceiling=_network_bid_ceiling,
                        weekly_spend_limit=text_network_weekly_spend_limit,
                        custom_period_spend_limit=(
                            text_network_custom_period_spend_limit
                        ),
                        custom_period_start_date=(
                            text_network_custom_period_start_date
                        ),
                        custom_period_end_date=(text_network_custom_period_end_date),
                        custom_period_auto_continue=(
                            text_network_custom_period_auto_continue
                        ),
                        budget_type=text_network_budget_type,
                        average_cpc=text_network_average_cpc,
                        pay_cpa=text_network_pay_cpa,
                        clicks_per_week=text_network_clicks_per_week,
                        reserve_return=text_network_reserve_return,
                        roi_coef=text_network_roi_coef,
                        profitability=text_network_profitability,
                        exploration_min_budget=(text_network_exploration_min_budget),
                        exploration_is_custom=(text_network_exploration_is_custom),
                        limit_percent=text_network_limit_percent,
                        priority_goals_items=_network_priority_goals_items,
                        sub_campaign_block=sub_block,
                        include_default=False,
                        is_update=True,
                    )
                else:
                    text_network = (
                        {"BiddingStrategyType": (network_strategy.upper())}
                        if network_strategy is not None
                        else None
                    )

                bidding_strategy_block: Dict[str, object] = {}
                if text_search is not None:
                    bidding_strategy_block["Search"] = text_search
                if text_network is not None:
                    bidding_strategy_block["Network"] = text_network
                if bidding_strategy_block:
                    sub_block["BiddingStrategy"] = bidding_strategy_block
            negative_keyword_shared_set_ids_obj = _array_of_integer_option(
                "--negative-keyword-shared-set-ids",
                negative_keyword_shared_set_ids,
                max_items=NEGATIVE_KEYWORD_SHARED_SET_IDS_MAX_ITEMS,
            )
            if negative_keyword_shared_set_ids_obj is not None:
                sub_block["NegativeKeywordSharedSetIds"] = (
                    negative_keyword_shared_set_ids_obj
                )
        elif campaign_type_norm == "SMART_CAMPAIGN":
            parsed_settings = parse_setting_specs(list(settings))
            if parsed_settings:
                sub_block["Settings"] = parsed_settings
            if counter_id is not None:
                sub_block["CounterId"] = counter_id
            priority_goals_items = _priority_goals_update_items(
                parse_priority_goals_spec(priority_goals)
            )
            if priority_goals_items is not None:
                sub_block["PriorityGoals"] = {"Items": priority_goals_items}
            if attribution_model:
                sub_block["AttributionModel"] = attribution_model.upper()
            smart_package_bidding_strategy_obj = _build_smart_package_bidding_strategy(
                package_strategy_id,
                package_strategy_from_campaign_id,
                package_platform_search,
                package_platform_network,
                require_platforms=False,
            )
            # SmartCampaign.BiddingStrategy.Search via shared builder (#367).
            # Returns ONLY the Search block. Network is built by the
            # separately registered #368 builder. On update, omit
            # BiddingStrategy entirely when no Search/Network flag is
            # present.
            smart_search_builder = get_bidding_strategy_builder(
                "SMART_CAMPAIGN", "update", "search"
            )
            smart_search_block = None
            if smart_search_builder is not None:
                smart_search_block = smart_search_builder(
                    search_strategy,
                    smart_search_average_cpc,
                    smart_search_filter_average_cpc,
                    smart_search_average_cpa,
                    smart_search_filter_average_cpa,
                    smart_search_cpa,
                    smart_search_goal_id,
                    smart_search_weekly_spend_limit,
                    smart_search_bid_ceiling,
                    smart_search_reserve_return,
                    smart_search_roi_coef,
                    smart_search_profitability,
                    smart_search_crr,
                    smart_search_cp_spend_limit,
                    smart_search_cp_start_date,
                    smart_search_cp_end_date,
                    smart_search_cp_auto_continue,
                    smart_search_exploration_min,
                    smart_search_exploration_min_custom,
                    smart_search_budget_type,
                    include_default=False,
                    is_update=True,
                )
            smart_network_builder = get_bidding_strategy_builder(
                "SMART_CAMPAIGN", "update", "network"
            )
            smart_network_block = None
            if smart_network_builder is not None:
                smart_network_block = smart_network_builder(
                    network_strategy,
                    smart_network_average_cpc,
                    smart_network_filter_average_cpc,
                    smart_network_average_cpa,
                    smart_network_filter_average_cpa,
                    smart_network_cpa,
                    smart_network_goal_id,
                    smart_network_weekly_spend_limit,
                    smart_network_bid_ceiling,
                    smart_network_reserve_return,
                    smart_network_roi_coef,
                    smart_network_profitability,
                    smart_network_crr,
                    smart_network_limit_percent,
                    smart_network_cp_spend_limit,
                    smart_network_cp_start_date,
                    smart_network_cp_end_date,
                    smart_network_cp_auto_continue,
                    smart_network_exploration_min,
                    smart_network_exploration_min_custom,
                    smart_network_budget_type,
                    include_default=False,
                    is_update=True,
                )
            if smart_package_bidding_strategy_obj is not None:
                package_incompatible = {
                    "--counter-id": counter_id,
                    "--priority-goals": priority_goals,
                    "--attribution-model": attribution_model,
                    "--search-strategy": search_strategy,
                    "--network-strategy": network_strategy,
                }
                provided = [
                    flag
                    for flag, value in package_incompatible.items()
                    if value is not None
                ]
                # PackageBiddingStrategy is mutually exclusive with any
                # typed Search/Network flag (WSDL: SmartCampaignUpdateItem
                # allows only one of BiddingStrategy / PackageBiddingStrategy).
                if smart_search_block is not None:
                    provided.append("SmartCampaign.BiddingStrategy.Search")
                if smart_network_block is not None:
                    provided.append("SmartCampaign.BiddingStrategy.Network")
                if provided:
                    raise click.UsageError(
                        t(
                            "SmartCampaign.PackageBiddingStrategy cannot be combined with {arg0}"
                        ).format(arg0=", ".join(sorted(provided)))
                    )
                sub_block["PackageBiddingStrategy"] = smart_package_bidding_strategy_obj
            elif smart_search_block is not None or smart_network_block is not None:
                bidding_strategy: Dict[str, object] = {}
                if smart_search_block is not None:
                    bidding_strategy["Search"] = smart_search_block
                if smart_network_block is not None:
                    bidding_strategy["Network"] = smart_network_block
                sub_block["BiddingStrategy"] = bidding_strategy
        elif campaign_type_norm == "MOBILE_APP_CAMPAIGN":
            parsed_settings = parse_setting_specs(list(settings))
            if parsed_settings:
                sub_block["Settings"] = parsed_settings
            mobile_builder = get_bidding_strategy_builder(
                "MOBILE_APP_CAMPAIGN", "update", "full"
            )
            if mobile_builder is not None:
                mobile_bidding_strategy = mobile_builder(
                    search_strategy,
                    mobile_search_weekly_spend_limit,
                    mobile_search_bid_ceiling,
                    mobile_search_custom_period_spend_limit,
                    mobile_search_custom_period_start_date,
                    mobile_search_custom_period_end_date,
                    mobile_search_custom_period_auto_continue,
                    mobile_search_average_cpc,
                    mobile_search_average_cpi,
                    mobile_search_clicks_per_week,
                    mobile_search_budget_type,
                    network_strategy,
                    mobile_network_weekly_spend_limit,
                    mobile_network_bid_ceiling,
                    mobile_network_custom_period_spend_limit,
                    mobile_network_custom_period_start_date,
                    mobile_network_custom_period_end_date,
                    mobile_network_custom_period_auto_continue,
                    mobile_network_average_cpc,
                    mobile_network_average_cpi,
                    mobile_network_clicks_per_week,
                    mobile_network_limit_percent,
                    mobile_network_budget_type,
                    include_defaults=False,
                    is_update=True,
                )
            else:
                mobile_bidding_strategy = (
                    {"Search": {"BiddingStrategyType": search_strategy.upper()}}
                    if search_strategy is not None
                    else None
                )
            if mobile_bidding_strategy is not None:
                sub_block["BiddingStrategy"] = mobile_bidding_strategy
            negative_keyword_shared_set_ids_obj = _array_of_integer_option(
                "--negative-keyword-shared-set-ids",
                negative_keyword_shared_set_ids,
                max_items=NEGATIVE_KEYWORD_SHARED_SET_IDS_MAX_ITEMS,
            )
            if negative_keyword_shared_set_ids_obj is not None:
                sub_block["NegativeKeywordSharedSetIds"] = (
                    negative_keyword_shared_set_ids_obj
                )
        elif campaign_type_norm == "CPM_BANNER_CAMPAIGN":
            parsed_settings = parse_setting_specs(list(settings))
            if parsed_settings:
                sub_block["Settings"] = parsed_settings
            cpm_builder = get_bidding_strategy_builder(
                "CPM_BANNER_CAMPAIGN", "update", "full"
            )
            if cpm_builder is not None:
                cpm_bidding_strategy = cpm_builder(
                    search_strategy,
                    network_strategy,
                    average_cpm,
                    average_cpv,
                    strategy_spend_limit,
                    strategy_start_date,
                    strategy_end_date,
                    strategy_auto_continue,
                    include_defaults=False,
                )
            else:
                cpm_bidding_strategy = None
                if search_strategy is not None or network_strategy is not None:
                    cpm_bidding_strategy = {}
                    if search_strategy is not None:
                        cpm_bidding_strategy["Search"] = {
                            "BiddingStrategyType": search_strategy.upper()
                        }
                    if network_strategy is not None:
                        cpm_bidding_strategy["Network"] = {
                            "BiddingStrategyType": network_strategy.upper()
                        }
            if cpm_bidding_strategy is not None:
                sub_block["BiddingStrategy"] = cpm_bidding_strategy
            counter_ids_obj = _array_of_integer_option("--counter-ids", counter_ids)
            if counter_ids_obj is not None:
                sub_block["CounterIds"] = counter_ids_obj
            frequency_cap_obj = _build_frequency_cap(
                frequency_cap_impressions,
                frequency_cap_period_days,
                frequency_cap_period_all,
            )
            if frequency_cap_obj is not None:
                sub_block["FrequencyCap"] = frequency_cap_obj
            if video_target:
                sub_block["VideoTarget"] = video_target.upper()
        if tracking_params:
            sub_block["TrackingParams"] = tracking_params
        if not sub_block:
            raise click.UsageError(
                t(
                    "--type {campaign_type_norm} requires at least one subtype-specific field to update."
                ).format(campaign_type_norm=campaign_type_norm)
            )
        subtype_container = {
            "TEXT_CAMPAIGN": "TextCampaign",
            "UNIFIED_CAMPAIGN": "UnifiedCampaign",
            "DYNAMIC_TEXT_CAMPAIGN": "DynamicTextCampaign",
            "SMART_CAMPAIGN": "SmartCampaign",
            "MOBILE_APP_CAMPAIGN": "MobileAppCampaign",
            "CPM_BANNER_CAMPAIGN": "CpmBannerCampaign",
        }[campaign_type_norm]
        campaign_data[subtype_container] = sub_block

    if len(campaign_data) == 1:
        raise click.UsageError(t("Provide at least one field to update"))

    body = {"method": "update", "params": {"Campaigns": [campaign_data]}}

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = client.campaigns().post(data=body)
    format_output(result().extract(), "json", None)


def _make_lifecycle_command(method: str, help_text: str):
    """Build a campaign lifecycle command (delete/archive/.../resume).

    These commands are identical except for the ``method`` sent in the request
    body and the help text shown in ``--help``. ``name=method`` pins the Click
    command name (otherwise every command would register as ``_command``);
    ``help=help_text`` pins the short help so ``--help`` is unchanged (setting
    ``__doc__`` after decoration is too late — Click reads it at decoration
    time).
    """

    @campaigns.command(name=method, help=help_text)
    @click.option("--id", "campaign_id", required=True, type=int, help="Campaign ID")
    @click.option("--dry-run", is_flag=True, help="Show request without sending")
    @click.pass_context
    @handle_api_errors
    def _command(ctx, campaign_id, dry_run):
        body = {
            "method": method,
            "params": {"SelectionCriteria": {"Ids": [campaign_id]}},
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = client_from_ctx(ctx, create_client)

        result = client.campaigns().post(data=body)
        format_output(result().extract(), "json", None)

    return _command


delete = _make_lifecycle_command("delete", "Delete campaign")
archive = _make_lifecycle_command("archive", "Archive campaign")
unarchive = _make_lifecycle_command("unarchive", "Unarchive campaign")
suspend = _make_lifecycle_command("suspend", "Suspend campaign")
resume = _make_lifecycle_command("resume", "Resume campaign")
