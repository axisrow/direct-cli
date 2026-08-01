"""
Tests for direct_cli.browser._chrome_crypto — the Keychain/AES-128-CBC cookie
decryption pipeline that #634 introduced.

These tests never read the real macOS Keychain and never touch a real Chrome
profile under ``~/Library``: every ciphertext is built here with the same
algorithm under test (see ``_encrypt`` below), every Keychain subprocess call
is mocked, and every sqlite database is a synthetic one built in ``tmp_path``.
This keeps the suite offline, platform-independent, and safe under the
default ``-n auto`` parallel run.
"""

import hashlib
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("cryptography")

from cryptography.hazmat.primitives.ciphers import (  # noqa: E402
    Cipher,
    algorithms,
    modes,
)

from direct_cli.browser import _chrome_crypto  # noqa: E402
from direct_cli.browser.session import ChromeCookieError  # noqa: E402


def _encrypt(
    value: str, key: bytes, host_key: str = "", with_prefix: bool = True
) -> bytes:
    """Build a v10-encrypted cookie blob the same way Chrome does.

    Mirrors decrypt_value's expectations exactly, so it doubles as the
    round-trip check for the module under test.
    """
    plaintext = (
        hashlib.sha256(host_key.encode("utf-8")).digest() if with_prefix else b""
    ) + (value.encode("utf-8"))
    pad_len = 16 - (len(plaintext) % 16)
    padded = plaintext + bytes([pad_len]) * pad_len
    encryptor = Cipher(
        algorithms.AES(key), modes.CBC(_chrome_crypto._CBC_IV)
    ).encryptor()
    body = encryptor.update(padded) + encryptor.finalize()
    return _chrome_crypto._V10_PREFIX + body


class TestKeyDerivation(unittest.TestCase):
    def test_derive_key_known_vector(self):
        key = _chrome_crypto.derive_key("peanuts", iterations=1)
        self.assertEqual(len(key), 16)
        expected = hashlib.pbkdf2_hmac("sha1", b"peanuts", b"saltysalt", 1, dklen=16)
        self.assertEqual(key, expected)

    def test_iterations_change_the_derived_key(self):
        # The classic macOS/Linux mix-up bug: using the wrong iteration count
        # silently derives a different (wrong) key instead of failing.
        key_1 = _chrome_crypto.derive_key("secret", iterations=1)
        key_1003 = _chrome_crypto.derive_key("secret", iterations=1003)
        self.assertNotEqual(key_1, key_1003)

    def test_platform_iterations_darwin(self):
        self.assertEqual(_chrome_crypto.platform_iterations("Darwin"), 1003)

    def test_platform_iterations_linux(self):
        self.assertEqual(_chrome_crypto.platform_iterations("Linux"), 1)

    def test_platform_iterations_windows_raises(self):
        with self.assertRaises(ChromeCookieError) as cm:
            _chrome_crypto.platform_iterations("Windows")
        self.assertIn("Windows", str(cm.exception))

    def test_platform_iterations_unknown_raises(self):
        with self.assertRaises(ChromeCookieError):
            _chrome_crypto.platform_iterations("SunOS")


class TestDecryptValue(unittest.TestCase):
    def setUp(self):
        self.key = _chrome_crypto.derive_key("test-password", iterations=1)

    def test_round_trip_various_lengths(self):
        for value in (
            "",
            "x" * 15,
            "x" * 16,
            "3:1754000000.5.0.169|123456789.0.2|abc",
            "кириллица",
        ):
            blob = _encrypt(value, self.key, host_key=".yandex.ru")
            self.assertEqual(
                _chrome_crypto.decrypt_value(blob, self.key, ".yandex.ru"), value
            )

    def test_prefix_stripped_when_present(self):
        blob = _encrypt(
            "Session_id-value", self.key, host_key=".yandex.ru", with_prefix=True
        )
        result = _chrome_crypto.decrypt_value(blob, self.key, ".yandex.ru")
        self.assertEqual(result, "Session_id-value")

    def test_prefix_not_stripped_when_absent(self):
        # Regression guard: hard-assuming the 32-byte prefix is always
        # present would corrupt values on an older Chrome that doesn't add
        # it. _strip_domain_hash must only strip on a structural match.
        blob = _encrypt(
            "legacy-value", self.key, host_key=".yandex.ru", with_prefix=False
        )
        result = _chrome_crypto.decrypt_value(blob, self.key, ".yandex.ru")
        self.assertEqual(result, "legacy-value")

    def test_value_not_mistaken_for_domain_hash(self):
        # A value whose first 32 bytes are NOT sha256(host_key) must survive
        # intact — no false-positive strip.
        arbitrary_prefix = b"\x00" * 32
        plaintext = arbitrary_prefix + b"tail-value"
        pad_len = 16 - (len(plaintext) % 16)
        padded = plaintext + bytes([pad_len]) * pad_len
        encryptor = Cipher(
            algorithms.AES(self.key), modes.CBC(_chrome_crypto._CBC_IV)
        ).encryptor()
        blob = (
            _chrome_crypto._V10_PREFIX + encryptor.update(padded) + encryptor.finalize()
        )

        result = _chrome_crypto.decrypt_value(blob, self.key, ".yandex.ru")
        self.assertEqual(result, (arbitrary_prefix + b"tail-value").decode("utf-8"))

    def test_wrong_key_raises_instead_of_returning_garbage(self):
        blob = _encrypt("secret", self.key, host_key=".yandex.ru")
        wrong_key = _chrome_crypto.derive_key("different-password", iterations=1)
        with self.assertRaises(_chrome_crypto._DecryptError):
            _chrome_crypto.decrypt_value(blob, wrong_key, ".yandex.ru")

    def test_empty_blob_returns_empty_string(self):
        self.assertEqual(_chrome_crypto.decrypt_value(b"", self.key, ".yandex.ru"), "")

    def test_non_v10_blob_returned_as_plaintext(self):
        self.assertEqual(
            _chrome_crypto.decrypt_value(b"plain-legacy-value", self.key, ".yandex.ru"),
            "plain-legacy-value",
        )


class TestKeychainSubprocess(unittest.TestCase):
    def _mock_run(self, **kwargs):
        return patch("direct_cli.browser._chrome_crypto.subprocess.run", **kwargs)

    def test_success_reads_password_and_argv(self):
        with (
            patch(
                "direct_cli.browser._chrome_crypto.shutil.which",
                return_value="/usr/bin/security",
            ),
            self._mock_run(
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="secretpw\n", stderr=""
                )
            ) as run,
        ):
            password = _chrome_crypto.read_keychain_password()
        self.assertEqual(password, "secretpw")
        args = run.call_args[0][0]
        self.assertEqual(
            args,
            [
                "/usr/bin/security",
                "find-generic-password",
                "-w",
                "-s",
                "Chrome Safe Storage",
                "-a",
                "Chrome",
            ],
        )

    def test_not_found_error_mentions_login(self):
        with (
            patch(
                "direct_cli.browser._chrome_crypto.shutil.which",
                return_value="/usr/bin/security",
            ),
            self._mock_run(
                return_value=subprocess.CompletedProcess(
                    args=[],
                    returncode=44,
                    stdout="",
                    stderr="security: could not be found",
                )
            ),
        ):
            with self.assertRaises(ChromeCookieError) as cm:
                _chrome_crypto.read_keychain_password()
        self.assertIn("direct.yandex.ru", str(cm.exception))

    def test_denied_error_mentions_alternative(self):
        with (
            patch(
                "direct_cli.browser._chrome_crypto.shutil.which",
                return_value="/usr/bin/security",
            ),
            self._mock_run(
                return_value=subprocess.CompletedProcess(
                    args=[],
                    returncode=45,
                    stdout="",
                    stderr="User interaction is not allowed.",
                )
            ),
        ):
            with self.assertRaises(ChromeCookieError) as cm:
                _chrome_crypto.read_keychain_password()
        self.assertIn("denied", str(cm.exception).lower())

    def test_timeout_error_mentions_dialog(self):
        with (
            patch(
                "direct_cli.browser._chrome_crypto.shutil.which",
                return_value="/usr/bin/security",
            ),
            self._mock_run(
                side_effect=subprocess.TimeoutExpired(cmd="security", timeout=30)
            ),
        ):
            with self.assertRaises(ChromeCookieError) as cm:
                _chrome_crypto.read_keychain_password()
        self.assertIn("Allow", str(cm.exception))

    def test_missing_security_cli_raises(self):
        with patch("direct_cli.browser._chrome_crypto.shutil.which", return_value=None):
            with self.assertRaises(ChromeCookieError) as cm:
                _chrome_crypto.read_keychain_password()
        self.assertIn("security", str(cm.exception))

    def test_empty_password_raises(self):
        with (
            patch(
                "direct_cli.browser._chrome_crypto.shutil.which",
                return_value="/usr/bin/security",
            ),
            self._mock_run(
                return_value=subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="   \n", stderr=""
                )
            ),
        ):
            with self.assertRaises(ChromeCookieError):
                _chrome_crypto.read_keychain_password()


class TestMappingHelpers(unittest.TestCase):
    def test_chrome_epoch_zero_is_session_cookie(self):
        self.assertEqual(_chrome_crypto.chrome_epoch_to_unix(0), -1.0)

    def test_chrome_epoch_known_timestamp(self):
        # 13253568000000000 us since 1601-01-01 -> a real, known Unix time.
        chrome_ts = 13253568000000000
        expected = chrome_ts / 1_000_000 - 11644473600
        self.assertAlmostEqual(
            _chrome_crypto.chrome_epoch_to_unix(chrome_ts), expected, places=3
        )

    def test_chrome_epoch_negative_or_absurd_is_session_cookie(self):
        self.assertEqual(_chrome_crypto.chrome_epoch_to_unix(1), -1.0)

    def test_samesite_mapping(self):
        self.assertEqual(_chrome_crypto.samesite_to_playwright(-1), "Lax")
        self.assertEqual(_chrome_crypto.samesite_to_playwright(0), "None")
        self.assertEqual(_chrome_crypto.samesite_to_playwright(1), "Lax")
        self.assertEqual(_chrome_crypto.samesite_to_playwright(2), "Strict")
        self.assertEqual(_chrome_crypto.samesite_to_playwright(99), "Lax")

    def test_row_to_cookie_uses_real_bool_types(self):
        key = _chrome_crypto.derive_key("pw", iterations=1)
        row = {
            "host_key": ".yandex.ru",
            "name": "L",
            "encrypted_value": _encrypt("v", key, host_key=".yandex.ru"),
            "path": "/",
            "expires_utc": 0,
            "is_secure": 1,
            "is_httponly": 0,
            "samesite": 1,
        }
        cookie = _chrome_crypto._row_to_playwright_cookie(row, key)
        self.assertIs(cookie["secure"], True)
        self.assertIs(cookie["httpOnly"], False)

    def test_samesite_none_downgraded_to_lax_when_not_secure(self):
        # Playwright silently DROPS (does not raise for) cookies with
        # sameSite="None" + secure=False — verified against a live Playwright
        # context. This is exactly #634's failure mode if left unguarded.
        key = _chrome_crypto.derive_key("pw", iterations=1)
        row = {
            "host_key": ".yandex.ru",
            "name": "risky",
            "encrypted_value": _encrypt("v", key, host_key=".yandex.ru"),
            "path": "/",
            "expires_utc": 0,
            "is_secure": 0,
            "is_httponly": 0,
            "samesite": 0,
        }
        cookie = _chrome_crypto._row_to_playwright_cookie(row, key)
        self.assertEqual(cookie["sameSite"], "Lax")

    def test_samesite_none_kept_when_secure(self):
        key = _chrome_crypto.derive_key("pw", iterations=1)
        row = {
            "host_key": ".yandex.ru",
            "name": "Session_id",
            "encrypted_value": _encrypt("v", key, host_key=".yandex.ru"),
            "path": "/",
            "expires_utc": 0,
            "is_secure": 1,
            "is_httponly": 1,
            "samesite": 0,
        }
        cookie = _chrome_crypto._row_to_playwright_cookie(row, key)
        self.assertEqual(cookie["sameSite"], "None")


def _make_cookie_db(path: Path, rows) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("""CREATE TABLE cookies (
            host_key TEXT, name TEXT, encrypted_value BLOB, path TEXT,
            expires_utc INTEGER, is_secure INTEGER, is_httponly INTEGER,
            samesite INTEGER
        )""")
    conn.executemany(
        "INSERT INTO cookies VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


class TestLoadYandexCookies(unittest.TestCase):
    def setUp(self):
        self.key = _chrome_crypto.derive_key("pw", iterations=1)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp_path = Path(tmp.name)
        self.profile = self.tmp_path / "Default"
        self.profile.mkdir()

    def _row(self, host_key, name, value="v", **overrides):
        base = {
            "host_key": host_key,
            "name": name,
            "encrypted_value": _encrypt(value, self.key, host_key=host_key),
            "path": "/",
            "expires_utc": 0,
            "is_secure": 1,
            "is_httponly": 0,
            "samesite": 0,
        }
        base.update(overrides)
        return (
            base["host_key"],
            base["name"],
            base["encrypted_value"],
            base["path"],
            base["expires_utc"],
            base["is_secure"],
            base["is_httponly"],
            base["samesite"],
        )

    def test_only_target_hosts_returned(self):
        _make_cookie_db(
            self.profile / "Cookies",
            [
                self._row(".yandex.ru", "Session_id"),
                self._row("passport.yandex.ru", "sessar"),
                self._row("direct.yandex.ru", "_direct_csrf_token"),
                self._row("github.com", "logged_in"),
                self._row("google.com", "NID"),
                self._row("metrika.yandex.ru", "_ym_uid"),
            ],
        )
        orig_stat = (self.profile / "Cookies").stat()

        cookies = _chrome_crypto.load_yandex_cookies(
            self.tmp_path, "Default", key=self.key
        )

        names = {c["name"] for c in cookies}
        self.assertEqual(names, {"Session_id", "sessar", "_direct_csrf_token"})
        # Privacy: hosts outside YANDEX_COOKIE_HOSTS must never appear,
        # including other Yandex properties like metrika.
        self.assertNotIn("_ym_uid", names)
        self.assertNotIn("logged_in", names)

        # The source DB must never be modified.
        new_stat = (self.profile / "Cookies").stat()
        self.assertEqual(orig_stat.st_size, new_stat.st_size)
        self.assertEqual(orig_stat.st_mtime, new_stat.st_mtime)

    def test_zero_matching_hosts_raises_login_message(self):
        _make_cookie_db(
            self.profile / "Cookies", [self._row("github.com", "logged_in")]
        )

        with self.assertRaises(ChromeCookieError) as cm:
            _chrome_crypto.load_yandex_cookies(self.tmp_path, "Default", key=self.key)
        self.assertIn("direct.yandex.ru", str(cm.exception))

    def test_all_rows_fail_decryption_raises_wrong_key_message(self):
        _make_cookie_db(
            self.profile / "Cookies", [self._row(".yandex.ru", "Session_id")]
        )

        wrong_key = _chrome_crypto.derive_key("wrong", iterations=1)
        with self.assertRaises(ChromeCookieError) as cm:
            _chrome_crypto.load_yandex_cookies(self.tmp_path, "Default", key=wrong_key)
        # Distinct message from the zero-matching-hosts case above.
        self.assertNotIn("Log in to", str(cm.exception))

    def test_partial_decrypt_failure_returns_the_rest(self):
        wrong_key = _chrome_crypto.derive_key("wrong", iterations=1)
        good_row = self._row(".yandex.ru", "Session_id")
        bad_row = self._row(
            ".yandex.ru",
            "corrupted",
            encrypted_value=_encrypt("x", wrong_key, host_key=".yandex.ru"),
        )
        _make_cookie_db(self.profile / "Cookies", [good_row, bad_row])

        cookies = _chrome_crypto.load_yandex_cookies(
            self.tmp_path, "Default", key=self.key
        )
        names = {c["name"] for c in cookies}
        self.assertEqual(names, {"Session_id"})

    def test_missing_cookie_db_names_both_candidate_paths(self):
        with self.assertRaises(ChromeCookieError) as cm:
            _chrome_crypto.load_yandex_cookies(self.tmp_path, "Default", key=self.key)
        message = str(cm.exception)
        self.assertIn("Cookies", message)
        self.assertIn("Network/Cookies", message)


if __name__ == "__main__":
    unittest.main()
