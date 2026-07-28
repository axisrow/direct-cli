"""UNIFIED_CAMPAIGN payload composition for ``campaigns add``.

Extracted verbatim from the former inline ``elif campaign_type_norm ==
"UNIFIED_CAMPAIGN":`` branch of ``direct_cli/commands/campaigns.py``
(issue #602, step 5 of the per-campaign-type split). The CLI surface is
unchanged — ``campaigns.py`` delegates here.
"""

from .._bidding_strategy import (
    _UNIFIED_CAMPAIGN_SEARCH_STRATEGY_TO_WSDL_SUBTYPE,
    _UNIFIED_NETWORK_AVERAGE_CPA_SUBTYPES,
    _UNIFIED_NETWORK_BID_CEILING_SUBTYPES,
    _UNIFIED_NETWORK_CRR_SUBTYPES,
    _UNIFIED_NETWORK_GOAL_ID_SUBTYPES,
    _UNIFIED_NETWORK_REQUIRES_PRIORITY_GOALS,
    _UNIFIED_SEARCH_REQUIRES_PRIORITY_GOALS,
    _UNIFIED_SEARCH_SUPPORTS_AVERAGE_CPA,
    _UNIFIED_SEARCH_SUPPORTS_BID_CEILING,
    _UNIFIED_SEARCH_SUPPORTS_CRR,
    _UNIFIED_SEARCH_SUPPORTS_GOAL_ID,
    UNIFIED_CAMPAIGN_NETWORK_STRATEGY_TO_WSDL_SUBTYPE,
    get_bidding_strategy_builder,
)
from ._campaigns_base import _route_cpa_flag


def build_add_block(
    p,
    campaign_data,
    parsed_settings,
    counter_ids_obj,
    priority_goals_items,
    package_bidding_strategy_obj,
    negative_keyword_shared_set_ids_obj,
    tracking_params,
    attribution_model,
):
    """Compose ``campaign_data['UnifiedCampaign']`` for ``campaigns add``.

    ``p`` is a snapshot of every CLI parameter of the ``add`` command
    (``dict(locals())``); only the Unified-relevant flags are pulled out
    below.
    """
    search_strategy = p["search_strategy"]
    network_strategy = p["network_strategy"]
    goal_id = p["goal_id"]
    average_cpa = p["average_cpa"]
    crr = p["crr"]
    bid_ceiling = p["bid_ceiling"]
    unified_search_placement_maps = p["unified_search_placement_maps"]
    unified_search_placement_search_organization_list = p[
        "unified_search_placement_search_organization_list"
    ]
    unified_search_weekly_spend_limit = p["unified_search_weekly_spend_limit"]
    unified_search_custom_period_spend_limit = p[
        "unified_search_custom_period_spend_limit"
    ]
    unified_search_custom_period_start_date = p[
        "unified_search_custom_period_start_date"
    ]
    unified_search_custom_period_end_date = p["unified_search_custom_period_end_date"]
    unified_search_custom_period_auto_continue = p[
        "unified_search_custom_period_auto_continue"
    ]
    unified_search_average_cpc = p["unified_search_average_cpc"]
    unified_search_pay_cpa = p["unified_search_pay_cpa"]
    unified_search_exploration_min_budget = p["unified_search_exploration_min_budget"]
    unified_search_exploration_is_custom = p["unified_search_exploration_is_custom"]
    unified_network_weekly_spend_limit = p["unified_network_weekly_spend_limit"]
    unified_network_custom_period_spend_limit = p[
        "unified_network_custom_period_spend_limit"
    ]
    unified_network_custom_period_start_date = p[
        "unified_network_custom_period_start_date"
    ]
    unified_network_custom_period_end_date = p["unified_network_custom_period_end_date"]
    unified_network_custom_period_auto_continue = p[
        "unified_network_custom_period_auto_continue"
    ]
    unified_network_average_cpc = p["unified_network_average_cpc"]
    unified_network_cpa = p["unified_network_cpa"]
    unified_network_exploration_min_budget = p["unified_network_exploration_min_budget"]
    unified_network_exploration_is_custom = p["unified_network_exploration_is_custom"]
    search_placement_search_results = p["search_placement_search_results"]
    search_placement_product_gallery = p["search_placement_product_gallery"]
    search_placement_dynamic_places = p["search_placement_dynamic_places"]

    unified_block: dict[str, object] = {"Settings": parsed_settings or []}
    if package_bidding_strategy_obj is not None:
        unified_block["PackageBiddingStrategy"] = package_bidding_strategy_obj
    else:
        # Issue #366 + #363: full typed-flag support for the 10
        # strategy subtype families on both
        # UnifiedCampaign.BiddingStrategy.Network (#366) and
        # UnifiedCampaign.BiddingStrategy.Search (#363). Mirrors
        # the TextCampaign pattern: shared legacy CPA flags
        # (``--goal-id``/``--average-cpa``/``--crr``/``--bid-ceiling``)
        # are routed per-side based on which subtype actually
        # accepts the WSDL field. include_default=True keeps the
        # legacy defaults (HIGHEST_POSITION for Search,
        # SERVING_OFF for Network) when neither side is provided.
        _u_search_subtype_for_routing = (
            _UNIFIED_CAMPAIGN_SEARCH_STRATEGY_TO_WSDL_SUBTYPE.get(
                (search_strategy or "").upper()
            )
        )
        _u_network_subtype_for_routing = (
            UNIFIED_CAMPAIGN_NETWORK_STRATEGY_TO_WSDL_SUBTYPE.get(
                (network_strategy or "").upper()
            )
        )

        def _u_route(value, search_support: set, network_support: set, default: str):
            """Route a shared CPA flag for UnifiedCampaign add (thin wrapper
            over the module-level ``_route_cpa_flag``)."""
            return _route_cpa_flag(
                value,
                _u_search_subtype_for_routing,
                _u_network_subtype_for_routing,
                search_support,
                network_support,
                default,
            )

        # Default-side routing for unrecognized flag/strategy
        # combinations: prefer the side whose strategy was
        # explicitly chosen so the rejection comes from the
        # builder the user is actually targeting. When neither
        # side is explicitly chosen, fall back to Search to keep
        # the canonical "CPA-shaped strategy required" error.
        _u_default_side = (
            "network"
            if network_strategy is not None and search_strategy is None
            else "search"
        )
        _u_search_goal_id, _u_network_goal_id = _u_route(
            goal_id,
            _UNIFIED_SEARCH_SUPPORTS_GOAL_ID,
            _UNIFIED_NETWORK_GOAL_ID_SUBTYPES,
            default=_u_default_side,
        )
        _u_search_average_cpa, _u_network_average_cpa = _u_route(
            average_cpa,
            _UNIFIED_SEARCH_SUPPORTS_AVERAGE_CPA,
            _UNIFIED_NETWORK_AVERAGE_CPA_SUBTYPES,
            default=_u_default_side,
        )
        _u_search_crr, _u_network_crr = _u_route(
            crr,
            _UNIFIED_SEARCH_SUPPORTS_CRR,
            _UNIFIED_NETWORK_CRR_SUBTYPES,
            default=_u_default_side,
        )
        _u_search_bid_ceiling, _u_network_bid_ceiling = _u_route(
            bid_ceiling,
            _UNIFIED_SEARCH_SUPPORTS_BID_CEILING,
            _UNIFIED_NETWORK_BID_CEILING_SUBTYPES,
            default=_u_default_side,
        )

        # PriorityGoals: route to whichever side accepts it.
        # When BOTH sides chose a multi-goal/MaxProfit subtype the
        # same items satisfy both builders (the parent placement
        # via ``sub_campaign_block`` is idempotent). When the
        # user supplies PriorityGoals without explicitly choosing
        # either side's strategy (#373: WSDL-valid standalone
        # case), suppress per-side wiring entirely — PriorityGoals
        # lands on the parent ``UnifiedCampaign.PriorityGoals``
        # sibling further below and the builders fall back to
        # the HIGHEST_POSITION / SERVING_OFF defaults. The
        # upstream guard already raises a clear error when a
        # per-side strategy was explicitly chosen with a subtype
        # outside the multi-goal / MaxProfit set.
        _u_search_uses_priority_goals = (
            _u_search_subtype_for_routing in _UNIFIED_SEARCH_REQUIRES_PRIORITY_GOALS
        )
        _u_network_uses_priority_goals = (
            _u_network_subtype_for_routing in _UNIFIED_NETWORK_REQUIRES_PRIORITY_GOALS
        )
        _u_search_priority_goals_items = (
            priority_goals_items if _u_search_uses_priority_goals else None
        )
        _u_network_priority_goals_items = (
            priority_goals_items if _u_network_uses_priority_goals else None
        )

        unified_search_builder = get_bidding_strategy_builder(
            "UNIFIED_CAMPAIGN", "add", "search"
        )
        if unified_search_builder is not None:
            unified_search = unified_search_builder(
                search_strategy=search_strategy,
                search_placement_search_results=(search_placement_search_results),
                search_placement_product_gallery=(search_placement_product_gallery),
                search_placement_dynamic_places=(search_placement_dynamic_places),
                search_placement_maps=unified_search_placement_maps,
                search_placement_search_organization_list=(
                    unified_search_placement_search_organization_list
                ),
                goal_id=_u_search_goal_id,
                average_cpa=_u_search_average_cpa,
                crr=_u_search_crr,
                bid_ceiling=_u_search_bid_ceiling,
                weekly_spend_limit=unified_search_weekly_spend_limit,
                custom_period_spend_limit=(unified_search_custom_period_spend_limit),
                custom_period_start_date=(unified_search_custom_period_start_date),
                custom_period_end_date=(unified_search_custom_period_end_date),
                custom_period_auto_continue=(
                    unified_search_custom_period_auto_continue
                ),
                budget_type=None,
                average_cpc=unified_search_average_cpc,
                pay_cpa=unified_search_pay_cpa,
                exploration_min_budget=(unified_search_exploration_min_budget),
                exploration_is_custom=(unified_search_exploration_is_custom),
                priority_goals_items=_u_search_priority_goals_items,
                sub_campaign_block=unified_block,
                include_default=True,
                is_update=False,
            )
        else:
            unified_search = {"BiddingStrategyType": "HIGHEST_POSITION"}
        unified_network_builder = get_bidding_strategy_builder(
            "UNIFIED_CAMPAIGN", "add", "network"
        )
        if unified_network_builder is not None:
            unified_network = unified_network_builder(
                network_strategy=network_strategy,
                goal_id=_u_network_goal_id,
                average_cpa=_u_network_average_cpa,
                crr=_u_network_crr,
                bid_ceiling=_u_network_bid_ceiling,
                weekly_spend_limit=unified_network_weekly_spend_limit,
                custom_period_spend_limit=(unified_network_custom_period_spend_limit),
                custom_period_start_date=(unified_network_custom_period_start_date),
                custom_period_end_date=(unified_network_custom_period_end_date),
                custom_period_auto_continue=(
                    unified_network_custom_period_auto_continue
                ),
                budget_type=None,
                average_cpc=unified_network_average_cpc,
                cpa=unified_network_cpa,
                exploration_min_budget=(unified_network_exploration_min_budget),
                exploration_is_custom=(unified_network_exploration_is_custom),
                priority_goals_items=_u_network_priority_goals_items,
                sub_campaign_block=unified_block,
                include_default=True,
                is_update=False,
            )
        else:
            unified_network = {
                "BiddingStrategyType": (network_strategy or "SERVING_OFF")
            }
        unified_block["BiddingStrategy"] = {
            "Search": unified_search,
            "Network": unified_network,
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
