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
import re

import pytest
from click.testing import CliRunner
from dotenv import load_dotenv

from direct_cli.cli import cli

load_dotenv()


@pytest.fixture(autouse=True)
def _block_login_resolve_network(monkeypatch):
    """Stop unit tests from ever hitting the network to resolve a client login.

    A developer machine with an active ``direct auth`` profile whose stored
    login is an email triggers a one-time network ``clients.get`` inside
    ``get_credentials`` (issue #480 migration). Under ``CliRunner`` that call
    can fire per invocation and — if the network is slow or Yandex serves a
    SmartCaptcha gateway — hang the whole suite (it had no timeout). Tests must
    never depend on that round-trip, so neutralize the resolver here. Tests
    that specifically exercise the resolver patch it themselves.
    """
    monkeypatch.setattr(
        "direct_cli.auth._resolve_client_login_via_api",
        lambda *_args, **_kwargs: None,
    )


@pytest.fixture(autouse=True)
def _default_cli_locale_en(monkeypatch):
    """Default the CLI UI locale to English across the suite.

    Russian is the product default UI locale (epic #466). The overwhelming
    majority of tests assert the stable *English* contract text of help and
    error messages; the Russian-default behaviour is owned exclusively by
    ``tests/test_i18n.py`` (and a handful of spots that pin Russian
    explicitly). Pinning the env default to ``en`` here keeps those English
    contract assertions valid without touching hundreds of call sites. Tests
    that need another locale override via ``--locale`` or an explicit
    ``YANDEX_DIRECT_CLI_LOCALE`` in the CliRunner env (an empty value resolves
    back to the Russian default).
    """
    monkeypatch.setenv("YANDEX_DIRECT_CLI_LOCALE", "en")


def _resolve_test_credentials():
    """Resolve API credentials for tests with env-vars taking priority.

    Inverted vs CLI on purpose (see CLAUDE.md): on a developer machine
    with an active ``direct auth`` profile we must not silently hit
    production during a plain ``pytest`` run. Env vars
    (``YANDEX_DIRECT_TOKEN`` / ``YANDEX_DIRECT_LOGIN``, optionally
    loaded from .env above) win over the active profile. Falls back to
    the profile-driven resolution only when env vars are absent.
    Returns (None, None) when no credentials are available.
    """
    env_token = os.environ.get("YANDEX_DIRECT_TOKEN")
    env_login = os.environ.get("YANDEX_DIRECT_LOGIN")
    if env_token:
        return env_token, env_login

    import direct_cli.auth as auth

    # This runs at import time (before the autouse fixture can patch anything).
    # Falling back to the active profile must not trigger the network
    # client-login resolution (#480) — that call could hang collection on a
    # slow network / SmartCaptcha gateway. Neutralize it for this one call.
    original_resolver = auth._resolve_client_login_via_api
    auth._resolve_client_login_via_api = lambda *_a, **_k: None
    try:
        return auth.get_credentials()
    except (RuntimeError, ValueError):
        return None, None
    finally:
        auth._resolve_client_login_via_api = original_resolver


_REAL_TOKEN, _REAL_LOGIN = _resolve_test_credentials()

# A dummy token is fine in replay mode — VCR intercepts the request before
# it touches the network.  In rewrite/record mode the real token from the
# environment is used instead.
TOKEN = _REAL_TOKEN or "REPLAY_DUMMY_TOKEN"

skip_if_no_token = pytest.mark.skipif(
    not _REAL_TOKEN,
    reason="No API credentials found — skipping integration tests",
)


# ── VCR configuration (pytest-recording) ────────────────────────────────


_REDACTED = "REDACTED"

# A retargeting rule references a Metrica goal by its numeric id
# (``"ExternalId":<goal>`` in the request body, echoed back in the response).
# When recording the live-write lifecycle we feed a *real* account goal id via
# ``YANDEX_DIRECT_TEST_RETARGETING_GOAL_ID``, but the repository is public, so
# that real id must never land in a committed cassette. The VCR filter swaps it
# for the synthetic placeholder ``12345`` (the same value the tests fall back to
# when no real goal is available) in both request and response bodies, keeping
# the recorded interaction self-consistent for body-based matching.
_SYNTHETIC_GOAL = "12345"
_REAL_RETARGETING_GOAL = os.environ.get("YANDEX_DIRECT_TEST_RETARGETING_GOAL_ID")


def _mask_retargeting_goal(text):
    """Replace the real retargeting goal id with the synthetic placeholder."""
    if not _REAL_RETARGETING_GOAL or _REAL_RETARGETING_GOAL == _SYNTHETIC_GOAL:
        return text, False
    if isinstance(text, str) and _REAL_RETARGETING_GOAL in text:
        return text.replace(_REAL_RETARGETING_GOAL, _SYNTHETIC_GOAL), True
    if isinstance(text, bytes):
        real = _REAL_RETARGETING_GOAL.encode()
        if real in text:
            return text.replace(real, _SYNTHETIC_GOAL.encode()), True
    return text, False


def _scrub_login(text: str) -> str:
    if _REAL_LOGIN and text:
        return text.replace(_REAL_LOGIN, _REDACTED)
    return text


# Free-text response fields that can carry account-holder PII (real names,
# contact data). The value is matched whether stored raw or JSON-escaped
# (``\uXXXX``) inside a serialized body, so the scrubber works on cassette
# strings as written by vcrpy. Extend this tuple when a new PII-bearing
# field surfaces in a recorded response.
_PII_RESPONSE_FIELDS = (
    "ClientInfo",
    "ContactPerson",
    "Email",
    "Phone",
)


def _scrub_pii_fields(text: str) -> str:
    """Redact known PII-bearing JSON fields in a (possibly escaped) body.

    Matches both ``"ClientInfo":"Имя"`` and the JSON-escaped
    ``\\"ClientInfo\\":\\"...\\"`` form that vcrpy stores, replacing the
    value with ``REDACTED`` while preserving the surrounding quoting style.
    """
    if not text:
        return text
    for field in _PII_RESPONSE_FIELDS:
        # Unescaped form: "Field":"value"
        text = re.sub(
            rf'("{field}"\s*:\s*")[^"]*(")',
            rf"\g<1>{_REDACTED}\g<2>",
            text,
        )
        # JSON-escaped form: \"Field\":\"value\"
        text = re.sub(
            rf'(\\"{field}\\"\s*:\s*\\")(?:[^"\\]|\\.)*?(\\")',
            rf"\g<1>{_REDACTED}\g<2>",
            text,
        )
    return text


def _before_record_request(request):
    """Strip sensitive headers and large binary payloads before storing."""
    for header in ("Authorization", "Client-Login", "authorization", "client-login"):
        if header in request.headers:
            request.headers[header] = _REDACTED
    body = getattr(request, "body", None)
    redacted = False
    if body and "VideoData" in (body if isinstance(body, str) else ""):
        request.body = re.sub(r'"VideoData":"[^"]*"', '"VideoData":"<REDACTED>"', body)
        redacted = True
    elif isinstance(body, bytes) and b"VideoData" in body:
        request.body = re.sub(
            rb'"VideoData":"[^"]*"', b'"VideoData":"<REDACTED>"', body
        )
        redacted = True
    # v4 JSON API carries the OAuth token inside the body as `"token":"..."`.
    if isinstance(request.body, str) and '"token"' in request.body:
        request.body = re.sub(r'"token":"[^"]*"', '"token":"<REDACTED>"', request.body)
        redacted = True
    elif isinstance(request.body, bytes) and b'"token"' in request.body:
        request.body = re.sub(
            rb'"token":"[^"]*"', b'"token":"<REDACTED>"', request.body
        )
        redacted = True
    # The login can also be echoed inside the request body — e.g. the v4
    # `GetClientsUnits` call sends the account login as a `Logins` param.
    if _REAL_LOGIN and request.body:
        if isinstance(request.body, str) and _REAL_LOGIN in request.body:
            request.body = request.body.replace(_REAL_LOGIN, _REDACTED)
            redacted = True
        elif isinstance(request.body, bytes) and _REAL_LOGIN.encode() in request.body:
            request.body = request.body.replace(
                _REAL_LOGIN.encode(), _REDACTED.encode()
            )
            redacted = True
    # A retargeting rule echoes the real Metrica goal id in the body — mask it.
    if request.body:
        request.body, masked_goal = _mask_retargeting_goal(request.body)
        redacted = redacted or masked_goal
    if redacted:
        new_body = request.body
        new_len = str(
            len(new_body.encode("utf-8") if isinstance(new_body, str) else new_body)
        )
        for k in list(request.headers.keys()):
            if k.lower() == "content-length":
                request.headers[k] = new_len
    return request


def _before_record_response(response):
    """Strip login + PII from response bodies, auth and login-echo headers."""
    body = response.get("body", {})
    data = body.get("string")
    if data is not None:
        if isinstance(data, bytes):
            decoded = data.decode("utf-8", errors="replace")
            scrubbed = _scrub_pii_fields(_scrub_login(decoded))
            scrubbed, _ = _mask_retargeting_goal(scrubbed)
            body["string"] = scrubbed.encode("utf-8")
        elif isinstance(data, str):
            scrubbed = _scrub_pii_fields(_scrub_login(data))
            scrubbed, _ = _mask_retargeting_goal(scrubbed)
            body["string"] = scrubbed

    headers = response.get("headers", {})
    for key in list(headers.keys()):
        low = key.lower()
        if low in {"authorization", "client-login", "set-cookie"} or "login" in low:
            headers[key] = [_REDACTED]
            continue
        if low == "x-accel-info":
            headers[key] = [
                (
                    re.sub(r"reqid:\d+", "reqid:0000000000000000000", v)
                    if isinstance(v, str)
                    else v
                )
                for v in headers[key]
            ]
            continue
        if _REAL_LOGIN:
            values = headers.get(key)
            if isinstance(values, list):
                headers[key] = [
                    _scrub_login(v) if isinstance(v, str) else v for v in values
                ]
    return response


# The Yandex Direct API answers on both ``api.direct.yandex.ru`` and
# ``api.direct.yandex.com`` (likewise ``api-sandbox.``); the vendored client's
# TLD has changed between releases. Cassettes recorded against one TLD must keep
# replaying after a vendor bump switches the other, so the ``host`` matcher
# treats the two as equivalent for Direct hosts only — every other host stays
# matched verbatim, preserving the strictness of the original ``host`` matcher.
_DIRECT_HOST_RE = re.compile(r"^(api(?:-sandbox)?\.direct\.yandex)\.(?:ru|com)$")


def _normalize_direct_host(host):
    """Collapse the ``.ru``/``.com`` TLD of a Yandex Direct API host."""
    match = _DIRECT_HOST_RE.match(host or "")
    return match.group(1) if match else host


def _host_tld_insensitive(r1, r2):
    """VCR ``host`` matcher that treats Direct ``.ru`` and ``.com`` as equal."""
    if _normalize_direct_host(r1.host) != _normalize_direct_host(r2.host):
        raise AssertionError(f"{r1.host} != {r2.host}")


def pytest_recording_configure(config, vcr):
    """Override the built-in ``host`` matcher before any cassette is matched.

    pytest-recording calls this hook with the freshly built ``VCR`` instance,
    before ``use_cassette`` resolves ``match_on`` names to matcher callables —
    so re-registering ``host`` here makes ``match_on=[..., "host", ...]`` pick
    up our TLD-insensitive variant.
    """
    vcr.register_matcher("host", _host_tld_insensitive)


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
        # can only be distinguished by payload.  ``host`` is the
        # TLD-insensitive matcher registered in ``pytest_recording_configure``
        # so a ``.ru`` cassette still matches a ``.com`` request (and vice
        # versa) after a vendor bump changes the Direct API TLD.
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
    """Invoke a CLI command with ``--sandbox``/``--token``/``--login`` injected.

    ``--login`` is required during cassette rewrite: without it the CLI
    falls back to whatever login the active ``direct auth`` profile
    holds, which is rarely the same account the sandbox token belongs
    to. In replay mode the value is irrelevant — VCR intercepts the
    request before any header is checked.
    """
    all_args = ["--sandbox", "--token", TOKEN]
    if _REAL_LOGIN:
        all_args += ["--login", _REAL_LOGIN]
    all_args += list(args)
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
    assert (
        "Errors" not in first or not first["Errors"]
    ), f"API rejected add: {first.get('Errors')}"
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
    assert (
        "Errors" not in first or not first["Errors"]
    ), f"API rejected: {first.get('Errors')}"
    return first


def _has_result_errors(output: str, key: str) -> bool:
    """Check whether an API result JSON contains embedded Errors."""
    try:
        data = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return False
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        # Walk into nested "result" if present
        result = data.get("result", data)
        items = result.get(key, [])
    else:
        return False
    if not items:
        return False
    first = items[0] if isinstance(items, list) else items
    return bool(first.get("Errors"))


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
    # sandbox returns this for features unavailable in test env
    "Operation not supported",
    "Not supported",  # sandbox returns this for unsupported campaign types
    "не поддерживается",  # Russian variant of the above
    "Campaign not found",
    "Ad group not found",
    "not accessible",
)

# Named extra_patterns for per-resource sandbox quirks.
# Import these in tests instead of repeating inline tuples.
_CAMPAIGN_STATUS_PATTERNS = (
    "DRAFT",
    "has not been saved",
    "is draft",
    "Invalid object status",
)
_ARCHIVE_PATTERNS = ("Cannot archive", "Cannot unarchive", "Invalid object status")
_KEYWORD_PATTERNS = ("Keyword not found",)
_SITELINK_PATTERNS = ("temporarily unavailable",)
_IMAGE_PATTERNS = ("Invalid format",)
_SMART_AD_PATTERNS = (
    "Неподходящий тип группы объявлений",
    "SelectionCriteria filtration",
)
_RETARGETING_PATTERNS = (
    "required field",
    "is omitted",
    "Invalid request",
    "Not specified",
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
        "campaigns",
        "add",
        "--name",
        name,
        "--start-date",
        tomorrow(),
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
        "adgroups",
        "add",
        "--name",
        "test-group",
        "--campaign-id",
        str(campaign_id),
        "--region-ids",
        "1,225",
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
        "ads",
        "add",
        "--adgroup-id",
        str(adgroup_id),
        "--title",
        "Test Ad",
        "--text",
        "Test ad text",
        "--href",
        "https://example.com",
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
        "keywords",
        "add",
        "--adgroup-id",
        str(adgroup_id),
        "--keyword",
        "тестовое ключевое слово",
        label="keywords add",
    )
    keyword_id = _fixture_parse(result)

    yield keyword_id

    _safe_delete("keywords", "delete", "--id", str(keyword_id))


@pytest.fixture
def sandbox_retargeting_list(unique_suffix):
    """Create a retargeting list from typed ``--rule`` flags in sandbox."""
    result = _invoke(
        "retargeting",
        "add",
        "--name",
        f"test-rtg-{unique_suffix}",
        "--type",
        "RETARGETING",
        "--rule",
        "ALL:12345:30",
    )
    if result.exit_code != 0:
        if _is_sandbox_error(result.output, extra_patterns=_RETARGETING_PATTERNS):
            pytest.skip(
                f"retargeting add not supported (sandbox): {result.output[:200]}"
            )
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
        if _is_sandbox_error(err_text, extra_patterns=_RETARGETING_PATTERNS):
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
    result = _invoke(
        "feeds",
        "add",
        "--name",
        f"test-feed-{unique_suffix}",
        "--url",
        "https://example.com/feed.xml",
        "--business-type",
        "RETAIL",
    )
    if result.exit_code != 0:
        if _is_sandbox_error(result.output):
            pytest.skip(f"feeds add fixture skipped: {result.output[:200]}")
        pytest.fail(f"feeds add failed (not a sandbox error): {result.output[:500]}")
    feed_id = _fixture_parse(result)

    yield feed_id

    _safe_delete("feeds", "delete", "--id", str(feed_id))


@pytest.fixture
def sandbox_dynamic_adgroup(unique_suffix):
    """Create a DYNAMIC_TEXT_CAMPAIGN + DYNAMIC_TEXT_AD_GROUP, yield adgroup ID.

    DynamicTextAdTargets (dynamicads) require DYNAMIC_TEXT_AD_GROUP type.
    The generic sandbox_adgroup fixture creates TEXT_AD_GROUP, which is wrong.
    """
    # Step 1: create DYNAMIC_TEXT_CAMPAIGN
    campaign_result = _fixture_invoke(
        "campaigns",
        "add",
        "--name",
        f"claude-dynamic-{unique_suffix}",
        "--start-date",
        tomorrow(),
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--setting",
        "ADD_METRICA_TAG=NO",
        "--search-strategy",
        "HIGHEST_POSITION",
        "--network-strategy",
        "SERVING_OFF",
        label="campaigns add (dynamic)",
    )
    campaign_id = _fixture_parse(campaign_result)

    # Step 2: create DYNAMIC_TEXT_AD_GROUP
    adgroup_result = _fixture_invoke(
        "adgroups",
        "add",
        "--name",
        "dynamic-test-group",
        "--campaign-id",
        str(campaign_id),
        "--region-ids",
        "1,225",
        "--type",
        "DYNAMIC_TEXT_AD_GROUP",
        "--domain-url",
        "example.com",
        label="adgroups add (dynamic)",
    )
    adgroup_id = _fixture_parse(adgroup_result)

    yield adgroup_id

    _safe_delete("adgroups", "delete", "--id", str(adgroup_id))
    _safe_delete("campaigns", "delete", "--id", str(campaign_id))


@pytest.fixture
def sandbox_smart_adgroup(unique_suffix, sandbox_feed):
    """Create a SMART_CAMPAIGN + SMART_AD_GROUP, yield adgroup ID.

    SmartAdTargets require SMART_AD_GROUP type.
    SmartAdGroup requires FeedId (per API docs).
    The generic sandbox_adgroup fixture creates TEXT_AD_GROUP, which is wrong.
    """
    # Step 1: create SMART_CAMPAIGN
    # --counter-id is WSDL-required (SmartCampaignAddItem.CounterId minOccurs=1).
    # Sandbox accepts any positive integer; replays match on body so the value
    # just needs to be stable.
    campaign_result = _fixture_invoke(
        "campaigns",
        "add",
        "--name",
        f"claude-smart-{unique_suffix}",
        "--start-date",
        tomorrow(),
        "--type",
        "SMART_CAMPAIGN",
        "--counter-id",
        "12345678",
        "--network-strategy",
        "AVERAGE_CPC_PER_FILTER",
        "--filter-average-cpc",
        "1000000",
        label="campaigns add (smart)",
    )
    campaign_id = _fixture_parse(campaign_result)

    # Step 2: create SMART_AD_GROUP (FeedId is required per API docs)
    adgroup_result = _fixture_invoke(
        "adgroups",
        "add",
        "--name",
        "smart-test-group",
        "--campaign-id",
        str(campaign_id),
        "--region-ids",
        "1,225",
        "--type",
        "SMART_AD_GROUP",
        "--feed-id",
        str(sandbox_feed),
        label="adgroups add (smart)",
    )
    adgroup_id = _fixture_parse(adgroup_result)

    yield adgroup_id

    _safe_delete("adgroups", "delete", "--id", str(adgroup_id))
    _safe_delete("campaigns", "delete", "--id", str(campaign_id))
