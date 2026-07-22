"""Dry-run payload tests for TEXT campaign search/network bidding strategies.

Split out of the historical monolithic ``tests/test_dry_run.py`` (issue #604).
See :mod:`tests.test_dry_run_shared` for the shared invocation helpers and
``tests/test_dry_run.py`` for the rationale behind the whole suite.
"""

from click.testing import CliRunner

from direct_cli.cli import cli
from tests.test_dry_run_shared import _dry_run, _failing_run, _rejected
from tests.test_dry_run_strategy_smart import _cpa_base_args


def test_campaigns_add_text_search_placement_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "HIGHEST_POSITION",
        "--search-placement-search-results",
        "YES",
        "--search-placement-product-gallery",
        "NO",
        "--search-placement-dynamic-places",
        "YES",
    )
    search = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"]["Search"]
    assert search == {
        "BiddingStrategyType": "HIGHEST_POSITION",
        "PlacementTypes": {
            "SearchResults": "YES",
            "ProductGallery": "NO",
            "DynamicPlaces": "YES",
        },
    }


def test_campaigns_update_text_search_placement_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "TEXT_CAMPAIGN",
        "--search-strategy",
        "SERVING_OFF",
        "--search-placement-product-gallery",
        "NO",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text["BiddingStrategy"]["Search"] == {
        "BiddingStrategyType": "SERVING_OFF",
        "PlacementTypes": {"ProductGallery": "NO"},
    }


def test_campaigns_add_text_search_placement_requires_strategy():
    result = _rejected(
        *_cpa_base_args(),
        "--search-placement-search-results",
        "YES",
    )
    assert (
        "TextCampaign search placement flags require --search-strategy" in result.output
    )


def test_campaigns_add_text_search_rejects_unknown_strategy():
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "BROKEN",
    )
    assert "--search-strategy for TEXT_CAMPAIGN must be one of" in result.output


def test_campaigns_help_exposes_text_search_placement_flags():
    placement_flags = {
        "--search-placement-search-results",
        "--search-placement-product-gallery",
        "--search-placement-dynamic-places",
    }
    out_of_scope_flags = {
        "--search-weekly-spend-limit",
        "--search-budget-type",
        "--search-average-cpa",
        "--search-crr",
    }
    for command in ("add", "update"):
        result = CliRunner().invoke(cli, ["campaigns", command, "--help"])
        assert result.exit_code == 0
        for flag in placement_flags:
            assert flag in result.output
        for flag in out_of_scope_flags:
            assert flag not in result.output


def test_campaigns_add_dynamic_text_network_default_payload():
    """#365: NETWORK_DEFAULT emits NetworkDefault.LimitPercent only."""
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net Default",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "NETWORK_DEFAULT",
        "--dyn-network-limit-percent",
        "40",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "NETWORK_DEFAULT",
        "NetworkDefault": {"LimitPercent": 40},
    }


def test_campaigns_add_dynamic_text_network_maximum_coverage_payload():
    """#365: MAXIMUM_COVERAGE accepts no detail block."""
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net Max Coverage",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "MAXIMUM_COVERAGE",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {"BiddingStrategyType": "MAXIMUM_COVERAGE"}


def test_campaigns_add_dynamic_text_network_wb_maximum_clicks_weekly_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net WbClicks Weekly",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--dyn-network-weekly-spend-limit",
        "1000000000",
        "--dyn-network-bid-ceiling",
        "100000000",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
        "WbMaximumClicks": {
            "WeeklySpendLimit": 1000000000,
            "BidCeiling": 100000000,
        },
    }


def test_campaigns_add_dynamic_text_network_wb_maximum_clicks_custom_period_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net WbClicks CP",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--dyn-network-custom-period-spend-limit",
        "5000000000",
        "--dyn-network-custom-period-start-date",
        "2026-06-01",
        "--dyn-network-custom-period-end-date",
        "2026-06-30",
        "--dyn-network-custom-period-auto-continue",
        "NO",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
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


def test_campaigns_add_dynamic_text_network_wb_maximum_conversion_rate_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net WbConvRate",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--dyn-network-goal-id",
        "77",
        "--dyn-network-weekly-spend-limit",
        "2000000000",
        "--dyn-network-bid-ceiling",
        "50000000",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
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


def test_campaigns_add_dynamic_text_network_average_cpc_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net AvgCpc",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPC",
        "--dyn-network-average-cpc",
        "7000000",
        "--dyn-network-weekly-spend-limit",
        "500000000",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPC",
        "AverageCpc": {
            "AverageCpc": 7000000,
            "WeeklySpendLimit": 500000000,
        },
    }


def test_campaigns_add_dynamic_text_network_average_cpa_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net AvgCpa",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPA",
        "--dyn-network-average-cpa",
        "150000000",
        "--dyn-network-goal-id",
        "12",
        "--dyn-network-bid-ceiling",
        "20000000",
        "--dyn-network-exploration-budget",
        "300000000",
        "--dyn-network-exploration-budget-custom",
        "YES",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
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


def test_campaigns_add_dynamic_text_network_pay_for_conversion_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net PayForConv",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "PAY_FOR_CONVERSION",
        "--dyn-network-cpa",
        "300000000",
        "--dyn-network-goal-id",
        "55",
        "--dyn-network-weekly-spend-limit",
        "2500000000",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
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


def test_campaigns_add_dynamic_text_network_average_roi_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net AvgRoi",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_ROI",
        "--dyn-network-reserve-return",
        "60",
        "--dyn-network-roi-coef",
        "150",
        "--dyn-network-goal-id",
        "88",
        "--dyn-network-profitability",
        "25",
        "--dyn-network-bid-ceiling",
        "12000000",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_ROI",
        "AverageRoi": {
            "ReserveReturn": 60,
            "RoiCoef": 150,
            "GoalId": 88,
            "BidCeiling": 12000000,
            "Profitability": 25,
        },
    }


def test_campaigns_add_dynamic_text_network_average_crr_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net AvgCrr",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CRR",
        "--dyn-network-crr",
        "30",
        "--dyn-network-goal-id",
        "61",
        "--dyn-network-weekly-spend-limit",
        "800000000",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
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


def test_campaigns_add_dynamic_text_network_pay_for_conversion_crr_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net P4CCrr",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--dyn-network-crr",
        "25",
        "--dyn-network-goal-id",
        "44",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_CRR",
        "PayForConversionCrr": {
            "Crr": 25,
            "GoalId": 44,
        },
    }


def test_campaigns_add_dynamic_text_network_weekly_click_package_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net WeeklyClick",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "WEEKLY_CLICK_PACKAGE",
        "--dyn-network-clicks-per-week",
        "200",
        "--dyn-network-average-cpc",
        "3000000",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WEEKLY_CLICK_PACKAGE",
        "WeeklyClickPackage": {
            "AverageCpc": 3000000,
            "ClicksPerWeek": 200,
        },
    }


def test_campaigns_add_dynamic_text_network_serving_off_payload():
    """#365: SERVING_OFF (and no flags) is the implicit default."""
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net Off",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {"BiddingStrategyType": "SERVING_OFF"}


def test_campaigns_add_dynamic_text_network_rejects_detail_without_strategy():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Dyn Missing Strategy",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--dyn-network-average-cpc",
        "5000000",
    )
    assert (
        "DynamicTextCampaign network detail flags require --network-strategy"
        in result.output
    )


def test_campaigns_add_dynamic_text_network_rejects_average_cpc_for_average_cpa():
    """#365: WSDL field-support gate — AverageCpa subtype has no AverageCpc."""
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Dyn Bad Field",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPA",
        "--dyn-network-average-cpa",
        "100000000",
        "--dyn-network-goal-id",
        "1",
        "--dyn-network-average-cpc",
        "5000000",
    )
    assert "AVERAGE_CPA does not accept --dyn-network-average-cpc" in result.output


def test_campaigns_add_dynamic_text_network_rejects_average_cpa_required_fields():
    """#365: WSDL minOccurs=1 gate — AverageCpa needs AverageCpa+GoalId."""
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Dyn Missing Req",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPA",
    )
    assert "AVERAGE_CPA requires" in result.output
    assert "--dyn-network-average-cpa" in result.output
    assert "--dyn-network-goal-id" in result.output


def test_campaigns_add_dynamic_text_network_rejects_average_roi_required_fields():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Dyn Roi Missing",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_ROI",
        "--dyn-network-reserve-return",
        "10",
    )
    assert "AVERAGE_ROI requires" in result.output
    assert "--dyn-network-roi-coef" in result.output
    assert "--dyn-network-goal-id" in result.output


def test_campaigns_add_dynamic_text_network_rejects_maximum_coverage_with_details():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Dyn MaxCov Bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "MAXIMUM_COVERAGE",
        "--dyn-network-bid-ceiling",
        "10000000",
    )
    assert (
        "MAXIMUM_COVERAGE does not accept DynamicTextCampaign network detail flags"
        in result.output
    )


def test_campaigns_add_dynamic_text_network_rejects_limit_percent_off_step():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Dyn LimitPct Bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "NETWORK_DEFAULT",
        "--dyn-network-limit-percent",
        "25",
    )
    assert "must be a multiple of 10" in result.output


def test_campaigns_add_dynamic_text_network_rejects_partial_custom_period():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Dyn CP Partial",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--dyn-network-custom-period-spend-limit",
        "100000000",
    )
    assert (
        "DynamicTextCampaign CustomPeriodBudget requires all custom-period flags"
        in result.output
    )


def test_campaigns_add_dynamic_text_network_weekly_click_package_combined_ceilings_payload():
    """#365: WSDL StrategyWeeklyClickPackageAdd allows AverageCpc + BidCeiling."""
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn WCP Combo",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "WEEKLY_CLICK_PACKAGE",
        "--dyn-network-clicks-per-week",
        "100",
        "--dyn-network-average-cpc",
        "5000000",
        "--dyn-network-bid-ceiling",
        "10000000",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WEEKLY_CLICK_PACKAGE",
        "WeeklyClickPackage": {
            "AverageCpc": 5000000,
            "BidCeiling": 10000000,
            "ClicksPerWeek": 100,
        },
    }


def test_campaigns_add_dynamic_text_network_rejects_partial_exploration_budget():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Dyn ExpBudget Partial",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPA",
        "--dyn-network-average-cpa",
        "100000000",
        "--dyn-network-goal-id",
        "1",
        "--dyn-network-exploration-budget",
        "100000000",
    )
    assert "DynamicTextCampaign ExplorationBudget requires both" in result.output


def test_campaigns_update_dynamic_text_network_average_cpc_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "999",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPC",
        "--dyn-network-average-cpc",
        "8000000",
        "--dyn-network-weekly-spend-limit",
        "1500000000",
    )
    dyn = body["params"]["Campaigns"][0]["DynamicTextCampaign"]
    assert dyn["BiddingStrategy"] == {
        "Network": {
            "BiddingStrategyType": "AVERAGE_CPC",
            "AverageCpc": {
                "AverageCpc": 8000000,
                "WeeklySpendLimit": 1500000000,
            },
        }
    }


def test_campaigns_update_dynamic_text_network_budget_type_weekly_payload():
    """#365: BudgetType WEEKLY_BUDGET nulls CustomPeriodBudget."""
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "1001",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--dyn-network-weekly-spend-limit",
        "300000000",
        "--dyn-network-budget-type",
        "WEEKLY_BUDGET",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
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


def test_campaigns_update_dynamic_text_network_budget_type_custom_period_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "1002",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPC",
        "--dyn-network-average-cpc",
        "5000000",
        "--dyn-network-custom-period-spend-limit",
        "1000000000",
        "--dyn-network-custom-period-start-date",
        "2026-07-01",
        "--dyn-network-custom-period-end-date",
        "2026-07-31",
        "--dyn-network-custom-period-auto-continue",
        "YES",
        "--dyn-network-budget-type",
        "CUSTOM_PERIOD_BUDGET",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
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


def test_campaigns_update_dynamic_text_network_rejects_budget_type_without_weekly():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "1003",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--dyn-network-budget-type",
        "WEEKLY_BUDGET",
    )
    assert "--dyn-network-budget-type WEEKLY_BUDGET requires" in result.output


def test_campaigns_update_dynamic_text_network_rejects_partial_strategy():
    """#365: partial update with only --network-strategy still must emit a block."""
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "2001",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "SERVING_OFF",
    )
    dyn = body["params"]["Campaigns"][0]["DynamicTextCampaign"]
    assert dyn["BiddingStrategy"]["Network"] == {"BiddingStrategyType": "SERVING_OFF"}


def test_campaigns_update_dynamic_text_network_default_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "2002",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "NETWORK_DEFAULT",
        "--dyn-network-limit-percent",
        "50",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "NETWORK_DEFAULT",
        "NetworkDefault": {"LimitPercent": 50},
    }


def test_campaigns_update_dynamic_text_network_wb_maximum_clicks_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "2003",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--dyn-network-weekly-spend-limit",
        "700000000",
        "--dyn-network-bid-ceiling",
        "20000000",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
        "WbMaximumClicks": {
            "WeeklySpendLimit": 700000000,
            "BidCeiling": 20000000,
        },
    }


def test_campaigns_update_dynamic_text_network_wb_maximum_conversion_rate_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "2004",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--dyn-network-goal-id",
        "111",
        "--dyn-network-weekly-spend-limit",
        "1200000000",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WB_MAXIMUM_CONVERSION_RATE",
        "WbMaximumConversionRate": {
            "GoalId": 111,
            "WeeklySpendLimit": 1200000000,
        },
    }


def test_campaigns_update_dynamic_text_network_average_cpa_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "2005",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPA",
        "--dyn-network-average-cpa",
        "180000000",
        "--dyn-network-goal-id",
        "22",
        "--dyn-network-bid-ceiling",
        "15000000",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPA",
        "AverageCpa": {
            "AverageCpa": 180000000,
            "GoalId": 22,
            "BidCeiling": 15000000,
        },
    }


def test_campaigns_update_dynamic_text_network_pay_for_conversion_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "2006",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "PAY_FOR_CONVERSION",
        "--dyn-network-cpa",
        "250000000",
        "--dyn-network-goal-id",
        "33",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION",
        "PayForConversion": {
            "Cpa": 250000000,
            "GoalId": 33,
        },
    }


def test_campaigns_update_dynamic_text_network_average_roi_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "2007",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_ROI",
        "--dyn-network-reserve-return",
        "40",
        "--dyn-network-roi-coef",
        "120",
        "--dyn-network-goal-id",
        "44",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_ROI",
        "AverageRoi": {
            "ReserveReturn": 40,
            "RoiCoef": 120,
            "GoalId": 44,
        },
    }


def test_campaigns_update_dynamic_text_network_average_crr_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "2008",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CRR",
        "--dyn-network-crr",
        "20",
        "--dyn-network-goal-id",
        "55",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CRR",
        "AverageCrr": {
            "Crr": 20,
            "GoalId": 55,
        },
    }


def test_campaigns_update_dynamic_text_network_pay_for_conversion_crr_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "2009",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--dyn-network-crr",
        "15",
        "--dyn-network-goal-id",
        "66",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_CRR",
        "PayForConversionCrr": {
            "Crr": 15,
            "GoalId": 66,
        },
    }


def test_campaigns_update_dynamic_text_network_weekly_click_package_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "2010",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "WEEKLY_CLICK_PACKAGE",
        "--dyn-network-clicks-per-week",
        "350",
        "--dyn-network-bid-ceiling",
        "8000000",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WEEKLY_CLICK_PACKAGE",
        "WeeklyClickPackage": {
            "ClicksPerWeek": 350,
            "BidCeiling": 8000000,
        },
    }


def test_campaigns_update_dynamic_text_network_maximum_coverage_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "2011",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "MAXIMUM_COVERAGE",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {"BiddingStrategyType": "MAXIMUM_COVERAGE"}


def test_campaigns_add_dynamic_text_network_wb_maximum_clicks_bare_payload():
    """#365: WSDL StrategyMaximumClicksAdd has only minOccurs=0 fields.

    WeeklySpendLimit/BidCeiling/CustomPeriodBudget are all optional
    per the cached WSDL (StrategyWeeklyBudgetAddBase line 1333). The
    bare ``--network-strategy WB_MAXIMUM_CLICKS`` add request must
    therefore round-trip with no nested block.
    """
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net WbClicks Bare",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {"BiddingStrategyType": "WB_MAXIMUM_CLICKS"}


def test_campaigns_add_dynamic_text_network_wb_maximum_conversion_rate_only_goal_payload():
    """#365: only GoalId is WSDL-required for WbMaximumConversionRate."""
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Net WbConv MinGoal",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--dyn-network-goal-id",
        "9",
    )
    network = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WB_MAXIMUM_CONVERSION_RATE",
        "WbMaximumConversionRate": {"GoalId": 9},
    }


def test_campaigns_add_dynamic_text_network_rejects_reserve_return_over_100():
    """#365: --dyn-network-reserve-return is constrained to 0..100."""
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Dyn Roi Bad Reserve",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_ROI",
        "--dyn-network-reserve-return",
        "150",
        "--dyn-network-roi-coef",
        "1",
        "--dyn-network-goal-id",
        "1",
    )
    assert "Invalid value for '--dyn-network-reserve-return'" in result.output


def test_campaigns_add_dynamic_text_network_rejects_wb_maximum_conversion_rate_without_goal():
    """#365: WSDL minOccurs=1 GoalId on WbMaximumConversionRate is enforced."""
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Dyn WbConv Missing Goal",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--dyn-network-weekly-spend-limit",
        "1000000000",
    )
    assert "WB_MAXIMUM_CONVERSION_RATE requires --dyn-network-goal-id" in result.output


def test_campaigns_add_dynamic_text_network_rejects_dyn_flag_for_text_campaign():
    """#365: --dyn-network-* must be DynamicText-only (silent-data-loss gate)."""
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Text Bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "TEXT_CAMPAIGN",
        "--dyn-network-limit-percent",
        "30",
    )
    assert (
        "--dyn-network-limit-percent is not compatible with --type TEXT_CAMPAIGN"
        in result.output
    )


def test_campaigns_add_dynamic_text_network_rejects_invalid_enum_value():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Dyn Bad Enum",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "NOT_A_REAL_STRATEGY",
    )
    assert (
        "--network-strategy for DYNAMIC_TEXT_CAMPAIGN must be one of" in result.output
    )


def test_campaigns_add_dynamic_text_network_rejects_package_with_network_flag():
    """#365: PackageBiddingStrategy must not coexist with --dyn-network-*."""
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Dyn Pkg + Net",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--package-strategy-id",
        "111",
        "--dyn-network-limit-percent",
        "20",
    )
    assert "DynamicTextCampaign.PackageBiddingStrategy cannot be combined with" in (
        result.output
    )
    assert "--dyn-network-limit-percent" in result.output


def _text_search_extract(body: dict) -> dict:
    return body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"]["Search"]


def _text_search_update(*extra: str) -> dict:
    return _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "TEXT_CAMPAIGN",
        *extra,
    )


def test_campaigns_add_text_search_wb_maximum_clicks_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--text-search-weekly-spend-limit",
        "300000000",
        "--bid-ceiling",
        "5000000",
    )
    search = _text_search_extract(body)
    assert search["BiddingStrategyType"] == "WB_MAXIMUM_CLICKS"
    assert search["WbMaximumClicks"] == {
        "WeeklySpendLimit": 300000000,
        "BidCeiling": 5000000,
    }


def test_campaigns_add_text_search_wb_maximum_conversion_rate_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--goal-id",
        "555",
        "--text-search-weekly-spend-limit",
        "200000000",
    )
    search = _text_search_extract(body)
    assert search["BiddingStrategyType"] == "WB_MAXIMUM_CONVERSION_RATE"
    assert search["WbMaximumConversionRate"] == {
        "GoalId": 555,
        "WeeklySpendLimit": 200000000,
    }


def test_campaigns_add_text_search_wb_maximum_conversion_rate_requires_goal_id():
    """StrategyMaximumConversionRateAdd.GoalId is WSDL minOccurs=1."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--text-search-weekly-spend-limit",
        "100000000",
    )
    assert "--goal-id" in result.output
    assert "WbMaximumConversionRate" in result.output


def test_campaigns_add_text_search_wb_maximum_clicks_requires_weekly_spend_limit():
    """Yandex docs: WeeklySpendLimit is required for WB_MAXIMUM_CLICKS."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
    )
    assert "--text-search-weekly-spend-limit" in result.output


def test_campaigns_add_text_search_wb_max_conv_rate_requires_weekly_spend_limit():
    """Yandex docs: WeeklySpendLimit is required for WB_MAXIMUM_CONVERSION_RATE."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--goal-id",
        "1",
    )
    assert "--text-search-weekly-spend-limit" in result.output


def test_campaigns_add_text_search_wb_max_clicks_with_custom_period_payload():
    """CustomPeriodBudget satisfies the WeeklySpendLimit requirement
    for WB_MAXIMUM_CLICKS on add, per Yandex docs (alternate budget
    slice)."""
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--text-search-custom-period-spend-limit",
        "300000000",
        "--text-search-custom-period-start-date",
        "2026-07-01",
        "--text-search-custom-period-end-date",
        "2026-07-31",
        "--text-search-custom-period-auto-continue",
        "NO",
    )
    search = _text_search_extract(body)
    assert search["WbMaximumClicks"] == {
        "CustomPeriodBudget": {
            "SpendLimit": 300000000,
            "StartDate": "2026-07-01",
            "EndDate": "2026-07-31",
            "AutoContinue": "NO",
        }
    }


def test_campaigns_add_text_search_wb_max_conv_rate_custom_period_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--goal-id",
        "42",
        "--text-search-custom-period-spend-limit",
        "200000000",
        "--text-search-custom-period-start-date",
        "2026-09-01",
        "--text-search-custom-period-end-date",
        "2026-09-30",
        "--text-search-custom-period-auto-continue",
        "YES",
    )
    search = _text_search_extract(body)
    assert search["WbMaximumConversionRate"] == {
        "GoalId": 42,
        "CustomPeriodBudget": {
            "SpendLimit": 200000000,
            "StartDate": "2026-09-01",
            "EndDate": "2026-09-30",
            "AutoContinue": "YES",
        },
    }


def test_campaigns_add_text_search_average_cpc_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPC",
        "--text-search-average-cpc",
        "12000000",
        "--text-search-weekly-spend-limit",
        "1000000000",
    )
    search = _text_search_extract(body)
    assert search["BiddingStrategyType"] == "AVERAGE_CPC"
    assert search["AverageCpc"] == {
        "AverageCpc": 12000000,
        "WeeklySpendLimit": 1000000000,
    }


def test_campaigns_add_text_search_average_cpc_requires_average_cpc():
    """StrategyAverageCpcAdd.AverageCpc is WSDL minOccurs=1."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPC",
    )
    assert "--text-search-average-cpc" in result.output


def test_campaigns_add_text_search_pay_for_conversion_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "PAY_FOR_CONVERSION",
        "--text-search-pay-cpa",
        "150000000",
        "--goal-id",
        "777",
    )
    search = _text_search_extract(body)
    assert search["BiddingStrategyType"] == "PAY_FOR_CONVERSION"
    assert search["PayForConversion"] == {"Cpa": 150000000, "GoalId": 777}


def test_campaigns_add_text_search_pay_for_conversion_requires_cpa_and_goal_id():
    """StrategyPayForConversionAdd: Cpa + GoalId both minOccurs=1."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "PAY_FOR_CONVERSION",
    )
    out = result.output
    assert "--text-search-pay-cpa" in out and "--goal-id" in out


def test_campaigns_add_text_search_weekly_click_package_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "WEEKLY_CLICK_PACKAGE",
        "--text-search-clicks-per-week",
        "1000",
        "--text-search-average-cpc",
        "5000000",
    )
    search = _text_search_extract(body)
    assert search["BiddingStrategyType"] == "WEEKLY_CLICK_PACKAGE"
    assert search["WeeklyClickPackage"] == {
        "ClicksPerWeek": 1000,
        "AverageCpc": 5000000,
    }


def test_campaigns_add_text_search_weekly_click_package_requires_clicks_per_week():
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "WEEKLY_CLICK_PACKAGE",
    )
    assert "--text-search-clicks-per-week" in result.output


def test_campaigns_add_text_search_weekly_click_package_rejects_cpc_with_bid_ceiling():
    """WEEKLY_CLICK_PACKAGE cannot combine AverageCpc with BidCeiling."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "WEEKLY_CLICK_PACKAGE",
        "--text-search-clicks-per-week",
        "100",
        "--text-search-average-cpc",
        "10000000",
        "--bid-ceiling",
        "500000",
    )
    assert "WEEKLY_CLICK_PACKAGE" in result.output


def test_campaigns_add_text_search_average_roi_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_ROI",
        "--text-search-reserve-return",
        "30",
        "--text-search-roi-coef",
        "1000000",
        "--goal-id",
        "42",
        "--text-search-weekly-spend-limit",
        "500000000",
        "--text-search-profitability",
        "20000000",
    )
    search = _text_search_extract(body)
    assert search["BiddingStrategyType"] == "AVERAGE_ROI"
    # RoiCoef and Profitability are percent × 1,000,000 per Yandex docs.
    assert search["AverageRoi"] == {
        "ReserveReturn": 30,
        "RoiCoef": 1000000,
        "GoalId": 42,
        "Profitability": 20000000,
        "WeeklySpendLimit": 500000000,
    }


def test_campaigns_add_text_search_average_roi_rejects_non_decimal_reserve_return():
    """Yandex docs: ReserveReturn must be a multiple of 10."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_ROI",
        "--text-search-reserve-return",
        "37",
        "--text-search-roi-coef",
        "100000000",
        "--goal-id",
        "1",
    )
    assert "--text-search-reserve-return" in result.output
    assert "multiple of 10" in result.output


def test_campaigns_add_text_search_average_roi_accepts_zero_reserve_return():
    """ReserveReturn=0 is a documented valid value."""
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_ROI",
        "--text-search-reserve-return",
        "0",
        "--text-search-roi-coef",
        "1000000",
        "--goal-id",
        "1",
    )
    search = _text_search_extract(body)
    assert search["AverageRoi"]["ReserveReturn"] == 0
    assert search["AverageRoi"]["RoiCoef"] == 1000000


def test_campaigns_add_text_search_average_roi_requires_reserve_return_and_roi():
    """StrategyAverageRoiAdd: ReserveReturn + RoiCoef + GoalId minOccurs=1."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_ROI",
    )
    out = result.output
    assert "--text-search-reserve-return" in out
    assert "--text-search-roi-coef" in out
    assert "--goal-id" in out


def test_campaigns_add_text_search_average_crr_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CRR",
        "--crr",
        "12",
        "--goal-id",
        "100",
        "--text-search-weekly-spend-limit",
        "400000000",
    )
    search = _text_search_extract(body)
    assert search["BiddingStrategyType"] == "AVERAGE_CRR"
    assert search["AverageCrr"] == {
        "Crr": 12,
        "GoalId": 100,
        "WeeklySpendLimit": 400000000,
    }


def test_campaigns_add_text_search_average_crr_requires_crr_and_goal_id():
    """StrategyAverageCrrAdd: Crr + GoalId minOccurs=1."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CRR",
    )
    out = result.output
    assert "--crr" in out and "--goal-id" in out


def test_campaigns_add_text_search_max_profit_payload():
    """MAX_PROFIT requires PriorityGoals per Yandex docs even though
    StrategyMaxProfitAdd has no minOccurs=1 WSDL fields."""
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "MAX_PROFIT",
        "--priority-goals",
        "1:500000000",
        "--text-search-weekly-spend-limit",
        "1000000000",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text["PriorityGoals"] == {"Items": [{"GoalId": 1, "Value": 500000000}]}
    search = text["BiddingStrategy"]["Search"]
    assert search["BiddingStrategyType"] == "MAX_PROFIT"
    assert search["MaxProfit"] == {"WeeklySpendLimit": 1000000000}


def test_campaigns_add_text_search_max_profit_rejects_without_priority_goals():
    """Yandex docs: MAX_PROFIT must be combined with PriorityGoals."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "MAX_PROFIT",
    )
    assert "--priority-goals" in result.output
    assert "MaxProfit" in result.output


def test_campaigns_add_text_search_average_cpa_multiple_goals_with_exploration():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--priority-goals",
        "111:60000000,222:40000000",
        "--bid-ceiling",
        "200000000",
        "--text-search-exploration-min-budget",
        "50000000",
        "--text-search-exploration-is-custom",
        "YES",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text["PriorityGoals"] == {
        "Items": [
            {"GoalId": 111, "Value": 60000000},
            {"GoalId": 222, "Value": 40000000},
        ]
    }
    search = text["BiddingStrategy"]["Search"]
    assert search["BiddingStrategyType"] == "AVERAGE_CPA_MULTIPLE_GOALS"
    assert search["AverageCpaMultipleGoals"] == {
        "BidCeiling": 200000000,
        "ExplorationBudget": {
            "MinimumExplorationBudget": 50000000,
            "IsMinimumExplorationBudgetCustom": "YES",
        },
    }


def test_campaigns_add_text_search_average_cpa_multi_goals_requires_two_items():
    """Per docs *_MULTIPLE_GOALS strategies require ≥2 priority goals."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--priority-goals",
        "111:100000000",
    )
    assert "at least 2" in result.output


def test_campaigns_add_text_search_pay_conv_multi_goals_requires_two_items():
    """Per docs PAY_FOR_CONVERSION_MULTIPLE_GOALS requires ≥2 priority goals."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "PAY_FOR_CONVERSION_MULTIPLE_GOALS",
        "--priority-goals",
        "111:100000000",
    )
    assert "at least 2" in result.output


def test_campaigns_add_text_search_pay_for_conversion_multiple_goals_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "PAY_FOR_CONVERSION_MULTIPLE_GOALS",
        "--priority-goals",
        "1:50000000,2:50000000",
        "--text-search-weekly-spend-limit",
        "700000000",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text["PriorityGoals"] == {
        "Items": [
            {"GoalId": 1, "Value": 50000000},
            {"GoalId": 2, "Value": 50000000},
        ]
    }
    search = text["BiddingStrategy"]["Search"]
    assert search["PayForConversionMultipleGoals"] == {
        "WeeklySpendLimit": 700000000,
    }


def test_campaigns_add_text_search_custom_period_budget_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPC",
        "--text-search-average-cpc",
        "10000000",
        "--text-search-custom-period-spend-limit",
        "500000000",
        "--text-search-custom-period-start-date",
        "2026-07-01",
        "--text-search-custom-period-end-date",
        "2026-07-31",
        "--text-search-custom-period-auto-continue",
        "NO",
    )
    search = _text_search_extract(body)
    assert search["AverageCpc"] == {
        "AverageCpc": 10000000,
        "CustomPeriodBudget": {
            "SpendLimit": 500000000,
            "StartDate": "2026-07-01",
            "EndDate": "2026-07-31",
            "AutoContinue": "NO",
        },
    }


def test_campaigns_add_text_search_custom_period_partial_rejected():
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPC",
        "--text-search-average-cpc",
        "10000000",
        "--text-search-custom-period-spend-limit",
        "500000000",
        "--text-search-custom-period-start-date",
        "2026-07-01",
    )
    assert "CustomPeriodBudget" in result.output


def test_campaigns_add_text_search_custom_period_weekly_conflict_rejected():
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPC",
        "--text-search-average-cpc",
        "10000000",
        "--text-search-weekly-spend-limit",
        "100000000",
        "--text-search-custom-period-spend-limit",
        "500000000",
        "--text-search-custom-period-start-date",
        "2026-07-01",
        "--text-search-custom-period-end-date",
        "2026-07-31",
        "--text-search-custom-period-auto-continue",
        "NO",
    )
    assert "weekly-spend-limit" in result.output


def test_campaigns_add_text_search_exploration_partial_rejected():
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPA",
        "--average-cpa",
        "100000000",
        "--goal-id",
        "1",
        "--text-search-exploration-min-budget",
        "50000000",
    )
    assert "ExplorationBudget" in result.output


def test_campaigns_add_text_search_exploration_is_custom_no_rejected():
    """Yandex docs: IsMinimumExplorationBudgetCustom=NO makes the API error."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPA",
        "--average-cpa",
        "100000000",
        "--goal-id",
        "1",
        "--text-search-exploration-min-budget",
        "50000000",
        "--text-search-exploration-is-custom",
        "NO",
    )
    assert "IsMinimumExplorationBudgetCustom" in result.output
    assert "YES" in result.output


def test_campaigns_add_text_search_silent_data_loss_invariant():
    """text-search-* flag attached to an unsupported subtype must raise."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPC",
        "--text-search-average-cpc",
        "10000000",
        "--text-search-reserve-return",
        "30",
    )
    assert "--text-search-reserve-return" in result.output
    assert "AverageCpc" in result.output


def test_campaigns_add_text_search_budget_type_add_only_rejected():
    """--text-search-budget-type is update-only per WSDL Strategy*Add."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPC",
        "--text-search-average-cpc",
        "10000000",
        "--text-search-budget-type",
        "WEEKLY_BUDGET",
    )
    assert "--text-search-budget-type" in result.output


def test_campaigns_update_text_search_average_cpa_payload():
    body = _text_search_update(
        "--search-strategy",
        "AVERAGE_CPA",
        "--average-cpa",
        "100000000",
        "--goal-id",
        "9",
        "--bid-ceiling",
        "500000000",
    )
    search = _text_search_extract(body)
    assert search["BiddingStrategyType"] == "AVERAGE_CPA"
    assert search["AverageCpa"] == {
        "AverageCpa": 100000000,
        "GoalId": 9,
        "BidCeiling": 500000000,
    }


def test_campaigns_update_text_search_pay_for_conversion_payload():
    body = _text_search_update(
        "--search-strategy",
        "PAY_FOR_CONVERSION",
        "--text-search-pay-cpa",
        "200000000",
        "--goal-id",
        "11",
        "--text-search-weekly-spend-limit",
        "1500000000",
    )
    search = _text_search_extract(body)
    assert search["BiddingStrategyType"] == "PAY_FOR_CONVERSION"
    assert search["PayForConversion"] == {
        "Cpa": 200000000,
        "GoalId": 11,
        "WeeklySpendLimit": 1500000000,
    }


def test_campaigns_update_text_search_budget_type_switch_payload():
    """Update-only BudgetType switch from WEEKLY_BUDGET → CUSTOM_PERIOD_BUDGET."""
    body = _text_search_update(
        "--search-strategy",
        "AVERAGE_CPC",
        "--text-search-average-cpc",
        "8000000",
        "--text-search-custom-period-spend-limit",
        "1200000000",
        "--text-search-custom-period-start-date",
        "2026-08-01",
        "--text-search-custom-period-end-date",
        "2026-08-31",
        "--text-search-custom-period-auto-continue",
        "YES",
        "--text-search-budget-type",
        "CUSTOM_PERIOD_BUDGET",
    )
    search = _text_search_extract(body)
    assert search["BiddingStrategyType"] == "AVERAGE_CPC"
    assert search["AverageCpc"] == {
        "AverageCpc": 8000000,
        "WeeklySpendLimit": None,
        "CustomPeriodBudget": {
            "SpendLimit": 1200000000,
            "StartDate": "2026-08-01",
            "EndDate": "2026-08-31",
            "AutoContinue": "YES",
        },
        "BudgetType": "CUSTOM_PERIOD_BUDGET",
    }


def test_campaigns_update_text_search_max_profit_with_weekly_spend_payload():
    """Switching to MAX_PROFIT on update requires --priority-goals per docs;
    additional optional fields land in the subtype block."""
    body = _text_search_update(
        "--search-strategy",
        "MAX_PROFIT",
        "--priority-goals",
        "9:1000000000",
        "--text-search-weekly-spend-limit",
        "999000000",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text["PriorityGoals"] == {
        "Items": [{"GoalId": 9, "Value": 1000000000, "Operation": "SET"}]
    }
    search = text["BiddingStrategy"]["Search"]
    assert search["MaxProfit"] == {"WeeklySpendLimit": 999000000}


def test_campaigns_update_text_search_max_profit_requires_priority_goals():
    """Switching --search-strategy MAX_PROFIT on update without
    --priority-goals is rejected per the Yandex docs."""
    result = CliRunner().invoke(
        cli,
        [
            "campaigns",
            "update",
            "--id",
            "123",
            "--type",
            "TEXT_CAMPAIGN",
            "--search-strategy",
            "MAX_PROFIT",
            "--text-search-weekly-spend-limit",
            "999000000",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "--priority-goals" in result.output
    assert "MaxProfit" in result.output


def test_campaigns_update_text_search_average_roi_payload():
    """Switching to AVERAGE_ROI on update requires all
    minOccurs=1 fields per Yandex docs (ReserveReturn + RoiCoef +
    GoalId); additional optional fields land in the subtype block.
    RoiCoef and Profitability are percent × 1,000,000 on the wire."""
    body = _text_search_update(
        "--search-strategy",
        "AVERAGE_ROI",
        "--text-search-reserve-return",
        "20",
        "--text-search-roi-coef",
        "1000000",
        "--goal-id",
        "42",
        "--text-search-profitability",
        "25000000",
    )
    search = _text_search_extract(body)
    assert search["AverageRoi"] == {
        "ReserveReturn": 20,
        "RoiCoef": 1000000,
        "GoalId": 42,
        "Profitability": 25000000,
    }


def test_campaigns_update_text_search_average_roi_rejects_partial():
    """Switching --search-strategy AVERAGE_ROI without RoiCoef/GoalId/
    ReserveReturn is a documented invalid update — CLI must reject."""
    result = CliRunner().invoke(
        cli,
        [
            "campaigns",
            "update",
            "--id",
            "123",
            "--type",
            "TEXT_CAMPAIGN",
            "--search-strategy",
            "AVERAGE_ROI",
            "--text-search-profitability",
            "25000000",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "--text-search-reserve-return" in result.output
    assert "--text-search-roi-coef" in result.output
    assert "--goal-id" in result.output


def test_campaigns_update_text_search_priority_goals_independent_of_strategy():
    """PriorityGoalsUpdateSetting on update is independent of BiddingStrategy."""
    body = _text_search_update(
        "--priority-goals",
        "1:80000000,2:20000000",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    # On update PriorityGoals uses the UpdateSetting shape (with
    # Operation=SET, see _priority_goals_update_items).
    assert text["PriorityGoals"] == {
        "Items": [
            {"GoalId": 1, "Value": 80000000, "Operation": "SET"},
            {"GoalId": 2, "Value": 20000000, "Operation": "SET"},
        ]
    }
    # And no BiddingStrategy is emitted, matching legacy behavior.
    assert "BiddingStrategy" not in text


def test_campaigns_update_text_search_detail_without_strategy_rejected():
    result = CliRunner().invoke(
        cli,
        [
            "campaigns",
            "update",
            "--id",
            "123",
            "--type",
            "TEXT_CAMPAIGN",
            "--text-search-weekly-spend-limit",
            "100000000",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "--search-strategy" in result.output


def test_campaigns_update_text_search_average_cpc_payload():
    body = _text_search_update(
        "--search-strategy",
        "AVERAGE_CPC",
        "--text-search-average-cpc",
        "9000000",
        "--text-search-weekly-spend-limit",
        "300000000",
    )
    search = _text_search_extract(body)
    assert search["AverageCpc"] == {
        "AverageCpc": 9000000,
        "WeeklySpendLimit": 300000000,
    }


def test_campaigns_update_text_search_average_crr_payload():
    body = _text_search_update(
        "--search-strategy",
        "AVERAGE_CRR",
        "--crr",
        "15",
        "--goal-id",
        "5",
    )
    search = _text_search_extract(body)
    assert search["AverageCrr"] == {"Crr": 15, "GoalId": 5}


def test_campaigns_update_text_search_average_crr_rejects_partial():
    """Switching --search-strategy AVERAGE_CRR without Crr/GoalId is
    a documented invalid update — CLI must reject."""
    result = CliRunner().invoke(
        cli,
        [
            "campaigns",
            "update",
            "--id",
            "123",
            "--type",
            "TEXT_CAMPAIGN",
            "--search-strategy",
            "AVERAGE_CRR",
            "--text-search-weekly-spend-limit",
            "100000000",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "--crr" in result.output
    assert "--goal-id" in result.output


def test_campaigns_update_text_search_pay_for_conversion_crr_payload():
    body = _text_search_update(
        "--search-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--crr",
        "10",
        "--goal-id",
        "3",
    )
    search = _text_search_extract(body)
    assert search["PayForConversionCrr"] == {"Crr": 10, "GoalId": 3}


def test_campaigns_update_text_search_pay_conv_crr_rejects_partial():
    """Switching --search-strategy PAY_FOR_CONVERSION_CRR without
    Crr/GoalId is a documented invalid update — CLI must reject."""
    result = CliRunner().invoke(
        cli,
        [
            "campaigns",
            "update",
            "--id",
            "123",
            "--type",
            "TEXT_CAMPAIGN",
            "--search-strategy",
            "PAY_FOR_CONVERSION_CRR",
            "--text-search-weekly-spend-limit",
            "100000000",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "--crr" in result.output
    assert "--goal-id" in result.output


def test_campaigns_update_text_search_weekly_click_package_payload():
    body = _text_search_update(
        "--search-strategy",
        "WEEKLY_CLICK_PACKAGE",
        "--text-search-clicks-per-week",
        "1500",
        "--text-search-average-cpc",
        "4000000",
    )
    search = _text_search_extract(body)
    assert search["WeeklyClickPackage"] == {
        "ClicksPerWeek": 1500,
        "AverageCpc": 4000000,
    }


def test_campaigns_update_text_search_average_cpa_multiple_goals_payload():
    body = _text_search_update(
        "--search-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--priority-goals",
        "100:60000000,200:40000000",
        "--bid-ceiling",
        "5000000",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    # On update PriorityGoals uses the UpdateSetting shape; the
    # BiddingStrategy carries the subtype container.
    assert text["PriorityGoals"] == {
        "Items": [
            {"GoalId": 100, "Value": 60000000, "Operation": "SET"},
            {"GoalId": 200, "Value": 40000000, "Operation": "SET"},
        ]
    }
    search = text["BiddingStrategy"]["Search"]
    assert search["AverageCpaMultipleGoals"] == {"BidCeiling": 5000000}


def test_campaigns_update_text_search_pay_for_conversion_multiple_goals_payload():
    body = _text_search_update(
        "--search-strategy",
        "PAY_FOR_CONVERSION_MULTIPLE_GOALS",
        "--priority-goals",
        "1:60000000,2:40000000",
        "--text-search-weekly-spend-limit",
        "800000000",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text["PriorityGoals"] == {
        "Items": [
            {"GoalId": 1, "Value": 60000000, "Operation": "SET"},
            {"GoalId": 2, "Value": 40000000, "Operation": "SET"},
        ]
    }
    search = text["BiddingStrategy"]["Search"]
    assert search["PayForConversionMultipleGoals"] == {
        "WeeklySpendLimit": 800000000,
    }


def test_campaigns_update_text_search_max_profit_with_priority_goals_payload():
    body = _text_search_update(
        "--search-strategy",
        "MAX_PROFIT",
        "--priority-goals",
        "9:1000000000",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text["PriorityGoals"] == {
        "Items": [{"GoalId": 9, "Value": 1000000000, "Operation": "SET"}]
    }
    search = text["BiddingStrategy"]["Search"]
    assert search["MaxProfit"] == {}


def test_campaigns_update_text_search_wb_maximum_clicks_partial_payload():
    """Update WSDL ``StrategyMaximumClicks`` declares every field as
    minOccurs=0, so patching only ``BidCeiling`` on a WB_MAXIMUM_CLICKS
    campaign must succeed."""
    body = _text_search_update(
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--bid-ceiling",
        "750000",
    )
    search = _text_search_extract(body)
    assert search["BiddingStrategyType"] == "WB_MAXIMUM_CLICKS"
    assert search["WbMaximumClicks"] == {"BidCeiling": 750000}


def test_campaigns_update_text_search_wb_max_conv_rate_partial_payload():
    """Update path treats every ``StrategyMaximumConversionRate`` field
    as optional EXCEPT the docs-required ``GoalId`` on strategy switch."""
    body = _text_search_update(
        "--search-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--goal-id",
        "42",
        "--bid-ceiling",
        "400000",
    )
    search = _text_search_extract(body)
    assert search["WbMaximumConversionRate"] == {
        "GoalId": 42,
        "BidCeiling": 400000,
    }


def test_campaigns_update_text_search_wb_maximum_clicks_rejects_budget_type():
    """Yandex update docs: WbMaximumClicks does not declare BudgetType."""
    result = CliRunner().invoke(
        cli,
        [
            "campaigns",
            "update",
            "--id",
            "123",
            "--type",
            "TEXT_CAMPAIGN",
            "--search-strategy",
            "WB_MAXIMUM_CLICKS",
            "--text-search-weekly-spend-limit",
            "400000000",
            "--text-search-budget-type",
            "WEEKLY_BUDGET",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "--text-search-budget-type" in result.output
    assert "WbMaximumClicks" in result.output


def test_campaigns_update_text_search_wb_max_conv_rate_rejects_budget_type():
    """Yandex update docs: WbMaximumConversionRate does not declare BudgetType."""
    result = CliRunner().invoke(
        cli,
        [
            "campaigns",
            "update",
            "--id",
            "123",
            "--type",
            "TEXT_CAMPAIGN",
            "--search-strategy",
            "WB_MAXIMUM_CONVERSION_RATE",
            "--goal-id",
            "8",
            "--text-search-weekly-spend-limit",
            "250000000",
            "--text-search-budget-type",
            "WEEKLY_BUDGET",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "--text-search-budget-type" in result.output


def test_campaigns_add_text_network_strategy_without_detail_flags_rejected():
    """``--network-strategy AVERAGE_CPA`` without typed CPA flags must be
    rejected after #364: ``StrategyAverageCpaAdd.AverageCpa`` /
    ``StrategyAverageCpaAdd.GoalId`` are both WSDL minOccurs=1 so the CLI
    fails fast instead of sending a half-configured payload."""
    result = _rejected(
        *_cpa_base_args(),
        "--network-strategy",
        "AVERAGE_CPA",
    )
    assert "AverageCpa requires" in result.output


def test_campaigns_add_text_network_cpa_with_detail_flags_accepted_payload():
    """#364: ``--network-strategy AVERAGE_CPA --average-cpa ... --goal-id ...``
    is now accepted and emits a full ``StrategyAverageCpaAdd`` block on the
    Network side (shared --average-cpa/--goal-id flags are routed to the
    Network branch when the network strategy is CPA-shaped)."""
    body = _dry_run(
        *_cpa_base_args(),
        "--network-strategy",
        "AVERAGE_CPA",
        "--average-cpa",
        "100000000",
        "--goal-id",
        "1",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPA",
        "AverageCpa": {
            "AverageCpa": 100000000,
            "GoalId": 1,
        },
    }


def _text_network_base_args():
    return [
        "campaigns",
        "add",
        "--name",
        "Net Campaign",
        "--start-date",
        "2026-06-01",
        "--type",
        "TEXT_CAMPAIGN",
    ]


def test_campaigns_add_text_network_serving_off_default_payload():
    """#364: implicit default (no Network flags) emits SERVING_OFF only."""
    body = _dry_run(*_text_network_base_args())
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {"BiddingStrategyType": "SERVING_OFF"}


def test_campaigns_add_text_network_maximum_coverage_payload():
    """#364: MAXIMUM_COVERAGE is settable but carries no nested block."""
    body = _dry_run(
        *_text_network_base_args(),
        "--network-strategy",
        "MAXIMUM_COVERAGE",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {"BiddingStrategyType": "MAXIMUM_COVERAGE"}


def test_campaigns_add_text_network_network_default_payload():
    """#364: NETWORK_DEFAULT emits NetworkDefault.LimitPercent."""
    body = _dry_run(
        *_text_network_base_args(),
        "--network-strategy",
        "NETWORK_DEFAULT",
        "--text-network-limit-percent",
        "40",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "NETWORK_DEFAULT",
        "NetworkDefault": {"LimitPercent": 40},
    }


def test_campaigns_add_text_network_wb_maximum_clicks_bare_payload():
    """#364: WSDL ``StrategyMaximumClicksAdd`` (campaigns.xml 1339-1347)
    has all fields ``minOccurs=0``, so a bare ``WB_MAXIMUM_CLICKS`` add
    with only the strategy name is valid."""
    body = _dry_run(
        *_text_network_base_args(),
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {"BiddingStrategyType": "WB_MAXIMUM_CLICKS"}


def test_campaigns_add_text_network_wb_maximum_conversion_rate_bare_payload():
    """#364: WSDL ``StrategyMaximumConversionRateAdd`` (campaigns.xml
    1348-1357) makes only ``GoalId`` required (minOccurs=1)."""
    body = _dry_run(
        *_text_network_base_args(),
        "--network-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--goal-id",
        "42",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WB_MAXIMUM_CONVERSION_RATE",
        "WbMaximumConversionRate": {"GoalId": 42},
    }


def test_campaigns_add_text_network_wb_maximum_clicks_weekly_payload():
    body = _dry_run(
        *_text_network_base_args(),
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--text-network-weekly-spend-limit",
        "1000000000",
        "--bid-ceiling",
        "100000000",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
        "WbMaximumClicks": {
            "WeeklySpendLimit": 1000000000,
            "BidCeiling": 100000000,
        },
    }


def test_campaigns_add_text_network_wb_maximum_clicks_custom_period_payload():
    body = _dry_run(
        *_text_network_base_args(),
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--text-network-custom-period-spend-limit",
        "5000000000",
        "--text-network-custom-period-start-date",
        "2026-06-01",
        "--text-network-custom-period-end-date",
        "2026-06-30",
        "--text-network-custom-period-auto-continue",
        "NO",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
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


def test_campaigns_add_text_network_wb_maximum_conversion_rate_payload():
    body = _dry_run(
        *_text_network_base_args(),
        "--network-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--goal-id",
        "77",
        "--text-network-weekly-spend-limit",
        "2000000000",
        "--bid-ceiling",
        "50000000",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
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


def test_campaigns_add_text_network_average_cpc_payload():
    body = _dry_run(
        *_text_network_base_args(),
        "--network-strategy",
        "AVERAGE_CPC",
        "--text-network-average-cpc",
        "7000000",
        "--text-network-weekly-spend-limit",
        "500000000",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPC",
        "AverageCpc": {
            "AverageCpc": 7000000,
            "WeeklySpendLimit": 500000000,
        },
    }


def test_campaigns_add_text_network_average_cpa_payload():
    body = _dry_run(
        *_text_network_base_args(),
        "--network-strategy",
        "AVERAGE_CPA",
        "--average-cpa",
        "150000000",
        "--goal-id",
        "12",
        "--bid-ceiling",
        "20000000",
        "--text-network-exploration-min-budget",
        "300000000",
        "--text-network-exploration-is-custom",
        "YES",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
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


def test_campaigns_add_text_network_pay_for_conversion_payload():
    body = _dry_run(
        *_text_network_base_args(),
        "--network-strategy",
        "PAY_FOR_CONVERSION",
        "--text-network-pay-cpa",
        "300000000",
        "--goal-id",
        "55",
        "--text-network-weekly-spend-limit",
        "2500000000",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
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


def test_campaigns_add_text_network_average_roi_payload():
    body = _dry_run(
        *_text_network_base_args(),
        "--network-strategy",
        "AVERAGE_ROI",
        "--text-network-reserve-return",
        "60",
        "--text-network-roi-coef",
        "150000000",
        "--goal-id",
        "88",
        "--text-network-profitability",
        "25000000",
        "--bid-ceiling",
        "12000000",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_ROI",
        "AverageRoi": {
            "ReserveReturn": 60,
            "RoiCoef": 150000000,
            "GoalId": 88,
            "Profitability": 25000000,
            "BidCeiling": 12000000,
        },
    }


def test_campaigns_add_text_network_average_crr_payload():
    body = _dry_run(
        *_text_network_base_args(),
        "--network-strategy",
        "AVERAGE_CRR",
        "--crr",
        "30",
        "--goal-id",
        "61",
        "--text-network-weekly-spend-limit",
        "800000000",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
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


def test_campaigns_add_text_network_pay_for_conversion_crr_payload():
    body = _dry_run(
        *_text_network_base_args(),
        "--network-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--crr",
        "25",
        "--goal-id",
        "44",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_CRR",
        "PayForConversionCrr": {
            "Crr": 25,
            "GoalId": 44,
        },
    }


def test_campaigns_add_text_network_weekly_click_package_payload():
    body = _dry_run(
        *_text_network_base_args(),
        "--network-strategy",
        "WEEKLY_CLICK_PACKAGE",
        "--text-network-clicks-per-week",
        "200",
        "--text-network-average-cpc",
        "3000000",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WEEKLY_CLICK_PACKAGE",
        "WeeklyClickPackage": {
            "ClicksPerWeek": 200,
            "AverageCpc": 3000000,
        },
    }


def test_campaigns_add_text_network_max_profit_payload():
    body = _dry_run(
        *_text_network_base_args(),
        "--network-strategy",
        "MAX_PROFIT",
        "--priority-goals",
        "1:60000000,2:40000000",
    )
    body_camp = body["params"]["Campaigns"][0]["TextCampaign"]
    assert body_camp["BiddingStrategy"]["Network"] == {
        "BiddingStrategyType": "MAX_PROFIT",
        "MaxProfit": {},
    }
    assert body_camp["PriorityGoals"] == {
        "Items": [
            {"GoalId": 1, "Value": 60000000},
            {"GoalId": 2, "Value": 40000000},
        ]
    }


def test_campaigns_add_text_network_average_cpa_multiple_goals_payload():
    body = _dry_run(
        *_text_network_base_args(),
        "--network-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--priority-goals",
        "10:70000000,20:30000000",
        "--bid-ceiling",
        "200000000",
    )
    body_camp = body["params"]["Campaigns"][0]["TextCampaign"]
    assert body_camp["BiddingStrategy"]["Network"] == {
        "BiddingStrategyType": "AVERAGE_CPA_MULTIPLE_GOALS",
        "AverageCpaMultipleGoals": {"BidCeiling": 200000000},
    }
    assert body_camp["PriorityGoals"] == {
        "Items": [
            {"GoalId": 10, "Value": 70000000},
            {"GoalId": 20, "Value": 30000000},
        ]
    }


def test_campaigns_add_text_network_pay_for_conversion_multiple_goals_payload():
    body = _dry_run(
        *_text_network_base_args(),
        "--network-strategy",
        "PAY_FOR_CONVERSION_MULTIPLE_GOALS",
        "--priority-goals",
        "11:55000000,22:45000000",
        "--text-network-weekly-spend-limit",
        "400000000",
    )
    body_camp = body["params"]["Campaigns"][0]["TextCampaign"]
    assert body_camp["BiddingStrategy"]["Network"] == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_MULTIPLE_GOALS",
        "PayForConversionMultipleGoals": {"WeeklySpendLimit": 400000000},
    }
    assert body_camp["PriorityGoals"] == {
        "Items": [
            {"GoalId": 11, "Value": 55000000},
            {"GoalId": 22, "Value": 45000000},
        ]
    }


def test_campaigns_add_text_network_rejects_detail_without_strategy():
    result = _rejected(
        *_text_network_base_args(),
        "--text-network-average-cpc",
        "5000000",
    )
    assert "TextCampaign network strategy detail flags require" in result.output


def test_campaigns_add_text_network_rejects_average_cpc_for_average_cpa():
    """#364: WSDL field-support gate — AverageCpa subtype has no AverageCpc."""
    result = _rejected(
        *_text_network_base_args(),
        "--network-strategy",
        "AVERAGE_CPA",
        "--average-cpa",
        "100000000",
        "--goal-id",
        "1",
        "--text-network-average-cpc",
        "5000000",
    )
    assert "--text-network-average-cpc is not valid" in result.output


def test_campaigns_add_text_network_rejects_average_roi_required_fields():
    """#364: WSDL minOccurs=1 gate — AverageRoi needs ReserveReturn+RoiCoef+GoalId."""
    result = _rejected(
        *_text_network_base_args(),
        "--network-strategy",
        "AVERAGE_ROI",
    )
    assert "AverageRoi requires" in result.output
    assert "--text-network-reserve-return" in result.output
    assert "--text-network-roi-coef" in result.output
    assert "--goal-id" in result.output


def test_campaigns_add_text_network_rejects_maximum_coverage_with_details():
    result = _rejected(
        *_text_network_base_args(),
        "--network-strategy",
        "MAXIMUM_COVERAGE",
        "--text-network-average-cpc",
        "5000000",
    )
    assert "MAXIMUM_COVERAGE does not accept" in result.output


def test_campaigns_add_text_network_rejects_limit_percent_off_step():
    result = _rejected(
        *_text_network_base_args(),
        "--network-strategy",
        "NETWORK_DEFAULT",
        "--text-network-limit-percent",
        "15",
    )
    assert "--text-network-limit-percent must be a multiple of 10" in result.output


def test_campaigns_add_text_network_rejects_partial_custom_period():
    result = _rejected(
        *_text_network_base_args(),
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--text-network-custom-period-spend-limit",
        "1000000000",
    )
    assert "TextCampaign Network CustomPeriodBudget requires all four" in result.output


def test_campaigns_add_text_network_rejects_partial_exploration_budget():
    result = _rejected(
        *_text_network_base_args(),
        "--network-strategy",
        "AVERAGE_CPA",
        "--average-cpa",
        "100000000",
        "--goal-id",
        "1",
        "--text-network-exploration-min-budget",
        "100000000",
    )
    assert "TextCampaign Network ExplorationBudget requires both" in result.output


def test_campaigns_add_text_network_rejects_weekly_combined_with_custom_period():
    result = _rejected(
        *_text_network_base_args(),
        "--network-strategy",
        "AVERAGE_CPC",
        "--text-network-average-cpc",
        "5000000",
        "--text-network-weekly-spend-limit",
        "100000000",
        "--text-network-custom-period-spend-limit",
        "200000000",
        "--text-network-custom-period-start-date",
        "2026-06-01",
        "--text-network-custom-period-end-date",
        "2026-06-30",
        "--text-network-custom-period-auto-continue",
        "NO",
    )
    assert "--text-network-weekly-spend-limit cannot be combined with" in result.output


def test_campaigns_add_text_network_rejects_budget_type_on_add():
    """#364: --text-network-budget-type is update-only (Strategy*Add types
    don't declare BudgetType; only get-side Strategy* used by
    TextCampaignUpdateItem)."""
    result = CliRunner().invoke(
        cli,
        [
            *_text_network_base_args(),
            "--network-strategy",
            "AVERAGE_CPC",
            "--text-network-average-cpc",
            "5000000",
            "--text-network-weekly-spend-limit",
            "100000000",
            "--text-network-budget-type",
            "WEEKLY_BUDGET",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "--text-network-budget-type" not in result.output or (
        "no such option" in result.output.lower()
    )


def test_campaigns_add_text_network_rejects_text_search_flag_for_dynamic_text():
    """#364: --text-network-* must reject for other --type values."""
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Wrong Type",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--text-network-average-cpc",
        "5000000",
    )
    assert "--text-network-average-cpc" in result.output


def test_campaigns_add_text_network_rejects_priority_goals_for_average_cpa():
    """#364: --priority-goals only valid for *_MULTIPLE_GOALS / MAX_PROFIT.
    With Search defaulting to HIGHEST_POSITION (which also rejects
    --priority-goals), the Search builder catches the invalid combination
    first; either rejection is acceptable as a guard."""
    result = _rejected(
        *_text_network_base_args(),
        "--network-strategy",
        "AVERAGE_CPA",
        "--average-cpa",
        "100000000",
        "--goal-id",
        "1",
        "--priority-goals",
        "1:60000000,2:40000000",
    )
    assert "--priority-goals" in result.output


def test_campaigns_add_text_network_search_cpa_plus_network_wb_max_clicks_payload():
    """#364: shared --average-cpa / --goal-id route to Search only when
    Network = WB_MAXIMUM_CLICKS (Network's StrategyMaximumClicksAdd has no
    AverageCpa/GoalId per WSDL); Network must still receive its own
    --text-network-weekly-spend-limit."""
    body = _dry_run(
        *_text_network_base_args(),
        "--search-strategy",
        "AVERAGE_CPA",
        "--average-cpa",
        "150000000",
        "--goal-id",
        "9",
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--text-network-weekly-spend-limit",
        "300000000",
        "--bid-ceiling",
        "20000000",
    )
    bs = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"]
    assert bs == {
        "Search": {
            "BiddingStrategyType": "AVERAGE_CPA",
            "AverageCpa": {
                "AverageCpa": 150000000,
                "GoalId": 9,
                "BidCeiling": 20000000,
            },
        },
        "Network": {
            "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
            "WbMaximumClicks": {
                "WeeklySpendLimit": 300000000,
                "BidCeiling": 20000000,
            },
        },
    }


def test_campaigns_add_text_network_search_cpa_plus_network_weekly_click_package_payload():
    """#364: shared --bid-ceiling routes to BOTH sides when both subtypes
    accept it (WeeklyClickPackage carries BidCeiling per WSDL line 1486)."""
    body = _dry_run(
        *_text_network_base_args(),
        "--search-strategy",
        "AVERAGE_CPA",
        "--average-cpa",
        "100000000",
        "--goal-id",
        "1",
        "--bid-ceiling",
        "50000000",
        "--network-strategy",
        "WEEKLY_CLICK_PACKAGE",
        "--text-network-clicks-per-week",
        "100",
    )
    bs = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"]
    assert bs["Search"]["AverageCpa"]["BidCeiling"] == 50000000
    assert bs["Network"]["WeeklyClickPackage"] == {
        "ClicksPerWeek": 100,
        "BidCeiling": 50000000,
    }


def test_campaigns_update_text_network_search_cpa_plus_network_wb_max_clicks_payload():
    """#364: update path applies the same per-side, per-flag routing."""
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "4001",
        "--type",
        "TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA",
        "--average-cpa",
        "100000000",
        "--goal-id",
        "5",
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--text-network-weekly-spend-limit",
        "400000000",
    )
    bs = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"]
    assert bs == {
        "Search": {
            "BiddingStrategyType": "AVERAGE_CPA",
            "AverageCpa": {
                "AverageCpa": 100000000,
                "GoalId": 5,
            },
        },
        "Network": {
            "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
            "WbMaximumClicks": {
                "WeeklySpendLimit": 400000000,
            },
        },
    }


def test_campaigns_add_text_network_rejects_priority_goals_for_pure_cpa_network():
    """#364: when Search is also CPA (so the Search builder accepts it) but
    Network is plain AVERAGE_CPA (single-goal), the Network builder catches
    the *_MULTIPLE_GOALS-only --priority-goals usage."""
    result = _rejected(
        *_text_network_base_args(),
        "--search-strategy",
        "AVERAGE_CPA",
        "--average-cpa",
        "100000000",
        "--goal-id",
        "1",
        "--network-strategy",
        "AVERAGE_CPA",
        "--priority-goals",
        "1:60000000,2:40000000",
    )
    assert "--priority-goals is only valid" in result.output


def test_campaigns_add_text_network_both_sides_multi_goals_payload():
    """#364: WSDL ``TextCampaignAddItem.PriorityGoals`` is a single sibling
    on the parent block, so when both Search AND Network pick a
    multi-goals strategy the same items must satisfy both builders'
    required-field checks. Both sides emit the marker subtype container
    and the parent receives PriorityGoals once."""
    body = _dry_run(
        *_text_network_base_args(),
        "--search-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--network-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--priority-goals",
        "1:60000000,2:40000000",
    )
    body_camp = body["params"]["Campaigns"][0]["TextCampaign"]
    assert body_camp["BiddingStrategy"]["Search"] == {
        "BiddingStrategyType": "AVERAGE_CPA_MULTIPLE_GOALS",
        "AverageCpaMultipleGoals": {},
    }
    assert body_camp["BiddingStrategy"]["Network"] == {
        "BiddingStrategyType": "AVERAGE_CPA_MULTIPLE_GOALS",
        "AverageCpaMultipleGoals": {},
    }
    assert body_camp["PriorityGoals"] == {
        "Items": [
            {"GoalId": 1, "Value": 60000000},
            {"GoalId": 2, "Value": 40000000},
        ]
    }


def test_campaigns_add_text_network_rejects_one_priority_goal_for_multi():
    """#364: AverageCpaMultipleGoals requires at least 2 priority goals."""
    result = _rejected(
        *_text_network_base_args(),
        "--network-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--priority-goals",
        "1:100000000",
    )
    assert "--priority-goals requires at least 2 entries" in result.output


def test_campaigns_add_text_network_weekly_click_package_combined_ceilings_payload():
    """#364: WSDL ``StrategyWeeklyClickPackageAdd`` (campaigns.xml lines
    1482-1487) declares ``AverageCpc`` and ``BidCeiling`` as independent
    sibling fields, so the CLI must accept both flags together for
    WEEKLY_CLICK_PACKAGE."""
    body = _dry_run(
        *_text_network_base_args(),
        "--network-strategy",
        "WEEKLY_CLICK_PACKAGE",
        "--text-network-clicks-per-week",
        "100",
        "--text-network-average-cpc",
        "5000000",
        "--bid-ceiling",
        "1000000",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WEEKLY_CLICK_PACKAGE",
        "WeeklyClickPackage": {
            "ClicksPerWeek": 100,
            "AverageCpc": 5000000,
            "BidCeiling": 1000000,
        },
    }


def test_campaigns_add_text_network_rejects_reserve_return_off_step():
    result = _rejected(
        *_text_network_base_args(),
        "--network-strategy",
        "AVERAGE_ROI",
        "--text-network-reserve-return",
        "55",
        "--text-network-roi-coef",
        "100000000",
        "--goal-id",
        "1",
    )
    assert "--text-network-reserve-return must be a multiple of 10" in result.output


def test_campaigns_add_text_network_exploration_is_custom_no_payload():
    """#364: WSDL ``IsMinimumExplorationBudgetCustom`` is a
    ``general:YesNoEnum`` (campaigns.xml lines 1973-1977), so NO is
    a valid value."""
    body = _dry_run(
        *_text_network_base_args(),
        "--network-strategy",
        "AVERAGE_CPA",
        "--average-cpa",
        "100000000",
        "--goal-id",
        "1",
        "--text-network-exploration-min-budget",
        "300000000",
        "--text-network-exploration-is-custom",
        "NO",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network["AverageCpa"]["ExplorationBudget"] == {
        "MinimumExplorationBudget": 300000000,
        "IsMinimumExplorationBudgetCustom": "NO",
    }


def test_campaigns_add_text_network_rejects_package_with_network_flag():
    """text-network-* must not silently disappear when user opts into a
    PackageBiddingStrategy."""
    result = _rejected(
        *_text_network_base_args(),
        "--network-strategy",
        "AVERAGE_CPC",
        "--text-network-average-cpc",
        "5000000",
        "--text-network-weekly-spend-limit",
        "100000000",
        "--package-strategy-id",
        "700",
        "--package-platform-search-result",
        "YES",
        "--package-platform-product-gallery",
        "NO",
        "--package-platform-network",
        "YES",
        "--package-platform-dynamic-places",
        "NO",
    )
    assert "PackageBiddingStrategy cannot be combined" in result.output
    assert "--text-network-average-cpc" in result.output


def test_campaigns_update_text_network_average_cpc_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPC",
        "--text-network-average-cpc",
        "8000000",
        "--text-network-weekly-spend-limit",
        "1500000000",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text["BiddingStrategy"] == {
        "Network": {
            "BiddingStrategyType": "AVERAGE_CPC",
            "AverageCpc": {
                "AverageCpc": 8000000,
                "WeeklySpendLimit": 1500000000,
            },
        }
    }


def test_campaigns_update_text_network_search_and_network_payload():
    """#364: typing Search + Network simultaneously emits both halves."""
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "1000",
        "--type",
        "TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPC",
        "--text-search-average-cpc",
        "6000000",
        "--network-strategy",
        "AVERAGE_CPC",
        "--text-network-average-cpc",
        "7000000",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text["BiddingStrategy"] == {
        "Search": {
            "BiddingStrategyType": "AVERAGE_CPC",
            "AverageCpc": {"AverageCpc": 6000000},
        },
        "Network": {
            "BiddingStrategyType": "AVERAGE_CPC",
            "AverageCpc": {"AverageCpc": 7000000},
        },
    }


def test_campaigns_update_text_network_budget_type_weekly_payload():
    """#364: BudgetType WEEKLY_BUDGET nulls CustomPeriodBudget."""
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "1001",
        "--type",
        "TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPC",
        "--text-network-average-cpc",
        "5000000",
        "--text-network-weekly-spend-limit",
        "300000000",
        "--text-network-budget-type",
        "WEEKLY_BUDGET",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
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


def test_campaigns_update_text_network_budget_type_custom_period_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "1002",
        "--type",
        "TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPC",
        "--text-network-average-cpc",
        "5000000",
        "--text-network-custom-period-spend-limit",
        "1000000000",
        "--text-network-custom-period-start-date",
        "2026-07-01",
        "--text-network-custom-period-end-date",
        "2026-07-31",
        "--text-network-custom-period-auto-continue",
        "YES",
        "--text-network-budget-type",
        "CUSTOM_PERIOD_BUDGET",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
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


def test_campaigns_update_text_network_rejects_budget_type_without_weekly():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "1003",
        "--type",
        "TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPC",
        "--text-network-average-cpc",
        "5000000",
        "--text-network-budget-type",
        "WEEKLY_BUDGET",
    )
    assert "--text-network-budget-type WEEKLY_BUDGET requires" in result.output


def test_campaigns_update_text_network_wb_maximum_clicks_budget_type_payload():
    """#364: WSDL ``StrategyMaximumClicks`` (campaigns.xml lines 789-797)
    declares ``BudgetType`` on the get-side type used by
    ``TextCampaignUpdateItem``, so the CLI must emit ``BudgetType`` and
    null the alternate budget slice when the user switches budget on
    update."""
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "1004",
        "--type",
        "TEXT_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--text-network-weekly-spend-limit",
        "300000000",
        "--text-network-budget-type",
        "WEEKLY_BUDGET",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
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


def test_campaigns_update_text_network_partial_strategy_payload():
    """#364: partial update with only --network-strategy SERVING_OFF still
    must emit a Network block (no silent no-op)."""
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "2001",
        "--type",
        "TEXT_CAMPAIGN",
        "--network-strategy",
        "SERVING_OFF",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text["BiddingStrategy"]["Network"] == {"BiddingStrategyType": "SERVING_OFF"}


def test_campaigns_update_text_network_average_cpa_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "2002",
        "--type",
        "TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPA",
        "--average-cpa",
        "100000000",
        "--goal-id",
        "5",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPA",
        "AverageCpa": {
            "AverageCpa": 100000000,
            "GoalId": 5,
        },
    }


def test_campaigns_update_text_network_wb_maximum_clicks_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "3001",
        "--type",
        "TEXT_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--text-network-weekly-spend-limit",
        "700000000",
        "--bid-ceiling",
        "20000000",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
        "WbMaximumClicks": {
            "WeeklySpendLimit": 700000000,
            "BidCeiling": 20000000,
        },
    }


def test_campaigns_update_text_network_wb_maximum_conversion_rate_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "3002",
        "--type",
        "TEXT_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--goal-id",
        "111",
        "--text-network-weekly-spend-limit",
        "1200000000",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WB_MAXIMUM_CONVERSION_RATE",
        "WbMaximumConversionRate": {
            "GoalId": 111,
            "WeeklySpendLimit": 1200000000,
        },
    }


def test_campaigns_update_text_network_pay_for_conversion_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "3003",
        "--type",
        "TEXT_CAMPAIGN",
        "--network-strategy",
        "PAY_FOR_CONVERSION",
        "--text-network-pay-cpa",
        "150000000",
        "--goal-id",
        "44",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION",
        "PayForConversion": {
            "Cpa": 150000000,
            "GoalId": 44,
        },
    }


def test_campaigns_update_text_network_average_roi_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "3004",
        "--type",
        "TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_ROI",
        "--text-network-reserve-return",
        "40",
        "--text-network-roi-coef",
        "200000000",
        "--goal-id",
        "9",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_ROI",
        "AverageRoi": {
            "ReserveReturn": 40,
            "RoiCoef": 200000000,
            "GoalId": 9,
        },
    }


def test_campaigns_update_text_network_average_crr_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "3005",
        "--type",
        "TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CRR",
        "--crr",
        "20",
        "--goal-id",
        "33",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CRR",
        "AverageCrr": {
            "Crr": 20,
            "GoalId": 33,
        },
    }


def test_campaigns_update_text_network_pay_for_conversion_crr_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "3006",
        "--type",
        "TEXT_CAMPAIGN",
        "--network-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--crr",
        "15",
        "--goal-id",
        "21",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_CRR",
        "PayForConversionCrr": {
            "Crr": 15,
            "GoalId": 21,
        },
    }


def test_campaigns_update_text_network_weekly_click_package_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "3007",
        "--type",
        "TEXT_CAMPAIGN",
        "--network-strategy",
        "WEEKLY_CLICK_PACKAGE",
        "--text-network-clicks-per-week",
        "120",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WEEKLY_CLICK_PACKAGE",
        "WeeklyClickPackage": {"ClicksPerWeek": 120},
    }


def test_campaigns_update_text_network_max_profit_payload():
    """MAX_PROFIT update with bare strategy switch — PriorityGoals goes
    through the dedicated PriorityGoalsUpdateSetting path so the Network
    block is just the typed-marker."""
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "3008",
        "--type",
        "TEXT_CAMPAIGN",
        "--network-strategy",
        "MAX_PROFIT",
        "--priority-goals",
        "1:60000000,2:40000000",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text["BiddingStrategy"]["Network"] == {
        "BiddingStrategyType": "MAX_PROFIT",
        "MaxProfit": {},
    }


def test_campaigns_update_text_network_average_cpa_multiple_goals_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "3009",
        "--type",
        "TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--priority-goals",
        "10:70000000,20:30000000",
        "--bid-ceiling",
        "200000000",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPA_MULTIPLE_GOALS",
        "AverageCpaMultipleGoals": {"BidCeiling": 200000000},
    }


def test_campaigns_update_text_network_pay_for_conversion_multiple_goals_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "3010",
        "--type",
        "TEXT_CAMPAIGN",
        "--network-strategy",
        "PAY_FOR_CONVERSION_MULTIPLE_GOALS",
        "--priority-goals",
        "11:55000000,22:45000000",
        "--text-network-weekly-spend-limit",
        "400000000",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_MULTIPLE_GOALS",
        "PayForConversionMultipleGoals": {"WeeklySpendLimit": 400000000},
    }


def test_campaigns_update_text_network_network_default_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "3011",
        "--type",
        "TEXT_CAMPAIGN",
        "--network-strategy",
        "NETWORK_DEFAULT",
        "--text-network-limit-percent",
        "50",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "NETWORK_DEFAULT",
        "NetworkDefault": {"LimitPercent": 50},
    }


def test_campaigns_update_text_network_maximum_coverage_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "3012",
        "--type",
        "TEXT_CAMPAIGN",
        "--network-strategy",
        "MAXIMUM_COVERAGE",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {"BiddingStrategyType": "MAXIMUM_COVERAGE"}


def test_campaigns_update_text_network_average_cpa_multiple_goals_budget_type_payload():
    """#364: WSDL StrategyAverageCpaMultipleGoals (campaigns.xml 946-953)
    declares BudgetType; CLI must emit it on update."""
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "3013",
        "--type",
        "TEXT_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--priority-goals",
        "1:60000000,2:40000000",
        "--text-network-weekly-spend-limit",
        "500000000",
        "--text-network-budget-type",
        "WEEKLY_BUDGET",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPA_MULTIPLE_GOALS",
        "AverageCpaMultipleGoals": {
            "WeeklySpendLimit": 500000000,
            "CustomPeriodBudget": None,
            "BudgetType": "WEEKLY_BUDGET",
        },
    }


def test_campaigns_update_text_network_wb_maximum_conversion_rate_budget_type_payload():
    """#364: WSDL StrategyMaximumConversionRate (campaigns.xml 798-806)
    declares BudgetType; CLI must emit it on update."""
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "3014",
        "--type",
        "TEXT_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--goal-id",
        "55",
        "--text-network-custom-period-spend-limit",
        "1000000000",
        "--text-network-custom-period-start-date",
        "2026-07-01",
        "--text-network-custom-period-end-date",
        "2026-07-31",
        "--text-network-custom-period-auto-continue",
        "YES",
        "--text-network-budget-type",
        "CUSTOM_PERIOD_BUDGET",
    )
    network = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WB_MAXIMUM_CONVERSION_RATE",
        "WbMaximumConversionRate": {
            "GoalId": 55,
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


def test_campaigns_update_text_search_average_cpa_multi_goals_rejects_budget_type():
    """Yandex update docs: AverageCpaMultipleGoals does not declare BudgetType."""
    result = CliRunner().invoke(
        cli,
        [
            "campaigns",
            "update",
            "--id",
            "123",
            "--type",
            "TEXT_CAMPAIGN",
            "--search-strategy",
            "AVERAGE_CPA_MULTIPLE_GOALS",
            "--priority-goals",
            "1:60000000,2:40000000",
            "--text-search-budget-type",
            "WEEKLY_BUDGET",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "--text-search-budget-type" in result.output


def test_campaigns_add_text_search_rejects_with_package_bidding_strategy():
    """text-search-* flag input must not silently disappear when the user
    opts into PackageBiddingStrategy — the conflict has to surface."""
    result = _rejected(
        *_cpa_base_args(),
        "--package-strategy-id",
        "700",
        "--package-platform-search-result",
        "YES",
        "--package-platform-product-gallery",
        "NO",
        "--package-platform-network",
        "YES",
        "--package-platform-dynamic-places",
        "NO",
        "--text-search-weekly-spend-limit",
        "100000000",
    )
    assert "PackageBiddingStrategy" in result.output
    assert "--text-search-weekly-spend-limit" in result.output


def test_campaigns_update_text_search_rejects_with_package_bidding_strategy():
    result = CliRunner().invoke(
        cli,
        [
            "campaigns",
            "update",
            "--id",
            "123",
            "--type",
            "TEXT_CAMPAIGN",
            "--package-strategy-id",
            "700",
            "--text-search-weekly-spend-limit",
            "100000000",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "PackageBiddingStrategy" in result.output
    assert "--text-search-weekly-spend-limit" in result.output


def test_campaigns_update_text_search_rejects_budget_type_with_package_strategy():
    result = CliRunner().invoke(
        cli,
        [
            "campaigns",
            "update",
            "--id",
            "123",
            "--type",
            "TEXT_CAMPAIGN",
            "--package-strategy-id",
            "700",
            "--text-search-budget-type",
            "WEEKLY_BUDGET",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "PackageBiddingStrategy" in result.output
    assert "--text-search-budget-type" in result.output


def test_campaigns_text_search_flags_rejected_for_other_campaign_types():
    """text-search-* flags must NOT be accepted under --type != TEXT_CAMPAIGN."""
    result = CliRunner().invoke(
        cli,
        [
            "campaigns",
            "add",
            "--name",
            "C",
            "--start-date",
            "2026-06-01",
            "--type",
            "DYNAMIC_TEXT_CAMPAIGN",
            "--text-search-weekly-spend-limit",
            "100000000",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert (
        "DYNAMIC_TEXT_CAMPAIGN" in result.output
        or "--text-search-weekly-spend-limit" in result.output
    )


def test_campaigns_add_dynamic_text_search_legacy_average_cpa_still_works():
    """#362 back-compat: legacy --average-cpa / --goal-id still drive
    DynamicTextCampaign Search AVERAGE_CPA when no --dyn-search-* flag
    is given. Mirrors the pre-#362 behavior of apply_cpa_strategy_fields.
    """
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn legacy CPA",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA",
        "--network-strategy",
        "SERVING_OFF",
        "--average-cpa",
        "200000000",
        "--goal-id",
        "42",
    )
    dyn = body["params"]["Campaigns"][0]["DynamicTextCampaign"]
    search = dyn["BiddingStrategy"]["Search"]
    assert search["BiddingStrategyType"] == "AVERAGE_CPA"
    assert search["AverageCpa"] == {"AverageCpa": 200000000, "GoalId": 42}


def test_campaigns_add_dynamic_text_search_highest_position_payload():
    """#362: HIGHEST_POSITION is the legacy default and accepts no
    Strategy*Add block.
    """
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Search Highest",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "HIGHEST_POSITION",
        "--network-strategy",
        "SERVING_OFF",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {"BiddingStrategyType": "HIGHEST_POSITION"}


def test_campaigns_add_dynamic_text_search_serving_off_payload():
    """#362: SERVING_OFF is enum-only, no Strategy*Add block."""
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Search Off",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "SERVING_OFF",
        "--network-strategy",
        "SERVING_OFF",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {"BiddingStrategyType": "SERVING_OFF"}


def test_campaigns_add_dynamic_text_search_impressions_below_search_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Search Below",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "IMPRESSIONS_BELOW_SEARCH",
        "--network-strategy",
        "SERVING_OFF",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {"BiddingStrategyType": "IMPRESSIONS_BELOW_SEARCH"}


def test_campaigns_add_dynamic_text_search_placement_types_payload():
    """#362: PlacementTypes (SearchResults/ProductGallery/DynamicPlaces)
    serialised as nested dict on the Search block.
    """
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Search Placement",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "HIGHEST_POSITION",
        "--network-strategy",
        "SERVING_OFF",
        "--search-placement-search-results",
        "YES",
        "--search-placement-product-gallery",
        "NO",
        "--search-placement-dynamic-places",
        "YES",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "HIGHEST_POSITION",
        "PlacementTypes": {
            "SearchResults": "YES",
            "ProductGallery": "NO",
            "DynamicPlaces": "YES",
        },
    }


def test_campaigns_add_dynamic_text_search_wb_maximum_clicks_weekly_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Search WbClicks Weekly",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-weekly-spend-limit",
        "1000000000",
        "--dyn-search-bid-ceiling",
        "100000000",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
        "WbMaximumClicks": {
            "WeeklySpendLimit": 1000000000,
            "BidCeiling": 100000000,
        },
    }


def test_campaigns_add_dynamic_text_search_wb_maximum_clicks_custom_period_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Search WbClicks CP",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-custom-period-spend-limit",
        "5000000000",
        "--dyn-search-custom-period-start-date",
        "2026-06-01",
        "--dyn-search-custom-period-end-date",
        "2026-06-30",
        "--dyn-search-custom-period-auto-continue",
        "YES",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
        "WbMaximumClicks": {
            "CustomPeriodBudget": {
                "SpendLimit": 5000000000,
                "StartDate": "2026-06-01",
                "EndDate": "2026-06-30",
                "AutoContinue": "YES",
            },
        },
    }


def test_campaigns_add_dynamic_text_search_wb_maximum_conversion_rate_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Search Wb Conv",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-goal-id",
        "42",
        "--dyn-search-weekly-spend-limit",
        "2000000000",
        "--dyn-search-bid-ceiling",
        "150000000",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "WB_MAXIMUM_CONVERSION_RATE",
        "WbMaximumConversionRate": {
            "GoalId": 42,
            "WeeklySpendLimit": 2000000000,
            "BidCeiling": 150000000,
        },
    }


def test_campaigns_add_dynamic_text_search_average_cpc_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Search AvgCpc",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPC",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-average-cpc",
        "8000000",
        "--dyn-search-weekly-spend-limit",
        "1500000000",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPC",
        "AverageCpc": {
            "AverageCpc": 8000000,
            "WeeklySpendLimit": 1500000000,
        },
    }


def test_campaigns_add_dynamic_text_search_average_cpa_with_exploration_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Search AvgCpa",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-average-cpa",
        "200000000",
        "--dyn-search-goal-id",
        "42",
        "--dyn-search-bid-ceiling",
        "50000000",
        "--dyn-search-exploration-budget",
        "100000000",
        "--dyn-search-exploration-budget-custom",
        "YES",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPA",
        "AverageCpa": {
            "AverageCpa": 200000000,
            "GoalId": 42,
            "BidCeiling": 50000000,
            "ExplorationBudget": {
                "MinimumExplorationBudget": 100000000,
                "IsMinimumExplorationBudgetCustom": "YES",
            },
        },
    }


def test_campaigns_add_dynamic_text_search_pay_for_conversion_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Search PayConv",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "PAY_FOR_CONVERSION",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-cpa",
        "300000000",
        "--dyn-search-goal-id",
        "42",
        "--dyn-search-weekly-spend-limit",
        "1000000000",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION",
        "PayForConversion": {
            "Cpa": 300000000,
            "GoalId": 42,
            "WeeklySpendLimit": 1000000000,
        },
    }


def test_campaigns_add_dynamic_text_search_average_roi_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Search Roi",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_ROI",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-reserve-return",
        "20",
        "--dyn-search-roi-coef",
        "150",
        "--dyn-search-goal-id",
        "42",
        "--dyn-search-profitability",
        "25",
        "--dyn-search-weekly-spend-limit",
        "2000000000",
        "--dyn-search-bid-ceiling",
        "100000000",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_ROI",
        "AverageRoi": {
            "ReserveReturn": 20,
            "RoiCoef": 150,
            "GoalId": 42,
            "Profitability": 25,
            "WeeklySpendLimit": 2000000000,
            "BidCeiling": 100000000,
        },
    }


def test_campaigns_add_dynamic_text_search_average_crr_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Search AvgCrr",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CRR",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-crr",
        "10",
        "--dyn-search-goal-id",
        "42",
        "--dyn-search-weekly-spend-limit",
        "1500000000",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CRR",
        "AverageCrr": {
            "Crr": 10,
            "GoalId": 42,
            "WeeklySpendLimit": 1500000000,
        },
    }


def test_campaigns_add_dynamic_text_search_pay_for_conversion_crr_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Search PayConvCrr",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-crr",
        "15",
        "--dyn-search-goal-id",
        "42",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_CRR",
        "PayForConversionCrr": {
            "Crr": 15,
            "GoalId": 42,
        },
    }


def test_campaigns_add_dynamic_text_search_weekly_click_package_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Search WCP",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "WEEKLY_CLICK_PACKAGE",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-clicks-per-week",
        "100",
        "--dyn-search-bid-ceiling",
        "50000000",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "WEEKLY_CLICK_PACKAGE",
        "WeeklyClickPackage": {
            "ClicksPerWeek": 100,
            "BidCeiling": 50000000,
        },
    }


def test_campaigns_add_dynamic_text_search_rejects_partial_exploration_budget():
    """#362: ExplorationBudget requires both subfields together."""
    result = _failing_run(
        "campaigns",
        "add",
        "--name",
        "Bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-average-cpa",
        "100000000",
        "--dyn-search-goal-id",
        "42",
        "--dyn-search-exploration-budget",
        "50000000",
    )
    assert result.exit_code != 0
    assert "ExplorationBudget" in result.output


def test_campaigns_add_dynamic_text_search_rejects_partial_custom_period():
    """#362: CustomPeriodBudget requires all four subfields together."""
    result = _failing_run(
        "campaigns",
        "add",
        "--name",
        "Bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-custom-period-spend-limit",
        "100000000",
        "--dyn-search-custom-period-start-date",
        "2026-06-01",
    )
    assert result.exit_code != 0
    assert "CustomPeriodBudget" in result.output


def test_campaigns_add_dynamic_text_search_rejects_weekly_and_custom_period_combo():
    """#362: WeeklySpendLimit and CustomPeriodBudget are mutually exclusive."""
    result = _failing_run(
        "campaigns",
        "add",
        "--name",
        "Bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-weekly-spend-limit",
        "1000000000",
        "--dyn-search-custom-period-spend-limit",
        "1000000000",
        "--dyn-search-custom-period-start-date",
        "2026-06-01",
        "--dyn-search-custom-period-end-date",
        "2026-06-30",
        "--dyn-search-custom-period-auto-continue",
        "YES",
    )
    assert result.exit_code != 0
    assert "cannot be combined" in result.output


def test_campaigns_add_dynamic_text_search_rejects_field_for_wrong_subtype():
    """#362: silent-data-loss invariant — typed flag rejected when not
    declared on the chosen Strategy*Add subtype."""
    result = _failing_run(
        "campaigns",
        "add",
        "--name",
        "Bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-average-cpa",
        "100000000",
        "--dyn-search-goal-id",
        "42",
        "--dyn-search-clicks-per-week",
        "500",
    )
    assert result.exit_code != 0
    assert "does not accept --dyn-search-clicks-per-week" in result.output


def test_campaigns_add_dynamic_text_search_rejects_legacy_flag_combo():
    """#362: combining legacy --average-cpa with --dyn-search-* is blocked."""
    result = _failing_run(
        "campaigns",
        "add",
        "--name",
        "Bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-average-cpa",
        "100000000",
        "--dyn-search-goal-id",
        "42",
        "--average-cpa",
        "200000000",
    )
    assert result.exit_code != 0
    assert "cannot be combined with the legacy CPA-shape flags" in result.output


def test_campaigns_add_dynamic_text_search_required_average_cpa_when_typed_used():
    """#362: minOccurs=1 enforcement on add path when typed flags engaged."""
    result = _failing_run(
        "campaigns",
        "add",
        "--name",
        "Bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-bid-ceiling",
        "100000000",
    )
    assert result.exit_code != 0
    assert "AVERAGE_CPA requires" in result.output


def test_campaigns_add_dynamic_text_search_strict_required_for_non_legacy_subtypes():
    """#362 regression guard: strategy-only creates of non-CPA-shape Search
    families must NOT bypass WSDL minOccurs=1 validation, because the
    legacy ``apply_cpa_strategy_fields`` path only fills AVERAGE_CPA and
    PAY_FOR_CONVERSION_CRR. Without this guard the campaigns.add call
    would emit a schema-invalid Strategy*Add block to Yandex.
    """
    cases = [
        ("AVERAGE_CPC", "AVERAGE_CPC requires --dyn-search-average-cpc"),
        ("AVERAGE_ROI", "AVERAGE_ROI requires"),
        (
            "WEEKLY_CLICK_PACKAGE",
            "WEEKLY_CLICK_PACKAGE requires --dyn-search-clicks-per-week",
        ),
        (
            "WB_MAXIMUM_CONVERSION_RATE",
            "WB_MAXIMUM_CONVERSION_RATE requires --dyn-search-goal-id",
        ),
        (
            "PAY_FOR_CONVERSION",
            "PAY_FOR_CONVERSION requires --dyn-search-cpa, --dyn-search-goal-id",
        ),
        ("AVERAGE_CRR", "AVERAGE_CRR requires"),
    ]
    for strategy, expected in cases:
        result = _failing_run(
            "campaigns",
            "add",
            "--name",
            "Bad",
            "--start-date",
            "2026-06-01",
            "--type",
            "DYNAMIC_TEXT_CAMPAIGN",
            "--search-strategy",
            strategy,
            "--network-strategy",
            "SERVING_OFF",
        )
        assert result.exit_code != 0, f"strategy {strategy} unexpectedly accepted"
        assert (
            expected in result.output
        ), f"strategy {strategy}: expected '{expected}' in output, got: {result.output}"


def test_campaigns_add_dynamic_text_search_wb_maximum_clicks_strategy_only_payload():
    """#362: WB_MAXIMUM_CLICKS has no minOccurs=1 fields beyond
    BiddingStrategyType (StrategyMaximumClicksAdd extends
    StrategyWeeklyBudgetAddBase, both members minOccurs=0). Strategy-only
    create must succeed without typed detail flags.
    """
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn WbClicks bare",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--network-strategy",
        "SERVING_OFF",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {"BiddingStrategyType": "WB_MAXIMUM_CLICKS"}


def test_campaigns_add_dynamic_text_search_rejects_serving_off_with_details():
    """#362: SERVING_OFF / HIGHEST_POSITION / IMPRESSIONS_BELOW_SEARCH
    do not accept Strategy*Add fields.
    """
    result = _failing_run(
        "campaigns",
        "add",
        "--name",
        "Bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "SERVING_OFF",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-weekly-spend-limit",
        "1000000000",
    )
    assert result.exit_code != 0
    assert "SERVING_OFF does not accept" in result.output


def test_campaigns_add_dynamic_text_search_rejects_detail_without_search_strategy():
    """#362: --dyn-search-* without --search-strategy raises UsageError."""
    result = _failing_run(
        "campaigns",
        "add",
        "--name",
        "Bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-weekly-spend-limit",
        "1000000000",
    )
    assert result.exit_code != 0
    assert "require --search-strategy" in result.output


def test_campaigns_add_dynamic_text_search_rejects_budget_type_on_add():
    """#362: --dyn-search-budget-type is update-only — not available on add.
    (It is intentionally not declared on the ``add`` decorator stack.)
    """
    result = _failing_run(
        "campaigns",
        "add",
        "--name",
        "Bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--network-strategy",
        "SERVING_OFF",
        "--dyn-search-weekly-spend-limit",
        "1000000000",
        "--dyn-search-budget-type",
        "WEEKLY_BUDGET",
    )
    assert result.exit_code != 0


def test_campaigns_update_dynamic_text_search_average_cpc_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "999",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPC",
        "--dyn-search-average-cpc",
        "8000000",
        "--dyn-search-weekly-spend-limit",
        "1500000000",
    )
    dyn = body["params"]["Campaigns"][0]["DynamicTextCampaign"]
    assert dyn["BiddingStrategy"] == {
        "Search": {
            "BiddingStrategyType": "AVERAGE_CPC",
            "AverageCpc": {
                "AverageCpc": 8000000,
                "WeeklySpendLimit": 1500000000,
            },
        }
    }


def test_campaigns_update_dynamic_text_search_placement_only_payload():
    """#362: placement-only update — Search is emitted with PlacementTypes
    but no Strategy*Add block.
    """
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "1001",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "HIGHEST_POSITION",
        "--search-placement-search-results",
        "YES",
        "--search-placement-product-gallery",
        "NO",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "HIGHEST_POSITION",
        "PlacementTypes": {
            "SearchResults": "YES",
            "ProductGallery": "NO",
        },
    }


def test_campaigns_update_dynamic_text_search_budget_type_weekly_payload():
    """#362: BudgetType WEEKLY_BUDGET nulls CustomPeriodBudget."""
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "2002",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--dyn-search-weekly-spend-limit",
        "300000000",
        "--dyn-search-budget-type",
        "WEEKLY_BUDGET",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
        "WbMaximumClicks": {
            "WeeklySpendLimit": 300000000,
            "CustomPeriodBudget": None,
            "BudgetType": "WEEKLY_BUDGET",
        },
    }


def test_campaigns_update_dynamic_text_search_budget_type_custom_period_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "2003",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA",
        "--dyn-search-custom-period-spend-limit",
        "1000000000",
        "--dyn-search-custom-period-start-date",
        "2026-06-01",
        "--dyn-search-custom-period-end-date",
        "2026-06-30",
        "--dyn-search-custom-period-auto-continue",
        "YES",
        "--dyn-search-budget-type",
        "CUSTOM_PERIOD_BUDGET",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPA",
        "AverageCpa": {
            "CustomPeriodBudget": {
                "SpendLimit": 1000000000,
                "StartDate": "2026-06-01",
                "EndDate": "2026-06-30",
                "AutoContinue": "YES",
            },
            "WeeklySpendLimit": None,
            "BudgetType": "CUSTOM_PERIOD_BUDGET",
        },
    }


def test_campaigns_update_dynamic_text_search_strategy_only_leaves_bs_unset():
    """#362: with neither search-strategy nor any typed flag, the update
    payload omits BiddingStrategy entirely.
    """
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "7007",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--tracking-params",
        "utm_source=test",
    )
    dyn = body["params"]["Campaigns"][0]["DynamicTextCampaign"]
    assert "BiddingStrategy" not in dyn
    assert dyn["TrackingParams"] == "utm_source=test"


def test_campaigns_update_dynamic_text_search_standalone_budget_type_payload():
    """#362: per WSDL StrategyMaximumClicks (campaigns WSDL line 789-797)
    BudgetType is an independent optional element. Standalone
    --dyn-search-budget-type on update must emit just BudgetType (use case:
    flip an already-configured campaign between budget slices without
    re-supplying the slice). Yandex enforces any inconsistency at the wire.
    """
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "8001",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--dyn-search-budget-type",
        "WEEKLY_BUDGET",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
        "WbMaximumClicks": {
            "CustomPeriodBudget": None,
            "BudgetType": "WEEKLY_BUDGET",
        },
    }


def test_campaigns_update_dynamic_text_search_rejects_budget_type_on_non_budget_subtype():
    """#362: BudgetType is only supported on the eight Wb*/AverageCp*/
    AverageRoi/AverageCrr/PayFor*Crr subtypes that carry both
    WeeklySpendLimit and CustomPeriodBudget. WeeklyClickPackage has no
    CustomPeriodBudget, so BudgetType is not in its WSDL declaration.
    """
    result = _failing_run(
        "campaigns",
        "update",
        "--id",
        "1",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "WEEKLY_CLICK_PACKAGE",
        "--dyn-search-budget-type",
        "WEEKLY_BUDGET",
    )
    assert result.exit_code != 0
    assert "does not accept --dyn-search-budget-type" in result.output


def test_campaigns_update_dynamic_text_search_rejects_partial_strategy_switch():
    """#362: switching --search-strategy on update without required typed
    flags is allowed (mirroring Network builder semantics) — only field-
    support validation runs. Sanity check that field-support fires.
    """
    result = _failing_run(
        "campaigns",
        "update",
        "--id",
        "1",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA",
        "--dyn-search-clicks-per-week",
        "10",
    )
    assert result.exit_code != 0
    assert "does not accept --dyn-search-clicks-per-week" in result.output


def test_campaigns_add_dynamic_text_search_package_strategy_rejects_dyn_search():
    """#362: PackageBiddingStrategy on DynamicTextCampaign add must reject
    every typed --dyn-search-* flag so search detail input is never
    silently dropped (mirrors the TEXT_CAMPAIGN text-search-* conflict).
    """
    result = _failing_run(
        "campaigns",
        "add",
        "--name",
        "Bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--package-strategy-id",
        "99",
        "--dyn-search-average-cpc",
        "10000000",
    )
    assert result.exit_code != 0
    assert (
        "PackageBiddingStrategy cannot be combined with --dyn-search-average-cpc"
        in result.output
    )


def test_campaigns_update_dynamic_text_search_wb_maximum_clicks_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "5005",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--dyn-search-weekly-spend-limit",
        "500000000",
        "--dyn-search-bid-ceiling",
        "50000000",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
        "WbMaximumClicks": {
            "WeeklySpendLimit": 500000000,
            "BidCeiling": 50000000,
        },
    }


def test_campaigns_update_dynamic_text_search_wb_maximum_conversion_rate_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "5006",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "WB_MAXIMUM_CONVERSION_RATE",
        "--dyn-search-goal-id",
        "77",
        "--dyn-search-weekly-spend-limit",
        "800000000",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "WB_MAXIMUM_CONVERSION_RATE",
        "WbMaximumConversionRate": {
            "GoalId": 77,
            "WeeklySpendLimit": 800000000,
        },
    }


def test_campaigns_update_dynamic_text_search_average_cpa_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "5007",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA",
        "--dyn-search-average-cpa",
        "150000000",
        "--dyn-search-goal-id",
        "42",
        "--dyn-search-bid-ceiling",
        "30000000",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPA",
        "AverageCpa": {
            "AverageCpa": 150000000,
            "GoalId": 42,
            "BidCeiling": 30000000,
        },
    }


def test_campaigns_update_dynamic_text_search_pay_for_conversion_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "5008",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "PAY_FOR_CONVERSION",
        "--dyn-search-cpa",
        "250000000",
        "--dyn-search-goal-id",
        "42",
        "--dyn-search-weekly-spend-limit",
        "1000000000",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION",
        "PayForConversion": {
            "Cpa": 250000000,
            "GoalId": 42,
            "WeeklySpendLimit": 1000000000,
        },
    }


def test_campaigns_update_dynamic_text_search_average_roi_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "5009",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_ROI",
        "--dyn-search-reserve-return",
        "30",
        "--dyn-search-roi-coef",
        "200",
        "--dyn-search-goal-id",
        "42",
        "--dyn-search-profitability",
        "20",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_ROI",
        "AverageRoi": {
            "ReserveReturn": 30,
            "RoiCoef": 200,
            "GoalId": 42,
            "Profitability": 20,
        },
    }


def test_campaigns_update_dynamic_text_search_average_crr_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "5010",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CRR",
        "--dyn-search-crr",
        "12",
        "--dyn-search-goal-id",
        "42",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CRR",
        "AverageCrr": {
            "Crr": 12,
            "GoalId": 42,
        },
    }


def test_campaigns_update_dynamic_text_search_pay_for_conversion_crr_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "5011",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--dyn-search-crr",
        "8",
        "--dyn-search-goal-id",
        "42",
        "--dyn-search-weekly-spend-limit",
        "500000000",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_CRR",
        "PayForConversionCrr": {
            "Crr": 8,
            "GoalId": 42,
            "WeeklySpendLimit": 500000000,
        },
    }


def test_campaigns_update_dynamic_text_search_weekly_click_package_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "5012",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "WEEKLY_CLICK_PACKAGE",
        "--dyn-search-clicks-per-week",
        "200",
        "--dyn-search-average-cpc",
        "5000000",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "WEEKLY_CLICK_PACKAGE",
        "WeeklyClickPackage": {
            "ClicksPerWeek": 200,
            "AverageCpc": 5000000,
        },
    }


def test_campaigns_update_dynamic_text_search_average_cpa_with_exploration_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "5013",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA",
        "--dyn-search-average-cpa",
        "200000000",
        "--dyn-search-goal-id",
        "42",
        "--dyn-search-exploration-budget",
        "100000000",
        "--dyn-search-exploration-budget-custom",
        "NO",
    )
    search = body["params"]["Campaigns"][0]["DynamicTextCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPA",
        "AverageCpa": {
            "AverageCpa": 200000000,
            "GoalId": 42,
            "ExplorationBudget": {
                "MinimumExplorationBudget": 100000000,
                "IsMinimumExplorationBudgetCustom": "NO",
            },
        },
    }
