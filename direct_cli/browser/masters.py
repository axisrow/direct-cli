"""
Мастер кампаний (Campaign Wizard) browser scraping and mutations.

Мастер кампаний has no API surface at all — see the package docstring in
``direct_cli/browser/__init__.py``. ``get`` (per-campaign overview) reads the
same server-side-rendered wizard page a human would (see
``tests/fixtures/masters_wizard_overview.html`` for the network capture that
established this). ``list`` does NOT scrape the campaigns grid's DOM — live
diagnosis for issue #639 found the grid is a virtualized SPA that renders zero
``/wizard/campaigns/`` anchors even after ``networkidle`` and manual scrolling.
Instead ``list`` replays the grid's own data call,
``POST /web-api/grid/api?operationName=GridCampaigns`` (``GRID_API_URL``),
which returns every campaign as typed JSON — see ``fetch_masters_list``.

No ``ulogin``/agency support: this module only ever reads the logged-in
user's own account. ``ulogin`` is Yandex's *managed-client* parameter (agency
access to someone else's account) — passing your own login there produces
"Доступ ограничен" and HTTP 401 on the grid's data calls (confirmed live).
Both ``list`` and ``get`` build URLs without ``ulogin``; Yandex itself
redirects ``/wizard/campaigns/{id}/`` to the correct ``?ulogin=<chief login>``.

There is no stable discriminator for "created via Мастер кампаний" among the
grid's own campaign-type fields (``type``, ``metaType``, ``__typename`` are
identical between a Мастер campaign and an ordinary one of the same type).
The one field that does distinguish them, confirmed live against a real
account, is ``source == "UAC"``.

``suspend_master``/``resume_master`` (issue #630) — **not live-verified**.
The overview page's "Возобновить кампанию" (resume) button text is confirmed
live (see the fixture). The suspend-side button text is NOT confirmed live —
this module tries a short list of plausible Russian labels
(``_SUSPEND_BUTTON_TEXTS``) via Playwright's text-based locator matching
(case-insensitive substring), and either action re-reads the page's status
text after clicking to verify the change actually happened (never trusting
the click alone — see ``_click_action_button``). If Yandex's real button text
isn't in that list, both functions raise ``BrowserSessionError`` with a
message asking the caller to re-run with ``--headful`` and report the actual
text, rather than clicking the wrong element. Re-confirm the exact button
text/behaviour against a live account before relying on this in production;
update ``_SUSPEND_BUTTON_TEXTS``/``_RESUME_BUTTON_TEXTS`` accordingly.
"""

import json
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from ..output import print_warning
from .session import BrowserSessionError, assert_authenticated, assert_not_captcha

if TYPE_CHECKING:
    from playwright.sync_api import Page

try:
    from playwright.sync_api import Error as PlaywrightError
except ImportError:  # pragma: no cover - exercised only when playwright is absent
    PlaywrightError = Exception  # type: ignore[assignment,misc]

GRID_URL = "https://direct.yandex.ru/dna/grid/campaigns/"
GRID_API_URL = "https://direct.yandex.ru/web-api/grid/api"
WIZARD_OVERVIEW_URL = "https://direct.yandex.ru/wizard/campaigns/{campaign_id}/"

# The grid's own data call identifies itself via this query parameter.
_GRID_CAMPAIGNS_OPERATION = "GridCampaigns"

# Discriminator for "created via Мастер кампаний" among GridCampaigns rows —
# see module docstring. Confirmed live: no campaign-type field distinguishes
# a Мастер campaign from an ordinary one of the same underlying type.
MASTERS_SOURCE = "UAC"

# Server-side page size confirmed live (a real account response used this
# exact limit); GridCampaigns' totalCount can exceed it, so list() must
# paginate rather than silently truncating.
GRID_PAGE_LIMIT = 200

# Timeout for observing the grid's GridCampaigns response (see
# _capture_grid_campaigns_request). Confirmed live: the grid can take
# 10-15s after domcontentloaded to fire it, well within this 30s budget.
_GRID_CAPTURE_TIMEOUT_MS = 30_000

# `status.primaryStatus` -> CLI-facing status filters for `masters list
# --status`. "not-archived" is the default (mirrors the CLI-wide convention
# of not surfacing archived resources unless asked, see COMMON_FIELDS
# elsewhere) -- but "archived" alone must be selectable, per user request.
STATUS_FILTERS = {
    "active": lambda s: s == "ACTIVE",
    "stopped": lambda s: s == "STOPPED",
    "archived": lambda s: s == "ARCHIVED",
    "all": lambda s: True,  # noqa: ARG005 - intentional constant-true predicate
    "not-archived": lambda s: s != "ARCHIVED",
}

# GridCampaigns' primaryStatus -> the CLI's existing Status vocabulary
# (fetch_master's status-text parser already produces "SUSPENDED"/"ACTIVE").
_PRIMARY_STATUS_TO_CLI_STATUS = {"STOPPED": "SUSPENDED"}

# Fixed order of the overview page's stat tiles, confirmed live (see fixture).
_STAT_TILE_LABELS = {
    "Показа": "impressions",
    "Показов": "impressions",
    "Кликов": "clicks",
    "Конверсии": "conversions",
    "Конверсий": "conversions",
    "За конверсию": "cost_per_conversion",
    "Расход": "cost",
}

# Overview-page action button text for resume/suspend (see module docstring:
# resume is confirmed live via the fixture, suspend is NOT — this is a
# best-effort candidate list of plausible Russian labels, matched
# case-insensitively as a substring against every button's text).
_RESUME_BUTTON_TEXTS = ("Возобновить кампанию", "Возобновить")
_SUSPEND_BUTTON_TEXTS = ("Остановить кампанию", "Приостановить кампанию", "Остановить")

# How long to wait, after clicking the action button, for the status text to
# actually change before giving up and reporting a possible false success.
_STATUS_CHANGE_TIMEOUT_MS = 10_000


def _is_grid_campaigns_request(response: Any) -> bool:
    return (
        f"operationName={_GRID_CAMPAIGNS_OPERATION}" in response.url
        and response.status == 200
        and bool(response.request.post_data)
    )


def _capture_grid_campaigns_request(page: "Page") -> Dict[str, Any]:
    """Navigate the grid and capture the ``GridCampaigns`` request it fires.

    Returns the raw ``dict`` from ``json.loads(request.post_data)`` plus the
    URL/headers needed to replay it, as
    ``{"body": dict, "url": str, "headers": dict}``.

    Deliberately does NOT hand-assemble the GraphQL query itself — the real
    query is several KB of fragments that would drift out of sync with
    Yandex's schema. Capturing and replaying the browser's own request (only
    varying ``limitOffset`` for pagination) is what makes this resilient to
    schema changes, and it also carries the CSRF/session headers a
    hand-built request would be missing.

    Uses ``page.expect_response`` (started before ``goto``, so it also
    catches a response that fires mid-navigation) rather than a manual
    ``page.on`` handler plus a polling loop: like Yandex's login page (#634),
    the grid keeps long-poll connections open, so ``networkidle`` never
    settles and burns its full timeout even though ``GridCampaigns`` fired
    seconds earlier — ``expect_response`` blocks on the actual event instead
    of sampling on an interval, and needs no listener cleanup.
    """
    with page.expect_response(
        _is_grid_campaigns_request, timeout=_GRID_CAPTURE_TIMEOUT_MS
    ) as response_info:
        # domcontentloaded, not networkidle: see docstring. No ulogin here
        # (see module docstring): passing our own login as the
        # managed-client param produces "Доступ ограничен" + HTTP 401.
        page.goto(GRID_URL, wait_until="domcontentloaded")
        assert_not_captcha(page.content())
        assert_authenticated(page.content())

    try:
        response = response_info.value
    except PlaywrightError as exc:
        raise BrowserSessionError(
            "Could not observe the campaigns grid's data request "
            f"(operationName={_GRID_CAMPAIGNS_OPERATION}) within "
            f"{_GRID_CAPTURE_TIMEOUT_MS / 1000:.0f}s. Yandex may have "
            "changed the grid's internal API, or the page is unusually "
            "slow to load."
        ) from exc

    post_data = response.request.post_data
    assert post_data  # guaranteed non-empty by _is_grid_campaigns_request
    return {
        "body": json.loads(post_data),
        "url": response.url,
        "headers": dict(response.request.headers),
    }


def _fetch_grid_campaigns_page(
    page: "Page", request: Dict[str, Any], offset: int
) -> Dict[str, Any]:
    """Replay the captured GridCampaigns request at a given pagination offset."""
    body = request["body"]
    body["variables"]["campaignInput"]["limitOffset"] = {
        "offset": offset,
        "limit": GRID_PAGE_LIMIT,
    }
    response = page.request.post(
        request["url"],
        data=json.dumps(body),
        headers=request["headers"],
    )
    if not response.ok:
        raise BrowserSessionError(
            f"Campaigns grid API returned HTTP {response.status} for "
            f"{_GRID_CAMPAIGNS_OPERATION} (offset={offset})."
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise BrowserSessionError(
            f"Campaigns grid API returned a non-JSON response for "
            f"{_GRID_CAMPAIGNS_OPERATION} (offset={offset})."
        ) from exc
    try:
        return payload["data"]["client"]["campaigns"]
    except (KeyError, TypeError) as exc:
        raise BrowserSessionError(
            "Campaigns grid API response did not have the expected shape "
            "(data.client.campaigns) — Yandex may have changed its schema."
        ) from exc


def fetch_masters_list(
    page: "Page", status: str = "not-archived"
) -> List[Dict[str, Any]]:
    """Return every Мастер кампаний row from the account's campaigns grid.

    Reads the grid's own JSON data call (see ``_capture_grid_campaigns_request``)
    rather than the grid's DOM, paginates through every row
    (``GRID_PAGE_LIMIT`` per page), keeps only rows whose ``source`` is
    ``MASTERS_SOURCE``, and applies ``status`` via ``STATUS_FILTERS``.
    """
    status_predicate = STATUS_FILTERS.get(status)
    if status_predicate is None:
        raise ValueError(
            f"Unknown status filter {status!r}; expected one of "
            f"{sorted(STATUS_FILTERS)}."
        )

    request = _capture_grid_campaigns_request(page)

    all_rows: List[Dict[str, Any]] = []
    offset = 0
    while True:
        campaigns = _fetch_grid_campaigns_page(page, request, offset)
        rowset = campaigns.get("rowset") or []
        all_rows.extend(rowset)
        offset += len(rowset)
        if not rowset or offset >= campaigns.get("totalCount", offset):
            break

    masters: List[Dict[str, Any]] = []
    for row in all_rows:
        if row.get("source") != MASTERS_SOURCE:
            continue
        primary_status = (row.get("status") or {}).get("primaryStatus") or ""
        if not status_predicate(primary_status):
            continue
        try:
            campaign_id = int(row["id"])
        except (KeyError, TypeError, ValueError):
            continue
        masters.append(
            {
                "CampaignId": campaign_id,
                "Name": row.get("name", ""),
                "Status": _PRIMARY_STATUS_TO_CLI_STATUS.get(
                    primary_status, primary_status
                ),
                "Type": row.get("type"),
                "StartDate": row.get("startDate"),
            }
        )

    if not masters:
        print_warning(
            "No Мастер кампаний rows found for status filter "
            f"{status!r}. Either the account has none matching this filter, "
            f"or Yandex changed the grid API this reads (source == "
            f"{MASTERS_SOURCE!r} in {_GRID_CAMPAIGNS_OPERATION})."
        )
    return masters


def fetch_master(page: "Page", campaign_id: int) -> Dict[str, Any]:
    """Fetch overview details for one Мастер кампаний by navigating its wizard page.

    Best-effort: a section this parser doesn't recognise is omitted from the
    result (with a warning), rather than failing the whole command — Yandex's
    internal markup has no stability guarantee (see module docstring).

    No ``ulogin`` on the URL (see module docstring) — confirmed live that
    Yandex itself redirects to the correct ``?ulogin=<chief login>``.
    """
    url = WIZARD_OVERVIEW_URL.format(campaign_id=campaign_id)
    page.goto(url, wait_until="domcontentloaded")
    assert_not_captcha(page.content())
    assert_authenticated(page.content())

    result: Dict[str, Any] = {"CampaignId": campaign_id}

    _extract_title(page, result)
    _extract_status(page, result)
    _extract_landing_url(page, result)
    _extract_stat_tiles(page, result)

    return result


def _extract_title(page: "Page", result: Dict[str, Any]) -> None:
    heading = page.locator("h1, [role=heading]").first
    try:
        result["Name"] = heading.inner_text().strip()
    except PlaywrightError:
        print_warning(f"Could not read campaign name for {result['CampaignId']}.")


def _extract_status(page: "Page", result: Dict[str, Any]) -> None:
    try:
        body_text = page.inner_text("body")
    except PlaywrightError:
        body_text = ""
    if "Кампания остановлена" in body_text:
        result["Status"] = "SUSPENDED"
    elif "Кампания активна" in body_text or "Кампания включена" in body_text:
        result["Status"] = "ACTIVE"
    else:
        print_warning(
            f"Could not determine status for campaign {result['CampaignId']} "
            "(unrecognised status text)."
        )


def _extract_landing_url(page: "Page", result: Dict[str, Any]) -> None:
    # The landing-page link's visible text is the bare domain, but its href
    # carries the full UTM-templated URL — see the confirmed fixture example.
    link = page.locator("a[href*='utm_source=']").first
    try:
        href = link.get_attribute("href")
        if href:
            result["LandingUrl"] = href
    except PlaywrightError:
        print_warning(
            f"Could not read landing URL for campaign {result['CampaignId']}."
        )


def _extract_stat_tiles(page: "Page", result: Dict[str, Any]) -> None:
    # Stat tiles render near the top of the page, well before the dozens of
    # nav/tab/edit buttons further down — stop as soon as every known label
    # is found instead of walking every button on the page.
    wanted_keys = set(_STAT_TILE_LABELS.values())
    stats: Dict[str, str] = {}
    buttons = page.locator("button")
    count = buttons.count()
    for i in range(count):
        if stats.keys() >= wanted_keys:
            break
        try:
            text = buttons.nth(i).inner_text().strip()
        except PlaywrightError:
            continue
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) != 2:
            continue
        value, label = lines
        key = _STAT_TILE_LABELS.get(label)
        if key and key not in stats:
            stats[key] = value

    if stats:
        result["Stats"] = stats
    else:
        print_warning(
            f"Could not read overview stat tiles for campaign {result['CampaignId']}."
        )


def _read_status_text(page: "Page") -> Optional[str]:
    """Return ``"SUSPENDED"``/``"ACTIVE"``/``None`` from the current page body.

    Shares the same marker text as ``_extract_status`` but returns the value
    directly instead of writing into a result dict — used by
    ``suspend_master``/``resume_master`` both before and after clicking, to
    verify the action actually changed the status rather than trusting the
    click alone.
    """
    try:
        body_text = page.inner_text("body")
    except PlaywrightError:
        return None
    if "Кампания остановлена" in body_text:
        return "SUSPENDED"
    if "Кампания активна" in body_text or "Кампания включена" in body_text:
        return "ACTIVE"
    return None


def _click_action_button(page: "Page", candidate_texts: Tuple[str, ...]) -> None:
    """Click the first visible button matching one of ``candidate_texts``.

    Raises :class:`BrowserSessionError` if none of the candidates match any
    visible button — this deliberately does NOT fall back to clicking an
    unrelated element, since suspend/resume is a real account mutation (see
    module docstring: the suspend-side button text is not live-confirmed).
    """
    for text in candidate_texts:
        locator = page.get_by_text(text, exact=False)
        try:
            count = locator.count()
        except PlaywrightError:
            continue
        for i in range(count):
            handle = locator.nth(i)
            try:
                if not handle.is_visible():
                    continue
                handle.click()
                return
            except PlaywrightError:
                continue
    raise BrowserSessionError(
        "Could not find an action button matching any of "
        f"{candidate_texts!r} on the campaign overview page. Yandex may "
        "have changed the button's text — re-run with --headful to "
        "inspect the page and report the actual text."
    )


def _suspend_or_resume(
    page: "Page",
    campaign_id: int,
    *,
    target_status: str,
    button_texts: Tuple[str, ...],
) -> Dict[str, Any]:
    """Shared body for ``suspend_master``/``resume_master``.

    Idempotent: if the campaign is already in ``target_status``, does not
    click anything and returns the current state with a warning (mirrors the
    rest of the CLI's suspend/resume convention). Otherwise clicks the
    matching action button and re-reads the status to confirm the mutation
    actually took effect — a click that doesn't visibly change the status is
    reported as a hard error, not a silent success.
    """
    url = WIZARD_OVERVIEW_URL.format(campaign_id=campaign_id)
    page.goto(url, wait_until="domcontentloaded")
    assert_not_captcha(page.content())
    assert_authenticated(page.content())

    current_status = _read_status_text(page)
    if current_status is None:
        raise BrowserSessionError(
            f"Could not determine current status for campaign {campaign_id} "
            "(unrecognised status text) — refusing to click blind."
        )
    if current_status == target_status:
        print_warning(
            f"Campaign {campaign_id} is already {target_status}; not clicking."
        )
        return {"CampaignId": campaign_id, "Status": current_status}

    _click_action_button(page, button_texts)

    deadline = time.monotonic() + _STATUS_CHANGE_TIMEOUT_MS / 1000
    new_status = current_status
    while time.monotonic() < deadline:
        new_status = _read_status_text(page)
        if new_status == target_status:
            break
        page.wait_for_timeout(250)

    if new_status != target_status:
        raise BrowserSessionError(
            f"Clicked the action button for campaign {campaign_id}, but its "
            f"status did not change to {target_status} within "
            f"{_STATUS_CHANGE_TIMEOUT_MS / 1000:.0f}s (still {new_status!r}). "
            "The click may not have hit the right element, or Yandex is "
            "slow to apply it — verify manually before retrying."
        )

    return {"CampaignId": campaign_id, "Status": new_status}


def suspend_master(page: "Page", campaign_id: int) -> Dict[str, Any]:
    """Stop (suspend) a Мастер кампаний, verifying the status actually changed.

    See module docstring: the "stop" button's exact text is NOT confirmed
    live — ``_SUSPEND_BUTTON_TEXTS`` is a best-effort candidate list.
    """
    return _suspend_or_resume(
        page,
        campaign_id,
        target_status="SUSPENDED",
        button_texts=_SUSPEND_BUTTON_TEXTS,
    )


def resume_master(page: "Page", campaign_id: int) -> Dict[str, Any]:
    """Resume a stopped Мастер кампаний, verifying the status actually changed.

    "Возобновить кампанию" is confirmed live (see module docstring /
    ``tests/fixtures/masters_wizard_overview.html``).
    """
    return _suspend_or_resume(
        page,
        campaign_id,
        target_status="ACTIVE",
        button_texts=_RESUME_BUTTON_TEXTS,
    )
