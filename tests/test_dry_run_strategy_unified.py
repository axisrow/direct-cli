"""Dry-run payload tests for UNIFIED campaign search/network bidding strategies.

Split out of the historical monolithic ``tests/test_dry_run.py`` (issue #604).
See :mod:`tests.test_dry_run_shared` for the shared invocation helpers and
``tests/test_dry_run.py`` for the rationale behind the whole suite.
"""

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from direct_cli.cli import cli
from tests.test_dry_run_shared import _dry_run, _rejected, _write_jsonl


def test_adgroups_add_unified_payload_omits_type():
    """Issue #283: unified ad group sends top-level UnifiedAdGroup."""
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Unified Group",
        "--campaign-id",
        "111",
        "--type",
        "UNIFIED_AD_GROUP",
        "--region-ids",
        "1,225",
        "--offer-retargeting",
        "yes",
    )
    group = body["params"]["AdGroups"][0]
    assert "Type" not in group
    assert group["RegionIds"] == [1, 225]
    assert group["UnifiedAdGroup"] == {"OfferRetargeting": "YES"}


def test_adgroups_add_rejects_unified_flag_for_text_group():
    """Issue #283: UnifiedAdGroup flags must not leak into other types."""
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Text Group",
        "--campaign-id",
        "111",
        "--type",
        "TEXT_AD_GROUP",
        "--region-ids",
        "225",
        "--offer-retargeting",
        "YES",
    )
    assert "--offer-retargeting is not compatible with --type TEXT_AD_GROUP" in (
        result.output
    )


def test_adgroups_update_unified_payload_without_type():
    """Issue #283: update sets top-level UnifiedAdGroup without --type."""
    body = _dry_run(
        "adgroups",
        "update",
        "--id",
        "222",
        "--offer-retargeting",
        "no",
    )
    group = body["params"]["AdGroups"][0]
    assert group == {
        "Id": 222,
        "UnifiedAdGroup": {"OfferRetargeting": "NO"},
    }


def test_adgroups_update_rejects_mixed_smart_and_unified_subtype_flags():
    """Issue #283: update must not emit SmartAdGroup and UnifiedAdGroup."""
    result = _rejected(
        "adgroups",
        "update",
        "--id",
        "222",
        "--ad-title-source",
        "name",
        "--offer-retargeting",
        "YES",
    )
    assert "SmartAdGroup update flags" in result.output
    assert "--ad-title-source" in result.output
    assert "UnifiedAdGroup update flags" in result.output
    assert "--offer-retargeting" in result.output


def _unified_network_add_base():
    return [
        "campaigns",
        "add",
        "--name",
        "Unified Network",
        "--start-date",
        "2026-06-01",
        "--type",
        "UNIFIED_CAMPAIGN",
    ]


def _unified_network_update_base(campaign_id="9001"):
    return [
        "campaigns",
        "update",
        "--id",
        campaign_id,
        "--type",
        "UNIFIED_CAMPAIGN",
    ]


def test_campaigns_add_unified_network_serving_off_default_payload():
    """#366: implicit default (no Network flags) emits SERVING_OFF only —
    matches the pre-#366 baseline so existing payloads keep working."""
    body = _dry_run(*_unified_network_add_base())
    network = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {"BiddingStrategyType": "SERVING_OFF"}


def test_campaigns_add_unified_network_serving_off_explicit_payload():
    body = _dry_run(
        *_unified_network_add_base(),
        "--network-strategy",
        "SERVING_OFF",
    )
    network = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {"BiddingStrategyType": "SERVING_OFF"}


def test_campaigns_add_unified_network_rejects_maximum_coverage():
    """#366: ``MAXIMUM_COVERAGE`` is NOT a member of
    ``UnifiedCampaignNetworkStrategyTypeEnum`` (campaigns.xml 299-315).
    The CLI must reject it rather than emit an API-invalid payload."""
    result = _rejected(
        *_unified_network_add_base(),
        "--network-strategy",
        "MAXIMUM_COVERAGE",
    )
    assert "UNIFIED_CAMPAIGN" in result.output


def test_campaigns_add_unified_network_network_default_payload():
    """#366: NETWORK_DEFAULT is enum-allowed but
    ``UnifiedCampaignStrategyAddBase`` declares no nested element for it
    (campaigns.xml 1631-1654) — emit BiddingStrategyType only."""
    body = _dry_run(
        *_unified_network_add_base(),
        "--network-strategy",
        "NETWORK_DEFAULT",
    )
    network = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {"BiddingStrategyType": "NETWORK_DEFAULT"}


def test_campaigns_add_unified_network_wb_maximum_clicks_bare_payload():
    """#366: WSDL ``StrategyMaximumClicksAdd`` (campaigns.xml 1339-1347)
    has all fields ``minOccurs=0``; a bare WB_MAXIMUM_CLICKS add with
    only the strategy name must succeed."""
    body = _dry_run(
        *_unified_network_add_base(),
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
    )
    network = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {"BiddingStrategyType": "WB_MAXIMUM_CLICKS"}


def test_campaigns_add_unified_network_wb_maximum_clicks_weekly_payload():
    body = _dry_run(
        *_unified_network_add_base(),
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--unified-network-weekly-spend-limit",
        "1000000000",
        "--bid-ceiling",
        "100000000",
    )
    network = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
        "WbMaximumClicks": {
            "WeeklySpendLimit": 1000000000,
            "BidCeiling": 100000000,
        },
    }


def test_campaigns_add_unified_network_wb_maximum_clicks_custom_period_payload():
    body = _dry_run(
        *_unified_network_add_base(),
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--unified-network-custom-period-spend-limit",
        "5000000000",
        "--unified-network-custom-period-start-date",
        "2026-06-01",
        "--unified-network-custom-period-end-date",
        "2026-06-30",
        "--unified-network-custom-period-auto-continue",
        "NO",
    )
    network = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
        "WbMaximumClicks": {
            "CustomPeriodBudget": {
                "SpendLimit": 5000000000,
                "StartDate": "2026-06-01",
                "EndDate": "2026-06-30",
                "AutoContinue": "NO",
            }
        },
    }


def test_campaigns_add_unified_network_wb_maximum_conversion_rate_payload():
    """#366: WSDL ``StrategyMaximumConversionRateAdd`` (campaigns.xml
    1348-1357) requires GoalId (minOccurs=1)."""
    body = _dry_run(
        *_unified_network_add_base(),
        "--network-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--goal-id",
        "77",
        "--unified-network-weekly-spend-limit",
        "2000000000",
        "--bid-ceiling",
        "50000000",
    )
    network = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WB_MAXIMUM_CONVERSION_RATE",
        "WbMaximumConversionRate": {
            "GoalId": 77,
            "WeeklySpendLimit": 2000000000,
            "BidCeiling": 50000000,
        },
    }


def test_campaigns_add_unified_network_average_cpc_payload():
    body = _dry_run(
        *_unified_network_add_base(),
        "--network-strategy",
        "AVERAGE_CPC",
        "--unified-network-average-cpc",
        "7000000",
        "--unified-network-weekly-spend-limit",
        "500000000",
    )
    network = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPC",
        "AverageCpc": {
            "AverageCpc": 7000000,
            "WeeklySpendLimit": 500000000,
        },
    }


def test_campaigns_add_unified_network_average_cpa_payload():
    body = _dry_run(
        *_unified_network_add_base(),
        "--network-strategy",
        "AVERAGE_CPA",
        "--average-cpa",
        "150000000",
        "--goal-id",
        "12",
        "--bid-ceiling",
        "20000000",
        "--unified-network-exploration-min-budget",
        "300000000",
        "--unified-network-exploration-is-custom",
        "YES",
    )
    network = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPA",
        "AverageCpa": {
            "AverageCpa": 150000000,
            "GoalId": 12,
            "BidCeiling": 20000000,
            "ExplorationBudget": {
                "MinimumExplorationBudget": 300000000,
                "IsMinimumExplorationBudgetCustom": "YES",
            },
        },
    }


def test_campaigns_add_unified_network_pay_for_conversion_payload():
    body = _dry_run(
        *_unified_network_add_base(),
        "--network-strategy",
        "PAY_FOR_CONVERSION",
        "--unified-network-cpa",
        "300000000",
        "--goal-id",
        "55",
        "--unified-network-weekly-spend-limit",
        "2500000000",
    )
    network = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION",
        "PayForConversion": {
            "Cpa": 300000000,
            "GoalId": 55,
            "WeeklySpendLimit": 2500000000,
        },
    }


def test_campaigns_add_unified_network_average_crr_payload():
    body = _dry_run(
        *_unified_network_add_base(),
        "--network-strategy",
        "AVERAGE_CRR",
        "--crr",
        "30",
        "--goal-id",
        "61",
        "--unified-network-weekly-spend-limit",
        "800000000",
    )
    network = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CRR",
        "AverageCrr": {
            "Crr": 30,
            "GoalId": 61,
            "WeeklySpendLimit": 800000000,
        },
    }


def test_campaigns_add_unified_network_pay_for_conversion_crr_payload():
    body = _dry_run(
        *_unified_network_add_base(),
        "--network-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--crr",
        "25",
        "--goal-id",
        "44",
    )
    network = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_CRR",
        "PayForConversionCrr": {
            "Crr": 25,
            "GoalId": 44,
        },
    }


def test_campaigns_add_unified_network_max_profit_payload():
    """#366: WSDL ``StrategyMaxProfitAdd`` (campaigns.xml 1489-1495) is
    fully optional. On UnifiedCampaign add, --priority-goals is gated
    elsewhere (#290/#373), so MAX_PROFIT add emits an empty subtype block
    — the API uses the presence of the MaxProfit child as the
    discriminator (mirrors TextCampaign behaviour)."""
    body = _dry_run(
        *_unified_network_add_base(),
        "--network-strategy",
        "MAX_PROFIT",
    )
    network = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "MAX_PROFIT",
        "MaxProfit": {},
    }


def test_campaigns_add_unified_network_average_cpa_multiple_goals_payload():
    """#366: WSDL ``StrategyAverageCpaMultipleGoalsAdd`` (campaigns.xml
    1496-1503) allows BidCeiling/WeeklySpendLimit. PriorityGoals is gated
    outside the builder on Unified add (#290/#373)."""
    body = _dry_run(
        *_unified_network_add_base(),
        "--network-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--bid-ceiling",
        "200000000",
    )
    network = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPA_MULTIPLE_GOALS",
        "AverageCpaMultipleGoals": {"BidCeiling": 200000000},
    }


def test_campaigns_add_unified_network_pay_for_conversion_multiple_goals_payload():
    body = _dry_run(
        *_unified_network_add_base(),
        "--network-strategy",
        "PAY_FOR_CONVERSION_MULTIPLE_GOALS",
        "--unified-network-weekly-spend-limit",
        "400000000",
    )
    network = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_MULTIPLE_GOALS",
        "PayForConversionMultipleGoals": {"WeeklySpendLimit": 400000000},
    }


def test_campaigns_add_unified_network_rejects_detail_without_strategy():
    """Typed --unified-network-* flag without --network-strategy must
    fail rather than silently picking a default subtype."""
    result = _rejected(
        *_unified_network_add_base(),
        "--unified-network-average-cpc",
        "5000000",
    )
    assert "UnifiedCampaign network strategy detail flags require" in result.output


def test_campaigns_add_unified_network_rejects_serving_off_with_details():
    result = _rejected(
        *_unified_network_add_base(),
        "--network-strategy",
        "SERVING_OFF",
        "--unified-network-average-cpc",
        "5000000",
    )
    assert "SERVING_OFF does not accept" in result.output


def test_campaigns_add_unified_network_rejects_maximum_coverage_even_with_details():
    """#366: MAXIMUM_COVERAGE is enum-invalid on Unified; even with detail
    flags the strategy validator rejects it first."""
    result = _rejected(
        *_unified_network_add_base(),
        "--network-strategy",
        "MAXIMUM_COVERAGE",
        "--unified-network-weekly-spend-limit",
        "1000000000",
    )
    assert "UNIFIED_CAMPAIGN" in result.output


def test_campaigns_add_unified_network_rejects_network_default_with_details():
    """#366: NETWORK_DEFAULT on Unified is a bare-marker (WSDL declares
    no nested NetworkDefault element on UnifiedCampaignStrategyAddBase)."""
    result = _rejected(
        *_unified_network_add_base(),
        "--network-strategy",
        "NETWORK_DEFAULT",
        "--unified-network-weekly-spend-limit",
        "1000000000",
    )
    assert "NETWORK_DEFAULT does not accept" in result.output


def test_campaigns_add_unified_network_rejects_invalid_strategy():
    result = _rejected(
        *_unified_network_add_base(),
        "--network-strategy",
        "AVERAGE_ROI",  # not declared on UnifiedCampaignStrategyAddBase
    )
    assert "UNIFIED_CAMPAIGN" in result.output


def test_campaigns_add_unified_network_rejects_required_average_cpc():
    """#366: WSDL ``StrategyAverageCpcAdd.AverageCpc`` minOccurs=1
    (campaigns.xml 1421-1428)."""
    result = _rejected(
        *_unified_network_add_base(),
        "--network-strategy",
        "AVERAGE_CPC",
    )
    assert "AverageCpc requires" in result.output
    assert "--unified-network-average-cpc" in result.output


def test_campaigns_add_unified_network_rejects_required_average_cpa_and_goal():
    """#366: WSDL ``StrategyAverageCpaAdd.AverageCpa`` + ``GoalId``
    are both minOccurs=1 (campaigns.xml 1430-1444)."""
    result = _rejected(
        *_unified_network_add_base(),
        "--network-strategy",
        "AVERAGE_CPA",
    )
    assert "AverageCpa requires" in result.output
    assert "--average-cpa" in result.output
    assert "--goal-id" in result.output


def test_campaigns_add_unified_network_rejects_required_pay_for_conversion():
    result = _rejected(
        *_unified_network_add_base(),
        "--network-strategy",
        "PAY_FOR_CONVERSION",
    )
    assert "PayForConversion requires" in result.output
    assert "--unified-network-cpa" in result.output
    assert "--goal-id" in result.output


def test_campaigns_add_unified_network_rejects_required_wb_maximum_conversion_rate_goal():
    result = _rejected(
        *_unified_network_add_base(),
        "--network-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
    )
    assert "WbMaximumConversionRate requires" in result.output
    assert "--goal-id" in result.output


def test_campaigns_add_unified_network_rejects_required_average_crr():
    result = _rejected(
        *_unified_network_add_base(),
        "--network-strategy",
        "AVERAGE_CRR",
    )
    assert "AverageCrr requires" in result.output
    assert "--crr" in result.output
    assert "--goal-id" in result.output


def test_campaigns_add_unified_network_rejects_required_pay_for_conversion_crr():
    result = _rejected(
        *_unified_network_add_base(),
        "--network-strategy",
        "PAY_FOR_CONVERSION_CRR",
    )
    assert "PayForConversionCrr requires" in result.output


def test_campaigns_add_unified_network_rejects_wrong_subtype_flag():
    """#366: --unified-network-cpa belongs only to PayForConversion;
    using it with AVERAGE_CPA must raise."""
    result = _rejected(
        *_unified_network_add_base(),
        "--network-strategy",
        "AVERAGE_CPA",
        "--average-cpa",
        "100000000",
        "--goal-id",
        "1",
        "--unified-network-cpa",
        "5000000",
    )
    assert "--unified-network-cpa is not valid" in result.output


def test_campaigns_add_unified_network_rejects_bid_ceiling_on_crr():
    """#366: WSDL StrategyAverageCrrAdd has no BidCeiling field."""
    result = _rejected(
        *_unified_network_add_base(),
        "--network-strategy",
        "AVERAGE_CRR",
        "--crr",
        "15",
        "--goal-id",
        "777",
        "--bid-ceiling",
        "10000000",
    )
    assert "--bid-ceiling is not valid" in result.output


def test_campaigns_add_unified_network_rejects_exploration_on_average_cpc():
    """#366: WSDL StrategyAverageCpcAdd has no ExplorationBudget."""
    result = _rejected(
        *_unified_network_add_base(),
        "--network-strategy",
        "AVERAGE_CPC",
        "--unified-network-average-cpc",
        "5000000",
        "--unified-network-exploration-min-budget",
        "1000000",
        "--unified-network-exploration-is-custom",
        "YES",
    )
    assert "ExplorationBudget is not valid" in result.output


def test_campaigns_add_unified_network_rejects_partial_custom_period_budget():
    result = _rejected(
        *_unified_network_add_base(),
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--unified-network-custom-period-spend-limit",
        "1000000000",
    )
    assert (
        "UnifiedCampaign Network CustomPeriodBudget requires all four" in result.output
    )


def test_campaigns_add_unified_network_rejects_partial_exploration_budget():
    result = _rejected(
        *_unified_network_add_base(),
        "--network-strategy",
        "AVERAGE_CPA",
        "--average-cpa",
        "100000000",
        "--goal-id",
        "1",
        "--unified-network-exploration-min-budget",
        "100000000",
    )
    assert "UnifiedCampaign Network ExplorationBudget requires both" in result.output


def test_campaigns_add_unified_network_rejects_weekly_combined_with_custom_period():
    result = _rejected(
        *_unified_network_add_base(),
        "--network-strategy",
        "AVERAGE_CPC",
        "--unified-network-average-cpc",
        "5000000",
        "--unified-network-weekly-spend-limit",
        "100000000",
        "--unified-network-custom-period-spend-limit",
        "200000000",
        "--unified-network-custom-period-start-date",
        "2026-06-01",
        "--unified-network-custom-period-end-date",
        "2026-06-30",
        "--unified-network-custom-period-auto-continue",
        "NO",
    )
    assert "--unified-network-weekly-spend-limit cannot be combined" in result.output


def test_campaigns_add_unified_network_rejects_budget_type_on_add():
    """#366: --unified-network-budget-type is update-only (only the
    get-side Strategy* types used by UnifiedCampaignUpdateItem declare
    ``BudgetType``). On add the Click parser must reject the option."""
    result = CliRunner().invoke(
        cli,
        [
            *_unified_network_add_base(),
            "--network-strategy",
            "AVERAGE_CPC",
            "--unified-network-average-cpc",
            "5000000",
            "--unified-network-budget-type",
            "WEEKLY_BUDGET",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert (
        "no such option" in result.output.lower()
        or "--unified-network-budget-type" in result.output
    )


def test_campaigns_add_unified_network_rejects_package_with_typed_flag():
    """#366: --package-strategy-id (UnifiedCampaign PackageBiddingStrategy)
    must conflict with the typed Network flags on add — mirrors the
    existing CounterIds/PriorityGoals collision behaviour."""
    result = _rejected(
        *_unified_network_add_base(),
        "--package-strategy-id",
        "700",
        "--package-platform-search-result",
        "YES",
        "--package-platform-product-gallery",
        "YES",
        "--package-platform-maps",
        "NO",
        "--package-platform-search-organization-list",
        "NO",
        "--package-platform-network",
        "YES",
        "--package-platform-dynamic-places",
        "NO",
        "--network-strategy",
        "AVERAGE_CPC",
        "--unified-network-average-cpc",
        "5000000",
    )
    assert "UnifiedCampaign.PackageBiddingStrategy cannot be combined" in result.output


def test_campaigns_add_unified_network_rejects_typed_flag_for_text_type():
    """#366: --unified-network-* must reject for other --type values
    (silent-data-loss invariant)."""
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Wrong type",
        "--start-date",
        "2026-06-01",
        "--type",
        "TEXT_CAMPAIGN",
        "--search-strategy",
        "HIGHEST_POSITION",
        "--network-strategy",
        "SERVING_OFF",
        "--unified-network-average-cpc",
        "5000000",
    )
    assert "--unified-network-average-cpc" in result.output


def test_campaigns_update_unified_network_serving_off_payload():
    """#366: partial update with only --network-strategy SERVING_OFF still
    emits a Network block (no silent no-op)."""
    body = _dry_run(
        *_unified_network_update_base("9000"),
        "--network-strategy",
        "SERVING_OFF",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 9000,
        "UnifiedCampaign": {
            "BiddingStrategy": {
                "Network": {"BiddingStrategyType": "SERVING_OFF"},
            }
        },
    }


def test_campaigns_update_unified_network_rejects_maximum_coverage():
    """#366: MAXIMUM_COVERAGE rejected on update too (not in
    UnifiedCampaignNetworkStrategyTypeEnum)."""
    result = _rejected(
        *_unified_network_update_base("9001"),
        "--network-strategy",
        "MAXIMUM_COVERAGE",
    )
    assert "UNIFIED_CAMPAIGN" in result.output


def test_campaigns_update_unified_network_network_default_payload():
    body = _dry_run(
        *_unified_network_update_base("9002"),
        "--network-strategy",
        "NETWORK_DEFAULT",
    )
    network = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {"BiddingStrategyType": "NETWORK_DEFAULT"}


def test_campaigns_update_unified_network_wb_maximum_clicks_payload():
    body = _dry_run(
        *_unified_network_update_base("9003"),
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--unified-network-weekly-spend-limit",
        "500000000",
    )
    network = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
        "WbMaximumClicks": {"WeeklySpendLimit": 500000000},
    }


def test_campaigns_update_unified_network_wb_maximum_conversion_rate_payload():
    body = _dry_run(
        *_unified_network_update_base("9004"),
        "--network-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--goal-id",
        "33",
    )
    network = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WB_MAXIMUM_CONVERSION_RATE",
        "WbMaximumConversionRate": {"GoalId": 33},
    }


def test_campaigns_update_unified_network_average_cpc_payload():
    body = _dry_run(
        *_unified_network_update_base("9005"),
        "--network-strategy",
        "AVERAGE_CPC",
        "--unified-network-average-cpc",
        "8000000",
        "--unified-network-weekly-spend-limit",
        "1500000000",
    )
    network = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPC",
        "AverageCpc": {
            "AverageCpc": 8000000,
            "WeeklySpendLimit": 1500000000,
        },
    }


def test_campaigns_update_unified_network_average_cpa_payload():
    body = _dry_run(
        *_unified_network_update_base("9006"),
        "--network-strategy",
        "AVERAGE_CPA",
        "--average-cpa",
        "120000000",
        "--goal-id",
        "21",
    )
    network = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPA",
        "AverageCpa": {
            "AverageCpa": 120000000,
            "GoalId": 21,
        },
    }


def test_campaigns_update_unified_network_pay_for_conversion_payload():
    body = _dry_run(
        *_unified_network_update_base("9007"),
        "--network-strategy",
        "PAY_FOR_CONVERSION",
        "--unified-network-cpa",
        "9000000",
        "--goal-id",
        "12",
    )
    network = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION",
        "PayForConversion": {"Cpa": 9000000, "GoalId": 12},
    }


def test_campaigns_update_unified_network_average_crr_payload():
    body = _dry_run(
        *_unified_network_update_base("9008"),
        "--network-strategy",
        "AVERAGE_CRR",
        "--crr",
        "25",
        "--goal-id",
        "10",
    )
    network = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CRR",
        "AverageCrr": {"Crr": 25, "GoalId": 10},
    }


def test_campaigns_update_unified_network_pay_for_conversion_crr_payload():
    body = _dry_run(
        *_unified_network_update_base("9009"),
        "--network-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--crr",
        "12",
        "--goal-id",
        "44",
    )
    network = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_CRR",
        "PayForConversionCrr": {"Crr": 12, "GoalId": 44},
    }


def test_campaigns_update_unified_network_max_profit_payload():
    """#366: switching to MAX_PROFIT on update requires --priority-goals
    (mirrors TextCampaign Network — Yandex API rejects the switch
    otherwise)."""
    body = _dry_run(
        *_unified_network_update_base("9010"),
        "--network-strategy",
        "MAX_PROFIT",
        "--priority-goals",
        "1:100000000",
    )
    campaign = body["params"]["Campaigns"][0]["UnifiedCampaign"]
    assert campaign["BiddingStrategy"]["Network"] == {
        "BiddingStrategyType": "MAX_PROFIT",
        "MaxProfit": {},
    }
    assert campaign["PriorityGoals"] == {
        "Items": [{"GoalId": 1, "Value": 100000000, "Operation": "SET"}]
    }


def test_campaigns_update_unified_network_average_cpa_multiple_goals_payload():
    """#366: switching to AVERAGE_CPA_MULTIPLE_GOALS requires at least
    two priority goals."""
    body = _dry_run(
        *_unified_network_update_base("9011"),
        "--network-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--priority-goals",
        "10:70000000,20:30000000",
        "--bid-ceiling",
        "200000000",
    )
    campaign = body["params"]["Campaigns"][0]["UnifiedCampaign"]
    assert campaign["BiddingStrategy"]["Network"] == {
        "BiddingStrategyType": "AVERAGE_CPA_MULTIPLE_GOALS",
        "AverageCpaMultipleGoals": {"BidCeiling": 200000000},
    }
    assert campaign["PriorityGoals"] == {
        "Items": [
            {"GoalId": 10, "Value": 70000000, "Operation": "SET"},
            {"GoalId": 20, "Value": 30000000, "Operation": "SET"},
        ]
    }


def test_campaigns_update_unified_network_pay_for_conversion_multiple_goals_payload():
    body = _dry_run(
        *_unified_network_update_base("9012"),
        "--network-strategy",
        "PAY_FOR_CONVERSION_MULTIPLE_GOALS",
        "--priority-goals",
        "11:55000000,22:45000000",
        "--unified-network-weekly-spend-limit",
        "400000000",
    )
    campaign = body["params"]["Campaigns"][0]["UnifiedCampaign"]
    assert campaign["BiddingStrategy"]["Network"] == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_MULTIPLE_GOALS",
        "PayForConversionMultipleGoals": {"WeeklySpendLimit": 400000000},
    }
    assert campaign["PriorityGoals"] == {
        "Items": [
            {"GoalId": 11, "Value": 55000000, "Operation": "SET"},
            {"GoalId": 22, "Value": 45000000, "Operation": "SET"},
        ]
    }


def test_campaigns_update_unified_network_rejects_multi_goal_without_priority_goals():
    """#366: switching to a multi-goal strategy on update without
    --priority-goals must reject (mirrors TextCampaign Network)."""
    result = _rejected(
        *_unified_network_update_base("9013"),
        "--network-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
    )
    assert "AverageCpaMultipleGoals requires" in result.output
    assert "--priority-goals" in result.output


def test_campaigns_update_unified_network_rejects_max_profit_without_priority_goals():
    result = _rejected(
        *_unified_network_update_base("9014"),
        "--network-strategy",
        "MAX_PROFIT",
    )
    assert "MaxProfit requires" in result.output
    assert "--priority-goals" in result.output


def test_campaigns_add_unified_network_rejects_multi_goal_with_single_goal():
    """#366: ``*_MULTIPLE_GOALS`` strategies require at least 2 entries
    (mirrors TextCampaign Network)."""
    result = _rejected(
        *_unified_network_add_base(),
        "--network-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--priority-goals",
        "1:100000000",
    )
    assert "at least 2 entries" in result.output


def test_campaigns_update_unified_network_rejects_multi_goal_with_single_goal():
    result = _rejected(
        *_unified_network_update_base("9015"),
        "--network-strategy",
        "PAY_FOR_CONVERSION_MULTIPLE_GOALS",
        "--priority-goals",
        "1:100000000",
    )
    assert "at least 2 entries" in result.output


def test_campaigns_update_unified_network_budget_type_weekly_payload():
    """#366: BudgetType WEEKLY_BUDGET nulls CustomPeriodBudget."""
    body = _dry_run(
        *_unified_network_update_base("9020"),
        "--network-strategy",
        "AVERAGE_CPC",
        "--unified-network-average-cpc",
        "5000000",
        "--unified-network-weekly-spend-limit",
        "300000000",
        "--unified-network-budget-type",
        "WEEKLY_BUDGET",
    )
    network = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPC",
        "AverageCpc": {
            "AverageCpc": 5000000,
            "WeeklySpendLimit": 300000000,
            "CustomPeriodBudget": None,
            "BudgetType": "WEEKLY_BUDGET",
        },
    }


def test_campaigns_update_unified_network_budget_type_custom_period_payload():
    body = _dry_run(
        *_unified_network_update_base("9021"),
        "--network-strategy",
        "AVERAGE_CPC",
        "--unified-network-average-cpc",
        "5000000",
        "--unified-network-custom-period-spend-limit",
        "1000000000",
        "--unified-network-custom-period-start-date",
        "2026-07-01",
        "--unified-network-custom-period-end-date",
        "2026-07-31",
        "--unified-network-custom-period-auto-continue",
        "YES",
        "--unified-network-budget-type",
        "CUSTOM_PERIOD_BUDGET",
    )
    network = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPC",
        "AverageCpc": {
            "AverageCpc": 5000000,
            "CustomPeriodBudget": {
                "SpendLimit": 1000000000,
                "StartDate": "2026-07-01",
                "EndDate": "2026-07-31",
                "AutoContinue": "YES",
            },
            "WeeklySpendLimit": None,
            "BudgetType": "CUSTOM_PERIOD_BUDGET",
        },
    }


def test_campaigns_update_unified_network_rejects_budget_type_without_weekly():
    result = _rejected(
        *_unified_network_update_base("9022"),
        "--network-strategy",
        "AVERAGE_CPC",
        "--unified-network-average-cpc",
        "5000000",
        "--unified-network-budget-type",
        "WEEKLY_BUDGET",
    )
    assert "--unified-network-budget-type WEEKLY_BUDGET requires" in result.output


def test_campaigns_update_unified_network_rejects_budget_type_without_custom_period():
    result = _rejected(
        *_unified_network_update_base("9023"),
        "--network-strategy",
        "AVERAGE_CPC",
        "--unified-network-average-cpc",
        "5000000",
        "--unified-network-budget-type",
        "CUSTOM_PERIOD_BUDGET",
    )
    assert (
        "--unified-network-budget-type CUSTOM_PERIOD_BUDGET requires" in result.output
    )


def test_campaigns_update_unified_network_no_op_when_no_flags_payload():
    """#366: update with --type UNIFIED_CAMPAIGN and no Network-side or
    Search-side typed flags must NOT emit a BiddingStrategy block (Network
    is left untouched). Same convention as TextCampaign / DynamicText /
    Smart update paths."""
    body = _dry_run(
        *_unified_network_update_base("9024"),
        "--tracking-params",
        "utm_source=direct",
    )
    campaign = body["params"]["Campaigns"][0]
    assert "BiddingStrategy" not in campaign["UnifiedCampaign"]
    assert campaign["UnifiedCampaign"]["TrackingParams"] == "utm_source=direct"


def test_campaigns_update_unified_network_rejects_package_with_typed_flag():
    """#366: --package-strategy-id must conflict with typed Network flags
    on update (mirrors DynamicTextCampaign behaviour)."""
    result = _rejected(
        *_unified_network_update_base("9025"),
        "--package-strategy-from-campaign-id",
        "456",
        "--package-platform-search-result",
        "YES",
        "--package-platform-product-gallery",
        "NO",
        "--package-platform-maps",
        "NO",
        "--package-platform-search-organization-list",
        "NO",
        "--package-platform-network",
        "YES",
        "--network-strategy",
        "AVERAGE_CPC",
        "--unified-network-average-cpc",
        "5000000",
    )
    assert "PackageBiddingStrategy cannot be combined" in result.output


def test_campaigns_update_unified_network_wb_maximum_clicks_budget_type_payload():
    """#366: WSDL ``StrategyMaximumClicks`` (campaigns.xml 789-797) declares
    ``BudgetType`` on the get-side type used by ``UnifiedCampaignUpdateItem``,
    so the CLI must emit ``BudgetType`` and null the alternate budget slice
    when the user switches budget on update."""
    body = _dry_run(
        *_unified_network_update_base("9026"),
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--unified-network-weekly-spend-limit",
        "300000000",
        "--unified-network-budget-type",
        "WEEKLY_BUDGET",
    )
    network = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
        "WbMaximumClicks": {
            "WeeklySpendLimit": 300000000,
            "CustomPeriodBudget": None,
            "BudgetType": "WEEKLY_BUDGET",
        },
    }


def test_campaigns_add_unified_network_rejects_package_with_typed_flag_no_strategy():
    """#366: --package-strategy-id must conflict with typed --unified-network-*
    flags on add EVEN WITHOUT --network-strategy. Without this guard, the
    package-strategy branch silently wins and the user's detail flags are
    dropped. Adversarial-review finding (gh issue #366 review iteration)."""
    result = _rejected(
        *_unified_network_add_base(),
        "--package-strategy-id",
        "700",
        "--package-platform-search-result",
        "YES",
        "--package-platform-product-gallery",
        "YES",
        "--package-platform-maps",
        "NO",
        "--package-platform-search-organization-list",
        "NO",
        "--package-platform-network",
        "YES",
        "--package-platform-dynamic-places",
        "NO",
        "--unified-network-average-cpc",
        "5000000",
    )
    assert "UnifiedCampaign.PackageBiddingStrategy cannot be combined" in result.output
    assert "--unified-network-average-cpc" in result.output


def test_campaigns_add_unified_network_average_cpa_multiple_goals_with_priority_goals_payload():
    """#366: ``AVERAGE_CPA_MULTIPLE_GOALS`` is a settable Strategy*Add
    subtype on ``UnifiedCampaignStrategyAddBase`` (campaigns.xml 1631-1654)
    and ``UnifiedCampaignAddItem.PriorityGoals`` is a real WSDL field
    (campaigns.xml 2165). On add the CLI emits both the subtype block and
    the parent PriorityGoals container."""
    body = _dry_run(
        *_unified_network_add_base(),
        "--network-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--priority-goals",
        "10:70000000,20:30000000",
        "--bid-ceiling",
        "200000000",
    )
    campaign = body["params"]["Campaigns"][0]["UnifiedCampaign"]
    assert campaign["BiddingStrategy"]["Network"] == {
        "BiddingStrategyType": "AVERAGE_CPA_MULTIPLE_GOALS",
        "AverageCpaMultipleGoals": {"BidCeiling": 200000000},
    }
    assert campaign["PriorityGoals"] == {
        "Items": [
            {"GoalId": 10, "Value": 70000000},
            {"GoalId": 20, "Value": 30000000},
        ]
    }


def test_campaigns_add_unified_network_pay_for_conversion_multiple_goals_with_priority_goals_payload():
    body = _dry_run(
        *_unified_network_add_base(),
        "--network-strategy",
        "PAY_FOR_CONVERSION_MULTIPLE_GOALS",
        "--priority-goals",
        "11:55000000,22:45000000",
        "--unified-network-weekly-spend-limit",
        "400000000",
    )
    campaign = body["params"]["Campaigns"][0]["UnifiedCampaign"]
    assert campaign["BiddingStrategy"]["Network"] == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_MULTIPLE_GOALS",
        "PayForConversionMultipleGoals": {"WeeklySpendLimit": 400000000},
    }
    assert campaign["PriorityGoals"] == {
        "Items": [
            {"GoalId": 11, "Value": 55000000},
            {"GoalId": 22, "Value": 45000000},
        ]
    }


def test_campaigns_add_unified_network_max_profit_with_priority_goals_payload():
    body = _dry_run(
        *_unified_network_add_base(),
        "--network-strategy",
        "MAX_PROFIT",
        "--priority-goals",
        "1:60000000,2:40000000",
    )
    campaign = body["params"]["Campaigns"][0]["UnifiedCampaign"]
    assert campaign["BiddingStrategy"]["Network"] == {
        "BiddingStrategyType": "MAX_PROFIT",
        "MaxProfit": {},
    }
    assert campaign["PriorityGoals"] == {
        "Items": [
            {"GoalId": 1, "Value": 60000000},
            {"GoalId": 2, "Value": 40000000},
        ]
    }


def test_campaigns_add_unified_network_rejects_priority_goals_for_non_multi_goal_strategy():
    """#373 (refines #366): an explicit per-side --network-strategy whose
    subtype builder does not consume PriorityGoals must be rejected
    up-front so the items are not silently dropped. WSDL-valid
    standalone PriorityGoals are covered separately by the
    ``..._standalone_payload`` test."""
    result = _rejected(
        *_unified_network_add_base(),
        "--network-strategy",
        "AVERAGE_CPC",
        "--unified-network-average-cpc",
        "5000000",
        "--priority-goals",
        "1:500000000",
    )
    assert "--priority-goals on UnifiedCampaign is only valid with" in result.output
    assert "AVERAGE_CPA_MULTIPLE_GOALS" in result.output


def test_campaigns_add_unified_network_allows_priority_goals_with_package():
    """#373 lifts the #366 carve-out: PriorityGoals + PackageBiddingStrategy
    are independent ``minOccurs=0`` siblings on ``UnifiedCampaignAddItem``
    (WSDL ``tests/wsdl_cache/campaigns.xml`` lines 2160-2172, no
    ``xsd:choice``). Mirrors the SmartCampaign mutex-lift in #369/#392 —
    the payload must carry both fields and no longer rejects the
    combination."""
    body = _dry_run(
        *_unified_network_add_base(),
        "--package-strategy-id",
        "700",
        "--package-platform-search-result",
        "YES",
        "--package-platform-product-gallery",
        "YES",
        "--package-platform-maps",
        "NO",
        "--package-platform-search-organization-list",
        "NO",
        "--package-platform-network",
        "YES",
        "--package-platform-dynamic-places",
        "NO",
        "--priority-goals",
        "1:500000000",
    )
    unified = body["params"]["Campaigns"][0]["UnifiedCampaign"]
    assert "PackageBiddingStrategy" in unified
    assert unified["PriorityGoals"] == {"Items": [{"GoalId": 1, "Value": 500000000}]}


def _unified_base_args():
    return [
        "campaigns",
        "add",
        "--name",
        "Unified Campaign",
        "--start-date",
        "2026-06-01",
        "--type",
        "UNIFIED_CAMPAIGN",
    ]


def _unified_search_extract(body: dict) -> dict:
    return body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Search"
    ]


def _unified_search_update(*extra: str) -> dict:
    return _dry_run(
        "campaigns",
        "update",
        "--id",
        "777",
        "--type",
        "UNIFIED_CAMPAIGN",
        *extra,
    )


def test_campaigns_add_unified_search_default_highest_position_payload():
    """Default container: Search = HIGHEST_POSITION (no subtype block),
    Network = SERVING_OFF (placeholder, #366 owns Network)."""
    body = _dry_run(*_unified_base_args())
    bs = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"]
    assert bs["Search"] == {"BiddingStrategyType": "HIGHEST_POSITION"}
    assert bs["Network"] == {"BiddingStrategyType": "SERVING_OFF"}


def test_campaigns_add_unified_search_serving_off_no_details():
    body = _dry_run(*_unified_base_args(), "--search-strategy", "SERVING_OFF")
    assert _unified_search_extract(body) == {"BiddingStrategyType": "SERVING_OFF"}


def test_campaigns_add_unified_search_serving_off_rejects_detail_flags():
    """SERVING_OFF carries no subtype block; detail flags must be rejected."""
    result = _rejected(
        *_unified_base_args(),
        "--search-strategy",
        "SERVING_OFF",
        "--unified-search-weekly-spend-limit",
        "100000000",
    )
    assert "SERVING_OFF" in result.output


def test_campaigns_add_unified_search_wb_maximum_clicks_payload():
    body = _dry_run(
        *_unified_base_args(),
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--unified-search-weekly-spend-limit",
        "300000000",
        "--bid-ceiling",
        "5000000",
    )
    search = _unified_search_extract(body)
    assert search["BiddingStrategyType"] == "WB_MAXIMUM_CLICKS"
    assert search["WbMaximumClicks"] == {
        "WeeklySpendLimit": 300000000,
        "BidCeiling": 5000000,
    }


def test_campaigns_add_unified_search_wb_maximum_clicks_bare_payload():
    """WbMaximumClicks has NO required typed fields per WSDL: the type
    extends StrategyWeeklyBudgetAddBase whose WeeklySpendLimit /
    BidCeiling are minOccurs=0 and the appended CustomPeriodBudget is
    also minOccurs=0 (campaigns.xml L1339-1347). The canonical WSDL is
    the source of truth for this PR (#363), so a bare
    ``--search-strategy WB_MAXIMUM_CLICKS`` is accepted. This diverges
    from the doc-strict TextCampaign Search precedent (#388)."""
    body = _dry_run(
        *_unified_base_args(),
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
    )
    search = _unified_search_extract(body)
    assert search["BiddingStrategyType"] == "WB_MAXIMUM_CLICKS"
    # *_MULTIPLE_GOALS / MAX_PROFIT subtypes always emit an empty
    # container so the API can discriminate; WbMaximumClicks does NOT
    # need that signal (it's a regular subtype with no required fields),
    # so an empty WbMaximumClicks block is emitted only when at least
    # one optional field was supplied. With no fields, the builder
    # emits only BiddingStrategyType — which is exactly the WSDL-valid
    # minimum payload.
    assert "WbMaximumClicks" not in search


def test_campaigns_add_unified_search_wb_max_conversion_rate_payload():
    body = _dry_run(
        *_unified_base_args(),
        "--search-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--goal-id",
        "42",
        "--unified-search-weekly-spend-limit",
        "200000000",
    )
    search = _unified_search_extract(body)
    assert search["BiddingStrategyType"] == "WB_MAXIMUM_CONVERSION_RATE"
    assert search["WbMaximumConversionRate"] == {
        "GoalId": 42,
        "WeeklySpendLimit": 200000000,
    }


def test_campaigns_add_unified_search_wb_max_conversion_rate_requires_goal_id():
    """StrategyMaximumConversionRateAdd.GoalId is WSDL minOccurs=1
    (campaigns.xml L1352). WeeklySpendLimit / CustomPeriodBudget are
    minOccurs=0, so a bare ``--search-strategy WB_MAXIMUM_CONVERSION_RATE
    --goal-id N`` is sufficient (no budget required) — but omitting the
    GoalId is still rejected."""
    result = _rejected(
        *_unified_base_args(),
        "--search-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
    )
    assert "--goal-id" in result.output
    assert "WbMaximumConversionRate" in result.output


def test_campaigns_add_unified_search_wb_max_conversion_rate_bare_goal_id_payload():
    """Per WSDL, only GoalId is required for WB_MAXIMUM_CONVERSION_RATE;
    WeeklySpendLimit / CustomPeriodBudget are minOccurs=0."""
    body = _dry_run(
        *_unified_base_args(),
        "--search-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--goal-id",
        "42",
    )
    search = _unified_search_extract(body)
    assert search["BiddingStrategyType"] == "WB_MAXIMUM_CONVERSION_RATE"
    assert search["WbMaximumConversionRate"] == {"GoalId": 42}


def test_campaigns_add_unified_search_wb_max_clicks_with_custom_period_payload():
    """CustomPeriodBudget satisfies the WeeklySpendLimit requirement for
    WB_MAXIMUM_CLICKS as alternate budget slice."""
    body = _dry_run(
        *_unified_base_args(),
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--unified-search-custom-period-spend-limit",
        "300000000",
        "--unified-search-custom-period-start-date",
        "2026-07-01",
        "--unified-search-custom-period-end-date",
        "2026-07-31",
        "--unified-search-custom-period-auto-continue",
        "NO",
    )
    search = _unified_search_extract(body)
    assert search["WbMaximumClicks"] == {
        "CustomPeriodBudget": {
            "SpendLimit": 300000000,
            "StartDate": "2026-07-01",
            "EndDate": "2026-07-31",
            "AutoContinue": "NO",
        }
    }


def test_campaigns_add_unified_search_average_cpc_payload():
    body = _dry_run(
        *_unified_base_args(),
        "--search-strategy",
        "AVERAGE_CPC",
        "--unified-search-average-cpc",
        "12000000",
        "--unified-search-weekly-spend-limit",
        "1000000000",
    )
    search = _unified_search_extract(body)
    assert search["BiddingStrategyType"] == "AVERAGE_CPC"
    assert search["AverageCpc"] == {
        "AverageCpc": 12000000,
        "WeeklySpendLimit": 1000000000,
    }


def test_campaigns_add_unified_search_average_cpc_requires_average_cpc():
    result = _rejected(*_unified_base_args(), "--search-strategy", "AVERAGE_CPC")
    assert "--unified-search-average-cpc" in result.output


def test_campaigns_add_unified_search_average_cpa_payload():
    body = _dry_run(
        *_unified_base_args(),
        "--search-strategy",
        "AVERAGE_CPA",
        "--average-cpa",
        "500000000",
        "--goal-id",
        "1234",
        "--bid-ceiling",
        "1000000000",
    )
    search = _unified_search_extract(body)
    assert search["BiddingStrategyType"] == "AVERAGE_CPA"
    assert search["AverageCpa"] == {
        "AverageCpa": 500000000,
        "GoalId": 1234,
        "BidCeiling": 1000000000,
    }


def test_campaigns_add_unified_search_average_cpa_requires_average_cpa_and_goal():
    result = _rejected(*_unified_base_args(), "--search-strategy", "AVERAGE_CPA")
    out = result.output
    assert "--average-cpa" in out and "--goal-id" in out


def test_campaigns_add_unified_search_pay_for_conversion_payload():
    body = _dry_run(
        *_unified_base_args(),
        "--search-strategy",
        "PAY_FOR_CONVERSION",
        "--unified-search-pay-cpa",
        "150000000",
        "--goal-id",
        "777",
    )
    search = _unified_search_extract(body)
    assert search["BiddingStrategyType"] == "PAY_FOR_CONVERSION"
    assert search["PayForConversion"] == {"Cpa": 150000000, "GoalId": 777}


def test_campaigns_add_unified_search_pay_for_conversion_requires_cpa_and_goal():
    result = _rejected(
        *_unified_base_args(),
        "--search-strategy",
        "PAY_FOR_CONVERSION",
    )
    out = result.output
    assert "--unified-search-pay-cpa" in out and "--goal-id" in out


def test_campaigns_add_unified_search_average_crr_payload():
    body = _dry_run(
        *_unified_base_args(),
        "--search-strategy",
        "AVERAGE_CRR",
        "--crr",
        "25",
        "--goal-id",
        "1",
    )
    search = _unified_search_extract(body)
    assert search["BiddingStrategyType"] == "AVERAGE_CRR"
    assert search["AverageCrr"] == {"Crr": 25, "GoalId": 1}


def test_campaigns_add_unified_search_pay_for_conversion_crr_payload():
    body = _dry_run(
        *_unified_base_args(),
        "--search-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--crr",
        "30",
        "--goal-id",
        "2",
    )
    search = _unified_search_extract(body)
    assert search["BiddingStrategyType"] == "PAY_FOR_CONVERSION_CRR"
    assert search["PayForConversionCrr"] == {"Crr": 30, "GoalId": 2}


def test_campaigns_add_unified_search_max_profit_payload():
    """StrategyMaxProfitAdd has only optional fields per WSDL L1489-1495,
    but the *Multi/MaxProfit container must always be emitted so the API
    can discriminate the strategy."""
    body = _dry_run(
        *_unified_base_args(),
        "--search-strategy",
        "MAX_PROFIT",
        "--unified-search-weekly-spend-limit",
        "5000000000",
    )
    search = _unified_search_extract(body)
    assert search["BiddingStrategyType"] == "MAX_PROFIT"
    assert search["MaxProfit"] == {"WeeklySpendLimit": 5000000000}


def test_campaigns_add_unified_search_average_cpa_multiple_goals_payload():
    """StrategyAverageCpaMultipleGoalsAdd has only optional fields per
    WSDL L1496-1503; the subtype container must always be emitted."""
    body = _dry_run(
        *_unified_base_args(),
        "--search-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--unified-search-weekly-spend-limit",
        "1000000000",
        "--bid-ceiling",
        "500000000",
    )
    search = _unified_search_extract(body)
    assert search["BiddingStrategyType"] == "AVERAGE_CPA_MULTIPLE_GOALS"
    assert search["AverageCpaMultipleGoals"] == {
        "WeeklySpendLimit": 1000000000,
        "BidCeiling": 500000000,
    }


def test_campaigns_add_unified_search_pay_for_conversion_multi_goals_payload():
    body = _dry_run(
        *_unified_base_args(),
        "--search-strategy",
        "PAY_FOR_CONVERSION_MULTIPLE_GOALS",
        "--unified-search-weekly-spend-limit",
        "2000000000",
    )
    search = _unified_search_extract(body)
    assert search["BiddingStrategyType"] == "PAY_FOR_CONVERSION_MULTIPLE_GOALS"
    assert search["PayForConversionMultipleGoals"] == {
        "WeeklySpendLimit": 2000000000,
    }


def test_campaigns_add_unified_search_rejects_average_cpc_for_pay_for_conversion():
    """--unified-search-average-cpc is only valid for AverageCpc; passing
    it with PAY_FOR_CONVERSION must raise UsageError, not silently drop
    (invariant #2 in test_wsdl_parity_gate)."""
    result = _rejected(
        *_unified_base_args(),
        "--search-strategy",
        "PAY_FOR_CONVERSION",
        "--unified-search-pay-cpa",
        "150000000",
        "--goal-id",
        "1",
        "--unified-search-average-cpc",
        "5000000",
    )
    assert "--unified-search-average-cpc" in result.output
    assert "PAY_FOR_CONVERSION" in result.output


def test_campaigns_add_unified_search_rejects_bid_ceiling_on_average_cpc():
    """StrategyAverageCpcAdd has no BidCeiling per WSDL L1363-1369."""
    result = _rejected(
        *_unified_base_args(),
        "--search-strategy",
        "AVERAGE_CPC",
        "--unified-search-average-cpc",
        "5000000",
        "--bid-ceiling",
        "1000000",
    )
    assert "--bid-ceiling" in result.output


def test_campaigns_add_unified_search_rejects_partial_custom_period_budget():
    """CustomPeriodBudget is all-or-nothing per WSDL L1965-1971."""
    result = _rejected(
        *_unified_base_args(),
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--unified-search-custom-period-spend-limit",
        "100000000",
    )
    assert "custom-period" in result.output


def test_campaigns_add_unified_search_rejects_partial_exploration_budget():
    result = _rejected(
        *_unified_base_args(),
        "--search-strategy",
        "AVERAGE_CPA",
        "--average-cpa",
        "500000000",
        "--goal-id",
        "1",
        "--unified-search-exploration-min-budget",
        "100000000",
    )
    assert "ExplorationBudget" in result.output


def test_campaigns_add_unified_search_exploration_is_custom_accepts_no():
    """Cached WSDL declares ``IsMinimumExplorationBudgetCustom`` as
    ``general:YesNoEnum`` with no restriction (campaigns.xml L1973-1977),
    so the CLI accepts both YES and NO — the canonical source for this
    PR is the WSDL, not Yandex public docs (showcaptcha-blocked, see
    #363 issue body)."""
    body = _dry_run(
        *_unified_base_args(),
        "--search-strategy",
        "AVERAGE_CPA",
        "--average-cpa",
        "500000000",
        "--goal-id",
        "1",
        "--unified-search-exploration-min-budget",
        "100000000",
        "--unified-search-exploration-is-custom",
        "NO",
    )
    search = _unified_search_extract(body)
    assert search["AverageCpa"]["ExplorationBudget"] == {
        "MinimumExplorationBudget": 100000000,
        "IsMinimumExplorationBudgetCustom": "NO",
    }


def test_campaigns_add_unified_search_rejects_detail_without_strategy():
    """Detail flags require a non-legacy --search-strategy. On add the
    container defaults to HIGHEST_POSITION (no subtype block), so detail
    flags surface the same "legacy strategy does not accept detail
    flags" error as for explicit HIGHEST_POSITION (mirror TextCampaign
    #388)."""
    result = _rejected(
        *_unified_base_args(),
        "--unified-search-weekly-spend-limit",
        "100000000",
    )
    assert "HIGHEST_POSITION" in result.output
    assert "--unified-search-weekly-spend-limit" in result.output


def test_campaigns_update_unified_search_rejects_detail_without_strategy():
    """On update there is no default strategy, so detail flags emit the
    canonical "--search-strategy required" error."""
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "777",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--unified-search-weekly-spend-limit",
        "100000000",
    )
    assert "--search-strategy" in result.output


def test_campaigns_add_unified_search_placement_types_payload():
    """UnifiedCampaign-only placements: Maps + SearchOrganizationList
    (WSDL L172-180 / L636-644)."""
    body = _dry_run(
        *_unified_base_args(),
        "--search-strategy",
        "AVERAGE_CPC",
        "--unified-search-average-cpc",
        "5000000",
        "--search-placement-search-results",
        "YES",
        "--search-placement-product-gallery",
        "NO",
        "--search-placement-dynamic-places",
        "YES",
        "--unified-search-placement-maps",
        "YES",
        "--unified-search-placement-search-organization-list",
        "NO",
    )
    search = _unified_search_extract(body)
    assert search["PlacementTypes"] == {
        "SearchResults": "YES",
        "ProductGallery": "NO",
        "DynamicPlaces": "YES",
        "Maps": "YES",
        "SearchOrganizationList": "NO",
    }


def test_campaigns_add_unified_search_rejects_average_cpa_with_highest_position():
    """Legacy CPA flag with HIGHEST_POSITION must surface the
    canonical 'CPA-shaped' error mirroring TextCampaign #361/#388."""
    result = _rejected(
        *_unified_base_args(),
        "--search-strategy",
        "HIGHEST_POSITION",
        "--average-cpa",
        "500000000",
    )
    assert "CPA-shaped" in result.output


def test_campaigns_add_unified_search_rejects_invalid_strategy():
    """Enum drift: only the 13 UnifiedCampaignSearchStrategyTypeEnum
    values are accepted (UNKNOWN is read-side only)."""
    result = _rejected(
        *_unified_base_args(),
        "--search-strategy",
        "BOGUS_STRATEGY",
    )
    assert "must be one of" in result.output


def test_campaigns_add_unified_search_rejects_weekly_click_package():
    """WEEKLY_CLICK_PACKAGE is in TextCampaign's enum but NOT in
    UnifiedCampaign's enum (WSDL L262-278) — must be rejected."""
    result = _rejected(
        *_unified_base_args(),
        "--search-strategy",
        "WEEKLY_CLICK_PACKAGE",
    )
    assert "must be one of" in result.output


def test_campaigns_add_unified_search_rejects_average_roi():
    """AVERAGE_ROI is not in UnifiedCampaignSearchStrategyTypeEnum
    (WSDL L262-278) — must be rejected."""
    result = _rejected(
        *_unified_base_args(),
        "--search-strategy",
        "AVERAGE_ROI",
    )
    assert "must be one of" in result.output


def test_campaigns_update_unified_search_average_cpc_payload():
    body = _unified_search_update(
        "--search-strategy",
        "AVERAGE_CPC",
        "--unified-search-average-cpc",
        "7000000",
    )
    search = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPC",
        "AverageCpc": {"AverageCpc": 7000000},
    }


def test_campaigns_update_unified_search_average_cpa_payload():
    body = _unified_search_update(
        "--search-strategy",
        "AVERAGE_CPA",
        "--average-cpa",
        "500000000",
        "--goal-id",
        "42",
    )
    search = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search["BiddingStrategyType"] == "AVERAGE_CPA"
    assert search["AverageCpa"] == {"AverageCpa": 500000000, "GoalId": 42}


def test_campaigns_update_unified_search_pay_for_conversion_payload():
    body = _unified_search_update(
        "--search-strategy",
        "PAY_FOR_CONVERSION",
        "--unified-search-pay-cpa",
        "100000000",
        "--goal-id",
        "9",
    )
    search = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search["PayForConversion"] == {"Cpa": 100000000, "GoalId": 9}


def test_campaigns_update_unified_search_wb_max_clicks_payload():
    body = _unified_search_update(
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--unified-search-weekly-spend-limit",
        "500000000",
    )
    search = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search["WbMaximumClicks"] == {"WeeklySpendLimit": 500000000}


def test_campaigns_update_unified_search_wb_max_conv_rate_payload():
    body = _unified_search_update(
        "--search-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--goal-id",
        "55",
    )
    search = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search["WbMaximumConversionRate"] == {"GoalId": 55}


def test_campaigns_update_unified_search_average_crr_payload():
    body = _unified_search_update(
        "--search-strategy",
        "AVERAGE_CRR",
        "--crr",
        "40",
        "--goal-id",
        "8",
    )
    search = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search["AverageCrr"] == {"Crr": 40, "GoalId": 8}


def test_campaigns_update_unified_search_pay_for_conversion_crr_payload():
    body = _unified_search_update(
        "--search-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--crr",
        "20",
        "--goal-id",
        "7",
    )
    search = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search["PayForConversionCrr"] == {"Crr": 20, "GoalId": 7}


def test_campaigns_update_unified_search_max_profit_payload():
    body = _unified_search_update(
        "--search-strategy",
        "MAX_PROFIT",
        "--unified-search-weekly-spend-limit",
        "3000000000",
    )
    search = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search["MaxProfit"] == {"WeeklySpendLimit": 3000000000}


def test_campaigns_update_unified_search_multi_goals_payload():
    body = _unified_search_update(
        "--search-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--unified-search-weekly-spend-limit",
        "1500000000",
    )
    search = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search["AverageCpaMultipleGoals"] == {"WeeklySpendLimit": 1500000000}


def test_campaigns_update_unified_search_pay_for_conversion_multi_goals_payload():
    body = _unified_search_update(
        "--search-strategy",
        "PAY_FOR_CONVERSION_MULTIPLE_GOALS",
        "--unified-search-weekly-spend-limit",
        "2500000000",
    )
    search = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search["PayForConversionMultipleGoals"] == {"WeeklySpendLimit": 2500000000}


def test_campaigns_update_unified_search_partial_field_no_required_check():
    """On update partial patches are legitimate when --search-strategy is
    NOT switched (WSDL update-side fields are all minOccurs=0)."""
    body = _unified_search_update(
        "--unified-search-weekly-spend-limit",
        "100000000",
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
    )
    # WB_MAXIMUM_CLICKS update path uses _UNIFIED_SEARCH_REQUIRED_TYPED_
    # FLAGS_UPDATE which intentionally omits WbMaximumClicks (docs declare
    # every field optional on update). So a one-field patch is allowed.
    assert "WbMaximumClicks" in (
        body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"]["Search"]
    )


def test_campaigns_update_unified_search_omits_bidding_strategy_when_unused():
    """Update with a non-strategy field only (e.g. --setting) must NOT
    include BiddingStrategy in the payload (no silent overwrite)."""
    body = _unified_search_update("--setting", "ADD_METRICA_TAG=YES")
    assert "BiddingStrategy" not in body["params"]["Campaigns"][0]["UnifiedCampaign"]


def test_campaigns_update_unified_search_budget_type_weekly_payload():
    body = _unified_search_update(
        "--search-strategy",
        "AVERAGE_CPC",
        "--unified-search-average-cpc",
        "5000000",
        "--unified-search-weekly-spend-limit",
        "200000000",
        "--unified-search-budget-type",
        "WEEKLY_BUDGET",
    )
    search = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Search"
    ]
    avc = search["AverageCpc"]
    assert avc["BudgetType"] == "WEEKLY_BUDGET"
    assert avc["CustomPeriodBudget"] is None  # explicit clearing


def test_campaigns_update_unified_search_budget_type_custom_period_payload():
    body = _unified_search_update(
        "--search-strategy",
        "AVERAGE_CPC",
        "--unified-search-average-cpc",
        "5000000",
        "--unified-search-custom-period-spend-limit",
        "300000000",
        "--unified-search-custom-period-start-date",
        "2026-08-01",
        "--unified-search-custom-period-end-date",
        "2026-08-31",
        "--unified-search-custom-period-auto-continue",
        "YES",
        "--unified-search-budget-type",
        "CUSTOM_PERIOD_BUDGET",
    )
    search = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Search"
    ]
    avc = search["AverageCpc"]
    assert avc["BudgetType"] == "CUSTOM_PERIOD_BUDGET"
    assert avc["WeeklySpendLimit"] is None


def test_campaigns_add_unified_search_budget_type_is_update_only():
    """--unified-search-budget-type does not exist on add (the Click option
    is registered only on the update command); on add the budget slice is
    inferred from WeeklySpendLimit vs CustomPeriodBudget presence."""
    result = _rejected(
        *_unified_base_args(),
        "--search-strategy",
        "AVERAGE_CPC",
        "--unified-search-average-cpc",
        "5000000",
        "--unified-search-budget-type",
        "WEEKLY_BUDGET",
    )
    # Click reports unknown option for add
    assert "--unified-search-budget-type" in result.output


def test_campaigns_update_unified_search_package_strategy_conflicts():
    """PackageBiddingStrategy is mutually exclusive with --unified-search-*
    on update (WSDL: UnifiedCampaignUpdateItem allows one of
    BiddingStrategy / PackageBiddingStrategy)."""
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "777",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--package-strategy-id",
        "1",
        "--unified-search-weekly-spend-limit",
        "100000000",
    )
    assert "PackageBiddingStrategy" in result.output


def test_campaigns_add_unified_search_package_strategy_conflicts():
    """PackageBiddingStrategy on add must also reject every typed
    ``--unified-search-*`` flag — otherwise input is silently dropped."""
    result = _rejected(
        *_unified_base_args(),
        "--package-strategy-id",
        "1",
        "--package-strategy-from-campaign-id",
        "2",
        "--package-platform-search-result",
        "YES",
        "--package-platform-product-gallery",
        "YES",
        "--package-platform-network",
        "YES",
        "--unified-search-weekly-spend-limit",
        "100000000",
    )
    assert "PackageBiddingStrategy" in result.output


def test_campaigns_update_unified_search_wb_max_clicks_budget_type_payload():
    body = _unified_search_update(
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--unified-search-weekly-spend-limit",
        "100000000",
        "--unified-search-budget-type",
        "WEEKLY_BUDGET",
    )
    search = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Search"
    ]
    block = search["WbMaximumClicks"]
    assert block["BudgetType"] == "WEEKLY_BUDGET"
    assert block["CustomPeriodBudget"] is None


def test_campaigns_update_unified_search_wb_max_conv_rate_budget_type_payload():
    body = _unified_search_update(
        "--search-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--goal-id",
        "1",
        "--unified-search-custom-period-spend-limit",
        "200000000",
        "--unified-search-custom-period-start-date",
        "2026-10-01",
        "--unified-search-custom-period-end-date",
        "2026-10-31",
        "--unified-search-custom-period-auto-continue",
        "YES",
        "--unified-search-budget-type",
        "CUSTOM_PERIOD_BUDGET",
    )
    search = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Search"
    ]
    block = search["WbMaximumConversionRate"]
    assert block["BudgetType"] == "CUSTOM_PERIOD_BUDGET"
    assert block["WeeklySpendLimit"] is None


def test_campaigns_update_unified_search_avg_cpa_multi_goals_budget_type_payload():
    body = _unified_search_update(
        "--search-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--unified-search-weekly-spend-limit",
        "500000000",
        "--unified-search-budget-type",
        "WEEKLY_BUDGET",
    )
    search = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Search"
    ]
    block = search["AverageCpaMultipleGoals"]
    assert block["BudgetType"] == "WEEKLY_BUDGET"


def test_campaigns_update_unified_search_standalone_budget_type_payload():
    """BudgetType can be patched standalone — the WSDL get-side
    Strategy* types declare it as an independent optional element
    (campaigns.xml L817, L827, etc.). Per cached WSDL all update-side
    fields are minOccurs=0, so the CLI does NOT re-require unrelated
    bidding values (e.g. --unified-search-average-cpc) when only
    BudgetType is being patched. This diverges from the docs-strict
    TextCampaign Search (#388) precedent."""
    body = _unified_search_update(
        "--search-strategy",
        "AVERAGE_CPC",
        "--unified-search-budget-type",
        "CUSTOM_PERIOD_BUDGET",
    )
    search = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Search"
    ]
    block = search["AverageCpc"]
    assert block["BudgetType"] == "CUSTOM_PERIOD_BUDGET"
    # The alternate-slice nulling stays — switching to CUSTOM_PERIOD_BUDGET
    # explicitly clears the stored WeeklySpendLimit, mirroring the
    # TextCampaign/MobileApp builder convention.
    assert block["WeeklySpendLimit"] is None


@pytest.mark.parametrize(
    "strategy,subtype",
    [
        ("WB_MAXIMUM_CLICKS", "WbMaximumClicks"),
        ("WB_MAXIMUM_CONVERSION_RATE", "WbMaximumConversionRate"),
        ("AVERAGE_CPC", "AverageCpc"),
        ("AVERAGE_CPA", "AverageCpa"),
        ("PAY_FOR_CONVERSION", "PayForConversion"),
        ("AVERAGE_CRR", "AverageCrr"),
        ("PAY_FOR_CONVERSION_CRR", "PayForConversionCrr"),
        ("AVERAGE_CPA_MULTIPLE_GOALS", "AverageCpaMultipleGoals"),
        ("PAY_FOR_CONVERSION_MULTIPLE_GOALS", "PayForConversionMultipleGoals"),
        ("MAX_PROFIT", "MaxProfit"),
    ],
)
def test_campaigns_update_unified_search_budget_type_only_per_subtype(
    strategy: str, subtype: str
):
    """Per WSDL the entire update-side Strategy* surface is minOccurs=0,
    so BudgetType can be patched standalone on every UnifiedCampaign
    Search subtype without re-supplying the strategy's other fields."""
    body = _unified_search_update(
        "--search-strategy",
        strategy,
        "--unified-search-budget-type",
        "WEEKLY_BUDGET",
    )
    search = body["params"]["Campaigns"][0]["UnifiedCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search["BiddingStrategyType"] == strategy
    assert search[subtype]["BudgetType"] == "WEEKLY_BUDGET"


def test_campaigns_update_unified_search_budget_type_weekly_rejects_custom_period():
    """Silent-data-loss guard: WEEKLY_BUDGET would null out a provided
    CustomPeriodBudget block."""
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "777",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPC",
        "--unified-search-budget-type",
        "WEEKLY_BUDGET",
        "--unified-search-custom-period-spend-limit",
        "200000000",
        "--unified-search-custom-period-start-date",
        "2026-09-01",
        "--unified-search-custom-period-end-date",
        "2026-09-30",
        "--unified-search-custom-period-auto-continue",
        "YES",
    )
    assert "WEEKLY_BUDGET" in result.output
    assert "custom-period" in result.output


def test_campaigns_update_unified_search_budget_type_custom_period_rejects_weekly():
    """Silent-data-loss guard: CUSTOM_PERIOD_BUDGET would null out a
    provided WeeklySpendLimit value."""
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "777",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPC",
        "--unified-search-budget-type",
        "CUSTOM_PERIOD_BUDGET",
        "--unified-search-weekly-spend-limit",
        "100000000",
    )
    assert "CUSTOM_PERIOD_BUDGET" in result.output
    assert "weekly-spend-limit" in result.output


def test_adgroups_add_batch_unified_routing_note(tmp_path):
    # A UnifiedAdGroup row still builds correctly in batch mode; the real send
    # would route via _post_adgroups (v501), but dry-run only previews the body.
    rows = [
        {
            "name": "U",
            "campaign-id": 1,
            "region-ids": "225",
            "type": "UNIFIED_AD_GROUP",
            "offer-retargeting": "YES",
        }
    ]
    path = _write_jsonl(tmp_path, rows)
    body = _dry_run("adgroups", "add", "--from-file", path)
    assert body["firstChunk"]["params"]["AdGroups"][0]["UnifiedAdGroup"] == {
        "OfferRetargeting": "YES"
    }


def test_adgroups_add_batch_rejects_mixed_unified_and_non_unified(tmp_path):
    # _post_adgroups routes the WHOLE body to v501 if any item is unified, so a
    # mix would send non-unified groups to the wrong endpoint. Refuse it.
    rows = [
        {"name": "T", "campaign-id": 1, "region-ids": "225", "type": "TEXT_AD_GROUP"},
        {
            "name": "U",
            "campaign-id": 1,
            "region-ids": "225",
            "type": "UNIFIED_AD_GROUP",
            "offer-retargeting": "YES",
        },
    ]
    path = _write_jsonl(tmp_path, rows)
    result = _rejected("adgroups", "add", "--from-file", path)
    assert "may not mix UNIFIED_AD_GROUP" in result.output


def test_adgroups_add_batch_all_unified_is_allowed(tmp_path):
    # An all-unified batch is fine — the whole body routes to v501 correctly.
    rows = [
        {
            "name": f"U{i}",
            "campaign-id": 1,
            "region-ids": "225",
            "type": "UNIFIED_AD_GROUP",
            "offer-retargeting": "YES",
        }
        for i in range(2)
    ]
    path = _write_jsonl(tmp_path, rows)
    body = _dry_run("adgroups", "add", "--from-file", path)
    groups = body["firstChunk"]["params"]["AdGroups"]
    assert all("UnifiedAdGroup" in g for g in groups)


def test_adgroups_update_batch_rejects_mixed_unified_and_non_unified(tmp_path):
    # _post_adgroups routes the whole body to v501 if any item is unified.
    rows = [
        {"id": 5, "name": "T"},
        {"id": 6, "offer-retargeting": "YES"},
    ]
    path = _write_jsonl(tmp_path, rows)
    result = _rejected("adgroups", "update", "--from-file", path)
    assert "may not mix UNIFIED_AD_GROUP" in result.output
