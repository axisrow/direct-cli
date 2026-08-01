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
from unittest.mock import patch

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

    def __init__(self, locators=None, body_text=""):
        self._locators = locators or {}
        self._body_text = body_text
        self.navigated_to = []

    def goto(self, url, wait_until=None):
        self.navigated_to.append(url)

    def locator(self, selector):
        return self._locators.get(selector, _FakeLocator([]))

    def inner_text(self, selector=None):
        return self._body_text


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


class TestBrowserSessionErrors(unittest.TestCase):
    def test_browser_captcha_error_is_a_browser_session_error(self):
        self.assertTrue(issubclass(BrowserCaptchaError, BrowserSessionError))


if __name__ == "__main__":
    unittest.main()
