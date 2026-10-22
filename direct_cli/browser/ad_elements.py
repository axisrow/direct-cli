"""
Per-ad element restrictions from the web UI's banners grid (issue #892).

The Yandex Direct API has no per-element display-restriction surface: the
ads WSDL carries ``AdCategories``/``StatusClarification`` at the ad level
only, and the per-element ``Status``/``StatusClarification`` pairs that do
exist (on responsive-ad assets) describe *moderation*, not the
category-driven display restrictions this module reads. Live example
(campaign 71149490, 2026-10-10): ``ads.get`` reported the ad
``AdCategories=MEDICINE`` and ``StatusClarification="Активно"``, while the
UI warned on the ad's headlines: «Показы запрещены в части заданных
регионов … „Медицинские услуги" …». Docs re-check (2026-10-22): the API
docs confirm categories are assigned at moderation, are immutable via the
API, and their display restrictions («показ запрещён / выводятся
предупреждения» per RF law) are not modelled per element anywhere.

Like ``masters.py``'s ``list`` (#639) and ``change_history.py`` (#837), this
module does NOT hand-build queries or scrape rendered rows. Live recon
2026-10-22 (account ``ksamatadirect``) found the banners grid
(``/dna/grid/banners?campaigns-ids=<id>``) fires exactly three data calls
that between them carry everything the UI shows:

* ``POST /api/v6/ads:list`` — per-ad composition: ``titles[]``, ``bodies[]``,
  ``moderation_flags`` (e.g. ``MODERATION_FLAGS_MED_SERVICES``),
  ``aggregated_status`` (``RUN_WARN`` + machine ``reasons``), ``href``;
* ``POST /web-api/grid/api?operationName=AdDisclaimers`` — per-ad
  ``disclaimer`` («Есть противопоказания. Посоветуйтесь с врачом.») and
  ``disclaimerCategories`` (the popup's full explanation, e.g. «Ваши
  объявления относятся к категории „Медицина и фармацевтика“ …»), plus
  per-asset moderation verdicts (``adaptiveTextImages[].moderationVerdict``,
  ``adaptiveTextVideos``, ``titleAssets``, ``bodyAssets``);
* ``GET /api/v6/ads:batchGet?ad_ids=…`` — per-ad statistics (lazy; the
  module waits a short grace period for it but reports ``metrics: {}``
  without it).

These are the same surfaces the UI itself renders: the row's
``DisclaimerButton`` opens a popup whose texts are verbatim the
``AdDisclaimers`` fields, and the row's aggregated-status cell renders its
wording (e.g. «Для показа в заданных регионах предоставьте документы») as
static DOM text — no hovering required anywhere.

Granularity note (verified live against the UI's own popup): the warning is
an AD-level fact — the popup says «Добавлено 1 предупреждение» for the whole
ad, and neither data call splits it per headline (``titleAssets``/
``bodyAssets`` were ``null``; should Yandex start populating them, the
parser below picks the fields up as elements of their own). The output
therefore attaches each ad's warnings to every element of that ad, with the
machine ``reason`` kept alongside the raw UI texts.
"""

import contextlib
import json
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from . import _clock
from .._captcha import find_captcha_marker, find_marker
from .session import (
    BrowserSessionError,
    _LOGIN_PAGE_MARKERS,
    assert_authenticated,
    assert_not_captcha,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from playwright.sync_api import Page

try:  # pragma: no cover - import shape mirrors masters.py/change_history.py
    from playwright.sync_api import Error as PlaywrightError
except ImportError:  # pragma: no cover
    PlaywrightError = Exception

# The banners grid: the UI's own view of a campaign's ads. Navigating it
# (filtered to one campaign) is what makes the three data calls fire; the
# page itself adds its ``ulogin`` query parameter, so it is deliberately not
# built here (same convention as GRID_URL — passing one's own login as
# ``ulogin`` is the managed-client parameter, see masters.py's module
# docstring).
BANNERS_URL = "https://direct.yandex.ru/dna/grid/banners"

# The three data calls, identified by URL. ``ads:list`` and ``AdDisclaimers``
# are required — the read is meaningless without either; ``ads:batchGet``
# (statistics) is lazy and optional.
_ADS_LIST_PATH = "/api/v6/ads:list"
_ADS_BATCH_GET_PATH = "/api/v6/ads:batchGet"
_DISCLAIMERS_MARKER = "operationName=AdDisclaimers"

# Budget for observing the two required calls after ``goto`` (the page is
# the same class of SPA as the grid — see masters.py's navigation notes for
# why ``commit`` + content polling rather than ``networkidle``).
_ADS_CAPTURE_TIMEOUT_MS = 30_000
# batchGet fires after the initial render; a short independent grace period,
# a non-fatal wait (an absent stats payload degrades to ``metrics: {}``).
_BATCH_GET_GRACE_MS = 10_000
_POLL_TICK_MS = 250


def _capture_banners_payloads(page: "Page", url: str) -> Dict[str, Any]:
    """Navigate the banners grid and capture its three data calls.

    The response listener is attached BEFORE the single ``goto`` (issue
    #892 recon: a second navigation to the same URL gets treated as a fresh
    page load and can land on the login screen), and the poll loop re-checks
    for a captcha/login page every tick so a mid-load redirect surfaces as
    the specific ``BrowserAuthError``/``BrowserCaptchaError`` instead of a
    generic capture timeout (same discipline as masters.py's
    ``_edit_form_terminal_state``).
    """
    captured: Dict[str, Any] = {}

    def on_response(resp: Any) -> None:
        u = resp.url
        with contextlib.suppress(ValueError, PlaywrightError):
            # A non-JSON body (or a response racing page teardown) is never
            # ours to parse; the poll below simply keeps waiting.
            if _ADS_LIST_PATH in u and "ads" not in captured:
                captured["ads"] = json.loads(resp.text())
            elif _DISCLAIMERS_MARKER in u and "disclaimers" not in captured:
                captured["disclaimers"] = json.loads(resp.text())
            elif _ADS_BATCH_GET_PATH in u and "batch_get" not in captured:
                captured["batch_get"] = json.loads(resp.text())

    page.on("response", on_response)
    try:
        page.goto(url, wait_until="commit")
        html = page.content()
        assert_not_captcha(html)
        assert_authenticated(html)

        def _redirected() -> Optional[str]:
            current = page.content()
            if find_captcha_marker(current) is not None:
                return "captcha"
            if find_marker(current, _LOGIN_PAGE_MARKERS) is not None:
                return "auth"
            return None

        deadline = _clock.now() + _ADS_CAPTURE_TIMEOUT_MS / 1000
        while _clock.now() < deadline:
            if "ads" in captured and "disclaimers" in captured:
                break
            state = None
            with contextlib.suppress(PlaywrightError):
                state = _redirected()
            if state == "captcha":
                assert_not_captcha(page.content())  # re-raises
            if state == "auth":
                assert_authenticated(page.content())  # re-raises
            page.wait_for_timeout(_POLL_TICK_MS)

        missing = [name for name in ("ads", "disclaimers") if name not in captured]
        if missing:
            raise BrowserSessionError(
                "The banners grid did not produce its data calls "
                f"(missing: {', '.join(missing)}) within "
                f"{_ADS_CAPTURE_TIMEOUT_MS / 1000:.0f}s for {url}. Yandex "
                "may have changed the page's internal API, the campaign may "
                "have no banners-grid view (Мастер кампаний campaigns are "
                "edited in the wizard instead), or the page is unusually "
                "slow to load. Re-run with --headful to inspect the page."
            )

        # Non-fatal grace period for the lazy statistics call.
        stats_deadline = _clock.now() + _BATCH_GET_GRACE_MS / 1000
        while "batch_get" not in captured and _clock.now() < stats_deadline:
            page.wait_for_timeout(_POLL_TICK_MS)
    finally:
        with contextlib.suppress(PlaywrightError):
            page.remove_listener("response", on_response)

    return captured


def _parse_disclaimers(payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Index the AdDisclaimers rowset by ad id.

    The call's envelope is ``{"data": {"client": {"ads": {"rowset": [...]}}}}``
    (live capture 2026-10-22); a structurally-changed payload yields ``{}``
    rather than raising — the warnings column degrades to the machine flags
    from ``ads:list`` instead of failing the whole read.
    """
    with contextlib.suppress(KeyError, TypeError):
        rowset = payload["data"]["client"]["ads"]["rowset"]
        return {str(row["id"]): row for row in rowset if row.get("id")}
    return {}


def _parse_stats(payload: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Index ``ads:batchGet``'s per-ad statistics by ad id."""
    if not payload:
        return {}
    with contextlib.suppress(TypeError):
        return {
            str(ad["id"]): ad.get("stats") or {}
            for ad in payload.get("ads") or []
            if ad.get("id")
        }
    return {}


def _compact_metrics(stats: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce batchGet's stats to the handful of fields worth reporting.

    Costs arrive as ``amount_micros`` strings; report roubles (the UI's own
    unit for «Расход») rounded to 2 decimals.
    """
    if not stats:
        return {}

    def _roubles(micros_obj: Any) -> Optional[float]:
        with contextlib.suppress(TypeError, ValueError):
            return round(int(micros_obj["amount_micros"]) / 1_000_000, 2)
        return None

    metrics: Dict[str, Any] = {}
    for key in ("shows", "clicks"):
        if stats.get(key) is not None:
            metrics[key] = int(stats[key])
    cost = _roubles(stats.get("cost_with_tax"))
    if cost is not None:
        metrics["cost"] = cost
    for key in ("avg_ctr", "avg_bounce_rate", "conversion_rate"):
        if stats.get(key) is not None:
            metrics[key] = stats[key]
    return metrics


def _ad_warnings(
    ad: Dict[str, Any], disclaimer_row: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Build the single ad-level warning entry (or ``[]`` for a clean ad).

    ``reason`` is the machine vocabulary (``aggregated_status.reasons`` +
    ``moderation_flags``), falling back to the short disclaimer; the UI's
    own wording rides in ``raw_tooltip`` — verbatim popup texts
    (``disclaimer`` + ``disclaimerCategories``), falling back to the machine
    parts when Yandex serves no explanation text.
    """
    status = ad.get("aggregated_status") or {}
    machine_parts = list(status.get("reasons") or []) + list(
        ad.get("moderation_flags") or []
    )
    disclaimer = (disclaimer_row.get("disclaimer") or "").strip()
    categories = (disclaimer_row.get("disclaimerCategories") or "").strip()

    reason = "; ".join(machine_parts) or disclaimer
    raw_tooltip = "\n".join(part for part in (disclaimer, categories) if part) or (
        "; ".join(machine_parts)
    )
    if not reason and not raw_tooltip:
        return []
    return [{"reason": reason, "raw_tooltip": raw_tooltip}]


def _leaf_values(node: Any):
    """Yield every scalar leaf of a nested dict/list structure."""
    if isinstance(node, dict):
        for value in node.values():
            yield from _leaf_values(value)
    elif isinstance(node, (list, tuple)):
        for value in node:
            yield from _leaf_values(value)
    else:
        yield node


def _verdict_to_reason(verdict: Any) -> Optional[str]:
    """Normalize a per-asset ``moderationVerdict`` to a reason string.

    A structured verdict counts as a warning only when it carries non-empty
    content somewhere: the live МК sweep (2026-10-22) served
    ``{"disclaimer": {"title": "", "description": ""}}`` on perfectly clean
    image assets, and stringifying that wholesale would manufacture a
    warning out of nothing. Strings pass through (empty string = none).
    """
    if verdict is None:
        return None
    if isinstance(verdict, str):
        return verdict or None
    if not any(leaf for leaf in _leaf_values(verdict) if isinstance(leaf, str)):
        return None
    return json.dumps(verdict, ensure_ascii=False)


def build_ad_elements(
    ads_payload: Dict[str, Any],
    disclaimers_payload: Dict[str, Any],
    stats_payload: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Flatten the captured payloads into the issue's per-element schema.

    One row per ad element (title/text/image/video), each carrying its ad's
    warnings, so the CLI output answers both «какие элементы» and «по какой
    причине» with ordinary ``--format``/jq slicing.
    """
    disclaimers = _parse_disclaimers(disclaimers_payload)
    stats = _parse_stats(stats_payload)

    elements: List[Dict[str, Any]] = []
    for ad in ads_payload.get("ads") or []:
        ad_id = str(ad.get("id"))
        if ad_id == "None":
            continue
        disclaimer_row = disclaimers.get(ad_id, {})
        warnings = _ad_warnings(ad, disclaimer_row)
        shared = {
            "ad_id": ad_id,
            "warnings": warnings,
            "metrics": _compact_metrics(stats.get(ad_id, {})),
            "ad_status": (ad.get("aggregated_status") or {}).get("status"),
            "moderation_flags": ad.get("moderation_flags") or [],
            "ad_group_id": ad.get("ad_group_id"),
            "href": ad.get("href") or "",
        }

        def _element(element_type, text, shared=shared, **extra):
            verdict = extra.pop("_verdict", None)
            verdict = _verdict_to_reason(verdict)
            element = {**shared, "element_type": element_type, "text": text}
            element.update(extra)
            if verdict:
                element["warnings"] = element["warnings"] + [
                    {"reason": verdict, "raw_tooltip": verdict}
                ]
            return element

        def _verdict_of(asset):
            return asset.get("moderationVerdict") if isinstance(asset, dict) else None

        ad_elements_rows = [
            _element("title", title, title_index=index + 1)
            for index, title in enumerate(ad.get("titles") or [])
        ]
        ad_elements_rows += [_element("text", body) for body in ad.get("bodies") or []]
        for image in disclaimer_row.get("adaptiveTextImages") or []:
            ad_elements_rows.append(
                _element("image", image.get("name") or "", _verdict=_verdict_of(image))
            )
        for video in disclaimer_row.get("adaptiveTextVideos") or []:
            text = (
                video
                if isinstance(video, str)
                else json.dumps(video, ensure_ascii=False)
            )
            ad_elements_rows.append(
                _element("video", text, _verdict=_verdict_of(video))
            )

        if not ad_elements_rows:
            # An ad with no composition at all must still surface its
            # warnings («элемент, на котором висит ограничение, отличается
            # от заголовка/текста — определять и его тоже»): one row at the
            # ad level instead of silently dropping the ad.
            ad_elements_rows.append(_element("ad", ""))
        elements.extend(ad_elements_rows)
    return elements


def fetch_ad_elements(
    page: "Page",
    campaign_id: int,
    *,
    group_ids: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    """Navigate the campaign's banners grid and return its ad elements.

    ``group_ids`` narrows the read to specific ad groups (the UI's own
    ``groups-ids`` filter); ``None`` reads every group the page loads for
    the campaign.
    """
    url = f"{BANNERS_URL}?campaigns-ids={campaign_id}"
    if group_ids:
        url += "&groups-ids=" + ",".join(str(g) for g in group_ids)
    captured = _capture_banners_payloads(page, url)
    return build_ad_elements(
        captured["ads"], captured["disclaimers"], captured.get("batch_get")
    )
