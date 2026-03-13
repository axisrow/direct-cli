"""Tests for 1Password integration in auth module"""

import subprocess
from unittest.mock import patch, MagicMock

import pytest

from direct_cli.auth import op_read, get_credentials


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
