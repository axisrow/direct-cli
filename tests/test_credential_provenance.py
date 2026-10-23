"""Credential provenance: inherited global profile visibility (issue #904).

In a folder with no explicit binding (cwd ``.env``, ``--profile``, base env)
the CLI silently resolves credentials from the global active profile
(``~/.direct-cli/auth.json``, issue #489). These tests pin the variant-1
contract from #904: ``auth status`` labels that state
``global-profile-inherited`` (text and JSON), and mutating commands warn on
stderr. Explicit binding (``.env`` / ``--token`` / ``--profile``) stays
exactly as before, and ``--dry-run`` / read-only commands stay silent.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from direct_cli.auth import (
    DEFAULT_OAUTH_CLIENT_ID,
    save_oauth_profile,
    set_active_profile,
)
from direct_cli.cli import cli

WARNING_SNIPPET = "Credentials inherited from global profile"


@pytest.fixture
def unbound_folder(monkeypatch, tmp_path):
    """Isolated auth store, tmp cwd without ``.env``, no base env tokens."""
    monkeypatch.setattr("direct_cli.auth.AUTH_STORE_PATH", tmp_path / "auth.json")
    monkeypatch.delenv("YANDEX_DIRECT_TOKEN", raising=False)
    monkeypatch.delenv("YANDEX_DIRECT_LOGIN", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _save_active_oauth_profile(profile="agency1", login="client-login-1"):
    save_oauth_profile(
        profile=profile,
        token="oauth-token-1",
        login=login,
        refresh_token="refresh-1",
        expires_at=4_100_000_000.0,
        client_id=DEFAULT_OAUTH_CLIENT_ID,
    )
    set_active_profile(profile)


def _fake_mutation_client():
    client = MagicMock()
    client.bids.return_value.post.return_value.return_value.extract.return_value = {
        "Results": []
    }
    return client


def _invoke_set_bids(*extra):
    return CliRunner().invoke(
        cli, ["bids", "set", "--campaign-id", "123", "--bid", "1000000", *extra]
    )


def _invoke_set_bids_with_input(stdin):
    return CliRunner().invoke(
        cli, ["bids", "set", "--campaign-id", "123", "--bid", "1000000"], input=stdin
    )


class TestAuthStatusInheritedSource:
    @patch("direct_cli.commands.auth.time.time", return_value=1000.0)
    def test_status_json_marks_global_profile_inherited(
        self, _mock_time, unbound_folder
    ):
        _save_active_oauth_profile("agency1", "client-login-1")

        result = CliRunner().invoke(cli, ["auth", "status", "--format", "json"])

        assert result.exit_code == 0
        assert json.loads(result.output) == {
            "profile": "agency1",
            "source": "global-profile-inherited",
            "has_token": True,
            "login": "client-login-1",
            "expires_at": 4_100_000_000.0,
            "expires_in_seconds": 4099999000,
        }

    def test_status_text_marks_global_profile_inherited(self, unbound_folder):
        _save_active_oauth_profile("agency1", "client-login-1")

        result = CliRunner().invoke(cli, ["auth", "status"])

        assert result.exit_code == 0
        assert "profile=agency1" in result.output
        assert "source=global-profile-inherited" in result.output
        assert "login=client-login-1" in result.output

    def test_status_explicit_profile_still_reports_oauth(self, unbound_folder):
        _save_active_oauth_profile("agency1", "client-login-1")

        result = CliRunner().invoke(
            cli, ["auth", "status", "--profile", "agency1", "--format", "json"]
        )

        assert result.exit_code == 0
        assert json.loads(result.output)["source"] == "oauth"

    def test_status_cwd_dotenv_still_reports_env(self, unbound_folder):
        _save_active_oauth_profile("agency1", "client-login-1")
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


class TestMutationFailClosedNonInteractive:
    def test_bids_set_fails_closed_with_inherited_credentials(self, unbound_folder):
        _save_active_oauth_profile("agency1", "client-login-1")

        with patch("direct_cli.commands.bids.create_client") as create_client:
            result = _invoke_set_bids()

        assert result.exit_code != 0
        assert "Refusing to run mutating command" in result.output
        assert "bids.set" in result.output
        assert "agency1" in result.output
        assert "client-login-1" in result.output
        assert "YANDEX_DIRECT_INHERIT_GLOBAL=1" in result.output
        # Fail-closed happens before the request is built: no API call.
        create_client.assert_not_called()

    def test_readonly_changes_check_warns_and_runs(self, unbound_folder):
        # `changes check` is a read-only call whose create_client is re-read
        # per invocation, so the mock keeps the test fully offline.
        _save_active_oauth_profile("agency1", "client-login-1")
        client = MagicMock()
        client.changes.return_value.post.return_value.data = {"ok": True}

        with patch("direct_cli.commands.changes.create_client", return_value=client):
            result = CliRunner().invoke(
                cli,
                [
                    "changes",
                    "check",
                    "--timestamp",
                    "2026-05-21T12:00:00Z",
                    "--campaign-ids",
                    "123",
                ],
            )

        assert result.exit_code == 0, result.output
        assert WARNING_SNIPPET in result.stderr
        assert "agency1" in result.stderr
        assert "client-login-1" in result.stderr

    def test_dry_run_mutation_stays_silent(self, unbound_folder):
        _save_active_oauth_profile("agency1", "client-login-1")

        with patch("direct_cli.commands.bids.create_client") as create_client:
            result = _invoke_set_bids("--dry-run")

        assert result.exit_code == 0, result.output
        assert WARNING_SNIPPET not in result.stderr
        create_client.assert_not_called()

    def test_sandbox_flag_does_not_bypass_fail_closed(self, unbound_folder):
        _save_active_oauth_profile("agency1", "client-login-1")

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
        assert "Refusing to run mutating command" in result.output
        create_client.assert_not_called()

    def test_inherit_global_env_restores_silent_behavior(
        self, unbound_folder, monkeypatch
    ):
        _save_active_oauth_profile("agency1", "client-login-1")
        monkeypatch.setenv("YANDEX_DIRECT_INHERIT_GLOBAL", "1")

        with patch(
            "direct_cli.commands.bids.create_client",
            return_value=_fake_mutation_client(),
        ):
            result = _invoke_set_bids()

        assert result.exit_code == 0, result.output
        assert WARNING_SNIPPET not in result.stderr

    def test_cwd_dotenv_binding_no_warning(self, unbound_folder):
        _save_active_oauth_profile("agency1", "client-login-1")
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
        assert WARNING_SNIPPET not in result.stderr

    def test_explicit_token_no_warning(self, unbound_folder):
        _save_active_oauth_profile("agency1", "client-login-1")

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
        assert WARNING_SNIPPET not in result.stderr


class TestInteractiveConfirm:
    def test_confirm_yes_runs_command_silently(self, unbound_folder, monkeypatch):
        _save_active_oauth_profile("agency1", "client-login-1")
        monkeypatch.setattr("direct_cli.cli._interactive_streams", lambda: True)

        with patch(
            "direct_cli.commands.bids.create_client",
            return_value=_fake_mutation_client(),
        ) as create_client:
            result = _invoke_set_bids_with_input("y\n")

        assert result.exit_code == 0, result.output
        assert "use these inherited credentials?" in result.output
        assert WARNING_SNIPPET not in result.stderr
        create_client.assert_called_once()

    def test_confirm_no_exits_with_binding_hints(self, unbound_folder, monkeypatch):
        _save_active_oauth_profile("agency1", "client-login-1")
        monkeypatch.setattr("direct_cli.cli._interactive_streams", lambda: True)

        with patch("direct_cli.commands.bids.create_client") as create_client:
            result = _invoke_set_bids_with_input("n\n")

        assert result.exit_code != 0
        assert "direct auth login" in result.output
        assert "YANDEX_DIRECT_TOKEN" in result.output
        create_client.assert_not_called()
