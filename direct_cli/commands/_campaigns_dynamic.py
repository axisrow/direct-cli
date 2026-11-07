"""DYNAMIC_TEXT_CAMPAIGN payload builders for campaigns add/update.

``build_add_block`` was extracted from the former monolithic
``direct_cli/commands/campaigns.py`` (issue #602, step 4).  It constructs
the ``DynamicTextCampaign`` subtype block for the ``campaigns add``
command.  ``build_update_block`` was extracted from the former inline
DYNAMIC paths of the shared text-family update block (epic #961,
campaigns track).  The CLI surface stays byte-for-byte identical.
"""

from __future__ import annotations

import click

from .._bidding_strategy import get_bidding_strategy_builder
from ..i18n import t
from ..utils import parse_priority_goals_spec, parse_setting_specs
from ._campaigns_base import (
    NEGATIVE_KEYWORD_SHARED_SET_IDS_MAX_ITEMS,
    _array_of_integer_option,
    _build_dynamic_placement_types,
    _build_package_bidding_strategy,
    _priority_goals_update_items,
)


def build_add_block(
    params,
    campaign_data: dict[str, object],
    parsed_settings: list | None,
    counter_ids_obj: object | None,
    priority_goals_items: list | None,
    package_bidding_strategy_obj: object | None,
    negative_keyword_shared_set_ids_obj: object | None,
    dynamic_placement_types: object | None,
) -> None:
    """Build the ``DynamicTextCampaign`` add-item subtype block.

    Mutates *campaign_data* in place by setting
    ``campaign_data["DynamicTextCampaign"]``.

    *params* is the typed snapshot of the ``add`` command parameters
    so that every flag value is available by name without an
    ever-growing formal parameter list.
    """
    # Unpack the flag values that this builder needs from the
    # locals snapshot.  Typed-flags used only by DynamicTextCampaign
    # are prefixed ``dyn_*``; shared legacy CPA flags are bare.
    network_strategy = params.network_strategy
    search_strategy = params.search_strategy
    search_placement_search_results = params.search_placement_search_results
    search_placement_product_gallery = params.search_placement_product_gallery
    search_placement_dynamic_places = params.search_placement_dynamic_places
    average_cpa = params.average_cpa
    goal_id = params.goal_id
    crr = params.crr
    bid_ceiling = params.bid_ceiling
    tracking_params = params.tracking_params
    attribution_model = params.attribution_model

    dyn_network_weekly_spend_limit = params.dyn_network_weekly_spend_limit
    dyn_network_bid_ceiling = params.dyn_network_bid_ceiling
    dyn_network_custom_period_spend_limit = params.dyn_network_custom_period_spend_limit
    dyn_network_custom_period_start_date = params.dyn_network_custom_period_start_date
    dyn_network_custom_period_end_date = params.dyn_network_custom_period_end_date
    dyn_network_custom_period_auto_continue = (
        params.dyn_network_custom_period_auto_continue
    )
    dyn_network_average_cpc = params.dyn_network_average_cpc
    dyn_network_average_cpa = params.dyn_network_average_cpa
    dyn_network_cpa = params.dyn_network_cpa
    dyn_network_goal_id = params.dyn_network_goal_id
    dyn_network_crr = params.dyn_network_crr
    dyn_network_clicks_per_week = params.dyn_network_clicks_per_week
    dyn_network_limit_percent = params.dyn_network_limit_percent
    dyn_network_reserve_return = params.dyn_network_reserve_return
    dyn_network_roi_coef = params.dyn_network_roi_coef
    dyn_network_profitability = params.dyn_network_profitability
    dyn_network_exploration_budget = params.dyn_network_exploration_budget
    dyn_network_exploration_budget_custom = params.dyn_network_exploration_budget_custom

    dyn_search_weekly_spend_limit = params.dyn_search_weekly_spend_limit
    dyn_search_bid_ceiling = params.dyn_search_bid_ceiling
    dyn_search_custom_period_spend_limit = params.dyn_search_custom_period_spend_limit
    dyn_search_custom_period_start_date = params.dyn_search_custom_period_start_date
    dyn_search_custom_period_end_date = params.dyn_search_custom_period_end_date
    dyn_search_custom_period_auto_continue = (
        params.dyn_search_custom_period_auto_continue
    )
    dyn_search_average_cpc = params.dyn_search_average_cpc
    dyn_search_average_cpa = params.dyn_search_average_cpa
    dyn_search_cpa = params.dyn_search_cpa
    dyn_search_goal_id = params.dyn_search_goal_id
    dyn_search_crr = params.dyn_search_crr
    dyn_search_clicks_per_week = params.dyn_search_clicks_per_week
    dyn_search_reserve_return = params.dyn_search_reserve_return
    dyn_search_roi_coef = params.dyn_search_roi_coef
    dyn_search_profitability = params.dyn_search_profitability
    dyn_search_exploration_budget = params.dyn_search_exploration_budget
    dyn_search_exploration_budget_custom = params.dyn_search_exploration_budget_custom

    dyn_block: dict[str, object] = {"Settings": parsed_settings or []}
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
                        "DynamicTextCampaign Search typed flags (--dyn-search-*) "
                        "cannot be combined with the legacy CPA-shape flags "
                        "{arg0}; use the matching --dyn-search-* equivalent"
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
        dyn_block["NegativeKeywordSharedSetIds"] = negative_keyword_shared_set_ids_obj
    if tracking_params:
        dyn_block["TrackingParams"] = tracking_params
    campaign_data["DynamicTextCampaign"] = dyn_block


def build_update_block(params, sub_block):
    """Fill ``sub_block`` for the DynamicTextCampaign subtype of ``campaigns update``.

    Verbatim extract of the former inline DYNAMIC paths of the shared
    text-family update block in ``campaigns.py`` (epic #961, campaigns
    track). ``params`` is the typed snapshot of every CLI parameter of the
    ``update`` command; only the DynamicTextCampaign-relevant flags are
    pulled out below.
    """
    settings = params.settings
    counter_ids = params.counter_ids
    priority_goals = params.priority_goals
    attribution_model = params.attribution_model
    package_strategy_id = params.package_strategy_id
    package_strategy_from_campaign_id = params.package_strategy_from_campaign_id
    package_platform_search_result = params.package_platform_search_result
    package_platform_product_gallery = params.package_platform_product_gallery
    package_platform_maps = params.package_platform_maps
    package_platform_search_organization_list = (
        params.package_platform_search_organization_list
    )
    package_platform_network = params.package_platform_network
    package_platform_dynamic_places = params.package_platform_dynamic_places
    dynamic_placement_search_results = params.dynamic_placement_search_results
    dynamic_placement_product_gallery = params.dynamic_placement_product_gallery
    search_strategy = params.search_strategy
    search_placement_search_results = params.search_placement_search_results
    search_placement_product_gallery = params.search_placement_product_gallery
    search_placement_dynamic_places = params.search_placement_dynamic_places
    network_strategy = params.network_strategy

    dyn_network_weekly_spend_limit = params.dyn_network_weekly_spend_limit
    dyn_network_bid_ceiling = params.dyn_network_bid_ceiling
    dyn_network_custom_period_spend_limit = params.dyn_network_custom_period_spend_limit
    dyn_network_custom_period_start_date = params.dyn_network_custom_period_start_date
    dyn_network_custom_period_end_date = params.dyn_network_custom_period_end_date
    dyn_network_custom_period_auto_continue = (
        params.dyn_network_custom_period_auto_continue
    )
    dyn_network_average_cpc = params.dyn_network_average_cpc
    dyn_network_average_cpa = params.dyn_network_average_cpa
    dyn_network_cpa = params.dyn_network_cpa
    dyn_network_goal_id = params.dyn_network_goal_id
    dyn_network_crr = params.dyn_network_crr
    dyn_network_clicks_per_week = params.dyn_network_clicks_per_week
    dyn_network_limit_percent = params.dyn_network_limit_percent
    dyn_network_reserve_return = params.dyn_network_reserve_return
    dyn_network_roi_coef = params.dyn_network_roi_coef
    dyn_network_profitability = params.dyn_network_profitability
    dyn_network_exploration_budget = params.dyn_network_exploration_budget
    dyn_network_exploration_budget_custom = params.dyn_network_exploration_budget_custom
    dyn_network_budget_type = params.dyn_network_budget_type

    dyn_search_weekly_spend_limit = params.dyn_search_weekly_spend_limit
    dyn_search_bid_ceiling = params.dyn_search_bid_ceiling
    dyn_search_custom_period_spend_limit = params.dyn_search_custom_period_spend_limit
    dyn_search_custom_period_start_date = params.dyn_search_custom_period_start_date
    dyn_search_custom_period_end_date = params.dyn_search_custom_period_end_date
    dyn_search_custom_period_auto_continue = (
        params.dyn_search_custom_period_auto_continue
    )
    dyn_search_average_cpc = params.dyn_search_average_cpc
    dyn_search_average_cpa = params.dyn_search_average_cpa
    dyn_search_cpa = params.dyn_search_cpa
    dyn_search_goal_id = params.dyn_search_goal_id
    dyn_search_crr = params.dyn_search_crr
    dyn_search_clicks_per_week = params.dyn_search_clicks_per_week
    dyn_search_reserve_return = params.dyn_search_reserve_return
    dyn_search_roi_coef = params.dyn_search_roi_coef
    dyn_search_profitability = params.dyn_search_profitability
    dyn_search_exploration_budget = params.dyn_search_exploration_budget
    dyn_search_exploration_budget_custom = params.dyn_search_exploration_budget_custom
    dyn_search_budget_type = params.dyn_search_budget_type
    negative_keyword_shared_set_ids = params.negative_keyword_shared_set_ids

    parsed_settings = parse_setting_specs(list(settings))
    if parsed_settings:
        sub_block["Settings"] = parsed_settings
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
        campaign_label="DynamicTextCampaign",
        require_platforms=False,
    )
    if package_bidding_strategy_obj is not None:
        # DynamicTextCampaign keeps the PackageBiddingStrategy mutex
        # (#373): any per-side Network (#365) / Search (#362) typed flag
        # combined with the package strategy on update is rejected so
        # user input is never silently dropped.
        package_incompatible: dict[str, object] = {
            "--network-strategy": network_strategy,
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
            "--dyn-network-budget-type": dyn_network_budget_type,
            # DynamicTextCampaign Search typed flags (#362).
            "--search-strategy": search_strategy,
            "--search-placement-search-results": search_placement_search_results,
            "--search-placement-product-gallery": search_placement_product_gallery,
            "--search-placement-dynamic-places": search_placement_dynamic_places,
            "--dyn-search-weekly-spend-limit": dyn_search_weekly_spend_limit,
            "--dyn-search-bid-ceiling": dyn_search_bid_ceiling,
            "--dyn-search-custom-period-spend-limit": (
                dyn_search_custom_period_spend_limit
            ),
            "--dyn-search-custom-period-start-date": (
                dyn_search_custom_period_start_date
            ),
            "--dyn-search-custom-period-end-date": dyn_search_custom_period_end_date,
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
        }
        provided = [
            flag for flag, value in package_incompatible.items() if value is not None
        ]
        if provided:
            raise click.UsageError(
                t(
                    "{package_label}.PackageBiddingStrategy cannot be "
                    "combined with {arg0}"
                ).format(
                    package_label="DynamicTextCampaign",
                    arg0=", ".join(sorted(provided)),
                )
            )
        sub_block["PackageBiddingStrategy"] = package_bidding_strategy_obj
    else:
        # DynamicTextCampaign.BiddingStrategy.Network update (#365).
        # Build via shared builder; include_default is False so an
        # absent --network-strategy with no detail flags leaves
        # BiddingStrategy untouched.
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
        # DynamicTextCampaign.BiddingStrategy.Search update (#362). The
        # branch="search" builder owns the entire Search payload
        # (PlacementTypes + subtype block). include_default=False: with
        # neither --search-strategy nor any --dyn-search-* detail flag,
        # Search is left untouched (returns None).
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
            bs: dict[str, object] = {}
            if dyn_search_block is not None:
                bs["Search"] = dyn_search_block
            if dyn_network_block is not None:
                bs["Network"] = dyn_network_block
            sub_block["BiddingStrategy"] = bs
    negative_keyword_shared_set_ids_obj = _array_of_integer_option(
        "--negative-keyword-shared-set-ids",
        negative_keyword_shared_set_ids,
        max_items=NEGATIVE_KEYWORD_SHARED_SET_IDS_MAX_ITEMS,
    )
    if negative_keyword_shared_set_ids_obj is not None:
        sub_block["NegativeKeywordSharedSetIds"] = negative_keyword_shared_set_ids_obj
