"""Tests for Bitwarden integration in auth module"""

import subprocess
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from direct_cli.auth import bw_read, get_credentials
from direct_cli.cli import cli


class TestBwRead:
    """Tests for bw_read function"""

    @patch("direct_cli.auth.subprocess.run")
    @patch("direct_cli.auth.shutil.which", return_value="/usr/local/bin/bw")
    def test_bw_read_success(self, mock_which, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="my-secret-token\n", stderr=""
        )
        result = bw_read("yandex-direct-item")
        assert result == "my-secret-token"
        mock_run.assert_called_once_with(
            ["/usr/local/bin/bw", "get", "password", "yandex-direct-item"],
            capture_output=True,
            text=True,
            timeout=10,
        )

    @patch("direct_cli.auth.subprocess.run")
    @patch("direct_cli.auth.shutil.which", return_value="/usr/local/bin/bw")
    def test_bw_read_custom_field(self, mock_which, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="my-username\n", stderr=""
        )
        result = bw_read("yandex-direct-item", field="username")
        assert result == "my-username"
        mock_run.assert_called_once_with(
            ["/usr/local/bin/bw", "get", "username", "yandex-direct-item"],
            capture_output=True,
            text=True,
            timeout=10,
        )

    @patch("direct_cli.auth.shutil.which", return_value=None)
    def test_bw_read_not_found(self, mock_which):
        with pytest.raises(RuntimeError, match="Bitwarden CLI .* not found"):
            bw_read("yandex-direct-item")

    @patch("direct_cli.auth.subprocess.run")
    @patch("direct_cli.auth.shutil.which", return_value="/usr/local/bin/bw")
    def test_bw_read_fails(self, mock_which, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="Not found."
        )
        with pytest.raises(RuntimeError, match="Not found."):
            bw_read("yandex-direct-item")

    @patch("direct_cli.auth.subprocess.run")
    @patch("direct_cli.auth.shutil.which", return_value="/usr/local/bin/bw")
    def test_bw_read_vault_locked(self, mock_which, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="Vault is locked."
        )
        with pytest.raises(
            RuntimeError, match=r"eval \$\(bw unlock\)"
        ):
            bw_read("yandex-direct-item")

    @patch("direct_cli.auth.subprocess.run")
    @patch("direct_cli.auth.shutil.which", return_value="/usr/local/bin/bw")
    def test_bw_read_timeout(self, mock_which, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="bw", timeout=10)
        with pytest.raises(RuntimeError, match="timed out"):
            bw_read("yandex-direct-item")


class TestGetCredentialsBw:
    """Tests for Bitwarden fallback in get_credentials"""

    @patch("direct_cli.auth.load_env_file")
    @patch("direct_cli.auth.bw_read", return_value="bw-token-value")
    def test_get_credentials_bw_fallback(
        self, mock_bw_read, mock_load, monkeypatch
    ):
        monkeypatch.delenv("YANDEX_DIRECT_TOKEN", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_LOGIN", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_OP_TOKEN_REF", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_OP_LOGIN_REF", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_BW_LOGIN_REF", raising=False)
        monkeypatch.setenv("YANDEX_DIRECT_BW_TOKEN_REF", "yandex-direct-item")

        token, login = get_credentials()
        assert token == "bw-token-value"
        mock_bw_read.assert_called_once_with("yandex-direct-item", "password")

    @patch("direct_cli.auth.load_env_file")
    @patch("direct_cli.auth.bw_read")
    def test_get_credentials_env_takes_priority_over_bw(
        self, mock_bw_read, mock_load, monkeypatch
    ):
        monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "env-token")
        monkeypatch.setenv("YANDEX_DIRECT_BW_TOKEN_REF", "yandex-direct-item")

        token, login = get_credentials()
        assert token == "env-token"
        mock_bw_read.assert_not_called()

    @patch("direct_cli.auth.load_env_file")
    @patch("direct_cli.auth.bw_read", return_value="bw-login-value")
    def test_get_credentials_bw_login_fallback(
        self, mock_bw_read, mock_load, monkeypatch
    ):
        monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "some-token")
        monkeypatch.delenv("YANDEX_DIRECT_LOGIN", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_OP_LOGIN_REF", raising=False)
        monkeypatch.setenv("YANDEX_DIRECT_BW_LOGIN_REF", "yandex-direct-item")

        token, login = get_credentials()
        assert login == "bw-login-value"
        mock_bw_read.assert_called_once_with("yandex-direct-item", "username")

    @patch("direct_cli.auth.load_env_file")
    @patch("direct_cli.auth.bw_read", return_value="bw-token-value")
    def test_get_credentials_explicit_bw_ref_param(
        self, mock_bw_read, mock_load, monkeypatch
    ):
        monkeypatch.delenv("YANDEX_DIRECT_TOKEN", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_LOGIN", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_BW_TOKEN_REF", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_BW_LOGIN_REF", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_OP_TOKEN_REF", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_OP_LOGIN_REF", raising=False)

        token, login = get_credentials(bw_token_ref="yandex-direct-item")
        assert token == "bw-token-value"
        mock_bw_read.assert_called_once_with("yandex-direct-item", "password")

    @patch("direct_cli.auth.load_env_file")
    @patch("direct_cli.auth.op_read", return_value="op-token-value")
    @patch("direct_cli.auth.bw_read")
    def test_op_takes_priority_over_bw(
        self, mock_bw_read, mock_op_read, mock_load, monkeypatch
    ):
        monkeypatch.delenv("YANDEX_DIRECT_TOKEN", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_LOGIN", raising=False)
        monkeypatch.setenv(
            "YANDEX_DIRECT_OP_TOKEN_REF", "op://vault/item/token"
        )
        monkeypatch.setenv(
            "YANDEX_DIRECT_BW_TOKEN_REF", "yandex-direct-item"
        )

        token, login = get_credentials()
        assert token == "op-token-value"
        mock_bw_read.assert_not_called()


class TestCLIBwOptions:
    """Tests for --bw-token-ref and --bw-login-ref CLI options"""

    def test_cli_help_shows_bw_options(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert "--bw-token-ref" in result.output
        assert "--bw-login-ref" in result.output

    @patch("direct_cli.auth.load_env_file")
    @patch("direct_cli.auth.bw_read", return_value="resolved-bw-token")
    def test_bw_token_ref_resolves_via_cli_flag(
        self, mock_bw_read, mock_load, monkeypatch
    ):
        monkeypatch.delenv("YANDEX_DIRECT_TOKEN", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_LOGIN", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_OP_TOKEN_REF", raising=False)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--bw-token-ref",
                "yandex-direct-item",
                "campaigns",
                "get",
                "--help",
            ],
        )
        assert result.exit_code == 0
        mock_bw_read.assert_called_once_with("yandex-direct-item", "password")

    @patch("direct_cli.auth.load_env_file")
    @patch(
        "direct_cli.auth.bw_read",
        side_effect=RuntimeError("Bitwarden CLI (bw) not found"),
    )
    def test_bw_token_ref_error_surfaces_cleanly(
        self, mock_bw_read, mock_load, monkeypatch
    ):
        monkeypatch.delenv("YANDEX_DIRECT_TOKEN", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_LOGIN", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_OP_TOKEN_REF", raising=False)
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--bw-token-ref", "yandex-direct-item", "campaigns", "get"]
        )
        assert result.exit_code != 0
        assert "Bitwarden CLI (bw) not found" in result.output
