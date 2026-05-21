"""
Campaigns commands
"""

from typing import Dict, List, Optional

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
    parse_json,
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

_NOTIFICATION_KEYS = {"SmsSettings", "EmailSettings"}
_SMS_SETTINGS_KEYS = {"Events", "TimeFrom", "TimeTo"}
_EMAIL_SETTINGS_KEYS = {
    "Email",
    "CheckPositionInterval",
    "WarningBalance",
    "SendAccountNews",
    "SendWarnings",
}
_TIME_TARGETING_KEYS = {
    "Schedule",
    "ConsiderWorkingWeekends",
    "HolidaysSchedule",
}
_HOLIDAYS_SCHEDULE_KEYS = {
    "SuspendOnHolidays",
    "BidPercent",
    "StartHour",
    "EndHour",
}


def _validate_notification_shape(notification: object) -> None:
    """Reject malformed --notification JSON before sending to API."""
    if not isinstance(notification, dict) or not notification:
        raise click.UsageError(
            "--notification must be a non-empty JSON object with "
            f"keys from {sorted(_NOTIFICATION_KEYS)}"
        )
    unknown = set(notification) - _NOTIFICATION_KEYS
    if unknown:
        raise click.UsageError(
            f"--notification contains unknown key(s) {sorted(unknown)}; "
            f"allowed: {sorted(_NOTIFICATION_KEYS)}"
        )
    sms = notification.get("SmsSettings")
    if sms is not None:
        if not isinstance(sms, dict):
            raise click.UsageError("--notification.SmsSettings must be a JSON object")
        unknown_sms = set(sms) - _SMS_SETTINGS_KEYS
        if unknown_sms:
            raise click.UsageError(
                "--notification.SmsSettings contains unknown key(s) "
                f"{sorted(unknown_sms)}; allowed: {sorted(_SMS_SETTINGS_KEYS)}"
            )
    email = notification.get("EmailSettings")
    if email is not None:
        if not isinstance(email, dict):
            raise click.UsageError("--notification.EmailSettings must be a JSON object")
        unknown_email = set(email) - _EMAIL_SETTINGS_KEYS
        if unknown_email:
            raise click.UsageError(
                "--notification.EmailSettings contains unknown key(s) "
                f"{sorted(unknown_email)}; allowed: "
                f"{sorted(_EMAIL_SETTINGS_KEYS)}"
            )


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


def _validate_time_targeting_shape(time_targeting: object) -> None:
    """Reject malformed --time-targeting JSON before sending to API."""
    if not isinstance(time_targeting, dict) or not time_targeting:
        raise click.UsageError(
            "--time-targeting must be a non-empty JSON object with "
            f"keys from {sorted(_TIME_TARGETING_KEYS)}"
        )
    unknown = set(time_targeting) - _TIME_TARGETING_KEYS
    if unknown:
        raise click.UsageError(
            f"--time-targeting contains unknown key(s) {sorted(unknown)}; "
            f"allowed: {sorted(_TIME_TARGETING_KEYS)}"
        )
    holidays = time_targeting.get("HolidaysSchedule")
    if holidays is not None:
        if not isinstance(holidays, dict):
            raise click.UsageError(
                "--time-targeting.HolidaysSchedule must be a JSON object"
            )
        unknown_h = set(holidays) - _HOLIDAYS_SCHEDULE_KEYS
        if unknown_h:
            raise click.UsageError(
                "--time-targeting.HolidaysSchedule contains unknown "
                f"key(s) {sorted(unknown_h)}; allowed: "
                f"{sorted(_HOLIDAYS_SCHEDULE_KEYS)}"
            )


@click.group()
def campaigns():
    """Manage campaigns"""


def _parse_csv_option(option_name: str, value: Optional[str]) -> Optional[List[str]]:
    """Parse a CSV option and reject explicitly empty input."""
    parsed = parse_csv_strings(value)
    if value is not None and not parsed:
        raise click.UsageError(f"{option_name} must contain at least one value")
    return parsed


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
        "(TextCampaign/DynamicTextCampaign.CounterIds)"
    ),
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
        "Comma-separated goal_id:value pairs for "
        "TextCampaign.PriorityGoals (required for "
        "AVERAGE_CPA_MULTIPLE_GOALS / PAY_FOR_CONVERSION_MULTIPLE_GOALS)"
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
    "--notification",
    "notification_json",
    help=(
        "JSON for CampaignBase.Notification "
        '({"SmsSettings":{...}, "EmailSettings":{...}})'
    ),
)
@click.option(
    "--time-targeting",
    "time_targeting_json",
    help=(
        "JSON for CampaignAddItem.TimeTargeting "
        '({"Schedule":[...], "ConsiderWorkingWeekends":"YES|NO", ...})'
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
    goal_id,
    priority_goals,
    average_cpa,
    crr,
    bid_ceiling,
    notification_json,
    time_targeting_json,
    dry_run,
):
    """Add new campaign"""
    try:
        campaign_type_norm = (
            (campaign_type or "TEXT_CAMPAIGN").upper().replace("-", "_")
        )
        supported_types = {
            "TEXT_CAMPAIGN",
            "DYNAMIC_TEXT_CAMPAIGN",
            "SMART_CAMPAIGN",
        }
        if campaign_type_norm not in supported_types:
            raise click.UsageError(
                "Invalid value for '--type': "
                f"{campaign_type!r} is not one of "
                "'TEXT_CAMPAIGN', 'DYNAMIC_TEXT_CAMPAIGN', 'SMART_CAMPAIGN'."
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
            }
            | text_dynamic_extras,
            "DYNAMIC_TEXT_CAMPAIGN": {
                "--setting",
                "--search-strategy",
                "--network-strategy",
            }
            | text_dynamic_extras,
            "SMART_CAMPAIGN": {
                "--setting",
                "--search-strategy",
                "--network-strategy",
                "--filter-average-cpc",
                "--counter-id",
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
                "--goal-id": goal_id,
                "--priority-goals": priority_goals,
                "--average-cpa": average_cpa,
                "--crr": crr,
                "--bid-ceiling": bid_ceiling,
            },
        )

        # Parse cross-cutting structured inputs up front so any
        # UsageError fires before we start composing the payload.
        notification_obj = None
        if notification_json is not None:
            try:
                notification_obj = parse_json(notification_json)
            except ValueError as exc:
                raise click.UsageError(f"--notification: {exc}")
            _validate_notification_shape(notification_obj)

        time_targeting_obj = None
        if time_targeting_json is not None:
            try:
                time_targeting_obj = parse_json(time_targeting_json)
            except ValueError as exc:
                raise click.UsageError(f"--time-targeting: {exc}")
            _validate_time_targeting_shape(time_targeting_obj)

        counter_ids_list = None
        if counter_ids is not None:
            counter_ids_list = parse_ids(counter_ids)
            if not counter_ids_list:
                raise click.UsageError(
                    "--counter-ids must contain at least one integer"
                )

        priority_goals_items = parse_priority_goals_spec(priority_goals)

        campaign_data = {"Name": name, "StartDate": start_date}
        parsed_settings = parse_setting_specs(list(settings))
        if campaign_type_norm == "TEXT_CAMPAIGN":
            text_block = {
                "BiddingStrategy": {
                    "Search": {
                        "BiddingStrategyType": (search_strategy or "HIGHEST_POSITION")
                    },
                    "Network": {
                        "BiddingStrategyType": (network_strategy or "SERVING_OFF")
                    },
                },
                "Settings": parsed_settings or [],
            }
            if counter_ids_list:
                text_block["CounterIds"] = counter_ids_list
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
            campaign_data["TextCampaign"] = text_block
        elif campaign_type_norm == "DYNAMIC_TEXT_CAMPAIGN":
            dyn_block = {
                "BiddingStrategy": {
                    "Search": {
                        "BiddingStrategyType": (search_strategy or "HIGHEST_POSITION")
                    },
                    "Network": {
                        "BiddingStrategyType": (network_strategy or "SERVING_OFF")
                    },
                },
                "Settings": parsed_settings or [],
            }
            if counter_ids_list:
                dyn_block["CounterIds"] = counter_ids_list
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
            campaign_data["DynamicTextCampaign"] = dyn_block
        elif campaign_type_norm == "SMART_CAMPAIGN":
            # WSDL SmartCampaignAddItem.CounterId is minOccurs=1
            # (issue #198 H6).
            if counter_id is None:
                raise click.UsageError(
                    "--counter-id is required for SMART_CAMPAIGN "
                    "(WSDL SmartCampaignAddItem.CounterId minOccurs=1)"
                )
            network_strategy_type = network_strategy or "AVERAGE_CPC_PER_FILTER"
            if (
                filter_average_cpc is not None
                and network_strategy_type != "AVERAGE_CPC_PER_FILTER"
            ):
                raise click.UsageError(
                    "--filter-average-cpc is only valid for SMART_CAMPAIGN "
                    "with AVERAGE_CPC_PER_FILTER network strategy"
                )
            smart_campaign = {
                "BiddingStrategy": {
                    "Search": {"BiddingStrategyType": search_strategy or "SERVING_OFF"},
                    "Network": {"BiddingStrategyType": network_strategy_type},
                },
                "CounterId": counter_id,
            }
            if network_strategy_type == "AVERAGE_CPC_PER_FILTER":
                if filter_average_cpc is None:
                    raise click.UsageError(
                        "--filter-average-cpc is required for SMART_CAMPAIGN "
                        "with AVERAGE_CPC_PER_FILTER network strategy"
                    )
                smart_campaign["BiddingStrategy"]["Network"]["AverageCpcPerFilter"] = {
                    "FilterAverageCpc": filter_average_cpc
                }
            if parsed_settings:
                smart_campaign["Settings"] = parsed_settings
            campaign_data["SmartCampaign"] = smart_campaign

        if budget:
            campaign_data["DailyBudget"] = {
                "Amount": budget,
                "Mode": "STANDARD",
            }

        if end_date:
            campaign_data["EndDate"] = end_date

        # CampaignBase.Notification + CampaignAddItem.TimeTargeting are
        # campaign-level (siblings of TextCampaign/DynamicTextCampaign/
        # SmartCampaign), so apply them after the subtype block.
        if notification_obj is not None:
            campaign_data["Notification"] = notification_obj
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
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def update(ctx, campaign_id, name, status, budget, start_date, end_date, dry_run):
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
