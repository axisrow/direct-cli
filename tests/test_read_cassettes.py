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

v4 read commands ARE covered (see the ``v4*`` cases below). vcrpy records the
vendored v4 Live client through the same ``requests``/``urllib3`` transport as
v5 — there is no incompatibility. Earlier recording attempts hung because the
v4 adapter retried request-limit errors (code 54/55) in an unbounded loop; that
loop is now bounded (``v4/adapter.py`` ``retry_request``), so ``--record-mode=
rewrite`` no longer hangs. The ``v4finance check-payment`` case is recorded as a
*deterministic error* (``error_code=370``, "Transaction does not exist"), so it
asserts a non-zero exit and the error string instead of success.
"""

from __future__ import annotations

import os
import sys

import pytest
from click.testing import CliRunner

from direct_cli.cli import cli

sys.path.insert(0, os.path.dirname(__file__))
from conftest import _REAL_LOGIN, _REAL_TOKEN, _REDACTED  # noqa: E402

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
    # creatives/strategies GetRequest.SelectionCriteria is WSDL minOccurs=1, so
    # the CLI now requires a filter (#498 B3c) — pass --ids to satisfy the guard.
    ("creatives_get", ["creatives", "get", "--ids", "1"]),
    # retargeting SelectionCriteria is minOccurs=0; a no-filter call stays valid
    # and now omits the empty criteria from the payload.
    ("retargeting_get", ["retargeting", "get"]),
    ("strategies_get", ["strategies", "get", "--ids", "1"]),
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
            "changes",
            "check",
            "--campaign-ids",
            SANDBOX_CAMPAIGN_ID,
            "--timestamp",
            "2026-05-29T00:00:00Z",
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
            "keywordsresearch",
            "has-search-volume",
            "--keywords",
            "купить телефон",
            "--region-ids",
            "213",
        ],
    ),
    (
        "keywordsresearch_deduplicate",
        [
            "keywordsresearch",
            "deduplicate",
            "--keywords",
            "купить телефон,телефон купить",
        ],
    ),
    (
        "reports_get",
        [
            "reports",
            "get",
            "--type",
            "campaign_performance_report",
            "--from",
            "2026-05-01",
            "--to",
            "2026-05-28",
            "--name",
            "vcr_camp_perf",
            "--fields",
            "CampaignId,Impressions,Clicks,Cost",
            "--campaign-ids",
            SANDBOX_CAMPAIGN_ID,
        ],
    ),
    ("sitelinks_get", ["sitelinks", "get"]),
    ("vcards_get", ["vcards", "get"]),
    ("feeds_get", ["feeds", "get"]),
    ("bids_get", ["bids", "get", "--campaign-ids", SANDBOX_CAMPAIGN_ID]),
    ("keywordbids_get", ["keywordbids", "get", "--campaign-ids", SANDBOX_CAMPAIGN_ID]),
    (
        "bidmodifiers_get",
        ["bidmodifiers", "get", "--campaign-ids", SANDBOX_CAMPAIGN_ID],
    ),
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
    # ── v4 Live read commands ──────────────────────────────────────────
    # All run against --sandbox and return a success body (exit 0). The v4
    # Live client shares the requests/urllib3 transport vcrpy patches, so
    # these record and replay exactly like the v5 cases above.
    (
        "v4goals_get_stat_goals",
        ["v4goals", "get-stat-goals", "--campaign-ids", SANDBOX_CAMPAIGN_ID],
    ),
    (
        "v4tags_get_campaigns",
        ["v4tags", "get-campaigns", "--campaign-ids", SANDBOX_CAMPAIGN_ID],
    ),
    ("v4forecast_list", ["v4forecast", "list"]),
    ("v4wordstat_list_reports", ["v4wordstat", "list-reports"]),
    (
        "v4events_get_events_log",
        [
            "v4events",
            "get-events-log",
            "--from",
            "2026-05-01T00:00:00",
            "--to",
            "2026-05-28T00:00:00",
        ],
    ),
    (
        "v4finance_get_clients_units",
        ["v4finance", "get-clients-units", "--logins", _REAL_LOGIN or _REDACTED],
    ),
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


# A 32-char latin-alphanumeric transaction id that does not exist — the v4
# Live CheckPayment method answers deterministically with error_code=370
# ("Transaction does not exist"). This makes a stable, secret-free cassette
# for the read-only error path that the success-only READ_CASES can't model.
_NONEXISTENT_TRANSACTION_ID = "abcdef0123456789abcdef0123456789"


@pytest.mark.vcr
def test_v4finance_check_payment_unknown_transaction() -> None:
    """v4finance check-payment replays a deterministic error_code=370.

    Unlike the success cases, this command aborts (non-zero exit) when the
    transaction is unknown — which is exactly the deterministic, side-effect
    free response we want to lock into a cassette.
    """
    result = _invoke_read(
        [
            "v4finance",
            "check-payment",
            "--custom-transaction-id",
            _NONEXISTENT_TRANSACTION_ID,
        ]
    )
    assert result.exit_code != 0, (
        f"expected non-zero exit for unknown transaction, got {result.exit_code}\n"
        f"output: {result.output}"
    )
    assert (
        "error_code=370" in result.output
    ), f"expected error_code=370 in output, got: {result.output}"
