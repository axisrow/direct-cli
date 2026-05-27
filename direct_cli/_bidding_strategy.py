"""Shared bidding-strategy builder foundation for `campaigns add/update`.

Foundation module for milestone 0.3.13 (#290). Pure 1:1 extraction of the
bidding-strategy maps, support/required-flag sets and builder helpers
previously living in ``direct_cli.commands.campaigns``. Behavior is
identical to the original implementation — this module exists so that
follow-up leaf-PRs (#361-369, #373) can register a single dispatch entry
instead of editing the giant if/elif chain in ``add()``/``update()``.

The dispatch registry (`CAMPAIGN_TYPE_BUILDERS`,
``register_bidding_strategy_builder``, ``get_bidding_strategy_builder``)
is keyed on ``(campaign_type, operation, branch)`` and resolves to the
builder callable owning that combo. Missing keys are intentional: the
caller falls back to today's legacy
``{"BiddingStrategyType": strategy_type}`` shape, exactly mirroring the
pre-refactor behavior.
"""

from typing import Callable, Dict, List, Optional

import click

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

CPM_BANNER_SEARCH_STRATEGIES = ["SERVING_OFF"]
CPM_BANNER_NETWORK_STRATEGIES = [
    "MANUAL_CPM",
    "CP_DECREASED_PRICE_FOR_REPEATED_IMPRESSIONS",
    "WB_DECREASED_PRICE_FOR_REPEATED_IMPRESSIONS",
    "CP_MAXIMUM_IMPRESSIONS",
    "WB_MAXIMUM_IMPRESSIONS",
    "CP_AVERAGE_CPV",
    "WB_AVERAGE_CPV",
]
TEXT_CAMPAIGN_SEARCH_STRATEGIES = [
    "AVERAGE_CPC",
    "AVERAGE_CPA",
    "PAY_FOR_CONVERSION",
    "WB_MAXIMUM_CONVERSION_RATE",
    "HIGHEST_POSITION",
    "IMPRESSIONS_BELOW_SEARCH",
    "SERVING_OFF",
    "WB_MAXIMUM_CLICKS",
    "WEEKLY_CLICK_PACKAGE",
    "AVERAGE_ROI",
    "AVERAGE_CRR",
    "PAY_FOR_CONVERSION_CRR",
    "AVERAGE_CPA_MULTIPLE_GOALS",
    "PAY_FOR_CONVERSION_MULTIPLE_GOALS",
    "MAX_PROFIT",
]
MOBILE_APP_SEARCH_STRATEGIES = [
    "HIGHEST_POSITION",
    "WB_MAXIMUM_CLICKS",
    "WB_MAXIMUM_APP_INSTALLS",
    "AVERAGE_CPC",
    "AVERAGE_CPI",
    "WEEKLY_CLICK_PACKAGE",
    "PAY_FOR_INSTALL",
    "SERVING_OFF",
]
MOBILE_APP_SEARCH_DISABLED_STRATEGIES = {"IMPRESSIONS_BELOW_SEARCH"}
MOBILE_APP_SEARCH_STRATEGY_TO_WSDL_SUBTYPE = {
    "WB_MAXIMUM_CLICKS": "WbMaximumClicks",
    "WB_MAXIMUM_APP_INSTALLS": "WbMaximumAppInstalls",
    "AVERAGE_CPC": "AverageCpc",
    "AVERAGE_CPI": "AverageCpi",
    "WEEKLY_CLICK_PACKAGE": "WeeklyClickPackage",
    "PAY_FOR_INSTALL": "PayForInstall",
}
MOBILE_APP_SEARCH_WEEKLY_SPEND_SUBTYPES = {
    "WbMaximumClicks",
    "WbMaximumAppInstalls",
    "AverageCpc",
    "AverageCpi",
    "PayForInstall",
}
MOBILE_APP_SEARCH_BID_CEILING_SUBTYPES = {
    "WbMaximumClicks",
    "WbMaximumAppInstalls",
    "AverageCpi",
    "WeeklyClickPackage",
}
MOBILE_APP_SEARCH_CUSTOM_PERIOD_SUBTYPES = {"WbMaximumClicks", "AverageCpc"}
MOBILE_APP_SEARCH_BUDGET_TYPE_SUBTYPES = {"WbMaximumClicks", "AverageCpc"}
MOBILE_APP_SEARCH_AVERAGE_CPC_SUBTYPES = {"AverageCpc", "WeeklyClickPackage"}
MOBILE_APP_SEARCH_AVERAGE_CPI_SUBTYPES = {"AverageCpi", "PayForInstall"}
MOBILE_APP_SEARCH_CLICKS_PER_WEEK_SUBTYPES = {"WeeklyClickPackage"}
MOBILE_APP_NETWORK_STRATEGIES = [
    "NETWORK_DEFAULT",
    "MAXIMUM_COVERAGE",
    "WB_MAXIMUM_CLICKS",
    "WB_MAXIMUM_APP_INSTALLS",
    "AVERAGE_CPC",
    "AVERAGE_CPI",
    "WEEKLY_CLICK_PACKAGE",
    "PAY_FOR_INSTALL",
    "SERVING_OFF",
]
MOBILE_APP_NETWORK_STRATEGY_TO_WSDL_SUBTYPE = {
    "NETWORK_DEFAULT": "NetworkDefault",
    "WB_MAXIMUM_CLICKS": "WbMaximumClicks",
    "WB_MAXIMUM_APP_INSTALLS": "WbMaximumAppInstalls",
    "AVERAGE_CPC": "AverageCpc",
    "AVERAGE_CPI": "AverageCpi",
    "WEEKLY_CLICK_PACKAGE": "WeeklyClickPackage",
    "PAY_FOR_INSTALL": "PayForInstall",
}
MOBILE_APP_NETWORK_WEEKLY_SPEND_SUBTYPES = {
    "WbMaximumClicks",
    "WbMaximumAppInstalls",
    "AverageCpc",
    "AverageCpi",
    "PayForInstall",
}
MOBILE_APP_NETWORK_BID_CEILING_SUBTYPES = {
    "WbMaximumClicks",
    "WbMaximumAppInstalls",
    "AverageCpi",
    "WeeklyClickPackage",
}
MOBILE_APP_NETWORK_CUSTOM_PERIOD_SUBTYPES = {
    "WbMaximumClicks",
    "AverageCpc",
    "AverageCpi",
    "PayForInstall",
}
MOBILE_APP_NETWORK_BUDGET_TYPE_SUBTYPES = {
    "WbMaximumClicks",
    "AverageCpc",
    "AverageCpi",
    "PayForInstall",
}
MOBILE_APP_NETWORK_AVERAGE_CPC_SUBTYPES = {"AverageCpc", "WeeklyClickPackage"}
MOBILE_APP_NETWORK_AVERAGE_CPI_SUBTYPES = {"AverageCpi", "PayForInstall"}
MOBILE_APP_NETWORK_CLICKS_PER_WEEK_SUBTYPES = {"WeeklyClickPackage"}
BUDGET_TYPES = ["WEEKLY_BUDGET", "CUSTOM_PERIOD_BUDGET"]

# DynamicTextCampaign.BiddingStrategy.Network — strategy families from
# DynamicTextCampaignNetworkStrategyTypeEnum (campaigns WSDL line 361).
# Issue #365.
DYNAMIC_TEXT_NETWORK_STRATEGIES = [
    "NETWORK_DEFAULT",
    "MAXIMUM_COVERAGE",
    "WB_MAXIMUM_CONVERSION_RATE",
    "WB_MAXIMUM_CLICKS",
    "AVERAGE_CPC",
    "AVERAGE_CPA",
    "PAY_FOR_CONVERSION",
    "AVERAGE_ROI",
    "AVERAGE_CRR",
    "PAY_FOR_CONVERSION_CRR",
    "WEEKLY_CLICK_PACKAGE",
    "SERVING_OFF",
]
# Maps DynamicTextCampaignNetworkStrategyTypeEnum -> nested Strategy*Add
# subtype field name on DynamicTextCampaignNetworkStrategyAdd. Subtypes
# without a nested block (MAXIMUM_COVERAGE, SERVING_OFF) are absent here
# and must reject detail flags.
DYNAMIC_TEXT_NETWORK_STRATEGY_TO_WSDL_SUBTYPE = {
    "NETWORK_DEFAULT": "NetworkDefault",
    "WB_MAXIMUM_CLICKS": "WbMaximumClicks",
    "WB_MAXIMUM_CONVERSION_RATE": "WbMaximumConversionRate",
    "AVERAGE_CPC": "AverageCpc",
    "AVERAGE_CPA": "AverageCpa",
    "PAY_FOR_CONVERSION": "PayForConversion",
    "AVERAGE_ROI": "AverageRoi",
    "AVERAGE_CRR": "AverageCrr",
    "PAY_FOR_CONVERSION_CRR": "PayForConversionCrr",
    "WEEKLY_CLICK_PACKAGE": "WeeklyClickPackage",
}
# Per-subtype WSDL field support (campaigns WSDL lines 1339-1514). Empty
# string set = the field is not declared on that Strategy*Add subtype and
# must raise a CLI UsageError instead of being silently dropped.
_DYN_NETWORK_WEEKLY_SPEND_LIMIT_SUBTYPES = {
    "WbMaximumClicks",
    "WbMaximumConversionRate",
    "AverageCpc",
    "AverageCpa",
    "PayForConversion",
    "AverageRoi",
    "AverageCrr",
    "PayForConversionCrr",
}
_DYN_NETWORK_BID_CEILING_SUBTYPES = {
    "WbMaximumClicks",
    "WbMaximumConversionRate",
    "AverageCpa",
    "AverageRoi",
    "WeeklyClickPackage",
}
_DYN_NETWORK_CUSTOM_PERIOD_SUBTYPES = {
    "WbMaximumClicks",
    "WbMaximumConversionRate",
    "AverageCpc",
    "AverageCpa",
    "PayForConversion",
    "AverageRoi",
    "AverageCrr",
    "PayForConversionCrr",
}
_DYN_NETWORK_GOAL_ID_SUBTYPES = {
    "WbMaximumConversionRate",
    "AverageCpa",
    "PayForConversion",
    "AverageRoi",
    "AverageCrr",
    "PayForConversionCrr",
}
_DYN_NETWORK_AVERAGE_CPA_SUBTYPES = {"AverageCpa"}
_DYN_NETWORK_CPA_SUBTYPES = {"PayForConversion"}
_DYN_NETWORK_AVERAGE_CPC_SUBTYPES = {"AverageCpc", "WeeklyClickPackage"}
_DYN_NETWORK_CRR_SUBTYPES = {"AverageCrr", "PayForConversionCrr"}
_DYN_NETWORK_CLICKS_PER_WEEK_SUBTYPES = {"WeeklyClickPackage"}
_DYN_NETWORK_RESERVE_RETURN_SUBTYPES = {"AverageRoi"}
_DYN_NETWORK_ROI_COEF_SUBTYPES = {"AverageRoi"}
_DYN_NETWORK_PROFITABILITY_SUBTYPES = {"AverageRoi"}
_DYN_NETWORK_EXPLORATION_BUDGET_SUBTYPES = {
    "AverageCpa",
    "AverageRoi",
    "AverageCrr",
}
_DYN_NETWORK_LIMIT_PERCENT_SUBTYPES = {"NetworkDefault"}
_DYN_NETWORK_BUDGET_TYPE_SUBTYPES = {
    "WbMaximumClicks",
    "WbMaximumConversionRate",
    "AverageCpc",
    "AverageCpa",
    "PayForConversion",
    "AverageRoi",
    "AverageCrr",
    "PayForConversionCrr",
}

# DynamicTextCampaign.BiddingStrategy.Search — strategy families from
# DynamicTextCampaignSearchStrategyTypeEnum (campaigns WSDL line 344-360).
# Issue #362.
#
# Settable values mirror the WSDL enum. ``UNKNOWN`` is a read-side sentinel
# (same convention as TextCampaign / MobileApp / CpmBanner enums on add)
# and is intentionally not exposed on the CLI.
DYNAMIC_TEXT_SEARCH_STRATEGIES = [
    "HIGHEST_POSITION",
    "WB_MAXIMUM_CONVERSION_RATE",
    "WB_MAXIMUM_CLICKS",
    "AVERAGE_CPC",
    "AVERAGE_CPA",
    "PAY_FOR_CONVERSION",
    "PAY_FOR_CONVERSION_CRR",
    "WEEKLY_CLICK_PACKAGE",
    "AVERAGE_ROI",
    "AVERAGE_CRR",
    "IMPRESSIONS_BELOW_SEARCH",
    "SERVING_OFF",
]
# Maps DynamicTextCampaignSearchStrategyTypeEnum -> nested Strategy*Add
# field name on DynamicTextCampaignSearchStrategyAdd (campaigns WSDL line
# 1712-1733). Subtypes without a nested Strategy*Add block
# (HIGHEST_POSITION, IMPRESSIONS_BELOW_SEARCH, SERVING_OFF) are absent
# here — the API discriminates only by BiddingStrategyType for those.
DYNAMIC_TEXT_SEARCH_STRATEGY_TO_WSDL_SUBTYPE: Dict[str, str] = {
    "WB_MAXIMUM_CLICKS": "WbMaximumClicks",
    "WB_MAXIMUM_CONVERSION_RATE": "WbMaximumConversionRate",
    "AVERAGE_CPC": "AverageCpc",
    "AVERAGE_CPA": "AverageCpa",
    "PAY_FOR_CONVERSION": "PayForConversion",
    "AVERAGE_ROI": "AverageRoi",
    "AVERAGE_CRR": "AverageCrr",
    "PAY_FOR_CONVERSION_CRR": "PayForConversionCrr",
    "WEEKLY_CLICK_PACKAGE": "WeeklyClickPackage",
}
# Per-subtype WSDL field support for DynamicTextCampaign.Search subtypes.
# WSDL references campaigns.xml lines 1339-1488 (Strategy*Add types) plus
# the Wb*-shared StrategyWeeklyBudgetAddBase (lines 1333-1338). Empty set
# = the field is not declared on that Strategy*Add subtype and must
# UsageError instead of being silently dropped.
_DYN_SEARCH_WEEKLY_SPEND_LIMIT_SUBTYPES = {
    "WbMaximumClicks",
    "WbMaximumConversionRate",
    "AverageCpc",
    "AverageCpa",
    "PayForConversion",
    "AverageRoi",
    "AverageCrr",
    "PayForConversionCrr",
}
_DYN_SEARCH_BID_CEILING_SUBTYPES = {
    "WbMaximumClicks",
    "WbMaximumConversionRate",
    "AverageCpa",
    "AverageRoi",
    "WeeklyClickPackage",
}
_DYN_SEARCH_CUSTOM_PERIOD_SUBTYPES = {
    "WbMaximumClicks",
    "WbMaximumConversionRate",
    "AverageCpc",
    "AverageCpa",
    "PayForConversion",
    "AverageRoi",
    "AverageCrr",
    "PayForConversionCrr",
}
_DYN_SEARCH_GOAL_ID_SUBTYPES = {
    "WbMaximumConversionRate",
    "AverageCpa",
    "PayForConversion",
    "AverageRoi",
    "AverageCrr",
    "PayForConversionCrr",
}
_DYN_SEARCH_AVERAGE_CPA_SUBTYPES = {"AverageCpa"}
_DYN_SEARCH_CPA_SUBTYPES = {"PayForConversion"}
_DYN_SEARCH_AVERAGE_CPC_SUBTYPES = {"AverageCpc", "WeeklyClickPackage"}
_DYN_SEARCH_CRR_SUBTYPES = {"AverageCrr", "PayForConversionCrr"}
_DYN_SEARCH_CLICKS_PER_WEEK_SUBTYPES = {"WeeklyClickPackage"}
_DYN_SEARCH_RESERVE_RETURN_SUBTYPES = {"AverageRoi"}
_DYN_SEARCH_ROI_COEF_SUBTYPES = {"AverageRoi"}
_DYN_SEARCH_PROFITABILITY_SUBTYPES = {"AverageRoi"}
# ExplorationBudget is declared on StrategyAverageCpaAdd (line 1377),
# StrategyAverageRoiAdd (line 1462) and StrategyAverageCrrAdd (line
# 1471) only — not on PayForConversionCrrAdd / others.
_DYN_SEARCH_EXPLORATION_BUDGET_SUBTYPES = {
    "AverageCpa",
    "AverageRoi",
    "AverageCrr",
}
# BudgetType (WEEKLY_BUDGET / CUSTOM_PERIOD_BUDGET) is an update-only
# switch; on add the budget slice is implied by WeeklySpendLimit vs
# CustomPeriodBudget presence. Per the official Yandex update docs
# (cross-referenced with WSDL) BudgetType is settable only on the
# strategies that carry both WeeklySpendLimit and CustomPeriodBudget,
# i.e. the eight Wb*/AverageCp*/AverageRoi/AverageCrr/PayFor*Crr
# subtypes (mirrors the DynamicText Network audit in #386).
_DYN_SEARCH_BUDGET_TYPE_SUBTYPES = {
    "WbMaximumClicks",
    "WbMaximumConversionRate",
    "AverageCpc",
    "AverageCpa",
    "PayForConversion",
    "AverageRoi",
    "AverageCrr",
    "PayForConversionCrr",
}


def apply_cpa_strategy_fields(
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


def build_text_campaign_search_base(
    *,
    search_strategy: Optional[str],
    search_placement_search_results: Optional[str],
    search_placement_product_gallery: Optional[str],
    search_placement_dynamic_places: Optional[str],
    include_default: bool,
) -> Optional[dict]:
    """Build the base TextCampaign.BiddingStrategy.Search container."""
    placement_values = {
        "--search-placement-search-results": search_placement_search_results,
        "--search-placement-product-gallery": search_placement_product_gallery,
        "--search-placement-dynamic-places": search_placement_dynamic_places,
    }
    has_placement = any(value is not None for value in placement_values.values())
    if not include_default and search_strategy is None:
        if has_placement:
            raise click.UsageError(
                "TextCampaign search placement flags require --search-strategy"
            )
        return None
    if has_placement and search_strategy is None:
        raise click.UsageError(
            "TextCampaign search placement flags require --search-strategy"
        )

    normalized_strategy = (search_strategy or "HIGHEST_POSITION").upper()
    if normalized_strategy not in TEXT_CAMPAIGN_SEARCH_STRATEGIES:
        raise click.UsageError(
            "--search-strategy for TEXT_CAMPAIGN must be one of "
            f"{', '.join(TEXT_CAMPAIGN_SEARCH_STRATEGIES)}"
        )

    search: dict = {"BiddingStrategyType": normalized_strategy}
    placement_types: dict = {}
    if search_placement_search_results is not None:
        placement_types["SearchResults"] = search_placement_search_results.upper()
    if search_placement_product_gallery is not None:
        placement_types["ProductGallery"] = search_placement_product_gallery.upper()
    if search_placement_dynamic_places is not None:
        placement_types["DynamicPlaces"] = search_placement_dynamic_places.upper()
    if placement_types:
        search["PlacementTypes"] = placement_types
    return search


def build_cpm_banner_bidding_strategy(
    search_strategy: Optional[str],
    network_strategy: Optional[str],
    average_cpm: Optional[int],
    average_cpv: Optional[int],
    spend_limit: Optional[int],
    start_date: Optional[str],
    end_date: Optional[str],
    auto_continue: Optional[str],
    *,
    include_defaults: bool,
) -> Optional[dict]:
    """Build CpmBannerCampaign.BiddingStrategy from typed flags."""
    has_details = any(
        value is not None
        for value in (
            average_cpm,
            average_cpv,
            spend_limit,
            start_date,
            end_date,
            auto_continue,
        )
    )
    if not include_defaults and search_strategy is None and network_strategy is None:
        if has_details:
            raise click.UsageError(
                "CpmBannerCampaign strategy detail flags require " "--network-strategy"
            )
        return None

    normalized_search = (search_strategy or "SERVING_OFF").upper()
    normalized_network = (network_strategy or "MANUAL_CPM").upper()
    if normalized_search not in CPM_BANNER_SEARCH_STRATEGIES:
        raise click.UsageError(
            "--search-strategy for CPM_BANNER_CAMPAIGN must be SERVING_OFF"
        )
    if normalized_network not in CPM_BANNER_NETWORK_STRATEGIES:
        raise click.UsageError(
            "--network-strategy for CPM_BANNER_CAMPAIGN must be one of "
            f"{', '.join(CPM_BANNER_NETWORK_STRATEGIES)}"
        )
    if has_details and network_strategy is None:
        raise click.UsageError(
            "CpmBannerCampaign strategy detail flags require --network-strategy"
        )

    strategy: dict = {}
    if include_defaults or search_strategy is not None:
        strategy["Search"] = {"BiddingStrategyType": normalized_search}

    if include_defaults or network_strategy is not None:
        network: dict = {"BiddingStrategyType": normalized_network}
        weekly_blocks = {
            "WB_MAXIMUM_IMPRESSIONS": ("WbMaximumImpressions", "AverageCpm"),
            "WB_DECREASED_PRICE_FOR_REPEATED_IMPRESSIONS": (
                "WbDecreasedPriceForRepeatedImpressions",
                "AverageCpm",
            ),
            "WB_AVERAGE_CPV": ("WbAverageCpv", "AverageCpv"),
        }
        custom_period_blocks = {
            "CP_MAXIMUM_IMPRESSIONS": ("CpMaximumImpressions", "AverageCpm"),
            "CP_DECREASED_PRICE_FOR_REPEATED_IMPRESSIONS": (
                "CpDecreasedPriceForRepeatedImpressions",
                "AverageCpm",
            ),
            "CP_AVERAGE_CPV": ("CpAverageCpv", "AverageCpv"),
        }
        if normalized_network == "MANUAL_CPM":
            provided = {
                "--average-cpm": average_cpm,
                "--average-cpv": average_cpv,
                "--strategy-spend-limit": spend_limit,
                "--strategy-start-date": start_date,
                "--strategy-end-date": end_date,
                "--strategy-auto-continue": auto_continue,
            }
            invalid = [flag for flag, value in provided.items() if value is not None]
            if invalid:
                raise click.UsageError(
                    "MANUAL_CPM does not accept strategy detail flags: "
                    f"{', '.join(sorted(invalid))}"
                )
        elif normalized_network in weekly_blocks:
            block_name, amount_field = weekly_blocks[normalized_network]
            amount = average_cpv if amount_field == "AverageCpv" else average_cpm
            amount_flag = (
                "--average-cpv" if amount_field == "AverageCpv" else "--average-cpm"
            )
            missing = [
                flag
                for flag, value in (
                    (amount_flag, amount),
                    ("--strategy-spend-limit", spend_limit),
                )
                if value is None
            ]
            if missing:
                raise click.UsageError(
                    f"{normalized_network} requires {', '.join(missing)}"
                )
            invalid = [
                flag
                for flag, value in (
                    (
                        "--average-cpm",
                        average_cpm if amount_field == "AverageCpv" else None,
                    ),
                    (
                        "--average-cpv",
                        average_cpv if amount_field == "AverageCpm" else None,
                    ),
                    ("--strategy-start-date", start_date),
                    ("--strategy-end-date", end_date),
                    ("--strategy-auto-continue", auto_continue),
                )
                if value is not None
            ]
            if invalid:
                raise click.UsageError(
                    f"{normalized_network} does not accept "
                    f"{', '.join(sorted(invalid))}"
                )
            network[block_name] = {
                amount_field: amount,
                "SpendLimit": spend_limit,
            }
        elif normalized_network in custom_period_blocks:
            block_name, amount_field = custom_period_blocks[normalized_network]
            amount = average_cpv if amount_field == "AverageCpv" else average_cpm
            amount_flag = (
                "--average-cpv" if amount_field == "AverageCpv" else "--average-cpm"
            )
            missing = [
                flag
                for flag, value in (
                    (amount_flag, amount),
                    ("--strategy-spend-limit", spend_limit),
                    ("--strategy-start-date", start_date),
                    ("--strategy-end-date", end_date),
                    ("--strategy-auto-continue", auto_continue),
                )
                if value is None
            ]
            if missing:
                raise click.UsageError(
                    f"{normalized_network} requires {', '.join(missing)}"
                )
            invalid = [
                flag
                for flag, value in (
                    (
                        "--average-cpm",
                        average_cpm if amount_field == "AverageCpv" else None,
                    ),
                    (
                        "--average-cpv",
                        average_cpv if amount_field == "AverageCpm" else None,
                    ),
                )
                if value is not None
            ]
            if invalid:
                raise click.UsageError(
                    f"{normalized_network} does not accept "
                    f"{', '.join(sorted(invalid))}"
                )
            assert amount is not None
            assert spend_limit is not None
            assert start_date is not None
            assert end_date is not None
            assert auto_continue is not None
            network[block_name] = {
                amount_field: amount,
                "SpendLimit": spend_limit,
                "StartDate": start_date,
                "EndDate": end_date,
                "AutoContinue": auto_continue.upper(),
            }
        strategy["Network"] = network

    return strategy


def build_mobile_app_search_strategy(
    search_strategy: Optional[str],
    weekly_spend_limit: Optional[int],
    bid_ceiling: Optional[int],
    custom_period_spend_limit: Optional[int],
    custom_period_start_date: Optional[str],
    custom_period_end_date: Optional[str],
    custom_period_auto_continue: Optional[str],
    average_cpc: Optional[int],
    average_cpi: Optional[int],
    clicks_per_week: Optional[int],
    budget_type: Optional[str],
    *,
    include_default: bool,
    is_update: bool,
) -> Optional[dict]:
    """Build MobileAppCampaign.BiddingStrategy.Search from typed flags."""
    detail_values = {
        "--mobile-search-weekly-spend-limit": weekly_spend_limit,
        "--mobile-search-bid-ceiling": bid_ceiling,
        "--mobile-search-custom-period-spend-limit": custom_period_spend_limit,
        "--mobile-search-custom-period-start-date": custom_period_start_date,
        "--mobile-search-custom-period-end-date": custom_period_end_date,
        "--mobile-search-custom-period-auto-continue": custom_period_auto_continue,
        "--mobile-search-average-cpc": average_cpc,
        "--mobile-search-average-cpi": average_cpi,
        "--mobile-search-clicks-per-week": clicks_per_week,
        "--mobile-search-budget-type": budget_type,
    }
    has_details = any(value is not None for value in detail_values.values())
    if not include_default and search_strategy is None:
        if has_details:
            raise click.UsageError(
                "MobileAppCampaign search detail flags require --search-strategy"
            )
        return None
    if has_details and search_strategy is None:
        raise click.UsageError(
            "MobileAppCampaign search detail flags require --search-strategy"
        )

    normalized_strategy = (search_strategy or "HIGHEST_POSITION").upper()
    if normalized_strategy in MOBILE_APP_SEARCH_DISABLED_STRATEGIES:
        raise click.UsageError(
            f"{normalized_strategy} is disabled in the Yandex Direct "
            "Campaigns service"
        )
    if normalized_strategy not in MOBILE_APP_SEARCH_STRATEGIES:
        raise click.UsageError(
            "--search-strategy for MOBILE_APP_CAMPAIGN must be one of "
            f"{', '.join(MOBILE_APP_SEARCH_STRATEGIES)}"
        )

    subtype = MOBILE_APP_SEARCH_STRATEGY_TO_WSDL_SUBTYPE.get(normalized_strategy)
    search: dict = {"BiddingStrategyType": normalized_strategy}
    if subtype is None:
        invalid = [flag for flag, value in detail_values.items() if value is not None]
        if invalid:
            raise click.UsageError(
                f"{normalized_strategy} does not accept mobile search detail flags: "
                f"{', '.join(sorted(invalid))}"
            )
        return search

    custom_period_values = {
        "--mobile-search-custom-period-spend-limit": custom_period_spend_limit,
        "--mobile-search-custom-period-start-date": custom_period_start_date,
        "--mobile-search-custom-period-end-date": custom_period_end_date,
        "--mobile-search-custom-period-auto-continue": custom_period_auto_continue,
    }
    custom_period_flags = [
        flag for flag, value in custom_period_values.items() if value is not None
    ]
    if custom_period_flags and len(custom_period_flags) != len(custom_period_values):
        missing = [
            flag for flag, value in custom_period_values.items() if value is None
        ]
        raise click.UsageError(
            "MobileAppCampaign CustomPeriodBudget requires all custom-period "
            f"flags; missing {', '.join(sorted(missing))}"
        )
    if custom_period_flags and subtype not in MOBILE_APP_SEARCH_CUSTOM_PERIOD_SUBTYPES:
        raise click.UsageError(
            f"{normalized_strategy} does not accept MobileAppCampaign "
            "CustomPeriodBudget flags"
        )
    if weekly_spend_limit is not None and custom_period_flags:
        raise click.UsageError(
            "--mobile-search-weekly-spend-limit cannot be combined with "
            "--mobile-search-custom-period-spend-limit"
        )
    if not is_update:
        required = {
            "WbMaximumClicks": {
                "--mobile-search-weekly-spend-limit or full CustomPeriodBudget": (
                    weekly_spend_limit if not custom_period_flags else 1
                )
            },
            "WbMaximumAppInstalls": {
                "--mobile-search-weekly-spend-limit": weekly_spend_limit
            },
            "AverageCpc": {"--mobile-search-average-cpc": average_cpc},
            "AverageCpi": {"--mobile-search-average-cpi": average_cpi},
            "WeeklyClickPackage": {"--mobile-search-clicks-per-week": clicks_per_week},
            "PayForInstall": {"--mobile-search-average-cpi": average_cpi},
        }[subtype]
        missing = [flag for flag, value in required.items() if value is None]
        if missing:
            raise click.UsageError(
                f"{normalized_strategy} requires {', '.join(sorted(missing))}"
            )

    if budget_type is not None:
        if not is_update:
            raise click.UsageError("--mobile-search-budget-type is update-only")
        if subtype not in MOBILE_APP_SEARCH_BUDGET_TYPE_SUBTYPES:
            raise click.UsageError(
                f"{normalized_strategy} does not accept --mobile-search-budget-type"
            )
        normalized_budget_type = budget_type.upper()
        if normalized_budget_type == "CUSTOM_PERIOD_BUDGET" and not custom_period_flags:
            raise click.UsageError(
                "--mobile-search-budget-type CUSTOM_PERIOD_BUDGET requires "
                "full CustomPeriodBudget flags"
            )
        if normalized_budget_type == "WEEKLY_BUDGET" and weekly_spend_limit is None:
            raise click.UsageError(
                "--mobile-search-budget-type WEEKLY_BUDGET requires "
                "--mobile-search-weekly-spend-limit"
            )
    if (
        subtype == "WeeklyClickPackage"
        and average_cpc is not None
        and bid_ceiling is not None
    ):
        raise click.UsageError(
            "WEEKLY_CLICK_PACKAGE cannot combine --mobile-search-average-cpc "
            "with --mobile-search-bid-ceiling"
        )

    field_support = {
        "--mobile-search-weekly-spend-limit": (
            weekly_spend_limit,
            MOBILE_APP_SEARCH_WEEKLY_SPEND_SUBTYPES,
        ),
        "--mobile-search-bid-ceiling": (
            bid_ceiling,
            MOBILE_APP_SEARCH_BID_CEILING_SUBTYPES,
        ),
        "--mobile-search-average-cpc": (
            average_cpc,
            MOBILE_APP_SEARCH_AVERAGE_CPC_SUBTYPES,
        ),
        "--mobile-search-average-cpi": (
            average_cpi,
            MOBILE_APP_SEARCH_AVERAGE_CPI_SUBTYPES,
        ),
        "--mobile-search-clicks-per-week": (
            clicks_per_week,
            MOBILE_APP_SEARCH_CLICKS_PER_WEEK_SUBTYPES,
        ),
    }
    for flag, (value, supported_subtypes) in field_support.items():
        if value is not None and subtype not in supported_subtypes:
            raise click.UsageError(f"{normalized_strategy} does not accept {flag}")

    block: dict = {}
    if weekly_spend_limit is not None:
        block["WeeklySpendLimit"] = weekly_spend_limit
    if bid_ceiling is not None:
        block["BidCeiling"] = bid_ceiling
    if average_cpc is not None:
        block["AverageCpc"] = average_cpc
    if average_cpi is not None:
        block["AverageCpi"] = average_cpi
    if clicks_per_week is not None:
        block["ClicksPerWeek"] = clicks_per_week
    if custom_period_flags:
        assert custom_period_spend_limit is not None
        assert custom_period_start_date is not None
        assert custom_period_end_date is not None
        assert custom_period_auto_continue is not None
        block["CustomPeriodBudget"] = {
            "SpendLimit": custom_period_spend_limit,
            "StartDate": custom_period_start_date,
            "EndDate": custom_period_end_date,
            "AutoContinue": custom_period_auto_continue.upper(),
        }
    if budget_type is not None:
        normalized_budget_type = budget_type.upper()
        if normalized_budget_type == "CUSTOM_PERIOD_BUDGET":
            block["WeeklySpendLimit"] = None
        elif normalized_budget_type == "WEEKLY_BUDGET":
            block["CustomPeriodBudget"] = None
        block["BudgetType"] = normalized_budget_type
    if block:
        search[subtype] = block
    return search


def build_mobile_app_network_strategy(
    network_strategy: Optional[str],
    weekly_spend_limit: Optional[int],
    bid_ceiling: Optional[int],
    custom_period_spend_limit: Optional[int],
    custom_period_start_date: Optional[str],
    custom_period_end_date: Optional[str],
    custom_period_auto_continue: Optional[str],
    average_cpc: Optional[int],
    average_cpi: Optional[int],
    clicks_per_week: Optional[int],
    limit_percent: Optional[int],
    budget_type: Optional[str],
    *,
    include_default: bool,
    is_update: bool,
) -> Optional[dict]:
    """Build MobileAppCampaign.BiddingStrategy.Network from typed flags."""
    detail_values = {
        "--mobile-network-weekly-spend-limit": weekly_spend_limit,
        "--mobile-network-bid-ceiling": bid_ceiling,
        "--mobile-network-custom-period-spend-limit": custom_period_spend_limit,
        "--mobile-network-custom-period-start-date": custom_period_start_date,
        "--mobile-network-custom-period-end-date": custom_period_end_date,
        "--mobile-network-custom-period-auto-continue": custom_period_auto_continue,
        "--mobile-network-average-cpc": average_cpc,
        "--mobile-network-average-cpi": average_cpi,
        "--mobile-network-clicks-per-week": clicks_per_week,
        "--mobile-network-limit-percent": limit_percent,
        "--mobile-network-budget-type": budget_type,
    }
    has_details = any(value is not None for value in detail_values.values())
    if not include_default and network_strategy is None:
        if has_details:
            raise click.UsageError(
                "MobileAppCampaign network detail flags require --network-strategy"
            )
        return None
    if has_details and network_strategy is None:
        raise click.UsageError(
            "MobileAppCampaign network detail flags require --network-strategy"
        )

    normalized_strategy = (network_strategy or "SERVING_OFF").upper()
    if normalized_strategy not in MOBILE_APP_NETWORK_STRATEGIES:
        raise click.UsageError(
            "--network-strategy for MOBILE_APP_CAMPAIGN must be one of "
            f"{', '.join(MOBILE_APP_NETWORK_STRATEGIES)}"
        )

    subtype = MOBILE_APP_NETWORK_STRATEGY_TO_WSDL_SUBTYPE.get(normalized_strategy)
    network: dict = {"BiddingStrategyType": normalized_strategy}
    if subtype is None:
        invalid = [flag for flag, value in detail_values.items() if value is not None]
        if invalid:
            raise click.UsageError(
                f"{normalized_strategy} does not accept mobile network detail flags: "
                f"{', '.join(sorted(invalid))}"
            )
        return network

    if limit_percent is not None:
        if limit_percent < 10 or limit_percent > 100 or limit_percent % 10 != 0:
            raise click.UsageError(
                "--mobile-network-limit-percent must be a multiple of 10 "
                "from 10 to 100"
            )
        if subtype != "NetworkDefault":
            raise click.UsageError(
                f"{normalized_strategy} does not accept "
                "--mobile-network-limit-percent"
            )

    custom_period_values = {
        "--mobile-network-custom-period-spend-limit": custom_period_spend_limit,
        "--mobile-network-custom-period-start-date": custom_period_start_date,
        "--mobile-network-custom-period-end-date": custom_period_end_date,
        "--mobile-network-custom-period-auto-continue": custom_period_auto_continue,
    }
    custom_period_flags = [
        flag for flag, value in custom_period_values.items() if value is not None
    ]
    if custom_period_flags and len(custom_period_flags) != len(custom_period_values):
        missing = [
            flag for flag, value in custom_period_values.items() if value is None
        ]
        raise click.UsageError(
            "MobileAppCampaign CustomPeriodBudget requires all custom-period "
            f"flags; missing {', '.join(sorted(missing))}"
        )
    if custom_period_flags and subtype not in MOBILE_APP_NETWORK_CUSTOM_PERIOD_SUBTYPES:
        raise click.UsageError(
            f"{normalized_strategy} does not accept MobileAppCampaign "
            "CustomPeriodBudget flags"
        )
    if weekly_spend_limit is not None and custom_period_flags:
        raise click.UsageError(
            "--mobile-network-weekly-spend-limit cannot be combined with "
            "--mobile-network-custom-period-spend-limit"
        )
    if not is_update:
        required = {
            "NetworkDefault": {},
            "WbMaximumClicks": {
                "--mobile-network-weekly-spend-limit or full CustomPeriodBudget": (
                    weekly_spend_limit if not custom_period_flags else 1
                )
            },
            "WbMaximumAppInstalls": {
                "--mobile-network-weekly-spend-limit": weekly_spend_limit
            },
            "AverageCpc": {"--mobile-network-average-cpc": average_cpc},
            "AverageCpi": {"--mobile-network-average-cpi": average_cpi},
            "WeeklyClickPackage": {"--mobile-network-clicks-per-week": clicks_per_week},
            "PayForInstall": {"--mobile-network-average-cpi": average_cpi},
        }[subtype]
        missing = [flag for flag, value in required.items() if value is None]
        if missing:
            raise click.UsageError(
                f"{normalized_strategy} requires {', '.join(sorted(missing))}"
            )

    if budget_type is not None:
        if not is_update:
            raise click.UsageError("--mobile-network-budget-type is update-only")
        if subtype not in MOBILE_APP_NETWORK_BUDGET_TYPE_SUBTYPES:
            raise click.UsageError(
                f"{normalized_strategy} does not accept --mobile-network-budget-type"
            )
        normalized_budget_type = budget_type.upper()
        if normalized_budget_type == "CUSTOM_PERIOD_BUDGET" and not custom_period_flags:
            raise click.UsageError(
                "--mobile-network-budget-type CUSTOM_PERIOD_BUDGET requires "
                "full CustomPeriodBudget flags"
            )
        if normalized_budget_type == "WEEKLY_BUDGET" and weekly_spend_limit is None:
            raise click.UsageError(
                "--mobile-network-budget-type WEEKLY_BUDGET requires "
                "--mobile-network-weekly-spend-limit"
            )
    if (
        subtype == "WeeklyClickPackage"
        and average_cpc is not None
        and bid_ceiling is not None
    ):
        raise click.UsageError(
            "WEEKLY_CLICK_PACKAGE cannot combine --mobile-network-average-cpc "
            "with --mobile-network-bid-ceiling"
        )

    field_support = {
        "--mobile-network-weekly-spend-limit": (
            weekly_spend_limit,
            MOBILE_APP_NETWORK_WEEKLY_SPEND_SUBTYPES,
        ),
        "--mobile-network-bid-ceiling": (
            bid_ceiling,
            MOBILE_APP_NETWORK_BID_CEILING_SUBTYPES,
        ),
        "--mobile-network-average-cpc": (
            average_cpc,
            MOBILE_APP_NETWORK_AVERAGE_CPC_SUBTYPES,
        ),
        "--mobile-network-average-cpi": (
            average_cpi,
            MOBILE_APP_NETWORK_AVERAGE_CPI_SUBTYPES,
        ),
        "--mobile-network-clicks-per-week": (
            clicks_per_week,
            MOBILE_APP_NETWORK_CLICKS_PER_WEEK_SUBTYPES,
        ),
    }
    for flag, (value, supported_subtypes) in field_support.items():
        if value is not None and subtype not in supported_subtypes:
            raise click.UsageError(f"{normalized_strategy} does not accept {flag}")

    block: dict = {}
    if limit_percent is not None:
        block["LimitPercent"] = limit_percent
    if weekly_spend_limit is not None:
        block["WeeklySpendLimit"] = weekly_spend_limit
    if bid_ceiling is not None:
        block["BidCeiling"] = bid_ceiling
    if average_cpc is not None:
        block["AverageCpc"] = average_cpc
    if average_cpi is not None:
        block["AverageCpi"] = average_cpi
    if clicks_per_week is not None:
        block["ClicksPerWeek"] = clicks_per_week
    if custom_period_flags:
        assert custom_period_spend_limit is not None
        assert custom_period_start_date is not None
        assert custom_period_end_date is not None
        assert custom_period_auto_continue is not None
        block["CustomPeriodBudget"] = {
            "SpendLimit": custom_period_spend_limit,
            "StartDate": custom_period_start_date,
            "EndDate": custom_period_end_date,
            "AutoContinue": custom_period_auto_continue.upper(),
        }
    if budget_type is not None:
        normalized_budget_type = budget_type.upper()
        if normalized_budget_type == "CUSTOM_PERIOD_BUDGET":
            block["WeeklySpendLimit"] = None
        elif normalized_budget_type == "WEEKLY_BUDGET":
            block["CustomPeriodBudget"] = None
        block["BudgetType"] = normalized_budget_type
    if block:
        network[subtype] = block
    return network


_TEXT_CAMPAIGN_SEARCH_BUDGET_TYPES = ["WEEKLY_BUDGET", "CUSTOM_PERIOD_BUDGET"]


# Full WSDL mapping: TextCampaignSearchStrategyTypeEnum value →
# WSDL subtype field name in ``TextCampaignSearchStrategyAdd`` (mirrors
# ``TextCampaignStrategyAddBase``). Strategies without a subtype block
# (HIGHEST_POSITION, IMPRESSIONS_BELOW_SEARCH, SERVING_OFF, UNKNOWN) are
# absent on purpose — adding them would emit fields the WSDL rejects.
_TEXT_CAMPAIGN_SEARCH_STRATEGY_TO_WSDL_SUBTYPE: Dict[str, str] = {
    "WB_MAXIMUM_CLICKS": "WbMaximumClicks",
    "WB_MAXIMUM_CONVERSION_RATE": "WbMaximumConversionRate",
    "AVERAGE_CPC": "AverageCpc",
    "AVERAGE_CPA": "AverageCpa",
    "PAY_FOR_CONVERSION": "PayForConversion",
    "WEEKLY_CLICK_PACKAGE": "WeeklyClickPackage",
    "AVERAGE_ROI": "AverageRoi",
    "AVERAGE_CRR": "AverageCrr",
    "PAY_FOR_CONVERSION_CRR": "PayForConversionCrr",
    "AVERAGE_CPA_MULTIPLE_GOALS": "AverageCpaMultipleGoals",
    "PAY_FOR_CONVERSION_MULTIPLE_GOALS": "PayForConversionMultipleGoals",
    "MAX_PROFIT": "MaxProfit",
}

# Per-subtype field support tables. Source: WSDL Strategy*Add types in
# ``tests/wsdl_cache/campaigns.xml`` (lines 1333-1509 / 1581-1608).
# Each entry lists the subtypes whose WSDL declares that field.
_TEXT_SEARCH_SUPPORTS_WEEKLY_SPEND_LIMIT = {
    "WbMaximumClicks",
    "WbMaximumConversionRate",
    "AverageCpc",
    "AverageCpa",
    "PayForConversion",
    "AverageRoi",
    "AverageCrr",
    "PayForConversionCrr",
    "AverageCpaMultipleGoals",
    "PayForConversionMultipleGoals",
    "MaxProfit",
}
_TEXT_SEARCH_SUPPORTS_CUSTOM_PERIOD_BUDGET = {
    "WbMaximumClicks",
    "WbMaximumConversionRate",
    "AverageCpc",
    "AverageCpa",
    "PayForConversion",
    "AverageRoi",
    "AverageCrr",
    "PayForConversionCrr",
    "AverageCpaMultipleGoals",
    "PayForConversionMultipleGoals",
    "MaxProfit",
}
_TEXT_SEARCH_SUPPORTS_BID_CEILING = {
    "WbMaximumClicks",
    "WbMaximumConversionRate",
    "AverageCpa",
    "AverageRoi",
    "AverageCpaMultipleGoals",
    "WeeklyClickPackage",
}
_TEXT_SEARCH_SUPPORTS_AVERAGE_CPC = {
    "AverageCpc",  # required
    "WeeklyClickPackage",  # optional
}
_TEXT_SEARCH_SUPPORTS_AVERAGE_CPA = {"AverageCpa"}
_TEXT_SEARCH_SUPPORTS_PAY_CPA = {"PayForConversion"}  # WSDL field name is "Cpa"
_TEXT_SEARCH_SUPPORTS_GOAL_ID = {
    "WbMaximumConversionRate",
    "AverageCpa",
    "PayForConversion",
    "AverageRoi",
    "AverageCrr",
    "PayForConversionCrr",
}
_TEXT_SEARCH_SUPPORTS_CRR = {"AverageCrr", "PayForConversionCrr"}
_TEXT_SEARCH_SUPPORTS_CLICKS_PER_WEEK = {"WeeklyClickPackage"}
_TEXT_SEARCH_SUPPORTS_RESERVE_RETURN = {"AverageRoi"}
_TEXT_SEARCH_SUPPORTS_ROI_COEF = {"AverageRoi"}
_TEXT_SEARCH_SUPPORTS_PROFITABILITY = {"AverageRoi"}
_TEXT_SEARCH_SUPPORTS_EXPLORATION_BUDGET = {
    "AverageCpa",
    "AverageRoi",
    "AverageCrr",
    "AverageCpaMultipleGoals",
    "MaxProfit",
}
# Per official Yandex update-text-campaign docs ``BudgetType`` is
# declared only on the listed subtypes; ``WbMaximumClicks``,
# ``WbMaximumConversionRate``, ``AverageCpaMultipleGoals`` and
# ``WeeklyClickPackage`` do NOT carry it and the CLI must reject the
# flag for those — sending it would emit an undocumented payload.
_TEXT_SEARCH_SUPPORTS_BUDGET_TYPE = {
    "AverageCpc",
    "AverageCpa",
    "PayForConversion",
    "AverageRoi",
    "AverageCrr",
    "PayForConversionCrr",
    "PayForConversionMultipleGoals",
    "MaxProfit",
}
# Per official Yandex Direct docs
# (https://yandex.com/dev/direct/doc/en/campaigns/add-text-campaign):
# ``PriorityGoals`` is required when ``BiddingStrategyType`` is
# ``AVERAGE_CPA_MULTIPLE_GOALS``, ``PAY_FOR_CONVERSION_MULTIPLE_GOALS`` or
# ``MAX_PROFIT``. WSDL declares ``PriorityGoals`` as a sibling field on
# ``TextCampaignAddItem`` (minOccurs=0), so the requirement is a
# documented-API constraint enforced here on the CLI.
_TEXT_SEARCH_REQUIRES_PRIORITY_GOALS = {
    "AverageCpaMultipleGoals",
    "PayForConversionMultipleGoals",
    "MaxProfit",
}
# Strategies that allow ``PriorityGoals`` even though it is not strictly
# required. The docs additionally accept it for ``AverageCrr`` and
# ``PayForConversionCrr`` (used together with
# ``IsMetrikaSourceOfValue``), but we keep the CLI strict on the
# required set for now — the supported set is the same as the required
# set in this PR.
_TEXT_SEARCH_ACCEPTS_PRIORITY_GOALS = _TEXT_SEARCH_REQUIRES_PRIORITY_GOALS

# WSDL ``minOccurs=1`` fields per Strategy*Add subtype for TextCampaign
# Search. Maps subtype → {WSDL field name → CLI option string}.
# Used to fail-fast at the CLI when the user picks the strategy but
# forgets a required typed flag (mirrors ``_STRATEGY_REQUIRED_TYPED_FLAGS``
# for legacy CPA flags).
_TEXT_SEARCH_REQUIRED_TYPED_FLAGS: Dict[str, Dict[str, str]] = {
    "AverageCpc": {"AverageCpc": "--text-search-average-cpc"},
    "AverageCpa": {"AverageCpa": "--average-cpa", "GoalId": "--goal-id"},
    "PayForConversion": {"Cpa": "--text-search-pay-cpa", "GoalId": "--goal-id"},
    # Per official Yandex docs WeeklySpendLimit is required for the
    # ``Wb*`` strategies even though WSDL marks the underlying
    # ``StrategyWeeklyBudgetAddBase`` field minOccurs=0. The runtime
    # check accepts either ``--text-search-weekly-spend-limit`` or a
    # full ``CustomPeriodBudget`` (placed as the alternate budget slice).
    "WbMaximumClicks": {
        "WeeklySpendLimit": (
            "--text-search-weekly-spend-limit or full CustomPeriodBudget"
        ),
    },
    "WbMaximumConversionRate": {
        "GoalId": "--goal-id",
        "WeeklySpendLimit": (
            "--text-search-weekly-spend-limit or full CustomPeriodBudget"
        ),
    },
    "WeeklyClickPackage": {"ClicksPerWeek": "--text-search-clicks-per-week"},
    "AverageRoi": {
        "ReserveReturn": "--text-search-reserve-return",
        "RoiCoef": "--text-search-roi-coef",
        "GoalId": "--goal-id",
    },
    "AverageCrr": {"Crr": "--crr", "GoalId": "--goal-id"},
    "PayForConversionCrr": {"Crr": "--crr", "GoalId": "--goal-id"},
    "AverageCpaMultipleGoals": {"PriorityGoals": "--priority-goals"},
    "PayForConversionMultipleGoals": {"PriorityGoals": "--priority-goals"},
    # Per official docs MAX_PROFIT requires PriorityGoals with the
    # target profit per conversion as the ``Value``.
    "MaxProfit": {"PriorityGoals": "--priority-goals"},
}

# Subtypes that require at least N priority goals per official docs.
_TEXT_SEARCH_MIN_PRIORITY_GOALS: Dict[str, int] = {
    "AverageCpaMultipleGoals": 2,
    "PayForConversionMultipleGoals": 2,
}

# On update, required-typed-flag enforcement is narrower: only fields
# that are conceptually required to define the NEW strategy must be
# supplied when ``--search-strategy`` is being switched. Fields that the
# campaign may already carry (e.g. WeeklySpendLimit on Wb* — docs require
# it on add but the update WSDL keeps it minOccurs=0) are intentionally
# omitted so partial updates remain legitimate.
_TEXT_SEARCH_REQUIRED_TYPED_FLAGS_UPDATE: Dict[str, Dict[str, str]] = {
    "AverageCpc": {"AverageCpc": "--text-search-average-cpc"},
    "AverageCpa": {"AverageCpa": "--average-cpa", "GoalId": "--goal-id"},
    "PayForConversion": {"Cpa": "--text-search-pay-cpa", "GoalId": "--goal-id"},
    "WbMaximumConversionRate": {"GoalId": "--goal-id"},
    "WeeklyClickPackage": {"ClicksPerWeek": "--text-search-clicks-per-week"},
    "AverageRoi": {
        "ReserveReturn": "--text-search-reserve-return",
        "RoiCoef": "--text-search-roi-coef",
        "GoalId": "--goal-id",
    },
    "AverageCrr": {"Crr": "--crr", "GoalId": "--goal-id"},
    "PayForConversionCrr": {"Crr": "--crr", "GoalId": "--goal-id"},
    "AverageCpaMultipleGoals": {"PriorityGoals": "--priority-goals"},
    "PayForConversionMultipleGoals": {"PriorityGoals": "--priority-goals"},
    "MaxProfit": {"PriorityGoals": "--priority-goals"},
    # ``WbMaximumClicks`` intentionally omitted: docs declare every
    # field optional on update so a partial patch is legitimate.
}


def _build_text_search_custom_period_budget(
    spend_limit: Optional[int],
    start_date: Optional[str],
    end_date: Optional[str],
    auto_continue: Optional[str],
) -> Optional[dict]:
    """Build a CustomPeriodBudget block from the four typed flags.

    All four flags must be provided together (WSDL minOccurs=1 each);
    returns ``None`` when none are provided.
    """
    values = {
        "--text-search-custom-period-spend-limit": spend_limit,
        "--text-search-custom-period-start-date": start_date,
        "--text-search-custom-period-end-date": end_date,
        "--text-search-custom-period-auto-continue": auto_continue,
    }
    provided = [flag for flag, value in values.items() if value is not None]
    if not provided:
        return None
    missing = [flag for flag, value in values.items() if value is None]
    if missing:
        raise click.UsageError(
            "TextCampaign CustomPeriodBudget requires all four custom-period "
            f"flags; missing {', '.join(sorted(missing))}"
        )
    assert spend_limit is not None
    assert start_date is not None
    assert end_date is not None
    assert auto_continue is not None
    return {
        "SpendLimit": spend_limit,
        "StartDate": start_date,
        "EndDate": end_date,
        "AutoContinue": auto_continue.upper(),
    }


def _build_text_search_exploration_budget(
    min_budget: Optional[int],
    is_custom: Optional[str],
) -> Optional[dict]:
    """Build an ExplorationBudget block from the two typed flags.

    Both fields are WSDL minOccurs=1; returns ``None`` when none are
    provided. Per official Yandex docs only ``YES`` is accepted for
    ``IsMinimumExplorationBudgetCustom`` — passing ``NO`` makes the API
    raise an error, so the CLI rejects it up-front.
    """
    values = {
        "--text-search-exploration-min-budget": min_budget,
        "--text-search-exploration-is-custom": is_custom,
    }
    provided = [flag for flag, value in values.items() if value is not None]
    if not provided:
        return None
    missing = [flag for flag, value in values.items() if value is None]
    if missing:
        raise click.UsageError(
            "TextCampaign ExplorationBudget requires both ExplorationBudget "
            f"flags; missing {', '.join(sorted(missing))}"
        )
    assert min_budget is not None
    assert is_custom is not None
    normalized_is_custom = is_custom.upper()
    if normalized_is_custom != "YES":
        raise click.UsageError(
            "--text-search-exploration-is-custom must be YES; the Yandex "
            "Direct API rejects NO for IsMinimumExplorationBudgetCustom"
        )
    return {
        "MinimumExplorationBudget": min_budget,
        "IsMinimumExplorationBudgetCustom": normalized_is_custom,
    }


def build_text_campaign_search_strategy(
    *,
    search_strategy: Optional[str],
    search_placement_search_results: Optional[str],
    search_placement_product_gallery: Optional[str],
    search_placement_dynamic_places: Optional[str],
    goal_id: Optional[int],
    average_cpa: Optional[int],
    crr: Optional[int],
    bid_ceiling: Optional[int],
    weekly_spend_limit: Optional[int],
    custom_period_spend_limit: Optional[int],
    custom_period_start_date: Optional[str],
    custom_period_end_date: Optional[str],
    custom_period_auto_continue: Optional[str],
    budget_type: Optional[str],
    average_cpc: Optional[int],
    pay_cpa: Optional[int],
    clicks_per_week: Optional[int],
    reserve_return: Optional[int],
    roi_coef: Optional[int],
    profitability: Optional[int],
    exploration_min_budget: Optional[int],
    exploration_is_custom: Optional[str],
    priority_goals_items: Optional[List[dict]],
    sub_campaign_block: dict,
    include_default: bool,
    is_update: bool,
) -> Optional[dict]:
    """Build the full ``TextCampaign.BiddingStrategy.Search`` payload.

    Covers all 12 strategy families declared in WSDL
    ``TextCampaignStrategyAddBase`` (issue #361). On the legacy three
    strategies (HIGHEST_POSITION / IMPRESSIONS_BELOW_SEARCH / SERVING_OFF)
    no subtype block is emitted — WSDL declares the container as
    ``BiddingStrategyType + PlacementTypes`` only for those.

    Also places ``PriorityGoals`` onto ``sub_campaign_block`` for
    *_MULTIPLE_GOALS strategies (WSDL ``TextCampaignAddItem.PriorityGoals``
    is a sibling of ``BiddingStrategy``, not nested inside it).
    """
    typed_detail_values = {
        "--text-search-weekly-spend-limit": weekly_spend_limit,
        "--text-search-custom-period-spend-limit": custom_period_spend_limit,
        "--text-search-custom-period-start-date": custom_period_start_date,
        "--text-search-custom-period-end-date": custom_period_end_date,
        "--text-search-custom-period-auto-continue": custom_period_auto_continue,
        "--text-search-budget-type": budget_type,
        "--text-search-average-cpc": average_cpc,
        "--text-search-pay-cpa": pay_cpa,
        "--text-search-clicks-per-week": clicks_per_week,
        "--text-search-reserve-return": reserve_return,
        "--text-search-roi-coef": roi_coef,
        "--text-search-profitability": profitability,
        "--text-search-exploration-min-budget": exploration_min_budget,
        "--text-search-exploration-is-custom": exploration_is_custom,
        "--bid-ceiling": bid_ceiling,
        "--average-cpa": average_cpa,
        "--crr": crr,
        "--goal-id": goal_id,
    }
    has_detail_flags = any(value is not None for value in typed_detail_values.values())

    # Reuse the base container builder for placement+strategy-type+enum
    # validation. ``include_default=False`` on update means we return
    # ``None`` if there is nothing to update.
    base_search = build_text_campaign_search_base(
        search_strategy=search_strategy,
        search_placement_search_results=search_placement_search_results,
        search_placement_product_gallery=search_placement_product_gallery,
        search_placement_dynamic_places=search_placement_dynamic_places,
        include_default=include_default,
    )

    # The base might be ``None`` on update when neither strategy nor
    # placement flags are provided. In that case we still must guard
    # against silent data loss from detail-only invocations.
    # ``priority_goals_items`` is intentionally NOT considered here on
    # update: PriorityGoalsUpdateSetting is a separate sibling-field
    # update path placed directly on the parent sub_campaign_block by
    # the caller — it does not require touching BiddingStrategy.
    if base_search is None:
        if has_detail_flags:
            raise click.UsageError(
                "TextCampaign search strategy detail flags require " "--search-strategy"
            )
        if priority_goals_items is not None and not is_update:
            raise click.UsageError(
                "TextCampaign search strategy detail flags require " "--search-strategy"
            )
        return None

    normalized_strategy = base_search["BiddingStrategyType"]
    subtype = _TEXT_CAMPAIGN_SEARCH_STRATEGY_TO_WSDL_SUBTYPE.get(normalized_strategy)

    # Legacy three (HIGHEST_POSITION / IMPRESSIONS_BELOW_SEARCH / SERVING_OFF)
    # do not carry any subtype block. Reject silent data loss.
    if subtype is None:
        provided = [
            flag for flag, value in typed_detail_values.items() if value is not None
        ]
        if provided:
            # Distinguish CPA-shaped legacy flags from the new text-search-*
            # flags so historical error strings ("CPA-shaped") stay stable
            # for users that grep error messages.
            legacy_cpa_flags = {
                "--average-cpa",
                "--goal-id",
                "--crr",
                "--bid-ceiling",
            }
            legacy_provided = [flag for flag in provided if flag in legacy_cpa_flags]
            if legacy_provided and not any(
                flag for flag in provided if flag not in legacy_cpa_flags
            ):
                raise click.UsageError(
                    f"{', '.join(sorted(legacy_provided))} are only "
                    "valid with a CPA-shaped --search-strategy or "
                    "--network-strategy (e.g. AVERAGE_CPA, "
                    "PAY_FOR_CONVERSION_CRR, AVERAGE_CPA_MULTIPLE_GOALS); "
                    f"got --search-strategy={search_strategy!r}"
                )
            raise click.UsageError(
                f"{normalized_strategy} does not accept TextCampaign search "
                f"strategy detail flags: {', '.join(sorted(provided))}"
            )
        if priority_goals_items is not None:
            raise click.UsageError(
                f"{normalized_strategy} does not accept --priority-goals"
            )
        return base_search

    # Per-subtype "supported field" enforcement (silent data loss invariant
    # #2 in test_wsdl_parity_gate). Each flag whose value is not None must
    # belong to the WSDL Strategy*Add type for the chosen subtype.
    field_support = {
        "--text-search-weekly-spend-limit": (
            weekly_spend_limit,
            _TEXT_SEARCH_SUPPORTS_WEEKLY_SPEND_LIMIT,
        ),
        "--text-search-budget-type": (
            budget_type,
            _TEXT_SEARCH_SUPPORTS_BUDGET_TYPE,
        ),
        "--text-search-average-cpc": (
            average_cpc,
            _TEXT_SEARCH_SUPPORTS_AVERAGE_CPC,
        ),
        "--text-search-pay-cpa": (
            pay_cpa,
            _TEXT_SEARCH_SUPPORTS_PAY_CPA,
        ),
        "--text-search-clicks-per-week": (
            clicks_per_week,
            _TEXT_SEARCH_SUPPORTS_CLICKS_PER_WEEK,
        ),
        "--text-search-reserve-return": (
            reserve_return,
            _TEXT_SEARCH_SUPPORTS_RESERVE_RETURN,
        ),
        "--text-search-roi-coef": (
            roi_coef,
            _TEXT_SEARCH_SUPPORTS_ROI_COEF,
        ),
        "--text-search-profitability": (
            profitability,
            _TEXT_SEARCH_SUPPORTS_PROFITABILITY,
        ),
        "--bid-ceiling": (bid_ceiling, _TEXT_SEARCH_SUPPORTS_BID_CEILING),
        "--average-cpa": (average_cpa, _TEXT_SEARCH_SUPPORTS_AVERAGE_CPA),
        "--crr": (crr, _TEXT_SEARCH_SUPPORTS_CRR),
        "--goal-id": (goal_id, _TEXT_SEARCH_SUPPORTS_GOAL_ID),
    }
    for flag, (value, supported) in field_support.items():
        if value is not None and subtype not in supported:
            raise click.UsageError(
                f"{flag} is not valid for TextCampaign Search strategy "
                f"{normalized_strategy} (subtype Strategy{subtype}Add); "
                f"WSDL field is declared only on {sorted(supported)}"
            )

    # ReserveReturn doc constraint: 0-100 percentage as a multiple of 10.
    if reserve_return is not None and reserve_return % 10 != 0:
        raise click.UsageError(
            "--text-search-reserve-return must be a multiple of 10 "
            "(0-100), per Yandex Direct API docs"
        )

    # CustomPeriodBudget and ExplorationBudget are container-level checks
    # — all-or-none. Build the nested dicts (or None) up-front and then
    # validate they belong to the chosen subtype.
    custom_period = _build_text_search_custom_period_budget(
        custom_period_spend_limit,
        custom_period_start_date,
        custom_period_end_date,
        custom_period_auto_continue,
    )
    if (
        custom_period is not None
        and subtype not in _TEXT_SEARCH_SUPPORTS_CUSTOM_PERIOD_BUDGET
    ):
        raise click.UsageError(
            f"TextCampaign CustomPeriodBudget is not valid for {normalized_strategy}"
        )
    exploration_budget = _build_text_search_exploration_budget(
        exploration_min_budget,
        exploration_is_custom,
    )
    if (
        exploration_budget is not None
        and subtype not in _TEXT_SEARCH_SUPPORTS_EXPLORATION_BUDGET
    ):
        raise click.UsageError(
            f"TextCampaign ExplorationBudget is not valid for {normalized_strategy}"
        )

    # WeeklySpendLimit + CustomPeriodBudget conflict per Yandex docs:
    # the same subtype can carry only one budget slice.
    if weekly_spend_limit is not None and custom_period is not None:
        raise click.UsageError(
            "--text-search-weekly-spend-limit cannot be combined with "
            "--text-search-custom-period-spend-limit"
        )

    # BudgetType is an update-only switch; on add the budget slice is
    # implied by which of WeeklySpendLimit / CustomPeriodBudget is set.
    if budget_type is not None:
        if not is_update:
            raise click.UsageError("--text-search-budget-type is update-only")
        normalized_budget_type = budget_type.upper()
        if normalized_budget_type not in _TEXT_CAMPAIGN_SEARCH_BUDGET_TYPES:
            raise click.UsageError(
                "--text-search-budget-type must be one of "
                f"{', '.join(_TEXT_CAMPAIGN_SEARCH_BUDGET_TYPES)}"
            )
        if normalized_budget_type == "CUSTOM_PERIOD_BUDGET" and custom_period is None:
            raise click.UsageError(
                "--text-search-budget-type CUSTOM_PERIOD_BUDGET requires the "
                "full CustomPeriodBudget flag set"
            )
        if normalized_budget_type == "WEEKLY_BUDGET" and weekly_spend_limit is None:
            raise click.UsageError(
                "--text-search-budget-type WEEKLY_BUDGET requires "
                "--text-search-weekly-spend-limit"
            )

    # WeeklyClickPackage edge: WSDL declares AverageCpc + BidCeiling as
    # mutually exclusive in practice; mirror MobileApp WeeklyClickPackage.
    if (
        subtype == "WeeklyClickPackage"
        and average_cpc is not None
        and bid_ceiling is not None
    ):
        raise click.UsageError(
            "WEEKLY_CLICK_PACKAGE cannot combine --text-search-average-cpc "
            "with --bid-ceiling"
        )

    # PriorityGoals scope check. On add we also place PriorityGoals onto
    # the parent sub-campaign block (WSDL ``TextCampaignAddItem.PriorityGoals``
    # is a sibling of BiddingStrategy, NOT nested inside it). On update
    # the caller has already placed PriorityGoals via the dedicated
    # ``PriorityGoalsUpdateSetting`` shape (with ``Operation: SET``) so
    # we only validate the strategy/subtype combination here.
    #
    # KNOWN ISSUE (#387): ``parse_priority_goals_spec`` forwards
    # ``Value`` as a raw integer. Per Yandex docs ``Value`` is
    # advertiser currency × 1,000,000; the cross-cutting fix is
    # tracked in issue #387 and intentionally NOT bundled into #361.
    if priority_goals_items is not None:
        if subtype not in _TEXT_SEARCH_REQUIRES_PRIORITY_GOALS:
            raise click.UsageError(
                "--priority-goals is only valid with "
                "AVERAGE_CPA_MULTIPLE_GOALS / "
                "PAY_FOR_CONVERSION_MULTIPLE_GOALS / MAX_PROFIT strategies; "
                f"got --search-strategy={search_strategy!r}"
            )
        # Per official Yandex docs *_MULTIPLE_GOALS subtypes require
        # at least two priority goals; reject one-goal payloads up-front.
        min_required = _TEXT_SEARCH_MIN_PRIORITY_GOALS.get(subtype)
        if min_required is not None and len(priority_goals_items) < min_required:
            raise click.UsageError(
                f"--priority-goals requires at least {min_required} entries "
                f"for {search_strategy} per Yandex Direct API docs"
            )
        if not is_update:
            sub_campaign_block["PriorityGoals"] = {"Items": priority_goals_items}

    # WSDL minOccurs=1 fields — fail-fast on add. On update the API
    # tolerates partial blocks (matches the legacy CPA strategy behavior
    # for AVERAGE_CPA on update, see existing dry-run fixtures).
    # For Wb* strategies, CustomPeriodBudget acts as the alternative
    # budget slice that also satisfies the WeeklySpendLimit-required
    # constraint from the Yandex docs. Treating ``custom_period`` as
    # equivalent for the required-flag check keeps both budget paths
    # reachable for ``WB_MAXIMUM_CLICKS`` / ``WB_MAXIMUM_CONVERSION_RATE``.
    weekly_or_custom_period = (
        weekly_spend_limit
        if weekly_spend_limit is not None
        else (1 if custom_period is not None else None)
    )
    provided_lookup = {
        "AverageCpc": average_cpc,
        "AverageCpa": average_cpa,
        "Cpa": pay_cpa,
        "GoalId": goal_id,
        "Crr": crr,
        "ClicksPerWeek": clicks_per_week,
        "ReserveReturn": reserve_return,
        "RoiCoef": roi_coef,
        "PriorityGoals": priority_goals_items,
        "WeeklySpendLimit": weekly_or_custom_period,
    }
    if not is_update:
        required = _TEXT_SEARCH_REQUIRED_TYPED_FLAGS.get(subtype, {})
        missing = [
            flag
            for wsdl_field, flag in required.items()
            if provided_lookup.get(wsdl_field) is None
        ]
        if missing:
            raise click.UsageError(
                f"Search strategy {subtype} requires {', '.join(sorted(missing))} "
                f"(per Yandex Direct API docs)"
            )
    else:
        # On update we let users patch individual subtype fields, but
        # when the user is switching the strategy type
        # (``--search-strategy`` is explicitly provided) every
        # *conceptually-required* field for the new subtype must be
        # supplied (Crr/GoalId for CRR strategies, PriorityGoals for
        # MAX_PROFIT and *_MULTIPLE_GOALS, etc.). Fields that the
        # campaign may already carry — e.g. ``WeeklySpendLimit`` on
        # ``WbMaximumClicks`` — are NOT re-required, matching the
        # update WSDL ``minOccurs=0`` and the official update docs.
        if search_strategy is not None:
            required = _TEXT_SEARCH_REQUIRED_TYPED_FLAGS_UPDATE.get(subtype, {})
            missing = [
                flag
                for wsdl_field, flag in required.items()
                if provided_lookup.get(wsdl_field) is None
            ]
            if missing:
                raise click.UsageError(
                    f"Search strategy {subtype} requires "
                    f"{', '.join(sorted(missing))} when switching "
                    "--search-strategy on update (per Yandex Direct "
                    "API docs)"
                )

    # Build the WSDL Strategy*Add block. Element order in the dict
    # follows WSDL sequence order for readability — JSON-RPC does not
    # require ordering, but matching makes diffs cleaner.
    block: dict = {}
    if subtype == "AverageCpc":
        if average_cpc is not None:
            block["AverageCpc"] = average_cpc
    elif subtype == "AverageCpa":
        if average_cpa is not None:
            block["AverageCpa"] = average_cpa
        if goal_id is not None:
            block["GoalId"] = goal_id
    elif subtype == "PayForConversion":
        if pay_cpa is not None:
            block["Cpa"] = pay_cpa
        if goal_id is not None:
            block["GoalId"] = goal_id
    elif subtype == "WbMaximumConversionRate":
        if goal_id is not None:
            block["GoalId"] = goal_id
    elif subtype == "WeeklyClickPackage":
        if clicks_per_week is not None:
            block["ClicksPerWeek"] = clicks_per_week
        if average_cpc is not None:
            block["AverageCpc"] = average_cpc
    elif subtype == "AverageRoi":
        if reserve_return is not None:
            block["ReserveReturn"] = reserve_return
        if roi_coef is not None:
            block["RoiCoef"] = roi_coef
        if goal_id is not None:
            block["GoalId"] = goal_id
        if profitability is not None:
            block["Profitability"] = profitability
    elif subtype in {"AverageCrr", "PayForConversionCrr"}:
        if crr is not None:
            block["Crr"] = crr
        if goal_id is not None:
            block["GoalId"] = goal_id
    # WbMaximumClicks / MaxProfit / *MultipleGoals have only optional
    # fields below — they share the WeeklySpendLimit/BidCeiling/etc.
    # tail handled next.

    if weekly_spend_limit is not None:
        block["WeeklySpendLimit"] = weekly_spend_limit
    if custom_period is not None:
        block["CustomPeriodBudget"] = custom_period
    if bid_ceiling is not None:
        block["BidCeiling"] = bid_ceiling
    if exploration_budget is not None:
        block["ExplorationBudget"] = exploration_budget
    if budget_type is not None:
        normalized_budget_type = budget_type.upper()
        # Mirror MobileApp builder convention: clearing the other slice
        # signals an explicit budget-type switch on update.
        if normalized_budget_type == "CUSTOM_PERIOD_BUDGET":
            block["WeeklySpendLimit"] = None
        elif normalized_budget_type == "WEEKLY_BUDGET":
            block["CustomPeriodBudget"] = None
        block["BudgetType"] = normalized_budget_type

    # *_MULTIPLE_GOALS subtypes must emit the container even when no
    # numeric fields are set, because PriorityGoals lives on the parent
    # ``sub_campaign_block`` and the subtype block is the only signal
    # the API uses to discriminate the chosen strategy on add.
    if block or subtype in _TEXT_SEARCH_REQUIRES_PRIORITY_GOALS:
        base_search[subtype] = block

    return base_search


def build_mobile_app_bidding_strategy(
    search_strategy: Optional[str],
    mobile_search_weekly_spend_limit: Optional[int],
    mobile_search_bid_ceiling: Optional[int],
    mobile_search_custom_period_spend_limit: Optional[int],
    mobile_search_custom_period_start_date: Optional[str],
    mobile_search_custom_period_end_date: Optional[str],
    mobile_search_custom_period_auto_continue: Optional[str],
    mobile_search_average_cpc: Optional[int],
    mobile_search_average_cpi: Optional[int],
    mobile_search_clicks_per_week: Optional[int],
    mobile_search_budget_type: Optional[str],
    network_strategy: Optional[str],
    mobile_network_weekly_spend_limit: Optional[int],
    mobile_network_bid_ceiling: Optional[int],
    mobile_network_custom_period_spend_limit: Optional[int],
    mobile_network_custom_period_start_date: Optional[str],
    mobile_network_custom_period_end_date: Optional[str],
    mobile_network_custom_period_auto_continue: Optional[str],
    mobile_network_average_cpc: Optional[int],
    mobile_network_average_cpi: Optional[int],
    mobile_network_clicks_per_week: Optional[int],
    mobile_network_limit_percent: Optional[int],
    mobile_network_budget_type: Optional[str],
    *,
    include_defaults: bool,
    is_update: bool,
) -> Optional[dict]:
    """Build MobileAppCampaign.BiddingStrategy from typed flags."""
    search = build_mobile_app_search_strategy(
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
        include_default=include_defaults,
        is_update=is_update,
    )
    network = build_mobile_app_network_strategy(
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
        include_default=include_defaults,
        is_update=is_update,
    )
    if search is None and network is None:
        return None
    strategy = {}
    if search is not None:
        strategy["Search"] = search
    if network is not None:
        strategy["Network"] = network
    return strategy


def build_dynamic_text_network_strategy(
    network_strategy: Optional[str],
    weekly_spend_limit: Optional[int],
    bid_ceiling: Optional[int],
    custom_period_spend_limit: Optional[int],
    custom_period_start_date: Optional[str],
    custom_period_end_date: Optional[str],
    custom_period_auto_continue: Optional[str],
    average_cpc: Optional[int],
    average_cpa: Optional[int],
    cpa: Optional[int],
    goal_id: Optional[int],
    crr: Optional[int],
    clicks_per_week: Optional[int],
    limit_percent: Optional[int],
    reserve_return: Optional[int],
    roi_coef: Optional[int],
    profitability: Optional[int],
    exploration_budget: Optional[int],
    exploration_budget_custom: Optional[str],
    budget_type: Optional[str],
    *,
    include_default: bool,
    is_update: bool,
) -> Optional[dict]:
    """Build DynamicTextCampaign.BiddingStrategy.Network from typed flags.

    Mirrors ``DynamicTextCampaignNetworkStrategyAdd`` (campaigns WSDL
    line 1753) and ``DynamicTextCampaignNetworkStrategy`` (line 1203).
    Strategy families and their nested Strategy*Add subtypes follow the
    cached WSDL enum ``DynamicTextCampaignNetworkStrategyTypeEnum`` and
    ``DynamicTextCampaignStrategyAddBase``. Issue #365.
    """
    detail_values = {
        "--dyn-network-weekly-spend-limit": weekly_spend_limit,
        "--dyn-network-bid-ceiling": bid_ceiling,
        "--dyn-network-custom-period-spend-limit": custom_period_spend_limit,
        "--dyn-network-custom-period-start-date": custom_period_start_date,
        "--dyn-network-custom-period-end-date": custom_period_end_date,
        "--dyn-network-custom-period-auto-continue": custom_period_auto_continue,
        "--dyn-network-average-cpc": average_cpc,
        "--dyn-network-average-cpa": average_cpa,
        "--dyn-network-cpa": cpa,
        "--dyn-network-goal-id": goal_id,
        "--dyn-network-crr": crr,
        "--dyn-network-clicks-per-week": clicks_per_week,
        "--dyn-network-limit-percent": limit_percent,
        "--dyn-network-reserve-return": reserve_return,
        "--dyn-network-roi-coef": roi_coef,
        "--dyn-network-profitability": profitability,
        "--dyn-network-exploration-budget": exploration_budget,
        "--dyn-network-exploration-budget-custom": exploration_budget_custom,
        "--dyn-network-budget-type": budget_type,
    }
    has_details = any(value is not None for value in detail_values.values())
    if not include_default and network_strategy is None:
        if has_details:
            raise click.UsageError(
                "DynamicTextCampaign network detail flags require " "--network-strategy"
            )
        return None
    if has_details and network_strategy is None:
        raise click.UsageError(
            "DynamicTextCampaign network detail flags require --network-strategy"
        )

    normalized_strategy = (network_strategy or "SERVING_OFF").upper()
    if normalized_strategy not in DYNAMIC_TEXT_NETWORK_STRATEGIES:
        raise click.UsageError(
            "--network-strategy for DYNAMIC_TEXT_CAMPAIGN must be one of "
            f"{', '.join(DYNAMIC_TEXT_NETWORK_STRATEGIES)}"
        )

    subtype = DYNAMIC_TEXT_NETWORK_STRATEGY_TO_WSDL_SUBTYPE.get(normalized_strategy)
    network: dict = {"BiddingStrategyType": normalized_strategy}
    if subtype is None:
        invalid = [flag for flag, value in detail_values.items() if value is not None]
        if invalid:
            raise click.UsageError(
                f"{normalized_strategy} does not accept DynamicTextCampaign "
                f"network detail flags: {', '.join(sorted(invalid))}"
            )
        return network

    # ExplorationBudget: both subfields must be supplied together (WSDL
    # ExplorationBudget MinimumExplorationBudget/IsMinimumExplorationBudgetCustom
    # are both minOccurs=1).
    exploration_provided = [
        flag
        for flag, value in (
            ("--dyn-network-exploration-budget", exploration_budget),
            ("--dyn-network-exploration-budget-custom", exploration_budget_custom),
        )
        if value is not None
    ]
    if exploration_provided and len(exploration_provided) != 2:
        missing = (
            "--dyn-network-exploration-budget-custom"
            if exploration_budget is not None
            else "--dyn-network-exploration-budget"
        )
        raise click.UsageError(
            "DynamicTextCampaign ExplorationBudget requires both "
            "--dyn-network-exploration-budget and "
            f"--dyn-network-exploration-budget-custom; missing {missing}"
        )
    if exploration_provided and subtype not in _DYN_NETWORK_EXPLORATION_BUDGET_SUBTYPES:
        raise click.UsageError(
            f"{normalized_strategy} does not accept "
            "--dyn-network-exploration-budget / "
            "--dyn-network-exploration-budget-custom"
        )

    # CustomPeriodBudget: all four subfields required together (WSDL
    # CustomPeriodBudget minOccurs=1).
    custom_period_values = {
        "--dyn-network-custom-period-spend-limit": custom_period_spend_limit,
        "--dyn-network-custom-period-start-date": custom_period_start_date,
        "--dyn-network-custom-period-end-date": custom_period_end_date,
        "--dyn-network-custom-period-auto-continue": custom_period_auto_continue,
    }
    custom_period_flags = [
        flag for flag, value in custom_period_values.items() if value is not None
    ]
    if custom_period_flags and len(custom_period_flags) != len(custom_period_values):
        missing = [
            flag for flag, value in custom_period_values.items() if value is None
        ]
        raise click.UsageError(
            "DynamicTextCampaign CustomPeriodBudget requires all custom-period "
            f"flags; missing {', '.join(sorted(missing))}"
        )
    if custom_period_flags and subtype not in _DYN_NETWORK_CUSTOM_PERIOD_SUBTYPES:
        raise click.UsageError(
            f"{normalized_strategy} does not accept DynamicTextCampaign "
            "CustomPeriodBudget flags"
        )
    if weekly_spend_limit is not None and custom_period_flags:
        raise click.UsageError(
            "--dyn-network-weekly-spend-limit cannot be combined with "
            "--dyn-network-custom-period-spend-limit"
        )

    if limit_percent is not None:
        if limit_percent < 10 or limit_percent > 100 or limit_percent % 10 != 0:
            raise click.UsageError(
                "--dyn-network-limit-percent must be a multiple of 10 " "from 10 to 100"
            )
        if subtype not in _DYN_NETWORK_LIMIT_PERCENT_SUBTYPES:
            raise click.UsageError(
                f"{normalized_strategy} does not accept " "--dyn-network-limit-percent"
            )

    # WSDL minOccurs=1 enforcement on the create path: a strategy whose
    # subtype declares required fields (AverageCpc, AverageCpa, GoalId,
    # Crr, Cpa, ClicksPerWeek, ReserveReturn, RoiCoef) must have them
    # supplied or rejected at CLI level.
    if not is_update:
        # Strict WSDL minOccurs=1 enforcement only — no inferred budget
        # requirements (campaigns WSDL: StrategyWeeklyBudgetAddBase has
        # WeeklySpendLimit minOccurs=0, StrategyMaximumClicksAdd /
        # StrategyMaximumConversionRateAdd add CustomPeriodBudget
        # minOccurs=0). Only fields declared minOccurs=1 in the relevant
        # Strategy*Add subtype are gated here.
        required_map = {
            "WbMaximumClicks": [],
            "WbMaximumConversionRate": [
                ("--dyn-network-goal-id", goal_id),
            ],
            "AverageCpc": [("--dyn-network-average-cpc", average_cpc)],
            "AverageCpa": [
                ("--dyn-network-average-cpa", average_cpa),
                ("--dyn-network-goal-id", goal_id),
            ],
            "PayForConversion": [
                ("--dyn-network-cpa", cpa),
                ("--dyn-network-goal-id", goal_id),
            ],
            "AverageRoi": [
                ("--dyn-network-reserve-return", reserve_return),
                ("--dyn-network-roi-coef", roi_coef),
                ("--dyn-network-goal-id", goal_id),
            ],
            "AverageCrr": [
                ("--dyn-network-crr", crr),
                ("--dyn-network-goal-id", goal_id),
            ],
            "PayForConversionCrr": [
                ("--dyn-network-crr", crr),
                ("--dyn-network-goal-id", goal_id),
            ],
            "WeeklyClickPackage": [
                ("--dyn-network-clicks-per-week", clicks_per_week),
            ],
            "NetworkDefault": [],
        }[subtype]
        missing = [flag for flag, value in required_map if value is None]
        if missing:
            raise click.UsageError(
                f"{normalized_strategy} requires {', '.join(sorted(missing))}"
            )

    if budget_type is not None:
        if not is_update:
            raise click.UsageError("--dyn-network-budget-type is update-only")
        if subtype not in _DYN_NETWORK_BUDGET_TYPE_SUBTYPES:
            raise click.UsageError(
                f"{normalized_strategy} does not accept " "--dyn-network-budget-type"
            )
        normalized_budget_type = budget_type.upper()
        if normalized_budget_type == "CUSTOM_PERIOD_BUDGET" and not custom_period_flags:
            raise click.UsageError(
                "--dyn-network-budget-type CUSTOM_PERIOD_BUDGET requires "
                "full CustomPeriodBudget flags"
            )
        if normalized_budget_type == "WEEKLY_BUDGET" and weekly_spend_limit is None:
            raise click.UsageError(
                "--dyn-network-budget-type WEEKLY_BUDGET requires "
                "--dyn-network-weekly-spend-limit"
            )

    field_support = {
        "--dyn-network-weekly-spend-limit": (
            weekly_spend_limit,
            _DYN_NETWORK_WEEKLY_SPEND_LIMIT_SUBTYPES,
        ),
        "--dyn-network-bid-ceiling": (bid_ceiling, _DYN_NETWORK_BID_CEILING_SUBTYPES),
        "--dyn-network-average-cpc": (
            average_cpc,
            _DYN_NETWORK_AVERAGE_CPC_SUBTYPES,
        ),
        "--dyn-network-average-cpa": (
            average_cpa,
            _DYN_NETWORK_AVERAGE_CPA_SUBTYPES,
        ),
        "--dyn-network-cpa": (cpa, _DYN_NETWORK_CPA_SUBTYPES),
        "--dyn-network-goal-id": (goal_id, _DYN_NETWORK_GOAL_ID_SUBTYPES),
        "--dyn-network-crr": (crr, _DYN_NETWORK_CRR_SUBTYPES),
        "--dyn-network-clicks-per-week": (
            clicks_per_week,
            _DYN_NETWORK_CLICKS_PER_WEEK_SUBTYPES,
        ),
        "--dyn-network-reserve-return": (
            reserve_return,
            _DYN_NETWORK_RESERVE_RETURN_SUBTYPES,
        ),
        "--dyn-network-roi-coef": (roi_coef, _DYN_NETWORK_ROI_COEF_SUBTYPES),
        "--dyn-network-profitability": (
            profitability,
            _DYN_NETWORK_PROFITABILITY_SUBTYPES,
        ),
    }
    for flag, (value, supported_subtypes) in field_support.items():
        if value is not None and subtype not in supported_subtypes:
            raise click.UsageError(f"{normalized_strategy} does not accept {flag}")

    block: dict = {}
    if limit_percent is not None:
        block["LimitPercent"] = limit_percent
    if reserve_return is not None:
        block["ReserveReturn"] = reserve_return
    if roi_coef is not None:
        block["RoiCoef"] = roi_coef
    if average_cpa is not None:
        block["AverageCpa"] = average_cpa
    if cpa is not None:
        block["Cpa"] = cpa
    if crr is not None:
        block["Crr"] = crr
    if goal_id is not None:
        block["GoalId"] = goal_id
    if average_cpc is not None:
        block["AverageCpc"] = average_cpc
    if clicks_per_week is not None:
        block["ClicksPerWeek"] = clicks_per_week
    if weekly_spend_limit is not None:
        block["WeeklySpendLimit"] = weekly_spend_limit
    if bid_ceiling is not None:
        block["BidCeiling"] = bid_ceiling
    if profitability is not None:
        block["Profitability"] = profitability
    if custom_period_flags:
        assert custom_period_spend_limit is not None
        assert custom_period_start_date is not None
        assert custom_period_end_date is not None
        assert custom_period_auto_continue is not None
        block["CustomPeriodBudget"] = {
            "SpendLimit": custom_period_spend_limit,
            "StartDate": custom_period_start_date,
            "EndDate": custom_period_end_date,
            "AutoContinue": custom_period_auto_continue.upper(),
        }
    if exploration_provided:
        assert exploration_budget is not None
        assert exploration_budget_custom is not None
        block["ExplorationBudget"] = {
            "MinimumExplorationBudget": exploration_budget,
            "IsMinimumExplorationBudgetCustom": exploration_budget_custom.upper(),
        }
    if budget_type is not None:
        normalized_budget_type = budget_type.upper()
        if normalized_budget_type == "CUSTOM_PERIOD_BUDGET":
            block["WeeklySpendLimit"] = None
        elif normalized_budget_type == "WEEKLY_BUDGET":
            block["CustomPeriodBudget"] = None
        block["BudgetType"] = normalized_budget_type
    if block:
        network[subtype] = block
    return network


def build_dynamic_text_search_strategy(
    search_strategy: Optional[str],
    search_placement_search_results: Optional[str],
    search_placement_product_gallery: Optional[str],
    search_placement_dynamic_places: Optional[str],
    weekly_spend_limit: Optional[int],
    bid_ceiling: Optional[int],
    custom_period_spend_limit: Optional[int],
    custom_period_start_date: Optional[str],
    custom_period_end_date: Optional[str],
    custom_period_auto_continue: Optional[str],
    average_cpc: Optional[int],
    average_cpa: Optional[int],
    cpa: Optional[int],
    goal_id: Optional[int],
    crr: Optional[int],
    clicks_per_week: Optional[int],
    reserve_return: Optional[int],
    roi_coef: Optional[int],
    profitability: Optional[int],
    exploration_budget: Optional[int],
    exploration_budget_custom: Optional[str],
    budget_type: Optional[str],
    *,
    include_default: bool,
    is_update: bool,
) -> Optional[dict]:
    """Build DynamicTextCampaign.BiddingStrategy.Search from typed flags.

    Mirrors ``DynamicTextCampaignSearchStrategyAdd`` (campaigns WSDL
    line 1741-1752) and ``DynamicTextCampaignSearchStrategy`` (line
    1191-1202). Strategy families and their nested Strategy*Add subtypes
    follow the cached WSDL enum
    ``DynamicTextCampaignSearchStrategyTypeEnum`` (line 344-360) and
    ``DynamicTextCampaignStrategyAddBase`` (line 1712-1733).

    PlacementTypes mirrors ``DynamicTextCampaignSearchStrategyPlacementTypesAdd``
    (line 1734-1740) — three YesNoEnum siblings (SearchResults,
    ProductGallery, DynamicPlaces), all minOccurs=0.

    Issue #362.
    """
    placement_values = {
        "--search-placement-search-results": search_placement_search_results,
        "--search-placement-product-gallery": search_placement_product_gallery,
        "--search-placement-dynamic-places": search_placement_dynamic_places,
    }
    has_placement = any(value is not None for value in placement_values.values())
    detail_values = {
        "--dyn-search-weekly-spend-limit": weekly_spend_limit,
        "--dyn-search-bid-ceiling": bid_ceiling,
        "--dyn-search-custom-period-spend-limit": custom_period_spend_limit,
        "--dyn-search-custom-period-start-date": custom_period_start_date,
        "--dyn-search-custom-period-end-date": custom_period_end_date,
        "--dyn-search-custom-period-auto-continue": custom_period_auto_continue,
        "--dyn-search-average-cpc": average_cpc,
        "--dyn-search-average-cpa": average_cpa,
        "--dyn-search-cpa": cpa,
        "--dyn-search-goal-id": goal_id,
        "--dyn-search-crr": crr,
        "--dyn-search-clicks-per-week": clicks_per_week,
        "--dyn-search-reserve-return": reserve_return,
        "--dyn-search-roi-coef": roi_coef,
        "--dyn-search-profitability": profitability,
        "--dyn-search-exploration-budget": exploration_budget,
        "--dyn-search-exploration-budget-custom": exploration_budget_custom,
        "--dyn-search-budget-type": budget_type,
    }
    has_details = any(value is not None for value in detail_values.values())

    if not include_default and search_strategy is None:
        if has_details:
            raise click.UsageError(
                "DynamicTextCampaign search detail flags require --search-strategy"
            )
        if has_placement:
            raise click.UsageError(
                "DynamicTextCampaign search placement flags require --search-strategy"
            )
        return None
    if has_details and search_strategy is None:
        raise click.UsageError(
            "DynamicTextCampaign search detail flags require --search-strategy"
        )
    if has_placement and search_strategy is None:
        raise click.UsageError(
            "DynamicTextCampaign search placement flags require --search-strategy"
        )

    normalized_strategy = (search_strategy or "HIGHEST_POSITION").upper()
    if normalized_strategy not in DYNAMIC_TEXT_SEARCH_STRATEGIES:
        raise click.UsageError(
            "--search-strategy for DYNAMIC_TEXT_CAMPAIGN must be one of "
            f"{', '.join(DYNAMIC_TEXT_SEARCH_STRATEGIES)}"
        )

    subtype = DYNAMIC_TEXT_SEARCH_STRATEGY_TO_WSDL_SUBTYPE.get(normalized_strategy)
    search: dict = {"BiddingStrategyType": normalized_strategy}
    placement_types: dict = {}
    if search_placement_search_results is not None:
        placement_types["SearchResults"] = search_placement_search_results.upper()
    if search_placement_product_gallery is not None:
        placement_types["ProductGallery"] = search_placement_product_gallery.upper()
    if search_placement_dynamic_places is not None:
        placement_types["DynamicPlaces"] = search_placement_dynamic_places.upper()
    if placement_types:
        search["PlacementTypes"] = placement_types

    # Legacy/sentinel strategies (HIGHEST_POSITION, IMPRESSIONS_BELOW_SEARCH,
    # SERVING_OFF) carry no Strategy*Add block — reject silent data loss.
    if subtype is None:
        invalid = [flag for flag, value in detail_values.items() if value is not None]
        if invalid:
            raise click.UsageError(
                f"{normalized_strategy} does not accept DynamicTextCampaign "
                f"search detail flags: {', '.join(sorted(invalid))}"
            )
        return search

    # ExplorationBudget: both subfields together (WSDL ExplorationBudget
    # MinimumExplorationBudget / IsMinimumExplorationBudgetCustom are both
    # minOccurs=1).
    exploration_provided = [
        flag
        for flag, value in (
            ("--dyn-search-exploration-budget", exploration_budget),
            ("--dyn-search-exploration-budget-custom", exploration_budget_custom),
        )
        if value is not None
    ]
    if exploration_provided and len(exploration_provided) != 2:
        missing = (
            "--dyn-search-exploration-budget-custom"
            if exploration_budget is not None
            else "--dyn-search-exploration-budget"
        )
        raise click.UsageError(
            "DynamicTextCampaign Search ExplorationBudget requires both "
            "--dyn-search-exploration-budget and "
            f"--dyn-search-exploration-budget-custom; missing {missing}"
        )
    if exploration_provided and subtype not in _DYN_SEARCH_EXPLORATION_BUDGET_SUBTYPES:
        raise click.UsageError(
            f"{normalized_strategy} does not accept "
            "--dyn-search-exploration-budget / "
            "--dyn-search-exploration-budget-custom"
        )

    # CustomPeriodBudget: all four subfields together (WSDL
    # CustomPeriodBudget minOccurs=1 on every field).
    custom_period_values = {
        "--dyn-search-custom-period-spend-limit": custom_period_spend_limit,
        "--dyn-search-custom-period-start-date": custom_period_start_date,
        "--dyn-search-custom-period-end-date": custom_period_end_date,
        "--dyn-search-custom-period-auto-continue": custom_period_auto_continue,
    }
    custom_period_flags = [
        flag for flag, value in custom_period_values.items() if value is not None
    ]
    if custom_period_flags and len(custom_period_flags) != len(custom_period_values):
        missing = [
            flag for flag, value in custom_period_values.items() if value is None
        ]
        raise click.UsageError(
            "DynamicTextCampaign Search CustomPeriodBudget requires all "
            f"custom-period flags; missing {', '.join(sorted(missing))}"
        )
    if custom_period_flags and subtype not in _DYN_SEARCH_CUSTOM_PERIOD_SUBTYPES:
        raise click.UsageError(
            f"{normalized_strategy} does not accept DynamicTextCampaign Search "
            "CustomPeriodBudget flags"
        )
    if weekly_spend_limit is not None and custom_period_flags:
        raise click.UsageError(
            "--dyn-search-weekly-spend-limit cannot be combined with "
            "--dyn-search-custom-period-spend-limit"
        )

    # WSDL minOccurs=1 enforcement on the create path: every Strategy*Add
    # subtype with a required leaf must have it supplied or rejected at
    # CLI level. References:
    #   StrategyMaximumConversionRateAdd.GoalId (line 1352, minOccurs=1)
    #   StrategyAverageCpcAdd.AverageCpc (line 1365, minOccurs=1)
    #   StrategyAverageCpaAdd.AverageCpa+GoalId (lines 1372-1373)
    #   StrategyPayForConversionAdd.Cpa+GoalId (lines 1382-1383)
    #   StrategyAverageRoiAdd.ReserveReturn+RoiCoef+GoalId (1455-1457)
    #   StrategyAverageCrrAdd.Crr+GoalId (1467-1468)
    #   StrategyPayForConversionCrrAdd.Crr+GoalId (1476-1477)
    #   StrategyWeeklyClickPackageAdd.ClicksPerWeek (1484, minOccurs=1)
    if not is_update:
        required_map = {
            "WbMaximumClicks": [],
            "WbMaximumConversionRate": [
                ("--dyn-search-goal-id", goal_id),
            ],
            "AverageCpc": [("--dyn-search-average-cpc", average_cpc)],
            "AverageCpa": [
                ("--dyn-search-average-cpa", average_cpa),
                ("--dyn-search-goal-id", goal_id),
            ],
            "PayForConversion": [
                ("--dyn-search-cpa", cpa),
                ("--dyn-search-goal-id", goal_id),
            ],
            "AverageRoi": [
                ("--dyn-search-reserve-return", reserve_return),
                ("--dyn-search-roi-coef", roi_coef),
                ("--dyn-search-goal-id", goal_id),
            ],
            "AverageCrr": [
                ("--dyn-search-crr", crr),
                ("--dyn-search-goal-id", goal_id),
            ],
            "PayForConversionCrr": [
                ("--dyn-search-crr", crr),
                ("--dyn-search-goal-id", goal_id),
            ],
            "WeeklyClickPackage": [
                ("--dyn-search-clicks-per-week", clicks_per_week),
            ],
        }[subtype]
        missing = [flag for flag, value in required_map if value is None]
        if missing:
            raise click.UsageError(
                f"{normalized_strategy} requires {', '.join(sorted(missing))}"
            )

    # BudgetType is update-only — on add the budget slice is implied by
    # which of WeeklySpendLimit / CustomPeriodBudget is set. On update,
    # WSDL ``StrategyMaximumClicks`` / ``StrategyAverageCpc`` / etc. all
    # declare ``BudgetType`` as an independent optional element
    # (campaigns WSDL lines 789-804, 813-827, ...). The CLI therefore
    # accepts the standalone switch — e.g. an update that flips an
    # already-configured campaign between WEEKLY_BUDGET and
    # CUSTOM_PERIOD_BUDGET without re-supplying the slice. Yandex
    # rejects inconsistent combinations at the wire; we surface that
    # round-trip error to the user instead of inventing a tighter local
    # contract than the WSDL declares (#362 adversarial-review feedback).
    if budget_type is not None:
        if not is_update:
            raise click.UsageError("--dyn-search-budget-type is update-only")
        if subtype not in _DYN_SEARCH_BUDGET_TYPE_SUBTYPES:
            raise click.UsageError(
                f"{normalized_strategy} does not accept --dyn-search-budget-type"
            )

    # Per-subtype field support — silent-data-loss invariant #2 in
    # tests/test_wsdl_parity_gate.py. Each flag whose value is not None
    # must belong to the WSDL Strategy*Add type for the chosen subtype.
    field_support = {
        "--dyn-search-weekly-spend-limit": (
            weekly_spend_limit,
            _DYN_SEARCH_WEEKLY_SPEND_LIMIT_SUBTYPES,
        ),
        "--dyn-search-bid-ceiling": (bid_ceiling, _DYN_SEARCH_BID_CEILING_SUBTYPES),
        "--dyn-search-average-cpc": (
            average_cpc,
            _DYN_SEARCH_AVERAGE_CPC_SUBTYPES,
        ),
        "--dyn-search-average-cpa": (
            average_cpa,
            _DYN_SEARCH_AVERAGE_CPA_SUBTYPES,
        ),
        "--dyn-search-cpa": (cpa, _DYN_SEARCH_CPA_SUBTYPES),
        "--dyn-search-goal-id": (goal_id, _DYN_SEARCH_GOAL_ID_SUBTYPES),
        "--dyn-search-crr": (crr, _DYN_SEARCH_CRR_SUBTYPES),
        "--dyn-search-clicks-per-week": (
            clicks_per_week,
            _DYN_SEARCH_CLICKS_PER_WEEK_SUBTYPES,
        ),
        "--dyn-search-reserve-return": (
            reserve_return,
            _DYN_SEARCH_RESERVE_RETURN_SUBTYPES,
        ),
        "--dyn-search-roi-coef": (roi_coef, _DYN_SEARCH_ROI_COEF_SUBTYPES),
        "--dyn-search-profitability": (
            profitability,
            _DYN_SEARCH_PROFITABILITY_SUBTYPES,
        ),
    }
    for flag, (value, supported_subtypes) in field_support.items():
        if value is not None and subtype not in supported_subtypes:
            raise click.UsageError(f"{normalized_strategy} does not accept {flag}")

    block: dict = {}
    if reserve_return is not None:
        block["ReserveReturn"] = reserve_return
    if roi_coef is not None:
        block["RoiCoef"] = roi_coef
    if average_cpa is not None:
        block["AverageCpa"] = average_cpa
    if cpa is not None:
        block["Cpa"] = cpa
    if crr is not None:
        block["Crr"] = crr
    if goal_id is not None:
        block["GoalId"] = goal_id
    if average_cpc is not None:
        block["AverageCpc"] = average_cpc
    if clicks_per_week is not None:
        block["ClicksPerWeek"] = clicks_per_week
    if weekly_spend_limit is not None:
        block["WeeklySpendLimit"] = weekly_spend_limit
    if bid_ceiling is not None:
        block["BidCeiling"] = bid_ceiling
    if profitability is not None:
        block["Profitability"] = profitability
    if custom_period_flags:
        assert custom_period_spend_limit is not None
        assert custom_period_start_date is not None
        assert custom_period_end_date is not None
        assert custom_period_auto_continue is not None
        block["CustomPeriodBudget"] = {
            "SpendLimit": custom_period_spend_limit,
            "StartDate": custom_period_start_date,
            "EndDate": custom_period_end_date,
            "AutoContinue": custom_period_auto_continue.upper(),
        }
    if exploration_provided:
        assert exploration_budget is not None
        assert exploration_budget_custom is not None
        block["ExplorationBudget"] = {
            "MinimumExplorationBudget": exploration_budget,
            "IsMinimumExplorationBudgetCustom": exploration_budget_custom.upper(),
        }
    if budget_type is not None:
        normalized_budget_type = budget_type.upper()
        # Mirror the Network/MobileApp/TextSearch builders: switching the
        # budget slice on update nulls the other slice explicitly.
        if normalized_budget_type == "CUSTOM_PERIOD_BUDGET":
            block["WeeklySpendLimit"] = None
        elif normalized_budget_type == "WEEKLY_BUDGET":
            block["CustomPeriodBudget"] = None
        block["BudgetType"] = normalized_budget_type
    if block:
        search[subtype] = block
    return search


# Dispatch registry for bidding-strategy builders. Keyed on
# ``(campaign_type, operation, branch)`` where:
#   - campaign_type: "TEXT_CAMPAIGN", "DYNAMIC_TEXT_CAMPAIGN",
#                    "UNIFIED_CAMPAIGN", "SMART_CAMPAIGN",
#                    "MOBILE_APP_CAMPAIGN", "CPM_BANNER_CAMPAIGN", ...
#   - operation:     "add" | "update"
#   - branch:        "search_base" | "full" | "priority_goals" | ...
#
# Leaf-PRs (#361-369, #373) extend the registry with one entry per
# (campaign_type x branch) instead of patching the giant if/elif in
# ``campaigns.add()``/``campaigns.update()``. Missing keys are intentional:
# ``get_bidding_strategy_builder`` returns ``None`` and the caller falls
# back to today's legacy
# ``{"BiddingStrategyType": strategy_type}`` shape.
CAMPAIGN_TYPE_BUILDERS: Dict[tuple, Callable] = {}


def register_bidding_strategy_builder(
    campaign_type: str,
    operation: str,
    branch: str,
    fn: Callable,
) -> None:
    """Register a builder for ``(campaign_type, operation, branch)``.

    Raises ``ValueError`` on duplicate registration to surface accidental
    overwrites during leaf-PR merges.
    """
    key = (campaign_type, operation, branch)
    if key in CAMPAIGN_TYPE_BUILDERS:
        raise ValueError(f"Bidding-strategy builder already registered for {key}")
    CAMPAIGN_TYPE_BUILDERS[key] = fn


def get_bidding_strategy_builder(
    campaign_type: str,
    operation: str,
    branch: str,
) -> Optional[Callable]:
    """Return the registered builder or ``None`` if no entry exists.

    Callers that get ``None`` must fall back to the legacy
    ``{"BiddingStrategyType": ...}`` shape, preserving today's behavior
    for combos not yet owned by a leaf-PR.
    """
    return CAMPAIGN_TYPE_BUILDERS.get((campaign_type, operation, branch))


# ---------------------------------------------------------------------------
# SmartCampaign.BiddingStrategy.Search (issue #367)
# ---------------------------------------------------------------------------
# Per-Campaign / Per-Filter strategies live ONLY on
# SmartCampaignStrategyAddBase (WSDL ``campaigns.xml`` lines 1789-1809), not
# on TextCampaign / DynamicTextCampaign. The builder returns ONLY the Search
# block — Network is built independently by the caller. Future leaf-PRs for
# Network (#368) and PriorityGoals (#369) register separate keys and do not
# touch this code path.
#
# Source of truth: cached WSDL at ``tests/wsdl_cache/campaigns.xml``.
# The Yandex Direct API v5 reference and developer-guide pages such as
# ``yandex.ru/dev/direct/doc/ref-v5/campaigns/SmartCampaignAdd.html``,
# ``yandex.com/dev/direct/doc/objects/strategies.html`` and
# ``yandex.com/dev/direct/doc/en/`` return HTTP 404 at the time of writing
# (manually verified during development of #367). Yandex publishes the
# canonical SmartCampaign field placement through the SOAP WSDL only,
# which the project caches under ``tests/wsdl_cache/`` and exposes via
# ``scripts/build_wsdl_optional_field_audit.py`` for the soft audit.
# Specifically: every enum value, subtype name, required-field set
# (``minOccurs=1``), and optional-field set used by this builder is
# pulled directly from the cached WSDL — see ``campaigns.xml`` lines:
#   * 396-410: ``SmartCampaignSearchStrategyTypeEnum`` (the 9 Per-*
#     families plus ``SERVING_OFF``).
#   * 1401-1481: ``Strategy*Add`` complex types (add-side, ``minOccurs=1``
#     fields enforced by ``SMART_CAMPAIGN_SEARCH_REQUIRED_FIELDS``).
#   * 851-929: ``Strategy*`` complex types (get/update-side,
#     ``minOccurs=0`` everywhere — required-field check is skipped on
#     update so users can patch a single field). ``BudgetType`` appears
#     only here, which is why ``--smart-search-budget-type`` is
#     update-only.
#   * 1789-1820: ``SmartCampaignStrategyAddBase`` /
#     ``SmartCampaignSearchStrategyAdd`` containers.
#   * 1965-1978: ``CustomPeriodBudget`` and ``ExplorationBudget`` shared
#     types (all-or-nothing groups).
#   * 2202-2214 and 2301-2313: ``SmartCampaignAddItem`` /
#     ``SmartCampaignUpdateItem`` envelopes — the Search block is wired
#     under ``BiddingStrategy.Search`` (add: ``minOccurs=1``, update:
#     ``minOccurs=0``).
SMART_CAMPAIGN_SEARCH_STRATEGIES = [
    "AVERAGE_CPC_PER_CAMPAIGN",
    "AVERAGE_CPC_PER_FILTER",
    "AVERAGE_CPA_PER_CAMPAIGN",
    "AVERAGE_CPA_PER_FILTER",
    "PAY_FOR_CONVERSION_PER_CAMPAIGN",
    "PAY_FOR_CONVERSION_PER_FILTER",
    "AVERAGE_ROI",
    "AVERAGE_CRR",
    "PAY_FOR_CONVERSION_CRR",
    "SERVING_OFF",
]
# Maps Search strategy enum value → WSDL Strategy*Add subtype field name on
# SmartCampaignStrategyAddBase. SERVING_OFF has no subtype block (only the
# BiddingStrategyType field). All other values map to a typed subtype.
SMART_CAMPAIGN_SEARCH_STRATEGY_TO_SUBTYPE = {
    "AVERAGE_CPC_PER_CAMPAIGN": "AverageCpcPerCampaign",
    "AVERAGE_CPC_PER_FILTER": "AverageCpcPerFilter",
    "AVERAGE_CPA_PER_CAMPAIGN": "AverageCpaPerCampaign",
    "AVERAGE_CPA_PER_FILTER": "AverageCpaPerFilter",
    "PAY_FOR_CONVERSION_PER_CAMPAIGN": "PayForConversionPerCampaign",
    "PAY_FOR_CONVERSION_PER_FILTER": "PayForConversionPerFilter",
    "AVERAGE_ROI": "AverageRoi",
    "AVERAGE_CRR": "AverageCrr",
    "PAY_FOR_CONVERSION_CRR": "PayForConversionCrr",
}
# WSDL `minOccurs=1` fields on Strategy*Add subtypes (campaigns.xml 1401-1481).
# Each tuple lists (WSDL field name, CLI option string, value-resolver key).
# Resolver key matches the kwarg name in build_smart_campaign_search_strategy.
SMART_CAMPAIGN_SEARCH_REQUIRED_FIELDS: Dict[str, List[tuple]] = {
    "AverageCpcPerCampaign": [
        ("AverageCpc", "--smart-search-average-cpc", "average_cpc"),
    ],
    "AverageCpcPerFilter": [
        # No required fields per WSDL; FilterAverageCpc is minOccurs=0.
    ],
    "AverageCpaPerCampaign": [
        ("AverageCpa", "--smart-search-average-cpa", "average_cpa"),
        ("GoalId", "--smart-search-goal-id", "goal_id"),
    ],
    "AverageCpaPerFilter": [
        ("FilterAverageCpa", "--smart-search-filter-average-cpa", "filter_average_cpa"),
        ("GoalId", "--smart-search-goal-id", "goal_id"),
    ],
    "PayForConversionPerCampaign": [
        ("Cpa", "--smart-search-cpa", "cpa"),
        ("GoalId", "--smart-search-goal-id", "goal_id"),
    ],
    "PayForConversionPerFilter": [
        ("Cpa", "--smart-search-cpa", "cpa"),
        ("GoalId", "--smart-search-goal-id", "goal_id"),
    ],
    "AverageRoi": [
        ("ReserveReturn", "--smart-search-reserve-return", "reserve_return"),
        ("RoiCoef", "--smart-search-roi-coef", "roi_coef"),
        ("GoalId", "--smart-search-goal-id", "goal_id"),
    ],
    "AverageCrr": [
        ("Crr", "--smart-search-crr", "crr"),
        ("GoalId", "--smart-search-goal-id", "goal_id"),
    ],
    "PayForConversionCrr": [
        ("Crr", "--smart-search-crr", "crr"),
        ("GoalId", "--smart-search-goal-id", "goal_id"),
    ],
}
# Which subtypes accept which numeric/typed fields. Used to fail-fast at the
# CLI when a user passes a flag that does not belong to the chosen subtype.
# Mirrors WSDL element presence on Strategy*Add subtypes.
SMART_CAMPAIGN_SEARCH_FIELD_SUPPORT: Dict[str, set] = {
    "AverageCpc": {"AverageCpcPerCampaign"},
    "FilterAverageCpc": {"AverageCpcPerFilter"},
    "AverageCpa": {"AverageCpaPerCampaign"},
    "FilterAverageCpa": {"AverageCpaPerFilter"},
    "Cpa": {"PayForConversionPerCampaign", "PayForConversionPerFilter"},
    "GoalId": {
        "AverageCpaPerCampaign",
        "AverageCpaPerFilter",
        "PayForConversionPerCampaign",
        "PayForConversionPerFilter",
        "AverageRoi",
        "AverageCrr",
        "PayForConversionCrr",
    },
    "WeeklySpendLimit": {
        "AverageCpcPerCampaign",
        "AverageCpcPerFilter",
        "AverageCpaPerCampaign",
        "AverageCpaPerFilter",
        "PayForConversionPerCampaign",
        "PayForConversionPerFilter",
        "AverageRoi",
        "AverageCrr",
        "PayForConversionCrr",
    },
    "BidCeiling": {
        "AverageCpcPerCampaign",
        "AverageCpcPerFilter",
        "AverageCpaPerCampaign",
        "AverageCpaPerFilter",
        "AverageRoi",
        # NOTE: PayForConversion*, AverageCrr, PayForConversionCrr have no
        # BidCeiling in WSDL (campaigns.xml 1411-1432, 1465-1481).
    },
    "ReserveReturn": {"AverageRoi"},
    "RoiCoef": {"AverageRoi"},
    "Profitability": {"AverageRoi"},
    "Crr": {"AverageCrr", "PayForConversionCrr"},
    # CustomPeriodBudget is supported by every subtype (campaigns.xml grep).
    "CustomPeriodBudget": {
        "AverageCpcPerCampaign",
        "AverageCpcPerFilter",
        "AverageCpaPerCampaign",
        "AverageCpaPerFilter",
        "PayForConversionPerCampaign",
        "PayForConversionPerFilter",
        "AverageRoi",
        "AverageCrr",
        "PayForConversionCrr",
    },
    # ExplorationBudget is on AverageCpa{Per,PerFilter}, AverageRoi,
    # AverageCrr. NOT on AverageCpc* or PayForConversion* (per WSDL).
    "ExplorationBudget": {
        "AverageCpaPerCampaign",
        "AverageCpaPerFilter",
        "AverageRoi",
        "AverageCrr",
    },
}


def build_smart_campaign_search_strategy(
    search_strategy: Optional[str],
    average_cpc: Optional[int],
    filter_average_cpc: Optional[int],
    average_cpa: Optional[int],
    filter_average_cpa: Optional[int],
    cpa: Optional[int],
    goal_id: Optional[int],
    weekly_spend_limit: Optional[int],
    bid_ceiling: Optional[int],
    reserve_return: Optional[int],
    roi_coef: Optional[int],
    profitability: Optional[int],
    crr: Optional[int],
    custom_period_spend_limit: Optional[int],
    custom_period_start_date: Optional[str],
    custom_period_end_date: Optional[str],
    custom_period_auto_continue: Optional[str],
    exploration_min_budget: Optional[int],
    exploration_min_budget_custom: Optional[str],
    budget_type: Optional[str] = None,
    *,
    include_default: bool,
    is_update: bool,
) -> Optional[dict]:
    """Build SmartCampaign.BiddingStrategy.Search from typed CLI flags.

    Returns ``None`` when no Search-related flag is present and
    ``include_default`` is ``False`` (update path). On the add path the
    caller passes ``include_default=True`` and gets a default
    ``{"BiddingStrategyType": "SERVING_OFF"}`` Search container so the
    SmartCampaignStrategyAdd ``Search`` minOccurs=1 contract is satisfied
    without forcing the user to set both Search and Network families.

    Per-Filter / Per-Campaign subtypes are owned by this helper and live
    only on SmartCampaignStrategyAddBase (WSDL campaigns.xml 1789-1809).
    Future leaf-PRs for SmartCampaign.Network (#368) and PriorityGoals
    (#369) register independent builders and do not share state with
    this code path.
    """
    detail_values = {
        "--smart-search-average-cpc": average_cpc,
        "--smart-search-filter-average-cpc": filter_average_cpc,
        "--smart-search-average-cpa": average_cpa,
        "--smart-search-filter-average-cpa": filter_average_cpa,
        "--smart-search-cpa": cpa,
        "--smart-search-goal-id": goal_id,
        "--smart-search-weekly-spend-limit": weekly_spend_limit,
        "--smart-search-bid-ceiling": bid_ceiling,
        "--smart-search-reserve-return": reserve_return,
        "--smart-search-roi-coef": roi_coef,
        "--smart-search-profitability": profitability,
        "--smart-search-crr": crr,
        "--smart-search-cp-spend-limit": custom_period_spend_limit,
        "--smart-search-cp-start-date": custom_period_start_date,
        "--smart-search-cp-end-date": custom_period_end_date,
        "--smart-search-cp-auto-continue": custom_period_auto_continue,
        "--smart-search-exploration-min": exploration_min_budget,
        "--smart-search-exploration-min-custom": exploration_min_budget_custom,
        "--smart-search-budget-type": budget_type,
    }
    has_details = any(value is not None for value in detail_values.values())
    if not include_default and search_strategy is None:
        if has_details:
            raise click.UsageError(
                "SmartCampaign search detail flags require --search-strategy"
            )
        return None
    if has_details and search_strategy is None:
        raise click.UsageError(
            "SmartCampaign search detail flags require --search-strategy"
        )

    normalized_strategy = (search_strategy or "SERVING_OFF").upper()
    if normalized_strategy not in SMART_CAMPAIGN_SEARCH_STRATEGIES:
        raise click.UsageError(
            "--search-strategy for SMART_CAMPAIGN must be one of "
            f"{', '.join(SMART_CAMPAIGN_SEARCH_STRATEGIES)}"
        )

    subtype = SMART_CAMPAIGN_SEARCH_STRATEGY_TO_SUBTYPE.get(normalized_strategy)
    search: dict = {"BiddingStrategyType": normalized_strategy}
    if subtype is None:
        # SERVING_OFF carries no nested block — every typed flag is invalid.
        invalid = [flag for flag, value in detail_values.items() if value is not None]
        if invalid:
            raise click.UsageError(
                f"{normalized_strategy} does not accept SmartCampaign search "
                f"detail flags: {', '.join(sorted(invalid))}"
            )
        return search

    # CustomPeriodBudget is all-or-nothing (4 WSDL minOccurs=1 fields).
    custom_period_values = {
        "--smart-search-cp-spend-limit": custom_period_spend_limit,
        "--smart-search-cp-start-date": custom_period_start_date,
        "--smart-search-cp-end-date": custom_period_end_date,
        "--smart-search-cp-auto-continue": custom_period_auto_continue,
    }
    custom_period_flags = [
        flag for flag, value in custom_period_values.items() if value is not None
    ]
    if custom_period_flags and len(custom_period_flags) != len(custom_period_values):
        missing = [
            flag for flag, value in custom_period_values.items() if value is None
        ]
        raise click.UsageError(
            "SmartCampaign Search CustomPeriodBudget requires all custom-period "
            f"flags; missing {', '.join(sorted(missing))}"
        )
    if (
        custom_period_flags
        and subtype not in SMART_CAMPAIGN_SEARCH_FIELD_SUPPORT["CustomPeriodBudget"]
    ):
        raise click.UsageError(
            f"{normalized_strategy} does not accept SmartCampaign Search "
            "CustomPeriodBudget flags"
        )
    if weekly_spend_limit is not None and custom_period_flags:
        raise click.UsageError(
            "--smart-search-weekly-spend-limit cannot be combined with "
            "--smart-search-cp-spend-limit"
        )

    # ExplorationBudget is all-or-nothing (2 WSDL minOccurs=1 fields).
    exploration_values = {
        "--smart-search-exploration-min": exploration_min_budget,
        "--smart-search-exploration-min-custom": exploration_min_budget_custom,
    }
    exploration_flags = [
        flag for flag, value in exploration_values.items() if value is not None
    ]
    if exploration_flags and len(exploration_flags) != len(exploration_values):
        missing = [flag for flag, value in exploration_values.items() if value is None]
        missing_str = ", ".join(sorted(missing))
        raise click.UsageError(
            "SmartCampaign Search ExplorationBudget requires both "
            "--smart-search-exploration-min and "
            f"--smart-search-exploration-min-custom; missing {missing_str}"
        )
    if (
        exploration_flags
        and subtype not in SMART_CAMPAIGN_SEARCH_FIELD_SUPPORT["ExplorationBudget"]
    ):
        raise click.UsageError(
            f"{normalized_strategy} does not accept SmartCampaign Search "
            "ExplorationBudget flags"
        )

    # Required-field check (WSDL minOccurs=1). Skipped on update so users can
    # partial-update a single field (matches CpmBanner / MobileApp semantics).
    if not is_update:
        required = SMART_CAMPAIGN_SEARCH_REQUIRED_FIELDS.get(subtype, [])
        missing = []
        provided_lookup = {
            "average_cpc": average_cpc,
            "filter_average_cpc": filter_average_cpc,
            "average_cpa": average_cpa,
            "filter_average_cpa": filter_average_cpa,
            "cpa": cpa,
            "goal_id": goal_id,
            "reserve_return": reserve_return,
            "roi_coef": roi_coef,
            "crr": crr,
        }
        for _wsdl_field, cli_flag, resolver in required:
            if provided_lookup.get(resolver) is None:
                missing.append(cli_flag)
        if missing:
            raise click.UsageError(
                f"{normalized_strategy} requires {', '.join(sorted(missing))}"
            )

    # Per-field support check: a typed flag that does not belong to the
    # chosen subtype must raise, not be silently dropped.
    field_support = {
        "--smart-search-average-cpc": ("AverageCpc", average_cpc),
        "--smart-search-filter-average-cpc": ("FilterAverageCpc", filter_average_cpc),
        "--smart-search-average-cpa": ("AverageCpa", average_cpa),
        "--smart-search-filter-average-cpa": ("FilterAverageCpa", filter_average_cpa),
        "--smart-search-cpa": ("Cpa", cpa),
        "--smart-search-goal-id": ("GoalId", goal_id),
        "--smart-search-weekly-spend-limit": ("WeeklySpendLimit", weekly_spend_limit),
        "--smart-search-bid-ceiling": ("BidCeiling", bid_ceiling),
        "--smart-search-reserve-return": ("ReserveReturn", reserve_return),
        "--smart-search-roi-coef": ("RoiCoef", roi_coef),
        "--smart-search-profitability": ("Profitability", profitability),
        "--smart-search-crr": ("Crr", crr),
    }
    for flag, (wsdl_field, value) in field_support.items():
        if (
            value is not None
            and subtype not in SMART_CAMPAIGN_SEARCH_FIELD_SUPPORT[wsdl_field]
        ):
            raise click.UsageError(f"{normalized_strategy} does not accept {flag}")

    block: dict = {}
    if average_cpc is not None:
        block["AverageCpc"] = average_cpc
    if filter_average_cpc is not None:
        block["FilterAverageCpc"] = filter_average_cpc
    if average_cpa is not None:
        block["AverageCpa"] = average_cpa
    if filter_average_cpa is not None:
        block["FilterAverageCpa"] = filter_average_cpa
    if cpa is not None:
        block["Cpa"] = cpa
    if goal_id is not None:
        block["GoalId"] = goal_id
    if weekly_spend_limit is not None:
        block["WeeklySpendLimit"] = weekly_spend_limit
    if bid_ceiling is not None:
        block["BidCeiling"] = bid_ceiling
    if reserve_return is not None:
        block["ReserveReturn"] = reserve_return
    if roi_coef is not None:
        block["RoiCoef"] = roi_coef
    if profitability is not None:
        block["Profitability"] = profitability
    if crr is not None:
        block["Crr"] = crr
    if custom_period_flags:
        assert custom_period_spend_limit is not None
        assert custom_period_start_date is not None
        assert custom_period_end_date is not None
        assert custom_period_auto_continue is not None
        block["CustomPeriodBudget"] = {
            "SpendLimit": custom_period_spend_limit,
            "StartDate": custom_period_start_date,
            "EndDate": custom_period_end_date,
            "AutoContinue": custom_period_auto_continue.upper(),
        }
    if exploration_flags:
        assert exploration_min_budget is not None
        assert exploration_min_budget_custom is not None
        block["ExplorationBudget"] = {
            "MinimumExplorationBudget": exploration_min_budget,
            "IsMinimumExplorationBudgetCustom": (exploration_min_budget_custom.upper()),
        }
    # BudgetType is only on the get-side Strategy* WSDL types
    # (campaigns.xml 858-929), which SmartCampaignUpdateItem uses. The
    # Strategy*Add types used by add do NOT declare BudgetType, so this
    # flag is update-only.
    if budget_type is not None:
        if not is_update:
            raise click.UsageError(
                "--smart-search-budget-type is update-only "
                "(WSDL BudgetType lives only on get-side Strategy*)"
            )
        normalized_budget_type = budget_type.upper()
        if normalized_budget_type == "CUSTOM_PERIOD_BUDGET" and not custom_period_flags:
            raise click.UsageError(
                "--smart-search-budget-type CUSTOM_PERIOD_BUDGET requires "
                "full CustomPeriodBudget flags"
            )
        if normalized_budget_type == "WEEKLY_BUDGET" and weekly_spend_limit is None:
            raise click.UsageError(
                "--smart-search-budget-type WEEKLY_BUDGET requires "
                "--smart-search-weekly-spend-limit"
            )
        if normalized_budget_type == "CUSTOM_PERIOD_BUDGET":
            block["WeeklySpendLimit"] = None
        elif normalized_budget_type == "WEEKLY_BUDGET":
            block["CustomPeriodBudget"] = None
        block["BudgetType"] = normalized_budget_type
    if block:
        search[subtype] = block
    return search


# ---------------------------------------------------------------------------
# TextCampaign.BiddingStrategy.Network (issue #364)
# ---------------------------------------------------------------------------
# Source of truth: cached WSDL at ``tests/wsdl_cache/campaigns.xml``:
#   * Lines 279-298: ``TextCampaignNetworkStrategyTypeEnum`` (the 13 settable
#     families + the ``MAXIMUM_COVERAGE`` / ``SERVING_OFF`` plain-enum values
#     + ``UNKNOWN`` read-only sentinel).
#   * Lines 1581-1608: ``TextCampaignStrategyAddBase`` — the 11 nested
#     ``Strategy*Add`` subtypes shared with ``TextCampaignSearchStrategyAdd``.
#   * Lines 1609-1620: ``TextCampaignNetworkStrategyAdd`` extends
#     ``TextCampaignStrategyAddBase`` with the network ``BiddingStrategyType``
#     enum and the optional ``NetworkDefault`` (``StrategyNetworkDefaultAdd``).
#   * Lines 1339-1514: per-subtype ``Strategy*Add`` complex types whose
#     ``minOccurs=1`` leaves are enforced via
#     ``_TEXT_NETWORK_REQUIRED_TYPED_FLAGS`` below.
#   * The same official Yandex docs constraints used for TextCampaign Search
#     (PR #388, issue #361) apply here: ``BudgetType`` is declared only on the
#     get-side ``Strategy*`` types used by ``TextCampaignUpdateItem`` (lines
#     789-958), so ``--text-network-budget-type`` is update-only and is gated
#     to the subset of subtypes that carry it in the docs.
TEXT_CAMPAIGN_NETWORK_STRATEGIES = [
    "WB_MAXIMUM_CLICKS",
    "WB_MAXIMUM_CONVERSION_RATE",
    "AVERAGE_CPC",
    "AVERAGE_CPA",
    "PAY_FOR_CONVERSION",
    "AVERAGE_ROI",
    "AVERAGE_CRR",
    "PAY_FOR_CONVERSION_CRR",
    "WEEKLY_CLICK_PACKAGE",
    "MAX_PROFIT",
    "AVERAGE_CPA_MULTIPLE_GOALS",
    "PAY_FOR_CONVERSION_MULTIPLE_GOALS",
    "NETWORK_DEFAULT",
    "MAXIMUM_COVERAGE",
    "SERVING_OFF",
]
# Maps ``TextCampaignNetworkStrategyTypeEnum`` value → nested
# ``Strategy*Add`` field name on ``TextCampaignNetworkStrategyAdd``.
# ``MAXIMUM_COVERAGE`` and ``SERVING_OFF`` are settable but carry no nested
# subtype block (the WSDL ``TextCampaignNetworkStrategyAdd`` only exposes
# ``BiddingStrategyType`` for those), so they are absent here.
TEXT_CAMPAIGN_NETWORK_STRATEGY_TO_WSDL_SUBTYPE: Dict[str, str] = {
    "WB_MAXIMUM_CLICKS": "WbMaximumClicks",
    "WB_MAXIMUM_CONVERSION_RATE": "WbMaximumConversionRate",
    "AVERAGE_CPC": "AverageCpc",
    "AVERAGE_CPA": "AverageCpa",
    "PAY_FOR_CONVERSION": "PayForConversion",
    "AVERAGE_ROI": "AverageRoi",
    "AVERAGE_CRR": "AverageCrr",
    "PAY_FOR_CONVERSION_CRR": "PayForConversionCrr",
    "WEEKLY_CLICK_PACKAGE": "WeeklyClickPackage",
    "MAX_PROFIT": "MaxProfit",
    "AVERAGE_CPA_MULTIPLE_GOALS": "AverageCpaMultipleGoals",
    "PAY_FOR_CONVERSION_MULTIPLE_GOALS": "PayForConversionMultipleGoals",
    "NETWORK_DEFAULT": "NetworkDefault",
}

# Per-subtype WSDL field support tables. Sources: ``Strategy*Add`` complex
# types in ``tests/wsdl_cache/campaigns.xml`` lines 1339-1514.
_TEXT_NETWORK_WEEKLY_SPEND_LIMIT_SUBTYPES = {
    "WbMaximumClicks",
    "WbMaximumConversionRate",
    "AverageCpc",
    "AverageCpa",
    "PayForConversion",
    "AverageRoi",
    "AverageCrr",
    "PayForConversionCrr",
    "MaxProfit",
    "AverageCpaMultipleGoals",
    "PayForConversionMultipleGoals",
}
_TEXT_NETWORK_CUSTOM_PERIOD_SUBTYPES = _TEXT_NETWORK_WEEKLY_SPEND_LIMIT_SUBTYPES
_TEXT_NETWORK_BID_CEILING_SUBTYPES = {
    "WbMaximumClicks",
    "WbMaximumConversionRate",
    "AverageCpa",
    "AverageRoi",
    "WeeklyClickPackage",
    "AverageCpaMultipleGoals",
}
_TEXT_NETWORK_AVERAGE_CPC_SUBTYPES = {"AverageCpc", "WeeklyClickPackage"}
_TEXT_NETWORK_AVERAGE_CPA_SUBTYPES = {"AverageCpa"}
_TEXT_NETWORK_PAY_CPA_SUBTYPES = {"PayForConversion"}  # WSDL field name is "Cpa"
_TEXT_NETWORK_GOAL_ID_SUBTYPES = {
    "WbMaximumConversionRate",
    "AverageCpa",
    "PayForConversion",
    "AverageRoi",
    "AverageCrr",
    "PayForConversionCrr",
}
_TEXT_NETWORK_CRR_SUBTYPES = {"AverageCrr", "PayForConversionCrr"}
_TEXT_NETWORK_CLICKS_PER_WEEK_SUBTYPES = {"WeeklyClickPackage"}
_TEXT_NETWORK_RESERVE_RETURN_SUBTYPES = {"AverageRoi"}
_TEXT_NETWORK_ROI_COEF_SUBTYPES = {"AverageRoi"}
_TEXT_NETWORK_PROFITABILITY_SUBTYPES = {"AverageRoi"}
_TEXT_NETWORK_EXPLORATION_BUDGET_SUBTYPES = {
    "AverageCpa",
    "AverageRoi",
    "AverageCrr",
    "AverageCpaMultipleGoals",
    "MaxProfit",
}
_TEXT_NETWORK_LIMIT_PERCENT_SUBTYPES = {"NetworkDefault"}
# Cached WSDL declares ``BudgetType`` on the get-side ``Strategy*`` types
# used by ``TextCampaignUpdateItem`` for every subtype in this set
# (campaigns.xml lines 789-958). Only ``StrategyWeeklyClickPackage`` (line
# 932) has no ``BudgetType`` leaf — that subtype is intentionally excluded.
# Source of truth is ``tests/wsdl_cache/campaigns.xml``; the Yandex public
# docs are showcaptcha-blocked and were not used to scope this set.
_TEXT_NETWORK_BUDGET_TYPE_SUBTYPES = {
    "WbMaximumClicks",
    "WbMaximumConversionRate",
    "AverageCpc",
    "AverageCpa",
    "PayForConversion",
    "AverageRoi",
    "AverageCrr",
    "PayForConversionCrr",
    "AverageCpaMultipleGoals",
    "PayForConversionMultipleGoals",
    "MaxProfit",
}
# Subtypes that require ``PriorityGoals`` per official Yandex docs. Same set
# as the Search branch — ``MAX_PROFIT`` + the two ``*_MULTIPLE_GOALS``
# strategies — placed on the parent ``TextCampaignAddItem.PriorityGoals``
# sibling, NOT inside the Strategy*Add block.
_TEXT_NETWORK_REQUIRES_PRIORITY_GOALS = {
    "AverageCpaMultipleGoals",
    "PayForConversionMultipleGoals",
    "MaxProfit",
}
_TEXT_NETWORK_MIN_PRIORITY_GOALS: Dict[str, int] = {
    "AverageCpaMultipleGoals": 2,
    "PayForConversionMultipleGoals": 2,
}
# WSDL ``minOccurs=1`` fields per Strategy*Add subtype on the add path.
# Maps subtype → {WSDL field name → CLI option string}. Strictly mirrors
# campaigns.xml (lines 1339-1514): only fields that the WSDL marks
# ``minOccurs=1`` (or the implicit parent ``StrategyWeeklyBudgetAddBase``
# attributes that are minOccurs=1 there) are gated here. WSDL declares
# ``StrategyMaximumClicksAdd`` (1339) and ``StrategyMaxProfitAdd`` (1489)
# as fully optional, so no required flags are enforced for them; the user
# can ship the bare-marker subtype. ``WbMaximumConversionRate`` only
# requires ``GoalId`` per WSDL line 1352. ``StrategyAverageCpaMultipleGoalsAdd``
# (1496) / ``StrategyPayForConversionMultipleGoalsAdd`` (1504) are also
# fully optional; ``--priority-goals`` is therefore not gated as required
# at the strategy-builder level (the Yandex API enforces PriorityGoals at
# the wire when the multi-goals strategy is selected, but the WSDL does
# not, so the CLI stays consistent with the strict-WSDL contract).
_TEXT_NETWORK_REQUIRED_TYPED_FLAGS: Dict[str, Dict[str, str]] = {
    "AverageCpc": {"AverageCpc": "--text-network-average-cpc"},
    "AverageCpa": {"AverageCpa": "--average-cpa", "GoalId": "--goal-id"},
    "PayForConversion": {"Cpa": "--text-network-pay-cpa", "GoalId": "--goal-id"},
    "WbMaximumConversionRate": {"GoalId": "--goal-id"},
    "WeeklyClickPackage": {"ClicksPerWeek": "--text-network-clicks-per-week"},
    "AverageRoi": {
        "ReserveReturn": "--text-network-reserve-return",
        "RoiCoef": "--text-network-roi-coef",
        "GoalId": "--goal-id",
    },
    "AverageCrr": {"Crr": "--crr", "GoalId": "--goal-id"},
    "PayForConversionCrr": {"Crr": "--crr", "GoalId": "--goal-id"},
    # WbMaximumClicks / MaxProfit / *MultipleGoals: all fields are
    # minOccurs=0 in campaigns.xml. No required-flag enforcement.
}
# On update we only enforce the fields that conceptually define the NEW
# strategy when ``--network-strategy`` is being switched. Fields the
# campaign may already carry (WeeklySpendLimit on Wb*) are intentionally
# omitted so partial updates remain legitimate (mirrors the Search branch).
_TEXT_NETWORK_REQUIRED_TYPED_FLAGS_UPDATE: Dict[str, Dict[str, str]] = {
    "AverageCpc": {"AverageCpc": "--text-network-average-cpc"},
    "AverageCpa": {"AverageCpa": "--average-cpa", "GoalId": "--goal-id"},
    "PayForConversion": {"Cpa": "--text-network-pay-cpa", "GoalId": "--goal-id"},
    "WbMaximumConversionRate": {"GoalId": "--goal-id"},
    "WeeklyClickPackage": {"ClicksPerWeek": "--text-network-clicks-per-week"},
    "AverageRoi": {
        "ReserveReturn": "--text-network-reserve-return",
        "RoiCoef": "--text-network-roi-coef",
        "GoalId": "--goal-id",
    },
    "AverageCrr": {"Crr": "--crr", "GoalId": "--goal-id"},
    "PayForConversionCrr": {"Crr": "--crr", "GoalId": "--goal-id"},
    "AverageCpaMultipleGoals": {"PriorityGoals": "--priority-goals"},
    "PayForConversionMultipleGoals": {"PriorityGoals": "--priority-goals"},
    "MaxProfit": {"PriorityGoals": "--priority-goals"},
    # ``WbMaximumClicks`` intentionally omitted (no required fields on update).
}


def _build_text_network_custom_period_budget(
    spend_limit: Optional[int],
    start_date: Optional[str],
    end_date: Optional[str],
    auto_continue: Optional[str],
) -> Optional[dict]:
    """Build a CustomPeriodBudget block from the four ``--text-network-*``
    custom-period flags. All four are required together (WSDL
    ``CustomPeriodBudget`` minOccurs=1 on each leaf)."""
    values = {
        "--text-network-custom-period-spend-limit": spend_limit,
        "--text-network-custom-period-start-date": start_date,
        "--text-network-custom-period-end-date": end_date,
        "--text-network-custom-period-auto-continue": auto_continue,
    }
    provided = [flag for flag, value in values.items() if value is not None]
    if not provided:
        return None
    missing = [flag for flag, value in values.items() if value is None]
    if missing:
        raise click.UsageError(
            "TextCampaign Network CustomPeriodBudget requires all four "
            f"custom-period flags; missing {', '.join(sorted(missing))}"
        )
    assert spend_limit is not None
    assert start_date is not None
    assert end_date is not None
    assert auto_continue is not None
    return {
        "SpendLimit": spend_limit,
        "StartDate": start_date,
        "EndDate": end_date,
        "AutoContinue": auto_continue.upper(),
    }


def _build_text_network_exploration_budget(
    min_budget: Optional[int],
    is_custom: Optional[str],
) -> Optional[dict]:
    """Build an ExplorationBudget block. Both fields are WSDL
    ``minOccurs=1`` (campaigns.xml lines 1973-1977); the typed flag
    ``IsMinimumExplorationBudgetCustom`` accepts any value from
    ``general:YesNoEnum`` (``YES``/``NO``)."""
    values = {
        "--text-network-exploration-min-budget": min_budget,
        "--text-network-exploration-is-custom": is_custom,
    }
    provided = [flag for flag, value in values.items() if value is not None]
    if not provided:
        return None
    missing = [flag for flag, value in values.items() if value is None]
    if missing:
        raise click.UsageError(
            "TextCampaign Network ExplorationBudget requires both "
            f"ExplorationBudget flags; missing {', '.join(sorted(missing))}"
        )
    assert min_budget is not None
    assert is_custom is not None
    return {
        "MinimumExplorationBudget": min_budget,
        "IsMinimumExplorationBudgetCustom": is_custom.upper(),
    }


def build_text_campaign_network_strategy(
    *,
    network_strategy: Optional[str],
    goal_id: Optional[int],
    average_cpa: Optional[int],
    crr: Optional[int],
    bid_ceiling: Optional[int],
    weekly_spend_limit: Optional[int],
    custom_period_spend_limit: Optional[int],
    custom_period_start_date: Optional[str],
    custom_period_end_date: Optional[str],
    custom_period_auto_continue: Optional[str],
    budget_type: Optional[str],
    average_cpc: Optional[int],
    pay_cpa: Optional[int],
    clicks_per_week: Optional[int],
    reserve_return: Optional[int],
    roi_coef: Optional[int],
    profitability: Optional[int],
    exploration_min_budget: Optional[int],
    exploration_is_custom: Optional[str],
    limit_percent: Optional[int],
    priority_goals_items: Optional[List[dict]],
    sub_campaign_block: dict,
    include_default: bool,
    is_update: bool,
) -> Optional[dict]:
    """Build the full ``TextCampaign.BiddingStrategy.Network`` payload.

    Covers all 13 settable ``TextCampaignNetworkStrategyTypeEnum`` values
    that map to a nested ``Strategy*Add`` subtype on
    ``TextCampaignNetworkStrategyAdd`` (campaigns WSDL line 1609), plus the
    two no-subtype values ``MAXIMUM_COVERAGE`` / ``SERVING_OFF``
    (BiddingStrategyType only).

    Also places ``PriorityGoals`` onto ``sub_campaign_block`` for
    ``*_MULTIPLE_GOALS`` and ``MAX_PROFIT`` strategies (WSDL
    ``TextCampaignAddItem.PriorityGoals`` is a sibling of
    ``BiddingStrategy``, not nested inside it). On update the caller has
    already placed PriorityGoals via the dedicated
    ``PriorityGoalsUpdateSetting`` shape, so we only validate the
    strategy/subtype combination here. Issue #364.
    """
    typed_detail_values = {
        "--text-network-weekly-spend-limit": weekly_spend_limit,
        "--text-network-custom-period-spend-limit": custom_period_spend_limit,
        "--text-network-custom-period-start-date": custom_period_start_date,
        "--text-network-custom-period-end-date": custom_period_end_date,
        "--text-network-custom-period-auto-continue": custom_period_auto_continue,
        "--text-network-budget-type": budget_type,
        "--text-network-average-cpc": average_cpc,
        "--text-network-pay-cpa": pay_cpa,
        "--text-network-clicks-per-week": clicks_per_week,
        "--text-network-reserve-return": reserve_return,
        "--text-network-roi-coef": roi_coef,
        "--text-network-profitability": profitability,
        "--text-network-exploration-min-budget": exploration_min_budget,
        "--text-network-exploration-is-custom": exploration_is_custom,
        "--text-network-limit-percent": limit_percent,
        "--bid-ceiling": bid_ceiling,
        "--average-cpa": average_cpa,
        "--crr": crr,
        "--goal-id": goal_id,
    }
    has_detail_flags = any(value is not None for value in typed_detail_values.values())

    if not include_default and network_strategy is None:
        if has_detail_flags:
            raise click.UsageError(
                "TextCampaign network strategy detail flags require "
                "--network-strategy"
            )
        return None
    if has_detail_flags and network_strategy is None:
        raise click.UsageError(
            "TextCampaign network strategy detail flags require --network-strategy"
        )

    normalized_strategy = (network_strategy or "SERVING_OFF").upper()
    if normalized_strategy not in TEXT_CAMPAIGN_NETWORK_STRATEGIES:
        raise click.UsageError(
            "--network-strategy for TEXT_CAMPAIGN must be one of "
            f"{', '.join(TEXT_CAMPAIGN_NETWORK_STRATEGIES)}"
        )

    subtype = TEXT_CAMPAIGN_NETWORK_STRATEGY_TO_WSDL_SUBTYPE.get(normalized_strategy)
    network: dict = {"BiddingStrategyType": normalized_strategy}

    # MAXIMUM_COVERAGE / SERVING_OFF carry no subtype block. Reject any
    # detail flag for those.
    if subtype is None:
        provided = [
            flag for flag, value in typed_detail_values.items() if value is not None
        ]
        if provided:
            legacy_cpa_flags = {
                "--average-cpa",
                "--goal-id",
                "--crr",
                "--bid-ceiling",
            }
            legacy_provided = [flag for flag in provided if flag in legacy_cpa_flags]
            if legacy_provided and not any(
                flag for flag in provided if flag not in legacy_cpa_flags
            ):
                raise click.UsageError(
                    f"{', '.join(sorted(legacy_provided))} are only "
                    "valid with a CPA-shaped --search-strategy or "
                    "--network-strategy (e.g. AVERAGE_CPA, "
                    "PAY_FOR_CONVERSION_CRR, AVERAGE_CPA_MULTIPLE_GOALS); "
                    f"got --network-strategy={network_strategy!r}"
                )
            raise click.UsageError(
                f"{normalized_strategy} does not accept TextCampaign network "
                f"strategy detail flags: {', '.join(sorted(provided))}"
            )
        if priority_goals_items is not None and not is_update:
            raise click.UsageError(
                f"{normalized_strategy} does not accept --priority-goals"
            )
        return network

    # Per-subtype "supported field" enforcement (silent data loss invariant
    # #2 in test_wsdl_parity_gate).
    field_support = {
        "--text-network-weekly-spend-limit": (
            weekly_spend_limit,
            _TEXT_NETWORK_WEEKLY_SPEND_LIMIT_SUBTYPES,
        ),
        "--text-network-budget-type": (
            budget_type,
            _TEXT_NETWORK_BUDGET_TYPE_SUBTYPES,
        ),
        "--text-network-average-cpc": (
            average_cpc,
            _TEXT_NETWORK_AVERAGE_CPC_SUBTYPES,
        ),
        "--text-network-pay-cpa": (
            pay_cpa,
            _TEXT_NETWORK_PAY_CPA_SUBTYPES,
        ),
        "--text-network-clicks-per-week": (
            clicks_per_week,
            _TEXT_NETWORK_CLICKS_PER_WEEK_SUBTYPES,
        ),
        "--text-network-reserve-return": (
            reserve_return,
            _TEXT_NETWORK_RESERVE_RETURN_SUBTYPES,
        ),
        "--text-network-roi-coef": (
            roi_coef,
            _TEXT_NETWORK_ROI_COEF_SUBTYPES,
        ),
        "--text-network-profitability": (
            profitability,
            _TEXT_NETWORK_PROFITABILITY_SUBTYPES,
        ),
        "--text-network-limit-percent": (
            limit_percent,
            _TEXT_NETWORK_LIMIT_PERCENT_SUBTYPES,
        ),
        "--bid-ceiling": (bid_ceiling, _TEXT_NETWORK_BID_CEILING_SUBTYPES),
        "--average-cpa": (average_cpa, _TEXT_NETWORK_AVERAGE_CPA_SUBTYPES),
        "--crr": (crr, _TEXT_NETWORK_CRR_SUBTYPES),
        "--goal-id": (goal_id, _TEXT_NETWORK_GOAL_ID_SUBTYPES),
    }
    for flag, (value, supported) in field_support.items():
        if value is not None and subtype not in supported:
            raise click.UsageError(
                f"{flag} is not valid for TextCampaign Network strategy "
                f"{normalized_strategy} (subtype Strategy{subtype}Add); "
                f"WSDL field is declared only on {sorted(supported)}"
            )

    # ReserveReturn doc constraint: 0-100 percentage as a multiple of 10.
    if reserve_return is not None and reserve_return % 10 != 0:
        raise click.UsageError(
            "--text-network-reserve-return must be a multiple of 10 "
            "(0-100), per Yandex Direct API docs"
        )

    # LimitPercent doc constraint: 10-100 by tens (same as MobileApp /
    # DynamicTextCampaign NetworkDefault).
    if limit_percent is not None and (
        limit_percent < 10 or limit_percent > 100 or limit_percent % 10 != 0
    ):
        raise click.UsageError(
            "--text-network-limit-percent must be a multiple of 10 " "from 10 to 100"
        )

    # CustomPeriodBudget and ExplorationBudget are all-or-none; build them
    # first and then validate subtype compatibility.
    custom_period = _build_text_network_custom_period_budget(
        custom_period_spend_limit,
        custom_period_start_date,
        custom_period_end_date,
        custom_period_auto_continue,
    )
    if (
        custom_period is not None
        and subtype not in _TEXT_NETWORK_CUSTOM_PERIOD_SUBTYPES
    ):
        raise click.UsageError(
            f"TextCampaign Network CustomPeriodBudget is not valid for "
            f"{normalized_strategy}"
        )
    exploration_budget = _build_text_network_exploration_budget(
        exploration_min_budget,
        exploration_is_custom,
    )
    if (
        exploration_budget is not None
        and subtype not in _TEXT_NETWORK_EXPLORATION_BUDGET_SUBTYPES
    ):
        raise click.UsageError(
            f"TextCampaign Network ExplorationBudget is not valid for "
            f"{normalized_strategy}"
        )

    # WeeklySpendLimit + CustomPeriodBudget conflict per Yandex docs.
    if weekly_spend_limit is not None and custom_period is not None:
        raise click.UsageError(
            "--text-network-weekly-spend-limit cannot be combined with "
            "--text-network-custom-period-spend-limit"
        )

    # BudgetType is an update-only switch.
    if budget_type is not None:
        if not is_update:
            raise click.UsageError("--text-network-budget-type is update-only")
        normalized_budget_type = budget_type.upper()
        if normalized_budget_type not in BUDGET_TYPES:
            raise click.UsageError(
                "--text-network-budget-type must be one of "
                f"{', '.join(BUDGET_TYPES)}"
            )
        if normalized_budget_type == "CUSTOM_PERIOD_BUDGET" and custom_period is None:
            raise click.UsageError(
                "--text-network-budget-type CUSTOM_PERIOD_BUDGET requires the "
                "full CustomPeriodBudget flag set"
            )
        if normalized_budget_type == "WEEKLY_BUDGET" and weekly_spend_limit is None:
            raise click.UsageError(
                "--text-network-budget-type WEEKLY_BUDGET requires "
                "--text-network-weekly-spend-limit"
            )

    # PriorityGoals scope check. On add we also place PriorityGoals onto
    # the parent ``TextCampaignAddItem`` (sibling of BiddingStrategy). On
    # update the caller passes PriorityGoals via the separate
    # ``PriorityGoalsUpdateSetting`` shape.
    if priority_goals_items is not None:
        if subtype not in _TEXT_NETWORK_REQUIRES_PRIORITY_GOALS:
            raise click.UsageError(
                "--priority-goals is only valid with "
                "AVERAGE_CPA_MULTIPLE_GOALS / "
                "PAY_FOR_CONVERSION_MULTIPLE_GOALS / MAX_PROFIT strategies; "
                f"got --network-strategy={network_strategy!r}"
            )
        min_required = _TEXT_NETWORK_MIN_PRIORITY_GOALS.get(subtype)
        if min_required is not None and len(priority_goals_items) < min_required:
            raise click.UsageError(
                f"--priority-goals requires at least {min_required} entries "
                f"for {network_strategy} per Yandex Direct API docs"
            )
        if not is_update:
            sub_campaign_block["PriorityGoals"] = {"Items": priority_goals_items}

    weekly_or_custom_period = (
        weekly_spend_limit
        if weekly_spend_limit is not None
        else (1 if custom_period is not None else None)
    )
    provided_lookup = {
        "AverageCpc": average_cpc,
        "AverageCpa": average_cpa,
        "Cpa": pay_cpa,
        "GoalId": goal_id,
        "Crr": crr,
        "ClicksPerWeek": clicks_per_week,
        "ReserveReturn": reserve_return,
        "RoiCoef": roi_coef,
        "PriorityGoals": priority_goals_items,
        "WeeklySpendLimit": weekly_or_custom_period,
    }
    if not is_update:
        required = _TEXT_NETWORK_REQUIRED_TYPED_FLAGS.get(subtype, {})
        missing = [
            flag
            for wsdl_field, flag in required.items()
            if provided_lookup.get(wsdl_field) is None
        ]
        if missing:
            raise click.UsageError(
                f"Network strategy {subtype} requires "
                f"{', '.join(sorted(missing))} "
                f"(per Yandex Direct API docs)"
            )
    else:
        if network_strategy is not None:
            required = _TEXT_NETWORK_REQUIRED_TYPED_FLAGS_UPDATE.get(subtype, {})
            missing = [
                flag
                for wsdl_field, flag in required.items()
                if provided_lookup.get(wsdl_field) is None
            ]
            if missing:
                raise click.UsageError(
                    f"Network strategy {subtype} requires "
                    f"{', '.join(sorted(missing))} when switching "
                    "--network-strategy on update (per Yandex Direct "
                    "API docs)"
                )

    # Build the WSDL Strategy*Add block. Element order follows WSDL
    # sequence order for readability.
    block: dict = {}
    if subtype == "AverageCpc":
        if average_cpc is not None:
            block["AverageCpc"] = average_cpc
    elif subtype == "AverageCpa":
        if average_cpa is not None:
            block["AverageCpa"] = average_cpa
        if goal_id is not None:
            block["GoalId"] = goal_id
    elif subtype == "PayForConversion":
        if pay_cpa is not None:
            block["Cpa"] = pay_cpa
        if goal_id is not None:
            block["GoalId"] = goal_id
    elif subtype == "WbMaximumConversionRate":
        if goal_id is not None:
            block["GoalId"] = goal_id
    elif subtype == "WeeklyClickPackage":
        if clicks_per_week is not None:
            block["ClicksPerWeek"] = clicks_per_week
        if average_cpc is not None:
            block["AverageCpc"] = average_cpc
    elif subtype == "AverageRoi":
        if reserve_return is not None:
            block["ReserveReturn"] = reserve_return
        if roi_coef is not None:
            block["RoiCoef"] = roi_coef
        if goal_id is not None:
            block["GoalId"] = goal_id
        if profitability is not None:
            block["Profitability"] = profitability
    elif subtype in {"AverageCrr", "PayForConversionCrr"}:
        if crr is not None:
            block["Crr"] = crr
        if goal_id is not None:
            block["GoalId"] = goal_id
    elif subtype == "NetworkDefault" and limit_percent is not None:
        block["LimitPercent"] = limit_percent
    # WbMaximumClicks / MaxProfit / *MultipleGoals only carry the shared
    # WeeklySpendLimit/BidCeiling/CustomPeriodBudget/ExplorationBudget
    # tail handled next.

    if weekly_spend_limit is not None:
        block["WeeklySpendLimit"] = weekly_spend_limit
    if custom_period is not None:
        block["CustomPeriodBudget"] = custom_period
    if bid_ceiling is not None:
        block["BidCeiling"] = bid_ceiling
    if exploration_budget is not None:
        block["ExplorationBudget"] = exploration_budget
    if budget_type is not None:
        normalized_budget_type = budget_type.upper()
        if normalized_budget_type == "CUSTOM_PERIOD_BUDGET":
            block["WeeklySpendLimit"] = None
        elif normalized_budget_type == "WEEKLY_BUDGET":
            block["CustomPeriodBudget"] = None
        block["BudgetType"] = normalized_budget_type

    # ``*_MULTIPLE_GOALS`` subtypes must emit the container even with no
    # numeric fields — PriorityGoals lives on the parent block and the
    # subtype block is the only signal the API uses to discriminate the
    # strategy on add.
    if block or subtype in _TEXT_NETWORK_REQUIRES_PRIORITY_GOALS:
        network[subtype] = block

    return network


# Register currently-implemented combos. These mirror the direct function
# calls previously inlined in ``campaigns.add()`` / ``campaigns.update()``.
# Adding a new strategy belongs to a leaf-PR, not this foundation PR.
register_bidding_strategy_builder(
    "TEXT_CAMPAIGN", "add", "search_base", build_text_campaign_search_base
)
register_bidding_strategy_builder(
    "TEXT_CAMPAIGN", "update", "search_base", build_text_campaign_search_base
)
register_bidding_strategy_builder(
    "TEXT_CAMPAIGN", "add", "search", build_text_campaign_search_strategy
)
register_bidding_strategy_builder(
    "TEXT_CAMPAIGN", "update", "search", build_text_campaign_search_strategy
)
register_bidding_strategy_builder(
    "TEXT_CAMPAIGN", "add", "priority_goals", apply_cpa_strategy_fields
)
register_bidding_strategy_builder(
    "DYNAMIC_TEXT_CAMPAIGN", "add", "priority_goals", apply_cpa_strategy_fields
)
register_bidding_strategy_builder(
    "CPM_BANNER_CAMPAIGN", "add", "full", build_cpm_banner_bidding_strategy
)
register_bidding_strategy_builder(
    "CPM_BANNER_CAMPAIGN", "update", "full", build_cpm_banner_bidding_strategy
)
register_bidding_strategy_builder(
    "MOBILE_APP_CAMPAIGN", "add", "full", build_mobile_app_bidding_strategy
)
register_bidding_strategy_builder(
    "MOBILE_APP_CAMPAIGN", "update", "full", build_mobile_app_bidding_strategy
)
# ---------------------------------------------------------------------------
# SmartCampaign.BiddingStrategy.Network (issue #368)
# ---------------------------------------------------------------------------
# Network branch of SmartCampaign is structurally symmetric to Search (#367):
# both reuse ``SmartCampaignStrategyAddBase`` (WSDL ``campaigns.xml`` 1789-
# 1810), which carries the same nine ``Strategy*Add`` subtypes (Per-Campaign /
# Per-Filter / AverageRoi / AverageCrr / PayForConversionCrr — lines 1401-
# 1481). The only Network-specific bits are:
#   * ``SmartCampaignNetworkStrategyTypeEnum`` (411-426) gains
#     ``NETWORK_DEFAULT`` (vs. Search's nine families + ``SERVING_OFF``);
#   * ``SmartCampaignNetworkStrategyAdd`` (1822-1834) extends the base with
#     ``BiddingStrategyType`` + an optional ``NetworkDefault`` element of type
#     ``StrategyNetworkDefaultAdd`` (1510-1514, exactly one ``LimitPercent``
#     ``xsd:int`` minOccurs=0); the get-side ``StrategyNetworkDefault``
#     (960-964) is identical.
# Required fields per subtype, optional-field placement, all-or-nothing
# CustomPeriodBudget / ExplorationBudget groups, BudgetType-on-update-only,
# and weekly-vs-custom-period mutex all follow the Search builder's contract
# (campaigns.xml 1965-1978 for the shared budget complex types). Source of
# truth is the cached WSDL — Yandex public docs return showcaptcha.
SMART_CAMPAIGN_NETWORK_STRATEGIES = [
    "NETWORK_DEFAULT",
    "AVERAGE_CPC_PER_CAMPAIGN",
    "AVERAGE_CPC_PER_FILTER",
    "AVERAGE_CPA_PER_CAMPAIGN",
    "AVERAGE_CPA_PER_FILTER",
    "PAY_FOR_CONVERSION_PER_CAMPAIGN",
    "PAY_FOR_CONVERSION_PER_FILTER",
    "AVERAGE_ROI",
    "AVERAGE_CRR",
    "PAY_FOR_CONVERSION_CRR",
    "SERVING_OFF",
]
# Maps Network strategy enum value → WSDL subtype field name on
# ``SmartCampaignNetworkStrategyAdd``. ``SERVING_OFF`` carries no nested
# block (only ``BiddingStrategyType``); ``NETWORK_DEFAULT`` writes the
# ``NetworkDefault`` element (campaigns.xml 1829-1830).
SMART_CAMPAIGN_NETWORK_STRATEGY_TO_SUBTYPE = {
    "NETWORK_DEFAULT": "NetworkDefault",
    "AVERAGE_CPC_PER_CAMPAIGN": "AverageCpcPerCampaign",
    "AVERAGE_CPC_PER_FILTER": "AverageCpcPerFilter",
    "AVERAGE_CPA_PER_CAMPAIGN": "AverageCpaPerCampaign",
    "AVERAGE_CPA_PER_FILTER": "AverageCpaPerFilter",
    "PAY_FOR_CONVERSION_PER_CAMPAIGN": "PayForConversionPerCampaign",
    "PAY_FOR_CONVERSION_PER_FILTER": "PayForConversionPerFilter",
    "AVERAGE_ROI": "AverageRoi",
    "AVERAGE_CRR": "AverageCrr",
    "PAY_FOR_CONVERSION_CRR": "PayForConversionCrr",
}
# WSDL ``minOccurs=1`` fields on Strategy*Add subtypes (campaigns.xml
# 1401-1481) and on ``StrategyNetworkDefaultAdd`` (1510-1514, which has no
# required fields). Shared subtypes mirror the Search side (#367) exactly.
SMART_CAMPAIGN_NETWORK_REQUIRED_FIELDS: Dict[str, List[tuple]] = {
    "NetworkDefault": [
        # ``LimitPercent`` is minOccurs=0; nothing is required on this subtype.
    ],
    "AverageCpcPerCampaign": [
        ("AverageCpc", "--smart-network-average-cpc", "average_cpc"),
    ],
    "AverageCpcPerFilter": [
        # ``FilterAverageCpc`` is minOccurs=0 on Per-Filter (campaigns.xml
        # 1447); subtype block may be empty.
    ],
    "AverageCpaPerCampaign": [
        ("AverageCpa", "--smart-network-average-cpa", "average_cpa"),
        ("GoalId", "--smart-network-goal-id", "goal_id"),
    ],
    "AverageCpaPerFilter": [
        (
            "FilterAverageCpa",
            "--smart-network-filter-average-cpa",
            "filter_average_cpa",
        ),
        ("GoalId", "--smart-network-goal-id", "goal_id"),
    ],
    "PayForConversionPerCampaign": [
        ("Cpa", "--smart-network-cpa", "cpa"),
        ("GoalId", "--smart-network-goal-id", "goal_id"),
    ],
    "PayForConversionPerFilter": [
        ("Cpa", "--smart-network-cpa", "cpa"),
        ("GoalId", "--smart-network-goal-id", "goal_id"),
    ],
    "AverageRoi": [
        ("ReserveReturn", "--smart-network-reserve-return", "reserve_return"),
        ("RoiCoef", "--smart-network-roi-coef", "roi_coef"),
        ("GoalId", "--smart-network-goal-id", "goal_id"),
    ],
    "AverageCrr": [
        ("Crr", "--smart-network-crr", "crr"),
        ("GoalId", "--smart-network-goal-id", "goal_id"),
    ],
    "PayForConversionCrr": [
        ("Crr", "--smart-network-crr", "crr"),
        ("GoalId", "--smart-network-goal-id", "goal_id"),
    ],
}
# Which subtypes accept which numeric/typed fields. Mirrors WSDL element
# presence on Strategy*Add subtypes; identical to the Search matrix for
# shared subtypes (campaigns.xml 1401-1481) plus ``LimitPercent`` on the
# Network-only ``NetworkDefault`` subtype.
SMART_CAMPAIGN_NETWORK_FIELD_SUPPORT: Dict[str, set] = {
    "AverageCpc": {"AverageCpcPerCampaign"},
    "FilterAverageCpc": {"AverageCpcPerFilter"},
    "AverageCpa": {"AverageCpaPerCampaign"},
    "FilterAverageCpa": {"AverageCpaPerFilter"},
    "Cpa": {"PayForConversionPerCampaign", "PayForConversionPerFilter"},
    "GoalId": {
        "AverageCpaPerCampaign",
        "AverageCpaPerFilter",
        "PayForConversionPerCampaign",
        "PayForConversionPerFilter",
        "AverageRoi",
        "AverageCrr",
        "PayForConversionCrr",
    },
    "WeeklySpendLimit": {
        "AverageCpcPerCampaign",
        "AverageCpcPerFilter",
        "AverageCpaPerCampaign",
        "AverageCpaPerFilter",
        "PayForConversionPerCampaign",
        "PayForConversionPerFilter",
        "AverageRoi",
        "AverageCrr",
        "PayForConversionCrr",
    },
    "BidCeiling": {
        "AverageCpcPerCampaign",
        "AverageCpcPerFilter",
        "AverageCpaPerCampaign",
        "AverageCpaPerFilter",
        "AverageRoi",
        # NOTE: PayForConversion*, AverageCrr, PayForConversionCrr have no
        # BidCeiling in WSDL (campaigns.xml 1411-1432, 1465-1481).
    },
    "ReserveReturn": {"AverageRoi"},
    "RoiCoef": {"AverageRoi"},
    "Profitability": {"AverageRoi"},
    "Crr": {"AverageCrr", "PayForConversionCrr"},
    "LimitPercent": {"NetworkDefault"},
    "CustomPeriodBudget": {
        "AverageCpcPerCampaign",
        "AverageCpcPerFilter",
        "AverageCpaPerCampaign",
        "AverageCpaPerFilter",
        "PayForConversionPerCampaign",
        "PayForConversionPerFilter",
        "AverageRoi",
        "AverageCrr",
        "PayForConversionCrr",
    },
    # ExplorationBudget is on AverageCpa{Per,PerFilter}, AverageRoi,
    # AverageCrr. NOT on AverageCpc* or PayForConversion* (per WSDL).
    "ExplorationBudget": {
        "AverageCpaPerCampaign",
        "AverageCpaPerFilter",
        "AverageRoi",
        "AverageCrr",
    },
}


def build_smart_campaign_network_strategy(
    network_strategy: Optional[str],
    average_cpc: Optional[int],
    filter_average_cpc: Optional[int],
    average_cpa: Optional[int],
    filter_average_cpa: Optional[int],
    cpa: Optional[int],
    goal_id: Optional[int],
    weekly_spend_limit: Optional[int],
    bid_ceiling: Optional[int],
    reserve_return: Optional[int],
    roi_coef: Optional[int],
    profitability: Optional[int],
    crr: Optional[int],
    limit_percent: Optional[int],
    custom_period_spend_limit: Optional[int],
    custom_period_start_date: Optional[str],
    custom_period_end_date: Optional[str],
    custom_period_auto_continue: Optional[str],
    exploration_min_budget: Optional[int],
    exploration_min_budget_custom: Optional[str],
    budget_type: Optional[str] = None,
    *,
    include_default: bool,
    is_update: bool,
) -> Optional[dict]:
    """Build SmartCampaign.BiddingStrategy.Network from typed CLI flags.

    Returns ``None`` when no Network-related flag is present and
    ``include_default`` is ``False`` (update path). On the add path the
    caller passes ``include_default=True`` and gets a default
    ``{"BiddingStrategyType": "AVERAGE_CPC_PER_FILTER"}`` Network container
    so the ``SmartCampaignStrategyAdd.Network`` ``minOccurs=1`` contract is
    satisfied without forcing the user to set both Search and Network
    families. This preserves the pre-#368 add-side default that lives in
    ``campaigns.add()``.

    Source of truth: cached WSDL ``tests/wsdl_cache/campaigns.xml`` lines:
      * 411-426: ``SmartCampaignNetworkStrategyTypeEnum``.
      * 1401-1481: ``Strategy*Add`` complex types (shared with Search; the
        ``minOccurs=1`` set is enforced by
        ``SMART_CAMPAIGN_NETWORK_REQUIRED_FIELDS``).
      * 1510-1514: ``StrategyNetworkDefaultAdd`` (single optional
        ``LimitPercent``).
      * 1789-1810 / 1822-1834: ``SmartCampaignStrategyAddBase`` /
        ``SmartCampaignNetworkStrategyAdd`` containers.
      * 1875-1882: ``SmartCampaignStrategyAdd`` envelope
        (``Search`` and ``Network`` both ``minOccurs=1`` on add).
      * 1965-1978: ``CustomPeriodBudget`` and ``ExplorationBudget`` shared
        types (all-or-nothing groups).
      * 858-929: get-side ``Strategy*`` types (carry ``BudgetType`` —
        update-only, mirrors the Search ``--smart-search-budget-type``
        convention).
    """
    detail_values = {
        "--smart-network-average-cpc": average_cpc,
        "--smart-network-filter-average-cpc": filter_average_cpc,
        "--smart-network-average-cpa": average_cpa,
        "--smart-network-filter-average-cpa": filter_average_cpa,
        "--smart-network-cpa": cpa,
        "--smart-network-goal-id": goal_id,
        "--smart-network-weekly-spend-limit": weekly_spend_limit,
        "--smart-network-bid-ceiling": bid_ceiling,
        "--smart-network-reserve-return": reserve_return,
        "--smart-network-roi-coef": roi_coef,
        "--smart-network-profitability": profitability,
        "--smart-network-crr": crr,
        "--smart-network-limit-percent": limit_percent,
        "--smart-network-cp-spend-limit": custom_period_spend_limit,
        "--smart-network-cp-start-date": custom_period_start_date,
        "--smart-network-cp-end-date": custom_period_end_date,
        "--smart-network-cp-auto-continue": custom_period_auto_continue,
        "--smart-network-exploration-min": exploration_min_budget,
        "--smart-network-exploration-min-custom": exploration_min_budget_custom,
        "--smart-network-budget-type": budget_type,
    }
    has_details = any(value is not None for value in detail_values.values())
    if not include_default and network_strategy is None:
        if has_details:
            raise click.UsageError(
                "SmartCampaign network detail flags require --network-strategy"
            )
        return None
    if has_details and network_strategy is None:
        raise click.UsageError(
            "SmartCampaign network detail flags require --network-strategy"
        )

    normalized_strategy = (network_strategy or "AVERAGE_CPC_PER_FILTER").upper()
    if normalized_strategy not in SMART_CAMPAIGN_NETWORK_STRATEGIES:
        raise click.UsageError(
            "--network-strategy for SMART_CAMPAIGN must be one of "
            f"{', '.join(SMART_CAMPAIGN_NETWORK_STRATEGIES)}"
        )

    subtype = SMART_CAMPAIGN_NETWORK_STRATEGY_TO_SUBTYPE.get(normalized_strategy)
    network: dict = {"BiddingStrategyType": normalized_strategy}
    if subtype is None:
        # SERVING_OFF carries no nested block — every typed flag is invalid.
        invalid = [flag for flag, value in detail_values.items() if value is not None]
        if invalid:
            raise click.UsageError(
                f"{normalized_strategy} does not accept SmartCampaign network "
                f"detail flags: {', '.join(sorted(invalid))}"
            )
        return network

    # CustomPeriodBudget is all-or-nothing (4 WSDL minOccurs=1 fields).
    custom_period_values = {
        "--smart-network-cp-spend-limit": custom_period_spend_limit,
        "--smart-network-cp-start-date": custom_period_start_date,
        "--smart-network-cp-end-date": custom_period_end_date,
        "--smart-network-cp-auto-continue": custom_period_auto_continue,
    }
    custom_period_flags = [
        flag for flag, value in custom_period_values.items() if value is not None
    ]
    if custom_period_flags and len(custom_period_flags) != len(custom_period_values):
        missing = [
            flag for flag, value in custom_period_values.items() if value is None
        ]
        raise click.UsageError(
            "SmartCampaign Network CustomPeriodBudget requires all custom-period "
            f"flags; missing {', '.join(sorted(missing))}"
        )
    if (
        custom_period_flags
        and subtype not in SMART_CAMPAIGN_NETWORK_FIELD_SUPPORT["CustomPeriodBudget"]
    ):
        raise click.UsageError(
            f"{normalized_strategy} does not accept SmartCampaign Network "
            "CustomPeriodBudget flags"
        )
    if weekly_spend_limit is not None and custom_period_flags:
        raise click.UsageError(
            "--smart-network-weekly-spend-limit cannot be combined with "
            "--smart-network-cp-spend-limit"
        )

    # ExplorationBudget is all-or-nothing (2 WSDL minOccurs=1 fields).
    exploration_values = {
        "--smart-network-exploration-min": exploration_min_budget,
        "--smart-network-exploration-min-custom": exploration_min_budget_custom,
    }
    exploration_flags = [
        flag for flag, value in exploration_values.items() if value is not None
    ]
    if exploration_flags and len(exploration_flags) != len(exploration_values):
        missing = [flag for flag, value in exploration_values.items() if value is None]
        missing_str = ", ".join(sorted(missing))
        raise click.UsageError(
            "SmartCampaign Network ExplorationBudget requires both "
            "--smart-network-exploration-min and "
            f"--smart-network-exploration-min-custom; missing {missing_str}"
        )
    if (
        exploration_flags
        and subtype not in SMART_CAMPAIGN_NETWORK_FIELD_SUPPORT["ExplorationBudget"]
    ):
        raise click.UsageError(
            f"{normalized_strategy} does not accept SmartCampaign Network "
            "ExplorationBudget flags"
        )

    # LimitPercent: documented local CLI constraint (multiple of 10 in
    # 10..100). The cached WSDL only declares
    # ``StrategyNetworkDefaultAdd.LimitPercent`` as ``xsd:int`` minOccurs=0
    # (campaigns.xml 1510-1513) with no range or step. The CLI mirrors
    # the existing sibling Network helpers
    # ``build_mobile_app_network_strategy`` and
    # ``build_dynamic_text_network_strategy`` (both gate
    # ``--mobile-network-limit-percent`` / ``--dyn-network-limit-percent``
    # with the same range + modulo on top of Click's ``IntRange(10, 100)``)
    # to keep a single project-wide contract across every network-bearing
    # campaign type. Per issue #368 acceptance criterion "validate only
    # documented local constraints", this is the locally documented one.
    if limit_percent is not None:
        if limit_percent < 10 or limit_percent > 100 or limit_percent % 10 != 0:
            raise click.UsageError(
                "--smart-network-limit-percent must be a multiple of 10 "
                "from 10 to 100"
            )
        if subtype not in SMART_CAMPAIGN_NETWORK_FIELD_SUPPORT["LimitPercent"]:
            raise click.UsageError(
                f"{normalized_strategy} does not accept --smart-network-limit-percent"
            )

    # Required-field check (WSDL minOccurs=1). Skipped on update so users can
    # partial-update a single field (matches Search / CpmBanner / MobileApp
    # update semantics).
    if not is_update:
        required = SMART_CAMPAIGN_NETWORK_REQUIRED_FIELDS.get(subtype, [])
        missing = []
        provided_lookup = {
            "average_cpc": average_cpc,
            "filter_average_cpc": filter_average_cpc,
            "average_cpa": average_cpa,
            "filter_average_cpa": filter_average_cpa,
            "cpa": cpa,
            "goal_id": goal_id,
            "reserve_return": reserve_return,
            "roi_coef": roi_coef,
            "crr": crr,
        }
        for _wsdl_field, cli_flag, resolver in required:
            if provided_lookup.get(resolver) is None:
                missing.append(cli_flag)
        if missing:
            raise click.UsageError(
                f"{normalized_strategy} requires {', '.join(sorted(missing))}"
            )

    # Per-field support check: a typed flag that does not belong to the
    # chosen subtype must raise, not be silently dropped.
    field_support = {
        "--smart-network-average-cpc": ("AverageCpc", average_cpc),
        "--smart-network-filter-average-cpc": ("FilterAverageCpc", filter_average_cpc),
        "--smart-network-average-cpa": ("AverageCpa", average_cpa),
        "--smart-network-filter-average-cpa": ("FilterAverageCpa", filter_average_cpa),
        "--smart-network-cpa": ("Cpa", cpa),
        "--smart-network-goal-id": ("GoalId", goal_id),
        "--smart-network-weekly-spend-limit": ("WeeklySpendLimit", weekly_spend_limit),
        "--smart-network-bid-ceiling": ("BidCeiling", bid_ceiling),
        "--smart-network-reserve-return": ("ReserveReturn", reserve_return),
        "--smart-network-roi-coef": ("RoiCoef", roi_coef),
        "--smart-network-profitability": ("Profitability", profitability),
        "--smart-network-crr": ("Crr", crr),
    }
    for flag, (wsdl_field, value) in field_support.items():
        if (
            value is not None
            and subtype not in SMART_CAMPAIGN_NETWORK_FIELD_SUPPORT[wsdl_field]
        ):
            raise click.UsageError(f"{normalized_strategy} does not accept {flag}")

    block: dict = {}
    if limit_percent is not None:
        block["LimitPercent"] = limit_percent
    if average_cpc is not None:
        block["AverageCpc"] = average_cpc
    if filter_average_cpc is not None:
        block["FilterAverageCpc"] = filter_average_cpc
    if average_cpa is not None:
        block["AverageCpa"] = average_cpa
    if filter_average_cpa is not None:
        block["FilterAverageCpa"] = filter_average_cpa
    if cpa is not None:
        block["Cpa"] = cpa
    if goal_id is not None:
        block["GoalId"] = goal_id
    if weekly_spend_limit is not None:
        block["WeeklySpendLimit"] = weekly_spend_limit
    if bid_ceiling is not None:
        block["BidCeiling"] = bid_ceiling
    if reserve_return is not None:
        block["ReserveReturn"] = reserve_return
    if roi_coef is not None:
        block["RoiCoef"] = roi_coef
    if profitability is not None:
        block["Profitability"] = profitability
    if crr is not None:
        block["Crr"] = crr
    if custom_period_flags:
        assert custom_period_spend_limit is not None
        assert custom_period_start_date is not None
        assert custom_period_end_date is not None
        assert custom_period_auto_continue is not None
        block["CustomPeriodBudget"] = {
            "SpendLimit": custom_period_spend_limit,
            "StartDate": custom_period_start_date,
            "EndDate": custom_period_end_date,
            "AutoContinue": custom_period_auto_continue.upper(),
        }
    if exploration_flags:
        assert exploration_min_budget is not None
        assert exploration_min_budget_custom is not None
        block["ExplorationBudget"] = {
            "MinimumExplorationBudget": exploration_min_budget,
            "IsMinimumExplorationBudgetCustom": (exploration_min_budget_custom.upper()),
        }
    # BudgetType is only on the get-side Strategy* WSDL types
    # (campaigns.xml 858-929), which SmartCampaignUpdateItem uses. The
    # Strategy*Add types used by add do NOT declare BudgetType, so this
    # flag is update-only (mirrors --smart-search-budget-type, #367).
    if budget_type is not None:
        if not is_update:
            raise click.UsageError(
                "--smart-network-budget-type is update-only "
                "(WSDL BudgetType lives only on get-side Strategy*)"
            )
        normalized_budget_type = budget_type.upper()
        if normalized_budget_type == "CUSTOM_PERIOD_BUDGET" and not custom_period_flags:
            raise click.UsageError(
                "--smart-network-budget-type CUSTOM_PERIOD_BUDGET requires "
                "full CustomPeriodBudget flags"
            )
        if normalized_budget_type == "WEEKLY_BUDGET" and weekly_spend_limit is None:
            raise click.UsageError(
                "--smart-network-budget-type WEEKLY_BUDGET requires "
                "--smart-network-weekly-spend-limit"
            )
        if normalized_budget_type == "CUSTOM_PERIOD_BUDGET":
            block["WeeklySpendLimit"] = None
        elif normalized_budget_type == "WEEKLY_BUDGET":
            block["CustomPeriodBudget"] = None
        block["BudgetType"] = normalized_budget_type
    if block:
        network[subtype] = block
    return network


register_bidding_strategy_builder(
    "SMART_CAMPAIGN", "add", "search", build_smart_campaign_search_strategy
)
register_bidding_strategy_builder(
    "SMART_CAMPAIGN", "update", "search", build_smart_campaign_search_strategy
)
register_bidding_strategy_builder(
    "SMART_CAMPAIGN", "add", "network", build_smart_campaign_network_strategy
)
register_bidding_strategy_builder(
    "SMART_CAMPAIGN", "update", "network", build_smart_campaign_network_strategy
)
register_bidding_strategy_builder(
    "DYNAMIC_TEXT_CAMPAIGN", "add", "network", build_dynamic_text_network_strategy
)
register_bidding_strategy_builder(
    "DYNAMIC_TEXT_CAMPAIGN", "update", "network", build_dynamic_text_network_strategy
)
register_bidding_strategy_builder(
    "TEXT_CAMPAIGN", "add", "network", build_text_campaign_network_strategy
)
register_bidding_strategy_builder(
    "TEXT_CAMPAIGN", "update", "network", build_text_campaign_network_strategy
)
register_bidding_strategy_builder(
    "DYNAMIC_TEXT_CAMPAIGN", "add", "search", build_dynamic_text_search_strategy
)
register_bidding_strategy_builder(
    "DYNAMIC_TEXT_CAMPAIGN", "update", "search", build_dynamic_text_search_strategy
)


# ---------------------------------------------------------------------------
# UnifiedCampaign.BiddingStrategy.Search (issue #363)
# ---------------------------------------------------------------------------
# WSDL reference: ``tests/wsdl_cache/campaigns.xml``:
#   * L262-278  ``UnifiedCampaignSearchStrategyTypeEnum`` — 13 enum values
#     (10 typed subtypes + HIGHEST_POSITION / SERVING_OFF / UNKNOWN; UNKNOWN
#     is a read-side sentinel and is not exposed on add/update).
#   * L172-180  ``UnifiedCampaignSearchStrategyPlacementTypesFieldEnum`` —
#     5 placement fields (SearchResults, ProductGallery, DynamicPlaces,
#     Maps, SearchOrganizationList).
#   * L636-644  ``UnifiedCampaignSearchStrategyPlacementTypes`` — sequence
#     of 5 ``YesNoEnum`` minOccurs=0 placement toggles.
#   * L1631-1654 ``UnifiedCampaignStrategyAddBase`` — 10 typed Strategy*Add
#     subtypes: WbMaximumClicks, WbMaximumConversionRate, AverageCpc,
#     AverageCpa, PayForConversion, AverageCrr, PayForConversionCrr,
#     AverageCpaMultipleGoals, PayForConversionMultipleGoals, MaxProfit.
#     (UnifiedCampaign does NOT carry WeeklyClickPackage or AverageRoi —
#     unlike TextCampaign / DynamicTextCampaign.)
#   * L1665-1674 ``UnifiedCampaignSearchStrategyAdd`` extends the base with
#     ``BiddingStrategyType`` (minOccurs=1) and ``PlacementTypes``
#     (minOccurs=0).
#   * L1339-1509 ``Strategy*Add`` subtypes with required-field minOccurs.
#   * L1965-1978 ``CustomPeriodBudget`` / ``ExplorationBudget`` shared
#     types (all-or-nothing groups, mirror the TextCampaign Search builder).
#   * L789-957  Get/update-side ``Strategy*`` types (every field
#     minOccurs=0; ``BudgetType`` is declared only here, which is why
#     ``--unified-search-budget-type`` is update-only).
#
# Source-of-truth note: the public Yandex Direct docs at
# ``yandex.ru/dev/direct`` return showcaptcha during automated review, so
# the cached WSDL is the canonical reference. Manual cross-checks against
# ``yandex.com/dev/direct/doc/en/campaigns/UnifiedCampaignAdd.html`` (when
# reachable) were performed.
#
# Parent issue #290; sibling leaf-PRs:
#   * #366 — UnifiedCampaign.Network (different prefix ``--unified-network-*``)
#   * #373 — UnifiedCampaign.PriorityGoals (sibling on
#     ``UnifiedCampaignAddItem``, not nested inside BiddingStrategy).
UNIFIED_CAMPAIGN_SEARCH_STRATEGIES = [
    "HIGHEST_POSITION",
    "WB_MAXIMUM_CONVERSION_RATE",
    "WB_MAXIMUM_CLICKS",
    "AVERAGE_CPC",
    "AVERAGE_CPA",
    "PAY_FOR_CONVERSION",
    "AVERAGE_CRR",
    "PAY_FOR_CONVERSION_CRR",
    "AVERAGE_CPA_MULTIPLE_GOALS",
    "PAY_FOR_CONVERSION_MULTIPLE_GOALS",
    "MAX_PROFIT",
    "SERVING_OFF",
]

# Maps UnifiedCampaignSearchStrategyTypeEnum value → WSDL Strategy*Add
# subtype field name on UnifiedCampaignStrategyAddBase. Strategies without
# a nested subtype block (HIGHEST_POSITION, SERVING_OFF) are absent — the
# API discriminates only by BiddingStrategyType for those.
_UNIFIED_CAMPAIGN_SEARCH_STRATEGY_TO_WSDL_SUBTYPE: Dict[str, str] = {
    "WB_MAXIMUM_CLICKS": "WbMaximumClicks",
    "WB_MAXIMUM_CONVERSION_RATE": "WbMaximumConversionRate",
    "AVERAGE_CPC": "AverageCpc",
    "AVERAGE_CPA": "AverageCpa",
    "PAY_FOR_CONVERSION": "PayForConversion",
    "AVERAGE_CRR": "AverageCrr",
    "PAY_FOR_CONVERSION_CRR": "PayForConversionCrr",
    "AVERAGE_CPA_MULTIPLE_GOALS": "AverageCpaMultipleGoals",
    "PAY_FOR_CONVERSION_MULTIPLE_GOALS": "PayForConversionMultipleGoals",
    "MAX_PROFIT": "MaxProfit",
}

# Per-subtype WSDL field support (campaigns.xml L1339-1509). Every set
# lists subtypes whose WSDL Strategy*Add declares the given field; passing
# the flag for any other subtype must raise a CLI UsageError instead of
# silently dropping the value (invariant #2 in tests/test_wsdl_parity_gate).
_UNIFIED_SEARCH_SUPPORTS_WEEKLY_SPEND_LIMIT = {
    "WbMaximumClicks",
    "WbMaximumConversionRate",
    "AverageCpc",
    "AverageCpa",
    "PayForConversion",
    "AverageCrr",
    "PayForConversionCrr",
    "AverageCpaMultipleGoals",
    "PayForConversionMultipleGoals",
    "MaxProfit",
}
_UNIFIED_SEARCH_SUPPORTS_CUSTOM_PERIOD_BUDGET = {
    "WbMaximumClicks",
    "WbMaximumConversionRate",
    "AverageCpc",
    "AverageCpa",
    "PayForConversion",
    "AverageCrr",
    "PayForConversionCrr",
    "AverageCpaMultipleGoals",
    "PayForConversionMultipleGoals",
    "MaxProfit",
}
_UNIFIED_SEARCH_SUPPORTS_BID_CEILING = {
    "WbMaximumClicks",
    "WbMaximumConversionRate",
    "AverageCpa",
    "AverageCpaMultipleGoals",
}
_UNIFIED_SEARCH_SUPPORTS_AVERAGE_CPC = {"AverageCpc"}
_UNIFIED_SEARCH_SUPPORTS_AVERAGE_CPA = {"AverageCpa"}
_UNIFIED_SEARCH_SUPPORTS_PAY_CPA = {"PayForConversion"}  # WSDL field name "Cpa"
_UNIFIED_SEARCH_SUPPORTS_GOAL_ID = {
    "WbMaximumConversionRate",
    "AverageCpa",
    "PayForConversion",
    "AverageCrr",
    "PayForConversionCrr",
}
_UNIFIED_SEARCH_SUPPORTS_CRR = {"AverageCrr", "PayForConversionCrr"}
_UNIFIED_SEARCH_SUPPORTS_EXPLORATION_BUDGET = {
    "AverageCpa",
    "AverageCrr",
    "AverageCpaMultipleGoals",
    "MaxProfit",
}
# BudgetType (WEEKLY_BUDGET / CUSTOM_PERIOD_BUDGET) is an update-only
# switch; on add the budget slice is implied by which of WeeklySpendLimit /
# CustomPeriodBudget is set. The cached WSDL is the canonical source for
# this PR (Yandex public docs are showcaptcha-blocked, see #363 issue
# body). Per the get-side ``Strategy*`` types (campaigns.xml L789-957)
# BudgetType is declared on EVERY UnifiedCampaign Search subtype that
# inherits from ``StrategyWeeklyBudgetBase`` or carries both WeeklySpend-
# Limit and CustomPeriodBudget — line-by-line:
#   * StrategyMaximumClicks            — L793  BudgetType
#   * StrategyMaximumConversionRate    — L803  BudgetType
#   * StrategyAverageCpc               — L817  BudgetType
#   * StrategyAverageCpa               — L827  BudgetType
#   * StrategyPayForConversion         — L835  BudgetType
#   * StrategyAverageCrr               — L921  BudgetType
#   * StrategyPayForConversionCrr      — L929  BudgetType
#   * StrategyMaxProfit                — L943  BudgetType
#   * StrategyAverageCpaMultipleGoals  — L951  BudgetType
#   * StrategyPayForConversionMultipleGoals — L957  BudgetType
# This intentionally diverges from the TextCampaign Search precedent
# (#388) which deferred to a Yandex public-docs subset for Wb* and
# *MultipleGoals; per the user instructions on this issue, WSDL is the
# canonical source, so all WSDL-declared rows are supported.
_UNIFIED_SEARCH_SUPPORTS_BUDGET_TYPE = {
    "WbMaximumClicks",
    "WbMaximumConversionRate",
    "AverageCpc",
    "AverageCpa",
    "PayForConversion",
    "AverageCrr",
    "PayForConversionCrr",
    "AverageCpaMultipleGoals",
    "PayForConversionMultipleGoals",
    "MaxProfit",
}

# Per official Yandex Direct docs (cross-referenced with
# ``campaigns/UnifiedCampaignAdd.html`` when reachable; otherwise the
# WSDL plus the TextCampaign precedent applies): ``PriorityGoals`` is
# required when ``BiddingStrategyType`` is ``AVERAGE_CPA_MULTIPLE_GOALS``,
# ``PAY_FOR_CONVERSION_MULTIPLE_GOALS`` or ``MAX_PROFIT``. WSDL declares
# PriorityGoals as a sibling on ``UnifiedCampaignAddItem`` (L2160-2174),
# NOT nested inside BiddingStrategy. UnifiedCampaign.PriorityGoals
# typed-flag support is owned by issue #373; this PR limits itself to
# scope validation against the subtype, leaving the actual sibling
# placement to #373.
_UNIFIED_SEARCH_REQUIRES_PRIORITY_GOALS = {
    "AverageCpaMultipleGoals",
    "PayForConversionMultipleGoals",
    "MaxProfit",
}

# WSDL ``minOccurs=1`` fields per Strategy*Add subtype for UnifiedCampaign
# Search. Maps subtype → {WSDL field → CLI flag string}. The cached WSDL
# is the canonical source for this PR (#363); no doc-stricter constraint
# beyond minOccurs=1 is enforced.
#
# Notable divergences from the TextCampaign Search precedent (#388):
#   * WbMaximumClicks has NO required fields (StrategyMaximumClicksAdd
#     extends StrategyWeeklyBudgetAddBase whose WeeklySpendLimit /
#     BidCeiling are minOccurs=0, plus CustomPeriodBudget minOccurs=0);
#   * WbMaximumConversionRate only requires GoalId (WSDL L1352);
#     WeeklySpendLimit / CustomPeriodBudget are minOccurs=0.
# #388 enforced a docs-strict "WeeklySpendLimit or CustomPeriodBudget"
# requirement that is not in the cached WSDL; per the issue body for
# #363 the cached WSDL takes precedence.
_UNIFIED_SEARCH_REQUIRED_TYPED_FLAGS: Dict[str, Dict[str, str]] = {
    "AverageCpc": {"AverageCpc": "--unified-search-average-cpc"},
    "AverageCpa": {"AverageCpa": "--average-cpa", "GoalId": "--goal-id"},
    "PayForConversion": {"Cpa": "--unified-search-pay-cpa", "GoalId": "--goal-id"},
    # WbMaximumClicks: no required fields per WSDL L1339-1347.
    "WbMaximumConversionRate": {"GoalId": "--goal-id"},
    "AverageCrr": {"Crr": "--crr", "GoalId": "--goal-id"},
    "PayForConversionCrr": {"Crr": "--crr", "GoalId": "--goal-id"},
    # ``*_MULTIPLE_GOALS`` / ``MAX_PROFIT`` — PriorityGoals lives on
    # UnifiedCampaignAddItem (not on BiddingStrategy.Search); the typed-
    # flag wiring is owned by #373. The required check is **skipped**
    # here on add until #373 ships; the scope-check below still rejects
    # ``--priority-goals`` for non-MultipleGoals subtypes.
}

# Min PriorityGoals items per subtype (mirror #388).
_UNIFIED_SEARCH_MIN_PRIORITY_GOALS: Dict[str, int] = {
    "AverageCpaMultipleGoals": 2,
    "PayForConversionMultipleGoals": 2,
}

_UNIFIED_CAMPAIGN_SEARCH_BUDGET_TYPES = ["WEEKLY_BUDGET", "CUSTOM_PERIOD_BUDGET"]


def _build_unified_search_custom_period_budget(
    spend_limit: Optional[int],
    start_date: Optional[str],
    end_date: Optional[str],
    auto_continue: Optional[str],
) -> Optional[dict]:
    """Build a CustomPeriodBudget block from the four typed flags.

    All four flags must be provided together (WSDL ``CustomPeriodBudget``
    minOccurs=1 each); returns ``None`` when none are provided. Mirrors
    the TextCampaign Search builder (#388).
    """
    values = {
        "--unified-search-custom-period-spend-limit": spend_limit,
        "--unified-search-custom-period-start-date": start_date,
        "--unified-search-custom-period-end-date": end_date,
        "--unified-search-custom-period-auto-continue": auto_continue,
    }
    provided = [flag for flag, value in values.items() if value is not None]
    if not provided:
        return None
    missing = [flag for flag, value in values.items() if value is None]
    if missing:
        raise click.UsageError(
            "UnifiedCampaign CustomPeriodBudget requires all four custom-period "
            f"flags; missing {', '.join(sorted(missing))}"
        )
    assert spend_limit is not None
    assert start_date is not None
    assert end_date is not None
    assert auto_continue is not None
    return {
        "SpendLimit": spend_limit,
        "StartDate": start_date,
        "EndDate": end_date,
        "AutoContinue": auto_continue.upper(),
    }


def _build_unified_search_exploration_budget(
    min_budget: Optional[int],
    is_custom: Optional[str],
) -> Optional[dict]:
    """Build an ExplorationBudget block from the two typed flags.

    Both fields are WSDL minOccurs=1; returns ``None`` when none are
    provided. The cached WSDL declares ``IsMinimumExplorationBudgetCustom``
    as ``general:YesNoEnum`` with NO restriction on which value is
    accepted (campaigns.xml L1973-1977), and per the issue body the
    cached WSDL is the canonical source. Both ``YES`` and ``NO`` are
    serialized as-is — this intentionally diverges from the TextCampaign
    Search precedent (#388) which deferred to a Yandex public-docs
    YES-only constraint.
    """
    values = {
        "--unified-search-exploration-min-budget": min_budget,
        "--unified-search-exploration-is-custom": is_custom,
    }
    provided = [flag for flag, value in values.items() if value is not None]
    if not provided:
        return None
    missing = [flag for flag, value in values.items() if value is None]
    if missing:
        raise click.UsageError(
            "UnifiedCampaign ExplorationBudget requires both ExplorationBudget "
            f"flags; missing {', '.join(sorted(missing))}"
        )
    assert min_budget is not None
    assert is_custom is not None
    return {
        "MinimumExplorationBudget": min_budget,
        "IsMinimumExplorationBudgetCustom": is_custom.upper(),
    }


def build_unified_campaign_search_base(
    *,
    search_strategy: Optional[str],
    search_placement_search_results: Optional[str],
    search_placement_product_gallery: Optional[str],
    search_placement_dynamic_places: Optional[str],
    search_placement_maps: Optional[str],
    search_placement_search_organization_list: Optional[str],
    include_default: bool,
) -> Optional[dict]:
    """Build the base UnifiedCampaign.BiddingStrategy.Search container.

    Mirrors ``build_text_campaign_search_base`` (#388) but exposes the two
    additional PlacementTypes fields declared only for UnifiedCampaign
    (Maps + SearchOrganizationList, WSDL L177-178).
    """
    placement_values = {
        "--search-placement-search-results": search_placement_search_results,
        "--search-placement-product-gallery": search_placement_product_gallery,
        "--search-placement-dynamic-places": search_placement_dynamic_places,
        "--unified-search-placement-maps": search_placement_maps,
        "--unified-search-placement-search-organization-list": (
            search_placement_search_organization_list
        ),
    }
    has_placement = any(value is not None for value in placement_values.values())
    if not include_default and search_strategy is None:
        if has_placement:
            raise click.UsageError(
                "UnifiedCampaign search placement flags require --search-strategy"
            )
        return None
    if has_placement and search_strategy is None:
        raise click.UsageError(
            "UnifiedCampaign search placement flags require --search-strategy"
        )

    normalized_strategy = (search_strategy or "HIGHEST_POSITION").upper()
    if normalized_strategy not in UNIFIED_CAMPAIGN_SEARCH_STRATEGIES:
        raise click.UsageError(
            "--search-strategy for UNIFIED_CAMPAIGN must be one of "
            f"{', '.join(UNIFIED_CAMPAIGN_SEARCH_STRATEGIES)}"
        )

    search: dict = {"BiddingStrategyType": normalized_strategy}
    placement_types: dict = {}
    if search_placement_search_results is not None:
        placement_types["SearchResults"] = search_placement_search_results.upper()
    if search_placement_product_gallery is not None:
        placement_types["ProductGallery"] = search_placement_product_gallery.upper()
    if search_placement_dynamic_places is not None:
        placement_types["DynamicPlaces"] = search_placement_dynamic_places.upper()
    if search_placement_maps is not None:
        placement_types["Maps"] = search_placement_maps.upper()
    if search_placement_search_organization_list is not None:
        placement_types["SearchOrganizationList"] = (
            search_placement_search_organization_list.upper()
        )
    if placement_types:
        search["PlacementTypes"] = placement_types
    return search


def build_unified_campaign_search_strategy(
    *,
    search_strategy: Optional[str],
    search_placement_search_results: Optional[str],
    search_placement_product_gallery: Optional[str],
    search_placement_dynamic_places: Optional[str],
    search_placement_maps: Optional[str],
    search_placement_search_organization_list: Optional[str],
    goal_id: Optional[int],
    average_cpa: Optional[int],
    crr: Optional[int],
    bid_ceiling: Optional[int],
    weekly_spend_limit: Optional[int],
    custom_period_spend_limit: Optional[int],
    custom_period_start_date: Optional[str],
    custom_period_end_date: Optional[str],
    custom_period_auto_continue: Optional[str],
    budget_type: Optional[str],
    average_cpc: Optional[int],
    pay_cpa: Optional[int],
    exploration_min_budget: Optional[int],
    exploration_is_custom: Optional[str],
    priority_goals_items: Optional[List[dict]],
    sub_campaign_block: dict,
    include_default: bool,
    is_update: bool,
) -> Optional[dict]:
    """Build the full ``UnifiedCampaign.BiddingStrategy.Search`` payload.

    Covers all 10 typed strategy families declared in WSDL
    ``UnifiedCampaignStrategyAddBase`` plus the legacy HIGHEST_POSITION /
    SERVING_OFF (no subtype block). Mirrors the TextCampaign Search
    builder (#388) — UnifiedCampaign differs only in:
      * no ``WeeklyClickPackage`` / ``AverageRoi`` subtypes,
      * two extra PlacementTypes (Maps, SearchOrganizationList).

    ``priority_goals_items`` is accepted for scope/min-count validation
    only; UnifiedCampaign.PriorityGoals typed-flag wiring (sibling on
    ``UnifiedCampaignAddItem``) is owned by issue #373. The caller is
    responsible for placing PriorityGoals onto ``sub_campaign_block``
    when #373 lands.
    """
    typed_detail_values = {
        "--unified-search-weekly-spend-limit": weekly_spend_limit,
        "--unified-search-custom-period-spend-limit": custom_period_spend_limit,
        "--unified-search-custom-period-start-date": custom_period_start_date,
        "--unified-search-custom-period-end-date": custom_period_end_date,
        "--unified-search-custom-period-auto-continue": custom_period_auto_continue,
        "--unified-search-budget-type": budget_type,
        "--unified-search-average-cpc": average_cpc,
        "--unified-search-pay-cpa": pay_cpa,
        "--unified-search-exploration-min-budget": exploration_min_budget,
        "--unified-search-exploration-is-custom": exploration_is_custom,
        "--bid-ceiling": bid_ceiling,
        "--average-cpa": average_cpa,
        "--crr": crr,
        "--goal-id": goal_id,
    }
    has_detail_flags = any(value is not None for value in typed_detail_values.values())

    # Reuse the base container builder for placement + strategy-type
    # validation. ``include_default=False`` on update means we return
    # ``None`` if there is nothing to update.
    base_search = build_unified_campaign_search_base(
        search_strategy=search_strategy,
        search_placement_search_results=search_placement_search_results,
        search_placement_product_gallery=search_placement_product_gallery,
        search_placement_dynamic_places=search_placement_dynamic_places,
        search_placement_maps=search_placement_maps,
        search_placement_search_organization_list=(
            search_placement_search_organization_list
        ),
        include_default=include_default,
    )

    # On update the base might be None when neither strategy nor
    # placement flags are provided. In that case we still guard against
    # silent data loss from detail-only invocations.
    if base_search is None:
        if has_detail_flags:
            raise click.UsageError(
                "UnifiedCampaign search strategy detail flags require "
                "--search-strategy"
            )
        if priority_goals_items is not None and not is_update:
            raise click.UsageError(
                "UnifiedCampaign search strategy detail flags require "
                "--search-strategy"
            )
        return None

    normalized_strategy = base_search["BiddingStrategyType"]
    subtype = _UNIFIED_CAMPAIGN_SEARCH_STRATEGY_TO_WSDL_SUBTYPE.get(normalized_strategy)

    # Legacy two (HIGHEST_POSITION / SERVING_OFF) carry no subtype block.
    # Reject silent data loss.
    if subtype is None:
        provided = [
            flag for flag, value in typed_detail_values.items() if value is not None
        ]
        if provided:
            legacy_cpa_flags = {
                "--average-cpa",
                "--goal-id",
                "--crr",
                "--bid-ceiling",
            }
            legacy_provided = [flag for flag in provided if flag in legacy_cpa_flags]
            if legacy_provided and not any(
                flag for flag in provided if flag not in legacy_cpa_flags
            ):
                raise click.UsageError(
                    f"{', '.join(sorted(legacy_provided))} are only "
                    "valid with a CPA-shaped --search-strategy (e.g. "
                    "AVERAGE_CPA, PAY_FOR_CONVERSION_CRR, "
                    "AVERAGE_CPA_MULTIPLE_GOALS); "
                    f"got --search-strategy={search_strategy!r}"
                )
            raise click.UsageError(
                f"{normalized_strategy} does not accept UnifiedCampaign search "
                f"strategy detail flags: {', '.join(sorted(provided))}"
            )
        if priority_goals_items is not None:
            raise click.UsageError(
                f"{normalized_strategy} does not accept --priority-goals"
            )
        return base_search

    # Per-subtype "supported field" enforcement (silent data loss
    # invariant #2 in test_wsdl_parity_gate). Each flag whose value is
    # not None must belong to the WSDL Strategy*Add type for the chosen
    # subtype.
    field_support = {
        "--unified-search-weekly-spend-limit": (
            weekly_spend_limit,
            _UNIFIED_SEARCH_SUPPORTS_WEEKLY_SPEND_LIMIT,
        ),
        "--unified-search-budget-type": (
            budget_type,
            _UNIFIED_SEARCH_SUPPORTS_BUDGET_TYPE,
        ),
        "--unified-search-average-cpc": (
            average_cpc,
            _UNIFIED_SEARCH_SUPPORTS_AVERAGE_CPC,
        ),
        "--unified-search-pay-cpa": (
            pay_cpa,
            _UNIFIED_SEARCH_SUPPORTS_PAY_CPA,
        ),
        "--bid-ceiling": (bid_ceiling, _UNIFIED_SEARCH_SUPPORTS_BID_CEILING),
        "--average-cpa": (average_cpa, _UNIFIED_SEARCH_SUPPORTS_AVERAGE_CPA),
        "--crr": (crr, _UNIFIED_SEARCH_SUPPORTS_CRR),
        "--goal-id": (goal_id, _UNIFIED_SEARCH_SUPPORTS_GOAL_ID),
    }
    for flag, (value, supported) in field_support.items():
        if value is not None and subtype not in supported:
            raise click.UsageError(
                f"{flag} is not valid for UnifiedCampaign Search strategy "
                f"{normalized_strategy} (subtype Strategy{subtype}Add); "
                f"WSDL field is declared only on {sorted(supported)}"
            )

    # CustomPeriodBudget and ExplorationBudget are container-level checks
    # — all-or-none. Build the nested dicts (or None) up-front and then
    # validate they belong to the chosen subtype.
    custom_period = _build_unified_search_custom_period_budget(
        custom_period_spend_limit,
        custom_period_start_date,
        custom_period_end_date,
        custom_period_auto_continue,
    )
    if (
        custom_period is not None
        and subtype not in _UNIFIED_SEARCH_SUPPORTS_CUSTOM_PERIOD_BUDGET
    ):
        raise click.UsageError(
            f"UnifiedCampaign CustomPeriodBudget is not valid for {normalized_strategy}"
        )
    exploration_budget = _build_unified_search_exploration_budget(
        exploration_min_budget,
        exploration_is_custom,
    )
    if (
        exploration_budget is not None
        and subtype not in _UNIFIED_SEARCH_SUPPORTS_EXPLORATION_BUDGET
    ):
        raise click.UsageError(
            f"UnifiedCampaign ExplorationBudget is not valid for {normalized_strategy}"
        )

    # WeeklySpendLimit + CustomPeriodBudget conflict per Yandex docs:
    # the same subtype can carry only one budget slice.
    if weekly_spend_limit is not None and custom_period is not None:
        raise click.UsageError(
            "--unified-search-weekly-spend-limit cannot be combined with "
            "--unified-search-custom-period-spend-limit"
        )

    # BudgetType is an update-only switch; on add the budget slice is
    # implied by which of WeeklySpendLimit / CustomPeriodBudget is set.
    # WSDL get-side Strategy* types (campaigns.xml L789-957) declare
    # BudgetType as an INDEPENDENT optional element — the field can be
    # patched standalone without re-supplying the stored budget values
    # (mirror the DynamicTextCampaign Search precedent, diverges from
    # the doc-strict #388 TextCampaign behaviour).
    if budget_type is not None:
        if not is_update:
            raise click.UsageError("--unified-search-budget-type is update-only")
        normalized_budget_type = budget_type.upper()
        if normalized_budget_type not in _UNIFIED_CAMPAIGN_SEARCH_BUDGET_TYPES:
            raise click.UsageError(
                "--unified-search-budget-type must be one of "
                f"{', '.join(_UNIFIED_CAMPAIGN_SEARCH_BUDGET_TYPES)}"
            )

    # PriorityGoals scope check. UnifiedCampaign.PriorityGoals typed-flag
    # wiring is owned by #373; this PR rejects --priority-goals for
    # non-MultipleGoals/non-MaxProfit subtypes and validates the min-2
    # entries rule for *_MULTIPLE_GOALS. Placement onto
    # ``sub_campaign_block`` is the caller's responsibility (mirror the
    # TextCampaign builder; #373 will wire the items in).
    if priority_goals_items is not None:
        if subtype not in _UNIFIED_SEARCH_REQUIRES_PRIORITY_GOALS:
            raise click.UsageError(
                "--priority-goals is only valid with "
                "AVERAGE_CPA_MULTIPLE_GOALS / "
                "PAY_FOR_CONVERSION_MULTIPLE_GOALS / MAX_PROFIT strategies; "
                f"got --search-strategy={search_strategy!r}"
            )
        min_required = _UNIFIED_SEARCH_MIN_PRIORITY_GOALS.get(subtype)
        if min_required is not None and len(priority_goals_items) < min_required:
            raise click.UsageError(
                f"--priority-goals requires at least {min_required} entries "
                f"for {search_strategy} per Yandex Direct API docs"
            )
        if not is_update:
            sub_campaign_block["PriorityGoals"] = {"Items": priority_goals_items}

    # WSDL minOccurs=1 fields — fail-fast on add. For Wb* strategies a
    # full CustomPeriodBudget acts as the alternative budget slice that
    # satisfies the WeeklySpendLimit requirement, mirroring #388.
    weekly_or_custom_period = (
        weekly_spend_limit
        if weekly_spend_limit is not None
        else (1 if custom_period is not None else None)
    )
    provided_lookup = {
        "AverageCpc": average_cpc,
        "AverageCpa": average_cpa,
        "Cpa": pay_cpa,
        "GoalId": goal_id,
        "Crr": crr,
        "PriorityGoals": priority_goals_items,
        "WeeklySpendLimit": weekly_or_custom_period,
    }
    if not is_update:
        required = _UNIFIED_SEARCH_REQUIRED_TYPED_FLAGS.get(subtype, {})
        missing = [
            flag
            for wsdl_field, flag in required.items()
            if provided_lookup.get(wsdl_field) is None
        ]
        if missing:
            raise click.UsageError(
                f"Search strategy {subtype} requires {', '.join(sorted(missing))} "
                f"(per Yandex Direct API docs)"
            )
    # On update no required-field check is run. The cached WSDL
    # ``Strategy*`` types (campaigns.xml L789-957) declare every field as
    # minOccurs=0 — every optional field can be patched standalone, and
    # ``--search-strategy`` on update is treated as a subtype selector
    # (which subtype block the patch targets), NOT as a "switching"
    # signal that re-imposes add-time required fields. This diverges
    # from the TextCampaign Search precedent (#388) which carried a
    # doc-strict switching-required check; for #363 the canonical
    # source is the WSDL.

    # Build the WSDL Strategy*Add block. Element order in the dict
    # follows WSDL sequence order for readability — JSON-RPC does not
    # require ordering, but matching makes diffs cleaner.
    block: dict = {}
    if subtype == "AverageCpc":
        if average_cpc is not None:
            block["AverageCpc"] = average_cpc
    elif subtype == "AverageCpa":
        if average_cpa is not None:
            block["AverageCpa"] = average_cpa
        if goal_id is not None:
            block["GoalId"] = goal_id
    elif subtype == "PayForConversion":
        if pay_cpa is not None:
            block["Cpa"] = pay_cpa
        if goal_id is not None:
            block["GoalId"] = goal_id
    elif subtype == "WbMaximumConversionRate":
        if goal_id is not None:
            block["GoalId"] = goal_id
    elif subtype in {"AverageCrr", "PayForConversionCrr"}:
        if crr is not None:
            block["Crr"] = crr
        if goal_id is not None:
            block["GoalId"] = goal_id
    # WbMaximumClicks / MaxProfit / *MultipleGoals have only optional
    # fields below — handled by the shared WeeklySpendLimit/BidCeiling/
    # CustomPeriodBudget/ExplorationBudget tail.

    if weekly_spend_limit is not None:
        block["WeeklySpendLimit"] = weekly_spend_limit
    if custom_period is not None:
        block["CustomPeriodBudget"] = custom_period
    if bid_ceiling is not None:
        block["BidCeiling"] = bid_ceiling
    if exploration_budget is not None:
        block["ExplorationBudget"] = exploration_budget
    if budget_type is not None:
        normalized_budget_type = budget_type.upper()
        # Mirror the TextCampaign/MobileApp builder convention: clearing
        # the other slice signals an explicit budget-type switch on update.
        if normalized_budget_type == "CUSTOM_PERIOD_BUDGET":
            block["WeeklySpendLimit"] = None
        elif normalized_budget_type == "WEEKLY_BUDGET":
            block["CustomPeriodBudget"] = None
        block["BudgetType"] = normalized_budget_type

    # *_MULTIPLE_GOALS / MAX_PROFIT subtypes must emit the container even
    # when no numeric fields are set, because PriorityGoals lives on the
    # parent ``sub_campaign_block`` and the subtype block is the only
    # signal the API uses to discriminate the chosen strategy on add.
    if block or subtype in _UNIFIED_SEARCH_REQUIRES_PRIORITY_GOALS:
        base_search[subtype] = block

    return base_search


register_bidding_strategy_builder(
    "UNIFIED_CAMPAIGN", "add", "search", build_unified_campaign_search_strategy
)
register_bidding_strategy_builder(
    "UNIFIED_CAMPAIGN", "update", "search", build_unified_campaign_search_strategy
)
