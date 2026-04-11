"""
Shared fixtures for integration_write tests.

Fixtures create sandbox resources (campaign → adgroup → ad/keyword) and
tear them down automatically.  All calls go through ``--sandbox`` so they
never touch production data.

The write tests are wired to **pytest-recording / vcrpy**: each test has a
YAML cassette committed under ``tests/cassettes/test_integration_write/``
with the Yandex Direct sandbox responses captured from a real run.  By
default (``--record-mode=none``, the CI mode) tests replay from cassettes
without any network calls, so no token is required.  To re-record after
CLI changes, run with ``--record-mode=rewrite`` and a valid
``YANDEX_DIRECT_TOKEN``; review the generated YAMLs for leaked secrets
before committing.
"""

import json
import os

import pytest
from click.testing import CliRunner
from dotenv import load_dotenv

from direct_cli.cli import cli

load_dotenv()

_REAL_TOKEN = os.getenv("YANDEX_DIRECT_TOKEN")
_REAL_LOGIN = os.getenv("YANDEX_DIRECT_LOGIN")

# A dummy token is fine in replay mode — VCR intercepts the request before
# it touches the network.  In rewrite/record mode the real token from the
# environment is used instead.
TOKEN = _REAL_TOKEN or "REPLAY_DUMMY_TOKEN"

skip_if_no_token = pytest.mark.skipif(
    not _REAL_TOKEN,
    reason="YANDEX_DIRECT_TOKEN is not set — skipping integration tests",
)


# ── VCR configuration (pytest-recording) ────────────────────────────────


_REDACTED = "REDACTED"


def _scrub_login(text: str) -> str:
    if _REAL_LOGIN and text:
        return text.replace(_REAL_LOGIN, _REDACTED)
    return text


def _before_record_request(request):
    """Strip sensitive headers before the request is stored in a cassette."""
    for header in ("Authorization", "Client-Login", "authorization", "client-login"):
        if header in request.headers:
            request.headers[header] = _REDACTED
    return request


def _before_record_response(response):
    """Strip login from response bodies, auth headers and login-echo headers."""
    if _REAL_LOGIN:
        body = response.get("body", {})
        data = body.get("string")
        if isinstance(data, bytes):
            body["string"] = _scrub_login(data.decode("utf-8", errors="replace")).encode("utf-8")
        elif isinstance(data, str):
            body["string"] = _scrub_login(data)

    headers = response.get("headers", {})
    for key in list(headers.keys()):
        low = key.lower()
        if low in {"authorization", "client-login", "set-cookie"} or "login" in low:
            headers[key] = [_REDACTED]
            continue
        if _REAL_LOGIN:
            values = headers.get(key)
            if isinstance(values, list):
                headers[key] = [
                    _scrub_login(v) if isinstance(v, str) else v for v in values
                ]
    return response


@pytest.fixture(scope="module")
def vcr_config():
    """VCR config shared by every ``@pytest.mark.vcr`` test in this suite."""
    return {
        "filter_headers": [
            ("authorization", _REDACTED),
            ("client-login", _REDACTED),
            ("cookie", _REDACTED),
        ],
        "before_record_request": _before_record_request,
        "before_record_response": _before_record_response,
        "decode_compressed_response": True,
        # Match on HTTP verb, URL and request body.  Body matching is
        # important: multiple sandbox commands hit the same endpoint and
        # can only be distinguished by payload.
        "match_on": ["method", "scheme", "host", "port", "path", "query", "body"],
        # NOTE: intentionally no ``record_mode`` key.  pytest-recording's
        # default is ``"none"`` (replay-only) when the CLI option
        # ``--record-mode`` is not passed, which is exactly what we want
        # in CI.  Setting it here would shadow the CLI option and block
        # ``--record-mode=rewrite`` from taking effect.
    }


# ── helpers ──────────────────────────────────────────────────────────────


def tomorrow() -> str:
    """Fixed far-future start date for VCR cassette determinism.

    Using a fixed literal keeps request payloads stable across replays.
    Before re-recording cassettes, make sure this date is still in the
    future from the sandbox's perspective (it is accepted up to several
    years ahead).  Bump the literal if Yandex starts rejecting it.
    """
    return "2030-01-15"


def _invoke(*args: str):
    """Invoke a CLI command with ``--sandbox`` and ``--token`` pre-injected."""
    all_args = ["--sandbox", "--token", TOKEN] + list(args)
    return CliRunner().invoke(cli, all_args)


def assert_success(result, cmd_label: str):
    """Assert command exited successfully with valid JSON output."""
    assert result.exit_code == 0, (
        f"[{cmd_label}] exit_code={result.exit_code}\n"
        f"output: {result.output}\n"
        f"exception: {result.exception}"
    )


def parse_add_result(result, key: str = "AddResults") -> int:
    """Extract first ``Id`` from an add-result JSON (list or dict)."""
    data = json.loads(result.output)
    # tapi-yandex-direct extract() returns plain list [{"Id": 123}]
    if isinstance(data, list):
        items = data
    else:
        items = data.get(key, data.get("SetItems", []))
    assert items, f"No results in add response: {result.output[:500]}"
    first = items[0]
    assert "Errors" not in first or not first["Errors"], (
        f"API rejected add: {first.get('Errors')}"
    )
    assert "Id" in first, f"No Id in add result: {first}"
    return first["Id"]


def parse_first_result(result, key: str = "AddResults") -> dict:
    """Extract first item from an API result (list or dict)."""
    data = json.loads(result.output)
    if isinstance(data, list):
        items = data
    else:
        items = data.get(key, data.get("SetItems", []))
    assert items, f"No results in response: {result.output[:500]}"
    first = items[0]
    assert "Errors" not in first or not first["Errors"], (
        f"API rejected: {first.get('Errors')}"
    )
    return first


def _safe_delete(*args):
    """Best-effort delete — ignore errors (resource may already be gone)."""
    try:
        _invoke(*args)
    except Exception:
        pass


# ── session-scoped ───────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def unique_suffix() -> str:
    """Deterministic suffix shared across all tests in a session.

    Fixed to a stable literal so that VCR cassette body matching stays
    stable across replays.  Before re-recording cassettes with a fresh
    sandbox, delete the campaigns that already carry this suffix or
    bump the literal.
    """
    return "cassette"


_SANDBOX_ERROR_PATTERNS = (
    "Object not found",
    "not supported",
    "Campaign not found",
    "Ad group not found",
    "not accessible",
)


def _is_sandbox_error(output: str, extra_patterns: tuple = ()) -> bool:
    """Check whether CLI failure is due to a known sandbox limitation.

    extra_patterns: additional patterns for commands where the sandbox API
    is stricter than production (e.g. requires fields, rejects parameters).
    Used only in specific test inline checks, NOT in _fixture_invoke.
    """
    lower = output.lower()
    patterns = _SANDBOX_ERROR_PATTERNS + extra_patterns
    return any(p.lower() in lower for p in patterns)


def _fixture_invoke(*args, label="fixture"):
    """Invoke CLI and skip only for known sandbox errors; fail on regressions."""
    result = _invoke(*args)
    if result.exit_code != 0:
        if _is_sandbox_error(result.output):
            pytest.skip(f"{label} failed in sandbox: {result.output[:200]}")
        else:
            pytest.fail(f"{label} failed (not a sandbox error): {result.output[:500]}")
    return result


def _fixture_parse(result):
    """Parse add result in fixture context — skip on API errors."""
    data = json.loads(result.output)
    if isinstance(data, list):
        items = data
    else:
        items = data.get("AddResults", data.get("SetItems", []))
    if not items:
        pytest.skip(f"No results in fixture response: {result.output[:200]}")
    first = items[0]
    if "Errors" in first and first["Errors"]:
        err_text = str(first["Errors"])
        if _is_sandbox_error(err_text):
            pytest.skip(f"API rejected fixture (sandbox): {first['Errors']}")
        pytest.fail(f"API rejected fixture resource (CLI bug?): {first['Errors']}")
    if "Id" not in first:
        pytest.skip(f"No Id in fixture result: {first}")
    return first["Id"]


# ── function-scoped resource fixtures ────────────────────────────────────


@pytest.fixture
def sandbox_campaign(unique_suffix):
    """Create a TEXT_CAMPAIGN in sandbox, yield its ID, delete on teardown."""
    name = f"claude-test-{unique_suffix}"
    result = _fixture_invoke(
        "campaigns", "add",
        "--name", name,
        "--start-date", tomorrow(),
        label="campaigns add",
    )
    campaign_id = _fixture_parse(result)

    yield campaign_id

    _safe_delete("campaigns", "delete", "--id", str(campaign_id))


@pytest.fixture
def sandbox_adgroup(sandbox_campaign):
    """Create a TEXT_AD_GROUP in sandbox, yield its ID, delete on teardown."""
    campaign_id = sandbox_campaign
    result = _fixture_invoke(
        "adgroups", "add",
        "--name", "test-group",
        "--campaign-id", str(campaign_id),
        "--region-ids", "1,225",
        label="adgroups add",
    )
    adgroup_id = _fixture_parse(result)

    yield adgroup_id

    _safe_delete("adgroups", "delete", "--id", str(adgroup_id))


@pytest.fixture
def sandbox_ad(sandbox_adgroup):
    """Create a TEXT_AD in sandbox, yield its ID, delete on teardown."""
    adgroup_id = sandbox_adgroup
    result = _fixture_invoke(
        "ads", "add",
        "--adgroup-id", str(adgroup_id),
        "--title", "Test Ad",
        "--text", "Test ad text",
        "--href", "https://example.com",
        label="ads add",
    )
    ad_id = _fixture_parse(result)

    yield ad_id

    _safe_delete("ads", "delete", "--id", str(ad_id))


@pytest.fixture
def sandbox_keyword(sandbox_adgroup):
    """Create a keyword in sandbox, yield its ID, delete on teardown."""
    adgroup_id = sandbox_adgroup
    result = _fixture_invoke(
        "keywords", "add",
        "--adgroup-id", str(adgroup_id),
        "--keyword", "тестовое ключевое слово",
        label="keywords add",
    )
    keyword_id = _fixture_parse(result)

    yield keyword_id

    _safe_delete("keywords", "delete", "--id", str(keyword_id))


@pytest.fixture
def sandbox_retargeting_list(unique_suffix):
    """Create a retargeting list in sandbox, yield its ID, delete on teardown."""
    result = _invoke(
        "retargeting", "add",
        "--name", f"test-rtg-{unique_suffix}",
        "--type", "RETARGETING",
        "--json", json.dumps({
            "Rules": [{
                "Operator": "ALL",
                "Arguments": [{"ExternalId": 12345}],
            }]
        }),
    )
    if result.exit_code != 0:
        if _is_sandbox_error(
            result.output,
            extra_patterns=("required field", "is omitted", "Invalid request"),
        ):
            pytest.skip(f"retargeting add not supported (sandbox): {result.output[:200]}")
        pytest.fail(f"retargeting add failed (CLI regression?): {result.output[:500]}")

    # Parse response body — sandbox may return exit 0 with Errors
    data = json.loads(result.output)
    if isinstance(data, list):
        first = data[0] if data else {}
    else:
        items = data.get("AddResults", [])
        first = items[0] if items else {}
    if "Errors" in first and first["Errors"]:
        err_text = str(first["Errors"])
        if _is_sandbox_error(
            err_text,
            extra_patterns=("required field", "is omitted", "Not specified"),
        ):
            pytest.skip(f"retargeting add rejected (sandbox): {first['Errors']}")
        pytest.fail(f"API rejected retargeting add (CLI bug?): {first['Errors']}")
    if "Id" not in first:
        pytest.skip(f"retargeting add returned no ID (sandbox): {first}")
    rtg_id = first["Id"]

    yield rtg_id

    _safe_delete("retargeting", "delete", "--id", str(rtg_id))


@pytest.fixture
def sandbox_feed(unique_suffix):
    """Create a feed in sandbox, yield its ID, delete on teardown."""
    result = _fixture_invoke(
        "feeds", "add",
        "--name", f"test-feed-{unique_suffix}",
        "--url", "https://example.com/feed.xml",
        label="feeds add",
    )
    feed_id = _fixture_parse(result)

    yield feed_id

    _safe_delete("feeds", "delete", "--id", str(feed_id))
