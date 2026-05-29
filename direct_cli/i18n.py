"""Minimal i18n catalog and helpers for localized CLI help.

Russian is the default locale. English is available via the global
``--locale en`` option or the ``YANDEX_DIRECT_CLI_LOCALE`` environment
variable. Only human-facing help/epilog text is localized — command names,
flag names, and the public CLI contract stay unchanged.

Keep all bilingual strings in ``CATALOG`` here rather than scattering literal
``ru``/``en`` pairs across command modules.
"""

from __future__ import annotations

import os
from typing import Optional

import click

DEFAULT_LOCALE = "ru"
SUPPORTED_LOCALES = ("ru", "en")
LOCALE_ENV_VAR = "YANDEX_DIRECT_CLI_LOCALE"

# key -> {locale -> text}. Each key must define every SUPPORTED_LOCALES entry.
CATALOG: dict[str, dict[str, str]] = {
    "v4finance.master_token_setup": {
        "ru": (
            "Чтобы выпустить мастер-токен, в интерфейсе Яндекс Директа откройте "
            "Инструменты -> API -> Финансовые операции, включите чекбокс "
            "«Разрешить финансовые операции», нажмите «Сохранить», затем "
            "выпустите мастер-токен на этой же странице и подтвердите действие "
            "по SMS."
        ),
        "en": (
            "To issue a master token in the Yandex Direct UI, open Tools -> API "
            "-> Financial operations, enable the 'Allow financial operations' "
            "checkbox, click Save, then issue the master token on the same "
            "Financial operations page and confirm by SMS."
        ),
    },
    "v4finance.master_token_option": {
        "ru": (
            "Финансовый мастер-токен, выпущенный после включения и сохранения "
            "финансовых операций в разделе Инструменты -> API -> Финансовые "
            "операции"
        ),
        "en": (
            "Financial master token issued after enabling and saving financial "
            "operations in Tools -> API -> Financial operations"
        ),
    },
}


def normalize_locale(value: Optional[str]) -> Optional[str]:
    """Return a supported locale code, or None if *value* is not supported."""
    if value and value.lower() in SUPPORTED_LOCALES:
        return value.lower()
    return None


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


def t(key: str, locale: Optional[str] = None) -> str:
    """Translate *key* into *locale* (resolved if omitted)."""
    entry = CATALOG[key]
    resolved = normalize_locale(locale) or DEFAULT_LOCALE
    return entry.get(resolved) or entry[DEFAULT_LOCALE]


class LocalizedOption(click.Option):
    """A Click option whose ``--help`` text is localized at render time.

    Pass ``help_key`` referencing a :data:`CATALOG` entry; the resolved-locale
    help is substituted when Click formats the option help record.
    """

    def __init__(self, *args, help_key: Optional[str] = None, **kwargs):
        self.help_key = help_key
        super().__init__(*args, **kwargs)

    def get_help_record(self, ctx: click.Context):
        if self.help_key:
            self.help = t(self.help_key, resolve_locale(ctx))
        return super().get_help_record(ctx)
