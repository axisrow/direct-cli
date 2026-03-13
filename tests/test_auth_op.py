"""Tests for 1Password integration in auth module"""

from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from direct_cli.auth import op_read, get_credentials
from direct_cli.cli import cli


class TestOpRead:
    """Tests for op_read function"""

    @patch("direct_cli.auth.subprocess.run")
    @patch("direct_cli.auth.shutil.which", return_value="/usr/local/bin/op")
    def test_op_read_success(self, mock_which, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="my-secret-token\n", stderr=""
        )
        result = op_read("op://vault/item/token")
        assert result == "my-secret-token"
        mock_run.assert_called_once_with(
            ["/usr/local/bin/op", "read", "op://vault/item/token"],
            capture_output=True,
            text=True,
            timeout=10,
        )

    @patch("direct_cli.auth.shutil.which", return_value=None)
    def test_op_read_op_not_found(self, mock_which):
        with pytest.raises(RuntimeError, match="1Password CLI .* not found"):
            op_read("op://vault/item/token")

    @patch("direct_cli.auth.subprocess.run")
    @patch("direct_cli.auth.shutil.which", return_value="/usr/local/bin/op")
    def test_op_read_op_fails(self, mock_which, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="item not found"
        )
        with pytest.raises(RuntimeError, match="item not found"):
            op_read("op://vault/item/token")

    @patch("direct_cli.auth.subprocess.run")
    @patch("direct_cli.auth.shutil.which", return_value="/usr/local/bin/op")
    def test_op_read_timeout(self, mock_which, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="op", timeout=10)
        with pytest.raises(RuntimeError, match="timed out"):
            op_read("op://vault/item/token")


class TestGetCredentialsOp:
    """Tests for 1Password fallback in get_credentials"""

    @patch("direct_cli.auth.load_env_file")
    @patch("direct_cli.auth.op_read", return_value="op-token-value")
    def test_get_credentials_op_fallback(self, mock_op_read, mock_load, monkeypatch):
        monkeypatch.delenv("YANDEX_DIRECT_TOKEN", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_LOGIN", raising=False)
        monkeypatch.setenv("YANDEX_DIRECT_OP_TOKEN_REF", "op://vault/item/token")

        token, login = get_credentials()
        assert token == "op-token-value"
        mock_op_read.assert_called_once_with("op://vault/item/token")

    @patch("direct_cli.auth.load_env_file")
    @patch("direct_cli.auth.op_read")
    def test_get_credentials_env_takes_priority_over_op(self, mock_op_read, mock_load, monkeypatch):
        monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "env-token")
        monkeypatch.setenv("YANDEX_DIRECT_OP_TOKEN_REF", "op://vault/item/token")

        token, login = get_credentials()
        assert token == "env-token"
        mock_op_read.assert_not_called()

    @patch("direct_cli.auth.load_env_file")
    @patch("direct_cli.auth.op_read", return_value="op-login-value")
    def test_get_credentials_op_login_fallback(self, mock_op_read, mock_load, monkeypatch):
        monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "some-token")
        monkeypatch.delenv("YANDEX_DIRECT_LOGIN", raising=False)
        monkeypatch.setenv("YANDEX_DIRECT_OP_LOGIN_REF", "op://vault/item/login")

        token, login = get_credentials()
        assert login == "op-login-value"
        mock_op_read.assert_called_once_with("op://vault/item/login")

    @patch("direct_cli.auth.load_env_file")
    @patch("direct_cli.auth.op_read", return_value="op-token-value")
    def test_get_credentials_explicit_op_ref_param(self, mock_op_read, mock_load, monkeypatch):
        monkeypatch.delenv("YANDEX_DIRECT_TOKEN", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_LOGIN", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_OP_TOKEN_REF", raising=False)

        token, login = get_credentials(op_token_ref="op://vault/item/token")
        assert token == "op-token-value"
        mock_op_read.assert_called_once_with("op://vault/item/token")


class TestCLIOpOptions:
    """Tests for --op-token-ref and --op-login-ref CLI options"""

    def test_cli_help_shows_op_options(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert "--op-token-ref" in result.output
        assert "--op-login-ref" in result.output

    def test_op_token_ref_stored_in_ctx(self):
        runner = CliRunner()
        result = runner.invoke(
            cli, ["--op-token-ref", "op://vault/item/token", "--help"]
        )
        assert result.exit_code == 0
