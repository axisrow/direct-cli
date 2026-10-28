"""Saved browser authorization shared by auth and browser-backed commands."""

import contextlib
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Generator, Optional

from .._auth_hints import HINT_LOGIN_BROWSER
from ..i18n import t
from ..output import print_warning_stderr
from . import session, store

if TYPE_CHECKING:
    from playwright.sync_api import Page


def _marker_owner(profile_dir: Path) -> Optional[str]:
    """Owner login stamped into the profile marker (issue #916), if any.

    ``None`` for a marker saved before the stamp existed — soft fallback.
    """
    try:
        return (profile_dir / session.PROFILE_MARKER_NAME).read_text(
            encoding="utf-8"
        ).strip() or None
    except OSError:
        return None


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
    tier = status.get("active_tier")
    if tier is None:
        return  # nothing is about to open; the missing-session error reports that
    if tier == "1.5":
        owner = status["persistent_profile"].get("owner")
    else:
        owner = status["saved_session"].get("owner_login")
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


def session_status(profile_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Inspect saved authorization without launching a browser or decrypting cookies."""
    persistent_dir = profile_dir or session.configured_persistent_profile_dir()
    usable = session.persistent_profile_is_usable(persistent_dir)
    saved = store.session_status()
    tier, source = None, None
    if usable:
        tier, source = "1.5", "masters login"
    elif saved["exists"] and not saved["error"] and saved["expired"] is not True:
        tier, source = "2", "playwright login"
    return {
        "active_tier": tier,
        "active_source": source,
        "persistent_profile": {
            "path": str(persistent_dir),
            "usable": usable,
            "owner": _marker_owner(persistent_dir),
        },
        "saved_session": saved,
    }


@contextlib.contextmanager
def open_session(
    *, headless: bool = True, profile_dir: Optional[Path] = None
) -> Generator["Page", None, None]:
    """Use saved credentials once; never import Chrome cookies or retry an operation."""
    # Every tier below launches a browser, so a missing playwright must
    # surface as the install hint even when no saved session exists — the
    # session-state report would otherwise preempt the actionable error.
    session._import_sync_playwright()
    status = session_status(profile_dir)
    # Before any launch: a stamped session owned by another account fails
    # here, loudly, instead of navigating the wrong account's pages (#907).
    _assert_session_owner(status)
    if status["active_tier"] == "1.5":
        opener = session.open_persistent_session(
            headless=headless,
            profile_dir=Path(status["persistent_profile"]["path"]),
        )
    elif status["active_tier"] == "2":
        opener = session.open_saved_session(headless=headless)
    else:
        raise session.BrowserSessionMissingError(
            t("No saved browser session. Run: {hint}").format(hint=HINT_LOGIN_BROWSER)
        )
    try:
        with opener as page:
            yield page
    except session.BrowserAuthError as exc:
        raise session.BrowserAuthError(
            f"{exc}\n{t('Run: {hint}').format(hint=HINT_LOGIN_BROWSER)}"
        ) from exc


def validate_persistent_profile(profile_dir: Path) -> None:
    """Refuse to remove directories not owned by the CLI, including symlinks."""
    if profile_dir.is_symlink():
        raise session.BrowserSessionError(
            f"Refusing to delete {profile_dir}: it is a symlink, not a "
            "profile directory created by `direct masters login`."
        )
    if not profile_dir.exists():
        return
    if not profile_dir.is_dir():
        raise session.BrowserSessionError(
            f"Refusing to delete {profile_dir}: not a directory."
        )
    if not (profile_dir / session.PROFILE_MARKER_NAME).is_file():
        raise session.BrowserSessionError(
            f"Refusing to delete {profile_dir}: it has no "
            f"{session.PROFILE_MARKER_NAME} marker, so it was not created by "
            "`direct masters login`. Delete it by hand if you are sure."
        )


def logout_persistent_profile(profile_dir: Optional[Path] = None) -> bool:
    """Delete only a CLI-owned profile and the pointer referring to that profile."""
    target = profile_dir or session.configured_persistent_profile_dir()
    validate_persistent_profile(target)
    try:
        pointer_target = session.PROFILE_POINTER_PATH.read_text(
            encoding="utf-8"
        ).strip()
    except OSError:
        pointer_target = None
    existed = target.exists()
    if existed:
        shutil.rmtree(target)
    if pointer_target and Path(pointer_target) == target.resolve():
        session.PROFILE_POINTER_PATH.unlink(missing_ok=True)
    return existed


def logout() -> None:
    """Forget both CLI browser sessions, leaving the user's real Chrome untouched."""
    target = session.configured_persistent_profile_dir()
    targets = {target, session.DEFAULT_PERSISTENT_PROFILE_DIR}
    for profile_dir in targets:
        validate_persistent_profile(profile_dir)
    saved_path = store.PLAYWRIGHT_SESSION_PATH
    if saved_path.is_dir() and not saved_path.is_symlink():
        raise session.BrowserSessionError(f"Not a session file: {saved_path}")
    for profile_dir in targets:
        logout_persistent_profile(profile_dir)
    saved_path.unlink(missing_ok=True)
