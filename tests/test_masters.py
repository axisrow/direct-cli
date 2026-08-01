"""
Tests for `direct masters` — the Мастер кампаний (Campaign Wizard) browser group.

Мастер кампаний has no API surface at all (see direct_cli/browser/__init__.py),
so unlike every other command module these tests never call a real API and
never launch a real browser.

``get`` (per-campaign overview) is a DOM parser exercised against small fake
Page/Locator objects that implement just the Playwright surface it calls
(locator/nth/count/inner_text/get_attribute/goto) — see
tests/fixtures/masters_wizard_overview.html for the live page structure these
fakes are modeled on.

``list`` reads the campaigns grid's own JSON data call instead of the DOM
(issue #639 found the grid is a virtualized SPA with no Мастер-related DOM to
scrape) — see tests/fixtures/masters_grid_campaigns.json for the trimmed real
GridCampaigns response these tests replay, and FakePage's ``request``/``on``
additions below for how that replay is faked.
"""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner

from direct_cli.browser import masters as browser_masters
from direct_cli.browser.masters import PlaywrightError
from direct_cli.browser.session import (
    BrowserCaptchaError,
    BrowserSessionError,
)
from direct_cli.cli import cli

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_grid_campaigns_fixture():
    with open(FIXTURES_DIR / "masters_grid_campaigns.json", encoding="utf-8") as f:
        return json.load(f)


class _FakeLocatorHandle:
    """One matched element — the subset of Playwright's Locator API the parser uses.

    ``click``/``fill``/``check``/``uncheck``/``is_visible`` support
    ``update_master``'s ``_set_*`` functions (issue #631) — ``on_click``/
    ``on_fill``/``on_check`` are optional no-arg/one-arg callbacks so tests
    can model the fake page's mutable state changing (mirrors
    ``_FakeTextLocatorHandle.on_click`` used by suspend/resume tests).
    ``input_value``/``is_checked`` support the post-save read-back
    verification in ``_verify_saved`` — they read the SAME mutable
    ``checked``/``value`` state ``fill``/``check``/``uncheck`` write, via
    ``state`` dict callables (``get_value``/``get_checked``), so a test can
    model "the reload shows what was actually saved" instead of "whatever
    was passed to fill/check".
    """

    def __init__(
        self,
        text="",
        attrs=None,
        raises=False,
        visible=True,
        on_click=None,
        on_fill=None,
        on_check=None,
        get_value=None,
        get_checked=None,
    ):
        self._text = text
        self._attrs = attrs or {}
        self._raises = raises
        self._visible = visible
        self._on_click = on_click
        self._on_fill = on_fill
        self._on_check = on_check
        self._get_value = get_value
        self._get_checked = get_checked

    def inner_text(self):
        if self._raises:
            # Real Playwright raises its own Error (a TimeoutError subclass) when
            # an element is missing — masters.py's `except PlaywrightError` must
            # catch exactly this class, so the test uses the real one too.
            raise PlaywrightError("element not found")
        return self._text

    def get_attribute(self, name):
        return self._attrs.get(name)

    def is_visible(self):
        if self._raises:
            raise PlaywrightError("element detached")
        return self._visible

    def click(self):
        if self._raises:
            raise PlaywrightError("element detached")
        if self._on_click is not None:
            self._on_click()

    def fill(self, value):
        if self._raises:
            raise PlaywrightError("element detached")
        self._text = value
        if self._on_fill is not None:
            self._on_fill(value)

    def check(self):
        if self._raises:
            raise PlaywrightError("element detached")
        if self._on_check is not None:
            self._on_check(True)

    def uncheck(self):
        if self._raises:
            raise PlaywrightError("element detached")
        if self._on_check is not None:
            self._on_check(False)

    def input_value(self):
        if self._raises:
            raise PlaywrightError("element detached")
        return self._get_value() if self._get_value is not None else self._text

    def is_checked(self):
        if self._raises:
            raise PlaywrightError("element detached")
        return self._get_checked() if self._get_checked is not None else False


class _FakeLocator:
    """A Locator for one selector — holds every matched handle for that selector."""

    def __init__(self, handles):
        self._handles = handles

    def count(self):
        return len(self._handles)

    def nth(self, i):
        return self._handles[i]

    @property
    def first(self):
        return self._handles[0] if self._handles else _FakeLocatorHandle(raises=True)


class _FakeRequest:
    def __init__(self, post_data=None, headers=None):
        self.post_data = post_data
        self.headers = headers or {"x-csrf-token": "fake"}


class _FakeGridResponse:
    """The subset of Playwright's Response ``_capture_grid_campaigns_request``
    reads off the ``response`` event: ``url``, ``status``,
    ``request.post_data``, ``request.headers``."""

    def __init__(self, url, status=200, post_data=None, headers=None):
        self.url = url
        self.status = status
        self.request = _FakeRequest(post_data, headers)


class _FakeApiRequestContext:
    """Fakes ``page.request`` — the replayed POST used for pagination."""

    def __init__(self, pages=None, ok=True, status=200, raw_body=None):
        # `pages`: list of dict payloads returned on successive .post() calls
        # (one per pagination page); the last one repeats if exhausted.
        self._pages = pages or []
        self._call_count = 0
        self._ok = ok
        self._status = status
        self._raw_body = raw_body
        self.calls = []  # (url, data, headers) for assertions

    def post(self, url, data=None, headers=None):
        self.calls.append((url, data, headers))
        idx = min(self._call_count, max(len(self._pages) - 1, 0))
        self._call_count += 1
        payload = self._pages[idx] if self._pages else {}
        return _FakeApiResponse(
            ok=self._ok, status=self._status, payload=payload, raw_body=self._raw_body
        )


class _FakeApiResponse:
    def __init__(self, ok=True, status=200, payload=None, raw_body=None):
        self.ok = ok
        self.status = status
        self._payload = payload
        self._raw_body = raw_body

    def json(self):
        if self._raw_body is not None:
            return json.loads(self._raw_body)  # may raise, on purpose
        return self._payload


class _FakeResponseInfo:
    """Mimics Playwright's ``EventContextManager`` returned by ``expect_response``.

    ``value`` is only resolved lazily (matching real Playwright, where the
    listener started in ``__enter__`` but the wait happens on first access
    to ``.value``, after the wrapped ``with`` block — e.g. ``goto`` — has
    run and had a chance to trigger the response).
    """

    def __init__(self, page, predicate):
        self._page = page
        self._predicate = predicate

    @property
    def value(self):
        candidate = self._page._grid_response
        if candidate is not None and self._predicate(candidate):
            return candidate
        # Real Playwright raises its TimeoutError (a PlaywrightError
        # subclass) when the predicate never matches within the timeout.
        raise PlaywrightError("Timeout waiting for response")


class _FakeExpectResponse:
    """Context manager fake for ``page.expect_response(predicate, timeout=...)``."""

    def __init__(self, page, predicate):
        self._page = page
        self._predicate = predicate

    def __enter__(self):
        return _FakeResponseInfo(self._page, self._predicate)

    def __exit__(self, *exc_info):
        return False


class _FakeTextLocatorHandle:
    """One matched element for ``get_by_text`` — supports ``is_visible``/``click``.

    ``on_click`` is an optional no-arg callback invoked when ``click()`` is
    called — used to model a suspend/resume click flipping the fake page's
    status text.
    """

    def __init__(self, visible=True, on_click=None, raises=False):
        self._visible = visible
        self._on_click = on_click
        self._raises = raises

    def is_visible(self):
        if self._raises:
            raise PlaywrightError("element detached")
        return self._visible

    def click(self):
        if self._raises:
            raise PlaywrightError("element detached")
        if self._on_click is not None:
            self._on_click()


class _FakeGetByTextLocator:
    """Fakes ``page.get_by_text(text, exact=False)`` — one handle list per text."""

    def __init__(self, handles):
        self._handles = handles

    def count(self):
        return len(self._handles)

    def nth(self, i):
        return self._handles[i]


class FakePage:
    """A Page whose ``locator(selector)`` result is pre-scripted per selector."""

    def __init__(
        self,
        locators=None,
        body_text="",
        html="<html></html>",
        grid_response=None,
        api_request=None,
        text_buttons=None,
        role_elements=None,
    ):
        self._locators = locators or {}
        self._body_text = body_text
        self._html = html
        self.navigated_to = []
        self.goto_wait_until = None
        self.closed = False
        # If set, matched by expect_response()'s predicate once goto() has
        # been called inside its `with` block — models the grid firing its
        # GridCampaigns XHR during navigation.
        self._grid_response = grid_response
        self.request = api_request or _FakeApiRequestContext()
        # {text: _FakeGetByTextLocator} for get_by_text() — used by
        # suspend_master/resume_master's action-button click.
        self._text_buttons = text_buttons or {}
        # [(role, accessible_name, handle), ...] for get_by_role() — honors
        # `exact` the same way real Playwright does (substring vs. equality
        # against `accessible_name`), so a fake test can actually catch a
        # get_by_role() call whose `exact`/`name` doesn't match the real
        # element, instead of always matching by selector-string identity
        # (issue #631 cycle-review: the previous get_by_text-based fakes
        # could not distinguish a correct role-scoped match from an
        # accidental ancestor-container match).
        self._role_elements = role_elements or []

    def goto(self, url, wait_until=None):
        self.navigated_to.append(url)
        self.goto_wait_until = wait_until

    def close(self):
        self.closed = True

    def expect_response(self, predicate, timeout=None):
        return _FakeExpectResponse(self, predicate)

    def eval_on_selector_all(self, selector, expression):
        return []

    def locator(self, selector):
        return self._locators.get(selector, _FakeLocator([]))

    def get_by_text(self, text, exact=False):
        return self._text_buttons.get(text, _FakeGetByTextLocator([]))

    def get_by_role(self, role, name=None, exact=False):
        matched = []
        for elem_role, elem_name, handle in self._role_elements:
            if elem_role != role:
                continue
            if name is None:
                matched.append(handle)
            elif exact:
                if elem_name == name:
                    matched.append(handle)
            elif name in elem_name:
                matched.append(handle)
        return _FakeGetByTextLocator(matched)

    def inner_text(self, selector=None):
        return self._body_text

    def content(self):
        return self._html

    def wait_for_timeout(self, timeout):
        pass


class TestMastersRegistered(unittest.TestCase):
    """The group and its subcommands must be wired into the root CLI."""

    def setUp(self):
        self.runner = CliRunner()

    def test_masters_group_registered(self):
        result = self.runner.invoke(cli, ["masters", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("list", result.output)
        self.assertIn("get", result.output)
        self.assertIn("login", result.output)
        self.assertIn("logout", result.output)

    def test_masters_list_help(self):
        result = self.runner.invoke(cli, ["masters", "list", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_masters_list_help_documents_chrome_profile_flag(self):
        # session.py's error message tells users with a non-Default Chrome
        # profile to pass --chrome-profile — that flag must actually exist.
        result = self.runner.invoke(cli, ["masters", "list", "--help"])
        self.assertIn("--chrome-profile", result.output)

    def test_masters_get_help(self):
        result = self.runner.invoke(cli, ["masters", "get", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_masters_list_has_no_login_option(self):
        # #639: --login built a `?ulogin=<own login>` URL, which Yandex
        # rejects with HTTP 401 "Доступ ограничен" — masters only ever reads
        # the logged-in browser session's own account, so the option is gone.
        result = self.runner.invoke(cli, ["masters", "list", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertNotIn("--login", result.output)

    def test_masters_get_has_no_login_option(self):
        result = self.runner.invoke(cli, ["masters", "get", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertNotIn("--login", result.output)

    def test_masters_list_has_status_option(self):
        result = self.runner.invoke(cli, ["masters", "list", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--status", result.output)

    def test_masters_no_credentials_required(self):
        # masters is in cli.py's _NO_CREDENTIALS_GROUPS -- no API token/login
        # is needed to even reach the browser layer's own errors.
        with patch.dict(
            "sys.modules", {"playwright": None, "playwright.sync_api": None}
        ):
            result = self.runner.invoke(
                cli,
                ["masters", "list"],
                env={"YANDEX_DIRECT_TOKEN": "", "YANDEX_DIRECT_LOGIN": ""},
            )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("playwright", result.output.lower())
        self.assertIn("pip install", result.output)
        self.assertNotIn("token", result.output.lower())

    def test_masters_list_missing_playwright_shows_install_hint(self):
        with patch.dict(
            "sys.modules", {"playwright": None, "playwright.sync_api": None}
        ):
            result = self.runner.invoke(cli, ["masters", "list"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("playwright", result.output.lower())
        self.assertIn("pip install", result.output)

    def test_open_session_catches_errors_raised_inside_the_with_block(self):
        # Regression test for #634: open_chrome_session is a
        # @contextlib.contextmanager, so calling it only builds a generator —
        # anything its body raises only surfaces on `__enter__`. A naive
        # `try: return open_chrome_session(...) except BrowserSessionError`
        # around just the *call* can never catch that (the call itself never
        # raises), so commands/masters.py::_open_session must itself be a
        # contextmanager wrapping the inner `with` statement — see its
        # docstring. This matters once code *inside* the `with` block raises
        # a BrowserSessionError subclass too (e.g. BrowserAuthError from
        # #634's login-page detector), which must be reported the same way.
        import contextlib

        from direct_cli.commands.masters import _open_session, masters

        # A genuine contextmanager generator whose body raises on __enter__,
        # exactly like open_chrome_session — not a mock with side_effect=,
        # which would raise on call and prove nothing about this bug.
        @contextlib.contextmanager
        def _fake_open_chrome_session(**kwargs):
            raise BrowserSessionError("boom from generator body")
            yield  # pragma: no cover - unreachable, contextmanager shape only

        # A real click.Context (rather than a bare Mock) so
        # ctx.get_parameter_source(...) behaves correctly for tier-1
        # detection inside _open_session. Built from the `list` subcommand
        # (not the `masters` group itself, which is no_args_is_help).
        list_cmd = masters.commands["list"]
        with list_cmd.make_context("list", []) as ctx:
            with (
                patch(
                    "direct_cli.browser.session.open_chrome_session",
                    _fake_open_chrome_session,
                ),
                patch(
                    "direct_cli.browser.store.session_status",
                    return_value={"exists": False, "error": None, "expired": None},
                ),
            ):
                with self.assertRaises(click.ClickException) as cm:
                    with _open_session(
                        ctx, headful=False, profile_dir=None, chrome_profile="Default"
                    ):
                        pass
        self.assertIn("boom from generator body", str(cm.exception))


class _FakeContext:
    def __init__(self):
        self.added_cookies = None
        self.closed = False
        self.locale = None

    def add_cookies(self, cookies):
        self.added_cookies = cookies

    def new_page(self):
        return FakePage()

    def close(self):
        self.closed = True


class _FakeBrowser:
    def __init__(self):
        self.contexts_created = []
        self.closed = False
        self.launch_kwargs = None

    def new_context(self, **kwargs):
        ctx = _FakeContext()
        ctx.locale = kwargs.get("locale")
        self.contexts_created.append(ctx)
        return ctx

    def close(self):
        self.closed = True


class _FakePersistentContext:
    """Fakes the context ``launch_persistent_context`` returns directly.

    Unlike ``_FakeBrowser``/``_FakeContext`` (a separate browser + context
    pair for ``chromium.launch()``), a persistent context IS the return
    value — there is no separate ``Browser`` object to close.
    """

    def __init__(self, pages=None):
        self.closed = False
        self.launch_kwargs = None
        self._pages = list(pages or [])

    def new_page(self):
        if self._pages:
            return self._pages.pop(0)
        return FakePage()

    def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self, browser, persistent_context=None):
        self._browser = browser
        self._persistent_context = persistent_context
        self.launch_kwargs = None
        self.launch_persistent_context_kwargs = None
        self.launch_persistent_context_user_data_dir = None

    def launch(self, **kwargs):
        self.launch_kwargs = kwargs
        return self._browser

    def launch_persistent_context(self, user_data_dir, **kwargs):
        self.launch_persistent_context_user_data_dir = user_data_dir
        self.launch_persistent_context_kwargs = kwargs
        return self._persistent_context


class _FakePlaywright:
    def __init__(self, chromium):
        self.chromium = chromium

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class TestOpenChromeSession(unittest.TestCase):
    """#634: cookies are decrypted ourselves and injected via add_cookies(),
    rather than relying on a real Chrome launched on a copied profile."""

    def test_injects_decrypted_cookies_without_requesting_real_chrome_channel(self):
        # playwright is the optional `browser` extra, not an offline test
        # dependency — the offline CI job doesn't install it, and this test
        # patches "playwright.sync_api.sync_playwright" by string path, which
        # requires the real import to succeed.
        pytest.importorskip("playwright")
        from direct_cli.browser import session as session_module

        fake_browser = _FakeBrowser()
        fake_chromium = _FakeChromium(fake_browser)
        fake_playwright = _FakePlaywright(fake_chromium)
        fake_cookies = [{"name": "Session_id", "value": "x", "domain": ".yandex.ru"}]

        with (
            patch(
                "playwright.sync_api.sync_playwright",
                return_value=fake_playwright,
            ),
            patch(
                "direct_cli.browser._chrome_crypto.load_yandex_cookies",
                return_value=fake_cookies,
            ),
            patch.object(
                session_module,
                "default_chrome_profile_dir",
                return_value=Path("/fake/chrome/profile"),
            ),
            patch.object(Path, "exists", return_value=True),
        ):
            with session_module.open_chrome_session() as page:
                self.assertIsInstance(page, FakePage)

        # Cookies were injected, not left for a real Chrome to decrypt itself.
        ctx = fake_browser.contexts_created[0]
        self.assertEqual(ctx.added_cookies, fake_cookies)
        self.assertEqual(ctx.locale, "ru-RU")
        # channel="chrome" required a real Google Chrome install to be
        # present; bundled Chromium is now sufficient since we no longer
        # depend on the real browser to decrypt cookies for us.
        self.assertNotIn("channel", fake_chromium.launch_kwargs)
        # Both the context and the browser process must be cleaned up.
        self.assertTrue(ctx.closed)
        self.assertTrue(fake_browser.closed)


class TestPersistentSession(unittest.TestCase):
    """direct masters login (issue #635) — CLI-owned persistent Chromium
    profile, no Keychain/real-Chrome-cookie involvement at all.

    Uses real temp directories (rather than fake Path patching) because
    _launch_persistent_context calls profile_dir.mkdir() for real.
    """

    def setUp(self):
        import tempfile

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.profile_dir = Path(self._tmpdir.name) / "chrome-profile"
        # A completed login records its profile dir; keep that off the
        # developer's real ~/.direct-cli.
        pointer = patch(
            "direct_cli.browser.session.PROFILE_POINTER_PATH",
            Path(self._tmpdir.name) / "chrome-profile-path",
        )
        pointer.start()
        self.addCleanup(pointer.stop)

    def _make_profile(self):
        """Create a profile dir the way a completed `masters login` leaves it."""
        from direct_cli.browser.session import PROFILE_MARKER_NAME

        self.profile_dir.mkdir(parents=True)
        (self.profile_dir / PROFILE_MARKER_NAME).touch()

    def test_login_refuses_to_mark_an_existing_unrelated_directory(self):
        """`--profile-dir` at an existing directory must not be claimed.

        Codex review finding on PR #644: the profile dir was created with
        `exist_ok=True` and then unconditionally marked CLI-owned, so
        `masters login --profile-dir ~` planted the ownership marker into the
        user's home directory — and `masters logout` on the same path then
        accepted that marker as authorization to `shutil.rmtree` it. A failed
        login armed it just the same, because the marker was written before
        Chromium even launched.
        """
        pytest.importorskip("playwright")
        from direct_cli.browser import session as session_module
        from direct_cli.browser.session import (
            PROFILE_MARKER_NAME,
            BrowserSessionError,
        )

        victim = Path(self._tmpdir.name) / "my-documents"
        victim.mkdir()
        (victim / "taxes.pdf").write_text("important")

        persistent_ctx = _FakePersistentContext()
        fake_chromium = _FakeChromium(_FakeBrowser(), persistent_ctx)
        fake_playwright = _FakePlaywright(fake_chromium)

        with patch("playwright.sync_api.sync_playwright", return_value=fake_playwright):
            with self.assertRaises(BrowserSessionError) as ctx:
                session_module.login_persistent_session(
                    profile_dir=victim, timeout_ms=1_000
                )

        self.assertFalse(
            (victim / PROFILE_MARKER_NAME).exists(),
            "login planted an ownership marker in a directory it did not create",
        )
        self.assertTrue((victim / "taxes.pdf").exists())
        self.assertIn("already exists", str(ctx.exception).lower())

    def test_aborted_login_does_not_leave_a_profile_that_looks_usable(self):
        """A login that never completed must not register as a usable profile.

        `_launch_persistent_context` creates the directory before Chromium
        starts, so a login the user ctrl-C's out of (or that times out) leaves
        a directory behind with no session in it. If tier 1.5 accepted mere
        directory existence, every later `masters` call would route through
        that empty profile, launch a browser, fail auth, and only then fall
        back — paying a wasted browser launch each time and bypassing the
        user's working saved session.
        """
        pytest.importorskip("playwright")
        from direct_cli.browser import session as session_module
        from direct_cli.browser.session import BrowserAuthError

        login_page = FakePage(locators={}, html="<body>Войдите с Яндекс ID</body>")
        probe_page = FakePage(locators={}, html="<body>Войдите с Яндекс ID</body>")
        persistent_ctx = _FakePersistentContext(pages=[login_page, probe_page])
        fake_chromium = _FakeChromium(_FakeBrowser(), persistent_ctx)
        fake_playwright = _FakePlaywright(fake_chromium)

        with patch("playwright.sync_api.sync_playwright", return_value=fake_playwright):
            with self.assertRaises(BrowserAuthError):
                session_module.login_persistent_session(
                    profile_dir=self.profile_dir, timeout_ms=1_000
                )

        self.assertFalse(
            session_module.persistent_profile_is_usable(self.profile_dir),
            "an aborted login left a profile tier 1.5 would route through",
        )

    def test_recorded_profile_dir_is_absolute(self):
        """The login pointer must not make later commands depend on cwd.

        `masters login --profile-dir prof` recorded "prof" verbatim, so
        `masters logout` run from a different directory resolved it against
        *that* cwd — deleting a different profile, or none. The marker check
        still bounded the damage, but which directory a command acts on must
        not depend on where the user happens to be standing.
        """
        from direct_cli.browser import session as session_module

        pointer = Path(self._tmpdir.name) / "chrome-profile-path"
        with patch.object(session_module, "PROFILE_POINTER_PATH", pointer):
            session_module.remember_persistent_profile_dir(Path("relative/profile"))
            recorded = session_module.configured_persistent_profile_dir()

        self.assertTrue(
            recorded.is_absolute(),
            f"recorded a cwd-dependent path: {recorded}",
        )

    def test_open_persistent_session_raises_when_profile_missing(self):
        pytest.importorskip("playwright")
        from direct_cli.browser.session import (
            BrowserSessionMissingError,
            open_persistent_session,
        )

        with self.assertRaises(BrowserSessionMissingError) as ctx:
            with open_persistent_session(profile_dir=self.profile_dir):
                pass
        self.assertIn("masters login", str(ctx.exception))

    def test_open_persistent_session_launches_persistent_context(self):
        pytest.importorskip("playwright")
        from direct_cli.browser import session as session_module

        self._make_profile()
        persistent_ctx = _FakePersistentContext()
        fake_chromium = _FakeChromium(_FakeBrowser(), persistent_ctx)
        fake_playwright = _FakePlaywright(fake_chromium)

        with patch("playwright.sync_api.sync_playwright", return_value=fake_playwright):
            with session_module.open_persistent_session(
                profile_dir=self.profile_dir
            ) as page:
                self.assertIsInstance(page, FakePage)

        self.assertEqual(
            fake_chromium.launch_persistent_context_user_data_dir,
            str(self.profile_dir),
        )
        self.assertEqual(
            fake_chromium.launch_persistent_context_kwargs["locale"], "ru-RU"
        )
        self.assertTrue(persistent_ctx.closed)

    def test_open_persistent_session_chmods_profile_dir_0700(self):
        # issue #635 risk: the profile holds a live Yandex session in
        # plaintext-readable cookies -- must be 0700, same as
        # direct_cli/browser/store.py's session file directory.
        pytest.importorskip("playwright")
        import stat

        from direct_cli.browser import session as session_module
        from direct_cli.browser.session import PROFILE_MARKER_NAME

        # A real profile (marker present) that has somehow ended up
        # world-readable -- reopening it must tighten the mode back to 0700.
        self.profile_dir.mkdir(parents=True, mode=0o755)
        (self.profile_dir / PROFILE_MARKER_NAME).touch()
        persistent_ctx = _FakePersistentContext()
        fake_chromium = _FakeChromium(_FakeBrowser(), persistent_ctx)
        fake_playwright = _FakePlaywright(fake_chromium)

        with patch("playwright.sync_api.sync_playwright", return_value=fake_playwright):
            with session_module.open_persistent_session(profile_dir=self.profile_dir):
                pass

        mode = stat.S_IMODE(self.profile_dir.stat().st_mode)
        self.assertEqual(format(mode, "04o"), "0700")

    def test_login_persistent_session_returns_once_authenticated(self):
        pytest.importorskip("playwright")
        from direct_cli.browser import session as session_module

        # Page 1 is the visible Passport tab; page 2 is the poll probe whose
        # HTML decides whether login has completed.
        login_page = FakePage(locators={}, html="<body>Войдите с Яндекс ID</body>")
        authed_page = FakePage(locators={}, html="<body>Кампания остановлена</body>")
        persistent_ctx = _FakePersistentContext(pages=[login_page, authed_page])
        fake_chromium = _FakeChromium(_FakeBrowser(), persistent_ctx)
        fake_playwright = _FakePlaywright(fake_chromium)

        with patch("playwright.sync_api.sync_playwright", return_value=fake_playwright):
            session_module.login_persistent_session(
                profile_dir=self.profile_dir, timeout_ms=5_000
            )

        self.assertTrue(persistent_ctx.closed)
        self.assertTrue(self.profile_dir.exists())

    def test_login_persistent_session_times_out_if_never_authenticated(self):
        pytest.importorskip("playwright")
        from direct_cli.browser import session as session_module
        from direct_cli.browser.session import BrowserAuthError

        login_page = FakePage(locators={}, html="<body>Войдите с Яндекс ID</body>")
        probe_page = FakePage(locators={}, html="<body>Войдите с Яндекс ID</body>")
        persistent_ctx = _FakePersistentContext(pages=[login_page, probe_page])
        fake_chromium = _FakeChromium(_FakeBrowser(), persistent_ctx)
        fake_playwright = _FakePlaywright(fake_chromium)

        with patch("playwright.sync_api.sync_playwright", return_value=fake_playwright):
            with self.assertRaises(BrowserAuthError) as ctx:
                session_module.login_persistent_session(
                    profile_dir=self.profile_dir,
                    timeout_ms=1_000,
                )
        self.assertIn("Timed out", str(ctx.exception))
        self.assertTrue(probe_page.closed, "poll probe page was left open")

    def test_login_polling_does_not_navigate_the_page_the_user_is_typing_into(self):
        """The visible login page must stay on Passport until login succeeds.

        The poll loop checks authentication by driving the *same* page the
        human is typing into. Every interval it navigates that page away to
        the grid, wiping a half-filled login form and any 2FA prompt on it —
        the user cannot finish signing in against a page that resets under
        their hands once a second.
        """
        pytest.importorskip("playwright")
        from direct_cli.browser import session as session_module
        from direct_cli.browser.session import BrowserAuthError

        login_page = FakePage(locators={}, html="<body>Войдите с Яндекс ID</body>")
        probe_page = FakePage(locators={}, html="<body>Войдите с Яндекс ID</body>")
        persistent_ctx = _FakePersistentContext(pages=[login_page, probe_page])
        fake_chromium = _FakeChromium(_FakeBrowser(), persistent_ctx)
        fake_playwright = _FakePlaywright(fake_chromium)

        with patch("playwright.sync_api.sync_playwright", return_value=fake_playwright):
            with self.assertRaises(BrowserAuthError):
                session_module.login_persistent_session(
                    profile_dir=self.profile_dir,
                    timeout_ms=3_000,
                )

        # The page the user interacts with is navigated exactly once: to
        # Passport. Polling must not steer it anywhere else.
        self.assertEqual(
            login_page.navigated_to,
            [session_module._PASSPORT_LOGIN_URL],
            "poll loop navigated the user's login page away from Passport",
        )


class TestOpenSessionTiers(unittest.TestCase):
    """_open_session's tiered resolution: explicit profile / persistent CLI
    profile / saved session / fresh-decrypt fallback (with auth-error
    self-heal retry)."""

    def setUp(self):
        # Every test in this class exercises tiers below 1.5 (persistent CLI
        # profile) unless a test explicitly wants that tier -- patch
        # DEFAULT_PERSISTENT_PROFILE_DIR to a guaranteed-nonexistent Path so
        # these tests don't depend on whether the developer running them has
        # ever run `direct masters login` for real.
        patcher = patch(
            "direct_cli.browser.session.DEFAULT_PERSISTENT_PROFILE_DIR",
            Path("/nonexistent/chrome-profile"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        # Resolution goes through the login pointer -- keep it off the
        # developer's real ~/.direct-cli so these tests never depend on
        # whether `masters login` has been run on this machine.
        pointer = patch(
            "direct_cli.browser.session.PROFILE_POINTER_PATH",
            Path("/nonexistent/chrome-profile-path"),
        )
        pointer.start()
        self.addCleanup(pointer.stop)

    def _list_ctx(self, args=None):
        from direct_cli.commands.masters import masters

        list_cmd = masters.commands["list"]
        return list_cmd.make_context("list", list(args or []))

    def test_custom_login_profile_dir_is_honoured_by_reads(self):
        """A session saved by `login --profile-dir X` must be used by reads.

        Tier 1.5 originally resolved the profile from
        DEFAULT_PERSISTENT_PROFILE_DIR only and passed no profile_dir to
        open_persistent_session, so `masters login --profile-dir X` reported
        "Login confirmed" and then every list/get/suspend/resume ignored X
        entirely -- falling through to the Keychain path the flag exists to
        avoid.
        """
        import tempfile

        from direct_cli.commands.masters import _open_session

        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        custom = Path(tmpdir.name) / "custom-profile"
        (custom / "Default").mkdir(parents=True)
        (custom / "Default" / "Cookies").write_bytes(b"")

        with self._list_ctx() as ctx:
            with (
                patch(
                    "direct_cli.commands.masters._configured_persistent_profile_dir",
                    return_value=custom,
                ),
                patch(
                    "direct_cli.browser.session.open_persistent_session"
                ) as persistent,
                patch("direct_cli.browser.session.open_saved_session") as saved,
                patch("direct_cli.browser.session.open_chrome_session") as fresh,
            ):
                persistent.return_value.__enter__ = lambda self: "page"
                persistent.return_value.__exit__ = lambda self, *a: False
                with _open_session(
                    ctx, headful=False, profile_dir=None, chrome_profile="Default"
                ):
                    pass

        persistent.assert_called_once()
        self.assertEqual(persistent.call_args.kwargs.get("profile_dir"), custom)
        saved.assert_not_called()
        fresh.assert_not_called()

    def test_explicit_profile_dir_bypasses_saved_session(self):
        from direct_cli.commands.masters import _open_session

        with self._list_ctx(["--profile-dir", "/some/profile"]) as ctx:
            with (
                patch("direct_cli.browser.session.open_saved_session") as saved,
                patch("direct_cli.browser.session.open_chrome_session") as fresh,
            ):
                fresh.return_value.__enter__ = lambda self: "page"
                fresh.return_value.__exit__ = lambda self, *a: False
                with _open_session(
                    ctx,
                    headful=False,
                    profile_dir="/some/profile",
                    chrome_profile="Default",
                ):
                    pass
        saved.assert_not_called()
        fresh.assert_called_once()

    def test_persistent_profile_used_when_present(self):
        """Tier 1.5: when the CLI's own persistent profile holds a session,
        it's preferred over the saved storage_state session and the Keychain
        decrypt path -- neither should be touched."""
        import tempfile

        from direct_cli.commands.masters import _open_session

        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        # A profile a completed login would leave: Chromium's cookie store is
        # what makes it usable, not the directory merely existing.
        profile = Path(tmpdir.name) / "chrome-profile"
        (profile / "Default").mkdir(parents=True)
        (profile / "Default" / "Cookies").write_bytes(b"")

        with self._list_ctx() as ctx:
            with (
                patch(
                    "direct_cli.commands.masters._configured_persistent_profile_dir",
                    return_value=profile,
                ),
                patch(
                    "direct_cli.browser.session.open_persistent_session"
                ) as persistent,
                patch("direct_cli.browser.store.session_status") as status,
                patch("direct_cli.browser.session.open_saved_session") as saved,
                patch("direct_cli.browser.session.open_chrome_session") as fresh,
            ):
                persistent.return_value.__enter__ = lambda self: "page"
                persistent.return_value.__exit__ = lambda self, *a: False
                with _open_session(
                    ctx, headful=False, profile_dir=None, chrome_profile="Default"
                ):
                    pass
        persistent.assert_called_once()
        status.assert_not_called()
        saved.assert_not_called()
        fresh.assert_not_called()

    def test_fresh_saved_session_used_without_decrypting(self):
        from direct_cli.commands.masters import _open_session

        with self._list_ctx() as ctx:
            with (
                patch(
                    "direct_cli.browser.store.session_status",
                    return_value={"exists": True, "error": None, "expired": False},
                ),
                patch("direct_cli.browser.session.open_saved_session") as saved,
                patch("direct_cli.browser.session.open_chrome_session") as fresh,
            ):
                saved.return_value.__enter__ = lambda self: "page"
                saved.return_value.__exit__ = lambda self, *a: False
                with _open_session(
                    ctx, headful=False, profile_dir=None, chrome_profile="Default"
                ):
                    pass
        saved.assert_called_once()
        fresh.assert_not_called()

    def test_expired_saved_session_falls_through_to_fresh(self):
        from direct_cli.commands.masters import _open_session

        with self._list_ctx() as ctx:
            with (
                patch(
                    "direct_cli.browser.store.session_status",
                    return_value={"exists": True, "error": None, "expired": True},
                ),
                patch("direct_cli.browser.session.open_saved_session") as saved,
                patch("direct_cli.browser.session.open_chrome_session") as fresh,
                patch("direct_cli.commands.masters.print_info"),
            ):
                fresh.return_value.__enter__ = lambda self: "page"
                fresh.return_value.__exit__ = lambda self, *a: False
                with _open_session(
                    ctx, headful=False, profile_dir=None, chrome_profile="Default"
                ):
                    pass
        saved.assert_not_called()
        fresh.assert_called_once()

    def test_no_saved_session_falls_through_to_fresh_with_tip(self):
        from direct_cli.commands.masters import _open_session

        with self._list_ctx() as ctx:
            with (
                patch(
                    "direct_cli.browser.store.session_status",
                    return_value={"exists": False, "error": None, "expired": None},
                ),
                patch("direct_cli.browser.session.open_chrome_session") as fresh,
                patch("direct_cli.commands.masters.print_info") as info,
            ):
                fresh.return_value.__enter__ = lambda self: "page"
                fresh.return_value.__exit__ = lambda self, *a: False
                with _open_session(
                    ctx, headful=False, profile_dir=None, chrome_profile="Default"
                ):
                    pass
        fresh.assert_called_once()
        info.assert_called_once()
        self.assertIn("playwright login", info.call_args[0][0])

    def test_auth_error_from_saved_session_enter_propagates_uncaught(self):
        """_open_session itself no longer catches BrowserAuthError -- the
        retry now lives one level up, in _with_session (see
        TestWithSessionRetry). A BrowserAuthError raised on
        open_saved_session's __enter__ must propagate straight through."""
        import contextlib

        from direct_cli.browser.session import BrowserAuthError
        from direct_cli.commands.masters import _open_session

        @contextlib.contextmanager
        def _fake_open_saved_session(**kwargs):
            raise BrowserAuthError("saved session expired server-side")
            yield  # pragma: no cover - unreachable, contextmanager shape only

        with self._list_ctx() as ctx:
            with (
                patch(
                    "direct_cli.browser.store.session_status",
                    return_value={"exists": True, "error": None, "expired": False},
                ),
                patch(
                    "direct_cli.browser.session.open_saved_session",
                    _fake_open_saved_session,
                ),
                patch("direct_cli.browser.session.open_chrome_session") as fresh,
            ):
                fresh.return_value.__enter__ = lambda self: "page"
                fresh.return_value.__exit__ = lambda self, *a: False
                with self.assertRaises(BrowserAuthError):
                    with _open_session(
                        ctx, headful=False, profile_dir=None, chrome_profile="Default"
                    ):
                        pass
        fresh.assert_not_called()


class TestWithSessionRetry(unittest.TestCase):
    """_with_session retries the whole operation on BrowserAuthError.

    Regression coverage for the double-yield bug: a stale saved session is
    NOT caught on open (assert_authenticated runs inside the caller's
    operation, after the session has already been yielded), so the retry
    must re-run the operation against a fresh session rather than trying to
    yield a second time from the same _open_session generator invocation
    (which raises RuntimeError: generator didn't stop after throw()).
    """

    def _list_ctx(self, args=None):
        from direct_cli.commands.masters import masters

        list_cmd = masters.commands["list"]
        return list_cmd.make_context("list", list(args or []))

    def test_auth_error_raised_inside_operation_retries_via_fresh_session(self):
        import contextlib

        from direct_cli.browser.session import BrowserAuthError
        from direct_cli.commands.masters import _with_session

        @contextlib.contextmanager
        def _fake_open_saved_session(**kwargs):
            yield "saved-page"

        @contextlib.contextmanager
        def _fake_open_chrome_session(**kwargs):
            yield "fresh-page"

        calls = []

        def operation(page):
            calls.append(page)
            if page == "saved-page":
                # Mirrors assert_authenticated raising deep inside
                # fetch_masters_list/fetch_master, after _open_session has
                # already yielded the page to the caller.
                raise BrowserAuthError("stale session, detected mid-body")
            return f"ok:{page}"

        with self._list_ctx() as ctx:
            with (
                patch(
                    "direct_cli.browser.store.session_status",
                    return_value={"exists": True, "error": None, "expired": False},
                ),
                patch(
                    "direct_cli.browser.session.open_saved_session",
                    _fake_open_saved_session,
                ),
                patch(
                    "direct_cli.browser.session.open_chrome_session",
                    _fake_open_chrome_session,
                ),
            ):
                result = _with_session(ctx, False, None, "Default", operation)

        self.assertEqual(result, "ok:fresh-page")
        self.assertEqual(calls, ["saved-page", "fresh-page"])

    def test_no_saved_session_runs_operation_once(self):
        import contextlib

        from direct_cli.commands.masters import _with_session

        @contextlib.contextmanager
        def _fake_open_chrome_session(**kwargs):
            yield "fresh-page"

        with self._list_ctx() as ctx:
            with (
                patch(
                    "direct_cli.browser.store.session_status",
                    return_value={"exists": False, "error": None, "expired": None},
                ),
                patch(
                    "direct_cli.browser.session.open_chrome_session",
                    _fake_open_chrome_session,
                ),
                patch("direct_cli.commands.masters.print_info"),
            ):
                result = _with_session(
                    ctx, False, None, "Default", lambda page: f"ok:{page}"
                )

        self.assertEqual(result, "ok:fresh-page")


class TestFetchMastersList(unittest.TestCase):
    """`list` reads the grid's GridCampaigns JSON call, not its DOM (#639):
    the grid is a virtualized SPA and never renders a
    ``a[href*='/wizard/campaigns/']`` anchor (confirmed live)."""

    _GRID_REQUEST_BODY = {
        "operationName": "GridCampaigns",
        "variables": {
            "login": "ksamatadirect",
            "campaignInput": {
                "filter": {},
                "limitOffset": {"offset": 0, "limit": 200},
            },
        },
        "query": "query GridCampaigns { ... }",
    }

    def _grid_response(self, post_data=None, status=200):
        return _FakeGridResponse(
            url=(
                f"{browser_masters.GRID_API_URL}"
                f"?operationName={browser_masters._GRID_CAMPAIGNS_OPERATION}"
            ),
            status=status,
            post_data=post_data or json.dumps(self._GRID_REQUEST_BODY),
        )

    def _page(self, api_pages, grid_status=200, grid_post_data=None):
        return FakePage(
            grid_response=self._grid_response(
                post_data=grid_post_data, status=grid_status
            ),
            api_request=_FakeApiRequestContext(pages=api_pages),
        )

    def test_selects_only_uac_source_rows(self):
        fixture = _load_grid_campaigns_fixture()
        page = self._page([fixture])

        result = browser_masters.fetch_masters_list(page, status="all")

        ids = {row["CampaignId"] for row in result}
        # 72349978/107707079 (STOPPED), 77501358 (ARCHIVED TEXT), 100571135
        # (ARCHIVED CPM_BANNER) are all source == "UAC" in the fixture.
        self.assertEqual(ids, {72349978, 107707079, 77501358, 100571135})
        # The two non-UAC rows (75071838, 74773845) must never appear.
        self.assertNotIn(75071838, ids)
        self.assertNotIn(74773845, ids)

    def test_stopped_masters_included_by_default_status_filter(self):
        # Regression for #639: the user's two STOPPED Мастера must be found
        # under the *default* status filter, not just an explicit one.
        fixture = _load_grid_campaigns_fixture()
        page = self._page([fixture])

        result = browser_masters.fetch_masters_list(page)  # default status

        ids = {row["CampaignId"] for row in result}
        self.assertIn(72349978, ids)
        self.assertIn(107707079, ids)
        stopped = next(r for r in result if r["CampaignId"] == 72349978)
        self.assertEqual(stopped["Status"], "SUSPENDED")

    def test_status_archived_returns_only_archived(self):
        fixture = _load_grid_campaigns_fixture()
        page = self._page([fixture])

        result = browser_masters.fetch_masters_list(page, status="archived")

        ids = {row["CampaignId"] for row in result}
        self.assertEqual(ids, {77501358, 100571135})

    def test_status_all_returns_every_uac_row(self):
        fixture = _load_grid_campaigns_fixture()
        page = self._page([fixture])

        result = browser_masters.fetch_masters_list(page, status="all")

        self.assertEqual(len(result), 4)

    def test_paginates_past_the_page_limit(self):
        # totalCount exceeds one page's rowset -> a second request must be
        # made and its rows included, matching the live behaviour that
        # motivated this (a real account's totalCount=224 vs. a 200-row page,
        # see issue #639 diagnosis).
        fixture = _load_grid_campaigns_fixture()
        first_page_rows = fixture["data"]["client"]["campaigns"]["rowset"]
        second_page_rows = [
            {
                "id": "999000001",
                "name": "Мастер со второй страницы",
                "type": "TEXT",
                "metaType": "DEFAULT_",
                "source": "UAC",
                "__typename": "GdTextCampaign",
                "status": {"primaryStatus": "STOPPED"},
                "startDate": "2025-01-01",
            }
        ]
        total_count = len(first_page_rows) + len(second_page_rows)
        first_page = {
            "data": {
                "client": {
                    "campaigns": {
                        "totalCount": total_count,
                        "rowset": first_page_rows,
                    }
                }
            }
        }
        second_page = {
            "data": {
                "client": {
                    "campaigns": {
                        "totalCount": total_count,
                        "rowset": second_page_rows,
                    }
                }
            }
        }
        page = self._page([first_page, second_page])

        result = browser_masters.fetch_masters_list(page, status="all")

        ids = {row["CampaignId"] for row in result}
        self.assertIn(999000001, ids)
        self.assertEqual(len(page.request.calls), 2)

    def test_grid_url_never_contains_ulogin(self):
        # #639: passing our own login as `ulogin` produced HTTP 401 "Доступ
        # ограничен" — list() must never build that URL.
        fixture = _load_grid_campaigns_fixture()
        page = self._page([fixture])

        browser_masters.fetch_masters_list(page, status="all")

        self.assertTrue(page.navigated_to)
        for url in page.navigated_to:
            self.assertNotIn("ulogin", url)

    def test_no_grid_campaigns_request_observed_raises(self):
        # The grid fired no matching response at all (e.g. Yandex renamed the
        # operation) -> a clear BrowserSessionError, not a silent empty list.
        page = FakePage(grid_response=None)

        with self.assertRaises(BrowserSessionError):
            browser_masters.fetch_masters_list(page, status="all")

    def test_non_ok_api_response_raises_browser_session_error(self):
        fixture = _load_grid_campaigns_fixture()
        page = FakePage(
            grid_response=self._grid_response(),
            api_request=_FakeApiRequestContext(pages=[fixture], ok=False, status=500),
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters.fetch_masters_list(page, status="all")

    def test_non_json_api_response_raises_browser_session_error(self):
        page = FakePage(
            grid_response=self._grid_response(),
            api_request=_FakeApiRequestContext(raw_body="not json"),
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters.fetch_masters_list(page, status="all")

    def test_empty_result_prints_warning(self):
        empty = {"data": {"client": {"campaigns": {"totalCount": 0, "rowset": []}}}}
        page = self._page([empty])

        with patch("direct_cli.browser.masters.print_warning") as warn:
            result = browser_masters.fetch_masters_list(page, status="all")

        self.assertEqual(result, [])
        warn.assert_called_once()

    def test_unknown_status_filter_raises_value_error(self):
        page = self._page([_load_grid_campaigns_fixture()])
        with self.assertRaises(ValueError):
            browser_masters.fetch_masters_list(page, status="bogus")


class TestFetchMaster(unittest.TestCase):
    """Overview-page parsing: title, status, landing URL, stat tiles."""

    def _page_for(self, title="Мастер Тест", status_text="Кампания остановлена"):
        return FakePage(
            locators={
                "h1, [role=heading]": _FakeLocator([_FakeLocatorHandle(text=title)]),
                "a[href*='utm_source=']": _FakeLocator(
                    [
                        _FakeLocatorHandle(
                            attrs={
                                "href": (
                                    "https://lp.example.com/x?utm_source=yandex&"
                                    "utm_medium=cpc"
                                )
                            }
                        )
                    ]
                ),
                "button": _FakeLocator(
                    [
                        _FakeLocatorHandle(text="281 722\nПоказа"),
                        _FakeLocatorHandle(text="2 529\nКликов"),
                        _FakeLocatorHandle(text="83\nКонверсии"),
                        _FakeLocatorHandle(text="272,45 ₽\nЗа конверсию"),
                        _FakeLocatorHandle(text="22 613,58 ₽\nРасход"),
                        _FakeLocatorHandle(
                            text="Возобновить кампанию"
                        ),  # noise: ignored
                    ]
                ),
            },
            body_text=status_text,
        )

    def test_parses_full_overview(self):
        page = self._page_for()

        result = browser_masters.fetch_master(page, 72349978)

        self.assertEqual(result["CampaignId"], 72349978)
        self.assertEqual(result["Name"], "Мастер Тест")
        self.assertEqual(result["Status"], "SUSPENDED")
        self.assertEqual(
            result["LandingUrl"],
            "https://lp.example.com/x?utm_source=yandex&utm_medium=cpc",
        )
        self.assertEqual(
            result["Stats"],
            {
                "impressions": "281 722",
                "clicks": "2 529",
                "conversions": "83",
                "cost_per_conversion": "272,45 ₽",
                "cost": "22 613,58 ₽",
            },
        )

    def test_active_status_recognised(self):
        page = self._page_for(status_text="Кампания активна")
        result = browser_masters.fetch_master(page, 1)
        self.assertEqual(result["Status"], "ACTIVE")

    def test_partial_result_on_unrecognised_sections(self):
        # A page with none of the expected sections must not raise — every
        # extractor degrades to omitting its field plus a warning, per the
        # module's "best-effort" contract (see fetch_master docstring).
        page = FakePage(locators={}, body_text="something Yandex changed the markup to")

        with patch("direct_cli.browser.masters.print_warning") as warn:
            result = browser_masters.fetch_master(page, 999)

        self.assertEqual(result, {"CampaignId": 999})
        self.assertGreaterEqual(warn.call_count, 3)  # name, status, landing, stats


class TestSuspendResumeMaster(unittest.TestCase):
    """suspend_master/resume_master (issue #630): click + verify, idempotent.

    See direct_cli/browser/masters.py module docstring: the suspend-side
    button text is NOT live-confirmed, only a best-effort candidate list --
    these tests exercise the click/verify/idempotency mechanics against that
    candidate list, not a live-verified button text.
    """

    def _page_with_button(
        self, status_text, button_text, next_status_text=None, visible=True
    ):
        state = {"status": status_text}

        def _flip():
            state["status"] = next_status_text

        page = FakePage(
            text_buttons={
                button_text: _FakeGetByTextLocator(
                    [_FakeTextLocatorHandle(visible=visible, on_click=_flip)]
                )
            },
        )
        # inner_text("body") must reflect the current (mutable) status, so
        # override the FakePage method rather than passing a fixed body_text.
        page.inner_text = lambda selector=None: state["status"]
        return page

    def test_resume_clicks_confirmed_button_and_verifies(self):
        page = self._page_with_button(
            "Кампания остановлена",
            "Возобновить кампанию",
            next_status_text="Кампания активна",
        )

        result = browser_masters.resume_master(page, 42)

        self.assertEqual(result, {"CampaignId": 42, "Status": "ACTIVE"})
        self.assertEqual(
            page.navigated_to,
            [browser_masters.WIZARD_OVERVIEW_URL.format(campaign_id=42)],
        )

    def test_suspend_clicks_candidate_button_and_verifies(self):
        page = self._page_with_button(
            "Кампания активна",
            "Остановить кампанию",
            next_status_text="Кампания остановлена",
        )

        result = browser_masters.suspend_master(page, 42)

        self.assertEqual(result, {"CampaignId": 42, "Status": "SUSPENDED"})

    def test_resume_idempotent_when_already_active(self):
        page = FakePage(body_text="Кампания активна")

        with patch("direct_cli.browser.masters.print_warning") as warn:
            result = browser_masters.resume_master(page, 7)

        self.assertEqual(result, {"CampaignId": 7, "Status": "ACTIVE"})
        warn.assert_called_once()
        self.assertIn("already", warn.call_args[0][0])

    def test_suspend_idempotent_when_already_suspended(self):
        page = FakePage(body_text="Кампания остановлена")

        with patch("direct_cli.browser.masters.print_warning"):
            result = browser_masters.suspend_master(page, 7)

        self.assertEqual(result, {"CampaignId": 7, "Status": "SUSPENDED"})

    def test_resume_raises_when_no_candidate_button_found(self):
        # None of _RESUME_BUTTON_TEXTS is present -- must not silently no-op.
        page = FakePage(body_text="Кампания остановлена", text_buttons={})

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.resume_master(page, 7)
        self.assertIn("--headful", str(ctx.exception))

    def test_suspend_raises_when_click_does_not_change_status(self):
        # The button is found and clicked, but the status text never flips --
        # must not report success on the click alone (module docstring).
        page = self._page_with_button(
            "Кампания активна",
            "Остановить кампанию",
            next_status_text="Кампания активна",  # unchanged after "click"
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.suspend_master(page, 42)
        self.assertIn("did not change", str(ctx.exception))

    def test_resume_raises_when_current_status_unrecognised(self):
        page = FakePage(body_text="something Yandex changed the markup to")

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.resume_master(page, 7)
        self.assertIn("Could not determine current status", str(ctx.exception))

    def test_suspend_button_invisible_is_skipped(self):
        # An invisible match (e.g. a hidden template) must not be clicked --
        # falls through to the "not found" error since it's the only handle.
        page = self._page_with_button(
            "Кампания активна", "Остановить кампанию", visible=False
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters.suspend_master(page, 42)


class TestMastersSuspendResumeCommand(unittest.TestCase):
    """CLI wiring for `masters suspend`/`masters resume`."""

    def setUp(self):
        self.runner = CliRunner()

    def test_suspend_registered(self):
        result = self.runner.invoke(cli, ["masters", "suspend", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_resume_registered(self):
        result = self.runner.invoke(cli, ["masters", "resume", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_suspend_has_no_login_option(self):
        result = self.runner.invoke(cli, ["masters", "suspend", "--help"])
        self.assertNotIn("--login", result.output)

    def test_resume_has_no_login_option(self):
        result = self.runner.invoke(cli, ["masters", "resume", "--help"])
        self.assertNotIn("--login", result.output)

    def test_suspend_calls_suspend_master_per_id(self):
        with (
            patch("direct_cli.browser.masters.suspend_master") as mock_suspend,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            result = self.runner.invoke(cli, ["masters", "suspend", "1,2"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_suspend.call_count, 2)

    def test_resume_calls_resume_master_per_id(self):
        with (
            patch("direct_cli.browser.masters.resume_master") as mock_resume,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            result = self.runner.invoke(cli, ["masters", "resume", "1"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_resume.call_count, 1)


class TestArchiveMaster(unittest.TestCase):
    """archive_master (issue #633): click + verify via the campaigns grid.

    Мастер кампаний has no separate "delete" (live recon, see module
    docstring) — archive is the only destructive/lifecycle action left.
    Unlike suspend/resume's text-matched candidate buttons, the overview
    page's "⋮" menu and its "Архивировать" item are confirmed live via
    stable ``data-testid`` selectors, so these tests exercise exact-selector
    clicks rather than a candidate-list fallback.
    """

    def _row(self, status):
        return {
            "CampaignId": 42,
            "Name": "Мастер тестовый",
            "Status": status,
            "Type": "TEXT",
            "StartDate": "2025-01-01",
        }

    def _page_with_menu(self, menu_trigger=None, archive_item=None):
        locators = {}
        if menu_trigger is not None:
            locators[browser_masters._MENU_TRIGGER_SELECTOR] = _FakeLocator(
                [menu_trigger]
            )
        if archive_item is not None:
            locators[browser_masters._ARCHIVE_MENU_ITEM_SELECTOR] = _FakeLocator(
                [archive_item]
            )
        return FakePage(locators=locators)

    def test_archives_and_verifies_via_grid(self):
        state = {"status": "STOPPED"}

        def _flip():
            state["status"] = "ARCHIVED"

        page = self._page_with_menu(
            menu_trigger=_FakeLocatorHandle(),
            archive_item=_FakeLocatorHandle(on_click=_flip),
        )

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            side_effect=lambda page, status="all": [self._row(state["status"])],
        ):
            result = browser_masters.archive_master(page, 42)

        self.assertEqual(result, self._row("ARCHIVED"))
        self.assertEqual(
            page.navigated_to,
            [browser_masters.WIZARD_OVERVIEW_URL.format(campaign_id=42)],
        )

    def test_idempotent_when_already_archived(self):
        page = self._page_with_menu()

        with (
            patch(
                "direct_cli.browser.masters.fetch_masters_list",
                return_value=[self._row("ARCHIVED")],
            ),
            patch("direct_cli.browser.masters.print_warning") as warn,
        ):
            result = browser_masters.archive_master(page, 42)

        self.assertEqual(result, self._row("ARCHIVED"))
        self.assertEqual(page.navigated_to, [])  # not clicking -> no navigation either
        warn.assert_called_once()
        self.assertIn("already archived", warn.call_args[0][0])

    def test_raises_when_campaign_not_found_in_grid(self):
        page = self._page_with_menu()

        with patch("direct_cli.browser.masters.fetch_masters_list", return_value=[]):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.archive_master(page, 42)

        self.assertIn("Could not find", str(ctx.exception))

    def test_raises_when_menu_trigger_not_found(self):
        page = self._page_with_menu()  # no menu_trigger locator registered

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            return_value=[self._row("STOPPED")],
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.archive_master(page, 42)

        self.assertIn("Could not open the campaign menu", str(ctx.exception))

    def test_raises_when_archive_menu_item_not_found(self):
        page = self._page_with_menu(menu_trigger=_FakeLocatorHandle())

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            return_value=[self._row("STOPPED")],
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.archive_master(page, 42)

        self.assertIn("Архивировать", str(ctx.exception))

    def test_raises_when_status_never_becomes_archived(self):
        # The click succeeds but the grid keeps reporting STOPPED -- must not
        # report success on the click alone.
        page = self._page_with_menu(
            menu_trigger=_FakeLocatorHandle(),
            archive_item=_FakeLocatorHandle(),
        )

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            return_value=[self._row("STOPPED")],
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.archive_master(page, 42)

        self.assertIn("did not report it as ARCHIVED", str(ctx.exception))


class TestMastersArchiveCommand(unittest.TestCase):
    """CLI wiring for `masters archive` (issue #633)."""

    def setUp(self):
        self.runner = CliRunner()

    def test_archive_registered(self):
        result = self.runner.invoke(cli, ["masters", "archive", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_archive_has_no_login_option(self):
        result = self.runner.invoke(cli, ["masters", "archive", "--help"])
        self.assertNotIn("--login", result.output)

    def test_archive_calls_archive_master_per_id(self):
        with (
            patch("direct_cli.browser.masters.archive_master") as mock_archive,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            result = self.runner.invoke(cli, ["masters", "archive", "1,2"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_archive.call_count, 2)

    def test_archive_reports_earlier_successes_when_a_later_id_fails(self):
        # Regression: archive is irreversible (no `masters unarchive`) -- a
        # naive list comprehension that aborts on the first exception would
        # silently lose the report that ids 1/2 were already archived in
        # production before id 3 failed. The per-ID outcome for every ID
        # must reach the user, not just the last error.
        def _fake_archive(page, campaign_id):
            if campaign_id == 3:
                raise BrowserSessionError("boom on id 3")
            return {"CampaignId": campaign_id, "Status": "ARCHIVED"}

        with (
            patch(
                "direct_cli.browser.masters.archive_master", side_effect=_fake_archive
            ) as mock_archive,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            result = self.runner.invoke(cli, ["masters", "archive", "1,2,3,4"])

        # All four IDs must be attempted -- a failure on id 3 must not skip
        # id 4, and must not discard the already-mutated 1/2 from the report.
        self.assertEqual(mock_archive.call_count, 4)
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("1", result.output)
        self.assertIn("ARCHIVED", result.output)
        self.assertIn("2", result.output)
        self.assertIn("boom on id 3", result.output)


class TestSetWeeklyBudget(unittest.TestCase):
    """``_set_weekly_budget`` (issue #631, Этап A) — fills the budget input."""

    def test_fills_field_with_bare_integer(self):
        state = {}
        handle = _FakeLocatorHandle(
            text="80 000", on_fill=lambda v: state.__setitem__("value", v)
        )
        page = FakePage(
            locators={
                browser_masters._WEEKLY_BUDGET_INPUT_XPATH: _FakeLocator([handle])
            }
        )

        browser_masters._set_weekly_budget(page, 95000)

        self.assertEqual(state["value"], "95000")

    def test_raises_browser_session_error_when_field_missing(self):
        page = FakePage(locators={})

        with self.assertRaises(BrowserSessionError):
            browser_masters._set_weekly_budget(page, 95000)


class TestSetDirectsHelps(unittest.TestCase):
    """``_set_directs_helps`` (issue #631, Этап A) — check/uncheck, idempotent API."""

    def test_enables_checkbox(self):
        state = {"checked": False}
        handle = _FakeLocatorHandle(on_check=lambda v: state.__setitem__("checked", v))
        page = FakePage(
            locators={
                browser_masters._DIRECT_HELPS_CHECKBOX_XPATH: _FakeLocator([handle])
            }
        )

        browser_masters._set_directs_helps(page, True)

        self.assertTrue(state["checked"])

    def test_disables_checkbox(self):
        state = {"checked": True}
        handle = _FakeLocatorHandle(on_check=lambda v: state.__setitem__("checked", v))
        page = FakePage(
            locators={
                browser_masters._DIRECT_HELPS_CHECKBOX_XPATH: _FakeLocator([handle])
            }
        )

        browser_masters._set_directs_helps(page, False)

        self.assertFalse(state["checked"])

    def test_raises_browser_session_error_when_checkbox_missing(self):
        page = FakePage(locators={})

        with self.assertRaises(BrowserSessionError):
            browser_masters._set_directs_helps(page, True)


class TestSetPromotionGoal(unittest.TestCase):
    """``_set_promotion_goal`` (issue #631, Этап A) — open dropdown, click, verify.

    Options are modeled via ``role_elements`` (role="option"), not
    ``text_buttons`` — ``_set_promotion_goal`` uses
    ``get_by_role("option", name=label, exact=True)`` (cycle-review fix: the
    previous ``get_by_text(exact=False)`` risked matching an ancestor
    container instead of the option row itself). Using ``role_elements``
    here means these tests actually exercise the same exact-name matching
    the real code performs, instead of matching by an opaque dict key.

    The trigger's ``inner_text()`` is modeled as TWO lines (static section
    label, then the current selection) — confirmed live 2026-08-01 (see
    ``tests/fixtures/masters_wizard_edit_stage_a.html``). A single-line fake
    would not have caught the regression where the verification code
    compared the WHOLE two-line ``inner_text()`` for exact equality against
    the bare one-line label (always false) instead of just its last line.
    """

    _TRIGGER_LABEL = "Цель продвижения"

    def _page_for_goal_selection(self, target_label, selected_line_after_click):
        state = {"selected_line": "Максимум целевых действий"}

        def _select():
            state["selected_line"] = selected_line_after_click

        trigger = _FakeLocatorHandle(text=self._TRIGGER_LABEL)
        # inner_text() must reflect the mutable state set by clicking the
        # option — two lines, matching the live-confirmed shape.
        trigger.inner_text = lambda: f"{self._TRIGGER_LABEL}\n{state['selected_line']}"

        return FakePage(
            locators={
                browser_masters._PROMOTION_GOAL_BUTTON_XPATH: _FakeLocator([trigger])
            },
            role_elements=[
                (
                    "option",
                    target_label,
                    _FakeTextLocatorHandle(visible=True, on_click=_select),
                )
            ],
        )

    def test_selects_option_and_verifies(self):
        page = self._page_for_goal_selection("Максимум переходов", "Максимум переходов")

        browser_masters._set_promotion_goal(page, "max-clicks")

        trigger = page.locator(browser_masters._PROMOTION_GOAL_BUTTON_XPATH).first
        self.assertEqual(trigger.inner_text(), "Цель продвижения\nМаксимум переходов")

    def test_does_not_match_option_whose_name_only_contains_label_as_substring(self):
        # A decoy element whose accessible name merely CONTAINS the target
        # label (e.g. an ancestor wrapper with extra description text) must
        # NOT be treated as a match — get_by_role(..., exact=True) requires
        # an exact accessible-name equality, not a substring.
        state = {"trigger_text": "Цель продвижения"}
        trigger = _FakeLocatorHandle(text="Цель продвижения")
        trigger.inner_text = lambda: state["trigger_text"]
        decoy_clicked = []
        page = FakePage(
            locators={
                browser_masters._PROMOTION_GOAL_BUTTON_XPATH: _FakeLocator([trigger])
            },
            role_elements=[
                (
                    "option",
                    "Максимум переходов — если хотите получать больше кликов",
                    _FakeTextLocatorHandle(
                        visible=True, on_click=lambda: decoy_clicked.append(True)
                    ),
                )
            ],
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters._set_promotion_goal(page, "max-clicks")
        self.assertEqual(decoy_clicked, [])

    def test_raises_on_unknown_goal_key(self):
        page = FakePage()

        with self.assertRaises(ValueError):
            browser_masters._set_promotion_goal(page, "not-a-real-goal")

    def test_raises_when_dropdown_trigger_missing(self):
        page = FakePage(locators={})

        with self.assertRaises(BrowserSessionError):
            browser_masters._set_promotion_goal(page, "max-clicks")

    def test_raises_when_option_not_found(self):
        trigger = _FakeLocatorHandle(text="Цель продвижения")
        page = FakePage(
            locators={
                browser_masters._PROMOTION_GOAL_BUTTON_XPATH: _FakeLocator([trigger])
            },
            role_elements=[],
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters._set_promotion_goal(page, "max-clicks")

    def test_raises_when_click_does_not_change_trigger_text(self):
        # Option is clicked but the trigger's selected line never changes.
        page = self._page_for_goal_selection(
            "Максимум переходов",
            "Максимум целевых действий",  # unchanged
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._set_promotion_goal(page, "max-clicks")
        self.assertIn("does not show it", str(ctx.exception))


class TestClickSave(unittest.TestCase):
    """``_click_save`` (issue #631, Этап A) — role-scoped, exact-name button match.

    ``_click_save`` uses ``get_by_role("button", name=_SAVE_BUTTON_TEXT,
    exact=True)`` (cycle-review fix: the previous ``get_by_text(exact=False)``
    risked matching an ancestor container instead of the button itself).
    """

    def test_does_not_click_a_decoy_whose_name_only_contains_the_button_text(self):
        # A decoy element whose accessible name merely CONTAINS
        # _SAVE_BUTTON_TEXT (e.g. an ancestor wrapper with extra text) must
        # NOT be treated as a match — exact=True requires exact equality.
        decoy_clicked = []
        page = FakePage(
            role_elements=[
                (
                    "button",
                    f"{browser_masters._SAVE_BUTTON_TEXT} и отмена",
                    _FakeTextLocatorHandle(
                        visible=True, on_click=lambda: decoy_clicked.append(True)
                    ),
                )
            ],
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters._click_save(page, 42)
        self.assertEqual(decoy_clicked, [])

    def test_clicks_the_exact_match_button(self):
        clicks = []
        page = FakePage(
            role_elements=[
                (
                    "button",
                    browser_masters._SAVE_BUTTON_TEXT,
                    _FakeTextLocatorHandle(
                        visible=True, on_click=lambda: clicks.append(True)
                    ),
                )
            ],
        )

        browser_masters._click_save(page, 42)

        self.assertEqual(clicks, [True])


class TestUpdateMaster(unittest.TestCase):
    """``update_master`` (issue #631, Этап A) — partial updates, one whole-form save.

    ``update_master`` now re-navigates and re-reads every requested field
    after clicking save (``_verify_saved``, cycle-review fix for "reports
    success without confirming the save actually took") — so these fakes
    model persistent mutable state (``budget_state``/``checkbox_state``)
    that BOTH the fill/check handles AND the post-reload read-back handles
    share, via ``get_value``/``get_checked`` callables. A test that wants to
    simulate "Yandex silently rejected the value" sets that shared state to
    something OTHER than what was requested, independent of what ``fill``
    was called with.
    """

    def _page_with_save_button(
        self, extra_locators=None, weekly_budget_state=None, directs_helps_state=None
    ):
        save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: save_clicks.append(True)
        )
        locators = dict(extra_locators or {})

        if weekly_budget_state is not None:
            budget_handle = _FakeLocatorHandle(
                on_fill=lambda v: weekly_budget_state.__setitem__("value", v),
                get_value=lambda: weekly_budget_state.get("value", ""),
            )
            locators[browser_masters._WEEKLY_BUDGET_INPUT_XPATH] = _FakeLocator(
                [budget_handle]
            )
        if directs_helps_state is not None:
            checkbox_handle = _FakeLocatorHandle(
                on_check=lambda v: directs_helps_state.__setitem__("checked", v),
                get_checked=lambda: directs_helps_state.get("checked", False),
            )
            locators[browser_masters._DIRECT_HELPS_CHECKBOX_XPATH] = _FakeLocator(
                [checkbox_handle]
            )

        page = FakePage(
            locators=locators,
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )
        return page, save_clicks

    def test_updates_only_weekly_budget(self):
        budget_state = {}
        page, save_clicks = self._page_with_save_button(
            weekly_budget_state=budget_state
        )

        result = browser_masters.update_master(page, 107707079, weekly_budget=95000)

        self.assertEqual(budget_state["value"], "95000")
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(result, {"CampaignId": 107707079, "WeeklyBudget": 95000})
        self.assertEqual(
            page.navigated_to,
            [
                browser_masters.WIZARD_EDIT_URL.format(campaign_id=107707079),
                browser_masters.WIZARD_EDIT_URL.format(campaign_id=107707079),
            ],
        )

    def test_updates_only_directs_helps(self):
        checkbox_state = {"checked": False}
        page, save_clicks = self._page_with_save_button(
            directs_helps_state=checkbox_state
        )

        result = browser_masters.update_master(page, 42, directs_helps=True)

        self.assertTrue(checkbox_state["checked"])
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(result, {"CampaignId": 42, "DirectsHelps": True})

    def test_updates_multiple_fields_in_one_call(self):
        budget_state = {}
        checkbox_state = {"checked": False}
        page, save_clicks = self._page_with_save_button(
            weekly_budget_state=budget_state, directs_helps_state=checkbox_state
        )

        result = browser_masters.update_master(
            page, 42, weekly_budget=50000, directs_helps=False
        )

        self.assertEqual(budget_state["value"], "50000")
        self.assertFalse(checkbox_state["checked"])
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(
            result,
            {"CampaignId": 42, "WeeklyBudget": 50000, "DirectsHelps": False},
        )

    def test_raises_value_error_when_no_field_provided(self):
        page = FakePage()

        with self.assertRaises(ValueError):
            browser_masters.update_master(page, 42)

    def test_does_not_click_save_when_field_setter_fails(self):
        # No locator registered for the budget field -> _set_weekly_budget
        # raises before _click_save is ever reached.
        page, save_clicks = self._page_with_save_button()

        with self.assertRaises(BrowserSessionError):
            browser_masters.update_master(page, 42, weekly_budget=1000)

        self.assertEqual(save_clicks, [])

    def test_raises_when_save_button_missing(self):
        page = FakePage(
            locators={
                browser_masters._WEEKLY_BUDGET_INPUT_XPATH: _FakeLocator(
                    [_FakeLocatorHandle(get_value=lambda: "1000")]
                )
            },
            role_elements=[],
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters.update_master(page, 42, weekly_budget=1000)

    def test_raises_when_saved_value_does_not_match_requested(self):
        # Save button is clicked, but the reload shows the OLD budget still
        # in place (e.g. Yandex silently rejected the value) — this must be
        # reported as a hard error, not a false success.
        budget_state = {"value": "80000"}  # never actually updated to 95000
        save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: save_clicks.append(True)
        )
        budget_handle = _FakeLocatorHandle(
            on_fill=lambda v: None,  # the fill "succeeds" but doesn't persist
            get_value=lambda: budget_state["value"],
        )
        page = FakePage(
            locators={
                browser_masters._WEEKLY_BUDGET_INPUT_XPATH: _FakeLocator(
                    [budget_handle]
                )
            },
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(page, 42, weekly_budget=95000)

        self.assertEqual(len(save_clicks), 1)  # save WAS clicked
        self.assertIn("did not save as requested", str(ctx.exception))

    def test_raises_when_saved_directs_helps_does_not_match_requested(self):
        checkbox_state = {"checked": False}  # never actually flips to True
        save_handle = _FakeTextLocatorHandle(visible=True)
        checkbox_handle = _FakeLocatorHandle(
            on_check=lambda v: None,
            get_checked=lambda: checkbox_state["checked"],
        )
        page = FakePage(
            locators={
                browser_masters._DIRECT_HELPS_CHECKBOX_XPATH: _FakeLocator(
                    [checkbox_handle]
                )
            },
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(page, 42, directs_helps=True)
        self.assertIn("did not save as requested", str(ctx.exception))

    def test_raises_when_saved_promotion_goal_does_not_match_requested(self):
        # The goal setter's own post-click check passes (trigger text
        # updates immediately), but the post-save reload shows the OLD
        # goal still selected -- _verify_saved must still catch this. The
        # trigger's inner_text() is modeled as two lines (static label +
        # selection), matching the live-confirmed shape.
        trigger_texts = iter(
            [
                "Цель продвижения\nМаксимум переходов",
                "Цель продвижения\nМаксимум целевых действий",
            ]
        )
        trigger = _FakeLocatorHandle(text="Цель продвижения")
        trigger.inner_text = lambda: next(trigger_texts)
        save_handle = _FakeTextLocatorHandle(visible=True)
        page = FakePage(
            locators={
                browser_masters._PROMOTION_GOAL_BUTTON_XPATH: _FakeLocator([trigger])
            },
            role_elements=[
                ("option", "Максимум переходов", _FakeTextLocatorHandle(visible=True)),
                ("button", browser_masters._SAVE_BUTTON_TEXT, save_handle),
            ],
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(page, 42, promotion_goal="max-clicks")
        self.assertIn("did not save as requested", str(ctx.exception))


class TestMastersUpdateCommand(unittest.TestCase):
    """CLI wiring for `masters update` (issue #631, Этап A)."""

    def setUp(self):
        self.runner = CliRunner()

    def test_registered(self):
        result = self.runner.invoke(cli, ["masters", "update", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_has_no_login_option(self):
        result = self.runner.invoke(cli, ["masters", "update", "--help"])
        self.assertNotIn("--login", result.output)

    def test_documents_stage_a_flags(self):
        result = self.runner.invoke(cli, ["masters", "update", "--help"])
        self.assertIn("--weekly-budget", result.output)
        self.assertIn("--promotion-goal", result.output)
        self.assertIn("--directs-helps", result.output)

    def test_calls_update_master_with_given_fields(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42, "WeeklyBudget": 95000}
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--weekly-budget", "95000"]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        mock_update.assert_called_once()
        args, kwargs = mock_update.call_args
        self.assertEqual(args[1], 42)
        self.assertEqual(kwargs["weekly_budget"], 95000)
        self.assertIsNone(kwargs["promotion_goal"])
        self.assertIsNone(kwargs["directs_helps"])

    def test_passes_promotion_goal_choice(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli,
                ["masters", "update", "42", "--promotion-goal", "max-clicks"],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_update.call_args.kwargs["promotion_goal"], "max-clicks")

    def test_rejects_unknown_promotion_goal(self):
        result = self.runner.invoke(
            cli, ["masters", "update", "42", "--promotion-goal", "bogus"]
        )
        self.assertNotEqual(result.exit_code, 0)

    def test_passes_directs_helps_flag(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--directs-helps"]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(mock_update.call_args.kwargs["directs_helps"])

    def test_passes_no_directs_helps_flag(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--no-directs-helps"]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertFalse(mock_update.call_args.kwargs["directs_helps"])

    def test_errors_when_no_field_given(self):
        result = self.runner.invoke(cli, ["masters", "update", "42"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("at least one", result.output)

    def test_does_not_call_update_master_when_no_field_given(self):
        with patch("direct_cli.browser.masters.update_master") as mock_update:
            self.runner.invoke(cli, ["masters", "update", "42"])
        mock_update.assert_not_called()


class TestMastersLoginCommand(unittest.TestCase):
    """CLI wiring for `masters login` (issue #635)."""

    def setUp(self):
        self.runner = CliRunner()
        # CliRunner supplies a non-tty stdin, so `login` would refuse to run
        # (it needs a human). Every test here exercises the interactive path;
        # the non-interactive refusal has its own test that overrides this.
        tty = patch(
            "direct_cli.commands.masters._stdin_is_interactive", return_value=True
        )
        tty.start()
        self.addCleanup(tty.stop)

    def test_login_registered(self):
        result = self.runner.invoke(cli, ["masters", "login", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_login_fails_fast_in_a_non_interactive_environment(self):
        """In CI/a script, fail immediately instead of blocking for the timeout.

        Issue #635 (Риски → Интерактивность): the command waits for a human, so
        run non-interactively it must "падать сразу с понятным текстом, а не
        висеть" — otherwise CI hangs for the full --timeout on a browser window
        nobody can see.
        """
        with patch("direct_cli.browser.session.login_persistent_session") as login_fn:
            with patch(
                "direct_cli.commands.masters._stdin_is_interactive",
                return_value=False,
            ):
                result = self.runner.invoke(cli, ["masters", "login"])

        login_fn.assert_not_called()
        self.assertNotEqual(result.exit_code, 0, result.output)
        self.assertIn("interactive", result.output.lower())

    def test_login_has_no_output_format_options(self):
        # login is interactive/side-effecting, not a data-fetching command --
        # it has no --format/--output, unlike list/get/suspend/resume.
        result = self.runner.invoke(cli, ["masters", "login", "--help"])
        self.assertNotIn("--format", result.output)

    def test_login_calls_login_persistent_session(self):
        with patch("direct_cli.browser.session.login_persistent_session") as mock_login:
            result = self.runner.invoke(cli, ["masters", "login"])

        self.assertEqual(result.exit_code, 0, result.output)
        mock_login.assert_called_once()
        _, kwargs = mock_login.call_args
        self.assertEqual(kwargs["timeout_ms"], 300_000)
        self.assertIsNone(kwargs["profile_dir"])

    def test_login_passes_explicit_profile_dir_and_timeout(self):
        with patch("direct_cli.browser.session.login_persistent_session") as mock_login:
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "login",
                    "--profile-dir",
                    "/custom/profile",
                    "--timeout",
                    "30",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        _, kwargs = mock_login.call_args
        self.assertEqual(kwargs["profile_dir"], Path("/custom/profile"))
        self.assertEqual(kwargs["timeout_ms"], 30_000)

    def test_login_converts_browser_session_error_to_click_exception(self):
        from direct_cli.browser.session import BrowserAuthError

        with patch(
            "direct_cli.browser.session.login_persistent_session",
            side_effect=BrowserAuthError("timed out"),
        ):
            result = self.runner.invoke(cli, ["masters", "login"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("timed out", result.output)

    def test_login_missing_playwright_raises_usage_error(self):
        with patch.dict(
            "sys.modules", {"playwright": None, "playwright.sync_api": None}
        ):
            result = self.runner.invoke(cli, ["masters", "login"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("playwright", result.output.lower())


class TestMastersLogoutCommand(unittest.TestCase):
    """CLI wiring for `masters logout` (issue #635 risk: revocation)."""

    def setUp(self):
        self.runner = CliRunner()
        import tempfile

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.profile_dir = Path(self._tmpdir.name) / "chrome-profile"

        # Keep the login pointer off the developer's real ~/.direct-cli.
        pointer = patch(
            "direct_cli.browser.session.PROFILE_POINTER_PATH",
            Path(self._tmpdir.name) / "chrome-profile-path",
        )
        pointer.start()
        self.addCleanup(pointer.stop)

    def _make_profile(self):
        """Create a profile dir the way `masters login` does — marker included."""
        from direct_cli.browser.session import PROFILE_MARKER_NAME

        self.profile_dir.mkdir(parents=True)
        (self.profile_dir / PROFILE_MARKER_NAME).touch()

    def test_logout_registered(self):
        result = self.runner.invoke(cli, ["masters", "logout", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_logout_deletes_existing_profile(self):
        self._make_profile()
        (self.profile_dir / "Cookies").write_text("fake")

        result = self.runner.invoke(
            cli, ["masters", "logout", "--profile-dir", str(self.profile_dir)]
        )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertFalse(self.profile_dir.exists())

    def test_logout_is_a_noop_warning_when_no_profile_exists(self):
        result = self.runner.invoke(
            cli, ["masters", "logout", "--profile-dir", str(self.profile_dir)]
        )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertFalse(self.profile_dir.exists())

    def test_logout_uses_default_persistent_profile_dir_when_unset(self):
        with patch(
            "direct_cli.browser.session.DEFAULT_PERSISTENT_PROFILE_DIR",
            self.profile_dir,
        ):
            self._make_profile()
            result = self.runner.invoke(cli, ["masters", "logout"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertFalse(self.profile_dir.exists())

    def test_logout_refuses_a_directory_it_did_not_create(self):
        """`--profile-dir` pointing at an unrelated directory must not be deleted.

        Codex review finding on PR #644: `logout` passes whatever `--profile-dir`
        resolves to straight into `shutil.rmtree`, with no check that the target
        is actually a profile this CLI created. A typo or a shell-expanded `.`
        therefore recursively deletes an arbitrary tree.

        `shutil.rmtree` is patched, so this test never deletes anything for real —
        it only records the path the command *would* have destroyed.
        """
        victim = Path(self._tmpdir.name) / "not-a-profile"
        victim.mkdir(parents=True)
        (victim / "important.txt").write_text("user data")

        with patch("shutil.rmtree") as rmtree:
            result = self.runner.invoke(
                cli, ["masters", "logout", "--profile-dir", str(victim)]
            )

        rmtree.assert_not_called()
        self.assertNotEqual(result.exit_code, 0, result.output)
        self.assertTrue(victim.exists())

    def test_logout_refuses_a_symlinked_profile_dir(self):
        """A symlink would let rmtree escape the directory the user named."""
        self._make_profile()
        link = Path(self._tmpdir.name) / "link-to-profile"
        link.symlink_to(self.profile_dir, target_is_directory=True)

        with patch("shutil.rmtree") as rmtree:
            result = self.runner.invoke(
                cli, ["masters", "logout", "--profile-dir", str(link)]
            )

        rmtree.assert_not_called()
        self.assertNotEqual(result.exit_code, 0, result.output)
        self.assertTrue(self.profile_dir.exists())

    def test_logout_explicit_profile_dir_does_not_clear_pointer_to_a_different_profile(
        self,
    ):
        """`logout --profile-dir A` must not wipe the pointer to a live profile B.

        `logout` unconditionally unlinks PROFILE_POINTER_PATH after deleting
        whatever `--profile-dir` resolved to. If the user logged into profile B
        (recorded by the pointer) after an older profile A, then deletes A by
        explicit path, the pointer to B — still on disk and in use — is wiped
        too. The next read then falls back to the default location instead of B.
        """
        from direct_cli.browser.session import PROFILE_MARKER_NAME

        old_profile = self.profile_dir  # profile A: about to be deleted
        self._make_profile()

        live_profile = Path(self._tmpdir.name) / "chrome-profile-b"
        live_profile.mkdir(parents=True)
        (live_profile / PROFILE_MARKER_NAME).touch()

        from direct_cli.browser import session as session_module

        session_module.remember_persistent_profile_dir(live_profile)

        result = self.runner.invoke(
            cli, ["masters", "logout", "--profile-dir", str(old_profile)]
        )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertFalse(old_profile.exists())
        self.assertTrue(live_profile.exists(), "unrelated live profile was deleted")
        self.assertEqual(
            session_module.configured_persistent_profile_dir(),
            live_profile.resolve(),
            "logout on an unrelated profile cleared the pointer to the live one",
        )


class TestCaptchaDetection(unittest.TestCase):
    def test_assert_not_captcha_raises_on_gate_markers(self):
        from direct_cli.browser.session import assert_not_captcha

        for marker_html in (
            "<html>showCaptcha(...)</html>",
            "<script>smartCaptcha.render()</script>",
            "<title>Captcha</title>",
        ):
            with self.assertRaises(BrowserCaptchaError):
                assert_not_captcha(marker_html)

    def test_assert_not_captcha_passes_on_real_content(self):
        from direct_cli.browser.session import assert_not_captcha

        # Must not raise.
        assert_not_captcha("<html><body>Кампания остановлена</body></html>")

    def test_fetch_masters_list_raises_on_captcha_page(self):
        # A live SmartCaptcha gate is served as an ordinary 200 HTML page, so
        # page.goto() itself never raises — fetch_masters_list must check the
        # rendered content and surface BrowserCaptchaError explicitly, per
        # issue #628 risk item 5 ("не молча падать" — never fail silently).
        page = FakePage(locators={}, html="<title>Captcha</title>")

        with self.assertRaises(BrowserCaptchaError):
            browser_masters.fetch_masters_list(page)

    def test_fetch_master_raises_on_captcha_page(self):
        page = FakePage(locators={}, html="<script>smartCaptcha.render()</script>")

        with self.assertRaises(BrowserCaptchaError):
            browser_masters.fetch_master(page, 1)


class TestAuthDetection(unittest.TestCase):
    """#634: decrypted cookies can still represent an expired/wrong session —
    detect Yandex's login page explicitly instead of relying on a timeout."""

    def test_assert_authenticated_raises_on_login_page(self):
        from direct_cli.browser.session import BrowserAuthError, assert_authenticated

        for marker_html in (
            "<html>redirecting to passport.yandex.ru/auth?...</html>",
            "<body>Войдите с Яндекс ID</body>",
        ):
            with self.assertRaises(BrowserAuthError):
                assert_authenticated(marker_html)

    def test_assert_authenticated_passes_on_real_content(self):
        from direct_cli.browser.session import assert_authenticated

        # Must not raise.
        assert_authenticated("<html><body>Кампания остановлена</body></html>")

    def test_fetch_masters_list_raises_on_login_page(self):
        page = FakePage(locators={}, html="<body>Войдите с Яндекс ID</body>")
        from direct_cli.browser.session import BrowserAuthError

        with self.assertRaises(BrowserAuthError):
            browser_masters.fetch_masters_list(page)

    def test_fetch_master_raises_on_login_page(self):
        page = FakePage(locators={}, html="<body>Войдите с Яндекс ID</body>")
        from direct_cli.browser.session import BrowserAuthError

        with self.assertRaises(BrowserAuthError):
            browser_masters.fetch_master(page, 1)

    def test_fetch_masters_list_waits_for_domcontentloaded_not_networkidle(self):
        # #634: networkidle never settles on Yandex's login page (it holds
        # long-poll connections), which is what turned an auth failure into
        # an opaque 30s timeout instead of a clear error. Guard against a
        # silent regression back to networkidle. (No captured grid response
        # here -> raises BrowserSessionError right after the goto assertion,
        # which is all this test needs to observe.)
        page = FakePage(locators={})
        with self.assertRaises(BrowserSessionError):
            browser_masters.fetch_masters_list(page)
        self.assertEqual(page.goto_wait_until, "domcontentloaded")

    def test_fetch_master_waits_for_domcontentloaded_not_networkidle(self):
        page = FakePage(locators={})
        browser_masters.fetch_master(page, 1)
        self.assertEqual(page.goto_wait_until, "domcontentloaded")


class TestBrowserSessionErrors(unittest.TestCase):
    def test_browser_captcha_error_is_a_browser_session_error(self):
        self.assertTrue(issubclass(BrowserCaptchaError, BrowserSessionError))

    def test_browser_auth_error_is_a_browser_session_error(self):
        from direct_cli.browser.session import BrowserAuthError

        self.assertTrue(issubclass(BrowserAuthError, BrowserSessionError))

    def test_chrome_cookie_error_is_a_browser_session_error(self):
        from direct_cli.browser.session import ChromeCookieError

        self.assertTrue(issubclass(ChromeCookieError, BrowserSessionError))


if __name__ == "__main__":
    unittest.main()
