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

``direct playwright login`` (see ``direct_cli/commands/browser_session.py``)
persists the result of this decrypt-and-inject dance as a Playwright
``storage_state`` file (``direct_cli/browser/store.py``), so subsequent
``direct masters`` calls can skip the Keychain round-trip entirely via
:func:`open_saved_session`. :func:`open_chrome_session` (decrypt every call,
nothing persisted) remains the zero-setup fallback ``direct masters`` uses
when no saved session exists — see ``direct_cli/commands/masters.py``.
"""

import contextlib
import os
import platform
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Generator, Optional, Tuple

from .._captcha import find_captcha_marker, find_marker

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page

_BROWSER_INSTALL_HINT = (
    'pip install "direct-cli[browser]" && playwright install chromium'
)


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


class BrowserSessionMissingError(BrowserSessionError):
    """Raised by :func:`open_saved_session` when no session file is on disk.

    Subclasses :class:`BrowserSessionError` (not a new sibling hierarchy) so
    existing ``except BrowserSessionError`` call sites — notably
    ``direct_cli/commands/masters.py``'s ``_open_session`` — catch it without
    any change.
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


def _import_sync_playwright():
    try:
        from playwright.sync_api import sync_playwright

        return sync_playwright
    except ImportError as exc:  # pragma: no cover - exercised via commands
        raise BrowserSessionError(
            "playwright is required for this command but is not installed. "
            f"Run: {_BROWSER_INSTALL_HINT}"
        ) from exc


def _resolve_profile_dir(profile_dir: Optional[Path]) -> Path:
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
    return source_root


@contextlib.contextmanager
def _launch_context(
    sync_playwright, *, headless: bool, storage_state: Optional[Dict[str, Any]] = None
) -> Generator[Tuple["Browser", Any], None, None]:
    """Shared launch/teardown body for both session flavours.

    Yields ``(browser, context)`` so callers add cookies or pass
    ``storage_state`` before creating a page; teardown mirrors the nested
    ``finally`` structure the original ``open_chrome_session`` used.
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        try:
            context = browser.new_context(locale="ru-RU", storage_state=storage_state)
            try:
                yield browser, context
            finally:
                context.close()
        finally:
            browser.close()


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

    Decrypts from Chrome on every call — nothing is persisted. See
    :func:`open_saved_session` for the persisted-session alternative that
    ``direct playwright login`` sets up.
    """
    sync_playwright = _import_sync_playwright()
    source_root = _resolve_profile_dir(profile_dir)

    # Deferred import: this pulls in _chrome_crypto (and, transitively, the
    # optional `cryptography` package) only once we actually know playwright
    # and the profile directory are usable.
    from . import _chrome_crypto

    cookies = _chrome_crypto.load_yandex_cookies(source_root, chrome_profile)

    with _launch_context(sync_playwright, headless=headless) as (_browser, context):
        context.add_cookies(cookies)
        page = context.new_page()
        yield page


def capture_storage_state(
    *,
    profile_dir: Optional[Path] = None,
    chrome_profile: str = "Default",
    headless: bool = True,
    verify: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Decrypt Chrome's Yandex cookies and return a Playwright ``storage_state``.

    Used by ``direct playwright login`` (``direct_cli/commands/browser_session.py``)
    to build the file :func:`open_saved_session` later reads. Always launches a
    real browser context — even when ``verify=False`` — because
    ``BrowserContext.storage_state()`` is what normalizes the raw cookie dicts
    (e.g. ``sameSite`` casing) into the shape Playwright itself expects;
    hand-assembling that shape from ``_chrome_crypto.load_yandex_cookies``'s
    output directly would silently drift from Playwright's own format over
    time.

    When ``verify`` is true (the default), navigates to the campaigns grid and
    runs the same captcha/auth checks ``direct masters`` uses, so a bad cookie
    jar is caught here rather than surfacing later as a confusing masters
    error. ``verify=False`` skips navigation entirely — for a captcha-gated
    network where the cookies are known-good but a live check isn't possible.

    Returns ``(storage_state, source_meta)`` — ``source_meta`` is diagnostic
    provenance (``profile_dir``, ``chrome_profile``) for the saved envelope,
    never used to re-decrypt.
    """
    sync_playwright = _import_sync_playwright()
    source_root = _resolve_profile_dir(profile_dir)

    from . import _chrome_crypto

    cookies = _chrome_crypto.load_yandex_cookies(source_root, chrome_profile)

    with _launch_context(sync_playwright, headless=headless) as (_browser, context):
        context.add_cookies(cookies)
        if verify:
            # Deferred import: direct_cli/browser/masters.py's GRID_URL is the
            # single canonical source for this URL (CLAUDE.md "No URL
            # literals outside the registry") — importing it here (rather
            # than at module load) avoids a session.py <-> masters.py import
            # cycle, since masters.py itself imports from session.py.
            from .masters import GRID_URL

            page = context.new_page()
            page.goto(GRID_URL, wait_until="domcontentloaded")
            html = page.content()
            assert_not_captcha(html)
            assert_authenticated(html)
        storage_state = context.storage_state()

    source_meta = {
        "profile_dir": str(source_root),
        "chrome_profile": chrome_profile,
    }
    return storage_state, source_meta


@contextlib.contextmanager
def open_saved_session(
    *,
    headless: bool = True,
    session_path: Optional[Path] = None,
) -> Generator["Page", None, None]:
    """Launch a bundled Chromium restoring a session saved by `direct playwright login`.

    Raises :class:`BrowserSessionMissingError` (a :class:`BrowserSessionError`
    subclass) when no saved session file exists, naming the command to fix it.
    """
    sync_playwright = _import_sync_playwright()

    # Deferred import: browser/store.py has no playwright/cryptography
    # dependency of its own, but importing it here (rather than at module
    # load) keeps this module's import-time footprint identical to before —
    # only paid for once a saved-session flow is actually used.
    from . import store

    try:
        storage_state = store.load_session(session_path)
    except store.SessionStoreError as exc:
        raise BrowserSessionMissingError(str(exc)) from exc

    with _launch_context(
        sync_playwright, headless=headless, storage_state=storage_state
    ) as (_browser, context):
        page = context.new_page()
        yield page


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
