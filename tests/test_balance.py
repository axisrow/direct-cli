import json
from unittest.mock import patch

from click.testing import CliRunner

from direct_cli.cli import cli


def test_balance_dry_run_with_logins_emits_v4_request_body():
    result = CliRunner().invoke(cli, ["balance", "--logins", "a,b,c", "--dry-run"])

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "GetClientsUnits",
        "param": {"Logins": ["a", "b", "c"]},
    }


def test_balance_omitted_logins_uses_configured_login():
    result = CliRunner(env={"YANDEX_DIRECT_LOGIN": "client-login"}).invoke(
        cli, ["balance", "--dry-run"]
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "GetClientsUnits",
        "param": {"Logins": ["client-login"]},
    }


def test_balance_omitted_logins_without_login_fails_before_api_call():
    with patch("direct_cli.cli.get_active_profile", return_value=None):
        with patch("direct_cli.commands.balance.create_v4_client") as create_client:
            result = CliRunner(
                env={"YANDEX_DIRECT_TOKEN": "", "YANDEX_DIRECT_LOGIN": ""}
            ).invoke(cli, ["balance"])

    assert result.exit_code != 0
    assert "Provide --logins or configure YANDEX_DIRECT_LOGIN" in result.output
    create_client.assert_not_called()


def test_balance_formats_mocked_v4_response_as_json():
    with patch("direct_cli.commands.balance.create_v4_client") as create_client:
        with patch(
            "direct_cli.commands.balance.call_v4",
            return_value=[{"Login": "a", "Units": 10}],
        ) as call:
            result = CliRunner().invoke(
                cli,
                [
                    "--token",
                    "token",
                    "balance",
                    "--logins",
                    "a",
                ],
            )

    assert result.exit_code == 0
    assert json.loads(result.output) == [{"Login": "a", "Units": 10}]
    create_client.assert_called_once()
    call.assert_called_once_with(
        create_client.return_value, "GetClientsUnits", {"Logins": ["a"]}
    )


def test_balance_formats_mocked_v4_response_as_table():
    with patch("direct_cli.commands.balance.create_v4_client") as create_client:
        with patch(
            "direct_cli.commands.balance.call_v4",
            return_value=[{"Login": "a", "Units": 10}],
        ):
            result = CliRunner().invoke(
                cli,
                [
                    "--token",
                    "token",
                    "balance",
                    "--logins",
                    "a",
                    "--format",
                    "table",
                ],
            )

    assert result.exit_code == 0
    assert "Login" in result.output
    assert "Units" in result.output
    assert "a" in result.output
    create_client.assert_called_once()


def test_balance_help_contains_no_json_input_flag():
    result = CliRunner().invoke(cli, ["balance", "--help"])

    assert result.exit_code == 0
    assert "--json" not in result.output
