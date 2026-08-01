"""
Tests for `direct masters` — the Мастер кампаний (Campaign Wizard) browser group.

Мастер кампаний has no API surface at all (see direct_cli/browser/__init__.py),
so unlike every other command module these tests never call a real API and
never launch a real browser. The DOM parser in direct_cli/browser/masters.py is
exercised against small fake Page/Locator objects that implement just the
Playwright surface the parser calls (locator/nth/count/inner_text/
get_attribute/goto) — see tests/fixtures/masters_wizard_overview.html for the
live page structure these fakes are modeled on.
"""

import unittest
from pathlib import Path
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner

from direct_cli.browser import masters as browser_masters
from direct_cli.browser.masters import PlaywrightError
from direct_cli.browser.session import BrowserCaptchaError, BrowserSessionError
from direct_cli.cli import cli


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


class FakePage:
    """A Page whose ``locator(selector)`` result is pre-scripted per selector."""

    def __init__(self, locators=None, body_text="", html="<html></html>"):
        self._locators = locators or {}
        self._body_text = body_text
        self._html = html
        self.navigated_to = []
        self.goto_wait_until = None

    def goto(self, url, wait_until=None):
        self.navigated_to.append(url)
        self.goto_wait_until = wait_until

    def locator(self, selector):
        return self._locators.get(selector, _FakeLocator([]))

    def inner_text(self, selector=None):
        return self._body_text

    def content(self):
        return self._html


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

    def test_masters_get_requires_login(self):
        # No --login, no active profile/env in this invocation's environment ->
        # the UsageError from commands/masters.py::_require_login must surface.
        result = self.runner.invoke(
            cli, ["masters", "get", "123"], env={"YANDEX_DIRECT_LOGIN": ""}
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("login is required", result.output.lower())

    def test_masters_list_missing_playwright_shows_install_hint(self):
        with patch.dict(
            "sys.modules", {"playwright": None, "playwright.sync_api": None}
        ):
            result = self.runner.invoke(
                cli,
                ["masters", "list", "--login", "ksamatadirect"],
            )
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

        from direct_cli.commands.masters import _open_session

        # A genuine contextmanager generator whose body raises on __enter__,
        # exactly like open_chrome_session — not a mock with side_effect=,
        # which would raise on call and prove nothing about this bug.
        @contextlib.contextmanager
        def _fake_open_chrome_session(**kwargs):
            raise BrowserSessionError("boom from generator body")
            yield  # pragma: no cover - unreachable, contextmanager shape only

        with patch(
            "direct_cli.browser.session.open_chrome_session",
            _fake_open_chrome_session,
        ):
            with self.assertRaises(click.ClickException) as cm:
                with _open_session(
                    headful=False, profile_dir=None, chrome_profile="Default"
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


class TestFetchMastersList(unittest.TestCase):
    """Grid-row detection: keyed off the /wizard/campaigns/{id}/ href signal."""

    def test_detects_master_rows_only(self):
        page = FakePage(
            locators={
                "a[href*='/wizard/campaigns/']": _FakeLocator(
                    [
                        _FakeLocatorHandle(
                            text="Мастер ИД Исцеляющий Детокс (холодный)",
                            attrs={
                                "href": (
                                    "/wizard/campaigns/72349978/?ulogin=ksamatadirect"
                                )
                            },
                        ),
                        _FakeLocatorHandle(
                            text="Мастер ИЖ Источник Жизни (холодный)",
                            attrs={
                                "href": (
                                    "/wizard/campaigns/107707079/?ulogin=ksamatadirect"
                                )
                            },
                        ),
                    ]
                )
            }
        )

        result = browser_masters.fetch_masters_list(page, "ksamatadirect")

        self.assertEqual(
            result,
            [
                {
                    "CampaignId": 72349978,
                    "Name": "Мастер ИД Исцеляющий Детокс (холодный)",
                },
                {
                    "CampaignId": 107707079,
                    "Name": "Мастер ИЖ Источник Жизни (холодный)",
                },
            ],
        )

    def test_deduplicates_repeated_hrefs(self):
        # A row can render more than one link to the same wizard URL (e.g. the
        # campaign name AND the "Перейти" action both point at it) — the
        # parser must not double-count the campaign.
        handle = _FakeLocatorHandle(
            text="Мастер X",
            attrs={"href": "/wizard/campaigns/1/?ulogin=acc"},
        )
        page = FakePage(
            locators={"a[href*='/wizard/campaigns/']": _FakeLocator([handle, handle])}
        )

        result = browser_masters.fetch_masters_list(page, "acc")

        self.assertEqual(result, [{"CampaignId": 1, "Name": "Мастер X"}])

    def test_empty_grid_returns_empty_list_with_warning(self):
        page = FakePage(locators={})

        with patch("direct_cli.browser.masters.print_warning") as warn:
            result = browser_masters.fetch_masters_list(page, "acc")

        self.assertEqual(result, [])
        warn.assert_called_once()


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

        result = browser_masters.fetch_master(page, 72349978, "ksamatadirect")

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
        result = browser_masters.fetch_master(page, 1, "acc")
        self.assertEqual(result["Status"], "ACTIVE")

    def test_partial_result_on_unrecognised_sections(self):
        # A page with none of the expected sections must not raise — every
        # extractor degrades to omitting its field plus a warning, per the
        # module's "best-effort" contract (see fetch_master docstring).
        page = FakePage(locators={}, body_text="something Yandex changed the markup to")

        with patch("direct_cli.browser.masters.print_warning") as warn:
            result = browser_masters.fetch_master(page, 999, "acc")

        self.assertEqual(result, {"CampaignId": 999})
        self.assertGreaterEqual(warn.call_count, 3)  # name, status, landing, stats


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
            browser_masters.fetch_masters_list(page, "acc")

    def test_fetch_master_raises_on_captcha_page(self):
        page = FakePage(locators={}, html="<script>smartCaptcha.render()</script>")

        with self.assertRaises(BrowserCaptchaError):
            browser_masters.fetch_master(page, 1, "acc")


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
            browser_masters.fetch_masters_list(page, "acc")

    def test_fetch_master_raises_on_login_page(self):
        page = FakePage(locators={}, html="<body>Войдите с Яндекс ID</body>")
        from direct_cli.browser.session import BrowserAuthError

        with self.assertRaises(BrowserAuthError):
            browser_masters.fetch_master(page, 1, "acc")

    def test_fetch_masters_list_waits_for_domcontentloaded_not_networkidle(self):
        # #634: networkidle never settles on Yandex's login page (it holds
        # long-poll connections), which is what turned an auth failure into
        # an opaque 30s timeout instead of a clear error. Guard against a
        # silent regression back to networkidle.
        page = FakePage(locators={})
        browser_masters.fetch_masters_list(page, "acc")
        self.assertEqual(page.goto_wait_until, "domcontentloaded")

    def test_fetch_master_waits_for_domcontentloaded_not_networkidle(self):
        page = FakePage(locators={})
        browser_masters.fetch_master(page, 1, "acc")
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
