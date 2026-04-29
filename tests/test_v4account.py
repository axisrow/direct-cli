import json
from typing import Optional
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli.v4_contracts import get_v4_contract


def _invoke(*args: str, env: Optional[dict] = None):
    base_env = {
        "YANDEX_DIRECT_TOKEN": "",
        "YANDEX_DIRECT_LOGIN": "",
        "YANDEX_DIRECT_FINANCE_TOKEN": "",
        "YANDEX_DIRECT_OPERATION_NUM": "",
    }
    if env:
        base_env.update(env)
    with patch("direct_cli.cli.get_active_profile", return_value=None):
        return CliRunner(env=base_env).invoke(cli, list(args))


def test_enable_shared_account_dry_run_uses_login_object():
    result = _invoke(
        "v4account",
        "enable-shared-account",
        "--client-login",
        "client-login",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "EnableSharedAccount",
        "param": {"Login": "client-login"},
    }


def test_account_management_update_dry_run_uses_nested_shared_account_body():
    result = _invoke(
        "v4account",
        "account-management",
        "--action",
        "Update",
        "--account-id",
        "1327944",
        "--day-budget",
        "100.50",
        "--spend-mode",
        "Default",
        "--money-in-sms",
        "Yes",
        "--money-out-sms",
        "No",
        "--paused-by-day-budget-sms",
        "Yes",
        "--sms-time-from",
        "09:15",
        "--sms-time-to",
        "19:45",
        "--email",
        "ops@example.com",
        "--money-warning-value",
        "25",
        "--paused-by-day-budget",
        "No",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "AccountManagement",
        "param": {
            "Action": "Update",
            "Accounts": [
                {
                    "AccountID": 1327944,
                    "AccountDayBudget": {
                        "Amount": 100.5,
                        "SpendMode": "Default",
                    },
                    "SmsNotification": {
                        "MoneyInSms": "Yes",
                        "MoneyOutSms": "No",
                        "PausedByDayBudgetSms": "Yes",
                        "SmsTimeFrom": "09:15",
                        "SmsTimeTo": "19:45",
                    },
                    "EmailNotification": {
                        "Email": "ops@example.com",
                        "MoneyWarningValue": 25,
                        "PausedByDayBudget": "No",
                    },
                }
            ],
        },
    }


@pytest.mark.parametrize(
    "args",
    [
        ("v4account", "enable-shared-account", "--client-login", "client-login"),
        (
            "v4account",
            "account-management",
            "--action",
            "Update",
            "--account-id",
            "1327944",
            "--money-in-sms",
            "Yes",
        ),
    ],
)
def test_v4account_commands_require_dry_run_before_api_call(args):
    with patch("direct_cli.commands.v4account.build_v4_body") as build_body:
        result = _invoke(*args)

    assert result.exit_code != 0
    assert "--dry-run is required" in result.output
    build_body.assert_not_called()


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (
            (
                "v4account",
                "enable-shared-account",
                "--client-login",
                "   ",
                "--dry-run",
            ),
            "--client-login must not be empty",
        ),
        (
            (
                "v4account",
                "account-management",
                "--action",
                "Get",
                "--account-id",
                "1327944",
                "--money-in-sms",
                "Yes",
                "--dry-run",
            ),
            "Only --action Update is supported",
        ),
        (
            (
                "v4account",
                "account-management",
                "--action",
                "Update",
                "--account-id",
                "1327944",
                "--dry-run",
            ),
            "Provide at least one update field",
        ),
        (
            (
                "v4account",
                "account-management",
                "--action",
                "Update",
                "--account-id",
                "1327944",
                "--day-budget",
                "100",
                "--dry-run",
            ),
            "--day-budget and --spend-mode must be provided together",
        ),
        (
            (
                "v4account",
                "account-management",
                "--action",
                "Update",
                "--account-id",
                "1327944",
                "--day-budget",
                "-0",
                "--spend-mode",
                "Default",
                "--dry-run",
            ),
            "--day-budget must be a non-negative amount",
        ),
        (
            (
                "v4account",
                "account-management",
                "--action",
                "Update",
                "--account-id",
                "1327944",
                "--sms-time-from",
                "09:10",
                "--sms-time-to",
                "19:45",
                "--dry-run",
            ),
            "--sms-time-from must use HH:MM",
        ),
        (
            (
                "v4account",
                "account-management",
                "--action",
                "Update",
                "--account-id",
                "1327944",
                "--sms-time-from",
                "09:15",
                "--dry-run",
            ),
            "--sms-time-from and --sms-time-to must be provided together",
        ),
    ],
)
def test_v4account_usage_errors_fail_before_body_build(args, message):
    with patch("direct_cli.commands.v4account.build_v4_body") as build_body:
        result = _invoke(*args)

    assert result.exit_code != 0
    assert message in result.output
    build_body.assert_not_called()


@pytest.mark.parametrize(
    "args",
    [
        (
            "v4account",
            "account-management",
            "--action",
            "Update",
            "--account-id",
            "1327944",
            "--money-in-sms",
            "Maybe",
            "--dry-run",
        ),
        (
            "v4account",
            "account-management",
            "--action",
            "Update",
            "--account-id",
            "1327944",
            "--spend-mode",
            "Fast",
            "--day-budget",
            "100",
            "--dry-run",
        ),
    ],
)
def test_v4account_click_choices_reject_invalid_values(args):
    result = _invoke(*args)

    assert result.exit_code != 0
    assert "Invalid value" in result.output


def test_v4account_missing_required_flags_fail():
    result = _invoke("v4account", "enable-shared-account", "--dry-run")
    assert result.exit_code != 0
    assert "Missing option '--client-login'" in result.output

    result = _invoke("v4account", "account-management", "--action", "Update")
    assert result.exit_code != 0
    assert "Missing option '--account-id'" in result.output


def test_v4account_help_contains_no_json_input_flag():
    for args in [
        ("v4account", "--help"),
        ("v4account", "enable-shared-account", "--help"),
        ("v4account", "account-management", "--help"),
    ]:
        result = _invoke(*args)
        assert result.exit_code == 0
        assert "--json" not in result.output


def test_v4account_commands_declare_v4_contracts():
    commands = cli.commands["v4account"].commands

    assert commands["enable-shared-account"].v4_method == "EnableSharedAccount"
    assert commands["enable-shared-account"].v4_contract == get_v4_contract(
        "EnableSharedAccount"
    )
    assert commands["account-management"].v4_method == "AccountManagement"
    assert commands["account-management"].v4_contract == get_v4_contract(
        "AccountManagement"
    )
