"""
Мастер кампаний (Campaign Wizard) read-only browser scraping.

Мастер кампаний has no API surface at all — see the package docstring in
``direct_cli/browser/__init__.py``. This module reads the same pages a human
would: the campaigns grid (for ``list``) and the per-campaign wizard page (for
``get``), both server-side rendered — there is no JSON endpoint carrying this
data (see ``tests/fixtures/masters_wizard_overview.html`` for the network
capture that established this).

Detection of a Мастер кампаний row in the grid does NOT count action links
(fragile — Yandex could add a link to any row type). Instead it keys off a
structural URL signal captured live: a Мастер кампаний row's campaign-name
link points at ``/wizard/campaigns/{id}/``, while every other campaign type's
name link points at ``/dna/grid/groups?...campaigns-ids={id}``.
"""

import re
from typing import TYPE_CHECKING, Any, Dict, List

from ..output import print_warning
from .session import assert_authenticated, assert_not_captcha

if TYPE_CHECKING:
    from playwright.sync_api import Page

try:
    from playwright.sync_api import Error as PlaywrightError
except ImportError:  # pragma: no cover - exercised only when playwright is absent
    PlaywrightError = Exception  # type: ignore[assignment,misc]

GRID_URL = "https://direct.yandex.ru/dna/grid/campaigns/"
WIZARD_OVERVIEW_URL = "https://direct.yandex.ru/wizard/campaigns/{campaign_id}/"

_WIZARD_HREF_RE = re.compile(r"/wizard/campaigns/(\d+)/")

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


def fetch_masters_list(page: "Page", login: str) -> List[Dict[str, Any]]:
    """Return every Мастер кампаний row visible in the campaigns grid.

    Navigates the grid with ``status-filter=ALL_EXCEPT_ARCHIVED`` (matching the
    CLI's other list commands, which don't surface archived resources by
    default) and filters rows by the ``/wizard/campaigns/{id}/`` href signal.
    """
    url = f"{GRID_URL}?ulogin={login}&status-filter=ALL_EXCEPT_ARCHIVED"
    # domcontentloaded, not networkidle: Yandex's login page holds long-poll
    # connections that keep the network "busy" forever, so networkidle never
    # settles there — it turned an auth failure into an opaque 30s timeout
    # instead of the explicit assert_authenticated error below (#634).
    page.goto(url, wait_until="domcontentloaded")
    assert_not_captcha(page.content())
    assert_authenticated(page.content())

    rows = page.locator("a[href*='/wizard/campaigns/']")
    count = rows.count()

    seen_ids: set = set()
    masters: List[Dict[str, Any]] = []
    for i in range(count):
        row = rows.nth(i)
        href = row.get_attribute("href") or ""
        match = _WIZARD_HREF_RE.search(href)
        if not match:
            continue
        campaign_id = int(match.group(1))
        if campaign_id in seen_ids:
            continue
        seen_ids.add(campaign_id)

        name = row.inner_text().strip()
        masters.append({"CampaignId": campaign_id, "Name": name})

    if not masters:
        print_warning(
            "No Мастер кампаний rows detected in the grid. Either the account "
            "has none, or Yandex changed the grid markup this parser keys off "
            "(a[href*='/wizard/campaigns/'])."
        )
    return masters


def fetch_master(page: "Page", campaign_id: int, login: str) -> Dict[str, Any]:
    """Fetch overview details for one Мастер кампаний by navigating its wizard page.

    Best-effort: a section this parser doesn't recognise is omitted from the
    result (with a warning), rather than failing the whole command — Yandex's
    internal markup has no stability guarantee (see module docstring).
    """
    url = f"{WIZARD_OVERVIEW_URL.format(campaign_id=campaign_id)}?ulogin={login}"
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
