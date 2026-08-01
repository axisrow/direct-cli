"""
Tests for the persistent browser session used by `direct playwright login` /
`direct playwright doctor` (see direct_cli/browser/store.py,
direct_cli/browser/diagnostics.py, direct_cli/browser/session.py, and
direct_cli/commands/browser_session.py).

direct_cli/browser/store.py and direct_cli/browser/diagnostics.py are
deliberately import-clean (no playwright, no cryptography), so most tests in
this module need no pytest.importorskip. Only tests that touch
direct_cli/browser/session.py's open_saved_session/capture_storage_state
(which import playwright) skip when the optional `browser` extra isn't
installed -- mirroring the convention in tests/test_masters.py and
tests/test_chrome_crypto.py.
"""

import json
import stat
import unittest
from unittest.mock import Mock, patch

import pytest

from direct_cli.browser import diagnostics, store
from direct_cli.browser._chrome_crypto import ChromeCookieError


@pytest.fixture(autouse=True)
def _isolated_session_path(tmp_path, monkeypatch):
    """Redirect PLAYWRIGHT_SESSION_PATH to a tmp_path for every test in this module.

    Unconditional (autouse) so a forgotten monkeypatch in a new test can never
    write to the developer's real ~/.direct-cli/playwright/ under xdist.
    """
    target = tmp_path / "playwright" / "session.json"
    monkeypatch.setattr(store, "PLAYWRIGHT_SESSION_PATH", target)
    yield target


class TestSaveSession(unittest.TestCase):
    def test_writes_0600_file_inside_0700_dir(self):
        path = store.save_session({"cookies": [], "origins": []})
        self.assertTrue(path.exists())
        self.assertEqual(format(stat.S_IMODE(path.stat().st_mode), "04o"), "0600")
        self.assertEqual(
            format(stat.S_IMODE(path.parent.stat().st_mode), "04o"), "0700"
        )

    def test_atomic_no_leftover_temp_files_on_success(self):
        path = store.save_session({"cookies": [], "origins": []})
        siblings = list(path.parent.iterdir())
        self.assertEqual(siblings, [path])

    def test_round_trip_preserves_storage_state(self):
        state = {
            "cookies": [{"name": "Session_id", "value": "x", "domain": ".yandex.ru"}],
            "origins": [{"origin": "https://direct.yandex.ru", "localStorage": []}],
        }
        store.save_session(state, source={"chrome_profile": "Default"})
        loaded = store.load_session()
        self.assertEqual(loaded, state)

    def test_failed_write_leaves_target_untouched_and_no_temp_left(self):
        path = store.save_session({"cookies": [], "origins": []})
        original = path.read_bytes()

        with patch(
            "direct_cli.browser.store.json.dumps", side_effect=RuntimeError("boom")
        ):
            with self.assertRaises(RuntimeError):
                store.save_session({"cookies": ["new"], "origins": []})

        self.assertEqual(path.read_bytes(), original)
        siblings = list(path.parent.iterdir())
        self.assertEqual(siblings, [path])


class TestLoadSession(unittest.TestCase):
    def test_missing_file_raises_session_store_error(self):
        with self.assertRaises(store.SessionStoreError) as ctx:
            store.load_session()
        self.assertIn("direct playwright login", str(ctx.exception))

    def test_wrong_version_raises_session_store_error(self):
        target = store.PLAYWRIGHT_SESSION_PATH
        target.parent.mkdir(parents=True)
        target.write_text(
            json.dumps({"version": 999, "storage_state": {"cookies": []}})
        )
        with self.assertRaises(store.SessionStoreError) as ctx:
            store.load_session()
        self.assertIn("999", str(ctx.exception))

    def test_missing_storage_state_raises_session_store_error(self):
        target = store.PLAYWRIGHT_SESSION_PATH
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps({"version": 1}))
        with self.assertRaises(store.SessionStoreError):
            store.load_session()


class TestReadSessionEnvelope(unittest.TestCase):
    def test_missing_file_returns_none(self):
        self.assertIsNone(store.read_session_envelope())

    def test_corrupt_json_returns_none(self):
        target = store.PLAYWRIGHT_SESSION_PATH
        target.parent.mkdir(parents=True)
        target.write_text("{not json")
        self.assertIsNone(store.read_session_envelope())

    def test_non_dict_json_returns_none(self):
        target = store.PLAYWRIGHT_SESSION_PATH
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps([1, 2, 3]))
        self.assertIsNone(store.read_session_envelope())


class TestSessionStatus(unittest.TestCase):
    def test_absent_file(self):
        status = store.session_status()
        self.assertEqual(status["exists"], False)
        self.assertIsNone(status["error"])

    def test_corrupt_file_reports_error_without_raising(self):
        target = store.PLAYWRIGHT_SESSION_PATH
        target.parent.mkdir(parents=True)
        target.write_text("{not json")
        status = store.session_status()
        self.assertTrue(status["exists"])
        self.assertIsNotNone(status["error"])

    def test_reports_mode_and_cookie_count(self):
        store.save_session(
            {
                "cookies": [
                    {"name": "a", "value": "1", "expires": -1},
                    {"name": "b", "value": "2", "expires": -1},
                ],
                "origins": [],
            }
        )
        status = store.session_status()
        self.assertTrue(status["exists"])
        self.assertEqual(status["mode"], "0600")
        self.assertEqual(status["cookie_count"], 2)

    def test_session_only_cookies_leave_expiry_unknown(self):
        store.save_session(
            {"cookies": [{"name": "a", "value": "1", "expires": -1}], "origins": []}
        )
        status = store.session_status()
        self.assertIsNone(status["expires_at"])
        self.assertIsNone(status["expired"])

    def test_expiry_is_minimum_of_positive_expiries(self):
        store.save_session(
            {
                "cookies": [
                    {"name": "a", "value": "1", "expires": 2000.0},
                    {"name": "b", "value": "2", "expires": 1000.0},
                    {"name": "c", "value": "3", "expires": -1},
                ],
                "origins": [],
            }
        )
        status = store.session_status(now=500.0)
        self.assertEqual(status["expires_at"], 1000.0)
        self.assertFalse(status["expired"])

    def test_expired_when_min_expiry_in_the_past(self):
        store.save_session(
            {"cookies": [{"name": "a", "value": "1", "expires": 1000.0}], "origins": []}
        )
        status = store.session_status(now=5000.0)
        self.assertTrue(status["expired"])

    def test_age_seconds_computed_from_created_at(self):
        store.save_session({"cookies": [], "origins": []})
        envelope = store.read_session_envelope()
        status = store.session_status(now=envelope["created_at"] + 42)
        self.assertEqual(status["age_seconds"], 42)

    def test_never_includes_cookie_values(self):
        store.save_session(
            {
                "cookies": [
                    {"name": "Session_id", "value": "top-secret-value", "expires": -1}
                ],
                "origins": [],
            }
        )
        status = store.session_status()
        self.assertNotIn("top-secret-value", json.dumps(status))
        self.assertNotIn("Session_id", json.dumps(status))


class TestRunDiagnosticsSurvivesFailures(unittest.TestCase):
    """run_diagnostics must return all 10 checks even when everything fails."""

    def test_every_check_present_when_every_dependency_fails(self):
        with (
            patch(
                "direct_cli.browser.diagnostics.platform_iterations",
                side_effect=ChromeCookieError("unsupported"),
            ),
            patch(
                "direct_cli.browser.diagnostics.default_chrome_profile_dir",
                return_value=None,
            ),
            patch(
                "direct_cli.browser.diagnostics.get_encryption_key",
                side_effect=ChromeCookieError("no keychain"),
            ),
            patch(
                "direct_cli.browser.diagnostics.importlib.util.find_spec",
                return_value=None,
            ),
        ):
            checks = diagnostics.run_diagnostics()

        names = [c.name for c in checks]
        self.assertEqual(
            names,
            [
                "platform_supported",
                "playwright_installed",
                "cryptography_installed",
                "chromium_downloaded",
                "chrome_profile_dir",
                "cookie_db_found",
                "keychain_key",
                "yandex_cookies_decrypt",
                "saved_session",
                "saved_session_fresh",
            ],
        )
        self.assertTrue(all(c.ok is not True for c in checks))


class TestRunDiagnosticsDoesNotLoginOrLaunch(unittest.TestCase):
    """Contract tests: doctor must never log in and never launch a browser."""

    def test_does_not_call_capture_storage_state_or_save_session(self):
        with (
            patch(
                "direct_cli.browser.session.capture_storage_state",
                side_effect=AssertionError("doctor must not log in"),
            ),
            patch(
                "direct_cli.browser.store.save_session",
                side_effect=AssertionError("doctor must not write a session"),
            ),
        ):
            # Should complete without raising the AssertionErrors above.
            diagnostics.run_diagnostics()

    def test_chromium_check_never_calls_launch(self):
        """The chromium_downloaded check reads .executable_path (a property
        lookup), never .launch() -- assert launch() is never called even
        though a full sync_playwright context is entered."""
        pytest.importorskip("playwright")
        fake_browser_type = Mock()
        fake_browser_type.executable_path = "/nonexistent/chrome"
        fake_browser_type.launch.side_effect = AssertionError(
            "doctor must not launch a browser"
        )
        fake_playwright = Mock()
        fake_playwright.chromium = fake_browser_type
        fake_sync_playwright = Mock()
        fake_sync_playwright.return_value.__enter__ = Mock(return_value=fake_playwright)
        fake_sync_playwright.return_value.__exit__ = Mock(return_value=False)

        with patch("playwright.sync_api.sync_playwright", fake_sync_playwright):
            diagnostics.run_diagnostics()

        fake_browser_type.launch.assert_not_called()


class TestDiagnosticsNeverLeakSecrets(unittest.TestCase):
    def test_keychain_check_never_contains_the_password(self):
        with patch(
            "direct_cli.browser.diagnostics.get_encryption_key",
            return_value=b"\x00" * 16,
        ):
            checks = diagnostics.run_diagnostics(profile_dir=None)
        keychain_check = next(c for c in checks if c.name == "keychain_key")
        self.assertNotIn("super-secret-password", keychain_check.detail)

    def test_keychain_derived_exactly_once(self):
        calls = []

        def _fake_get_key(**kwargs):
            calls.append(kwargs)
            return b"\x00" * 16

        with patch(
            "direct_cli.browser.diagnostics.get_encryption_key",
            side_effect=_fake_get_key,
        ):
            diagnostics.run_diagnostics()

        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
