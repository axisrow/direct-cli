"""UNIFIED_CAMPAIGN payload composition for ``campaigns add``/``update``.

``build_add_block`` was extracted verbatim from the former inline
``elif campaign_type_norm == "UNIFIED_CAMPAIGN":`` branch of
``direct_cli/commands/campaigns.py`` (issue #602, step 5 of the
per-campaign-type split). ``build_update_block`` was extracted from the
former inline UNIFIED paths of the shared text-family update block
(epic #961, campaigns track). The CLI surface is unchanged —
``campaigns.py`` delegates here.
"""

import click

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
from ..i18n import t
from ..utils import parse_priority_goals_spec, parse_setting_specs
from ._campaigns_base import (
    NEGATIVE_KEYWORD_SHARED_SET_IDS_MAX_ITEMS,
    _array_of_integer_option,
    _build_package_bidding_strategy,
    _priority_goals_update_items,
    _route_cpa_flag,
)


def build_add_block(
    params,
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

    ``params`` is a snapshot of every CLI parameter of the ``add``
    command; only the Unified-relevant flags are pulled out below.
    """
    search_strategy = params.search_strategy
    network_strategy = params.network_strategy
    goal_id = params.goal_id
    average_cpa = params.average_cpa
    crr = params.crr
    bid_ceiling = params.bid_ceiling
    unified_search_placement_maps = params.unified_search_placement_maps
    unified_search_placement_search_organization_list = (
        params.unified_search_placement_search_organization_list
    )
    unified_search_weekly_spend_limit = params.unified_search_weekly_spend_limit
    unified_search_custom_period_spend_limit = (
        params.unified_search_custom_period_spend_limit
    )
    unified_search_custom_period_start_date = (
        params.unified_search_custom_period_start_date
    )
    unified_search_custom_period_end_date = params.unified_search_custom_period_end_date
    unified_search_custom_period_auto_continue = (
        params.unified_search_custom_period_auto_continue
    )
    unified_search_average_cpc = params.unified_search_average_cpc
    unified_search_pay_cpa = params.unified_search_pay_cpa
    unified_search_exploration_min_budget = params.unified_search_exploration_min_budget
    unified_search_exploration_is_custom = params.unified_search_exploration_is_custom
    unified_network_weekly_spend_limit = params.unified_network_weekly_spend_limit
    unified_network_custom_period_spend_limit = (
        params.unified_network_custom_period_spend_limit
    )
    unified_network_custom_period_start_date = (
        params.unified_network_custom_period_start_date
    )
    unified_network_custom_period_end_date = (
        params.unified_network_custom_period_end_date
    )
    unified_network_custom_period_auto_continue = (
        params.unified_network_custom_period_auto_continue
    )
    unified_network_average_cpc = params.unified_network_average_cpc
    unified_network_cpa = params.unified_network_cpa
    unified_network_exploration_min_budget = (
        params.unified_network_exploration_min_budget
    )
    unified_network_exploration_is_custom = params.unified_network_exploration_is_custom
    search_placement_search_results = params.search_placement_search_results
    search_placement_product_gallery = params.search_placement_product_gallery
    search_placement_dynamic_places = params.search_placement_dynamic_places

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


def build_update_block(params, sub_block):
    """Fill ``sub_block`` for the UnifiedCampaign subtype of ``campaigns update``.

    Verbatim extract of the former inline UNIFIED paths of the shared
    text-family update block in ``campaigns.py`` (epic #961, campaigns
    track). ``params`` is the typed snapshot of every CLI parameter of the
    ``update`` command; only the UnifiedCampaign-relevant flags are pulled
    out below.
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
    search_strategy = params.search_strategy
    search_placement_search_results = params.search_placement_search_results
    search_placement_product_gallery = params.search_placement_product_gallery
    search_placement_dynamic_places = params.search_placement_dynamic_places
    network_strategy = params.network_strategy
    goal_id = params.goal_id
    average_cpa = params.average_cpa
    crr = params.crr
    bid_ceiling = params.bid_ceiling
    unified_search_placement_maps = params.unified_search_placement_maps
    unified_search_placement_search_organization_list = (
        params.unified_search_placement_search_organization_list
    )
    unified_search_weekly_spend_limit = params.unified_search_weekly_spend_limit
    unified_search_custom_period_spend_limit = (
        params.unified_search_custom_period_spend_limit
    )
    unified_search_custom_period_start_date = (
        params.unified_search_custom_period_start_date
    )
    unified_search_custom_period_end_date = params.unified_search_custom_period_end_date
    unified_search_custom_period_auto_continue = (
        params.unified_search_custom_period_auto_continue
    )
    unified_search_budget_type = params.unified_search_budget_type
    unified_search_average_cpc = params.unified_search_average_cpc
    unified_search_pay_cpa = params.unified_search_pay_cpa
    unified_search_exploration_min_budget = params.unified_search_exploration_min_budget
    unified_search_exploration_is_custom = params.unified_search_exploration_is_custom
    unified_network_weekly_spend_limit = params.unified_network_weekly_spend_limit
    unified_network_custom_period_spend_limit = (
        params.unified_network_custom_period_spend_limit
    )
    unified_network_custom_period_start_date = (
        params.unified_network_custom_period_start_date
    )
    unified_network_custom_period_end_date = (
        params.unified_network_custom_period_end_date
    )
    unified_network_custom_period_auto_continue = (
        params.unified_network_custom_period_auto_continue
    )
    unified_network_budget_type = params.unified_network_budget_type
    unified_network_average_cpc = params.unified_network_average_cpc
    unified_network_cpa = params.unified_network_cpa
    unified_network_exploration_min_budget = (
        params.unified_network_exploration_min_budget
    )
    unified_network_exploration_is_custom = params.unified_network_exploration_is_custom
    negative_keyword_shared_set_ids = params.negative_keyword_shared_set_ids

    parsed_settings = parse_setting_specs(list(settings))
    if parsed_settings:
        sub_block["Settings"] = parsed_settings
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
        campaign_label="UnifiedCampaign",
        require_platforms=False,
    )
    if package_bidding_strategy_obj is not None:
        # Issue #373: ``UnifiedCampaignUpdateItem.PriorityGoals`` is a
        # nillable sibling of ``UnifiedCampaignUpdateItem.PackageBiddingStrategy``
        # on the same ``xsd:sequence`` (no ``xsd:choice``). The UNIFIED
        # variant additionally conflicts with ``--counter-ids`` /
        # ``--attribution-model`` and the per-side typed strategy flags
        # (#363/#366) so user input is never silently dropped.
        package_incompatible: dict[str, object] = {
            "--counter-ids": counter_ids,
            "--attribution-model": attribution_model,
            # UnifiedCampaign.BiddingStrategy.Network typed flags must
            # conflict with PackageBiddingStrategy on update (#366) —
            # mirror DynamicTextCampaign behavior.
            "--network-strategy": network_strategy,
            "--unified-network-weekly-spend-limit": unified_network_weekly_spend_limit,
            "--unified-network-custom-period-spend-limit": (
                unified_network_custom_period_spend_limit
            ),
            "--unified-network-custom-period-start-date": (
                unified_network_custom_period_start_date
            ),
            "--unified-network-custom-period-end-date": (
                unified_network_custom_period_end_date
            ),
            "--unified-network-custom-period-auto-continue": (
                unified_network_custom_period_auto_continue
            ),
            "--unified-network-average-cpc": unified_network_average_cpc,
            "--unified-network-cpa": unified_network_cpa,
            "--unified-network-exploration-min-budget": (
                unified_network_exploration_min_budget
            ),
            "--unified-network-exploration-is-custom": (
                unified_network_exploration_is_custom
            ),
            "--unified-network-budget-type": unified_network_budget_type,
            # UnifiedCampaign.BiddingStrategy.Search typed flags (#363)
            # — mutually exclusive with PackageBiddingStrategy on update.
            "--search-strategy": search_strategy,
            "--search-placement-search-results": search_placement_search_results,
            "--search-placement-product-gallery": search_placement_product_gallery,
            "--search-placement-dynamic-places": search_placement_dynamic_places,
            "--goal-id": goal_id,
            "--average-cpa": average_cpa,
            "--crr": crr,
            "--bid-ceiling": bid_ceiling,
            "--unified-search-placement-maps": unified_search_placement_maps,
            "--unified-search-placement-search-organization-list": (
                unified_search_placement_search_organization_list
            ),
            "--unified-search-weekly-spend-limit": unified_search_weekly_spend_limit,
            "--unified-search-custom-period-spend-limit": (
                unified_search_custom_period_spend_limit
            ),
            "--unified-search-custom-period-start-date": (
                unified_search_custom_period_start_date
            ),
            "--unified-search-custom-period-end-date": (
                unified_search_custom_period_end_date
            ),
            "--unified-search-custom-period-auto-continue": (
                unified_search_custom_period_auto_continue
            ),
            "--unified-search-budget-type": unified_search_budget_type,
            "--unified-search-average-cpc": unified_search_average_cpc,
            "--unified-search-pay-cpa": unified_search_pay_cpa,
            "--unified-search-exploration-min-budget": (
                unified_search_exploration_min_budget
            ),
            "--unified-search-exploration-is-custom": (
                unified_search_exploration_is_custom
            ),
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
                    package_label="UnifiedCampaign",
                    arg0=", ".join(sorted(provided)),
                )
            )
        sub_block["PackageBiddingStrategy"] = package_bidding_strategy_obj
    else:
        # UnifiedCampaign.BiddingStrategy update — Network (#366) and
        # Search (#363). Shared legacy CPA flags are routed per-side
        # based on which subtype actually accepts the WSDL field
        # (mirrors the add path and TextCampaign update).
        # include_default=False: with neither --network-strategy /
        # --search-strategy nor any --unified-{network,search}-* /
        # shared CPA flag the corresponding side is left untouched
        # (returns None).
        _u_search_subtype_for_routing_up = (
            _UNIFIED_CAMPAIGN_SEARCH_STRATEGY_TO_WSDL_SUBTYPE.get(
                (search_strategy or "").upper()
            )
        )
        _u_network_subtype_for_routing_up = (
            UNIFIED_CAMPAIGN_NETWORK_STRATEGY_TO_WSDL_SUBTYPE.get(
                (network_strategy or "").upper()
            )
        )

        def _u_route_update(
            value, search_support: set, network_support: set, default: str
        ):
            """Route a shared CPA flag for UnifiedCampaign update (thin
            wrapper over the module-level ``_route_cpa_flag``, binding
            this block's Search/Network routing subtypes). Mirrors the
            add path (#544 C11)."""
            return _route_cpa_flag(
                value,
                _u_search_subtype_for_routing_up,
                _u_network_subtype_for_routing_up,
                search_support,
                network_support,
                default,
            )

        _u_default_side_up = (
            "network"
            if network_strategy is not None and search_strategy is None
            else "search"
        )
        _u_search_goal_id_up, _u_network_goal_id_up = _u_route_update(
            goal_id,
            _UNIFIED_SEARCH_SUPPORTS_GOAL_ID,
            _UNIFIED_NETWORK_GOAL_ID_SUBTYPES,
            default=_u_default_side_up,
        )
        _u_search_average_cpa_up, _u_network_average_cpa_up = _u_route_update(
            average_cpa,
            _UNIFIED_SEARCH_SUPPORTS_AVERAGE_CPA,
            _UNIFIED_NETWORK_AVERAGE_CPA_SUBTYPES,
            default=_u_default_side_up,
        )
        _u_search_crr_up, _u_network_crr_up = _u_route_update(
            crr,
            _UNIFIED_SEARCH_SUPPORTS_CRR,
            _UNIFIED_NETWORK_CRR_SUBTYPES,
            default=_u_default_side_up,
        )
        _u_search_bid_ceiling_up, _u_network_bid_ceiling_up = _u_route_update(
            bid_ceiling,
            _UNIFIED_SEARCH_SUPPORTS_BID_CEILING,
            _UNIFIED_NETWORK_BID_CEILING_SUBTYPES,
            default=_u_default_side_up,
        )

        # PriorityGoals: route to whichever side accepts it for the
        # chosen subtype. The Network builder writes via
        # sub_campaign_block; the Search builder does not write on
        # update (PriorityGoals placement on update is owned by #373).
        _u_search_uses_pg_up = (
            _u_search_subtype_for_routing_up in _UNIFIED_SEARCH_REQUIRES_PRIORITY_GOALS
        )
        _u_network_uses_pg_up = (
            _u_network_subtype_for_routing_up
            in _UNIFIED_NETWORK_REQUIRES_PRIORITY_GOALS
        )
        if _u_search_uses_pg_up or _u_network_uses_pg_up:
            _u_search_pg_items_up = (
                priority_goals_items if _u_search_uses_pg_up else None
            )
            _u_network_pg_items_up = (
                priority_goals_items if _u_network_uses_pg_up else None
            )
        else:
            _u_search_pg_items_up = None
            _u_network_pg_items_up = priority_goals_items

        unified_network_builder = get_bidding_strategy_builder(
            "UNIFIED_CAMPAIGN", "update", "network"
        )
        if unified_network_builder is not None:
            unified_network_block = unified_network_builder(
                network_strategy=network_strategy,
                goal_id=_u_network_goal_id_up,
                average_cpa=_u_network_average_cpa_up,
                crr=_u_network_crr_up,
                bid_ceiling=_u_network_bid_ceiling_up,
                weekly_spend_limit=unified_network_weekly_spend_limit,
                custom_period_spend_limit=unified_network_custom_period_spend_limit,
                custom_period_start_date=unified_network_custom_period_start_date,
                custom_period_end_date=unified_network_custom_period_end_date,
                custom_period_auto_continue=(
                    unified_network_custom_period_auto_continue
                ),
                budget_type=unified_network_budget_type,
                average_cpc=unified_network_average_cpc,
                cpa=unified_network_cpa,
                exploration_min_budget=unified_network_exploration_min_budget,
                exploration_is_custom=unified_network_exploration_is_custom,
                priority_goals_items=_u_network_pg_items_up,
                sub_campaign_block=sub_block,
                include_default=False,
                is_update=True,
            )
        else:
            unified_network_block = (
                {"BiddingStrategyType": network_strategy.upper()}
                if network_strategy is not None
                else None
            )

        unified_search_builder = get_bidding_strategy_builder(
            "UNIFIED_CAMPAIGN", "update", "search"
        )
        unified_search_block = None
        if unified_search_builder is not None:
            unified_search_block = unified_search_builder(
                search_strategy=search_strategy,
                search_placement_search_results=search_placement_search_results,
                search_placement_product_gallery=search_placement_product_gallery,
                search_placement_dynamic_places=search_placement_dynamic_places,
                search_placement_maps=unified_search_placement_maps,
                search_placement_search_organization_list=(
                    unified_search_placement_search_organization_list
                ),
                goal_id=_u_search_goal_id_up,
                average_cpa=_u_search_average_cpa_up,
                crr=_u_search_crr_up,
                bid_ceiling=_u_search_bid_ceiling_up,
                weekly_spend_limit=unified_search_weekly_spend_limit,
                custom_period_spend_limit=unified_search_custom_period_spend_limit,
                custom_period_start_date=unified_search_custom_period_start_date,
                custom_period_end_date=unified_search_custom_period_end_date,
                custom_period_auto_continue=(
                    unified_search_custom_period_auto_continue
                ),
                budget_type=unified_search_budget_type,
                average_cpc=unified_search_average_cpc,
                pay_cpa=unified_search_pay_cpa,
                exploration_min_budget=unified_search_exploration_min_budget,
                exploration_is_custom=unified_search_exploration_is_custom,
                priority_goals_items=_u_search_pg_items_up,
                sub_campaign_block=sub_block,
                include_default=False,
                is_update=True,
            )
        else:
            unified_search_block = (
                {"BiddingStrategyType": search_strategy.upper()}
                if search_strategy is not None
                else None
            )

        if unified_network_block is not None or unified_search_block is not None:
            bs_u: dict[str, object] = {}
            if unified_search_block is not None:
                bs_u["Search"] = unified_search_block
            if unified_network_block is not None:
                bs_u["Network"] = unified_network_block
            sub_block["BiddingStrategy"] = bs_u
    negative_keyword_shared_set_ids_obj = _array_of_integer_option(
        "--negative-keyword-shared-set-ids",
        negative_keyword_shared_set_ids,
        max_items=NEGATIVE_KEYWORD_SHARED_SET_IDS_MAX_ITEMS,
    )
    if negative_keyword_shared_set_ids_obj is not None:
        sub_block["NegativeKeywordSharedSetIds"] = negative_keyword_shared_set_ids_obj
