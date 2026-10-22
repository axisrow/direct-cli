"""
Tests for direct_cli/browser/ad_elements.py — the banners-grid per-element
restriction reader (issue #892).

The fixture (``tests/fixtures/ad_elements_payloads.json``) holds the LIVE
shapes of the banners grid's three data calls, captured 2026-10-22 (account
``ksamatairect``-owned campaign 71149490, group 5775404731) and trimmed to
three ads: the warned target ad with 7 titles × 1 text, a second warned ad
carrying an image entry, and a clean ad. Everything runs offline: the
capture test drives a fake page whose ``on``-registered listener receives
canned responses, mirroring how the module consumes the real page.
"""

import json
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from direct_cli.browser import ad_elements
from direct_cli.browser.session import BrowserAuthError, BrowserSessionError

_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "ad_elements_payloads.json").read_text(
        encoding="utf-8"
    )
)

TARGET_AD = "1923626368383074682"
SECOND_WARNED_AD = "1923626277116170752"
CLEAN_AD = "1916262659838535640"


def _build():
    return ad_elements.build_ad_elements(
        _FIXTURE["ads_list"],
        _FIXTURE["ad_disclaimers"],
        _FIXTURE["ads_batch_get"],
    )


class TestBuildAdElements(unittest.TestCase):
    def setUp(self):
        self.elements = _build()

    def _target(self, element_type, **filters):
        found = [
            e
            for e in self.elements
            if e["ad_id"] == TARGET_AD and e["element_type"] == element_type
        ]
        for key, value in filters.items():
            found = [e for e in found if e.get(key) == value]
        return found

    def test_target_ad_yields_exactly_seven_title_elements(self):
        titles = self._target("title")
        self.assertEqual(len(titles), 7)
        # 1-based, no gaps: the issue's acceptance counts headlines.
        self.assertEqual([t["title_index"] for t in titles], list(range(1, 8)))

    def test_warned_ad_titles_carry_the_medicine_disclaimer(self):
        # The issue's live example: this headline is one of the warned ones.
        warned = [
            t
            for t in self._target("title")
            if "Как убрать дискомфорт в спине за 5 дней" in t["text"]
        ]
        self.assertEqual(len(warned), 1)
        warnings = warned[0]["warnings"]
        self.assertEqual(len(warnings), 1)
        raw = warnings[0]["raw_tooltip"]
        self.assertIn("Есть противопоказания. Посоветуйтесь с врачом.", raw)
        self.assertIn("Медицина и фармацевтика", raw)
        self.assertIn("MODERATION_FLAGS_MED_SERVICES", warnings[0]["reason"])

    def test_every_title_of_a_warned_ad_carries_the_ad_level_warning(self):
        """The warning is an AD-level fact (the UI's own popup says
        «Добавлено 1 предупреждение» for the whole ad); the reader attaches
        it to every element of that ad rather than inventing a per-headline
        split no data surface provides."""
        titles = self._target("title")
        self.assertTrue(titles)
        for title in titles:
            self.assertEqual(len(title["warnings"]), 1)

    def test_target_ad_text_element(self):
        texts = self._target("text")
        self.assertEqual(len(texts), 1)
        self.assertEqual(
            texts[0]["text"],
            "Скованность в спине и хруст? Гибкость позвоночника. Бесплатный курс.",
        )

    def test_clean_ad_elements_have_no_warnings(self):
        clean = [e for e in self.elements if e["ad_id"] == CLEAN_AD]
        self.assertTrue(clean)
        for element in clean:
            self.assertEqual(element["warnings"], [])

    def test_image_element_from_disclaimers_payload(self):
        # The live capture attaches the image entry to the CLEAN ad's row.
        images = [
            e
            for e in self.elements
            if e["ad_id"] == CLEAN_AD and e["element_type"] == "image"
        ]
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["text"], "тестиюль2026 ad_14")
        # moderationVerdict is null here — no extra warning on the asset,
        # but the ad-level warning list is empty for a clean ad either way.
        self.assertEqual(images[0]["warnings"], [])

    def test_metrics_from_batch_get(self):
        target = self._target("title")[0]
        self.assertEqual(target["metrics"]["shows"], 6450)
        self.assertEqual(target["metrics"]["clicks"], 21)
        # cost_with_tax 212173800 micros -> 212.17 roubles.
        self.assertEqual(target["metrics"]["cost"], 212.17)

    def test_clean_ad_gets_metrics_when_batch_get_covers_it(self):
        """batchGet is not warning-scoped: a clean ad still reports its
        stats, it just reports no warnings."""
        clean = [e for e in self.elements if e["ad_id"] == CLEAN_AD]
        self.assertEqual(clean[0]["warnings"], [])
        self.assertEqual(clean[0]["metrics"]["shows"], 1546)

    def test_shared_ad_metadata_on_elements(self):
        target = self._target("title")[0]
        self.assertEqual(target["ad_group_id"], "5775404731")
        self.assertEqual(target["ad_status"], "RUN_WARN")
        self.assertEqual(target["moderation_flags"], ["MODERATION_FLAGS_MED_SERVICES"])
        self.assertEqual(target["href"], "https://lp.ksamata.ru/rd_yan")

    def test_ad_with_no_composition_still_surfaces_its_warnings(self):
        ads_payload = {
            "ads": [
                {
                    "id": "999",
                    "titles": [],
                    "bodies": [],
                    "moderation_flags": ["MODERATION_FLAGS_MED_SERVICES"],
                    "aggregated_status": {"status": "RUN_WARN", "reasons": ["R1"]},
                }
            ]
        }
        elements = ad_elements.build_ad_elements(ads_payload, {"data": {}})
        self.assertEqual(len(elements), 1)
        self.assertEqual(elements[0]["element_type"], "ad")
        self.assertIn(
            "MODERATION_FLAGS_MED_SERVICES", elements[0]["warnings"][0]["reason"]
        )

    def test_empty_structured_image_verdict_is_not_a_warning(self):
        """Live МК sweep 2026-10-22: clean image assets carry
        {"disclaimer": {"title": "", "description": ""}} — that must not
        manufacture a warning."""
        ads_payload = {
            "ads": [
                {
                    "id": "1",
                    "titles": ["t"],
                    "bodies": [],
                    "moderation_flags": [],
                    "aggregated_status": {"status": "RUN", "reasons": []},
                }
            ]
        }
        disclaimers_payload = {
            "data": {
                "client": {
                    "ads": {
                        "rowset": [
                            {
                                "id": "1",
                                "adaptiveTextImages": [
                                    {
                                        "name": "pic",
                                        "moderationVerdict": {
                                            "disclaimer": {
                                                "title": "",
                                                "description": "",
                                            }
                                        },
                                    }
                                ],
                            }
                        ]
                    }
                }
            }
        }
        elements = ad_elements.build_ad_elements(ads_payload, disclaimers_payload)
        image = next(e for e in elements if e["element_type"] == "image")
        self.assertEqual(image["warnings"], [])
        # And a verdict with actual content still warns, stringified.
        disclaimers_payload["data"]["client"]["ads"]["rowset"][0]["adaptiveTextImages"][
            0
        ]["moderationVerdict"] = {"disclaimer": {"title": "реклама табака"}}
        elements = ad_elements.build_ad_elements(ads_payload, disclaimers_payload)
        image = next(e for e in elements if e["element_type"] == "image")
        self.assertIsInstance(image["warnings"][0]["reason"], str)
        self.assertIn("табака", image["warnings"][0]["reason"])

    def test_structurally_changed_disclaimers_payload_degrades_to_flags(self):
        elements = ad_elements.build_ad_elements(
            _FIXTURE["ads_list"], {"data": {"unexpected": True}}
        )
        target = [
            e
            for e in elements
            if e["ad_id"] == TARGET_AD and e["element_type"] == "title"
        ]
        self.assertEqual(len(target), 7)
        self.assertIn(
            "MODERATION_FLAGS_MED_SERVICES", target[0]["warnings"][0]["reason"]
        )
        self.assertNotIn(
            "Есть противопоказания", target[0]["warnings"][0]["raw_tooltip"]
        )


class _FakeResponse:
    def __init__(self, url, body):
        self.url = url
        self._body = json.dumps(body)

    def text(self):
        return self._body


class _FakePage:
    """Minimal page: records the goto URL, feeds canned responses to the
    registered listener on the first wait_for_timeout tick (the offline
    analogue of the SPA's own data calls firing)."""

    def __init__(self, responses, html="<html>grid</html>"):
        self._responses = responses
        self.html = html
        self.handlers = []
        self.goto_calls = []
        self.listeners_removed = False
        self.wait_ticks = 0
        self._fired = False

    def on(self, event, handler):
        self.handlers.append(handler)

    def remove_listener(self, event, handler):
        self.handlers.remove(handler)
        self.listeners_removed = True

    def goto(self, url, wait_until=None):
        self.goto_calls.append(url)

    def content(self):
        return self.html

    def wait_for_timeout(self, ms):
        self.wait_ticks += 1
        if not self._fired:
            self._fired = True
            for handler in list(self.handlers):
                for response in self._responses:
                    handler(response)


def _canned_responses():
    return [
        _FakeResponse(
            "https://direct.yandex.ru/api/v6/ads:list",
            _FIXTURE["ads_list"],
        ),
        _FakeResponse(
            "https://direct.yandex.ru/web-api/grid/api"
            "?operationName=AdDisclaimers&ulogin=ksamatadirect",
            _FIXTURE["ad_disclaimers"],
        ),
        _FakeResponse(
            "https://direct.yandex.ru/api/v6/ads:batchGet?ad_ids=1%2C2",
            _FIXTURE["ads_batch_get"],
        ),
    ]


class TestFetchAdElements(unittest.TestCase):
    def test_builds_url_from_campaign_and_groups_and_parses(self):
        page = _FakePage(_canned_responses())
        result = ad_elements.fetch_ad_elements(
            cast(Any, page), 71149490, group_ids=[5775404731]
        )
        self.assertEqual(
            page.goto_calls,
            [
                "https://direct.yandex.ru/dna/grid/banners"
                "?campaigns-ids=71149490&groups-ids=5775404731"
            ],
        )
        self.assertTrue(page.listeners_removed)
        self.assertEqual(
            len([e for e in result if e["ad_id"] == TARGET_AD]), 8
        )  # 7 titles + 1 text

    def test_missing_ads_call_raises_capture_timeout_error(self):
        page = _FakePage(
            [
                _FakeResponse(
                    "https://direct.yandex.ru/web-api/grid/api"
                    "?operationName=AdDisclaimers",
                    _FIXTURE["ad_disclaimers"],
                )
            ]
        )
        with patch.object(ad_elements._clock, "now", side_effect=[0.0] + [100.0] * 200):
            with self.assertRaises(BrowserSessionError) as cm:
                ad_elements.fetch_ad_elements(cast(Any, page), 42)
        self.assertIn("missing: ads, disclaimers", str(cm.exception))

    def test_login_page_redirect_raises_browser_auth_error(self):
        page = _FakePage([], html="<html>passport.yandex.ru/auth list</html>")
        with self.assertRaises(BrowserAuthError):
            ad_elements.fetch_ad_elements(cast(Any, page), 42)


if __name__ == "__main__":
    unittest.main()
