"""
Read-only integration tests with VCR cassettes (Yandex Direct sandbox).

Unlike ``test_integration.py`` (which hits the live API on every run and
auto-skips without a token), this suite records each read-only command's
sandbox response into a committed cassette under
``tests/cassettes/test_read_cassettes/`` so CI can replay every v5 ``*.get``
path offline, with no token and no network.

- **Replay mode (default, CI):** ``--record-mode=none`` — every command
  replays from its cassette. No credentials required.
- **Rewrite mode (manual):** regenerate after a CLI change with::

      pytest tests/test_read_cassettes.py --record-mode=rewrite

  and a valid ``YANDEX_DIRECT_TOKEN`` / ``YANDEX_DIRECT_LOGIN`` (or an
  active ``direct auth`` profile). Review the generated YAMLs for leaked
  secrets before committing — the ``conftest.py`` scrubbers redact the
  Authorization header, the ``Client-Login`` header, and the real login
  from request/response bodies.

Every command targets ``--sandbox`` and is strictly read-only: no
add/update/delete/set/suspend/resume. The sandbox fixtures are stable
(campaign 700012672, login resolved from credentials), so cassette bodies
are deterministic across re-records.

Coverage notes — v5 read commands intentionally NOT recorded here:

    agencyclients get   — account is not an agency (API error 54)

v4 read commands are NOT covered by this suite: vcrpy cannot intercept the
vendored v4 Live HTTP client in ``--record-mode=rewrite`` (recording hangs
indefinitely even for a single v4 case, although each v4 command runs in
1-2s outside pytest). v4 read paths remain covered by the live
``test_v4_live_contracts.py`` suite until VCR×v4 is resolved separately.
"""

from __future__ import annotations

import os
import sys

import pytest
from click.testing import CliRunner

from direct_cli.cli import cli

sys.path.insert(0, os.path.dirname(__file__))
from conftest import _REAL_LOGIN, _REAL_TOKEN  # noqa: E402

# Stable sandbox fixtures (confirmed live against the recording account).
SANDBOX_CAMPAIGN_ID = "700012672"
# A syntactically valid advideo id from the smoke probe; the sandbox
# returns an empty list for it, which is a fine deterministic cassette.
ADVIDEO_PROBE_ID = "1122065647"


def _invoke_read(args: list[str]):
    """Invoke a read-only CLI command against the sandbox.

    Credentials are passed as explicit ``--token``/``--login`` flags
    (priority 1 in the CLI credential chain) so a re-record never silently
    falls back to a developer's active production profile. In replay mode
    the token is a dummy — VCR intercepts the request before the network.
    """
    token = _REAL_TOKEN or "REPLAY_DUMMY_TOKEN"
    flags = ["--sandbox", "--token", token]
    if _REAL_LOGIN:
        flags += ["--login", _REAL_LOGIN]
    return CliRunner().invoke(cli, flags + args)


# (cassette_id, CLI args) — every recorded command returns a success
# (exit 0) sandbox response; an empty list is valid and still non-empty
# as text.
READ_CASES: list[tuple[str, list[str]]] = [
    ("campaigns_get", ["campaigns", "get"]),
    ("adgroups_get", ["adgroups", "get", "--campaign-ids", SANDBOX_CAMPAIGN_ID]),
    ("ads_get", ["ads", "get", "--campaign-ids", SANDBOX_CAMPAIGN_ID]),
    ("keywords_get", ["keywords", "get", "--campaign-ids", SANDBOX_CAMPAIGN_ID]),
    ("adextensions_get", ["adextensions", "get"]),
    ("adimages_get", ["adimages", "get"]),
    ("creatives_get", ["creatives", "get"]),
    ("retargeting_get", ["retargeting", "get"]),
    ("strategies_get", ["strategies", "get"]),
    ("dictionaries_get", ["dictionaries", "get", "--names", "Currencies,GeoRegions"]),
    (
        "dynamicfeedadtargets_get",
        ["dynamicfeedadtargets", "get", "--campaign-ids", SANDBOX_CAMPAIGN_ID],
    ),
    ("leads_get", ["leads", "get", "--turbo-page-ids", "1"]),
    ("turbopages_get", ["turbopages", "get"]),
    ("businesses_get", ["businesses", "get"]),
    ("advideos_get", ["advideos", "get", "--ids", ADVIDEO_PROBE_ID]),
    ("clients_get", ["clients", "get"]),
    (
        "changes_check",
        [
            "changes", "check",
            "--campaign-ids", SANDBOX_CAMPAIGN_ID,
            "--timestamp", "2026-05-29T00:00:00Z",
        ],
    ),
    (
        "changes_check_campaigns",
        ["changes", "check-campaigns", "--timestamp", "2026-05-29T00:00:00Z"],
    ),
    ("changes_check_dictionaries", ["changes", "check-dictionaries"]),
    (
        "keywordsresearch_has_search_volume",
        [
            "keywordsresearch", "has-search-volume",
            "--keywords", "купить телефон",
            "--region-ids", "213",
        ],
    ),
    (
        "keywordsresearch_deduplicate",
        ["keywordsresearch", "deduplicate", "--keywords", "купить телефон,телефон купить"],
    ),
    (
        "reports_get",
        [
            "reports", "get",
            "--type", "campaign_performance_report",
            "--from", "2026-05-01",
            "--to", "2026-05-28",
            "--name", "vcr_camp_perf",
            "--fields", "CampaignId,Impressions,Clicks,Cost",
            "--campaign-ids", SANDBOX_CAMPAIGN_ID,
        ],
    ),
    ("sitelinks_get", ["sitelinks", "get"]),
    ("vcards_get", ["vcards", "get"]),
    ("feeds_get", ["feeds", "get"]),
    ("bids_get", ["bids", "get", "--campaign-ids", SANDBOX_CAMPAIGN_ID]),
    ("keywordbids_get", ["keywordbids", "get", "--campaign-ids", SANDBOX_CAMPAIGN_ID]),
    ("bidmodifiers_get", ["bidmodifiers", "get", "--campaign-ids", SANDBOX_CAMPAIGN_ID]),
    (
        "audiencetargets_get",
        ["audiencetargets", "get", "--campaign-ids", SANDBOX_CAMPAIGN_ID],
    ),
    ("dynamicads_get", ["dynamicads", "get", "--campaign-ids", SANDBOX_CAMPAIGN_ID]),
    (
        "smartadtargets_get",
        ["smartadtargets", "get", "--campaign-ids", SANDBOX_CAMPAIGN_ID],
    ),
    ("negativekeywordsharedsets_get", ["negativekeywordsharedsets", "get"]),
]


@pytest.mark.vcr
@pytest.mark.parametrize(
    ("cassette_id", "args"),
    READ_CASES,
    ids=[case[0] for case in READ_CASES],
)
def test_read_command(cassette_id: str, args: list[str]) -> None:
    """Each read-only command replays its sandbox response from a cassette."""
    result = _invoke_read(args)
    assert result.exit_code == 0, (
        f"[{cassette_id}] exit={result.exit_code}\n"
        f"output: {result.output}\nexception: {result.exception}"
    )
    # Output must be present (JSON list/object or TSV report body); an
    # empty sandbox list is valid and still non-empty as text.
    assert result.output.strip() != "", f"[{cassette_id}] produced no output"
