"""
Browser automation layer for Yandex Direct features that have no API surface.

Currently used only by ``direct masters`` (Мастер кампаний / Campaign Wizard) —
see ``direct_cli/browser/session.py`` and ``direct_cli/browser/masters.py``.
``playwright`` is an optional dependency (``pip install "direct-cli[browser]"``);
nothing in this package is imported unless a browser-backed command actually runs.
"""

from .session import BrowserCaptchaError, BrowserSessionError, open_chrome_session

__all__ = [
    "BrowserCaptchaError",
    "BrowserSessionError",
    "open_chrome_session",
]
