"""
Decrypt Chrome's on-disk cookie store so ``direct masters`` can read Мастер
кампаний (Campaign Wizard) pages with the user's real Yandex session — see the
package docstring in ``direct_cli/browser/__init__.py`` for why this data has
no API surface at all.

Why this module exists (#634): the previous approach in ``session.py`` copied
``Cookies`` + ``Local State`` into a throwaway temp profile and launched Chrome
on it, assuming Chromium would decrypt the cookies itself. On macOS this is
false — Chrome's cookie AES key lives *only* in the login Keychain, under the
service name ``Chrome Safe Storage``. ``Local State``'s ``os_crypt.encrypted_key``
field, which the old code implicitly relied on, is populated only on Windows;
on macOS ``os_crypt`` is an empty object. The temp Chrome therefore silently
discarded every cookie as undecryptable, producing an unauthenticated session
and a ``Page.goto`` timeout on Yandex's login page (which holds long-poll
connections, so ``wait_until="networkidle"`` never settles) — see
``direct_cli/browser/masters.py`` and ``direct_cli/browser/session.py``.

This module reads the Keychain password itself, derives Chrome's AES-128-CBC
key from it, decrypts each cookie value, and hands the caller a list of
Playwright-shaped cookie dicts to inject via ``BrowserContext.add_cookies()``
instead. Scheme reference: Chromium ``components/os_crypt/sync/os_crypt_mac.mm``
(macOS/Linux; Windows uses a different DPAPI-based scheme and is out of scope).

Only cookies for Yandex Direct's own hosts (``YANDEX_COOKIE_HOSTS``) are ever
decrypted — never the rest of the user's Chrome profile.
"""

from __future__ import annotations

import hashlib
import platform
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .session import ChromeCookieError

# --- Keychain -----------------------------------------------------------

_KEYCHAIN_SERVICE = "Chrome Safe Storage"
_KEYCHAIN_ACCOUNT = "Chrome"
# The Keychain read can pop a one-time system permission dialog that blocks
# until the user clicks Allow — auth.py's 10s subprocess template (op_read /
# bw_read) would spuriously time that out, so this is deliberately longer.
_SUBPROCESS_TIMEOUT_SECONDS = 30

# --- Chromium os_crypt constants -----------------------------------------
# All four values below are Chromium constants, not something Yandex or this
# project controls — see components/os_crypt/sync/os_crypt_mac.mm /
# os_crypt_linux.cc. They have been stable for years.
_PBKDF2_SALT = b"saltysalt"
_PBKDF2_ITERATIONS_DARWIN = 1003
_PBKDF2_ITERATIONS_LINUX = 1
# Chrome on Linux falls back to this fixed password only when launched
# without a real OS keyring available (--password-store=basic, or headless/
# minimal desktop environments) — see load_yandex_cookies' Linux handling.
_LINUX_FALLBACK_PASSWORD = "peanuts"
_AES_KEY_LENGTH = 16  # AES-128
_CBC_IV = b" " * 16  # Chromium uses 16 x 0x20 as a fixed (not random) IV.
_V10_PREFIX = b"v10"
# Chrome >= ~130 prepends sha256(host_key) to the plaintext before encrypting
# cookie values. Verified empirically against a live macOS Chrome 150 profile
# (#634): across every v10-encrypted cookie in the profile, ciphertext body
# length (encrypted_value minus the 3-byte "v10" tag) was never below 48 and
# always a multiple of 16 — including cookies known to hold very short values
# (e.g. a "yes"/"no" flag), which would otherwise produce a 16-byte body. That
# is only possible if a fixed 32-byte block precedes the value. We still
# verify per-cookie (see _strip_domain_hash) rather than hard-assuming this,
# so an older Chrome without the prefix is handled correctly too.
_DOMAIN_HASH_LENGTH = 32

# Cookie epoch used by Chrome's sqlite schema: microseconds since
# 1601-01-01, vs. Unix's seconds since 1970-01-01.
_CHROME_EPOCH_OFFSET_SECONDS = 11644473600

# Only Yandex Direct's own hosts are ever decrypted and handed to the
# browser — never the rest of the user's Chrome profile. Matched by exact
# membership, not suffix, so unrelated Yandex properties (metrika.yandex.ru,
# mail.yandex.ru, ...) that carry no Direct auth value are never touched.
YANDEX_COOKIE_HOSTS = (
    ".yandex.ru",
    "yandex.ru",
    "direct.yandex.ru",
    ".direct.yandex.ru",
    "passport.yandex.ru",
    ".passport.yandex.ru",
)

_COOKIE_DB_CANDIDATES = ("Cookies", "Network/Cookies")


class _DecryptError(RuntimeError):
    """Internal: one cookie's ciphertext failed to decrypt (e.g. wrong key)."""


def platform_iterations(system: Optional[str] = None) -> int:
    """Return the PBKDF2 iteration count Chrome uses on this OS.

    Args:
        system: Override for ``platform.system()`` (used by tests to exercise
            every branch on any host).

    Returns:
        The iteration count Chromium's os_crypt uses to derive the AES key.

    Raises:
        ChromeCookieError: On a platform Chrome cookie decryption isn't
            implemented for (currently anything but macOS/Linux).
    """
    system = system if system is not None else platform.system()
    if system == "Darwin":
        return _PBKDF2_ITERATIONS_DARWIN
    if system == "Linux":
        return _PBKDF2_ITERATIONS_LINUX
    raise ChromeCookieError(
        f"Reading Chrome cookies is not supported on {system!r} yet "
        "(only macOS and Linux are implemented). See issue #634."
    )


def derive_key(password: str, *, iterations: int) -> bytes:
    """Derive Chrome's AES-128 cookie key from its Keychain/keyring password."""
    return hashlib.pbkdf2_hmac(
        "sha1",
        password.encode("utf-8"),
        _PBKDF2_SALT,
        iterations,
        dklen=_AES_KEY_LENGTH,
    )


def read_keychain_password(
    *, service: str = _KEYCHAIN_SERVICE, account: str = _KEYCHAIN_ACCOUNT
) -> str:
    """Read Chrome's cookie-encryption password from the macOS login Keychain.

    Args:
        service: Keychain service name Chrome stores the password under.
        account: Keychain account name Chrome stores the password under.

    Returns:
        The password (not yet key-derived).

    Raises:
        ChromeCookieError: If the ``security`` CLI is missing, the read is
            denied or times out, or no matching Keychain entry exists.
    """
    security_path = shutil.which("security")
    if not security_path:
        raise ChromeCookieError(
            "macOS 'security' CLI not found — cannot read the Chrome cookie "
            "key from your Keychain."
        )
    try:
        result = subprocess.run(
            [
                security_path,
                "find-generic-password",
                "-w",
                "-s",
                service,
                "-a",
                account,
            ],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise ChromeCookieError(
            f"Timed out after {_SUBPROCESS_TIMEOUT_SECONDS}s waiting for Keychain "
            "access. macOS shows a one-time 'direct wants to use your confidential "
            "information' dialog on first run — click Allow (or Always Allow) and "
            "retry."
        )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "-25300" in stderr or "could not be found" in stderr:
            raise ChromeCookieError(
                f"No '{service}' key found in your login Keychain. Open Google "
                "Chrome at least once and log in to https://direct.yandex.ru, "
                "then retry."
            )
        if "-25308" in stderr or "User interaction is not allowed" in stderr:
            raise ChromeCookieError(
                "Keychain access was denied. Unlock your login keychain and "
                "retry — macOS will ask once and remember your choice. If "
                "you'd rather not grant Keychain access, use a dedicated CLI "
                "Chrome profile instead (see README)."
            )
        raise ChromeCookieError(f"Keychain read failed: {stderr}")
    password = result.stdout.strip()
    if not password:
        # An empty password silently derives a wrong AES key and decrypts to
        # garbage rather than raising — exactly the class of silent failure
        # this module exists to eliminate, so treat it as an error.
        raise ChromeCookieError(f"Keychain returned an empty value for '{service}'.")
    return password


def get_encryption_key(*, system: Optional[str] = None) -> bytes:
    """Resolve Chrome's cookie AES key for the current platform.

    Args:
        system: Override for ``platform.system()`` (see :func:`platform_iterations`).

    Returns:
        A 16-byte AES-128 key.
    """
    resolved_system = system if system is not None else platform.system()
    iterations = platform_iterations(resolved_system)
    if resolved_system == "Linux":
        password = _LINUX_FALLBACK_PASSWORD
    else:
        password = read_keychain_password()
    return derive_key(password, iterations=iterations)


# --- Decryption -----------------------------------------------------------


def _strip_domain_hash(plaintext: bytes, host_key: str) -> bytes:
    """Strip the sha256(host_key) prefix Chrome >= ~130 prepends, if present.

    Verified structurally rather than assumed from a Chrome-version check
    (see the module-level comment on ``_DOMAIN_HASH_LENGTH``): comparing the
    first 32 bytes against the expected digest means an older Chrome without
    the prefix is handled correctly too, instead of having 32 bytes of
    garbage silently spliced into every decrypted value.
    """
    expected = hashlib.sha256(host_key.encode("utf-8")).digest()
    if plaintext[:_DOMAIN_HASH_LENGTH] == expected:
        return plaintext[_DOMAIN_HASH_LENGTH:]
    return plaintext


def decrypt_value(encrypted_value: bytes, key: bytes, host_key: str) -> str:
    """Decrypt one Chrome cookie's ``encrypted_value`` blob.

    Args:
        encrypted_value: The raw ``encrypted_value`` BLOB from Chrome's
            ``cookies`` sqlite table.
        key: The AES-128 key from :func:`get_encryption_key`.
        host_key: The cookie's ``host_key`` column, used to detect and strip
            the optional domain-hash prefix.

    Returns:
        The decrypted cookie value.

    Raises:
        _DecryptError: If the ciphertext cannot be decrypted with ``key``
            (e.g. wrong/rotated key — invalid PKCS7 padding).
    """
    if not encrypted_value:
        return ""
    if not encrypted_value.startswith(_V10_PREFIX):
        # Legacy/unencrypted row (rare, but not worth failing the whole run
        # over) — return it as-is rather than raising.
        return encrypted_value.decode("utf-8", errors="replace")

    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as exc:
        raise ChromeCookieError(
            "The 'cryptography' package is required to decrypt Chrome cookies "
            "but is not installed. Run: "
            'pip install --upgrade "direct-cli[browser]"'
        ) from exc

    body = encrypted_value[len(_V10_PREFIX) :]
    if len(body) % 16 != 0:
        raise _DecryptError(f"Ciphertext length {len(body)} is not a multiple of 16.")

    decryptor = Cipher(algorithms.AES(key), modes.CBC(_CBC_IV)).decryptor()
    padded = decryptor.update(body) + decryptor.finalize()

    # Manual PKCS7 validation (rather than a library unpadder) so a wrong key
    # — which produces invalid padding — is distinguishable from success,
    # instead of silently returning truncated garbage.
    if not padded:
        raise _DecryptError("Decrypted to an empty block.")
    pad_len = padded[-1]
    if not (1 <= pad_len <= 16) or padded[-pad_len:] != bytes([pad_len]) * pad_len:
        raise _DecryptError("Invalid PKCS7 padding — wrong or rotated key.")
    plaintext = padded[:-pad_len]

    plaintext = _strip_domain_hash(plaintext, host_key)
    return plaintext.decode("utf-8", errors="replace")


# --- Chrome epoch / Playwright mapping -------------------------------------


def chrome_epoch_to_unix(expires_utc: int) -> float:
    """Convert a Chrome ``expires_utc`` column value to a Playwright ``expires``.

    Chrome stores microseconds since 1601-01-01; Playwright wants seconds
    since the Unix epoch, with ``-1`` meaning a session cookie.
    """
    if not expires_utc:
        return -1.0
    unix_seconds = expires_utc / 1_000_000 - _CHROME_EPOCH_OFFSET_SECONDS
    if unix_seconds <= 0:
        return -1.0
    return unix_seconds


def samesite_to_playwright(value: int) -> str:
    """Map Chrome's integer ``samesite`` column to Playwright's string enum."""
    return {0: "None", 1: "Lax", 2: "Strict"}.get(value, "Lax")


def _row_to_playwright_cookie(
    row: Dict[str, Any], key: bytes
) -> Optional[Dict[str, Any]]:
    """Decrypt one sqlite row into a Playwright ``add_cookies`` dict, or None."""
    try:
        value = decrypt_value(row["encrypted_value"], key, row["host_key"])
    except _DecryptError:
        return None

    is_secure = bool(row["is_secure"])
    same_site = samesite_to_playwright(row["samesite"])
    if same_site == "None" and not is_secure:
        # Playwright's add_cookies() does NOT raise for sameSite="None" +
        # secure=False — it silently drops the cookie from the context
        # (verified empirically against a live Playwright/Chromium: this is
        # the only one of the six sameSite x secure combinations that gets
        # dropped, with no error). That is exactly #634's failure mode, so
        # downgrade rather than let an auth cookie vanish without a trace.
        same_site = "Lax"

    return {
        "name": row["name"],
        "value": value,
        "domain": row["host_key"],
        "path": row["path"],
        "expires": chrome_epoch_to_unix(row["expires_utc"]),
        "httpOnly": bool(row["is_httponly"]),
        "secure": is_secure,
        "sameSite": same_site,
    }


# --- sqlite loading ---------------------------------------------------------

_COOKIE_COLUMNS = (
    "host_key",
    "name",
    "encrypted_value",
    "path",
    "expires_utc",
    "is_secure",
    "is_httponly",
    "samesite",
)


def _find_cookie_db(profile_dir: Path) -> Path:
    for candidate in _COOKIE_DB_CANDIDATES:
        path = profile_dir / candidate
        if path.exists():
            return path
    searched = ", ".join(str(profile_dir / c) for c in _COOKIE_DB_CANDIDATES)
    raise ChromeCookieError(f"No Chrome cookie database found. Looked for: {searched}")


def _copy_cookie_db(source: Path, dest_dir: Path) -> Path:
    """Copy the cookie sqlite file (and any WAL/SHM siblings) into dest_dir.

    Never opens or writes the live file directly: a running Chrome holds a
    lock on it, and any sqlite journal we created there would land inside the
    user's real profile directory.
    """
    dest = dest_dir / source.name
    shutil.copy2(source, dest)
    for suffix in ("-wal", "-shm"):
        sidecar = source.with_name(source.name + suffix)
        if sidecar.exists():
            shutil.copy2(sidecar, dest_dir / sidecar.name)
    return dest


def load_yandex_cookies(
    profile_dir: Path,
    chrome_profile: str = "Default",
    *,
    hosts: Sequence[str] = YANDEX_COOKIE_HOSTS,
    key: Optional[bytes] = None,
) -> List[Dict[str, Any]]:
    """Decrypt and return Yandex Direct auth cookies as Playwright cookie dicts.

    Args:
        profile_dir: Chrome user-data-dir (e.g.
            ``~/Library/Application Support/Google/Chrome``).
        chrome_profile: Profile subdirectory to read (e.g. ``"Default"``).
        hosts: Cookie hosts to decrypt — defaults to :data:`YANDEX_COOKIE_HOSTS`.
        key: AES key override for tests; resolved via
            :func:`get_encryption_key` when omitted.

    Returns:
        A list of dicts shaped for ``BrowserContext.add_cookies()``.

    Raises:
        ChromeCookieError: If the cookie database is missing, no cookies
            match ``hosts``, or every matching cookie fails to decrypt (wrong
            or rotated key).
    """
    source_db = _find_cookie_db(profile_dir / chrome_profile)
    resolved_key = key if key is not None else get_encryption_key()

    with tempfile.TemporaryDirectory(prefix="direct-cli-cookies-") as tmp:
        db_copy = _copy_cookie_db(source_db, Path(tmp))
        conn = sqlite3.connect(f"file:{db_copy}?mode=ro", uri=True)
        try:
            placeholders = ",".join("?" for _ in hosts)
            columns = ",".join(_COOKIE_COLUMNS)
            cursor = conn.execute(
                f"SELECT {columns} FROM cookies WHERE host_key IN ({placeholders})",
                tuple(hosts),
            )
            rows: List[Dict[str, Any]] = [
                dict(zip(_COOKIE_COLUMNS, row)) for row in cursor.fetchall()
            ]
        finally:
            conn.close()

    if not rows:
        raise ChromeCookieError(
            "Found no Yandex cookies in your Chrome profile "
            f"({profile_dir / chrome_profile}). Log in to "
            "https://direct.yandex.ru in Chrome, then retry."
        )

    cookies = []
    for row in rows:
        cookie = _row_to_playwright_cookie(row, resolved_key)
        if cookie is not None:
            cookies.append(cookie)

    if not cookies:
        raise ChromeCookieError(
            "Found Yandex cookies but could not decrypt any of them — your "
            "Chrome cookie key may have changed since the last unlock, or "
            "belongs to a different keychain entry."
        )

    return cookies
