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

``archive_master`` (issue #633, live-recon confirmed no separate "delete"
exists for Мастер кампаний — only archive; see the issue comment). Both
the campaigns-grid row menu and the overview page's own "⋮" menu were
inspected live: neither has a "Удалить" item, only "Архивировать" (grid
row menu also has Перейти/Редактировать/Статистика/Запустить-Остановить;
overview menu has only Клонировать/Архивировать). Confirmed live,
stable ``data-testid`` attributes back the overview menu:
``CampaignHeader.MenuTrigger`` (opens the "⋮" dropdown) and
``CampaignHeader.Menu.archive`` (the "Архивировать" menu item) — unlike
suspend/resume's text-based matching, this does not depend on Russian
button copy. Archiving is verified via ``fetch_masters_list`` (the grid
API's ``primaryStatus``), not the overview page's status text — no
archived-campaign overview fixture has been captured, so there is no
confirmed status-text marker for "archived" on that page the way there is
for "Кампания остановлена"/"активна".

``update_master`` (issue #631, Этап A only) — live-verified against campaign
107707079 (see ``tests/fixtures/masters_wizard_edit_stage_a.html`` for the
full investigation notes). Covers exactly three fields: weekly budget,
promotion goal, and the "Директ помогает" auto-recommendations toggle.
Later stages (headline/text lists, sitelinks, audience, media uploads) are
tracked separately in issue #631 and are NOT implemented here.

Confirmed live: the edit page (``/wizard/campaigns/{id}/edit/``) is a single
form with exactly one "Сохранить кампанию" button at the bottom — there is no
per-section independent save. A partial ``update_master`` call (only some
kwargs passed) therefore still submits the whole form; fields the caller
didn't ask to change are simply left as their current on-page value by never
touching their input, not via any server-side partial-update semantics.

**Save verification.** ``_click_save`` only confirms the button was
clickable — a click alone is not proof Yandex actually saved the change
(client-side validation can silently reject a value and leave the form open
with an inline error this module has no stable way to read, see issue
#631's "Валидация на стороне Яндекса непрозрачна" risk). ``update_master``
therefore re-navigates to the edit page after saving and re-reads every
requested field via ``_verify_saved`` — if a field still doesn't match what
was requested after a real reload, it raises ``BrowserSessionError`` rather
than reporting false success. This mirrors ``_suspend_or_resume``'s
"a click that doesn't visibly change the state is a hard error, not a
silent success" convention, applied to the whole-form save instead of a
single status field. Not yet covered: an inline validation-error TEXT is
not itself surfaced to the caller (only the resulting mismatch is) — a
follow-up could read and report Yandex's actual rejection reason.

``create_master`` (issue #632) — live recon only, NOT live-verified end to end
(no campaign was ever actually launched/saved during recon — see
``tests/fixtures/masters_wizard_create.html``). Covers exactly the "Конверсии
и трафик" Мастер кампаний type (the other five tile types on the create
modal — Товарная кампания, Продажи на маркетплейсах, Подписчики в
телеграм-канал, Продвижение бизнеса без сайта, Продвижение специалистов — are
out of scope; each is a materially different form). The create flow is NOT a
multi-page "Далее" wizard as the issue assumed: it is one micro-step (a
landing-page URL field with client-side format validation) followed by a
single long form covering every field ``update_master`` above already knows
about, terminating in exactly two buttons — "Запустить кампанию" (launch) and
"Сохранить как черновик" (save as draft) — instead of ``update_master``'s one
"Сохранить кампанию". Confirmed live: only three fields carry a required-field
marker in the UI — headline variants, ad-text variants, and the display
region — and of those three, only the region starts genuinely empty (Yandex
auto-populates headlines/texts by scanning the landing page). This module
therefore requires the caller to pass headlines/texts/regions explicitly
rather than trusting Yandex's AI-generated copy silently, given the "no
sandbox, no rollback" risk profile called out in issue #632.

**Save/launch verification.** Ported from ``update_master``'s
``_verify_saved`` pattern (issue #631 review finding, see the CHANGELOG
entry): ``create_master`` does not trust a single click of the launch/draft
button as proof anything actually happened — see ``_verify_created`` below.
Dropdown-style option clicks additionally use ``get_by_role(...,
exact=True)`` instead of a substring ``get_by_text`` match, for the same
reason ``_set_promotion_goal``/``_click_save`` were fixed: a container whose
text merely contains the target string is not the same element as an actual
clickable button/option row.
"""

import contextlib
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
WIZARD_EDIT_URL = "https://direct.yandex.ru/wizard/campaigns/{campaign_id}/edit/"

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

# Overview page's "⋮" menu, confirmed live (issue #633) — see module
# docstring. Unlike _RESUME_BUTTON_TEXTS/_SUSPEND_BUTTON_TEXTS these are
# selectors, not text-matched candidates: both testids were read directly off
# a live account's DOM, not guessed.
_MENU_TRIGGER_SELECTOR = '[data-testid="CampaignHeader.MenuTrigger"]'
_ARCHIVE_MENU_ITEM_SELECTOR = '[data-testid="CampaignHeader.Menu.archive"]'

# How long to wait, after clicking Архивировать, for the grid API to report
# the campaign as ARCHIVED before giving up (see archive_master).
_ARCHIVE_VERIFY_TIMEOUT_MS = 10_000

# "Цель продвижения" dropdown options, confirmed live by opening the dropdown
# on the edit page — exactly these two rows exist, no others (see
# tests/fixtures/masters_wizard_edit_stage_a.html). CLI-facing enum keys are
# kebab-case (this field has no WSDL to mirror, unlike the rest of the CLI).
PROMOTION_GOAL_CHOICES = {
    "max-conversions": "Максимум целевых действий",
    "max-clicks": "Максимум переходов",
}

# create_master (issue #632) — confirmed live, see
# tests/fixtures/masters_wizard_create.html.
WIZARD_CREATE_URL = "https://direct.yandex.ru/wizard/campaigns/new/"

# Step 1's only field. No stable id/data-testid (see module docstring) — text
# matches the exact live placeholder.
_CREATE_URL_INPUT_PLACEHOLDER = "Ссылка на сайт, соцсеть, маркетплейс или приложение"

# Step 1's "Далее" button — confirmed live it is clickable even with a
# malformed URL (it does not disable on format), so a click is always
# required to surface the inline validation error below.
_CREATE_NEXT_BUTTON_TEXT = "Далее"

# Confirmed live: this exact string appears under the URL field when the
# "Далее" click rejects the value as not a well-formed URL. Pure
# client-side check, no network round-trip.
_CREATE_INVALID_URL_TEXT = "Некорректный формат ссылки"

# How long to wait for step 2's long form to render after clicking "Далее" —
# confirmed live this can take 10-15s+ (Yandex scans the landing page's
# content to pre-fill headlines/texts/images), well within this budget.
_CREATE_STEP2_TIMEOUT_MS = 30_000

# Step 2 field locators — heading-proximity XPath, same convention as
# update_master's _WEEKLY_BUDGET_INPUT_XPATH etc. (no stable id/data-testid).
_HEADLINES_ADD_INPUT_XPATH = (
    "xpath=//*[self::h1 or self::h2 or self::h3][normalize-space(text())="
    "'Варианты заголовков']/following::input[1]"
)
_TEXTS_ADD_INPUT_XPATH = (
    "xpath=//*[self::h1 or self::h2 or self::h3][normalize-space(text())="
    "'Варианты текстов объявлений']/following::textarea[1]"
    "|xpath=//*[self::h1 or self::h2 or self::h3][normalize-space(text())="
    "'Варианты текстов объявлений']/following::input[1]"
)
_REGION_INPUT_XPATH = (
    "xpath=//*[self::h1 or self::h2 or self::h3][normalize-space(text())="
    "'Регион показов']/following::input[1]"
)
# XPath fragment: the text input immediately following (as a descendant of an
# adjacent sibling) the "Недельный бюджет" heading. Confirmed live — see
# fixture. Headings on this page have no stable id/data-testid, so matching
# is by heading text, same fragility class as _extract_*/_click_action_button.
_WEEKLY_BUDGET_INPUT_XPATH = (
    "xpath=//*[self::h1 or self::h2 or self::h3][normalize-space(text())="
    "'Недельный бюджет']/following::input[1]"
)

# XPath fragment: the checkbox immediately following the "Директ помогает"
# heading. Confirmed live — a plain HTML checkbox, not a custom toggle
# component (see fixture). Deliberately scoped to the FIRST following
# checkbox only, so the nested "Оптимизировать расширенные настройки..."
# checkbox that appears once this one is checked is never touched.
_DIRECT_HELPS_CHECKBOX_XPATH = (
    "xpath=//*[self::h1 or self::h2 or self::h3][normalize-space(text())="
    "'Директ помогает']/following::input[@type='checkbox'][1]"
)

# XPath fragment: the "Цель продвижения" dropdown's trigger button. Confirmed
# live via accessibility-tree read: its accessible name is the static label
# "Цель продвижения" (not the current selection) — it is the first <button>
# following the section heading of the same name.
_PROMOTION_GOAL_BUTTON_XPATH = (
    "xpath=//*[self::h1 or self::h2 or self::h3][normalize-space(text())="
    "'Цель продвижения']/following::button[1]"
)

_SAVE_BUTTON_TEXT = "Сохранить кампанию"
_LAUNCH_BUTTON_TEXT = "Запустить кампанию"
_SAVE_DRAFT_BUTTON_TEXT = "Сохранить как черновик"

# Confirmed live: navigating away from an unsubmitted create form triggers
# the browser's native beforeunload "Leave site?" dialog — the wizard
# considers an in-progress, un-launched/un-drafted form "dirty" client-side
# state, independent of any server round-trip (see fixture). Not acted on by
# this module (no dialog-handling code needed for launch/draft themselves,
# which navigate away deliberately) — documented here only as the signal
# that confirmed no earlier recon pass had accidentally persisted anything.


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


def _find_master_row(
    page: "Page", campaign_id: int, *, status: str = "all"
) -> Optional[Dict[str, Any]]:
    """Return this campaign's row from ``fetch_masters_list``, or ``None``."""
    for row in fetch_masters_list(page, status=status):
        if row["CampaignId"] == campaign_id:
            return row
    return None


def archive_master(page: "Page", campaign_id: int) -> Dict[str, Any]:
    """Archive a Мастер кампаний, verifying the grid actually reports it archived.

    There is no separate "delete" for Мастер кампаний (issue #633 live
    recon, documented in the module docstring) — this is the only
    destructive/lifecycle action beyond suspend/resume. Idempotent: if the
    campaign is already archived, does not click anything and returns the
    current row with a warning (mirrors ``suspend_master``/``resume_master``).

    Opens the campaign's overview page, clicks the "⋮" menu trigger, then the
    "Архивировать" item (both selected via confirmed-live ``data-testid``
    attributes, not guessed text — see module docstring), and re-reads the
    campaigns grid via ``fetch_masters_list`` to confirm ``Status ==
    "ARCHIVED"`` before reporting success — never trusting the click alone.
    """
    existing = _find_master_row(page, campaign_id)
    if existing is None:
        raise BrowserSessionError(
            f"Could not find Мастер кампаний {campaign_id} in the campaigns "
            "grid — check the ID, or it may already be gone."
        )
    if existing["Status"] == "ARCHIVED":
        print_warning(f"Campaign {campaign_id} is already archived; not clicking.")
        return existing

    url = WIZARD_OVERVIEW_URL.format(campaign_id=campaign_id)
    page.goto(url, wait_until="domcontentloaded")
    assert_not_captcha(page.content())
    assert_authenticated(page.content())

    menu_trigger = page.locator(_MENU_TRIGGER_SELECTOR).first
    try:
        menu_trigger.click()
    except PlaywrightError as exc:
        raise BrowserSessionError(
            f"Could not open the campaign menu for {campaign_id} "
            f"({_MENU_TRIGGER_SELECTOR!r} not found/clickable) — Yandex may "
            "have changed the overview page's markup."
        ) from exc

    archive_item = page.locator(_ARCHIVE_MENU_ITEM_SELECTOR).first
    try:
        archive_item.click()
    except PlaywrightError as exc:
        raise BrowserSessionError(
            f"Could not find/click 'Архивировать' for campaign {campaign_id} "
            f"({_ARCHIVE_MENU_ITEM_SELECTOR!r} not found) — Yandex may have "
            "changed the overview page's menu."
        ) from exc

    deadline = time.monotonic() + _ARCHIVE_VERIFY_TIMEOUT_MS / 1000
    updated = existing
    while time.monotonic() < deadline:
        updated = _find_master_row(page, campaign_id)
        if updated is not None and updated["Status"] == "ARCHIVED":
            break
        page.wait_for_timeout(250)

    if updated is None or updated["Status"] != "ARCHIVED":
        raise BrowserSessionError(
            f"Clicked 'Архивировать' for campaign {campaign_id}, but the "
            f"campaigns grid did not report it as ARCHIVED within "
            f"{_ARCHIVE_VERIFY_TIMEOUT_MS / 1000:.0f}s. The click may not "
            "have hit the right element, or Yandex is slow to apply it — "
            "verify manually before retrying."
        )

    return updated


def _set_weekly_budget(page: "Page", amount: int) -> None:
    """Fill the "Недельный бюджет" input with ``amount`` (bare integer, no grouping).

    Located by heading-proximity XPath (see ``_WEEKLY_BUDGET_INPUT_XPATH``) —
    the input has no stable id/data-testid (see module docstring).
    """
    field = page.locator(_WEEKLY_BUDGET_INPUT_XPATH).first
    try:
        field.click()
        field.fill(str(amount))
    except PlaywrightError as exc:
        raise BrowserSessionError(
            "Could not find or fill the weekly budget input ('Недельный "
            "бюджет') on the campaign edit page — Yandex may have changed "
            "the page's markup. Re-run with --headful to inspect the page."
        ) from exc


def _set_directs_helps(page: "Page", enabled: bool) -> None:
    """Check/uncheck the "Директ помогает" auto-recommendations checkbox.

    Scoped to the FIRST checkbox following the "Директ помогает" heading only
    (see ``_DIRECT_HELPS_CHECKBOX_XPATH``) — checking it reveals a second,
    nested checkbox ("Оптимизировать расширенные настройки...") that is out
    of scope for Этап A and must be left untouched.
    """
    checkbox = page.locator(_DIRECT_HELPS_CHECKBOX_XPATH).first
    try:
        if enabled:
            checkbox.check()
        else:
            checkbox.uncheck()
    except PlaywrightError as exc:
        raise BrowserSessionError(
            "Could not find or toggle the 'Директ помогает' checkbox "
            "('Автоматически применять рекомендации') on the campaign edit "
            "page — Yandex may have changed the page's markup. Re-run with "
            "--headful to inspect the page."
        ) from exc


def _trigger_shows_selection(trigger, label: str) -> bool:
    """True if the "Цель продвижения" trigger button currently shows ``label``.

    Confirmed live (2026-08-01 re-investigation, see
    ``tests/fixtures/masters_wizard_edit_stage_a.html``): the trigger's
    ``inner_text()`` is TWO lines — the static section label first, then the
    current selection on its own line (unlike the accessibility-tree
    computed NAME, which stays static and never carries the selection). An
    exact match against the whole two-line string can therefore never
    succeed; only the LAST line reflects the live selection.
    """
    try:
        text = trigger.inner_text().strip()
    except PlaywrightError:
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return bool(lines) and lines[-1] == label


def _set_promotion_goal(page: "Page", goal: str) -> None:
    """Select ``goal`` (a key of ``PROMOTION_GOAL_CHOICES``) in the "Цель
    продвижения" dropdown.

    Opens the dropdown (click the trigger button), clicks the option row
    whose text matches the target Russian label, then verifies the trigger
    button's own text now reflects the new selection — mirrors
    ``_suspend_or_resume``'s "never trust the click alone" convention.
    """
    label = PROMOTION_GOAL_CHOICES.get(goal)
    if label is None:
        raise ValueError(
            f"Unknown promotion goal {goal!r}; expected one of "
            f"{sorted(PROMOTION_GOAL_CHOICES)}."
        )

    trigger = page.locator(_PROMOTION_GOAL_BUTTON_XPATH).first
    try:
        trigger.click()
    except PlaywrightError as exc:
        raise BrowserSessionError(
            "Could not find or open the 'Цель продвижения' dropdown on the "
            "campaign edit page — Yandex may have changed the page's "
            "markup. Re-run with --headful to inspect the page."
        ) from exc

    # get_by_role scopes to actual clickable option rows (not any container
    # whose text happens to contain the label as a substring) — see the
    # cycle-review finding this fixed: the previous get_by_text(exact=False)
    # could match an ancestor wrapper instead of the option itself.
    option = page.get_by_role("option", name=label, exact=True)
    clicked = False
    try:
        count = option.count()
    except PlaywrightError:
        count = 0
    for i in range(count):
        handle = option.nth(i)
        try:
            if not handle.is_visible():
                continue
            handle.click()
            clicked = True
            break
        except PlaywrightError:
            continue

    if not clicked:
        raise BrowserSessionError(
            f"Could not find the {label!r} option in the 'Цель продвижения' "
            "dropdown on the campaign edit page — Yandex may have changed "
            "the page's markup. Re-run with --headful to inspect the page."
        )

    if not _trigger_shows_selection(trigger, label):
        try:
            current = trigger.inner_text().strip()
        except PlaywrightError:
            current = ""
        raise BrowserSessionError(
            f"Clicked the {label!r} option for 'Цель продвижения', but the "
            f"dropdown still does not show it (shows {current!r}). The "
            "click may not have hit the right element — verify manually "
            "before retrying."
        )


def _click_save(page: "Page", campaign_id: int) -> None:
    """Click the edit page's single "Сохранить кампанию" button.

    Confirmed live: the whole edit page is one form with exactly one save
    button at the bottom (see module docstring) — there is no per-section
    save to target instead.
    """
    # get_by_role scopes to the actual <button> element (exact accessible
    # name), not any ancestor container whose text merely contains this
    # substring — see the cycle-review finding this fixed.
    save_button = page.get_by_role("button", name=_SAVE_BUTTON_TEXT, exact=True)
    try:
        count = save_button.count()
    except PlaywrightError:
        count = 0
    for i in range(count):
        handle = save_button.nth(i)
        try:
            if not handle.is_visible():
                continue
            handle.click()
            return
        except PlaywrightError:
            continue
    raise BrowserSessionError(
        f"Could not find the '{_SAVE_BUTTON_TEXT}' button on the edit page "
        f"for campaign {campaign_id} — Yandex may have changed the page's "
        "markup. Re-run with --headful to inspect the page."
    )


def _read_weekly_budget(page: "Page") -> Optional[int]:
    """Read the "Недельный бюджет" input's current bare-integer value.

    Returns ``None`` if the field can't be found/read — the caller treats
    that as "verification inconclusive", not as a specific budget value.
    """
    field = page.locator(_WEEKLY_BUDGET_INPUT_XPATH).first
    try:
        raw = field.input_value()
    except PlaywrightError:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _read_directs_helps(page: "Page") -> Optional[bool]:
    """Read the "Директ помогает" checkbox's current checked state.

    Returns ``None`` if the field can't be found/read (inconclusive).
    """
    checkbox = page.locator(_DIRECT_HELPS_CHECKBOX_XPATH).first
    try:
        return checkbox.is_checked()
    except PlaywrightError:
        return None


def _read_promotion_goal_label(page: "Page") -> Optional[str]:
    """Read the "Цель продвижения" dropdown trigger's current selection.

    The trigger's ``inner_text()`` is two lines — the static section label,
    then the current selection on its own line (see
    ``_trigger_shows_selection``) — so this returns only the LAST line, not
    the raw two-line text, to compare directly against a bare
    ``PROMOTION_GOAL_CHOICES`` value. Returns ``None`` if the trigger can't
    be found/read (inconclusive).
    """
    trigger = page.locator(_PROMOTION_GOAL_BUTTON_XPATH).first
    try:
        text = trigger.inner_text().strip()
    except PlaywrightError:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else None


def _verify_saved(
    page: "Page",
    campaign_id: int,
    *,
    weekly_budget: Optional[int],
    promotion_goal: Optional[str],
    directs_helps: Optional[bool],
) -> None:
    """Reload the edit page and confirm every requested field actually saved.

    Never trust the save-button click alone (mirrors ``_suspend_or_resume``'s
    "a click that doesn't visibly change the state is a hard error, not a
    silent success" convention) — Yandex's client-side validation can reject
    a value and leave the form open with an inline error that this module
    has no stable way to read (see module docstring's "Save verification"
    note, issue #631's own "Валидация... непрозрачна" risk). Re-navigating
    and re-reading each touched field is the only reliable signal available:
    if a field still doesn't match after a real reload, the save did not
    take effect and this raises rather than reporting false success.
    """
    url = WIZARD_EDIT_URL.format(campaign_id=campaign_id)
    page.goto(url, wait_until="domcontentloaded")
    assert_not_captcha(page.content())
    assert_authenticated(page.content())

    mismatches = []

    if weekly_budget is not None:
        actual = _read_weekly_budget(page)
        if actual != weekly_budget:
            mismatches.append(
                f"weekly_budget: expected {weekly_budget}, page now shows {actual!r}"
            )

    if directs_helps is not None:
        actual_checked = _read_directs_helps(page)
        if actual_checked != directs_helps:
            mismatches.append(
                f"directs_helps: expected {directs_helps}, page now shows "
                f"{actual_checked!r}"
            )

    if promotion_goal is not None:
        expected_label = PROMOTION_GOAL_CHOICES[promotion_goal]
        actual_label = _read_promotion_goal_label(page)
        if actual_label != expected_label:
            mismatches.append(
                f"promotion_goal: expected {expected_label!r}, page now shows "
                f"{actual_label!r}"
            )

    if mismatches:
        raise BrowserSessionError(
            f"Clicked '{_SAVE_BUTTON_TEXT}' for campaign {campaign_id}, but "
            "re-reading the edit page after reload shows it did not save "
            "as requested: " + "; ".join(mismatches) + ". Yandex may have "
            "rejected the value (client-side validation) or the save did "
            "not complete — verify manually before retrying."
        )


def update_master(
    page: "Page",
    campaign_id: int,
    *,
    weekly_budget: Optional[int] = None,
    promotion_goal: Optional[str] = None,
    directs_helps: Optional[bool] = None,
) -> Dict[str, Any]:
    """Update one or more Этап A fields of a Мастер кампаний and save.

    Only fields passed as non-``None`` are touched — see module docstring for
    why this is safe despite the page having a single whole-form save (fields
    left alone keep their current on-page value simply by never having their
    input touched). Raises ``ValueError`` if no field is provided, mirroring
    the rest of the CLI's "nothing to update" guard for partial updates.

    After clicking save, reloads the edit page and re-reads every requested
    field to confirm it actually saved (see ``_verify_saved``) — a click
    that doesn't visibly change the saved state is reported as a hard error,
    not a silent success, mirroring ``_suspend_or_resume``.

    Later Этап (B/C/D) fields — headline/text lists, sitelinks, audience,
    Metrika counters/goals, budget adaptation, media — are out of scope for
    this function; see issue #631.
    """
    if weekly_budget is None and promotion_goal is None and directs_helps is None:
        raise ValueError(
            "update_master requires at least one field to update "
            "(weekly_budget, promotion_goal, directs_helps)."
        )

    url = WIZARD_EDIT_URL.format(campaign_id=campaign_id)
    page.goto(url, wait_until="domcontentloaded")
    assert_not_captcha(page.content())
    assert_authenticated(page.content())

    if weekly_budget is not None:
        _set_weekly_budget(page, weekly_budget)
    if promotion_goal is not None:
        _set_promotion_goal(page, promotion_goal)
    if directs_helps is not None:
        _set_directs_helps(page, directs_helps)

    _click_save(page, campaign_id)

    _verify_saved(
        page,
        campaign_id,
        weekly_budget=weekly_budget,
        promotion_goal=promotion_goal,
        directs_helps=directs_helps,
    )

    result: Dict[str, Any] = {"CampaignId": campaign_id}
    if weekly_budget is not None:
        result["WeeklyBudget"] = weekly_budget
    if promotion_goal is not None:
        result["PromotionGoal"] = promotion_goal
    if directs_helps is not None:
        result["DirectsHelps"] = directs_helps
    return result


def _fill_landing_url(page: "Page", url: str) -> None:
    """Fill step 1's URL field and click "Далее" to advance to step 2.

    Confirmed live: "Далее" is clickable even when the field holds a
    malformed value — it does not disable on format, so a click is always
    needed to trigger the (purely client-side) validation. If Yandex
    rejects the format, this raises :class:`BrowserSessionError` immediately
    instead of waiting the full step-2 timeout for a page that will never
    render (see ``_CREATE_INVALID_URL_TEXT``).
    """
    field = page.get_by_placeholder(_CREATE_URL_INPUT_PLACEHOLDER)
    try:
        field.click()
        field.fill(url)
    except PlaywrightError as exc:
        raise BrowserSessionError(
            "Could not find or fill the landing-page URL field on the "
            "Мастер кампаний create page — Yandex may have changed the "
            "page's markup. Re-run with --headful to inspect the page."
        ) from exc

    # get_by_role scopes to the actual <button> element (exact accessible
    # name), mirroring the fix applied to update_master's _click_save/
    # _set_promotion_goal (issue #631 review) — a get_by_text(exact=False)
    # substring match could hit an ancestor container instead of the button.
    next_button = page.get_by_role("button", name=_CREATE_NEXT_BUTTON_TEXT, exact=True)
    clicked = False
    try:
        count = next_button.count()
    except PlaywrightError:
        count = 0
    for i in range(count):
        handle = next_button.nth(i)
        try:
            if not handle.is_visible():
                continue
            handle.click()
            clicked = True
            break
        except PlaywrightError:
            continue
    if not clicked:
        raise BrowserSessionError(
            f"Could not find the {_CREATE_NEXT_BUTTON_TEXT!r} button on the "
            "Мастер кампаний create page — Yandex may have changed the "
            "page's markup. Re-run with --headful to inspect the page."
        )

    error = page.get_by_text(_CREATE_INVALID_URL_TEXT, exact=False)
    try:
        count = error.count()
    except PlaywrightError:
        count = 0
    if count:
        raise BrowserSessionError(
            f"Yandex rejected {url!r} as a malformed URL "
            f"({_CREATE_INVALID_URL_TEXT!r}) — pass a well-formed "
            "http(s):// URL."
        )


def _wait_for_step2(page: "Page") -> None:
    """Block until step 2's long form has rendered.

    Confirmed live this can take 10-15s+ after clicking "Далее" — Yandex
    scans the landing page's content server-side to pre-fill headlines,
    texts, and images before rendering the rest of the form. Polls for the
    "Регион показов" heading (the one field guaranteed to be present and
    genuinely empty — see module docstring) rather than a fixed sleep.
    """
    region_heading = page.get_by_text("Регион показов", exact=False)
    deadline = time.monotonic() + _CREATE_STEP2_TIMEOUT_MS / 1000
    while time.monotonic() < deadline:
        with contextlib.suppress(PlaywrightError):
            if region_heading.count():
                return
        page.wait_for_timeout(250)

    raise BrowserSessionError(
        "Timed out waiting for the Мастер кампаний create form's step 2 "
        f"(the 'Регион показов' section) to render within "
        f"{_CREATE_STEP2_TIMEOUT_MS / 1000:.0f}s. Yandex may be slow to "
        "scan the landing page, or the page's markup changed — re-run with "
        "--headful to inspect the page."
    )


def _add_repeating_values(page: "Page", xpath: str, values: List[str]) -> None:
    """Fill+submit each of ``values`` into a repeating list field (headlines/texts).

    Confirmed live these sections start pre-populated by Yandex's own AI
    scan of the landing page (see module docstring) — this module does not
    clear that pre-filled list first; it only ever adds the caller's own
    values on top, since the create-page's DOM offers no stable "clear all"
    control and blindly clicking every visible "x" risks removing an
    unrelated section's items (sitelinks, images) that share the same close
    icon. Callers who want the AI-generated defaults gone entirely must
    remove them by hand (``--headful``) before scripting the rest.
    """
    for value in values:
        field = page.locator(xpath).first
        try:
            field.click()
            field.fill(value)
            field.press("Enter")
        except PlaywrightError as exc:
            raise BrowserSessionError(
                f"Could not add {value!r} via the create page's input at "
                f"{xpath!r} — Yandex may have changed the page's markup. "
                "Re-run with --headful to inspect the page."
            ) from exc


def _read_repeating_values(page: "Page", xpath: str) -> List[str]:
    """Read every value currently entered into a repeating list field.

    Used by ``_verify_created`` to confirm ``_add_repeating_values`` actually
    persisted each value — mirrors ``update_master``'s ``_read_weekly_budget``
    etc. Returns whatever the matched inputs currently hold; an unreadable
    input is treated as an empty string rather than aborting the whole read,
    since a partial mismatch is exactly what the caller needs to see.
    """
    values = []
    locator = page.locator(xpath)
    try:
        count = locator.count()
    except PlaywrightError:
        return values
    for i in range(count):
        try:
            values.append(locator.nth(i).input_value())
        except PlaywrightError:
            values.append("")
    return values


def _set_region(page: "Page", regions: List[str]) -> None:
    """Fill the "Регион показов" combobox with each of ``regions``.

    The one field confirmed live to start genuinely empty (see module
    docstring) — every other required-looking section has an AI-generated
    or sane default. Selects each typed region from the dropdown's first
    matching suggestion, mirroring how a human picks from the combobox
    rather than typing free text the server may not accept.

    Uses ``get_by_role("option", ...)`` rather than a substring
    ``get_by_text`` match, same fix as ``update_master``'s
    ``_set_promotion_goal`` (issue #631 review): a container whose text
    merely contains the region name is not the same element as the actual
    clickable suggestion row.
    """
    field = page.locator(_REGION_INPUT_XPATH).first
    for region in regions:
        try:
            field.click()
            field.fill(region)
        except PlaywrightError as exc:
            raise BrowserSessionError(
                "Could not find or fill the 'Регион показов' field on the "
                "Мастер кампаний create page — Yandex may have changed the "
                "page's markup. Re-run with --headful to inspect the page."
            ) from exc

        option = page.get_by_role("option", name=region, exact=True)
        try:
            count = option.count()
        except PlaywrightError:
            count = 0
        clicked = False
        for i in range(count):
            handle = option.nth(i)
            try:
                if not handle.is_visible():
                    continue
                handle.click()
                clicked = True
                break
            except PlaywrightError:
                continue
        if not clicked:
            raise BrowserSessionError(
                f"Could not find {region!r} in the 'Регион показов' "
                "suggestion list on the Мастер кампаний create page — check "
                "the region name matches Yandex's own wording."
            )


def _read_region_tags(page: "Page") -> List[str]:
    """Read the "Регион показов" field's currently selected region tags.

    The combobox is expected to render each accepted selection as a
    removable tag/chip rather than leaving it in the free-text input (typing
    and selecting an option clears the input back to empty — confirmed by
    ``_set_region``'s own click-then-fill-again loop over multiple regions).
    This function has NOT been live-verified against the actual tag markup
    (issue #632 step 0 recon was read-only, see module docstring) — it reads
    the same input's current value as a best-effort fallback, which will
    only ever reflect the LAST region typed, not the full accepted set. A
    follow-up live pass must confirm the real tag-list markup and replace
    this with an accurate reader before trusting multi-region verification.
    """
    field = page.locator(_REGION_INPUT_XPATH).first
    try:
        return [field.input_value()]
    except PlaywrightError:
        return []


def _set_weekly_budget_on_create(page: "Page", amount: int) -> None:
    """Fill the create page's "Недельный бюджет" input (same shape as update_master's).

    A separate function (not shared with ``update_master``'s
    ``_set_weekly_budget``, issue #631) because the two pages are otherwise
    unrelated DOM trees — the XPath happens to match by coincidence (both
    key off the same heading text), not by design; keeping them separate
    avoids a false coupling if either page's markup drifts independently.
    """
    field = page.locator(_WEEKLY_BUDGET_INPUT_XPATH).first
    try:
        field.click()
        field.fill(str(amount))
    except PlaywrightError as exc:
        raise BrowserSessionError(
            "Could not find or fill the weekly budget input ('Недельный "
            "бюджет') on the Мастер кампаний create page — Yandex may have "
            "changed the page's markup. Re-run with --headful to inspect "
            "the page."
        ) from exc


def _click_terminal_button(page: "Page", text: str) -> None:
    """Click one of the create page's two terminal buttons (launch/draft).

    Uses ``get_by_role("button", ..., exact=True)`` rather than a substring
    ``get_by_text`` match — same fix applied to ``update_master``'s
    ``_click_save`` (issue #631 review): scopes to the actual clickable
    button element, not any ancestor container whose text merely contains
    this label.
    """
    button = page.get_by_role("button", name=text, exact=True)
    try:
        count = button.count()
    except PlaywrightError:
        count = 0
    for i in range(count):
        handle = button.nth(i)
        try:
            if not handle.is_visible():
                continue
            handle.click()
            return
        except PlaywrightError:
            continue
    raise BrowserSessionError(
        f"Could not find the {text!r} button on the Мастер кампаний create "
        "page — Yandex may have changed the page's markup. Re-run with "
        "--headful to inspect the page."
    )


def _verify_created(
    page: "Page",
    *,
    headlines: List[str],
    texts: List[str],
    weekly_budget: Optional[int],
) -> None:
    """Confirm the fields this module actually set are still present after the
    terminal click, rather than trusting the click alone.

    Ported from ``update_master``'s ``_verify_saved`` (issue #631 review
    finding): a click on "Запустить кампанию"/"Сохранить как черновик" is not
    proof Yandex accepted the form — client-side validation can reject a
    value silently. Unlike ``_verify_saved``, this does NOT re-navigate and
    reload first: issue #632 step 0 recon never confirmed what URL the
    launch/draft click lands on (module docstring), so there is no known
    page to reload yet. This re-reads the CURRENT page's fields immediately
    after the click instead — a strictly weaker check than a real reload,
    but the strongest one available until a live pass confirms the
    post-click destination. Region is intentionally NOT verified here: see
    ``_read_region_tags``'s docstring for why its reader is not yet reliable
    enough to gate a hard failure on.
    """
    mismatches = []

    actual_headlines = _read_repeating_values(page, _HEADLINES_ADD_INPUT_XPATH)
    for headline in headlines:
        if headline not in actual_headlines:
            mismatches.append(
                f"headline {headline!r} not found among current values "
                f"{actual_headlines!r}"
            )

    actual_texts = _read_repeating_values(page, _TEXTS_ADD_INPUT_XPATH)
    for text in texts:
        if text not in actual_texts:
            mismatches.append(
                f"text {text!r} not found among current values {actual_texts!r}"
            )

    if weekly_budget is not None:
        field = page.locator(_WEEKLY_BUDGET_INPUT_XPATH).first
        try:
            raw = field.input_value()
        except PlaywrightError:
            raw = ""
        digits = "".join(ch for ch in raw if ch.isdigit())
        actual_budget = int(digits) if digits else None
        if actual_budget != weekly_budget:
            mismatches.append(
                f"weekly_budget: expected {weekly_budget}, page now shows "
                f"{actual_budget!r}"
            )

    if mismatches:
        raise BrowserSessionError(
            "Clicked the create page's terminal button, but re-reading the "
            "page afterwards shows it did not take effect as requested: "
            + "; ".join(mismatches)
            + ". Yandex may have rejected the form "
            "(client-side validation) or the click did not land — verify "
            "manually before retrying."
        )


def create_master(
    page: "Page",
    url: str,
    *,
    headlines: List[str],
    texts: List[str],
    regions: List[str],
    weekly_budget: Optional[int] = None,
    launch: bool = True,
) -> Dict[str, Any]:
    """Create a new Мастер кампаний ("Конверсии и трафик" type) end to end.

    Not idempotent (see issue #632 module docstring / issue body): calling
    this twice with the same arguments creates a SECOND campaign, not an
    update to the first — Мастер кампаний has no API-level duplicate
    detection the way ``campaigns add`` does. Callers must not blindly
    retry a failed/uncertain call without first checking ``masters list``.

    ``headlines``/``texts``/``regions`` are required CLI-side (not merely
    UI-required) even though Yandex's own wizard auto-populates
    headlines/texts by scanning ``url``'s content — this module refuses to
    silently launch AI-generated ad copy the caller never reviewed, given
    there is no sandbox and no rollback for Мастер кампаний (issue #632
    "Риски"). Pass the AI-suggested text back explicitly if that's what you
    want published.

    ``launch=True`` (default) clicks "Запустить кампанию"; ``launch=False``
    clicks "Сохранить как черновик" instead. After clicking, re-reads the
    headline/text/budget fields to confirm the form actually reflects what
    was requested (see ``_verify_created``) rather than trusting the click
    alone — mirrors ``update_master``'s ``_verify_saved`` convention (issue
    #631 review). Neither button's post-click landing page was live-verified
    during recon (issue #632 step 0 was read-only, see
    ``tests/fixtures/masters_wizard_create.html``) — in particular, where the
    created/drafted campaign's ID can be read from (URL redirect vs. an
    on-page confirmation element) is NOT yet determined, so this returns
    only the fields the caller supplied, not a ``CampaignId`` — a follow-up
    live pass must confirm the ID source before that can be added.
    """
    if not headlines:
        raise ValueError("create_master requires at least one headline.")
    if not texts:
        raise ValueError("create_master requires at least one ad text.")
    if not regions:
        raise ValueError("create_master requires at least one region.")

    page.goto(WIZARD_CREATE_URL, wait_until="domcontentloaded")
    assert_not_captcha(page.content())
    assert_authenticated(page.content())

    _fill_landing_url(page, url)
    _wait_for_step2(page)

    _add_repeating_values(page, _HEADLINES_ADD_INPUT_XPATH, headlines)
    _add_repeating_values(page, _TEXTS_ADD_INPUT_XPATH, texts)
    _set_region(page, regions)
    if weekly_budget is not None:
        _set_weekly_budget_on_create(page, weekly_budget)

    _click_terminal_button(
        page, _LAUNCH_BUTTON_TEXT if launch else _SAVE_DRAFT_BUTTON_TEXT
    )

    _verify_created(
        page,
        headlines=headlines,
        texts=texts,
        weekly_budget=weekly_budget,
    )

    result: Dict[str, Any] = {
        "LandingUrl": url,
        "Headlines": headlines,
        "Texts": texts,
        "Regions": regions,
        "Launched": launch,
    }
    if weekly_budget is not None:
        result["WeeklyBudget"] = weekly_budget
    return result
