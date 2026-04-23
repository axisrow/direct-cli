"""Tests for OAuth profile authentication flows."""

import stat
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from direct_cli.auth import (
    DEFAULT_OAUTH_CLIENT_ID,
    get_credentials,
    save_oauth_profile,
)
from direct_cli.cli import cli


@pytest.fixture
def isolated_auth_store(monkeypatch, tmp_path):
    store_path = tmp_path / "auth.json"
    monkeypatch.setattr("direct_cli.auth.AUTH_STORE_PATH", store_path)
    return store_path


class TestAuthOAuth:
    """OAuth profile and credential resolution tests."""

    @patch("direct_cli.auth.load_env_file")
    def test_get_credentials_reads_oauth_profile(
        self, mock_load_env, isolated_auth_store, monkeypatch
    ):
        monkeypatch.delenv("YANDEX_DIRECT_TOKEN", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_LOGIN", raising=False)
        save_oauth_profile(
            profile="agency1",
            token="oauth-token-1",
            login="client-login-1",
            make_active=False,
        )

        token, login = get_credentials(profile="agency1")
        assert token == "oauth-token-1"
        assert login == "client-login-1"

    @patch("direct_cli.auth.load_env_file")
    def test_get_credentials_reads_profile_from_env(
        self, mock_load_env, isolated_auth_store, monkeypatch
    ):
        monkeypatch.delenv("YANDEX_DIRECT_TOKEN", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_LOGIN", raising=False)
        monkeypatch.setenv("YANDEX_DIRECT_TOKEN_AGENCY1", "env-token-1")
        monkeypatch.setenv("YANDEX_DIRECT_LOGIN_AGENCY1", "env-login-1")

        token, login = get_credentials(profile="agency1")
        assert token == "env-token-1"
        assert login == "env-login-1"

    @patch("direct_cli.auth.load_env_file")
    def test_profile_does_not_fallback_to_base_env(
        self, mock_load_env, isolated_auth_store, monkeypatch
    ):
        monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "base-token")
        monkeypatch.setenv("YANDEX_DIRECT_LOGIN", "base-login")

        with pytest.raises(ValueError, match="Profile 'agency1' is not configured"):
            get_credentials(profile="agency1")

    @patch("direct_cli.auth.load_env_file")
    def test_profile_token_does_not_mix_global_login(
        self, mock_load_env, isolated_auth_store, monkeypatch
    ):
        monkeypatch.setenv("YANDEX_DIRECT_TOKEN_AGENCY1", "env-token-1")
        monkeypatch.setenv("YANDEX_DIRECT_LOGIN", "base-login")

        token, login = get_credentials(profile="agency1")
        assert token == "env-token-1"
        assert login is None

    @patch("direct_cli.auth.load_env_file")
    def test_explicit_login_overrides_profile_login(
        self, mock_load_env, isolated_auth_store, monkeypatch
    ):
        monkeypatch.setenv("YANDEX_DIRECT_TOKEN_AGENCY1", "env-token-1")
        monkeypatch.setenv("YANDEX_DIRECT_LOGIN_AGENCY1", "profile-login")

        token, login = get_credentials(profile="agency1", login="client-login")
        assert token == "env-token-1"
        assert login == "client-login"

    @patch("direct_cli.auth.load_env_file")
    def test_yandex_direct_profile_env_is_ignored(
        self, mock_load_env, isolated_auth_store, monkeypatch
    ):
        monkeypatch.setenv("YANDEX_DIRECT_PROFILE", "agency1")
        monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "base-token")
        monkeypatch.setenv("YANDEX_DIRECT_LOGIN", "base-login")
        monkeypatch.setenv("YANDEX_DIRECT_TOKEN_AGENCY1", "profile-token")

        token, login = get_credentials()
        assert token == "base-token"
        assert login == "base-login"

    def test_auth_login_oauth_token_mode(self, isolated_auth_store):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "auth",
                "login",
                "--oauth-token",
                "y0_secret_token",
                "--profile",
                "agency1",
            ],
        )
        assert result.exit_code == 0
        assert "Profile 'agency1' is saved and active." in result.output
        assert "y0_secret_token" not in result.output

        status = runner.invoke(cli, ["auth", "status", "--profile", "agency1"])
        assert status.exit_code == 0
        assert "has_token=yes" in status.output
        assert "y0_secret_token" not in status.output

    def test_auth_store_uses_private_permissions(self, isolated_auth_store):
        save_oauth_profile(profile="agency1", token="oauth-token-1")

        directory_mode = stat.S_IMODE(isolated_auth_store.parent.stat().st_mode)
        file_mode = stat.S_IMODE(isolated_auth_store.stat().st_mode)
        assert directory_mode == 0o700
        assert file_mode == 0o600

    @patch("direct_cli.commands.auth.exchange_oauth_code", return_value="y0_token")
    def test_auth_login_code_mode_custom_app(self, mock_exchange, isolated_auth_store):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "auth",
                "login",
                "--profile",
                "agency1",
                "--code",
                "abc123",
                "--client-id",
                "cid",
                "--client-secret",
                "csecret",
            ],
        )
        assert result.exit_code == 0
        mock_exchange.assert_called_once_with(
            code="abc123",
            client_id="cid",
            client_secret="csecret",
            code_verifier=None,
        )

    @patch("direct_cli.commands.auth.build_pkce_pair", return_value=("ver", "chal"))
    @patch("direct_cli.commands.auth.exchange_oauth_code", return_value="y0_pkce")
    def test_auth_login_pkce_mode(self, mock_exchange, mock_pkce, isolated_auth_store):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["auth", "login", "--profile", "agency1"],
            input="abc123\n",
        )
        assert result.exit_code == 0
        assert "oauth.yandex.ru/authorize" in result.output
        mock_exchange.assert_called_once_with(
            code="abc123",
            client_id="dcf15d9625f6471d94d6d054d52017ba",
            client_secret=None,
            code_verifier="ver",
        )

    def test_default_oauth_client_id_matches_plugin_app(self):
        assert DEFAULT_OAUTH_CLIENT_ID == "dcf15d9625f6471d94d6d054d52017ba"

    @patch("direct_cli.cli.get_credentials", return_value=("active-token", None))
    def test_active_profile_triggers_early_cli_resolution(
        self, mock_get_credentials, isolated_auth_store, monkeypatch
    ):
        monkeypatch.delenv("YANDEX_DIRECT_TOKEN", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_LOGIN", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_OP_TOKEN_REF", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_OP_LOGIN_REF", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_BW_TOKEN_REF", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_BW_LOGIN_REF", raising=False)
        save_oauth_profile(profile="agency1", token="oauth-token-1")
        runner = CliRunner()

        result = runner.invoke(cli, ["campaigns", "get", "--help"])

        assert result.exit_code == 0
        mock_get_credentials.assert_called_once()

    def test_auth_use_works_for_env_profile(self, isolated_auth_store, monkeypatch):
        monkeypatch.setenv("YANDEX_DIRECT_TOKEN_AGENCY1", "env-token")
        runner = CliRunner()
        result = runner.invoke(cli, ["auth", "use", "--profile", "agency1"])
        assert result.exit_code == 0
        assert "Active profile is 'agency1'." in result.output

        result = runner.invoke(cli, ["auth", "list"])
        assert result.exit_code == 0
        assert "* agency1" in result.output
