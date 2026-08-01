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
    """One matched element — the subset of Playwright's Locator API the parser uses."""

    def __init__(self, text="", attrs=None, raises=False):
        self._text = text
        self._attrs = attrs or {}
        self._raises = raises

    def inner_text(self):
        if self._raises:
            # Real Playwright raises its own Error (a TimeoutError subclass) when
            # an element is missing — masters.py's `except PlaywrightError` must
            # catch exactly this class, so the test uses the real one too.
            raise PlaywrightError("element not found")
        return self._text

    def get_attribute(self, name):
        return self._attrs.get(name)


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
    ):
        self._locators = locators or {}
        self._body_text = body_text
        self._html = html
        self.navigated_to = []
        self.goto_wait_until = None
        # If set, matched by expect_response()'s predicate once goto() has
        # been called inside its `with` block — models the grid firing its
        # GridCampaigns XHR during navigation.
        self._grid_response = grid_response
        self.request = api_request or _FakeApiRequestContext()
        # {text: _FakeGetByTextLocator} for get_by_text() — used by
        # suspend_master/resume_master's action-button click.
        self._text_buttons = text_buttons or {}

    def goto(self, url, wait_until=None):
        self.navigated_to.append(url)
        self.goto_wait_until = wait_until

    def expect_response(self, predicate, timeout=None):
        return _FakeExpectResponse(self, predicate)

    def eval_on_selector_all(self, selector, expression):
        return []

    def locator(self, selector):
        return self._locators.get(selector, _FakeLocator([]))

    def get_by_text(self, text, exact=False):
        return self._text_buttons.get(text, _FakeGetByTextLocator([]))

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


class _FakeChromium:
    def __init__(self, browser):
        self._browser = browser
        self.launch_kwargs = None

    def launch(self, **kwargs):
        self.launch_kwargs = kwargs
        return self._browser


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


class TestOpenSessionTiers(unittest.TestCase):
    """_open_session's three-tier resolution: explicit profile / saved
    session / fresh-decrypt fallback (with auth-error self-heal retry)."""

    def _list_ctx(self, args=None):
        from direct_cli.commands.masters import masters

        list_cmd = masters.commands["list"]
        return list_cmd.make_context("list", list(args or []))

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
