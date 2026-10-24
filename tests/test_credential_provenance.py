"""Credential binding gate: no silent inheritance of the global profile (#904).

A folder with no explicit binding (cwd ``.env``, ``--profile``, base env) has
no credentials of its own. These tests pin the contract:

- non-interactive sessions fail closed with binding hints (read-only and
  mutating commands alike), and `direct auth write --profile NAME` binds a
  folder without any prompts;
- terminal sessions fail the same way; only explicit auth login asks questions;
- ``--dry-run`` (no API call) stays silent;
- ``YANDEX_DIRECT_INHERIT_GLOBAL=1`` restores the pre-#904 silent inheritance
  (including the ``global-profile-inherited`` auth status marker);
- ``auth status`` in an unbound folder reports no credentials plus a note
  about the global profile, instead of presenting it as usable credentials.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from direct_cli.auth import (
    DEFAULT_OAUTH_CLIENT_ID,
    save_oauth_profile,
    set_active_profile,
)
from direct_cli.cli import cli

BIND_HINT_SNIPPET = "No credentials bound to this folder"


@pytest.fixture
def unbound_folder(monkeypatch, tmp_path):
    """Isolated auth store, tmp cwd without ``.env``, no base env tokens.

    Clears the suite-wide inheritance opt-in so the tests exercise the
    production default of the #904 gate.
    """
    monkeypatch.setattr("direct_cli.auth.AUTH_STORE_PATH", tmp_path / "auth.json")
    monkeypatch.delenv("YANDEX_DIRECT_TOKEN", raising=False)
    monkeypatch.delenv("YANDEX_DIRECT_LOGIN", raising=False)
    monkeypatch.delenv("YANDEX_DIRECT_INHERIT_GLOBAL", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _save_oauth_profile(profile="agency1", login="client-login-1", active=False):
    save_oauth_profile(
        profile=profile,
        token="oauth-token-1",
        login=login,
        refresh_token="refresh-1",
        expires_at=4_100_000_000.0,
        client_id=DEFAULT_OAUTH_CLIENT_ID,
    )
    if active:
        set_active_profile(profile)


def _fake_mutation_client():
    client = MagicMock()
    client.bids.return_value.post.return_value.return_value.extract.return_value = {
        "Results": []
    }
    return client


def _invoke_set_bids(*extra, **kwargs):
    return CliRunner().invoke(
        cli,
        ["bids", "set", "--campaign-id", "123", "--bid", "1000000", *extra],
        **kwargs,
    )


class TestAuthStatusUnbound:
    def test_status_json_reports_no_binding_plus_global_note(self, unbound_folder):
        _save_oauth_profile("default", "global-login", active=True)

        result = CliRunner().invoke(cli, ["auth", "status", "--format", "json"])

        assert result.exit_code == 0
        assert json.loads(result.output) == {
            "profile": None,
            "source": None,
            "has_token": False,
            "login": None,
            "global_profile": "default",
            "global_login": "global-login",
        }

    def test_status_text_reports_no_binding_plus_global_note(self, unbound_folder):
        _save_oauth_profile("default", "global-login", active=True)

        result = CliRunner().invoke(cli, ["auth", "status"])

        assert result.exit_code == 0
        assert "No credentials bound to this folder." in result.output
        assert (
            "Global profile 'default' (login=global-login) exists but is not "
            "bound here." in result.output
        )
        assert "YANDEX_DIRECT_INHERIT_GLOBAL=1" in result.output

    def test_status_opt_in_env_still_reports_inherited(
        self, unbound_folder, monkeypatch
    ):
        _save_oauth_profile("agency1", "client-login-1", active=True)
        monkeypatch.setenv("YANDEX_DIRECT_INHERIT_GLOBAL", "1")

        result = CliRunner().invoke(cli, ["auth", "status", "--format", "json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["source"] == "global-profile-inherited"
        assert payload["profile"] == "agency1"

    def test_status_explicit_profile_still_reports_oauth(self, unbound_folder):
        _save_oauth_profile("agency1", "client-login-1", active=True)

        result = CliRunner().invoke(
            cli, ["auth", "status", "--profile", "agency1", "--format", "json"]
        )

        assert result.exit_code == 0
        assert json.loads(result.output)["source"] == "oauth"

    def test_status_cwd_dotenv_still_reports_env(self, unbound_folder):
        _save_oauth_profile("agency1", "client-login-1", active=True)
        (unbound_folder / ".env").write_text(
            "YANDEX_DIRECT_TOKEN=dotenv-token\nYANDEX_DIRECT_LOGIN=dotenv-login\n",
            encoding="utf-8",
        )

        result = CliRunner().invoke(cli, ["auth", "status", "--format", "json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["source"] == "env"
        assert payload["profile"] is None
        assert "dotenv-token" not in result.output


class TestUnboundFolderGate:
    def test_non_interactive_mutation_fails_closed(self, unbound_folder):
        _save_oauth_profile("agency1", "client-login-1", active=True)

        with patch("direct_cli.commands.bids.create_client") as create_client:
            result = _invoke_set_bids()

        assert result.exit_code != 0
        assert BIND_HINT_SNIPPET in result.output
        assert "direct auth write --profile" in result.output
        assert "direct auth login" in result.output
        assert "YANDEX_DIRECT_INHERIT_GLOBAL=1" in result.output
        create_client.assert_not_called()

    def test_non_interactive_readonly_also_fails_closed(self, unbound_folder):
        _save_oauth_profile("agency1", "client-login-1", active=True)

        with patch("direct_cli.commands.changes.create_client") as create_client:
            result = CliRunner().invoke(
                cli,
                ["changes", "check", "--timestamp", "2026-05-21T12:00:00Z"],
            )

        assert result.exit_code != 0
        assert BIND_HINT_SNIPPET in result.output
        create_client.assert_not_called()

    def test_dry_run_stays_silent(self, unbound_folder):
        _save_oauth_profile("agency1", "client-login-1", active=True)

        with patch("direct_cli.commands.bids.create_client") as create_client:
            result = _invoke_set_bids("--dry-run")

        assert result.exit_code == 0, result.output
        assert BIND_HINT_SNIPPET not in result.output
        create_client.assert_not_called()

    def test_sandbox_flag_does_not_bypass_gate(self, unbound_folder):
        _save_oauth_profile("agency1", "client-login-1", active=True)

        with patch("direct_cli.commands.bids.create_client") as create_client:
            result = CliRunner().invoke(
                cli,
                [
                    "--sandbox",
                    "bids",
                    "set",
                    "--campaign-id",
                    "123",
                    "--bid",
                    "1000000",
                ],
            )

        assert result.exit_code != 0
        assert BIND_HINT_SNIPPET in result.output
        create_client.assert_not_called()

    def test_login_only_env_ref_does_not_inherit_active_profile(
        self, unbound_folder, monkeypatch
    ):
        # Regression: an exported YANDEX_DIRECT_LOGIN alone (any partial ref)
        # must not let the active-profile rung hand out its token and bypass
        # the #904 gate — a login is not a credential binding.
        _save_oauth_profile("agency1", "client-login-1")
        monkeypatch.setenv("YANDEX_DIRECT_LOGIN", "stale-login")

        with patch("direct_cli.commands.bids.create_client") as create_client:
            result = _invoke_set_bids()

        assert result.exit_code != 0
        assert BIND_HINT_SNIPPET in result.output
        assert not (unbound_folder / ".env").exists()
        create_client.assert_not_called()

    def test_inherit_global_env_restores_silent_inheritance(
        self, unbound_folder, monkeypatch
    ):
        _save_oauth_profile("agency1", "client-login-1", active=True)
        monkeypatch.setenv("YANDEX_DIRECT_INHERIT_GLOBAL", "1")

        with patch(
            "direct_cli.commands.bids.create_client",
            return_value=_fake_mutation_client(),
        ):
            result = _invoke_set_bids()

        assert result.exit_code == 0, result.output
        assert BIND_HINT_SNIPPET not in result.output
        assert not (unbound_folder / ".env").exists()

    def test_cwd_dotenv_binding_needs_no_menu(self, unbound_folder):
        _save_oauth_profile("agency1", "client-login-1", active=True)
        (unbound_folder / ".env").write_text(
            "YANDEX_DIRECT_TOKEN=dotenv-token\n",
            encoding="utf-8",
        )

        with patch(
            "direct_cli.commands.bids.create_client",
            return_value=_fake_mutation_client(),
        ):
            result = _invoke_set_bids()

        assert result.exit_code == 0, result.output
        assert BIND_HINT_SNIPPET not in result.output

    def test_explicit_token_needs_no_menu(self, unbound_folder):
        _save_oauth_profile("agency1", "client-login-1", active=True)

        with patch(
            "direct_cli.commands.bids.create_client",
            return_value=_fake_mutation_client(),
        ):
            result = CliRunner().invoke(
                cli,
                [
                    "--token",
                    "explicit-arg-token",
                    "bids",
                    "set",
                    "--campaign-id",
                    "123",
                    "--bid",
                    "1000000",
                ],
            )

        assert result.exit_code == 0, result.output
        assert BIND_HINT_SNIPPET not in result.output


class TestNoImplicitLogin:
    @pytest.mark.parametrize("terminal", [False, True])
    @pytest.mark.parametrize(
        "argv",
        [
            ["campaigns", "get"],
            ["bids", "set", "--campaign-id", "123", "--bid", "1000000"],
        ],
    )
    def test_unbound_commands_never_ask_questions(self, unbound_folder, terminal, argv):
        _save_oauth_profile("agency1", "client-login-1", active=True)
        with (
            patch("sys.stdin.isatty", return_value=terminal),
            patch("sys.stdout.isatty", return_value=terminal),
            patch("click.prompt") as prompt,
            patch("direct_cli.commands.auth.webbrowser.open") as browser,
            patch("direct_cli.commands.auth.exchange_oauth_code") as exchange,
            patch("direct_cli.commands.bids.create_client") as client,
        ):
            result = CliRunner().invoke(cli, argv)
        assert result.exit_code == 2, result.output
        assert "direct auth login --method api" in result.output
        assert not (unbound_folder / ".env").exists()
        prompt.assert_not_called()
        browser.assert_not_called()
        exchange.assert_not_called()
        client.assert_not_called()


class TestAuthWrite:
    def test_write_binds_folder_without_prompts(self, unbound_folder):
        _save_oauth_profile("agency1", "client-login-1", active=True)

        with patch.dict(os.environ):
            result = CliRunner().invoke(cli, ["auth", "write", "--profile", "agency1"])

        assert result.exit_code == 0, result.output
        assert "Bound credentials to .env (profile agency1)." in result.output
        assert "oauth-token-1" not in result.output  # токен не печатается
        dotenv = (unbound_folder / ".env").read_text(encoding="utf-8")
        assert "oauth-token-1" in dotenv
        assert "client-login-1" in dotenv

    def test_write_merges_with_existing_dotenv(self, unbound_folder):
        _save_oauth_profile("agency1", "client-login-1")
        (unbound_folder / ".env").write_text(
            "OTHER=value\nYANDEX_DIRECT_TOKEN=old-token\n", encoding="utf-8"
        )

        with patch.dict(os.environ):
            result = CliRunner().invoke(cli, ["auth", "write", "--profile", "agency1"])

        assert result.exit_code == 0, result.output
        dotenv = (unbound_folder / ".env").read_text(encoding="utf-8")
        assert "OTHER=value" in dotenv
        assert "oauth-token-1" in dotenv
        assert "old-token" not in dotenv

    def test_write_unknown_profile_fails(self, unbound_folder):
        result = CliRunner().invoke(cli, ["auth", "write", "--profile", "nope"])

        assert result.exit_code != 0
        assert "Profile 'nope'" in result.output
        assert not (unbound_folder / ".env").exists()

    def test_write_requires_explicit_profile(self, unbound_folder):
        _save_oauth_profile("agency1", "client-login-1", active=True)

        result = CliRunner().invoke(cli, ["auth", "write"])

        assert result.exit_code != 0
        assert not (unbound_folder / ".env").exists()

    def test_write_enables_api_command_without_menu(self, unbound_folder):
        _save_oauth_profile("agency1", "client-login-1", active=True)
        with patch.dict(os.environ):
            CliRunner().invoke(cli, ["auth", "write", "--profile", "agency1"])

        with (
            patch.dict(os.environ),
            patch(
                "direct_cli.commands.bids.create_client",
                return_value=_fake_mutation_client(),
            ) as create_client,
        ):
            result = _invoke_set_bids()

        assert result.exit_code == 0, result.output
        create_client.assert_called_once()

    def test_pick_profile_overrides_exported_stale_login(
        self, unbound_folder, monkeypatch
    ):
        # A shell-exported YANDEX_DIRECT_LOGIN must not survive the bind:
        # load_dotenv never overrides set variables, so the re-export in
        # bind_profile_to_dotenv is what makes the running command use the
        # freshly picked profile's login.
        _save_oauth_profile("agency1", "client-login-1")
        monkeypatch.setattr(
            "direct_cli.commands.auth._stdin_is_interactive", lambda: True
        )
        monkeypatch.setenv("YANDEX_DIRECT_LOGIN", "stale-login")

        with (
            patch.dict(os.environ),
            patch(
                "direct_cli.commands.bids.create_client",
                return_value=_fake_mutation_client(),
            ) as create_client,
        ):
            result = CliRunner().invoke(
                cli, ["auth", "login", "--method", "api", "--interactive"], input="1\n"
            )
            assert result.exit_code == 0, result.output
            result = _invoke_set_bids()

        assert result.exit_code == 0, result.output
        create_client.assert_called_once()
        assert create_client.call_args.kwargs["login"] == "client-login-1"
