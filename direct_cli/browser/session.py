"""
Playwright session management for browser-backed commands (``direct masters``).

Reuses the user's own Chrome cookies so ``direct masters`` can read Мастер
кампаний (Campaign Wizard) pages without a separate login flow — this data has
no API surface at all (see module docstring in ``direct_cli/browser/__init__.py``).

Playwright cannot attach to a Chrome profile that is currently open (the
profile directory is locked), so this module does not launch Chrome on the
user's real profile at all. Instead it decrypts the user's Yandex Direct
cookies itself (see ``direct_cli/browser/_chrome_crypto.py`` — on macOS the
cookie AES key lives only in the login Keychain, never in ``Local State``,
which is why an earlier version of this module that merely *copied*
``Cookies``/``Local State`` into a temp profile did not work, see #634) and
injects the decrypted cookies into a fresh, bundled Chromium context via
``BrowserContext.add_cookies()``. The user's own Chrome window is never
touched and does not need to be closed.
"""

import contextlib
import os
import platform
from pathlib import Path
from typing import TYPE_CHECKING, Generator, Optional

from .._captcha import find_captcha_marker, find_marker

if TYPE_CHECKING:
    from playwright.sync_api import Page


class BrowserSessionError(RuntimeError):
    """Raised when a Playwright/Chrome session cannot be established."""


class BrowserCaptchaError(BrowserSessionError):
    """Raised when Yandex serves a SmartCaptcha gate instead of real content."""


class BrowserAuthError(BrowserSessionError):
    """Raised when Yandex serves its login page instead of Direct content.

    Distinct from a Keychain/decryption failure (:class:`ChromeCookieError`):
    this means the cookies decrypted fine but the session they represent is
    no longer valid (expired, or belongs to a different account) — see
    ``assert_authenticated``.
    """


class ChromeCookieError(BrowserSessionError):
    """Raised when Chrome's cookie store cannot be read or decrypted.

    See ``direct_cli/browser/_chrome_crypto.py`` for the macOS Keychain /
    AES-128-CBC decryption pipeline this wraps.
    """


# Markers that appear only on Yandex Passport's login page, never on a real
# Direct page. Declared once, ``_captcha.py``-style, rather than duplicated
# across call sites (see CLAUDE.md "No URL literals outside the registry" and
# the #426 post-mortem it cites).
_LOGIN_PAGE_MARKERS = ("passport.yandex.ru/auth", "Войдите с Яндекс ID")


def default_chrome_profile_dir() -> Optional[Path]:
    """Best-effort default Chrome user-data-dir for the current OS.

    Returns ``None`` on platforms we don't have a canonical path for — callers
    must then require ``--profile-dir`` explicitly.
    """
    system = platform.system()
    home = Path.home()
    if system == "Darwin":
        return home / "Library" / "Application Support" / "Google" / "Chrome"
    if system == "Linux":
        return home / ".config" / "google-chrome"
    if system == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "Google" / "Chrome" / "User Data"
        return None
    return None


@contextlib.contextmanager
def open_chrome_session(
    *,
    profile_dir: Optional[Path] = None,
    chrome_profile: str = "Default",
    headless: bool = True,
) -> Generator["Page", None, None]:
    """Launch a bundled Chromium with the user's decrypted Yandex cookies injected.

    Yields a ready-to-use Playwright ``Page``. Import of ``playwright`` is
    deferred to this function so the rest of the CLI has no hard dependency on
    it — see ``direct_cli/commands/masters.py`` for the ``UsageError`` shown
    when the optional extra isn't installed.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - exercised via commands/masters.py
        raise BrowserSessionError(
            "playwright is required for `direct masters` but is not installed. "
            'Run: pip install "direct-cli[browser]" && playwright install chromium'
        ) from exc

    source_root = profile_dir or default_chrome_profile_dir()
    if source_root is None:
        raise BrowserSessionError(
            "Could not determine your Chrome profile directory automatically "
            "on this platform. Pass --profile-dir explicitly."
        )
    if not source_root.exists():
        raise BrowserSessionError(
            f"Chrome profile directory not found: {source_root}. "
            "Pass --profile-dir to point at your actual Chrome user-data-dir."
        )

    # Deferred import: this pulls in _chrome_crypto (and, transitively, the
    # optional `cryptography` package) only once we actually know playwright
    # and the profile directory are usable.
    from . import _chrome_crypto

    cookies = _chrome_crypto.load_yandex_cookies(source_root, chrome_profile)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        try:
            context = browser.new_context(locale="ru-RU")
            context.add_cookies(cookies)
            page = context.new_page()
            try:
                yield page
            finally:
                context.close()
        finally:
            browser.close()


def assert_not_captcha(html: str) -> None:
    """Raise :class:`BrowserCaptchaError` if ``html`` looks like a SmartCaptcha gate.

    Uses the shared marker registry in ``direct_cli._captcha`` — the same
    guard ``direct_cli.wsdl_coverage``/``direct_cli.reports_coverage`` use —
    so a captcha gate fails loudly here too, never silently parsed as if it
    were real content.
    """
    if find_captcha_marker(html) is not None:
        raise BrowserCaptchaError(
            "Yandex served a SmartCaptcha challenge instead of the Direct page. "
            "Open direct.yandex.ru in your regular Chrome window, solve the "
            "captcha there, then retry."
        )


def assert_authenticated(html: str) -> None:
    """Raise :class:`BrowserAuthError` if ``html`` looks like Yandex's login page.

    Injected cookies can decrypt successfully yet represent an expired or
    wrong-account session — before #634 this surfaced only as a
    ``Page.goto`` timeout, because Yandex's login page holds long-poll
    connections and ``wait_until="networkidle"`` never settles on it. Callers
    should use ``wait_until="domcontentloaded"`` and call this immediately
    after, so an auth failure is reported explicitly instead of as an opaque
    30-second timeout.

    Uses the same ``find_marker`` scan primitive as
    :func:`assert_not_captcha` (``direct_cli._captcha``), just against a
    different marker set.
    """
    if find_marker(html, _LOGIN_PAGE_MARKERS) is not None:
        raise BrowserAuthError(
            "Yandex served its login page instead of Direct. Your Chrome "
            "session cookies are expired or belong to a different "
            "account. Open https://direct.yandex.ru in Chrome, log in, "
            "then retry."
        )
