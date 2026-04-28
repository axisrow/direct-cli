import json
from typing import Optional
from unittest.mock import patch

import pytest
from click import UsageError
from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli.v4_contracts import get_v4_contract
from direct_cli.v4.money import parse_v4_money_sum


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


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1", 1.0),
        ("100.50", 100.5),
    ],
)
def test_parse_v4_money_sum_accepts_positive_decimal_amounts(value, expected):
    assert parse_v4_money_sum(value) == expected


@pytest.mark.parametrize(
    "value",
    ["", " ", "0", "0.00", "000", "-1", "1.", ".50", "1.234", "abc", "NaN", "inf"],
)
def test_parse_v4_money_sum_rejects_invalid_amounts(value):
    with pytest.raises(UsageError):
        parse_v4_money_sum(value)


def test_transfer_money_dry_run_uses_campaign_arrays_and_masks_finance_token():
    result = _invoke(
        "v4finance",
        "transfer-money",
        "--from-campaign-id",
        "123",
        "--to-campaign-id",
        "456",
        "--amount",
        "100.50",
        "--finance-token",
        "secret-finance-token",
        "--operation-num",
        "42",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert "secret-finance-token" not in result.output
    assert json.loads(result.output) == {
        "method": "TransferMoney",
        "param": {
            "FromCampaigns": [{"CampaignID": 123, "Sum": 100.5}],
            "ToCampaigns": [{"CampaignID": 456, "Sum": 100.5}],
        },
        "finance_token": "<redacted>",
        "operation_num": 42,
    }


def test_pay_campaigns_dry_run_uses_payment_object_and_masks_finance_token():
    result = _invoke(
        "v4finance",
        "pay-campaigns",
        "--campaign-id",
        "123",
        "--amount",
        "100.50",
        "--contract-id",
        "contract-id",
        "--pay-method",
        "CREDIT",
        "--finance-token",
        "secret-finance-token",
        "--operation-num",
        "42",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert "secret-finance-token" not in result.output
    assert json.loads(result.output) == {
        "method": "PayCampaigns",
        "param": {
            "Payments": [{"CampaignID": 123, "Sum": 100.5}],
            "ContractID": "contract-id",
            "PayMethod": "CREDIT",
        },
        "finance_token": "<redacted>",
        "operation_num": 42,
    }


def test_transfer_money_uses_finance_env_fallback_for_dry_run():
    result = _invoke(
        "v4finance",
        "transfer-money",
        "--from-campaign-id",
        "123",
        "--to-campaign-id",
        "456",
        "--amount",
        "100.50",
        "--dry-run",
        env={
            "YANDEX_DIRECT_FINANCE_TOKEN": "env-finance-token",
            "YANDEX_DIRECT_OPERATION_NUM": "77",
        },
    )

    assert result.exit_code == 0
    assert "env-finance-token" not in result.output
    assert json.loads(result.output)["operation_num"] == 77


def test_v4finance_money_commands_require_dry_run_before_api_call():
    with patch("direct_cli.commands.v4finance.create_v4_client") as create_client:
        result = _invoke(
            "--token",
            "token",
            "v4finance",
            "transfer-money",
            "--from-campaign-id",
            "123",
            "--to-campaign-id",
            "456",
            "--amount",
            "100.50",
            "--finance-token",
            "finance-token",
            "--operation-num",
            "42",
        )

    assert result.exit_code != 0
    assert "--dry-run is required" in result.output
    create_client.assert_not_called()


def test_v4finance_money_commands_require_finance_credentials_before_api_call():
    with patch("direct_cli.commands.v4finance.create_v4_client") as create_client:
        result = _invoke(
            "--token",
            "token",
            "v4finance",
            "pay-campaigns",
            "--campaign-id",
            "123",
            "--amount",
            "100.50",
            "--contract-id",
            "contract-id",
            "--pay-method",
            "CREDIT",
            "--dry-run",
        )

    assert result.exit_code != 0
    assert "Provide --finance-token and --operation-num" in result.output
    create_client.assert_not_called()


def test_v4finance_money_commands_validate_amount_before_api_call():
    with patch("direct_cli.commands.v4finance.create_v4_client") as create_client:
        result = _invoke(
            "v4finance",
            "transfer-money",
            "--from-campaign-id",
            "123",
            "--to-campaign-id",
            "456",
            "--amount",
            "0",
            "--finance-token",
            "finance-token",
            "--operation-num",
            "42",
            "--dry-run",
        )

    assert result.exit_code != 0
    assert "--amount must be greater than zero" in result.output
    create_client.assert_not_called()


def test_v4finance_money_commands_reject_blank_string_options():
    result = _invoke(
        "v4finance",
        "pay-campaigns",
        "--campaign-id",
        "123",
        "--amount",
        "100.50",
        "--contract-id",
        "contract-id",
        "--pay-method",
        "   ",
        "--finance-token",
        "finance-token",
        "--operation-num",
        "42",
        "--dry-run",
    )

    assert result.exit_code != 0
    assert "--pay-method must not be empty" in result.output


def test_check_payment_is_not_registered_without_official_docs():
    assert "check-payment" not in cli.commands["v4finance"].commands


def test_v4finance_money_help_contains_no_json_input_flag():
    for args in [
        ("v4finance", "transfer-money", "--help"),
        ("v4finance", "pay-campaigns", "--help"),
    ]:
        result = _invoke(*args)
        assert result.exit_code == 0
        assert "--json" not in result.output


def test_v4finance_money_commands_declare_v4_contracts():
    commands = cli.commands["v4finance"].commands

    assert commands["transfer-money"].v4_method == "TransferMoney"
    assert commands["transfer-money"].v4_contract == get_v4_contract("TransferMoney")
    assert commands["pay-campaigns"].v4_method == "PayCampaigns"
    assert commands["pay-campaigns"].v4_contract == get_v4_contract("PayCampaigns")
