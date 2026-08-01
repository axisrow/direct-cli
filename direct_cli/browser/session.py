"""
Playwright session management for browser-backed commands (``direct masters``).

Reuses the user's own Chrome cookies so ``direct masters`` can read Мастер
кампаний (Campaign Wizard) pages without a separate login flow — this data has
no API surface at all (see module docstring in ``direct_cli/browser/__init__.py``).

Playwright cannot attach to a Chrome profile that is currently open (the
profile directory is locked), so this module copies the minimal set of files
Chromium needs to decrypt cookies (``Cookies``, ``Local State``, and the
``Default`` subdirectory they live in) into a throwaway temporary directory,
then launches a persistent context against that copy with
``channel="chrome"``. The live Chrome window is never touched and does not
need to be closed. The temp copy is always removed on exit, success or not.
"""

import contextlib
import os
import platform
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Generator, Optional

from .._captcha import find_captcha_marker

if TYPE_CHECKING:
    from playwright.sync_api import Page

# Files/directories inside a Chrome user-data-dir that are sufficient for
# Chromium to decrypt and present saved cookies. Copying the whole profile is
# unnecessary (and slow — profiles can be gigabytes with cache/history).
_PROFILE_COOKIE_FILES = ("Cookies", "Cookies-journal", "Network/Cookies")
_PROFILE_ROOT_FILES = ("Local State",)


class BrowserSessionError(RuntimeError):
    """Raised when a Playwright/Chrome session cannot be established."""


class BrowserCaptchaError(BrowserSessionError):
    """Raised when Yandex serves a SmartCaptcha gate instead of real content."""


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


def _copy_profile_cookies(source_root: Path, dest_root: Path, profile: str) -> None:
    """Copy just the cookie-decryption files for one Chrome profile."""
    for name in _PROFILE_ROOT_FILES:
        src = source_root / name
        if src.exists():
            shutil.copy2(src, dest_root / name)

    src_profile_dir = source_root / profile
    if not src_profile_dir.exists():
        raise BrowserSessionError(
            f"Chrome profile directory not found: {src_profile_dir}. "
            "Pass --profile-dir to point at your actual Chrome user-data-dir, "
            "or --chrome-profile if you use a profile other than 'Default'."
        )

    dest_profile_dir = dest_root / profile
    for rel_name in _PROFILE_COOKIE_FILES:
        src = src_profile_dir / rel_name
        if not src.exists():
            continue
        dest = dest_profile_dir / rel_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


@contextlib.contextmanager
def open_chrome_session(
    *,
    profile_dir: Optional[Path] = None,
    chrome_profile: str = "Default",
    headless: bool = True,
) -> Generator["Page", None, None]:
    """Launch Chrome (via Playwright) on a throwaway copy of the user's cookies.

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

    with tempfile.TemporaryDirectory(prefix="direct-cli-chrome-") as tmp:
        tmp_root = Path(tmp)
        _copy_profile_cookies(source_root, tmp_root, chrome_profile)

        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(tmp_root),
                channel="chrome",
                headless=headless,
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                yield page
            finally:
                context.close()


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
