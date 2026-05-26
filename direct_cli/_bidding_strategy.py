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
_TEXT_SEARCH_SUPPORTS_BUDGET_TYPE = {
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
        # documented required field for the new subtype must be
        # supplied — the existing campaign value cannot be relied on
        # across a strategy-type switch.
        if search_strategy is not None:
            required = _TEXT_SEARCH_REQUIRED_TYPED_FLAGS.get(subtype, {})
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
