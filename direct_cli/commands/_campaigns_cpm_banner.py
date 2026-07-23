"""CPM_BANNER_CAMPAIGN payload composition for ``campaigns add``/``update``.

Extracted verbatim from the former inline ``elif campaign_type_norm ==
"CPM_BANNER_CAMPAIGN":`` branches of ``direct_cli/commands/campaigns.py``
(issue #602, step 1 of the per-campaign-type split). The CLI surface is
unchanged — ``campaigns.py`` delegates here.
"""

from typing import Dict

from .._bidding_strategy import get_bidding_strategy_builder
from ..utils import parse_setting_specs
from ._campaigns_base import _array_of_integer_option, _build_frequency_cap


def build_add_block(
    p, campaign_data, parsed_settings, counter_ids_obj, frequency_cap_obj
):
    """Compose ``campaign_data['CpmBannerCampaign']`` for ``campaigns add``.

    ``p`` is a snapshot of every CLI parameter of the ``add`` command
    (``dict(locals())``); only the CPM-relevant flags are pulled out below.
    """
    search_strategy = p["search_strategy"]
    network_strategy = p["network_strategy"]
    average_cpm = p["average_cpm"]
    average_cpv = p["average_cpv"]
    strategy_spend_limit = p["strategy_spend_limit"]
    strategy_start_date = p["strategy_start_date"]
    strategy_end_date = p["strategy_end_date"]
    strategy_auto_continue = p["strategy_auto_continue"]
    video_target = p["video_target"]

    cpm_builder = get_bidding_strategy_builder("CPM_BANNER_CAMPAIGN", "add", "full")
    if cpm_builder is not None:
        cpm_bidding_strategy = cpm_builder(
            search_strategy,
            network_strategy,
            average_cpm,
            average_cpv,
            strategy_spend_limit,
            strategy_start_date,
            strategy_end_date,
            strategy_auto_continue,
            include_defaults=True,
        )
    else:
        cpm_bidding_strategy = {
            "Search": {
                "BiddingStrategyType": ((search_strategy or "SERVING_OFF").upper())
            },
            "Network": {
                "BiddingStrategyType": ((network_strategy or "MANUAL_CPM").upper())
            },
        }
    cpm_campaign: Dict[str, object] = {"BiddingStrategy": cpm_bidding_strategy}
    if parsed_settings:
        cpm_campaign["Settings"] = parsed_settings
    if counter_ids_obj is not None:
        cpm_campaign["CounterIds"] = counter_ids_obj
    if frequency_cap_obj is not None:
        cpm_campaign["FrequencyCap"] = frequency_cap_obj
    if video_target:
        cpm_campaign["VideoTarget"] = video_target.upper()
    campaign_data["CpmBannerCampaign"] = cpm_campaign


def build_update_block(p, sub_block):
    """Fill ``sub_block`` for the CpmBannerCampaign subtype of ``campaigns update``.

    ``p`` is a snapshot of every CLI parameter of the ``update`` command.
    """
    search_strategy = p["search_strategy"]
    network_strategy = p["network_strategy"]
    average_cpm = p["average_cpm"]
    average_cpv = p["average_cpv"]
    strategy_spend_limit = p["strategy_spend_limit"]
    strategy_start_date = p["strategy_start_date"]
    strategy_end_date = p["strategy_end_date"]
    strategy_auto_continue = p["strategy_auto_continue"]
    settings = p["settings"]
    counter_ids = p["counter_ids"]
    frequency_cap_impressions = p["frequency_cap_impressions"]
    frequency_cap_period_days = p["frequency_cap_period_days"]
    frequency_cap_period_all = p["frequency_cap_period_all"]
    video_target = p["video_target"]

    parsed_settings = parse_setting_specs(list(settings))
    if parsed_settings:
        sub_block["Settings"] = parsed_settings
    cpm_builder = get_bidding_strategy_builder("CPM_BANNER_CAMPAIGN", "update", "full")
    if cpm_builder is not None:
        cpm_bidding_strategy = cpm_builder(
            search_strategy,
            network_strategy,
            average_cpm,
            average_cpv,
            strategy_spend_limit,
            strategy_start_date,
            strategy_end_date,
            strategy_auto_continue,
            include_defaults=False,
        )
    else:
        cpm_bidding_strategy = None
        if search_strategy is not None or network_strategy is not None:
            cpm_bidding_strategy = {}
            if search_strategy is not None:
                cpm_bidding_strategy["Search"] = {
                    "BiddingStrategyType": search_strategy.upper()
                }
            if network_strategy is not None:
                cpm_bidding_strategy["Network"] = {
                    "BiddingStrategyType": network_strategy.upper()
                }
    if cpm_bidding_strategy is not None:
        sub_block["BiddingStrategy"] = cpm_bidding_strategy
    counter_ids_obj = _array_of_integer_option("--counter-ids", counter_ids)
    if counter_ids_obj is not None:
        sub_block["CounterIds"] = counter_ids_obj
    frequency_cap_obj = _build_frequency_cap(
        frequency_cap_impressions,
        frequency_cap_period_days,
        frequency_cap_period_all,
    )
    if frequency_cap_obj is not None:
        sub_block["FrequencyCap"] = frequency_cap_obj
    if video_target:
        sub_block["VideoTarget"] = video_target.upper()
