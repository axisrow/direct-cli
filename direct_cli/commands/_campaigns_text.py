"""TEXT_CAMPAIGN type-specific payload builders for campaigns add/update.

``build_add_block`` was extracted from ``direct_cli/commands/campaigns.py``
(issue #618, step 6 of epic #602).  ``build_update_block`` was extracted
from the former inline TEXT paths of the shared text-family update block
(epic #961, campaigns track).  The CLI surface is byte-for-byte identical
to the former monolith — ``campaigns.py`` delegates here.
"""

import click
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
from ..i18n import t
from ..utils import parse_priority_goals_spec, parse_setting_specs
from ._campaigns_base import (
    NEGATIVE_KEYWORD_SHARED_SET_IDS_MAX_ITEMS,
    _array_of_integer_option,
    _build_package_bidding_strategy,
    _build_relevant_keywords,
    _priority_goals_update_items,
    _route_cpa_flag,
)


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


def build_update_block(params, sub_block):
    """Fill ``sub_block`` for the TextCampaign subtype of ``campaigns update``.

    Verbatim extract of the former inline TEXT paths of the shared
    text-family update block in ``campaigns.py`` (epic #961, campaigns
    track). ``params`` is the typed snapshot of every CLI parameter of the
    ``update`` command; only the TextCampaign-relevant flags are pulled out
    below.
    """
    settings = params.settings
    counter_ids = params.counter_ids
    priority_goals = params.priority_goals
    relevant_keywords_budget_percent = params.relevant_keywords_budget_percent
    relevant_keywords_mode = params.relevant_keywords_mode
    relevant_keywords_optimize_goal_id = params.relevant_keywords_optimize_goal_id
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
    text_search_weekly_spend_limit = params.text_search_weekly_spend_limit
    text_search_custom_period_spend_limit = params.text_search_custom_period_spend_limit
    text_search_custom_period_start_date = params.text_search_custom_period_start_date
    text_search_custom_period_end_date = params.text_search_custom_period_end_date
    text_search_custom_period_auto_continue = (
        params.text_search_custom_period_auto_continue
    )
    text_search_budget_type = params.text_search_budget_type
    text_search_average_cpc = params.text_search_average_cpc
    text_search_pay_cpa = params.text_search_pay_cpa
    text_search_clicks_per_week = params.text_search_clicks_per_week
    text_search_reserve_return = params.text_search_reserve_return
    text_search_roi_coef = params.text_search_roi_coef
    text_search_profitability = params.text_search_profitability
    text_search_exploration_min_budget = params.text_search_exploration_min_budget
    text_search_exploration_is_custom = params.text_search_exploration_is_custom
    text_network_weekly_spend_limit = params.text_network_weekly_spend_limit
    text_network_custom_period_spend_limit = (
        params.text_network_custom_period_spend_limit
    )
    text_network_custom_period_start_date = params.text_network_custom_period_start_date
    text_network_custom_period_end_date = params.text_network_custom_period_end_date
    text_network_custom_period_auto_continue = (
        params.text_network_custom_period_auto_continue
    )
    text_network_budget_type = params.text_network_budget_type
    text_network_average_cpc = params.text_network_average_cpc
    text_network_pay_cpa = params.text_network_pay_cpa
    text_network_clicks_per_week = params.text_network_clicks_per_week
    text_network_reserve_return = params.text_network_reserve_return
    text_network_roi_coef = params.text_network_roi_coef
    text_network_profitability = params.text_network_profitability
    text_network_exploration_min_budget = params.text_network_exploration_min_budget
    text_network_exploration_is_custom = params.text_network_exploration_is_custom
    text_network_limit_percent = params.text_network_limit_percent
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
    relevant_keywords_obj = _build_relevant_keywords(
        relevant_keywords_budget_percent,
        relevant_keywords_mode,
        relevant_keywords_optimize_goal_id,
        require_budget_percent=False,
    )
    if relevant_keywords_obj is not None:
        sub_block["RelevantKeywords"] = relevant_keywords_obj
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
        campaign_label="TextCampaign",
        require_platforms=False,
    )
    if package_bidding_strategy_obj is not None:
        # Issue #373: ``UnifiedCampaignUpdateItem.PriorityGoals`` is a
        # nillable sibling of ``PackageBiddingStrategy`` on the same
        # ``xsd:sequence`` (no ``xsd:choice``), so TextCampaign keeps the
        # mutex: any typed strategy detail flag combined with
        # PackageBiddingStrategy on update is rejected so user input is
        # never silently dropped.
        package_incompatible: dict[str, object] = {
            "--priority-goals": priority_goals,
            "--search-strategy": search_strategy,
            "--search-placement-search-results": search_placement_search_results,
            "--search-placement-product-gallery": search_placement_product_gallery,
            "--search-placement-dynamic-places": search_placement_dynamic_places,
            "--goal-id": goal_id,
            "--average-cpa": average_cpa,
            "--crr": crr,
            "--bid-ceiling": bid_ceiling,
            "--text-search-weekly-spend-limit": text_search_weekly_spend_limit,
            "--text-search-custom-period-spend-limit": (
                text_search_custom_period_spend_limit
            ),
            "--text-search-custom-period-start-date": (
                text_search_custom_period_start_date
            ),
            "--text-search-custom-period-end-date": (
                text_search_custom_period_end_date
            ),
            "--text-search-custom-period-auto-continue": (
                text_search_custom_period_auto_continue
            ),
            "--text-search-budget-type": text_search_budget_type,
            "--text-search-average-cpc": text_search_average_cpc,
            "--text-search-pay-cpa": text_search_pay_cpa,
            "--text-search-clicks-per-week": text_search_clicks_per_week,
            "--text-search-reserve-return": text_search_reserve_return,
            "--text-search-roi-coef": text_search_roi_coef,
            "--text-search-profitability": text_search_profitability,
            "--text-search-exploration-min-budget": (
                text_search_exploration_min_budget
            ),
            "--text-search-exploration-is-custom": (text_search_exploration_is_custom),
            # Issue #364: TextCampaign Network typed flags must conflict
            # with PackageBiddingStrategy on update for the same reason.
            "--network-strategy": network_strategy,
            "--text-network-weekly-spend-limit": text_network_weekly_spend_limit,
            "--text-network-custom-period-spend-limit": (
                text_network_custom_period_spend_limit
            ),
            "--text-network-custom-period-start-date": (
                text_network_custom_period_start_date
            ),
            "--text-network-custom-period-end-date": (
                text_network_custom_period_end_date
            ),
            "--text-network-custom-period-auto-continue": (
                text_network_custom_period_auto_continue
            ),
            "--text-network-budget-type": text_network_budget_type,
            "--text-network-average-cpc": text_network_average_cpc,
            "--text-network-pay-cpa": text_network_pay_cpa,
            "--text-network-clicks-per-week": text_network_clicks_per_week,
            "--text-network-reserve-return": text_network_reserve_return,
            "--text-network-roi-coef": text_network_roi_coef,
            "--text-network-profitability": text_network_profitability,
            "--text-network-exploration-min-budget": (
                text_network_exploration_min_budget
            ),
            "--text-network-exploration-is-custom": (
                text_network_exploration_is_custom
            ),
            "--text-network-limit-percent": text_network_limit_percent,
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
                    package_label="TextCampaign",
                    arg0=", ".join(sorted(provided)),
                )
            )
        sub_block["PackageBiddingStrategy"] = package_bidding_strategy_obj
    else:
        # Issue #361/#364: full typed-flag support for the 12 strategy
        # families on TextCampaign.BiddingStrategy on update. The
        # branch="search" / branch="network" builders own each half of the
        # Bidding Strategy. The shared legacy CPA flags and
        # ``--priority-goals`` are routed per-side, per-flag against the
        # actual WSDL field-support sets (mirrors the add path).
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

        def _route_update(
            value, search_support: set, network_support: set, default: str
        ):
            """Route a shared CPA flag for TextCampaign update (thin
            wrapper over the module-level ``_route_cpa_flag``, binding
            this block's Search/Network routing subtypes). Mirrors the
            add path (#544 C11)."""
            return _route_cpa_flag(
                value,
                _search_subtype_for_routing,
                _network_subtype_for_routing,
                search_support,
                network_support,
                default,
            )

        _search_goal_id, _network_goal_id = _route_update(
            goal_id,
            _TEXT_SEARCH_SUPPORTS_GOAL_ID,
            _TEXT_NETWORK_GOAL_ID_SUBTYPES,
            default="search",
        )
        _search_average_cpa, _network_average_cpa = _route_update(
            average_cpa,
            _TEXT_SEARCH_SUPPORTS_AVERAGE_CPA,
            _TEXT_NETWORK_AVERAGE_CPA_SUBTYPES,
            default="search",
        )
        _search_crr, _network_crr = _route_update(
            crr,
            _TEXT_SEARCH_SUPPORTS_CRR,
            _TEXT_NETWORK_CRR_SUBTYPES,
            default="search",
        )
        _search_bid_ceiling, _network_bid_ceiling = _route_update(
            bid_ceiling,
            _TEXT_SEARCH_SUPPORTS_BID_CEILING,
            _TEXT_NETWORK_BID_CEILING_SUBTYPES,
            default="search",
        )

        # PriorityGoals routing on update mirrors add: both sides may
        # simultaneously belong to the multi-goals family and must each
        # see the items for their own required-field check (the parent
        # placement on update is handled by the dedicated
        # PriorityGoalsUpdateSetting shape earlier in this branch, so
        # the builders only validate scope without writing to sub_block
        # here).
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
            _search_priority_goals_items = priority_goals_items
            _network_priority_goals_items = None

        search_builder = get_bidding_strategy_builder(
            "TEXT_CAMPAIGN", "update", "search"
        )
        if search_builder is not None:
            text_search = search_builder(
                search_strategy=search_strategy,
                search_placement_search_results=search_placement_search_results,
                search_placement_product_gallery=search_placement_product_gallery,
                search_placement_dynamic_places=search_placement_dynamic_places,
                goal_id=_search_goal_id,
                average_cpa=_search_average_cpa,
                crr=_search_crr,
                bid_ceiling=_search_bid_ceiling,
                weekly_spend_limit=text_search_weekly_spend_limit,
                custom_period_spend_limit=text_search_custom_period_spend_limit,
                custom_period_start_date=text_search_custom_period_start_date,
                custom_period_end_date=text_search_custom_period_end_date,
                custom_period_auto_continue=text_search_custom_period_auto_continue,
                budget_type=text_search_budget_type,
                average_cpc=text_search_average_cpc,
                pay_cpa=text_search_pay_cpa,
                clicks_per_week=text_search_clicks_per_week,
                reserve_return=text_search_reserve_return,
                roi_coef=text_search_roi_coef,
                profitability=text_search_profitability,
                exploration_min_budget=text_search_exploration_min_budget,
                exploration_is_custom=text_search_exploration_is_custom,
                priority_goals_items=_search_priority_goals_items,
                sub_campaign_block=sub_block,
                include_default=False,
                is_update=True,
            )
        else:
            text_search = (
                {"BiddingStrategyType": (search_strategy.upper())}
                if search_strategy is not None
                else None
            )

        network_builder = get_bidding_strategy_builder(
            "TEXT_CAMPAIGN", "update", "network"
        )
        if network_builder is not None:
            text_network = network_builder(
                network_strategy=network_strategy,
                goal_id=_network_goal_id,
                average_cpa=_network_average_cpa,
                crr=_network_crr,
                bid_ceiling=_network_bid_ceiling,
                weekly_spend_limit=text_network_weekly_spend_limit,
                custom_period_spend_limit=text_network_custom_period_spend_limit,
                custom_period_start_date=text_network_custom_period_start_date,
                custom_period_end_date=text_network_custom_period_end_date,
                custom_period_auto_continue=text_network_custom_period_auto_continue,
                budget_type=text_network_budget_type,
                average_cpc=text_network_average_cpc,
                pay_cpa=text_network_pay_cpa,
                clicks_per_week=text_network_clicks_per_week,
                reserve_return=text_network_reserve_return,
                roi_coef=text_network_roi_coef,
                profitability=text_network_profitability,
                exploration_min_budget=text_network_exploration_min_budget,
                exploration_is_custom=text_network_exploration_is_custom,
                limit_percent=text_network_limit_percent,
                priority_goals_items=_network_priority_goals_items,
                sub_campaign_block=sub_block,
                include_default=False,
                is_update=True,
            )
        else:
            text_network = (
                {"BiddingStrategyType": (network_strategy.upper())}
                if network_strategy is not None
                else None
            )

        bidding_strategy_block: dict[str, object] = {}
        if text_search is not None:
            bidding_strategy_block["Search"] = text_search
        if text_network is not None:
            bidding_strategy_block["Network"] = text_network
        if bidding_strategy_block:
            sub_block["BiddingStrategy"] = bidding_strategy_block
    negative_keyword_shared_set_ids_obj = _array_of_integer_option(
        "--negative-keyword-shared-set-ids",
        negative_keyword_shared_set_ids,
        max_items=NEGATIVE_KEYWORD_SHARED_SET_IDS_MAX_ITEMS,
    )
    if negative_keyword_shared_set_ids_obj is not None:
        sub_block["NegativeKeywordSharedSetIds"] = negative_keyword_shared_set_ids_obj
