"""
Tests for `direct history` — «История изменений» (issue #837).

Like `direct masters`, this group has no API surface at all: it replays the
web interface's own GraphQL data call
(``POST /web-api/user-action-log/api?operationName=userActionLog``). These
tests never launch a browser and never hit the network — they drive
``fetch_change_history`` against small fakes implementing just the Playwright
surface it calls (``expect_response``/``goto``/``content``/``request.post``).

See ``tests/fixtures/user_action_log.json`` for the trimmed real response
these fakes replay.

No fake clock is installed here (unlike tests/test_masters.py, issue #767):
this module's production code has no ``wait_for_timeout`` poll loop — its
only wait is ``expect_response``, which blocks on an event rather than
sampling on an interval.
"""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from direct_cli.browser import change_history
from direct_cli.browser.change_history import (
    LOG_PAGE_LIMIT,
    PlaywrightError,
    fetch_change_history,
)
from direct_cli.browser.session import (
    BrowserAuthError,
    BrowserCaptchaError,
    BrowserSessionError,
)
from direct_cli.cli import cli

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture():
    with open(FIXTURES_DIR / "user_action_log.json", encoding="utf-8") as f:
        return json.load(f)


def _captured_request_body(variables=None):
    """The GraphQL body the live page posts, in the shape recon confirmed."""
    return {
        "operationName": "userActionLog",
        "variables": {
            "order": "DESC",
            "dateFrom": "2026-08-05T17:00:00",
            "dateTo": "2026-08-13T16:59:59",
            "categories": ["CAMPAIGN_STRATEGY", "CAMPAIGN_ARCHIVED"],
            "campaignIds": None,
            "adGroupIds": None,
            "adIds": None,
            "logins": None,
            "changeSources": None,
            "limit": LOG_PAGE_LIMIT,
            "token": None,
            **(variables or {}),
        },
        "query": "query userActionLog(...) { ... }",
    }


class _FakeRequest:
    def __init__(self, post_data, headers=None):
        self.post_data = post_data
        self.headers = headers or {"x-csrf-token": "fake-csrf"}


class _FakeResponse:
    """The subset of Playwright's Response the capture reads."""

    def __init__(self, url, status=200, post_data=None, headers=None):
        self.url = url
        self.status = status
        self.request = _FakeRequest(post_data, headers)


class _FakeResponseInfo:
    def __init__(self, page, predicate):
        self._page = page
        self._predicate = predicate

    @property
    def value(self):
        candidate = self._page._log_response
        if candidate is not None and self._predicate(candidate):
            return candidate
        raise PlaywrightError("Timeout waiting for response")


class _FakeExpectResponse:
    def __init__(self, page, predicate):
        self._page = page
        self._predicate = predicate

    def __enter__(self):
        return _FakeResponseInfo(self._page, self._predicate)

    def __exit__(self, *exc_info):
        # Mirrors real Playwright: the EventContextManager resolves the
        # response on exit when the wrapped block did not raise, so a
        # timeout surfaces from the `with` block's own exit (issue #694).
        if exc_info[0] is not None:
            return False
        candidate = self._page._log_response
        if candidate is None or not self._predicate(candidate):
            raise PlaywrightError("Timeout waiting for response")
        return False


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


class _FakeApiRequestContext:
    """Fakes ``page.request`` — the replayed POST used for pagination."""

    def __init__(self, pages=None, ok=True, status=200, raw_body=None):
        self._pages = pages or []
        self._call_count = 0
        self._ok = ok
        self._status = status
        self._raw_body = raw_body
        self.calls = []  # (url, parsed_body, headers) for assertions

    def post(self, url, data=None, headers=None):
        self.calls.append((url, json.loads(data), headers))
        idx = min(self._call_count, max(len(self._pages) - 1, 0))
        self._call_count += 1
        payload = self._pages[idx] if self._pages else {}
        return _FakeApiResponse(
            ok=self._ok, status=self._status, payload=payload, raw_body=self._raw_body
        )


class FakePage:
    def __init__(self, log_response=None, api_request=None, html="<html></html>"):
        self._log_response = log_response
        self.request = api_request or _FakeApiRequestContext()
        self._html = html
        self.navigated_to = []
        self.goto_wait_until = None

    def goto(self, url, wait_until=None, timeout=None):
        self.navigated_to.append(url)
        self.goto_wait_until = wait_until

    def content(self):
        return self._html

    def expect_response(self, predicate, timeout=None):
        return _FakeExpectResponse(self, predicate)


def _page_with(pages, captured_variables=None, url=None):
    """A FakePage that observes the log request and replays `pages`."""
    response = _FakeResponse(
        url
        or "https://direct.yandex.ru/web-api/user-action-log/api"
        "?operationName=userActionLog&ulogin=example-login",
        post_data=json.dumps(_captured_request_body(captured_variables)),
    )
    return FakePage(log_response=response, api_request=_FakeApiRequestContext(pages))


def _payload(records, next_token=None):
    return {
        "data": {"userActionLog": {"logRecords": records, "nextPageToken": next_token}},
        "errors": [],
    }


class TestFetchChangeHistory(unittest.TestCase):
    def test_returns_flattened_records_from_live_shaped_fixture(self):
        fixture = _load_fixture()
        records = fixture["data"]["userActionLog"]["logRecords"]
        page = _page_with([_payload(records)])

        result = fetch_change_history(page)

        self.assertEqual(len(result), 2)
        first = result[0]
        self.assertEqual(first["Datetime"], "2026-08-13T16:22:39")
        self.assertEqual(first["Login"], "example-login")
        self.assertEqual(first["Uid"], 1000000001)
        self.assertEqual(first["ChangeSource"], "WEB")
        self.assertEqual(first["Category"], "CAMPAIGN_STRATEGY")
        self.assertEqual(first["EventType"], "CampaignStrategyEvent")
        self.assertEqual(first["CampaignId"], 77593206)
        self.assertEqual(first["CampaignName"], "Мастер РД (холодный) набор 3")
        self.assertTrue(first["Gtid"])

    def test_raw_event_is_passed_through_untouched(self):
        """The old->new strategy pair is what issue #837 actually needs."""
        fixture = _load_fixture()
        records = fixture["data"]["userActionLog"]["logRecords"]
        page = _page_with([_payload(records)])

        result = fetch_change_history(page)

        event = result[0]["Event"]
        self.assertEqual(event["oldStrategy"]["strategyType"], "OPTIMIZE_CLICKS")
        self.assertEqual(event["newStrategy"]["strategyType"], "OPTIMIZE_CONVERSIONS")
        # The dropped/changed strategy goal is readable without this module
        # having to model per-event-type schemas.
        self.assertEqual(event["newStrategy"]["goalId"], 3000000001)

    def test_event_types_without_a_diff_still_flatten(self):
        """CampaignStatusChangeEvent carries no old/new pair — not an error."""
        fixture = _load_fixture()
        records = fixture["data"]["userActionLog"]["logRecords"]
        page = _page_with([_payload(records)])

        result = fetch_change_history(page)

        second = result[1]
        self.assertEqual(second["EventType"], "CampaignStatusChangeEvent")
        self.assertEqual(second["Category"], "CAMPAIGN_ARCHIVED")
        self.assertEqual(second["CampaignId"], 107706575)
        self.assertNotIn("oldStrategy", second["Event"])

    def test_navigates_with_commit_wait_until(self):
        """Direct's SPA never reaches domcontentloaded (issues #682/#694)."""
        page = _page_with([_payload([])])

        fetch_change_history(page)

        self.assertEqual(page.navigated_to, [change_history.LOG_URL])
        self.assertEqual(page.goto_wait_until, "commit")


class TestPagination(unittest.TestCase):
    def _record(self, gtid):
        return {
            "datetime": "2026-08-13T10:00:00",
            "user": {"uid": 1, "login": "example-login"},
            "changeSource": "WEB",
            "gtid": gtid,
            "event": {
                "__typename": "CampaignStatusChangeEvent",
                "category": "CAMPAIGN_HIDE",
                "campaign": {"id": 1, "name": "c"},
            },
        }

    def test_follows_next_page_token_until_exhausted(self):
        page = _page_with(
            [
                _payload([self._record("a")], next_token="tok-2"),
                _payload([self._record("b")], next_token="tok-3"),
                _payload([self._record("c")], next_token=None),
            ]
        )

        result = fetch_change_history(page)

        self.assertEqual([r["Gtid"] for r in result], ["a", "b", "c"])

    def test_cursor_is_threaded_into_the_next_request(self):
        """Offset-style replay would silently re-read page 1 forever."""
        page = _page_with(
            [
                _payload([self._record("a")], next_token="tok-2"),
                _payload([self._record("b")], next_token=None),
            ]
        )

        fetch_change_history(page)

        tokens = [body["variables"]["token"] for _, body, _ in page.request.calls]
        self.assertEqual(tokens, [None, "tok-2"])

    def test_stops_when_a_page_comes_back_empty(self):
        page = _page_with(
            [
                _payload([self._record("a")], next_token="tok-2"),
                _payload([], next_token="tok-3"),
            ]
        )

        result = fetch_change_history(page)

        self.assertEqual([r["Gtid"] for r in result], ["a"])
        self.assertEqual(len(page.request.calls), 2)

    def test_limit_bounds_total_records_and_stops_paginating(self):
        page = _page_with(
            [
                _payload([self._record("a"), self._record("b")], next_token="tok-2"),
                _payload([self._record("c")], next_token=None),
            ]
        )

        result = fetch_change_history(page, limit=2)

        self.assertEqual([r["Gtid"] for r in result], ["a", "b"])
        self.assertEqual(len(page.request.calls), 1)

    def test_limit_truncates_an_overshooting_page(self):
        page = _page_with(
            [_payload([self._record("a"), self._record("b")], next_token=None)]
        )

        result = fetch_change_history(page, limit=1)

        self.assertEqual([r["Gtid"] for r in result], ["a"])

    def test_non_positive_limit_is_rejected(self):
        page = _page_with([_payload([])])

        with self.assertRaises(ValueError):
            fetch_change_history(page, limit=0)

    def test_page_cap_stops_a_server_that_never_stops_paginating(self):
        # One page repeated forever: without the cap this loops until OOM.
        page = _page_with([_payload([self._record("a")], next_token="always")])

        with patch.object(change_history, "_MAX_PAGES", 3):
            result = fetch_change_history(page)

        # Every page after the first is a duplicate, so dedup collapses them
        # to one record — but the cap is what stops the requests.
        self.assertEqual([r["Gtid"] for r in result], ["a"])
        self.assertEqual(len(page.request.calls), 3)

    def test_overlapping_pages_are_deduplicated_by_gtid(self):
        """The cursor is a 1-second timestamp, so page boundaries overlap.

        Measured live over 2026-07-01..08-13: 6877 rows for 3257 distinct
        gtids. The first overlap landed on page 3, which is why a two-page
        check reads as clean.
        """
        page = _page_with(
            [
                _payload([self._record("a"), self._record("b")], next_token="tok-2"),
                # "b" repeats: it shares the previous page's last second.
                _payload([self._record("b"), self._record("c")], next_token="tok-3"),
                _payload([self._record("c"), self._record("d")], next_token=None),
            ]
        )

        result = fetch_change_history(page)

        self.assertEqual([r["Gtid"] for r in result], ["a", "b", "c", "d"])

    def test_limit_counts_deduplicated_records(self):
        """A limit must not be satisfied by duplicates of the same record."""
        page = _page_with(
            [
                _payload([self._record("a")], next_token="tok-2"),
                _payload([self._record("a")], next_token="tok-3"),
                _payload([self._record("b")], next_token=None),
            ]
        )

        result = fetch_change_history(page, limit=2)

        self.assertEqual([r["Gtid"] for r in result], ["a", "b"])

    def test_records_without_a_gtid_are_kept(self):
        """A record the server sends without an id must not be dropped."""
        record = self._record("a")
        del record["gtid"]
        page = _page_with([_payload([record, self._record("b")], next_token=None)])

        result = fetch_change_history(page)

        self.assertEqual([r["Gtid"] for r in result], [None, "b"])


class TestFilters(unittest.TestCase):
    def _body(self, page):
        return page.request.calls[0][1]["variables"]

    def test_filters_are_applied_server_side(self):
        page = _page_with([_payload([])])

        fetch_change_history(
            page,
            campaign_ids=[1, 2],
            date_from="2026-08-01T00:00:00",
            date_to="2026-08-02T23:59:59",
            categories=["CAMPAIGN_STRATEGY"],
            logins=["someone"],
            change_sources=["API"],
        )

        variables = self._body(page)
        self.assertEqual(variables["campaignIds"], [1, 2])
        self.assertEqual(variables["dateFrom"], "2026-08-01T00:00:00")
        self.assertEqual(variables["dateTo"], "2026-08-02T23:59:59")
        self.assertEqual(variables["categories"], ["CAMPAIGN_STRATEGY"])
        self.assertEqual(variables["logins"], ["someone"])
        self.assertEqual(variables["changeSources"], ["API"])

    def test_unset_filters_keep_the_pages_own_values(self):
        """Notably `categories`: the UI sends 44 of them, guessing drops kinds."""
        page = _page_with([_payload([])])

        fetch_change_history(page)

        variables = self._body(page)
        self.assertEqual(
            variables["categories"], ["CAMPAIGN_STRATEGY", "CAMPAIGN_ARCHIVED"]
        )
        self.assertEqual(variables["dateFrom"], "2026-08-05T17:00:00")
        self.assertIsNone(variables["campaignIds"])

    def test_login_variable_is_preserved(self):
        """Dropping variables.login returns HTTP 200 + "Нет прав" (live)."""
        page = _page_with([_payload([])], captured_variables={"login": "example-login"})

        fetch_change_history(page, campaign_ids=[1])

        self.assertEqual(self._body(page)["login"], "example-login")

    def test_query_is_replayed_verbatim(self):
        """Hand-assembling the GraphQL query would drift from Yandex's schema."""
        page = _page_with([_payload([])])

        fetch_change_history(page)

        self.assertEqual(
            page.request.calls[0][1]["query"],
            _captured_request_body()["query"],
        )

    def test_captured_headers_are_replayed(self):
        page = _page_with([_payload([])])

        fetch_change_history(page)

        self.assertEqual(page.request.calls[0][2]["x-csrf-token"], "fake-csrf")

    def test_ulogin_is_stripped_from_the_replay_url(self):
        """Unlike GridCampaigns, this endpoint needs no ulogin (live-confirmed)."""
        page = _page_with([_payload([])])

        fetch_change_history(page)

        url = page.request.calls[0][0]
        self.assertNotIn("ulogin", url)
        self.assertIn("operationName=userActionLog", url)


class TestErrorHandling(unittest.TestCase):
    def test_graphql_errors_are_raised_not_read_as_empty(self):
        """ "Нет прав" arrives as HTTP 200 + errors[] — a status check misses it."""
        page = _page_with(
            [
                {
                    "data": {"userActionLog": None},
                    "errors": [{"message": "Нет прав"}],
                }
            ]
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            fetch_change_history(page)

        self.assertIn("Нет прав", str(ctx.exception))

    def test_http_error_is_reported(self):
        response = _FakeResponse(
            "https://direct.yandex.ru/web-api/user-action-log/api"
            "?operationName=userActionLog",
            post_data=json.dumps(_captured_request_body()),
        )
        page = FakePage(
            log_response=response,
            api_request=_FakeApiRequestContext(ok=False, status=500),
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            fetch_change_history(page)

        self.assertIn("500", str(ctx.exception))

    def test_non_json_response_is_reported(self):
        response = _FakeResponse(
            "https://direct.yandex.ru/web-api/user-action-log/api"
            "?operationName=userActionLog",
            post_data=json.dumps(_captured_request_body()),
        )
        page = FakePage(
            log_response=response,
            api_request=_FakeApiRequestContext(raw_body="<html>captcha</html>"),
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            fetch_change_history(page)

        self.assertIn("non-JSON", str(ctx.exception))

    def test_unexpected_schema_is_reported(self):
        page = _page_with([{"data": {"somethingElse": {}}, "errors": []}])

        with self.assertRaises(BrowserSessionError) as ctx:
            fetch_change_history(page)

        self.assertIn("expected shape", str(ctx.exception))

    def test_capture_timeout_is_reported(self):
        page = FakePage(log_response=None)

        with self.assertRaises(BrowserSessionError) as ctx:
            fetch_change_history(page)

        self.assertIn("userActionLog", str(ctx.exception))

    def test_captcha_propagates_rather_than_being_relabelled(self):
        page = FakePage(log_response=None)

        with patch.object(
            change_history,
            "assert_not_captcha",
            side_effect=BrowserCaptchaError("captcha"),
        ):
            with self.assertRaises(BrowserCaptchaError):
                fetch_change_history(page)

    def test_auth_error_propagates_rather_than_being_relabelled(self):
        """_with_session's self-heal retry depends on seeing this unchanged."""
        page = FakePage(log_response=None)

        with patch.object(
            change_history,
            "assert_authenticated",
            side_effect=BrowserAuthError("logged out"),
        ):
            with self.assertRaises(BrowserAuthError):
                fetch_change_history(page)


class TestHistoryCommand(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    def _invoke(self, *args, records=None):
        captured = {}

        def _fake_fetch(page, **kwargs):
            captured.update(kwargs)
            return records if records is not None else []

        def _fake_with_session(ctx, headful, profile_dir, chrome_profile, operation):
            return operation(object())

        with patch.object(change_history, "fetch_change_history", _fake_fetch):
            with patch("direct_cli.commands.history._with_session", _fake_with_session):
                result = self.runner.invoke(cli, ["history", "get", *args])
        return result, captured

    def test_outputs_records_as_json(self):
        records = [{"Datetime": "2026-08-13T16:22:39", "CampaignId": 1}]
        result, _ = self._invoke(records=records)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("2026-08-13T16:22:39", result.output)

    def test_campaign_ids_are_parsed_to_ints(self):
        _, captured = self._invoke("--campaign-ids", "1, 2,3")

        self.assertEqual(captured["campaign_ids"], [1, 2, 3])

    def test_bare_dates_are_widened_to_cover_the_whole_day(self):
        _, captured = self._invoke(
            "--date-from", "2026-08-01", "--date-to", "2026-08-02"
        )

        self.assertEqual(captured["date_from"], "2026-08-01T00:00:00")
        self.assertEqual(captured["date_to"], "2026-08-02T23:59:59")

    def test_explicit_datetimes_pass_through_unchanged(self):
        _, captured = self._invoke(
            "--date-from", "2026-08-01T09:30:00", "--date-to", "2026-08-01T10:00:00"
        )

        self.assertEqual(captured["date_from"], "2026-08-01T09:30:00")
        self.assertEqual(captured["date_to"], "2026-08-01T10:00:00")

    def test_csv_options_are_split(self):
        _, captured = self._invoke(
            "--categories",
            "CAMPAIGN_STRATEGY, CAMPAIGN_ARCHIVED",
            "--logins",
            "a,b",
            "--change-sources",
            "WEB",
        )

        self.assertEqual(
            captured["categories"], ["CAMPAIGN_STRATEGY", "CAMPAIGN_ARCHIVED"]
        )
        self.assertEqual(captured["logins"], ["a", "b"])
        self.assertEqual(captured["change_sources"], ["WEB"])

    def test_unset_csv_options_stay_none(self):
        """None must not collapse to [], which would filter everything out."""
        _, captured = self._invoke()

        self.assertIsNone(captured["categories"])
        self.assertIsNone(captured["logins"])
        self.assertIsNone(captured["change_sources"])
        self.assertIsNone(captured["campaign_ids"])

    def test_non_positive_limit_is_rejected(self):
        result, _ = self._invoke("--limit", "0")

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--limit", result.output)

    def test_invalid_campaign_ids_are_rejected(self):
        result, _ = self._invoke("--campaign-ids", "abc")

        self.assertNotEqual(result.exit_code, 0)

    def test_group_needs_no_api_credentials(self):
        """Browser-backed: authorizes off the session, not off a token."""
        from direct_cli.cli import _NO_CREDENTIALS_GROUPS

        self.assertIn("history", _NO_CREDENTIALS_GROUPS)


if __name__ == "__main__":
    unittest.main()
