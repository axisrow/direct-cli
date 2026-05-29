"""Scalable i18n for localized CLI help and runtime messages.

Russian is the default locale. English is available via the global
``--locale en`` option or the ``YANDEX_DIRECT_CLI_LOCALE`` environment
variable. Only human-facing text (option ``help=``, command/group docstrings,
group epilogs, and ``print_*`` runtime messages) is localized — command names,
flag names, and the public CLI contract stay unchanged.

Translations live in JSON files under ``direct_cli/translations/``. Each file is
a flat object keyed by the **English source string**::

    {"Output file": "Файл вывода", "Show request without sending": "..."}

``common.json`` is loaded first; per-module files (``campaigns.json`` etc.) are
merged on top, so a module may override a shared string. English is the source,
so no English file is needed — :func:`t` returns the key verbatim for ``en`` and
falls back to it when a Russian translation is missing (graceful degradation).

The catalog is keyed by source string on purpose: the same English help (e.g.
"Output file") is translated once and reused everywhere, and command modules
need no ``cls=``/``help_key`` edits — ``cli._apply_directcli_classes`` retypes
every plain ``click.Option`` to :class:`LocalizedOption` after registration.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import click

DEFAULT_LOCALE = "ru"
SUPPORTED_LOCALES = ("ru", "en")
LOCALE_ENV_VAR = "YANDEX_DIRECT_CLI_LOCALE"

_TRANSLATIONS_DIR = Path(__file__).resolve().parent / "translations"


def _load_translations() -> dict[str, str]:
    """Merge all ``translations/*.json`` into one ``{source: russian}`` table.

    ``common.json`` is applied first so per-module files can override shared
    strings. Missing directory or empty catalog is fine (English-only mode).
    """
    table: dict[str, str] = {}
    if not _TRANSLATIONS_DIR.is_dir():
        return table
    paths = sorted(
        _TRANSLATIONS_DIR.glob("*.json"),
        key=lambda p: (p.stem != "common", p.stem),
    )
    for path in paths:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            table.update(data)
    return table


# Russian translations keyed by English source string. English is the source.
_RU: dict[str, str] = _load_translations()

# Locale used by t() when no explicit locale/context is available (runtime
# print_* messages and Click's get_short_help_str, which receives no context).
# Primed from the resolved --locale in the root callback and in help rendering.
_active_locale = DEFAULT_LOCALE


def normalize_locale(value: Optional[str]) -> Optional[str]:
    """Return a supported locale code, or None if *value* is not supported."""
    if value and value.lower() in SUPPORTED_LOCALES:
        return value.lower()
    return None


def set_active_locale(locale: Optional[str]) -> None:
    """Set the process-wide active locale used by context-free translations."""
    global _active_locale
    _active_locale = normalize_locale(locale) or DEFAULT_LOCALE


def get_active_locale() -> str:
    """Return the current process-wide active locale."""
    return _active_locale


def resolve_locale(ctx: Optional[click.Context] = None) -> str:
    """Resolve the active locale.

    Priority: explicit ``--locale`` on the root context (stored in
    ``ctx.obj['locale']`` or root params) > ``YANDEX_DIRECT_CLI_LOCALE`` env
    var > ``DEFAULT_LOCALE``.
    """
    if ctx is not None:
        try:
            root = ctx.find_root()
        except Exception:  # pragma: no cover - defensive
            root = ctx
        if isinstance(root.obj, dict):
            normalized = normalize_locale(root.obj.get("locale"))
            if normalized:
                return normalized
        normalized = normalize_locale(root.params.get("locale"))
        if normalized:
            return normalized
    normalized = normalize_locale(os.environ.get(LOCALE_ENV_VAR))
    if normalized:
        return normalized
    return DEFAULT_LOCALE


def t(source: Optional[str], locale: Optional[str] = None) -> Optional[str]:
    """Translate the English *source* string into *locale*.

    English is the source: for ``en`` (or any unsupported locale) the source is
    returned verbatim. For ``ru`` the catalog is consulted, falling back to the
    source string when no translation exists. When *locale* is omitted the
    process-wide active locale (see :func:`set_active_locale`) is used, so this
    works in runtime messages where no Click context is available.
    """
    if not source:
        return source
    resolved = normalize_locale(locale) or (_active_locale if locale is None else None)
    resolved = resolved or DEFAULT_LOCALE
    if resolved == "en":
        return source
    return _RU.get(source, source)


class LocalizedOption(click.Option):
    """A Click option whose ``--help`` text is localized at render time.

    The English ``help=`` string is the catalog key; the resolved-locale text is
    substituted when Click formats the option help record and restored after, so
    the source key stays stable across repeated renders. Plain ``click.Option``
    instances are retyped to this class automatically (see
    ``cli._apply_directcli_classes``) — modules need no ``cls=``.
    """

    def get_help_record(self, ctx: click.Context):
        if self.help:
            original = self.help
            self.help = t(self.help, resolve_locale(ctx))
            try:
                return super().get_help_record(ctx)
            finally:
                self.help = original
        return super().get_help_record(ctx)
