"""
Campaigns commands
"""

import re
from typing import Dict, List, Optional, Sequence

import click

from ..api import create_client
from ..output import format_output, print_error
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

# WSDL: BiddingStrategyType enum value → Strategy*Add subtype field name
# in TextCampaignSearch/Network/SmartCampaign… containers.
# Only CPA-shaped subtypes that accept --average-cpa / --goal-id /
# --bid-ceiling / --priority-goals are listed; legacy types
# (HIGHEST_POSITION etc.) do not carry these fields and must not get
# a nested subtype block at all.
_SEARCH_STRATEGY_TO_WSDL_SUBTYPE = {
    "AVERAGE_CPA": "AverageCpa",
    "PAY_FOR_CONVERSION_CRR": "PayForConversionCrr",
    "AVERAGE_CPA_MULTIPLE_GOALS": "AverageCpaMultipleGoals",
    "PAY_FOR_CONVERSION_MULTIPLE_GOALS": "PayForConversionMultipleGoals",
}
# Per-Campaign / Per-Filter subtypes live only on SmartCampaignStrategyAddBase
# (WSDL), not on TextCampaign/DynamicTextCampaign network strategy. SMART_CAMPAIGN
# follows a separate code path that doesn't call _apply_cpa_strategy_fields, so
# the network mapping for these typed flags is intentionally empty. Adding them
# here would silently emit fields the WSDL rejects.
_NETWORK_STRATEGY_TO_WSDL_SUBTYPE: Dict[str, str] = {}

_STRATEGY_SUPPORTS_AVERAGE_CPA = {
    "AverageCpa",
}
_STRATEGY_SUPPORTS_GOAL_ID = {
    "AverageCpa",
    "PayForConversionCrr",
}
_STRATEGY_SUPPORTS_BID_CEILING = {
    "AverageCpa",
    "AverageCpaMultipleGoals",
}
_STRATEGY_SUPPORTS_CRR = {
    "PayForConversionCrr",
}
_STRATEGY_REQUIRES_PRIORITY_GOALS = {
    "AverageCpaMultipleGoals",
    "PayForConversionMultipleGoals",
}
# WSDL minOccurs=1 fields per Strategy*Add subtype — used to fail-fast at the
# CLI when the user picks the strategy but forgets a required typed flag.
# Maps subtype name → {WSDL field name → (CLI option string, value resolver)}.
# The resolver takes the runtime closure of CLI args; values use direct
# variable names from the add(...) function.
_STRATEGY_REQUIRED_TYPED_FLAGS: Dict[str, Dict[str, str]] = {
    "AverageCpa": {"AverageCpa": "--average-cpa", "GoalId": "--goal-id"},
    "PayForConversionCrr": {"Crr": "--crr", "GoalId": "--goal-id"},
    "AverageCpaMultipleGoals": {"PriorityGoals": "--priority-goals"},
    "PayForConversionMultipleGoals": {"PriorityGoals": "--priority-goals"},
}

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


def _apply_cpa_strategy_fields(
    bidding_strategy: dict,
    *,
    search_strategy: Optional[str],
    network_strategy: Optional[str],
    goal_id: Optional[int],
    average_cpa: Optional[int],
    crr: Optional[int],
    bid_ceiling: Optional[int],
    priority_goals_items: Optional[List[dict]],
    sub_campaign_block: dict,
) -> None:
    """Place AverageCpa/GoalId/Crr/BidCeiling/PriorityGoals into the
    correct WSDL Strategy*Add subtype block, enforcing 1:1 parity.

    `bidding_strategy` is the {"Search":{...}, "Network":{...}} dict;
    `sub_campaign_block` is the parent TextCampaign/DynamicTextCampaign
    dict (PriorityGoals belongs to it, not to the strategy).
    """
    search_subtype = _SEARCH_STRATEGY_TO_WSDL_SUBTYPE.get(search_strategy or "")
    network_subtype = _NETWORK_STRATEGY_TO_WSDL_SUBTYPE.get(network_strategy or "")

    has_cpa_flags = (
        goal_id is not None
        or average_cpa is not None
        or crr is not None
        or bid_ceiling is not None
    )

    if has_cpa_flags and search_subtype is None and network_subtype is None:
        raise click.UsageError(
            "--average-cpa / --goal-id / --crr / --bid-ceiling are only "
            "valid with a CPA-shaped --search-strategy or --network-strategy "
            "(e.g. AVERAGE_CPA, PAY_FOR_CONVERSION_CRR, "
            "AVERAGE_CPA_MULTIPLE_GOALS); "
            f"got --search-strategy={search_strategy!r}, "
            f"--network-strategy={network_strategy!r}"
        )

    # Single-goal CPA strategies must reject --priority-goals;
    # only *_MULTIPLE_GOALS subtypes carry PriorityGoals.
    if priority_goals_items is not None:
        chosen_subtype = search_subtype or network_subtype
        if chosen_subtype not in _STRATEGY_REQUIRES_PRIORITY_GOALS:
            raise click.UsageError(
                "--priority-goals is only valid with "
                "AVERAGE_CPA_MULTIPLE_GOALS / "
                "PAY_FOR_CONVERSION_MULTIPLE_GOALS strategies; "
                f"got --search-strategy={search_strategy!r}, "
                f"--network-strategy={network_strategy!r}"
            )
        sub_campaign_block["PriorityGoals"] = {"Items": priority_goals_items}

    # WSDL minOccurs=1 fields per subtype: fail-fast at CLI level. The
    # "invalid combinations never reach the API" guarantee depends on
    # this check; without it, a half-configured strategy block would be
    # silently sent to Yandex and rejected at the wire with a confusing
    # error message instead of a CLI hint.
    def _ensure_required(side: str, subtype: Optional[str]) -> None:
        if subtype is None:
            return
        required = _STRATEGY_REQUIRED_TYPED_FLAGS.get(subtype, {})
        provided_lookup = {
            "AverageCpa": average_cpa,
            "GoalId": goal_id,
            "Crr": crr,
            "PriorityGoals": priority_goals_items,
        }
        missing = [
            flag
            for wsdl_field, flag in required.items()
            if provided_lookup.get(wsdl_field) is None
        ]
        if missing:
            raise click.UsageError(
                f"{side} strategy {subtype} requires "
                f"{', '.join(sorted(missing))} "
                f"(WSDL Strategy{subtype}Add minOccurs=1)"
            )

    _ensure_required("Search", search_subtype)
    _ensure_required("Network", network_subtype)

    def _place(side: str, subtype: Optional[str]) -> None:
        if subtype is None:
            return
        block: Dict[str, int] = {}
        if average_cpa is not None:
            if subtype not in _STRATEGY_SUPPORTS_AVERAGE_CPA:
                raise click.UsageError(
                    f"--average-cpa is not valid for {side} strategy "
                    f"{subtype}; WSDL field is declared only on "
                    f"{sorted(_STRATEGY_SUPPORTS_AVERAGE_CPA)}"
                )
            block["AverageCpa"] = average_cpa
        if crr is not None:
            if subtype not in _STRATEGY_SUPPORTS_CRR:
                raise click.UsageError(
                    f"--crr is not valid for {side} strategy "
                    f"{subtype}; WSDL field is declared only on "
                    f"{sorted(_STRATEGY_SUPPORTS_CRR)}"
                )
            block["Crr"] = crr
        if goal_id is not None:
            if subtype not in _STRATEGY_SUPPORTS_GOAL_ID:
                raise click.UsageError(
                    f"--goal-id is not valid for {side} strategy "
                    f"{subtype}; WSDL field is declared only on "
                    f"{sorted(_STRATEGY_SUPPORTS_GOAL_ID)}"
                )
            block["GoalId"] = goal_id
        if bid_ceiling is not None:
            if subtype not in _STRATEGY_SUPPORTS_BID_CEILING:
                raise click.UsageError(
                    f"--bid-ceiling is not valid for {side} strategy "
                    f"{subtype}; WSDL field is declared only on "
                    f"{sorted(_STRATEGY_SUPPORTS_BID_CEILING)}"
                )
            block["BidCeiling"] = bid_ceiling
        if block:
            bidding_strategy[side][subtype] = block

    def _place_multiple_goals(side: str, subtype: Optional[str]) -> None:
        if subtype is None:
            return
        bidding_strategy[side].setdefault(subtype, {})
        if bid_ceiling is not None:
            if subtype not in _STRATEGY_SUPPORTS_BID_CEILING:
                raise click.UsageError(
                    f"--bid-ceiling is not valid for {side} strategy "
                    f"{subtype}; WSDL field is declared only on "
                    f"{sorted(_STRATEGY_SUPPORTS_BID_CEILING)}"
                )
            bidding_strategy[side][subtype]["BidCeiling"] = bid_ceiling

    # If the user picked a *_MULTIPLE_GOALS subtype, place the subtype
    # container even without numeric fields, because PriorityGoals is
    # the only required CPA-side input. BidCeiling is still gated by
    # _STRATEGY_SUPPORTS_BID_CEILING — e.g. PayForConversionMultipleGoals
    # has no BidCeiling in WSDL.
    if search_subtype in _STRATEGY_REQUIRES_PRIORITY_GOALS:
        _place_multiple_goals("Search", search_subtype)
    else:
        _place("Search", search_subtype)
    if network_subtype in _STRATEGY_REQUIRES_PRIORITY_GOALS:
        _place_multiple_goals("Network", network_subtype)
    else:
        _place("Network", network_subtype)


@click.group()
def campaigns():
    """Manage campaigns"""


def _parse_csv_option(option_name: str, value: Optional[str]) -> Optional[List[str]]:
    """Parse a CSV option and reject explicitly empty input."""
    parsed = parse_csv_strings(value)
    if value is not None and not parsed:
        raise click.UsageError(f"{option_name} must contain at least one value")
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
        raise click.UsageError(f"{option_name} must contain at most {max_items} items")
    if parsed and max_item_length is not None:
        too_long = [item for item in parsed if len(item) > max_item_length]
        if too_long:
            raise click.UsageError(
                f"{option_name} items must be at most " f"{max_item_length} characters"
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
        raise click.UsageError(f"{option_name} must contain at least one integer")
    if max_items is not None and len(parsed) > max_items:
        raise click.UsageError(f"{option_name} must contain at most {max_items} items")
    return {"Items": parsed}


def _time_targeting_schedule_option(values: Sequence[str]) -> Optional[dict]:
    """Build TimeTargeting.Schedule without splitting comma-bearing rows."""
    if not values:
        return None
    items = [value.strip() for value in values if value.strip()]
    if len(items) != len(values):
        raise click.UsageError(
            "--time-targeting-schedule must contain at least one value"
        )
    if len(items) > TIME_TARGETING_SCHEDULE_MAX_ITEMS:
        raise click.UsageError(
            "--time-targeting-schedule must contain at most "
            f"{TIME_TARGETING_SCHEDULE_MAX_ITEMS} items"
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
        raise click.UsageError(f"{option_name} must be at most {max_length} characters")
    return value


def _validate_sms_time(option_name: str, value: Optional[str]) -> Optional[str]:
    """Validate documented HH:MM values with 15-minute steps."""
    if value is None:
        return None
    if not HH_MM_RE.fullmatch(value):
        raise click.UsageError(
            f"{option_name} must use HH:MM with minutes 00, 15, 30, or 45"
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
                "--sms-events contains invalid value(s) "
                f"{invalid}; allowed: {sorted(SMS_EVENTS)}"
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
            "TimeTargeting requires --consider-working-weekends when any "
            "time-targeting flag is provided."
        )

    time_targeting: dict = {
        "ConsiderWorkingWeekends": consider_working_weekends.upper()
    }
    if schedule is not None:
        time_targeting["Schedule"] = schedule

    if has_holidays:
        if holidays_suspend_on_holidays is None:
            raise click.UsageError(
                "TimeTargeting.HolidaysSchedule requires "
                "--holidays-suspend-on-holidays when any --holidays-* flag "
                "is provided."
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
                "--holidays-bid-percent, --holidays-start-hour, and "
                "--holidays-end-hour can be provided only when "
                "--holidays-suspend-on-holidays is NO."
            )
        if holidays_bid_percent is not None and holidays_bid_percent % 10 != 0:
            raise click.UsageError("--holidays-bid-percent must be a multiple of 10")
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
            "--relevant-keywords-budget-percent is required when adding "
            "TextCampaign.RelevantKeywords"
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
            "--frequency-cap-period-days and --frequency-cap-period-all "
            "are mutually exclusive"
        )
    if impressions is None:
        raise click.UsageError(
            "--frequency-cap-impressions is required with "
            "--frequency-cap-period-days or --frequency-cap-period-all"
        )
    if period_days is None and not period_all:
        raise click.UsageError(
            "--frequency-cap-impressions requires --frequency-cap-period-days "
            "or --frequency-cap-period-all"
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
            f"{campaign_label}.PackageBiddingStrategy requires "
            "--package-platform-search-result, "
            "--package-platform-product-gallery, and --package-platform-network"
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
            "SmartCampaign.PackageBiddingStrategy requires "
            "--package-platform-search and --package-platform-network"
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


def _reject_incompatible_flags(
    command_type: str,
    allowed_flags: set[str],
    provided_flags: dict[str, object],
) -> None:
    """Reject typed flags that do not belong to the chosen subtype."""
    incompatible = [
        flag
        for flag, value in provided_flags.items()
        if value is not None and flag not in allowed_flags
    ]
    if incompatible:
        raise click.UsageError(
            f"{', '.join(sorted(incompatible))} is not compatible with --type "
            f"{command_type}."
        )


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
@click.option("--text-campaign-fields", help="Comma-separated TextCampaignFieldNames")
@click.option(
    "--text-campaign-search-strategy-placement-types-fields",
    help="Comma-separated TextCampaignSearchStrategyPlacementTypesFieldNames",
)
@click.option(
    "--mobile-app-campaign-fields",
    help="Comma-separated MobileAppCampaignFieldNames",
)
@click.option(
    "--dynamic-text-campaign-fields",
    help="Comma-separated DynamicTextCampaignFieldNames",
)
@click.option(
    "--dynamic-text-campaign-search-strategy-placement-types-fields",
    help="Comma-separated DynamicTextCampaignSearchStrategyPlacementTypesFieldNames",
)
@click.option(
    "--cpm-banner-campaign-fields",
    help="Comma-separated CpmBannerCampaignFieldNames",
)
@click.option("--smart-campaign-fields", help="Comma-separated SmartCampaignFieldNames")
@click.option(
    "--unified-campaign-fields",
    help="Comma-separated UnifiedCampaignFieldNames",
)
@click.option(
    "--unified-campaign-search-strategy-placement-types-fields",
    help="Comma-separated UnifiedCampaignSearchStrategyPlacementTypesFieldNames",
)
@click.option(
    "--unified-campaign-package-bidding-strategy-platforms-fields",
    help="Comma-separated UnifiedCampaignPackageBiddingStrategyPlatformsFieldNames",
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
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
    text_campaign_fields,
    text_campaign_search_strategy_placement_types_fields,
    mobile_app_campaign_fields,
    dynamic_text_campaign_fields,
    dynamic_text_campaign_search_strategy_placement_types_fields,
    cpm_banner_campaign_fields,
    smart_campaign_fields,
    unified_campaign_fields,
    unified_campaign_search_strategy_placement_types_fields,
    unified_campaign_package_bidding_strategy_platforms_fields,
    dry_run,
):
    """Get campaigns"""
    if status and statuses:
        raise click.UsageError("--status and --statuses are mutually exclusive")

    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        # Parse field names
        field_names = (
            _parse_csv_option("--fields", fields)
            if fields is not None
            else get_default_fields("campaigns")
        )

        # Build selection criteria
        criteria = build_selection_criteria(
            ids=parse_ids(ids), status=status, types=types
        )
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
                "--text-campaign-fields",
                text_campaign_fields,
            ),
            "TextCampaignSearchStrategyPlacementTypesFieldNames": (
                "--text-campaign-search-strategy-placement-types-fields",
                text_campaign_search_strategy_placement_types_fields,
            ),
            "MobileAppCampaignFieldNames": (
                "--mobile-app-campaign-fields",
                mobile_app_campaign_fields,
            ),
            "DynamicTextCampaignFieldNames": (
                "--dynamic-text-campaign-fields",
                dynamic_text_campaign_fields,
            ),
            "DynamicTextCampaignSearchStrategyPlacementTypesFieldNames": (
                "--dynamic-text-campaign-search-strategy-placement-types-fields",
                dynamic_text_campaign_search_strategy_placement_types_fields,
            ),
            "CpmBannerCampaignFieldNames": (
                "--cpm-banner-campaign-fields",
                cpm_banner_campaign_fields,
            ),
            "SmartCampaignFieldNames": (
                "--smart-campaign-fields",
                smart_campaign_fields,
            ),
            "UnifiedCampaignFieldNames": (
                "--unified-campaign-fields",
                unified_campaign_fields,
            ),
            "UnifiedCampaignSearchStrategyPlacementTypesFieldNames": (
                "--unified-campaign-search-strategy-placement-types-fields",
                unified_campaign_search_strategy_placement_types_fields,
            ),
            "UnifiedCampaignPackageBiddingStrategyPlatformsFieldNames": (
                "--unified-campaign-package-bidding-strategy-platforms-fields",
                unified_campaign_package_bidding_strategy_platforms_fields,
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

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


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
        "PAY_FOR_CONVERSION_MULTIPLE_GOALS)"
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
        "TextCampaign/UnifiedCampaign.PackageBiddingStrategy." "Platforms.DynamicPlaces"
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
    average_cpa,
    crr,
    bid_ceiling,
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
    try:
        campaign_type_norm = (
            (campaign_type or "TEXT_CAMPAIGN").upper().replace("-", "_")
        )
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
                "Invalid value for '--type': "
                f"{campaign_type!r} is not one of "
                "'TEXT_CAMPAIGN', 'UNIFIED_CAMPAIGN', "
                "'DYNAMIC_TEXT_CAMPAIGN', 'SMART_CAMPAIGN', "
                "'MOBILE_APP_CAMPAIGN', 'CPM_BANNER_CAMPAIGN'."
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
        allowed_flags_by_type = {
            "TEXT_CAMPAIGN": {
                "--setting",
                "--search-strategy",
                "--network-strategy",
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
            | text_dynamic_extras,
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
            },
            "DYNAMIC_TEXT_CAMPAIGN": {
                "--setting",
                "--search-strategy",
                "--network-strategy",
                "--tracking-params",
                "--dynamic-placement-search-results",
                "--dynamic-placement-product-gallery",
                "--attribution-model",
                "--package-strategy-id",
                "--package-strategy-from-campaign-id",
                "--negative-keyword-shared-set-ids",
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
            },
            "MOBILE_APP_CAMPAIGN": {
                "--setting",
                "--negative-keyword-shared-set-ids",
            },
            "CPM_BANNER_CAMPAIGN": {
                "--setting",
                "--counter-ids",
                "--frequency-cap-impressions",
                "--frequency-cap-period-days",
                "--frequency-cap-period-all",
                "--video-target",
            },
        }
        _reject_incompatible_flags(
            campaign_type_norm,
            allowed_flags_by_type[campaign_type_norm],
            {
                "--setting": list(settings) or None,
                "--search-strategy": search_strategy,
                "--network-strategy": network_strategy,
                "--filter-average-cpc": filter_average_cpc,
                "--counter-id": counter_id,
                "--counter-ids": counter_ids,
                "--dynamic-placement-search-results": dynamic_placement_search_results,
                "--dynamic-placement-product-gallery": (
                    dynamic_placement_product_gallery
                ),
                "--goal-id": goal_id,
                "--priority-goals": priority_goals,
                "--relevant-keywords-budget-percent": relevant_keywords_budget_percent,
                "--relevant-keywords-mode": relevant_keywords_mode,
                "--relevant-keywords-optimize-goal-id": (
                    relevant_keywords_optimize_goal_id
                ),
                "--attribution-model": attribution_model,
                "--package-strategy-id": package_strategy_id,
                "--package-strategy-from-campaign-id": (
                    package_strategy_from_campaign_id
                ),
                "--package-platform-search": package_platform_search,
                "--package-platform-search-result": package_platform_search_result,
                "--package-platform-product-gallery": (
                    package_platform_product_gallery
                ),
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
                "--average-cpa": average_cpa,
                "--crr": crr,
                "--bid-ceiling": bid_ceiling,
                "--tracking-params": tracking_params,
            },
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
                "--priority-goals": priority_goals,
                "--goal-id": goal_id,
                "--average-cpa": average_cpa,
                "--crr": crr,
                "--bid-ceiling": bid_ceiling,
            }
            if campaign_type_norm == "UNIFIED_CAMPAIGN":
                package_incompatible.update(
                    {
                        "--counter-ids": counter_ids,
                        "--attribution-model": attribution_model,
                    }
                )
            provided = [
                flag
                for flag, value in package_incompatible.items()
                if value is not None
            ]
            if provided:
                raise click.UsageError(
                    f"{package_label}.PackageBiddingStrategy cannot be combined with "
                    f"{', '.join(sorted(provided))}"
                )
        if smart_package_bidding_strategy_obj is not None:
            smart_package_incompatible = {
                "--search-strategy": search_strategy,
                "--network-strategy": network_strategy,
                "--filter-average-cpc": filter_average_cpc,
                "--priority-goals": priority_goals,
                "--attribution-model": attribution_model,
            }
            provided = [
                flag
                for flag, value in smart_package_incompatible.items()
                if value is not None
            ]
            if provided:
                raise click.UsageError(
                    "SmartCampaign.PackageBiddingStrategy cannot be combined with "
                    f"{', '.join(sorted(provided))}"
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
                    "UnifiedCampaign cannot be combined with "
                    f"{', '.join(sorted(provided))}"
                )
            if priority_goals is not None:
                raise click.UsageError(
                    "UnifiedCampaign.PriorityGoals on campaigns add requires "
                    "a compatible UnifiedCampaign.BiddingStrategy; shared "
                    "BiddingStrategy support is tracked in #290."
                )
        if campaign_type_norm == "SMART_CAMPAIGN" and priority_goals is not None:
            raise click.UsageError(
                "SmartCampaign.PriorityGoals on campaigns add requires a compatible "
                "SmartCampaign.BiddingStrategy; shared BiddingStrategy support is "
                "tracked in #290."
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
                flag
                for flag, value in strategy_followup_flags.items()
                if value is not None
            ]
            if provided:
                raise click.UsageError(
                    f"{campaign_type_norm} BiddingStrategy typed parameters are "
                    f"tracked in #290; got {', '.join(sorted(provided))}"
                )

        campaign_data = {"Name": name, "StartDate": start_date}
        parsed_settings = parse_setting_specs(list(settings))
        if campaign_type_norm == "TEXT_CAMPAIGN":
            text_block = {"Settings": parsed_settings or []}
            if package_bidding_strategy_obj is not None:
                text_block["PackageBiddingStrategy"] = package_bidding_strategy_obj
            else:
                text_block["BiddingStrategy"] = {
                    "Search": {
                        "BiddingStrategyType": (search_strategy or "HIGHEST_POSITION")
                    },
                    "Network": {
                        "BiddingStrategyType": (network_strategy or "SERVING_OFF")
                    },
                }
                _apply_cpa_strategy_fields(
                    text_block["BiddingStrategy"],
                    search_strategy=search_strategy,
                    network_strategy=network_strategy,
                    goal_id=goal_id,
                    average_cpa=average_cpa,
                    crr=crr,
                    bid_ceiling=bid_ceiling,
                    priority_goals_items=priority_goals_items,
                    sub_campaign_block=text_block,
                )
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
            unified_block = {"Settings": parsed_settings or []}
            if package_bidding_strategy_obj is not None:
                unified_block["PackageBiddingStrategy"] = package_bidding_strategy_obj
            else:
                unified_block["BiddingStrategy"] = {
                    "Search": {"BiddingStrategyType": "HIGHEST_POSITION"},
                    "Network": {"BiddingStrategyType": "SERVING_OFF"},
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
                dyn_block["BiddingStrategy"] = {
                    "Search": {
                        "BiddingStrategyType": (search_strategy or "HIGHEST_POSITION")
                    },
                    "Network": {
                        "BiddingStrategyType": (network_strategy or "SERVING_OFF")
                    },
                }
                _apply_cpa_strategy_fields(
                    dyn_block["BiddingStrategy"],
                    search_strategy=search_strategy,
                    network_strategy=network_strategy,
                    goal_id=goal_id,
                    average_cpa=average_cpa,
                    crr=crr,
                    bid_ceiling=bid_ceiling,
                    priority_goals_items=priority_goals_items,
                    sub_campaign_block=dyn_block,
                )
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
                    "--counter-id is required for SMART_CAMPAIGN "
                    "(WSDL SmartCampaignAddItem.CounterId minOccurs=1)"
                )
            smart_campaign: Dict[str, object] = {"CounterId": counter_id}
            if smart_package_bidding_strategy_obj is not None:
                smart_campaign["PackageBiddingStrategy"] = (
                    smart_package_bidding_strategy_obj
                )
            else:
                network_strategy_type = network_strategy or "AVERAGE_CPC_PER_FILTER"
                if (
                    filter_average_cpc is not None
                    and network_strategy_type != "AVERAGE_CPC_PER_FILTER"
                ):
                    raise click.UsageError(
                        "--filter-average-cpc is only valid for SMART_CAMPAIGN "
                        "with AVERAGE_CPC_PER_FILTER network strategy"
                    )
                smart_campaign["BiddingStrategy"] = {
                    "Search": {"BiddingStrategyType": search_strategy or "SERVING_OFF"},
                    "Network": {"BiddingStrategyType": network_strategy_type},
                }
                if network_strategy_type == "AVERAGE_CPC_PER_FILTER":
                    if filter_average_cpc is None:
                        raise click.UsageError(
                            "--filter-average-cpc is required for SMART_CAMPAIGN "
                            "with AVERAGE_CPC_PER_FILTER network strategy"
                        )
                    smart_campaign["BiddingStrategy"]["Network"][
                        "AverageCpcPerFilter"
                    ] = {"FilterAverageCpc": filter_average_cpc}
            if parsed_settings:
                smart_campaign["Settings"] = parsed_settings
            if attribution_model:
                smart_campaign["AttributionModel"] = attribution_model.upper()
            if tracking_params:
                smart_campaign["TrackingParams"] = tracking_params
            campaign_data["SmartCampaign"] = smart_campaign
        elif campaign_type_norm == "MOBILE_APP_CAMPAIGN":
            mobile_campaign: Dict[str, object] = {
                "BiddingStrategy": {
                    "Search": {
                        "BiddingStrategyType": search_strategy or "HIGHEST_POSITION"
                    },
                    "Network": {
                        "BiddingStrategyType": network_strategy or "SERVING_OFF"
                    },
                }
            }
            if parsed_settings:
                mobile_campaign["Settings"] = parsed_settings
            if negative_keyword_shared_set_ids_obj is not None:
                mobile_campaign["NegativeKeywordSharedSetIds"] = (
                    negative_keyword_shared_set_ids_obj
                )
            campaign_data["MobileAppCampaign"] = mobile_campaign
        elif campaign_type_norm == "CPM_BANNER_CAMPAIGN":
            cpm_campaign: Dict[str, object] = {
                "BiddingStrategy": {
                    "Search": {"BiddingStrategyType": search_strategy or "SERVING_OFF"},
                    "Network": {
                        "BiddingStrategyType": network_strategy or "MANUAL_CPM"
                    },
                }
            }
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

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.campaigns().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


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
        "goal_id:value[:YES|NO] pairs"
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
        "TextCampaign/UnifiedCampaign.PackageBiddingStrategy." "Platforms.DynamicPlaces"
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
def update(
    ctx,
    campaign_id,
    name,
    status,
    budget,
    start_date,
    end_date,
    settings,
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
    try:
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
            "--counter-id": counter_id,
            "--counter-ids": counter_ids,
            "--dynamic-placement-search-results": dynamic_placement_search_results,
            "--dynamic-placement-product-gallery": dynamic_placement_product_gallery,
            "--priority-goals": priority_goals,
            "--relevant-keywords-budget-percent": relevant_keywords_budget_percent,
            "--relevant-keywords-mode": relevant_keywords_mode,
            "--relevant-keywords-optimize-goal-id": (
                relevant_keywords_optimize_goal_id
            ),
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
            "--tracking-params": tracking_params,
        }
        subtype_flags_provided = [
            flag for flag, value in subtype_flag_values.items() if value is not None
        ]
        if (
            campaign_type_norm is not None
            and campaign_type_norm not in subtype_supported
        ):
            raise click.UsageError(
                "Invalid value for '--type': "
                f"{campaign_type!r} is not one of "
                "'TEXT_CAMPAIGN', 'UNIFIED_CAMPAIGN', "
                "'DYNAMIC_TEXT_CAMPAIGN', 'SMART_CAMPAIGN', "
                "'MOBILE_APP_CAMPAIGN', 'CPM_BANNER_CAMPAIGN'."
            )
        if subtype_flags_provided and campaign_type_norm is None:
            raise click.UsageError(
                f"{', '.join(sorted(subtype_flags_provided))} requires --type "
                "(TEXT_CAMPAIGN | UNIFIED_CAMPAIGN | "
                "DYNAMIC_TEXT_CAMPAIGN | SMART_CAMPAIGN | "
                "MOBILE_APP_CAMPAIGN | CPM_BANNER_CAMPAIGN)."
            )
        if campaign_type_norm is not None:
            text_campaign_flags = {
                "--setting",
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
            }
            mobile_app_campaign_flags = {
                "--setting",
                "--negative-keyword-shared-set-ids",
            }
            cpm_banner_campaign_flags = {
                "--setting",
                "--counter-ids",
                "--frequency-cap-impressions",
                "--frequency-cap-period-days",
                "--frequency-cap-period-all",
                "--video-target",
            }
            allowed_subtype_flags_by_type = {
                "TEXT_CAMPAIGN": text_campaign_flags,
                "UNIFIED_CAMPAIGN": unified_campaign_flags,
                "DYNAMIC_TEXT_CAMPAIGN": dynamic_campaign_flags,
                "SMART_CAMPAIGN": smart_campaign_flags,
                "MOBILE_APP_CAMPAIGN": mobile_app_campaign_flags,
                "CPM_BANNER_CAMPAIGN": cpm_banner_campaign_flags,
            }
            _reject_incompatible_flags(
                campaign_type_norm,
                allowed_subtype_flags_by_type[campaign_type_norm],
                subtype_flag_values,
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
                        "UnifiedCampaign cannot be combined with "
                        f"{', '.join(sorted(provided))}"
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
                    package_incompatible = {
                        "--priority-goals": priority_goals,
                    }
                    if is_unified:
                        package_incompatible.update(
                            {
                                "--counter-ids": counter_ids,
                                "--attribution-model": attribution_model,
                            }
                        )
                    provided = [
                        flag
                        for flag, value in package_incompatible.items()
                        if value is not None
                    ]
                    if provided:
                        raise click.UsageError(
                            f"{package_label}.PackageBiddingStrategy cannot be "
                            f"combined with {', '.join(sorted(provided))}"
                        )
                    sub_block["PackageBiddingStrategy"] = package_bidding_strategy_obj
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
                smart_package_bidding_strategy_obj = (
                    _build_smart_package_bidding_strategy(
                        package_strategy_id,
                        package_strategy_from_campaign_id,
                        package_platform_search,
                        package_platform_network,
                        require_platforms=False,
                    )
                )
                if smart_package_bidding_strategy_obj is not None:
                    package_incompatible = {
                        "--counter-id": counter_id,
                        "--priority-goals": priority_goals,
                        "--attribution-model": attribution_model,
                    }
                    provided = [
                        flag
                        for flag, value in package_incompatible.items()
                        if value is not None
                    ]
                    if provided:
                        raise click.UsageError(
                            "SmartCampaign.PackageBiddingStrategy cannot be "
                            f"combined with {', '.join(sorted(provided))}"
                        )
                    sub_block["PackageBiddingStrategy"] = (
                        smart_package_bidding_strategy_obj
                    )
            elif campaign_type_norm == "MOBILE_APP_CAMPAIGN":
                parsed_settings = parse_setting_specs(list(settings))
                if parsed_settings:
                    sub_block["Settings"] = parsed_settings
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
                    f"--type {campaign_type_norm} requires at least one "
                    "subtype-specific field to update."
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
            raise click.UsageError("Provide at least one field to update")

        body = {"method": "update", "params": {"Campaigns": [campaign_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.campaigns().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@campaigns.command()
@click.option("--id", "campaign_id", required=True, type=int, help="Campaign ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def delete(ctx, campaign_id, dry_run):
    """Delete campaign"""
    try:
        body = {
            "method": "delete",
            "params": {"SelectionCriteria": {"Ids": [campaign_id]}},
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.campaigns().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@campaigns.command()
@click.option("--id", "campaign_id", required=True, type=int, help="Campaign ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def archive(ctx, campaign_id, dry_run):
    """Archive campaign"""
    try:
        body = {
            "method": "archive",
            "params": {"SelectionCriteria": {"Ids": [campaign_id]}},
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.campaigns().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@campaigns.command()
@click.option("--id", "campaign_id", required=True, type=int, help="Campaign ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def unarchive(ctx, campaign_id, dry_run):
    """Unarchive campaign"""
    try:
        body = {
            "method": "unarchive",
            "params": {"SelectionCriteria": {"Ids": [campaign_id]}},
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.campaigns().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@campaigns.command()
@click.option("--id", "campaign_id", required=True, type=int, help="Campaign ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def suspend(ctx, campaign_id, dry_run):
    """Suspend campaign"""
    try:
        body = {
            "method": "suspend",
            "params": {"SelectionCriteria": {"Ids": [campaign_id]}},
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.campaigns().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@campaigns.command()
@click.option("--id", "campaign_id", required=True, type=int, help="Campaign ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def resume(ctx, campaign_id, dry_run):
    """Resume campaign"""
    try:
        body = {
            "method": "resume",
            "params": {"SelectionCriteria": {"Ids": [campaign_id]}},
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.campaigns().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()
