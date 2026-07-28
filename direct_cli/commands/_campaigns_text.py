"""TEXT_CAMPAIGN type-specific payload builder for campaigns add.

Extracted from ``direct_cli/commands/campaigns.py`` (issue #618,
step 6 of epic #602).  Only the ``add`` dispatch branch is
extracted here; the ``update`` path lives inside the shared
``text_family`` block (TEXT + UNIFIED + DYNAMIC) and will be
split when the DYNAMIC / UNIFIED steps (4+5) are merged.

``campaigns.py`` imports ``build_add_block`` so the CLI surface
is byte-for-byte identical to the former monolith.
"""

from typing import Any, Optional

from .._bidding_strategy import (
    TEXT_CAMPAIGN_NETWORK_STRATEGY_TO_WSDL_SUBTYPE,
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
    get_bidding_strategy_builder,
)
from ._campaigns_base import _route_cpa_flag


def build_add_block(
    campaign_data: dict[str, Any],
    parsed_settings: Optional[list],
    package_bidding_strategy_obj,
    counter_ids_obj,
    priority_goals_items,
    negative_keyword_shared_set_ids_obj,
    relevant_keywords_obj,
    goal_id,
    average_cpa,
    crr,
    bid_ceiling,
    search_strategy,
    search_placement_search_results,
    search_placement_product_gallery,
    search_placement_dynamic_places,
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
    network_strategy,
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
    attribution_model,
    tracking_params,
) -> None:
    """Build the TextCampaign add payload and write it into *campaign_data*.

    This is a verbatim extract of the ``if campaign_type_norm == "TEXT_CAMPAIGN":``
    branch from ``campaigns.add`` (issue #618).  The function mutates
    *campaign_data* in place, adding the ``"TextCampaign"`` key.
    """
    text_block: dict[str, Any] = {"Settings": parsed_settings or []}
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
        search_builder = get_bidding_strategy_builder("TEXT_CAMPAIGN", "add", "search")
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
                custom_period_auto_continue=(text_search_custom_period_auto_continue),
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
            text_search: dict[str, Any] = {
                "BiddingStrategyType": ((search_strategy or "HIGHEST_POSITION").upper())
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
                custom_period_auto_continue=(text_network_custom_period_auto_continue),
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
            text_network: dict[str, Any] = {
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
        text_block["NegativeKeywordSharedSetIds"] = negative_keyword_shared_set_ids_obj
    if tracking_params:
        text_block["TrackingParams"] = tracking_params
    campaign_data["TextCampaign"] = text_block
