"""Shared constants, validators and payload builders for campaigns commands.

This module was extracted from the former monolithic
``direct_cli/commands/campaigns.py`` (issue #602) as part of an
incremental split. It holds everything that is not the ``campaigns``
Click group itself or the ``get``/``add``/``update`` command functions:

* module-level constants (``CAMPAIGNS_GET_CRITERIA_LIMITS``, ``YES_NO``, …)
* typed-flag validators (``_validate_max_length``, ``_validate_sms_time``)
* payload builders (``_build_notification``, ``_build_time_targeting``,
  ``_build_relevant_keywords``, ``_build_dynamic_placement_types``,
  ``_build_frequency_cap``, ``_build_package_bidding_strategy``,
  ``_build_smart_package_bidding_strategy``, ``_priority_goals_update_items``,
  ``_route_cpa_flag``)
* reusable composite ``click.option`` groups for the TextCampaign strategy
  flags (``_TEXT_SEARCH_STRATEGY_OPTIONS``, ``_TEXT_NETWORK_STRATEGY_OPTIONS``
  and their ``*_UPDATE`` variants) plus the ``_apply_options`` helper.

``campaigns.py`` re-imports every public name from here so the CLI surface
is byte-for-byte identical.
"""

import re
from typing import Dict, List, Optional, Sequence

import click

from ..i18n import t
from ..utils import MICRO_RUBLES, parse_csv_strings, parse_ids
from .._bidding_strategy import BUDGET_TYPES

# Yandex Direct campaigns.get caps SelectionCriteria.Ids at runtime
# (the WSDL declares maxOccurs="unbounded"). Live measurement 2026-06-17 via
# sandbox: --ids ×1001 → 4001 "Exceed the maximum number of IDs per array
# SelectionCriteria.Ids" (N=10/100/1000 accepted).
CAMPAIGNS_GET_CRITERIA_LIMITS = {"Ids": 1000}

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


# TextCampaign Search typed-strategy options shared verbatim by ``add`` and
# ``update`` (issue #361/#388). Defined once as a composite decorator so the
# 13 ``@click.option`` declarations are not copy-pasted across both commands;
# ``update`` additionally carries the update-only ``--text-search-budget-type``
# as a separate option after this block, preserving the original --help order.
_TEXT_SEARCH_STRATEGY_OPTIONS = [
    click.option(
        "--text-search-weekly-spend-limit",
        type=MICRO_RUBLES,
        help="TextCampaign Search strategy WeeklySpendLimit in micro-rubles",
    ),
    click.option(
        "--text-search-custom-period-spend-limit",
        type=MICRO_RUBLES,
        help="TextCampaign Search CustomPeriodBudget.SpendLimit in micro-rubles",
    ),
    click.option(
        "--text-search-custom-period-start-date",
        help="TextCampaign Search CustomPeriodBudget.StartDate",
    ),
    click.option(
        "--text-search-custom-period-end-date",
        help="TextCampaign Search CustomPeriodBudget.EndDate",
    ),
    click.option(
        "--text-search-custom-period-auto-continue",
        type=click.Choice(YES_NO, case_sensitive=False),
        help="TextCampaign Search CustomPeriodBudget.AutoContinue: YES or NO",
    ),
    click.option(
        "--text-search-average-cpc",
        type=MICRO_RUBLES,
        help="TextCampaign Search strategy AverageCpc in micro-rubles",
    ),
    click.option(
        "--text-search-pay-cpa",
        type=MICRO_RUBLES,
        help="TextCampaign Search StrategyPayForConversionAdd.Cpa in micro-rubles",
    ),
    click.option(
        "--text-search-clicks-per-week",
        type=click.IntRange(1),
        help="TextCampaign Search WEEKLY_CLICK_PACKAGE ClicksPerWeek",
    ),
    click.option(
        "--text-search-reserve-return",
        type=click.IntRange(0, 100),
        help=(
            "TextCampaign Search AVERAGE_ROI ReserveReturn percentage "
            "(0-100, multiple of 10)"
        ),
    ),
    click.option(
        "--text-search-roi-coef",
        type=MICRO_RUBLES,
        help=(
            "TextCampaign Search AVERAGE_ROI RoiCoef as a ratio (sales profit "
            "/ promotion costs), supplied directly in micro-rubles wire format "
            "(e.g. a 1.0 ratio is 1000000)."
        ),
    ),
    click.option(
        "--text-search-profitability",
        type=MICRO_RUBLES,
        help=(
            "TextCampaign Search AVERAGE_ROI Profitability percentage, "
            "supplied directly in micro-rubles wire format "
            "(e.g. 20% is 20000000)."
        ),
    ),
    click.option(
        "--text-search-exploration-min-budget",
        type=MICRO_RUBLES,
        help="TextCampaign Search ExplorationBudget.MinimumExplorationBudget in micro-rubles",
    ),
    click.option(
        "--text-search-exploration-is-custom",
        type=click.Choice(YES_NO, case_sensitive=False),
        help=(
            "TextCampaign Search ExplorationBudget."
            "IsMinimumExplorationBudgetCustom: YES or NO"
        ),
    ),
]


def _apply_options(func, options):
    """Apply a list of ``click.option`` decorators to ``func`` preserving the
    list's top-to-bottom order in ``--help`` (Click stacks bottom-up, so apply
    in reverse)."""
    for option in reversed(options):
        func = option(func)
    return func


def _text_search_strategy_options(func):
    """Apply the shared TextCampaign Search typed-strategy options (add order)."""
    return _apply_options(func, _TEXT_SEARCH_STRATEGY_OPTIONS)


# Update variant: identical to add but with the update-only
# ``--text-search-budget-type`` switch spliced in after the custom-period
# options (position 5), exactly where update declared it inline — so the
# rendered --help order is byte-identical to the pre-dedup update command.
_TEXT_SEARCH_STRATEGY_OPTIONS_UPDATE = (
    _TEXT_SEARCH_STRATEGY_OPTIONS[:5]
    + [
        click.option(
            "--text-search-budget-type",
            type=click.Choice(BUDGET_TYPES, case_sensitive=False),
            help="TextCampaign Search strategy BudgetType for update",
        )
    ]
    + _TEXT_SEARCH_STRATEGY_OPTIONS[5:]
)


def _text_search_strategy_options_update(func):
    """Apply the shared TextCampaign Search options plus the update-only
    ``--text-search-budget-type`` in its original mid-cluster position."""
    return _apply_options(func, _TEXT_SEARCH_STRATEGY_OPTIONS_UPDATE)


# TextCampaign Network typed-strategy options shared verbatim by ``add`` and
# ``update`` (issue #364). Same composite-decorator pattern as the Search
# cluster above; ``update`` splices the update-only ``--text-network-budget-type``
# in at position 5, exactly where it sat inline.
_TEXT_NETWORK_STRATEGY_OPTIONS = [
    click.option(
        "--text-network-weekly-spend-limit",
        type=MICRO_RUBLES,
        help="TextCampaign Network strategy WeeklySpendLimit in micro-rubles (#364)",
    ),
    click.option(
        "--text-network-custom-period-spend-limit",
        type=MICRO_RUBLES,
        help=(
            "TextCampaign Network CustomPeriodBudget.SpendLimit "
            "in micro-rubles (#364)"
        ),
    ),
    click.option(
        "--text-network-custom-period-start-date",
        help="TextCampaign Network CustomPeriodBudget.StartDate (#364)",
    ),
    click.option(
        "--text-network-custom-period-end-date",
        help="TextCampaign Network CustomPeriodBudget.EndDate (#364)",
    ),
    click.option(
        "--text-network-custom-period-auto-continue",
        type=click.Choice(YES_NO, case_sensitive=False),
        help=("TextCampaign Network CustomPeriodBudget.AutoContinue: YES or NO (#364)"),
    ),
    click.option(
        "--text-network-average-cpc",
        type=MICRO_RUBLES,
        help="TextCampaign Network strategy AverageCpc in micro-rubles (#364)",
    ),
    click.option(
        "--text-network-pay-cpa",
        type=MICRO_RUBLES,
        help=(
            "TextCampaign Network StrategyPayForConversionAdd.Cpa "
            "in micro-rubles (#364)"
        ),
    ),
    click.option(
        "--text-network-clicks-per-week",
        type=click.IntRange(1),
        help="TextCampaign Network WEEKLY_CLICK_PACKAGE ClicksPerWeek (#364)",
    ),
    click.option(
        "--text-network-reserve-return",
        type=click.IntRange(0, 100),
        help=(
            "TextCampaign Network AVERAGE_ROI ReserveReturn percentage "
            "(0-100, multiple of 10) (#364)"
        ),
    ),
    click.option(
        "--text-network-roi-coef",
        type=MICRO_RUBLES,
        help=(
            "TextCampaign Network AVERAGE_ROI RoiCoef as a ratio (sales profit "
            "/ promotion costs), supplied directly in micro-rubles wire format "
            "(e.g. a 1.0 ratio is 1000000) (#364)."
        ),
    ),
    click.option(
        "--text-network-profitability",
        type=MICRO_RUBLES,
        help=(
            "TextCampaign Network AVERAGE_ROI Profitability percentage, "
            "supplied directly in micro-rubles wire format "
            "(e.g. 20% is 20000000) (#364)."
        ),
    ),
    click.option(
        "--text-network-exploration-min-budget",
        type=MICRO_RUBLES,
        help=(
            "TextCampaign Network ExplorationBudget.MinimumExplorationBudget "
            "in micro-rubles (#364)"
        ),
    ),
    click.option(
        "--text-network-exploration-is-custom",
        type=click.Choice(YES_NO, case_sensitive=False),
        help=(
            "TextCampaign Network ExplorationBudget."
            "IsMinimumExplorationBudgetCustom: YES or NO (#364)"
        ),
    ),
    click.option(
        "--text-network-limit-percent",
        type=click.IntRange(10, 100),
        help=(
            "TextCampaign Network NetworkDefault.LimitPercent, 10-100 by tens (#364)"
        ),
    ),
]


def _text_network_strategy_options(func):
    """Apply the shared TextCampaign Network typed-strategy options (add order)."""
    return _apply_options(func, _TEXT_NETWORK_STRATEGY_OPTIONS)


_TEXT_NETWORK_STRATEGY_OPTIONS_UPDATE = (
    _TEXT_NETWORK_STRATEGY_OPTIONS[:5]
    + [
        click.option(
            "--text-network-budget-type",
            type=click.Choice(BUDGET_TYPES, case_sensitive=False),
            help="TextCampaign Network strategy BudgetType for update (#364)",
        )
    ]
    + _TEXT_NETWORK_STRATEGY_OPTIONS[5:]
)


def _text_network_strategy_options_update(func):
    """Apply the shared TextCampaign Network options plus the update-only
    ``--text-network-budget-type`` in its original mid-cluster position."""
    return _apply_options(func, _TEXT_NETWORK_STRATEGY_OPTIONS_UPDATE)
