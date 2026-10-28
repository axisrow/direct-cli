"""
Read-only diagnostics for the browser-session pipeline (``direct playwright doctor``).

Invariant (enforced by tests in ``tests/test_playwright_session.py``): this
module NEVER calls :func:`direct_cli.browser.session.capture_storage_state`,
NEVER launches a real browser (``chromium.launch``), and NEVER writes
anything to disk or reads Keychain. The explicit manual-login command is the
only one that logs in and persists a session — ``doctor`` only inspects and
reports (the auto-import lives in ``open_session``, not here).

Each check runs in its own ``try/except`` so one failing check never aborts
the rest of the report — a doctor that stops at the first problem defeats the
point of a doctor.
"""

from __future__ import annotations

import importlib.util
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from . import store
from .._auth_hints import HINT_LOGIN_BROWSER_CHROME
from ._chrome_crypto import (
    ChromeCookieError,
    find_cookie_db,
    platform_iterations,
)
from .session import default_chrome_profile_dir


@dataclass
class Check:
    """One diagnostic result. ``ok=None`` means "unknown / not applicable"."""

    name: str
    ok: Optional[bool]
    detail: str
    hint: Optional[str] = None


_INSTALL_HINT = 'pip install "direct-cli[browser]"'


def _check_platform_supported() -> Check:
    system = platform.system()
    try:
        platform_iterations(system)
    except ChromeCookieError as exc:
        return Check("platform_supported", False, str(exc))
    return Check("platform_supported", True, system)


def _check_module_installed(name: str, package_label: str) -> Check:
    spec = importlib.util.find_spec(name)
    if spec is None:
        return Check(
            f"{name}_installed",
            False,
            f"{package_label} is not installed",
            hint=_INSTALL_HINT,
        )
    return Check(f"{name}_installed", True, f"{package_label} is installed")


def _check_chromium_downloaded() -> Check:
    if importlib.util.find_spec("playwright") is None:
        return Check(
            "chromium_downloaded",
            None,
            "skipped — playwright is not installed",
        )
    try:
        from playwright.sync_api import sync_playwright

        # ``chromium.executable_path`` is a property lookup, not a launch —
        # it does not start a browser process.
        with sync_playwright() as playwright:
            exe = Path(playwright.chromium.executable_path)
    except Exception as exc:  # noqa: PIE786 - playwright-internal, deliberately broad
        return Check(
            "chromium_downloaded", False, str(exc), hint="playwright install chromium"
        )
    if not exe.exists():
        return Check(
            "chromium_downloaded",
            False,
            f"not found at {exe}",
            hint="playwright install chromium",
        )
    return Check("chromium_downloaded", True, str(exe))


def _check_chrome_profile_dir(profile_dir: Optional[Path]) -> Check:
    resolved = profile_dir or default_chrome_profile_dir()
    if resolved is None:
        return Check(
            "chrome_profile_dir",
            False,
            "could not determine a default Chrome profile directory on this platform",
            hint="Pass --profile-dir <your Chrome user-data-dir>",
        )
    if not resolved.exists():
        return Check(
            "chrome_profile_dir",
            False,
            f"not found: {resolved}",
            hint="Pass --profile-dir <your Chrome user-data-dir>",
        )
    return Check("chrome_profile_dir", True, str(resolved))


def _check_cookie_db_found(profile_dir: Optional[Path], chrome_profile: str) -> Check:
    resolved = profile_dir or default_chrome_profile_dir()
    if resolved is None or not resolved.exists():
        return Check(
            "cookie_db_found",
            None,
            "skipped — Chrome profile directory not found",
        )
    try:
        db_path = find_cookie_db(resolved / chrome_profile)
    except ChromeCookieError as exc:
        return Check(
            "cookie_db_found",
            False,
            str(exc),
            hint="Pass --chrome-profile (e.g. 'Profile 1')",
        )
    return Check("cookie_db_found", True, str(db_path))


def _check_saved_session(session_path: Optional[Path]) -> Check:
    status = store.session_status(session_path)
    if not status["exists"]:
        return Check(
            "saved_session",
            False,
            "not found",
            hint=f"Run: {HINT_LOGIN_BROWSER_CHROME}",
        )
    if status["error"]:
        return Check(
            "saved_session",
            False,
            status["error"],
            hint=f"Run: {HINT_LOGIN_BROWSER_CHROME}",
        )
    detail = (
        f"{status['path']} ({status['cookie_count']} cookies, "
        f"mode={status['mode']}, age={status['age_seconds']}s)"
    )
    owner = status.get("owner_login")
    if owner:
        # Issue #916: name the account the saved session belongs to.
        detail += f", owner={owner}"
    return Check("saved_session", True, detail)


def _check_saved_session_fresh(session_path: Optional[Path]) -> Check:
    status = store.session_status(session_path)
    if not status["exists"] or status["error"]:
        return Check("saved_session_fresh", None, "skipped — no saved session")
    expired = status["expired"]
    if expired is None:
        return Check(
            "saved_session_fresh",
            None,
            "unknown — saved session has no cookie expiry to check",
        )
    if expired:
        return Check(
            "saved_session_fresh",
            False,
            "saved session has expired",
            hint=f"Run: {HINT_LOGIN_BROWSER_CHROME}",
        )
    return Check(
        "saved_session_fresh",
        True,
        "not expired (cookie expiry "
        "only — server-side validity is not checked; run a read "
        "command, e.g. `direct masters list`, to confirm)",
    )


def run_diagnostics(
    *,
    profile_dir: Optional[Path] = None,
    chrome_profile: str = "Default",
    session_path: Optional[Path] = None,
) -> List[Check]:
    """Run every doctor check and return the full list, in a fixed order.

    Never raises: every check that can fail is wrapped individually so one
    failure (e.g. a Keychain error) does not prevent the rest of the report
    from being produced.
    """
    checks: List[Check] = []

    def _run(fn, *args) -> Check:
        try:
            return fn(*args)
        except Exception as exc:  # noqa: PIE786 - one check must never abort the rest
            return Check(fn.__name__.lstrip("_"), False, f"unexpected error: {exc}")

    checks.append(_run(_check_platform_supported))

    playwright_check = _run(_check_module_installed, "playwright", "playwright")
    checks.append(playwright_check)

    checks.append(_run(_check_module_installed, "cryptography", "cryptography"))
    checks.append(_run(_check_chromium_downloaded))
    checks.append(_run(_check_chrome_profile_dir, profile_dir))
    checks.append(_run(_check_cookie_db_found, profile_dir, chrome_profile))

    for name in ("keychain_key", "yandex_cookies_decrypt"):
        checks.append(
            Check(
                name,
                None,
                "skipped — cookie decryption is only performed by explicit login",
                hint=f"Run: {HINT_LOGIN_BROWSER_CHROME}",
            )
        )

    checks.append(_run(_check_saved_session, session_path))
    checks.append(_run(_check_saved_session_fresh, session_path))

    return checks
