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

``direct masters login`` (issue #635) is a third, independent path that does
not touch the user's real Chrome profile or the macOS Keychain at all:
:func:`open_persistent_session` launches a bundled Chromium against its own
persistent profile directory (``~/.direct-cli/chrome-profile/`` by default),
and the user logs in by hand once via ``passport.yandex.ru``. Cookies then
persist on disk the same way a real Chrome profile would (Chromium manages
its own on-disk cookie store for a persistent context — no ``storage_state``
capture/injection dance needed). This works identically on macOS/Linux/
Windows and needs no Keychain access, at the cost of a one-time manual login
instead of a transparent cookie copy.
"""

import contextlib
import os
import platform
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Generator, Optional, Tuple

from .._captcha import find_captcha_marker, find_marker

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page

try:
    from playwright.sync_api import Error as PlaywrightError
except ImportError:  # pragma: no cover - exercised only when playwright is absent
    PlaywrightError = Exception  # type: ignore[assignment,misc]

_BROWSER_INSTALL_HINT = (
    'pip install "direct-cli[browser]" && playwright install chromium'
)

# Sibling of direct_cli/browser/store.py's PLAYWRIGHT_SESSION_PATH and
# direct_cli/auth.py's AUTH_STORE_PATH under ~/.direct-cli/ — a dedicated
# subdirectory so this profile's own Chromium lock files/caches never mix
# with either of those.
DEFAULT_PERSISTENT_PROFILE_DIR = Path.home() / ".direct-cli" / "chrome-profile"

#: Marker file written into every profile directory the CLI creates. It is the
#: sole proof of ownership `masters logout` accepts before deleting a tree — an
#: arbitrary ``--profile-dir`` (a typo, a shell-expanded ``.``) has no marker and
#: is refused rather than recursively removed.
PROFILE_MARKER_NAME = ".direct-cli-profile"

_PASSPORT_LOGIN_URL = "https://passport.yandex.ru/auth"

# How long `direct masters login` waits for the user to finish logging in by
# hand before giving up.
_LOGIN_WAIT_TIMEOUT_MS = 5 * 60 * 1000
_LOGIN_POLL_INTERVAL_MS = 1_000


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
#
# issue #666: Yandex migrated the login page from ``/auth`` to
# ``/pwl-yandex`` and dropped "Войдите с Яндекс ID" from the HTML entirely —
# live-confirmed 2026-08-02 via a real expired saved session redirected to
# ``passport.yandex.ru/pwl-yandex?...&cause=auth&...``. Both original markers
# went stale at once, so ``assert_authenticated`` silently treated a real
# login page as authenticated, turning an expired/invalid session into an
# opaque grid-request timeout instead of a clear ``BrowserAuthError``. The
# old markers are kept alongside the new one rather than replaced outright —
# Yandex could roll the URL back, and a marker that's merely unused costs
# nothing.
_LOGIN_PAGE_MARKERS = (
    "passport.yandex.ru/auth",
    "passport.yandex.ru/pwl-yandex",
    "Войдите с Яндекс ID",
)

# DOM markers this module polls for after ``wait_until="commit"`` navigations
# — see ``_wait_for_marker``'s docstring for why ``commit`` replaced
# ``domcontentloaded`` here (issue #686). Both are the outer shell of their
# respective page, present regardless of which specific sub-state (account
# picker, password form, 2FA prompt; populated grid vs. empty one) is
# showing, so waiting on them cannot itself race the thing a caller actually
# wants to inspect next (``page.content()`` for the auth/captcha checks, or —
# for the Passport case — the human's own typing into the form).
#
# ``auth-logo`` confirmed live 2026-08-03 against a real
# ``passport.yandex.ru/pwl-yandex/auth/list`` response (Yandex's own account
# picker) — the Passport page shell's logo, present on every Passport screen
# (login form, account list, 2FA) since it's part of the shared layout, not
# any single step's own markup.
_PASSPORT_PAGE_MARKERS = ('[data-testid="auth-logo"]',)

# ``Sidebar`` confirmed live 2026-08-03 against a real, authenticated
# ``https://direct.yandex.ru/dna/grid/campaigns/`` response — Direct's own
# left navigation shell, present on every authenticated Direct page
# regardless of the grid's own virtualized content (issue #639: the grid
# never renders a stable content marker of its own, only its
# ``GridCampaigns`` data call does — see ``direct_cli/browser/masters.py``'s
# ``_capture_grid_campaigns_request``). Waiting on the general Direct shell
# is sufficient here: both call sites only need ``page.content()`` to be
# real markup for the captcha/auth checks, not the grid's own data.
_DIRECT_PAGE_MARKERS = ('[data-testid="Sidebar"]',)

# Union of both marker sets — for a navigation that can legitimately land on
# either page (see ``_wait_for_marker``'s "Accepts multiple selectors"
# paragraph).
_DIRECT_OR_PASSPORT_PAGE_MARKERS = _DIRECT_PAGE_MARKERS + _PASSPORT_PAGE_MARKERS

# Both markers render fast (page-shell chrome, not the data-heavy content
# behind it) — comfortably inside the same budget the module's other
# navigation timeouts use.
_PAGE_MARKER_TIMEOUT_MS = 30_000
_PAGE_MARKER_POLL_MS = 250


def _wait_for_marker(
    page: "Page",
    selectors: "Tuple[str, ...]",
    timeout_ms: int = _PAGE_MARKER_TIMEOUT_MS,
) -> bool:
    """Poll until any of ``selectors`` appears in ``page``'s DOM, or on timeout.

    Used after ``wait_until="commit"`` navigations to Yandex Passport and the
    Direct campaigns grid. ``commit`` only waits for the network response to
    begin — it returns as soon as the browser has committed to the
    navigation, before any of the SPA's own JS has run. ``domcontentloaded``
    would normally be the next step up, but both Passport and the grid keep
    long-poll connections open (see ``BrowserAuthError``'s docstring and
    ``_capture_grid_campaigns_request`` in ``masters.py``), so
    ``domcontentloaded`` — which Playwright fires once the HTML parser
    finishes, external long-poll requests notwithstanding — is not the
    problem; the problem observed live (issue #686) was ``goto`` itself
    occasionally timing out on ``domcontentloaded`` during Passport's own
    slow initial paint. Polling for a concrete DOM marker instead means every
    caller observes an actually-rendered page, on a budget independent of
    whichever network event Playwright happens to fire first.

    Accepts multiple selectors (matched as "any of") rather than one,
    because a single ``goto`` can legitimately land on either page: the
    ``login_persistent_session`` polling loop re-navigates to the grid every
    tick, but an unfinished login redirects that same URL back to Passport —
    waiting on the grid's marker alone would burn ``timeout_ms`` every tick
    until the user finishes logging in.

    Returns ``True`` once a marker is found, ``False`` on timeout — mirrors
    ``direct_cli/browser/masters.py``'s ``_poll_until`` so a timeout is a
    normal, non-raising outcome the caller decides how to handle (a
    ``BrowserAuthError``/``BrowserCaptchaError`` from the content-based
    checks that follow it is almost always the more specific error the user
    should see, rather than a generic "marker never appeared").
    """
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        with contextlib.suppress(PlaywrightError):
            if any(page.locator(selector).first.count() > 0 for selector in selectors):
                return True
        page.wait_for_timeout(_PAGE_MARKER_POLL_MS)
    return False


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


def _resolve_persistent_profile_dir(profile_dir: Optional[Path]) -> Path:
    return profile_dir or DEFAULT_PERSISTENT_PROFILE_DIR


#: Records the profile directory the last `masters login` used, so read
#: commands can find a session saved outside the default location. Without
#: it `--profile-dir` would be accepted by `login` and silently ignored by
#: everything else.
PROFILE_POINTER_PATH = Path.home() / ".direct-cli" / "chrome-profile-path"


def remember_persistent_profile_dir(profile_dir: Path) -> None:
    """Record which profile directory `masters login` populated.

    Stored absolute: a relative path would be re-resolved against whatever
    directory a later command happened to run from, so `masters logout`
    would act on a different profile depending on where the user stood.
    """
    PROFILE_POINTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_POINTER_PATH.write_text(str(profile_dir.resolve()), encoding="utf-8")
    os.chmod(PROFILE_POINTER_PATH, 0o600)


def configured_persistent_profile_dir() -> Path:
    """Return the profile directory `masters` commands should read from.

    The one recorded by the last `masters login --profile-dir`, else the
    default location.
    """
    try:
        recorded = PROFILE_POINTER_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return DEFAULT_PERSISTENT_PROFILE_DIR
    # A hand-edited or truncated record must not silently resolve against the
    # caller's cwd — only an absolute path is trustworthy here.
    if not recorded or not Path(recorded).is_absolute():
        return DEFAULT_PERSISTENT_PROFILE_DIR
    return Path(recorded)


def persistent_profile_is_usable(profile_dir: Optional[Path] = None) -> bool:
    """Return whether a persistent profile holds an actual browser session.

    Mere directory existence is not enough: ``_launch_persistent_context``
    creates the directory (and its marker) before Chromium starts, so a login
    the user aborted leaves an empty profile behind. Routing ``masters``
    commands through it would launch a browser, fail auth, and fall back on
    every single call. Chromium writes its cookie store only once it has
    actually run, so that file is the honest signal.
    """
    resolved = _resolve_persistent_profile_dir(profile_dir)
    return (resolved / "Default" / "Cookies").exists()


@contextlib.contextmanager
def _launch_persistent_context(
    sync_playwright, profile_dir: Path, *, headless: bool
) -> Generator[Any, None, None]:
    """Shared launch/teardown for the CLI's own persistent Chromium profile.

    Unlike :func:`_launch_context` (a fresh, throwaway context every call),
    ``launch_persistent_context`` both launches the browser *and* returns the
    context in one call — there is no separate ``Browser`` object to close,
    Playwright owns that lifecycle internally for persistent contexts.

    The profile directory holds a live Yandex session (cookies readable in
    plaintext by the owning process) — chmod 0700 on every launch, the same
    treatment ``direct_cli/browser/store.py`` and ``direct_cli/auth.py`` give
    their own on-disk session files (issue #635 risk: "Хранение живой сессии
    Яндекса на диске").

    The ownership marker is only ever written into a directory this function
    *created*. An existing directory must already carry the marker to be
    reused; otherwise it belongs to someone else and is refused. Without that
    asymmetry ``--profile-dir ~`` would mark the user's home directory as
    CLI-owned, and ``masters logout`` would then accept that marker as
    authorization to ``shutil.rmtree`` it.
    """
    marker = profile_dir / PROFILE_MARKER_NAME
    try:
        profile_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        if not marker.is_file():
            raise BrowserSessionError(
                f"Refusing to use {profile_dir} as a browser profile: the "
                "directory already exists and was not created by `direct "
                f"masters login` (no {PROFILE_MARKER_NAME} marker). Pick a "
                "path that does not exist yet, or delete that directory by "
                "hand if you are sure."
            ) from None
    else:
        marker.touch()

    os.chmod(profile_dir, 0o700)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile_dir), headless=headless, locale="ru-RU"
        )
        try:
            yield context
        finally:
            context.close()


def login_persistent_session(
    *,
    profile_dir: Optional[Path] = None,
    headless: bool = False,
    timeout_ms: int = _LOGIN_WAIT_TIMEOUT_MS,
) -> None:
    """Open the CLI's own persistent Chromium profile for a one-time manual login.

    Navigates to Yandex Passport's login page and polls (every
    :data:`_LOGIN_POLL_INTERVAL_MS`) until :func:`assert_authenticated` no
    longer raises against ``direct.yandex.ru`` — i.e. until the user has
    finished logging in by hand in the visible window. Raises
    :class:`BrowserAuthError` if ``timeout_ms`` elapses first.

    Deliberately defaults ``headless=False``: a headless window cannot be
    logged into by a human, so ``direct masters login`` always shows the
    window regardless of ``--headful`` unless the caller overrides it
    (e.g. for tests).
    """
    sync_playwright = _import_sync_playwright()
    resolved_dir = _resolve_persistent_profile_dir(profile_dir)

    # Deferred import: direct_cli/browser/masters.py's GRID_URL is the single
    # canonical source for this URL (CLAUDE.md "No URL literals outside the
    # registry"); imported here rather than at module load to avoid a
    # session.py <-> masters.py import cycle (masters.py imports session.py).
    from .masters import GRID_URL

    with _launch_persistent_context(
        sync_playwright, resolved_dir, headless=headless
    ) as context:
        page = context.new_page()
        page.goto(_PASSPORT_LOGIN_URL, wait_until="commit")
        if not _wait_for_marker(page, _PASSPORT_PAGE_MARKERS):
            # Fail closed: a timed-out marker means the page never rendered
            # far enough to trust `page.content()` — an in-progress/blank
            # shell may contain neither the login-page nor captcha markers
            # `assert_authenticated`/`assert_not_captcha` scan for, which
            # would otherwise let an unrendered page sail through as if it
            # were a real one (issue #692 cycle-review).
            raise BrowserSessionError(
                f"Timed out waiting for {_PASSPORT_LOGIN_URL} to render. "
                "This can happen on a slow connection — retry `direct "
                "masters login`."
            )

        # Poll on a second page, never on `page`: the human is typing into
        # that one, and navigating it to the grid once a second would wipe a
        # half-filled login form or a pending 2FA prompt out from under them.
        # Both pages share the persistent context's cookie jar, so a login
        # completed on `page` is immediately visible to `probe`.
        probe = context.new_page()
        try:
            elapsed_ms = 0
            while elapsed_ms < timeout_ms:
                probe.goto(GRID_URL, wait_until="commit")
                # Either marker is a valid landing spot here: an unfinished
                # login redirects the grid URL right back to Passport, so
                # waiting on the grid's own marker alone would burn the full
                # timeout every tick until the user finishes logging in (see
                # `_wait_for_marker`'s docstring). Capped at the poll
                # interval, not `_PAGE_MARKER_TIMEOUT_MS`, so a slow-to-paint
                # page degrades to "try again next tick" rather than
                # stalling this loop's own cadence.
                marker_found = _wait_for_marker(
                    probe,
                    _DIRECT_OR_PASSPORT_PAGE_MARKERS,
                    timeout_ms=_LOGIN_POLL_INTERVAL_MS,
                )
                if not marker_found:
                    # Neither page rendered far enough this tick to trust
                    # `probe.content()` — a blank/in-progress shell can
                    # contain neither the login-page nor captcha markers, so
                    # treat this exactly like "not authenticated yet" rather
                    # than risking `assert_authenticated` passing an
                    # unrendered page (issue #692 cycle-review). This is the
                    # expected outcome on a slow tick, not an error.
                    elapsed_ms += _LOGIN_POLL_INTERVAL_MS
                    continue
                html = probe.content()
                assert_not_captcha(html)
                try:
                    assert_authenticated(html)
                except BrowserAuthError:
                    probe.wait_for_timeout(_LOGIN_POLL_INTERVAL_MS)
                    elapsed_ms += _LOGIN_POLL_INTERVAL_MS
                    continue
                # Only once the session is real: read commands resolve the
                # profile through this pointer, so recording an unfinished
                # login would point them at an empty profile.
                remember_persistent_profile_dir(resolved_dir)
                return
        finally:
            probe.close()

        raise BrowserAuthError(
            f"Timed out after {timeout_ms // 1000}s waiting for login to "
            f"{_PASSPORT_LOGIN_URL} to complete. Run `direct masters login` "
            "again and finish signing in within the time limit."
        )


@contextlib.contextmanager
def open_persistent_session(
    *,
    profile_dir: Optional[Path] = None,
    headless: bool = True,
) -> Generator["Page", None, None]:
    """Launch the CLI's own persistent Chromium profile for regular use.

    Raises :class:`BrowserSessionMissingError` if the profile directory
    doesn't exist yet or Yandex serves its login page — the fix in both
    cases is ``direct masters login``.
    """
    sync_playwright = _import_sync_playwright()
    resolved_dir = _resolve_persistent_profile_dir(profile_dir)

    if not resolved_dir.exists():
        raise BrowserSessionMissingError(
            f"No persistent browser profile found at {resolved_dir}. "
            "Run: direct masters login"
        )

    with _launch_persistent_context(
        sync_playwright, resolved_dir, headless=headless
    ) as context:
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
            page.goto(GRID_URL, wait_until="commit")
            # Either marker is a valid landing spot: a bad/expired cookie
            # jar redirects the grid URL to Passport instead of rendering
            # the grid, and `assert_authenticated` below is what turns that
            # into the specific `BrowserAuthError` (see `_wait_for_marker`'s
            # docstring for why a single marker would be wrong here).
            if not _wait_for_marker(page, _DIRECT_OR_PASSPORT_PAGE_MARKERS):
                # Fail closed: an unrendered page can contain neither the
                # login-page nor captcha markers the checks below scan for,
                # which would otherwise let it pass as if it were a
                # verified, authenticated grid (issue #692 cycle-review).
                raise BrowserAuthError(
                    f"Timed out waiting for {GRID_URL} to render while "
                    "verifying the session. Retry `direct playwright login`."
                )
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
    connections and ``wait_until="networkidle"`` never settles on it.
    ``wait_until="domcontentloaded"`` fixed that, but issue #686 found it
    still occasionally timed out on Passport's own slow initial paint, so
    every ``goto`` this module makes to Passport or the Direct grid now uses
    ``wait_until="commit"`` (returns as soon as the navigation is committed,
    before any of the target SPA's own JS runs) followed by
    :func:`_wait_for_marker` polling for a concrete DOM marker
    (``_PASSPORT_PAGE_MARKERS``/``_DIRECT_PAGE_MARKERS``) — only once that
    marker is present is the page actually rendered enough for
    ``page.content()`` to reflect the real page (login page or Direct page)
    rather than an in-progress shell. Callers should follow this same
    ``commit`` + marker-poll pattern and call this function immediately
    after, so an auth failure is reported explicitly instead of as an opaque
    timeout.

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
