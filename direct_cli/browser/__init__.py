"""
Browser automation layer for Yandex Direct features that have no API surface.

Used by ``direct masters`` (Мастер кампаний / Campaign Wizard), ``direct
history`` («История изменений» — the per-field change journal the API does not
expose at all) and ``direct support`` (the Yandex Messenger support chat) — see
``direct_cli/browser/session.py``, ``direct_cli/browser/masters.py``,
``direct_cli/browser/change_history.py`` and ``direct_cli/browser/support.py``.
``playwright`` is an optional dependency (``pip install "direct-cli[browser]"``);
nothing in this package is imported unless a browser-backed command actually runs.
"""

from .session import (
    BrowserAuthError,
    BrowserCaptchaError,
    BrowserSessionError,
    ChromeCookieError,
)

__all__ = [
    "BrowserAuthError",
    "BrowserCaptchaError",
    "BrowserSessionError",
    "ChromeCookieError",
]
