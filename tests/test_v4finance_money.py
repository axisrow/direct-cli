import json
from typing import Optional
from unittest.mock import patch

import pytest
from click import UsageError
from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli.v4_contracts import get_v4_contract
from direct_cli.v4.money import (
    build_finance_token,
    normalize_finance_login,
    parse_v4_money_sum,
)


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


def test_build_finance_token_uses_docs_formula_and_normalized_login():
    token = build_finance_token(
        "master-token",
        42,
        "TransferMoney",
        " Agency-Login ",
    )

    assert normalize_finance_login(" Agency-Login ") == "agency-login"
    assert token == "26a042849d1c395595b87a4248f34489788ab4c83d23bdabb4fa128042a0904c"


def test_build_finance_token_rejects_invalid_operation_num():
    with pytest.raises(UsageError):
        build_finance_token("master-token", 0, "TransferMoney", "agency-login")


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
            "FromCampaigns": [{"CampaignID": 123, "Sum": 100.5, "Currency": "RUB"}],
            "ToCampaigns": [{"CampaignID": 456, "Sum": 100.5, "Currency": "RUB"}],
        },
        "finance_token": "<redacted>",
        "operation_num": 42,
    }


def test_pay_campaigns_dry_run_uses_payment_object_and_masks_finance_token():
    result = _invoke(
        "v4finance",
        "pay-campaigns",
        "--campaign-ids",
        "123,456",
        "--amount",
        "100.50",
        "--contract-id",
        "contract-id",
        "--pay-method",
        "Bank",
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
            "Payments": [
                {"CampaignID": 123, "Sum": 100.5, "Currency": "RUB"},
                {"CampaignID": 456, "Sum": 100.5, "Currency": "RUB"},
            ],
            "ContractID": "contract-id",
            "PayMethod": "Bank",
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


def test_transfer_money_can_compute_finance_token_from_master_token():
    with patch("direct_cli.commands.v4finance.build_finance_token") as build_token:
        build_token.return_value = "computed-finance-token"
        result = _invoke(
            "v4finance",
            "transfer-money",
            "--from-campaign-id",
            "123",
            "--to-campaign-id",
            "456",
            "--amount",
            "100.50",
            "--master-token",
            "master-token",
            "--operation-num",
            "42",
            "--finance-login",
            "Agency-Login",
            "--dry-run",
        )

    assert result.exit_code == 0
    assert "computed-finance-token" not in result.output
    build_token.assert_called_once_with(
        "master-token",
        42,
        "TransferMoney",
        "Agency-Login",
    )


def test_finance_credentials_reject_token_and_master_token_conflict():
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
        "finance-token",
        "--master-token",
        "master-token",
        "--operation-num",
        "42",
        "--dry-run",
    )

    assert result.exit_code != 0
    assert "Use either --finance-token or --master-token" in result.output


def test_master_token_requires_finance_login_without_login_fallback():
    result = _invoke(
        "v4finance",
        "transfer-money",
        "--from-campaign-id",
        "123",
        "--to-campaign-id",
        "456",
        "--amount",
        "100.50",
        "--master-token",
        "master-token",
        "--operation-num",
        "42",
        "--dry-run",
    )

    assert result.exit_code != 0
    assert "Provide --finance-login" in result.output


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
            "--campaign-ids",
            "123",
            "--amount",
            "100.50",
            "--contract-id",
            "contract-id",
            "--pay-method",
            "Bank",
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
        "--campaign-ids",
        "123",
        "--amount",
        "100.50",
        "--contract-id",
        "contract-id",
        "--pay-method",
        "Invalid",
        "--finance-token",
        "finance-token",
        "--operation-num",
        "42",
        "--dry-run",
    )

    assert result.exit_code != 0
    assert "Invalid value for '--pay-method'" in result.output


def test_pay_campaigns_requires_contract_for_bank():
    result = _invoke(
        "v4finance",
        "pay-campaigns",
        "--campaign-ids",
        "123",
        "--amount",
        "100.50",
        "--pay-method",
        "Bank",
        "--finance-token",
        "finance-token",
        "--operation-num",
        "42",
        "--dry-run",
    )

    assert result.exit_code != 0
    assert "--contract-id is required when --pay-method Bank" in result.output


def test_pay_campaigns_rejects_non_positive_campaign_ids():
    result = _invoke(
        "v4finance",
        "pay-campaigns",
        "--campaign-ids",
        "0,-1",
        "--amount",
        "100.50",
        "--pay-method",
        "Overdraft",
        "--finance-token",
        "finance-token",
        "--operation-num",
        "42",
        "--dry-run",
    )

    assert result.exit_code != 0
    assert "--campaign-ids must contain only positive integers" in result.output


def test_pay_campaigns_allows_overdraft_without_contract():
    result = _invoke(
        "v4finance",
        "pay-campaigns",
        "--campaign-ids",
        "123",
        "--amount",
        "100.50",
        "--pay-method",
        "Overdraft",
        "--currency",
        "usd",
        "--finance-token",
        "finance-token",
        "--operation-num",
        "42",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["param"] == {
        "Payments": [{"CampaignID": 123, "Sum": 100.5, "Currency": "USD"}],
        "PayMethod": "Overdraft",
    }


def test_check_payment_dry_run_uses_custom_transaction_id_object():
    result = _invoke(
        "v4finance",
        "check-payment",
        "--custom-transaction-id",
        "A123456789012345678901234567890B",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "CheckPayment",
        "param": {"CustomTransactionID": "A123456789012345678901234567890B"},
    }


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "short",
        "A123456789012345678901234567890",
        "A123456789012345678901234567890BC",
        "A12345678901234567890123456789-B",
        "A12345678901234567890123456789 Б",
    ],
)
def test_check_payment_rejects_invalid_custom_transaction_id_before_api_call(value):
    with patch("direct_cli.commands.v4finance.create_v4_client") as create_client:
        result = _invoke(
            "v4finance",
            "check-payment",
            "--custom-transaction-id",
            value,
        )

    assert result.exit_code != 0
    assert "--custom-transaction-id must be exactly 32 latin letters or digits" in (
        result.output
    )
    create_client.assert_not_called()


def test_check_payment_formats_mocked_response_as_json():
    with patch("direct_cli.commands.v4finance.create_v4_client") as create_client:
        with patch(
            "direct_cli.commands.v4finance.call_v4",
            return_value={"Status": "Done"},
        ) as call:
            result = _invoke(
                "--token",
                "token",
                "--login",
                "client-login",
                "v4finance",
                "check-payment",
                "--custom-transaction-id",
                "A123456789012345678901234567890B",
            )

    assert result.exit_code == 0
    assert json.loads(result.output) == {"Status": "Done"}
    create_client.assert_called_once_with(
        token="token",
        login="client-login",
        profile=None,
        sandbox=False,
    )
    call.assert_called_once_with(
        create_client.return_value,
        "CheckPayment",
        {"CustomTransactionID": "A123456789012345678901234567890B"},
    )


def test_v4finance_money_help_contains_no_json_input_flag():
    for args in [
        ("v4finance", "transfer-money", "--help"),
        ("v4finance", "pay-campaigns", "--help"),
        ("v4finance", "check-payment", "--help"),
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
    assert commands["check-payment"].v4_method == "CheckPayment"
    assert commands["check-payment"].v4_contract == get_v4_contract("CheckPayment")
