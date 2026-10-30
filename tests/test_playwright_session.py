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

import contextlib
import json
import stat
import tempfile
import unittest
import urllib.error
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from direct_cli.browser import diagnostics, store
from direct_cli.browser._chrome_crypto import ChromeCookieError

# The real probe function, captured at import time: the conftest-wide offline
# pin (_pin_sso_probe_offline) replaces the module attribute for every test,
# and TestSsoProbe unit-tests the probe itself.
from direct_cli.browser.session import probe_sso_session as _real_probe_sso_session


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
        self.assertIn("direct auth login browser --source chrome", str(ctx.exception))

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
        assert envelope is not None
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


class TestDiagnosticsNeverReadSecrets(unittest.TestCase):
    def test_keychain_and_cookie_decryption_are_skipped(self):
        with (
            patch("direct_cli.browser._chrome_crypto.get_encryption_key") as key,
            patch("direct_cli.browser._chrome_crypto.load_yandex_cookies") as cookies,
        ):
            checks = diagnostics.run_diagnostics()
        key.assert_not_called()
        cookies.assert_not_called()
        skipped = {
            c.name: c
            for c in checks
            if c.name in ("keychain_key", "yandex_cookies_decrypt")
        }
        self.assertEqual(len(skipped), 2)
        for check in skipped.values():
            self.assertIsNone(check.ok)
            self.assertIn("explicit login", check.detail)


class TestPlaywrightLoginCommand(unittest.TestCase):
    """``direct playwright login``'s ``verified`` output contract (issue #870
    п.3): a script must be able to tell a verified session from a merely
    saved one — ``"verified": false`` with exit code 0 in JSON, and the
    ``verified=no`` line in text format."""

    def _invoke_login(self, *extra_args):
        from click.testing import CliRunner

        from direct_cli.cli import cli

        return CliRunner().invoke(cli, ["playwright", "login", *extra_args])

    def _patched_capture(self, verified):
        return patch(
            "direct_cli.browser.session.capture_storage_state",
            return_value=(
                {"cookies": [{"name": "Session_id", "domain": ".yandex.ru"}]},
                {
                    "profile_dir": "/fake/chrome",
                    "chrome_profile": "Default",
                    "verified": verified,
                },
            ),
        )

    def test_json_payload_reports_an_unverified_session(self):
        with self._patched_capture(False):
            result = self._invoke_login("--format", "json")

        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["cookies"], 1)
        self.assertFalse(
            payload["verified"],
            "an unverified capture must be reportable from the JSON payload",
        )

    def test_json_payload_reports_a_verified_session(self):
        with self._patched_capture(True):
            result = self._invoke_login("--format", "json")

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(json.loads(result.stdout)["verified"])

    def test_no_verify_reports_unverified_even_with_a_true_default(self):
        """--no-verify skips the live check entirely, so the payload must say
        verified=false regardless of what the (skipped) check would say."""
        with self._patched_capture(False):
            result = self._invoke_login("--format", "json", "--no-verify")

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertFalse(json.loads(result.stdout)["verified"])

    def test_text_format_prints_the_verified_line(self):
        with self._patched_capture(True):
            result = self._invoke_login("--format", "text")

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("verified=yes", result.output)

        with self._patched_capture(False):
            result = self._invoke_login("--format", "text")

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("verified=no", result.output)


class TestCaptureStorageStateHeadfulRetryMessage(unittest.TestCase):
    """Fresh cookies + a login page even headful must read as server-side
    invalidation, not as the #870 bot challenge (live case 2026-10-22: the
    real Chrome session had been rotated server-side long before its cookie
    expires_utc; re-login in Chrome was the fix, headful retries never
    helped)."""

    def test_fresh_cookies_rejected_headful_read_as_server_side_invalidation(self):
        pytest.importorskip("playwright")
        from direct_cli.browser import session as browser_session

        fresh_cookies = [
            {
                "name": "Session_id",
                "value": "irrelevant",
                "expires": 2**31,
                "domain": ".yandex.ru",
            }
        ]

        @contextlib.contextmanager
        def _fake_launch_context(_sync_playwright, *, headless, storage_state=None):
            context = Mock()
            context.new_page.return_value = Mock()
            yield Mock(), context

        with (
            patch.object(
                browser_session, "_import_sync_playwright", return_value=object()
            ),
            patch(
                "direct_cli.browser._chrome_crypto.load_yandex_cookies",
                return_value=fresh_cookies,
            ),
            patch.object(browser_session, "_launch_context", _fake_launch_context),
            patch.object(
                browser_session,
                "_goto_with_network_retry",
                side_effect=browser_session.BrowserAuthError("login page served"),
            ),
            # Issue #954: the catch block now probes the jar; "unknown" keeps
            # the legacy messages this test pins, offline.
            patch.object(browser_session, "probe_sso_session", return_value="unknown"),
            patch("direct_cli.browser.session.print_warning_stderr"),
        ):
            with self.assertRaises(browser_session.BrowserAuthError) as cm:
                # A real existing directory: _resolve_profile_dir runs before
                # any of the patches above and requires the profile dir to
                # exist (the CI runner has no default Chrome profile).
                browser_session.capture_storage_state(
                    profile_dir=Path(tempfile.gettempdir())
                )

        message = str(cm.exception)
        self.assertIn("invalidated server-side", message)
        self.assertIn("direct auth login browser --source chrome", message)


def test_save_session_warns_when_replacing_existing_session(tmp_path, capsys):
    from direct_cli.browser import store

    target = tmp_path / "session.json"
    store.save_session({"cookies": []}, path=target)
    assert capsys.readouterr().err == ""
    store.save_session({"cookies": []}, path=target)
    err = capsys.readouterr().err
    assert str(target) in err
    assert "session.json" in err


class TestOwnerStamp(unittest.TestCase):
    """Issue #916: the envelope records whose account the session belongs to.

    Old sessions saved before the stamp read back as ``owner_login=None`` —
    a soft fallback, never an error."""

    def test_envelope_and_status_carry_owner_login(self):
        store.save_session({"cookies": [], "origins": []}, owner_login="some-owner")
        envelope = store.read_session_envelope()
        assert envelope is not None
        self.assertEqual(envelope["owner_login"], "some-owner")
        self.assertEqual(store.session_status()["owner_login"], "some-owner")

    def test_missing_stamp_reads_as_none_and_still_loads(self):
        state = {"cookies": [], "origins": []}
        store.save_session(state)
        envelope = store.read_session_envelope()
        assert envelope is not None
        self.assertIsNone(envelope["owner_login"])
        self.assertIsNone(store.session_status()["owner_login"])
        self.assertEqual(store.load_session(), state)

    def test_replacing_a_different_owner_warns_with_both_logins(self):
        store.save_session({"cookies": []}, owner_login="old-owner")
        with patch("direct_cli.browser.store.print_warning_stderr") as warn:
            store.save_session({"cookies": []}, owner_login="new-owner")
        warned = " ".join(str(call) for call in warn.call_args_list)
        self.assertIn("old-owner", warned)
        self.assertIn("new-owner", warned)

    def test_replacing_the_same_owner_keeps_the_generic_warning(self):
        store.save_session({"cookies": []}, owner_login="same-owner")
        with patch("direct_cli.browser.store.print_warning_stderr") as warn:
            store.save_session({"cookies": []}, owner_login="same-owner")
        warned = " ".join(str(call) for call in warn.call_args_list)
        self.assertNotIn("same-owner", warned)

    def test_replacing_an_unstamped_session_keeps_the_generic_warning(self):
        store.save_session({"cookies": []})
        with patch("direct_cli.browser.store.print_warning_stderr") as warn:
            store.save_session({"cookies": []}, owner_login="new-owner")
        warned = " ".join(str(call) for call in warn.call_args_list)
        self.assertNotIn("new-owner", warned)


class TestOwnerLoginFromCookies(unittest.TestCase):
    """The owner stamp is resolved from the same jar the auth checks read."""

    def test_reads_passport_identity_cookie(self):
        from direct_cli.browser.session import _owner_login_from_cookies

        cookies = [
            {"name": "Session_id", "value": "s", "domain": ".yandex.ru"},
            {"name": "yandex_login", "value": "owner", "domain": ".yandex.ru"},
        ]
        self.assertEqual(_owner_login_from_cookies(cookies), "owner")

    def test_ignores_foreign_domains_and_empty_values(self):
        from direct_cli.browser.session import _owner_login_from_cookies

        cookies = [
            {"name": "yandex_login", "value": "evil", "domain": ".notyandex.ru"},
            {"name": "yandex_login", "value": "  ", "domain": "yandex.ru"},
            {"name": "other", "value": "x", "domain": ".yandex.ru"},
        ]
        self.assertIsNone(_owner_login_from_cookies(cookies))

    def test_absent_identity_cookie_is_a_soft_none(self):
        from direct_cli.browser.session import _owner_login_from_cookies

        self.assertIsNone(_owner_login_from_cookies([{"name": "Session_id"}]))
        self.assertIsNone(_owner_login_from_cookies([]))

    def test_legacy_login_cookie_is_not_trusted(self):
        """Only ``yandex_login`` stamps the owner (review of PR #933): this
        repo never observed a Passport ``login`` cookie, so trusting that
        name would let a foreign cookie forge the owner stamp."""
        from direct_cli.browser.session import _owner_login_from_cookies

        cookies = [
            {"name": "login", "value": "someone", "domain": ".yandex.ru"},
            {"name": "Session_id", "value": "s", "domain": ".yandex.ru"},
        ]
        self.assertIsNone(_owner_login_from_cookies(cookies))


class TestAssertSessionOwner(unittest.TestCase):
    """Issue #907: opening a saved session must refuse a stamped session
    owned by another account, and only warn for an unstamped (old) one."""

    def setUp(self):
        # Keep the anchor deterministic: no developer .env/env leakage, an
        # empty per-test auth store (conftest already isolates AUTH_STORE_PATH).
        env = patch.dict(
            "os.environ",
            {
                "YANDEX_DIRECT_TOKEN": "",
                "YANDEX_DIRECT_LOGIN": "",
                "YANDEX_DIRECT_BIND_PROFILE": "",
            },
            clear=False,
        )
        env.start()
        self.addCleanup(env.stop)

    @staticmethod
    def _status(owner):
        return {"exists": True, "owner_login": owner}

    def test_mismatched_stamp_raises_loudly_with_both_logins(self):
        from direct_cli.browser import auth as browser_auth
        from direct_cli.browser.session import BrowserAuthError

        with patch.object(
            browser_auth, "_expected_session_login", return_value="ksamatadirect"
        ):
            with self.assertRaises(BrowserAuthError) as cm:
                browser_auth._assert_session_owner(self._status("engineeringprint-ru"))
        message = str(cm.exception)
        self.assertIn("engineeringprint-ru", message)
        self.assertIn("ksamatadirect", message)
        # The hint must be the canonical _auth_hints pointer, not a variant.
        self.assertIn("direct auth login browser", message)

    def test_unstamped_session_warns_but_opens(self):
        from direct_cli.browser import auth as browser_auth

        with patch.object(
            browser_auth, "_expected_session_login", return_value="expected"
        ):
            with patch.object(browser_auth, "print_warning_stderr") as warn:
                browser_auth._assert_session_owner(self._status(None))
        warn.assert_called_once()
        self.assertIn("direct auth login browser", str(warn.call_args))
        # #916 wording: an unstamped session is about a missing identity
        # cookie, not about the CLI version that saved it.
        self.assertNotIn("older direct-cli", str(warn.call_args))

    def test_matching_owner_is_silent(self):
        from direct_cli.browser import auth as browser_auth

        with patch.object(
            browser_auth, "_expected_session_login", return_value="Owner"
        ):
            with patch.object(browser_auth, "print_warning_stderr") as warn:
                browser_auth._assert_session_owner(self._status("owner"))
        warn.assert_not_called()

    def test_no_anchor_means_no_opinion(self):
        from direct_cli.browser import auth as browser_auth

        with patch.object(browser_auth, "_expected_session_login", return_value=None):
            with patch.object(browser_auth, "print_warning_stderr") as warn:
                browser_auth._assert_session_owner(self._status("anyone"))
        warn.assert_not_called()

    def test_missing_session_is_a_noop(self):
        """Nothing is about to open — the missing-session error reports it."""
        from direct_cli.browser import auth as browser_auth

        with patch.object(
            browser_auth, "_expected_session_login", return_value="expected"
        ) as anchor:
            with patch.object(browser_auth, "print_warning_stderr") as warn:
                browser_auth._assert_session_owner(
                    {"exists": False, "owner_login": None}
                )
        anchor.assert_not_called()
        warn.assert_not_called()


class TestBrowserUA(unittest.TestCase):
    """Every context this module creates sends a real Chrome UA (#950):
    Yandex meets the default Playwright UA with ``showcaptchafast`` even on
    a valid cookie jar."""

    def _recording_chromium(self):
        class _Chromium:
            def __init__(self):
                self.launch_kwargs: Any = {}
                self.context_kwargs: Any = {}

            def launch(self, **kwargs):
                self.launch_kwargs = kwargs
                return self

            def close(self):
                pass

            def new_context(self, **kwargs):
                self.context_kwargs = kwargs
                return Mock()

        return _Chromium()

    def _fake_playwright(self, chromium_obj):
        class _Playwright:
            chromium: Any

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

        playwright = _Playwright()
        playwright.chromium = chromium_obj
        return playwright

    def test_default_ua_reaches_new_context(self):
        from direct_cli.browser import session as session_module

        chromium = self._recording_chromium()
        with patch.dict("os.environ", {}, clear=True):
            with session_module._launch_context(
                lambda: self._fake_playwright(chromium), headless=True
            ) as _:
                pass
        self.assertEqual(
            chromium.context_kwargs["user_agent"], session_module.DEFAULT_BROWSER_UA
        )

    def test_direct_browser_ua_env_overrides_default(self):
        from direct_cli.browser import session as session_module

        chromium = self._recording_chromium()
        with patch.dict("os.environ", {"DIRECT_BROWSER_UA": "TestUA/1.0"}):
            with session_module._launch_context(
                lambda: self._fake_playwright(chromium), headless=True
            ) as _:
                pass
        self.assertEqual(chromium.context_kwargs["user_agent"], "TestUA/1.0")

    def test_explicit_parameter_beats_env(self):
        from direct_cli.browser import session as session_module

        chromium = self._recording_chromium()
        with patch.dict("os.environ", {"DIRECT_BROWSER_UA": "TestUA/1.0"}):
            with session_module._launch_context(
                lambda: self._fake_playwright(chromium),
                headless=True,
                user_agent="Explicit/2.0",
            ) as _:
                pass
        self.assertEqual(chromium.context_kwargs["user_agent"], "Explicit/2.0")

    def test_empty_env_value_keeps_default(self):
        from direct_cli.browser import session as session_module

        chromium = self._recording_chromium()
        with patch.dict("os.environ", {"DIRECT_BROWSER_UA": ""}):
            with session_module._launch_context(
                lambda: self._fake_playwright(chromium), headless=True
            ) as _:
                pass
        self.assertEqual(
            chromium.context_kwargs["user_agent"], session_module.DEFAULT_BROWSER_UA
        )

    def test_platform_token_follows_host_os(self):
        # Playwright's user_agent overrides only the UA string —
        # navigator.platform and sec-ch-ua-platform keep reporting the real
        # host OS, so a Macintosh UA over Linux/Windows hints is itself a
        # fingerprint mismatch. Darwin's token is the #950-validated one.
        from direct_cli.browser import session as session_module

        expected = {
            "Darwin": "Macintosh; Intel Mac OS X 10_15_7",
            "Windows": "Windows NT 10.0; Win64; x64",
            "Linux": "X11; Linux x86_64",
            "SunOS": "X11; Linux x86_64",  # unknown host: X11 fallback
        }
        for system, token in expected.items():
            with self.subTest(system=system):
                with patch("platform.system", return_value=system):
                    self.assertEqual(session_module._chrome_platform_token(), token)

    def test_default_ua_shape(self):
        from direct_cli.browser import session as session_module

        self.assertRegex(
            session_module.DEFAULT_BROWSER_UA,
            r"^Mozilla/5\.0 \(.+\) AppleWebKit/537\.36 "
            r"\(KHTML, like Gecko\) Chrome/\d[\d.]* Safari/537\.36$",
        )


class TestExpectedSessionLogin(unittest.TestCase):
    """The tokenless anchor ladder: linked profile > base env > active
    profile (the last rung only under the #904 inherit opt-in)."""

    def setUp(self):
        env = patch.dict(
            "os.environ",
            {
                "YANDEX_DIRECT_TOKEN": "",
                "YANDEX_DIRECT_LOGIN": "",
                "YANDEX_DIRECT_BIND_PROFILE": "",
                # Explicit, not the conftest default: the gate is part of
                # the ladder under test.
                "YANDEX_DIRECT_INHERIT_GLOBAL": "1",
            },
            clear=False,
        )
        env.start()
        self.addCleanup(env.stop)

    def _save_store(self, profiles, active=None):
        from direct_cli import auth as api_auth

        api_auth.save_auth_store({"profiles": profiles, "active_profile": active})

    @staticmethod
    def _profile(login):
        return {"token": "t", "login": login, "source": "oauth"}

    def test_base_env_login_needs_the_base_token(self):
        from direct_cli.browser.auth import _expected_session_login

        self.assertIsNone(_expected_session_login())
        import os

        os.environ["YANDEX_DIRECT_LOGIN"] = "env-owner"
        self.assertIsNone(_expected_session_login())
        os.environ["YANDEX_DIRECT_TOKEN"] = "t"
        self.assertEqual(_expected_session_login(), "env-owner")

    def test_linked_profile_wins_and_is_isolated(self):
        """A configured folder link resolves like --profile: no fall-through
        to the active profile when the link's own login is absent (#917)."""
        import os

        from direct_cli.browser.auth import _expected_session_login

        self._save_store(
            {
                "linked": self._profile(None),
                "active": self._profile("active-owner"),
            },
            active="active",
        )
        os.environ["YANDEX_DIRECT_BIND_PROFILE"] = "linked"
        self.assertIsNone(_expected_session_login())

        os.environ["YANDEX_DIRECT_BIND_PROFILE"] = "missing"
        self.assertIsNone(_expected_session_login())

    def test_active_profile_login_is_the_last_rung(self):
        import os

        from direct_cli.browser.auth import _expected_session_login

        self._save_store({"p": self._profile("profile-owner")}, active="p")
        self.assertEqual(_expected_session_login(), "profile-owner")
        # A linked profile beats the active profile's login.
        self._save_store(
            {
                "p": self._profile("profile-owner"),
                "l": self._profile("linked-owner"),
            },
            active="p",
        )
        os.environ["YANDEX_DIRECT_BIND_PROFILE"] = "l"
        self.assertEqual(_expected_session_login(), "linked-owner")

    def test_stale_active_profile_is_no_anchor_without_the_inherit_opt_in(self):
        """The silent active-profile rung exists only under the #904 opt-in,
        like the chain's own allow_active_profile gate (review of #943): in
        a default no-binding folder a stale global profile must not refuse
        the browser session — the re-login hint could not fix that."""
        import os

        from direct_cli.browser.auth import _expected_session_login

        self._save_store({"p": self._profile("profile-owner")}, active="p")
        os.environ["YANDEX_DIRECT_INHERIT_GLOBAL"] = ""
        self.assertIsNone(_expected_session_login())
        os.environ["YANDEX_DIRECT_INHERIT_GLOBAL"] = "1"
        self.assertEqual(_expected_session_login(), "profile-owner")

    def test_email_login_is_not_a_comparable_anchor(self):
        """Pre-#480 profiles may store a Passport email; that is no opinion,
        never a mismatch against the Client-Login in the stamp."""
        from direct_cli.browser.auth import _expected_session_login

        self._save_store({"p": self._profile("owner@example.com")}, active="p")
        self.assertIsNone(_expected_session_login())


def test_capture_storage_state_resolves_owner_login(tmp_path, monkeypatch):
    """`auth login browser --source chrome` stamps the owner resolved from
    the same decrypted jar the verification ran on."""
    pytest.importorskip("playwright")
    from direct_cli.browser import session as browser_session

    cookies = [
        {"name": "Session_id", "value": "s", "expires": -1, "domain": ".yandex.ru"},
        {"name": "yandex_login", "value": "chrome-owner", "domain": ".yandex.ru"},
    ]

    @contextlib.contextmanager
    def fake_launch(_sync_playwright, *, headless, storage_state=None):
        page = Mock()
        page.locator.return_value.first.count.return_value = 1
        page.content.return_value = "<html><body>grid</body></html>"
        context = Mock()
        context.new_page.return_value = page
        context.storage_state.return_value = {"cookies": cookies, "origins": []}
        yield Mock(), context

    monkeypatch.setattr(browser_session, "_import_sync_playwright", lambda: object())
    monkeypatch.setattr(
        "direct_cli.browser._chrome_crypto.load_yandex_cookies",
        lambda *args, **kwargs: cookies,
    )
    monkeypatch.setattr(browser_session, "_launch_context", fake_launch)

    _storage_state, source_meta = browser_session.capture_storage_state(
        profile_dir=tmp_path
    )
    assert source_meta["owner_login"] == "chrome-owner"
    assert source_meta["verified"] is True


def test_browser_session_status_reports_owner():
    from direct_cli.browser import auth as browser_auth

    store.save_session({"cookies": [], "origins": []}, owner_login="saved-owner")

    payload = browser_auth.session_status()

    assert payload["owner_login"] == "saved-owner"
    assert payload["exists"] is True


def test_auth_status_text_shows_owner():
    from click.testing import CliRunner

    from direct_cli.cli import cli

    store.save_session({"cookies": [], "origins": []}, owner_login="saved-owner")

    result = CliRunner().invoke(cli, ["auth", "status", "browser"])

    assert result.exit_code == 0, result.output
    assert "owner=saved-owner" in result.output


def test_import_browser_session_stamps_owner(tmp_path):
    from click.testing import CliRunner

    from direct_cli.cli import cli

    with patch(
        "direct_cli.browser.session.capture_storage_state",
        return_value=(
            {"cookies": [{"name": "Session_id", "domain": ".yandex.ru"}]},
            {
                "profile_dir": "/fake/chrome",
                "chrome_profile": "Default",
                "verified": True,
                "owner_login": "chrome-owner",
            },
        ),
    ):
        result = CliRunner().invoke(
            cli,
            ["auth", "login", "browser", "--source", "chrome", "--format", "json"],
        )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["owner"] == "chrome-owner"
    envelope = store.read_session_envelope()
    assert envelope is not None
    assert envelope["owner_login"] == "chrome-owner"


class TestSsoProbe(unittest.TestCase):
    """The cookie-only probe behind issue #954: one GET to the grid, verdict
    by status line alone — a server-revoked SSO session must be nameable
    without a browser (the #954 reporter diagnosed it with a manual curl)."""

    JAR = [
        {"name": "Session_id", "value": "sess", "domain": ".yandex.ru"},
        {"name": "sessionid2", "value": "s2", "domain": ".yandex.ru"},
        {"name": "yandex_login", "value": "owner", "domain": ".yandex.ru"},
        {"name": "yandexuid", "value": "uid", "domain": ".yandex.ru"},
    ]

    @staticmethod
    def _http_error(code, location=None):
        import email.message

        headers = email.message.Message()
        if location:
            headers["Location"] = location
        return urllib.error.HTTPError(
            "https://direct.yandex.ru/dna/grid/campaigns/", code, "x", headers, None
        )

    @contextlib.contextmanager
    def _opener(self, *, status=200, exc=None):
        recorded = {}

        class _Response:
            status: int = 200

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

        _Response.status = status

        class _Opener:
            def open(self, request, timeout=None):  # noqa: A003 - OpenerDirector API
                recorded["cookie"] = request.headers.get("Cookie")
                recorded["user_agent"] = request.headers.get("User-agent")
                recorded["timeout"] = timeout
                if exc is not None:
                    raise exc
                return _Response()

        with patch("urllib.request.build_opener", return_value=_Opener()):
            yield recorded

    def test_http_200_reads_as_alive_and_sends_the_whole_jar(self):
        with self._opener(status=200) as seen:
            verdict = _real_probe_sso_session(self.JAR)
        self.assertEqual(verdict, "alive")
        self.assertIn("Session_id=sess", seen["cookie"])
        self.assertIn("yandexuid=uid", seen["cookie"])
        self.assertTrue(seen["user_agent"].startswith("Mozilla/5.0"))

    def test_redirect_to_passport_reads_as_revoked(self):
        error = self._http_error(302, "https://passport.yandex.ru/auth?retpath=x")
        with self._opener(exc=error):
            self.assertEqual(_real_probe_sso_session(self.JAR), "revoked")

    def test_redirect_to_passport_locales_reads_as_revoked(self):
        """Passport's non-.ru login locales count too — by exact host name,
        so a look-alike domain (passport.yandex.evil.ru) stays unknown."""

        for host in ("passport.yandex.com", "passport.yandex.com.tr"):
            with self.subTest(host=host):
                error = self._http_error(302, f"https://{host}/auth")
                with self._opener(exc=error):
                    self.assertEqual(_real_probe_sso_session(self.JAR), "revoked")

    def test_look_alike_passport_domain_is_not_a_revocation(self):
        error = self._http_error(302, "https://passport.yandex.evil.ru/auth")
        with self._opener(exc=error):
            self.assertEqual(_real_probe_sso_session(self.JAR), "unknown")

    def test_redirect_elsewhere_is_not_a_revocation(self):
        error = self._http_error(302, "https://yandex.ru/somewhere")
        with self._opener(exc=error):
            self.assertEqual(_real_probe_sso_session(self.JAR), "unknown")

    def test_non_redirect_statuses_are_inconclusive(self):
        with self._opener(status=403):
            self.assertEqual(_real_probe_sso_session(self.JAR), "unknown")

    def test_network_failure_is_inconclusive_never_revoked(self):
        with self._opener(exc=urllib.error.URLError("connection refused")):
            self.assertEqual(_real_probe_sso_session(self.JAR), "unknown")

    def test_jar_without_sso_cookies_is_probed_without_a_request(self):
        """No Session_id/sessionid2 → no session for the server to recognize
        or revoke; the request would be pure network noise."""

        tracker_only = [{"name": "yandexuid", "value": "u", "domain": ".yandex.ru"}]
        with self._opener(status=200) as seen:
            verdict = _real_probe_sso_session(tracker_only)
        self.assertEqual(verdict, "unknown")
        self.assertNotIn("cookie", seen, "no request must be opened at all")

    def test_sso_cookie_names_scope_to_yandex_domains(self):
        from direct_cli.browser import session as browser_session

        jar = self.JAR + [
            {"name": "Session_id", "value": "evil", "domain": ".notyandex.ru"}
        ]
        self.assertEqual(
            browser_session.sso_cookie_names(jar),
            ["Session_id", "sessionid2", "yandex_login"],
        )
        self.assertEqual(browser_session.sso_cookie_names([]), [])

    def test_saved_session_probe_reads_the_envelope(self):
        from direct_cli.browser import session as browser_session

        self.assertEqual(browser_session.probe_saved_session(), "unknown")
        store.save_session({"cookies": self.JAR, "origins": []})
        with patch.object(
            browser_session, "probe_sso_session", return_value="revoked"
        ) as probe:
            self.assertEqual(browser_session.probe_saved_session(), "revoked")
        probed_jar = probe.call_args.args[0]
        self.assertEqual(
            [c["name"] for c in probed_jar],
            ["Session_id", "sessionid2", "yandex_login", "yandexuid"],
        )

    def test_cookieless_envelope_probes_unknown_without_a_request(self):
        from direct_cli.browser import session as browser_session

        store.save_session({"cookies": [], "origins": []})
        with patch("urllib.request.build_opener") as opener:
            self.assertEqual(browser_session.probe_saved_session(), "unknown")
        opener.assert_not_called()


class TestNoVerifyImportProbesTheJar(unittest.TestCase):
    """``--no-verify`` must not save a jar the server no longer recognizes
    (issue #954 п.2): the #954 import masked a dead session under a fresh-
    looking envelope. The probe is cookie-only, so the refusal needs no
    browser at all."""

    JAR = [{"name": "Session_id", "value": "x", "domain": ".yandex.ru"}]

    def _patched_capture(self, probe_verdict):
        from direct_cli.browser import session as browser_session

        @contextlib.contextmanager
        def _no_launch(*args, **kwargs):
            raise AssertionError("no browser may be launched for the probe refusal")

        @contextlib.contextmanager
        def _fake_launch(_sync_playwright, *, headless, storage_state=None):
            context = Mock()
            context.storage_state.return_value = {"cookies": self.JAR, "origins": []}
            yield Mock(), context

        return (
            patch.object(
                browser_session, "_import_sync_playwright", return_value=object()
            ),
            patch(
                "direct_cli.browser._chrome_crypto.load_yandex_cookies",
                return_value=self.JAR,
            ),
            patch.object(
                browser_session,
                "default_chrome_profile_dir",
                return_value=Path(tempfile.gettempdir()),
            ),
            patch.object(Path, "exists", return_value=True),
            patch.object(
                browser_session, "probe_sso_session", return_value=probe_verdict
            ),
            patch.object(
                browser_session,
                "_launch_context",
                _fake_launch if probe_verdict == "alive" else _no_launch,
            ),
        )

    def test_revoked_verdict_refuses_the_save_without_a_browser(self):
        pytest.importorskip("playwright")
        from direct_cli.browser import session as browser_session

        with contextlib.ExitStack() as stack:
            for ctx in self._patched_capture("revoked"):
                stack.enter_context(ctx)
            with self.assertRaises(browser_session.BrowserAuthError) as cm:
                browser_session.capture_storage_state(verify=False)

        # Locale-independent fragments: the passport host and the canonical
        # re-import hint are the same under every locale.
        message = str(cm.exception)
        self.assertIn("passport.yandex.ru", message)
        self.assertIn("direct auth login browser --source chrome", message)
        self.assertIsNone(store.read_session_envelope(), "a revoked jar is not saved")

    def test_alive_verdict_saves_the_session_unverified(self):
        pytest.importorskip("playwright")
        from direct_cli.browser import session as browser_session

        with contextlib.ExitStack() as stack:
            for ctx in self._patched_capture("alive"):
                stack.enter_context(ctx)
            state, source_meta = browser_session.capture_storage_state(verify=False)

        self.assertFalse(
            source_meta["verified"], "--no-verify never claims a verified session"
        )
        # The verdict is not the save: capture returns the normalized
        # storage_state, and the command layer (import_browser_session)
        # persists it — covered by the owner-stamp tests below.
        self.assertEqual(state, {"cookies": self.JAR, "origins": []})


class TestVerifyFailureProbe(unittest.TestCase):
    """The verify path's auth failure must split into "revoked server-side"
    (probe says so) vs. the legacy #870 bot-challenge/expiry stories."""

    def _capture_expect_auth_error(self, probe_verdict):
        from direct_cli.browser import session as browser_session

        jar = [
            {
                "name": "Session_id",
                "value": "irrelevant",
                "expires": 2**31,
                "domain": ".yandex.ru",
            }
        ]

        @contextlib.contextmanager
        def _fake_launch_context(_sync_playwright, *, headless, storage_state=None):
            context = Mock()
            context.new_page.return_value = Mock()
            yield Mock(), context

        with contextlib.ExitStack() as stack:
            for ctx in (
                patch.object(
                    browser_session, "_import_sync_playwright", return_value=object()
                ),
                patch(
                    "direct_cli.browser._chrome_crypto.load_yandex_cookies",
                    return_value=jar,
                ),
                patch.object(browser_session, "_launch_context", _fake_launch_context),
                patch.object(
                    browser_session,
                    "_goto_with_network_retry",
                    side_effect=browser_session.BrowserAuthError("login page served"),
                ),
                patch.object(
                    browser_session, "probe_sso_session", return_value=probe_verdict
                ),
            ):
                stack.enter_context(ctx)
            with self.assertRaises(browser_session.BrowserAuthError) as cm:
                browser_session.capture_storage_state(
                    profile_dir=Path(tempfile.gettempdir())
                )
        return str(cm.exception)

    def test_revoked_verdict_replaces_the_ambiguous_message(self):
        pytest.importorskip("playwright")

        message = self._capture_expect_auth_error("revoked")

        self.assertIn("passport.yandex.ru", message)
        self.assertIn("direct auth login browser --source chrome", message)
        self.assertNotIn(
            "invalidated server-side",
            message,
            "a probe-confirmed revocation must not read as a may-be challenge",
        )

    def test_unknown_verdict_keeps_the_legacy_messages(self):
        pytest.importorskip("playwright")

        message = self._capture_expect_auth_error("unknown")

        self.assertIn("invalidated server-side", message)
        self.assertIn("direct auth login browser --source chrome", message)


class TestOpenSessionRevokedProbe(unittest.TestCase):
    """A command failing mid-flight with the #870 auth error gets one
    cookie-only probe with the saved jar; a revoked verdict replaces the
    message (issue #954), an unknown one keeps the original untouched."""

    JAR = [{"name": "Session_id", "value": "x", "domain": ".yandex.ru"}]

    def _run_open_session(self, probe_verdict):
        from direct_cli.browser import auth as browser_auth
        from direct_cli.browser import session as browser_session

        store.save_session({"cookies": self.JAR, "origins": []})

        @contextlib.contextmanager
        def _saved(**kwargs):
            yield Mock()

        with (
            patch.object(
                browser_session, "_import_sync_playwright", return_value=object()
            ),
            patch.object(browser_session, "open_saved_session", _saved),
            patch.object(
                browser_session, "probe_sso_session", return_value=probe_verdict
            ),
            patch.object(browser_auth, "print_warning_stderr"),
        ):
            with self.assertRaises(browser_session.BrowserAuthError) as cm:
                with browser_auth.open_session():
                    raise browser_session.BrowserAuthError("login page served")
        return str(cm.exception)

    def test_revoked_verdict_replaces_the_error(self):
        pytest.importorskip("playwright")

        message = self._run_open_session("revoked")

        self.assertIn("passport.yandex.ru", message)
        self.assertIn("direct auth login browser --source chrome", message)
        self.assertNotIn("login page served", message)

    def test_unknown_verdict_keeps_the_original_error_and_hint(self):
        pytest.importorskip("playwright")

        message = self._run_open_session("unknown")

        self.assertIn("login page served", message)
        self.assertIn("direct auth login browser", message)
        self.assertNotIn("passport.yandex.ru", message)


class TestAuthStatusBrowserProbePayload(unittest.TestCase):
    """`auth status browser` (issue #954 п.3): probe verdict, SSO cookie
    inventory and the envelope's created_at — "the session is dead" visible
    without curl. The hidden legacy aliases render the same payload, so the
    JSON contract (bare status == api + browser subcommands) still holds."""

    JAR = [
        {"name": "Session_id", "value": "s", "domain": ".yandex.ru"},
        {"name": "yandex_login", "value": "owner", "domain": ".yandex.ru"},
    ]

    def _invoke_status(self, probe_verdict, *extra_args):
        from click.testing import CliRunner

        from direct_cli.browser import session as browser_session
        from direct_cli.cli import cli

        store.save_session(
            {"cookies": self.JAR, "origins": []},
            owner_login="owner",
            source={},
        )
        with patch.object(
            browser_session, "probe_sso_session", return_value=probe_verdict
        ):
            return CliRunner().invoke(cli, ["auth", "status", "browser", *extra_args])

    def test_json_payload_carries_probe_sso_and_created_at(self):
        result = self._invoke_status("alive", "--format", "json")

        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["probe"], "alive")
        self.assertEqual(payload["sso_cookies"], 2)
        self.assertEqual(payload["sso_cookie_names"], ["Session_id", "yandex_login"])
        self.assertIsInstance(payload["created_at"], float)
        self.assertEqual(payload["owner_login"], "owner")

    def test_text_output_shows_the_probe_line(self):
        result = self._invoke_status("alive")

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("probe: alive", result.output)
        self.assertIn("sso_cookies: 2 (Session_id, yandex_login)", result.output)
        self.assertIn("created_at: ", result.output)

    def test_revoked_verdict_prints_the_diagnostic(self):
        result = self._invoke_status("revoked")

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("probe: revoked", result.output)
        # Locale-independent fragments of the #954 diagnostic.
        self.assertIn("passport.yandex.ru", result.output)
        self.assertIn("direct auth login browser --source chrome", result.output)

    def test_missing_session_probes_unknown_without_a_request(self):
        from click.testing import CliRunner

        from direct_cli.cli import cli

        with patch("urllib.request.build_opener") as opener:
            result = CliRunner().invoke(cli, ["auth", "status", "browser"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("probe: unknown", result.output)
        opener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
