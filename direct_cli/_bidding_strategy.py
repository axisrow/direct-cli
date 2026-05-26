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

    # WeeklyClickPackage rule: AverageCpc and BidCeiling are exclusive
    # alternatives (WSDL StrategyWeeklyClickPackageAdd documents them as
    # optional ceilings; only one shapes the bid policy).
    if (
        subtype == "WeeklyClickPackage"
        and average_cpc is not None
        and bid_ceiling is not None
    ):
        raise click.UsageError(
            "WEEKLY_CLICK_PACKAGE cannot combine --dyn-network-average-cpc "
            "with --dyn-network-bid-ceiling"
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
register_bidding_strategy_builder(
    "DYNAMIC_TEXT_CAMPAIGN", "add", "network", build_dynamic_text_network_strategy
)
register_bidding_strategy_builder(
    "DYNAMIC_TEXT_CAMPAIGN", "update", "network", build_dynamic_text_network_strategy
)
