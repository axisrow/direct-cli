"""Saved browser authorization shared by auth and browser-backed commands."""

import contextlib
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Generator, Optional

from .._auth_hints import HINT_LOGIN_BROWSER, HINT_LOGIN_BROWSER_MANUAL
from ..i18n import t
from ..output import print_warning_stderr
from . import session, store

if TYPE_CHECKING:
    from playwright.sync_api import Page

# One-time cleanup target: the pre-refactor persistent Chromium profile (the
# old `direct masters login` store). Best-effort removal in 0.5.x so an
# upgrade does not leave a dead cookie jar on disk; drop in 0.6.x.
_LEGACY_PROFILE_DIR = Path.home() / ".direct-cli" / "chrome-profile"
_LEGACY_PROFILE_MARKER = ".direct-cli-profile"  # ponytail: temp, remove in 0.6.x


def _comparable_login(login: Any) -> Optional[str]:
    """Normalize a stored login into something comparable to a Passport login.

    Pre-#480 profiles may still store a Passport *email*; the owner stamp
    carries the Client-Login, so an email is not a mismatch — it is "no
    opinion". Same for anything non-string or empty.
    """
    if not isinstance(login, str):
        return None
    login = login.strip()
    if not login or "@" in login:
        return None
    return login


def _expected_session_login() -> Optional[str]:
    """Login of the account the CLI's own credential chain considers active.

    A tokenless, network-free mirror of ``get_credentials_with_source``'s
    ladder — the anchor the owner check (#907) compares a session stamp
    against: the folder-linked profile's stored login (an explicit binding
    is isolated — configured link, no fall-through, per #917), else base
    ``YANDEX_DIRECT_LOGIN`` alongside a base ``YANDEX_DIRECT_TOKEN``, else —
    only under the #904 opt-in, like the chain's own
    ``allow_active_profile=inherit_globally_enabled()`` — the active
    profile's stored login. ``None`` = no comparable anchor (browser-only
    setup, an unconfigured link/profile, an email-only login, or a stale
    global profile in a default no-binding folder): the check then has no
    opinion instead of guessing.
    """
    from .. import auth as api_auth

    linked = (os.getenv(api_auth.BIND_PROFILE_ENV) or "").strip()
    if linked:
        profile = api_auth.get_oauth_profile(linked)
        return _comparable_login(profile.get("login")) if profile else None
    if os.getenv("YANDEX_DIRECT_TOKEN"):
        return _comparable_login(os.getenv("YANDEX_DIRECT_LOGIN"))
    # The silent active-profile rung exists only under the #904 opt-in: in
    # the default no-binding folder a stale global profile is nobody's
    # anchor, and a false refusal here could not be fixed by the re-login
    # hint this check prints.
    if api_auth.inherit_globally_enabled():
        active = api_auth.get_active_profile()
        if active:
            profile = api_auth.get_oauth_profile(active)
            if profile:
                return _comparable_login(profile.get("login"))
    return None


def _assert_session_owner(status: Dict[str, Any]) -> None:
    """Refuse to open a session that demonstrably belongs to another account.

    Issue #907: after the user switched Yandex profiles in their real
    browser, every ``masters`` command silently worked on the wrong account
    and surfaced only as an unrelated "did not render" timeout. The owner
    stamps from #916 make a pre-flight check free: a *stamped* session whose
    owner differs from the active credential anchor fails loudly
    (:class:`session.BrowserAuthError`) before any navigation happens; an
    *unstamped* session (saved before #916) stays a soft fallback and only
    warns on stderr. No anchor means no opinion — a browser-only setup has
    nothing to compare against. The warning is safety output: it goes
    through ``print_warning_stderr`` and is never silenced by DIRECT_QUIET.
    """
    if not status.get("exists"):
        return  # nothing is about to open; the missing-session error reports that
    owner = status.get("owner_login")
    if not owner:
        print_warning_stderr(
            t(
                "The saved browser session carries no owner stamp (the "
                "identity cookie that stores it is missing), so the account "
                "it belongs to cannot be verified. Run: {hint}"
            ).format(hint=HINT_LOGIN_BROWSER)
        )
        return
    expected = _expected_session_login()
    if not expected or owner.strip().lower() == expected.strip().lower():
        return
    raise session.BrowserAuthError(
        t(
            "The saved browser session belongs to {owner}, but the active "
            "CLI profile is {expected} — refusing to work on the wrong "
            "Yandex account. Re-login: {hint}"
        ).format(owner=owner, expected=expected, hint=HINT_LOGIN_BROWSER)
    )


def session_status() -> Dict[str, Any]:
    """Inspect saved authorization without launching a browser or decrypting cookies.

    The flat saved-session report (``exists``, ``owner_login``, ``expired``,
    ``cookie_count``, ``path``, ``error``) — the single browser session this
    CLI keeps. The pre-refactor ``active_tier``/``persistent_profile`` keys
    are gone (BREAKING): there is exactly one store.
    """
    return store.session_status()


@contextlib.contextmanager
def open_session(*, headless: bool = True) -> Generator["Page", None, None]:
    """Open the single saved session; auto-import from Chrome when unusable.

    Auto-import is the contract now (#950 review): when the saved session is
    missing, corrupt or expired, the live session is copied from the user's
    Chrome headlessly — no window opens for that (Keychain may be asked once
    for the cookie-decryption key). A failed import raises
    :class:`session.BrowserSessionMissingError` with the login hint;
    the explicit manual-login command (:func:`session.login_manual_session`)
    remains the only path that opens a window.
    """
    # The import below launches a browser, so a missing playwright must
    # surface as the install hint even when no saved session exists — the
    # session-state report would otherwise preempt the actionable error.
    session._import_sync_playwright()
    saved = session_status()
    if not (
        saved.get("exists") and not saved.get("error") and saved.get("expired") is not True
    ):
        try:
            storage_state, source_meta = session.capture_storage_state(headless=True)
        except session.BrowserSessionError as exc:
            raise session.BrowserSessionMissingError(
                t(
                    "No usable saved browser session and the automatic import "
                    "from Chrome failed: {error}. Run: {hint}"
                ).format(error=exc, hint=HINT_LOGIN_BROWSER_MANUAL)
            ) from exc
        store.save_session(
            storage_state,
            owner_login=source_meta.get("owner_login"),
            source=source_meta,
        )
        saved = session_status()
    # Before any launch: a stamped session owned by another account fails
    # here, loudly, instead of navigating the wrong account's pages (#907).
    _assert_session_owner(saved)
    try:
        with session.open_saved_session(headless=headless) as page:
            yield page
    except session.BrowserAuthError as exc:
        raise session.BrowserAuthError(
            f"{exc}\n{t('Run: {hint}').format(hint=HINT_LOGIN_BROWSER)}"
        ) from exc


def _cleanup_legacy_chrome_profile() -> None:
    """Best-effort removal of the pre-refactor persistent Chromium profile.

    Only a directory carrying the old CLI-ownership marker is removed; a
    path that does not match (symlink, foreign directory, anything odd) is
    left for the user to delete by hand. A one-time cleanup must never fail
    the logout.
    """
    profile_dir = _LEGACY_PROFILE_DIR
    try:
        if profile_dir.is_symlink() or not profile_dir.is_dir():
            return
        if not (profile_dir / _LEGACY_PROFILE_MARKER).is_file():
            return
        shutil.rmtree(profile_dir)
    except OSError:
        pass  # ponytail: one-time cleanup, remove with the constants in 0.6.x


def logout() -> None:
    """Forget the saved browser session, leaving the user's real Chrome untouched."""
    saved_path = store.PLAYWRIGHT_SESSION_PATH
    if saved_path.is_dir() and not saved_path.is_symlink():
        raise session.BrowserSessionError(f"Not a session file: {saved_path}")
    saved_path.unlink(missing_ok=True)
    _cleanup_legacy_chrome_profile()
