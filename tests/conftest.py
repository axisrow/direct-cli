"""
Shared fixtures for integration_write tests.

Fixtures create sandbox resources (campaign → adgroup → ad/keyword) and
tear them down automatically.  All calls go through ``--sandbox`` so they
never touch production data.
"""

import json
import os
import uuid
from datetime import date, timedelta
from typing import Optional

import pytest
from click.testing import CliRunner
from dotenv import load_dotenv

from direct_cli.cli import cli

load_dotenv()

TOKEN = os.getenv("YANDEX_DIRECT_TOKEN")

skip_if_no_token = pytest.mark.skipif(
    not TOKEN,
    reason="YANDEX_DIRECT_TOKEN is not set — skipping integration_write tests",
)


# ── helpers ──────────────────────────────────────────────────────────────


def tomorrow() -> str:
    return (date.today() + timedelta(days=1)).isoformat()


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
    """Extract first ``Id`` from an add-result JSON."""
    data = json.loads(result.output)
    items = data.get(key, data.get("SetItems", []))
    assert items, f"No results in add response: {result.output[:500]}"
    first = items[0]
    assert "Errors" not in first or not first["Errors"], (
        f"API rejected add: {first.get('Errors')}"
    )
    assert "Id" in first, f"No Id in add result: {first}"
    return first["Id"]


def _safe_delete(*args):
    """Best-effort delete — ignore errors (resource may already be gone)."""
    try:
        _invoke(*args)
    except Exception:
        pass


# ── session-scoped ───────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def unique_suffix() -> str:
    """Deterministic suffix shared across all tests in a session."""
    return f"{date.today().isoformat()}-{uuid.uuid4().hex[:6]}"


# ── function-scoped resource fixtures ────────────────────────────────────


@pytest.fixture
def sandbox_campaign(unique_suffix):
    """Create a TEXT_CAMPAIGN in sandbox, yield its ID, delete on teardown."""
    name = f"claude-test-{unique_suffix}"
    result = _invoke(
        "campaigns", "add",
        "--name", name,
        "--start-date", tomorrow(),
    )
    assert_success(result, "campaigns add (fixture)")
    campaign_id = parse_add_result(result)

    yield campaign_id

    _safe_delete("campaigns", "delete", "--id", str(campaign_id))


@pytest.fixture
def sandbox_adgroup(sandbox_campaign):
    """Create a TEXT_AD_GROUP in sandbox, yield its ID, delete on teardown."""
    campaign_id = sandbox_campaign
    result = _invoke(
        "adgroups", "add",
        "--name", f"test-group",
        "--campaign-id", str(campaign_id),
        "--region-ids", "1,225",
    )
    assert_success(result, "adgroups add (fixture)")
    adgroup_id = parse_add_result(result)

    yield adgroup_id

    _safe_delete("adgroups", "delete", "--id", str(adgroup_id))


@pytest.fixture
def sandbox_ad(sandbox_adgroup):
    """Create a TEXT_AD in sandbox, yield its ID, delete on teardown."""
    adgroup_id = sandbox_adgroup
    result = _invoke(
        "ads", "add",
        "--adgroup-id", str(adgroup_id),
        "--title", "Test Ad",
        "--text", "Test ad text",
        "--href", "https://example.com",
    )
    assert_success(result, "ads add (fixture)")
    ad_id = parse_add_result(result)

    yield ad_id

    _safe_delete("ads", "delete", "--id", str(ad_id))


@pytest.fixture
def sandbox_keyword(sandbox_adgroup):
    """Create a keyword in sandbox, yield its ID, delete on teardown."""
    adgroup_id = sandbox_adgroup
    result = _invoke(
        "keywords", "add",
        "--adgroup-id", str(adgroup_id),
        "--keyword", "тестовое ключевое слово",
    )
    assert_success(result, "keywords add (fixture)")
    keyword_id = parse_add_result(result)

    yield keyword_id

    _safe_delete("keywords", "delete", "--id", str(keyword_id))


@pytest.fixture
def sandbox_retargeting_list(unique_suffix):
    """Create a retargeting list in sandbox, yield its ID, delete on teardown."""
    result = _invoke(
        "retargeting", "add",
        "--name", f"test-rtg-{unique_suffix}",
        "--type", "AUDIENCE_SEGMENT",
    )
    assert_success(result, "retargeting add (fixture)")
    rtg_id = parse_add_result(result)

    yield rtg_id

    _safe_delete("retargeting", "delete", "--id", str(rtg_id))


@pytest.fixture
def sandbox_feed(unique_suffix):
    """Create a feed in sandbox, yield its ID, delete on teardown."""
    result = _invoke(
        "feeds", "add",
        "--name", f"test-feed-{unique_suffix}",
        "--url", "https://example.com/feed.xml",
    )
    assert_success(result, "feeds add (fixture)")
    feed_id = parse_add_result(result)

    yield feed_id

    _safe_delete("feeds", "delete", "--id", str(feed_id))
