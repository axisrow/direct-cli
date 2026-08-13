"""
«История изменений» (user action log) — browser-backed reader, issue #837.

Yandex Direct's API has no per-field change journal: ``changes.checkCampaigns``
returns only ``ChangesIn: SELF|CHILDREN|STAT``, ``changes.check`` only lists
changed IDs, and Live v4's ``GetEventsLog`` logs *system* events
(``BannerModerated``, ``MoneyOut``, …) — never "user X set the strategy goal
from A to B". The only place that history exists is the web interface's
«История изменений» section, ``https://direct.yandex.ru/dna/log/``.

Like ``masters.py``'s ``list`` (issue #639), this module does NOT scrape the
section's DOM. Live recon on 2026-08-13 (account ``ksamatadirect``) found the
page is driven by its own GraphQL call,
``POST /web-api/user-action-log/api?operationName=userActionLog``
(``USER_ACTION_LOG_API_URL``), which returns every record as typed JSON —
including the ``oldStrategy``/``newStrategy`` pair that is the whole point of
the section. Capturing and replaying that call is strictly better than parsing
rendered rows: the values arrive already typed and un-truncated, whereas the
grid renders them as prose inside a virtualized table.

The captured GraphQL ``query`` (~5.7 KB of fragments) is replayed verbatim and
never hand-assembled — same rationale as ``_capture_grid_campaigns_request``:
a hand-built query would drift out of sync with Yandex's schema and would be
missing the CSRF/session headers. Only ``variables`` are varied.

Two facts about this endpoint, both confirmed live, differ from the campaigns
grid and matter:

* ``variables.login`` is **required**. Dropping it returns HTTP 200 with
  ``errors: [{message: "Нет прав"}]`` and a null payload, not an auth error.
  ``_capture_user_action_log_request`` therefore reads the login out of the
  captured request rather than inventing one.
* The URL-level ``ulogin`` query parameter is **not** needed — replaying
  against a bare ``?operationName=userActionLog`` works and returns the same
  200 records. This is the opposite of ``GridCampaigns``, where passing one's
  own login as ``ulogin`` produces HTTP 401 «Доступ ограничен» (see
  ``masters.py``'s module docstring). ``LOG_URL`` below keeps whatever the
  page itself uses; the replay URL is normalized by
  ``_strip_ulogin`` so an agency-flavoured captured URL can't leak into it.

Pagination is cursor-based, not offset-based: the response carries
``nextPageToken``, which is fed back as ``variables.token``. An offset-style
replay like the grid's would silently re-read page 1 forever.

**Pages overlap, and ``fetch_change_history`` de-duplicates them.** The
cursor is a timestamp with one-second granularity — ``nextPageToken`` decodes
to ``{"t": <unix seconds>, …}`` — so every record sharing the last returned
record's second is served *again* at the head of the next page. This is
invisible in a two-page check (the first overlap measured live landed on page
3) and severe over a real range: a 2026-07-01..08-13 query returned 6877 rows
for 3257 distinct ``gtid``s. Dedup is on ``gtid``, the server's own
per-record id, not on the record body — the same campaign archived twice is
legitimately identical apart from ``datetime``.
"""

import json
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..output import print_warning
from .session import (
    BrowserSessionError,
    assert_authenticated,
    assert_not_captcha,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from playwright.sync_api import Page

try:  # pragma: no cover - import shape mirrors masters.py
    from playwright.sync_api import Error as PlaywrightError
except ImportError:  # pragma: no cover - exercised only when playwright is absent
    PlaywrightError = Exception  # type: ignore[assignment,misc]


LOG_URL = "https://direct.yandex.ru/dna/log/"
USER_ACTION_LOG_API_URL = "https://direct.yandex.ru/web-api/user-action-log/api"

# The section's data call identifies itself via this query parameter.
_USER_ACTION_LOG_OPERATION = "userActionLog"

# Server-side page size the UI itself requests (confirmed live: a real
# response contained exactly this many records and still carried a
# nextPageToken).
LOG_PAGE_LIMIT = 200

# Timeout for observing the section's own data call. Mirrors the grid's
# budget in masters.py — the page is the same class of SPA.
_LOG_CAPTURE_TIMEOUT_MS = 30_000

# Safety valve for the pagination loop: a server that keeps returning a
# nextPageToken must not spin forever. 200 pages x 200 records = 40k records,
# far beyond any realistic «История изменений» query.
_MAX_PAGES = 200


def _is_user_action_log_request(response: Any) -> bool:
    return (
        f"operationName={_USER_ACTION_LOG_OPERATION}" in response.url
        and response.status == 200
        and bool(response.request.post_data)
    )


def _strip_ulogin(url: str) -> str:
    """Drop any ``ulogin`` query parameter from a captured request URL.

    ``ulogin`` is Yandex's managed-client (agency) parameter. This module
    only ever reads the logged-in user's own account, and the endpoint does
    not need it (confirmed live — see the module docstring), while the
    *page* URL does carry one. Normalizing here keeps a captured
    agency-flavoured URL from being replayed as-is.
    """
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != "ulogin"]
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def _capture_user_action_log_request(page: "Page") -> Dict[str, Any]:
    """Navigate «История изменений» and capture the request it fires.

    Returns ``{"body": dict, "url": str, "headers": dict}`` — the parsed
    GraphQL body (``operationName``/``variables``/``query``), the replay URL
    with any ``ulogin`` stripped, and the request headers (which carry the
    CSRF token and session cookies a hand-built request would lack).

    Uses ``page.expect_response`` started *before* ``goto`` and
    ``wait_until="commit"`` for the same reasons ``masters.py``'s grid
    capture does (issues #682/#694): Direct's SPA pages keep long-poll
    connections open so ``networkidle`` never settles, ``readyState`` never
    advances past ``"interactive"`` so ``domcontentloaded`` times out, and a
    ``expect_response`` timeout surfaces from the ``with`` block's own exit
    rather than from reading ``.value`` afterwards — so the whole block must
    sit inside the ``try``.
    """
    try:
        with page.expect_response(
            _is_user_action_log_request, timeout=_LOG_CAPTURE_TIMEOUT_MS
        ) as response_info:
            page.goto(LOG_URL, wait_until="commit")
            assert_not_captcha(page.content())
            assert_authenticated(page.content())
        response = response_info.value
    except BrowserSessionError:
        # BrowserCaptchaError/BrowserAuthError must propagate as-is rather
        # than being relabelled as the generic timeout below — and without
        # this clause the bare-Exception PlaywrightError fallback (used when
        # playwright isn't installed) would swallow them.
        raise
    except PlaywrightError as exc:
        raise BrowserSessionError(
            "Could not observe the change-history data request "
            f"(operationName={_USER_ACTION_LOG_OPERATION}) within "
            f"{_LOG_CAPTURE_TIMEOUT_MS / 1000:.0f}s. Yandex may have "
            "changed the section's internal API, or the page is unusually "
            "slow to load."
        ) from exc

    post_data = response.request.post_data
    assert post_data  # guaranteed non-empty by _is_user_action_log_request
    return {
        "body": json.loads(post_data),
        "url": _strip_ulogin(response.url),
        "headers": dict(response.request.headers),
    }


def _apply_filters(
    request: Dict[str, Any],
    *,
    campaign_ids: Optional[List[int]],
    date_from: Optional[str],
    date_to: Optional[str],
    categories: Optional[List[str]],
    logins: Optional[List[str]],
    change_sources: Optional[List[str]],
) -> None:
    """Overlay CLI filters onto the captured request's variables, in place.

    Every filter is applied server-side. ``None`` means "leave whatever the
    page itself sent" — notably for ``categories``, whose default is the
    44-entry list the UI requests; replacing it with a partial guess would
    silently drop event kinds.
    """
    variables = request["body"].setdefault("variables", {})
    if campaign_ids is not None:
        variables["campaignIds"] = campaign_ids
    if date_from is not None:
        variables["dateFrom"] = date_from
    if date_to is not None:
        variables["dateTo"] = date_to
    if categories is not None:
        variables["categories"] = categories
    if logins is not None:
        variables["logins"] = logins
    if change_sources is not None:
        variables["changeSources"] = change_sources
    variables["limit"] = LOG_PAGE_LIMIT


def _fetch_log_page(
    page: "Page", request: Dict[str, Any], token: Optional[str]
) -> Dict[str, Any]:
    """Replay the captured request at a given pagination cursor.

    ``token=None`` requests the first page; subsequent pages pass the
    previous response's ``nextPageToken``.
    """
    body = request["body"]
    body["variables"]["token"] = token
    response = page.request.post(
        request["url"],
        data=json.dumps(body),
        headers=request["headers"],
    )
    if not response.ok:
        raise BrowserSessionError(
            f"Change-history API returned HTTP {response.status} for "
            f"{_USER_ACTION_LOG_OPERATION}."
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise BrowserSessionError(
            "Change-history API returned a non-JSON response for "
            f"{_USER_ACTION_LOG_OPERATION}."
        ) from exc

    # This endpoint reports authorization failures as HTTP 200 + a GraphQL
    # `errors` array (confirmed live: dropping variables.login yields
    # "Нет прав" this way), so a status-only check would read the empty
    # payload as "no history".
    errors = payload.get("errors") or []
    if errors:
        messages = "; ".join(
            str(e.get("message", e)) for e in errors if isinstance(e, dict)
        ) or str(errors)
        raise BrowserSessionError(f"Change-history API returned an error: {messages}")

    try:
        return payload["data"][_USER_ACTION_LOG_OPERATION]
    except (KeyError, TypeError) as exc:
        raise BrowserSessionError(
            "Change-history API response did not have the expected shape "
            f"(data.{_USER_ACTION_LOG_OPERATION}) — Yandex may have changed "
            "its schema."
        ) from exc


def _flatten_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Project one raw log record onto the CLI's flat output shape.

    The nested ``event`` object is passed through untouched under
    ``Event``: it is a GraphQL union with a different field set per
    ``__typename`` (``CampaignStrategyEvent`` carries
    ``oldStrategy``/``newStrategy``, ``CampaignStatusChangeEvent`` carries
    neither, and there are at least five more kinds — all seen live). Only
    the fields common to *every* record are lifted to the top level; typed
    per-event diffing is deliberately out of scope here so that a new event
    kind shows up as data rather than as a parse error.
    """
    event = record.get("event") or {}
    campaign = event.get("campaign") or {}
    user = record.get("user") or {}
    return {
        "Datetime": record.get("datetime"),
        "Login": user.get("login"),
        "Uid": user.get("uid"),
        "ChangeSource": record.get("changeSource"),
        "Category": event.get("category"),
        "EventType": event.get("__typename"),
        "CampaignId": campaign.get("id"),
        "CampaignName": campaign.get("name"),
        "Gtid": record.get("gtid"),
        "Event": event,
    }


def fetch_change_history(
    page: "Page",
    *,
    campaign_ids: Optional[List[int]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    categories: Optional[List[str]] = None,
    logins: Optional[List[str]] = None,
    change_sources: Optional[List[str]] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Return «История изменений» records, newest first.

    Reads the section's own JSON data call (see
    ``_capture_user_action_log_request``) and follows ``nextPageToken`` until
    the server stops issuing one, ``limit`` records have been collected, or
    ``_MAX_PAGES`` is reached.

    ``limit`` bounds the *total* number of records returned, independent of
    the server's fixed ``LOG_PAGE_LIMIT`` page size.
    """
    if limit is not None and limit <= 0:
        raise ValueError(f"limit must be positive, got {limit!r}")

    request = _capture_user_action_log_request(page)
    _apply_filters(
        request,
        campaign_ids=campaign_ids,
        date_from=date_from,
        date_to=date_to,
        categories=categories,
        logins=logins,
        change_sources=change_sources,
    )

    records: List[Dict[str, Any]] = []
    seen_gtids: Set[str] = set()
    token: Optional[str] = None
    for _ in range(_MAX_PAGES):
        log = _fetch_log_page(page, request, token)
        page_records = log.get("logRecords") or []
        # Consecutive pages overlap: the cursor is a *timestamp* with
        # one-second granularity (``nextPageToken`` decodes to
        # ``{"t": <unix seconds>, …}``), so every record sharing the last
        # record's second is served again at the head of the next page.
        # Measured live over 2026-07-01..08-13: 6877 rows returned for 3257
        # distinct ``gtid``s — a >2x inflation that only appears past page 2,
        # which is why a two-page check reads as clean. ``gtid`` is the
        # server's own per-record identifier, so dedup on it rather than on
        # the record body (identical field values recur legitimately — the
        # same campaign archived twice looks the same apart from datetime).
        for record in page_records:
            gtid = record.get("gtid")
            if gtid is not None:
                if gtid in seen_gtids:
                    continue
                seen_gtids.add(gtid)
            records.append(record)
        token = log.get("nextPageToken")
        if not page_records or not token:
            break
        if limit is not None and len(records) >= limit:
            break
    else:
        print_warning(
            f"Stopped after {_MAX_PAGES} pages of change history; there may "
            "be more records. Narrow the query with --date-from/--date-to "
            "or --campaign-ids."
        )

    if limit is not None:
        records = records[:limit]

    if not records:
        print_warning(
            "No change-history records found. Either nothing matched this "
            "filter, or Yandex changed the section's API this reads "
            f"(operationName={_USER_ACTION_LOG_OPERATION})."
        )
    return [_flatten_record(record) for record in records]
