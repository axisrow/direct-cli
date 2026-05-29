"""Tests for localized CLI help (issue #156): Russian default, English opt-in."""

from unittest.mock import patch

from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli.i18n import DEFAULT_LOCALE, normalize_locale, resolve_locale, t


def _invoke(*args, env=None):
    base_env = {"YANDEX_DIRECT_TOKEN": "", "YANDEX_DIRECT_LOGIN": ""}
    if env:
        base_env.update(env)
    with patch("direct_cli.cli.get_active_profile", return_value=None):
        return CliRunner(env=base_env).invoke(cli, list(args))


# --- catalog / helpers -----------------------------------------------------


def test_default_locale_is_russian():
    assert DEFAULT_LOCALE == "ru"


def test_normalize_locale_accepts_supported_and_rejects_others():
    assert normalize_locale("RU") == "ru"
    assert normalize_locale("en") == "en"
    assert normalize_locale("de") is None
    assert normalize_locale(None) is None


def test_resolve_locale_falls_back_to_default_without_context_or_env():
    with patch.dict("os.environ", {}, clear=True):
        assert resolve_locale() == "ru"


def test_t_returns_locale_specific_text():
    assert "мастер-токен" in t("v4finance.master_token_setup", "ru")
    assert "master token" in t("v4finance.master_token_setup", "en")
    # Unknown locale falls back to the default (Russian).
    assert t("v4finance.master_token_setup", "de") == t(
        "v4finance.master_token_setup", "ru"
    )


# --- group epilog ----------------------------------------------------------


def test_v4finance_help_is_russian_by_default():
    result = _invoke("v4finance", "--help")
    assert result.exit_code == 0
    assert "мастер-токен" in result.output
    assert "master token in the Yandex" not in result.output
    # The shared V4 Live tail is still appended (single-sourced V4_EPILOG).
    assert "V4 Live commands use typed flags" in result.output


def test_v4finance_help_english_via_locale_flag():
    result = _invoke("--locale", "en", "v4finance", "--help")
    assert result.exit_code == 0
    assert "master token in the Yandex" in result.output
    assert "мастер-токен" not in result.output


def test_v4finance_help_english_via_env_var():
    result = _invoke("v4finance", "--help", env={"YANDEX_DIRECT_CLI_LOCALE": "en"})
    assert result.exit_code == 0
    assert "master token in the Yandex" in result.output


def test_uppercase_env_locale_is_normalized_not_rejected():
    # A non-canonical case ("EN") must normalize to "en", not hard-fail the
    # command via strict click.Choice validation on the env var.
    result = _invoke("v4finance", "--help", env={"YANDEX_DIRECT_CLI_LOCALE": "EN"})
    assert result.exit_code == 0
    assert "master token in the Yandex" in result.output


def test_invalid_env_locale_degrades_to_russian_default():
    # An unsupported env locale must degrade to the Russian default rather
    # than breaking every command (regression: strict Choice on the env var
    # used to raise "Invalid value for '--locale'" and abort with exit 2).
    result = _invoke("v4finance", "--help", env={"YANDEX_DIRECT_CLI_LOCALE": "fr"})
    assert result.exit_code == 0
    assert "Invalid value" not in result.output
    assert "мастер-токен" in result.output


def test_invalid_locale_flag_degrades_to_russian_default():
    # Same lenient handling for the explicit flag form.
    result = _invoke("--locale", "fr", "v4finance", "--help")
    assert result.exit_code == 0
    assert "Invalid value" not in result.output
    assert "мастер-токен" in result.output


# --- option help -----------------------------------------------------------


def test_master_token_option_help_russian_by_default():
    result = _invoke("v4finance", "get-credit-limits", "--help")
    assert result.exit_code == 0
    assert "Финансовый мастер-токен" in result.output


def test_master_token_option_help_english_via_locale_flag():
    result = _invoke("--locale", "en", "v4finance", "get-credit-limits", "--help")
    assert result.exit_code == 0
    assert "Financial master token issued" in result.output


def test_locale_does_not_change_command_or_flag_names():
    ru = _invoke("v4finance", "get-credit-limits", "--help")
    en = _invoke("--locale", "en", "v4finance", "get-credit-limits", "--help")
    for output in (ru.output, en.output):
        assert "--master-token" in output
        assert "--operation-num" in output
