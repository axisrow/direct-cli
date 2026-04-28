import json
from unittest.mock import patch

from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli.v4_contracts import get_v4_contract


def _invoke(*args: str):
    return CliRunner().invoke(cli, list(args))


def test_get_stat_goals_dry_run_uses_campaign_ids_param():
    result = _invoke(
        "v4goals",
        "get-stat-goals",
        "--campaign-ids",
        "1,2,3",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "GetStatGoals",
        "param": {"CampaignIDS": [1, 2, 3]},
    }


def test_get_retargeting_goals_dry_run_uses_campaign_ids_param():
    result = _invoke(
        "v4goals",
        "get-retargeting-goals",
        "--campaign-ids",
        "1,2,3",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "GetRetargetingGoals",
        "param": {"CampaignIDS": [1, 2, 3]},
    }


def test_get_stat_goals_missing_campaign_ids_fails_with_usage_error():
    result = _invoke("v4goals", "get-stat-goals", "--dry-run")

    assert result.exit_code != 0
    assert "Missing option '--campaign-ids'" in result.output


def test_get_retargeting_goals_missing_campaign_ids_fails_with_usage_error():
    result = _invoke("v4goals", "get-retargeting-goals", "--dry-run")

    assert result.exit_code != 0
    assert "Missing option '--campaign-ids'" in result.output


def test_get_stat_goals_empty_campaign_ids_fails_with_usage_error():
    result = _invoke(
        "v4goals",
        "get-stat-goals",
        "--campaign-ids",
        "",
        "--dry-run",
    )

    assert result.exit_code != 0
    assert "--campaign-ids must not be empty" in result.output


def test_get_retargeting_goals_empty_campaign_ids_fails_with_usage_error():
    result = _invoke(
        "v4goals",
        "get-retargeting-goals",
        "--campaign-ids",
        "",
        "--dry-run",
    )

    assert result.exit_code != 0
    assert "--campaign-ids must not be empty" in result.output


def test_get_stat_goals_formats_mocked_response_as_json():
    with patch("direct_cli.commands.v4goals.create_v4_client") as create_client:
        with patch(
            "direct_cli.commands.v4goals.call_v4",
            return_value=[{"CampaignID": 1, "GoalID": 10, "Name": "Lead"}],
        ) as call:
            result = _invoke(
                "--token",
                "token",
                "v4goals",
                "get-stat-goals",
                "--campaign-ids",
                "1",
            )

    assert result.exit_code == 0
    assert json.loads(result.output) == [
        {"CampaignID": 1, "GoalID": 10, "Name": "Lead"}
    ]
    call.assert_called_once_with(
        create_client.return_value,
        "GetStatGoals",
        {"CampaignIDS": [1]},
    )


def test_get_stat_goals_with_login_keeps_method_param_schema():
    with patch("direct_cli.commands.v4goals.create_v4_client") as create_client:
        with patch(
            "direct_cli.commands.v4goals.call_v4",
            return_value=[{"CampaignID": 1, "GoalID": 10, "Name": "Lead"}],
        ) as call:
            result = _invoke(
                "--token",
                "token",
                "--login",
                "client-login",
                "v4goals",
                "get-stat-goals",
                "--campaign-ids",
                "1",
            )

    assert result.exit_code == 0
    create_client.assert_called_once_with(
        token="token",
        login="client-login",
        profile=None,
        sandbox=False,
    )
    call.assert_called_once_with(
        create_client.return_value,
        "GetStatGoals",
        {"CampaignIDS": [1]},
    )


def test_get_retargeting_goals_formats_mocked_response_as_table():
    with patch("direct_cli.commands.v4goals.create_v4_client") as create_client:
        with patch(
            "direct_cli.commands.v4goals.call_v4",
            return_value=[{"CampaignID": 1, "GoalID": 10, "Name": "Lead"}],
        ) as call:
            result = _invoke(
                "--token",
                "token",
                "v4goals",
                "get-retargeting-goals",
                "--campaign-ids",
                "1",
                "--format",
                "table",
            )

    assert result.exit_code == 0
    assert "CampaignID" in result.output
    assert "GoalID" in result.output
    assert "Lead" in result.output
    call.assert_called_once_with(
        create_client.return_value,
        "GetRetargetingGoals",
        {"CampaignIDS": [1]},
    )


def test_v4goals_help_contains_no_json_input_flag():
    for args in [
        ("v4goals", "--help"),
        ("v4goals", "get-stat-goals", "--help"),
        ("v4goals", "get-retargeting-goals", "--help"),
    ]:
        result = _invoke(*args)
        assert result.exit_code == 0
        assert "--json" not in result.output


def test_v4goals_commands_declare_v4_contracts():
    commands = cli.commands["v4goals"].commands

    assert commands["get-stat-goals"].v4_method == "GetStatGoals"
    assert commands["get-stat-goals"].v4_contract == get_v4_contract("GetStatGoals")
    assert commands["get-retargeting-goals"].v4_method == "GetRetargetingGoals"
    assert commands["get-retargeting-goals"].v4_contract == get_v4_contract(
        "GetRetargetingGoals"
    )
