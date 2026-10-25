"""Saved browser authorization shared by auth and browser-backed commands."""

import contextlib
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Generator, Optional

from .._auth_hints import HINT_LOGIN_BROWSER
from ..i18n import t
from . import session, store

if TYPE_CHECKING:
    from playwright.sync_api import Page


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
        "persistent_profile": {"path": str(persistent_dir), "usable": usable},
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
