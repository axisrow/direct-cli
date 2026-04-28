from unittest.mock import patch

from click.testing import CliRunner

from direct_cli.api import create_v4_client
from direct_cli.cli import cli
from direct_cli.v4 import build_v4_body


def test_create_v4_client_passes_resolved_credentials():
    with patch("direct_cli.api.get_credentials", return_value=("token", "login")):
        with patch("direct_cli.api.YandexDirectV4Live") as client_class:
            create_v4_client(
                token="raw-token",
                login="raw-login",
                profile="prod",
                sandbox=True,
                op_token_ref="op://vault/item/token",
                op_login_ref="op://vault/item/login",
                bw_token_ref="bw-token",
                bw_login_ref="bw-login",
                language="ru",
                retry_if_exceeded_limit=False,
                retries_if_server_error=2,
            )

    client_class.assert_called_once_with(
        access_token="token",
        login="login",
        is_sandbox=True,
        language="ru",
        retry_if_exceeded_limit=False,
        retries_if_server_error=2,
    )


def test_build_v4_body_with_param():
    assert build_v4_body("GetClientsUnits", {"Logins": ["x"]}) == {
        "method": "GetClientsUnits",
        "param": {"Logins": ["x"]},
    }


def test_v4_groups_appear_in_root_help():
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0
    for group in [
        "v4finance",
        "v4account",
        "v4goals",
        "v4events",
        "v4wordstat",
        "v4forecast",
        "v4meta",
    ]:
        assert group in result.output


def test_v4_group_help_does_not_mention_json_input():
    runner = CliRunner()

    for group in [
        "v4finance",
        "v4account",
        "v4goals",
        "v4events",
        "v4wordstat",
        "v4forecast",
        "v4meta",
    ]:
        result = runner.invoke(cli, [group, "--help"])
        assert result.exit_code == 0
        assert "--json" not in result.output
