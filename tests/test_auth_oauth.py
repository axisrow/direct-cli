"""Tests for OAuth profile authentication flows."""

import io
import json
import stat
import urllib.parse
from urllib.error import HTTPError, URLError
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from direct_cli.auth import (
    DEFAULT_OAUTH_CLIENT_ID,
    exchange_oauth_code,
    get_credentials,
    load_auth_store,
    refresh_access_token,
    save_auth_store,
    save_oauth_profile,
)
from direct_cli.cli import cli


@pytest.fixture
def isolated_auth_store(monkeypatch, tmp_path):
    store_path = tmp_path / "auth.json"
    monkeypatch.setattr("direct_cli.auth.AUTH_STORE_PATH", store_path)
    return store_path


class FakeOAuthResponse:
    """Minimal context manager for urllib response mocks."""

    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def fake_http_error(code=400, body=b"invalid_grant"):
    """Build an HTTPError with a deterministic response body."""
    return HTTPError(
        url="https://oauth.yandex.ru/token",
        code=code,
        msg="Bad Request",
        hdrs=None,
        fp=io.BytesIO(body),
    )


def request_form_body(mock_urlopen):
    """Parse the form body from the mocked urllib Request."""
    request = mock_urlopen.call_args.args[0]
    return urllib.parse.parse_qs(request.data.decode("utf-8"))


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
            refresh_token="refresh-1",
            expires_at=4_100_000_000.0,
            client_id=DEFAULT_OAUTH_CLIENT_ID,
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

    @patch("direct_cli.commands.campaigns.create_client")
    def test_cli_command_uses_active_profile_credentials(
        self, mock_create_client, isolated_auth_store, monkeypatch
    ):
        monkeypatch.delenv("YANDEX_DIRECT_TOKEN", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_LOGIN", raising=False)
        save_oauth_profile(
            profile="agency1",
            token="oauth-token-1",
            login="client-login-1",
            refresh_token="refresh-1",
            expires_at=4_100_000_000.0,
            client_id=DEFAULT_OAUTH_CLIENT_ID,
        )
        runner = CliRunner()

        result = runner.invoke(cli, ["campaigns", "get", "--ids", "123", "--dry-run"])

        assert result.exit_code == 0
        mock_create_client.assert_called_once_with(
            token="oauth-token-1", login="client-login-1", sandbox=False
        )
        assert "oauth-token-1" not in result.output
        assert "client-login-1" not in result.output

    @patch("direct_cli.commands.campaigns.create_client")
    def test_cli_command_uses_env_credentials(
        self, mock_create_client, isolated_auth_store, monkeypatch
    ):
        monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "env-token")
        monkeypatch.setenv("YANDEX_DIRECT_LOGIN", "env-login")
        runner = CliRunner()

        result = runner.invoke(cli, ["campaigns", "get", "--ids", "123", "--dry-run"])

        assert result.exit_code == 0
        mock_create_client.assert_called_once_with(
            token="env-token", login="env-login", sandbox=False
        )
        assert "env-token" not in result.output
        assert "env-login" not in result.output

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
        save_oauth_profile(
            profile="agency1",
            token="oauth-token-1",
            refresh_token="refresh-1",
            expires_at=4_100_000_000.0,
            client_id=DEFAULT_OAUTH_CLIENT_ID,
        )

        directory_mode = stat.S_IMODE(isolated_auth_store.parent.stat().st_mode)
        file_mode = stat.S_IMODE(isolated_auth_store.stat().st_mode)
        assert directory_mode == 0o700
        assert file_mode == 0o600

    @patch("direct_cli.commands.auth.time.time", return_value=1000.0)
    @patch("direct_cli.commands.auth.build_pkce_pair", return_value=("ver", "chal"))
    def test_auth_login_start_pkce_text_output_saves_pending_state(
        self, mock_pkce, mock_time, isolated_auth_store
    ):
        runner = CliRunner()

        result = runner.invoke(
            cli,
            [
                "auth",
                "login",
                "--start-pkce",
                "--profile",
                "agency1",
                "--login",
                "client-login",
            ],
        )

        assert result.exit_code == 0
        assert "oauth.yandex.ru/authorize" in result.output
        assert "code_challenge=chal" in result.output
        assert "ver" not in result.output
        store = load_auth_store()
        assert store["pending_pkce"]["agency1"] == {
            "type": "pkce",
            "client_id": DEFAULT_OAUTH_CLIENT_ID,
            "code_verifier": "ver",
            "login": "client-login",
            "created_at": 1000.0,
            "expires_at": 1600.0,
        }

    @patch("direct_cli.commands.auth.time.time", return_value=1000.0)
    @patch("direct_cli.commands.auth.build_pkce_pair", return_value=("ver", "chal"))
    def test_auth_login_start_pkce_json_output_does_not_expose_verifier(
        self, mock_pkce, mock_time, isolated_auth_store
    ):
        runner = CliRunner()

        result = runner.invoke(
            cli,
            [
                "auth",
                "login",
                "--start-pkce",
                "--profile",
                "agency1",
                "--format",
                "json",
            ],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload == {
            "profile": "agency1",
            "authorize_url": (
                "https://oauth.yandex.ru/authorize?"
                "response_type=code&client_id="
                "dcf15d9625f6471d94d6d054d52017ba&"
                "code_challenge_method=S256&code_challenge=chal"
            ),
            "expires_at": 1600.0,
        }
        assert "code_verifier" not in result.output
        assert "ver" not in result.output

    @patch("direct_cli.commands.auth._stdin_is_interactive", return_value=False)
    @patch("direct_cli.commands.auth.time.time", return_value=1000.0)
    @patch("direct_cli.commands.auth.build_pkce_pair", return_value=("ver", "chal"))
    def test_auth_login_noninteractive_starts_pkce_without_prompt(
        self, mock_pkce, mock_time, mock_is_interactive, isolated_auth_store
    ):
        runner = CliRunner()

        result = runner.invoke(
            cli,
            ["auth", "login", "--profile", "agency1", "--login", "client-login"],
        )

        assert result.exit_code == 0
        assert "oauth.yandex.ru/authorize" in result.output
        assert "code_challenge=chal" in result.output
        assert "Enter OAuth code" not in result.output
        assert "ver" not in result.output
        store = load_auth_store()
        assert store["pending_pkce"]["agency1"] == {
            "type": "pkce",
            "client_id": DEFAULT_OAUTH_CLIENT_ID,
            "code_verifier": "ver",
            "login": "client-login",
            "created_at": 1000.0,
            "expires_at": 1600.0,
        }

    @patch("direct_cli.commands.auth._stdin_is_interactive", return_value=False)
    @patch("direct_cli.commands.auth.time.time", return_value=1000.0)
    def test_auth_login_noninteractive_remembers_confidential_client(
        self, mock_time, mock_is_interactive, isolated_auth_store
    ):
        runner = CliRunner()

        result = runner.invoke(
            cli,
            [
                "auth",
                "login",
                "--profile",
                "agency1",
                "--client-id",
                "cid",
                "--client-secret",
                "csecret",
                "--login",
                "client-login",
            ],
        )

        assert result.exit_code == 0
        assert "oauth.yandex.ru/authorize" in result.output
        assert "Enter OAuth code" not in result.output
        assert "csecret" not in result.output
        store = load_auth_store()
        assert store["pending_pkce"]["agency1"] == {
            "type": "confidential",
            "client_id": "cid",
            "client_secret": "csecret",
            "login": "client-login",
            "created_at": 1000.0,
            "expires_at": 1600.0,
        }

    @patch(
        "direct_cli.commands.auth.exchange_oauth_code",
        return_value={
            "access_token": "y0_token",
            "refresh_token": "r1",
            "expires_in": 3600,
        },
    )
    @patch("direct_cli.commands.auth.time.time", return_value=1000.0)
    def test_auth_login_code_mode_custom_app(
        self, mock_time, mock_exchange, isolated_auth_store
    ):
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
        profile = load_auth_store()["profiles"]["agency1"]
        assert profile["client_secret"] == "csecret"

    @patch(
        "direct_cli.commands.auth.exchange_oauth_code",
        return_value={
            "access_token": "y0_pkce",
            "refresh_token": "r1",
            "expires_in": 3600,
        },
    )
    @patch("direct_cli.commands.auth.time.time", return_value=1000.0)
    def test_auth_login_code_mode_uses_pending_pkce_state(
        self, mock_time, mock_exchange, isolated_auth_store
    ):
        save_auth_store(
            {
                "profiles": {},
                "active_profile": None,
                "pending_pkce": {
                    "agency1": {
                        "client_id": "cid",
                        "code_verifier": "ver",
                        "login": "client-login",
                        "created_at": 900.0,
                        "expires_at": 1500.0,
                    }
                },
            }
        )
        runner = CliRunner()

        result = runner.invoke(
            cli,
            ["auth", "login", "--profile", "agency1", "--code", "abc123"],
        )

        assert result.exit_code == 0
        mock_exchange.assert_called_once_with(
            code="abc123",
            client_id="cid",
            client_secret=None,
            code_verifier="ver",
        )
        store = load_auth_store()
        assert "agency1" not in store["pending_pkce"]
        profile = store["profiles"]["agency1"]
        assert profile["token"] == "y0_pkce"
        assert profile["login"] == "client-login"

    def test_auth_login_code_mode_missing_pending_pkce_fails(self, isolated_auth_store):
        runner = CliRunner()

        result = runner.invoke(
            cli,
            ["auth", "login", "--profile", "agency1", "--code", "abc123"],
        )

        assert result.exit_code != 0
        assert "direct auth login --profile agency1" in result.output

    @patch(
        "direct_cli.commands.auth.exchange_oauth_code",
        return_value={
            "access_token": "y0_pkce",
            "refresh_token": "r1",
            "expires_in": 3600,
        },
    )
    @patch("direct_cli.commands.auth.time.time", return_value=1000.0)
    def test_auth_login_code_dash_uses_pending_pkce_state(
        self, mock_time, mock_exchange, isolated_auth_store
    ):
        save_auth_store(
            {
                "profiles": {},
                "active_profile": None,
                "pending_pkce": {
                    "agency1": {
                        "type": "pkce",
                        "client_id": "cid",
                        "code_verifier": "ver",
                        "login": "client-login",
                        "created_at": 900.0,
                        "expires_at": 1500.0,
                    }
                },
            }
        )
        runner = CliRunner()

        result = runner.invoke(
            cli,
            ["auth", "login", "--profile", "agency1", "--code", "-"],
            input="abc123\n",
        )

        assert result.exit_code == 0
        assert "abc123" not in result.output
        mock_exchange.assert_called_once_with(
            code="abc123",
            client_id="cid",
            client_secret=None,
            code_verifier="ver",
        )
        store = load_auth_store()
        assert "agency1" not in store["pending_pkce"]
        profile = store["profiles"]["agency1"]
        assert profile["token"] == "y0_pkce"
        assert profile["login"] == "client-login"

    @patch(
        "direct_cli.commands.auth.exchange_oauth_code",
        return_value={
            "access_token": "y0_pkce",
            "refresh_token": "r1",
            "expires_in": 3600,
        },
    )
    @patch("direct_cli.commands.auth.time.time", return_value=1000.0)
    def test_auth_login_code_stdin_alias_uses_pending_pkce_state(
        self, mock_time, mock_exchange, isolated_auth_store
    ):
        save_auth_store(
            {
                "profiles": {},
                "active_profile": None,
                "pending_pkce": {
                    "agency1": {
                        "type": "pkce",
                        "client_id": "cid",
                        "code_verifier": "ver",
                        "login": "client-login",
                        "created_at": 900.0,
                        "expires_at": 1500.0,
                    }
                },
            }
        )
        runner = CliRunner()

        result = runner.invoke(
            cli,
            ["auth", "login", "--profile", "agency1", "--code-stdin"],
            input="abc123\n",
        )

        assert result.exit_code == 0
        assert "abc123" not in result.output
        mock_exchange.assert_called_once_with(
            code="abc123",
            client_id="cid",
            client_secret=None,
            code_verifier="ver",
        )

    def test_auth_login_code_dash_requires_input(self, isolated_auth_store):
        runner = CliRunner()

        result = runner.invoke(
            cli,
            ["auth", "login", "--profile", "agency1", "--code", "-"],
            input="\n",
        )

        assert result.exit_code != 0
        assert "--code - requires a code on stdin" in result.output

    def test_auth_login_code_dash_conflicts_before_reading_stdin(
        self, isolated_auth_store
    ):
        runner = CliRunner()

        result = runner.invoke(
            cli,
            [
                "auth",
                "login",
                "--profile",
                "agency1",
                "--code",
                "-",
                "--start-pkce",
            ],
        )

        assert result.exit_code != 0
        assert "--code - cannot be combined" in result.output

    def test_auth_login_code_dash_oauth_token_conflict_before_reading_stdin(
        self, isolated_auth_store
    ):
        runner = CliRunner()

        result = runner.invoke(
            cli,
            [
                "auth",
                "login",
                "--profile",
                "agency1",
                "--code",
                "-",
                "--oauth-token",
                "token",
            ],
        )

        assert result.exit_code != 0
        assert "--code - cannot be combined" in result.output
        assert "--code - requires a code on stdin" not in result.output

    def test_auth_login_code_stdin_alias_conflicts_with_code(self, isolated_auth_store):
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
                "--code-stdin",
            ],
            input="stdin-code\n",
        )

        assert result.exit_code != 0
        assert "--code-stdin cannot be combined with --code" in result.output

    @patch(
        "direct_cli.commands.auth.exchange_oauth_code",
        return_value={
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        },
    )
    @patch("direct_cli.commands.auth.time.time", return_value=1000.0)
    def test_auth_login_code_dash_custom_app(
        self, mock_time, mock_exchange, isolated_auth_store
    ):
        runner = CliRunner()

        result = runner.invoke(
            cli,
            [
                "auth",
                "login",
                "--profile",
                "agency1",
                "--code",
                "-",
                "--client-id",
                "cid",
                "--client-secret",
                "csecret",
            ],
            input="abc123\n",
        )

        assert result.exit_code == 0
        assert "abc123" not in result.output
        mock_exchange.assert_called_once_with(
            code="abc123",
            client_id="cid",
            client_secret="csecret",
            code_verifier=None,
        )
        profile = load_auth_store()["profiles"]["agency1"]
        assert profile["client_secret"] == "csecret"

    @patch("direct_cli.commands.auth.time.time", return_value=1000.0)
    def test_auth_login_code_mode_expired_pending_pkce_without_secret_fails(
        self, mock_time, isolated_auth_store
    ):
        save_auth_store(
            {
                "profiles": {},
                "active_profile": None,
                "pending_pkce": {
                    "agency1": {
                        "client_id": "cid",
                        "code_verifier": "ver",
                        "login": "client-login",
                        "created_at": 100.0,
                        "expires_at": 999.0,
                    }
                },
            }
        )
        runner = CliRunner()

        result = runner.invoke(
            cli,
            ["auth", "login", "--profile", "agency1", "--code", "abc123"],
        )

        assert result.exit_code != 0
        assert "direct auth login --profile agency1" in result.output

    @patch(
        "direct_cli.commands.auth.exchange_oauth_code",
        return_value={
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        },
    )
    @patch("direct_cli.commands.auth.time.time", return_value=1000.0)
    def test_auth_login_code_mode_expired_pending_falls_back_to_saved_secret(
        self, mock_time, mock_exchange, isolated_auth_store
    ):
        save_auth_store(
            {
                "profiles": {
                    "agency1": {
                        "token": "old-access",
                        "login": "client-login",
                        "source": "oauth",
                        "refresh_token": "old-refresh",
                        "expires_at": 2000.0,
                        "client_id": "cid",
                        "client_secret": "csecret",
                    }
                },
                "active_profile": "agency1",
                "pending_pkce": {
                    "agency1": {
                        "client_id": "cid",
                        "code_verifier": "ver",
                        "login": "client-login",
                        "created_at": 100.0,
                        "expires_at": 999.0,
                    }
                },
            }
        )
        runner = CliRunner()

        result = runner.invoke(
            cli,
            ["auth", "login", "--profile", "agency1", "--code", "abc123"],
        )

        assert result.exit_code == 0
        mock_exchange.assert_called_once_with(
            code="abc123",
            client_id="cid",
            client_secret="csecret",
            code_verifier=None,
        )
        store = load_auth_store()
        assert "agency1" not in store["pending_pkce"]
        assert store["profiles"]["agency1"]["client_secret"] == "csecret"

    @patch(
        "direct_cli.commands.auth.exchange_oauth_code",
        return_value={
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        },
    )
    @patch("direct_cli.commands.auth.time.time", return_value=1000.0)
    def test_auth_login_code_mode_uses_pending_confidential_state(
        self, mock_time, mock_exchange, isolated_auth_store
    ):
        save_auth_store(
            {
                "profiles": {},
                "active_profile": None,
                "pending_pkce": {
                    "agency1": {
                        "type": "confidential",
                        "client_id": "cid",
                        "client_secret": "csecret",
                        "login": "client-login",
                        "created_at": 900.0,
                        "expires_at": 1500.0,
                    }
                },
            }
        )
        runner = CliRunner()

        result = runner.invoke(
            cli,
            ["auth", "login", "--profile", "agency1", "--code", "abc123"],
        )

        assert result.exit_code == 0
        mock_exchange.assert_called_once_with(
            code="abc123",
            client_id="cid",
            client_secret="csecret",
            code_verifier=None,
        )
        store = load_auth_store()
        assert "agency1" not in store["pending_pkce"]
        profile = store["profiles"]["agency1"]
        assert profile["client_secret"] == "csecret"
        assert profile["login"] == "client-login"

    @patch(
        "direct_cli.commands.auth.exchange_oauth_code",
        side_effect=RuntimeError("OAuth token request failed with HTTP 400"),
    )
    @patch("direct_cli.commands.auth.time.time", return_value=1000.0)
    def test_auth_login_code_mode_exchange_failure_keeps_pending_state(
        self, mock_time, mock_exchange, isolated_auth_store
    ):
        save_auth_store(
            {
                "profiles": {},
                "active_profile": None,
                "pending_pkce": {
                    "agency1": {
                        "client_id": "cid",
                        "code_verifier": "ver",
                        "login": "client-login",
                        "created_at": 900.0,
                        "expires_at": 1500.0,
                    }
                },
            }
        )
        runner = CliRunner()

        result = runner.invoke(
            cli,
            ["auth", "login", "--profile", "agency1", "--code", "bad-code"],
        )

        assert result.exit_code != 0
        assert load_auth_store()["pending_pkce"]["agency1"]["code_verifier"] == "ver"

    @patch(
        "direct_cli.commands.auth.exchange_oauth_code",
        return_value={
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        },
    )
    @patch("direct_cli.commands.auth.time.time", return_value=1000.0)
    def test_auth_login_code_mode_uses_remembered_confidential_client(
        self, mock_time, mock_exchange, isolated_auth_store
    ):
        save_oauth_profile(
            profile="agency1",
            token="old-access",
            login="client-login",
            refresh_token="old-refresh",
            expires_at=2000.0,
            client_id="cid",
            client_secret="csecret",
        )
        runner = CliRunner()

        result = runner.invoke(
            cli,
            ["auth", "login", "--profile", "agency1", "--code", "abc123"],
        )

        assert result.exit_code == 0
        mock_exchange.assert_called_once_with(
            code="abc123",
            client_id="cid",
            client_secret="csecret",
            code_verifier=None,
        )
        profile = load_auth_store()["profiles"]["agency1"]
        assert profile["client_secret"] == "csecret"
        assert profile["token"] == "new-access"

    @patch(
        "direct_cli.commands.auth.exchange_oauth_code",
        return_value={
            "access_token": "y0_pkce",
            "refresh_token": "r1",
            "expires_in": 3600,
        },
    )
    @patch("direct_cli.commands.auth.time.time", return_value=1000.0)
    def test_auth_login_code_mode_pending_pkce_wins_over_remembered_secret(
        self, mock_time, mock_exchange, isolated_auth_store
    ):
        save_auth_store(
            {
                "profiles": {
                    "agency1": {
                        "token": "old-access",
                        "login": "old-login",
                        "source": "oauth",
                        "refresh_token": "old-refresh",
                        "expires_at": 2000.0,
                        "client_id": "confidential-cid",
                        "client_secret": "csecret",
                    }
                },
                "active_profile": "agency1",
                "pending_pkce": {
                    "agency1": {
                        "client_id": "pkce-cid",
                        "code_verifier": "ver",
                        "login": "pkce-login",
                        "created_at": 900.0,
                        "expires_at": 1500.0,
                    }
                },
            }
        )
        runner = CliRunner()

        result = runner.invoke(
            cli,
            ["auth", "login", "--profile", "agency1", "--code", "abc123"],
        )

        assert result.exit_code == 0
        mock_exchange.assert_called_once_with(
            code="abc123",
            client_id="pkce-cid",
            client_secret=None,
            code_verifier="ver",
        )
        profile = load_auth_store()["profiles"]["agency1"]
        assert "client_secret" not in profile
        assert profile["login"] == "pkce-login"

    @patch("direct_cli.commands.auth.time.time", return_value=1000.0)
    def test_auth_login_code_mode_remembered_client_id_mismatch_fails(
        self, mock_time, isolated_auth_store
    ):
        save_oauth_profile(
            profile="agency1",
            token="old-access",
            login="client-login",
            refresh_token="old-refresh",
            expires_at=2000.0,
            client_id="saved-cid",
            client_secret="csecret",
        )
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
                "other-cid",
            ],
        )

        assert result.exit_code != 0
        assert "does not match saved client_id" in result.output

    @patch("direct_cli.commands.auth.time.time", return_value=1000.0)
    def test_auth_login_code_mode_pending_client_id_mismatch_fails(
        self, mock_time, isolated_auth_store
    ):
        save_auth_store(
            {
                "profiles": {},
                "active_profile": None,
                "pending_pkce": {
                    "agency1": {
                        "client_id": "pending-cid",
                        "code_verifier": "ver",
                        "login": "client-login",
                        "created_at": 900.0,
                        "expires_at": 1500.0,
                    }
                },
            }
        )
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
                "other-cid",
            ],
        )

        assert result.exit_code != 0
        assert "does not match pending client_id" in result.output

    @patch("direct_cli.commands.auth._stdin_is_interactive", return_value=True)
    @patch("direct_cli.commands.auth.time.time", return_value=1000.0)
    @patch("direct_cli.commands.auth.build_pkce_pair", return_value=("ver", "chal"))
    @patch(
        "direct_cli.commands.auth.exchange_oauth_code",
        return_value={
            "access_token": "y0_pkce",
            "refresh_token": "r1",
            "expires_in": 3600,
        },
    )
    def test_auth_login_pkce_mode(
        self,
        mock_exchange,
        mock_pkce,
        mock_time,
        mock_is_interactive,
        isolated_auth_store,
    ):
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
        save_oauth_profile(
            profile="agency1",
            token="oauth-token-1",
            refresh_token="refresh-1",
            expires_at=4_100_000_000.0,
            client_id=DEFAULT_OAUTH_CLIENT_ID,
        )
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

    @patch(
        "direct_cli.auth.urllib.request.urlopen",
        return_value=FakeOAuthResponse(
            {
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "expires_in": 3600,
            }
        ),
    )
    def test_exchange_oauth_code_returns_token_response(self, mock_urlopen):
        result = exchange_oauth_code(
            code="abc123", client_id="cid", code_verifier="verifier"
        )

        assert result == {
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "expires_in": 3600,
        }

    def test_save_oauth_profile_persists_refresh_metadata(self, isolated_auth_store):
        save_oauth_profile(
            profile="agency1",
            token="access-1",
            login="client-login",
            refresh_token="refresh-1",
            expires_at=2000.0,
            client_id="cid",
        )

        store = load_auth_store()
        assert store["profiles"]["agency1"] == {
            "token": "access-1",
            "login": "client-login",
            "source": "oauth",
            "refresh_token": "refresh-1",
            "expires_at": 2000.0,
            "client_id": "cid",
        }

    def test_save_oauth_profile_persists_client_secret(self, isolated_auth_store):
        save_oauth_profile(
            profile="agency1",
            token="access-1",
            login="client-login",
            refresh_token="refresh-1",
            expires_at=2000.0,
            client_id="cid",
            client_secret="csecret",
        )

        profile = load_auth_store()["profiles"]["agency1"]
        assert profile["client_secret"] == "csecret"

    @patch(
        "direct_cli.commands.auth.exchange_oauth_code",
        return_value={
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        },
    )
    @patch("direct_cli.commands.auth.time.time", return_value=1000.0)
    def test_auth_login_code_mode_explicit_secret_clears_pending_state(
        self, mock_time, mock_exchange, isolated_auth_store
    ):
        save_auth_store(
            {
                "profiles": {},
                "active_profile": None,
                "pending_pkce": {
                    "agency1": {
                        "client_id": "old-cid",
                        "code_verifier": "ver",
                        "login": "client-login",
                        "created_at": 900.0,
                        "expires_at": 1500.0,
                    }
                },
            }
        )
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
        store = load_auth_store()
        assert "agency1" not in store["pending_pkce"]
        assert store["profiles"]["agency1"]["client_secret"] == "csecret"

    @patch("direct_cli.auth.load_env_file")
    @patch("direct_cli.auth.time.time", return_value=1000.0)
    @patch(
        "direct_cli.auth.urllib.request.urlopen",
        return_value=FakeOAuthResponse(
            {
                "access_token": "access-2",
                "refresh_token": "refresh-2",
                "expires_in": 3600,
            }
        ),
    )
    def test_get_credentials_refreshes_expiring_oauth_profile(
        self, mock_urlopen, mock_time, mock_load_env, isolated_auth_store, monkeypatch
    ):
        monkeypatch.delenv("YANDEX_DIRECT_TOKEN", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_LOGIN", raising=False)
        save_oauth_profile(
            profile="agency1",
            token="access-1",
            login="client-login",
            refresh_token="refresh-1",
            expires_at=1050.0,
            client_id="cid",
            make_active=False,
        )

        token, login = get_credentials(profile="agency1")

        assert token == "access-2"
        assert login == "client-login"
        profile = load_auth_store()["profiles"]["agency1"]
        assert profile["token"] == "access-2"
        assert profile["refresh_token"] == "refresh-2"
        assert profile["expires_at"] == 4600.0

    @patch("direct_cli.auth.load_env_file")
    @patch("direct_cli.auth.time.time", return_value=1000.0)
    @patch(
        "direct_cli.auth.urllib.request.urlopen",
        return_value=FakeOAuthResponse(
            {
                "access_token": "access-2",
                "refresh_token": "refresh-2",
                "expires_in": 3600,
            }
        ),
    )
    def test_get_credentials_refreshes_at_refresh_skew_boundary(
        self, mock_urlopen, mock_time, mock_load_env, isolated_auth_store, monkeypatch
    ):
        monkeypatch.delenv("YANDEX_DIRECT_TOKEN", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_LOGIN", raising=False)
        save_oauth_profile(
            profile="agency1",
            token="access-1",
            login="client-login",
            refresh_token="refresh-1",
            expires_at=1060.0,
            client_id="cid",
            make_active=False,
        )

        token, login = get_credentials(profile="agency1")

        assert token == "access-2"
        assert login == "client-login"
        assert mock_urlopen.call_count == 1

    @patch("direct_cli.auth.load_env_file")
    def test_legacy_oauth_profile_without_refresh_token_fails(
        self, mock_load_env, isolated_auth_store, monkeypatch
    ):
        monkeypatch.delenv("YANDEX_DIRECT_TOKEN", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_LOGIN", raising=False)
        save_auth_store(
            {
                "profiles": {
                    "agency1": {
                        "token": "access-1",
                        "login": "client-login",
                        "source": "oauth",
                    }
                },
                "active_profile": "agency1",
            }
        )

        with pytest.raises(
            ValueError, match="Run direct auth login --profile agency1 again"
        ):
            get_credentials(profile="agency1")

    @patch(
        "direct_cli.auth.urllib.request.urlopen",
        side_effect=fake_http_error(code=400),
    )
    def test_refresh_access_token_expired_refresh_token_fails_cleanly(
        self, mock_urlopen, isolated_auth_store
    ):
        save_oauth_profile(
            profile="agency1",
            token="access-1",
            login="client-login",
            refresh_token="refresh-1",
            expires_at=1000.0,
            client_id="cid",
        )

        with pytest.raises(RuntimeError, match="OAuth refresh token expired"):
            refresh_access_token("agency1")

    def test_refresh_access_token_recovers_from_concurrent_refresh(
        self, isolated_auth_store
    ):
        save_oauth_profile(
            profile="agency1",
            token="access-1",
            login="client-login",
            refresh_token="refresh-1",
            expires_at=1000.0,
            client_id="cid",
        )

        def simulate_concurrent_refresh(*_args, **_kwargs):
            # Imitate another process having just rotated the token on disk
            # before the current refresh request could complete.
            store = load_auth_store()
            store["profiles"]["agency1"]["token"] = "access-2"
            store["profiles"]["agency1"]["refresh_token"] = "refresh-2"
            store["profiles"]["agency1"]["expires_at"] = 4_100_000_000.0
            save_auth_store(store)
            raise fake_http_error(code=400)

        with patch(
            "direct_cli.auth.urllib.request.urlopen",
            side_effect=simulate_concurrent_refresh,
        ):
            result = refresh_access_token("agency1")

        assert result["token"] == "access-2"
        assert result["refresh_token"] == "refresh-2"
        assert result["expires_at"] == 4_100_000_000.0

    @patch(
        "direct_cli.auth.urllib.request.urlopen",
        side_effect=URLError(TimeoutError("timed out")),
    )
    def test_refresh_access_token_timeout_message(
        self, mock_urlopen, isolated_auth_store
    ):
        save_oauth_profile(
            profile="agency1",
            token="access-1",
            login="client-login",
            refresh_token="refresh-1",
            expires_at=1000.0,
            client_id="cid",
        )

        with pytest.raises(RuntimeError, match="OAuth refresh request timed out"):
            refresh_access_token("agency1")

    @patch(
        "direct_cli.auth.urllib.request.urlopen",
        return_value=FakeOAuthResponse(
            {
                "access_token": "access-2",
                "expires_in": 3600,
            }
        ),
    )
    def test_refresh_access_token_sends_client_secret(
        self, mock_urlopen, isolated_auth_store
    ):
        save_oauth_profile(
            profile="agency1",
            token="access-1",
            login="client-login",
            refresh_token="refresh-1",
            expires_at=1000.0,
            client_id="cid",
            client_secret="csecret",
        )

        refresh_access_token("agency1")

        assert request_form_body(mock_urlopen) == {
            "grant_type": ["refresh_token"],
            "client_id": ["cid"],
            "refresh_token": ["refresh-1"],
            "client_secret": ["csecret"],
        }

    @patch(
        "direct_cli.auth.urllib.request.urlopen",
        side_effect=URLError("temporary failure in name resolution"),
    )
    def test_refresh_access_token_network_error_is_readable(
        self, mock_urlopen, isolated_auth_store
    ):
        save_oauth_profile(
            profile="agency1",
            token="access-1",
            login="client-login",
            refresh_token="refresh-1",
            expires_at=1000.0,
            client_id="cid",
        )

        with pytest.raises(RuntimeError, match="OAuth refresh request failed"):
            refresh_access_token("agency1")

    @patch(
        "direct_cli.auth.urllib.request.urlopen",
        side_effect=fake_http_error(code=500, body=b"super-secret-response"),
    )
    def test_refresh_access_token_http_error_does_not_expose_body(
        self, mock_urlopen, isolated_auth_store
    ):
        save_oauth_profile(
            profile="agency1",
            token="access-1",
            login="client-login",
            refresh_token="refresh-1",
            expires_at=1000.0,
            client_id="cid",
        )

        with pytest.raises(RuntimeError) as exc_info:
            refresh_access_token("agency1")

        assert str(exc_info.value) == "OAuth refresh request failed with HTTP 500"
        assert "super-secret-response" not in str(exc_info.value)

    @patch(
        "direct_cli.auth.urllib.request.urlopen",
        side_effect=fake_http_error(code=400, body=b"super-secret-response"),
    )
    def test_exchange_oauth_code_http_error_does_not_expose_body(self, mock_urlopen):
        with pytest.raises(RuntimeError) as exc_info:
            exchange_oauth_code(code="abc123", client_id="cid")

        assert str(exc_info.value) == "OAuth token request failed with HTTP 400"
        assert "super-secret-response" not in str(exc_info.value)

    @patch("direct_cli.commands.auth.time.time", return_value=1000.0)
    def test_auth_status_json_does_not_expose_client_secret(
        self, mock_time, isolated_auth_store
    ):
        save_oauth_profile(
            profile="agency1",
            token="access-1",
            login="client-login",
            refresh_token="refresh-1",
            expires_at=4600.0,
            client_id="cid",
            client_secret="csecret",
        )
        runner = CliRunner()

        result = runner.invoke(
            cli, ["auth", "status", "--profile", "agency1", "--format", "json"]
        )

        assert result.exit_code == 0
        assert json.loads(result.output) == {
            "profile": "agency1",
            "source": "oauth",
            "has_token": True,
            "login": "client-login",
            "expires_at": 4600.0,
            "expires_in_seconds": 3600,
        }
        assert "client_secret" not in result.output
        assert "csecret" not in result.output

    def test_auth_status_legacy_oauth_profile_fails(self, isolated_auth_store):
        save_auth_store(
            {
                "profiles": {
                    "agency1": {
                        "token": "access-1",
                        "login": "client-login",
                        "source": "oauth",
                    }
                },
                "active_profile": "agency1",
            }
        )
        runner = CliRunner()

        result = runner.invoke(cli, ["auth", "status", "--profile", "agency1"])

        assert result.exit_code != 0
        assert "Run direct auth login --profile agency1 again" in result.output

    def test_auth_login_oauth_token_mode_saves_manual_profile(
        self, isolated_auth_store
    ):
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
        profile = load_auth_store()["profiles"]["agency1"]
        assert profile["source"] == "manual"
        assert "refresh_token" not in profile
