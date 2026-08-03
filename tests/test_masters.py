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
from unittest.mock import Mock, patch

import click
import pytest
from click.testing import CliRunner

from direct_cli.browser import masters as browser_masters
from direct_cli.browser.masters import PlaywrightError
from direct_cli.browser.session import (
    BrowserAuthError,
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

    ``click``/``fill``/``check``/``uncheck``/``press``/``is_visible`` support
    ``update_master``'s ``_set_*`` functions (issue #631) and
    ``create_master``'s private helpers (issue #632) — ``on_click``/
    ``on_fill``/``on_check``/``on_press`` are optional no-arg/one-arg
    callbacks so tests can model the fake page's mutable state changing
    (mirrors ``_FakeTextLocatorHandle.on_click`` used by suspend/resume
    tests). ``input_value``/``is_checked`` support the post-save/post-create
    read-back verification in ``_verify_saved``/``_verify_created`` — they
    read the SAME mutable ``checked``/``value`` state ``fill``/``check``/
    ``uncheck`` write, via ``state`` dict callables (``get_value``/
    ``get_checked``), so a test can model "the reload shows what was
    actually saved" instead of "whatever was passed to fill/check".
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
        on_press=None,
        get_value=None,
        get_checked=None,
        on_upload=None,
    ):
        self._text = text
        self._attrs = attrs or {}
        self._raises = raises
        self._visible = visible
        self._on_click = on_click
        self._on_fill = on_fill
        self._on_check = on_check
        self._on_press = on_press
        self._get_value = get_value
        self._get_checked = get_checked
        self._on_upload = on_upload

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

    def click(self, timeout=None):
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

    def type(self, value, delay=None):  # noqa: A003 - mirrors Playwright's Locator.type
        # Same fake behaviour as fill() — _fill_landing_url uses type()
        # instead of fill() because the real element is a contenteditable
        # <div>, not an <input>/<textarea> (issue #650), but the fake only
        # needs to record what was entered.
        self.fill(value)

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

    def press(self, key):
        if self._raises:
            raise PlaywrightError("element detached")
        if self._on_press is not None:
            self._on_press(key)

    def input_value(self):
        if self._raises:
            raise PlaywrightError("element detached")
        return self._get_value() if self._get_value is not None else self._text

    def is_checked(self):
        if self._raises:
            raise PlaywrightError("element detached")
        return self._get_checked() if self._get_checked is not None else False

    def count(self):
        # Playwright's `Locator.first` is itself a Locator, so `.first.count()`
        # is legal and answers "did the selector match anything?" — 0 when it
        # matched nothing (which is what `raises=True` models here, since
        # `_FakeLocator.first` hands back a raising handle for an empty match),
        # 1 otherwise. `_set_region` uses exactly this to decide whether the
        # region popup is already open before clicking the launcher again.
        return 0 if self._raises else 1

    def set_input_files(self, path):
        # Models Playwright's Locator.set_input_files() on the image manager
        # modal's hidden <input type="file"> (issue #670, Этап D) — a fake
        # test supplies ``on_upload`` to mutate whatever shared state models
        # "a new image now appears in the modal's selected panel".
        if self._raises:
            raise PlaywrightError("element detached")
        if self._on_upload is not None:
            self._on_upload(path)


class _FakeContentEditableHandle(_FakeLocatorHandle):
    """A slot that models the REAL contenteditable semantics (issue #655 review).

    ``_FakeLocatorHandle.type()`` delegates to ``fill()``, which REPLACES the
    field's content — real ``Locator.type()`` on a ``contenteditable``
    APPENDS from the caret, which is the entire reason ``_clear_text_field``
    exists. A fake that replaces cannot observe a missing/failed clear, so it
    silently passes code that would splice the caller's value into Yandex's
    AI-generated copy (or leave that copy in place entirely).

    ``supports_modifier`` models Playwright <1.44, where ``ControlOrMeta`` is
    rejected server-side with ``Unknown modifier`` — the failure mode that
    makes the suppressed clear a no-op on the versions ``pyproject.toml``
    permits.
    """

    def __init__(self, *args, supports_modifier=True, **kwargs):
        super().__init__(*args, **kwargs)
        self._supports_modifier = supports_modifier
        self._selected_all = False

    def type(self, value, delay=None):  # noqa: A003 - mirrors Locator.type
        if self._raises:
            raise PlaywrightError("element detached")
        # APPEND, exactly like the real contenteditable.
        self._text = self._text + value
        if self._on_fill is not None:
            self._on_fill(value)

    def press(self, key):
        if self._raises:
            raise PlaywrightError("element detached")
        if key == "ControlOrMeta+a":
            if not self._supports_modifier:
                # Playwright <1.44 throws this from input.ts, server-side.
                raise PlaywrightError("Unknown modifier ControlOrMeta")
            self._selected_all = True
        elif key == "Backspace" and self._selected_all:
            self._text = ""
            self._selected_all = False
        if self._on_press is not None:
            self._on_press(key)


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
        # Mutated by goto() and settable directly by a test's on_click
        # callback to simulate Yandex's post-click redirect (see
        # TestCopyMaster) — copy_master polls this the same way
        # archive_master polls fetch_masters_list.
        self.url = ""
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
        self.url = url

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


class TestCopyMaster(unittest.TestCase):
    """``copy_master`` (issue #659): click Клонировать, then the clone form's

    terminal button, verified via both the post-click URL redirect and the
    campaigns grid — live-verified end to end (see module docstring, campaign
    107707079 -> draft copy 713231614).
    """

    SOURCE_ID = 42
    NEW_ID = 4200

    def _source_row(self, status="STOPPED"):
        return {
            "CampaignId": self.SOURCE_ID,
            "Name": "Мастер тестовый",
            "Status": status,
            "Type": "TEXT",
            "StartDate": "2025-01-01",
        }

    def _new_row(self, status="DRAFT"):
        return {
            "CampaignId": self.NEW_ID,
            "Name": "Мастер тестовый — 2",
            "Status": status,
            "Type": "TEXT",
            "StartDate": "2026-08-02",
        }

    def _page(
        self,
        menu_trigger=None,
        clone_item=None,
        region_heading=True,
        terminal_button_text=None,
        redirect_on_click=True,
    ):
        locators = {}
        if menu_trigger is not None:
            locators[browser_masters._MENU_TRIGGER_SELECTOR] = _FakeLocator(
                [menu_trigger]
            )
        if clone_item is not None:
            locators[browser_masters._CLONE_MENU_ITEM_SELECTOR] = _FakeLocator(
                [clone_item]
            )

        text_buttons = {}
        if region_heading:
            text_buttons["Регион показов"] = _FakeGetByTextLocator(
                [_FakeTextLocatorHandle()]
            )

        page = FakePage(locators=locators, text_buttons=text_buttons)

        if terminal_button_text is not None:

            def _on_terminal_click():
                if redirect_on_click:
                    page.url = browser_masters.WIZARD_OVERVIEW_URL.format(
                        campaign_id=self.NEW_ID
                    )

            page._role_elements = [
                (
                    "button",
                    terminal_button_text,
                    _FakeTextLocatorHandle(visible=True, on_click=_on_terminal_click),
                )
            ]
        return page

    def test_copies_saves_as_draft_by_default_and_verifies(self):
        page = self._page(
            menu_trigger=_FakeLocatorHandle(),
            clone_item=_FakeLocatorHandle(),
            terminal_button_text=browser_masters._SAVE_DRAFT_BUTTON_TEXT,
        )

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            side_effect=lambda page, status="all": [
                self._source_row(),
                self._new_row(),
            ],
        ):
            result = browser_masters.copy_master(page, self.SOURCE_ID)

        self.assertEqual(result["SourceCampaignId"], self.SOURCE_ID)
        self.assertEqual(result["CampaignId"], self.NEW_ID)
        self.assertEqual(result["Status"], "DRAFT")
        self.assertFalse(result["Launched"])
        self.assertEqual(
            page.navigated_to[0],
            browser_masters.WIZARD_OVERVIEW_URL.format(campaign_id=self.SOURCE_ID),
        )

    def test_launch_true_clicks_launch_button(self):
        page = self._page(
            menu_trigger=_FakeLocatorHandle(),
            clone_item=_FakeLocatorHandle(),
            terminal_button_text=browser_masters._LAUNCH_BUTTON_TEXT,
        )

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            side_effect=lambda page, status="all": [
                self._source_row(),
                self._new_row(status="ACTIVE"),
            ],
        ):
            result = browser_masters.copy_master(page, self.SOURCE_ID, launch=True)

        self.assertTrue(result["Launched"])
        self.assertEqual(result["Status"], "ACTIVE")

    def test_raises_when_source_campaign_not_found(self):
        page = self._page()

        with patch("direct_cli.browser.masters.fetch_masters_list", return_value=[]):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.copy_master(page, self.SOURCE_ID)

        self.assertIn("Could not find", str(ctx.exception))

    def test_raises_when_menu_trigger_not_found(self):
        page = self._page()  # no menu_trigger locator registered

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            return_value=[self._source_row()],
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.copy_master(page, self.SOURCE_ID)

        self.assertIn("Could not open the campaign menu", str(ctx.exception))

    def test_raises_when_clone_menu_item_not_found(self):
        page = self._page(menu_trigger=_FakeLocatorHandle())

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            return_value=[self._source_row()],
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.copy_master(page, self.SOURCE_ID)

        self.assertIn("Клонировать", str(ctx.exception))

    def test_raises_when_no_redirect_after_terminal_click(self):
        # The terminal button is clicked but Yandex never redirects -- must
        # not report success on the click alone (not idempotent, so a false
        # success here is expensive to clean up).
        page = self._page(
            menu_trigger=_FakeLocatorHandle(),
            clone_item=_FakeLocatorHandle(),
            terminal_button_text=browser_masters._SAVE_DRAFT_BUTTON_TEXT,
            redirect_on_click=False,
        )

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            return_value=[self._source_row()],
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.copy_master(page, self.SOURCE_ID)

        self.assertIn("did not redirect", str(ctx.exception))

    def test_raises_when_new_campaign_never_appears_in_grid(self):
        # The redirect happens (page.url changes) but the grid never reports
        # the new campaign -- must not trust the URL alone either.
        page = self._page(
            menu_trigger=_FakeLocatorHandle(),
            clone_item=_FakeLocatorHandle(),
            terminal_button_text=browser_masters._SAVE_DRAFT_BUTTON_TEXT,
        )

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            return_value=[self._source_row()],  # never includes NEW_ID
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.copy_master(page, self.SOURCE_ID)

        self.assertIn("did not appear in the campaigns grid", str(ctx.exception))

    def test_auth_error_during_post_click_verification_is_not_retried(self):
        # The clone/terminal-button click has ALREADY happened (irreversible,
        # not idempotent) by the time verification runs. If the saved session
        # is invalidated exactly in that window, fetch_masters_list's own
        # assert_authenticated raises BrowserAuthError -- which _with_session
        # (direct_cli/commands/masters.py) would otherwise catch and retry
        # the WHOLE copy_master call under a fresh session, re-clicking
        # Клонировать and the terminal button and creating a SECOND copy (or,
        # with --launch, a second live campaign spending real budget). This
        # must surface as a plain BrowserSessionError (not BrowserAuthError),
        # so _with_session's retry-on-BrowserAuthError does not fire, and the
        # error message must reference NEW_ID so the caller can check
        # manually instead of losing track of the clone that already exists.
        page = self._page(
            menu_trigger=_FakeLocatorHandle(),
            clone_item=_FakeLocatorHandle(),
            terminal_button_text=browser_masters._SAVE_DRAFT_BUTTON_TEXT,
        )

        calls = []

        def _fetch_masters_list(page, status="all"):
            # First call (before the click) looks up the source campaign and
            # must succeed; only the post-click lookup (finding new_id) hits
            # the invalidated session.
            calls.append(status)
            if len(calls) == 1:
                return [self._source_row()]
            raise BrowserAuthError("stale session, detected mid-body")

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            side_effect=_fetch_masters_list,
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.copy_master(page, self.SOURCE_ID)

        self.assertNotIsInstance(ctx.exception, BrowserAuthError)
        self.assertIn(str(self.NEW_ID), str(ctx.exception))


class TestMastersCopyCommand(unittest.TestCase):
    """CLI wiring for `masters copy` (issue #659)."""

    def setUp(self):
        self.runner = CliRunner()

    def test_copy_registered(self):
        result = self.runner.invoke(cli, ["masters", "copy", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_copy_has_no_login_option(self):
        result = self.runner.invoke(cli, ["masters", "copy", "--help"])
        self.assertNotIn("--login", result.output)

    def test_copy_defaults_to_draft(self):
        with (
            patch("direct_cli.browser.masters.copy_master") as mock_copy,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_copy.return_value = {"CampaignId": 99, "SourceCampaignId": 42}
            result = self.runner.invoke(cli, ["masters", "copy", "42"])

        self.assertEqual(result.exit_code, 0, result.output)
        mock_copy.assert_called_once_with(mock_copy.call_args[0][0], 42, launch=False)

    def test_copy_launch_flag_passes_through(self):
        with (
            patch("direct_cli.browser.masters.copy_master") as mock_copy,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_copy.return_value = {"CampaignId": 99, "SourceCampaignId": 42}
            result = self.runner.invoke(cli, ["masters", "copy", "42", "--launch"])

        self.assertEqual(result.exit_code, 0, result.output)
        mock_copy.assert_called_once_with(mock_copy.call_args[0][0], 42, launch=True)


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


class TestDraftEditPageSave(unittest.TestCase):
    """``_is_draft_edit_page``/``_click_save`` DRAFT path (issue #668).

    A DRAFT campaign's edit page has NO "Сохранить кампанию" button at all
    — only ``CampaignFormControls.saveDraft.button``/``.save.button``, the
    latter labelled "Запустить кампанию" (publishes) here, unlike the
    non-DRAFT page's "Сохранить кампанию" — live-confirmed against campaign
    713231614, see the module docstring's "DRAFT support" note.
    """

    def test_is_draft_edit_page_true_when_save_draft_button_present(self):
        page = FakePage(
            locators={
                browser_masters._DRAFT_SAVE_DRAFT_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                )
            }
        )

        self.assertTrue(browser_masters._is_draft_edit_page(page))

    def test_is_draft_edit_page_false_when_absent(self):
        page = FakePage(locators={})

        self.assertFalse(browser_masters._is_draft_edit_page(page))

    def test_click_save_on_draft_clicks_save_draft_button_by_default(self):
        clicks = []
        page = FakePage(
            locators={
                browser_masters._DRAFT_SAVE_DRAFT_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(on_click=lambda: clicks.append("draft"))]
                ),
                browser_masters._DRAFT_LAUNCH_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(on_click=lambda: clicks.append("launch"))]
                ),
            }
        )

        browser_masters._click_save(page, 713231614)

        # The publish button must never be touched unless --launch was
        # explicitly requested.
        self.assertEqual(clicks, ["draft"])

    def test_click_save_on_draft_clicks_launch_button_when_requested(self):
        clicks = []
        page = FakePage(
            locators={
                browser_masters._DRAFT_SAVE_DRAFT_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(on_click=lambda: clicks.append("draft"))]
                ),
                browser_masters._DRAFT_LAUNCH_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(on_click=lambda: clicks.append("launch"))]
                ),
            }
        )

        browser_masters._click_save(page, 713231614, launch=True)

        self.assertEqual(clicks, ["launch"])

    def test_click_save_on_draft_raises_when_button_missing(self):
        page = FakePage(
            locators={
                browser_masters._DRAFT_SAVE_DRAFT_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                )
                # _DRAFT_LAUNCH_BUTTON_TESTID deliberately absent.
            }
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters._click_save(page, 713231614, launch=True)

    def test_click_save_prefers_non_draft_path_when_save_draft_button_absent(self):
        # Regression guard: a non-DRAFT page must keep using the plain
        # "Сохранить кампанию" role-scoped match, not the DRAFT testid path.
        clicks = []
        page = FakePage(
            locators={},
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


class TestUpdateMasterDraftSupport(unittest.TestCase):
    """``update_master`` end to end on a DRAFT campaign (issue #668)."""

    def _draft_page_with_headline_slot(self, *, saved_text_after_save):
        # _verify_saved re-navigates to the SAME edit URL after saving —
        # FakePage's goto() is a no-op that just records the URL, so the
        # same locator objects (and their mutable state) are seen both
        # before and after the "reload", exactly like the non-DRAFT
        # TestUpdateMaster fakes above.
        #
        # _click_draft_terminal_button (issue #668 live-recon fix) polls
        # page.url until it leaves "/edit/" before returning, mirroring the
        # click's real ~5s redirect to the overview page — on_click here
        # mutates page.url the same way TestCopyMaster's fakes do, so the
        # poll resolves immediately instead of burning the real timeout.
        slot = _FakeContentEditableHandle(text="Старый заголовок")
        draft_clicks = []
        selector = (
            f"[data-testid="
            f'"{browser_masters._HEADLINES_TESTID_TEMPLATE.format(index=0)}"]'
        )

        def _on_draft_click():
            draft_clicks.append(True)
            page.url = browser_masters.WIZARD_OVERVIEW_URL.format(campaign_id=713231614)

        page = FakePage(
            locators={
                browser_masters._DRAFT_SAVE_DRAFT_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(on_click=_on_draft_click)]
                ),
                selector: _FakeLocator([slot]),
            }
        )
        page.url = browser_masters.WIZARD_EDIT_URL.format(campaign_id=713231614)
        return page, slot, draft_clicks

    def test_updates_headline_on_draft_campaign_saving_as_draft(self):
        page, slot, draft_clicks = self._draft_page_with_headline_slot(
            saved_text_after_save="Новый заголовок"
        )

        result = browser_masters.update_master(
            page, 713231614, headlines={0: "Новый заголовок"}
        )

        self.assertEqual(slot.inner_text(), "Новый заголовок")
        self.assertEqual(len(draft_clicks), 1)
        self.assertEqual(
            result, {"CampaignId": 713231614, "Headlines": {0: "Новый заголовок"}}
        )

    def test_error_message_on_draft_mismatch_names_the_draft_button_not_save(self):
        # The mismatch error text must reflect the button THIS run actually
        # clicked, not a hard-coded "Сохранить кампанию" that was never on
        # the page.
        slot = _FakeContentEditableHandle(text="Старый заголовок")
        slot.type = lambda value, delay=None: None  # write silently rejected
        selector = (
            f"[data-testid="
            f'"{browser_masters._HEADLINES_TESTID_TEMPLATE.format(index=0)}"]'
        )

        def _on_draft_click():
            page.url = browser_masters.WIZARD_OVERVIEW_URL.format(campaign_id=713231614)

        page = FakePage(
            locators={
                browser_masters._DRAFT_SAVE_DRAFT_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(on_click=_on_draft_click)]
                ),
                selector: _FakeLocator([slot]),
            }
        )
        page.url = browser_masters.WIZARD_EDIT_URL.format(campaign_id=713231614)

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(
                page, 713231614, headlines={0: "Новый заголовок"}
            )

        self.assertIn(
            f"'{browser_masters._SAVE_DRAFT_BUTTON_TEXT}'", str(ctx.exception)
        )
        self.assertNotIn(browser_masters._SAVE_BUTTON_TEXT, str(ctx.exception))


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
        self,
        extra_locators=None,
        weekly_budget_state=None,
        directs_helps_state=None,
        name_state=None,
        headlines_state=None,
        texts_state=None,
    ):
        save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: save_clicks.append(True)
        )
        locators = dict(extra_locators or {})
        headline_handles = {}
        text_handles = {}

        def _add_repeating_slot_locators(state, testid_template, slot_count, out):
            # ``state`` maps 0-based index -> starting text, pre-populated
            # by the test with whatever the fake edit page starts showing
            # (a real slot is either filled or empty; ``_set_repeating_value``
            # refuses to write to an empty one, mirroring the live page).
            #
            # FakePage reuses the SAME handle object across both goto()
            # calls inside one update_master() run (save, then the
            # post-save reload), just like the real page keeps rendering
            # the same slot — so a plain _FakeContentEditableHandle's own
            # mutable ``_text`` already carries the mutation
            # ``_set_repeating_value`` made into ``_verify_saved``'s re-read.
            # ``out`` hands the handles back to the caller so a test can
            # assert on ``handle.inner_text()`` directly.
            for index in range(slot_count):
                selector = f'[data-testid="{testid_template.format(index=index)}"]'
                handle = _FakeContentEditableHandle(text=state.get(index, ""))
                locators[selector] = _FakeLocator([handle])
                out[index] = handle

        if headlines_state is not None:
            _add_repeating_slot_locators(
                headlines_state,
                browser_masters._HEADLINES_TESTID_TEMPLATE,
                browser_masters._HEADLINES_SLOT_COUNT,
                headline_handles,
            )
        if texts_state is not None:
            _add_repeating_slot_locators(
                texts_state,
                browser_masters._TEXTS_TESTID_TEMPLATE,
                browser_masters._TEXTS_SLOT_COUNT,
                text_handles,
            )

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
        if name_state is not None:
            # The rename modal's "Применить" only updates the header's
            # optimistic state on click -- the header handle's own text is
            # what _read_campaign_name reads back after a reload, so
            # on_fill here writes to the SAME state _read_campaign_name's
            # get_value reads, mirroring the budget/checkbox pattern above.
            edit_button_handle = _FakeLocatorHandle()
            name_input_handle = _FakeLocatorHandle(
                on_fill=lambda v: name_state.__setitem__("value", v),
                get_value=lambda: name_state.get("value", ""),
            )
            accept_handle = _FakeLocatorHandle()
            header_handle = _FakeLocatorHandle()
            header_handle.inner_text = lambda: name_state.get("value", "")
            locators[browser_masters._EDIT_NAME_BUTTON_SELECTOR] = _FakeLocator(
                [edit_button_handle]
            )
            locators[browser_masters._NAME_MODAL_INPUT_SELECTOR] = _FakeLocator(
                [name_input_handle]
            )
            locators[browser_masters._NAME_MODAL_ACCEPT_SELECTOR] = _FakeLocator(
                [accept_handle]
            )
            locators[browser_masters._NAME_HEADER_SELECTOR] = _FakeLocator(
                [header_handle]
            )

        page = FakePage(
            locators=locators,
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )
        # Attached rather than returned as extra tuple elements, so the
        # many existing ``page, save_clicks = ...`` two-value call sites
        # above don't all need updating for this one new capability.
        page.headline_handles = headline_handles
        page.text_handles = text_handles
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

    def test_updates_only_name(self):
        name_state = {}
        page, save_clicks = self._page_with_save_button(name_state=name_state)

        result = browser_masters.update_master(page, 42, name="Новое имя")

        self.assertEqual(name_state["value"], "Новое имя")
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(result, {"CampaignId": 42, "Name": "Новое имя"})

    def test_updates_name_together_with_weekly_budget(self):
        budget_state = {}
        name_state = {}
        page, save_clicks = self._page_with_save_button(
            weekly_budget_state=budget_state, name_state=name_state
        )

        result = browser_masters.update_master(
            page, 42, weekly_budget=50000, name="Новое имя"
        )

        self.assertEqual(budget_state["value"], "50000")
        self.assertEqual(name_state["value"], "Новое имя")
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(
            result, {"CampaignId": 42, "WeeklyBudget": 50000, "Name": "Новое имя"}
        )

    def test_raises_when_saved_name_does_not_match_requested(self):
        # The modal's "Применить" click "succeeds", but the state backing
        # the header text never actually changes (Yandex silently rejected
        # the rename, or the terminal save didn't persist it).
        name_state = {"value": "Старое имя"}
        save_handle = _FakeTextLocatorHandle(visible=True)
        edit_button_handle = _FakeLocatorHandle()
        name_input_handle = _FakeLocatorHandle(
            on_fill=lambda v: None,  # the fill "succeeds" but doesn't persist
            get_value=lambda: name_state["value"],
        )
        accept_handle = _FakeLocatorHandle()
        header_handle = _FakeLocatorHandle()
        header_handle.inner_text = lambda: name_state["value"]
        page = FakePage(
            locators={
                browser_masters._EDIT_NAME_BUTTON_SELECTOR: _FakeLocator(
                    [edit_button_handle]
                ),
                browser_masters._NAME_MODAL_INPUT_SELECTOR: _FakeLocator(
                    [name_input_handle]
                ),
                browser_masters._NAME_MODAL_ACCEPT_SELECTOR: _FakeLocator(
                    [accept_handle]
                ),
                browser_masters._NAME_HEADER_SELECTOR: _FakeLocator([header_handle]),
            },
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(page, 42, name="Новое имя")
        self.assertIn("did not save as requested", str(ctx.exception))

    def test_does_not_click_save_when_name_edit_button_missing(self):
        page = FakePage(role_elements=[])

        with self.assertRaises(BrowserSessionError):
            browser_masters.update_master(page, 42, name="Новое имя")

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

    def test_updates_only_one_headline_slot(self):
        headlines_state = {0: "Старый заголовок", 1: "Другой заголовок"}
        page, save_clicks = self._page_with_save_button(headlines_state=headlines_state)

        result = browser_masters.update_master(
            page, 42, headlines={0: "Новый заголовок"}
        )

        self.assertEqual(page.headline_handles[0].inner_text(), "Новый заголовок")
        # Slot 1 must be left exactly as it was.
        self.assertEqual(page.headline_handles[1].inner_text(), "Другой заголовок")
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(
            result, {"CampaignId": 42, "Headlines": {0: "Новый заголовок"}}
        )

    def test_updates_headline_and_text_together_with_weekly_budget(self):
        budget_state = {}
        headlines_state = {0: "Старый заголовок"}
        texts_state = {0: "Старый текст"}
        page, save_clicks = self._page_with_save_button(
            weekly_budget_state=budget_state,
            headlines_state=headlines_state,
            texts_state=texts_state,
        )

        result = browser_masters.update_master(
            page,
            42,
            weekly_budget=60000,
            headlines={0: "Новый заголовок"},
            texts={0: "Новый текст"},
        )

        self.assertEqual(budget_state["value"], "60000")
        self.assertEqual(page.headline_handles[0].inner_text(), "Новый заголовок")
        self.assertEqual(page.text_handles[0].inner_text(), "Новый текст")
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(
            result,
            {
                "CampaignId": 42,
                "WeeklyBudget": 60000,
                "Headlines": {0: "Новый заголовок"},
                "Texts": {0: "Новый текст"},
            },
        )

    def test_raises_when_saved_headline_does_not_match_requested(self):
        # The setter's write "succeeds", but the post-save reload shows the
        # OLD value still in the slot (mirrors the budget/goal equivalents
        # above) — must be a hard error, not a false success.
        headlines_state = {0: "Старый заголовок"}
        save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: save_clicks.append(True)
        )
        slot = _FakeContentEditableHandle(text=headlines_state[0])
        # Detach the write from the shared state entirely, unlike the
        # normal helper wiring, to simulate Yandex silently rejecting it.
        slot.type = lambda value, delay=None: None
        selector = (
            f"[data-testid="
            f'"{browser_masters._HEADLINES_TESTID_TEMPLATE.format(index=0)}"]'
        )
        page = FakePage(
            locators={selector: _FakeLocator([slot])},
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(page, 42, headlines={0: "Новый заголовок"})

        self.assertEqual(len(save_clicks), 1)  # save WAS clicked
        self.assertIn("did not save as requested", str(ctx.exception))

    def test_does_not_click_save_when_headline_slot_is_empty(self):
        headlines_state = {0: ""}  # empty slot -> _set_repeating_value refuses
        page, save_clicks = self._page_with_save_button(headlines_state=headlines_state)

        with self.assertRaises(BrowserSessionError):
            browser_masters.update_master(page, 42, headlines={0: "Новый заголовок"})

        self.assertEqual(save_clicks, [])

    def test_raises_value_error_when_only_empty_headlines_dict_provided(self):
        # An empty dict is falsy — same "nothing to update" guard as every
        # other field, not treated as "update with zero slots".
        page = FakePage()

        with self.assertRaises(ValueError):
            browser_masters.update_master(page, 42, headlines={})

    def test_raises_value_error_when_only_empty_images_dict_provided(self):
        page = FakePage()

        with self.assertRaises(ValueError):
            browser_masters.update_master(page, 42, images={})

    def test_update_master_replaces_an_image(self):
        page_save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: page_save_clicks.append(True)
        )
        page = _FakeImagesPage(
            ["a", "b", "c"],
            upload_ids=["new"],
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        result = browser_masters.update_master(page, 42, images={1: "/tmp/fake.png"})

        self.assertEqual(page.ids, ["a", "c", "new"])
        self.assertEqual(len(page_save_clicks), 1)
        self.assertEqual(result, {"CampaignId": 42, "Images": {1: "/tmp/fake.png"}})

    def test_update_master_replaces_multiple_images_by_original_position(self):
        """Two ``--image`` flags in one call must resolve BOTH positions
        against the ORIGINAL (pre-mutation) set, not the live, already
        reordered one.

        Found independently by both reviewers in cycle-review round 1 of
        PR #672: ``_set_image`` re-reads the live page on every call, and
        the image manager appends replacements to the END of the set
        (confirmed live), so a naive per-position loop resolves the second
        ``--image`` against a set that has already shifted because of the
        first. Replacing positions 1 and 2 of ``[a, b, c, d]`` must remove
        exactly ``a`` and ``b`` — never a third, untouched image like
        ``c`` — regardless of set reordering in between.
        """
        page_save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: page_save_clicks.append(True)
        )
        page = _FakeImagesPage(
            ["a", "b", "c", "d"],
            upload_ids=["new1", "new2"],
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        result = browser_masters.update_master(
            page, 42, images={0: "/tmp/one.png", 1: "/tmp/two.png"}
        )

        self.assertEqual(set(page.ids), {"c", "d", "new1", "new2"})
        self.assertNotIn("a", page.ids)
        self.assertNotIn("b", page.ids)
        self.assertEqual(len(page_save_clicks), 1)
        self.assertEqual(
            result,
            {
                "CampaignId": 42,
                "Images": {0: "/tmp/one.png", 1: "/tmp/two.png"},
            },
        )

    def test_update_master_raises_when_saved_image_set_does_not_match(self):
        """Mirrors the headline "silently rejected" test — the page-level
        save WAS clicked, but the post-reload re-read still shows the image
        that was supposed to be gone."""
        page_save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: page_save_clicks.append(True)
        )
        page = _FakeImagesPage(
            ["a", "b", "c"],
            upload_ids=["new"],
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )
        # Sabotage AFTER _set_image runs but BEFORE _verify_saved's reload —
        # models Yandex accepting the modal's own Save but the page-level
        # terminal save silently not persisting the change.
        original_click = save_handle._on_click

        def _click():
            original_click()
            page.ids = ["a", "b", "c"]  # revert, as if nothing was saved

        save_handle._on_click = _click

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(page, 42, images={1: "/tmp/fake.png"})

        self.assertEqual(len(page_save_clicks), 1)
        self.assertIn("did not save as requested", str(ctx.exception))

    def test_auth_error_during_post_save_image_verification_is_not_retried(self):
        """Mirrors ``copy_master``'s
        ``test_auth_error_during_post_click_verification_is_not_retried``.

        By the time ``_verify_saved`` reloads the edit page, every requested
        image replacement has ALREADY been committed via its own modal Save
        — irreversible from here, and NOT idempotent for images the way
        ``_set_repeating_value`` is for headlines/texts (replacement always
        appends to the end of the set — see ``_set_image``'s docstring), so
        a positional re-application on retry would replace DIFFERENT images
        than the ones the caller named. If the saved session is invalidated
        in exactly this window, ``_verify_saved``'s own
        ``assert_authenticated`` raises ``BrowserAuthError`` — letting that
        propagate as-is would make ``_with_session``
        (``direct_cli/commands/masters.py``) retry this ENTIRE
        ``update_master`` call under a fresh session, re-snapshotting the
        now-already-mutated image set and removing further, untouched
        images. This must surface as a plain ``BrowserSessionError`` (not
        ``BrowserAuthError``), so ``_with_session``'s retry-on-auth-error
        does not fire — found via adversarial review (Codex) in
        cycle-review round 2 of PR #672.
        """
        page_save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: page_save_clicks.append(True)
        )
        page = _FakeImagesPage(
            ["a", "b", "c", "d"],
            upload_ids=["new1", "new2"],
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        original_assert_authenticated = browser_masters.assert_authenticated
        calls = []

        def _assert_authenticated(content):
            calls.append(True)
            # First call happens before any mutation (module convention);
            # only the post-save reload inside _verify_saved (second call)
            # hits the invalidated session.
            if len(calls) >= 2:
                raise BrowserAuthError("stale session, detected mid-body")
            return original_assert_authenticated(content)

        with patch.object(
            browser_masters,
            "assert_authenticated",
            side_effect=_assert_authenticated,
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.update_master(
                    page, 42, images={0: "/tmp/one.png", 1: "/tmp/two.png"}
                )

        self.assertNotIsInstance(ctx.exception, BrowserAuthError)
        self.assertEqual(len(page_save_clicks), 1)
        # The images WERE already replaced (irreversibly) before the auth
        # error surfaced -- the error message must say so rather than
        # implying nothing happened.
        self.assertIn("42", str(ctx.exception))


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
        self.assertIn("--name", result.output)

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
        self.assertIsNone(kwargs["name"])

    def test_passes_name_flag(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42, "Name": "Новое имя"}
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--name", "Новое имя"]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_update.call_args.kwargs["name"], "Новое имя")

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

    def test_documents_headline_and_text_flags(self):
        result = self.runner.invoke(cli, ["masters", "update", "--help"])
        self.assertIn("--headline", result.output)
        self.assertIn("--text", result.output)

    def test_passes_headline_slot_as_zero_based_index(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--headline", "2=Новый заголовок"]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        # User-facing slot 2 (1-based) -> browser layer's 0-based index 1.
        self.assertEqual(
            mock_update.call_args.kwargs["headlines"], {1: "Новый заголовок"}
        )

    def test_passes_multiple_headline_and_text_slots(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "update",
                    "42",
                    "--headline",
                    "1=Заголовок один",
                    "--headline",
                    "3=Заголовок три",
                    "--text",
                    "2=Текст два",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            mock_update.call_args.kwargs["headlines"],
            {0: "Заголовок один", 2: "Заголовок три"},
        )
        self.assertEqual(mock_update.call_args.kwargs["texts"], {1: "Текст два"})

    def test_headline_value_containing_equals_sign_splits_on_first_only(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli,
                ["masters", "update", "42", "--headline", "1=x=y=z"],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_update.call_args.kwargs["headlines"], {0: "x=y=z"})

    def test_rejects_headline_without_equals_sign(self):
        result = self.runner.invoke(
            cli, ["masters", "update", "42", "--headline", "no equals here"]
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn('"N=text"', result.output)

    def test_rejects_non_numeric_slot_number(self):
        result = self.runner.invoke(
            cli, ["masters", "update", "42", "--headline", "abc=Текст"]
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("integer", result.output)

    def test_rejects_slot_number_below_one(self):
        result = self.runner.invoke(
            cli, ["masters", "update", "42", "--headline", "0=Текст"]
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("1 or greater", result.output)

    def test_rejects_duplicate_slot_number(self):
        result = self.runner.invoke(
            cli,
            [
                "masters",
                "update",
                "42",
                "--headline",
                "1=Первый",
                "--headline",
                "1=Второй",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("more than once", result.output)

    def test_format_errors_do_not_open_a_browser_session(self):
        with patch("direct_cli.commands.masters._with_session") as mock_with_session:
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--headline", "bogus"]
            )
        self.assertNotEqual(result.exit_code, 0)
        mock_with_session.assert_not_called()

    def test_rejects_an_out_of_range_headline_slot(self):
        """``--headline "6=x"`` names a slot the edit page does not have.

        The edit page renders a FIXED 5 headline / 3 text slots, so an
        oversized slot number is a purely invalid CLI argument — it must be
        refused here, as a UsageError, not carried into a browser session
        only for ``_set_repeating_value`` to reject it as a
        BrowserSessionError after a Chromium launch and possible auth prompt.
        """
        result = self.runner.invoke(
            cli, ["masters", "update", "42", "--headline", "6=x"]
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("1-5", result.output)

    def test_rejects_an_out_of_range_text_slot(self):
        result = self.runner.invoke(cli, ["masters", "update", "42", "--text", "4=x"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("1-3", result.output)

    def test_accepts_the_last_valid_slot_of_each_field(self):
        """The upper bound is inclusive — 5 headlines and 3 texts are valid."""
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli,
                ["masters", "update", "42", "--headline", "5=a", "--text", "3=b"],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_update.call_args.kwargs["headlines"], {4: "a"})
        self.assertEqual(mock_update.call_args.kwargs["texts"], {2: "b"})

    def test_out_of_range_slot_does_not_open_a_browser_session(self):
        with patch("direct_cli.commands.masters._with_session") as mock_with_session:
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--headline", "6=x"]
            )
        self.assertNotEqual(result.exit_code, 0)
        mock_with_session.assert_not_called()

    def test_rejects_an_empty_headline_replacement(self):
        """``--headline "1="`` would DELETE variant 1, not replace it.

        Deleting a variant is explicitly out of scope for Этап B (issue
        #665), and the failure mode is silent: the slot gets cleared, the
        empty string typed, the form saved, and the post-save check compares
        the re-read slot against the requested value — both empty, so it
        matches and the delete is reported as a successful update.
        """
        result = self.runner.invoke(
            cli, ["masters", "update", "42", "--headline", "1="]
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("empty", result.output.lower())

    def test_rejects_a_whitespace_only_text_replacement(self):
        result = self.runner.invoke(cli, ["masters", "update", "42", "--text", "2=   "])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("empty", result.output.lower())

    def test_empty_replacement_does_not_open_a_browser_session(self):
        """The refusal must land before any live page is touched — an
        already-open edit page is a live, no-rollback mutation surface."""
        with patch("direct_cli.commands.masters._with_session") as mock_with_session:
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--headline", "1="]
            )
        self.assertNotEqual(result.exit_code, 0)
        mock_with_session.assert_not_called()

    def test_headline_flag_alone_satisfies_the_at_least_one_field_guard(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--headline", "1=Текст"]
            )

        self.assertEqual(result.exit_code, 0, result.output)

    def test_documents_launch_flag(self):
        result = self.runner.invoke(cli, ["masters", "update", "--help"])
        self.assertIn("--launch", result.output)

    def test_launch_flag_defaults_to_false(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--weekly-budget", "1000"]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertFalse(mock_update.call_args.kwargs["launch"])

    def test_passes_launch_flag(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli,
                ["masters", "update", "42", "--weekly-budget", "1000", "--launch"],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(mock_update.call_args.kwargs["launch"])

    def test_documents_image_flag(self):
        result = self.runner.invoke(cli, ["masters", "update", "--help"])
        self.assertIn("--image", result.output)

    def test_image_uses_path_not_text_in_format_error(self):
        """--image must show its OWN vocabulary ("N=path"), not Этап B's
        "N=text" — regression guard for the shared parser's parameterization
        (issue #670): the two option's defaults must never bleed into each
        other."""
        result = self.runner.invoke(
            cli, ["masters", "update", "42", "--image", "no equals here"]
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn('"N=path"', result.output)
        self.assertNotIn('"N=text"', result.output)

    def test_headline_format_error_still_says_text_after_image_added(self):
        """The Этап B regression anchor itself, byte-for-byte — proves
        adding --image's overrides did not change --headline's defaults."""
        result = self.runner.invoke(
            cli, ["masters", "update", "42", "--headline", "no equals here"]
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn('"N=text"', result.output)

    def test_rejects_a_nonexistent_image_path(self):
        result = self.runner.invoke(
            cli, ["masters", "update", "42", "--image", "1=/no/such/file.png"]
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("does not exist", result.output.lower())

    def test_rejects_an_unsupported_image_extension(self):
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".txt") as f:
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--image", f"1={f.name}"]
            )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("unsupported extension", result.output.lower())

    def test_rejects_an_out_of_range_image_slot(self):
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".png") as f:
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--image", f"6={f.name}"]
            )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("1-5", result.output)

    def test_rejects_an_empty_image_replacement(self):
        result = self.runner.invoke(cli, ["masters", "update", "42", "--image", "1="])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("empty", result.output.lower())
        self.assertNotIn("ad variant", result.output.lower())

    def test_image_format_errors_do_not_open_a_browser_session(self):
        with patch("direct_cli.commands.masters._with_session") as mock_with_session:
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--image", "bogus"]
            )
        self.assertNotEqual(result.exit_code, 0)
        mock_with_session.assert_not_called()

    def test_nonexistent_image_path_does_not_open_a_browser_session(self):
        with patch("direct_cli.commands.masters._with_session") as mock_with_session:
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--image", "1=/no/such/file.png"]
            )
        self.assertNotEqual(result.exit_code, 0)
        mock_with_session.assert_not_called()

    def test_image_flag_alone_satisfies_the_at_least_one_field_guard(self):
        import tempfile

        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            with tempfile.NamedTemporaryFile(suffix=".png") as f:
                result = self.runner.invoke(
                    cli, ["masters", "update", "42", "--image", f"1={f.name}"]
                )

        self.assertEqual(result.exit_code, 0, result.output)

    def test_calls_update_master_with_parsed_images(self):
        import tempfile

        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
                result = self.runner.invoke(
                    cli, ["masters", "update", "42", "--image", f"2={f.name}"]
                )

                self.assertEqual(result.exit_code, 0, result.output)
                self.assertEqual(mock_update.call_args.kwargs["images"], {1: f.name})


class TestMastersAdimagesCommand(unittest.TestCase):
    """CLI wiring for `masters adimages get/add/delete/set`."""

    def setUp(self):
        self.runner = CliRunner()

    def test_group_registered(self):
        result = self.runner.invoke(cli, ["masters", "adimages", "--help"])
        self.assertEqual(result.exit_code, 0)
        for leaf in ("get", "add", "delete", "set"):
            self.assertIn(leaf, result.output)

    def test_get_help_registered(self):
        result = self.runner.invoke(cli, ["masters", "adimages", "get", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_add_help_documents_image_file_and_launch(self):
        result = self.runner.invoke(cli, ["masters", "adimages", "add", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--image-file", result.output)
        self.assertIn("--launch", result.output)

    def test_delete_help_documents_addressing_flags(self):
        result = self.runner.invoke(cli, ["masters", "adimages", "delete", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--position", result.output)
        self.assertIn("--content-id", result.output)
        self.assertIn("--all", result.output)

    def test_set_help_documents_allow_empty(self):
        result = self.runner.invoke(cli, ["masters", "adimages", "set", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--image-file", result.output)
        self.assertIn("--allow-empty", result.output)

    def test_get_calls_fetch_master_images(self):
        with (
            patch("direct_cli.browser.masters.fetch_master_images") as mock_fetch,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_fetch.return_value = {"CampaignId": 42, "Images": [], "Count": 0}
            result = self.runner.invoke(cli, ["masters", "adimages", "get", "42"])

        self.assertEqual(result.exit_code, 0, result.output)
        mock_fetch.assert_called_once()
        self.assertEqual(mock_fetch.call_args.args[1], 42)

    def test_add_rejects_missing_file_before_any_session_opens(self):
        with patch("direct_cli.commands.masters._with_session") as mock_with_session:
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "adimages",
                    "add",
                    "42",
                    "--image-file",
                    "/tmp/does-not-exist-xyz-123.png",
                ],
            )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("does not exist", result.output)
        mock_with_session.assert_not_called()

    def test_add_rejects_unsupported_extension_before_any_session_opens(self):
        import tempfile

        with (
            tempfile.NamedTemporaryFile(suffix=".webp") as f,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            result = self.runner.invoke(
                cli, ["masters", "adimages", "add", "42", "--image-file", f.name]
            )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("unsupported extension", result.output)
        mock_with_session.assert_not_called()

    def test_add_rejects_more_files_than_the_cap_before_any_session_opens(self):
        with patch("direct_cli.commands.masters._with_session") as mock_with_session:
            args = ["masters", "adimages", "add", "42"]
            for i in range(6):
                args += ["--image-file", f"/tmp/{i}.png"]
            result = self.runner.invoke(cli, args)

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("cap", result.output.lower())
        mock_with_session.assert_not_called()

    def test_add_calls_add_master_images_with_paths_and_launch(self):
        import tempfile

        with (
            tempfile.NamedTemporaryFile(suffix=".jpg") as f,
            patch("direct_cli.browser.masters.add_master_images") as mock_add,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_add.return_value = {"CampaignId": 42, "Added": 1, "Count": 1}
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "adimages",
                    "add",
                    "42",
                    "--image-file",
                    f.name,
                    "--launch",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        mock_add.assert_called_once()
        args, kwargs = mock_add.call_args
        self.assertEqual(args[1], 42)
        self.assertEqual(kwargs["paths"], [f.name])
        self.assertTrue(kwargs["launch"])

    def test_delete_rejects_when_no_addressing_flag_given(self):
        result = self.runner.invoke(cli, ["masters", "adimages", "delete", "42"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("at least one", result.output.lower())

    def test_delete_rejects_all_combined_with_position(self):
        result = self.runner.invoke(
            cli, ["masters", "adimages", "delete", "42", "--all", "--position", "1"]
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("cannot be combined", result.output.lower())

    def test_delete_rejects_position_zero(self):
        result = self.runner.invoke(
            cli, ["masters", "adimages", "delete", "42", "--position", "0"]
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("out of range", result.output.lower())

    def test_delete_rejects_duplicate_positions(self):
        result = self.runner.invoke(
            cli,
            [
                "masters",
                "adimages",
                "delete",
                "42",
                "--position",
                "1",
                "--position",
                "1",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("more than once", result.output.lower())

    def test_delete_calls_delete_master_images_with_zero_based_positions(self):
        with (
            patch("direct_cli.browser.masters.delete_master_images") as mock_delete,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_delete.return_value = {"CampaignId": 42, "Deleted": 1, "Count": 1}
            result = self.runner.invoke(
                cli,
                ["masters", "adimages", "delete", "42", "--position", "2"],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        kwargs = mock_delete.call_args.kwargs
        self.assertEqual(kwargs["positions"], [1])
        self.assertIsNone(kwargs["content_ids"])
        self.assertFalse(kwargs["all_images"])

    def test_delete_calls_delete_master_images_with_all(self):
        with (
            patch("direct_cli.browser.masters.delete_master_images") as mock_delete,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_delete.return_value = {"CampaignId": 42, "Deleted": 3, "Count": 0}
            result = self.runner.invoke(
                cli, ["masters", "adimages", "delete", "42", "--all"]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        kwargs = mock_delete.call_args.kwargs
        self.assertTrue(kwargs["all_images"])

    def test_set_rejects_no_files_without_allow_empty(self):
        result = self.runner.invoke(cli, ["masters", "adimages", "set", "42"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("allow-empty", result.output.lower())
        self.assertIn("delete --all", result.output)

    def test_set_with_allow_empty_calls_set_master_images_with_no_paths(self):
        with (
            patch("direct_cli.browser.masters.set_master_images") as mock_set,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_set.return_value = {"CampaignId": 42, "Count": 0}
            result = self.runner.invoke(
                cli, ["masters", "adimages", "set", "42", "--allow-empty"]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_set.call_args.kwargs["paths"], [])

    def test_set_calls_set_master_images_with_paths(self):
        import tempfile

        with (
            tempfile.NamedTemporaryFile(suffix=".png") as f,
            patch("direct_cli.browser.masters.set_master_images") as mock_set,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_set.return_value = {"CampaignId": 42, "Count": 1}
            result = self.runner.invoke(
                cli, ["masters", "adimages", "set", "42", "--image-file", f.name]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_set.call_args.kwargs["paths"], [f.name])

    def test_set_rejects_more_files_than_the_cap(self):
        with patch("direct_cli.commands.masters._with_session") as mock_with_session:
            args = ["masters", "adimages", "set", "42"]
            for i in range(6):
                args += ["--image-file", f"/tmp/{i}.png"]
            result = self.runner.invoke(cli, args)

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("cap", result.output.lower())
        mock_with_session.assert_not_called()


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

    def test_assert_authenticated_raises_on_current_pwl_yandex_login_page(self):
        # Live re-recon 2026-08-02 (issue #666): Yandex Passport's login page
        # has migrated from /auth to /pwl-yandex, and no longer renders the
        # "Войдите с Яндекс ID" text anywhere in the HTML — confirmed via a
        # real open_saved_session() + goto(GRID_URL) against an actual
        # expired/invalid saved session. Both #634 markers went stale at the
        # same time, so assert_authenticated silently passed a real login
        # page through as "authenticated", turning an expired session into
        # an opaque `masters list` timeout ("waiting for event 'response'")
        # instead of a clear BrowserAuthError.
        from direct_cli.browser.session import BrowserAuthError, assert_authenticated

        html = (
            "<title>Авторизация</title>"
            "<script>window.__CONSTANTS__ = {'baseUrl':'/pwl-yandex',"
            "'authUrl':'https://passport.yandex.ru/pwl-yandex?retpath=..."
            "&origin=direct', ...};</script>"
        )
        with self.assertRaises(BrowserAuthError):
            assert_authenticated(html)

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


class TestFillLandingUrl(unittest.TestCase):
    """``_fill_landing_url`` (issue #632, re-recon issue #650) — step 1's URL
    field + "Далее".

    Both the URL field and the "Далее" button are located via
    ``page.locator(...)`` on their ``data-testid`` (issue #650 re-recon,
    2026-08-02) — Yandex replaced the plain ``<input placeholder="...">``
    with a Combobox whose text control is a ``contenteditable`` ``<div
    role="textbox">`` that ``get_by_placeholder()``/``get_by_role()`` can no
    longer find the same way.
    """

    def _page(self, url_state=None, next_clicks=None, error_visible=False):
        url_state = url_state if url_state is not None else {}
        next_clicks = next_clicks if next_clicks is not None else []
        field = _FakeLocatorHandle(on_fill=lambda v: url_state.__setitem__("url", v))
        next_button = _FakeLocatorHandle(on_click=lambda: next_clicks.append(True))
        return FakePage(
            locators={
                browser_masters._CREATE_URL_INPUT_TESTID: _FakeLocator([field]),
                browser_masters._CREATE_NEXT_BUTTON_TESTID: _FakeLocator([next_button]),
            },
            text_buttons={
                browser_masters._CREATE_INVALID_URL_TEXT: _FakeGetByTextLocator(
                    [_FakeTextLocatorHandle()] if error_visible else []
                ),
            },
        )

    def test_fills_field_and_clicks_next(self):
        url_state = {}
        next_clicks = []
        page = self._page(url_state=url_state, next_clicks=next_clicks)

        browser_masters._fill_landing_url(page, "https://ksamata.ru/")

        self.assertEqual(url_state["url"], "https://ksamata.ru/")
        self.assertEqual(len(next_clicks), 1)

    def test_raises_when_url_field_missing(self):
        page = FakePage(locators={})

        with self.assertRaises(BrowserSessionError):
            browser_masters._fill_landing_url(page, "https://ksamata.ru/")

    def test_raises_when_next_button_missing(self):
        page = FakePage(
            locators={
                browser_masters._CREATE_URL_INPUT_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
            },
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters._fill_landing_url(page, "https://ksamata.ru/")

    def test_raises_on_invalid_url_format_error(self):
        page = self._page(error_visible=True)

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._fill_landing_url(page, "not-a-valid-url")
        self.assertIn("malformed", str(ctx.exception))


class TestWaitForStep2(unittest.TestCase):
    """``_wait_for_step2`` (issue #632) — polls for the "Регион показов" heading."""

    def test_returns_once_heading_present(self):
        page = FakePage(
            text_buttons={
                "Регион показов": _FakeGetByTextLocator([_FakeTextLocatorHandle()])
            }
        )

        browser_masters._wait_for_step2(page)  # must not raise

    def test_raises_when_heading_never_appears(self):
        page = FakePage(text_buttons={})

        with (
            patch.object(browser_masters, "_CREATE_STEP2_TIMEOUT_MS", 10),
            self.assertRaises(BrowserSessionError),
        ):
            browser_masters._wait_for_step2(page)

    def test_timeout_message_says_the_page_is_still_on_step_1(self):
        # Issue #653: which step the page is stuck on changes the diagnosis
        # entirely, and re-running --headful just to find out is expensive on
        # a page with no sandbox — so the error must say it. Step 1's URL
        # field still being in the DOM means "Далее" never advanced the form.
        page = FakePage(
            text_buttons={},
            locators={
                browser_masters._CREATE_URL_INPUT_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                )
            },
        )

        with (
            patch.object(browser_masters, "_CREATE_STEP2_TIMEOUT_MS", 10),
            self.assertRaises(BrowserSessionError) as ctx,
        ):
            browser_masters._wait_for_step2(page)
        self.assertIn("still showing step 1", str(ctx.exception))

    def test_timeout_message_says_the_page_left_step_1(self):
        # The other branch: step 1's URL field is gone, so step 2 rendered but
        # without the expected section — that points at a markup change.
        page = FakePage(text_buttons={}, locators={})

        with (
            patch.object(browser_masters, "_CREATE_STEP2_TIMEOUT_MS", 10),
            self.assertRaises(BrowserSessionError) as ctx,
        ):
            browser_masters._wait_for_step2(page)
        self.assertIn("has left step 1", str(ctx.exception))


class TestAddRepeatingValues(unittest.TestCase):
    """``_add_repeating_values`` (issue #632, re-recon #653) — headline/text
    fixed-slot entry.

    Issue #653 re-recon (2026-08-02): Yandex replaced the old "single
    current-variant input, fill + Enter" flow with a FIXED set of
    pre-rendered contenteditable ``<div role="textbox">`` slots, each its
    own ``data-testid`` (``CampaignTitles{N}.textarea`` etc.) — so the fake
    now keys ``page._locators`` by per-slot selector, and the function
    types via ``.click()`` + ``.type()`` (contenteditable divs have no
    ``.fill()``/Enter-to-submit semantics) instead of pressing Enter.
    """

    def test_types_into_each_slot_by_index(self):
        typed = []
        handles = {
            0: _FakeLocatorHandle(on_fill=lambda v: typed.append((0, v))),
            1: _FakeLocatorHandle(on_fill=lambda v: typed.append((1, v))),
        }
        page = FakePage(
            locators={
                '[data-testid="fake0.textarea"]': _FakeLocator([handles[0]]),
                '[data-testid="fake1.textarea"]': _FakeLocator([handles[1]]),
            }
        )

        browser_masters._add_repeating_values(
            page, "fake{index}.textarea", 2, ["Заголовок 1", "Заголовок 2"]
        )

        self.assertEqual(typed, [(0, "Заголовок 1"), (1, "Заголовок 2")])

    def test_clears_each_slot_before_typing(self):
        """Slots arrive PRE-FILLED with Yandex's AI copy (issue #653).

        ``.type()`` appends from wherever the click left the caret, so
        without an explicit clear the caller's value is spliced into the
        middle of Yandex's text — confirmed live as
        ``'Центр оздоровления и китайско<typed>й гимнастики цигун!'``.
        """
        events = []
        field = _FakeLocatorHandle(
            text="Центр оздоровления и китайской гимнастики цигун!",
            on_press=lambda key: events.append(("press", key)),
            on_fill=lambda v: events.append(("type", v)),
        )
        page = FakePage(
            locators={'[data-testid="fake0.textarea"]': _FakeLocator([field])}
        )

        browser_masters._add_repeating_values(
            page, "fake{index}.textarea", 1, ["Тест фикса 653"]
        )

        # The clear must happen BEFORE the type, not after.
        self.assertEqual(
            events,
            [
                ("press", "ControlOrMeta+a"),
                ("press", "Backspace"),
                ("type", "Тест фикса 653"),
            ],
        )

    def test_raises_when_field_missing(self):
        page = FakePage(locators={})

        with self.assertRaises(BrowserSessionError):
            browser_masters._add_repeating_values(
                page, "fake{index}.textarea", 1, ["x"]
            )

    def test_raises_when_more_values_than_slots(self):
        page = FakePage(locators={})

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._add_repeating_values(
                page, "fake{index}.textarea", 1, ["a", "b"]
            )
        self.assertIn("only renders 1 slots", str(ctx.exception))

    def test_clears_every_slot_not_just_the_ones_being_filled(self):
        """Unused slots must not keep Yandex's AI copy (issue #655 review).

        The page renders a FIXED set of slots, most pre-filled by Yandex's
        AI scan. Filling only the first ``len(values)`` of them leaves the
        rest populated, and every non-empty slot is a published ad variant —
        so a single ``--headline`` would launch that headline PLUS four
        AI-written ones the caller never reviewed. That directly violates
        this module's stated contract ("refuses to silently launch
        AI-generated ad copy the caller never reviewed", see create_master's
        docstring) on a page with no sandbox and no rollback.
        """
        slots = {
            0: _FakeContentEditableHandle(text=""),
            1: _FakeContentEditableHandle(
                text="Центр оздоровления и китайской гимнастики!"
            ),
            2: _FakeContentEditableHandle(text="Цигун в Москве — записаться"),
        }
        page = FakePage(
            locators={
                f'[data-testid="fake{i}.textarea"]': _FakeLocator([handle])
                for i, handle in slots.items()
            }
        )

        browser_masters._add_repeating_values(
            page, "fake{index}.textarea", 3, ["Мой заголовок"]
        )

        self.assertEqual(slots[0].inner_text(), "Мой заголовок")
        # The AI-generated leftovers must be GONE, not merely un-touched.
        self.assertEqual(slots[1].inner_text(), "")
        self.assertEqual(slots[2].inner_text(), "")

    def test_aborts_when_a_slot_cannot_be_cleared(self):
        """A failed clear must abort BEFORE anything is typed (issue #655).

        ``pyproject.toml`` permits ``playwright>=1.40``, but ``ControlOrMeta``
        only exists from 1.44 — on 1.40-1.43 the modifier press throws
        ``Unknown modifier`` server-side. Silently swallowing that leaves the
        slot pre-filled and ``.type()`` then splices the caller's value into
        Yandex's copy; ``create_master`` clicks Launch before it re-reads
        anything, so the mangled variant ships. Failing loudly is the only
        safe outcome on a page with no rollback.
        """
        slot = _FakeContentEditableHandle(
            text="Центр оздоровления и китайской гимнастики!",
            supports_modifier=False,
        )
        page = FakePage(
            locators={'[data-testid="fake0.textarea"]': _FakeLocator([slot])}
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._add_repeating_values(
                page, "fake{index}.textarea", 1, ["Мой заголовок"]
            )

        # The pre-filled copy must be left untouched rather than spliced into.
        self.assertEqual(
            slot.inner_text(), "Центр оздоровления и китайской гимнастики!"
        )
        self.assertIn("clear", str(ctx.exception).lower())

    def test_aborts_when_an_unused_slot_cannot_be_clicked(self):
        """A click failure on an UNUSED slot must not be a soft skip
        (issue #655 round-2 review, Codex).

        The previous fix treated ``value is None`` (a trailing slot with no
        caller-supplied value) as safe to skip on a click failure, reasoning
        the slot "may simply not be rendered". But a click can also fail on
        a slot that IS rendered and IS still holding Yandex's AI copy — an
        overlay, a transient obstruction, anything short of "truly absent".
        ``create_master`` clicks the terminal LAUNCH button before
        ``_verify_created`` ever re-reads the page, so skipping here risks
        publishing unreviewed copy from a live, no-rollback campaign and
        only discovering it after the fact. Must fail before any click.
        """
        slot0 = _FakeContentEditableHandle(text="")
        slot1 = _FakeLocatorHandle(text="Центр оздоровления и китайской гимнастики!")
        slot1.click = lambda timeout=None: (_ for _ in ()).throw(
            PlaywrightError("intercepted: element obscured")
        )
        page = FakePage(
            locators={
                '[data-testid="fake0.textarea"]': _FakeLocator([slot0]),
                '[data-testid="fake1.textarea"]': _FakeLocator([slot1]),
            }
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters._add_repeating_values(
                page, "fake{index}.textarea", 2, ["Мой заголовок"]
            )

        # slot1's AI copy must survive untouched — the whole point is that
        # this must fail loudly instead of silently leaving it live.
        self.assertEqual(
            slot1.inner_text(), "Центр оздоровления и китайской гимнастики!"
        )


class TestReadRepeatingValues(unittest.TestCase):
    """``_read_repeating_values`` (issue #632, re-recon #653) — post-add
    read-back used by ``_verify_created``.

    Reads each slot's contenteditable div via ``inner_text()``, not
    ``input_value()`` (a contenteditable div has no ``value`` attribute).
    """

    def test_reads_inner_text_of_every_slot(self):
        handles = {
            0: _FakeLocatorHandle(text="Заголовок 1"),
            1: _FakeLocatorHandle(text="Заголовок 2"),
        }
        page = FakePage(
            locators={
                '[data-testid="fake0.textarea"]': _FakeLocator([handles[0]]),
                '[data-testid="fake1.textarea"]': _FakeLocator([handles[1]]),
            }
        )

        values = browser_masters._read_repeating_values(page, "fake{index}.textarea", 2)

        self.assertEqual(values, ["Заголовок 1", "Заголовок 2"])

    def test_missing_slot_reads_as_empty_string(self):
        page = FakePage(locators={})

        values = browser_masters._read_repeating_values(page, "fake{index}.textarea", 2)

        self.assertEqual(values, ["", ""])

    def test_unreadable_slot_reads_as_empty_string_not_a_hard_failure(self):
        handles = {
            0: _FakeLocatorHandle(text="ok"),
            1: _FakeLocatorHandle(raises=True),
        }
        page = FakePage(
            locators={
                '[data-testid="fake0.textarea"]': _FakeLocator([handles[0]]),
                '[data-testid="fake1.textarea"]': _FakeLocator([handles[1]]),
            }
        )

        values = browser_masters._read_repeating_values(page, "fake{index}.textarea", 2)

        self.assertEqual(values, ["ok", ""])


class TestSetRepeatingValue(unittest.TestCase):
    """``_set_repeating_value`` (issue #665, Этап B) — point replacement of
    ONE existing headline/text slot on the edit page.

    Unlike ``_add_repeating_values`` (the create-page setter, which clears
    and rewrites every slot unconditionally), this only ever touches the
    one requested slot — the rest of the fakes' slots must stay untouched
    across every scenario, mirroring the module's own docstring contract.
    """

    def test_replaces_a_filled_slot(self):
        events = []
        field = _FakeContentEditableHandle(
            text="Старый заголовок",
            on_press=lambda key: events.append(("press", key)),
            on_fill=lambda v: events.append(("type", v)),
        )
        page = FakePage(
            locators={'[data-testid="fake0.textarea"]': _FakeLocator([field])}
        )

        browser_masters._set_repeating_value(
            page, "fake{index}.textarea", 5, 0, "Новый заголовок"
        )

        self.assertEqual(field.inner_text(), "Новый заголовок")
        # Clear must happen before typing, same convention as
        # _add_repeating_values.
        self.assertEqual(
            events,
            [
                ("press", "ControlOrMeta+a"),
                ("press", "Backspace"),
                ("type", "Новый заголовок"),
            ],
        )

    def test_other_slots_are_never_touched(self):
        untouched = _FakeContentEditableHandle(text="Не трогать")
        target = _FakeContentEditableHandle(text="Старый текст")
        page = FakePage(
            locators={
                '[data-testid="fake0.textarea"]': _FakeLocator([untouched]),
                '[data-testid="fake1.textarea"]': _FakeLocator([target]),
            }
        )

        browser_masters._set_repeating_value(
            page, "fake{index}.textarea", 2, 1, "Новый текст"
        )

        self.assertEqual(untouched.inner_text(), "Не трогать")
        self.assertEqual(target.inner_text(), "Новый текст")

    def test_raises_when_slot_is_empty(self):
        """Writing to an empty slot would add a new variant, not replace one
        — refused rather than silently treated as "add" (issue #665)."""
        field = _FakeContentEditableHandle(text="")
        page = FakePage(
            locators={'[data-testid="fake0.textarea"]': _FakeLocator([field])}
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._set_repeating_value(
                page, "fake{index}.textarea", 5, 0, "Новый заголовок"
            )

        self.assertIn("empty", str(ctx.exception).lower())
        # Nothing should have been typed into the empty slot.
        self.assertEqual(field.inner_text(), "")

    def test_raises_when_index_out_of_range(self):
        page = FakePage(locators={})

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._set_repeating_value(
                page, "fake{index}.textarea", 3, 5, "x"
            )

        self.assertIn("out of range", str(ctx.exception).lower())

    def test_raises_when_field_missing(self):
        page = FakePage(locators={})

        with self.assertRaises(BrowserSessionError):
            browser_masters._set_repeating_value(
                page, "fake{index}.textarea", 1, 0, "x"
            )

    def test_aborts_when_slot_cannot_be_cleared(self):
        """Same ``supports_modifier=False`` (Playwright <1.44) guard as
        ``_add_repeating_values`` — must fail loudly, not splice text."""
        field = _FakeContentEditableHandle(
            text="Старый заголовок", supports_modifier=False
        )
        page = FakePage(
            locators={'[data-testid="fake0.textarea"]': _FakeLocator([field])}
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._set_repeating_value(
                page, "fake{index}.textarea", 5, 0, "Новый заголовок"
            )

        self.assertEqual(field.inner_text(), "Старый заголовок")
        self.assertIn("clear", str(ctx.exception).lower())

    def test_click_failure_raises_browser_session_error(self):
        field = _FakeContentEditableHandle(text="Старый заголовок")
        field.click = lambda timeout=None: (_ for _ in ()).throw(
            PlaywrightError("element detached")
        )
        page = FakePage(
            locators={'[data-testid="fake0.textarea"]': _FakeLocator([field])}
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters._set_repeating_value(
                page, "fake{index}.textarea", 5, 0, "Новый заголовок"
            )

    def test_refuses_to_blank_a_slot_with_an_empty_value(self):
        """An empty replacement would DELETE a live ad variant.

        Deleting a variant is explicitly out of scope for Этап B (issue #665
        lists it under "Явно вне объёма"), and the damage is silent: the slot
        is cleared, the empty string is typed, the form is saved, and
        ``_verify_repeating_value_mismatches`` then compares the re-read slot
        against the REQUESTED value — ``"" == ""`` matches, so the delete is
        reported as a successful update. On an active campaign that is a live
        ad mutation with no rollback (and with ``--launch`` on a DRAFT, it is
        published immediately). Guarded here as well as at the CLI boundary
        so the browser layer is safe for any caller, not just the CLI.
        """
        field = _FakeContentEditableHandle(text="Старый заголовок")
        page = FakePage(
            locators={'[data-testid="fake0.textarea"]': _FakeLocator([field])}
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._set_repeating_value(page, "fake{index}.textarea", 5, 0, "")

        # The existing variant must survive untouched — not cleared-then-failed.
        self.assertEqual(field.inner_text(), "Старый заголовок")
        self.assertIn("empty", str(ctx.exception).lower())

    def test_refuses_to_blank_a_slot_with_a_whitespace_only_value(self):
        """Whitespace-only is the same delete wearing a disguise."""
        field = _FakeContentEditableHandle(text="Старый заголовок")
        page = FakePage(
            locators={'[data-testid="fake0.textarea"]': _FakeLocator([field])}
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._set_repeating_value(
                page, "fake{index}.textarea", 5, 0, "   "
            )

        self.assertEqual(field.inner_text(), "Старый заголовок")
        self.assertIn("empty", str(ctx.exception).lower())


class _FakeImagesPage(FakePage):
    """Models the image set + image manager modal (issue #670, Этап D).

    Unlike headlines/texts, there is no fixed slot count — the page and the
    modal's "Выбранные изображения" panel each render a variable-length list
    of cards. This fake keeps ONE shared ``ids`` list (content IDs, standing
    in 1:1 for thumb URLs too, since ``_set_image`` never needs to tell them
    apart — see ``_read_modal_selected_thumb_urls``'s docstring) that both
    ``_read_image_content_ids`` (via the page-level ``ContentImage.*``
    locator) and ``_read_modal_selected_thumb_urls``/the remove buttons (via
    the modal-level ``SelectedImage.*`` locators) read/mutate — mirroring
    how ``_page_with_save_button``'s ``budget_state``/``headline_handles``
    share mutable state between the "edit" and "post-save reload" phases of
    one ``update_master`` call.

    ``open_images_modal`` toggles whether ``ImageSuggestionsEditorModal`` is
    present at all — real Playwright only renders it after the "Выбрать
    другие изображения" click (confirmed live), and ``_open_images_modal``'s
    polling loop depends on that transition being observable.
    """

    def __init__(self, ids, *, save_clicks=None, upload_ids=None, **kwargs):
        super().__init__(**kwargs)
        self.ids = list(ids)
        self.modal_open = False
        self.save_clicks = save_clicks if save_clicks is not None else []
        # Content IDs assigned to successive set_input_files() uploads, one
        # per call, in order — mirrors a test wanting deterministic new IDs
        # without depending on upload ordering internals.
        self._upload_ids = list(upload_ids or [])
        self._upload_call = 0
        # Every path passed to set_input_files(), in call order — lets
        # ``masters adimages set``/``add`` tests assert upload sequencing
        # (e.g. "removed everything, then uploaded in the order given").
        self.upload_paths = []

    def locator(self, selector):
        if selector == browser_masters._IMAGES_EDITOR_SELECTOR:
            # The images section itself — present as soon as the (fake) page
            # has rendered, which is what `_wait_for_images_editor` polls for
            # before trusting an empty read as "this campaign has no images".
            return _FakeLocator([_FakeLocatorHandle()])
        if not self.modal_open and selector == browser_masters._IMAGES_MODAL_SELECTOR:
            return _FakeLocator([])
        if self.modal_open and selector == browser_masters._IMAGES_MODAL_SELECTOR:
            return _FakeLocator([_FakeLocatorHandle()])
        if selector == browser_masters._IMAGES_OPEN_MODAL_SELECTOR:
            return _FakeLocator(
                [_FakeLocatorHandle(on_click=lambda: setattr(self, "modal_open", True))]
            )
        if selector == browser_masters._IMAGES_MODAL_FILE_INPUT_SELECTOR:
            return _FakeLocator([_FakeLocatorHandle(on_upload=self._upload)])
        if selector == browser_masters._IMAGES_MODAL_SAVE_SELECTOR:
            return _FakeLocator(
                [
                    _FakeLocatorHandle(
                        on_click=lambda: (
                            self.save_clicks.append(True),
                            setattr(self, "modal_open", False),
                        )
                    )
                ]
            )
        selector_prefix = (
            f'[data-testid^="{browser_masters._IMAGES_CONTENT_TESTID_PREFIX}"]'
        )
        if selector == selector_prefix:
            return _FakeLocator(
                [
                    _FakeLocatorHandle(attrs={"data-testid": self._content_testid(cid)})
                    for cid in self.ids
                ]
            )
        modal_prefix = (
            f'[data-testid^="{browser_masters._IMAGES_MODAL_SELECTED_PREFIX}"]'
        )
        if selector == modal_prefix:
            return _FakeLocator(
                [
                    _FakeLocatorHandle(
                        attrs={"data-testid": self._selected_testid(cid)}
                    )
                    for cid in self.ids
                ]
            )
        for cid in self.ids:
            remove_testid = browser_masters._IMAGES_MODAL_REMOVE_TESTID_TEMPLATE.format(
                thumb_url=cid
            )
            remove_selector = f'[data-testid="{remove_testid}"]'
            if selector == remove_selector:
                bound_cid = cid
                return _FakeLocator(
                    [
                        _FakeLocatorHandle(
                            on_click=lambda bound_cid=bound_cid: self.ids.remove(
                                bound_cid
                            )
                        )
                    ]
                )
        return super().locator(selector)

    def _content_testid(self, content_id):
        return f"{browser_masters._IMAGES_CONTENT_TESTID_PREFIX}{content_id}"

    def _selected_testid(self, content_id):
        return f"{browser_masters._IMAGES_MODAL_SELECTED_PREFIX}{content_id}"

    def _upload(self, path):
        self.upload_paths.append(path)
        if self._upload_call < len(self._upload_ids):
            new_id = self._upload_ids[self._upload_call]
        else:
            new_id = f"uploaded-{self._upload_call}"
        self._upload_call += 1
        self.ids.append(new_id)


class TestReadImageContentIds(unittest.TestCase):
    """``_read_image_content_ids`` (issue #670, Этап D)."""

    def test_reads_ids_in_dom_order(self):
        page = _FakeImagesPage(["a", "b", "c"])

        self.assertEqual(browser_masters._read_image_content_ids(page), ["a", "b", "c"])

    def test_empty_set_is_not_an_error(self):
        """Unlike headlines/texts, zero images is a legitimate campaign state."""
        page = _FakeImagesPage([])

        self.assertEqual(browser_masters._read_image_content_ids(page), [])


class TestWaitForImagesEditor(unittest.TestCase):
    """``_wait_for_images_editor`` (issue #670) — regression guard for a bug
    found during live verification.

    The edit page is an SPA: ``goto(wait_until="domcontentloaded")`` returns
    while the images section is still absent, so reading the set straight
    away yields ``[]`` — indistinguishable from "this campaign genuinely has
    no images". Live-confirmed: four consecutive DRAFT campaigns were
    rejected with "no images" by ``masters update --image`` while their edit
    pages demonstrably rendered four images each.
    """

    def test_returns_once_the_section_is_present(self):
        page = _FakeImagesPage(["a"])

        browser_masters._wait_for_images_editor(page)  # must not raise

    def test_raises_rather_than_reporting_no_images(self):
        """A section that never renders is a hard error, NOT an empty set."""

        class _NoEditorPage(_FakeImagesPage):
            def locator(self, selector):
                if selector == browser_masters._IMAGES_EDITOR_SELECTOR:
                    return _FakeLocator([])
                return super().locator(selector)

        page = _NoEditorPage([])
        with patch.object(browser_masters, "_IMAGES_EDITOR_TIMEOUT_MS", 1):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters._wait_for_images_editor(page)

        self.assertIn("did not finish rendering", str(ctx.exception))

    def test_set_image_does_not_claim_no_images_before_the_section_renders(self):
        """The end-to-end shape of the live bug: `_set_image` must not
        report "no images" for a page whose section has not rendered yet."""

        class _NoEditorPage(_FakeImagesPage):
            def locator(self, selector):
                if selector == browser_masters._IMAGES_EDITOR_SELECTOR:
                    return _FakeLocator([])
                return super().locator(selector)

        page = _NoEditorPage([])
        with patch.object(browser_masters, "_IMAGES_EDITOR_TIMEOUT_MS", 1):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters._set_image(
                    page, 0, "/tmp/fake.png", target_content_id="a"
                )

        self.assertIn("did not finish rendering", str(ctx.exception))
        self.assertNotIn("no images", str(ctx.exception).lower())

    def test_waits_out_the_loading_stub_state_before_returning(self):
        """Live-confirmed 2026-08-03 regression (campaigns 713234191 and
        713234204, both with 4 real images): ``ImageSuggestionsEditor``
        itself renders FIRST with four ``...CampaignContents.StubN``
        loading placeholders, and NEITHER ``ContentImage.*`` nor ``.Open``
        exist yet — only ~3s later do the stubs get replaced by the real
        content. Waiting on ``_IMAGES_EDITOR_SELECTOR`` alone (the original
        implementation) returned during this stub window, so
        ``masters adimages get`` reported ``Count: 0`` for a campaign that
        demonstrably had 4 images, and a subsequent ``adimages add`` then
        uploaded into what it believed was an empty set and timed out.
        """

        class _StubThenContentPage(_FakeImagesPage):
            def __init__(self, *args, stub_ticks=2, **kwargs):
                super().__init__(*args, **kwargs)
                self._stub_ticks_remaining = stub_ticks

            def locator(self, selector):
                stub_prefix = (
                    f'[data-testid^="{browser_masters._IMAGES_STUB_TESTID_PREFIX}"]'
                )
                if selector == stub_prefix:
                    if self._stub_ticks_remaining > 0:
                        self._stub_ticks_remaining -= 1
                        return _FakeLocator([_FakeLocatorHandle() for _ in range(4)])
                    return _FakeLocator([])
                return super().locator(selector)

        page = _StubThenContentPage(["a", "b", "c", "d"], stub_ticks=2)

        browser_masters._wait_for_images_editor(page)  # must not raise

        # Confirms the wait actually consumed the stub ticks rather than
        # returning on the very first (still-stubbed) poll.
        self.assertEqual(page._stub_ticks_remaining, 0)
        self.assertEqual(
            browser_masters._read_image_content_ids(page), ["a", "b", "c", "d"]
        )

    def test_raises_if_stubs_never_clear(self):
        """A section stuck showing loading placeholders forever must be a
        hard error, not silently treated as an empty (or populated) set."""

        class _StuckStubPage(_FakeImagesPage):
            def locator(self, selector):
                stub_prefix = (
                    f'[data-testid^="{browser_masters._IMAGES_STUB_TESTID_PREFIX}"]'
                )
                if selector == stub_prefix:
                    return _FakeLocator([_FakeLocatorHandle() for _ in range(4)])
                return super().locator(selector)

        page = _StuckStubPage(["a", "b", "c", "d"])
        with patch.object(browser_masters, "_IMAGES_EDITOR_TIMEOUT_MS", 1):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters._wait_for_images_editor(page)

        self.assertIn("did not finish rendering", str(ctx.exception))
        self.assertIn("loading placeholders", str(ctx.exception))


class TestSetImage(unittest.TestCase):
    """``_set_image`` (issue #670, Этап D) — synthetic point-replacement
    composed from the image manager modal's remove+upload+save.
    """

    def test_replaces_the_requested_position_only(self):
        page = _FakeImagesPage(["a", "b", "c"], upload_ids=["new"])

        browser_masters._set_image(page, 1, "/tmp/fake.png", target_content_id="b")

        # Confirmed-live behaviour: the new image lands at the END of the
        # set, not back at position 1 — see _set_image's own docstring.
        self.assertEqual(page.ids, ["a", "c", "new"])
        self.assertEqual(len(page.save_clicks), 1)
        self.assertFalse(page.modal_open)

    def test_raises_when_image_set_is_empty(self):
        page = _FakeImagesPage([])

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._set_image(page, 0, "/tmp/fake.png", target_content_id="a")

        self.assertIn("no images", str(ctx.exception).lower())
        self.assertEqual(page.save_clicks, [])

    def test_raises_when_position_out_of_range(self):
        page = _FakeImagesPage(["a", "b"])

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._set_image(
                page, 5, "/tmp/fake.png", target_content_id="nonexistent"
            )

        self.assertIn("out of range", str(ctx.exception).lower())
        self.assertEqual(page.ids, ["a", "b"])
        self.assertEqual(page.save_clicks, [])

    def test_raises_when_target_content_id_already_gone(self):
        """Models the caller-contract violation this signature exists to
        prevent: a second ``_set_image`` in the same batch naming a content
        ID an earlier call in the SAME batch already removed. A live page
        race is not the scenario here — ``update_master`` always resolves
        ``target_content_id`` from its own pre-batch snapshot, so this can
        only happen if a caller passes a stale/already-consumed ID."""
        page = _FakeImagesPage(["a", "b"])

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._set_image(
                page, 0, "/tmp/fake.png", target_content_id="already-removed"
            )

        self.assertIn("no longer present", str(ctx.exception).lower())
        self.assertEqual(page.ids, ["a", "b"])
        self.assertEqual(page.save_clicks, [])

    def test_does_not_save_when_upload_never_appears(self):
        """A stalled/failed async upload must not be committed via Save."""
        page = _FakeImagesPage(["a", "b"], upload_ids=[])
        # Sabotage the upload: the file input exists but never actually adds
        # a new card to the selected panel.
        original_locator = page.locator

        def _locator(selector):
            if selector == browser_masters._IMAGES_MODAL_FILE_INPUT_SELECTOR:
                return _FakeLocator([_FakeLocatorHandle(on_upload=lambda path: None)])
            return original_locator(selector)

        page.locator = _locator
        # Keep the test fast — patch.object restores the real value even on
        # failure, and never hardcodes it (a `finally:` assignment would).
        with patch.object(browser_masters, "_IMAGE_UPLOAD_TIMEOUT_MS", 1):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters._set_image(
                    page, 0, "/tmp/fake.png", target_content_id="a"
                )

        self.assertIn("no new", str(ctx.exception).lower())
        self.assertEqual(page.save_clicks, [])
        # The removed image must NOT still be missing from the caller's
        # perspective of "nothing was saved" — the campaign's actually-saved
        # set is untouched because Save was never clicked, even though the
        # modal's own in-progress state lost it.

    def test_removed_image_not_still_present_raises(self):
        """Models Yandex's own remove click silently failing."""
        page = _FakeImagesPage(["a", "b"])
        original_locator = page.locator

        def _locator(selector):
            remove_testid = browser_masters._IMAGES_MODAL_REMOVE_TESTID_TEMPLATE.format(
                thumb_url="a"
            )
            remove_selector = f'[data-testid="{remove_testid}"]'
            if selector == remove_selector:
                return _FakeLocator([_FakeLocatorHandle(on_click=lambda: None)])
            return original_locator(selector)

        page.locator = _locator
        with patch.object(browser_masters, "_IMAGE_MODAL_OPEN_TIMEOUT_MS", 1):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters._set_image(
                    page, 0, "/tmp/fake.png", target_content_id="a"
                )

        self.assertIn("still shown", str(ctx.exception).lower())
        self.assertEqual(page.save_clicks, [])


class TestApplyImageOperations(unittest.TestCase):
    """``_apply_image_operations`` — the bulk one-modal primitive behind
    ``masters adimages add/delete/set`` (unlike ``_set_image``, which opens
    its own modal per call).
    """

    def test_no_op_when_both_lists_empty(self):
        page = _FakeImagesPage(["a", "b"])

        browser_masters._apply_image_operations(
            page, remove_content_ids=(), upload_paths=()
        )

        self.assertEqual(page.ids, ["a", "b"])
        self.assertFalse(page.modal_open)
        self.assertEqual(page.save_clicks, [])

    def test_uploads_into_an_empty_set(self):
        page = _FakeImagesPage([], upload_ids=["new1", "new2"])

        browser_masters._apply_image_operations(
            page,
            remove_content_ids=(),
            upload_paths=["/tmp/a.png", "/tmp/b.png"],
        )

        self.assertEqual(page.ids, ["new1", "new2"])
        self.assertEqual(page.upload_paths, ["/tmp/a.png", "/tmp/b.png"])
        self.assertEqual(len(page.save_clicks), 1)
        self.assertFalse(page.modal_open)

    def test_removes_every_image_leaving_the_set_empty(self):
        page = _FakeImagesPage(["a", "b", "c"])

        browser_masters._apply_image_operations(
            page,
            remove_content_ids=["a", "b", "c"],
            upload_paths=(),
        )

        self.assertEqual(page.ids, [])
        self.assertEqual(len(page.save_clicks), 1)

    def test_removes_and_uploads_in_one_modal_session(self):
        """The core invariant bulk ops need: N removes + M uploads, but
        exactly ONE open/Save cycle — not N+M cycles like ``_set_image``."""
        page = _FakeImagesPage(["a", "b", "c"], upload_ids=["x", "y"])

        browser_masters._apply_image_operations(
            page,
            remove_content_ids=["a", "b", "c"],
            upload_paths=["/tmp/x.png", "/tmp/y.png"],
        )

        self.assertEqual(page.ids, ["x", "y"])
        self.assertEqual(page.upload_paths, ["/tmp/x.png", "/tmp/y.png"])
        self.assertEqual(len(page.save_clicks), 1)

    def test_upload_order_is_preserved(self):
        page = _FakeImagesPage(["a"], upload_ids=["u1", "u2", "u3"])

        browser_masters._apply_image_operations(
            page,
            remove_content_ids=(),
            upload_paths=["/tmp/1.png", "/tmp/2.png", "/tmp/3.png"],
        )

        self.assertEqual(page.upload_paths, ["/tmp/1.png", "/tmp/2.png", "/tmp/3.png"])
        self.assertEqual(page.ids, ["a", "u1", "u2", "u3"])

    def test_unknown_remove_content_id_raises_before_any_click(self):
        page = _FakeImagesPage(["a", "b"])

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._apply_image_operations(
                page,
                remove_content_ids=["nonexistent"],
                upload_paths=(),
            )

        self.assertIn("not present", str(ctx.exception).lower())
        self.assertEqual(page.ids, ["a", "b"])
        self.assertEqual(page.save_clicks, [])

    def test_upload_that_never_lands_raises_and_does_not_save(self):
        page = _FakeImagesPage(["a"], upload_ids=[])
        original_locator = page.locator

        def _locator(selector):
            if selector == browser_masters._IMAGES_MODAL_FILE_INPUT_SELECTOR:
                return _FakeLocator([_FakeLocatorHandle(on_upload=lambda path: None)])
            return original_locator(selector)

        page.locator = _locator
        with patch.object(browser_masters, "_IMAGE_UPLOAD_TIMEOUT_MS", 1):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters._apply_image_operations(
                    page,
                    remove_content_ids=(),
                    upload_paths=["/tmp/a.png"],
                )

        self.assertIn("no new", str(ctx.exception).lower())
        self.assertEqual(page.save_clicks, [])

    def test_remove_that_never_takes_effect_raises_and_does_not_save(self):
        page = _FakeImagesPage(["a", "b"])
        original_locator = page.locator

        def _locator(selector):
            remove_testid = browser_masters._IMAGES_MODAL_REMOVE_TESTID_TEMPLATE.format(
                thumb_url="a"
            )
            remove_selector = f'[data-testid="{remove_testid}"]'
            if selector == remove_selector:
                return _FakeLocator([_FakeLocatorHandle(on_click=lambda: None)])
            return original_locator(selector)

        page.locator = _locator
        with patch.object(browser_masters, "_IMAGE_MODAL_OPEN_TIMEOUT_MS", 1):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters._apply_image_operations(
                    page,
                    remove_content_ids=["a"],
                    upload_paths=(),
                )

        self.assertIn("still shown", str(ctx.exception).lower())
        self.assertEqual(page.save_clicks, [])


class TestVerifyImageSetMismatches(unittest.TestCase):
    """``_verify_image_set_mismatches`` — absolute end-state verification
    generalizing ``_verify_image_mismatches``'s hardcoded "removed count ==
    added count" assumption, so ``masters adimages add/delete/set`` can each
    state their own expected end size.
    """

    def test_no_mismatches_when_end_state_matches(self):
        page = _FakeImagesPage(["a", "c", "new"])  # "b" removed, "new" added

        mismatches = browser_masters._verify_image_set_mismatches(
            page,
            expected_kept_ids=["a", "c"],
            removed_ids={"b"},
            expected_added_count=1,
        )

        self.assertEqual(mismatches, [])

    def test_asserts_the_set_is_now_empty(self):
        """The ``delete --all`` / ``set`` with no files case — the old
        ``_verify_image_mismatches`` couldn't express this at all."""
        page = _FakeImagesPage([])

        mismatches = browser_masters._verify_image_set_mismatches(
            page,
            expected_kept_ids=[],
            removed_ids={"a", "b", "c"},
            expected_added_count=0,
        )

        self.assertEqual(mismatches, [])

    def test_flags_a_leftover_image_when_set_should_be_empty(self):
        page = _FakeImagesPage(["leftover"])

        mismatches = browser_masters._verify_image_set_mismatches(
            page,
            expected_kept_ids=[],
            removed_ids={"a"},
            expected_added_count=0,
        )

        self.assertTrue(any("expected 0" in m for m in mismatches))

    def test_flags_a_removed_id_still_present(self):
        page = _FakeImagesPage(["a", "b"])

        mismatches = browser_masters._verify_image_set_mismatches(
            page, expected_kept_ids=[], removed_ids={"a", "b"}, expected_added_count=0
        )

        self.assertTrue(any("still present" in m for m in mismatches))

    def test_flags_a_kept_id_that_went_missing(self):
        page = _FakeImagesPage(["a"])

        mismatches = browser_masters._verify_image_set_mismatches(
            page,
            expected_kept_ids=["a", "b"],
            removed_ids=set(),
            expected_added_count=0,
        )

        self.assertTrue(any("missing" in m for m in mismatches))

    def test_flags_wrong_end_size_with_both_numbers(self):
        page = _FakeImagesPage(["a", "b", "c"])

        mismatches = browser_masters._verify_image_set_mismatches(
            page, expected_kept_ids=["a"], removed_ids=set(), expected_added_count=1
        )

        self.assertTrue(any("has 3 image(s), expected 2" in m for m in mismatches))


class TestFetchMasterImages(unittest.TestCase):
    """``fetch_master_images`` — read-only, never saves."""

    def test_returns_positions_content_ids_and_thumb_urls(self):
        page = _FakeImagesPage(["a", "b", "c"])

        result = browser_masters.fetch_master_images(page, 42)

        self.assertEqual(result["CampaignId"], 42)
        self.assertEqual(result["Count"], 3)
        self.assertEqual(result["MaxCount"], browser_masters._IMAGES_MAX_COUNT)
        self.assertEqual(
            result["Images"],
            [
                {"Position": 1, "ContentId": "a", "ThumbUrl": "a"},
                {"Position": 2, "ContentId": "b", "ThumbUrl": "b"},
                {"Position": 3, "ContentId": "c", "ThumbUrl": "c"},
            ],
        )
        self.assertEqual(page.save_clicks, [])

    def test_empty_set_is_a_successful_result_not_an_error(self):
        page = _FakeImagesPage([])

        result = browser_masters.fetch_master_images(page, 42)

        self.assertEqual(result["Count"], 0)
        self.assertEqual(result["Images"], [])
        self.assertEqual(page.save_clicks, [])

    def test_never_clicks_save(self):
        """The modal opens to read thumb URLs, but is abandoned rather than
        Saved — nothing commits to the saved image set (see
        ``fetch_master_images``'s docstring: same abandon-safe invariant
        ``_set_image``/``_apply_image_operations`` rely on)."""
        page = _FakeImagesPage(["a", "b"])

        browser_masters.fetch_master_images(page, 42)

        self.assertEqual(page.save_clicks, [])

    def test_empty_set_never_opens_the_modal(self):
        """Nothing to read a thumb URL for, so the modal stays shut."""
        page = _FakeImagesPage([])

        result = browser_masters.fetch_master_images(page, 42)

        self.assertEqual(result["Count"], 0)
        self.assertFalse(page.modal_open)

    def test_unrendered_editor_raises_rather_than_reporting_no_images(self):
        class _NoEditorPage(_FakeImagesPage):
            def locator(self, selector):
                if selector == browser_masters._IMAGES_EDITOR_SELECTOR:
                    return _FakeLocator([])
                return super().locator(selector)

        page = _NoEditorPage([])
        with patch.object(browser_masters, "_IMAGES_EDITOR_TIMEOUT_MS", 1):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.fetch_master_images(page, 42)

        self.assertIn("did not finish rendering", str(ctx.exception))
        self.assertNotIn("no images", str(ctx.exception).lower())


class TestAddMasterImages(unittest.TestCase):
    """``add_master_images`` — append into an existing or empty set."""

    def _page_with_save(self, ids, **kwargs):
        save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: save_clicks.append(True)
        )
        page = _FakeImagesPage(
            ids,
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
            **kwargs,
        )
        return page, save_clicks

    def test_appends_into_an_empty_set(self):
        page, save_clicks = self._page_with_save([], upload_ids=["new1"])

        result = browser_masters.add_master_images(page, 42, paths=["/tmp/a.png"])

        self.assertEqual(page.ids, ["new1"])
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(result, {"CampaignId": 42, "Added": 1, "Count": 1})

    def test_appends_onto_an_existing_set(self):
        page, save_clicks = self._page_with_save(["a", "b"], upload_ids=["new1"])

        result = browser_masters.add_master_images(page, 42, paths=["/tmp/a.png"])

        self.assertEqual(page.ids, ["a", "b", "new1"])
        self.assertEqual(result, {"CampaignId": 42, "Added": 1, "Count": 3})

    def test_exceeding_the_cap_raises_and_never_opens_the_modal(self):
        page, save_clicks = self._page_with_save(["a", "b", "c", "d", "e"])

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.add_master_images(page, 42, paths=["/tmp/a.png"])

        self.assertIn("cap", str(ctx.exception).lower())
        self.assertFalse(page.modal_open)
        self.assertEqual(save_clicks, [])

    def test_auth_error_during_verification_is_re_raised_non_idempotent(self):
        page, _save_clicks = self._page_with_save([], upload_ids=["new1"])
        with patch.object(
            browser_masters,
            "_verify_saved_images",
            side_effect=BrowserAuthError("stale session"),
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.add_master_images(page, 42, paths=["/tmp/a.png"])

        self.assertIn("not idempotent", str(ctx.exception).lower())


class TestDeleteMasterImages(unittest.TestCase):
    """``delete_master_images`` — by position, by content ID, or ``--all``."""

    def _page_with_save(self, ids, **kwargs):
        save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: save_clicks.append(True)
        )
        page = _FakeImagesPage(
            ids,
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
            **kwargs,
        )
        return page, save_clicks

    def test_deletes_by_position(self):
        page, save_clicks = self._page_with_save(["a", "b", "c"])

        result = browser_masters.delete_master_images(page, 42, positions=[1])

        self.assertEqual(page.ids, ["a", "c"])
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(result, {"CampaignId": 42, "Deleted": 1, "Count": 2})

    def test_deletes_by_content_id(self):
        page, save_clicks = self._page_with_save(["a", "b", "c"])

        result = browser_masters.delete_master_images(page, 42, content_ids=["b"])

        self.assertEqual(page.ids, ["a", "c"])
        self.assertEqual(result, {"CampaignId": 42, "Deleted": 1, "Count": 2})

    def test_deletes_all(self):
        page, save_clicks = self._page_with_save(["a", "b", "c"])

        result = browser_masters.delete_master_images(page, 42, all_images=True)

        self.assertEqual(page.ids, [])
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(result, {"CampaignId": 42, "Deleted": 3, "Count": 0})

    def test_all_on_an_already_empty_set_is_an_idempotent_no_op(self):
        page, save_clicks = self._page_with_save([])

        result = browser_masters.delete_master_images(page, 42, all_images=True)

        self.assertEqual(result, {"CampaignId": 42, "Deleted": 0, "Count": 0})
        self.assertEqual(save_clicks, [])
        self.assertFalse(page.modal_open)

    def test_out_of_range_position_raises(self):
        page, save_clicks = self._page_with_save(["a", "b"])

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.delete_master_images(page, 42, positions=[5])

        self.assertIn("out of range", str(ctx.exception).lower())
        self.assertEqual(save_clicks, [])

    def test_unknown_content_id_raises(self):
        page, save_clicks = self._page_with_save(["a", "b"])

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.delete_master_images(page, 42, content_ids=["ghost"])

        self.assertIn("not present", str(ctx.exception).lower())
        self.assertEqual(save_clicks, [])


class TestSetMasterImages(unittest.TestCase):
    """``set_master_images`` — whole-set replacement in one modal."""

    def _page_with_save(self, ids, **kwargs):
        save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: save_clicks.append(True)
        )
        page = _FakeImagesPage(
            ids,
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
            **kwargs,
        )
        return page, save_clicks

    def test_full_replacement_in_one_modal(self):
        page, save_clicks = self._page_with_save(["a", "b", "c"], upload_ids=["x", "y"])

        result = browser_masters.set_master_images(
            page, 42, paths=["/tmp/x.png", "/tmp/y.png"]
        )

        self.assertEqual(page.ids, ["x", "y"])
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(result, {"CampaignId": 42, "Count": 2})

    def test_empty_paths_empties_the_set(self):
        page, save_clicks = self._page_with_save(["a", "b"])

        result = browser_masters.set_master_images(page, 42, paths=[])

        self.assertEqual(page.ids, [])
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(result, {"CampaignId": 42, "Count": 0})

    def test_already_empty_with_no_paths_is_a_no_op(self):
        page, save_clicks = self._page_with_save([])

        result = browser_masters.set_master_images(page, 42, paths=[])

        self.assertEqual(result, {"CampaignId": 42, "Count": 0})
        self.assertEqual(save_clicks, [])
        self.assertFalse(page.modal_open)

    def test_exceeding_the_cap_raises(self):
        page, save_clicks = self._page_with_save([])

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.set_master_images(
                page,
                42,
                paths=[f"/tmp/{i}.png" for i in range(6)],
            )

        self.assertIn("cap", str(ctx.exception).lower())
        self.assertEqual(save_clicks, [])


class TestVerifyImageMismatches(unittest.TestCase):
    """``_verify_image_mismatches`` (issue #670, Этап D) — set-membership
    verification, NOT positional (see ``_set_image``'s docstring for why).
    """

    def test_no_mismatches_when_replaced_gone_and_kept_present(self):
        page = _FakeImagesPage(["a", "c", "new"])  # "b" was replaced by "new"

        mismatches = browser_masters._verify_image_mismatches(
            page, before_ids=["a", "b", "c"], replaced_ids={"b"}
        )

        self.assertEqual(mismatches, [])

    def test_flags_a_replaced_id_still_present(self):
        """Yandex silently rejected the replacement — "b" never left."""
        page = _FakeImagesPage(["a", "b", "c"])

        mismatches = browser_masters._verify_image_mismatches(
            page, before_ids=["a", "b", "c"], replaced_ids={"b"}
        )

        self.assertTrue(any("still present" in m for m in mismatches))

    def test_flags_a_kept_id_that_went_missing(self):
        """Something clobbered an image the caller never asked to touch."""
        page = _FakeImagesPage(["a", "new"])  # "c" vanished unexpectedly

        mismatches = browser_masters._verify_image_mismatches(
            page, before_ids=["a", "b", "c"], replaced_ids={"b"}
        )

        self.assertTrue(any("missing" in m for m in mismatches))

    def test_no_requested_replacements_is_a_no_op(self):
        page = _FakeImagesPage(["a", "b", "c"])

        mismatches = browser_masters._verify_image_mismatches(
            page, before_ids=[], replaced_ids=set()
        )

        self.assertEqual(mismatches, [])


class TestSetRegion(unittest.TestCase):
    """``_set_region`` (issue #632, re-recon #653) — the one genuinely-empty
    required field.

    Issue #653 re-recon (2026-08-02): Yandex replaced the old text-combobox
    with a tree/tag-group widget. The fake models: clicking the launcher
    (``_REGION_LAUNCHER_TESTID``) reveals a separate filter field
    (``_REGION_EDITOR_TESTID``), typing into it is a no-op on the fake page
    (the real tree-filtering is server/client-state this fake does not
    model), and the node is matched by an XPath string built from
    ``_xpath_literal(region)`` — the fake's ``locator()`` keys on that exact
    XPath string, same convention ``_REGION_INPUT_XPATH`` used pre-#653.

    The fake models the real toggle semantics confirmed live: the LABEL is
    what gets clicked (the ``<input>`` it wraps is not actionable), and the
    input's checked state is what gets read back — so a label click flips the
    input, exactly like the real control.
    """

    def _label_xpath(self, region):
        return (
            "xpath=//label[@data-testid='RegionsTreeNode.Checkbox.label']"
            f"[normalize-space(.)={browser_masters._xpath_literal(region)}]"
        )

    def _checkbox_xpath(self, region):
        return (
            f"{self._label_xpath(region)}"
            f"//input[@data-testid='{browser_masters._REGION_CHECKBOX_TESTID}']"
        )

    def _region_node(self, region, checked, visible=True):
        """A (label, input) pair whose label click toggles the input."""
        state = {"checked": False}

        def _toggle():
            state["checked"] = not state["checked"]
            if state["checked"]:
                checked.append(region)

        label = _FakeLocatorHandle(visible=visible, on_click=_toggle)
        box = _FakeLocatorHandle(get_checked=lambda: state["checked"])
        return label, box

    def _page_for_region(self, region, checkbox_visible=True):
        launcher = _FakeLocatorHandle()
        editor = _FakeLocatorHandle()
        locators = {
            browser_masters._REGION_LAUNCHER_TESTID: _FakeLocator([launcher]),
            browser_masters._REGION_EDITOR_TESTID: _FakeLocator([editor]),
        }
        checked = []
        if checkbox_visible:
            label, box = self._region_node(region, checked)
            locators[self._label_xpath(region)] = _FakeLocator([label])
            locators[self._checkbox_xpath(region)] = _FakeLocator([box])
        return FakePage(locators=locators), checked

    def test_fills_and_selects_each_region(self):
        page, checked = self._page_for_region("Москва")

        browser_masters._set_region(page, ["Москва"])

        self.assertEqual(checked, ["Москва"])

    def test_raises_when_launcher_missing(self):
        page = FakePage(locators={})

        with self.assertRaises(BrowserSessionError):
            browser_masters._set_region(page, ["Москва"])

    def test_raises_when_checkbox_not_found(self):
        page, _ = self._page_for_region("Атлантида", checkbox_visible=False)

        with (
            patch.object(browser_masters, "_REGION_FILTER_TIMEOUT_MS", 10),
            self.assertRaises(BrowserSessionError) as ctx,
        ):
            browser_masters._set_region(page, ["Атлантида"])
        self.assertIn("Атлантида", str(ctx.exception))

    def test_does_not_select_a_decoy_whose_name_only_contains_the_region(self):
        # A decoy checkbox whose label merely CONTAINS the region name
        # (e.g. "Москва и область") must NOT be treated as a match — the
        # fake only registers a locator for the EXACT-match XPath, so a
        # lookup for "Москва" never finds "Москва и область"'s checkbox.
        launcher = _FakeLocatorHandle()
        editor = _FakeLocatorHandle()
        decoy_clicked = []
        page = FakePage(
            locators={
                browser_masters._REGION_LAUNCHER_TESTID: _FakeLocator([launcher]),
                browser_masters._REGION_EDITOR_TESTID: _FakeLocator([editor]),
                self._label_xpath("Москва и область"): _FakeLocator(
                    [
                        _FakeLocatorHandle(
                            visible=True, on_click=lambda: decoy_clicked.append(True)
                        )
                    ]
                ),
            },
        )

        with (
            patch.object(browser_masters, "_REGION_FILTER_TIMEOUT_MS", 10),
            self.assertRaises(BrowserSessionError),
        ):
            browser_masters._set_region(page, ["Москва"])
        self.assertEqual(decoy_clicked, [])

    def test_retry_does_not_reclick_launcher_and_clears_before_retyping(self):
        """A retry must start from a known state, not the previous attempt's.

        Issue #653 live testing: the launcher TOGGLES the popup, so clicking
        it again while the popup is open closes it, and ``type()`` APPENDS to
        a contenteditable, so re-typing without clearing yields
        "МоскваМосква" — which filters the tree to zero nodes and can never
        match. Either mistake turns attempts 2..N into guaranteed no-ops that
        only add latency, so both are pinned here.

        The fake models the popup already being open (the editor locator
        matches from the start) and the checkbox only appearing on the second
        attempt.
        """
        launcher_clicks = []
        launcher = _FakeLocatorHandle(on_click=lambda: launcher_clicks.append(True))
        typed = []
        presses = []
        editor = _FakeLocatorHandle(on_fill=typed.append, on_press=presses.append)

        checked = []
        label, box = self._region_node("Москва", checked)

        class _FlakyLabelLocator:
            """Matches nothing on the first attempt, one label afterwards.

            Keyed on how many times the region was TYPED (one per attempt) —
            not on how many times ``count()`` was called, which the caller
            polls repeatedly within a single attempt.
            """

            def count(self):
                return 0 if len(typed) <= 1 else 1

            def nth(self, i):
                return label

        page = FakePage(
            locators={
                browser_masters._REGION_LAUNCHER_TESTID: _FakeLocator([launcher]),
                browser_masters._REGION_EDITOR_TESTID: _FakeLocator([editor]),
                self._label_xpath("Москва"): _FlakyLabelLocator(),
                self._checkbox_xpath("Москва"): _FakeLocator([box]),
            },
        )

        with patch.object(browser_masters, "_REGION_FILTER_TIMEOUT_MS", 10):
            browser_masters._set_region(page, ["Москва"])

        self.assertEqual(checked, ["Москва"])
        # The popup was already open, so the launcher must never be clicked
        # (clicking it would have closed the popup).
        self.assertEqual(launcher_clicks, [])
        # Two attempts typed the region — each preceded by a clear, so the
        # editor never accumulates "МоскваМосква".
        self.assertEqual(typed, ["Москва", "Москва"])
        self.assertEqual(
            presses, ["ControlOrMeta+a", "Backspace", "ControlOrMeta+a", "Backspace"]
        )

    def test_clicks_launcher_when_popup_is_not_open(self):
        # Mirror of the test above: when the editor is absent (popup closed),
        # the launcher MUST be clicked to open it.
        launcher_clicks = []
        launcher = _FakeLocatorHandle(on_click=lambda: launcher_clicks.append(True))
        page = FakePage(
            locators={
                browser_masters._REGION_LAUNCHER_TESTID: _FakeLocator([launcher]),
                # No _REGION_EDITOR_TESTID entry -> `.first` raises -> count()==0.
                self._label_xpath("Москва"): _FakeLocator([]),
            },
        )

        with (
            patch.object(browser_masters, "_REGION_FILTER_TIMEOUT_MS", 10),
            self.assertRaises(BrowserSessionError),
        ):
            browser_masters._set_region(page, ["Москва"])

        self.assertEqual(len(launcher_clicks), browser_masters._REGION_OPEN_ATTEMPTS)


class TestXpathLiteral(unittest.TestCase):
    """``_xpath_literal`` — safe XPath 1.0 string-literal quoting."""

    def test_quotes_a_plain_value(self):
        self.assertEqual(browser_masters._xpath_literal("Москва"), "'Москва'")

    def test_handles_a_value_containing_a_single_quote(self):
        result = browser_masters._xpath_literal("O'Brien")
        # Must not naively produce 'O'Brien' (invalid XPath) — concat() form.
        self.assertNotEqual(result, "'O'Brien'")
        self.assertTrue(result.startswith("concat("))


class TestReadRegionTags(unittest.TestCase):
    """``_read_region_tags`` (issue #632, re-recon #653) — live-verified tag
    reader for the tree/tag-group widget's accepted selections."""

    def test_returns_every_tag_when_wrapper_present(self):
        page = FakePage(
            locators={
                browser_masters._REGION_TAGS_WRAPPER_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                browser_masters._REGION_TAG_TESTID_PATTERN: _FakeLocator(
                    [
                        _FakeLocatorHandle(text="Москва"),
                        _FakeLocatorHandle(text="Санкт-Петербург"),
                    ]
                ),
            }
        )

        self.assertEqual(
            browser_masters._read_region_tags(page), ["Москва", "Санкт-Петербург"]
        )

    def test_returns_empty_list_when_wrapper_missing(self):
        page = FakePage(locators={})

        self.assertEqual(browser_masters._read_region_tags(page), [])


class TestSetWeeklyBudgetOnCreate(unittest.TestCase):
    """``_set_weekly_budget_on_create`` (issue #632)."""

    def test_fills_field_with_bare_integer(self):
        state = {}
        handle = _FakeLocatorHandle(on_fill=lambda v: state.__setitem__("value", v))
        page = FakePage(
            locators={
                browser_masters._WEEKLY_BUDGET_INPUT_XPATH: _FakeLocator([handle])
            }
        )

        browser_masters._set_weekly_budget_on_create(page, 50000)

        self.assertEqual(state["value"], "50000")

    def test_raises_when_field_missing(self):
        page = FakePage(locators={})

        with self.assertRaises(BrowserSessionError):
            browser_masters._set_weekly_budget_on_create(page, 50000)


class TestClickTerminalButton(unittest.TestCase):
    """``_click_terminal_button`` (issue #632) — launch vs. draft, role-scoped.

    Uses ``get_by_role("button", name=text, exact=True)`` (ported from
    ``_click_save``'s fix, issue #631 review): the previous
    ``get_by_text(exact=False)`` risked matching an ancestor container
    instead of the button itself.
    """

    def test_clicks_matching_visible_button(self):
        clicks = []
        page = FakePage(
            role_elements=[
                (
                    "button",
                    browser_masters._LAUNCH_BUTTON_TEXT,
                    _FakeTextLocatorHandle(
                        visible=True, on_click=lambda: clicks.append(True)
                    ),
                )
            ]
        )

        browser_masters._click_terminal_button(
            page, browser_masters._LAUNCH_BUTTON_TEXT
        )

        self.assertEqual(len(clicks), 1)

    def test_raises_when_button_missing(self):
        page = FakePage(role_elements=[])

        with self.assertRaises(BrowserSessionError):
            browser_masters._click_terminal_button(
                page, browser_masters._SAVE_DRAFT_BUTTON_TEXT
            )

    def test_does_not_click_a_decoy_whose_name_only_contains_the_button_text(self):
        # A decoy element whose accessible name merely CONTAINS the target
        # text (e.g. "Запустить кампанию сейчас") must NOT be treated as a
        # match — exact=True requires exact equality.
        decoy_clicked = []
        page = FakePage(
            role_elements=[
                (
                    "button",
                    f"{browser_masters._LAUNCH_BUTTON_TEXT} сейчас",
                    _FakeTextLocatorHandle(
                        visible=True, on_click=lambda: decoy_clicked.append(True)
                    ),
                )
            ]
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters._click_terminal_button(
                page, browser_masters._LAUNCH_BUTTON_TEXT
            )
        self.assertEqual(decoy_clicked, [])


class TestVerifyCreated(unittest.TestCase):
    """``_verify_created`` (issue #632) — ported from ``update_master``'s
    ``_verify_saved`` (issue #631 review finding): a click on the terminal
    button is not proof Yandex accepted the form.
    """

    def _page(self, headline_values, text_values, budget_value=None):
        locators = {}
        for index, value in enumerate(headline_values):
            selector = (
                '[data-testid="'
                + browser_masters._HEADLINES_TESTID_TEMPLATE.format(index=index)
                + '"]'
            )
            locators[selector] = _FakeLocator([_FakeLocatorHandle(text=value)])
        for index, value in enumerate(text_values):
            selector = (
                '[data-testid="'
                + browser_masters._TEXTS_TESTID_TEMPLATE.format(index=index)
                + '"]'
            )
            locators[selector] = _FakeLocator([_FakeLocatorHandle(text=value)])
        if budget_value is not None:
            locators[browser_masters._WEEKLY_BUDGET_INPUT_XPATH] = _FakeLocator(
                [_FakeLocatorHandle(get_value=lambda: budget_value)]
            )
        return FakePage(locators=locators)

    def test_passes_when_every_requested_value_is_present(self):
        page = self._page(["Заголовок"], ["Текст объявления"])

        browser_masters._verify_created(
            page,
            headlines=["Заголовок"],
            texts=["Текст объявления"],
            weekly_budget=None,
        )  # must not raise

    def test_raises_when_an_unrequested_headline_variant_survives(self):
        """Extra non-empty slots are published variants (issue #655 review).

        The membership-only check this replaced ("is each requested value
        present?") passed happily while four AI-written headlines sat in the
        remaining slots. Every non-empty slot ships as an ad variant, so a
        leftover the clear missed must be a hard failure — this is the
        defense-in-depth layer behind ``_add_repeating_values``' clear.
        """
        page = self._page(
            ["Заголовок", "Центр оздоровления и китайской гимнастики!"],
            ["Текст объявления"],
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._verify_created(
                page,
                headlines=["Заголовок"],
                texts=["Текст объявления"],
                weekly_budget=None,
            )
        self.assertIn("unrequested headline variants", str(ctx.exception))
        self.assertIn("Центр оздоровления", str(ctx.exception))

    def test_raises_when_an_unrequested_text_variant_survives(self):
        # Same invariant on the ad-text slots.
        page = self._page(
            ["Заголовок"],
            ["Текст объявления", "Приходите на пробное занятие цигун!"],
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._verify_created(
                page,
                headlines=["Заголовок"],
                texts=["Текст объявления"],
                weekly_budget=None,
            )
        self.assertIn("unrequested ad-text variants", str(ctx.exception))

    def test_raises_when_a_headline_is_missing(self):
        page = self._page(["Другой заголовок"], ["Текст объявления"])

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._verify_created(
                page,
                headlines=["Заголовок"],
                texts=["Текст объявления"],
                weekly_budget=None,
            )
        self.assertIn("did not take effect as requested", str(ctx.exception))

    def test_raises_when_a_text_is_missing(self):
        page = self._page(["Заголовок"], ["Другой текст"])

        with self.assertRaises(BrowserSessionError):
            browser_masters._verify_created(
                page,
                headlines=["Заголовок"],
                texts=["Текст объявления"],
                weekly_budget=None,
            )

    def test_raises_when_weekly_budget_does_not_match(self):
        page = self._page(["Заголовок"], ["Текст объявления"], budget_value="10000")

        with self.assertRaises(BrowserSessionError):
            browser_masters._verify_created(
                page,
                headlines=["Заголовок"],
                texts=["Текст объявления"],
                weekly_budget=50000,
            )

    def test_ignores_weekly_budget_when_not_requested(self):
        page = self._page(["Заголовок"], ["Текст объявления"], budget_value="10000")

        browser_masters._verify_created(
            page,
            headlines=["Заголовок"],
            texts=["Текст объявления"],
            weekly_budget=None,
        )  # must not raise -- caller never asked for a budget


class TestCreateMaster(unittest.TestCase):
    """``create_master`` (issue #632) — end-to-end wiring of the helpers above."""

    def _full_page(self, region="Москва"):
        url_state = {}
        headline_state = []
        text_state = []
        region_checked = []
        budget_state = {}
        launch_clicks = []
        draft_clicks = []

        url_field = _FakeLocatorHandle(
            on_fill=lambda v: url_state.__setitem__("url", v)
        )
        headline_last = {"value": ""}

        def _fill_headline(v):
            headline_state.append(v)
            headline_last["value"] = v

        headline_field = _FakeLocatorHandle(
            on_fill=_fill_headline, get_value=lambda: headline_last["value"]
        )
        text_last = {"value": ""}

        def _fill_text(v):
            text_state.append(v)
            text_last["value"] = v

        text_field = _FakeLocatorHandle(
            on_fill=_fill_text, get_value=lambda: text_last["value"]
        )
        region_launcher = _FakeLocatorHandle()
        region_editor = _FakeLocatorHandle()
        budget_field = _FakeLocatorHandle(
            on_fill=lambda v: budget_state.__setitem__("value", v),
            get_value=lambda: budget_state.get("value", ""),
        )

        next_button = _FakeLocatorHandle()

        # The real page always renders every slot (issue #653 recon: exactly
        # 5 headline / 3 text slots, no "add another" control) — registering
        # only slot 0 was unrealistic and hid the issue #655 round-2 finding
        # that a click failure on an UNUSED slot must still be fatal. Slot 0
        # is the caller-filled one (headline_field/text_field, wired to
        # headline_state/text_state below); the rest start genuinely empty,
        # same as the real create page's trailing slots.
        headline_selector = (
            '[data-testid="'
            + browser_masters._HEADLINES_TESTID_TEMPLATE.format(index=0)
            + '"]'
        )
        text_selector = (
            '[data-testid="'
            + browser_masters._TEXTS_TESTID_TEMPLATE.format(index=0)
            + '"]'
        )
        extra_headline_selectors = {
            '[data-testid="'
            + browser_masters._HEADLINES_TESTID_TEMPLATE.format(index=i)
            + '"]': _FakeLocator([_FakeContentEditableHandle(text="")])
            for i in range(1, browser_masters._HEADLINES_SLOT_COUNT)
        }
        extra_text_selectors = {
            '[data-testid="'
            + browser_masters._TEXTS_TESTID_TEMPLATE.format(index=i)
            + '"]': _FakeLocator([_FakeContentEditableHandle(text="")])
            for i in range(1, browser_masters._TEXTS_SLOT_COUNT)
        }
        region_label_xpath = (
            "xpath=//label[@data-testid='RegionsTreeNode.Checkbox.label']"
            f"[normalize-space(.)={browser_masters._xpath_literal(region)}]"
        )
        region_checkbox_xpath = (
            f"{region_label_xpath}"
            f"//input[@data-testid='{browser_masters._REGION_CHECKBOX_TESTID}']"
        )
        # The label is what gets clicked; the input is what gets read back
        # (confirmed live — see _set_region). Model the real toggle.
        region_state = {"checked": False}

        def _toggle_region():
            region_state["checked"] = not region_state["checked"]
            if region_state["checked"]:
                region_checked.append(region)

        page = FakePage(
            locators={
                browser_masters._CREATE_URL_INPUT_TESTID: _FakeLocator([url_field]),
                browser_masters._CREATE_NEXT_BUTTON_TESTID: _FakeLocator([next_button]),
                headline_selector: _FakeLocator([headline_field]),
                text_selector: _FakeLocator([text_field]),
                **extra_headline_selectors,
                **extra_text_selectors,
                browser_masters._REGION_LAUNCHER_TESTID: _FakeLocator(
                    [region_launcher]
                ),
                browser_masters._REGION_EDITOR_TESTID: _FakeLocator([region_editor]),
                region_label_xpath: _FakeLocator(
                    [_FakeLocatorHandle(visible=True, on_click=_toggle_region)]
                ),
                region_checkbox_xpath: _FakeLocator(
                    [_FakeLocatorHandle(get_checked=lambda: region_state["checked"])]
                ),
                browser_masters._WEEKLY_BUDGET_INPUT_XPATH: _FakeLocator(
                    [budget_field]
                ),
            },
            role_elements=[
                (
                    "button",
                    browser_masters._LAUNCH_BUTTON_TEXT,
                    _FakeTextLocatorHandle(
                        visible=True, on_click=lambda: launch_clicks.append(True)
                    ),
                ),
                (
                    "button",
                    browser_masters._SAVE_DRAFT_BUTTON_TEXT,
                    _FakeTextLocatorHandle(
                        visible=True, on_click=lambda: draft_clicks.append(True)
                    ),
                ),
            ],
            text_buttons={
                browser_masters._CREATE_INVALID_URL_TEXT: _FakeGetByTextLocator([]),
                "Регион показов": _FakeGetByTextLocator([_FakeTextLocatorHandle()]),
            },
        )
        return page, {
            "url": url_state,
            "headlines": headline_state,
            "texts": text_state,
            "region_checked": region_checked,
            "budget": budget_state,
            "launch_clicks": launch_clicks,
            "draft_clicks": draft_clicks,
        }

    def test_launches_by_default(self):
        page, state = self._full_page()

        result = browser_masters.create_master(
            page,
            "https://ksamata.ru/",
            headlines=["Заголовок"],
            texts=["Текст объявления"],
            regions=["Москва"],
        )

        self.assertEqual(state["url"]["url"], "https://ksamata.ru/")
        self.assertEqual(state["headlines"], ["Заголовок"])
        self.assertEqual(state["texts"], ["Текст объявления"])
        self.assertEqual(state["region_checked"], ["Москва"])
        self.assertEqual(len(state["launch_clicks"]), 1)
        self.assertEqual(len(state["draft_clicks"]), 0)
        self.assertEqual(
            result,
            {
                "LandingUrl": "https://ksamata.ru/",
                "Headlines": ["Заголовок"],
                "Texts": ["Текст объявления"],
                "Regions": ["Москва"],
                "Launched": True,
            },
        )
        self.assertEqual(page.navigated_to, [browser_masters.WIZARD_CREATE_URL])
        self.assertEqual(page.goto_wait_until, "commit")

    def test_saves_as_draft_when_launch_false(self):
        page, state = self._full_page()

        result = browser_masters.create_master(
            page,
            "https://ksamata.ru/",
            headlines=["Заголовок"],
            texts=["Текст объявления"],
            regions=["Москва"],
            launch=False,
        )

        self.assertEqual(len(state["draft_clicks"]), 1)
        self.assertEqual(len(state["launch_clicks"]), 0)
        self.assertFalse(result["Launched"])

    def test_includes_weekly_budget_when_given(self):
        page, state = self._full_page()

        result = browser_masters.create_master(
            page,
            "https://ksamata.ru/",
            headlines=["Заголовок"],
            texts=["Текст объявления"],
            regions=["Москва"],
            weekly_budget=50000,
        )

        self.assertEqual(state["budget"]["value"], "50000")
        self.assertEqual(result["WeeklyBudget"], 50000)

    def test_omits_weekly_budget_key_when_not_given(self):
        page, _ = self._full_page()

        result = browser_masters.create_master(
            page,
            "https://ksamata.ru/",
            headlines=["Заголовок"],
            texts=["Текст объявления"],
            regions=["Москва"],
        )

        self.assertNotIn("WeeklyBudget", result)

    def test_raises_value_error_when_no_headlines(self):
        page, _ = self._full_page()

        with self.assertRaises(ValueError):
            browser_masters.create_master(
                page, "https://ksamata.ru/", headlines=[], texts=["t"], regions=["r"]
            )

    def test_raises_value_error_when_no_texts(self):
        page, _ = self._full_page()

        with self.assertRaises(ValueError):
            browser_masters.create_master(
                page, "https://ksamata.ru/", headlines=["h"], texts=[], regions=["r"]
            )

    def test_raises_value_error_when_no_regions(self):
        page, _ = self._full_page()

        with self.assertRaises(ValueError):
            browser_masters.create_master(
                page, "https://ksamata.ru/", headlines=["h"], texts=["t"], regions=[]
            )

    def test_invalid_url_stops_before_step2(self):
        page, _ = self._full_page()
        page._text_buttons[browser_masters._CREATE_INVALID_URL_TEXT] = (
            _FakeGetByTextLocator([_FakeTextLocatorHandle()])
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters.create_master(
                page,
                "not-a-valid-url",
                headlines=["h"],
                texts=["t"],
                regions=["Москва"],
            )

    def test_step1_timeout_raises_when_url_field_never_renders(self):
        """issue #685: ``goto`` now uses ``wait_until="commit"``, which
        returns before the page has any real content — the create page's
        step 1 field must be waited on explicitly, and a page that never
        renders it must fail with a specific ``BrowserSessionError``, not an
        opaque markup-changed error from ``_fill_landing_url`` racing an
        unrendered field.
        """
        page, _ = self._full_page()
        del page._locators[browser_masters._CREATE_URL_INPUT_TESTID]

        with patch.object(browser_masters, "_CREATE_STEP1_TIMEOUT_MS", 10):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.create_master(
                    page,
                    "https://ksamata.ru/",
                    headlines=["h"],
                    texts=["t"],
                    regions=["Москва"],
                )
        self.assertIn("step 1", str(ctx.exception))

    def test_raises_before_launch_when_a_headline_slot_did_not_actually_clear(
        self,
    ):
        """The terminal button must NOT be clicked if pre-click state is
        already wrong (issue #655 round-3 review, Codex).

        Every round of this issue's review (1, 2, 3) found a new way for a
        slot's true content to diverge from what ``_add_repeating_values``
        believes it wrote — a click failure, an unused slot, a no-op
        keypress that succeeds without exception. ``_verify_created``
        already re-reads and compares state correctly; the actual defect was
        never in the check, it was that ``create_master`` only ran that
        check AFTER ``_click_terminal_button`` already launched the
        campaign. This pins the fix at the level that closes ALL variants:
        the state check must gate the click, not just report on it
        afterwards.

        Sabotage: slot 0's ``press()`` succeeds without raising (models a
        prevented Backspace / lost selection / re-render race — issue #655
        round-3 finding) but never actually clears the field, so
        ``.type()`` appends onto the stale AI copy instead of replacing it.
        """
        page, state = self._full_page()
        stuck_handle = _FakeLocatorHandle(text="Старый заголовок")
        stuck_handle.press = lambda key: None  # succeeds, does nothing
        stuck_handle.type = lambda value, delay=None: None  # never reflects
        headline_selector = (
            '[data-testid="'
            + browser_masters._HEADLINES_TESTID_TEMPLATE.format(index=0)
            + '"]'
        )
        page._locators[headline_selector] = _FakeLocator([stuck_handle])

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.create_master(
                page,
                "https://ksamata.ru/",
                headlines=["Заголовок"],
                texts=["Текст объявления"],
                regions=["Москва"],
            )
        # The whole point: caught BEFORE the irreversible click, not after.
        self.assertEqual(len(state["launch_clicks"]), 0)
        self.assertIn("before clicking", str(ctx.exception))

    def test_raises_when_terminal_click_does_not_actually_save_headline(self):
        # The headline field reflects correctly right up until the click,
        # but Yandex's OWN post-click processing (client-side validation on
        # submit, not on type) reverts it — the pre-click gate above cannot
        # catch this, since the field looked correct at check time and only
        # diverges as a side effect of the click itself. _verify_created
        # remains the backstop for this case.
        page, state = self._full_page()
        stuck_handle = _FakeLocatorHandle(text="Старый заголовок")

        def _type(value, delay=None):
            stuck_handle._text = value

        stuck_handle.type = _type
        headline_selector = (
            '[data-testid="'
            + browser_masters._HEADLINES_TESTID_TEMPLATE.format(index=0)
            + '"]'
        )
        page._locators[headline_selector] = _FakeLocator([stuck_handle])

        launch_handle = next(
            handle
            for role, name, handle in page._role_elements
            if role == "button" and name == browser_masters._LAUNCH_BUTTON_TEXT
        )
        real_on_click = launch_handle._on_click

        def _revert_then_click():
            stuck_handle._text = "Старый заголовок"
            if real_on_click is not None:
                real_on_click()

        launch_handle._on_click = _revert_then_click

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.create_master(
                page,
                "https://ksamata.ru/",
                headlines=["Заголовок"],
                texts=["Текст объявления"],
                regions=["Москва"],
            )
        self.assertEqual(len(state["launch_clicks"]), 1)  # the click DID happen
        self.assertIn("did not take effect as requested", str(ctx.exception))


class TestMastersAddCommand(unittest.TestCase):
    """CLI wiring for `masters add` (issue #632)."""

    def setUp(self):
        self.runner = CliRunner()

    def test_registered(self):
        result = self.runner.invoke(cli, ["masters", "add", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_has_no_login_option(self):
        result = self.runner.invoke(cli, ["masters", "add", "--help"])
        self.assertNotIn("--login", result.output)

    def test_headline_text_region_are_required(self):
        result = self.runner.invoke(cli, ["masters", "add", "https://ksamata.ru/"])
        self.assertNotEqual(result.exit_code, 0)

    def test_calls_create_master_with_given_fields(self):
        with (
            patch("direct_cli.browser.masters.create_master") as mock_create,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_create.return_value = {"Launched": True}
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "add",
                    "https://ksamata.ru/",
                    "--headline",
                    "Заголовок 1",
                    "--headline",
                    "Заголовок 2",
                    "--text",
                    "Текст",
                    "--region",
                    "Москва",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        mock_create.assert_called_once()
        _, kwargs = mock_create.call_args
        self.assertEqual(kwargs["headlines"], ["Заголовок 1", "Заголовок 2"])
        self.assertEqual(kwargs["texts"], ["Текст"])
        self.assertEqual(kwargs["regions"], ["Москва"])
        self.assertTrue(kwargs["launch"])

    def test_draft_flag_disables_launch(self):
        with (
            patch("direct_cli.browser.masters.create_master") as mock_create,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_create.return_value = {"Launched": False}
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "add",
                    "https://ksamata.ru/",
                    "--headline",
                    "h",
                    "--text",
                    "t",
                    "--region",
                    "Москва",
                    "--draft",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        _, kwargs = mock_create.call_args
        self.assertFalse(kwargs["launch"])

    def test_passes_weekly_budget(self):
        with (
            patch("direct_cli.browser.masters.create_master") as mock_create,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_create.return_value = {"Launched": True}
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "add",
                    "https://ksamata.ru/",
                    "--headline",
                    "h",
                    "--text",
                    "t",
                    "--region",
                    "Москва",
                    "--weekly-budget",
                    "50000",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        _, kwargs = mock_create.call_args
        self.assertEqual(kwargs["weekly_budget"], 50000)

    def test_region_or_region_id_is_required(self):
        result = self.runner.invoke(
            cli,
            [
                "masters",
                "add",
                "https://ksamata.ru/",
                "--headline",
                "h",
                "--text",
                "t",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--region/--region-id", result.output)

    def test_region_id_resolves_via_geo_regions_dictionary(self):
        service = Mock()
        service.post.return_value = Mock(
            data={
                "result": {
                    "GeoRegions": [{"GeoRegionId": 213, "GeoRegionName": "Москва"}]
                }
            }
        )
        client = Mock()
        client.dictionaries.return_value = service

        with (
            patch("direct_cli.browser.masters.create_master") as mock_create,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
            patch("direct_cli.commands.masters.create_client", return_value=client),
        ):
            mock_create.return_value = {"Launched": True}
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "add",
                    "https://ksamata.ru/",
                    "--headline",
                    "h",
                    "--text",
                    "t",
                    "--region-id",
                    "213",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        body = service.post.call_args_list[0].kwargs["data"]
        self.assertEqual(body["method"], "getGeoRegions")
        self.assertEqual(body["params"]["SelectionCriteria"]["RegionIds"], [213])
        _, kwargs = mock_create.call_args
        self.assertEqual(kwargs["regions"], ["Москва"])

    def test_region_and_region_id_combine(self):
        service = Mock()
        service.post.return_value = Mock(
            data={
                "result": {
                    "GeoRegions": [
                        {"GeoRegionId": 2, "GeoRegionName": "Санкт-Петербург"}
                    ]
                }
            }
        )
        client = Mock()
        client.dictionaries.return_value = service

        with (
            patch("direct_cli.browser.masters.create_master") as mock_create,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
            patch("direct_cli.commands.masters.create_client", return_value=client),
        ):
            mock_create.return_value = {"Launched": True}
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "add",
                    "https://ksamata.ru/",
                    "--headline",
                    "h",
                    "--text",
                    "t",
                    "--region",
                    "Москва",
                    "--region-id",
                    "2",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        _, kwargs = mock_create.call_args
        self.assertEqual(kwargs["regions"], ["Москва", "Санкт-Петербург"])

    def test_unknown_region_id_raises_usage_error(self):
        service = Mock()
        service.post.return_value = Mock(data={"result": {"GeoRegions": []}})
        client = Mock()
        client.dictionaries.return_value = service

        with (
            patch("direct_cli.browser.masters.create_master") as mock_create,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
            patch("direct_cli.commands.masters.create_client", return_value=client),
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "add",
                    "https://ksamata.ru/",
                    "--headline",
                    "h",
                    "--text",
                    "t",
                    "--region-id",
                    "999999",
                ],
            )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Unknown --region-id value(s): 999999", result.output)
        mock_create.assert_not_called()


class TestResolveRegionIds(unittest.TestCase):
    """Unit tests for `_resolve_region_ids` (issue #652)."""

    def test_empty_region_ids_skips_api_call(self):
        from direct_cli.commands.masters import _resolve_region_ids

        with patch("direct_cli.commands.masters.create_client") as mock_create_client:
            result = _resolve_region_ids(Mock(), ())

        self.assertEqual(result, [])
        mock_create_client.assert_not_called()

    def test_resolves_multiple_ids_preserving_order(self):
        from direct_cli.commands.masters import _resolve_region_ids

        service = Mock()
        service.post.return_value = Mock(
            data={
                "result": {
                    "GeoRegions": [
                        {"GeoRegionId": 2, "GeoRegionName": "Санкт-Петербург"},
                        {"GeoRegionId": 213, "GeoRegionName": "Москва"},
                    ]
                }
            }
        )
        client = Mock()
        client.dictionaries.return_value = service

        with patch("direct_cli.commands.masters.create_client", return_value=client):
            result = _resolve_region_ids(Mock(), (213, 2))

        self.assertEqual(result, ["Москва", "Санкт-Петербург"])

    def test_ambiguous_region_name_raises_usage_error(self):
        """Two distinct RegionIds sharing one GeoRegionName must not resolve
        silently — `_set_region`'s browser-side exact-name match would click
        whichever same-named option appears first, risking a live launch
        against the wrong geography (issue #652 follow-up)."""
        from direct_cli.commands.masters import _resolve_region_ids

        service = Mock()
        service.post.side_effect = [
            Mock(
                data={
                    "result": {
                        "GeoRegions": [
                            {"GeoRegionId": 111, "GeoRegionName": "Сосновка"}
                        ]
                    }
                }
            ),
            Mock(
                data={
                    "result": {
                        "GeoRegions": [
                            {"GeoRegionId": 111, "GeoRegionName": "Сосновка"},
                            {"GeoRegionId": 222, "GeoRegionName": "Сосновка"},
                        ]
                    }
                }
            ),
        ]
        client = Mock()
        client.dictionaries.return_value = service

        with patch("direct_cli.commands.masters.create_client", return_value=client):
            with self.assertRaises(click.UsageError) as cm:
                _resolve_region_ids(Mock(), (111,))

        self.assertIn("ambiguous", str(cm.exception).lower())
        self.assertIn("Сосновка", str(cm.exception))
        self.assertIn("--region", str(cm.exception))

        second_call_body = service.post.call_args_list[1].kwargs["data"]
        self.assertIn("SelectionCriteria", second_call_body["params"])
        self.assertEqual(
            second_call_body["params"]["SelectionCriteria"]["ExactNames"],
            ["Сосновка"],
        )

    def test_unique_region_name_resolves_normally(self):
        """A RegionId whose name has no duplicates elsewhere in the full
        dictionary must still resolve without raising."""
        from direct_cli.commands.masters import _resolve_region_ids

        service = Mock()
        service.post.side_effect = [
            Mock(
                data={
                    "result": {
                        "GeoRegions": [{"GeoRegionId": 213, "GeoRegionName": "Москва"}]
                    }
                }
            ),
            Mock(
                data={
                    "result": {
                        "GeoRegions": [
                            {"GeoRegionId": 213, "GeoRegionName": "Москва"},
                            {"GeoRegionId": 2, "GeoRegionName": "Санкт-Петербург"},
                        ]
                    }
                }
            ),
        ]
        client = Mock()
        client.dictionaries.return_value = service

        with patch("direct_cli.commands.masters.create_client", return_value=client):
            result = _resolve_region_ids(Mock(), (213,))

        self.assertEqual(result, ["Москва"])


if __name__ == "__main__":
    unittest.main()
