"""
Playwright session management for browser-backed commands (``direct masters``).

Browser-backed commands read Мастер кампаний (Campaign Wizard) pages, which
have no API surface at all (see module docstring in
``direct_cli/browser/__init__.py``). This module never launches the user's
real Chrome — the profile directory is locked to its own process. Instead
there is exactly ONE saved session: a Playwright ``storage_state`` envelope
at ``~/.direct-cli/playwright/session.json`` (:func:`store.save_session`,
``direct_cli/browser/store.py``), and every command replays it into a fresh,
bundled Chromium context (:func:`open_saved_session`).

Filling that one file:

- Chrome import (:func:`capture_storage_state`, ``auth login browser
  --source chrome``): decrypts the user's live Yandex cookies from Chrome
  itself (macOS: the AES key lives in the login Keychain, never in ``Local
  State`` — see ``direct_cli/browser/_chrome_crypto.py`` and #634) and saves
  them as the envelope. The user's own Chrome window is never touched.
- Manual login (:func:`login_manual_session`, ``auth login browser``): a
  visible window on a fresh context; the login is detected from the cookie
  jar and the envelope is saved from the same context (#950: one
  user-agent for both issuing and replaying a session).

``open_session`` (``direct_cli/browser/auth.py``) auto-imports from Chrome
when the envelope is missing or expired; the former persistent Chromium
profile machinery was removed in this release.
"""

import contextlib
import os
import platform
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Generator,
    List,
    Optional,
    Sequence,
    Tuple,
)

from . import _clock
from . import store
from .._auth_hints import HINT_LOGIN_BROWSER, HINT_LOGIN_BROWSER_CHROME
from .._captcha import find_captcha_marker, find_marker
from ..i18n import t
from ..output import print_warning_stderr

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
except ImportError:  # pragma: no cover - exercised only when playwright is absent
    PlaywrightError = Exception  # type: ignore[assignment,misc]

    # A fallback that can never match a real raised exception: with
    # playwright absent no navigation — and hence no goto timeout — can
    # happen at all, so the isinstance() check in
    # `_is_network_navigation_error` must simply never be true. Aliasing
    # this to ``Exception`` (PlaywrightError's own fallback shape) would
    # instead classify *every* error as a navigation timeout.
    class _AbsentPlaywrightTimeout(Exception):
        pass

    PlaywrightTimeoutError = _AbsentPlaywrightTimeout  # type: ignore[misc]

_BROWSER_INSTALL_HINT = (
    'pip install "direct-cli[browser]" && playwright install chromium'
)
_PASSPORT_LOGIN_URL = "https://passport.yandex.ru/auth"

# How long `direct masters login` waits for the user to finish logging in by
# hand before giving up.
_LOGIN_WAIT_TIMEOUT_MS = 5 * 60 * 1000
_LOGIN_POLL_INTERVAL_MS = 1_000

# Yandex Passport's authenticated-session cookies — the SSO pair shared by
# every *.yandex.ru host. Their presence in the context's cookie jar is what
# the manual login polls for as the "the human finished signing
# in" signal (issue #858): the same jar is what ``_chrome_crypto`` copies out
# of Chrome to authenticate a fresh context, so these cookies *are* the
# Direct session. Deliberately excludes the pre-authentication cookies
# Passport sets on the very first page load (``yandexuid``, ``gdpr``, csrf
# tokens) — those appear long before the user has typed anything, so keying
# the verification probe on them would fire it under the user's fingers.
_AUTH_SESSION_COOKIE_NAMES = frozenset({"Session_id", "sessionid2"})


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


class SaveNotVerifiedError(BrowserSessionError):
    """Raised when a whole-form save's post-save re-read shows old values.

    Distinct from a plain :class:`BrowserSessionError` so ``update_master``
    can auto-retry exactly this failure once (issues #869/#870: Yandex's
    first save click after editing a field can close the form WITHOUT
    applying the change — the re-read then shows the pre-save state, and a
    second identical run saves fine). Callers that must not retry check for
    this class specifically; everyone else keeps catching
    :class:`BrowserSessionError` unchanged.

    ``mismatches`` carries the per-field verification lines the message was
    built from, so the retry decision can tell "the requested scalar value
    did not stick" (safe to re-run) apart from "a section-preservation
    guard fired" (the save may have silently dropped a section — a re-run
    would re-baseline from the already-mutated page and accept the loss).
    The default is the IMMUTABLE empty tuple and the retry gate treats an
    unannotated error as NOT retryable (fail-closed): only the real raise
    site — which always has lines to attach — may opt an error into the
    auto-retry.

    ``no_op_save`` certifies the #870 no-op mode: the raise site compared
    the page's post-save state with the certified pre-save baseline and
    found them EQUAL — nothing the request asked for was applied and
    nothing else changed. That is the one section-guard firing a re-run
    may converge on: the target-actions guard folds the REQUESTED prices
    into its expected map, so a no-op save fires it as a restatement of
    the requested-value mismatch, not as a section loss. Default
    ``False`` (fail-closed — a guard mismatch without this certification
    keeps the no-retry behavior). The retry gate additionally requires
    that no OTHER guard prefix fired alongside it.
    """

    mismatches: Sequence[str] = ()
    # `List[str]` would share one mutable list across every unannotated
    # instance; the tuple default cannot be poisoned by an errant
    # `exc.mismatches.append(...)` on a raise site that forgot to assign.

    no_op_save: bool = False


class BrowserNetworkError(BrowserSessionError):
    """Raised when a navigation is aborted at the network layer (issue #857).

    An unstable VPN/proxy/connection can kill ``Page.goto`` before Playwright
    receives any response (``net::ERR_ABORTED``, ``net::ERR_CONNECTION_*``,
    …) — which says nothing about whether the Yandex session is valid.
    Deliberately distinct from :class:`BrowserAuthError` (expired or
    wrong-account cookies) so an error message can tell "restore the
    connection and retry" apart from "re-login": before this class existed
    the raw Playwright traceback escaped ``direct masters login`` uncaught,
    and the natural reading — an auth problem — sent the user chasing a
    session that was fine (the live #857 report blamed exactly that).
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

# issue #859: Yandex dropped the ``Sidebar`` testid from the campaigns grid's
# left navigation shell entirely — live-confirmed 2026-08-29 against a real,
# authenticated ``https://direct.yandex.ru/dna/grid/campaigns/`` response
# (611 KB of real markup, no login/captcha marker, but no ``Sidebar`` testid
# either) that made ``direct playwright login`` time out and fail closed even
# though the underlying Chrome session was valid — the same failure mode
# #666's login-page marker rot hit, just on the authenticated side this time.
# ``DirectGrid`` replaces it: the grid's own outer shell (confirmed unique,
# single occurrence, present regardless of the grid's own virtualized row
# content — issue #639: the grid never renders a stable content marker of
# its own, only its ``GridCampaigns`` data call does, see
# ``direct_cli/browser/masters.py``'s ``_capture_grid_campaigns_request``).
# The old ``Sidebar`` marker is kept alongside the new one rather than
# replaced outright, same rationale as ``_LOGIN_PAGE_MARKERS`` above — Yandex
# could reintroduce it, and a marker that's merely unused costs nothing.
# Waiting on either is sufficient here: both call sites only need
# ``page.content()`` to be real markup for the captcha/auth checks, not the
# grid's own data.
_DIRECT_PAGE_MARKERS = (
    '[data-testid="DirectGrid"]',
    '[data-testid="Sidebar"]',
)

# Union of both marker sets — for a navigation that can legitimately land on
# either page (see ``_wait_for_marker``'s "Accepts multiple selectors"
# paragraph).
_DIRECT_OR_PASSPORT_PAGE_MARKERS = _DIRECT_PAGE_MARKERS + _PASSPORT_PAGE_MARKERS

# Both markers render fast (page-shell chrome, not the data-heavy content
# behind it) — comfortably inside the same budget the module's other
# navigation timeouts use.
_PAGE_MARKER_TIMEOUT_MS = 30_000
_PAGE_MARKER_POLL_MS = 250

#: GitHub issue tracker URL for reporting a stale/renamed DOM marker — kept
#: as a single literal here rather than repeated in each timeout message
#: (CLAUDE.md "No URL literals outside the registry" spirit, even though this
#: one isn't a Yandex docs URL: a second copy would drift the same way #426's
#: duplicated captcha URL did).
_ISSUE_TRACKER_URL = "https://github.com/axisrow/direct-cli/issues"


def _stale_marker_hint() -> str:
    """Diagnostic addendum for a "timed out waiting for ... to render"
    message — appended when the first navigation to a page (Passport or the
    Direct grid) never shows a marker `_wait_for_marker` recognizes.

    A bare "timed out" reads as a session/network problem, but issue #859
    showed a second, systemic cause: Yandex silently renamed or removed the
    specific DOM marker(s) this module polls for (``[data-testid="Sidebar"]``
    disappeared from the grid entirely, even though the grid itself rendered
    611 KB of real, authenticated markup) — the two markers this file polls
    for today (``_PASSPORT_PAGE_MARKERS``, ``_DIRECT_PAGE_MARKERS``) are just
    as vulnerable to Yandex renaming them again tomorrow. Without this hint a
    user whose session is actually fine (the page opens normally in their own
    Chrome) has no way to tell "retry" from "report a bug" apart, and would
    just keep retrying a timeout that can never succeed until the marker
    itself is fixed in code.
    """
    return (
        "This can mean either your session is expired/slow, or the page's "
        "markup changed and the marker this tool looks for is now outdated "
        "(this has happened before, see issue #859). If the page opens fine "
        f"in your own Chrome, please report this at {_ISSUE_TRACKER_URL} — "
        "the tracker is public, so first redact any account-identifying "
        "details (campaign names/IDs, account login, tokens) before "
        "attaching the page's HTML or a screenshot."
    )


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
    because a single ``goto`` can legitimately land on either page: an
    unfinished (or stale) login redirects the grid URL right back to
    Passport — the manual login's one-shot verification probe and
    ``capture_storage_state``'s verify path can both be sent to the grid in
    that state, and waiting on the grid's marker alone would burn
    ``timeout_ms`` on every such attempt until the user finishes logging in.

    Returns ``True`` once a marker is found, ``False`` on timeout — mirrors
    ``direct_cli/browser/masters.py``'s ``_poll_until`` so a timeout is a
    normal, non-raising outcome the caller decides how to handle (a
    ``BrowserAuthError``/``BrowserCaptchaError`` from the content-based
    checks that follow it is almost always the more specific error the user
    should see, rather than a generic "marker never appeared").
    """
    deadline = _clock.now() + timeout_ms / 1000
    while _clock.now() < deadline:
        with contextlib.suppress(PlaywrightError):
            if any(page.locator(selector).first.count() > 0 for selector in selectors):
                return True
        page.wait_for_timeout(_PAGE_MARKER_POLL_MS)
    return False


# Every network-layer failure Chromium reports for a navigation surfaces from
# Playwright as an error whose message carries the Chromium network error
# code — ``net::ERR_ABORTED``, ``net::ERR_CONNECTION_RESET``,
# ``net::ERR_NAME_NOT_RESOLVED``, ``net::ERR_TIMED_OUT``, … (Chromium's
# ``net_error_list.h`` is the full family). This package only ever drives
# ``playwright.chromium``, so the Firefox ``NS_ERROR_*`` family cannot appear
# here, and one prefix covers the whole family — no per-code denylist to
# drift out of sync with Chromium (same "declare the marker once" spirit as
# ``_LOGIN_PAGE_MARKERS`` above).
_NETWORK_NAVIGATION_MARKER = "net::ERR_"

# Retry budget for :func:`_goto_with_network_retry` — enough attempts to ride
# out a flaky-VPN blip on a navigation the flow cannot continue without (the
# Passport login page, ``playwright login``'s verification probe), while still
# failing fast with a clear network-level message when the connection is
# genuinely down. The login verification probe
# (:func:`_grid_shows_authenticated_session`) uses the same budget: while the
# user is still typing, the cookie poll navigates nothing at all (issue
# #858), so a network failure can only strike once there is a session to
# verify — and a rerun after restoring the connection re-verifies the
# still-saved session instantly.
_GOTO_NETWORK_ATTEMPTS = 3
_GOTO_NETWORK_RETRY_INTERVAL_MS = 1_000


def _is_network_navigation_error(exc: BaseException) -> bool:
    """True if ``exc`` is a Playwright navigation failure from the network layer.

    Issue #857: an unstable VPN/proxy aborts ``Page.goto`` before Playwright
    ever sees a response — ``net::ERR_ABORTED`` in the live report — or, on
    a merely *slow* connection, lets the navigation hit Playwright's own
    timeout first (``Page.goto: Timeout 30000ms exceeded``, no ``net::ERR_``
    code in sight — #865 review flagged it as the more frequent companion
    of a flaky VPN). Either way the failure says nothing about the session's
    validity, so it must be retried and reported as a connectivity problem,
    never folded into the expired/wrong-account story
    :class:`BrowserAuthError` tells.

    Scoped by call site, not by message alone: this helper is only ever
    asked about exceptions raised by a ``goto`` navigation, so matching
    Playwright's :class:`TimeoutError` by class here cannot misclassify a
    timeout from some unrelated ``wait_for_*`` call.
    """
    if not isinstance(exc, PlaywrightError):
        return False
    return _NETWORK_NAVIGATION_MARKER in str(exc) or isinstance(
        exc, PlaywrightTimeoutError
    )


def _goto_with_network_retry(page: "Page", url: str) -> None:
    """``page.goto(url, wait_until="commit")``, retrying network-layer aborts.

    Transient ``net::ERR_*`` failures (flaky VPN/proxy — issue #857) are
    retried up to :data:`_GOTO_NETWORK_ATTEMPTS` times, waiting
    :data:`_GOTO_NETWORK_RETRY_INTERVAL_MS` between attempts via
    ``page.wait_for_timeout`` — the #767 tick primitive, never a raw sleep the
    offline harness cannot advance. Any other Playwright failure is re-raised
    untouched: only the network layer is ours to retry. Exhaustion raises
    :class:`BrowserNetworkError`, which names the connectivity cause
    explicitly so the user is not sent chasing a session that isn't expired.
    """
    for attempt in range(1, _GOTO_NETWORK_ATTEMPTS + 1):
        try:
            page.goto(url, wait_until="commit")
            return
        except PlaywrightError as exc:
            if not _is_network_navigation_error(exc):
                raise
            if attempt == _GOTO_NETWORK_ATTEMPTS:
                raise BrowserNetworkError(
                    f"Navigation to {url} failed at the network level "
                    f"({exc}). This is a connectivity problem (VPN, proxy or "
                    "unstable network), not an expired or wrong-account "
                    "session. Restore the connection and retry."
                ) from exc
            page.wait_for_timeout(_GOTO_NETWORK_RETRY_INTERVAL_MS)


def _is_yandex_ru_domain(domain: str) -> bool:
    """True for ``yandex.ru`` itself and any dotted subdomain of it.

    Covers both forms Playwright reports — host-only (``yandex.ru``,
    ``passport.yandex.ru``) and the dotted cookie-domain (``.yandex.ru``) —
    without accepting suffix look-alikes: a naive ``endswith("yandex.ru")``
    would let ``notyandex.ru`` through (review of #858).
    """
    return domain == "yandex.ru" or domain.endswith(".yandex.ru")


# Passport's identity cookie: its value is the login of the account the
# session belongs to (issue #916's owner stamp), set on the ``*.yandex.ru``
# hosts alongside the SSO pair in :data:`_AUTH_SESSION_COOKIE_NAMES`.
# Deliberately no legacy-name fallback: this repo and its tests only ever
# observed ``yandex_login``, and a same-named foreign cookie would forge the
# owner stamp (and a false replacement warning) — review of PR #933. An
# absent cookie means an unstamped session, the soft fallback.
_OWNER_LOGIN_COOKIE_NAME = "yandex_login"

#: The cookie names whose presence (and server recognition) *is* the SSO
#: session — the auth pair plus the identity cookie. ``auth status`` reports
#: how many of these the saved jar carries (issue #954): a jar missing them
#: was never a session, while a jar carrying them can still have been
#: revoked server-side — what :func:`probe_sso_session` is for.
SSO_COOKIE_NAMES = _AUTH_SESSION_COOKIE_NAMES | {_OWNER_LOGIN_COOKIE_NAME}

#: UA platform token per host OS. Playwright's ``user_agent`` overrides
#: only the UA string — ``navigator.platform`` and ``sec-ch-ua-platform``
#: keep reporting the real host, so a Macintosh UA over Linux/Windows
#: platform hints is itself a fingerprint mismatch. Darwin's token is the
#: exact string validated live in #950.
_PLATFORM_TOKENS = {
    "Darwin": "Macintosh; Intel Mac OS X 10_15_7",
    "Windows": "Windows NT 10.0; Win64; x64",
    "Linux": "X11; Linux x86_64",
}


def _chrome_platform_token() -> str:
    """The host OS's Chrome UA token; unknown hosts take the X11 fallback."""
    return _PLATFORM_TOKENS.get(platform.system(), "X11; Linux x86_64")


#: UA sent by every browser context this module creates. The default
#: Playwright UA (``HeadlessChrome`` in headless) makes Yandex answer a
#: valid cookie jar with ``showcaptchafast`` / the login page — the session
#: cookies are issued to real Chrome, and a foreign UA reads as a bot
#: (#950: the same jar plus a Chrome/155 UA loaded Direct with HTTP 200,
#: the default UA got a captcha). Bump when Yandex tightens its checks.
DEFAULT_BROWSER_UA = (
    f"Mozilla/5.0 ({_chrome_platform_token()}) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
)


def _resolve_user_agent(explicit: Optional[str]) -> str:
    """Explicit argument > ``DIRECT_BROWSER_UA`` env > the Chrome default."""
    return explicit or os.environ.get("DIRECT_BROWSER_UA") or DEFAULT_BROWSER_UA


def _owner_login_from_cookies(
    cookies: Sequence[Dict[str, Any]],
) -> Optional[str]:
    """Best-effort owner stamp: the login behind a cookie jar (issue #916).

    Resolved from the same jar the auth checks read — the SSO cookies in
    :data:`_AUTH_SESSION_COOKIE_NAMES` and the identity cookie live on the
    same ``*.yandex.ru`` hosts. Returns ``None`` when the jar carries no
    identity cookie: callers then save an unstamped session (soft fallback),
    never fail.
    """
    for cookie in cookies:
        if cookie.get("name") != _OWNER_LOGIN_COOKIE_NAME:
            continue
        if not _is_yandex_ru_domain(str(cookie.get("domain", ""))):
            continue
        value = str(cookie.get("value") or "").strip()
        if value:
            return value
    return None


def _session_cookie_signature(
    cookies: Sequence[Dict[str, Any]],
) -> Optional[Tuple[Tuple[str, str], ...]]:
    """Fingerprint the Yandex SSO session cookies in a ``context.cookies()`` jar.

    Returns the sorted ``(name, value)`` pairs of the authenticated-session
    cookies (:data:`_AUTH_SESSION_COOKIE_NAMES`) on a :func:`_is_yandex_ru_domain`
    domain, or ``None`` when the jar holds none — i.e. "no session yet" vs.
    "some session". The manual login re-runs its grid
    verification exactly when this signature *changes*, so a rejected
    session stays rejected until Passport actually issues different cookies
    (a stale ``Session_id`` sitting in a reused profile does not re-trigger
    the probe every second), while a state that was merely inconclusive is
    retried.
    """
    pairs = sorted(
        (cookie["name"], cookie["value"])
        for cookie in cookies
        if cookie.get("name") in _AUTH_SESSION_COOKIE_NAMES
        and _is_yandex_ru_domain(str(cookie.get("domain", "")))
    )
    return tuple(pairs) if pairs else None


def _grid_shows_authenticated_session(page: "Page") -> Optional[bool]:
    """One-shot "is the session real?" check: navigate ``page`` to the grid once.

    Extracted from the manual-login poll loop (issue #858) so
    the loop can poll the cookie jar for free and only pay for a navigation
    when there is a session to verify. The checks are exactly the triad the
    old per-second loop ran — ``wait_until="commit"`` navigation (issue
    #686), marker poll (fail-closed on unrendered pages, issue #692), then
    the captcha and auth content scans.

    Returns a tri-state:

    - ``True`` — the grid rendered with an authenticated session;
    - ``False`` — Yandex served its login page instead: the cookie jar does
      not add up to a valid session (expired, or issued mid-login before the
      human actually finished). Only a *changed* jar is worth re-checking;
    - ``None`` — inconclusive: the page never rendered far enough to trust
      ``page.content()``. Retried on the next tick, unlike ``False``.
    """
    # Deferred import: GRID_URL's canonical source is masters.py (CLAUDE.md
    # "No URL literals outside the registry"); imported here rather than at
    # module load to avoid a session.py <-> masters.py import cycle — same
    # rationale as `capture_storage_state` below.
    from .masters import GRID_URL

    # Same retry-and-classify treatment as the Passport navigation and
    # `capture_storage_state`'s verify path (issues #857/#865): a flaky
    # VPN/proxy aborts `goto` at the network layer — transient aborts are
    # retried in place, a connection that stays dead fails as
    # `BrowserNetworkError`, and non-network Playwright errors are re-raised
    # untouched for the poll loop's guard to classify.
    _goto_with_network_retry(page, GRID_URL)
    # Either marker is a valid landing spot: an unfinished login redirects
    # the grid URL right back to Passport, so waiting on the grid's own
    # marker alone would burn the full timeout on a login-page landing (see
    # `_wait_for_marker`'s docstring). On the verification budget (a
    # dedicated one-shot page, not a once-a-second shared cadence anymore) a
    # full `_PAGE_MARKER_TIMEOUT_MS` is affordable and lets a slow first
    # paint of the grid SPA resolve instead of reporting a false "None".
    if not _wait_for_marker(page, _DIRECT_OR_PASSPORT_PAGE_MARKERS):
        return None
    html = page.content()
    assert_not_captcha(html)
    try:
        assert_authenticated(html)
    except BrowserAuthError:
        return False
    return True


#: Per-request budget of :func:`probe_sso_session`. A single GET, no retries:
#: a probe that cannot answer quickly is an inconclusive probe ("unknown"),
#: never a reason to block the caller.
_SSO_PROBE_TIMEOUT_SECONDS = 10.0


def revoked_sso_session_message() -> str:
    """The issue #954 diagnostic for a server-revoked SSO session.

    Shared verbatim by every revoked verdict site (``--no-verify`` import,
    the verify-failure path and a saved-session command failing mid-flight,
    plus ``auth status``'s revoked line), so the advice cannot drift between
    them: the fix is always re-login in Chrome and re-import.
    """
    return t(
        "Yandex's server no longer recognizes this browser session (the "
        "cookie-only check was redirected to passport.yandex.ru). Log in to "
        "https://direct.yandex.ru in Chrome, then run: {hint}"
    ).format(hint=HINT_LOGIN_BROWSER_CHROME)


def revoked_sso_session_error() -> "BrowserAuthError":
    """:class:`BrowserAuthError` carrying :func:`revoked_sso_session_message`."""
    return BrowserAuthError(revoked_sso_session_message())


def probe_sso_session(
    cookies: Sequence[Dict[str, Any]],
    *,
    timeout_seconds: float = _SSO_PROBE_TIMEOUT_SECONDS,
) -> str:
    """One cookie-only ``GET`` to the campaigns grid — no browser (issue #954).

    A server-side session revocation is invisible on disk: the cookies stay
    formally unexpired, every browser flow reads as the #870 login-page/bot-
    challenge ambiguity, and only a bare HTTP request settles it — the exact
    manual curl the #954 reporter had to run. This probe is that curl: the
    jar is sent as one ``Cookie`` header to ``GRID_URL`` and the *status line*
    is the whole verdict —

    - ``"alive"`` — HTTP 200: the server still recognizes this jar;
    - ``"revoked"`` — a 3xx redirect to ``passport.yandex.ru``: the server
      bounces this jar to the login page. The session was revoked
      server-side; no browser/fingerprint diagnosis applies;
    - ``"unknown"`` — everything else: network failure, timeout, a non-redirect
      status, a redirect somewhere else. Inconclusive, and deliberately
      non-fatal at every call site: an unknown probe must never block a flow
      that worked without it.

    A jar carrying none of :data:`_AUTH_SESSION_COOKIE_NAMES` is probed
    without a request — with no SSO cookie there is no session for the
    server to either recognize or revoke, so ``"unknown"`` is the honest
    verdict (the caller's own no-session error already covers it).
    """
    # Deferred import: GRID_URL's canonical source is masters.py (CLAUDE.md
    # "No URL literals outside the registry"); deferred like the other GRID_URL
    # uses in this module to keep the session.py <-> masters.py cycle broken.
    from .masters import GRID_URL

    has_sso_cookie = any(
        cookie.get("name") in _AUTH_SESSION_COOKIE_NAMES
        and _is_yandex_ru_domain(str(cookie.get("domain", "")))
        for cookie in cookies
    )
    if not has_sso_cookie:
        return "unknown"
    # The full jar, like the manual curl diagnosis: all hosts' cookies share
    # the request, duplicates resolve to the last occurrence — the SSO pair
    # itself lives only on .yandex.ru and does not collide.
    header = "; ".join(
        f"{cookie['name']}={cookie['value']}"
        for cookie in cookies
        if cookie.get("name") and cookie.get("value") is not None
    )
    request = urllib.request.Request(
        GRID_URL,
        headers={
            "Cookie": header,
            # The jar was issued to Chrome; the #950 UA is what keeps Yandex
            # from answering even a valid jar with a captcha interstitial.
            "User-Agent": _resolve_user_agent(None),
        },
        method="GET",
    )

    class _NoRedirects(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None  # surfaces the 3xx itself as an HTTPError

    opener = urllib.request.build_opener(_NoRedirects)
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            return "alive" if response.status == 200 else "unknown"
    except urllib.error.HTTPError as error:
        if 300 <= error.code < 400:
            location = urllib.parse.urlsplit(error.headers.get("Location", ""))
            if location.hostname == "passport.yandex.ru":
                return "revoked"
        return "unknown"
    except (urllib.error.URLError, OSError):
        # URLError covers DNS/refused/timeout; OSError the raw socket errors.
        # Connectivity says nothing about the session (#857's lesson).
        return "unknown"


def probe_saved_session(path: Optional[Path] = None) -> str:
    """:func:`probe_sso_session` over the saved envelope's jar (issue #954).

    Best-effort by design: a missing, corrupt or cookie-less envelope probes
    as ``"unknown"`` without touching the network — ``auth status`` and the
    open-session failure path must stay informative on a machine that simply
    has no session yet.
    """
    envelope = store.read_session_envelope(path)
    storage_state = envelope.get("storage_state") if envelope else None
    cookies = storage_state.get("cookies") if isinstance(storage_state, dict) else None
    if not isinstance(cookies, list):
        return "unknown"
    return probe_sso_session(cookies)


def sso_cookie_names(cookies: Sequence[Dict[str, Any]]) -> List[str]:
    """Which of :data:`SSO_COOKIE_NAMES` a jar carries, sorted (issue #954).

    Only ``*.yandex.ru``-domain cookies count — the same scoping
    :func:`_owner_login_from_cookies` uses, so a foreign-domain look-alike
    cannot inflate the inventory.
    """
    return sorted(
        {
            cookie["name"]
            for cookie in cookies
            if cookie.get("name") in SSO_COOKIE_NAMES
            and _is_yandex_ru_domain(str(cookie.get("domain", "")))
        }
    )


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
    sync_playwright,
    *,
    headless: bool,
    storage_state: Optional[Dict[str, Any]] = None,
    user_agent: Optional[str] = None,
) -> Generator[Tuple["Browser", Any], None, None]:
    """Shared launch/teardown body for both session flavours.

    Yields ``(browser, context)`` so callers add cookies or pass
    ``storage_state`` before creating a page; teardown closes the context
    and then the browser.
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        try:
            context = browser.new_context(
                locale="ru-RU",
                storage_state=storage_state,
                user_agent=_resolve_user_agent(user_agent),
            )
            try:
                yield browser, context
            finally:
                context.close()
        finally:
            browser.close()


def login_manual_session(*, timeout_ms: int = _LOGIN_WAIT_TIMEOUT_MS) -> Dict[str, Any]:
    """One manual login in a visible window; saves the single session envelope.

    The context is a fresh throwaway (:func:`_launch_context` — the same
    factory the read commands use, so the session is issued to and later
    replayed under the same user-agent, #950). The wait mechanics: poll the
    context cookie jar for the
    SSO cookies, verify once via a short-lived probe tab, fail fast when the
    window dies (issue #858 poll, #692 fail-closed). On success the resulting
    ``storage_state`` is saved as the only browser session this CLI keeps —
    owner-stamped from the same jar — and nothing else is written to disk:
    no persistent profile, no pointer, no marker.

    Returns ``{"owner_login": Optional[str], "verified": True}``. Raises
    :class:`BrowserAuthError` on timeout, :class:`BrowserSessionError` when
    the window dies before the login completes.
    """
    sync_playwright = _import_sync_playwright()

    with _launch_context(sync_playwright, headless=False) as (_, context):
        page = context.new_page()
        _goto_with_network_retry(page, _PASSPORT_LOGIN_URL)
        if not _wait_for_marker(page, _PASSPORT_PAGE_MARKERS):
            # Fail closed (issue #692): an unrendered shell must not sail
            # through as a rendered login page.
            raise BrowserSessionError(
                f"Timed out waiting for {_PASSPORT_LOGIN_URL} to render. "
                f"Retry {HINT_LOGIN_BROWSER}."
            )

        deadline = _clock.now() + timeout_ms / 1000
        rejected_signature: Optional[Tuple[Tuple[str, str], ...]] = None
        try:
            while _clock.now() < deadline:
                signature = _session_cookie_signature(context.cookies())
                if signature is not None and signature != rejected_signature:
                    probe = context.new_page()
                    try:
                        verdict = _grid_shows_authenticated_session(probe)
                    except PlaywrightError as exc:
                        if not _is_network_navigation_error(exc):
                            raise
                        # Inconclusive verification: the same signature is
                        # retried on the next tick.
                        verdict = None
                    finally:
                        with contextlib.suppress(PlaywrightError):
                            probe.close()
                    if verdict:
                        cookies = context.cookies()
                        owner_login = _owner_login_from_cookies(cookies)
                        store.save_session(
                            context.storage_state(),
                            owner_login=owner_login,
                            source={"kind": "manual", "verified": True},
                        )
                        return {"owner_login": owner_login, "verified": True}
                    if verdict is False:
                        # Conclusive "no valid session": wait for Passport to
                        # issue different cookies instead of re-probing this
                        # jar every tick.
                        rejected_signature = signature
                page.wait_for_timeout(_LOGIN_POLL_INTERVAL_MS)
        except PlaywrightError as exc:
            raise BrowserSessionError(
                "The browser window was closed (or crashed) while waiting "
                "for you to log in — there is nothing left to wait for. Run "
                f"{HINT_LOGIN_BROWSER} again."
            ) from exc

        raise BrowserAuthError(
            f"Timed out after {timeout_ms // 1000}s waiting for login to "
            f"{_PASSPORT_LOGIN_URL} to complete. Run {HINT_LOGIN_BROWSER} "
            "again and finish signing in within the time limit."
        )


def capture_storage_state(
    *,
    profile_dir: Optional[Path] = None,
    chrome_profile: str = "Default",
    headless: bool = True,
    verify: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Decrypt Chrome's Yandex cookies and return a Playwright ``storage_state``.

    Used by ``playwright login`` (``direct_cli/commands/browser_session.py``)
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
    error. ``verify=False`` skips the browser navigation — for a captcha-gated
    network where the cookies are known-good but a live check isn't possible —
    but still runs the cookie-only probe (:func:`probe_sso_session`): a jar
    Yandex no longer recognizes is refused even when the browser check is
    skipped (issue #954).

    Returns ``(storage_state, source_meta)`` — ``source_meta`` is diagnostic
    provenance (``profile_dir``, ``chrome_profile``) for the saved envelope,
    never used to re-decrypt.
    """
    sync_playwright = _import_sync_playwright()
    source_root = _resolve_profile_dir(profile_dir)

    from . import _chrome_crypto

    cookies = _chrome_crypto.load_yandex_cookies(source_root, chrome_profile)

    # Issue #954: --no-verify skips the browser check, but a jar the server
    # has already stopped recognizing must not be saved under a fresh-looking
    # envelope — that is exactly what masked the revoked session in the #954
    # report. The probe is cookie-only, so this refusal happens before any
    # browser is launched.
    if not verify and probe_sso_session(cookies) == "revoked":
        raise revoked_sso_session_error()

    def _capture(*, headless: bool) -> Tuple[Dict[str, Any], bool]:
        """Launch one context, inject the cookies, optionally verify.

        Returns ``(storage_state, verified)`` — ``verified`` is False both
        for ``verify=False`` runs and for the issue #870 render-timeout path
        below (cookies saved, live check inconclusive).
        """
        with _launch_context(sync_playwright, headless=headless) as (
            _browser,
            context,
        ):
            context.add_cookies(cookies)
            verified = False
            if verify:
                # Deferred import: direct_cli/browser/masters.py's GRID_URL is the
                # single canonical source for this URL (CLAUDE.md "No URL
                # literals outside the registry") — importing it here (rather
                # than at module load) avoids a session.py <-> masters.py import
                # cycle, since masters.py itself imports from session.py.
                from .masters import GRID_URL

                page = context.new_page()
                # Same retry-and-classify treatment as the login flow's
                # navigations (issue #857): a network-layer abort here used to
                # escape `direct playwright login` as a raw Playwright traceback,
                # reading like a session problem when the connection was the
                # culprit.
                _goto_with_network_retry(page, GRID_URL)
                # Either marker is a valid landing spot: a bad/expired cookie
                # jar redirects the grid URL to Passport instead of rendering
                # the grid, and `assert_authenticated` below is what turns that
                # into the specific `BrowserAuthError` (see `_wait_for_marker`'s
                # docstring for why a single marker would be wrong here).
                # Double timeout: issue #870's live repro had a session that
                # WAS fine fail the 30s render wait in a visible window.
                if not _wait_for_marker(
                    page,
                    _DIRECT_OR_PASSPORT_PAGE_MARKERS,
                    timeout_ms=_PAGE_MARKER_TIMEOUT_MS * 2,
                ):
                    # Issue #870 п.3: a render timeout is NOT proof of bad
                    # cookies — the live repro saved a working session the
                    # CLI reported as failed. Unlike the #692 fail-closed
                    # rationale (never CLAIM a verified session without a
                    # rendered page), the cookies are still saved and
                    # reported as unverified; every `direct masters` flow
                    # re-checks auth markers on use, so a genuinely bad jar
                    # still fails loudly downstream.
                    # stderr, not stdout: `direct playwright login --format
                    # json` prints its machine-readable payload on stdout,
                    # and this warning fires exactly in the scenario where a
                    # script most needs to parse that payload (issue #850).
                    print_warning_stderr(
                        f"Timed out waiting for {GRID_URL} to render while "
                        "verifying the session — the session was saved "
                        "WITHOUT live verification (issue #870: a headless "
                        "render timeout does not mean the cookies are bad). "
                        "Run `direct playwright doctor` to inspect the "
                        "chain; `direct masters` re-verifies on use. "
                        f"{_stale_marker_hint()}"
                    )
                else:
                    html = page.content()
                    assert_not_captcha(html)
                    assert_authenticated(html)
                    verified = True
            return context.storage_state(), verified

    try:
        storage_state, verified = _capture(headless=headless)
    except BrowserAuthError as auth_error:
        # Issue #954: a server-side revocation is invisible to the browser
        # check — it reads as the same login page a bot challenge produces.
        # One cookie-only GET settles which story is true before any of the
        # expiry-based messages below is chosen.
        if probe_sso_session(cookies) == "revoked":
            raise revoked_sso_session_error() from auth_error
        # Issue #870 п.2: judge the cookies by expires_utc before saying
        # anything about expiry. A failed headless verification never upgrades
        # itself to a visible browser; the caller must opt in explicitly.
        # Only the auth cookies are judged here: load_yandex_cookies returns
        # every host cookie, and the jar always carries long-lived tracking
        # cookies (yandexuid etc.) that would make ANY session look fresh.
        auth_cookies = [
            c for c in cookies if c.get("name") in _AUTH_SESSION_COOKIE_NAMES
        ]
        freshness = _chrome_crypto.any_cookie_valid_now(auth_cookies)
        if freshness is False:
            raise BrowserAuthError(
                "Yandex served its login page instead of Direct, and the "
                "Chrome cookie database says the session cookies HAVE "
                "expired (expires_utc in the past). Log in to "
                "https://direct.yandex.ru in Chrome, then run: "
                f"{HINT_LOGIN_BROWSER_CHROME}."
            ) from None
        if not headless:
            raise
        raise BrowserAuthError(
            "Headless verification hit Yandex's login page although the Chrome "
            "cookies do not show an expired session. The session may have been "
            "invalidated server-side or rejected by a bot challenge. "
            "No visible browser was opened. Retry with: "
            f"{HINT_LOGIN_BROWSER_CHROME}."
        ) from auth_error

    source_meta = {
        "profile_dir": str(source_root),
        "chrome_profile": chrome_profile,
        "verified": verified,
        # Issue #916: the owner stamp, resolved from the same decrypted jar
        # the auth checks run on. None → session is saved without a stamp.
        "owner_login": _owner_login_from_cookies(cookies),
    }
    return storage_state, source_meta


@contextlib.contextmanager
def open_saved_session(
    *,
    headless: bool = True,
    session_path: Optional[Path] = None,
) -> Generator["Page", None, None]:
    """Launch a bundled Chromium restoring a session saved by `playwright login`.

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
            "Yandex served its login page instead of Direct. The session "
            "cookies may be expired, may belong to a different account, "
            "or a headless browser may have been redirected by Yandex's "
            "bot challenge (issue #870 — this reads as a login page even "
            "when the cookies are fresh)."
        )
