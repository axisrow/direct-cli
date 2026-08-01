"""
On-disk persistence for a Playwright ``storage_state`` (browser session).

Split out from ``session.py`` on purpose: this module imports neither
``playwright`` nor ``cryptography``, so ``direct playwright doctor`` and the
offline test suite can inspect a saved session without the optional
``browser`` extra installed. See ``direct_cli/commands/browser_session.py``
for the ``direct playwright login`` / ``direct playwright doctor`` commands
this backs.

Session file: ``~/.direct-cli/playwright/session.json`` — a sibling directory
of ``direct_cli/auth.py``'s ``AUTH_STORE_PATH`` (``~/.direct-cli/auth.json``),
kept separate so the two stores never fight over the same directory's
permission bits. The file holds a live Yandex session (equivalent to a
logged-in cookie jar), so it gets the same 0600/0700 treatment as
``auth.json`` — the atomic-write pattern below intentionally duplicates
``auth.py``'s ``_write_json`` rather than importing it, so this package stays
free of the OAuth module's dependencies.
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

SESSION_FORMAT_VERSION = 1

PLAYWRIGHT_SESSION_PATH = Path.home() / ".direct-cli" / "playwright" / "session.json"


class SessionStoreError(RuntimeError):
    """Raised when a saved session cannot be read, is missing, or is corrupt."""


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    """Write ``payload`` as JSON to ``path`` atomically, 0600 inside 0700.

    Deliberately mirrors ``direct_cli/auth.py::_write_json`` (mkdir -> chmod
    parent 0700 -> mkstemp -> chmod 0600 -> write -> os.replace) rather than
    importing it — see module docstring.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    tmp_path = Path(tmp)
    try:
        os.chmod(tmp, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = -1  # ownership transferred to the file object
            f.write(json.dumps(payload, ensure_ascii=False, indent=2))
        os.replace(tmp, path)
    except Exception:
        if fd != -1:
            with contextlib.suppress(OSError):
                os.close(fd)
        with contextlib.suppress(OSError):
            tmp_path.unlink()
        raise


def save_session(
    storage_state: Dict[str, Any],
    *,
    source: Optional[Dict[str, Any]] = None,
    path: Optional[Path] = None,
) -> Path:
    """Persist ``storage_state`` (as returned by Playwright) to disk.

    Wraps it in a versioned envelope with a timestamp and (diagnostic-only,
    never used to re-decrypt) provenance. Returns the path written.
    """
    target = path or PLAYWRIGHT_SESSION_PATH
    envelope = {
        "version": SESSION_FORMAT_VERSION,
        "created_at": time.time(),
        "source": source or {},
        "storage_state": storage_state,
    }
    _atomic_write_json(target, envelope)
    return target


def read_session_envelope(path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Return the raw envelope dict, or ``None`` if the file is absent.

    Never raises on a corrupt/unreadable file — callers that need to
    distinguish "absent" from "corrupt" should use :func:`session_status`,
    which surfaces the parse error instead of swallowing it.
    """
    target = path or PLAYWRIGHT_SESSION_PATH
    if not target.exists():
        return None
    try:
        raw = target.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def load_session(path: Optional[Path] = None) -> Dict[str, Any]:
    """Return the saved ``storage_state`` dict, ready for ``new_context()``.

    Raises:
        SessionStoreError: if no session file exists, it can't be parsed, or
            its ``version`` doesn't match :data:`SESSION_FORMAT_VERSION`.
    """
    target = path or PLAYWRIGHT_SESSION_PATH
    envelope = read_session_envelope(target)
    if envelope is None:
        raise SessionStoreError(
            f"No saved browser session found at {target}. "
            "Run: direct playwright login"
        )
    version = envelope.get("version")
    if version != SESSION_FORMAT_VERSION:
        raise SessionStoreError(
            f"Saved session at {target} has unsupported format version "
            f"{version!r} (expected {SESSION_FORMAT_VERSION}). "
            "Run: direct playwright login"
        )
    storage_state = envelope.get("storage_state")
    if not isinstance(storage_state, dict):
        raise SessionStoreError(
            f"Saved session at {target} is corrupt (missing storage_state). "
            "Run: direct playwright login"
        )
    return storage_state


def _file_mode(path: Path) -> Optional[str]:
    try:
        return format(stat.S_IMODE(path.stat().st_mode), "04o")
    except OSError:
        return None


def session_status(
    path: Optional[Path] = None, *, now: Optional[float] = None
) -> Dict[str, Any]:
    """Read-only inspection of the saved session for ``direct playwright doctor``.

    Never raises — any I/O or parse failure is reported via the ``error``
    key. Never includes cookie names or values, only counts/timestamps.
    """
    target = path or PLAYWRIGHT_SESSION_PATH
    status: Dict[str, Any] = {
        "exists": False,
        "path": str(target),
        "version": None,
        "created_at": None,
        "age_seconds": None,
        "cookie_count": None,
        "expires_at": None,
        "expired": None,
        "mode": None,
        "error": None,
    }
    if not target.exists():
        return status

    status["exists"] = True
    status["mode"] = _file_mode(target)

    envelope = read_session_envelope(target)
    if envelope is None:
        status["error"] = "Session file exists but could not be parsed as JSON."
        return status

    status["version"] = envelope.get("version")
    created_at = envelope.get("created_at")
    status["created_at"] = created_at
    current = now if now is not None else time.time()
    if isinstance(created_at, (int, float)):
        status["age_seconds"] = int(current - created_at)

    storage_state = envelope.get("storage_state")
    if not isinstance(storage_state, dict):
        status["error"] = "Session file is missing its storage_state payload."
        return status

    cookies = storage_state.get("cookies")
    if not isinstance(cookies, list):
        cookies = []
    status["cookie_count"] = len(cookies)

    # Playwright uses -1 (or omits the field) for session-only cookies with
    # no expiry; only positive values are real expiry timestamps. The
    # earliest-expiring auth cookie is what actually kills the session, so
    # take the minimum across positive expiries.
    positive_expiries = [
        c["expires"]
        for c in cookies
        if isinstance(c, dict)
        and isinstance(c.get("expires"), (int, float))
        and c["expires"] > 0
    ]
    if positive_expiries:
        expires_at = min(positive_expiries)
        status["expires_at"] = expires_at
        status["expired"] = expires_at <= current
    # else: every cookie is session-only (or there are no cookies) -- expiry
    # is genuinely unknown, leave expires_at/expired as None rather than
    # guessing.

    return status
