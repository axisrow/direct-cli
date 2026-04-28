import json
from typing import Optional
from unittest.mock import patch

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


def test_get_credit_limits_dry_run_uses_login_list_and_masks_finance_token():
    result = _invoke(
        "v4finance",
        "get-credit-limits",
        "--logins",
        "a,b,c",
        "--finance-token",
        "secret-finance-token",
        "--operation-num",
        "42",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert "secret-finance-token" not in result.output
    assert json.loads(result.output) == {
        "method": "GetCreditLimits",
        "param": ["a", "b", "c"],
        "finance_token": "<redacted>",
        "operation_num": 42,
    }


def test_get_credit_limits_uses_finance_env_fallback_for_dry_run():
    result = _invoke(
        "v4finance",
        "get-credit-limits",
        "--logins",
        "client-login",
        "--dry-run",
        env={
            "YANDEX_DIRECT_FINANCE_TOKEN": "env-finance-token",
            "YANDEX_DIRECT_OPERATION_NUM": "77",
        },
    )

    assert result.exit_code == 0
    assert "env-finance-token" not in result.output
    assert json.loads(result.output) == {
        "method": "GetCreditLimits",
        "param": ["client-login"],
        "finance_token": "<redacted>",
        "operation_num": 77,
    }


def test_get_credit_limits_requires_finance_credentials_before_api_call():
    with patch("direct_cli.commands.v4finance.create_v4_client") as create_client:
        result = _invoke(
            "--token",
            "token",
            "v4finance",
            "get-credit-limits",
            "--logins",
            "client-login",
        )

    assert result.exit_code != 0
    assert "Provide --finance-token and --operation-num" in result.output
    create_client.assert_not_called()


def test_get_credit_limits_rejects_blank_finance_token_before_api_call():
    with patch("direct_cli.commands.v4finance.create_v4_client") as create_client:
        result = _invoke(
            "--token",
            "token",
            "v4finance",
            "get-credit-limits",
            "--logins",
            "client-login",
            "--finance-token",
            "   ",
            "--operation-num",
            "1",
        )

    assert result.exit_code != 0
    assert "Provide --finance-token and --operation-num" in result.output
    create_client.assert_not_called()


def test_get_credit_limits_strips_finance_token_before_api_call():
    with patch("direct_cli.commands.v4finance.create_v4_client") as create_client:
        with patch("direct_cli.commands.v4finance.call_v4", return_value=[]) as call:
            result = _invoke(
                "--token",
                "token",
                "v4finance",
                "get-credit-limits",
                "--logins",
                "client-login",
                "--finance-token",
                " finance-token ",
                "--operation-num",
                "1",
            )

    assert result.exit_code == 0
    create_client.assert_called_once()
    assert create_client.call_args.kwargs["finance_token"] == "finance-token"
    call.assert_called_once()


def test_get_credit_limits_empty_logins_fails_before_api_call():
    with patch("direct_cli.commands.v4finance.create_v4_client") as create_client:
        result = _invoke(
            "--token",
            "token",
            "v4finance",
            "get-credit-limits",
            "--logins",
            ",",
            "--finance-token",
            "finance-token",
            "--operation-num",
            "1",
        )

    assert result.exit_code != 0
    assert "--logins must not be empty" in result.output
    create_client.assert_not_called()


def test_get_credit_limits_formats_mocked_response_as_json():
    with patch("direct_cli.commands.v4finance.create_v4_client") as create_client:
        with patch(
            "direct_cli.commands.v4finance.call_v4",
            return_value=[{"Login": "client-login", "CreditLimit": 1000}],
        ) as call:
            result = _invoke(
                "--token",
                "token",
                "--login",
                "agency-login",
                "v4finance",
                "get-credit-limits",
                "--logins",
                "client-login",
                "--finance-token",
                "finance-token",
                "--operation-num",
                "42",
            )

    assert result.exit_code == 0
    assert json.loads(result.output) == [
        {"Login": "client-login", "CreditLimit": 1000}
    ]
    create_client.assert_called_once_with(
        token="token",
        login="agency-login",
        profile=None,
        sandbox=False,
        finance_token="finance-token",
        operation_num=42,
    )
    call.assert_called_once_with(
        create_client.return_value,
        "GetCreditLimits",
        ["client-login"],
    )


def test_v4finance_help_contains_no_json_input_flag():
    for args in [
        ("v4finance", "--help"),
        ("v4finance", "get-credit-limits", "--help"),
    ]:
        result = _invoke(*args)
        assert result.exit_code == 0
        assert "--json" not in result.output


def test_v4finance_command_declares_v4_contract():
    command = cli.commands["v4finance"].commands["get-credit-limits"]

    assert command.v4_method == "GetCreditLimits"
    assert command.v4_contract == get_v4_contract("GetCreditLimits")
