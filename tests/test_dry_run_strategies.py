"""Dry-run payload tests for the ``strategies`` service (packaged strategies).

Split out of the historical monolithic ``tests/test_dry_run.py`` (issue #604).
See :mod:`tests.test_dry_run_shared` for the shared invocation helpers and
``tests/test_dry_run.py`` for the rationale behind the whole suite.
"""

import pytest
from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli.utils import get_default_fields
from tests.test_dry_run_shared import _dry_run, _failing_run, _read_dry_run

STRATEGIES_GET_NESTED_FIELD_NAME_OPTIONS = [
    ("--strategy-average-cpa-field-names", "StrategyAverageCpaFieldNames"),
    (
        "--strategy-average-cpa-multiple-goals-field-names",
        "StrategyAverageCpaMultipleGoalsFieldNames",
    ),
    (
        "--strategy-average-cpa-per-campaign-field-names",
        "StrategyAverageCpaPerCampaignFieldNames",
    ),
    (
        "--strategy-average-cpa-per-filter-field-names",
        "StrategyAverageCpaPerFilterFieldNames",
    ),
    ("--strategy-average-cpc-field-names", "StrategyAverageCpcFieldNames"),
    (
        "--strategy-average-cpc-per-campaign-field-names",
        "StrategyAverageCpcPerCampaignFieldNames",
    ),
    (
        "--strategy-average-cpc-per-filter-field-names",
        "StrategyAverageCpcPerFilterFieldNames",
    ),
    ("--strategy-average-crr-field-names", "StrategyAverageCrrFieldNames"),
    ("--strategy-max-profit-field-names", "StrategyMaxProfitFieldNames"),
    ("--strategy-maximum-clicks-field-names", "StrategyMaximumClicksFieldNames"),
    (
        "--strategy-maximum-conversion-rate-field-names",
        "StrategyMaximumConversionRateFieldNames",
    ),
    (
        "--strategy-pay-for-conversion-crr-field-names",
        "StrategyPayForConversionCrrFieldNames",
    ),
    (
        "--strategy-pay-for-conversion-field-names",
        "StrategyPayForConversionFieldNames",
    ),
    (
        "--strategy-pay-for-conversion-multiple-goals-field-names",
        "StrategyPayForConversionMultipleGoalsFieldNames",
    ),
    (
        "--strategy-pay-for-conversion-per-campaign-field-names",
        "StrategyPayForConversionPerCampaignFieldNames",
    ),
    (
        "--strategy-pay-for-conversion-per-filter-field-names",
        "StrategyPayForConversionPerFilterFieldNames",
    ),
]


def test_strategies_get_default_field_names_payload():
    body = _read_dry_run("strategies", "get", "--ids", "123")

    assert body["method"] == "get"
    assert body["params"]["SelectionCriteria"] == {"Ids": [123]}
    assert body["params"]["FieldNames"] == get_default_fields("strategies")
    assert "StrategyAverageCpaFieldNames" not in body["params"]


def test_strategies_get_nested_field_names_payload():
    body = _read_dry_run(
        "strategies",
        "get",
        "--ids",
        "123",
        "--strategy-average-cpa-field-names",
        "AverageCpa,GoalId",
        "--strategy-maximum-clicks-field-names",
        "WeeklySpendLimit,BidCeiling",
        "--strategy-pay-for-conversion-multiple-goals-field-names",
        "WeeklySpendLimit,PriorityGoals",
    )

    params = body["params"]
    assert params["StrategyAverageCpaFieldNames"] == ["AverageCpa", "GoalId"]
    assert params["StrategyMaximumClicksFieldNames"] == [
        "WeeklySpendLimit",
        "BidCeiling",
    ]
    assert params["StrategyPayForConversionMultipleGoalsFieldNames"] == [
        "WeeklySpendLimit",
        "PriorityGoals",
    ]


def test_strategies_get_help_exposes_nested_field_names_options():
    result = CliRunner().invoke(cli, ["strategies", "get", "--help"])

    assert result.exit_code == 0
    assert "--dry-run" in result.output
    for flag, _ in STRATEGIES_GET_NESTED_FIELD_NAME_OPTIONS:
        assert flag in result.output


@pytest.mark.parametrize("flag,wsdl_key", STRATEGIES_GET_NESTED_FIELD_NAME_OPTIONS)
def test_strategies_get_rejects_empty_nested_field_names(flag, wsdl_key):
    result = CliRunner().invoke(cli, ["strategies", "get", flag, ",", "--dry-run"])

    assert result.exit_code != 0
    assert f"Provide a non-empty comma-separated {wsdl_key} list." in result.output


def test_strategies_add_payload():
    body = _dry_run(
        "strategies",
        "add",
        "--name",
        "My Strategy",
        "--type",
        "AverageCpc",
        "--average-cpc",
        "1000000",
        "--priority-goal",
        "123:2000000",
    )
    assert body["method"] == "add"
    s = body["params"]["Strategies"][0]
    assert s["Name"] == "My Strategy"
    assert s["AverageCpc"]["AverageCpc"] == 1000000
    assert s["PriorityGoals"]["Items"] == [{"GoalId": 123, "Value": 2000000}]


def test_strategies_add_priority_goal_metrika_source_payload():
    body = _dry_run(
        "strategies",
        "add",
        "--name",
        "CRR Strategy",
        "--type",
        "AverageCrr",
        "--average-crr",
        "10",
        "--goal-id",
        "123",
        "--priority-goal",
        "123:2000000:YES",
        "--priority-goal",
        "456:1000000:no",
    )
    s = body["params"]["Strategies"][0]
    assert s["PriorityGoals"]["Items"] == [
        {
            "GoalId": 123,
            "Value": 2000000,
            "IsMetrikaSourceOfValue": "YES",
        },
        {
            "GoalId": 456,
            "Value": 1000000,
            "IsMetrikaSourceOfValue": "NO",
        },
    ]


def test_strategies_add_no_type_key_at_root():
    body = _dry_run(
        "strategies",
        "add",
        "--name",
        "My Strategy",
        "--type",
        "WbMaximumClicks",
    )
    s = body["params"]["Strategies"][0]
    assert "Type" not in s
    assert "WbMaximumClicks" in s


def test_strategies_update_payload():
    body = _dry_run(
        "strategies",
        "update",
        "--id",
        "77",
        "--name",
        "Updated",
        "--type",
        "AverageCpc",
        "--average-cpc",
        "1500000",
    )
    assert body["method"] == "update"
    s = body["params"]["Strategies"][0]
    assert s["Id"] == 77
    assert s["Name"] == "Updated"
    assert s["AverageCpc"]["AverageCpc"] == 1500000


def test_strategies_update_priority_goal_metrika_source_payload():
    body = _dry_run(
        "strategies",
        "update",
        "--id",
        "77",
        "--priority-goal",
        "123:2000000:YES",
    )
    s = body["params"]["Strategies"][0]
    assert s == {
        "Id": 77,
        "PriorityGoals": {
            "Items": [
                {
                    "GoalId": 123,
                    "Value": 2000000,
                    "IsMetrikaSourceOfValue": "YES",
                }
            ]
        },
    }


def test_strategies_rejects_invalid_priority_goal_metrika_source():
    result = _failing_run(
        "strategies",
        "update",
        "--id",
        "77",
        "--priority-goal",
        "123:2000000:MAYBE",
        "--dry-run",
    )
    assert result.exit_code != 0
    assert "IsMetrikaSourceOfValue must be YES or NO" in result.output


def test_strategies_add_rejects_priority_goal_value_below_micro_min():
    # Issue #387 sibling: PriorityGoalsItem.Value is xsd:long in
    # advertiser currency × 1,000,000 for standalone Strategy* items
    # too (tests/wsdl_cache/strategies.xml lines 503-509). Reject
    # raw-ruble inputs at CLI parse time to mirror the campaigns side.
    result = _failing_run(
        "strategies",
        "add",
        "--name",
        "CRR Strategy",
        "--type",
        "AverageCrr",
        "--average-crr",
        "10",
        "--goal-id",
        "123",
        "--priority-goal",
        "123:500",
        "--dry-run",
    )
    assert result.exit_code != 0
    assert "--priority-goal" in result.output
    assert "micro-currency" in result.output
    assert "500000000" in result.output


def test_strategies_update_rejects_priority_goal_negative_value():
    result = _failing_run(
        "strategies",
        "update",
        "--id",
        "77",
        "--priority-goal",
        "123:-1000000",
        "--dry-run",
    )
    assert result.exit_code != 0
    assert "--priority-goal" in result.output
    assert "non-negative" in result.output


def test_strategies_update_requires_type_for_strategy_specific_fields():
    result = _failing_run(
        "strategies",
        "update",
        "--id",
        "77",
        "--average-cpc",
        "1500000",
        "--dry-run",
    )
    assert result.exit_code != 0
    assert "Provide --type when setting strategy-specific fields" in result.output


def test_strategies_update_average_cpc_per_filter_maps_to_filter_average_cpc():
    body = _dry_run(
        "strategies",
        "update",
        "--id",
        "42",
        "--type",
        "AverageCpcPerFilter",
        "--average-cpc",
        "30000000",
    )
    s = body["params"]["Strategies"][0]
    assert s["AverageCpcPerFilter"] == {"FilterAverageCpc": 30000000}


def test_strategies_update_pay_for_conversion_maps_average_cpa_to_cpa():
    body = _dry_run(
        "strategies",
        "update",
        "--id",
        "42",
        "--type",
        "PayForConversion",
        "--average-cpa",
        "4000000",
        "--goal-id",
        "123",
    )
    s = body["params"]["Strategies"][0]
    assert s["PayForConversion"] == {"Cpa": 4000000, "GoalId": 123}


def test_strategies_update_average_cpa_without_goal_id_is_allowed():
    body = _dry_run(
        "strategies",
        "update",
        "--id",
        "42",
        "--type",
        "AverageCpa",
        "--average-cpa",
        "4000000",
    )
    s = body["params"]["Strategies"][0]
    assert s["AverageCpa"] == {"AverageCpa": 4000000}
    assert "GoalId" not in s["AverageCpa"]


def test_strategies_add_custom_period_budget_payload():
    body = _dry_run(
        "strategies",
        "add",
        "--name",
        "Custom Period",
        "--type",
        "WbMaximumClicks",
        "--custom-period-spend-limit",
        "1000000000",
        "--custom-period-start-date",
        "2026-06-01",
        "--custom-period-end-date",
        "2026-06-30",
        "--custom-period-auto-continue",
        "yes",
    )
    s = body["params"]["Strategies"][0]
    assert s["WbMaximumClicks"] == {
        "CustomPeriodBudget": {
            "SpendLimit": 1000000000,
            "StartDate": "2026-06-01",
            "EndDate": "2026-06-30",
            "AutoContinue": "YES",
        }
    }


def test_strategies_update_custom_period_budget_payload():
    body = _dry_run(
        "strategies",
        "update",
        "--id",
        "42",
        "--type",
        "AverageCpc",
        "--custom-period-spend-limit",
        "500000000",
        "--custom-period-start-date",
        "2026-07-01",
        "--custom-period-end-date",
        "2026-07-31",
        "--custom-period-auto-continue",
        "no",
    )
    s = body["params"]["Strategies"][0]
    assert s["Id"] == 42
    assert s["AverageCpc"] == {
        "CustomPeriodBudget": {
            "SpendLimit": 500000000,
            "StartDate": "2026-07-01",
            "EndDate": "2026-07-31",
            "AutoContinue": "NO",
        }
    }


def test_strategies_custom_period_budget_requires_all_fields():
    result = _failing_run(
        "strategies",
        "add",
        "--name",
        "Custom Period",
        "--type",
        "WbMaximumClicks",
        "--custom-period-spend-limit",
        "1000000000",
        "--dry-run",
    )
    assert result.exit_code != 0
    assert "CustomPeriodBudget requires" in result.output
    assert "--custom-period-start-date" in result.output
    assert "--custom-period-end-date" in result.output
    assert "--custom-period-auto-continue" in result.output


def test_strategies_update_custom_period_budget_requires_type():
    result = _failing_run(
        "strategies",
        "update",
        "--id",
        "42",
        "--custom-period-spend-limit",
        "1000000000",
        "--custom-period-start-date",
        "2026-06-01",
        "--custom-period-end-date",
        "2026-06-30",
        "--custom-period-auto-continue",
        "YES",
        "--dry-run",
    )
    assert result.exit_code != 0
    assert "Provide --type when setting strategy-specific fields" in result.output


def test_strategies_update_average_cpa_rejects_custom_period_budget():
    result = _failing_run(
        "strategies",
        "update",
        "--id",
        "42",
        "--type",
        "AverageCpa",
        "--custom-period-spend-limit",
        "1000000000",
        "--custom-period-start-date",
        "2026-06-01",
        "--custom-period-end-date",
        "2026-06-30",
        "--custom-period-auto-continue",
        "YES",
        "--dry-run",
    )
    assert result.exit_code != 0
    assert (
        "--custom-period-* flags are not valid for --type AverageCpa "
        "on strategies update."
    ) in result.output


def test_strategies_custom_period_budget_rejects_weekly_spend_limit():
    result = _failing_run(
        "strategies",
        "add",
        "--name",
        "Custom Period",
        "--type",
        "WbMaximumClicks",
        "--weekly-spend-limit",
        "900000000",
        "--custom-period-spend-limit",
        "1000000000",
        "--custom-period-start-date",
        "2026-06-01",
        "--custom-period-end-date",
        "2026-06-30",
        "--custom-period-auto-continue",
        "YES",
        "--dry-run",
    )
    assert result.exit_code != 0
    assert (
        "--weekly-spend-limit cannot be combined with --custom-period-* flags"
        in result.output
    )


def test_strategies_add_exploration_budget_payload():
    body = _dry_run(
        "strategies",
        "add",
        "--name",
        "Exploration",
        "--type",
        "AverageCpa",
        "--average-cpa",
        "4000000",
        "--goal-id",
        "123",
        "--minimum-exploration-budget",
        "200000000",
    )
    s = body["params"]["Strategies"][0]
    assert s["AverageCpa"]["ExplorationBudget"] == {
        "MinimumExplorationBudget": 200000000,
        "IsMinimumExplorationBudgetCustom": "YES",
    }


def test_strategies_update_exploration_budget_payload_accepts_zero():
    body = _dry_run(
        "strategies",
        "update",
        "--id",
        "42",
        "--type",
        "MaxProfit",
        "--minimum-exploration-budget",
        "0",
    )
    s = body["params"]["Strategies"][0]
    assert s["MaxProfit"] == {
        "ExplorationBudget": {
            "MinimumExplorationBudget": 0,
            "IsMinimumExplorationBudgetCustom": "YES",
        }
    }


def test_strategies_exploration_budget_requires_type():
    result = _failing_run(
        "strategies",
        "update",
        "--id",
        "42",
        "--minimum-exploration-budget",
        "200000000",
        "--dry-run",
    )
    assert result.exit_code != 0
    assert "Provide --type when setting strategy-specific fields" in result.output


def test_strategies_exploration_budget_rejects_unsupported_type():
    result = _failing_run(
        "strategies",
        "update",
        "--id",
        "42",
        "--type",
        "AverageCpc",
        "--minimum-exploration-budget",
        "200000000",
        "--dry-run",
    )
    assert result.exit_code != 0
    assert (
        "--minimum-exploration-budget is not valid for --type AverageCpc."
        in result.output
    )


def test_strategies_exploration_budget_rejects_value_above_weekly_budget():
    result = _failing_run(
        "strategies",
        "add",
        "--name",
        "Exploration",
        "--type",
        "AverageCpa",
        "--average-cpa",
        "4000000",
        "--goal-id",
        "123",
        "--weekly-spend-limit",
        "100000000",
        "--minimum-exploration-budget",
        "200000000",
        "--dry-run",
    )
    assert result.exit_code != 0
    assert (
        "--minimum-exploration-budget must be less than or equal to "
        "--weekly-spend-limit"
    ) in result.output


def test_strategies_archive_payload():
    body = _dry_run("strategies", "archive", "--id", "10")
    assert body == {
        "method": "archive",
        "params": {"SelectionCriteria": {"Ids": [10]}},
    }


def test_strategies_unarchive_payload():
    body = _dry_run("strategies", "unarchive", "--id", "10")
    assert body == {
        "method": "unarchive",
        "params": {"SelectionCriteria": {"Ids": [10]}},
    }
