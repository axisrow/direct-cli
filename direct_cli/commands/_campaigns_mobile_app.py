"""MOBILE_APP_CAMPAIGN payload composition for ``campaigns add``/``update``.

Extracted verbatim from the former inline ``elif campaign_type_norm ==
"MOBILE_APP_CAMPAIGN":`` branches of ``direct_cli/commands/campaigns.py``
(issue #602, step 2 of the per-campaign-type split). The CLI surface is
unchanged — ``campaigns.py`` delegates here.
"""

from typing import Dict

from .._bidding_strategy import get_bidding_strategy_builder
from ..utils import parse_setting_specs
from ._campaigns_base import (
    NEGATIVE_KEYWORD_SHARED_SET_IDS_MAX_ITEMS,
    _array_of_integer_option,
)


def build_add_block(
    p,
    campaign_data,
    parsed_settings,
    negative_keyword_shared_set_ids_obj,
):
    """Compose ``campaign_data['MobileAppCampaign']`` for ``campaigns add``.

    ``p`` is a snapshot of every CLI parameter of the ``add`` command
    (``dict(locals())``); only the mobile-app-relevant flags are pulled out
    below.
    """
    search_strategy = p["search_strategy"]
    network_strategy = p["network_strategy"]
    mobile_search_weekly_spend_limit = p["mobile_search_weekly_spend_limit"]
    mobile_search_bid_ceiling = p["mobile_search_bid_ceiling"]
    mobile_search_custom_period_spend_limit = p[
        "mobile_search_custom_period_spend_limit"
    ]
    mobile_search_custom_period_start_date = p["mobile_search_custom_period_start_date"]
    mobile_search_custom_period_end_date = p["mobile_search_custom_period_end_date"]
    mobile_search_custom_period_auto_continue = p[
        "mobile_search_custom_period_auto_continue"
    ]
    mobile_search_average_cpc = p["mobile_search_average_cpc"]
    mobile_search_average_cpi = p["mobile_search_average_cpi"]
    mobile_search_clicks_per_week = p["mobile_search_clicks_per_week"]
    mobile_network_weekly_spend_limit = p["mobile_network_weekly_spend_limit"]
    mobile_network_bid_ceiling = p["mobile_network_bid_ceiling"]
    mobile_network_custom_period_spend_limit = p[
        "mobile_network_custom_period_spend_limit"
    ]
    mobile_network_custom_period_start_date = p[
        "mobile_network_custom_period_start_date"
    ]
    mobile_network_custom_period_end_date = p["mobile_network_custom_period_end_date"]
    mobile_network_custom_period_auto_continue = p[
        "mobile_network_custom_period_auto_continue"
    ]
    mobile_network_average_cpc = p["mobile_network_average_cpc"]
    mobile_network_average_cpi = p["mobile_network_average_cpi"]
    mobile_network_clicks_per_week = p["mobile_network_clicks_per_week"]
    mobile_network_limit_percent = p["mobile_network_limit_percent"]

    mobile_builder = get_bidding_strategy_builder("MOBILE_APP_CAMPAIGN", "add", "full")
    if mobile_builder is not None:
        mobile_bidding_strategy = mobile_builder(
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
            None,
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
            None,
            include_defaults=True,
            is_update=False,
        )
    else:
        mobile_bidding_strategy = {
            "Search": {
                "BiddingStrategyType": ((search_strategy or "HIGHEST_POSITION").upper())
            },
            "Network": {
                "BiddingStrategyType": ((network_strategy or "SERVING_OFF").upper())
            },
        }
    mobile_campaign: Dict[str, object] = {"BiddingStrategy": mobile_bidding_strategy}
    if parsed_settings:
        mobile_campaign["Settings"] = parsed_settings
    if negative_keyword_shared_set_ids_obj is not None:
        mobile_campaign["NegativeKeywordSharedSetIds"] = (
            negative_keyword_shared_set_ids_obj
        )
    campaign_data["MobileAppCampaign"] = mobile_campaign


def build_update_block(p, sub_block):
    """Fill ``sub_block`` for the MobileAppCampaign subtype of ``campaigns update``.

    ``p`` is a snapshot of every CLI parameter of the ``update`` command.
    """
    search_strategy = p["search_strategy"]
    network_strategy = p["network_strategy"]
    mobile_search_weekly_spend_limit = p["mobile_search_weekly_spend_limit"]
    mobile_search_bid_ceiling = p["mobile_search_bid_ceiling"]
    mobile_search_custom_period_spend_limit = p[
        "mobile_search_custom_period_spend_limit"
    ]
    mobile_search_custom_period_start_date = p["mobile_search_custom_period_start_date"]
    mobile_search_custom_period_end_date = p["mobile_search_custom_period_end_date"]
    mobile_search_custom_period_auto_continue = p[
        "mobile_search_custom_period_auto_continue"
    ]
    mobile_search_average_cpc = p["mobile_search_average_cpc"]
    mobile_search_average_cpi = p["mobile_search_average_cpi"]
    mobile_search_clicks_per_week = p["mobile_search_clicks_per_week"]
    mobile_search_budget_type = p["mobile_search_budget_type"]
    mobile_network_weekly_spend_limit = p["mobile_network_weekly_spend_limit"]
    mobile_network_bid_ceiling = p["mobile_network_bid_ceiling"]
    mobile_network_custom_period_spend_limit = p[
        "mobile_network_custom_period_spend_limit"
    ]
    mobile_network_custom_period_start_date = p[
        "mobile_network_custom_period_start_date"
    ]
    mobile_network_custom_period_end_date = p["mobile_network_custom_period_end_date"]
    mobile_network_custom_period_auto_continue = p[
        "mobile_network_custom_period_auto_continue"
    ]
    mobile_network_average_cpc = p["mobile_network_average_cpc"]
    mobile_network_average_cpi = p["mobile_network_average_cpi"]
    mobile_network_clicks_per_week = p["mobile_network_clicks_per_week"]
    mobile_network_limit_percent = p["mobile_network_limit_percent"]
    mobile_network_budget_type = p["mobile_network_budget_type"]
    settings = p["settings"]
    negative_keyword_shared_set_ids = p["negative_keyword_shared_set_ids"]

    parsed_settings = parse_setting_specs(list(settings))
    if parsed_settings:
        sub_block["Settings"] = parsed_settings
    mobile_builder = get_bidding_strategy_builder(
        "MOBILE_APP_CAMPAIGN", "update", "full"
    )
    if mobile_builder is not None:
        mobile_bidding_strategy = mobile_builder(
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
            include_defaults=False,
            is_update=True,
        )
    else:
        mobile_bidding_strategy = (
            {"Search": {"BiddingStrategyType": search_strategy.upper()}}
            if search_strategy is not None
            else None
        )
    if mobile_bidding_strategy is not None:
        sub_block["BiddingStrategy"] = mobile_bidding_strategy
    negative_keyword_shared_set_ids_obj = _array_of_integer_option(
        "--negative-keyword-shared-set-ids",
        negative_keyword_shared_set_ids,
        max_items=NEGATIVE_KEYWORD_SHARED_SET_IDS_MAX_ITEMS,
    )
    if negative_keyword_shared_set_ids_obj is not None:
        sub_block["NegativeKeywordSharedSetIds"] = negative_keyword_shared_set_ids_obj
