"""Unit tests for the error-56 transport retry with backoff (#918).

Error 56 ("Exceeded limit of method requests", 1 request / 10 seconds) hits
hardest when several `direct` clients share one account: each keeps stealing
the other's window, so the transport retries with exponential backoff + jitter
and only then reports an honest final error. All sleeps here are fakes — no
test waits real time.
"""

from unittest.mock import MagicMock, patch

import click
import pytest
import requests
from click.testing import CliRunner

from direct_cli._vendor.tapi_yandex_direct import exceptions as tapi_exceptions
from direct_cli.api import ERROR_56_ATTEMPTS, ERROR_56_BASE_DELAY, post_with_retry
from direct_cli.api import _error_56_delay
from direct_cli.cli import cli


def _client_error(code):
    """Build the exception the CLI layer actually sees for a v5 API error."""
    response = requests.Response()
    response.status_code = 400
    response.reason = "Bad Request"
    response.url = "https://api.direct.yandex.com/json/v5/reports"
    response._content = b"{}"
    payload = {
        "error": {
            "error_code": code,
            "error_string": "Exceeded limit of method requests",
            "error_detail": "This method can't be requested more than "
            "1 times in 10 seconds",
            "request_id": "test-request-id",
        }
    }
    return tapi_exceptions.YandexDirectClientError(
        response, payload, client=MagicMock()
    )


class _FakeResource:
    """Duck-typed stand-in for ``client.reports()``; outcomes replay in order."""

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0

    def post(self, *, data):
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_retries_on_error_56_then_succeeds():
    resource = _FakeResource([_client_error(56), _client_error(56), "ok"])
    sleeps = []

    result = post_with_retry(resource, data={"params": {}}, sleep=sleeps.append)

    assert result == "ok"
    assert resource.calls == 3
    assert len(sleeps) == 2


def test_retry_delays_are_exponential_with_jitter():
    resource = _FakeResource([_client_error(56) for _ in range(4)] + ["ok"])
    sleeps = []

    post_with_retry(resource, data={}, sleep=sleeps.append)

    # attempt 1..4 wait 10/20/40/80s, each inflated by up to +50% jitter.
    for attempt, delay in enumerate(sleeps, start=1):
        floor = ERROR_56_BASE_DELAY * 2 ** (attempt - 1)
        ceiling = floor * (1 + 0.5) + 1e-9
        assert floor <= delay <= ceiling, (attempt, delay)


def test_error_56_delay_unit_bands():
    for attempt in range(1, 5):
        floor = ERROR_56_BASE_DELAY * 2 ** (attempt - 1)
        assert floor <= _error_56_delay(attempt) <= floor * 1.5


def test_exhaustion_raises_honest_final_error():
    resource = _FakeResource([_client_error(56) for _ in range(10)])
    sleeps = []

    with patch("direct_cli.api.random.uniform", return_value=0):
        with pytest.raises(click.ClickException) as excinfo:
            post_with_retry(resource, data={}, sleep=sleeps.append)

    message = str(excinfo.value)
    assert f"persisted after {ERROR_56_ATTEMPTS} attempts" in message
    # The hint from the issue: another client may be holding the method quota.
    assert "same Yandex Direct account" in message
    # "wait N sec" (#920): the advice names the next backoff step the client
    # would have waited — 10 * 2**4 = 160s with jitter zeroed above.
    assert "Wait at least 160s before the next attempt" in message
    # Live evidence from #920: a 56 that outlasts minutes of waiting with no
    # concurrent client is a stuck server-side limit, not local contention.
    assert "stuck on the API side" in message
    # The original error stays in the final text (request_id, codes).
    assert "error_code=56" in message
    assert "test-request-id" in message
    assert resource.calls == ERROR_56_ATTEMPTS
    assert len(sleeps) == ERROR_56_ATTEMPTS - 1


def test_exhaustion_wait_advice_tracks_base_delay():
    """The advised N scales with the backoff base, not a literal constant."""

    resource = _FakeResource([_client_error(56) for _ in range(10)])

    with patch("direct_cli.api.random.uniform", return_value=0):
        with pytest.raises(click.ClickException) as excinfo:
            post_with_retry(resource, data={}, sleep=lambda _: None, base_delay=1.0)

    assert "Wait at least 16s before the next attempt" in str(excinfo.value)


@pytest.mark.parametrize("code", [53, 152, 400, 506, 9000])
def test_other_error_codes_are_not_retried(code):
    error = _client_error(code)
    resource = _FakeResource([error])
    sleeps = []

    with pytest.raises(tapi_exceptions.YandexDirectClientError) as excinfo:
        post_with_retry(resource, data={}, sleep=sleeps.append)

    assert excinfo.value is error
    assert resource.calls == 1
    assert sleeps == []


def test_non_api_error_is_not_retried():
    boom = ValueError("no transport at all")
    resource = _FakeResource([boom])
    sleeps = []

    with pytest.raises(ValueError) as excinfo:
        post_with_retry(resource, data={}, sleep=sleeps.append)

    assert excinfo.value is boom
    assert resource.calls == 1
    assert sleeps == []


_REPORT_ARGS = [
    "--token",
    "t",
    "reports",
    "get",
    "--type",
    "CAMPAIGN_PERFORMANCE_REPORT",
    "--from",
    "2026-10-01",
    "--to",
    "2026-10-02",
    "--name",
    "r",
    "--fields",
    "CampaignId,Impressions",
]


def test_reports_get_cli_retries_transient_56(monkeypatch):
    """End-to-end: the CLI retries a transient 56 and still serves the report."""
    sleeps = []
    monkeypatch.setattr("direct_cli.api.time.sleep", sleeps.append)
    sentinel = MagicMock()
    sentinel().to_dicts.return_value = [{"CampaignId": 1}]
    client = MagicMock()
    client.reports.return_value.post.side_effect = [_client_error(56), sentinel]

    with patch("direct_cli.commands.reports.create_client", return_value=client):
        result = CliRunner().invoke(cli, _REPORT_ARGS)

    assert result.exit_code == 0, result.output
    assert client.reports.return_value.post.call_count == 2
    assert len(sleeps) == 1
    assert ERROR_56_BASE_DELAY <= sleeps[0] <= ERROR_56_BASE_DELAY * 1.5
    assert "attempt 1/5" in result.stderr
    assert '"CampaignId": 1' in result.output


def test_reports_get_cli_gives_up_after_exhaustion(monkeypatch):
    """A persistent 56 ends in one honest final error, not a silent exit."""
    sleeps = []
    monkeypatch.setattr("direct_cli.api.time.sleep", sleeps.append)
    client = MagicMock()
    client.reports.return_value.post.side_effect = _client_error(56)

    with patch("direct_cli.commands.reports.create_client", return_value=client):
        result = CliRunner().invoke(cli, _REPORT_ARGS)

    assert result.exit_code == 1
    assert client.reports.return_value.post.call_count == ERROR_56_ATTEMPTS
    assert len(sleeps) == ERROR_56_ATTEMPTS - 1
    stderr = result.stderr
    for attempt in range(1, ERROR_56_ATTEMPTS):
        assert f"attempt {attempt}/5" in stderr
    assert "persisted after 5 attempts" in stderr
    assert "same Yandex Direct account" in stderr
    assert "Wait at least" in stderr
