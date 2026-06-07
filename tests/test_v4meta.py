import json
from unittest.mock import patch

from click.testing import CliRunner

from direct_cli.cli import cli

META_COMMANDS = {
    "ping-api": "PingAPI",
    "ping-api-x": "PingAPI_X",
    "get-version": "GetVersion",
    "get-available-versions": "GetAvailableVersions",
}


def _invoke(*args: str):
    env = {"YANDEX_DIRECT_TOKEN": "", "YANDEX_DIRECT_LOGIN": ""}
    with patch("direct_cli.cli.get_active_profile", return_value=None):
        return CliRunner(env=env).invoke(cli, list(args))


def test_v4meta_help_lists_all_meta_commands():
    result = _invoke("v4meta", "--help")

    assert result.exit_code == 0
    for command in META_COMMANDS:
        assert command in result.output


def test_v4meta_help_contains_no_json_input_flag():
    for command in (None, *META_COMMANDS):
        args = (
            ["v4meta", "--help"] if command is None else ["v4meta", command, "--help"]
        )
        result = _invoke(*args)

        assert result.exit_code == 0
        assert "--json" not in result.output


def test_v4meta_dry_runs_emit_no_param_body():
    for command, method in META_COMMANDS.items():
        result = _invoke("v4meta", command, "--dry-run")

        assert result.exit_code == 0
        assert json.loads(result.output) == {"method": method}


def test_v4meta_commands_execute_via_v4_client():
    for command, method in META_COMMANDS.items():
        response = {"ok": method}
        with patch("direct_cli.v4.emit.create_v4_client") as create_client:
            with patch("direct_cli.v4.emit.call_v4", return_value=response) as call:
                result = _invoke(
                    "--token",
                    "token",
                    "--login",
                    "client-login",
                    "v4meta",
                    command,
                )

        assert result.exit_code == 0
        assert json.loads(result.output) == response
        create_client.assert_called_once_with(
            token="token",
            login="client-login",
            profile=None,
            sandbox=False,
        )
        call.assert_called_once_with(create_client.return_value, method, None)
