"""Unified auth entrypoints and the no-implicit-login boundary."""

import ast
import contextlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner

import direct_cli
from direct_cli.auth import (
    get_oauth_profile,
    load_auth_store,
    save_oauth_profile,
    save_pending_pkce,
    save_env_credentials,
)
from direct_cli.browser import session, store
from direct_cli.cli import cli


@pytest.fixture
def auth_env(monkeypatch, tmp_path):
    for name in tuple(os.environ):
        if name.startswith("YANDEX_DIRECT_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("YANDEX_DIRECT_CLI_LOCALE", "en")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("direct_cli.auth.AUTH_STORE_PATH", tmp_path / "auth.json")
    monkeypatch.setattr(session, "DEFAULT_PERSISTENT_PROFILE_DIR", tmp_path / "browser")
    monkeypatch.setattr(session, "PROFILE_POINTER_PATH", tmp_path / "browser-path")
    monkeypatch.setattr(store, "PLAYWRIGHT_SESSION_PATH", tmp_path / "session.json")
    return tmp_path


@pytest.fixture
def interactive(monkeypatch):
    monkeypatch.setattr("direct_cli.commands.auth._stdin_is_interactive", lambda: True)
    browser = Mock()
    monkeypatch.setattr("direct_cli.commands.auth.webbrowser.open", browser)
    return browser


def save_profile(name="account", token="stored-token", active=False):
    save_oauth_profile(name, token, login=name, source="manual", make_active=active)


@pytest.mark.parametrize("argv", [["login"], ["login", "api"]])
def test_login_without_a_terminal_starts_headless(auth_env, monkeypatch, argv):
    monkeypatch.setattr("direct_cli.commands.auth._stdin_is_interactive", lambda: False)
    prompt, confirm, browser = Mock(), Mock(), Mock()
    monkeypatch.setattr("click.prompt", prompt)
    monkeypatch.setattr("click.confirm", confirm)
    monkeypatch.setattr("direct_cli.commands.auth.webbrowser.open", browser)
    result = CliRunner().invoke(cli, ["auth", *argv])
    assert result.exit_code == 0, result.output
    assert "oauth.yandex.ru/authorize" in result.stdout
    assert not (auth_env / ".env").exists()
    prompt.assert_not_called()
    confirm.assert_not_called()
    browser.assert_not_called()


def test_login_in_a_terminal_is_interactive_by_default(
    auth_env, interactive, monkeypatch
):
    prompt = Mock(return_value="code")
    monkeypatch.setattr("click.prompt", prompt)
    exchange = Mock(
        return_value={
            "access_token": "fresh-token",
            "refresh_token": "r",
            "expires_in": 3600,
        }
    )
    monkeypatch.setattr("direct_cli.commands.auth.exchange_oauth_code", exchange)
    monkeypatch.setattr(
        "direct_cli.commands.auth.resolve_account_login", lambda _: "account"
    )
    result = CliRunner().invoke(cli, ["auth", "login", "api"], input="code\n")
    assert result.exit_code == 0, result.output
    prompt.assert_called_once()
    interactive.assert_called_once()
    assert "fresh-token" in (auth_env / ".env").read_text()


def test_scripted_inputs_stay_headless_in_a_terminal(
    auth_env, interactive, monkeypatch
):
    prompt = Mock()
    monkeypatch.setattr("click.prompt", prompt)
    runner = CliRunner()
    json_start = runner.invoke(cli, ["auth", "login", "api", "--format", "json"])
    assert json_start.exit_code == 0, json_start.output
    assert "authorize_url" in json.loads(json_start.stdout)
    pkce_start = runner.invoke(cli, ["auth", "login", "api", "--start-pkce"])
    assert pkce_start.exit_code == 0, pkce_start.output
    code_stdin = runner.invoke(
        cli, ["auth", "login", "api", "--code", "-"], input="code\n"
    )
    assert code_stdin.exit_code != 0  # no pending/remembered PKCE to finish it
    prompt.assert_not_called()
    interactive.assert_not_called()


def test_headless_code_completion_refuses_to_overwrite_an_existing_profile(
    auth_env, monkeypatch
):
    save_profile("default", token="stored-token")
    exchange = Mock()
    monkeypatch.setattr("direct_cli.commands.auth.exchange_oauth_code", exchange)
    result = CliRunner().invoke(cli, ["auth", "login", "--code", "some-code"])
    assert result.exit_code == 2, result.output
    assert "already exists" in result.output
    assert "--force" in result.output
    assert "(login=default)" in result.output
    exchange.assert_not_called()


def test_oauth_token_import_refuses_to_overwrite_an_existing_profile(
    auth_env, monkeypatch
):
    save_profile("default", token="stored-token")
    resolve = Mock()
    monkeypatch.setattr("direct_cli.commands.auth.resolve_account_login", resolve)
    result = CliRunner().invoke(cli, ["auth", "login", "--oauth-token", "tok"])
    assert result.exit_code == 2, result.output
    assert "--force" in result.output
    resolve.assert_not_called()


def test_force_overwrites_an_existing_profile(auth_env, monkeypatch):
    save_profile("default", token="stored-token")
    save_pending_pkce("default", "cid", "verifier", "account")
    monkeypatch.setattr(
        "direct_cli.commands.auth.exchange_oauth_code",
        Mock(
            return_value={
                "access_token": "new-token",
                "refresh_token": "new-refresh",
                "expires_in": 3600,
            }
        ),
    )
    result = CliRunner().invoke(cli, ["auth", "login", "--code", "c", "--force"])
    assert result.exit_code == 0, result.output
    profile = get_oauth_profile("default")
    assert profile is not None and profile["token"] == "new-token"


def test_completion_into_a_fresh_profile_name_needs_no_force(auth_env, monkeypatch):
    save_profile("default", token="stored-token")
    save_pending_pkce("fresh", "cid", "verifier", "fresh-login")
    monkeypatch.setattr(
        "direct_cli.commands.auth.exchange_oauth_code",
        Mock(
            return_value={
                "access_token": "fresh-token",
                "refresh_token": "r",
                "expires_in": 3600,
            }
        ),
    )
    result = CliRunner().invoke(
        cli, ["auth", "login", "--code", "c", "--profile", "fresh"]
    )
    assert result.exit_code == 0, result.output
    fresh = get_oauth_profile("fresh")
    assert fresh is not None and fresh["token"] == "fresh-token"
    default_profile = get_oauth_profile("default")
    assert default_profile is not None and default_profile["token"] == "stored-token"


def test_save_oauth_profile_refuses_to_overwrite_without_explicit_flag(auth_env):
    save_profile("account", token="stored-token")
    with pytest.raises(ValueError, match="already exists"):
        save_oauth_profile("account", "new-token", login="account")
    stored = get_oauth_profile("account")
    assert stored is not None and stored["token"] == "stored-token"
    save_oauth_profile(
        "account", "new-token", login="account", source="manual", overwrite=True
    )
    overwritten = get_oauth_profile("account")
    assert overwritten is not None and overwritten["token"] == "new-token"


def test_save_env_credentials_warns_when_replacing_existing_token(auth_env, capsys):
    (auth_env / ".env").write_text(
        "YANDEX_DIRECT_TOKEN=old-token\nYANDEX_DIRECT_LOGIN=old-login\n"
    )
    save_env_credentials(token="new-token", login="new-login")
    err = capsys.readouterr().err
    assert "YANDEX_DIRECT_TOKEN" in err
    assert "old-login" in err


def test_save_env_credentials_is_silent_for_a_fresh_binding(auth_env, capsys):
    save_env_credentials(token="new-token", login="new-login")
    assert "YANDEX" not in capsys.readouterr().err


def test_interactive_explicit_profile_refuses_to_overwrite_without_force(
    auth_env, interactive, monkeypatch
):
    save_profile("agency1", token="stored-token")
    monkeypatch.setattr(
        "direct_cli.commands.auth.exchange_oauth_code",
        Mock(
            return_value={
                "access_token": "hijacked-token",
                "refresh_token": "r",
                "expires_in": 3600,
            }
        ),
    )
    result = CliRunner().invoke(
        cli, ["auth", "login", "api", "--profile", "agency1"], input="code\n"
    )
    assert result.exit_code == 2, result.output
    assert "already exists" in result.output
    assert "--force" in result.output


def test_force_is_not_a_browser_login_option(auth_env, monkeypatch):
    browser_import = Mock()
    monkeypatch.setattr(
        "direct_cli.commands.auth.import_browser_session", browser_import
    )
    result = CliRunner().invoke(
        cli, ["auth", "login", "browser", "--source", "chrome", "--force"]
    )
    assert result.exit_code == 2, result.output
    browser_import.assert_not_called()


def test_api_menu_reuses_profile_and_binds_without_confirmation(
    auth_env, interactive, monkeypatch
):
    save_profile()
    (auth_env / ".env").write_text("OTHER=keep\n")
    confirm = Mock()
    monkeypatch.setattr("click.confirm", confirm)
    result = CliRunner().invoke(cli, ["auth", "login", "api"], input="1\n")
    assert result.exit_code == 0, result.output
    assert "1) account" in result.output
    assert "1) API" not in result.output  # the method-choice menu is gone
    assert "OTHER=keep" in (auth_env / ".env").read_text()
    assert "YANDEX_DIRECT_TOKEN=stored-token" in (auth_env / ".env").read_text()
    assert "stored-token" not in result.output
    confirm.assert_not_called()
    interactive.assert_not_called()


@pytest.mark.parametrize("existing", [False, True])
def test_new_api_profile_is_named_without_overwriting_an_existing_profile(
    auth_env, interactive, monkeypatch, existing
):
    if existing:
        save_profile("account", "old-token", active=True)
    exchange = Mock(
        return_value={
            "access_token": "fresh-token",
            "refresh_token": "refresh",
            "expires_in": 3600,
        }
    )
    monkeypatch.setattr("direct_cli.commands.auth.exchange_oauth_code", exchange)
    monkeypatch.setattr(
        "direct_cli.commands.auth.resolve_account_login", lambda _: "account"
    )
    result = CliRunner().invoke(
        cli,
        ["auth", "login", "api"],
        input=("0\n" if existing else "") + "secret-code\n",
    )
    assert result.exit_code == 0, result.output
    name = "account-2" if existing else "account"
    saved = get_oauth_profile(name)
    assert saved is not None and saved["token"] == "fresh-token"
    assert "fresh-token" in (auth_env / ".env").read_text()
    assert "secret-code" not in result.output
    interactive.assert_called_once()
    if existing:
        original = get_oauth_profile("account")
        assert original is not None and original["token"] == "old-token"
        assert load_auth_store()["active_profile"] == "account"


def test_failed_api_login_preserves_binding(auth_env, interactive, monkeypatch):
    env = auth_env / ".env"
    env.write_text("OTHER=keep\nYANDEX_DIRECT_TOKEN=previous\n")
    monkeypatch.setattr(
        "direct_cli.commands.auth.exchange_oauth_code",
        Mock(side_effect=RuntimeError("invalid code")),
    )
    result = CliRunner().invoke(cli, ["auth", "login", "api"], input="code\n")
    assert result.exit_code != 0
    assert "invalid code" in result.output
    assert env.read_text() == "OTHER=keep\nYANDEX_DIRECT_TOKEN=previous\n"
    assert load_auth_store()["profiles"] == {}


def test_cancelled_profile_menu_does_not_write_credentials(auth_env, interactive):
    save_profile()
    result = CliRunner().invoke(cli, ["auth", "login", "api"], input="")
    assert result.exit_code != 0
    assert not (auth_env / ".env").exists()
    stored = get_oauth_profile("account")
    assert stored is not None and stored["token"] == "stored-token"
    interactive.assert_not_called()


def test_api_profile_selection_needs_no_browser_dependencies(
    auth_env, interactive, monkeypatch
):
    save_profile()
    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    result = CliRunner().invoke(cli, ["auth", "login", "api"], input="1\n")
    assert result.exit_code == 0, result.output
    assert "stored-token" in (auth_env / ".env").read_text()


def test_json_api_start_never_prompts_even_in_terminal(
    auth_env, interactive, monkeypatch
):
    prompt = Mock()
    monkeypatch.setattr("click.prompt", prompt)
    result = CliRunner().invoke(cli, ["auth", "login", "api", "--format", "json"])
    assert result.exit_code == 0, result.output
    assert "authorize_url" in json.loads(result.stdout)
    prompt.assert_not_called()
    interactive.assert_not_called()


def test_manual_browser_login_opens_the_persistent_window(
    auth_env, interactive, monkeypatch
):
    login = Mock()
    monkeypatch.setattr(session, "login_persistent_session", login)
    result = CliRunner().invoke(cli, ["auth", "login", "browser"])
    assert result.exit_code == 0, result.output
    login.assert_called_once_with(profile_dir=None, timeout_ms=300_000, headless=False)
    assert not (auth_env / ".env").exists()
    assert not (auth_env / "auth.json").exists()


def test_browser_login_without_tty_fails_without_launching(auth_env, monkeypatch):
    monkeypatch.setattr("direct_cli.commands.auth._stdin_is_interactive", lambda: False)
    login = Mock()
    monkeypatch.setattr(session, "login_persistent_session", login)
    result = CliRunner().invoke(cli, ["auth", "login", "browser"])
    assert result.exit_code != 0
    assert "interactive terminal" in result.output
    assert "direct auth login browser" in result.output
    login.assert_not_called()


@pytest.mark.parametrize(
    "arguments",
    [
        ["browser", "--chrome-profile", "Profile 1"],
        ["browser", "--no-verify"],
        ["browser", "--source", "chrome", "--timeout", "5"],
        ["browser", "--source", "chrome", "--allow-no-tty"],
        ["api", "--source", "chrome"],
        ["api", "--profile-dir", "/unused"],
    ],
)
def test_incompatible_login_options_fail_before_login(
    auth_env, interactive, monkeypatch, arguments
):
    login = Mock()
    exchange = Mock()
    monkeypatch.setattr(session, "login_persistent_session", login)
    monkeypatch.setattr("direct_cli.commands.auth.exchange_oauth_code", exchange)
    result = CliRunner().invoke(cli, ["auth", "login", *arguments])
    assert result.exit_code == 2, result.output
    login.assert_not_called()
    exchange.assert_not_called()
    interactive.assert_not_called()


@pytest.mark.parametrize(
    "verb,method,replacement",
    [
        ("login", "api", "direct auth login api"),
        ("login", "browser", "direct auth login browser"),
        ("status", "api", "direct auth status api"),
        ("status", "browser", "direct auth status browser"),
        ("status", "all", "direct auth status"),
        ("logout", "api", "direct auth logout api"),
        ("logout", "browser", "direct auth logout browser"),
    ],
)
def test_removed_method_flag_names_the_exact_replacement(
    auth_env, verb, method, replacement
):
    result = CliRunner().invoke(cli, ["auth", verb, "--method", method])
    assert result.exit_code == 2, result.output
    assert "--method was removed" in result.output
    assert replacement in result.output


@pytest.mark.parametrize("arguments", [["--interactive"], ["--headful"]])
def test_removed_ui_flags_without_a_domain_name_both_commands(auth_env, arguments):
    result = CliRunner().invoke(cli, ["auth", "login", *arguments])
    assert result.exit_code == 2, result.output
    assert "direct auth login api" in result.output
    assert "direct auth login browser" in result.output


@pytest.mark.parametrize(
    "domain,arguments",
    [
        ("api", ["api", "--interactive"]),
        ("api", ["api", "--headful"]),
        ("browser", ["browser", "--interactive"]),
        ("browser", ["browser", "--headful"]),
    ],
)
def test_removed_ui_flags_on_a_domain_advise_that_domain(auth_env, domain, arguments):
    result = CliRunner().invoke(cli, ["auth", "login", *arguments])
    assert result.exit_code == 2, result.output
    assert f"direct auth login {domain}" in result.output


def test_profile_flag_is_ignored_with_a_note_in_the_browser_domain(auth_env):
    capture = Mock(
        return_value=(
            {"cookies": [{"domain": ".yandex.ru", "value": "secret"}], "origins": []},
            {"verified": False},
        )
    )
    monkey_target = "direct_cli.browser.session.capture_storage_state"
    with patch(monkey_target, capture):
        result = CliRunner().invoke(
            cli,
            ["auth", "login", "browser", "--source", "chrome", "--profile", "x"],
        )
    assert result.exit_code == 0, result.output
    assert "--profile" in result.output and "ignored" in result.output
    result = CliRunner().invoke(cli, ["auth", "status", "browser", "--profile", "x"])
    assert result.exit_code == 0, result.output
    assert "--profile" in result.output and "ignored" in result.output


def test_profile_flag_is_silent_in_the_api_domain(auth_env, monkeypatch):
    monkeypatch.setattr("direct_cli.commands.auth._stdin_is_interactive", lambda: False)
    result = CliRunner().invoke(cli, ["auth", "login", "api", "--profile", "fresh"])
    assert result.exit_code == 0, result.output
    assert "ignored" not in result.output


def test_chrome_import_is_explicit_and_keeps_legacy_json(auth_env, monkeypatch):
    capture = Mock(
        return_value=(
            {"cookies": [{"domain": ".yandex.ru", "value": "secret"}], "origins": []},
            {"verified": True},
        )
    )
    monkeypatch.setattr(session, "capture_storage_state", capture)
    args = [
        "--profile-dir",
        str(auth_env / "chrome"),
        "--chrome-profile",
        "Profile 1",
        "--format",
        "json",
    ]
    runner = CliRunner()
    canonical = runner.invoke(
        cli, ["auth", "login", "browser", "--source", "chrome", *args]
    )
    legacy = runner.invoke(cli, ["playwright", "login", *args])
    assert canonical.exit_code == legacy.exit_code == 0, (
        canonical.output + legacy.output
    )
    assert json.loads(canonical.stdout) == json.loads(legacy.stdout)
    assert "secret" not in canonical.stdout + legacy.stdout
    assert "Deprecated" in legacy.stderr


@pytest.mark.parametrize(
    "argv", [["masters", "list"], ["history", "get"], ["adrestrictions", "123"]]
)
@pytest.mark.parametrize("expired", [None, True])
def test_browser_commands_never_import_or_log_in(auth_env, monkeypatch, argv, expired):
    if expired:
        store.save_session({"cookies": [{"expires": 1}], "origins": []})
    import_cookies, login, decrypt, opener = Mock(), Mock(), Mock(), Mock()
    monkeypatch.setattr(session, "capture_storage_state", import_cookies)
    monkeypatch.setattr(session, "login_persistent_session", login)
    monkeypatch.setattr(session, "open_chrome_session", opener)
    monkeypatch.setattr("direct_cli.browser._chrome_crypto.get_encryption_key", decrypt)
    result = CliRunner().invoke(cli, argv)
    assert result.exit_code != 0
    assert "direct auth login browser" in result.output, result.output
    for operation in (import_cookies, login, decrypt, opener):
        operation.assert_not_called()


def test_invalid_saved_session_does_not_repeat_operation(auth_env, monkeypatch):
    store.save_session({"cookies": [], "origins": []})

    @contextlib.contextmanager
    def saved(**kwargs):
        yield object()

    monkeypatch.setattr(session, "open_saved_session", saved)
    fresh = Mock()
    monkeypatch.setattr(session, "open_chrome_session", fresh)
    operation = Mock(side_effect=session.BrowserAuthError("expired server-side"))
    monkeypatch.setattr("direct_cli.browser.masters.fetch_masters_list", operation)
    result = CliRunner().invoke(cli, ["masters", "list"])
    assert result.exit_code != 0
    assert "direct auth login browser" in result.output
    operation.assert_called_once()
    fresh.assert_not_called()


@pytest.mark.parametrize(
    "flag,value", [("--profile-dir", "/unused"), ("--chrome-profile", "Default")]
)
def test_resource_chrome_flags_have_migration_error(auth_env, monkeypatch, flag, value):
    key = Mock()
    monkeypatch.setattr("direct_cli.browser._chrome_crypto.get_encryption_key", key)
    result = CliRunner().invoke(cli, ["masters", "list", flag, value])
    assert result.exit_code == 2
    assert "direct auth login browser --source chrome" in result.output
    key.assert_not_called()


def test_status_defaults_to_both_domains(auth_env):
    save_profile()
    runner = CliRunner()
    api = runner.invoke(
        cli, ["auth", "status", "api", "--profile", "account", "--format", "json"]
    )
    browser = runner.invoke(cli, ["masters", "status", "--format", "json"])
    both = runner.invoke(
        cli,
        ["auth", "status", "--profile", "account", "--format", "json"],
    )
    assert api.exit_code == browser.exit_code == both.exit_code == 0
    assert json.loads(both.stdout) == {
        "api": json.loads(api.stdout),
        "browser": json.loads(browser.stdout),
    }
    assert json.loads(browser.stdout)["active_source"] is None


def test_api_logout_clears_only_current_binding_and_selected_profile(auth_env):
    save_profile("account", active=True)
    save_profile("other")
    save_pending_pkce("account", "cid", "verifier", "challenge")
    env = auth_env / ".env"
    env.write_text(
        "OTHER=keep\nYANDEX_DIRECT_TOKEN = secret\n"
        "export YANDEX_DIRECT_LOGIN = account\n"
        "YANDEX_DIRECT_OP_TOKEN_REF=op://vault/item/token\n"
        "YANDEX_DIRECT_BW_TOKEN_REF=previous-account\n"
        "YANDEX_DIRECT_INHERIT_GLOBAL=1\n"
    )
    result = CliRunner().invoke(cli, ["auth", "logout", "api", "--profile", "account"])
    assert result.exit_code == 0, result.output
    assert env.read_text() == "OTHER=keep\n"
    data = load_auth_store()
    assert set(data["profiles"]) == {"other"}
    assert data["active_profile"] is None
    assert "account" not in data["pending_pkce"]
    assert "secret" not in result.output


def test_failed_dotenv_write_keeps_original_file(auth_env, monkeypatch):
    env = auth_env / ".env"
    env.write_text("OTHER=keep\nYANDEX_DIRECT_TOKEN=original\n")
    monkeypatch.setattr(
        "direct_cli.auth.os.replace", Mock(side_effect=OSError("write failed"))
    )
    with pytest.raises(OSError, match="write failed"):
        save_env_credentials("replacement")
    assert env.read_text() == "OTHER=keep\nYANDEX_DIRECT_TOKEN=original\n"
    assert not list(auth_env.glob(".direct-env-*"))


def test_doctor_understands_persistent_session_without_chrome_import(
    auth_env, monkeypatch
):
    from direct_cli.browser import diagnostics

    profile = session.DEFAULT_PERSISTENT_PROFILE_DIR
    (profile / "Default").mkdir(parents=True)
    (profile / "Default" / "Cookies").touch()
    monkeypatch.setattr(
        diagnostics,
        "_check_chromium_downloaded",
        lambda: diagnostics.Check("chromium_downloaded", True, "installed"),
    )
    monkeypatch.setattr(
        diagnostics,
        "_check_module_installed",
        lambda name, label: diagnostics.Check(f"{name}_installed", True, "installed"),
    )
    key = Mock()
    monkeypatch.setattr("direct_cli.browser._chrome_crypto.get_encryption_key", key)
    result = CliRunner().invoke(cli, ["auth", "doctor", "--format", "json"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["ok"] is True
    saved = next(
        check for check in report["checks"] if check["name"] == "saved_session"
    )
    assert saved["ok"] is True and str(profile) in saved["detail"]
    key.assert_not_called()


def test_api_logout_requires_explicit_profile(auth_env):
    save_profile()
    result = CliRunner().invoke(cli, ["auth", "logout", "api"])
    assert result.exit_code == 2
    assert get_oauth_profile("account") is not None


def test_api_logout_rejects_symlinked_dotenv_before_removing_profile(auth_env):
    save_profile()
    target = auth_env / "external.env"
    target.write_text("YANDEX_DIRECT_TOKEN=secret\n")
    (auth_env / ".env").symlink_to(target)
    result = CliRunner().invoke(cli, ["auth", "logout", "api", "--profile", "account"])
    assert result.exit_code != 0
    assert get_oauth_profile("account") is not None
    assert target.read_text() == "YANDEX_DIRECT_TOKEN=secret\n"


def test_browser_logout_forgets_both_cli_sessions(auth_env):
    profile = session.DEFAULT_PERSISTENT_PROFILE_DIR
    profile.mkdir()
    (profile / session.PROFILE_MARKER_NAME).touch()
    session.remember_persistent_profile_dir(profile)
    store.save_session({"cookies": [], "origins": []})
    result = CliRunner().invoke(cli, ["auth", "logout", "browser"])
    assert result.exit_code == 0, result.output
    assert not profile.exists()
    assert not session.PROFILE_POINTER_PATH.exists()
    assert not store.PLAYWRIGHT_SESSION_PATH.exists()


def test_browser_logout_cannot_fall_back_to_old_default_profile(auth_env):
    default = session.DEFAULT_PERSISTENT_PROFILE_DIR
    custom = auth_env / "custom-browser"
    for profile in (default, custom):
        (profile / "Default").mkdir(parents=True)
        (profile / session.PROFILE_MARKER_NAME).touch()
        (profile / "Default" / "Cookies").touch()
    session.remember_persistent_profile_dir(custom)
    result = CliRunner().invoke(cli, ["auth", "logout", "browser"])
    assert result.exit_code == 0, result.output
    assert not default.exists() and not custom.exists()
    status = CliRunner().invoke(cli, ["auth", "status", "browser", "--format", "json"])
    assert json.loads(status.stdout)["active_source"] is None


def test_browser_logout_refuses_unowned_profile_without_deleting_saved_session(
    auth_env,
):
    session.DEFAULT_PERSISTENT_PROFILE_DIR.mkdir()
    store.save_session({"cookies": [], "origins": []})
    result = CliRunner().invoke(cli, ["auth", "logout", "browser"])
    assert result.exit_code != 0
    assert "marker" in result.output
    assert session.DEFAULT_PERSISTENT_PROFILE_DIR.exists()
    assert store.PLAYWRIGHT_SESSION_PATH.exists()


# Issue #924: every auth error and deprecation notice must advise exactly one
# canonical login command, imported from ``direct_cli/_auth_hints.py``. A
# hand-written literal (``direct auth login …`` / ``direct playwright login
# …``) is how one error ended up printing four contradictory suggestions, so
# the guard below bans those substrings in ANY string literal outside the
# constants module — including Click help/docstrings, which do reach users.
_BANNED_LOGIN_HINTS = ("direct auth login", "direct playwright login")


def _banned_login_hint_literals(source: str) -> list[tuple[int, str]]:
    """Return (lineno, text) for every string literal that advises a login."""
    offenders = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
            if any(banned in text for banned in _BANNED_LOGIN_HINTS):
                offenders.append((node.lineno, text))
    return offenders


def test_no_literal_login_hints_outside_auth_hints():
    package_dir = Path(direct_cli.__file__).parent
    offenders = []
    for module_path in sorted(package_dir.rglob("*.py")):
        if module_path.name == "_auth_hints.py":
            continue  # the one legitimate source of login pointers
        if "_vendor" in module_path.parts:
            continue  # fork-synced third-party code, not our message surface
        offenders.extend(
            f"{module_path.relative_to(package_dir)}:{lineno}: {text!r}"
            for lineno, text in _banned_login_hint_literals(
                module_path.read_text(encoding="utf-8")
            )
        )
    assert offenders == [], (
        "These literals hard-code a login pointer instead of importing it "
        "from direct_cli/_auth_hints.py — a second hint source drifts from "
        "the canonical one and contradicts it at runtime (issue #924):\n"
        + "\n".join(offenders)
    )


# The detector needs its own coverage, same as TestBrowserPackageClock: the
# guard passes both when the package is clean and when the detector is blind.


def test_detector_flags_a_plain_hint_literal():
    source = 'raise UsageError("Run: direct auth login --profile x")\n'
    assert len(_banned_login_hint_literals(source)) == 1


def test_detector_flags_a_literal_inside_an_f_string():
    source = 'msg = f"see direct auth login --profile x docs"\n'
    assert len(_banned_login_hint_literals(source)) == 1


def test_detector_flags_a_docstring():
    source = 'def cmd():\n    """Use direct playwright login instead."""\n'
    assert len(_banned_login_hint_literals(source)) == 1


def test_detector_allows_composition_from_the_constant():
    from direct_cli._auth_hints import HINT_LOGIN_BROWSER

    source = (
        "from direct_cli._auth_hints import HINT_LOGIN_BROWSER\n"
        'msg = f"Run: {HINT_LOGIN_BROWSER}"\n'
    )
    assert _banned_login_hint_literals(source) == []
    assert HINT_LOGIN_BROWSER  # the imported name is the sanctioned pointer
