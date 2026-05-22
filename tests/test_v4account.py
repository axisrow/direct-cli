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
        "YANDEX_DIRECT_MASTER_TOKEN": "",
        "YANDEX_DIRECT_OPERATION_NUM": "",
        "YANDEX_DIRECT_FINANCE_LOGIN": "",
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
    with patch("direct_cli.commands.v4account.create_v4_client") as create_client:
        result = _invoke(*args)

    assert result.exit_code != 0
    assert "--dry-run is required unless --sandbox is set" in result.output
    create_client.assert_not_called()


def test_enable_shared_account_sandbox_calls_v4_api_without_dry_run():
    with patch("direct_cli.commands.v4account.create_v4_client") as create_client:
        with patch(
            "direct_cli.commands.v4account.call_v4",
            return_value={"result": "ok"},
        ) as call:
            result = _invoke(
                "--sandbox",
                "--token",
                "token",
                "--login",
                "client-login",
                "v4account",
                "enable-shared-account",
                "--client-login",
                "client-login",
            )

    assert result.exit_code == 0
    assert json.loads(result.output) == {"result": "ok"}
    create_client.assert_called_once_with(
        token="token",
        login="client-login",
        profile=None,
        sandbox=True,
    )
    call.assert_called_once_with(
        create_client.return_value,
        "EnableSharedAccount",
        {"Login": "client-login"},
    )


def test_account_management_sandbox_calls_v4_api_without_dry_run():
    with patch("direct_cli.commands.v4account.create_v4_client") as create_client:
        with patch(
            "direct_cli.commands.v4account.call_v4",
            return_value={"ActionsResult": [{"AccountID": 1327944}]},
        ) as call:
            result = _invoke(
                "--sandbox",
                "--token",
                "token",
                "--login",
                "client-login",
                "v4account",
                "account-management",
                "--action",
                "Update",
                "--account-id",
                "1327944",
                "--money-in-sms",
                "No",
            )

    assert result.exit_code == 0
    assert json.loads(result.output) == {"ActionsResult": [{"AccountID": 1327944}]}
    create_client.assert_called_once_with(
        token="token",
        login="client-login",
        profile=None,
        sandbox=True,
    )
    call.assert_called_once_with(
        create_client.return_value,
        "AccountManagement",
        {
            "Action": "Update",
            "Accounts": [
                {
                    "AccountID": 1327944,
                    "SmsNotification": {"MoneyInSms": "No"},
                }
            ],
        },
    )


def test_account_management_sandbox_formats_mocked_response_as_table():
    with patch("direct_cli.commands.v4account.create_v4_client"):
        with patch(
            "direct_cli.commands.v4account.call_v4",
            return_value=[{"AccountID": 1327944, "Status": "Updated"}],
        ):
            result = _invoke(
                "--sandbox",
                "--token",
                "token",
                "v4account",
                "account-management",
                "--action",
                "Update",
                "--account-id",
                "1327944",
                "--money-in-sms",
                "No",
                "--format",
                "table",
            )

    assert result.exit_code == 0
    assert "AccountID" in result.output
    assert "Status" in result.output
    assert "1327944" in result.output


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
                "Bogus",
                "--dry-run",
            ),
            "--action must be one of: Get, Update, Deposit, Invoice, TransferMoney",
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

    # --action is required for account-management.
    result = _invoke("v4account", "account-management", "--dry-run")
    assert result.exit_code != 0
    assert "Missing option '--action'" in result.output

    # --account-id is required for Update specifically.
    result = _invoke(
        "v4account", "account-management", "--action", "Update", "--dry-run"
    )
    assert result.exit_code != 0
    assert "--account-id is required for --action Update" in result.output


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


# ─── AccountManagement Get ────────────────────────────────────────────────


def test_account_management_get_dry_run_omits_selection_criteria_when_no_filters():
    result = _invoke(
        "v4account", "account-management", "--action", "Get", "--dry-run"
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "AccountManagement",
        "param": {"Action": "Get"},
    }


def test_account_management_get_dry_run_with_logins_only():
    result = _invoke(
        "v4account",
        "account-management",
        "--action",
        "Get",
        "--logins",
        "client-a,client-b",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "AccountManagement",
        "param": {
            "Action": "Get",
            "SelectionCriteria": {"Logins": ["client-a", "client-b"]},
        },
    }


def test_account_management_get_dry_run_with_account_ids_only():
    result = _invoke(
        "v4account",
        "account-management",
        "--action",
        "Get",
        "--account-ids",
        "1,2,3",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "AccountManagement",
        "param": {
            "Action": "Get",
            "SelectionCriteria": {"AccountIDS": [1, 2, 3]},
        },
    }


def test_account_management_get_dry_run_with_both_filters():
    result = _invoke(
        "v4account",
        "account-management",
        "--action",
        "Get",
        "--logins",
        "client-a",
        "--account-ids",
        "1,2",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "AccountManagement",
        "param": {
            "Action": "Get",
            "SelectionCriteria": {
                "Logins": ["client-a"],
                "AccountIDS": [1, 2],
            },
        },
    }


def test_account_management_get_rejects_update_only_flag():
    with patch("direct_cli.commands.v4account.build_v4_body") as build_body:
        result = _invoke(
            "v4account",
            "account-management",
            "--action",
            "Get",
            "--day-budget",
            "100",
            "--dry-run",
        )

    assert result.exit_code != 0
    assert "--day-budget not valid for --action Get" in result.output
    build_body.assert_not_called()


def test_account_management_get_does_not_require_dry_run_or_sandbox():
    with patch("direct_cli.commands.v4account.create_v4_client") as create_client:
        with patch(
            "direct_cli.commands.v4account.call_v4",
            return_value={"Accounts": []},
        ):
            result = _invoke(
                "--token",
                "token",
                "--login",
                "agency-login",
                "v4account",
                "account-management",
                "--action",
                "Get",
            )

    assert result.exit_code == 0
    create_client.assert_called_once()


def test_account_management_get_caps_logins_at_50():
    logins = ",".join(f"login-{i}" for i in range(51))
    with patch("direct_cli.commands.v4account.build_v4_body") as build_body:
        result = _invoke(
            "v4account",
            "account-management",
            "--action",
            "Get",
            "--logins",
            logins,
            "--dry-run",
        )

    assert result.exit_code != 0
    assert "--logins accepts at most 50 entries" in result.output
    build_body.assert_not_called()


def test_account_management_get_caps_account_ids_at_100():
    ids = ",".join(str(i) for i in range(1, 102))
    with patch("direct_cli.commands.v4account.build_v4_body") as build_body:
        result = _invoke(
            "v4account",
            "account-management",
            "--action",
            "Get",
            "--account-ids",
            ids,
            "--dry-run",
        )

    assert result.exit_code != 0
    assert "--account-ids accepts at most 100 entries" in result.output
    build_body.assert_not_called()


# ─── AccountManagement Update — additional misuse cases ───────────────────


def test_account_management_update_rejects_get_flag():
    with patch("direct_cli.commands.v4account.build_v4_body") as build_body:
        result = _invoke(
            "v4account",
            "account-management",
            "--action",
            "Update",
            "--account-id",
            "1",
            "--logins",
            "a",
            "--money-in-sms",
            "No",
            "--dry-run",
        )

    assert result.exit_code != 0
    assert "--logins not valid for --action Update" in result.output
    build_body.assert_not_called()


# ─── AccountManagement Deposit ────────────────────────────────────────────


def test_account_management_deposit_dry_run_masks_finance_token():
    result = _invoke(
        "v4account",
        "account-management",
        "--action",
        "Deposit",
        "--payment",
        "1327944=100.50",
        "--currency",
        "RUB",
        "--finance-token",
        "secret-finance-token",
        "--operation-num",
        "42",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert "secret-finance-token" not in result.output
    assert json.loads(result.output) == {
        "method": "AccountManagement",
        "param": {
            "Action": "Deposit",
            "Payments": [
                {"AccountID": 1327944, "Amount": 100.5, "Currency": "RUB"}
            ],
        },
        "finance_token": "<redacted>",
        "operation_num": 42,
    }


def test_account_management_deposit_with_origin_and_contract():
    result = _invoke(
        "v4account",
        "account-management",
        "--action",
        "Deposit",
        "--payment",
        "1=10.00",
        "--payment",
        "2=20.00",
        "--currency",
        "USD",
        "--origin",
        "Overdraft",
        "--contract",
        "CONTRACT-123",
        "--finance-token",
        "tok",
        "--operation-num",
        "1",
        "--dry-run",
    )

    assert result.exit_code == 0
    body = json.loads(result.output)
    assert body["param"]["Action"] == "Deposit"
    for item in body["param"]["Payments"]:
        assert item["Origin"] == "Overdraft"
        assert item["Contract"] == "CONTRACT-123"


def test_account_management_deposit_requires_dry_run_or_sandbox():
    with patch("direct_cli.commands.v4account.create_v4_client") as create_client:
        result = _invoke(
            "--token",
            "token",
            "v4account",
            "account-management",
            "--action",
            "Deposit",
            "--payment",
            "1=10",
            "--currency",
            "RUB",
            "--finance-token",
            "tok",
            "--operation-num",
            "1",
        )

    assert result.exit_code != 0
    assert "--dry-run is required unless --sandbox is set" in result.output
    create_client.assert_not_called()


def test_account_management_deposit_requires_finance_credentials():
    with patch("direct_cli.commands.v4account.build_v4_body") as build_body:
        result = _invoke(
            "v4account",
            "account-management",
            "--action",
            "Deposit",
            "--payment",
            "1=10",
            "--currency",
            "RUB",
            "--dry-run",
        )

    assert result.exit_code != 0
    assert "Provide --finance-token and --operation-num" in result.output
    build_body.assert_not_called()


def test_account_management_deposit_requires_currency():
    with patch("direct_cli.commands.v4account.build_v4_body") as build_body:
        result = _invoke(
            "v4account",
            "account-management",
            "--action",
            "Deposit",
            "--payment",
            "1=10",
            "--finance-token",
            "tok",
            "--operation-num",
            "1",
            "--dry-run",
        )

    assert result.exit_code != 0
    assert "--currency is required for --action Deposit" in result.output
    build_body.assert_not_called()


def test_account_management_deposit_rejects_duplicate_account_ids():
    with patch("direct_cli.commands.v4account.build_v4_body") as build_body:
        result = _invoke(
            "v4account",
            "account-management",
            "--action",
            "Deposit",
            "--payment",
            "1=10",
            "--payment",
            "1=20",
            "--currency",
            "RUB",
            "--finance-token",
            "tok",
            "--operation-num",
            "1",
            "--dry-run",
        )

    assert result.exit_code != 0
    assert "--payment account IDs must be unique" in result.output
    build_body.assert_not_called()


# ─── AccountManagement Invoice ────────────────────────────────────────────


def test_account_management_invoice_dry_run_uses_payments_without_origin():
    result = _invoke(
        "v4account",
        "account-management",
        "--action",
        "Invoice",
        "--payment",
        "1=50.00",
        "--currency",
        "EUR",
        "--finance-token",
        "tok",
        "--operation-num",
        "1",
        "--dry-run",
    )

    assert result.exit_code == 0
    body = json.loads(result.output)
    assert body["param"] == {
        "Action": "Invoice",
        "Payments": [{"AccountID": 1, "Amount": 50.0, "Currency": "EUR"}],
    }
    assert "Origin" not in body["param"]["Payments"][0]
    assert "Contract" not in body["param"]["Payments"][0]


def test_account_management_invoice_rejects_origin_flag():
    with patch("direct_cli.commands.v4account.build_v4_body") as build_body:
        result = _invoke(
            "v4account",
            "account-management",
            "--action",
            "Invoice",
            "--payment",
            "1=10",
            "--currency",
            "RUB",
            "--origin",
            "Overdraft",
            "--finance-token",
            "tok",
            "--operation-num",
            "1",
            "--dry-run",
        )

    assert result.exit_code != 0
    assert "--origin not valid for --action Invoice" in result.output
    build_body.assert_not_called()


# ─── AccountManagement TransferMoney ──────────────────────────────────────


def test_account_management_transfer_dry_run_uses_single_transfer():
    result = _invoke(
        "v4account",
        "account-management",
        "--action",
        "TransferMoney",
        "--from-account-id",
        "10",
        "--to-account-id",
        "20",
        "--amount",
        "50.00",
        "--currency",
        "RUB",
        "--finance-token",
        "tok",
        "--operation-num",
        "1",
        "--dry-run",
    )

    assert result.exit_code == 0
    body = json.loads(result.output)
    assert body["param"] == {
        "Action": "TransferMoney",
        "Transfers": [
            {
                "FromAccountID": 10,
                "ToAccountID": 20,
                "Amount": 50.0,
                "Currency": "RUB",
            }
        ],
    }


def test_account_management_transfer_rejects_equal_from_to():
    with patch("direct_cli.commands.v4account.build_v4_body") as build_body:
        result = _invoke(
            "v4account",
            "account-management",
            "--action",
            "TransferMoney",
            "--from-account-id",
            "10",
            "--to-account-id",
            "10",
            "--amount",
            "50",
            "--currency",
            "RUB",
            "--finance-token",
            "tok",
            "--operation-num",
            "1",
            "--dry-run",
        )

    assert result.exit_code != 0
    assert "--from-account-id and --to-account-id must differ" in result.output
    build_body.assert_not_called()


def test_account_management_transfer_requires_currency():
    with patch("direct_cli.commands.v4account.build_v4_body") as build_body:
        result = _invoke(
            "v4account",
            "account-management",
            "--action",
            "TransferMoney",
            "--from-account-id",
            "10",
            "--to-account-id",
            "20",
            "--amount",
            "50",
            "--finance-token",
            "tok",
            "--operation-num",
            "1",
            "--dry-run",
        )

    assert result.exit_code != 0
    assert "--currency is required for --action TransferMoney" in result.output
    build_body.assert_not_called()


def test_account_management_transfer_requires_all_three_flags():
    with patch("direct_cli.commands.v4account.build_v4_body") as build_body:
        result = _invoke(
            "v4account",
            "account-management",
            "--action",
            "TransferMoney",
            "--from-account-id",
            "10",
            "--currency",
            "RUB",
            "--finance-token",
            "tok",
            "--operation-num",
            "1",
            "--dry-run",
        )

    assert result.exit_code != 0
    assert (
        "--from-account-id, --to-account-id, and --amount are required"
        in result.output
    )
    build_body.assert_not_called()


# ─── Allow-list integrity ─────────────────────────────────────────────────


def test_account_management_options_are_all_in_allow_list():
    """Every Click option on account-management must appear in some allow-list."""
    from direct_cli.commands.v4account import (
        _ACCOUNT_ACTION_ALLOWED_FLAGS,
        _COMMON_PARAMS,
    )

    command = cli.commands["v4account"].commands["account-management"]
    option_param_names = {
        opt.name
        for opt in command.params
        if opt.name not in {"format"}  # 'format' is the dest for --format
    }
    option_param_names.add("output_format")  # explicit dest

    covered = set(_COMMON_PARAMS)
    for allowed in _ACCOUNT_ACTION_ALLOWED_FLAGS.values():
        covered |= allowed

    uncovered = option_param_names - covered
    assert not uncovered, (
        f"account-management options not in any allow-list: {sorted(uncovered)}"
    )


# ─── Envvar-vs-CLI source distinction (regression for PR #234 review) ────


def test_account_management_get_ignores_finance_envvars():
    """Finance envvars exported in the shell must not break --action Get."""
    result = _invoke(
        "v4account",
        "account-management",
        "--action",
        "Get",
        "--dry-run",
        env={
            "YANDEX_DIRECT_FINANCE_TOKEN": "env-finance-token",
            "YANDEX_DIRECT_MASTER_TOKEN": "env-master-token",
            "YANDEX_DIRECT_OPERATION_NUM": "42",
            "YANDEX_DIRECT_FINANCE_LOGIN": "env-login",
        },
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "method": "AccountManagement",
        "param": {"Action": "Get"},
    }


def test_account_management_update_ignores_finance_envvars():
    """Finance envvars exported in the shell must not break --action Update."""
    result = _invoke(
        "v4account",
        "account-management",
        "--action",
        "Update",
        "--account-id",
        "1",
        "--money-in-sms",
        "No",
        "--dry-run",
        env={
            "YANDEX_DIRECT_FINANCE_TOKEN": "env-finance-token",
            "YANDEX_DIRECT_MASTER_TOKEN": "env-master-token",
            "YANDEX_DIRECT_OPERATION_NUM": "42",
            "YANDEX_DIRECT_FINANCE_LOGIN": "env-login",
        },
    )

    assert result.exit_code == 0, result.output


def test_account_management_deposit_misleading_amount_message_uses_payment_label():
    """A bad amount in --payment must point at --payment, not --amount."""
    with patch("direct_cli.commands.v4account.build_v4_body") as build_body:
        result = _invoke(
            "v4account",
            "account-management",
            "--action",
            "Deposit",
            "--payment",
            "1=bad",
            "--currency",
            "RUB",
            "--finance-token",
            "tok",
            "--operation-num",
            "1",
            "--dry-run",
        )

    assert result.exit_code != 0
    assert "--payment" in result.output
    assert "--amount" not in result.output
    build_body.assert_not_called()
