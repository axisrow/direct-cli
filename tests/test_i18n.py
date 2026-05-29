"""Tests for localized CLI help (issue #156, #467): Russian default, English opt-in.

The localization mechanism is source-string keyed: the English ``help=`` /
docstring / epilog text is the catalog key, and Russian translations live in
``direct_cli/translations/*.json``. ``LOCALIZED_GROUPS`` is the registry of
top-level command groups that are fully localized; it grows as each module PR
lands. Two invariants are enforced for every registered group:

* **completeness** — every English help/docstring string rendered by the group
  has a Russian translation in the catalog (no silent English leak under the
  Russian default);
* **runtime messages wrapped** — ``print_error``/``print_info``/``print_warning``
  in the group's module are never called with a bare string literal; the text
  must pass through ``t(...)`` so it localizes.
"""

import ast
import inspect
from unittest.mock import patch

import click
from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli.i18n import (
    DEFAULT_LOCALE,
    _RU,
    normalize_locale,
    resolve_locale,
    set_active_locale,
    t,
)

# Top-level command groups that are fully localized. Append a group name here in
# the PR that localizes it (issues #468-#471) so the invariants below start
# enforcing full coverage for that module.
LOCALIZED_GROUPS = ("v4finance",)

_RUNTIME_MESSAGE_FUNCS = {"print_error", "print_info", "print_warning"}


def _invoke(*args, env=None):
    base_env = {"YANDEX_DIRECT_TOKEN": "", "YANDEX_DIRECT_LOGIN": ""}
    if env:
        base_env.update(env)
    with patch("direct_cli.cli.get_active_profile", return_value=None):
        return CliRunner(env=base_env).invoke(cli, list(args))


def _iter_commands(command):
    """Yield *command* and, recursively, every subcommand."""
    yield command
    if isinstance(command, click.Group):
        for sub in command.commands.values():
            yield from _iter_commands(sub)


def _help_sources(command):
    """Yield every English help/docstring source string under *command*."""
    for cmd in _iter_commands(command):
        if cmd.help:
            yield cmd.help
        for param in cmd.params:
            if isinstance(param, click.Option) and param.help:
                yield param.help


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


def test_t_translates_by_source_string():
    # English is the source: returned verbatim for en, looked up for ru.
    assert t("Output file", "en") == "Output file"
    assert t("Output file", "ru") == "Файл для вывода"
    # Unknown locale falls back to the default (Russian).
    assert t("Output file", "de") == t("Output file", "ru")
    # A source with no translation degrades to itself, never KeyErrors.
    assert t("a string absent from any catalog", "ru") == (
        "a string absent from any catalog"
    )


def test_active_locale_drives_context_free_translation():
    # Runtime messages call t() without a Click context; the process-wide
    # active locale must steer them.
    try:
        set_active_locale("en")
        assert t("Output file") == "Output file"
        set_active_locale("ru")
        assert t("Output file") == "Файл для вывода"
    finally:
        set_active_locale(DEFAULT_LOCALE)


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


# --- option / docstring help ----------------------------------------------


def test_master_token_option_help_russian_by_default():
    result = _invoke("v4finance", "get-credit-limits", "--help")
    assert result.exit_code == 0
    assert "Финансовый мастер-токен" in result.output


def test_master_token_option_help_english_via_locale_flag():
    result = _invoke("--locale", "en", "v4finance", "get-credit-limits", "--help")
    assert result.exit_code == 0
    assert "Financial master token issued" in result.output


def test_command_docstring_is_localized():
    ru = _invoke("v4finance", "get-credit-limits", "--help")
    en = _invoke("--locale", "en", "v4finance", "get-credit-limits", "--help")
    assert "Получить кредитные лимиты клиента." in ru.output
    assert "Get client credit limits." in en.output


def test_root_epilog_is_localized():
    ru = _invoke("--help")
    en = _invoke("--locale", "en", "--help")
    assert "Контекст учётных данных" in ru.output
    assert "Credential context" in en.output


def test_locale_does_not_change_command_or_flag_names():
    ru = _invoke("v4finance", "get-credit-limits", "--help")
    en = _invoke("--locale", "en", "v4finance", "get-credit-limits", "--help")
    for output in (ru.output, en.output):
        assert "--master-token" in output
        assert "--operation-num" in output


# --- registry invariants (enforced per localized module) -------------------


def test_localized_groups_exist():
    for name in LOCALIZED_GROUPS:
        assert name in cli.commands, f"unknown group in LOCALIZED_GROUPS: {name}"


def test_localized_groups_have_complete_translations():
    """Every help/docstring string of a localized group must be translatable.

    Source-keyed catalog: the English string is the key. A missing key means
    the Russian default would silently render English — the bug #466 fixes.
    """
    missing: dict[str, list[str]] = {}
    for name in LOCALIZED_GROUPS:
        group = cli.commands[name]
        gaps = [src for src in _help_sources(group) if src not in _RU]
        if gaps:
            missing[name] = gaps
    assert not missing, "untranslated strings in localized groups: " + repr(missing)


def test_localized_groups_wrap_runtime_messages():
    """print_error/info/warning in a localized module must not take a bare
    string literal — the text has to pass through t(...) to localize."""
    offenders: dict[str, list[str]] = {}
    seen_files: set[str] = set()
    for name in LOCALIZED_GROUPS:
        group = cli.commands[name]
        module = inspect.getmodule(group.callback)
        path = getattr(module, "__file__", None)
        if not path or path in seen_files:
            continue
        seen_files.add(path)
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            func_name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr if isinstance(func, ast.Attribute) else None
            )
            if func_name not in _RUNTIME_MESSAGE_FUNCS:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                offenders.setdefault(name, []).append(first.value)
    assert not offenders, "bare-literal runtime messages (wrap in t()): " + repr(
        offenders
    )
