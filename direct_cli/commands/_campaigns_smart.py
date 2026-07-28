"""SMART_CAMPAIGN payload composition for ``campaigns add``/``update``.

Extracted verbatim from the former inline ``elif campaign_type_norm ==
"SMART_CAMPAIGN":`` branches of ``direct_cli/commands/campaigns.py``
(issue #602, step 3 of the per-campaign-type split). The CLI surface is
unchanged — ``campaigns.py`` delegates here.
"""

from __future__ import annotations

import click

from .._bidding_strategy import get_bidding_strategy_builder
from ..i18n import t
from ..utils import parse_priority_goals_spec, parse_setting_specs
from ._campaigns_base import (
    _build_smart_package_bidding_strategy,
    _priority_goals_update_items,
)


def build_add_block(
    p,
    campaign_data,
    parsed_settings,
    priority_goals_items,
    smart_package_bidding_strategy_obj,
):
    """Compose ``campaign_data['SmartCampaign']`` for ``campaigns add``.

    ``p`` is a snapshot of every CLI parameter of the ``add`` command
    (``dict(locals())``); only the Smart-relevant flags are pulled out below.
    """
    counter_id = p["counter_id"]
    search_strategy = p["search_strategy"]
    smart_search_average_cpc = p["smart_search_average_cpc"]
    smart_search_filter_average_cpc = p["smart_search_filter_average_cpc"]
    smart_search_average_cpa = p["smart_search_average_cpa"]
    smart_search_filter_average_cpa = p["smart_search_filter_average_cpa"]
    smart_search_cpa = p["smart_search_cpa"]
    smart_search_goal_id = p["smart_search_goal_id"]
    smart_search_weekly_spend_limit = p["smart_search_weekly_spend_limit"]
    smart_search_bid_ceiling = p["smart_search_bid_ceiling"]
    smart_search_reserve_return = p["smart_search_reserve_return"]
    smart_search_roi_coef = p["smart_search_roi_coef"]
    smart_search_profitability = p["smart_search_profitability"]
    smart_search_crr = p["smart_search_crr"]
    smart_search_cp_spend_limit = p["smart_search_cp_spend_limit"]
    smart_search_cp_start_date = p["smart_search_cp_start_date"]
    smart_search_cp_end_date = p["smart_search_cp_end_date"]
    smart_search_cp_auto_continue = p["smart_search_cp_auto_continue"]
    smart_search_exploration_min = p["smart_search_exploration_min"]
    smart_search_exploration_min_custom = p["smart_search_exploration_min_custom"]
    network_strategy = p["network_strategy"]
    smart_network_average_cpc = p["smart_network_average_cpc"]
    smart_network_filter_average_cpc = p["smart_network_filter_average_cpc"]
    smart_network_average_cpa = p["smart_network_average_cpa"]
    smart_network_filter_average_cpa = p["smart_network_filter_average_cpa"]
    smart_network_cpa = p["smart_network_cpa"]
    smart_network_goal_id = p["smart_network_goal_id"]
    smart_network_weekly_spend_limit = p["smart_network_weekly_spend_limit"]
    smart_network_bid_ceiling = p["smart_network_bid_ceiling"]
    smart_network_reserve_return = p["smart_network_reserve_return"]
    smart_network_roi_coef = p["smart_network_roi_coef"]
    smart_network_profitability = p["smart_network_profitability"]
    smart_network_crr = p["smart_network_crr"]
    smart_network_limit_percent = p["smart_network_limit_percent"]
    smart_network_cp_spend_limit = p["smart_network_cp_spend_limit"]
    smart_network_cp_start_date = p["smart_network_cp_start_date"]
    smart_network_cp_end_date = p["smart_network_cp_end_date"]
    smart_network_cp_auto_continue = p["smart_network_cp_auto_continue"]
    smart_network_exploration_min = p["smart_network_exploration_min"]
    smart_network_exploration_min_custom = p["smart_network_exploration_min_custom"]
    filter_average_cpc = p["filter_average_cpc"]
    attribution_model = p["attribution_model"]
    tracking_params = p["tracking_params"]

    # WSDL SmartCampaignAddItem.CounterId is minOccurs=1
    # (issue #198 H6).
    if counter_id is None:
        raise click.UsageError(
            t(
                "--counter-id is required for SMART_CAMPAIGN "
                "(WSDL SmartCampaignAddItem.CounterId minOccurs=1)"
            )
        )
    smart_campaign: dict[str, object] = {"CounterId": counter_id}
    if smart_package_bidding_strategy_obj is not None:
        smart_campaign["PackageBiddingStrategy"] = smart_package_bidding_strategy_obj
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
            "--smart-network-filter-average-cpc": (smart_network_filter_average_cpc),
            "--smart-network-average-cpa": smart_network_average_cpa,
            "--smart-network-filter-average-cpa": (smart_network_filter_average_cpa),
            "--smart-network-cpa": smart_network_cpa,
            "--smart-network-goal-id": smart_network_goal_id,
            "--smart-network-weekly-spend-limit": (smart_network_weekly_spend_limit),
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
        network_block: dict | None
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


def build_update_block(p, sub_block):
    """Fill ``sub_block`` for the SmartCampaign subtype of ``campaigns update``.

    ``p`` is a snapshot of every CLI parameter of the ``update`` command.
    """
    settings = p["settings"]
    counter_id = p["counter_id"]
    priority_goals = p["priority_goals"]
    attribution_model = p["attribution_model"]
    package_strategy_id = p["package_strategy_id"]
    package_strategy_from_campaign_id = p["package_strategy_from_campaign_id"]
    package_platform_search = p["package_platform_search"]
    package_platform_network = p["package_platform_network"]
    search_strategy = p["search_strategy"]
    network_strategy = p["network_strategy"]
    smart_search_average_cpc = p["smart_search_average_cpc"]
    smart_search_filter_average_cpc = p["smart_search_filter_average_cpc"]
    smart_search_average_cpa = p["smart_search_average_cpa"]
    smart_search_filter_average_cpa = p["smart_search_filter_average_cpa"]
    smart_search_cpa = p["smart_search_cpa"]
    smart_search_goal_id = p["smart_search_goal_id"]
    smart_search_weekly_spend_limit = p["smart_search_weekly_spend_limit"]
    smart_search_bid_ceiling = p["smart_search_bid_ceiling"]
    smart_search_reserve_return = p["smart_search_reserve_return"]
    smart_search_roi_coef = p["smart_search_roi_coef"]
    smart_search_profitability = p["smart_search_profitability"]
    smart_search_crr = p["smart_search_crr"]
    smart_search_cp_spend_limit = p["smart_search_cp_spend_limit"]
    smart_search_cp_start_date = p["smart_search_cp_start_date"]
    smart_search_cp_end_date = p["smart_search_cp_end_date"]
    smart_search_cp_auto_continue = p["smart_search_cp_auto_continue"]
    smart_search_exploration_min = p["smart_search_exploration_min"]
    smart_search_exploration_min_custom = p["smart_search_exploration_min_custom"]
    smart_search_budget_type = p["smart_search_budget_type"]
    smart_network_average_cpc = p["smart_network_average_cpc"]
    smart_network_filter_average_cpc = p["smart_network_filter_average_cpc"]
    smart_network_average_cpa = p["smart_network_average_cpa"]
    smart_network_filter_average_cpa = p["smart_network_filter_average_cpa"]
    smart_network_cpa = p["smart_network_cpa"]
    smart_network_goal_id = p["smart_network_goal_id"]
    smart_network_weekly_spend_limit = p["smart_network_weekly_spend_limit"]
    smart_network_bid_ceiling = p["smart_network_bid_ceiling"]
    smart_network_reserve_return = p["smart_network_reserve_return"]
    smart_network_roi_coef = p["smart_network_roi_coef"]
    smart_network_profitability = p["smart_network_profitability"]
    smart_network_crr = p["smart_network_crr"]
    smart_network_limit_percent = p["smart_network_limit_percent"]
    smart_network_cp_spend_limit = p["smart_network_cp_spend_limit"]
    smart_network_cp_start_date = p["smart_network_cp_start_date"]
    smart_network_cp_end_date = p["smart_network_cp_end_date"]
    smart_network_cp_auto_continue = p["smart_network_cp_auto_continue"]
    smart_network_exploration_min = p["smart_network_exploration_min"]
    smart_network_exploration_min_custom = p["smart_network_exploration_min_custom"]
    smart_network_budget_type = p["smart_network_budget_type"]

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
            flag for flag, value in package_incompatible.items() if value is not None
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
                    "SmartCampaign.PackageBiddingStrategy cannot be "
                    "combined with {arg0}"
                ).format(arg0=", ".join(sorted(provided)))
            )
        sub_block["PackageBiddingStrategy"] = smart_package_bidding_strategy_obj
    elif smart_search_block is not None or smart_network_block is not None:
        bidding_strategy: dict[str, object] = {}
        if smart_search_block is not None:
            bidding_strategy["Search"] = smart_search_block
        if smart_network_block is not None:
            bidding_strategy["Network"] = smart_network_block
        sub_block["BiddingStrategy"] = bidding_strategy
