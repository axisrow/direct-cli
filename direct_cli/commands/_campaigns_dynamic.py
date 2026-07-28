"""DYNAMIC_TEXT_CAMPAIGN add-payload builder (issue #602, step 4).

This module holds the ``build_add_block`` function that constructs the
``DynamicTextCampaign`` subtype block for the ``campaigns add`` command.
It was extracted from the former monolithic
``direct_cli/commands/campaigns.py`` to reduce its size while keeping
the CLI surface byte-for-byte identical.

The update-path DynamicTextCampaign logic lives inside the shared
``text_family`` block in ``campaigns.py`` (TEXT + UNIFIED + DYNAMIC
share one ``is_unified`` / ``is_dynamic``-branched block); extracting
it is deferred to a future sub-issue.
"""

from __future__ import annotations

from typing import Any

import click

from .._bidding_strategy import get_bidding_strategy_builder
from ..i18n import t


def build_add_block(
    p: dict[str, Any],
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

    *p* is the ``dict(locals())`` snapshot from the ``add`` command
    so that every flag value is available by name without an
    ever-growing formal parameter list.
    """
    # Unpack the flag values that this builder needs from the
    # locals snapshot.  Typed-flags used only by DynamicTextCampaign
    # are prefixed ``dyn_*``; shared legacy CPA flags are bare.
    network_strategy = p["network_strategy"]
    search_strategy = p["search_strategy"]
    search_placement_search_results = p["search_placement_search_results"]
    search_placement_product_gallery = p["search_placement_product_gallery"]
    search_placement_dynamic_places = p["search_placement_dynamic_places"]
    average_cpa = p["average_cpa"]
    goal_id = p["goal_id"]
    crr = p["crr"]
    bid_ceiling = p["bid_ceiling"]
    tracking_params = p["tracking_params"]
    attribution_model = p["attribution_model"]

    dyn_network_weekly_spend_limit = p["dyn_network_weekly_spend_limit"]
    dyn_network_bid_ceiling = p["dyn_network_bid_ceiling"]
    dyn_network_custom_period_spend_limit = p["dyn_network_custom_period_spend_limit"]
    dyn_network_custom_period_start_date = p["dyn_network_custom_period_start_date"]
    dyn_network_custom_period_end_date = p["dyn_network_custom_period_end_date"]
    dyn_network_custom_period_auto_continue = p[
        "dyn_network_custom_period_auto_continue"
    ]
    dyn_network_average_cpc = p["dyn_network_average_cpc"]
    dyn_network_average_cpa = p["dyn_network_average_cpa"]
    dyn_network_cpa = p["dyn_network_cpa"]
    dyn_network_goal_id = p["dyn_network_goal_id"]
    dyn_network_crr = p["dyn_network_crr"]
    dyn_network_clicks_per_week = p["dyn_network_clicks_per_week"]
    dyn_network_limit_percent = p["dyn_network_limit_percent"]
    dyn_network_reserve_return = p["dyn_network_reserve_return"]
    dyn_network_roi_coef = p["dyn_network_roi_coef"]
    dyn_network_profitability = p["dyn_network_profitability"]
    dyn_network_exploration_budget = p["dyn_network_exploration_budget"]
    dyn_network_exploration_budget_custom = p["dyn_network_exploration_budget_custom"]

    dyn_search_weekly_spend_limit = p["dyn_search_weekly_spend_limit"]
    dyn_search_bid_ceiling = p["dyn_search_bid_ceiling"]
    dyn_search_custom_period_spend_limit = p["dyn_search_custom_period_spend_limit"]
    dyn_search_custom_period_start_date = p["dyn_search_custom_period_start_date"]
    dyn_search_custom_period_end_date = p["dyn_search_custom_period_end_date"]
    dyn_search_custom_period_auto_continue = p["dyn_search_custom_period_auto_continue"]
    dyn_search_average_cpc = p["dyn_search_average_cpc"]
    dyn_search_average_cpa = p["dyn_search_average_cpa"]
    dyn_search_cpa = p["dyn_search_cpa"]
    dyn_search_goal_id = p["dyn_search_goal_id"]
    dyn_search_crr = p["dyn_search_crr"]
    dyn_search_clicks_per_week = p["dyn_search_clicks_per_week"]
    dyn_search_reserve_return = p["dyn_search_reserve_return"]
    dyn_search_roi_coef = p["dyn_search_roi_coef"]
    dyn_search_profitability = p["dyn_search_profitability"]
    dyn_search_exploration_budget = p["dyn_search_exploration_budget"]
    dyn_search_exploration_budget_custom = p["dyn_search_exploration_budget_custom"]

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
        dyn_block["NegativeKeywordSharedSetIds"] = negative_keyword_shared_set_ids_obj
    if tracking_params:
        dyn_block["TrackingParams"] = tracking_params
    campaign_data["DynamicTextCampaign"] = dyn_block
