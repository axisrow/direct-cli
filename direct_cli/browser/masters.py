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

``suspend_master``/``resume_master`` (issue #630) — **live-verified
2026-08-06** against campaign 713277109 over 12 real transitions (issues
#766/#764). Both action buttons carry a stable ``data-testid``, read
directly off the live DOM rather than guessed:
``CampaignHeader.ActionButton.stop`` ("Остановить кампанию", rendered while
ACTIVE/MODERATION) and ``CampaignHeader.ActionButton.resume``
("Возобновить кампанию", rendered while SUSPENDED). Note the suspend side's
testid is ``.stop``, named after the Russian label rather than after this
module's own verb. ``_SUSPEND_BUTTON_TEXTS``/``_RESUME_BUTTON_TEXTS`` are
retained only as a fallback (and as the vocabulary the "could not find the
button" error reports), no longer the primary locator.

**The first click on a freshly rendered overview page is frequently a
silent no-op** — this was issue #766's root cause, and it also explains the
symptom #758 misattributed to a too-small timeout. Confirmed live by
capturing every network request after the click: ``.click()`` returns
without raising, Playwright's actionability checks all pass, and NO request
is issued at all — React's own click handler was not yet attached. Waiting
longer cannot help in that state, which is why #766's reporter saw a
permanent failure that repeated CLI runs never fixed, while ``masters
update``'s "always works on the second try" behaviour comes from the same
race resolving itself between runs. ``_click_and_wait_for_status_change``
therefore re-clicks (up to ``_STATUS_CLICK_MAX_ATTEMPTS``) instead of
waiting longer, re-reading the status immediately before every retry so an
already-effective click is never repeated — the same treatment
``_click_and_wait_for_popup`` already gives the "⋮" menu and the rename
modal (issues #723/#725). Once a click does land, the status text follows
within 1.6–2.3s (measured, n=12 — see ``_STATUS_CHANGE_TIMEOUT_MS``).
Either action still re-reads the page's status to verify the change really
happened, never trusting the click alone.

That pre-retry re-read matters because the poll has a deadline: a click
whose status update arrives after it must not be clicked again, or suspend
would toggle straight back and unarchive would re-archive. For the same
reason a button that has *vanished* between the read and the click is
checked against the status before being reported as missing — for
``resume`` the page swaps ``.resume`` for ``.stop`` the moment the status
flips, so "the button is gone" is usually proof the mutation succeeded, not
evidence of a markup change.

``archive_master`` (issue #633, live-recon confirmed no separate "delete"
exists for Мастер кампаний — only archive; see the issue comment). Both
the campaigns-grid row menu and the overview page's own "⋮" menu were
inspected live: neither has a "Удалить" item, only "Архивировать" (grid
row menu also has Перейти/Редактировать/Статистика/Запустить-Остановить;
overview menu has only Клонировать/Архивировать, or just Клонировать —
see the transition matrix below). Confirmed live, stable ``data-testid``
attributes back the overview menu: ``CampaignHeader.MenuTrigger`` (opens
the "⋮" dropdown), ``CampaignHeader.Menu.archive`` (the "Архивировать"
menu item), and ``CampaignHeader.Menu.unarchive`` (the "Разархивировать"
item, ARCHIVED-only) — unlike suspend/resume's text-based matching, none
of these depend on Russian button copy. Archiving is verified via
``fetch_masters_list`` (the grid API's ``primaryStatus``); the overview
page's own status text ALSO has a confirmed marker for "archived" now
(issue #730, "Кампания в\xa0архиве" — see ``_read_status_text``), which
the two-step transitions below rely on for their intermediate check.

Two-step status transitions (issue #758, live-confirmed 2026-08-05 against
campaign 713277109 through a full round trip archived -> ... -> archived).
Both ``resume_master`` and ``archive_master`` are single clicks that only
work from one specific starting status — the UI has no direct
ARCHIVED<->ACTIVE transition, and this module now walks the intermediate
step itself instead of failing:

============  ============================================  ============
Status        "⋮" menu contents / action button              -> leads to
============  ============================================  ============
ARCHIVED      menu: ONLY "Разархивировать" (unarchive item). -> SUSPENDED
              No resume button on the page at all.
SUSPENDED     button: "Возобновить кампанию".                -> ACTIVE or
              menu: Клонировать + Архивировать.                 MODERATION
ACTIVE /      button: "Остановить кампанию".                 -> SUSPENDED
MODERATION    menu: ONLY "Клонировать" — no archive item.
============  ============================================  ============

Resuming a SUSPENDED campaign can land in either ACTIVE or MODERATION
depending on whether Yandex decides the campaign needs re-review (a fresh
or edited campaign goes to moderation; an already-approved one returns
directly to ACTIVE) — this is not something the caller can predict ahead
of time, so ``resume_master`` treats both as success and returns whichever
one actually happened.

``update_master`` (issue #631, Этап A) — live-verified against campaign
107707079 (see ``tests/fixtures/masters_wizard_edit_stage_a.html`` for the
full investigation notes). Covers exactly three fields: weekly budget,
promotion goal, and the "Директ помогает" auto-recommendations toggle.

``update_master`` headlines/texts (issue #665, Этап B) — live-verified
against campaign 107707079 (see
``tests/fixtures/masters_wizard_edit_stage_b.html``). Replaces the text of
ONE existing headline/text slot at a time (``_set_repeating_value``), NOT
the whole variant list — a deliberate departure from this CLI's usual
"update replaces the whole array" list-field convention (see
``_set_repeating_value``'s own docstring for the rationale). Writing to an
empty slot (adding a brand-new variant) is refused; deleting a variant and
editing variant weights are both tracked as separate follow-ups, not
implemented here. Later stages (sitelinks, audience, Metrika counters/goals,
budget adaptation, media uploads) are tracked in issue #648 and are NOT
implemented here.

``name`` (issue #663) — live-verified against campaigns 713231614 (DRAFT)
and 107707079 (non-draft, read-only recon) — see
``tests/fixtures/masters_wizard_edit_name.html``. Unlike the Этап A fields
above, the name is edited via a separate modal
(``CampaignHeader.EditName.Button`` → ``ModalEditTitle.CampaignName`` →
"Применить") rather than a plain form input, but the modal's own
"Применить" only updates the page's optimistic/local state — the rename is
persisted only by the same terminal save action every other field here
relies on, so this module never trusts the modal click alone (verified via
the header's displayed name after a real reload).

**DRAFT support** (issue #668). A DRAFT campaign's edit page renders NO
"Сохранить кампанию" button at all — only
``CampaignFormControls.saveDraft.button`` ("Сохранить как черновик") and
``CampaignFormControls.save.button`` (labelled "Запустить кампанию" here,
NOT "Сохранить кампанию" — same testid suffix as the non-DRAFT save button,
different label and consequence: this one publishes the draft). Confirmed
live against campaign 713231614 (2026-08-02, read-only recon before any
code change). ``_is_draft_edit_page`` detects DRAFT by the presence of
``saveDraft.button`` itself, so the detection and the click it gates can
never disagree about what "DRAFT" means. ``update_master``'s ``launch``
kwarg (CLI: ``masters update --launch``) defaults to ``False`` — saving a
DRAFT keeps it a DRAFT unless the caller explicitly asks to publish it,
mirroring ``create_master``/``copy_master``'s own draft-preserving
defaults. Originally out of scope for #663 (see #660's initial gap report);
#665's live verification needed a working DRAFT save path to exercise, so
it was implemented here instead of deferred further.

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

**Step 2 markup migration (issue #653, re-recon 2026-08-02).** Following
#650's URL-field fix, live testing found the rest of step 2 had ALSO
migrated to new markup — headlines/texts moved from a "single current-
variant input, fill + Enter" flow to a FIXED set of pre-rendered
contenteditable slots (``CampaignTitles{N}.textarea``/
``CampaignTexts{N}.textarea``, 5/3 slots respectively, most pre-filled with
Yandex's AI-generated copy — see ``_add_repeating_values``), and the region
picker moved from a text combobox with an autocomplete dropdown to a
tree/tag-group widget (``RegionsTreeEditor``) whose typed filter
auto-expands every ancestor/descendant of a match — see ``_set_region``.
Weekly budget, "Директ помогает", and "Цель продвижения" were re-confirmed
live to still use their pre-#653 heading-proximity XPaths unchanged (they
were not affected by this markup migration).

``copy_master`` (issue #659, live-verified end to end against campaign
107707079 — a draft copy, 713231614, was actually created and confirmed in
the campaigns grid during recon). The overview menu's "Клонировать" item
(``CampaignHeader.Menu.clone``, confirmed live alongside
``CampaignHeader.Menu.archive`` — see the ``archive_master`` note above) does
NOT clone instantly: it navigates to ``WIZARD_CREATE_URL``, landing on the
same step-2 form ``create_master`` uses, pre-filled end to end from the
source campaign (headlines, texts, images, video, display region, Metrika
counters, target actions, weekly budget) — Yandex itself appends " — N" to
the cloned campaign's name. ``_wait_for_step2`` (already used by
``create_master``) is reused as-is: the pre-fill is server-side and just as
slow (confirmed live ~14s), and the clone form's "Регион показов" heading is
the same marker. The same two terminal buttons apply
(``_LAUNCH_BUTTON_TEXT``/``_SAVE_DRAFT_BUTTON_TEXT`` via
``_click_terminal_button``) — ``copy_master`` defaults to the draft button,
mirroring ``create_master``'s CLI-level ``--draft`` default. After clicking,
Yandex redirects ``page.url`` to ``WIZARD_OVERVIEW_URL`` with the new
campaign's ID (confirmed live, ~7s after the click) — the primary ID source
— and this is cross-checked against a ``fetch_masters_list`` grid diff
(confirmed to agree during recon) before reporting success, following the
module's "never trust the click alone" convention.

**DRAFT overview page** (issue #660, live-confirmed 2026-08-04 against
campaign 713231614 — see ``tests/fixtures/masters_wizard_draft_overview.html``).
A freshly created ``DRAFT`` campaign's overview page (``WIZARD_OVERVIEW_URL``
itself, no ``/edit/``) turns out to BE the editable wizard form — no "⋮"
menu, no ``CampaignHeader.MenuTrigger``, no "Кампания остановлена"/"активна"
status text, no stat tiles — rather than the stats-dashboard overview every
other status renders. It reuses the SAME header testids the edit page's
DRAFT path already relies on for its terminal save/launch buttons
(``CampaignFormControls.saveDraft.button``/``CampaignFormControls.save.button``,
see "DRAFT support" above), plus ``CampaignHeader.TitleName``,
``CampaignHeader.Status`` (reads "Черновик"), and
``BudgetWithSuggest.PriceTextInput`` for the weekly budget field.
``fetch_master`` detects this via ``_is_draft_overview_page`` (keyed off
``CampaignHeader.Status`` reading "Черновик", mirroring
``_is_draft_edit_page``'s "detection and the click it gates can never
disagree" rationale) and reads name/status/weekly budget from the form
instead of the dashboard extractors — no ``LandingUrl``/``Stats`` (the form
has no rendered landing-URL link with the confirmed ``utm_source=`` marker,
and obviously no stats yet). No delete action exists for a Мастер кампаний
draft anywhere in the UI (checked live: neither this page nor the grid row's
own menu has one) — so ``archive_master``/``suspend_master``/
``resume_master`` all refuse with a clear ``BrowserSessionError`` on a
``DRAFT`` campaign instead of clicking blind at selectors that don't exist
on this page (``archive_master`` already reads the campaign's grid row
before navigating, so this is a plain status check added there;
``suspend``/``resume`` check ``_is_draft_overview_page`` right after
navigating, before ``_read_status_text`` would otherwise report "unrecognised
status text"). ``copy_master`` itself does not depend on any of these working.

**Menu/modal-trigger hydration race** (issues #723/#725). Live testing found
that clicking a trigger element which is itself visible/enabled — the "⋮"
menu trigger (``_MENU_TRIGGER_SELECTOR``, used by ``archive_master`` and
``copy_master``) or the name-edit pencil button
(``_EDIT_NAME_BUTTON_SELECTOR``, used by ``_set_campaign_name``) — sometimes
does not open the popup/modal it controls: the click physically lands
(Playwright's own actionability check only inspects the DOM element, not
whether React's click handler or the portal that renders the popup has
finished hydrating), but nothing opens. ``_click_and_wait_for_popup`` is the
shared fix: click the trigger, wait briefly for the expected popup element to
become visible, and retry the whole click if it doesn't, up to
``_POPUP_CLICK_MAX_ATTEMPTS`` times, before raising a clear error. Safe to
retry unconditionally here — unlike the terminal save/launch buttons
(``_click_draft_terminal_button``), opening a menu or a rename modal has no
side effect on the campaign itself.
"""

import contextlib
import json
import os
import re
import sys
from urllib.parse import urlsplit
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

from . import _clock
from .._captcha import find_captcha_marker, find_marker
from ..output import print_warning
from .session import (
    _LOGIN_PAGE_MARKERS,
    BrowserAuthError,
    BrowserCaptchaError,
    BrowserSessionError,
    assert_authenticated,
    assert_not_captcha,
)

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

# GridCampaigns' primaryStatus value for an archived campaign (issue #730,
# live-confirmed 2026-08-04 against campaign 713277109 — see
# ``_widen_filter_status_for_archived``).
_ARCHIVED_PRIMARY_STATUS = "ARCHIVED"

# ``status`` values whose predicate can match an archived row -- these need
# ``_widen_filter_status_for_archived`` to run before replaying the captured
# request, everything else can replay the grid UI's own default filter as-is.
_ARCHIVE_INCLUDING_STATUSES = frozenset({"archived", "all"})

# Stat-tiles section render marker (issue #708, live recon 2026-08-04 against
# 12 live ACTIVE campaigns in one account — see _extract_stat_tiles). Each
# tile carries a stable ``data-testid`` of ``ChartSummary.<key>`` (confirmed
# live: shows/clicks/conversions/cpa/cost — see _STAT_TILE_TESTID_KEYS)
# inside the same ``ChartSummary`` chart-container the overview
# page always renders. Unlike the previous text-based button scan, this
# needs no label/whitespace normalisation and no consecutive-stable-tick
# heuristic: live recon (12/12 runs, 9 distinct campaigns, 50ms poll
# granularity) found the DOM has NO partial state at all — the section
# renders zero ``ChartSummary.*`` nodes, then all five atomically in the
# same React commit (first-observed-with-any-tile-present == first-observed-
# with-all-five-present in every run). Network capture of the same loads
# confirmed why: the tiles are driven by a single
# ``GET /wizard/web-api/aggregate?...`` XHR whose response arrives ~1-2ms
# before the DOM update, not a piecemeal per-tile render — so unlike
# _wait_for_images_editor's stub/ghost render passes, there is no
# loading-skeleton state to distinguish from "genuinely fewer tiles" here,
# because live data never showed fewer than 5. This resolves #708's
# open question for the confirmed-live shape: wait for the marker, don't
# guess with a tick count.
_STAT_TILE_TESTID_PREFIX = "ChartSummary."
_STAT_TILE_TESTID_KEYS = {
    "shows": "impressions",
    "clicks": "clicks",
    "conversions": "conversions",
    "cpa": "cost_per_conversion",
    "cost": "cost",
}

# Overview-page action buttons for resume/suspend. Confirmed live 2026-08-06
# (issue #766) against campaign 713277109: BOTH buttons carry a stable
# `data-testid` — `CampaignHeader.ActionButton.resume` (label "Возобновить
# кампанию", rendered while SUSPENDED) and `CampaignHeader.ActionButton.stop`
# (label "Остановить кампанию", rendered while ACTIVE/MODERATION). The
# suspend-side testid is `.stop`, NOT `.suspend` — named after the Russian
# label, not after this module's own verb.
#
# These replace text matching as the PRIMARY locator, the same way
# `_MENU_TRIGGER_SELECTOR`/`_ARCHIVE_MENU_ITEM_SELECTOR` already do for the
# "⋮" menu: a testid read off a live DOM does not depend on Russian button
# copy. The text candidates below are kept only as a fallback for the case
# where Yandex renames a testid, and — separately — because they are what
# lets `_click_action_button` report what it actually saw on the page when
# neither locator matches (issue #766 asked for exactly that).
_RESUME_BUTTON_SELECTOR = '[data-testid="CampaignHeader.ActionButton.resume"]'
_SUSPEND_BUTTON_SELECTOR = '[data-testid="CampaignHeader.ActionButton.stop"]'

# Fallback label candidates, matched case-insensitively as a substring. Both
# "Возобновить кампанию" and "Остановить кампанию" are now confirmed live
# (issue #766) — the suspend side was previously an unverified guess (#630).
# Note `get_by_text` matches the <span class="dc-Button__text"> INSIDE the
# button, not the <button> itself, which is why the fallback path resolves
# `.locator("xpath=ancestor-or-self::button[1]")` before clicking.
_RESUME_BUTTON_TEXTS = ("Возобновить кампанию", "Возобновить")
_SUSPEND_BUTTON_TEXTS = ("Остановить кампанию", "Приостановить кампанию", "Остановить")

# How long to wait, after an action-button click, for the status text to
# actually change before treating that click as a no-op and retrying.
#
# Measured live 2026-08-06 (issue #764) against campaign 713277109 over 12
# real transitions across two runs (suspend and resume, alternating):
# latency from the *effective* click to the overview page's status text
# reporting the new status was 1.64s..2.28s (mean 1.8s) — every single
# sample, with no long tail. The 60s from #758 was never measuring that
# latency: it was masking the no-op-first-click bug below (issue #766), where
# the status never changes at all no matter how long you wait. 8s is ~3.5x
# the observed max, generous for a figure this tightly clustered, and small
# enough that a genuinely dead click is retried in seconds instead of after a
# full minute.
_STATUS_CHANGE_TIMEOUT_MS = 8_000

# How long to wait for the status element to render *at all* after navigating,
# BEFORE any click — a different quantity from the post-click budget above,
# and deliberately a separate constant.
#
# `_goto_overview_page` only guarantees the title rendered (issue #683); the
# status element is a later render pass. The 1.6-2.3s measurement above is the
# lag from an *effective click* to the status text updating — it says nothing
# about how long a freshly navigated page takes to render that element in the
# first place, which was never measured. Before #766 this wait was inline in
# `resume_master` with the then-current 60s budget; folding it into
# `_STATUS_CHANGE_TIMEOUT_MS` would have silently cut it to 8s.
#
# That matters because `resume_master` branches on this read: a campaign whose
# ARCHIVED status has not hydrated yet reads as None, skips the unarchive step,
# and then hunts for a resume button an archived page never renders — leaving
# the campaign archived and reporting a misleading "could not find" error. So
# this keeps the pre-#766 value until real numbers replace it; see
# `_log_timing` for how those numbers are being collected.
_STATUS_HYDRATION_TIMEOUT_MS = 60_000

# How many times to click the action button before giving up (issue #766).
#
# Live-confirmed 2026-08-06 against campaign 713277109: the FIRST click on a
# freshly navigated overview page is frequently a silent no-op — Playwright's
# actionability checks pass, `.click()` returns without raising, and NO
# network request is issued at all (verified by capturing every request after
# the click: only unrelated telemetry). React's own click handler was not yet
# attached. A second click, a few seconds later, lands and mutates. Over 12
# measured transitions this needed at most 2 clicks, non-deterministically —
# it is a hydration race, not a property of a particular action or status.
#
# This is the same failure mode `_click_and_wait_for_popup` already handles
# for the "⋮" menu and the rename modal (issues #723/#725); suspend/resume
# was simply never given the equivalent retry, so #766's reporter saw a
# permanent failure that no amount of waiting or re-running could fix.
#
# Retrying is safe HERE specifically because suspend/resume is idempotent
# and reversible, and because each attempt re-checks the status first: if an
# earlier click did land, the loop exits before clicking again. Contrast
# `_click_draft_terminal_button`, which deliberately never retries — a
# duplicated launch is not reversible.
_STATUS_CLICK_MAX_ATTEMPTS = 4

# Overview page's header title, confirmed live (issue #683) as the earliest
# stable marker of a rendered wizard overview page — present on BOTH a
# DRAFT campaign's page (which has no "⋮" menu at all, see _MENU_TRIGGER_
# SELECTOR below and issue #660) and every other status. Unlike the plain
# `h1, [role=heading]` CSS selector `_extract_title` uses (which matches
# nothing here — the real element is an `<h2 data-testid="CampaignHeader.
# Title">` with no explicit `role` attribute), this selector is exact.
_OVERVIEW_TITLE_SELECTOR = '[data-testid="CampaignHeader.Title"]'

# Overview page's landing-page link, confirmed live 2026-08-06 (issue #763).
# The previous selector, `a[href*='utm_source=']`, targeted the *content* of
# an href rather than a stable element identity, and that content is not
# unique to the campaign's own link: the page always also renders a Yandex
# promo banner ("Yandex Neuro Ads") whose href is itself UTM-tagged
# (`ya.ru/project/yna/?utm_source=yandex&utm_medium=direct&...`). When the
# campaign's own LandingUrl carries no UTM tail (e.g. right after `update
# --landing-url` with UTMInput left untouched, per #761), that banner becomes
# the *only* href-based match and `.first` silently returns it instead of the
# campaign's link — this is the exact "stale LandingUrl" symptom reported in
# #763 (it isn't a cache: the selector was simply reading the wrong anchor).
# When the campaign's LandingUrl does carry a UTM tail, both anchors match
# and the campaign's own link happens to win only by DOM order, i.e. the old
# selector was correct by accident in that case.
# `[data-testid="Link"]` alone is not unique either (8 matches on a typical
# overview page: sidebar entries, footer links, the campaign-id caption,
# etc.) — scoping to the `CampaignHeader` container is required and yields
# exactly 1 match in both cases confirmed live above.
_OVERVIEW_LANDING_LINK_SELECTOR = '[data-testid="CampaignHeader"] a[data-testid="Link"]'

# How long to wait for `_OVERVIEW_TITLE_SELECTOR` to render after navigating
# to WIZARD_OVERVIEW_URL (issue #683). Confirmed live: the overview page can
# take several seconds after `wait_until="commit"` returns before its React
# tree paints anything at all.
_OVERVIEW_LOAD_TIMEOUT_MS = 30_000

# How long _extract_stat_tiles waits for _STAT_TILE_TESTID_PREFIX's marker
# after the title has rendered but before the stat tiles themselves have
# (issue #683). Confirmed live (campaign 72349978, headless): the title
# (`_OVERVIEW_TITLE_SELECTOR`) is present well before the stat tiles finish
# rendering — a single post-title read intermittently found 0 of them
# despite the campaign genuinely having 5. As slow as
# _OVERVIEW_LOAD_TIMEOUT_MS itself: live headless recon measured the tiles
# finishing their OWN render up to ~15s after the title, not the sub-second
# gap a headful/extension browser showed — these are two independent SPA
# render passes, not one paint. #708's follow-up recon found the real
# marker (see _STAT_TILE_TESTID_PREFIX) so this timeout now gates a single
# explicit wait instead of a tick-stabilization heuristic, but the same
# generous budget still applies since the underlying render latency is
# unchanged.
_STAT_TILES_TIMEOUT_MS = 30_000


# How long to wait, after launch_master's click already redirected away from
# /edit/, for the overview page's own status text to report MODERATION
# (issue #704). Live-confirmed 2026-08-04: the overview page reflected the
# new status immediately after the redirect (well under 10s), unlike the
# campaigns grid's primaryStatus, which lagged the same transition by 45+
# seconds in the same recon — see launch_master's docstring for why the
# grid is deliberately not used for this half of the check. Navigation
# itself now goes through _goto_overview_page (issue #683), so this budget
# only needs to cover the status-text poll after that page has rendered.
_LAUNCH_VERIFY_TIMEOUT_MS = 15_000

# Overview page's "⋮" menu, confirmed live (issue #633) — see module
# docstring. Unlike _RESUME_BUTTON_TEXTS/_SUSPEND_BUTTON_TEXTS these are
# selectors, not text-matched candidates: both testids were read directly off
# a live account's DOM, not guessed. NOT present on a DRAFT campaign's
# overview page (issue #660) — callers that need it (archive_master,
# copy_master) still only wait for _OVERVIEW_TITLE_SELECTOR via
# _goto_overview_page; DRAFT support for the menu-based actions remains the
# tracked #660 gap, not something this fixes.
_MENU_TRIGGER_SELECTOR = '[data-testid="CampaignHeader.MenuTrigger"]'
_ARCHIVE_MENU_ITEM_SELECTOR = '[data-testid="CampaignHeader.Menu.archive"]'
# Confirmed live (issue #659) alongside the archive item above — same menu,
# same testid convention.
_CLONE_MENU_ITEM_SELECTOR = '[data-testid="CampaignHeader.Menu.clone"]'
# Confirmed live 2026-08-05 (issue #758) on campaign 713277109: an ARCHIVED
# campaign's "⋮" menu contains ONLY this item — there is no "Возобновить"
# button on the page at all, which is why resume_master could never work
# starting from ARCHIVED (see the module docstring's transition matrix).
_UNARCHIVE_MENU_ITEM_SELECTOR = '[data-testid="CampaignHeader.Menu.unarchive"]'

# Issues #723/#725: live testing found that clicking a trigger element that
# is itself visible/enabled (CampaignHeader.MenuTrigger for the "⋮" menu,
# CampaignHeader.EditName.Button for the name-edit pencil) does not always
# open the popup/modal it controls — React's click handler or the portal
# rendering the popup can still be hydrating even though Playwright's own
# actionability check (which only looks at the DOM element, not React's
# internal readiness) already considers the element clickable. The click
# itself does not raise in this case; it is simply swallowed. A short
# wait-then-retry loop (see _click_and_wait_for_popup) absorbs this without
# conflating it with a genuinely missing/renamed selector, which still fails
# loudly after every retry is exhausted.
_POPUP_APPEAR_TIMEOUT_MS = 1_500
_POPUP_CLICK_MAX_ATTEMPTS = 3

# How long to wait, after clicking Архивировать, for the grid API to report
# the campaign as ARCHIVED before giving up (see archive_master).
_ARCHIVE_VERIFY_TIMEOUT_MS = 10_000

# DRAFT overview page support (issue #660, live-confirmed 2026-08-04 against
# campaign 713231614 — see the module docstring's "DRAFT overview page" note).
# A DRAFT campaign's overview page (WIZARD_OVERVIEW_URL itself, no "/edit/")
# renders the editable wizard form, not the stats dashboard: no
# CampaignHeader.MenuTrigger, no status text ("Кампания остановлена"/
# "активна"), no stat tiles. It reuses the SAME header/terminal-button testids
# as the edit page's DRAFT path (_DRAFT_SAVE_DRAFT_BUTTON_TESTID/
# _DRAFT_LAUNCH_BUTTON_TESTID above), plus its own header ones below.
_CAMPAIGN_HEADER_TITLE_NAME_SELECTOR = '[data-testid="CampaignHeader.TitleName"]'
_CAMPAIGN_HEADER_STATUS_SELECTOR = '[data-testid="CampaignHeader.Status"]'
_BUDGET_INPUT_SELECTOR = '[data-testid="BudgetWithSuggest.PriceTextInput"]'
_DRAFT_STATUS_TEXT = "Черновик"

# How long to wait, right after navigating to the overview page, for EITHER
# CampaignHeader.Status (DRAFT) or the non-DRAFT dashboard's own status body
# text (see _read_status_text) to hydrate before classifying the page.
# wait_until="domcontentloaded" returns before the SPA's client-side render
# has necessarily produced either — the same race that #685 already fixed
# for the create page's step 1 field (_wait_for_create_step1) via
# _poll_until rather than a bare .count() snapshot.
_DRAFT_OVERVIEW_DETECT_TIMEOUT_MS = 15_000

# How long to wait, after clicking the clone form's terminal button, for
# Yandex to redirect page.url to the new campaign's overview URL (confirmed
# live ~7s, issue #659) before giving up on copy_master.
_CLONE_VERIFY_TIMEOUT_MS = 20_000

# How long to wait for the DRAFT edit page's saveDraft/launch click to
# redirect away from /edit/ (issue #668) — live-confirmed ~5s in one recon,
# generous headroom for a slower response.
_DRAFT_SAVE_REDIRECT_TIMEOUT_MS = 20_000

# Matches WIZARD_OVERVIEW_URL's {campaign_id} once Yandex redirects there
# after a successful clone save/launch (see copy_master).
_WIZARD_OVERVIEW_URL_ID_RE = re.compile(r"/wizard/campaigns/(\d+)/")

# "Цель продвижения" dropdown options, confirmed live by opening the dropdown
# on the edit page — exactly these two rows exist, no others (see
# tests/fixtures/masters_wizard_edit_stage_a.html). CLI-facing enum keys are
# kebab-case (this field has no WSDL to mirror, unlike the rest of the CLI).
PROMOTION_GOAL_CHOICES = {
    "max-conversions": "Максимум целевых действий",
    "max-clicks": "Максимум переходов",
}

# Yandex's own internal enum values for each PROMOTION_GOAL_CHOICES key,
# confirmed live 2026-08-04 (issue #696 recon) via each option row's
# data-testid (``CampaignTargetSelect.TargetSelect.ListBox.<value>``). These
# ALSO gate whether ``CampaignTargetSelect.PriceInput`` (the --goal-price
# field) exists at all — see ``_set_goal_price``.
PROMOTION_GOAL_INTERNAL_VALUES = {
    "max-conversions": "INVOLVED_CONVERSION",
    "max-clicks": "DIRECT_CLICK",
}

# create_master (issue #632) — confirmed live, see
# tests/fixtures/masters_wizard_create.html.
WIZARD_CREATE_URL = "https://direct.yandex.ru/wizard/campaigns/new/"

# Step 1's only field (issue #650 re-recon, 2026-08-02): Yandex replaced the
# plain <input placeholder="..."> with a Combobox whose text control is a
# contenteditable <div role="textbox"> — confirmed live it still carries the
# same placeholder text, but Playwright's get_by_placeholder() only matches
# <input>/<textarea> elements, so it silently stopped finding this field.
# The field DOES carry a stable data-testid now, unlike most of this page
# (see module docstring) — confirmed live via page.content().
_CREATE_URL_INPUT_TESTID = '[data-testid="CampaignFormUrl.Textinput"]'

# Step 1's "Далее" button — confirmed live (issue #650 re-recon) it now also
# carries a stable data-testid, and only renders/becomes clickable after the
# URL field has text (unlike the old always-present button this replaced).
# Issue #690 re-recon (2026-08-04): this button ONLY renders when the typed
# URL has NO match in the account's suggestion history (see
# _CREATE_URL_LISTBOX_TESTID below) — when a match exists, Yandex shows a
# suggestions dropdown instead and this button never appears at all (count()
# stays 0 the whole time), so _fill_landing_url must not treat its absence
# as an error on its own.
_CREATE_NEXT_BUTTON_TESTID = '[data-testid="CampaignFormUrl.button"]'

# Issue #690 re-recon (2026-08-04, live against ksamatadirect account):
# typing ANY URL — matched in the account's suggestion history or not —
# renders a Combobox suggestions popup (a `role="listbox"` whose options
# each carry a `data-testid` of `CampaignFormUrl.listBox.<raw suggestion
# url>`, confirmed live), showing unrelated history when there's no real
# match. _CREATE_NEXT_BUTTON_TESTID is absent from the DOM only while a
# suggestion EXACTLY matching the typed URL exists — see _fill_landing_url,
# which locates that one option directly by its full data-testid rather
# than matching the popup as a whole, so an unrelated suggestion already
# showing is never clicked by mistake.

# How long to wait for either the suggestions popup or the "Далее" button to
# appear after typing — confirmed live the popup can take ~1-3s to render
# (it does its own debounced lookup against the account's history).
_CREATE_URL_RESPONSE_TIMEOUT_MS = 8_000

# Per-keystroke delay and retry budget for _type_landing_url (issue #690
# re-recon, 2026-08-04) — see its docstring for why a retry-with-verify loop
# is needed at all. 80ms is a human-typing-like rate; every live retry
# observed succeeded within 2 attempts, so 5 leaves generous headroom.
_TYPE_URL_DELAY_MS = 80
_TYPE_URL_MAX_ATTEMPTS = 5

# Confirmed live: this exact string appears under the URL field when the
# "Далее" click rejects the value as not a well-formed URL. Pure
# client-side check, no network round-trip.
_CREATE_INVALID_URL_TEXT = "Некорректный формат ссылки"

# How long to wait for step 2's long form to render after clicking "Далее" —
# confirmed live this can take 10-15s+ (Yandex scans the landing page's
# content to pre-fill headlines/texts/images), well within this budget.
_CREATE_STEP2_TIMEOUT_MS = 30_000

# How long to wait for step 1's URL field to render after ``goto`` (issue
# #685). Same SPA shape as the edit page (``_wait_for_images_editor``'s
# docstring): the create page hydrates client-side, so
# ``wait_until="commit"`` — which only waits for the response headers, not
# even the initial HTML parse ``domcontentloaded`` gives you — returns while
# step 1's own field is still absent from the DOM. 15s is generous for a
# static first step (no server-side scan happens until "Далее" is clicked).
_CREATE_STEP1_TIMEOUT_MS = 15_000

# Step 2 field locators for headlines/texts (issue #653 re-recon,
# 2026-08-02): Yandex replaced the single "current variant input + Enter"
# flow with a FIXED set of pre-rendered slots, each its own contenteditable
# <div role="textbox"> carrying a stable data-testid
# ``CampaignTitles{N}.textarea``/``CampaignTexts{N}.textarea`` (N = 0-based
# slot index) — confirmed live via ``document.querySelectorAll('[data-testid]')``
# on the create page. Confirmed live: exactly 5 headline slots and 3 text
# slots render, no "add another" control exists — most slots start
# pre-filled with Yandex's own AI-generated copy from scanning the landing
# page (see module docstring), only the trailing slots are genuinely empty.
# The old heading-proximity XPath (matched only h1/h2/h3) silently stopped
# matching because "Варианты заголовков"/"Варианты текстов объявлений" are
# plain text nodes on this page, not headings.
_HEADLINES_SLOT_COUNT = 5
_TEXTS_SLOT_COUNT = 3
_HEADLINES_TESTID_TEMPLATE = "CampaignTitles{index}.textarea"
_TEXTS_TESTID_TEMPLATE = "CampaignTexts{index}.textarea"

# Edit-page-ready marker (issue #684). ``goto(..., wait_until="commit")``
# returns as soon as the response headers are received — before ANY of the
# SPA's own JS has run — so every call site that immediately reads/writes a
# form field needs an explicit wait for real content first, same reasoning
# as ``_IMAGES_EDITOR_TIMEOUT_MS`` below. The first headline slot
# (``CampaignTitles0.textarea``) is the marker: headlines are not optional
# like images (see ``_HEADLINES_SLOT_COUNT``'s module-level comment), so
# slot 0 is guaranteed present on every rendered edit page, DRAFT or not
# (the DRAFT edit page still renders headlines/texts — see module docstring's
# "DRAFT support" note).
_EDIT_FORM_READY_TESTID = _HEADLINES_TESTID_TEMPLATE.format(index=0)
_EDIT_FORM_READY_TIMEOUT_MS = 30_000

# Images (issue #670, Этап D). Confirmed live 2026-08-02 against DRAFT clone
# 713234191 that images are a COMPLETELY different shape from headlines/texts
# above: there is no fixed slot count in the DOM at all — the edit page
# renders exactly as many ``ContentImage``/``CloseButton`` pairs as the
# campaign actually has images (observed: 4), keyed by a Yandex-assigned
# content ID, not a 0-based slot index. "Можно добавить до 5 штук" is an
# upper bound on the SET, not a slot count — unlike headlines/texts, an
# images set may legitimately be EMPTY (zero images is a valid state; there
# is no "at least one" invariant here). ``_IMAGES_MAX_COUNT`` therefore
# bounds the CLI's slot-number parsing only; the real per-campaign ceiling is
# always ``len(_read_image_content_ids(page))``, read fresh from the page.
_IMAGES_MAX_COUNT = 5
_IMAGES_EDITOR_SELECTOR = '[data-testid="ImageSuggestionsEditor"]'
# Loading skeleton the section renders BEFORE the real content resolves —
# confirmed live 2026-08-03 against campaigns 713234191/713234204 (both with
# 4 real images): ``ImageSuggestionsEditor`` itself appears first with four
# ``ImageSuggestionsEditor.CampaignContents.StubN`` placeholders (N=0-3) and
# NEITHER ``ContentImage.*`` NOR ``.Open`` present yet; the stubs are
# replaced by the real content ~3s later. Waiting only for
# ``_IMAGES_EDITOR_SELECTOR`` (what this constant guarded before) is
# insufficient — it returns during the stub window, so
# ``_read_image_content_ids`` reads ``[]`` for a campaign that demonstrably
# has 4 images, exactly the "empty list indistinguishable from not-yet-
# rendered" failure mode ``_wait_for_images_editor``'s own docstring already
# describes but did not fully guard against. See ``_wait_for_images_editor``.
_IMAGES_STUB_TESTID_PREFIX = "ImageSuggestionsEditor.CampaignContents.Stub"
_IMAGES_CONTENT_TESTID_PREFIX = "ImageSuggestionsEditor.CampaignContents.ContentImage."
_IMAGES_OPEN_MODAL_SELECTOR = '[data-testid="ImageSuggestionsEditor.Open"]'
_IMAGES_MODAL_SELECTOR = '[data-testid="ImageSuggestionsEditorModal"]'
_IMAGES_MODAL_FILE_INPUT_SELECTOR = (
    '[data-testid="ImageSuggestionsEditorModal.UploadZone.filePicker"]'
)
_IMAGES_MODAL_SELECTED_PREFIX = (
    "ImageSuggestionsEditorModal.SelectedImagesContainer.SelectedImage."
)
_IMAGES_MODAL_REMOVE_TESTID_TEMPLATE = (
    "ImageSuggestionsEditorModal.SelectedImagesContainer.SelectedImage."
    "{thumb_url}.CloseButton"
)
_IMAGES_MODAL_SAVE_SELECTOR = '[data-testid="ImageSuggestionsEditorModal.Save"]'
# ``accept=`` on Yandex's own file input (the selector above) is
# ``image/png,image/jpeg,image/jpg,image/gif`` — confirmed live 2026-08-02.
# Lives here, next to the input it describes, so the CLI's fail-fast check
# can't drift from what the page actually accepts (same reasoning as
# ``_IMAGES_MAX_COUNT``).
_IMAGE_UPLOAD_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif"})
_IMAGE_MODAL_OPEN_TIMEOUT_MS = 10_000
_IMAGE_UPLOAD_TIMEOUT_MS = 60_000
# The edit page is an SPA: ``goto(..., wait_until="domcontentloaded")``
# returns long before the images section exists in the DOM. Reading the set
# too early yields an empty list, which is INDISTINGUISHABLE from the
# legitimate "this campaign genuinely has no images" state — live-confirmed
# 2026-08-02 to make `--image` fail with a false "no images" on campaigns
# that demonstrably had four. Hence an explicit wait for the section itself
# before any read that a decision depends on (see `_wait_for_images_editor`).
# Bumped 30s -> 60s for issue #687's "ghost" render pass (see
# `_wait_for_images_editor`): that pass alone was observed lasting up to
# ~14.5s live before the real stub round even begins, and one full
# ghost+real timeline was clocked at 43.6s live (11 repeat runs, both
# campaigns) — so the original 30s budget, and even a first attempt at 45s,
# left too little margin.
_IMAGES_EDITOR_TIMEOUT_MS = 60_000
# How long a "no StubN observed yet, no ContentImage yet" reading must hold
# continuously before `_wait_for_images_editor` trusts it as a genuinely
# empty/already-settled campaign rather than issue #687's ghost render pass
# (see that function's docstring). The ghost pass was observed live lasting
# up to ~14.5s, so this must clear that with margin; a truly empty campaign
# pays this as fixed latency once per edit-page visit.
_IMAGES_GHOST_GRACE_S = 20.0

# Region picker (issue #653 re-recon, 2026-08-02): Yandex replaced the old
# text-combobox-with-suggestions flow with a tree/tag-group widget
# (``data-testid="RegionsTreeEditor"``). Confirmed live: the tag group's
# ``RegionsTreeTagGroup.launcher`` is a <button>, not a text field — clicking
# it opens the tree popup AND reveals a SEPARATE contenteditable filter field
# (``RegionsTreeTagGroup.editor``, only present in the DOM once the popup is
# open) that must be typed into. Typing filters the tree AND auto-expands
# every ancestor/descendant of a match (e.g. typing "Москва" also renders
# "Москва и область" and every district inside Москва) — so selection must
# scope to a checkbox (``RegionsTreeNode.Checkbox.input``, a real HTML
# checkbox with a stable ``id="region-node-<id>"`` but no stable id known
# ahead of time by name) whose LABEL text is an EXACT match, not merely
# contains the typed region name, same fix class as
# _set_promotion_goal's get_by_role(exact=True). A selected region renders
# as a removable tag inside ``RegionsTreeTagGroup.tags-wrapper``.
_REGION_LAUNCHER_TESTID = '[data-testid="RegionsTreeTagGroup.launcher"]'
_REGION_EDITOR_TESTID = '[data-testid="RegionsTreeTagGroup.editor"]'
_REGION_CHECKBOX_TESTID = "RegionsTreeNode.Checkbox.input"
# How long to poll for the tree's checkbox list after typing a filter —
# the tree re-filters asynchronously (debounced), so an immediate count()
# can race it and see zero matches for a region that does exist.
_REGION_FILTER_TIMEOUT_MS = 8_000
# How long to wait for the editor field to appear after clicking the
# launcher (live testing, issue #653: this can occasionally not render on
# the first click under real network conditions).
_REGION_EDITOR_APPEAR_TIMEOUT_MS = 3_000
# How many times to retry the whole open-popup→type→poll sequence per
# region before giving up — live testing found a single attempt is
# occasionally not enough (see docstring). Each retry must be IDEMPOTENT to
# be worth anything: the launcher toggles the popup (so re-clicking it while
# open closes it) and type() appends to a contenteditable (so re-typing
# without clearing yields "МоскваМосква", matching nothing) — _set_region
# therefore only clicks the launcher when the editor is absent, and clears
# the field via _clear_text_field before every type(). Don't "simplify" that
# back into an unconditional click + type: it turns attempts 2..N into
# guaranteed no-ops that only add latency.
_REGION_OPEN_ATTEMPTS = 3
# Each accepted region tag also renders a same-prefixed close button
# (``RegionsTreeTagGroup.tag.{N}.close``, confirmed live) — the
# ``:not([data-testid$=".close"])`` exclusion keeps _read_region_tags from
# reading the close button (empty text) as a phantom extra tag.
_REGION_TAGS_WRAPPER_TESTID = '[data-testid="RegionsTreeTagGroup.tags-wrapper"]'
_REGION_TAG_TESTID_PATTERN = (
    '[data-testid^="RegionsTreeTagGroup.tag."]:not([data-testid$=".close"])'
)

# Weekly budget / "Директ помогает" / "Цель продвижения" (issue #653
# re-recon, 2026-08-02): confirmed live these three still render under
# genuine h1/h2/h3 headings on the create page (unlike headlines/texts/
# region above), so the pre-existing heading-proximity XPaths continue to
# match the correct element — re-confirmed by comparing the XPath match
# against each field's own data-testid
# (``BudgetWithSuggest.PriceTextInput``,
# ``CampaignRecommendationsEditor.AcceptRecommendations.input``,
# ``CampaignTargetSelect.TargetSelect``) via a live DOM read. Left as-is
# (heading-proximity XPath, same convention as update_master's
# _WEEKLY_BUDGET_INPUT_XPATH) rather than switched to data-testid, since
# they were not broken by the markup change that broke headlines/texts/
# region.
_WEEKLY_BUDGET_INPUT_XPATH = (
    "xpath=//*[self::h1 or self::h2 or self::h3][normalize-space(text())="
    "'Недельный бюджет']/following::input[1]"
)


def _xpath_literal(value: str) -> str:
    """Render ``value`` as a safely-quoted XPath 1.0 string literal.

    XPath 1.0 has no string-escaping mechanism — a value containing both
    ``'`` and ``"`` cannot be quoted directly. Region names are not expected
    to contain quotes, but ``concat()``-splitting on ``'`` keeps this
    correct even if one ever does, rather than building a query that could
    break out of the literal.
    """
    if "'" not in value:
        return f"'{value}'"
    parts = value.split("'")
    return "concat(" + ', "\'", '.join(f"'{part}'" for part in parts) + ")"


def _clear_text_field(field: Any) -> bool:
    """Empty a focused contenteditable field via select-all + Backspace.

    ``.fill("")`` does not work on the ``contenteditable`` ``<div
    role="textbox">`` elements this page uses (same constraint that forces
    ``.type()`` over ``.fill()`` everywhere else in this module), and
    ``.type()`` APPENDS — so any retry that re-types into a field must clear
    it first or it accumulates text (``"МоскваМосква"``) that matches
    nothing. ``ControlOrMeta`` keeps this correct on both macOS and Linux,
    but it only exists from Playwright 1.44 — older versions reject it
    server-side with ``Unknown modifier`` (hence the floor in
    ``pyproject.toml``).

    Returns whether the field was actually cleared. Callers that go on to
    ``.type()`` into a PRE-FILLED slot must treat ``False`` as fatal: typing
    after a failed clear splices the caller's value into Yandex's own copy,
    and ``create_master`` clicks Launch before it re-reads anything, so the
    mangled variant would ship on a page with no rollback (issue #655
    review). Callers that merely re-type into a scratch filter field (the
    region popup) can retry instead, since their own poll decides success.
    """
    try:
        field.press("ControlOrMeta+a")
        field.press("Backspace")
    except PlaywrightError:
        return False
    return True


# "Директ помогает" auto-recommendations toggle (issue #724, live
# diagnosis): the underlying ``<input type="checkbox">`` is a classic
# visually-hidden accessible-toggle input (wrapped in a clip-rect-0 div) —
# ``is_visible()`` is False, so Playwright's ``.check()``/``.uncheck()``,
# which both require visibility before clicking, hang until timeout. The
# actually-clickable element is the sibling
# ``[data-testid="CampaignRecommendationsEditor.AcceptRecommendations.label"]``,
# which wraps a visible toggle div
# (``data-testid="CampaignRecommendationsEditor.AcceptRecommendations"``)
# whose ``data-checked`` attribute ("true"/"false") reflects state —
# confirmed live: clicking the label flips both ``data-checked`` and the
# hidden input's own ``is_checked()``. ``_set_directs_helps``/
# ``_read_directs_helps`` therefore click/read the label's toggle div.
_DIRECT_HELPS_TOGGLE_LABEL_SELECTOR = (
    '[data-testid="CampaignRecommendationsEditor.AcceptRecommendations.label"]'
)
_DIRECT_HELPS_TOGGLE_DIV_SELECTOR = (
    '[data-testid="CampaignRecommendationsEditor.AcceptRecommendations"]'
)

# XPath fragment: the "Цель продвижения" dropdown's trigger button. Confirmed
# live via accessibility-tree read: its accessible name is the static label
# "Цель продвижения" (not the current selection) — it is the first <button>
# following the section heading of the same name.
_PROMOTION_GOAL_BUTTON_XPATH = (
    "xpath=//*[self::h1 or self::h2 or self::h3][normalize-space(text())="
    "'Цель продвижения']/following::button[1]"
)

# "Цель продвижения" dropdown option rows, by data-testid (issue #696
# recon, 2026-08-04 re-investigation): Yandex now renders each option's
# accessible name as the label PLUS a description sentence and, for some
# rows, a "Рекомендуем" badge (e.g. "Максимум целевых действийЕсли хотите
# получать больше звонков и сообщений от клиентовРекомендуем") — this broke
# the previous get_by_role("option", name=label, exact=True) match, which
# requires the WHOLE accessible name to equal the bare label. The
# data-testid suffix (PROMOTION_GOAL_INTERNAL_VALUES) is stable and
# unambiguous regardless of the surrounding description text.
_PROMOTION_GOAL_OPTION_TESTID_TEMPLATE = (
    "CampaignTargetSelect.TargetSelect.ListBox.{value}"
)

# --goal-price (issue #696 recon, 2026-08-04, campaigns 713234191/713234204):
# a single ``CampaignTargetSelect.PriceInput`` <input type="text"> exists in
# the "Цель продвижения" block ONLY when promotion_goal is "max-clicks"
# (DIRECT_CLICK) — confirmed live it does NOT exist at all for
# "max-conversions" (INVOLVED_CONVERSION), whose price is instead set
# per-goal in the separate "Целевые действия" table
# (``TargetActions.<id>.PriceInput`` — see ``--target-action-price``,
# issue #707). Even under max-clicks, the field only renders while the
# "Цена перехода" strategy selector is on its default AVG_PRICE value
# ("Средняя за неделю") — it disappears entirely under the OPTIMUM ("Без
# ограничений") strategy, which has no fixed/target price at all. This
# module never touches the strategy selector itself, so --goal-price only
# works against a campaign whose current strategy is (or defaults to)
# AVG_PRICE.
_GOAL_PRICE_INPUT_TESTID = '[data-testid="CampaignTargetSelect.PriceInput"]'

# How long _read_goal_price waits for the field to render before concluding
# it genuinely does not exist for the campaign's current goal (issue #696
# live testing): the "Цель продвижения" section can still be hydrating
# when _wait_for_edit_form returns (that wait only polls the first
# headline slot, near the top of the page) — an immediate is_visible()
# check raced this and read "not there yet" as "field doesn't exist",
# producing a false negative in _verify_saved right after a save that DID
# succeed server-side.
_GOAL_PRICE_WAIT_TIMEOUT_MS = 5_000

# How long _verify_saved's _read_until_matches retries a field reader before
# trusting its value (issue #706 live testing): _wait_for_edit_form only
# polls the first HEADLINE slot, near the top of the page — the weekly-
# budget input, "Директ помогает" checkbox, "Цель продвижения" dropdown, and
# name header all sit elsewhere on the same form and can still be hydrating
# (still showing the PRE-reload value) once that wait returns, the same race
# _GOAL_PRICE_WAIT_TIMEOUT_MS was added for. A one-shot read of any of them
# right after _wait_for_edit_form can misreport a save that DID succeed
# server-side as a mismatch.
_VERIFY_FIELD_READ_TIMEOUT_MS = 5_000

# "Целевые действия" table (issue #707 recon, 2026-08-04, live campaign
# 713234191, ksamatadirect account, promotion goal max-conversions): a
# SEPARATE per-goal price table from ``--goal-price`` above — confirmed live
# it renders ONLY under "max-conversions" (the opposite gating from
# ``_GOAL_PRICE_INPUT_TESTID``, which is max-clicks only). One <tr
# data-testid="TargetActions.OTHER.<goalId>"> per goal the campaign already
# optimizes for; ``<goalId>`` is Yandex Metrika's own numeric goal ID (e.g.
# 159614149), read from the campaign's linked Metrika counter (visible on
# the same page as "gc.<domain> · <counterId> · N целей") — NOT a
# Direct-assigned id. "OTHER" is the only category testid observed live;
# no other category value has ever been seen, so this module hard-codes it
# rather than parsing it out of each row's own testid.
#
# Each row's lone <td data-testid="TableCell"> holds, in DOM order: the
# goal's label as the FIRST `[data-testid="Text"]` child (e.g.
# "Регистрация" — confirmed live goal labels are NOT unique across an
# account's Metrika counter, e.g. "Регистрация JS"/"Регистрация JS
# ретаргет" both exist as distinct goal IDs — so a label can never safely
# identify a row, only the numeric goal ID can), then the
# ``TargetActions.OTHER.<goalId>.PriceInput`` <input type="text">, a second
# `Text` node (the "₽" suffix), and a
# ``TargetActions.OTHER.<goalId>.CloseButton`` (removes the goal — out of
# scope here, this module only ever fills an EXISTING row's price, same
# "no add/remove, only replace" convention as ``_set_repeating_value``).
#
# There is no separate "select this goal for optimization" control — a
# goal's presence AS A ROW in this table (added via
# ``TargetActions.OTHER.MiniGrid.AddButton``'s search popup) is what makes it
# "selected"; filling its ``PriceInput`` is the only action, confirming issue
# #707's open question about whether a distinct selection flag is needed (it
# is not).
#
# Add/remove (issue #717 recon, 2026-08-04, live campaign 713277109
# temporarily unarchived for this — see ``_TARGET_ACTION_UNARCHIVE_NOTE``
# below): clicking ``TargetActions.OTHER.MiniGrid.AddButton`` opens a
# ``[data-testid="AddTargetAction.OTHER"]`` list BELOW the table (not a
# separate modal), containing one ``[role="option"]`` per goal the
# campaign's linked Metrika counter has that is NOT ALREADY a row in the
# table — Yandex filters already-added goals out of this list itself, so
# there is no "already added" error state to reproduce; a goal id absent
# from the list is either not the counter's or already present. Each
# option's own testid is ``AddTargetAction.OTHER.<goalId>`` — the same
# numeric Metrika goal id used everywhere else in this module. A text search
# input (``SelectSearchTargetInput``, placeholder "Поиск") also lives in
# this list but is not needed here: this module identifies a goal purely by
# id (see the "Goal ids ... never by its label" note above), so clicking the
# id-scoped option directly is both simpler and immune to a goal's display
# name changing.
#
# Confirmed live: clicking an option adds a new row with an EMPTY price
# input — not a page default as issue #717 speculated. Saving with that
# field still empty is rejected client-side (the row's
# ``data-form-error`` flips to ``"true"``, a red icon appears, and the
# terminal save click does not persist) — so ``_add_target_action`` requires
# a price, unlike ``_set_target_action_price`` which only ever touches a
# price that's already there. The list stays open after a click (no
# auto-close) — irrelevant here since this module never needs to add more
# than one goal per popup open.
#
# Removal is simpler: ``TargetActions.OTHER.<goalId>.CloseButton`` removes
# the row from the DOM immediately on click, no confirmation dialog.
_TARGET_ACTIONS_SECTION_TESTID = '[data-testid="TargetActionsSection"]'
_TARGET_ACTIONS_CATEGORY = "OTHER"
_TARGET_ACTION_ROW_TESTID_TEMPLATE = "TargetActions.{category}.{goal_id}"
_TARGET_ACTION_PRICE_TESTID_TEMPLATE = "TargetActions.{category}.{goal_id}.PriceInput"
_TARGET_ACTION_CLOSE_TESTID_TEMPLATE = "TargetActions.{category}.{goal_id}.CloseButton"
_TARGET_ACTION_ADD_BUTTON_TESTID_TEMPLATE = (
    "TargetActions.{category}.MiniGrid.AddButton"
)
_TARGET_ACTION_ADD_OPTION_TESTID_TEMPLATE = "AddTargetAction.{category}.{goal_id}"

# How many times ``_click_and_wait_for_popup``-style retries are attempted
# for the add-popup's option to become visible/clickable — same hydration
# race as every other menu/modal trigger in this module (issues #723/#725),
# confirmed live here too: the first click after the section scrolls into
# view frequently lands before the popup's React handler is ready.
_TARGET_ACTION_ADD_OPTION_MAX_ATTEMPTS = 5

# How long to wait for the "Целевые действия" section to render before
# concluding a requested goal row genuinely isn't there — same hydration
# race as ``_GOAL_PRICE_WAIT_TIMEOUT_MS`` (this section sits even lower on
# the edit page, below "Цель продвижения").
_TARGET_ACTION_WAIT_TIMEOUT_MS = 5_000

# Issue #750 (Codex round-3 finding on #749): the section can go through a
# genuine, non-throwing EMPTY interval mid-hydration — live recon against
# campaign 713277109 confirmed the row-testid locator's own ``.count()``
# dips to 0 (and ``TargetActionsSection`` itself briefly leaves the DOM,
# ``.count() == 0``) for ~1-1.5s starting around 4-4.5s after
# ``_wait_for_edit_form`` returns, before the real row set (re)appears
# around 5-5.5s. No section-scoped loading/spinner ``data-testid`` exists
# to poll instead (confirmed live: the only "loading"-flavoured markup
# nearby is an unrelated, always-present ``TextInput_disabled`` addon
# class on the add-action input, not a completeness signal). A single read
# landing in that dip is not an exception (``_read_target_actions_or_none``
# returns a genuinely well-formed ``[]``, not ``None``) — it's a truthful
# snapshot of a table that has not finished loading, which is exactly the
# gap ``_wait_for_target_actions_settled`` closes: require
# ``_TARGET_ACTION_STABLE_STREAK`` consecutive equal row-count reads,
# ``_TARGET_ACTION_STABLE_TICK_MS`` apart, before trusting any read of this
# table — mirrors ``_wait_for_audience_section``'s tag-count settling
# (``_AUDIENCE_TAG_STABLE_STREAK``), same class of race, same fix shape.
_TARGET_ACTION_STABLE_STREAK = 5
_TARGET_ACTION_STABLE_TICK_MS = 300
_TARGET_ACTION_SETTLE_TIMEOUT_MS = 10_000

# "Аудитория" section (issue #681, Этап C, live recon 2026-08-04 against
# campaign 713277109, ksamatadirect account — see module docstring for the
# archive/unarchive detour needed to reach this campaign's edit page).
#
# "Пол и возраст" ("AgeAndGenderEditorLegacy", note the "Legacy" suffix —
# Yandex's own naming, not this module's) is three independent single-select
# dropdowns, each with a stable data-testid, confirmed live via each popup's
# own option rows (2026-08-04, campaign 713277109):
#
# * gender: ``GenderSelect.ListBox.{All,Male,Female}`` (trigger shows "Любой
#   пол"/"Мужчины"/"Женщины").
# * age-from: ``AgeFromSelect.ListBox.Age{0,18,25,35,45,55}``.
# * age-to: ``AgeToSelect.ListBox.Age{18,25,35,45,55}`` PLUS
#   ``AgeToSelect.ListBox.AgeUnlimited`` (no ``Age0`` — "to 0" is not a valid
#   upper bound; the trigger renders "55+" for the unlimited case, but the
#   option testid itself has no numeric suffix at all).
_GENDER_SELECT_TESTID = '[data-testid="AgeAndGenderEditorLegacy.GenderSelect"]'
_AGE_FROM_SELECT_TESTID = '[data-testid="AgeAndGenderEditorLegacy.AgeFromSelect"]'
_AGE_TO_SELECT_TESTID = '[data-testid="AgeAndGenderEditorLegacy.AgeToSelect"]'

_GENDER_OPTION_TESTID_TEMPLATE = (
    '[data-testid="AgeAndGenderEditorLegacy.GenderSelect.ListBox.{value}"]'
)
_AGE_FROM_OPTION_TESTID_TEMPLATE = (
    '[data-testid="AgeAndGenderEditorLegacy.AgeFromSelect.ListBox.Age{value}"]'
)
# Confirmed live: every FINITE age-to option's testid also carries the
# "Age" prefix (``ListBox.Age45``, not ``ListBox.45``) — same shape as
# AgeFromSelect's own options — but the unlimited option does NOT
# (``ListBox.AgeUnlimited``, i.e. "Age" is part of the literal suffix
# "Unlimited" fuses onto, not a separate prefix applied to a numeric
# value). ``_set_age_bound`` accounts for this by passing "Unlimited" as
# ``option_value`` for the unlimited case (no separate "Age" needed) and
# a bare number otherwise (this template supplies the "Age" prefix).
_AGE_TO_OPTION_TESTID_TEMPLATE = (
    '[data-testid="AgeAndGenderEditorLegacy.AgeToSelect.ListBox.Age{value}"]'
)

# CLI-facing keys -> the trigger button's own displayed label, used both to
# build the option locator and to verify the post-click selection (mirrors
# PROMOTION_GOAL_CHOICES/_trigger_shows_selection's identical convention).
GENDER_CHOICES = {
    "any": "Любой пол",
    "male": "Мужчины",
    "female": "Женщины",
}
_GENDER_INTERNAL_VALUES = {"any": "All", "male": "Male", "female": "Female"}

AGE_FROM_CHOICES = (0, 18, 25, 35, 45, 55)
AGE_TO_CHOICES = (18, 25, 35, 45, 55, None)  # None = AgeUnlimited ("55+")

# "Интересы и поисковые запросы" (CustomAudienceAndSearchTermsEditor):
# a single tag list mixing TWO distinct kinds of entries, confirmed live —
# a search-term tag ("keyword") and an interest-category tag. They render
# with different leading icons (magnifying glass vs. a cloud-shaped "audience
# segment" icon in the actual page; not distinguished in this module's own
# reads) and, critically, have DIFFERENT data-testid shapes for their
# CustomAudienceTagIcon child:
#
# * a keyword tag's testid is ``CustomAudienceTagIcon.keyword_<exact text>``
#   — deterministic and reproducible from the typed text alone.
# * an interest tag's testid is ``CustomAudienceTagIcon.<numeric Yandex id>``
#   — that id is assigned server-side per interest CATEGORY and cannot be
#   derived from the category's display text (e.g. "Спорт" confirmed live at
#   id 2499680371 on this account, but nothing about that id is guessable
#   ahead of time).
#
# Both kinds are added through the SAME free-text input, which opens an
# autocomplete popup (``CustomAudienceAndSearchTermsEditor.TagGroup.editor.
# popup``/``...editor.listBox``) mixing keyword suggestions (each rendered as
# an accessible-tree ``option`` whose testid follows the keyword_<text>
# pattern above) and interest-category suggestions (each an ``option`` too,
# but with a numeric-id testid) — confirmed live via
# ``mcp__claude-in-chrome__find`` locating the "Спорт" suggestion as
# ``option "Спорт" (interest_suggestion)``. Because the interest testid is
# unpredictable, THIS MODULE MATCHES BOTH KINDS BY THE SUGGESTION ROW'S
# VISIBLE ACCESSIBLE NAME (Playwright ``get_by_role("option", name=...,
# exact=True)``), never by constructing a testid — the keyword_<text> pattern
# above is documented for context (it's what's visible in the DOM) but is
# NOT used to build a locator, so both tag kinds share one code path.
#
# Tags themselves are both READ and REMOVED by POSITION, not by re-deriving
# either testid shape above — each ``...TagGroup.tag.{index}`` div's own
# ``inner_text()`` is the tag's exact display text (confirmed live: tag 0
# read back "автобус"), and ``...TagGroup.tag.{index}.close`` removes it —
# mirrors ``_HEADLINES_TESTID_TEMPLATE``'s existing index-based convention,
# and sidesteps the interest/keyword testid split entirely for both reading
# and removal.
# The tags-wrapper container is always in the DOM, and clicking it MOUNTS a
# contenteditable div input (confirmed live, testid ``...TagGroup.editor.
# Textinput``) that does not exist in the DOM at all before that first click
# — so adding a tag is a two-step locate: click the wrapper, THEN locate the
# now-mounted text input. The input itself is the same contenteditable shape
# as the headline/text slots ``_clear_text_field``/``_add_repeating_values``
# already handle — not a plain ``<input>``/``<textarea>``, so ``.fill()``
# does not work on it.
_AUDIENCE_TAG_WRAPPER_TESTID = (
    '[data-testid="CustomAudienceAndSearchTermsEditor.TagGroup.tags-wrapper"]'
)
_AUDIENCE_TAG_INPUT_TESTID = (
    '[data-testid="CustomAudienceAndSearchTermsEditor.TagGroup.editor.Textinput"]'
)
_AUDIENCE_TAG_LISTBOX_TESTID = (
    '[data-testid="CustomAudienceAndSearchTermsEditor.TagGroup.editor.listBox"]'
)
_AUDIENCE_TAG_TESTID_TEMPLATE = (
    "CustomAudienceAndSearchTermsEditor.TagGroup.tag.{index}"
)
_AUDIENCE_TAG_CLOSE_TESTID_TEMPLATE = (
    "CustomAudienceAndSearchTermsEditor.TagGroup.tag.{index}.close"
)
_AUDIENCE_TAG_COUNT_LIMIT_KEYWORDS = 200
_AUDIENCE_TAG_COUNT_LIMIT_INTERESTS = 30

# How long the autocomplete popup gets to render suggestions for a freshly
# typed query before concluding the requested tag genuinely has no matching
# suggestion — mirrors ``_GOAL_PRICE_WAIT_TIMEOUT_MS``'s same class of
# "give the SPA time to hydrate before treating absence as final" guard.
_AUDIENCE_TAG_SUGGEST_TIMEOUT_MS = 5_000

# How long _wait_for_audience_section polls the "Пол" trigger for a
# non-empty label before giving up — confirmed live (issue #681) this
# section needs MEASURABLY longer than the rest of the edit page's fields:
# a read at ~1.5s after _wait_for_edit_form returned saw a stale/default
# value, the same campaign re-read at ~4s was correct. 8s gives headroom
# above that observed 4s settle time.
_AUDIENCE_SECTION_READY_TIMEOUT_MS = 8_000

# How many CONSECUTIVE equal tag-count reads _wait_for_audience_section
# requires (each _AUDIENCE_TAG_STABLE_WINDOW_MS/streak tick apart) before
# trusting the audience-tag list has actually finished loading, and how
# long it polls overall — cycle-review (PR #751) finding: a single pair of
# equal reads 250ms apart can both land on the same PREMATURE value (e.g.
# 0 read twice before the real 112-tag payload starts arriving at all),
# which is "stable" by a 2-sample test but still wrong. Live recon (this
# module's own docstring above) put the actual settle point somewhere
# between 1.5s and 4s after the gender trigger already had data; 5
# consecutive equal samples spaced 500ms apart span 2.5s of continued
# agreement on top of whatever tick first produced that value, which does
# not by itself guarantee correctness but meaningfully raises the bar
# above "two ticks of an SPA that hasn't started rendering yet".
_AUDIENCE_TAG_STABLE_STREAK = 5
_AUDIENCE_TAG_STABLE_WINDOW_MS = 10_000

# "Устройства пользователей" (DeviceEditor): a multi-select popup with
# exactly three checkboxes, confirmed live all pre-checked by default
# ("Любые" = all three checked, not a fourth distinct value) — mobile,
# desktop, tablet, in that DOM order.
_DEVICE_SELECT_TESTID = '[data-testid="DeviceEditor.Select"]'
_DEVICE_OPTION_TESTID_TEMPLATE = '[data-testid="DeviceEditor.Select.ListBox.{value}"]'
DEVICE_OPTION_VALUES = ("mobile", "desktop", "tablet")

_EDIT_NAME_BUTTON_SELECTOR = '[data-testid="CampaignHeader.EditName.Button"]'
_NAME_HEADER_SELECTOR = '[data-testid="CampaignHeader.TitleName"]'
_NAME_MODAL_INPUT_SELECTOR = '[data-testid="ModalEditTitle.CampaignName"]'
_NAME_MODAL_ACCEPT_SELECTOR = '[data-testid="AcceptButton"]'

# "Ссылка на продвигаемую страницу" field on the EDIT page (issue #757,
# live-confirmed 2026-08-04 against campaign 713277109) — a DIFFERENT
# component from the create page's ``CampaignFormUrl`` (module docstring's
# "Two distinct pages" note): the edit page renders it under a
# ``CampaignLinkEditorLite`` namespace instead, but the field itself is the
# same kind of widget — a ``contenteditable`` ``<div role="textbox">`` that
# must be clicked, cleared, and re-typed exactly like
# ``_CREATE_URL_INPUT_TESTID`` (see ``_type_landing_url``'s docstring for why
# a retry-with-verify loop is required). There is no separate "Далее"/
# suggestions-popup step here — the field lives directly on the single
# whole-form edit page and is committed by the same terminal
# ``_click_save`` as every other field this module writes.
#
# Confirmed live: this field (and its own Clear button) is READ-ONLY
# whenever the campaign's current status is ARCHIVED — the Clear button's
# ``disabled`` attribute is ``true`` and the field's own ``contentEditable``
# stays ``"false"`` even after a click, exactly the "click does nothing"
# symptom of a disabled contenteditable widget. The field becomes editable
# again as soon as the campaign leaves ARCHIVED (confirmed live via
# ``masters resume``/the overview page's "Разархивировать" flow — see issue
# #758 for the gap in ``resume_master`` this surfaced). ``_set_landing_url``
# raises a clear, named error for this rather than letting the click/type
# attempt fail with an opaque markup-changed message.
_EDIT_URL_INPUT_TESTID = '[data-testid="CampaignLinkEditorLite.LinkInput.Textinput"]'
_EDIT_URL_CLEAR_BUTTON_TESTID = (
    '[data-testid="CampaignLinkEditorLite.LinkInput.Textinput.Clear"]'
)
_EDIT_UTM_INPUT_TESTID = '[data-testid="CampaignLinkEditorLite.UTMInput"]'
_EDIT_UTM_SPOILER_BUTTON_TESTID = (
    '[data-testid="CampaignLinkEditorLite.Spoiler.Button"]'
)

# The separate "UTM-метки и параметры URL" field under "Дополнительные
# параметры" (``CampaignLinkEditorLite.UTMInput``) is the intended, dedicated
# place to hold a campaign's UTM query string (issue #761) — a genuinely
# independent field ``_set_landing_url``/``--landing-url`` never touches.
# It is lazily mounted under a collapsed spoiler
# (``CampaignLinkEditorLite.Spoiler.Button``, ``_expand_utm_spoiler``) —
# ``_set_tracking_params``/``--tracking-params`` is the dedicated setter,
# expanding the spoiler before writing. Pass an empty string to clear it.

_SAVE_BUTTON_TEXT = "Сохранить кампанию"
_LAUNCH_BUTTON_TEXT = "Запустить кампанию"
_SAVE_DRAFT_BUTTON_TEXT = "Сохранить как черновик"

# DRAFT edit page's terminal buttons (issue #668, live-confirmed 2026-08-02
# against campaign 713231614 — see the module docstring's "DRAFT support"
# note). A DRAFT edit page has NO "Сохранить кампанию" button at all — only
# these two, under a shared testid prefix. Matched by data-testid rather than
# accessible-name text (unlike ``_click_save``/``_click_terminal_button``)
# because ``CampaignFormControls.save.button``'s TEXT is "Запустить
# кампанию" here — the same testid suffix (``save.button``) that means
# "Сохранить кампанию" on a non-DRAFT page means "publish this draft" on a
# DRAFT one, so the label alone can't disambiguate; the testid can.
_DRAFT_SAVE_DRAFT_BUTTON_TESTID = (
    '[data-testid="CampaignFormControls.saveDraft.button"]'
)
_DRAFT_LAUNCH_BUTTON_TESTID = '[data-testid="CampaignFormControls.save.button"]'

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

    Uses ``wait_until="commit"``, not ``"domcontentloaded"`` (#682): live
    diagnosis in #671 found the grid is a virtualized SPA whose
    ``document.readyState`` never advances past ``"interactive"``, so
    ``domcontentloaded`` itself was timing out after 30s waiting for an
    event that never fires. ``commit`` only waits for the network response
    headers and the start of the document body — earlier than
    ``domcontentloaded`` — which is safe here because the actual wait for
    grid data is ``expect_response`` above, not the ``goto`` call. The
    captcha/login-page checks below still see valid HTML at ``commit``
    time: both are server-rendered gate pages (not part of the grid SPA),
    so their marker text is present in the initial document body Yandex
    sends, before any client-side JS runs.
    """
    try:
        with page.expect_response(
            _is_grid_campaigns_request, timeout=_GRID_CAPTURE_TIMEOUT_MS
        ) as response_info:
            # commit, not domcontentloaded/networkidle: see docstring. No
            # ulogin here (see module docstring): passing our own login as
            # the managed-client param produces "Доступ ограничен" + HTTP
            # 401.
            page.goto(GRID_URL, wait_until="commit")
            assert_not_captcha(page.content())
            assert_authenticated(page.content())
        response = response_info.value
    except BrowserSessionError:
        # assert_not_captcha/assert_authenticated raise BrowserCaptchaError/
        # BrowserAuthError (both BrowserSessionError subclasses) -- these
        # must propagate as-is, not be relabelled as the generic timeout
        # error below. Without this PlaywrightError falls back to bare
        # Exception when the playwright package isn't installed (see the
        # import fallback above), which would otherwise swallow them too.
        raise
    except PlaywrightError as exc:
        # Playwright's EventContextManager.__exit__ resolves
        # response_info.value itself when the `with` block exits without
        # raising — so a expect_response timeout surfaces as the `with`
        # block's own exit, not as an exception from reading
        # response_info.value afterwards (issue #694). The whole block
        # (goto/assert_* included) must be inside this try, or the timeout
        # escapes uncaught.
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


def _widen_filter_status_for_archived(request: Dict[str, Any]) -> None:
    """Add ``ARCHIVED`` to the captured request's ``filterStatusIn``, in place.

    Issue #730, live-confirmed 2026-08-04: the grid UI's own default view
    (whatever ``GRID_URL`` renders without any query string) sends a
    ``campaignInput.filter.filterStatusIn`` list of exactly ``["ACTIVE",
    "DRAFT", "MODERATION", "MODERATION_DENIED", "RUN_WARN", "STOPPED",
    "TEMPORARILY_PAUSED"]`` — no ``"ARCHIVED"``. ``_capture_grid_campaigns_
    request`` replays that captured body verbatim, so a real archived
    campaign is excluded server-side, before ``fetch_masters_list``'s own
    ``STATUS_FILTERS`` predicate ever sees it (confirmed live against
    campaign 713277109: absent from ``totalCount``/``rowset`` entirely, not
    merely filtered out downstream). The grid's URL-level ``status-filter``
    query parameter is already known to be ignored server-side (see module
    docstring) — mutating this captured GraphQL variable is what actually
    works.
    """
    filter_obj = (
        request["body"]
        .setdefault("variables", {})
        .setdefault("campaignInput", {})
        .setdefault("filter", {})
    )
    status_in = filter_obj.get("filterStatusIn")
    if isinstance(status_in, list) and _ARCHIVED_PRIMARY_STATUS not in status_in:
        status_in.append(_ARCHIVED_PRIMARY_STATUS)


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

    For ``status in {"archived", "all"}`` the captured request's
    ``filterStatusIn`` is widened first (see
    ``_widen_filter_status_for_archived``) — otherwise the grid's own default
    filter excludes archived rows server-side and ``STATUS_FILTERS`` below
    would never even see them (issue #730).
    """
    status_predicate = STATUS_FILTERS.get(status)
    if status_predicate is None:
        raise ValueError(
            f"Unknown status filter {status!r}; expected one of "
            f"{sorted(STATUS_FILTERS)}."
        )

    request = _capture_grid_campaigns_request(page)
    if status in _ARCHIVE_INCLUDING_STATUSES:
        _widen_filter_status_for_archived(request)

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


def _goto_overview_page(page: "Page", campaign_id: int) -> None:
    """Navigate to a campaign's wizard overview page and block until it has
    actually rendered (issue #683).

    Every entry point that reads/mutates the overview page previously used
    ``page.goto(url, wait_until="domcontentloaded")`` and immediately trusted
    the page to be ready — but the overview page is a client-rendered SPA,
    same as the edit page ``_wait_for_images_editor`` guards against (#670):
    ``domcontentloaded`` fires while the header/menu/stats are all still
    absent from the DOM. Live-confirmed 2026-08-03 against campaign
    72349978: ``fetch_master`` intermittently failed to read the campaign
    name (``h1, [role=heading]`` — a selector that, separately, never
    matches this page's real ``<h2 data-testid="CampaignHeader.Title">``
    element at all) while status/landing-URL/stats all read back fine, a
    classic race between the read and the still-in-flight render.

    ``wait_until="commit"`` (fires as soon as the navigation's response
    headers arrive, before ANY DOM work) replaces ``domcontentloaded`` here
    so this function's own poll loop is what actually waits for content,
    rather than layering an unreliable implicit wait under an also-unreliable
    explicit one. It polls for ``_OVERVIEW_TITLE_SELECTOR`` — confirmed live
    to render on both a DRAFT campaign's overview page (which has no "⋮"
    menu at all, see ``_MENU_TRIGGER_SELECTOR`` and issue #660) and every
    other status, making it the earliest common marker every caller here can
    rely on regardless of campaign status.

    ``assert_not_captcha``/``assert_authenticated`` run once immediately
    after navigation AND on every poll tick, so a captcha gate or an
    expired session is reported via its own specific error right away,
    instead of only surfacing after burning the full
    ``_OVERVIEW_LOAD_TIMEOUT_MS`` waiting for a title that a login/captcha
    page will never render. The extra upfront check does not change
    behavior on the happy path -- it only matters when the gate is already
    present at commit time, which is exactly the case that must not depend
    on ``_poll_until``'s first tick actually running promptly.

    The captcha/auth check happens OUTSIDE ``_poll_until``'s predicate (via
    ``_terminal_state``, which returns a marker instead of raising), same
    pattern as ``_wait_for_edit_form``/
    ``_edit_form_terminal_state`` (issue #689): ``_poll_until`` suppresses
    ``PlaywrightError``, which is aliased to the broad ``Exception`` when
    Playwright isn't installed (the offline-unit-test import fallback
    above) — in that environment a raise from inside the predicate would
    be silently swallowed as "not yet" instead of propagating, and this
    function would misreport a real captcha/auth failure as its own
    generic render-timeout (cycle-review #697 finding).
    """
    url = WIZARD_OVERVIEW_URL.format(campaign_id=campaign_id)
    page.goto(url, wait_until="commit")

    initial_html = page.content()
    assert_not_captcha(initial_html)
    assert_authenticated(initial_html)

    def _terminal_state() -> "Optional[str]":
        html = page.content()
        try:
            assert_not_captcha(html)
            assert_authenticated(html)
        except BrowserCaptchaError:
            return "captcha"
        except BrowserAuthError:
            return "auth"
        if page.locator(_OVERVIEW_TITLE_SELECTOR).first.count() > 0:
            return "ready"
        return None

    state = _poll_until_terminal(page, _terminal_state, _OVERVIEW_LOAD_TIMEOUT_MS)
    if state == "ready":
        return
    if state == "captcha":
        assert_not_captcha(page.content())  # re-raises BrowserCaptchaError
    if state == "auth":
        assert_authenticated(page.content())  # re-raises BrowserAuthError

    raise BrowserSessionError(
        f"The wizard overview page for campaign {campaign_id} did not "
        f"render within {_OVERVIEW_LOAD_TIMEOUT_MS / 1000:.0f}s (no "
        f"{_OVERVIEW_TITLE_SELECTOR!r} appeared) — Yandex may have changed "
        "the page's markup, or the page may still be loading. Re-run with "
        "--headful to inspect the page."
    )


def fetch_master(page: "Page", campaign_id: int) -> Dict[str, Any]:
    """Fetch overview details for one Мастер кампаний by navigating its wizard page.

    Best-effort: a section this parser doesn't recognise is omitted from the
    result (with a warning), rather than failing the whole command — Yandex's
    internal markup has no stability guarantee (see module docstring).

    No ``ulogin`` on the URL (see module docstring) — confirmed live that
    Yandex itself redirects to the correct ``?ulogin=<chief login>``.

    A DRAFT campaign renders a different page at this same URL (issue #660,
    see module docstring's "DRAFT overview page" note) — no status text, no
    stat tiles, the header uses different testids. ``_fetch_draft_master``
    handles that case; every other status keeps using the stats-dashboard
    extractors below.
    """
    _goto_overview_page(page, campaign_id)

    if _is_draft_overview_page(page):
        return _fetch_draft_master(page, campaign_id)

    result: Dict[str, Any] = {"CampaignId": campaign_id}

    _extract_title(page, result)
    _extract_status(page, result)
    _extract_landing_url(page, result)
    _extract_stat_tiles(page, result)

    return result


def _is_draft_overview_page(page: "Page") -> bool:
    """True if the overview page currently open is a DRAFT campaign's.

    Detected by ``CampaignHeader.Status`` reading "Черновик" — the same
    testid the non-DRAFT dashboard doesn't have at all (its status instead
    lives in plain body text, see ``_read_status_text``), so this check and
    the DRAFT-specific extractors it gates can never disagree about what
    "DRAFT" means (mirrors ``_is_draft_edit_page``'s own rationale).

    ``goto(..., wait_until="domcontentloaded")`` returns before the SPA has
    necessarily rendered either shape (the same race issue #685 hit for the
    create page's step 1 field — see ``_wait_for_create_step1``), so this
    polls, up to ``_DRAFT_OVERVIEW_DETECT_TIMEOUT_MS``, until EITHER
    ``CampaignHeader.Status`` reads its final text (DRAFT) OR one of the
    non-DRAFT dashboard's own status-text markers (``_read_status_text``'s
    "Кампания остановлена"/"активна"/"включена") has appeared, before
    deciding. Checking the status node's mere *presence* would not be
    enough — a framework can mount an element before filling in its text,
    so this reads the node's actual (trimmed) text on every poll tick,
    not just whether it exists yet.
    """

    def _read_draft_status_text() -> str:
        try:
            return (
                page.locator(_CAMPAIGN_HEADER_STATUS_SELECTOR)
                .first.inner_text()
                .strip()
            )
        except PlaywrightError:
            return ""

    def _either_rendered() -> bool:
        return bool(_read_draft_status_text()) or _read_status_text(page) is not None

    _poll_until(page, _either_rendered, _DRAFT_OVERVIEW_DETECT_TIMEOUT_MS)

    return _read_draft_status_text() == _DRAFT_STATUS_TEXT


def _fetch_draft_master(page: "Page", campaign_id: int) -> Dict[str, Any]:
    """Read name/status/weekly budget from a DRAFT campaign's overview page.

    No stat tiles, no landing-URL link with the confirmed ``utm_source=``
    marker the non-DRAFT extractor keys off (the form's landing-URL field is
    a plain input, not a rendered link) — DRAFT results simply omit
    ``LandingUrl``/``Stats`` rather than guessing at a different selector.
    """
    result: Dict[str, Any] = {"CampaignId": campaign_id, "Status": "DRAFT"}

    try:
        result["Name"] = (
            page.locator(_CAMPAIGN_HEADER_TITLE_NAME_SELECTOR)
            .first.inner_text()
            .strip()
        )
    except PlaywrightError:
        print_warning(f"Could not read campaign name for {campaign_id}.")

    try:
        result["WeeklyBudget"] = (
            page.locator(_BUDGET_INPUT_SELECTOR).first.input_value().strip()
        )
    except PlaywrightError:
        print_warning(f"Could not read weekly budget for {campaign_id}.")

    return result


def _extract_title(page: "Page", result: Dict[str, Any]) -> None:
    # Confirmed live 2026-08-03 (issue #683 investigation, campaign
    # 72349978): the overview page's real title element is
    # `<h2 data-testid="CampaignHeader.Title">` — no `role` attribute, so
    # the previous `h1, [role=heading]` CSS selector never matched it at
    # all. _goto_overview_page already waits for this exact selector
    # (_OVERVIEW_TITLE_SELECTOR) before this function ever runs.
    heading = page.locator(_OVERVIEW_TITLE_SELECTOR).first
    try:
        result["Name"] = heading.inner_text().strip()
    except PlaywrightError:
        print_warning(f"Could not read campaign name for {result['CampaignId']}.")


def _extract_status(page: "Page", result: Dict[str, Any]) -> None:
    status = _read_status_text(page)
    if status is not None:
        result["Status"] = status
    else:
        print_warning(
            f"Could not determine status for campaign {result['CampaignId']} "
            "(unrecognised status text)."
        )


def _extract_landing_url(page: "Page", result: Dict[str, Any]) -> None:
    # The landing-page link's visible text is the bare domain, but its href
    # carries the full URL, including any UTM tail. See
    # _OVERVIEW_LANDING_LINK_SELECTOR above for why this selector is required.
    link = page.locator(_OVERVIEW_LANDING_LINK_SELECTOR).first
    try:
        href = link.get_attribute("href")
        if href:
            result["LandingUrl"] = href
    except PlaywrightError:
        print_warning(
            f"Could not read landing URL for campaign {result['CampaignId']}."
        )


def _extract_stat_tiles(page: "Page", result: Dict[str, Any]) -> None:
    # Confirmed live 2026-08-04 (issue #708, 12 runs across 9 distinct ACTIVE
    # campaigns): the stat tiles carry a stable ``data-testid`` of
    # ``ChartSummary.<key>`` (see _STAT_TILE_TESTID_KEYS) and render
    # atomically — the first poll tick that observes ANY ChartSummary.* node
    # always already has all five. There is therefore a real settled marker
    # here (unlike the previous text-based button scan this replaced, which
    # needed a consecutive-stable-tick heuristic to guess when rendering had
    # finished — see #683/#697 history in git blame): wait for the marker's
    # first appearance, then read the fixed testid set directly, no scanning
    # every button on the page and no label/whitespace matching required.
    _poll_until(
        page,
        lambda: page.locator(f'[data-testid^="{_STAT_TILE_TESTID_PREFIX}"]').count()
        > 0,
        _STAT_TILES_TIMEOUT_MS,
    )

    stats: Dict[str, str] = {}
    try:
        tiles = page.locator(f'[data-testid^="{_STAT_TILE_TESTID_PREFIX}"]')
        count = tiles.count()
        for i in range(count):
            testid = tiles.nth(i).get_attribute("data-testid") or ""
            suffix = testid[len(_STAT_TILE_TESTID_PREFIX) :]
            key = _STAT_TILE_TESTID_KEYS.get(suffix)
            if not key:
                continue
            value = tiles.nth(i).inner_text().strip()
            if value:
                stats[key] = value
    except PlaywrightError:
        pass

    if stats:
        result["Stats"] = stats
    else:
        print_warning(
            f"Could not read overview stat tiles for campaign {result['CampaignId']}."
        )


def _log_timing(what: str, started: float, outcome: object) -> None:
    """TEMPORARY (issue #764 follow-up): print how long a status wait took.

    Silent unless ``DIRECT_MASTERS_DEBUG_TIMING`` is set to a non-empty value,
    so ordinary runs are unaffected. Deliberately a scaffold, not a feature:
    no CLI flag, no logger config, no plumbing through call signatures — the
    env var is read here and nowhere else, so removing this function plus its
    three call sites removes the whole thing.

    It exists because two of the three waits in this module have never been
    measured (see ``_STATUS_HYDRATION_TIMEOUT_MS``): the constants were picked
    from a measurement of a *different* quantity. Rather than guess again,
    collect real numbers from real runs, then set the constants from them and
    delete this.
    """
    if not os.environ.get("DIRECT_MASTERS_DEBUG_TIMING"):
        return
    elapsed = _clock.now() - started
    print(f"[masters timing] {what}: {elapsed:.2f}s -> {outcome!r}", file=sys.stderr)


def _read_status_text(page: "Page") -> Optional[str]:
    """Return ``"SUSPENDED"``/``"ACTIVE"``/``"MODERATION"``/``"ARCHIVED"``/
    ``None`` from the current page body.

    Shared by ``_extract_status`` (``masters get``) and by
    ``suspend_master``/``resume_master``/``launch_master``, which call this
    directly both before and after clicking to verify the action actually
    changed the status rather than trusting the click alone.

    ``"Кампания на\xa0модерации"`` (issue #704, live-confirmed 2026-08-04
    against campaign 713271855's overview page right after a real launch) is
    read from this page rather than the campaigns grid: the grid's own
    ``primaryStatus`` was observed to lag the actual DRAFT->MODERATION
    transition by 45+ seconds in that same recon, while the overview page
    already showed the new status immediately after the redirect. The space
    between "на" and "модерации" is a non-breaking space (U+00A0), not a
    regular ASCII space — ``inner_text()`` returns it verbatim, and a naive
    ASCII-space literal here silently never matches (this cost a full
    debugging pass live: the click and the actual status change both
    succeeded every time, only this string comparison was wrong).

    ``"Кампания в\xa0архиве"`` (issue #730, live-confirmed 2026-08-04 against
    campaign 713277109's overview page, a real archived campaign) fills the
    gap the module docstring's ``archive_master`` note flagged: no archived
    overview fixture had been captured before, so this marker was simply
    missing and ``masters get``/``masters list --status archived`` on an
    archived campaign either warned "unrecognised status text" or the row
    was silently excluded by a status predicate that could never match. Same
    non-breaking-space pitfall as "на\xa0модерации" — the space between "в"
    and "архиве" is U+00A0, not ASCII.
    """
    try:
        body_text = page.inner_text("body")
    except PlaywrightError:
        return None
    if "Кампания остановлена" in body_text:
        return "SUSPENDED"
    if "Кампания активна" in body_text or "Кампания включена" in body_text:
        return "ACTIVE"
    if "Кампания на\xa0модерации" in body_text:
        return "MODERATION"
    if "Кампания в\xa0архиве" in body_text:
        return "ARCHIVED"
    return None


def _is_button_disabled(handle: Any) -> bool:
    """Return whether ``handle`` is disabled — via the ``disabled`` DOM
    property, the ``disabled`` HTML attribute, or ``aria-disabled`` (issue
    #728: Yandex renders "Остановить кампанию" as disabled, not hidden,
    while part of the campaign's creatives are still in moderation/rejected
    — a plain visibility check does not catch this, and the click then
    physically lands on a no-op element).
    """
    with contextlib.suppress(PlaywrightError, AttributeError):
        if handle.is_disabled():
            return True
    with contextlib.suppress(PlaywrightError):
        if handle.get_attribute("disabled") is not None:
            return True
    with contextlib.suppress(PlaywrightError):
        if (handle.get_attribute("aria-disabled") or "").lower() == "true":
            return True
    return False


def _describe_page_buttons(page: "Page") -> str:
    """Return a short human-readable inventory of the overview page's own
    action buttons, for inclusion in a "could not find the button" error.

    Issue #766 asked for exactly this: the previous error named only the
    candidate labels it had searched for, so a reader could not tell whether
    Yandex had renamed the button, whether the page had rendered a different
    status than expected, or whether the page had not finished loading at
    all. Listing what IS on the page turns all three into a one-glance
    diagnosis without a ``--headful`` re-run.

    Deliberately scoped to ``CampaignHeader.ActionButton*`` plus the header's
    own status text rather than every button on the page — the sidebar alone
    contributes a dozen irrelevant ones (Обзор/Кампании/Статистика/…), which
    would bury the signal.
    """
    parts = []
    with contextlib.suppress(PlaywrightError):
        buttons = page.locator('[data-testid^="CampaignHeader.ActionButton"]')
        found = []
        for i in range(buttons.count()):
            handle = buttons.nth(i)
            with contextlib.suppress(PlaywrightError):
                testid = handle.get_attribute("data-testid")
                label = (handle.inner_text() or "").strip()
                state = "disabled" if _is_button_disabled(handle) else "enabled"
                if not handle.is_visible():
                    state = "hidden"
                found.append(f"{testid!r} ({label!r}, {state})")
        parts.append(
            "action buttons on the page: " + (", ".join(found) if found else "none")
        )
    status = _read_status_text(page)
    parts.append(f"page status reads as {status!r}")
    return "; ".join(parts)


def _click_action_button(
    page: "Page",
    candidate_texts: Tuple[str, ...],
    *,
    selector: Optional[str] = None,
) -> None:
    """Click the overview page's suspend/resume action button.

    Prefers ``selector`` — a stable ``data-testid``, confirmed live for both
    actions (issue #766, see ``_RESUME_BUTTON_SELECTOR``/
    ``_SUSPEND_BUTTON_SELECTOR``) — and falls back to matching
    ``candidate_texts`` as a case-insensitive substring only if the testid
    matches nothing, so a future Yandex testid rename degrades to the old
    behaviour instead of breaking outright.

    The text fallback resolves the matched node's enclosing ``<button>``
    before clicking. ``get_by_text`` matches the ``<span class=
    "dc-Button__text">`` *inside* the button, not the button itself
    (confirmed live, issue #766) — clicking the span happens to work here
    because the click is dispatched at its coordinates and React's listener
    sits on an ancestor, but resolving the real button first makes
    ``_is_button_disabled``'s check meaningful, since ``disabled``/
    ``aria-disabled`` live on the ``<button>``, never on the inner span.

    Raises :class:`BrowserSessionError` if nothing matches — this
    deliberately does NOT fall back to clicking an unrelated element, since
    suspend/resume is a real account mutation. The error names both the
    selector and the labels that were searched for, and lists what the page
    actually renders (``_describe_page_buttons``), per issue #766.

    A matching button that is visible but disabled (issue #728) is treated
    as a distinct case from "not found": Yandex renders "Остановить
    кампанию" disabled — not hidden — while part of the campaign's
    creatives are still in moderation or rejected, so a click there
    physically lands but is a no-op. Reporting that as the generic "could
    not find a button, markup may have drifted" error sends the caller
    chasing a markup change that never happened. Raise a specific error
    naming the real cause instead, and keep scanning remaining candidates
    in case a different, enabled match exists.

    NOTE: a click that lands is NOT proof the action ran — see
    ``_STATUS_CLICK_MAX_ATTEMPTS``. Callers must verify the status actually
    changed and re-click if it did not; that loop lives in
    ``_click_and_wait_for_status_change``.
    """
    saw_disabled_match = False

    candidates = []
    if selector:
        with contextlib.suppress(PlaywrightError):
            locator = page.locator(selector)
            candidates.extend(locator.nth(i) for i in range(locator.count()))

    for text in candidate_texts:
        locator = page.get_by_text(text, exact=False)
        try:
            count = locator.count()
        except PlaywrightError:
            continue
        for i in range(count):
            node = locator.nth(i)
            # Resolve the enclosing <button> (see docstring); fall back to
            # the matched node itself if it has no button ancestor, which is
            # what the pre-#766 code always clicked.
            handle = node
            with contextlib.suppress(PlaywrightError):
                enclosing = node.locator("xpath=ancestor-or-self::button[1]")
                if enclosing.count():
                    handle = enclosing.first
            candidates.append(handle)

    for handle in candidates:
        try:
            if not handle.is_visible():
                continue
            if _is_button_disabled(handle):
                saw_disabled_match = True
                continue
            handle.click()
            return
        except PlaywrightError:
            continue

    if saw_disabled_match:
        raise BrowserSessionError(
            "The action button is currently disabled — this happens while "
            "part of the campaign's creatives are still on moderation or "
            "have been rejected. Try again once moderation finishes."
        )
    raise BrowserSessionError(
        "Could not find an action button on the campaign overview page. "
        f"Searched for selector {selector!r} and, as a fallback, any element "
        f"whose text contains one of {candidate_texts!r}. What the page "
        f"actually has — {_describe_page_buttons(page)}. Yandex may have "
        "changed the button's testid and text — re-run with --headful to "
        "inspect the page and report what you see."
    )


def _click_and_wait_for_status_change(
    page: "Page",
    campaign_id: int,
    *,
    current_status: str,
    target_statuses: Tuple[str, ...],
    button_texts: Tuple[str, ...],
    selector: Optional[str] = None,
    action_description: str,
) -> str:
    """Click the action button and confirm the status really changed,
    re-clicking if it did not (issue #766).

    The overview page's first click after navigation is frequently a silent
    no-op — see ``_STATUS_CLICK_MAX_ATTEMPTS`` for the live evidence (no
    network request is issued at all; React's handler was not yet attached).
    Waiting longer never helps in that state, which is why #766's reporter
    saw a permanent failure across repeated CLI runs while the pre-existing
    60s budget (#758/#764) merely made each failure slower.

    Each attempt re-reads the status BEFORE clicking, then clicks once, then
    polls for ``_STATUS_CHANGE_TIMEOUT_MS`` (calibrated to the measured
    1.6–2.3s real latency, see that constant).

    The pre-click re-read is what makes re-clicking safe. The poll alone is
    not enough: it gives up at the 8s deadline, so a click that lands but
    whose status update arrives late would otherwise be followed by a second
    click that undoes it. Worse for ``resume`` — once the status flips, the
    DOM swaps ``CampaignHeader.ActionButton.resume`` for ``.stop``, so the
    re-click finds neither the testid nor the fallback labels and raises
    "could not find an action button" for a mutation that actually
    succeeded. Reading first turns both cases into a plain success.
    """
    last_seen: Optional[str] = current_status
    started = _clock.now()
    for attempt in range(1, _STATUS_CLICK_MAX_ATTEMPTS + 1):
        if attempt > 1:
            # A previous attempt's click may have landed after its poll gave
            # up (see docstring) -- check before clicking again, never after.
            seen = _read_status_text(page)
            if seen is not None:
                last_seen = seen
            if last_seen in target_statuses:
                _log_timing(f"landed late, before click x{attempt}", started, last_seen)
                return last_seen  # type: ignore[return-value]

        try:
            _click_action_button(page, button_texts, selector=selector)
        except BrowserSessionError:
            # The button can legitimately vanish between the read above and
            # this click: the status flipped in that window, and the page
            # re-rendered the opposite action (resume -> stop). Re-read once
            # before surfacing this -- "button gone because we already
            # succeeded" must not be reported as a failure.
            seen = _read_status_text(page)
            if seen in target_statuses:
                _log_timing(f"button gone, already {seen}", started, seen)
                return seen  # type: ignore[return-value]
            raise

        last_seen = _poll_status(
            page, current_status=current_status, target_statuses=target_statuses
        )
        if last_seen in target_statuses:
            _log_timing(f"action-button click x{attempt}", started, last_seen)
            return last_seen  # type: ignore[return-value]

    raise BrowserSessionError(
        f"{action_description} for campaign {campaign_id} "
        f"{_STATUS_CLICK_MAX_ATTEMPTS} times, but its status never changed to "
        f"any of {target_statuses!r} (still {last_seen!r}) — each click was "
        f"given {_STATUS_CHANGE_TIMEOUT_MS / 1000:.0f}s to take effect. The "
        f"page reports: {_describe_page_buttons(page)}. Verify manually "
        "before retrying."
    )


def _click_and_wait_for_popup(
    page: "Page",
    *,
    trigger_selector: str,
    popup_selector: str,
    description: str,
) -> None:
    """Click ``trigger_selector`` and retry until ``popup_selector`` actually
    appears (issues #723/#725).

    Live testing found clicking a menu trigger or an edit-name button that is
    itself visible/enabled sometimes does not open its popup/modal at all —
    the click physically lands (Playwright's actionability check passes,
    nothing raises), but the popup/portal it should open never renders,
    because React's own click handler or the portal mount was still
    hydrating at the moment of the click. A single click plus an
    unconditional ``.click()`` on the popup's contents (what every caller did
    before this helper) would then fail with a generic "not found" error that
    looks identical to Yandex having actually changed the page's markup.

    This clicks the trigger, waits up to ``_POPUP_APPEAR_TIMEOUT_MS`` for the
    popup to become visible, and — if it doesn't — retries the whole
    click-then-wait sequence up to ``_POPUP_CLICK_MAX_ATTEMPTS`` times before
    raising. Each retry re-clicks the trigger rather than just waiting
    longer: the menu trigger toggles (a lingering half-open popup would be
    closed by a second click, which is fine — the following wait then opens
    it fresh) and the edit-name button reliably opens a fresh modal instance
    on every click, so a retry here is safe to repeat, unlike the terminal
    save/launch buttons this module deliberately clicks only once (see
    ``_click_draft_terminal_button``'s docstring for why an unconditional
    retry is NOT safe there — it is safe here specifically because opening a
    menu/modal has no side effect on the campaign itself).
    """
    trigger = page.locator(trigger_selector).first
    popup = page.locator(popup_selector).first

    last_exc: Optional[Exception] = None
    for _ in range(_POPUP_CLICK_MAX_ATTEMPTS):
        # A prior iteration's wait_for() can time out at the 1.5s mark just
        # before a genuinely successful (merely slow) open finishes
        # rendering. Re-clicking the trigger unconditionally in that case
        # would close a toggle menu that did open, or land on an overlay for
        # the rename modal — turning a slow-but-correct open into a
        # deterministic failure. Check first: if the popup is already up (a
        # near-zero-timeout wait_for, not a one-shot is_visible() snapshot —
        # consistent with this module's convention elsewhere, see
        # _read_goal_price), we're done without touching the trigger again.
        try:
            popup.wait_for(state="visible", timeout=1)
            return
        except PlaywrightError:
            pass

        try:
            trigger.click()
        except PlaywrightError as exc:
            last_exc = exc
            continue

        try:
            popup.wait_for(state="visible", timeout=_POPUP_APPEAR_TIMEOUT_MS)
            return
        except PlaywrightError as exc:
            last_exc = exc
            continue

    raise BrowserSessionError(
        f"Clicked {trigger_selector!r} to open {description}, but "
        f"{popup_selector!r} did not appear within "
        f"{_POPUP_APPEAR_TIMEOUT_MS / 1000:.1f}s even after "
        f"{_POPUP_CLICK_MAX_ATTEMPTS} attempts — Yandex may have changed the "
        "page's markup, or the click keeps landing before the page's React "
        "handlers finish hydrating. Re-run with --headful to inspect the "
        "page."
    ) from last_exc


def _poll_status(
    page: "Page",
    *,
    current_status: Optional[str],
    target_statuses: Tuple[str, ...],
) -> Optional[str]:
    """Poll ``_read_status_text`` for up to ``_STATUS_CHANGE_TIMEOUT_MS``,
    returning the last status read — one of ``target_statuses`` if it got
    there, otherwise whatever it still says.

    Unlike the pre-#766 ``_wait_for_status`` this does NOT raise on timeout:
    a status that has not changed is a normal, expected outcome of the
    no-op first click (see ``_STATUS_CLICK_MAX_ATTEMPTS``), and the decision
    to retry or give up belongs to the caller's click loop, not here.

    The measured latency this budget covers is 1.6–2.3s (issue #764, see
    ``_STATUS_CHANGE_TIMEOUT_MS``); reads that come back ``None`` (the
    status element momentarily unrendered mid-transition — observed live)
    are simply polled again rather than treated as a distinct state.
    """
    started = _clock.now()
    deadline = started + _STATUS_CHANGE_TIMEOUT_MS / 1000
    new_status = current_status
    while True:
        seen = _read_status_text(page)
        if seen is not None:
            new_status = seen
        if new_status in target_statuses:
            _log_timing("post-click status change", started, new_status)
            return new_status
        if _clock.now() >= deadline:
            _log_timing("post-click status change (TIMED OUT)", started, new_status)
            return new_status
        page.wait_for_timeout(250)


def _wait_for_recognised_status(page: "Page") -> Optional[str]:
    """Poll ``_read_status_text`` until it returns a recognised status, or
    ``_STATUS_CHANGE_TIMEOUT_MS`` elapses; return ``None`` if it never does.

    ``_goto_overview_page`` only guarantees the *title* has rendered (issue
    #683); the status element is a separate render pass and routinely reads
    as ``None`` for a moment after it. Every caller that branches on the
    current status needs this wait first — ``resume_master`` had it inline
    (issue #758 follow-up) but ``_suspend_or_resume`` did not, which
    live-aborted a real ``masters suspend`` with "unrecognised status text"
    (issue #766).

    Budgeted by ``_STATUS_HYDRATION_TIMEOUT_MS``, NOT the post-click
    ``_STATUS_CHANGE_TIMEOUT_MS`` — see that constant for why the two are
    deliberately separate.
    """
    started = _clock.now()
    deadline = started + _STATUS_HYDRATION_TIMEOUT_MS / 1000
    status = _read_status_text(page)
    while status is None and _clock.now() < deadline:
        page.wait_for_timeout(250)
        status = _read_status_text(page)
    _log_timing("initial status hydration", started, status)
    return status


def _click_menu_item_and_wait_for_status(
    page: "Page",
    campaign_id: int,
    *,
    item_selector: str,
    item_label: str,
    current_status: str,
    target_statuses: Tuple[str, ...],
) -> str:
    """``_click_menu_item`` plus the same click-really-landed retry loop
    ``_click_and_wait_for_status_change`` applies to the action buttons
    (issue #766).

    ``_click_and_wait_for_popup`` already retries opening the "⋮" menu, but
    nothing previously retried the click on the menu *item* itself — and
    that click is subject to the identical hydration no-op (the menu item is
    rendered by the same React tree). ``resume_master``'s unarchive step is
    the only caller; before #766 it clicked once and then waited out the
    full status budget, which is exactly the failure shape #764 recorded for
    the unarchive leg.

    Safe to retry for the same reason the action-button loop is: re-opening
    the menu has no side effect, the status is re-checked before each
    attempt, and unarchive is reversible.
    """
    last_seen: Optional[str] = current_status
    started = _clock.now()
    for attempt in range(1, _STATUS_CLICK_MAX_ATTEMPTS + 1):
        if attempt > 1:
            # Same pre-click re-read as the action-button loop: a click whose
            # status update arrived after its poll gave up must not be
            # followed by another one (unarchive is reversible, but a
            # re-archive would be a real, unwanted mutation).
            seen = _read_status_text(page)
            if seen is not None:
                last_seen = seen
            if last_seen in target_statuses:
                _log_timing(f"landed late, before click x{attempt}", started, last_seen)
                return last_seen  # type: ignore[return-value]

        try:
            _click_menu_item(
                page,
                campaign_id,
                item_selector=item_selector,
                item_label=item_label,
            )
        except BrowserSessionError:
            # The menu item disappears once the campaign leaves ARCHIVED --
            # "gone because it worked" is a success, not a failure.
            seen = _read_status_text(page)
            if seen in target_statuses:
                _log_timing(f"menu item gone, already {seen}", started, seen)
                return seen  # type: ignore[return-value]
            raise

        last_seen = _poll_status(
            page, current_status=current_status, target_statuses=target_statuses
        )
        if last_seen in target_statuses:
            _log_timing(f"menu-item click x{attempt}", started, last_seen)
            return last_seen  # type: ignore[return-value]

    raise BrowserSessionError(
        f"Clicked {item_label!r} for campaign {campaign_id} "
        f"{_STATUS_CLICK_MAX_ATTEMPTS} times, but its status never changed to "
        f"any of {target_statuses!r} (still {last_seen!r}) — each click was "
        f"given {_STATUS_CHANGE_TIMEOUT_MS / 1000:.0f}s to take effect. The "
        f"page reports: {_describe_page_buttons(page)}. Verify manually "
        "before retrying."
    )


def _suspend_or_resume(
    page: "Page",
    campaign_id: int,
    *,
    target_statuses: Tuple[str, ...],
    button_texts: Tuple[str, ...],
    button_selector: Optional[str] = None,
) -> Dict[str, Any]:
    """Shared body for ``suspend_master``/``resume_master``.

    Idempotent: if the campaign is already in one of ``target_statuses``,
    does not click anything and returns the current state with a warning
    (mirrors the rest of the CLI's suspend/resume convention). Otherwise
    clicks the matching action button and re-reads the status to confirm the
    mutation actually took effect — a click that doesn't visibly change the
    status is retried up to ``_STATUS_CLICK_MAX_ATTEMPTS`` times (issue
    #766: the first click on a freshly-rendered page is often a silent
    no-op) and only then reported as a hard error, never as a silent
    success.

    ``target_statuses`` is a tuple, not a single status, because resuming a
    SUSPENDED campaign can land in either ACTIVE or MODERATION depending on
    whether Yandex decides the campaign needs re-review (issue #758,
    live-confirmed 2026-08-05 — see the module docstring's transition
    matrix); the caller cannot predict which one ahead of time, and treating
    MODERATION as a failure here would make a perfectly successful resume
    time out.

    A DRAFT campaign's overview page has no ACTIVE/SUSPENDED status and no
    action button to click (issue #660, see module docstring's "DRAFT
    overview page" note) — refuses with a clear error instead of clicking
    blind or misreporting a made-up status.
    """
    _goto_overview_page(page, campaign_id)

    if _is_draft_overview_page(page):
        raise BrowserSessionError(
            f"Campaign {campaign_id} is a DRAFT — it has no ACTIVE/SUSPENDED "
            "state to suspend/resume. Launch it first (masters launch)."
        )

    # Poll rather than read once: _goto_overview_page only guarantees the
    # title rendered (issue #683), and the status element is a separate
    # render pass that routinely still reads as None immediately after it.
    # Live-confirmed 2026-08-06 (issue #766) — a bare single read here
    # aborted a real `masters suspend` with "unrecognised status text" on a
    # campaign whose status was perfectly readable a second later.
    # resume_master already had this poll on its own pre-branch read; this
    # is the same wait, now also covering the suspend path and resume's
    # second leg. _read_status_text returning None forever (a genuinely
    # unrecognised status) still raises below.
    current_status = _wait_for_recognised_status(page)
    if current_status is None:
        raise BrowserSessionError(
            f"Could not determine current status for campaign {campaign_id} "
            "(unrecognised status text) — refusing to click blind. The page "
            f"reports: {_describe_page_buttons(page)}."
        )
    if current_status in target_statuses:
        print_warning(
            f"Campaign {campaign_id} is already {current_status}; not clicking."
        )
        return {"CampaignId": campaign_id, "Status": current_status}

    new_status = _click_and_wait_for_status_change(
        page,
        campaign_id,
        current_status=current_status,
        target_statuses=target_statuses,
        button_texts=button_texts,
        selector=button_selector,
        action_description="Clicked the action button",
    )

    return {"CampaignId": campaign_id, "Status": new_status}


def suspend_master(page: "Page", campaign_id: int) -> Dict[str, Any]:
    """Stop (suspend) a Мастер кампаний, verifying the status actually changed.

    Live-verified 2026-08-06 (issue #766) against campaign 713277109: the
    button is ``CampaignHeader.ActionButton.stop``, labelled "Остановить
    кампанию" — both the testid and the label are now confirmed, replacing
    #630's unverified guess.
    """
    return _suspend_or_resume(
        page,
        campaign_id,
        target_statuses=("SUSPENDED",),
        button_texts=_SUSPEND_BUTTON_TEXTS,
        button_selector=_SUSPEND_BUTTON_SELECTOR,
    )


def resume_master(page: "Page", campaign_id: int) -> Dict[str, Any]:
    """Resume a Мастер кампаний, verifying the status actually changed.

    "Возобновить кампанию" is confirmed live (see module docstring /
    ``tests/fixtures/masters_wizard_overview.html``).

    If the campaign is currently ARCHIVED, first clicks "Разархивировать"
    (issue #758, live-confirmed 2026-08-05) and waits for SUSPENDED — an
    ARCHIVED campaign's overview page has no resume button at all, only
    this menu item, and it does not itself lead to ACTIVE. Once SUSPENDED
    (whether it started there or just arrived via unarchive), proceeds with
    the ordinary one-click resume, accepting either ACTIVE or MODERATION as
    success (see ``_suspend_or_resume``'s docstring for why both are valid).

    Navigates to the overview page itself first to read the current status
    — ``_suspend_or_resume`` navigates again below, which is a harmless
    repeat (``_goto_overview_page`` is idempotent) rather than trusting a
    status read against whatever page ``page`` happened to be on before this
    call, the same tradeoff ``archive_master`` makes for its own suspend-then-
    archive path below.
    """
    _goto_overview_page(page, campaign_id)
    # _goto_overview_page only guarantees the title rendered (issue #683) --
    # the separate status-text element can still read as unrecognised
    # (None) on the very first call right after navigation. Poll briefly
    # for a recognised status before branching on it, so a hydration race
    # here doesn't silently skip the ARCHIVED/unarchive branch and fall
    # through to a doomed search for a resume button that an ARCHIVED page
    # does not have (issue #758 follow-up). _suspend_or_resume's own
    # ``current_status is None`` check below remains the final safety net
    # for a genuinely unrecognised status that never hydrates.
    current_status = _wait_for_recognised_status(page)
    if current_status == "ARCHIVED":
        _click_menu_item_and_wait_for_status(
            page,
            campaign_id,
            item_selector=_UNARCHIVE_MENU_ITEM_SELECTOR,
            item_label="Разархивировать",
            current_status=current_status,
            target_statuses=("SUSPENDED",),
        )

    return _suspend_or_resume(
        page,
        campaign_id,
        target_statuses=("ACTIVE", "MODERATION"),
        button_texts=_RESUME_BUTTON_TEXTS,
        button_selector=_RESUME_BUTTON_SELECTOR,
    )


def _find_master_row(
    page: "Page", campaign_id: int, *, status: str = "all"
) -> Optional[Dict[str, Any]]:
    """Return this campaign's row from ``fetch_masters_list``, or ``None``."""
    for row in fetch_masters_list(page, status=status):
        if row["CampaignId"] == campaign_id:
            return row
    return None


def _click_menu_item(
    page: "Page",
    campaign_id: int,
    *,
    item_selector: str,
    item_label: str,
) -> None:
    """Open the overview page's "⋮" menu and click ``item_selector``.

    Shared by ``archive_master`` (Архивировать) and ``resume_master``
    (Разархивировать, issue #758) — both need the exact same
    open-menu-then-click-item sequence, backed by confirmed-live
    ``data-testid`` selectors, not guessed text (see module docstring).
    Reuses ``_click_and_wait_for_popup`` for its hydration-race retries
    (issues #723/#725) rather than duplicating that click logic here.
    """
    try:
        _click_and_wait_for_popup(
            page,
            trigger_selector=_MENU_TRIGGER_SELECTOR,
            popup_selector=item_selector,
            description=f"the campaign menu for {campaign_id}",
        )
    except BrowserSessionError as exc:
        raise BrowserSessionError(
            f"Could not open the campaign menu for {campaign_id} and find "
            f"'{item_label}' ({_MENU_TRIGGER_SELECTOR!r} / {item_selector!r}) "
            "— Yandex may have changed the overview page's markup."
        ) from exc

    item = page.locator(item_selector).first
    try:
        item.click()
    except PlaywrightError as exc:
        raise BrowserSessionError(
            f"Could not click '{item_label}' for campaign {campaign_id} "
            f"({item_selector!r} found but not clickable) — Yandex may have "
            "changed the overview page's menu."
        ) from exc


def archive_master(page: "Page", campaign_id: int) -> Dict[str, Any]:
    """Archive a Мастер кампаний, verifying the grid actually reports it archived.

    There is no separate "delete" for Мастер кампаний (issue #633 live
    recon, documented in the module docstring) — this is the only
    destructive/lifecycle action beyond suspend/resume. Idempotent: if the
    campaign is already archived, does not click anything and returns the
    current row with a warning (mirrors ``suspend_master``/``resume_master``).

    If the campaign is currently ACTIVE or MODERATION, first suspends it
    (issue #758, live-confirmed 2026-08-05) and waits for SUSPENDED — the
    "Архивировать" menu item is not present at all until the campaign is
    SUSPENDED (see module docstring's transition matrix). Reuses
    ``suspend_master`` rather than duplicating its click/verify logic.

    Once SUSPENDED, opens the campaign's overview page, clicks the "⋮" menu
    trigger, then the "Архивировать" item (both selected via confirmed-live
    ``data-testid`` attributes, not guessed text — see module docstring),
    and re-reads the campaigns grid via ``fetch_masters_list`` to confirm
    ``Status == "ARCHIVED"`` before reporting success — never trusting the
    click alone.
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
    if existing["Status"] == "DRAFT":
        raise BrowserSessionError(
            f"Campaign {campaign_id} is a DRAFT — its overview page has no "
            '"⋮" menu to archive from (issue #660), and no delete action '
            "exists for a Мастер кампаний draft anywhere in the UI. Launch "
            "it first (masters launch) if you want to archive it."
        )

    _goto_overview_page(page, campaign_id)

    if existing["Status"] in ("ACTIVE", "MODERATION"):
        suspend_master(page, campaign_id)
        _goto_overview_page(page, campaign_id)

    _click_menu_item(
        page,
        campaign_id,
        item_selector=_ARCHIVE_MENU_ITEM_SELECTOR,
        item_label="Архивировать",
    )

    deadline = _clock.now() + _ARCHIVE_VERIFY_TIMEOUT_MS / 1000
    updated = existing
    while _clock.now() < deadline:
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


def _verify_launched_to_moderation(page: "Page", campaign_id: int) -> str:
    """Poll the overview page's status text until it reports MODERATION.

    Shared by ``launch_master`` and ``update_master --launch`` (issue #721):
    both click a DRAFT edit page's launch button and then need the SAME
    proof the publish actually happened — Yandex does not flip a DRAFT
    straight to ACTIVE, clicking "Запустить кампанию" sends it to moderation
    first (confirmed live, issue #668's recon of the same button). Reads the
    overview page's own status text (``_read_status_text``, "Кампания
    на\xa0модерации"), NOT the campaigns grid (``fetch_masters_list``) — the
    grid's ``primaryStatus`` was observed to lag the real DRAFT->MODERATION
    transition by 45+ seconds in the issue #704 recon, while the overview
    page already reflected it immediately after the click's own redirect.

    Callers must already be on (or have just navigated to) the campaign's
    overview page — this function only polls ``_read_status_text``, it does
    not navigate itself, so callers with different pre-poll navigation needs
    (``launch_master`` re-navigates via ``_goto_overview_page`` after its
    click; ``update_master`` is already there after ``_click_save``'s own
    redirect-wait) stay in control of that step.

    Raises :class:`BrowserSessionError` if the status never becomes
    MODERATION within ``_LAUNCH_VERIFY_TIMEOUT_MS`` — a click that doesn't
    visibly change the status is a hard error, not a silent success, per
    this module's dominant convention (see ``_suspend_or_resume``).
    """
    deadline = _clock.now() + _LAUNCH_VERIFY_TIMEOUT_MS / 1000
    new_status = None
    while _clock.now() < deadline:
        new_status = _read_status_text(page)
        if new_status == "MODERATION":
            break
        page.wait_for_timeout(250)

    if new_status != "MODERATION":
        raise BrowserSessionError(
            f"Clicked '{_LAUNCH_BUTTON_TEXT}' for campaign {campaign_id}, but "
            "its overview page did not report MODERATION within "
            f"{_LAUNCH_VERIFY_TIMEOUT_MS / 1000:.0f}s (still "
            f"{new_status!r}). The click may not have hit the right "
            "element, or Yandex is slow to apply it — verify manually "
            "before retrying."
        )

    return new_status


def launch_master(page: "Page", campaign_id: int) -> Dict[str, Any]:
    """Publish a DRAFT Мастер кампаний via the edit page's launch button (issue #704).

    Mirrors ``archive_master``'s contract: idempotent (a non-DRAFT campaign
    is a no-op, returning its current row with a warning — there is no
    un-launch), verifies the status actually changed before reporting
    success, never trusts the click alone.

    Yandex does not flip a DRAFT straight to ACTIVE — clicking "Запустить
    кампанию" sends it to moderation first (confirmed live, issue #668's
    recon of the same button). This function therefore waits for
    ``"MODERATION"``, not ``"ACTIVE"``.

    **Live-confirmed 2026-08-04 (issue #704 recon, campaign 713271554):**
    verification reads the overview page's own status text
    (``_read_status_text``, "Кампания на\xa0модерации"), NOT the campaigns grid
    (``fetch_masters_list``) — the grid's ``primaryStatus`` was observed to
    lag the real DRAFT->MODERATION transition by 45+ seconds in that recon,
    while the overview page already reflected it immediately after the
    click's own redirect. The grid is still used for the BEFORE check
    (there is no cheaper way to confirm a campaign is currently DRAFT
    without first knowing which page to open), but never for the AFTER
    check — that half is ``_verify_launched_to_moderation`` (issue #721),
    shared with ``update_master --launch`` so both entry points that publish
    a DRAFT prove it the same way.

    Reuses ``_click_draft_terminal_button(page, campaign_id, launch=True)``
    from #668 — the same DRAFT edit-page save-as-draft/launch pair
    ``update_master --launch`` already drives — rather than re-deriving the
    click from scratch.
    """
    existing = _find_master_row(page, campaign_id, status="all")
    if existing is None:
        raise BrowserSessionError(
            f"Could not find Мастер кампаний {campaign_id} in the campaigns "
            "grid — check the ID, or it may already be gone."
        )
    if existing["Status"] != "DRAFT":
        print_warning(
            f"Campaign {campaign_id} is not a DRAFT (status "
            f"{existing['Status']!r}); not clicking."
        )
        return existing

    url = WIZARD_EDIT_URL.format(campaign_id=campaign_id)
    page.goto(url, wait_until="commit")
    assert_not_captcha(page.content())
    assert_authenticated(page.content())
    _wait_for_edit_form(page, campaign_id)

    if not _is_draft_edit_page(page):
        raise BrowserSessionError(
            f"Campaign {campaign_id} was reported as DRAFT by the campaigns "
            "grid, but its edit page does not show the DRAFT save-as-draft/"
            "launch buttons — Yandex may have changed the page's markup, or "
            "the status changed between the grid read and this navigation. "
            "Verify manually before retrying."
        )

    _click_draft_terminal_button(page, campaign_id, launch=True)

    # _click_draft_terminal_button already waited for page.url to leave
    # /edit/, but that may land on the overview page mid-transition (or on a
    # different route entirely) — one fresh navigation to the overview URL,
    # rather than trusting wherever the redirect happened to land, is what
    # _read_status_text below actually needs. _goto_overview_page (issue
    # #683) is the module's shared "navigate and wait for the page to
    # actually render" helper — the same race this function hit in its own
    # live recon (a bare wait_until="commit" plus an immediate read found no
    # status text at all, because the SPA hadn't painted anything yet).
    _goto_overview_page(page, campaign_id)

    new_status = _verify_launched_to_moderation(page, campaign_id)

    return {"CampaignId": campaign_id, "Status": new_status}


def copy_master(
    page: "Page", campaign_id: int, *, launch: bool = False
) -> Dict[str, Any]:
    """Clone a Мастер кампаний via the overview menu's "Клонировать" item.

    Live-verified end to end (issue #659, campaign 107707079 → draft copy
    713231614 — see module docstring). "Клонировать" does not clone
    instantly: it navigates to the same step-2 create form ``create_master``
    uses, pre-filled from the source campaign (headlines, texts, images,
    region, budget, ...). Not idempotent, like ``create_master``: calling
    this twice creates a SECOND copy, not an update to the first — there is
    no rollback for Мастер кампаний.

    ``launch=False`` (default) clicks "Сохранить как черновик" — the copy is
    created but not launched, mirroring ``masters add``'s ``--draft``
    default. ``launch=True`` clicks "Запустить кампанию" instead, launching
    the copy immediately in production.
    """
    existing = _find_master_row(page, campaign_id)
    if existing is None:
        raise BrowserSessionError(
            f"Could not find Мастер кампаний {campaign_id} in the campaigns "
            "grid — check the ID, or it may already be gone."
        )

    _goto_overview_page(page, campaign_id)

    try:
        _click_and_wait_for_popup(
            page,
            trigger_selector=_MENU_TRIGGER_SELECTOR,
            popup_selector=_CLONE_MENU_ITEM_SELECTOR,
            description=f"the campaign menu for {campaign_id}",
        )
    except BrowserSessionError as exc:
        raise BrowserSessionError(
            f"Could not open the campaign menu for {campaign_id} and find "
            f"'Клонировать' ({_MENU_TRIGGER_SELECTOR!r} / "
            f"{_CLONE_MENU_ITEM_SELECTOR!r}) — Yandex may have changed the "
            "overview page's markup."
        ) from exc

    clone_item = page.locator(_CLONE_MENU_ITEM_SELECTOR).first
    try:
        clone_item.click()
    except PlaywrightError as exc:
        raise BrowserSessionError(
            f"Could not click 'Клонировать' for campaign {campaign_id} "
            f"({_CLONE_MENU_ITEM_SELECTOR!r} found but not clickable) — "
            "Yandex may have changed the overview page's menu."
        ) from exc

    _wait_for_step2(page)
    _click_terminal_button(
        page, _LAUNCH_BUTTON_TEXT if launch else _SAVE_DRAFT_BUTTON_TEXT
    )

    deadline = _clock.now() + _CLONE_VERIFY_TIMEOUT_MS / 1000
    new_id: Optional[int] = None
    while _clock.now() < deadline:
        match = _WIZARD_OVERVIEW_URL_ID_RE.search(page.url)
        # Must be a DIFFERENT campaign ID than the source: page.url still
        # holds the source's own overview URL from the goto() above until
        # Yandex actually redirects to the clone's, so matching the source's
        # ID here is not evidence of anything having happened yet.
        if match and int(match.group(1)) != campaign_id:
            new_id = int(match.group(1))
            break
        page.wait_for_timeout(250)

    if new_id is None:
        raise BrowserSessionError(
            f"Clicked '{_LAUNCH_BUTTON_TEXT if launch else _SAVE_DRAFT_BUTTON_TEXT}' "
            f"after cloning campaign {campaign_id}, but Yandex did not "
            f"redirect to the new campaign's overview page within "
            f"{_CLONE_VERIFY_TIMEOUT_MS / 1000:.0f}s — verify manually "
            "before retrying (this is not idempotent)."
        )

    # The clone/terminal-button click above already happened — irreversible,
    # not idempotent (a retry would re-click and create a SECOND copy). If
    # the saved session is invalidated in exactly this window,
    # fetch_masters_list's own assert_authenticated raises BrowserAuthError;
    # letting that propagate as-is would make _with_session
    # (direct_cli/commands/masters.py) retry this ENTIRE function under a
    # fresh session, silently duplicating the campaign. Re-raise as a plain
    # BrowserSessionError so that retry does not trigger, and name new_id so
    # the caller can check the clone that already exists instead of losing
    # track of it.
    updated = None
    deadline = _clock.now() + _CLONE_VERIFY_TIMEOUT_MS / 1000
    try:
        while _clock.now() < deadline:
            updated = _find_master_row(page, new_id, status="all")
            if updated is not None:
                break
            page.wait_for_timeout(250)
    except BrowserAuthError as exc:
        raise BrowserSessionError(
            f"Yandex redirected to campaign {new_id} after cloning "
            f"{campaign_id}, but the session was invalidated while "
            "verifying it in the campaigns grid — the clone was likely "
            f"created; check campaign {new_id} manually rather than "
            "retrying (this is not idempotent)."
        ) from exc

    if updated is None:
        raise BrowserSessionError(
            f"Yandex redirected to campaign {new_id} after cloning "
            f"{campaign_id}, but it did not appear in the campaigns grid "
            f"within {_CLONE_VERIFY_TIMEOUT_MS / 1000:.0f}s — verify "
            "manually before retrying (this is not idempotent)."
        )

    result = dict(updated)
    result["SourceCampaignId"] = campaign_id
    result["Launched"] = launch
    return result


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


def _set_campaign_name(page: "Page", name: str) -> None:
    """Rename the campaign via the header's "Название кампании" modal.

    Unlike every other Этап A field, the name lives behind a separate modal
    opened by the header's pencil icon (``_EDIT_NAME_BUTTON_SELECTOR``) —
    see the module docstring for why the modal's own "Применить" isn't the
    real save.
    """
    try:
        _click_and_wait_for_popup(
            page,
            trigger_selector=_EDIT_NAME_BUTTON_SELECTOR,
            popup_selector=_NAME_MODAL_INPUT_SELECTOR,
            description="the campaign name modal ('Название кампании')",
        )
    except BrowserSessionError as exc:
        raise BrowserSessionError(
            "Could not open the campaign name modal ('Название кампании') "
            f"on the campaign edit page ({_EDIT_NAME_BUTTON_SELECTOR!r} / "
            f"{_NAME_MODAL_INPUT_SELECTOR!r}) — Yandex may have changed the "
            "page's markup. Re-run with --headful to inspect the page."
        ) from exc

    try:
        name_input = page.locator(_NAME_MODAL_INPUT_SELECTOR).first
        name_input.click()
        name_input.fill(name)
        page.locator(_NAME_MODAL_ACCEPT_SELECTOR).first.click()
    except PlaywrightError as exc:
        raise BrowserSessionError(
            "Could not fill or submit the campaign name modal ('Название "
            "кампании') on the campaign edit page — Yandex may have changed "
            "the page's markup. Re-run with --headful to inspect the page."
        ) from exc


_SPOILER_EXPAND_POLL_TIMEOUT_MS = 2000
_SPOILER_EXPAND_MAX_ATTEMPTS = 3


def _expand_utm_spoiler(page: "Page") -> bool:
    """Expand the "Дополнительные параметры" spoiler to reveal UTMInput.

    The UTM field is lazily mounted — it only appears in the DOM after the
    spoiler is expanded. Retries the click (up to
    ``_SPOILER_EXPAND_MAX_ATTEMPTS`` times) if the first attempt is
    swallowed by a React re-render (observed live during issue #761
    recon), same "click a trigger and verify the effect landed" shape as
    ``_click_and_wait_for_popup`` — but the trigger here (an inline
    disclosure toggle) is safe to re-click unconditionally on every retry,
    unlike that helper's menu/modal triggers, so a plain loop suffices
    rather than sharing its popup-specific bookkeeping.

    Returns ``True`` if the spoiler is expanded, ``False`` if the spoiler
    element was not found at all.
    """
    btn = page.locator(_EDIT_UTM_SPOILER_BUTTON_TESTID).first
    try:
        if btn.count() == 0:
            return False
    except PlaywrightError:
        return False
    for _ in range(_SPOILER_EXPAND_MAX_ATTEMPTS):
        try:
            if btn.get_attribute("aria-expanded") == "true":
                return True
            btn.click()
        except PlaywrightError:
            # Fallback: direct JS click (bypasses Playwright actionability
            # checks) if the Playwright click itself failed to land.
            with contextlib.suppress(PlaywrightError):
                page.evaluate(
                    "(sel) => { const b = document.querySelector(sel); "
                    "if (b) b.click(); }",
                    _EDIT_UTM_SPOILER_BUTTON_TESTID,
                )
        if _poll_until(
            page,
            lambda: btn.get_attribute("aria-expanded") == "true",
            _SPOILER_EXPAND_POLL_TIMEOUT_MS,
        ):
            return True
    return False


def _read_tracking_params(page: "Page") -> Optional[str]:
    """Read the UTMInput field value ("UTM-метки и параметры URL"), expanding
    the "Дополнительные параметры" spoiler if needed.

    Returns the raw query string (without leading ``?``), or ``None`` if the
    field is not mounted / not readable.  An empty string means the field
    is mounted and genuinely empty.
    """
    # _expand_utm_spoiler is itself a cheap no-op (single aria-expanded
    # read) when the spoiler is already open, so there is no need to
    # duplicate that check here first.
    _expand_utm_spoiler(page)
    field = page.locator(_EDIT_UTM_INPUT_TESTID).first
    try:
        return field.text_content()
    except PlaywrightError:
        return None


def _set_contenteditable_field(
    page: "Page", testid: str, value: str, *, label: str
) -> None:
    """Click, clear and retype one of the edit page's contenteditable fields.

    The shared click/clear/verify-cleared/``_type_landing_url`` mechanics
    behind ``_set_landing_url`` and ``_set_tracking_params`` — both are the
    same widget family (issue #690's keystroke-dropping race applies to
    every field in it), differing only in testid and in the ``label`` used
    to keep each caller's error messages field-specific rather than generic.

    Passing an empty ``value`` clears the field and returns without typing.
    Callers own any field-specific preconditions (``_set_landing_url``'s
    ARCHIVED guard, ``_set_tracking_params``' spoiler expansion) — those run
    before this helper is called.
    """
    field = page.locator(testid).first
    try:
        field.click()
    except PlaywrightError as exc:
        raise BrowserSessionError(
            f"Could not find or click the {label} field "
            f"({testid!r}) on the campaign edit page — Yandex may have "
            "changed the page's markup. Re-run with --headful to inspect "
            "the page."
        ) from exc

    if not _clear_text_field(field):
        raise BrowserSessionError(
            f"Could not clear the {label} field on the campaign edit page "
            "before typing the new value — Yandex may have changed the "
            "page's markup. Re-run with --headful to inspect the page."
        )

    try:
        current = field.text_content()
    except PlaywrightError:
        current = None
    if current not in ("", None):
        raise BrowserSessionError(
            f"Could not clear the {label} field on the campaign edit page "
            "— Yandex may have changed the page's markup. Re-run with "
            "--headful to inspect the page."
        )

    if not value:
        return

    _type_landing_url(field, value)


def _set_tracking_params(page: "Page", tracking_params: str) -> None:
    """Set the edit page's "UTM-метки и параметры URL" field (issue #761,
    see the module docstring's UTMInput note for what this field is).

    Lazily mounted under the collapsed "Дополнительные параметры" spoiler
    (``_EDIT_UTM_SPOILER_BUTTON_TESTID``), which this function expands
    first. Passing an empty string clears the field.
    """
    if not _expand_utm_spoiler(page):
        raise BrowserSessionError(
            "Could not find the 'Дополнительные параметры' spoiler to "
            "reveal the UTM params field — Yandex may have changed the "
            "page's markup. Re-run with --headful to inspect the page."
        )

    _set_contenteditable_field(
        page, _EDIT_UTM_INPUT_TESTID, tracking_params, label="UTM params"
    )


def _read_landing_url(page: "Page") -> Optional[str]:
    """Read the edit page's current "Ссылка на продвигаемую страницу" value.

    Returns ``None`` if the field can't be found/read (inconclusive) — same
    convention as ``_read_campaign_name``. An empty string is a real,
    distinguishable value (the field genuinely cleared, not unreadable).
    """
    field = page.locator(_EDIT_URL_INPUT_TESTID).first
    try:
        return field.text_content()
    except PlaywrightError:
        return None


def _set_landing_url(page: "Page", url: str) -> None:
    """Set the edit page's "Ссылка на продвигаемую страницу" field.

    Reuses the same contenteditable click/clear/type-with-verify mechanics
    as the create page's ``_fill_landing_url``/``_type_landing_url`` (issue
    #690's keystroke-dropping race applies here too — same widget family,
    different testid namespace, see ``_EDIT_URL_INPUT_TESTID``'s docstring)
    but WITHOUT that function's step-1-specific "Далее"/suggestions-popup
    handling: this field lives directly on the single whole-form edit page,
    with no separate continuation step — typing a new value and letting the
    terminal ``_click_save`` commit it (like every other field
    ``update_master`` writes) is the whole flow.

    Passing an empty string clears the field down to Yandex's placeholder,
    which mirrors the Clear button's own effect. This field is independent
    of the UTM query string, which lives in a separate dedicated field (see
    ``_set_tracking_params``/``--tracking-params``, issue #761) — passing a
    full URL with a ``?...`` query string here writes that query string as
    part of this field's own value, unchanged.

    Confirmed live (issue #757) this field is READ-ONLY while the
    campaign's current status is ARCHIVED. Does NOT pre-check the Clear
    button's ``disabled`` state to detect this up front (issue #761
    cycle-review round 2, Codex): that button is ALSO legitimately
    disabled on an ordinary, non-ARCHIVED campaign — whenever the field is
    unfocused (confirmed live, ``scripts/recon_761_utm_split.py``) or
    whenever the URL is currently empty (nothing to clear) — so no
    point-in-time read of it, cold or click-then-poll, can reliably tell
    "read-only because ARCHIVED" from "disabled for an unrelated reason"
    without a first-class status read. Instead, this just attempts the
    write via ``_set_contenteditable_field``, which already raises a named
    ``BrowserSessionError`` if the field won't clear/accept text — an
    ARCHIVED campaign's genuinely read-only field surfaces through that
    same path, upgraded with a status-text hint (best-effort, via
    ``_read_status_text``) when it's actually the cause, exactly like
    ``_wait_for_draft_status``'s own ARCHIVED-timeout message.
    """
    try:
        _set_contenteditable_field(
            page, _EDIT_URL_INPUT_TESTID, url, label="landing-page URL"
        )
    except BrowserSessionError as exc:
        status_hint = ""
        with contextlib.suppress(PlaywrightError):
            if _read_status_text(page) == "ARCHIVED":
                status_hint = (
                    " The landing-page URL field is read-only for this "
                    "campaign — Yandex disables it while the campaign is "
                    "ARCHIVED. Resume the campaign first (e.g. via "
                    "`masters resume`) before changing its landing URL."
                )
        if status_hint:
            raise BrowserSessionError(f"{exc}{status_hint}") from exc
        raise


def _set_directs_helps(page: "Page", enabled: bool) -> None:
    """Check/uncheck the "Директ помогает" auto-recommendations checkbox.

    Clicks the visible label/toggle div, not the underlying
    ``<input type="checkbox">`` (see ``_DIRECT_HELPS_TOGGLE_LABEL_SELECTOR``'s
    docstring, issue #724): that input is visually-hidden, so
    ``.check()``/``.uncheck()`` — which require visibility — hang until
    timeout. Clicking the label is a no-op if the toggle is already in the
    requested state (unlike ``.check()``/``.uncheck()``, a plain ``.click()``
    would flip it either way), so this only clicks when
    ``_read_directs_helps`` reports the opposite of ``enabled``. Scoped to
    the "Директ помогает" toggle only — checking it reveals a second,
    nested checkbox ("Оптимизировать расширенные настройки...") that is out
    of scope for Этап A and must be left untouched.

    The pre-click read polls only while INCONCLUSIVE (``None``), not until
    it matches ``enabled`` (Codex, cycle-review round 2 of PR #731, fixing
    the round-1 fix): ``_wait_for_edit_form`` only guarantees the first
    headline slot has rendered, so a one-shot read right after can catch
    ``data-checked`` still unset/absent (``None``) while the toggle is
    ALREADY in the requested state — the same hydration race
    ``_read_until_matches``'s own docstring documents for every other field.
    Treating that transient ``None`` as "opposite of ``enabled``" would
    click the label and invert an already-correct state instead of leaving
    it alone. But polling for ``enabled`` specifically (via
    ``_read_until_matches``) is wrong once the read is settled: on a
    genuine state CHANGE, ``_read_directs_helps`` stably reports the
    opposite of ``enabled`` until the click below actually flips it —
    nothing makes it converge to ``enabled`` on its own — so that would
    burn the full ``_VERIFY_FIELD_READ_TIMEOUT_MS`` on every real toggle
    for no reason. Only ``None`` is a signal worth waiting out.

    If ``current`` is STILL ``None`` once the poll times out — not a
    transient hydration gap but a genuinely unreadable/absent
    ``data-checked`` for the whole window — this raises instead of
    clicking (issue #736, Codex round-3 finding on PR #731): clicking the
    visible label without knowing the toggle's real state can invert an
    already-correct value and commit that on a live Yandex account. A
    click is only safe once the pre-click state is actually known.
    """
    current = _read_until_matches(
        page, _read_directs_helps, None, matches=lambda actual, _exp: actual is not None
    )
    if current is None:
        raise BrowserSessionError(
            "Could not read the 'Директ помогает' checkbox's current state "
            "('Автоматически применять рекомендации') on the campaign edit "
            "page — its data-checked attribute stayed unreadable for "
            f"{_VERIFY_FIELD_READ_TIMEOUT_MS / 1000:.0f}s. Refusing to click "
            "blind, since that could invert an already-correct state. "
            "Yandex may have changed the page's markup, or the page is "
            "still hydrating — re-run with --headful to inspect the page."
        )
    if current is enabled:
        return

    label = page.locator(_DIRECT_HELPS_TOGGLE_LABEL_SELECTOR).first
    try:
        label.click()
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
    matching ``goal``'s ``PROMOTION_GOAL_INTERNAL_VALUES`` data-testid, then
    verifies the trigger button's own text now reflects the new selection —
    mirrors ``_suspend_or_resume``'s "never trust the click alone"
    convention.

    Matched by data-testid, not accessible-name text (issue #696
    re-investigation, 2026-08-04): Yandex now appends a description sentence
    and, for some rows, a "Рекомендуем" badge to each option's accessible
    name, so the previous ``get_by_role("option", name=label, exact=True)``
    — which required the WHOLE accessible name to equal the bare label — no
    longer matches anything and this failed on every live call. The
    data-testid suffix is stable regardless of that surrounding text.
    """
    label = PROMOTION_GOAL_CHOICES.get(goal)
    internal_value = PROMOTION_GOAL_INTERNAL_VALUES.get(goal)
    if label is None or internal_value is None:
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

    option_testid = _PROMOTION_GOAL_OPTION_TESTID_TEMPLATE.format(value=internal_value)
    option = page.locator(f'[data-testid="{option_testid}"]').first
    clicked = False
    try:
        option.click()
        clicked = True
    except PlaywrightError:
        clicked = False

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


def _set_goal_price(page: "Page", goal_price: float) -> None:
    """Fill the "Цель продвижения" block's target-price input.

    Only exists (see ``_GOAL_PRICE_INPUT_TESTID``) when the campaign's
    promotion goal is currently "max-clicks" — callers must call
    ``_set_promotion_goal(page, "max-clicks")`` first (or already have that
    goal saved) before this. Raises ``BrowserSessionError`` naming that
    requirement if the field is absent, rather than silently no-op'ing.

    Uses ``click()`` (not a one-shot ``is_visible()`` snapshot) to locate
    the field before filling — live testing (issue #696) found this
    section of the edit page can still be hydrating when
    ``_wait_for_edit_form`` returns (that wait only polls the first
    headline slot, near the top of the page), so an immediate
    ``is_visible()`` check can read "not there yet" as "field doesn't
    exist for this goal" and raise a false negative. ``click()``'s
    built-in actionability auto-wait (mirrors ``_set_weekly_budget``'s
    identical pattern for the same lower-page-position field) gives the
    section time to render before concluding the field is genuinely
    absent.
    """
    field = page.locator(_GOAL_PRICE_INPUT_TESTID).first
    try:
        field.click()
        field.fill(_format_goal_price(goal_price))
    except PlaywrightError as exc:
        raise BrowserSessionError(
            "Could not find or fill the target-price input for 'Цель "
            "продвижения' on the campaign edit page. This field only "
            "exists when the promotion goal is 'max-clicks' — pass "
            "--promotion-goal max-clicks together with --goal-price, or "
            "set it on the campaign first. It also requires the 'Цена "
            "перехода' strategy to be 'Средняя за неделю' (the default) "
            "rather than 'Без ограничений'. If the field should exist, "
            "Yandex may have changed the page's markup — re-run with "
            "--headful to inspect the page."
        ) from exc


def _set_target_action_price(page: "Page", goal_id: int, price: float) -> None:
    """Fill the "Целевые действия" table's price input for an EXISTING goal row.

    ``goal_id`` is Yandex Metrika's own numeric goal id (see
    ``_TARGET_ACTION_ROW_TESTID_TEMPLATE``'s docstring) — the goal must
    already be a row in the table (added via the page's own "Добавить"
    search popup, out of scope here); this only replaces its price, the
    same "no add/remove, only replace existing" convention as
    ``_set_repeating_value``/``_set_goal_price``. Raises
    ``BrowserSessionError`` naming that requirement if the row is absent,
    rather than silently no-op'ing.

    Uses ``click()`` (not a one-shot presence check) before filling, same
    reasoning as ``_set_goal_price``: this section sits even lower on the
    edit page and can still be hydrating when ``_wait_for_edit_form``
    returns.
    """
    testid = _TARGET_ACTION_PRICE_TESTID_TEMPLATE.format(
        category=_TARGET_ACTIONS_CATEGORY, goal_id=goal_id
    )
    field = page.locator(f'[data-testid="{testid}"]').first
    try:
        field.click()
        field.fill(_format_goal_price(price))
    except PlaywrightError as exc:
        raise BrowserSessionError(
            f"Could not find or fill the target-action price input for goal "
            f"{goal_id} in the 'Целевые действия' table on the campaign "
            "edit page. This table only exists when the promotion goal is "
            "'max-conversions', and only shows goals already added to it — "
            f"pass --promotion-goal max-conversions, and confirm goal "
            f"{goal_id} is already listed (add it first with "
            "--add-target-action, or via --headful). If the goal should "
            "already be there, Yandex may have changed the page's markup — "
            "re-run with --headful to inspect the page."
        ) from exc


def _add_target_action(page: "Page", goal_id: int, price: float) -> None:
    """Add a NEW row to the "Целевые действия" table for ``goal_id`` and set
    its price, via the table's own "Добавить" popup.

    ``goal_id`` must be one of the campaign's linked Metrika counter's goals
    that ISN'T already a row — Yandex's own popup list only ever offers
    those (see ``_TARGET_ACTIONS_CATEGORY``'s docstring), so a goal id that's
    already present or that doesn't belong to the counter simply never
    appears as a clickable option; both cases surface as the same "option
    never appeared" ``BrowserSessionError`` below, since this module has no
    separate way to tell them apart without guessing at Yandex's internal
    reasoning.

    The popup opens BELOW the table (not a modal) and does not auto-close
    after a click — same "open via retry, no need to close" shape as
    ``_click_and_wait_for_popup``, reimplemented here rather than reused
    because the target here is a per-goal-id OPTION inside the popup, not
    the popup's own container.

    A freshly clicked option renders with an EMPTY price input (confirmed
    live — not a page default), so this always fills one — there is no
    "add with no price" caller path; the CLI-boundary parse requires a
    price for exactly this reason (see ``_parse_add_target_action_options``).
    """
    add_button_testid = _TARGET_ACTION_ADD_BUTTON_TESTID_TEMPLATE.format(
        category=_TARGET_ACTIONS_CATEGORY
    )
    add_button = page.locator(f'[data-testid="{add_button_testid}"]').first
    option_testid = _TARGET_ACTION_ADD_OPTION_TESTID_TEMPLATE.format(
        category=_TARGET_ACTIONS_CATEGORY, goal_id=goal_id
    )
    option = page.locator(f'[data-testid="{option_testid}"]').first

    opened = False
    last_exc: Optional[Exception] = None
    for _ in range(_TARGET_ACTION_ADD_OPTION_MAX_ATTEMPTS):
        try:
            add_button.click()
        except PlaywrightError as exc:
            last_exc = exc
            continue
        try:
            option.wait_for(state="visible", timeout=_POPUP_APPEAR_TIMEOUT_MS)
            opened = True
            break
        except PlaywrightError as exc:
            last_exc = exc
            continue

    if not opened:
        raise BrowserSessionError(
            f"Could not find goal {goal_id} in the 'Добавить' target-action "
            "popup on the campaign edit page. This table only exists when "
            "the promotion goal is 'max-conversions' — pass "
            "--promotion-goal max-conversions if that's not already the "
            "case. Otherwise the popup only lists goals from the "
            "campaign's linked Metrika counter that AREN'T already in the "
            "table — confirm goal "
            f"{goal_id} belongs to that counter and isn't already listed "
            "(`masters targetactions get`), or Yandex may have changed the "
            "page's markup — re-run with --headful to inspect the page."
        ) from last_exc

    option.click()

    try:
        _set_target_action_price(page, goal_id, price)
    except BrowserSessionError as exc:
        raise BrowserSessionError(
            f"Added goal {goal_id} to the 'Целевые действия' table but "
            f"could not fill its price: {exc}"
        ) from exc


def _remove_target_action(page: "Page", goal_id: int) -> None:
    """Remove an EXISTING row from the "Целевые действия" table for
    ``goal_id``, via that row's own close button.

    Raises ``BrowserSessionError`` naming the requirement if the row is
    absent — mirrors ``_set_target_action_price``'s "must already be a row"
    guard rather than silently no-op'ing on an already-absent goal.
    """
    close_testid = _TARGET_ACTION_CLOSE_TESTID_TEMPLATE.format(
        category=_TARGET_ACTIONS_CATEGORY, goal_id=goal_id
    )
    close_button = page.locator(f'[data-testid="{close_testid}"]').first
    try:
        close_button.click()
    except PlaywrightError as exc:
        raise BrowserSessionError(
            f"Could not find or click the remove button for goal {goal_id} "
            "in the 'Целевые действия' table on the campaign edit page. "
            "This table only exists when the promotion goal is "
            "'max-conversions' — pass --promotion-goal max-conversions if "
            f"that's not already the case. Otherwise confirm goal {goal_id} "
            "is currently listed (`masters targetactions get`), or Yandex "
            "may have changed the page's markup — re-run with --headful to "
            "inspect the page."
        ) from exc


def _wait_for_audience_section(page: "Page") -> None:
    """Block until the "Аудитория" section's manual-targeting fields have
    actually rendered with server data, not just mounted their DOM shell.

    Issue #681 live recon (2026-08-04, campaign 713277109): every reader/
    writer below sits well below the first headline slot
    ``_wait_for_edit_form`` waits for, and — worse than a typical hydration
    race — the section's top-level preset trigger (see ``_GENDER_SELECT_
    TESTID``'s sibling comment) can render its DOM node with a STALE/
    default value ("Подобрать оптимальную") before the real server value
    ("Настроить вручную") arrives; a one-shot read at that point doesn't
    just see an empty tag list, it sees an ACTIVELY WRONG committed value —
    confirmed live: a read landing ~1.5s after ``_wait_for_edit_form``
    returned misreported a campaign with 112 audience tags as having
    ``[]``, while the SAME campaign read again after ~4s correctly showed
    all 112. This polls the "Пол" dropdown trigger (present, with campaign
    data, as soon as manual targeting has actually loaded) for non-empty
    text rather than trusting either presence-in-DOM or a fixed sleep.

    Does NOT distinguish "still hydrating" from "campaign is currently in
    'Подобрать оптимальную' auto mode, where this whole section is absent"
    — both look like "trigger never shows a non-empty label" from here.
    Callers that need every manual-targeting field (gender/age/devices/
    tags) should treat a timeout as "this section is not usable right now"
    rather than assuming a markup change; switching the top-level preset
    is out of scope for this module (see ``update_master``'s docstring).
    """
    trigger = page.locator(_GENDER_SELECT_TESTID).first

    def _has_label() -> bool:
        try:
            return bool(trigger.inner_text(timeout=500).strip())
        except PlaywrightError:
            return False

    if not _poll_until(page, _has_label, _AUDIENCE_SECTION_READY_TIMEOUT_MS):
        raise BrowserSessionError(
            "The 'Пол' dropdown on the campaign edit page never showed a "
            f"value within {_AUDIENCE_SECTION_READY_TIMEOUT_MS / 1000:.0f}s "
            "— either the 'Аудитория' section is still hydrating, the "
            "campaign is currently in 'Подобрать оптимальную' auto mode "
            "(where this section is absent), or Yandex changed the page's "
            "markup. Re-run with --headful to inspect the page."
        )

    # The gender trigger settling is NOT proof the (much larger, on a
    # campaign with 100+ tags) audience-tag list has also finished loading
    # — issue #681 live recon found these two sub-sections hydrate on
    # independent timers. Confirmed live: back-to-back runs against the
    # SAME campaign, both starting only after the gender trigger already
    # showed a non-empty label, read the tag count as 0 in one run and 112
    # in another — an outright wrong committed value, not merely "not
    # there yet". A single pair of equal consecutive counts 250ms apart
    # (``_poll_until``'s tick) is NOT enough to rule this out — a count
    # that reads 0 twice in a row before the real 112-tag payload has even
    # started arriving is "stable" by that test too. Live recon showed the
    # race resolving somewhere between 1.5s and 4s after the gender trigger
    # already had data, so this instead requires ``_AUDIENCE_TAG_STABLE_
    # STREAK`` consecutive equal counts spread across
    # ``_AUDIENCE_TAG_STABLE_WINDOW_MS`` (comfortably past that observed 4s
    # settle point) before treating the count as trustworthy.
    previous_count: "Optional[int]" = None
    stable_streak = 0

    def _tag_count_stable() -> bool:
        nonlocal previous_count, stable_streak
        current_count = len(_read_audience_tags(page))
        if previous_count is not None and current_count == previous_count:
            stable_streak += 1
        else:
            stable_streak = 0
        previous_count = current_count
        return stable_streak >= _AUDIENCE_TAG_STABLE_STREAK

    if not _poll_until(
        page, _tag_count_stable, _AUDIENCE_TAG_STABLE_WINDOW_MS, tick_ms=500
    ):
        raise BrowserSessionError(
            "The 'Интересы и поисковые запросы' tag count never settled "
            f"within {_AUDIENCE_TAG_STABLE_WINDOW_MS / 1000:.0f}s — the "
            "'Аудитория' section may still be hydrating, or Yandex changed "
            "the page's markup. Re-run with --headful to inspect the page."
        )


def _set_gender(page: "Page", gender: str) -> None:
    """Select ``gender`` (a key of ``GENDER_CHOICES``) in the "Пол" dropdown.

    Mirrors ``_set_promotion_goal``'s open-trigger/click-option/verify-label
    shape, matched by data-testid rather than accessible-name text for the
    same reason (issue #696 recon: option rows can carry extra description
    text beyond the bare label).
    """
    label = GENDER_CHOICES.get(gender)
    internal_value = _GENDER_INTERNAL_VALUES.get(gender)
    if label is None or internal_value is None:
        raise ValueError(
            f"Unknown gender {gender!r}; expected one of " f"{sorted(GENDER_CHOICES)}."
        )

    trigger = page.locator(_GENDER_SELECT_TESTID).first
    try:
        trigger.click()
    except PlaywrightError as exc:
        raise BrowserSessionError(
            "Could not find or open the 'Пол' dropdown on the campaign edit "
            "page — Yandex may have changed the page's markup. Re-run with "
            "--headful to inspect the page."
        ) from exc

    option = page.locator(
        _GENDER_OPTION_TESTID_TEMPLATE.format(value=internal_value)
    ).first
    try:
        option.click()
    except PlaywrightError as exc:
        raise BrowserSessionError(
            f"Could not find the {label!r} option in the 'Пол' dropdown on "
            "the campaign edit page — Yandex may have changed the page's "
            "markup. Re-run with --headful to inspect the page."
        ) from exc

    actual = _read_gender_label(page)
    if actual != label:
        raise BrowserSessionError(
            f"Clicked the {label!r} option for 'Пол', but the dropdown now "
            f"shows {actual!r}. The click may not have hit the right "
            "element — verify manually before retrying."
        )


def _read_gender_label(page: "Page") -> Optional[str]:
    """Read the "Пол" dropdown trigger's current selection text.

    Returns ``None`` if the trigger can't be found/read (inconclusive).
    """
    trigger = page.locator(_GENDER_SELECT_TESTID).first
    try:
        return trigger.inner_text().strip()
    except PlaywrightError:
        return None


def _set_age_bound(page: "Page", *, is_from: bool, age: Optional[int]) -> None:
    """Select ``age`` in the "от"/"до" age-bound dropdown.

    ``age`` must be a member of ``AGE_FROM_CHOICES``/``AGE_TO_CHOICES``
    matching ``is_from`` — ``None`` is only valid for the "до" bound
    (selects "Без ограничений", the ``AgeUnlimited`` option; there is no
    unlimited option on the "от" side). Verifies via the trigger's own
    post-click text, same "never trust the click alone" convention as
    ``_set_gender``/``_set_promotion_goal`` — but the trigger's DISPLAYED
    text does not simply echo the option testid (confirmed live: selecting
    ``AgeUnlimited`` renders the trigger text as "до 55+", not "Без
    ограничений", and a plain numeric bound renders as "от {age}"/"до
    {age}" with no suffix) — see ``_read_age_bound_label`` for the exact
    shape this compares against.
    """
    testid_template = _AGE_FROM_SELECT_TESTID if is_from else _AGE_TO_SELECT_TESTID
    option_template = (
        _AGE_FROM_OPTION_TESTID_TEMPLATE if is_from else _AGE_TO_OPTION_TESTID_TEMPLATE
    )
    label = "от" if is_from else "до"

    if age is None:
        if is_from:
            raise ValueError("age_from has no 'unlimited' option; pass an int.")
        option_value = "Unlimited"
    else:
        option_value = str(age)

    trigger = page.locator(testid_template).first
    try:
        trigger.click()
    except PlaywrightError as exc:
        raise BrowserSessionError(
            f"Could not find or open the '{label}' age dropdown on the "
            "campaign edit page — Yandex may have changed the page's "
            "markup. Re-run with --headful to inspect the page."
        ) from exc

    option = page.locator(option_template.format(value=option_value)).first
    try:
        option.click()
    except PlaywrightError as exc:
        raise BrowserSessionError(
            f"Could not find the {age!r} option in the '{label}' age "
            "dropdown on the campaign edit page — Yandex may have changed "
            "the page's markup. Re-run with --headful to inspect the page."
        ) from exc

    actual = _read_age_bound_label(page, is_from=is_from)
    expected = _format_age_bound_label(is_from=is_from, age=age)
    if actual != expected:
        raise BrowserSessionError(
            f"Clicked the {age!r} option for the '{label}' age dropdown, "
            f"but it now shows {actual!r} (expected {expected!r}). The "
            "click may not have hit the right element — verify manually "
            "before retrying."
        )


def _format_age_bound_label(*, is_from: bool, age: Optional[int]) -> str:
    """The age-bound trigger's expected display text for ``age``.

    Confirmed live: a plain numeric bound renders as "от {age}"/"до {age}"
    with no suffix; the "до" side's unlimited option renders as "до 55+"
    (the highest finite option, suffixed with "+") rather than echoing "Без
    ограничений" anywhere in the trigger text.
    """
    if age is None:
        highest_finite = AGE_TO_CHOICES[-2]
        return f"до {highest_finite}+"
    return f"{'от' if is_from else 'до'} {age}"


def _read_age_bound_label(page: "Page", *, is_from: bool) -> Optional[str]:
    """Read the "от"/"до" age-bound dropdown trigger's current text.

    Normalizes non-breaking spaces (``\\xa0``) to plain spaces — confirmed
    live the trigger renders "от" and the number with a non-breaking space
    between them (e.g. ``"от\\xa025"``), not a plain space, which would
    otherwise never equal ``_format_age_bound_label``'s plain-space
    expectation.

    Returns ``None`` if the trigger can't be found/read (inconclusive).
    """
    testid_template = _AGE_FROM_SELECT_TESTID if is_from else _AGE_TO_SELECT_TESTID
    trigger = page.locator(testid_template).first
    try:
        return trigger.inner_text().strip().replace("\xa0", " ")
    except PlaywrightError:
        return None


def _read_devices(page: "Page") -> Optional[Set[str]]:
    """Read the "Устройства пользователей" multi-select's currently checked
    device keys (a subset of ``DEVICE_OPTION_VALUES``).

    Opens the popup to read each checkbox's state (there is no summary
    attribute on the closed trigger beyond the free-text "Любые"/etc. label,
    which is not parsed here), then closes it again via Escape to leave the
    page state as this function found it. Returns ``None`` if the trigger or
    any checkbox can't be found/read (inconclusive).
    """
    trigger = page.locator(_DEVICE_SELECT_TESTID).first
    try:
        trigger.click()
    except PlaywrightError:
        return None

    selected: Set[str] = set()
    try:
        for value in DEVICE_OPTION_VALUES:
            option = page.locator(
                _DEVICE_OPTION_TESTID_TEMPLATE.format(value=value)
            ).first
            checked = option.get_attribute("aria-selected")
            if checked == "true":
                selected.add(value)
    except PlaywrightError:
        return None
    finally:
        with contextlib.suppress(PlaywrightError):
            page.keyboard.press("Escape")

    return selected


def _set_devices(page: "Page", devices: Set[str]) -> None:
    """Set the "Устройства пользователей" multi-select to exactly ``devices``.

    Each of the three checkboxes (``DEVICE_OPTION_VALUES``) is toggled only
    if its current state disagrees with the requested membership — mirrors
    ``_set_directs_helps``'s "click only flips, so only click when the
    current state is wrong" convention, applied per-checkbox here since this
    is a multi-select rather than a single toggle. Raises
    ``BrowserSessionError`` naming the field if ``devices`` is empty (Yandex
    requires at least one device type; there is no page-level way to select
    zero) or if any checkbox can't be found/read.
    """
    if not devices:
        raise BrowserSessionError(
            "Cannot set 'Устройства пользователей' to an empty set — at "
            "least one of smartphones/desktops/tablets must stay selected."
        )
    unknown = devices - set(DEVICE_OPTION_VALUES)
    if unknown:
        raise ValueError(
            f"Unknown device(s) {sorted(unknown)}; expected a subset of "
            f"{list(DEVICE_OPTION_VALUES)}."
        )

    trigger = page.locator(_DEVICE_SELECT_TESTID).first
    try:
        trigger.click()
    except PlaywrightError as exc:
        raise BrowserSessionError(
            "Could not find or open the 'Устройства пользователей' dropdown "
            "on the campaign edit page — Yandex may have changed the "
            "page's markup. Re-run with --headful to inspect the page."
        ) from exc

    try:
        for value in DEVICE_OPTION_VALUES:
            option = page.locator(
                _DEVICE_OPTION_TESTID_TEMPLATE.format(value=value)
            ).first
            currently_checked = option.get_attribute("aria-selected") == "true"
            should_be_checked = value in devices
            if currently_checked != should_be_checked:
                option.click()
    except PlaywrightError as exc:
        raise BrowserSessionError(
            "Could not toggle a device checkbox in the 'Устройства "
            "пользователей' dropdown on the campaign edit page — Yandex "
            "may have changed the page's markup. Re-run with --headful to "
            "inspect the page."
        ) from exc
    finally:
        with contextlib.suppress(PlaywrightError):
            page.keyboard.press("Escape")

    actual = _read_devices(page)
    if actual != devices:
        raise BrowserSessionError(
            f"Set 'Устройства пользователей' checkboxes, but re-reading "
            f"them now shows {sorted(actual) if actual is not None else None} "
            f"instead of the requested {sorted(devices)}. Verify manually "
            "before retrying."
        )


def _read_audience_tags(page: "Page") -> List[str]:
    """Read every current tag's display text in "Интересы и поисковые
    запросы" (both keyword and interest-category tags, in on-page order).

    Unlike ``_read_repeating_values``, this does not know the count ahead of
    time (the tag list is a variable-length, caller-grown array, not a fixed
    set of slots) — it reads index 0, 1, 2, ... until a slot's ``inner_text()``
    raises (meaning that index no longer exists), then stops.

    Waits for the tags-wrapper CONTAINER first (present regardless of tag
    count), not just a one-shot read of tag index 0 — the same hydration
    race ``_GOAL_PRICE_WAIT_TIMEOUT_MS`` guards against: ``_wait_for_edit_
    form`` only guarantees the first HEADLINE slot has rendered, and this
    section sits lower on the page. Without this wait, a call landing before
    the section hydrates would misread a campaign that genuinely HAS tags as
    having zero (confirmed live, issue #681 recon: a fresh navigation's
    first read raced this and returned ``[]`` against a campaign with 88
    tags).
    """
    try:
        page.locator(_AUDIENCE_TAG_WRAPPER_TESTID).first.wait_for(
            state="attached", timeout=_AUDIENCE_TAG_SUGGEST_TIMEOUT_MS
        )
    except PlaywrightError:
        return []

    tags: List[str] = []
    index = 0
    while True:
        selector = (
            f'[data-testid="{_AUDIENCE_TAG_TESTID_TEMPLATE.format(index=index)}"]'
        )
        try:
            text = page.locator(selector).first.inner_text(timeout=1_000).strip()
        except PlaywrightError:
            break
        if not text:
            break
        tags.append(text)
        index += 1
    return tags


def _add_audience_tag(page: "Page", text: str) -> None:
    """Add one tag (keyword or interest) to "Интересы и поисковые запросы"
    by typing ``text`` into the tag input and clicking the suggestion row
    whose FIRST LINE exactly matches it.

    Matched by the option row's first line of text, not by constructing a
    data-testid, and not by Playwright's ``get_by_role(..., name=...,
    exact=True)`` either — see the module-level comment above
    ``_AUDIENCE_TAG_LISTBOX_TESTID`` for why testid construction doesn't
    work here (interest-category suggestions carry an unpredictable
    numeric-id testid). ``exact=True`` accessible-name matching doesn't
    work either (confirmed live, issue #681): each option's accessible name
    is the WHOLE multi-line row — headline, a "Люди, которые ищут ..."
    description sentence, and a "Высокий охват" badge, all concatenated
    (e.g. ``"йога\\nЛюди, которые ищут «йога» в Поиске\\nВысокий охват"``)
    — the same class of "description text breaks an exact match" issue
    ``_set_promotion_goal``'s docstring documents for its own dropdown.
    This instead reads every option's ``inner_text()``, splits on the first
    newline, and clicks the first row whose FIRST LINE equals ``text``
    exactly (mirrors ``_trigger_shows_selection``'s "only the relevant
    line matters" convention). If more than one suggestion happens to
    share the same first line, the first is used (mirrors this module's
    general "first match wins" convention).

    Raises ``BrowserSessionError`` if the input can't be found/typed into,
    or if no suggestion whose first line matches appears within
    ``_AUDIENCE_TAG_SUGGEST_TIMEOUT_MS`` — the caller's requested tag simply
    has no matching keyword/interest on Yandex's side, which is a real
    outcome (not every free-text string is a valid tag), not a markup-drift
    signal.
    """
    # The text input does not exist in the DOM at all until the wrapper is
    # clicked once (confirmed live) — click the wrapper first to mount it,
    # then locate the now-mounted input. A plain wrapper.click() (Playwright
    # default: dead center of the element) is UNRELIABLE once a campaign has
    # many existing tags (confirmed live, issue #681, campaign 713277109
    # with 112 tags at the time): the wrapper's bounding box is the whole
    # flex-wrapped tag grid — over 2000px tall in that case — so its visual
    # center lands on some ARBITRARY tag mid-list, not empty space after the
    # last tag, and the newly-typed text can be inserted mid-list instead of
    # appended (confirmed live: a stray manual keystroke once landed between
    # two unrelated existing tags this way). Clicking near the wrapper's
    # bottom-right corner instead reliably lands after the last tag — this
    # DOM's flex-wrap layout fills left-to-right, top-to-bottom, so the tail
    # of the list is always near the bottom-right of the container.
    wrapper = page.locator(_AUDIENCE_TAG_WRAPPER_TESTID).first
    try:
        box = wrapper.bounding_box()
        if box is None:
            raise PlaywrightError("tags-wrapper has no bounding box")
        wrapper.click(position={"x": box["width"] - 5, "y": box["height"] - 5})
    except PlaywrightError as exc:
        raise BrowserSessionError(
            "Could not click the 'Интересы и поисковые запросы' tag list "
            "on the campaign edit page — Yandex may have changed the "
            "page's markup. Re-run with --headful to inspect the page."
        ) from exc

    field = page.locator(_AUDIENCE_TAG_INPUT_TESTID).first
    try:
        field.click()
        cleared = _clear_text_field(field)
    except PlaywrightError as exc:
        raise BrowserSessionError(
            "Could not click the 'Интересы и поисковые запросы' tag input "
            "on the campaign edit page — Yandex may have changed the "
            "page's markup. Re-run with --headful to inspect the page."
        ) from exc
    if not cleared:
        raise BrowserSessionError(
            "Could not clear the 'Интересы и поисковые запросы' tag input "
            "before typing. This usually means Playwright is older than "
            "1.44 (the version that added the 'ControlOrMeta' modifier) — "
            "upgrade with 'pip install -U playwright'."
        )
    try:
        field.type(text)
    except PlaywrightError as exc:
        raise BrowserSessionError(
            f"Could not type {text!r} into the 'Интересы и поисковые "
            "запросы' tag input on the campaign edit page — Yandex may "
            "have changed the page's markup. Re-run with --headful to "
            "inspect the page."
        ) from exc

    listbox = page.locator(_AUDIENCE_TAG_LISTBOX_TESTID).first
    options = listbox.get_by_role("option")

    def _find_matching_option():
        try:
            count = options.count()
        except PlaywrightError:
            return None
        for i in range(count):
            option = options.nth(i)
            try:
                first_line = option.inner_text(timeout=500).split("\n", 1)[0]
            except PlaywrightError:
                continue
            if first_line == text:
                return option
        return None

    deadline = _clock.now() + _AUDIENCE_TAG_SUGGEST_TIMEOUT_MS / 1000
    match = None
    while _clock.now() < deadline:
        match = _find_matching_option()
        if match is not None:
            break
        page.wait_for_timeout(250)

    if match is None:
        with contextlib.suppress(PlaywrightError):
            page.keyboard.press("Escape")
        raise BrowserSessionError(
            f"No suggestion exactly matching {text!r} appeared in the "
            "'Интересы и поисковые запросы' autocomplete within "
            f"{_AUDIENCE_TAG_SUGGEST_TIMEOUT_MS / 1000:.0f}s — this is not "
            "a valid keyword or interest on Yandex's side, or its "
            "suggestion label differs from the exact text passed. Re-run "
            "with --headful to see the actual suggestion list."
        )

    try:
        match.click()
    except PlaywrightError as exc:
        raise BrowserSessionError(
            f"Found a matching suggestion for {text!r} in the 'Интересы и "
            "поисковые запросы' autocomplete but could not click it — "
            "Yandex may have changed the page's markup. Re-run with "
            "--headful to inspect the page."
        ) from exc


def _remove_audience_tag(page: "Page", index: int) -> None:
    """Remove the tag currently at position ``index`` in "Интересы и
    поисковые запросы" by clicking its close button.

    ``index`` must reference an EXISTING tag (see ``_read_audience_tags``) —
    this does not resolve tags by text, since two tags can legitimately
    share display text (e.g. the same word as both a keyword and an
    interest-category suggestion happen to render identically) and only a
    position is guaranteed to identify one specific tag.
    """
    selector = (
        f'[data-testid="{_AUDIENCE_TAG_CLOSE_TESTID_TEMPLATE.format(index=index)}"]'
    )
    try:
        page.locator(selector).first.click()
    except PlaywrightError as exc:
        raise BrowserSessionError(
            f"Could not remove the tag at position {index + 1} via "
            f"{selector!r} on the campaign edit page — Yandex may have "
            "changed the page's markup, or that position no longer exists. "
            "Re-run with --headful to inspect the page."
        ) from exc


def _read_target_actions(page: "Page") -> List[Dict[str, Any]]:
    """Read the "Целевые действия" table's current rows.

    Returns a list of ``{"GoalId": int, "Name": str, "Price": Optional[float]}``
    — one entry per goal row currently in the table (see
    ``_TARGET_ACTION_ROW_TESTID_TEMPLATE``'s docstring). Returns ``[]`` both
    when the section can't be found/read AND when it legitimately does not
    exist for the campaign's current promotion goal (mirrors
    ``_read_goal_price``'s "inconclusive/absent" convention) — callers that
    need to distinguish "no goals configured" from "section not on this
    page"/"row scan failed" should use ``_read_target_actions_or_none``
    instead (used by ``_verify_saved``'s add/remove verification, where that
    distinction is safety-critical — see its docstring).

    Goal ids are discovered via ``_read_testid_suffixes`` on the row-testid
    prefix (same convention as ``_read_image_content_ids``), skipping the
    ``.PriceInput``/``.CloseButton`` children that share the prefix. Each
    row's label is read via a compound CSS selector scoping ``[data-testid=
    "Text"]`` (not itself unique — every row shares that testid) to that
    ONE row's own full testid, rather than a chained sub-locator — matching
    every other reader in this module's "select directly off ``page``" rule
    (see ``_read_testid_suffixes``'s docstring) while still disambiguating
    between rows, which a bare prefix scan cannot do for a repeated child
    testid.
    """
    rows = _read_target_actions_or_none(page)
    return [] if rows is None else rows


def _read_target_actions_or_none(page: "Page") -> Optional[List[Dict[str, Any]]]:
    """Same read as ``_read_target_actions``, but returns ``None`` — distinct
    from ``[]`` — the moment ANY step of the row scan fails, rather than
    only on the section-visibility check.

    ``_read_target_actions`` itself collapses every failure into ``[]`` —
    a legitimate simplification for its read-only callers
    (``fetch_master_target_actions``, ``target_action_prices``
    verification), for whom "couldn't read" and "genuinely empty" are both
    handled the same way (retry, then report what was last seen).
    ``--add-target-action``/``--remove-target-action`` verification cannot
    afford that collapse: a removed goal reported "absent" from a read that
    never actually saw the table would silently confirm a removal that may
    not have happened server-side — see ``_verify_saved``.

    Deliberately does NOT delegate row enumeration to
    ``_read_testid_suffixes`` (unlike ``_read_target_actions``'s first cut,
    Codex adversarial review of #717 round 2): that helper does its own
    independent ``page.locator(...).count()`` call and swallows a failure
    there into ``[]`` — an earlier "probe" ``count()`` call in this function
    verifying the SAME locator succeeds is not a guarantee the helper's own
    later, separate call will too (a row can detach between the two), so a
    probe-then-delegate shape still lets a mid-scan failure collapse into
    "confirmed empty". Enumerating inline here, with every locator
    read wrapped in its own failure check, is the only way a raised
    ``PlaywrightError`` at any point reliably becomes this function's own
    ``None`` rather than someone else's swallowed ``[]``.
    """
    section = page.locator(_TARGET_ACTIONS_SECTION_TESTID).first
    try:
        section.wait_for(state="visible", timeout=_TARGET_ACTION_WAIT_TIMEOUT_MS)
    except PlaywrightError:
        return None

    prefix = f"TargetActions.{_TARGET_ACTIONS_CATEGORY}."
    try:
        row_elements = page.locator(f'[data-testid^="{prefix}"]')
        count = row_elements.count()
        raw_testids = [
            row_elements.nth(i).get_attribute("data-testid") for i in range(count)
        ]
    except PlaywrightError:
        return None

    goal_ids: List[int] = []
    for testid in raw_testids:
        if not testid or not testid.startswith(prefix):
            continue
        suffix = testid[len(prefix) :]
        if suffix.endswith((".PriceInput", ".CloseButton")):
            continue
        try:
            goal_ids.append(int(suffix))
        except ValueError:
            continue

    results: List[Dict[str, Any]] = []
    for goal_id in goal_ids:
        row_testid = _TARGET_ACTION_ROW_TESTID_TEMPLATE.format(
            category=_TARGET_ACTIONS_CATEGORY, goal_id=goal_id
        )
        name_selector = f'[data-testid="{row_testid}"] [data-testid="Text"]'
        try:
            texts = page.locator(name_selector).all_inner_texts()
        except PlaywrightError:
            # Unlike the row-enumeration failure above, a raise HERE is not
            # ambiguous about whether the row exists — its testid was just
            # found in the DOM-order scan above, so it does. But its PRICE
            # is exactly the field `_add_remove_match`/`_target_action_prices_match`
            # compare against the requested value — a swallowed failure
            # here would silently read as "price field is empty", which
            # `_target_action_price_matches` (never matching ``None``)
            # would then report as a genuine save mismatch rather than the
            # transient read failure it actually is. Propagate ``None`` for
            # the whole read rather than guess at this one row's state.
            return None
        name = texts[0].strip() if texts else None

        price_testid = _TARGET_ACTION_PRICE_TESTID_TEMPLATE.format(
            category=_TARGET_ACTIONS_CATEGORY, goal_id=goal_id
        )
        try:
            raw_price = page.locator(
                f'[data-testid="{price_testid}"]'
            ).first.input_value()
        except PlaywrightError:
            return None
        price = _parse_target_action_price(raw_price)

        results.append({"GoalId": goal_id, "Name": name, "Price": price})

    return results


def _wait_for_target_actions_settled(page: "Page") -> bool:
    """Block until the "Целевые действия" table's row count has stopped
    changing, so a caller's subsequent read is a settled snapshot rather
    than a mid-hydration one.

    Issue #750 (Codex round-3 finding on #749): rounds 1-2 hardened
    ``_read_target_actions_or_none`` against every failure mode that
    surfaces as a raised ``PlaywrightError`` — but live recon against
    campaign 713277109 confirmed the row-testid locator's ``.count()`` (and
    even ``TargetActionsSection`` itself) can genuinely, without ever
    raising, report a transient EMPTY state for over a second while the
    real row set is still arriving. A caller trusting that read would
    misreport a genuinely-present goal as removed — the same "truthful but
    partial snapshot" class of race ``_wait_for_audience_section``'s tag-
    count settling loop exists to close for the "Аудитория" section, and
    the fix here is the identical shape: require
    ``_TARGET_ACTION_STABLE_STREAK`` consecutive equal row-count reads,
    ``_TARGET_ACTION_STABLE_TICK_MS`` apart, before treating the count as
    trustworthy, rather than a single read or a bare visibility check.

    A raised ``PlaywrightError`` mid-poll (the section detaching between
    ticks) is treated the same as "count changed" — it resets the streak
    rather than propagating, since ``_read_target_actions_or_none`` (the
    caller's actual read, right after this returns) already has its own
    ``None``-on-failure handling; this function only needs to decide when
    a *count* has stopped moving, not to be the failure-reporting layer
    itself.

    Returns ``True`` once the count has settled, ``False`` on timeout —
    callers treat a timeout as "could not confirm settling" and let their
    own read-retry loop's existing failure/mismatch handling take over
    (mirroring how ``_read_target_actions_or_none`` itself degrades),
    rather than raising here and pre-empting that reporting.
    """
    prefix = f"TargetActions.{_TARGET_ACTIONS_CATEGORY}."
    row_locator = page.locator(f'[data-testid^="{prefix}"]')
    previous_count: "Optional[int]" = None
    stable_streak = 0

    def _row_count_stable() -> bool:
        nonlocal previous_count, stable_streak
        current_count = row_locator.count()
        if previous_count is not None and current_count == previous_count:
            stable_streak += 1
        else:
            stable_streak = 0
        previous_count = current_count
        return stable_streak >= _TARGET_ACTION_STABLE_STREAK

    return _poll_until(
        page,
        _row_count_stable,
        _TARGET_ACTION_SETTLE_TIMEOUT_MS,
        tick_ms=_TARGET_ACTION_STABLE_TICK_MS,
    )


def _parse_target_action_price(raw: str) -> Optional[float]:
    """Parse a target-action price input's raw string value, same
    normalization as ``_goal_price_matches`` (comma decimal separator,
    possible thin-space grouping). Returns ``None`` for an empty/unparseable
    value rather than 0.0 — a goal row with no price set yet is a distinct
    state from a price of zero."""
    normalized = raw.strip().replace(",", ".").replace("\xa0", "")
    if not normalized:
        return None
    try:
        return float(normalized)
    except ValueError:
        return None


def _target_action_price_matches(expected: float, actual: Optional[float]) -> bool:
    """Compare a requested ``--target-action-price`` against the page's
    re-read value, mirroring ``_goal_price_matches``."""
    return actual is not None and actual == expected


def _format_goal_price(goal_price: float) -> str:
    """Render ``goal_price`` the way ``--weekly-budget``-style numeric CLI
    fields are rendered: an integer value with no trailing ``.0`` (the
    field's own input mask accepts a plain integer or decimal string —
    confirmed live it displays a comma, not a dot, as the decimal
    separator, but ``fill()`` accepts either)."""
    if isinstance(goal_price, float) and goal_price.is_integer():
        return str(int(goal_price))
    return str(goal_price)


def _click_draft_terminal_button(
    page: "Page", campaign_id: int, *, launch: bool
) -> None:
    """Click a DRAFT edit page's save-as-draft/launch button (issue #668).

    A DRAFT campaign's edit page has no "Сохранить кампанию" button at all
    — only ``CampaignFormControls.saveDraft.button`` ("Сохранить как
    черновик") and ``CampaignFormControls.save.button`` ("Запустить
    кампанию", which PUBLISHES the campaign — a real, no-rollback mutation).
    Matched by ``data-testid``, not accessible-name text, because the same
    testid SUFFIX (``save.button``) carries a different label — and a
    different consequence — depending on whether the page is DRAFT or not
    (see the constants' own comment). ``launch`` defaults to ``False`` at
    every call site in this module; only an explicit ``masters update
    --launch`` sets it, mirroring ``create_master``/``copy_master``'s
    draft-preserving defaults.

    **Live-confirmed 2026-08-02 (real mutation against campaign 713231614,
    reverted immediately after observing this):** unlike the non-DRAFT
    "Сохранить кампанию" button, this click redirects the page away from
    ``/edit/`` to the campaign's overview page (``page.url`` becomes
    ``/wizard/campaigns/{id}/...``, no longer ``/edit/``) — and NOT
    instantly; ~5s elapsed before the redirect completed in this recon. The
    edit itself WAS actually saved server-side (confirmed by reloading
    ``/edit/`` afterwards), but ``update_master``'s original ``_click_save``
    → immediate ``_verify_saved`` reload raced this redirect and read a
    transitional state, producing a false "did not save as requested"
    error. This function therefore waits for ``page.url`` to actually leave
    ``/edit/`` before returning, so the caller's subsequent re-navigation to
    the edit URL lands after Yandex's own redirect has settled, not during
    it — same "poll page.url until it actually changes" pattern
    ``copy_master`` already uses for its own post-click redirect.

    **Live-confirmed 2026-08-04 (issue #704 recon, campaigns 713271284/
    713271498):** clicking immediately after ``_wait_for_edit_form`` returns
    (which only waits for the first headline slot to render) can silently
    no-op — the click lands before later-loading page sections (the
    "Продвижение организации"/preview panels, confirmed live via screenshot)
    finish hydrating, and the button's own handler isn't wired up yet. An
    earlier version of this function retried the click once, purely on
    elapsed time, if no redirect had happened yet — cycle-review PR #711
    (Codex) proved this structurally double-submits the no-rollback
    save/launch click: ANY threshold shorter than the full redirect-wait
    window is, by construction, still reachable by a healthy click whose
    redirect simply lands a bit later than usual (proven live for both a
    4s and a 12s threshold against this file's own documented ~5-10s
    redirect range) — a time-only retry cannot distinguish "stuck" from
    "still in flight" without a positive failure signal this page does not
    expose. So this function clicks exactly once and fails loudly if
    Yandex never redirects, rather than risk a silent double mutation —
    the hydration race from the #704 recon now surfaces as an explicit
    "verify manually" error instead of an auto-retried click.
    """
    selector = (
        _DRAFT_LAUNCH_BUTTON_TESTID if launch else _DRAFT_SAVE_DRAFT_BUTTON_TESTID
    )
    button_label = _LAUNCH_BUTTON_TEXT if launch else _SAVE_DRAFT_BUTTON_TEXT
    handle = page.locator(selector).first
    try:
        handle.click()
    except PlaywrightError as exc:
        raise BrowserSessionError(
            f"Could not find the {button_label!r} button on the DRAFT edit "
            f"page for campaign {campaign_id} — Yandex may have changed "
            "the page's markup. Re-run with --headful to inspect the page."
        ) from exc

    deadline = _clock.now() + _DRAFT_SAVE_REDIRECT_TIMEOUT_MS / 1000
    while _clock.now() < deadline:
        if "/edit/" not in page.url:
            return
        page.wait_for_timeout(250)

    raise BrowserSessionError(
        f"Clicked {button_label!r} for DRAFT campaign {campaign_id}, but "
        "Yandex did not redirect away from the edit page within "
        f"{_DRAFT_SAVE_REDIRECT_TIMEOUT_MS / 1000:.0f}s — the edit may not "
        "have saved (or the click landed before the page finished "
        "hydrating and silently no-op'd — issue #704 recon). Reload the "
        "edit page and verify manually before retrying."
    )


def _is_draft_edit_page(page: "Page") -> bool:
    """True if the edit page currently open is a DRAFT campaign's.

    Detected by the presence of ``CampaignFormControls.saveDraft.button`` —
    the one control that exists ONLY on a DRAFT edit page (issue #668,
    confirmed live: a non-DRAFT edit page has no draft-save button at all,
    only "Сохранить кампанию"). Detecting via the very button
    ``_click_draft_terminal_button`` would click keeps this check and that
    click from ever disagreeing about what "DRAFT" means here.
    """
    try:
        return page.locator(_DRAFT_SAVE_DRAFT_BUTTON_TESTID).first.count() > 0
    except PlaywrightError:
        return False


def _draft_status_terminal_state(page: "Page") -> "Optional[str]":
    """Predicate for ``_wait_for_draft_status``'s poll loop.

    Returns ``"draft"`` once the DRAFT-only save-as-draft marker is
    present, ``"non_draft"`` once the exact, visible non-DRAFT "Сохранить
    кампанию" button is present, or ``None`` to keep polling. The two
    outcomes are mutually exclusive on a real page (issue #668) — whichever
    appears first is the answer.
    """
    if page.locator(_DRAFT_SAVE_DRAFT_BUTTON_TESTID).first.count() > 0:
        return "draft"
    save_button = page.get_by_role("button", name=_SAVE_BUTTON_TEXT, exact=True)
    for i in range(save_button.count()):
        if save_button.nth(i).is_visible():
            return "non_draft"
    return None


def _wait_for_draft_status(page: "Page", campaign_id: int) -> bool:
    """Block until the edit page's DRAFT-vs-non-DRAFT terminal save control
    has actually rendered, then return whether it's a DRAFT page.

    Issue #726 (Codex-caught gap in the initial fix, cycle-review round 2):
    ``_wait_for_edit_form`` only waits for the first headline slot
    (``_EDIT_FORM_READY_TESTID``) — it guarantees nothing about either
    terminal save control's own mount time. A caller that read
    ``_is_draft_edit_page`` immediately after ``_wait_for_edit_form``
    returned could still misclassify a DRAFT campaign whose headline
    happens to render before ``CampaignFormControls.saveDraft.button``
    does — the original #726 diagnosis confirmed a present-then-absent
    flap, but never ruled out this absent-then-present ordering. Polling
    for either terminal marker (mutually exclusive per
    ``_draft_status_terminal_state``) closes both directions at once,
    instead of trusting a single point-in-time read.

    Raises ``BrowserSessionError`` on timeout — same "surface a specific,
    actionable error rather than silently guessing" convention as
    ``_wait_for_edit_form``/``_wait_for_images_editor``.
    """
    state = _poll_until_terminal(
        page,
        lambda: _draft_status_terminal_state(page),
        _EDIT_FORM_READY_TIMEOUT_MS,
    )
    if state is None:
        # ARCHIVED campaigns render NO terminal save control at all on the
        # edit page (issue #761 recon) — this timeout is also what an
        # ARCHIVED campaign hits, since neither marker this function polls
        # for ever appears for one. ``_read_status_text`` is a best-effort
        # hint for the error message only (it may or may not read the edit
        # page reliably — unverified live) — it does NOT gate anything
        # before this timeout already fired, so it cannot misclassify an
        # ordinary campaign the way a pre-mutation field-shaped guard could
        # (issue #761 cycle-review round 2, Codex: a Clear-button proxy
        # guard false-positived on both an unfocused field and an empty
        # URL).
        status_hint = ""
        with contextlib.suppress(PlaywrightError):
            if _read_status_text(page) == "ARCHIVED":
                status_hint = (
                    f" Campaign {campaign_id} is ARCHIVED — its edit page "
                    "has no save control at all while archived. Resume "
                    "the campaign first (e.g. via `masters resume`) "
                    "before updating it."
                )
        raise BrowserSessionError(
            "Neither the DRAFT save-as-draft button nor the non-DRAFT "
            f"'{_SAVE_BUTTON_TEXT}' button appeared on the edit page for "
            f"campaign {campaign_id} within "
            f"{_EDIT_FORM_READY_TIMEOUT_MS / 1000:.0f}s.{status_hint} "
            "Otherwise Yandex may have changed the page's markup — re-run "
            "with --headful to inspect the page."
        )
    return state == "draft"


def _click_save(
    page: "Page", campaign_id: int, *, is_draft: bool, launch: bool = False
) -> None:
    """Click the edit page's save button — "Сохранить кампанию" on a
    non-DRAFT campaign, or the DRAFT-specific save-as-draft/launch button.

    Confirmed live: the whole non-DRAFT edit page is one form with exactly
    one save button at the bottom (see module docstring) — there is no
    per-section save to target instead. A DRAFT campaign's edit page has a
    DIFFERENT pair of terminal buttons entirely (issue #668) — see
    ``_click_draft_terminal_button``.

    ``is_draft`` MUST be the caller's own ``_is_draft_edit_page`` reading,
    taken once right after ``_wait_for_edit_form`` returns — NOT re-derived
    here. Issue #726 (live-confirmed): the DRAFT-terminal marker
    (``_DRAFT_SAVE_DRAFT_BUTTON_TESTID``) can transiently disappear from the
    DOM mid-hydration and reappear ~1.5s later, so a fresh
    ``_is_draft_edit_page(page)`` call made immediately before this click
    can read ``False`` for a page that was (and still is) DRAFT — sending a
    DRAFT campaign down the non-DRAFT "Сохранить кампанию" path, which
    doesn't exist on that page and raises. Every caller already determines
    ``is_draft`` before doing any of the mutations that precede this click,
    for the same "read it while the page still reflects what's about to
    happen" reason ``update_master`` documents at its own call site.
    """
    if is_draft:
        _click_draft_terminal_button(page, campaign_id, launch=launch)
        return

    # The save button sits at the very bottom of a long, lazily-mounted
    # page — confirmed live (issue #681) it is simply ABSENT from the DOM
    # (locator count 0, not just not-yet-visible) when the viewport is
    # still scrolled to wherever an earlier mutation (e.g. adding an
    # audience tag deep in a 100+-tag list) left it. Every other mutation
    # this module supports happens to leave the viewport high enough on
    # the page for the button to already be mounted by the time this runs,
    # but that's incidental, not guaranteed — scrolling to the bottom
    # first makes this reliable regardless of what ran before it.
    # mouse.wheel rather than keyboard.press("End") — the latter depends on
    # focus being on the document body/a scrollable ancestor, which is not
    # guaranteed here (e.g. right after typing into the audience-tag
    # contenteditable input, focus can still be inside that field). Retried
    # (not a single scroll+check) because a single wheel event's resulting
    # mount isn't instantaneous — confirmed live (issue #681) a one-shot
    # 500ms wait after the wheel event was sometimes enough and sometimes
    # not for the exact same page state, so this re-scrolls on every tick
    # rather than trusting one wait to be long enough.
    # get_by_role scopes to the actual <button> element (exact accessible
    # name), not any ancestor container whose text merely contains this
    # substring — see the cycle-review finding this fixed.
    save_button = page.get_by_role("button", name=_SAVE_BUTTON_TEXT, exact=True)

    def _find_visible_save_button():
        page.mouse.wheel(0, 20_000)
        try:
            count = save_button.count()
        except PlaywrightError:
            return None
        for i in range(count):
            handle = save_button.nth(i)
            try:
                if handle.is_visible():
                    return handle
            except PlaywrightError:
                continue
        return None

    deadline = _clock.now() + _AUDIENCE_SECTION_READY_TIMEOUT_MS / 1000
    while _clock.now() < deadline:
        handle = _find_visible_save_button()
        if handle is not None:
            try:
                handle.click()
                return
            except PlaywrightError:
                pass
        page.wait_for_timeout(300)

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

    Reads the visible toggle div's ``data-checked`` attribute, not the
    underlying ``<input type="checkbox">``'s ``is_checked()`` (issue #724):
    the input is visually-hidden, and while ``is_checked()`` itself doesn't
    require visibility, keeping the read path on the same element
    ``_set_directs_helps`` clicks avoids the two ever silently disagreeing
    if Yandex's toggle implementation changes. Returns ``None`` if the field
    can't be found/read, OR if ``data-checked`` holds neither "true" nor
    "false" (inconclusive either way).
    """
    toggle = page.locator(_DIRECT_HELPS_TOGGLE_DIV_SELECTOR).first
    try:
        value = toggle.get_attribute("data-checked")
    except PlaywrightError:
        return None
    if value == "true":
        return True
    if value == "false":
        return False
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


def _read_goal_price(page: "Page") -> Optional[str]:
    """Read the "Цель продвижения" block's target-price input value.

    Returns ``None`` both when the field can't be found/read AND when it
    legitimately does not exist for the campaign's current promotion goal
    (see ``_GOAL_PRICE_INPUT_TESTID``) — either way, the caller treats
    ``None`` as "verification inconclusive", never as a specific price.

    Uses ``wait_for(state="visible")`` (see ``_GOAL_PRICE_WAIT_TIMEOUT_MS``)
    rather than a one-shot ``is_visible()`` snapshot, for the same reason
    ``_set_goal_price`` switched to ``click()``: this section of the edit
    page can still be hydrating right after ``_wait_for_edit_form``
    returns, and an immediate check can misread "not rendered yet" as
    "field doesn't exist for this goal".
    """
    field = page.locator(_GOAL_PRICE_INPUT_TESTID).first
    try:
        field.wait_for(state="visible", timeout=_GOAL_PRICE_WAIT_TIMEOUT_MS)
        return field.input_value()
    except PlaywrightError:
        return None


def _goal_price_matches(expected: float, actual: Optional[str]) -> bool:
    """Compare a requested ``--goal-price`` against the page's re-read value.

    The field's own input mask renders a comma as the decimal separator
    (confirmed live) and may pad/trim trailing zeros, so this compares
    parsed numeric values rather than raw strings — mirrors
    ``_read_weekly_budget``'s digit-only normalization for the same class
    of "Yandex's own formatting differs from what we typed" mismatch.
    """
    if actual is None:
        return False
    normalized = actual.strip().replace(",", ".").replace("\xa0", "")
    try:
        return float(normalized) == float(expected)
    except ValueError:
        return False


def _read_campaign_name(page: "Page") -> Optional[str]:
    """Read the edit page header's current campaign name.

    Returns ``None`` if the header can't be found/read (inconclusive).
    """
    header = page.locator(_NAME_HEADER_SELECTOR).first
    try:
        return header.inner_text().strip()
    except PlaywrightError:
        return None


def _verify_repeating_value_mismatches(
    page: "Page",
    *,
    testid_template: str,
    slot_count: int,
    label: str,
    requested: Optional[Dict[int, str]],
) -> List[str]:
    """Re-read only the slots ``update_master`` was asked to change and
    report any that don't match — unlike ``_repeating_values_mismatches``
    (the create-page check), slots NOT in ``requested`` are never flagged:
    leftover variants are the normal, intentional state of a partial update,
    not evidence something went wrong (issue #665).
    """
    if not requested:
        return []
    actual = _read_repeating_values(page, testid_template, slot_count)
    mismatches = []
    for index, expected in requested.items():
        current = actual[index] if index < len(actual) else ""
        if current != expected:
            mismatches.append(
                f"{label} slot {index + 1}: expected {expected!r}, page now "
                f"shows {current!r}"
            )
    return mismatches


def _read_until_matches(
    page: "Page",
    reader: "Callable[[Page], Any]",
    expected: Any,
    *,
    timeout_ms: int = _VERIFY_FIELD_READ_TIMEOUT_MS,
    matches: "Optional[Callable[[Any, Any], bool]]" = None,
) -> Any:
    """Retry ``reader(page)`` until it matches ``expected`` or ``timeout_ms`` elapses.

    ``_wait_for_edit_form`` only guarantees the first headline slot has
    rendered — a one-shot call to ``_read_weekly_budget``/
    ``_read_directs_helps``/``_read_promotion_goal_label``/
    ``_read_campaign_name``/``_read_goal_price``/``_read_target_actions``
    right after it can catch that field still showing its pre-reload value
    while the rest of the form is still hydrating (issue #706/#716, same
    race ``_read_goal_price`` was first hardened against in issue #696).
    Returns the LAST value read — on a genuine mismatch (Yandex actually
    rejected the save) that is the settled, correct-but-wrong value, so
    ``_verify_saved`` still reports it accurately once the retries are
    exhausted.

    ``matches`` defaults to ``==`` but accepts a predicate for callers whose
    "did it match" comparison isn't plain equality (e.g. ``_goal_price_matches``'s
    comma/dot normalization, or ``target_action_prices``' per-goal lookup into
    the list ``_read_target_actions`` returns).
    """
    is_match = matches or (lambda actual, exp: actual == exp)
    last: Any = None
    deadline = _clock.now() + timeout_ms / 1000
    while True:
        last = reader(page)
        if is_match(last, expected) or _clock.now() >= deadline:
            return last
        page.wait_for_timeout(250)


def _verify_saved(
    page: "Page",
    campaign_id: int,
    *,
    weekly_budget: Optional[int],
    promotion_goal: Optional[str],
    directs_helps: Optional[bool],
    name: Optional[str] = None,
    landing_url: Optional[str] = None,
    tracking_params: Optional[str] = None,
    headlines: Optional[Dict[int, str]] = None,
    texts: Optional[Dict[int, str]] = None,
    images_before_ids: Optional[List[str]] = None,
    images_replaced_ids: Optional[Set[str]] = None,
    goal_price: Optional[float] = None,
    target_action_prices: Optional[Dict[int, float]] = None,
    add_target_actions: Optional[Dict[int, float]] = None,
    remove_target_action_goal_ids: Optional[List[int]] = None,
    gender: Optional[str] = None,
    age_from_requested: bool = False,
    age_from: Optional[int] = None,
    age_to_requested: bool = False,
    age_to: Optional[int] = None,
    devices: Optional[Set[str]] = None,
    audience_tags_before: Optional[List[str]] = None,
    add_audience_tags: Optional[List[str]] = None,
    remove_audience_tag_count: int = 0,
    clicked_button_label: str = _SAVE_BUTTON_TEXT,
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
    _audience_touched = (
        gender is not None
        or age_from_requested
        or age_to_requested
        or devices is not None
        or add_audience_tags
        or remove_audience_tag_count
    )
    if _audience_touched:
        # Confirmed live (issue #681): reloading immediately after clicking
        # 'Сохранить кампанию' can race the server-side commit for this
        # section specifically — a reload landing too soon reads back the
        # PRE-save value even though the save demonstrably did take effect
        # (a separate, later `masters audience get` call against the same
        # campaign correctly showed the new value). This race was observed
        # to persist past a 2s delay on a campaign with 100+ audience tags
        # (a much heavier page than this module's other test campaigns) —
        # 5s gives more headroom, though the underlying race is still not
        # fully closed (see this function's own docstring "false negative"
        # note and issue #681's follow-up). No other field this module
        # verifies has shown this same race, so the delay is scoped to
        # audience-touching saves only rather than slowing down every
        # update_master call.
        page.wait_for_timeout(5_000)

    url = WIZARD_EDIT_URL.format(campaign_id=campaign_id)
    page.goto(url, wait_until="commit")
    assert_not_captcha(page.content())
    assert_authenticated(page.content())
    _wait_for_edit_form(page, campaign_id)
    if _audience_touched:
        _wait_for_audience_section(page)

    checks = [
        ("weekly_budget", weekly_budget, _read_weekly_budget),
        ("directs_helps", directs_helps, _read_directs_helps),
        (
            "promotion_goal",
            None if promotion_goal is None else PROMOTION_GOAL_CHOICES[promotion_goal],
            _read_promotion_goal_label,
        ),
        ("name", name, _read_campaign_name),
        ("landing_url", landing_url, _read_landing_url),
        (
            "gender",
            None if gender is None else GENDER_CHOICES[gender],
            _read_gender_label,
        ),
    ]

    mismatches = []
    for label, expected, reader in checks:
        if expected is None:
            continue
        actual = _read_until_matches(page, reader, expected)
        if actual != expected:
            mismatches.append(
                f"{label}: expected {expected!r}, page now shows {actual!r}"
            )

    if tracking_params is not None:
        # Same settle-wait-then-poll shape as the audience section above
        # (issue #681): the "Дополнительные параметры" spoiler is not
        # guaranteed ready by _wait_for_edit_form, and a single
        # _read_tracking_params call right after reload can itself take
        # 4-5s just to expand it — confirmed live (issue #761), leaving no
        # room in the default 5s retry budget for even one retry.
        page.wait_for_timeout(3_000)
        actual = _read_until_matches(
            page,
            _read_tracking_params,
            tracking_params,
            timeout_ms=_VERIFY_FIELD_READ_TIMEOUT_MS * 4,
        )
        if actual != tracking_params:
            mismatches.append(
                f"tracking_params: expected {tracking_params!r}, page now "
                f"shows {actual!r}"
            )

    if age_from_requested:
        expected_label = _format_age_bound_label(is_from=True, age=age_from)
        actual = _read_until_matches(
            page, lambda p: _read_age_bound_label(p, is_from=True), expected_label
        )
        if actual != expected_label:
            mismatches.append(
                f"age_from: expected {expected_label!r}, page now shows " f"{actual!r}"
            )

    if age_to_requested:
        expected_label = _format_age_bound_label(is_from=False, age=age_to)
        actual = _read_until_matches(
            page, lambda p: _read_age_bound_label(p, is_from=False), expected_label
        )
        if actual != expected_label:
            mismatches.append(
                f"age_to: expected {expected_label!r}, page now shows " f"{actual!r}"
            )

    if devices is not None:
        actual_devices = _read_until_matches(page, _read_devices, devices)
        if actual_devices != devices:
            mismatches.append(
                f"devices: expected {sorted(devices)}, page now shows "
                f"{sorted(actual_devices) if actual_devices is not None else None}"
            )

    if add_audience_tags or remove_audience_tag_count:
        expected_count = (
            len(audience_tags_before or [])
            + len(add_audience_tags or [])
            - remove_audience_tag_count
        )

        def _tag_state_matches(actual_tags: List[str], _expected: Any) -> bool:
            return len(actual_tags) == expected_count and all(
                tag in actual_tags for tag in (add_audience_tags or [])
            )

        # A longer timeout than _VERIFY_FIELD_READ_TIMEOUT_MS's default:
        # _read_audience_tags itself already spends up to
        # _AUDIENCE_SECTION_READY_TIMEOUT_MS settling before returning a
        # single reading, so the default 5s budget could afford barely one
        # retry. Confirmed live (issue #681) a save's tag-list commit can
        # itself lag behind the reload by several seconds beyond that.
        actual_tags = _read_until_matches(
            page,
            _read_audience_tags,
            None,
            matches=_tag_state_matches,
            timeout_ms=_AUDIENCE_SECTION_READY_TIMEOUT_MS * 3,
        )
        if not _tag_state_matches(actual_tags, None):
            mismatches.append(
                f"audience_tags: expected {expected_count} tag(s) including "
                f"{add_audience_tags!r}, page now shows {actual_tags!r}"
            )

    if goal_price is not None:
        actual_goal_price = _read_until_matches(
            page,
            _read_goal_price,
            goal_price,
            matches=lambda actual, expected: _goal_price_matches(expected, actual),
        )
        if not _goal_price_matches(goal_price, actual_goal_price):
            mismatches.append(
                f"goal_price: expected {goal_price!r}, page now shows "
                f"{actual_goal_price!r}"
            )

    if target_action_prices:

        def _read_target_action_prices(
            p: "Page",
        ) -> Optional[Dict[int, Optional[float]]]:
            rows = _read_target_actions_or_none(p)
            if rows is None:
                return None
            return {row["GoalId"]: row["Price"] for row in rows}

        def _target_action_prices_match(
            actual: Optional[Dict[int, Optional[float]]], expected: Dict[int, float]
        ) -> bool:
            if actual is None:
                return False
            return all(
                _target_action_price_matches(price, actual.get(goal_id))
                for goal_id, price in expected.items()
            )

        actual_target_actions = _read_until_matches(
            page,
            _read_target_action_prices,
            target_action_prices,
            matches=_target_action_prices_match,
        )
        if actual_target_actions is None:
            mismatches.append(
                "target_action_price: could not read the 'Целевые действия' "
                "table after saving (row scan never succeeded) — unable to "
                "confirm the price took effect"
            )
        else:
            for goal_id, expected_price in target_action_prices.items():
                actual_price = actual_target_actions.get(goal_id)
                if not _target_action_price_matches(expected_price, actual_price):
                    mismatches.append(
                        f"target_action_price[{goal_id}]: expected "
                        f"{expected_price!r}, page now shows {actual_price!r}"
                    )

    if add_target_actions or remove_target_action_goal_ids:
        # Issue #750: a removed goal's absence from the FIRST read of this
        # table is not by itself proof of removal — the table can go
        # through a genuine, non-throwing empty/partial interval while
        # hydrating (see ``_wait_for_target_actions_settled``'s docstring).
        # Settling once here, before the match-retry loop below even
        # starts, means that loop's first read already lands on a
        # completeness-checked snapshot instead of leaning on repeated
        # reads to average out a race it has no way to detect on its own.
        #
        # Codex adversarial review of this PR (#753): a settle TIMEOUT must
        # not be silently swallowed — the retry loop below stops at its
        # FIRST matching read (``_read_until_matches`` returns as soon as
        # ``is_match`` is true), so without this check a table that never
        # settles could still have its very first, still-hydrating read
        # happen to look like a match (e.g. a removed goal's row genuinely
        # absent from an incomplete snapshot) and be trusted immediately —
        # exactly the false-success this settling wait exists to prevent.
        # Report it as its own mismatch (same shape as the "section never
        # became visible" case below) rather than raising here, so a
        # genuinely never-settling table is reported through the same
        # single ``_verify_saved`` failure path as every other mismatch.
        if not _wait_for_target_actions_settled(page):
            mismatches.append(
                "target actions: the 'Целевые действия' table's row count "
                f"never settled within {_TARGET_ACTION_SETTLE_TIMEOUT_MS / 1000:.0f}s "
                "after saving — unable to confirm add/remove took effect"
            )
        else:

            def _read_target_action_goal_ids(
                p: "Page",
            ) -> Optional[Dict[int, Optional[float]]]:
                # ``None`` (as opposed to ``{}``) means the table could not
                # be read this attempt — see ``_read_target_actions_or_none``'s
                # docstring (Codex adversarial review of #717) for the two
                # distinct failure modes it collapses into ``None``. Either
                # way this is NOT the same as a genuinely empty table — the
                # distinction is required so a removed goal is never
                # confirmed absent from a read that never actually saw the
                # table — see ``_add_remove_match``.
                rows = _read_target_actions_or_none(p)
                if rows is None:
                    return None
                return {row["GoalId"]: row["Price"] for row in rows}

            # Codex adversarial review of this PR (#753), round 2: the
            # settling wait above and this predicate's own read are TWO
            # separate DOM reads — settling certifying 5 stable ``.count()``
            # ticks does not certify that THIS predicate's next, independent
            # ``_read_target_actions_or_none`` call lands on the same
            # settled state (reproduced live: a stable pre-dip streak
            # followed by one post-settle empty read was enough to report a
            # no-op removal as successful). Rather than trust a single
            # matching read here either, require
            # ``_TARGET_ACTION_STABLE_STREAK`` CONSECUTIVE matching reads
            # of the full add/remove snapshot before accepting it — the
            # same stability bar ``_wait_for_target_actions_settled``
            # applies to a bare row count, now applied to the actual
            # verified state.
            match_streak = 0

            def _add_remove_match(
                actual: Optional[Dict[int, Optional[float]]], _expected: Any
            ) -> bool:
                nonlocal match_streak
                if actual is None:
                    match_streak = 0
                    return False
                added_ok = all(
                    _target_action_price_matches(price, actual.get(goal_id))
                    for goal_id, price in (add_target_actions or {}).items()
                )
                removed_ok = not any(
                    goal_id in actual for goal_id in remove_target_action_goal_ids or []
                )
                if added_ok and removed_ok:
                    match_streak += 1
                else:
                    match_streak = 0
                return match_streak >= _TARGET_ACTION_STABLE_STREAK

            actual_after_add_remove = _read_until_matches(
                page,
                _read_target_action_goal_ids,
                None,
                matches=_add_remove_match,
                timeout_ms=_VERIFY_FIELD_READ_TIMEOUT_MS
                + _TARGET_ACTION_SETTLE_TIMEOUT_MS,
            )
            if actual_after_add_remove is None:
                # Every retry within the timeout hit a transient hydration
                # failure — never had a genuine read of the table. Report
                # this as its own mismatch rather than falling back to
                # `{}`, which would make every requested removal look like
                # it succeeded.
                mismatches.append(
                    "target actions: could not read the 'Целевые действия' "
                    "table after saving (section never became visible) — "
                    "unable to confirm add/remove took effect"
                )
            else:
                for goal_id, expected_price in (add_target_actions or {}).items():
                    actual_price = actual_after_add_remove.get(goal_id)
                    if not _target_action_price_matches(expected_price, actual_price):
                        mismatches.append(
                            f"add_target_action[{goal_id}]: expected price "
                            f"{expected_price!r}, page now shows {actual_price!r}"
                        )
                for goal_id in remove_target_action_goal_ids or []:
                    if goal_id in actual_after_add_remove:
                        mismatches.append(
                            f"remove_target_action[{goal_id}]: still present "
                            "in the 'Целевые действия' table after save"
                        )

    mismatches.extend(
        _verify_repeating_value_mismatches(
            page,
            testid_template=_HEADLINES_TESTID_TEMPLATE,
            slot_count=_HEADLINES_SLOT_COUNT,
            label="headline",
            requested=headlines,
        )
    )
    mismatches.extend(
        _verify_repeating_value_mismatches(
            page,
            testid_template=_TEXTS_TESTID_TEMPLATE,
            slot_count=_TEXTS_SLOT_COUNT,
            label="text",
            requested=texts,
        )
    )
    mismatches.extend(
        _verify_image_mismatches(
            page,
            before_ids=images_before_ids or [],
            replaced_ids=images_replaced_ids or set(),
        )
    )

    if mismatches:
        raise BrowserSessionError(
            f"Clicked '{clicked_button_label}' for campaign {campaign_id}, "
            "but re-reading the edit page after reload shows it did not "
            "save as requested: " + "; ".join(mismatches) + ". Yandex may "
            "have rejected the value (client-side validation) or the save "
            "did not complete — verify manually before retrying."
        )


def update_master(
    page: "Page",
    campaign_id: int,
    *,
    weekly_budget: Optional[int] = None,
    promotion_goal: Optional[str] = None,
    goal_price: Optional[float] = None,
    target_action_prices: Optional[Dict[int, float]] = None,
    add_target_actions: Optional[Dict[int, float]] = None,
    remove_target_action_goal_ids: Optional[List[int]] = None,
    directs_helps: Optional[bool] = None,
    name: Optional[str] = None,
    landing_url: Optional[str] = None,
    tracking_params: Optional[str] = None,
    headlines: Optional[Dict[int, str]] = None,
    texts: Optional[Dict[int, str]] = None,
    images: Optional[Dict[int, str]] = None,
    gender: Optional[str] = None,
    age_from: Optional[int] = None,
    age_from_requested: bool = False,
    age_to: Optional[int] = None,
    age_to_requested: bool = False,
    devices: Optional[Set[str]] = None,
    add_audience_tags: Optional[List[str]] = None,
    remove_audience_tags: Optional[List[int]] = None,
    launch: bool = False,
) -> Dict[str, Any]:
    """Update one or more Этап A/B/D fields (plus the campaign name) and save.

    Only fields passed as non-``None`` are touched — see module docstring for
    why this is safe despite the page having a single whole-form save (fields
    left alone keep their current on-page value simply by never having their
    input touched). Raises ``ValueError`` if no field is provided, mirroring
    the rest of the CLI's "nothing to update" guard for partial updates.

    ``name`` (issue #663) is set via a separate modal (``_set_campaign_name``)
    rather than a plain form field — see module docstring — but is persisted
    by the same terminal ``_click_save`` as every other field here.

    ``landing_url`` (issue #757) replaces the "Ссылка на продвигаемую
    страницу" field's value WHOLESALE. Passing ``""`` clears the field
    entirely. Confirmed live this field is READ-ONLY while the campaign's
    status is ARCHIVED — ``_set_landing_url`` raises naming that
    requirement rather than surfacing an opaque markup-changed error.

    ``tracking_params`` (issue #761) replaces the separate "UTM-метки и
    параметры URL" field (``CampaignLinkEditorLite.UTMInput``) — the
    dedicated place for a campaign's UTM query string, independent of
    ``landing_url`` above (see ``_set_tracking_params``'s docstring for why
    this field was previously mistaken for an unused "extra params"
    helper). Passing ``""`` clears it.

    ``headlines``/``texts`` (issue #665, Этап B) map a 0-based slot index to
    its replacement text and REPLACE ONLY THOSE SLOTS — every other headline/
    text variant on the campaign is left exactly as it was. This is a
    deliberate departure from this CLI's dominant list-field convention
    (``campaigns update --negative-keywords`` and similar replace the WHOLE
    array in one shot) — see ``_set_repeating_value``'s docstring for why a
    full-array rewrite doesn't fit here. Writing to a slot that is currently
    empty raises ``BrowserSessionError`` — adding a brand-new variant is a
    different operation, not covered here (see issue #665's follow-ups).

    After clicking save, reloads the edit page and re-reads every requested
    field to confirm it actually saved (see ``_verify_saved``) — a click
    that doesn't visibly change the saved state is reported as a hard error,
    not a silent success, mirroring ``_suspend_or_resume``. Renaming is
    idempotent (re-applying the same name is harmless), so unlike
    ``copy_master`` this function needs no extra guard against
    ``_with_session``'s whole-operation retry on ``BrowserAuthError``.

    ``images`` (issue #670, Этап D) maps a 0-based POSITION (not a content
    ID — content IDs are Yandex-assigned and unknown to callers ahead of
    time) to a local file path, and replaces the image currently at that
    position. Unlike ``headlines``/``texts``, this is NOT a literal
    positional swap — Yandex has no "replace in place" primitive for
    images, so this composes remove+add inside the image manager modal, and
    the newly uploaded image always lands at the END of the set (confirmed
    live — see ``_set_image``'s docstring). The set may legitimately be
    EMPTY (images are optional, unlike headlines/texts); writing to an
    empty set, or to a position beyond the campaign's actual image count,
    raises ``BrowserSessionError``.

    ``gender``/``age_from``/``age_to``/``devices``/``add_audience_tags``/
    ``remove_audience_tags`` (issue #681, Этап C) cover the "Аудитория"
    section's manual-targeting fields — see ``_set_gender``/
    ``_set_age_bound``/``_set_devices``/``_add_audience_tag``/
    ``_remove_audience_tag`` for the per-field mechanics. This module never
    touches the section's own top-level preset selector ("Настроить
    вручную" vs. "Подобрать оптимальную") — every field below only exists
    on the page while "Настроить вручную" is already selected, and switching
    presets is out of scope here (issue #681 follow-up). ``age_from``/
    ``age_to`` accept ``None`` as an explicit, distinct value from "not
    requested" (unlike every other optional field here) — ``age_to=None``
    means "Без ограничений" (no upper bound), a real selectable option, not
    "leave unchanged" — so both are paired with their own
    ``*_requested`` flag; the CLI layer is responsible for only ever
    passing ``age_from_requested``/``age_to_requested`` when the
    corresponding ``--age-from``/``--age-to`` flag was actually given.
    ``add_audience_tags`` appends new keyword/interest tags (Yandex
    disambiguates which kind a given text resolves to; see the
    ``_AUDIENCE_TAG_LISTBOX_TESTID`` module comment) — a tag with no
    matching suggestion raises rather than silently no-op'ing.
    ``remove_audience_tags`` takes 0-based POSITIONS into the tag list as it
    exists BEFORE this call (see ``masters audience get`` to read current
    positions) — removed low-to-high internally so earlier removals don't
    shift the position of a later one still pending.

    Later Этап C fields — sitelinks, Metrika counters/goals, budget
    adaptation — plus video (a separate follow-up issue, different upload
    control/pipeline) are out of scope for this function; see issue #648.

    ``launch`` (issue #668) matters only when ``campaign_id`` is currently a
    DRAFT: that edit page has no "Сохранить кампанию" button at all, only a
    save-as-draft/launch pair (see ``_click_save``/``_is_draft_edit_page``).
    Defaults to ``False`` — DRAFT stays DRAFT unless the caller explicitly
    asks to publish it, mirroring ``create_master``/``copy_master``'s own
    draft-preserving defaults. Has no effect on a non-DRAFT campaign, which
    always uses the single "Сохранить кампанию" button regardless — the
    returned result only carries ``"Launched": True`` when the campaign WAS a
    DRAFT and ``launch=True`` actually published it (issue #704: a dedicated
    ``masters launch`` command, via ``launch_master``, is the
    field-preserving way to just publish a DRAFT without touching any of its
    fields; this ``launch`` kwarg stays for launching in the same call as an
    edit).

    ``goal_price`` (issue #696) sets the "Цель продвижения" block's target
    price. Confirmed live this field ONLY exists on the page when the
    campaign's promotion goal is (or is being set to) "max-clicks" — under
    "max-conversions" the price is instead per-goal in the separate
    "Целевые действия" table, covered by ``target_action_prices`` below.
    Passing ``goal_price`` does not implicitly change ``promotion_goal``;
    if the campaign's CURRENT goal is not "max-clicks" and
    ``promotion_goal="max-clicks"`` isn't also passed in this same call,
    ``_set_goal_price`` raises ``BrowserSessionError`` naming the field as
    not found, since it genuinely is not on the page yet.

    ``target_action_prices`` (issue #707) maps a Yandex Metrika goal id to
    its target price in the "Целевые действия" table — the "max-
    conversions" counterpart to ``goal_price`` above. Only exists on the
    page under "max-conversions", and only for a goal ALREADY listed as a
    row in that table — see ``_set_target_action_price``'s docstring.
    Passing a goal id not currently in the table raises
    ``BrowserSessionError`` naming that requirement.

    ``add_target_actions``/``remove_target_action_goal_ids`` (issue #717)
    add/remove rows in that same table via its own "Добавить"
    popup/close-button, rather than only replacing an existing row's price.
    ``add_target_actions`` maps a goal id NOT currently in the table to its
    price (required — a freshly added row's price input starts empty and
    Yandex rejects saving it empty, see ``_add_target_action``'s docstring);
    the goal must be one of the campaign's linked Metrika counter's goals,
    which is all Yandex's own popup ever offers.
    ``remove_target_action_goal_ids`` lists goal ids to remove. Applied
    AFTER ``target_action_prices`` (an existing row's price can be
    corrected first) and BEFORE the loop below adds new rows — a goal id
    cannot sensibly appear in more than one of ``target_action_prices``/
    ``add_target_actions``/``remove_target_action_goal_ids`` in the same
    call; the CLI boundary rejects that combination before this function is
    reached, this function does not re-validate it.
    """
    if (
        weekly_budget is None
        and promotion_goal is None
        and goal_price is None
        and not target_action_prices
        and not add_target_actions
        and not remove_target_action_goal_ids
        and directs_helps is None
        and name is None
        and landing_url is None
        and tracking_params is None
        and not headlines
        and not texts
        and not images
        and gender is None
        and not age_from_requested
        and not age_to_requested
        and devices is None
        and not add_audience_tags
        and not remove_audience_tags
    ):
        raise ValueError(
            "update_master requires at least one field to update "
            "(weekly_budget, promotion_goal, goal_price, "
            "target_action_prices, add_target_actions, "
            "remove_target_action_goal_ids, directs_helps, name, "
            "landing_url, tracking_params, headlines, texts, images, "
            "gender, age_from, age_to, devices, "
            "add_audience_tags, remove_audience_tags)."
        )

    url = WIZARD_EDIT_URL.format(campaign_id=campaign_id)
    page.goto(url, wait_until="commit")
    assert_not_captcha(page.content())
    assert_authenticated(page.content())
    _wait_for_edit_form(page, campaign_id)

    # Determined right here, before ANY mutation runs, via
    # _wait_for_draft_status rather than a single _is_draft_edit_page read
    # — issue #726 (live-confirmed): the DRAFT-terminal marker can
    # transiently vanish from the DOM mid-hydration and reappear ~1.5s
    # later, and (cycle-review round 2, Codex) _wait_for_edit_form only
    # guarantees the headline slot has rendered, not either terminal save
    # control, so a naive point-in-time read here could also fire before
    # the DRAFT marker has mounted at all. Reading it after the field/image
    # mutations below (as this used to) only narrows the first race, it
    # does not close either — mutations take an unbounded amount of time
    # and can still land inside the flap. Polling for either terminal
    # marker before any mutation closes both directions (see
    # ``_wait_for_draft_status``'s docstring).
    was_draft = _wait_for_draft_status(page, campaign_id)

    if name is not None:
        _set_campaign_name(page, name)
    if landing_url is not None:
        _set_landing_url(page, landing_url)
    if tracking_params is not None:
        _set_tracking_params(page, tracking_params)
    if weekly_budget is not None:
        _set_weekly_budget(page, weekly_budget)
    if promotion_goal is not None:
        _set_promotion_goal(page, promotion_goal)
    if goal_price is not None:
        _set_goal_price(page, goal_price)
    for goal_id, price in (target_action_prices or {}).items():
        _set_target_action_price(page, goal_id, price)
    for goal_id in remove_target_action_goal_ids or []:
        _remove_target_action(page, goal_id)
    for goal_id, price in (add_target_actions or {}).items():
        _add_target_action(page, goal_id, price)
    if directs_helps is not None:
        _set_directs_helps(page, directs_helps)

    _audience_requested = (
        gender is not None
        or age_from_requested
        or age_to_requested
        or devices is not None
        or add_audience_tags
        or remove_audience_tags
    )
    if _audience_requested:
        _wait_for_audience_section(page)
    if gender is not None:
        _set_gender(page, gender)
    if age_from_requested:
        _set_age_bound(page, is_from=True, age=age_from)
    if age_to_requested:
        _set_age_bound(page, is_from=False, age=age_to)
    if devices is not None:
        _set_devices(page, devices)

    # Snapshotted BEFORE any tag mutation, same "resolve later ops against a
    # stable pre-mutation baseline" reasoning as the image-position snapshot
    # below — _verify_saved needs the pre-call count to compute the expected
    # post-save count, and _remove_audience_tags below needs it to remove
    # high-to-low without an earlier removal shifting a later requested
    # position.
    audience_tags_before = (
        _read_audience_tags(page) if (add_audience_tags or remove_audience_tags) else []
    )
    _running_tag_count = len(audience_tags_before)  # noqa: SIM113
    for index in sorted(remove_audience_tags or [], reverse=True):
        if index >= len(audience_tags_before):
            raise BrowserSessionError(
                f"Audience tag position {index + 1} is out of range — this "
                f"campaign currently has {len(audience_tags_before)} tag(s) "
                f"(positions 1-{len(audience_tags_before)})."
            )
        _remove_audience_tag(page, index)
        # Same "click alone isn't proof" guard as the add-tag verification
        # below — confirmed live (issue #681) a save immediately after a
        # close-button click that hadn't actually committed to the DOM yet
        # reloaded with the tag still present.
        _running_tag_count -= 1
        deadline = _clock.now() + _AUDIENCE_TAG_SUGGEST_TIMEOUT_MS / 1000
        actual_count = len(_read_audience_tags(page))
        while actual_count != _running_tag_count and _clock.now() < deadline:
            page.wait_for_timeout(250)
            actual_count = len(_read_audience_tags(page))
        if actual_count != _running_tag_count:
            raise BrowserSessionError(
                f"Clicked the close button for the tag at position "
                f"{index + 1}, but the tag list still shows {actual_count} "
                f"tag(s) instead of the expected {_running_tag_count} — the "
                "click may not have committed. Verify manually before "
                "retrying."
            )
    for text in add_audience_tags or []:
        _add_audience_tag(page, text)
        # A click that doesn't visibly grow the tag list is a hard error
        # here too, not a silent no-op (mirrors _click_action_button's
        # "never trust the click alone" convention) — confirmed live
        # (issue #681) a save immediately after an _add_audience_tag click
        # that hadn't actually committed to the DOM yet reloaded with the
        # tag missing, even though the click itself raised no error.
        _running_tag_count += 1
        deadline = _clock.now() + _AUDIENCE_TAG_SUGGEST_TIMEOUT_MS / 1000
        actual_count = len(_read_audience_tags(page))
        while actual_count != _running_tag_count and _clock.now() < deadline:
            page.wait_for_timeout(250)
            actual_count = len(_read_audience_tags(page))
        if actual_count != _running_tag_count:
            raise BrowserSessionError(
                f"Clicked the matching suggestion for {text!r} in "
                "'Интересы и поисковые запросы', but the tag list still "
                f"shows {actual_count} tag(s) instead of the expected "
                f"{_running_tag_count} — the click may not have committed. "
                "Verify manually before retrying."
            )

    for index, value in (headlines or {}).items():
        _set_repeating_value(
            page, _HEADLINES_TESTID_TEMPLATE, _HEADLINES_SLOT_COUNT, index, value
        )
    for index, value in (texts or {}).items():
        _set_repeating_value(
            page, _TEXTS_TESTID_TEMPLATE, _TEXTS_SLOT_COUNT, index, value
        )

    # Snapshotted BEFORE any image mutation — ``_verify_saved`` needs to know
    # which content IDs were replaced (to confirm they're gone) and which
    # were left alone (to confirm they're still there). This snapshot is
    # ALSO what each ``_set_image`` call is resolved against (by content ID,
    # never by re-deriving a live position): a naive per-position loop would
    # resolve later ``--image`` flags against the set as ``_set_image`` left
    # it after an earlier replacement — which always appends to the end
    # (see ``_set_image``'s docstring) — silently removing a DIFFERENT image
    # than the one the caller named. Found independently by two reviewers in
    # cycle-review round 1 of PR #670/#672. The wait matters here too: an
    # unrendered section would snapshot an empty "before" set and silently
    # verify nothing afterwards.
    if images:
        _wait_for_images_editor(page)
    images_before_ids = _read_image_content_ids(page) if images else []
    images_replaced_ids: Set[str] = set()
    for index, path in (images or {}).items():
        if index >= len(images_before_ids):
            raise BrowserSessionError(
                f"Image position {index + 1} is out of range — this "
                f"campaign currently has {len(images_before_ids)} image(s) "
                f"(positions 1-{len(images_before_ids)})."
            )
        target_content_id = images_before_ids[index]
        images_replaced_ids.add(target_content_id)
        _set_image(page, index, path, target_content_id=target_content_id)

    # was_draft was captured right after _wait_for_edit_form, above — reused
    # here rather than re-derived, for the same reason _click_save takes it
    # as an explicit argument instead of re-querying the DOM itself.
    if was_draft:
        clicked_button_label = (
            _LAUNCH_BUTTON_TEXT if launch else _SAVE_DRAFT_BUTTON_TEXT
        )
    else:
        clicked_button_label = _SAVE_BUTTON_TEXT

    _click_save(page, campaign_id, is_draft=was_draft, launch=launch)

    # The terminal-button click above already happened — irreversible, and
    # for images NOT idempotent (a retry would re-snapshot the
    # already-mutated set and replace DIFFERENT images than the ones the
    # caller named; see _set_image's docstring). If the saved session is
    # invalidated in exactly this window, _verify_saved's own
    # assert_authenticated raises BrowserAuthError; letting that propagate
    # as-is would make _with_session (direct_cli/commands/masters.py) retry
    # this ENTIRE update_master call under a fresh session. Re-raise as a
    # plain BrowserSessionError so that retry does not trigger — mirrors
    # copy_master's identical guard around its own post-click verification.
    try:
        _verify_saved(
            page,
            campaign_id,
            weekly_budget=weekly_budget,
            promotion_goal=promotion_goal,
            directs_helps=directs_helps,
            name=name,
            landing_url=landing_url,
            tracking_params=tracking_params,
            headlines=headlines,
            texts=texts,
            images_before_ids=images_before_ids,
            images_replaced_ids=images_replaced_ids,
            goal_price=goal_price,
            target_action_prices=target_action_prices,
            add_target_actions=add_target_actions,
            remove_target_action_goal_ids=remove_target_action_goal_ids,
            gender=gender,
            age_from_requested=age_from_requested,
            age_from=age_from,
            age_to_requested=age_to_requested,
            age_to=age_to,
            devices=devices,
            audience_tags_before=audience_tags_before,
            add_audience_tags=add_audience_tags,
            remove_audience_tag_count=len(remove_audience_tags or []),
            clicked_button_label=clicked_button_label,
        )
    except BrowserAuthError as exc:
        raise BrowserSessionError(
            f"Clicked '{clicked_button_label}' for campaign {campaign_id}, "
            "but the session was invalidated while verifying the save — "
            "the requested changes were likely already applied; check "
            f"campaign {campaign_id} manually rather than retrying "
            "(image replacements are not idempotent)."
        ) from exc

    result: Dict[str, Any] = {"CampaignId": campaign_id}
    if weekly_budget is not None:
        result["WeeklyBudget"] = weekly_budget
    if promotion_goal is not None:
        result["PromotionGoal"] = promotion_goal
    if goal_price is not None:
        result["GoalPrice"] = goal_price
    if target_action_prices:
        result["TargetActionPrices"] = target_action_prices
    if add_target_actions:
        result["AddedTargetActions"] = add_target_actions
    if remove_target_action_goal_ids:
        result["RemovedTargetActionGoalIds"] = remove_target_action_goal_ids
    if directs_helps is not None:
        result["DirectsHelps"] = directs_helps
    if name is not None:
        result["Name"] = name
    if landing_url is not None:
        result["LandingUrl"] = landing_url
    if tracking_params is not None:
        result["TrackingParams"] = tracking_params
    if headlines:
        result["Headlines"] = headlines
    if texts:
        result["Texts"] = texts
    if images:
        result["Images"] = images
    if gender is not None:
        result["Gender"] = gender
    if age_from_requested:
        result["AgeFrom"] = age_from
    if age_to_requested:
        result["AgeTo"] = age_to
    if devices is not None:
        result["Devices"] = sorted(devices)
    if add_audience_tags:
        result["AddedAudienceTags"] = add_audience_tags
    if remove_audience_tags:
        result["RemovedAudienceTagPositions"] = sorted(remove_audience_tags)
    if was_draft and launch:
        # Issue #721: the DRAFT edit page's launch click redirects away from
        # /edit/ (already awaited by _click_draft_terminal_button inside
        # _click_save above), but that redirect is not proof Yandex actually
        # sent the campaign to moderation — it can land on the overview page
        # mid-transition, same race launch_master's own recon hit (see
        # module docstring). _verify_saved above already re-navigated the
        # page back to WIZARD_EDIT_URL to check the touched fields, so this
        # needs its own trip to the overview page (mirroring launch_master's
        # own _goto_overview_page call) before _verify_launched_to_moderation
        # can read its status text — closing the gap where update_master
        # --launch previously reported "Launched": True purely off the
        # click/redirect, with no check that the campaign didn't silently
        # stay DRAFT.
        #
        # This trip is just as irreversible/non-idempotent as the click
        # itself (see the guard above _verify_saved): if the session is
        # invalidated in this window, letting BrowserAuthError propagate
        # bare would make _with_session retry the ENTIRE update_master call
        # under a fresh session, re-mutating any --image replacements a
        # second time (found via adversarial review, cycle-review round 1
        # of PR #727).
        try:
            _goto_overview_page(page, campaign_id)
            _verify_launched_to_moderation(page, campaign_id)
        except BrowserAuthError as exc:
            raise BrowserSessionError(
                f"Clicked '{_LAUNCH_BUTTON_TEXT}' for campaign {campaign_id}, "
                "but the session was invalidated while confirming it reached "
                "moderation — the requested changes were likely already "
                f"applied and launched; check campaign {campaign_id} "
                "manually rather than retrying (image replacements are not "
                "idempotent)."
            ) from exc
        result["Launched"] = True
    return result


def _open_images_editor(page: "Page", campaign_id: int) -> Tuple[List[str], bool]:
    """Navigate to the campaign's edit page and return its current image
    content IDs plus its DRAFT status, once the "Изображения" section has
    actually rendered.

    The shared opening move of every ``masters adimages`` entry point:
    ``goto`` + captcha/auth assertions + ``_wait_for_images_editor``. That
    settle is what makes the returned content-ID list trustworthy — read any
    earlier and a campaign that simply has not finished rendering is
    indistinguishable from one that genuinely has no images (see
    ``_wait_for_images_editor``).

    The DRAFT status is determined right after ``_wait_for_edit_form``, via
    ``_wait_for_draft_status`` rather than a single ``_is_draft_edit_page``
    read — the marker can both flap present→absent mid-hydration AND not
    have mounted at all yet when only the headline slot has rendered (issue
    #726; the latter ordering was a cycle-review round-2 gap in the first
    fix). Returned for the caller to carry through
    ``_apply_image_operations`` (uploads/removals, unbounded elapsed time)
    into ``_save_and_verify_images`` unchanged. Re-deriving it after
    ``_apply_image_operations`` would land back in the same DOM-flap race
    the caller-side fix in ``update_master`` was written to close (see
    ``_click_save``'s docstring).
    """
    page.goto(
        WIZARD_EDIT_URL.format(campaign_id=campaign_id),
        wait_until="commit",
    )
    assert_not_captcha(page.content())
    assert_authenticated(page.content())
    _wait_for_edit_form(page, campaign_id)
    is_draft = _wait_for_draft_status(page, campaign_id)

    _wait_for_images_editor(page)
    return _read_image_content_ids(page), is_draft


def fetch_master_images(page: "Page", campaign_id: int) -> Dict[str, Any]:
    """Read a campaign's current image set — content IDs, 1-based
    positions, and thumb URLs.

    Read-only: opens the image manager modal to also read
    ``_read_modal_selected_thumb_urls`` (the thumb URL is not exposed on
    the edit page itself), then abandons it WITHOUT ever clicking Save —
    safe, because nothing commits to the saved image set before Save (the
    same invariant ``_set_image``'s and ``_apply_image_operations``'s
    docstrings establish). A campaign with no images skips the modal
    entirely, there being nothing to read.

    An empty image set is a legitimate, successful result (``Count: 0``),
    not an error — unlike headlines/texts, images have no "at least one"
    invariant (see ``_IMAGES_MAX_COUNT``'s module-level comment).
    """
    content_ids, _is_draft = _open_images_editor(page, campaign_id)

    thumb_urls: Dict[str, Optional[str]] = {cid: None for cid in content_ids}
    if content_ids:
        _open_images_modal(page)
        modal_ids = _read_image_content_ids(page)
        panel_urls = _read_modal_selected_thumb_urls(page)
        if len(modal_ids) == len(panel_urls):
            thumb_urls.update(dict(zip(modal_ids, panel_urls)))

    images = [
        {
            "Position": index + 1,
            "ContentId": content_id,
            "ThumbUrl": thumb_urls.get(content_id),
        }
        for index, content_id in enumerate(content_ids)
    ]

    return {
        "CampaignId": campaign_id,
        "Images": images,
        "Count": len(content_ids),
        "MaxCount": _IMAGES_MAX_COUNT,
    }


def fetch_master_target_actions(page: "Page", campaign_id: int) -> Dict[str, Any]:
    """Read a campaign's current "Целевые действия" (target action / CPA)
    table — see ``_read_target_actions``'s docstring for the row shape.

    Read-only, mirrors ``fetch_master_images``: navigates straight to the
    edit page (this data does not exist on the overview page ``fetch_master``
    reads — see issue #707) and reads without ever touching Save.

    An empty list is a legitimate result — either the campaign's promotion
    goal is not "max-conversions" (the table doesn't exist on the page at
    all), or it is but no goal has been added to it yet. This function does
    not distinguish the two; callers that need to know which should also
    check ``promotion_goal`` via ``fetch_master``.
    """
    page.goto(WIZARD_EDIT_URL.format(campaign_id=campaign_id), wait_until="commit")
    assert_not_captcha(page.content())
    assert_authenticated(page.content())
    _wait_for_edit_form(page, campaign_id)

    target_actions = _read_target_actions(page)

    return {
        "CampaignId": campaign_id,
        "TargetActions": target_actions,
        "Count": len(target_actions),
    }


def fetch_master_audience(page: "Page", campaign_id: int) -> Dict[str, Any]:
    """Read a campaign's current "Аудитория" (gender/age/interests-and-
    search-terms/devices) manual-targeting settings.

    Read-only, mirrors ``fetch_master_target_actions``: navigates straight
    to the edit page (this data does not exist on the overview page
    ``fetch_master`` reads) and reads without ever touching Save.

    ``AudienceTags`` is returned in on-page order (0-based positions match
    what ``masters update --remove-audience-tag`` expects) — this function
    does not distinguish a keyword tag from an interest-category tag in the
    result (see the ``_AUDIENCE_TAG_LISTBOX_TESTID`` module comment for why
    that distinction isn't reliably derivable from an already-added tag's
    display text alone).
    """
    page.goto(WIZARD_EDIT_URL.format(campaign_id=campaign_id), wait_until="commit")
    assert_not_captcha(page.content())
    assert_authenticated(page.content())
    _wait_for_edit_form(page, campaign_id)
    _wait_for_audience_section(page)

    audience_tags = _read_audience_tags(page)
    devices = _read_devices(page)

    return {
        "CampaignId": campaign_id,
        "Gender": _read_gender_label(page),
        "AgeFromLabel": _read_age_bound_label(page, is_from=True),
        "AgeToLabel": _read_age_bound_label(page, is_from=False),
        "AudienceTags": audience_tags,
        "AudienceTagCount": len(audience_tags),
        "Devices": sorted(devices) if devices is not None else None,
    }


def add_master_images(
    page: "Page",
    campaign_id: int,
    *,
    paths: Sequence[str],
    launch: bool = False,
) -> Dict[str, Any]:
    """Upload every file in ``paths`` and append them to the campaign's
    image set — works from an empty set (unlike ``update_master``'s
    ``--image``, which only replaces an existing image).

    All uploads happen inside ONE modal session via
    ``_apply_image_operations``, followed by the edit page's terminal
    save (draft-aware, same as ``update_master``) and a re-navigate
    verification via ``_verify_saved_images``.
    """
    if not paths:
        raise ValueError("add_master_images requires at least one path.")

    before_ids, is_draft = _open_images_editor(page, campaign_id)

    if len(before_ids) + len(paths) > _IMAGES_MAX_COUNT:
        raise BrowserSessionError(
            f"Campaign {campaign_id} currently has {len(before_ids)} "
            f"image(s); adding {len(paths)} more would exceed Yandex's "
            f"cap of {_IMAGES_MAX_COUNT} images per campaign."
        )

    _apply_image_operations(
        page,
        remove_content_ids=(),
        upload_paths=paths,
    )

    final_ids = _save_and_verify_images(
        page,
        campaign_id,
        is_draft=is_draft,
        expected_kept_ids=before_ids,
        removed_ids=set(),
        expected_added_count=len(paths),
        launch=launch,
        not_idempotent_noun="image uploads",
    )

    return {
        "CampaignId": campaign_id,
        "Added": len(paths),
        "Count": len(final_ids),
    }


def delete_master_images(
    page: "Page",
    campaign_id: int,
    *,
    positions: Optional[Sequence[int]] = None,
    content_ids: Optional[Sequence[str]] = None,
    all_images: bool = False,
    launch: bool = False,
) -> Dict[str, Any]:
    """Delete images from the campaign's image set, addressed by 0-based
    ``positions``, explicit ``content_ids``, or ``all_images=True`` for
    every image currently in the set.

    ``all_images=True`` against an already-empty set is an idempotent
    no-op success when ``launch=False`` (mirrors ``suspend``/``resume``'s
    "idempotent if already X" convention) — no modal is opened, nothing is
    saved. With ``launch=True``, the no-op still applies to the images (the
    modal is never opened), but the DRAFT-publish click still happens —
    ``--launch`` is a second, independent request that an empty image set
    must not swallow (issue #678). Naming a specific position or content ID
    that does not exist is always an error, empty set or not.
    """
    if not positions and not content_ids and not all_images:
        raise ValueError(
            "delete_master_images requires positions, content_ids, or "
            "all_images=True."
        )

    before_ids, is_draft = _open_images_editor(page, campaign_id)

    if all_images:
        if not before_ids and not launch:
            return {"CampaignId": campaign_id, "Deleted": 0, "Count": 0}
        targets: List[str] = list(before_ids)
    else:
        targets = []
        for position in positions or ():
            if position >= len(before_ids):
                raise BrowserSessionError(
                    f"Image position {position + 1} is out of range — "
                    f"this campaign currently has {len(before_ids)} "
                    f"image(s) (positions 1-{len(before_ids)})."
                )
            cid = before_ids[position]
            if cid not in targets:
                targets.append(cid)
        for content_id in content_ids or ():
            if content_id not in before_ids:
                raise BrowserSessionError(
                    f"Content ID {content_id!r} is not present in "
                    f"campaign {campaign_id}'s current image set."
                )
            if content_id not in targets:
                targets.append(content_id)

    _apply_image_operations(
        page,
        remove_content_ids=targets,
        upload_paths=(),
    )

    final_ids = _save_and_verify_images(
        page,
        campaign_id,
        is_draft=is_draft,
        expected_kept_ids=[cid for cid in before_ids if cid not in targets],
        removed_ids=set(targets),
        expected_added_count=0,
        launch=launch,
        not_idempotent_noun="image deletions",
    )

    return {
        "CampaignId": campaign_id,
        "Deleted": len(targets),
        "Count": len(final_ids),
    }


def set_master_images(
    page: "Page",
    campaign_id: int,
    *,
    paths: Sequence[str],
    launch: bool = False,
) -> Dict[str, Any]:
    """Replace the campaign's ENTIRE image set with ``paths`` — every
    current image is removed, then every file in ``paths`` is uploaded, in
    one modal session. ``paths=()`` empties the set entirely.

    Removals and uploads happen inside the SAME ``_apply_image_operations``
    call, so a full at-cap replacement (e.g. 5 images out, 5 images in)
    never transiently exceeds Yandex's cap — the removals are applied to
    the modal's live selection before any upload begins.

    An already-empty set with ``paths=()`` is a no-op for the images (the
    modal is never opened) when ``launch=False``. With ``launch=True`` the
    DRAFT-publish click still happens — ``--launch`` is a second,
    independent request that an empty image set must not swallow (issue
    #678).
    """
    if len(paths) > _IMAGES_MAX_COUNT:
        raise BrowserSessionError(
            f"Cannot set {len(paths)} images — Yandex's cap is "
            f"{_IMAGES_MAX_COUNT} images per campaign."
        )

    before_ids, is_draft = _open_images_editor(page, campaign_id)

    if not before_ids and not paths and not launch:
        return {"CampaignId": campaign_id, "Count": 0}

    _apply_image_operations(
        page,
        remove_content_ids=before_ids,
        upload_paths=paths,
    )

    final_ids = _save_and_verify_images(
        page,
        campaign_id,
        is_draft=is_draft,
        expected_kept_ids=[],
        removed_ids=set(before_ids),
        expected_added_count=len(paths),
        launch=launch,
        not_idempotent_noun="image replacements",
    )

    return {
        "CampaignId": campaign_id,
        "Count": len(final_ids),
    }


def _type_landing_url(field: Any, url: str) -> None:
    """Type ``url`` into a landing-URL contenteditable field, verifying it
    landed. Shared by the create page's step 1 field and the edit page's
    "Ссылка на продвигаемую страницу" field (issue #757) — both are the same
    kind of widget, just under different testid namespaces.

    Issue #690 re-recon (2026-08-04): typing this field via
    ``field.type(url)`` intermittently drops characters from the MIDDLE of
    the string — confirmed live via ``textContent`` reads immediately after
    typing (e.g. typing produced ``"https://.ru/novaya-..."`` with
    ``"ksamata"`` simply missing), not just a trailing/leading truncation.
    This reproduces at both the Playwright default (no per-key delay) and a
    150ms delay, just less often at the latter — it is the widget's own
    debounced-suggestion lookup racing a keystroke burst, not something a
    fixed delay alone reliably avoids. ``field.fill()`` does not help either
    despite succeeding without error: it sets the DOM text directly without
    the real ``input`` events this Combobox listens for, so neither the
    suggestions popup nor the "Далее" button ever appears afterwards
    (confirmed live: polled 10s with zero reaction from the widget).

    The only reliable approach found live is retry-with-verify: type with a
    human-like delay, read ``textContent`` back, and retry (clearing first,
    since ``.type()`` APPENDS to a contenteditable — see
    ``_clear_text_field``) if it doesn't match. Every attempt observed live
    needed at most 2 tries; ``_TYPE_URL_MAX_ATTEMPTS`` leaves generous
    headroom above that.
    """
    actual: Optional[str] = None
    for attempt in range(_TYPE_URL_MAX_ATTEMPTS):
        if attempt:
            _clear_text_field(field)
        try:
            field.type(url, delay=_TYPE_URL_DELAY_MS)
        except PlaywrightError as exc:
            raise BrowserSessionError(
                "Could not type into the landing-page URL field on the "
                "Мастер кампаний page — Yandex may have changed the page's "
                "markup. Re-run with --headful to inspect the page."
            ) from exc
        try:
            actual = field.text_content()
        except PlaywrightError:
            actual = None
        if actual == url:
            return

    raise BrowserSessionError(
        f"Typed {url!r} into the landing-page URL field on the Мастер "
        f"кампаний page {_TYPE_URL_MAX_ATTEMPTS} times, but the field "
        f"still shows {actual!r} — Yandex's Combobox widget appears to be "
        "dropping keystrokes. Re-run with --headful to inspect the page."
    )


def _fill_landing_url(page: "Page", url: str) -> None:
    """Fill step 1's URL field and advance to step 2.

    Field located by ``_CREATE_URL_INPUT_TESTID`` (issue #650 re-recon,
    2026-08-02) — Yandex replaced the plain ``<input placeholder="...">``
    with a Combobox whose text control is a ``contenteditable`` ``<div
    role="textbox">`` that ``get_by_placeholder()`` (matches only
    ``<input>``/``<textarea>``) can no longer find, even though the
    placeholder text itself is unchanged. See ``_type_landing_url`` for why
    typing itself needs a retry-with-verify loop.

    **Two distinct continuations, not one "Далее" click** (issue #690
    re-recon): typing a URL Yandex recognises from the account's own
    history (previously used landing pages, e.g. a bare match of a
    previously created campaign's URL) renders a suggestions Combobox popup
    (confirmed live: a ``role="listbox"`` containing one ``role="option"``
    per suggestion, each carrying a ``data-testid`` of
    ``CampaignFormUrl.listBox.<raw suggestion url>``) INSTEAD of enabling
    ``_CREATE_NEXT_BUTTON_TESTID`` — the button's own data-testid is
    completely absent from the DOM the whole time this popup is open.
    Selecting the matching option is enough to advance: Yandex re-validates
    the URL server-side and the SPA moves on to step 2 on its own within
    ~10s, with no "Далее" click at all (confirmed live: the button
    reappears disabled, then becomes enabled-but-invisible, without ever
    being clicked, exactly when step 2's own markup takes over the DOM).
    Confirmed live: Yandex stores the suggestion WITHOUT a trailing slash
    even when the campaign's actual URL has one (``.../ksamata.ru`` for a
    site whose real landing is ``.../ksamata.ru/``) — the testid is matched
    against both the exact ``url`` and its trailing-slash-stripped form so
    a same-site match isn't missed over that alone.

    A URL with NO exact suggestion match still renders this popup — showing
    the account's unrelated suggestion history instead (confirmed live) —
    but with ``_CREATE_NEXT_BUTTON_TESTID`` also present and already
    enabled; this is matched by exact ``data-testid``, not accessible-name
    text, precisely so an unrelated suggestion is never clicked by mistake.
    """
    field = page.locator(_CREATE_URL_INPUT_TESTID).first
    try:
        field.click()
    except PlaywrightError as exc:
        raise BrowserSessionError(
            "Could not find or click the landing-page URL field on the "
            "Мастер кампаний create page — Yandex may have changed the "
            "page's markup. Re-run with --headful to inspect the page."
        ) from exc

    _type_landing_url(field, url)

    next_button = page.locator(_CREATE_NEXT_BUTTON_TESTID)
    # Two candidate testids, not one combined CSS selector: confirmed live
    # Yandex stores the suggestion without a trailing slash even when the
    # real URL has one (see docstring), and querying each candidate
    # separately keeps this a plain data-testid lookup like every other
    # locator in this module.
    #
    # Scoped to the bare-domain-root case ONLY — confirmed live is exactly
    # "https://host/" vs. the stored "https://host", i.e. path == "/" AND no
    # query/fragment. Generalizing this to any URL ending in "/" would also
    # strip a PATH's trailing slash (e.g. "/sale/" -> "/sale") or a QUERY
    # VALUE's trailing slash (e.g. "/?next=/" -> "/?next="), neither of
    # which is confirmed to be the same destination and neither was
    # observed live — matching on that alone risked selecting an unintended
    # suggestion and launching the campaign against a different landing
    # page (Codex review, PR #703 rounds 1 and 2).
    split_url = urlsplit(url)
    url_candidates = (
        [url, url.rstrip("/")]
        if url.endswith("/")
        and split_url.path == "/"
        and not split_url.query
        and not split_url.fragment
        else [url]
    )
    option_locators = [
        page.locator(f'[data-testid="CampaignFormUrl.listBox.{candidate}"]')
        for candidate in url_candidates
    ]

    def _matching_option():
        for locator in option_locators:
            if locator.count():
                return locator
        return None

    def _suggestion_or_button_ready() -> bool:
        return _matching_option() is not None or bool(next_button.count())

    if not _poll_until(
        page, _suggestion_or_button_ready, _CREATE_URL_RESPONSE_TIMEOUT_MS
    ):
        raise BrowserSessionError(
            "Neither a matching suggestion nor the 'Далее' button appeared "
            "after typing the landing-page URL on the Мастер кампаний "
            "create page within "
            f"{_CREATE_URL_RESPONSE_TIMEOUT_MS / 1000:.0f}s — Yandex may "
            "have changed the page's markup. Re-run with --headful to "
            "inspect the page."
        )

    matching_option = _matching_option()
    if matching_option is not None:
        try:
            matching_option.first.click()
        except PlaywrightError as exc:
            raise BrowserSessionError(
                f"Could not click the matching suggestion for {url!r} on "
                "the Мастер кампаний create page — Yandex may have changed "
                "the page's markup. Re-run with --headful to inspect the "
                "page."
            ) from exc
        return

    try:
        next_button.first.click()
    except PlaywrightError as exc:
        raise BrowserSessionError(
            "Could not find or click the 'Далее' button on the Мастер "
            "кампаний create page — Yandex may have changed the page's "
            "markup. Re-run with --headful to inspect the page."
        ) from exc

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


def _wait_for_create_step1(page: "Page") -> None:
    """Block until the create page's step 1 URL field has rendered.

    ``goto(WIZARD_CREATE_URL, wait_until="commit")`` returns as soon as the
    response headers arrive — before Playwright has even parsed the initial
    HTML, let alone run the client-side JS that renders step 1's field (see
    ``_CREATE_STEP1_TIMEOUT_MS``). Without this wait, ``_fill_landing_url``'s
    ``page.locator(_CREATE_URL_INPUT_TESTID).first.click()`` races the page's
    hydration: Playwright's own actionability auto-wait usually absorbs this,
    but on a slow render it can exceed ``.click()``'s default timeout and
    surface as an opaque ``PlaywrightError`` that ``_fill_landing_url``
    reports as "Yandex may have changed the page's markup" — a misdiagnosis
    of a load-timing issue as a markup change (issue #685).
    """
    if _poll_until(
        page,
        lambda: page.locator(_CREATE_URL_INPUT_TESTID).count() > 0,
        _CREATE_STEP1_TIMEOUT_MS,
    ):
        return

    # ``commit`` returns before the page has any real content, so the
    # captcha/auth checks callers run immediately after ``goto`` may have
    # passed vacuously against near-empty HTML. Re-run them against
    # whatever rendered during the poll above so a captcha/login page that
    # only appeared partway through is reported specifically, instead of as
    # this function's generic step-1 timeout.
    assert_not_captcha(page.content())
    assert_authenticated(page.content())

    raise BrowserSessionError(
        "Timed out waiting for the Мастер кампаний create page's step 1 "
        f"(the landing-page URL field) to render within "
        f"{_CREATE_STEP1_TIMEOUT_MS / 1000:.0f}s. Yandex may have changed "
        "the page's markup, or the page may still be loading. Re-run with "
        "--headful to inspect the page."
    )


def _wait_for_step2(page: "Page") -> None:
    """Block until step 2's long form has rendered.

    Confirmed live this can take 10-15s+ after advancing from step 1 —
    Yandex scans the landing page's content server-side to pre-fill
    headlines, texts, and images before rendering the rest of the form.

    Polls for ``CampaignTitles0.textarea`` (issue #690 re-recon,
    2026-08-04) rather than the "Регион показов" heading this used before:
    live testing found the region picker section (``RegionsTreeEditor`` /
    "Регион показов") had not yet rendered at the point that snapshot was
    taken. Headlines slot 0 is used instead for the same reason
    ``_EDIT_FORM_READY_TESTID`` picked it on the edit page: it is the one
    field guaranteed present and stably identified by ``data-testid`` on
    every step 2 render (see ``_HEADLINES_SLOT_COUNT``'s docstring).

    Issue #705 re-recon, same day: confirmed the region picker section DOES
    render on this same account shortly after this function returns — it was
    a render-timing snapshot, not a removed field (see ``_set_region``'s
    docstring and the fixture's 2026-08-04 region re-recon notes).
    """
    headlines_ready = page.locator(f'[data-testid="{_EDIT_FORM_READY_TESTID}"]')
    if _poll_until(
        page, lambda: bool(headlines_ready.count()), _CREATE_STEP2_TIMEOUT_MS
    ):
        return

    # Which step the page is actually stuck on changes the diagnosis
    # entirely, and re-running --headful just to find out is expensive on a
    # page with no sandbox — so report it in the error itself. Step 1's URL
    # field is gone from the DOM once step 2 renders, so its presence means
    # the form never advanced.
    still_on_step1 = False
    with contextlib.suppress(PlaywrightError):
        still_on_step1 = bool(page.locator(_CREATE_URL_INPUT_TESTID).count())
    where = (
        "The page is still showing step 1 (the URL field), so it never "
        "advanced — Yandex may still be scanning the landing page."
        if still_on_step1
        else "The page has left step 1, so step 2 rendered but without the "
        "expected first headline slot — its markup may have changed."
    )

    raise BrowserSessionError(
        "Timed out waiting for the Мастер кампаний create form's step 2 "
        f"(the first headline slot) to render within "
        f"{_CREATE_STEP2_TIMEOUT_MS / 1000:.0f}s. {where} Re-run with "
        "--headful to inspect the page."
    )


def _add_repeating_values(
    page: "Page", testid_template: str, slot_count: int, values: List[str]
) -> None:
    """Fill each of ``values`` into successive slots of a fixed-size repeating
    list field (headlines/texts) — issue #653 re-recon, 2026-08-02.

    Yandex replaced the old "single current-variant input, fill + Enter"
    flow with a FIXED set of pre-rendered contenteditable ``<div
    role="textbox">`` slots (``testid_template.format(index=N)``, confirmed
    live via ``CampaignTitles{N}.textarea``/``CampaignTexts{N}.textarea``) —
    there is no "add another" control, and ``.fill()``/``.press("Enter")``
    do not work on a contenteditable div (same class of markup change as
    ``_fill_landing_url``'s URL field, issue #650). This types into each
    slot in order via ``.click()`` + ``.type()`` instead.

    Confirmed live these sections start pre-populated by Yandex's own AI
    scan of the landing page (see module docstring), so EVERY slot is
    CLEARED — not just the ``len(values)`` being written. Two distinct
    reasons, both found by the issue #655 review:

    * ``.type()`` appends from wherever the click left the caret, so a slot
      that is not cleared first gets the caller's value spliced into the
      middle of Yandex's copy rather than replacing it.
    * every non-empty slot is a PUBLISHED ad variant, so leaving the unused
      trailing slots pre-filled would launch the caller's headline plus the
      leftover AI-written ones they never reviewed — precisely what
      ``create_master``'s contract refuses to do.

    A slot that cannot even be clicked, or cannot be cleared, is fatal for
    EVERY slot — including one with no caller-supplied value. A click
    failure does not distinguish "not rendered" from "obstructed but still
    holding Yandex's AI copy" (issue #655 round-2 review, Codex): treating
    it as safe-to-skip once let a click failure on a populated slot slip
    through, and ``create_master`` clicks the terminal LAUNCH button before
    ``_verify_created`` ever re-reads the page — so a skipped-but-populated
    slot would publish unreviewed copy from a live campaign before anyone
    found out, with no rollback. Callers whose values would overflow
    ``slot_count`` (more values than available slots) get a hard error
    rather than a silent drop, for the same reason.
    """
    if len(values) > slot_count:
        raise BrowserSessionError(
            f"Cannot add {len(values)} values — the create page only "
            f"renders {slot_count} slots for this field. Reduce the number "
            "of values, or clear some of Yandex's AI-generated defaults by "
            "hand first (--headful)."
        )

    # EVERY slot is cleared, not just the ``len(values)`` being filled: each
    # non-empty slot is a published ad variant, and most of them arrive
    # pre-filled with Yandex's AI scan of the landing page. Clearing only the
    # slots we write would launch the caller's headline PLUS the leftover
    # AI-written ones they never reviewed — exactly what this module's
    # contract refuses to do (see create_master's docstring), on a page with
    # no sandbox and no rollback (issue #655 review).
    for index in range(slot_count):
        selector = f'[data-testid="{testid_template.format(index=index)}"]'
        field = page.locator(selector).first
        value = values[index] if index < len(values) else None
        try:
            field.click()
            # The slot arrives pre-filled with Yandex's AI-generated copy and
            # type() appends from wherever the click put the caret, so without
            # this the value lands INSIDE the existing text (confirmed live:
            # "Центр оздоровления и китайско<typed>й гимнастики цигун!").
            cleared = _clear_text_field(field)
        except PlaywrightError as exc:
            # Fatal even for an unused slot (``value is None``): a click
            # failure does not distinguish "not rendered" from "obstructed
            # but still holding Yandex's AI copy" (issue #655 round-2
            # review, Codex) — and ``create_master`` clicks the terminal
            # LAUNCH button before ``_verify_created`` ever re-reads the
            # page, so a skipped-but-populated slot would publish unreviewed
            # copy from a live, no-rollback campaign before anyone finds out.
            target = f"{value!r}" if value is not None else "an unused slot"
            raise BrowserSessionError(
                f"Could not add {target} via the create page's field at "
                f"{selector!r} — Yandex may have changed the page's markup. "
                "Re-run with --headful to inspect the page."
            ) from exc

        if not cleared:
            raise BrowserSessionError(
                f"Could not clear the create page's field at {selector!r} "
                "before typing. Typing into a slot that still holds Yandex's "
                "AI-generated copy would splice the two together and launch "
                "ad copy you never reviewed, so this aborts instead. This "
                "usually means Playwright is older than 1.44 (the version "
                "that added the 'ControlOrMeta' modifier) — upgrade with "
                "'pip install -U playwright'."
            )

        if value is None:
            continue
        try:
            field.type(value)
        except PlaywrightError as exc:
            raise BrowserSessionError(
                f"Could not add {value!r} via the create page's field at "
                f"{selector!r} — Yandex may have changed the page's markup. "
                "Re-run with --headful to inspect the page."
            ) from exc


def _read_repeating_values(
    page: "Page", testid_template: str, slot_count: int
) -> List[str]:
    """Read every value currently held by a fixed-size repeating list field.

    Used by ``_verify_created`` to confirm ``_add_repeating_values`` actually
    persisted each value — mirrors ``update_master``'s ``_read_weekly_budget``
    etc. Reads each slot's ``.textarea`` contenteditable div via
    ``inner_text()`` (not ``input_value()`` — a contenteditable div has no
    ``value`` attribute, same as ``_fill_landing_url``'s field). An
    unreadable/missing slot is treated as an empty string rather than
    aborting the whole read, since a partial mismatch is exactly what the
    caller needs to see.
    """
    values = []
    for index in range(slot_count):
        selector = f'[data-testid="{testid_template.format(index=index)}"]'
        field = page.locator(selector).first
        try:
            values.append(field.inner_text())
        except PlaywrightError:
            values.append("")
    return values


def _set_repeating_value(
    page: "Page", testid_template: str, slot_count: int, index: int, value: str
) -> None:
    """Replace the value in ONE existing slot of a fixed-size repeating list
    field (headlines/texts), leaving every other slot untouched.

    Issue #665 (Этап B, part of the #648 umbrella). This is a DIFFERENT
    contract from ``_add_repeating_values``: that function clears and
    rewrites every slot (create-page semantics — Yandex pre-fills every slot
    with AI-generated copy, so a partial write there would publish leftover
    unreviewed variants). ``update_master`` is a partial-update command by
    project convention, and headline/text variant sets on a live campaign can
    be large — forcing the caller to re-type every other variant just to fix
    one typo is the opposite of what "partial update" means. So this module
    deliberately does NOT reuse ``_add_repeating_values`` here; it edits
    exactly the one requested slot.

    This is also a deliberate departure from this CLI's dominant list-field
    convention, where ``update`` commands replace the ENTIRE array in one
    shot (e.g. ``campaigns update --negative-keywords``, built via
    ``_array_of_string_option`` — see ``direct_cli/commands/
    _campaigns_base.py``). That convention exists because those fields go
    through the WSDL API's ``ArrayOfString`` semantics, where a full-array
    write is cheap and the array is typically short. Мастер кампаний has no
    API at all — every mutation is a live page edit — and forcing a
    full-list rewrite through five/three fixed slots would be both more
    error-prone (misordering a variant silently changes ad copy) and no
    safer than a targeted slot write. A future refactor MAY want to
    unify this with the rest of the CLI's list-update convention, but that
    is not settled and is explicitly out of scope here.

    Confirmed live (2026-08-02, campaign 107707079, read-only recon — see
    ``tests/fixtures/masters_wizard_edit_stage_b.html``) that the edit page's
    slots are IDENTICAL in shape and count to the create page's: same
    ``testid_template``, same ``slot_count`` (5 headlines / 3 texts), same
    contenteditable ``<div role="textbox">`` shape ``_clear_text_field``/
    ``_read_repeating_values`` already handle correctly.

    Writing to an EMPTY slot is refused (``BrowserSessionError``) rather
    than treated as "add a new variant" — that is a materially different
    operation (publishing a variant that did not exist before, on a page
    with no sandbox/rollback) tracked as a separate follow-up, not silently
    folded into "update an existing one".
    """
    if index >= slot_count:
        raise BrowserSessionError(
            f"Slot index {index + 1} is out of range — this field only has "
            f"{slot_count} slots on the edit page."
        )

    # Checked BEFORE the field is read or cleared: an empty replacement is a
    # DELETE, not a replace, and deleting a variant is out of scope for Этап
    # B (issue #665). It is also the silent kind of damage — the slot would
    # be cleared, "" typed, the form saved, and
    # ``_verify_repeating_value_mismatches`` would then compare the re-read
    # slot against the REQUESTED value, find "" == "", and report the
    # deletion as a successful update. The CLI refuses this earlier
    # (``_parse_repeating_slot_options``); this guard keeps the browser layer
    # safe for any other caller too.
    if not value.strip():
        raise BrowserSessionError(
            f"Refusing to write an empty value to slot {index + 1}: that "
            "would delete the existing ad variant rather than replace it, "
            "which this command does not support."
        )

    selector = f'[data-testid="{testid_template.format(index=index)}"]'
    field = page.locator(selector).first

    try:
        current = field.inner_text()
    except PlaywrightError as exc:
        raise BrowserSessionError(
            f"Could not read the current value of slot {index + 1} at "
            f"{selector!r} — Yandex may have changed the page's markup. "
            "Re-run with --headful to inspect the page."
        ) from exc

    if not current:
        raise BrowserSessionError(
            f"Slot {index + 1} at {selector!r} is currently empty. Writing "
            "to an empty slot would add a new ad variant, which this "
            "command does not support — only replacing an existing "
            "variant's text."
        )

    try:
        field.click()
        cleared = _clear_text_field(field)
    except PlaywrightError as exc:
        raise BrowserSessionError(
            f"Could not replace slot {index + 1}'s value via the edit "
            f"page's field at {selector!r} — Yandex may have changed the "
            "page's markup. Re-run with --headful to inspect the page."
        ) from exc

    if not cleared:
        raise BrowserSessionError(
            f"Could not clear slot {index + 1}'s existing value at "
            f"{selector!r} before typing the replacement. Typing without "
            "clearing would splice the new text into the old one. This "
            "usually means Playwright is older than 1.44 (the version that "
            "added the 'ControlOrMeta' modifier) — upgrade with "
            "'pip install -U playwright'."
        )

    try:
        field.type(value)
    except PlaywrightError as exc:
        raise BrowserSessionError(
            f"Could not type the replacement value into slot {index + 1} "
            f"at {selector!r} — Yandex may have changed the page's markup. "
            "Re-run with --headful to inspect the page."
        ) from exc


def _poll_until(
    page: "Page",
    predicate: "Callable[[], bool]",
    timeout_ms: int,
    *,
    tick_ms: int = 250,
    clock: "Optional[Callable[[], float]]" = None,
) -> bool:
    """Poll ``predicate`` until it is true or ``timeout_ms`` elapses.

    Returns ``True`` if the predicate became true, ``False`` on timeout, so
    each caller keeps its own (deliberately site-specific) ``BrowserSessionError``
    message rather than sharing a generic one.

    ``PlaywrightError`` from the predicate is suppressed and treated as
    "not yet" — a locator query racing a mid-render DOM is the normal case
    these loops exist to absorb.

    ``clock`` defaults to ``None``, meaning the package-wide clock
    (``_clock.now``, itself ``time.monotonic`` in production — issue #767),
    but can be swapped per-call for a fake clock in tests (issue #715):
    the previous hard-coded ``time.monotonic()`` measured real wall-clock
    time, so a test mocking ``page.wait_for_timeout`` as a no-op tick
    counter got a tick count purely determined by how many iterations the
    host CPU spun through before real time elapsed — non-deterministic
    under a loaded CI runner. A fake clock that only advances inside
    ``wait_for_timeout`` makes the deadline (and therefore the tick count)
    deterministic instead.
    """
    _now = clock or _clock.now
    deadline = _now() + timeout_ms / 1000
    while _now() < deadline:
        with contextlib.suppress(PlaywrightError):
            if predicate():
                return True
        page.wait_for_timeout(tick_ms)
    return False


def _read_testid_suffixes(
    page: "Page", prefix: str, *, skip_suffixes: "tuple[str, ...]" = ()
) -> List[str]:
    """Read every ``data-testid`` starting with ``prefix``, in DOM order,
    with ``prefix`` stripped off.

    Shared by the two image readers below — both scrape a testid prefix off
    ``page`` directly (matching every other reader in this module, which
    always locates by a single full ``data-testid`` selector rather than a
    scoped container + chained sub-locator).

    A locator failure yields ``[]`` rather than raising: for images an empty
    result is a legitimate state, and callers that need to distinguish it
    from "not rendered yet" wait for the section first
    (``_wait_for_images_editor``).
    """
    try:
        elements = page.locator(f'[data-testid^="{prefix}"]')
        count = elements.count()
    except PlaywrightError:
        return []

    suffixes = []
    for i in range(count):
        testid = elements.nth(i).get_attribute("data-testid")
        if not testid:
            continue
        suffix = testid[len(prefix) :]
        if skip_suffixes and suffix.endswith(skip_suffixes):
            continue
        suffixes.append(suffix)
    return suffixes


def _wait_for_edit_form(page: "Page", campaign_id: int) -> None:
    """Block until the edit page's form has actually rendered.

    Issue #684: every ``WIZARD_EDIT_URL`` navigation in this module now uses
    ``wait_until="commit"`` (fires as soon as the response starts arriving,
    before any redirect/parse/JS has happened) instead of the previous
    ``wait_until="domcontentloaded"`` — ``domcontentloaded`` on this SPA was
    observed to time out under real network conditions (the page's own
    long-poll connections can make even that early a lifecycle event hang;
    see the module's "The edit page is an SPA" comment on
    ``_IMAGES_EDITOR_TIMEOUT_MS`` for the same long-poll reasoning).
    ``commit`` never hangs on page-internal behaviour — it only waits on the
    network response itself — but it also guarantees nothing about the DOM,
    so every call site must wait for a real content marker afterwards
    instead of trusting the navigation call alone.

    Polls for ``_EDIT_FORM_READY_TESTID`` (the first headline slot) rather
    than a fixed sleep, same convention as ``_wait_for_step2``/
    ``_wait_for_images_editor``. Also re-checks for a captcha/login page on
    every tick (cycle-review #689 finding): the one-shot
    ``assert_not_captcha``/``assert_authenticated`` checks each call site
    runs right after ``goto(..., wait_until="commit")`` only see whatever
    the response committed with — a captcha gate or an expired-session
    redirect that the SPA's own JS renders in *after* that point would be
    invisible to those checks and would otherwise surface here as a
    generic timeout instead of the specific ``BrowserCaptchaError``/
    ``BrowserAuthError`` callers rely on to know not to retry a
    non-idempotent operation (e.g. ``_verify_saved_images``).

    The captcha/auth check happens OUTSIDE ``_poll_until``'s predicate
    (via ``_edit_form_terminal_state``, which returns a marker instead of
    raising) rather than inside it: ``_poll_until`` suppresses
    ``PlaywrightError``, which is aliased to the broad ``Exception`` when
    Playwright isn't installed (the offline-unit-test import fallback
    above) — in that environment a raise from inside the predicate would
    be silently swallowed as "not yet" instead of propagating, and this
    function would misreport a real captcha/auth failure as its own
    generic render-timeout.
    """
    state = _poll_until_terminal(
        page,
        lambda: _edit_form_terminal_state(page),
        _EDIT_FORM_READY_TIMEOUT_MS,
    )
    if state == "ready":
        return
    if state == "captcha":
        assert_not_captcha(page.content())  # re-raises BrowserCaptchaError
    if state == "auth":
        assert_authenticated(page.content())  # re-raises BrowserAuthError

    raise BrowserSessionError(
        f"The edit page for campaign {campaign_id} did not finish rendering "
        f"within {_EDIT_FORM_READY_TIMEOUT_MS / 1000:.0f}s (the "
        f"'{_EDIT_FORM_READY_TESTID}' field never appeared). Yandex may have "
        "changed the page's markup, the campaign may not exist, or the page "
        "may still be loading. Re-run with --headful to inspect the page."
    )


def _edit_form_terminal_state(page: "Page") -> "Optional[str]":
    """Predicate for ``_wait_for_edit_form``'s poll loop.

    Returns ``"ready"`` once the form marker is present, ``"captcha"``/
    ``"auth"`` if a captcha or login page appears instead, or ``None`` to
    keep polling. Deliberately returns rather than raises — see
    ``_wait_for_edit_form``'s docstring for why the caller re-runs
    ``assert_not_captcha``/``assert_authenticated`` itself, outside the
    poll loop, to actually raise.
    """
    html = page.content()
    if find_captcha_marker(html) is not None:
        return "captcha"
    if find_marker(html, _LOGIN_PAGE_MARKERS) is not None:
        return "auth"
    if page.locator(f'[data-testid="{_EDIT_FORM_READY_TESTID}"]').count() > 0:
        return "ready"
    return None


def _poll_until_terminal(
    page: "Page",
    predicate: "Callable[[], Optional[str]]",
    timeout_ms: int,
    *,
    tick_ms: int = 250,
    clock: "Optional[Callable[[], float]]" = None,
) -> "Optional[str]":
    """Like ``_poll_until``, but for a predicate returning a terminal-state
    string (truthy, non-``None``) instead of a bare bool.

    Used where the poll loop must distinguish several ready-to-stop states
    (e.g. "form rendered" vs. "captcha appeared") rather than a single
    true/false — see ``_edit_form_terminal_state``. ``PlaywrightError`` is
    suppressed the same way ``_poll_until`` does, for the same reason (a
    locator query racing a mid-render DOM is expected, not a failure).

    ``clock`` defaults to the package-wide clock (``_clock.now``) — see
    ``_poll_until``'s docstring (issues #715/#767) for why this is
    injectable.
    """
    _now = clock or _clock.now
    deadline = _now() + timeout_ms / 1000
    while _now() < deadline:
        with contextlib.suppress(PlaywrightError):
            state = predicate()
            if state is not None:
                return state
        page.wait_for_timeout(tick_ms)
    return None


def _wait_for_images_editor(page: "Page") -> None:
    """Block until the edit page's "Изображения" section has rendered ITS
    ACTUAL CONTENT, not just its outer container.

    The edit page is a client-rendered SPA — ``goto(...,
    wait_until="domcontentloaded")`` (what every entry point in this module
    uses, deliberately: Yandex holds long-poll connections, so
    ``networkidle`` never settles) returns while this section is still
    absent from the DOM.

    Without this wait, ``_read_image_content_ids`` returns ``[]`` for a
    campaign that simply has not rendered yet, and an empty list is
    INDISTINGUISHABLE from the legitimate "this campaign has no images"
    state (images are optional — unlike headlines/texts). Live-confirmed
    2026-08-02: four consecutive DRAFT campaigns were reported as having no
    images by ``masters update --image`` while the very same edit pages
    demonstrably rendered four ``ContentImage`` elements each.

    **Two-stage render, confirmed live 2026-08-03 (campaigns 713234191 and
    713234204, both with 4 real images):** ``ImageSuggestionsEditor`` itself
    (the selector this function used to wait on exclusively) appears FIRST
    with four ``ImageSuggestionsEditor.CampaignContents.StubN`` loading
    placeholders and NEITHER ``ContentImage.*`` nor ``.Open`` present yet —
    then, roughly 3s later, the stubs are replaced by the real content.
    Returning as soon as the outer container exists (the original
    ``_IMAGES_EDITOR_SELECTOR``-only check) reproduces the exact bug this
    function's docstring already describes, just one render stage later:
    ``masters adimages get`` on one of the campaigns above reported
    ``Count: 0`` for a campaign that demonstrably has 4 images, and a
    subsequent ``adimages add`` then uploaded into what it believed was an
    empty set and timed out, because the true starting panel size was wrong.
    This function now also polls until no ``_IMAGES_STUB_TESTID_PREFIX``
    element remains, so a caller never observes the mid-render stub state.

    **Third render stage, root-caused live 2026-08-03 for issue #687 (both
    campaigns above, 6 independent repeat runs, both with 5 real images by
    the time of this investigation):** BEFORE the ``StubN`` round described
    above even begins, ``ImageSuggestionsEditor`` briefly mounts a first
    time with ``.Open`` present but ZERO ``StubN`` and ZERO ``ContentImage``
    elements — a stale/ghost render, most likely the section's own
    "collapsed" resting state re-appearing for one paint before the real
    data fetch kicks off, not a genuine settle. This ghost pass never shows
    a single ``StubN`` element; the real pass always does. Observed
    live 2026-08-03: the ghost pass alone can last from under a second up to
    ~14.5s, and the check that existed before this fix — "editor present AND
    zero ``StubN``" — is trivially true throughout it, so it is
    indistinguishable from a real settle by DOM shape alone. This is exactly
    the false-negative-to-false-positive drift #673 already fixed one render
    stage earlier (empty container -> unsettled stub round), one stage
    earlier still: ``masters adimages get``/``update --image`` calling
    ``_wait_for_images_editor`` at that instant would read ``[]`` for a
    campaign confirmed live to have 5 images, reproducing #687's exact
    "no images" false negative. Confirmed by direct instrumentation of this
    function, unmodified, before the fix below: it returned within ~4s with
    ``_read_image_content_ids`` reading ``[]`` on a campaign with 5 images,
    100% reproducible across 3 consecutive live runs.

    The fix cannot be a fixed debounce window — the ghost pass's observed
    duration (under 1s to ~14.5s) makes any fixed wait either too short
    (still catches the ghost) or too close to the whole timeout budget (too
    slow). Instead "no ``StubN``" is only trusted once ANY of:

    (a) at least one real ``StubN`` element has actually been observed
        first — the ghost pass never produces one;
    (b) ``ContentImage`` elements are already present — confirmed live:
        their count is always 0 throughout the ghost pass, so their
        presence is never a false positive, and this also covers a
        campaign whose images were already loaded with no stub round at
        all (e.g. a fast-enough fetch, or a repeat read on an
        already-hydrated page — the shape every other test in this class
        exercises);
    (c) the "editor present, no ``StubN``, no ``ContentImage``" reading
        holds continuously for ``_IMAGES_GHOST_GRACE_S`` — the ghost pass
        and a genuinely empty image set are otherwise indistinguishable by
        DOM shape at a single instant (images are legitimately optional —
        see ``_IMAGES_MAX_COUNT``'s module comment), so a truly empty
        campaign is only trusted once that reading has outlasted the
        ghost pass's worst observed duration, at the cost of paying that
        wait once per edit-page visit.

    Verified live 2026-08-03: 11/11 repeat runs across both non-empty
    campaigns (after correcting an initial false-negative batch that turned
    out to be testing a stale editable install pointing at a different
    checkout — see the worktree caveat below) settle on the correct, stable
    image count via (a)/(b), with a worst observed combined ghost+real
    timeline of 43.6s (see ``_IMAGES_EDITOR_TIMEOUT_MS``'s bump to
    accommodate it with margin). Path (c) has no live test campaign with a
    genuinely empty image set available at investigation time (every DRAFT
    campaign on the verification account already had images) — its
    correctness rests on the offline fixture in
    ``tests/test_masters.py::TestWaitForImagesEditor`` and the invariant
    that the ghost pass never lasted longer than ~14.5s across every run
    observed. If a live campaign with zero images later shows a ghost pass
    longer than ``_IMAGES_GHOST_GRACE_S``, this path would misreport "no
    images" prematurely — re-verify against one if hydration issues
    resurface on empty-image campaigns specifically.

    **Re-verified live 2026-08-03 in combination with PR #689 (issue #695):**
    the live verification above originally ran before PR #689 landed
    ``wait_until="commit"`` + ``_wait_for_edit_form`` on the other three
    ``WIZARD_EDIT_URL`` navigation sites. After rebasing this fix onto
    #689, direct instrumentation of both campaigns (post-``_wait_for_edit_form``,
    reading the same ``editor``/``stub``/``content`` counts this function
    itself checks) confirmed the same three-stage render — ghost pass
    (≤2.3s here), a real ``StubN`` round, then content — settling within
    ~3-6s, well inside the ``_IMAGES_GHOST_GRACE_S``/timeout budget. 8
    subsequent ``masters adimages get`` runs across both campaigns (via
    this fixed code, not the pre-#687 guard) all correctly read 5 images
    each, elapsed 12.3s-28.1s. No occurrence of #695's original symptom
    (section stuck at ``children == 0`` for 20+ seconds with no stub round
    ever appearing) was observed in this combined verification — #695's
    concern was a reasonable one to raise pending confirmation, but did
    not reproduce here.

    Absence of the section (or persistence of the stub state, or a settle
    declared before any ``StubN`` round was ever observed) after the timeout
    is reported as a hard error rather than silently treated as "no images",
    for the same reason.
    """

    stubs_ever_seen = False
    empty_since: Optional[float] = None

    def _content_settled() -> bool:
        nonlocal stubs_ever_seen, empty_since
        if page.locator(_IMAGES_EDITOR_SELECTOR).first.count() == 0:
            empty_since = None
            return False
        stub_count = page.locator(
            f'[data-testid^="{_IMAGES_STUB_TESTID_PREFIX}"]'
        ).count()
        if stub_count > 0:
            stubs_ever_seen = True
            empty_since = None
            return False
        if stubs_ever_seen:
            # A real StubN round has already been observed and cleared —
            # this "no StubN" reading is trustworthy regardless of content
            # count (zero is the legitimate "campaign has no images" state).
            return True
        content_count = page.locator(
            f'[data-testid^="{_IMAGES_CONTENT_TESTID_PREFIX}"]'
        ).count()
        if content_count > 0:
            # Confirmed live: content count is always 0 throughout the ghost
            # pass (see the docstring note above), so its presence here is
            # never a false positive — this is a campaign whose images were
            # already loaded server-side with no stub round at all.
            return True
        # No StubN round has ever been seen AND there is no content yet —
        # this is EITHER the ghost pass (transient, confirmed live to last
        # up to ~14.5s) OR a campaign that genuinely has zero images and
        # settled straight into that state with no stub round to observe.
        # These are indistinguishable by DOM shape alone at a single instant,
        # so require this exact state (no editor mutation observed) to hold
        # continuously for `_IMAGES_GHOST_GRACE_S` before trusting it — long
        # enough to outlast the ghost pass, short enough not to matter for a
        # page that is genuinely already settled.
        now = _clock.now()
        if empty_since is None:
            empty_since = now
            return False
        return (now - empty_since) >= _IMAGES_GHOST_GRACE_S

    if _poll_until(page, _content_settled, _IMAGES_EDITOR_TIMEOUT_MS):
        return

    raise BrowserSessionError(
        "The edit page's 'Изображения' section did not finish rendering "
        f"within {_IMAGES_EDITOR_TIMEOUT_MS / 1000:.0f}s (it may still be "
        "showing loading placeholders), so this command cannot tell "
        "whether the campaign has images or not. Yandex may have changed "
        "the page's markup, or the page may still be loading. Re-run with "
        "--headful to inspect the page."
    )


def _read_image_content_ids(page: "Page") -> List[str]:
    """Read the campaign's current image set as an ordered list of Yandex
    content IDs.

    Unlike ``_read_repeating_values`` (headlines/texts), there is no fixed
    slot count to iterate — the edit page renders exactly as many
    ``ImageSuggestionsEditor.CampaignContents.ContentImage.<contentId>``
    elements as the campaign actually has images, in DOM order (confirmed
    live 2026-08-02, campaign 713234191, stable across reloads). An EMPTY
    list is a valid, normal result — images are optional, unlike headlines/
    texts which always have at least one variant.

    A broken/unloaded thumbnail does not affect this: the ``ContentImage``
    element (and its ``data-testid``) is present in the DOM regardless of
    whether the underlying thumb URL actually rendered — confirmed live,
    2 of 4 images had a broken-image icon while still being fully valid,
    counted images. So content ID, never the thumb URL's load state, is the
    only thing this reads.

    Selects directly off ``page`` by the ``ContentImage`` testid prefix
    (matching every other reader in this module — ``_read_repeating_values``
    etc. — which always locates by a single full ``data-testid`` selector,
    never a scoped container + chained sub-locator).
    """
    return _read_testid_suffixes(page, _IMAGES_CONTENT_TESTID_PREFIX)


def _open_images_modal(page: "Page") -> None:
    """Click "Выбрать другие изображения" and wait for the image manager
    modal to actually render.

    Confirmed live 2026-08-02: the modal (``ImageSuggestionsEditorModal``) is
    not in the DOM at all until this button is clicked — a fresh element,
    not merely hidden — so this must poll for its appearance rather than
    assume the click was synchronous.
    """
    open_button = page.locator(_IMAGES_OPEN_MODAL_SELECTOR).first
    try:
        open_button.click()
    except PlaywrightError as exc:
        raise BrowserSessionError(
            "Could not find/click the 'Выбрать другие изображения' button — "
            "Yandex may have changed the page's markup. Re-run with "
            "--headful to inspect the page."
        ) from exc

    if _poll_until(
        page,
        lambda: page.locator(_IMAGES_MODAL_SELECTOR).first.count() > 0,
        _IMAGE_MODAL_OPEN_TIMEOUT_MS,
    ):
        return

    raise BrowserSessionError(
        "Clicked 'Выбрать другие изображения' but the image manager modal "
        f"did not appear within {_IMAGE_MODAL_OPEN_TIMEOUT_MS / 1000:.0f}s "
        "— Yandex may have changed the page's markup. Re-run with "
        "--headful to inspect the page."
    )


def _read_modal_selected_thumb_urls(page: "Page") -> List[str]:
    """Read the image manager modal's right-hand "Выбранные изображения"
    panel as an ordered list of thumb URLs.

    Confirmed live 2026-08-02: this panel's DOM order matches the edit
    page's own image order exactly (same 4 thumb URLs, same sequence) — so
    the Nth entry here corresponds to the Nth ``ContentImage`` on the page,
    letting slot index N map onto this panel positionally without ever
    needing to correlate a content ID with a thumb URL.

    Selects directly off ``page``, same reasoning as
    ``_read_image_content_ids``.

    Each card renders THREE testids sharing the same thumb-URL prefix (the
    card itself, ``.Content``, ``.CloseButton`` — confirmed live) — only the
    bare thumb URL (no further ``.`` suffix) identifies one distinct image;
    the sub-elements would otherwise be double-counted, hence the skip list.
    """
    return _read_testid_suffixes(
        page,
        _IMAGES_MODAL_SELECTED_PREFIX,
        skip_suffixes=(".Content", ".CloseButton"),
    )


def _set_image(page: "Page", index: int, path: str, *, target_content_id: str) -> None:
    """Replace the image identified by ``target_content_id`` — the image
    originally at position ``index`` (0-based) when the caller snapshotted
    the set, before any of this call's siblings ran — with the file at
    ``path``.

    Issue #670 (Этап D, part of the #648 umbrella). Unlike headlines/texts'
    ``_set_repeating_value``, Yandex has no "replace this slot" primitive at
    all for images — only "remove from the set" and "add to the set", both
    inside the ``ImageSuggestionsEditorModal`` opened via ``_open_images_modal``.
    This function composes the two into one synthetic point-replacement:

    1. Locate ``target_content_id`` in the current set; refuse if the set is
       empty (images are optional — unlike headlines/texts, a campaign can
       legitimately have zero) or if that content ID is no longer present
       (it must always be found on the FIRST replacement in a batch; a
       later one going missing means an earlier replacement in the same
       call already removed it — a caller bug, not a live-page race, so
       this raises rather than silently no-op'ing).
    2. Open the modal.
    3. Remove that image's card from the modal's right-hand panel
       (confirmed live: this panel's order matches the page's image order
       positionally — see ``_read_modal_selected_thumb_urls`` — but this
       function locates by content ID, not by re-deriving a position, so it
       is immune to any prior reordering within the same ``update_master``
       call).
    4. Upload the new file via the modal's hidden file input.
    5. Poll for the new card to appear in the panel — Yandex processes the
       upload asynchronously before it shows up there (confirmed live: not
       instant).
    6. Click "Добавить в кампанию" (Save) to commit the whole modal
       operation back onto the edit page in one shot.

    **Confirmed live 2026-08-02, campaign 713234191 (real DOM mutation,
    Save never clicked, page abandoned afterwards — no campaign mutation):
    a newly uploaded image is always appended to the END of the set, never
    inserted at the freed position.** So this is NOT a literal positional
    replacement — replacing position 2 of ``[A, B, C, D]`` yields
    ``[A, C, D, NEW]``, not ``[A, NEW, C, D]``. The set's order carries no
    product meaning (Yandex rotates/biases images by performance regardless
    of position), so this is a cosmetic limitation, not a functional one —
    but callers (the CLI help text, README, CHANGELOG) MUST say so rather
    than imply a true positional swap.

    **``index`` is used only for user-facing error messages — never to
    locate the image to remove.** A previous version resolved ``index``
    against the LIVE, already-reordered set on each call; since a
    replacement always appends to the end, a second ``--image`` in the same
    ``update_master`` call would silently resolve against a set that had
    already shifted because of the first, removing a DIFFERENT image than
    the one the caller named — found independently by two reviewers in
    cycle-review round 1 of PR #670/#672, and reproduced via
    ``tests/test_masters.py::test_update_master_replaces_multiple_images_by_original_position``.
    ``target_content_id`` is resolved once, by the caller
    (``update_master``), against the set as it stood before any
    replacement in the batch ran, closing that gap.

    Because both the removal and the upload happen inside the same open
    modal, a failure at any point before ``Save`` leaves the campaign's
    actual saved image set untouched — the modal can simply be abandoned
    (``Cancel`` or navigating away), unlike a mid-way failure that had
    already committed a change to the live page.
    """
    # Must precede the read: an empty result is only meaningful once the
    # section has actually rendered (see _wait_for_images_editor).
    _wait_for_images_editor(page)
    current_ids = _read_image_content_ids(page)

    if not current_ids:
        raise BrowserSessionError(
            "This campaign has no images — there is nothing to replace. "
            "Adding a brand-new image (to an empty set) is not supported "
            "by this command."
        )

    if index >= len(current_ids):
        raise BrowserSessionError(
            f"Image position {index + 1} is out of range — this campaign "
            f"currently has {len(current_ids)} image(s) "
            f"(positions 1-{len(current_ids)})."
        )

    if target_content_id not in current_ids:
        raise BrowserSessionError(
            f"Image position {index + 1} (content ID {target_content_id}) "
            "is no longer present in the campaign's image set — an earlier "
            "--image replacement in this same command already removed it. "
            "Re-run with the remaining --image flags only, after checking "
            "the campaign's current image set."
        )

    _open_images_modal(page)

    before_urls = _read_modal_selected_thumb_urls(page)
    modal_ids = _read_image_content_ids(page)
    if target_content_id not in modal_ids or len(modal_ids) != len(before_urls):
        raise BrowserSessionError(
            f"Image position {index + 1} (content ID {target_content_id}) "
            f"could not be matched inside the image manager modal — it "
            f"shows {len(before_urls)} selected image(s), which does not "
            f"match the {len(current_ids)} shown on the edit page itself. "
            "Yandex may have changed the page's markup. Re-run with "
            "--headful to inspect the page."
        )
    target_url = before_urls[modal_ids.index(target_content_id)]

    remove_selector = (
        f'[data-testid="'
        f"{_IMAGES_MODAL_REMOVE_TESTID_TEMPLATE.format(thumb_url=target_url)}"
        f'"]'
    )
    try:
        page.locator(remove_selector).first.click()
    except PlaywrightError as exc:
        raise BrowserSessionError(
            f"Could not remove the image at position {index + 1} inside "
            "the image manager modal — Yandex may have changed the page's "
            "markup. Re-run with --headful to inspect the page. The "
            "campaign's saved image set has NOT been changed (the modal "
            "was never saved)."
        ) from exc

    if not _poll_until(
        page,
        lambda: target_url not in _read_modal_selected_thumb_urls(page),
        _IMAGE_MODAL_OPEN_TIMEOUT_MS,
    ):
        raise BrowserSessionError(
            f"Clicked to remove the image at position {index + 1} inside "
            "the image manager modal, but it is still shown there after "
            f"{_IMAGE_MODAL_OPEN_TIMEOUT_MS / 1000:.0f}s. The campaign's "
            "saved image set has NOT been changed (the modal was never "
            "saved) — close the browser and retry."
        )

    try:
        page.locator(_IMAGES_MODAL_FILE_INPUT_SELECTOR).first.set_input_files(path)
    except PlaywrightError as exc:
        raise BrowserSessionError(
            f"Could not upload {path!r} inside the image manager modal — "
            "Yandex may have changed the page's markup. Re-run with "
            "--headful to inspect the page. The campaign's saved image set "
            "has NOT been changed (the modal was never saved)."
        ) from exc

    # One image was just removed, so the post-removal panel holds
    # ``len(before_urls) - 1``; the upload has landed once the panel grows
    # back to at least its original size.
    if not _poll_until(
        page,
        lambda: len(_read_modal_selected_thumb_urls(page)) >= len(before_urls),
        _IMAGE_UPLOAD_TIMEOUT_MS,
    ):
        raise BrowserSessionError(
            f"Uploaded {path!r} inside the image manager modal, but no new "
            f"image appeared there within {_IMAGE_UPLOAD_TIMEOUT_MS / 1000:.0f}s "
            "— Yandex's asynchronous processing may have failed or be "
            "unusually slow. The campaign's saved image set has NOT been "
            "changed (the modal was never saved) — close the browser and "
            "retry."
        )

    try:
        page.locator(_IMAGES_MODAL_SAVE_SELECTOR).first.click()
    except PlaywrightError as exc:
        raise BrowserSessionError(
            "Could not find/click 'Добавить в кампанию' to commit the "
            "image manager modal — Yandex may have changed the page's "
            "markup. Re-run with --headful to inspect the page. The "
            "campaign's saved image set has NOT been changed (the modal "
            "was never saved)."
        ) from exc

    if _poll_until(
        page,
        lambda: page.locator(_IMAGES_MODAL_SELECTOR).first.count() == 0,
        _IMAGE_MODAL_OPEN_TIMEOUT_MS,
    ):
        return

    raise BrowserSessionError(
        "Clicked 'Добавить в кампанию' but the image manager modal did not "
        f"close within {_IMAGE_MODAL_OPEN_TIMEOUT_MS / 1000:.0f}s — the "
        "commit may not have completed. Verify manually before retrying."
    )


def _apply_image_operations(
    page: "Page",
    *,
    remove_content_ids: "Sequence[str]",
    upload_paths: "Sequence[str]",
) -> None:
    """Remove zero or more images and upload zero or more files inside ONE
    open/Save cycle of the image manager modal.

    Unlike ``_set_image`` (one open/remove/upload/Save cycle PER call — left
    untouched, still what ``update_master``'s ``--image`` point-replacement
    uses), this is the bulk primitive for ``masters adimages add/delete/
    set``: open the modal once, perform every removal, perform every
    upload, then click "Добавить в кампанию" exactly once. Composed from
    the same two Yandex primitives ``_set_image`` uses — "remove from the
    set" and "add to the set" — there being no bulk endpoint either.

    Nothing is committed to the campaign's saved image set until the single
    Save click at the end; a failure at any earlier point leaves the saved
    set untouched (same abandon-safe property as ``_set_image``).

    An empty ``remove_content_ids``/``upload_paths`` pair (both empty) is a
    no-op — the modal is never opened. Removing every image so the set ends
    up EMPTY, or uploading into a campaign that currently has none, are both
    legitimate outcomes (unlike headlines/texts, images have no "at least
    one" invariant — see ``_IMAGES_MAX_COUNT``'s module-level comment).

    Confirmed live 2026-08-03 on DRAFT campaign 713234191: Yandex's
    "Добавить в кампанию" button stays clickable when the modal's selection
    is reduced to zero mid-session (the ``delete``-everything /
    ``set``-with-nothing-kept case) — this was the primitive's one
    previously-unverified risk, exercised via ``masters adimages delete
    --all`` and ``masters adimages set --allow-empty``.

    **Not live-verified:** uploading via a single ``set_input_files([path1,
    path2, ...])`` call with multiple paths — real Playwright accepts a
    list, but PR #672's recon never exercised it, so this uploads strictly
    one path per call, sequentially, to stay on already-confirmed ground.

    Removals are located by the target's thumb URL, captured from the
    modal's panel BEFORE any removal in this call runs — exactly the
    ``target_content_id`` → thumb-URL resolution ``_set_image`` already
    does — so a later removal in the same batch is never thrown off by the
    panel's re-indexing as earlier cards disappear.

    Uploads are waited for via an ABSOLUTE expected panel size (the size
    after all removals, plus one per upload so far), not ``_set_image``'s
    relative "grew back to at least the original size" check — that only
    happens to work for an exact 1-removed/1-added swap and would under- or
    over-count for any other combination.
    """
    if not remove_content_ids and not upload_paths:
        return

    _open_images_modal(page)

    panel_urls = _read_modal_selected_thumb_urls(page)
    modal_ids = _read_image_content_ids(page)
    if len(modal_ids) != len(panel_urls):
        raise BrowserSessionError(
            f"The image manager modal shows {len(panel_urls)} selected "
            f"image(s), which does not match the {len(modal_ids)} shown on "
            "the edit page itself. Yandex may have changed the page's "
            "markup. Re-run with --headful to inspect the page."
        )
    url_by_content_id = dict(zip(modal_ids, panel_urls))

    for content_id in remove_content_ids:
        target_url = url_by_content_id.get(content_id)
        if target_url is None:
            raise BrowserSessionError(
                f"Content ID {content_id!r} is not present in the image "
                "manager modal's current selection — it may already have "
                "been removed earlier in this same command. The "
                "campaign's saved image set has NOT been changed (the "
                "modal was never saved)."
            )

        remove_selector = (
            f'[data-testid="'
            f"{_IMAGES_MODAL_REMOVE_TESTID_TEMPLATE.format(thumb_url=target_url)}"
            f'"]'
        )
        try:
            page.locator(remove_selector).first.click()
        except PlaywrightError as exc:
            raise BrowserSessionError(
                f"Could not remove image {content_id!r} inside the image "
                "manager modal — Yandex may have changed the page's "
                "markup. Re-run with --headful to inspect the page. The "
                "campaign's saved image set has NOT been changed (the "
                "modal was never saved)."
            ) from exc

        if not _poll_until(
            page,
            lambda target_url=target_url: target_url
            not in _read_modal_selected_thumb_urls(page),
            _IMAGE_MODAL_OPEN_TIMEOUT_MS,
        ):
            raise BrowserSessionError(
                f"Clicked to remove image {content_id!r} inside the image "
                "manager modal, but it is still shown there after "
                f"{_IMAGE_MODAL_OPEN_TIMEOUT_MS / 1000:.0f}s. The "
                "campaign's saved image set has NOT been changed (the "
                "modal was never saved) — close the browser and retry."
            )

    base_count = len(panel_urls) - len(remove_content_ids)
    for expected_count, path in enumerate(upload_paths, start=base_count + 1):
        try:
            page.locator(_IMAGES_MODAL_FILE_INPUT_SELECTOR).first.set_input_files(path)
        except PlaywrightError as exc:
            raise BrowserSessionError(
                f"Could not upload {path!r} inside the image manager modal "
                "— Yandex may have changed the page's markup. Re-run with "
                "--headful to inspect the page. The campaign's saved image "
                "set has NOT been changed (the modal was never saved)."
            ) from exc

        if not _poll_until(
            page,
            lambda expected_count=expected_count: len(
                _read_modal_selected_thumb_urls(page)
            )
            >= expected_count,
            _IMAGE_UPLOAD_TIMEOUT_MS,
        ):
            raise BrowserSessionError(
                f"Uploaded {path!r} inside the image manager modal, but no "
                "new image appeared there within "
                f"{_IMAGE_UPLOAD_TIMEOUT_MS / 1000:.0f}s — Yandex's "
                "asynchronous processing may have failed or be unusually "
                "slow. The campaign's saved image set has NOT been changed "
                "(the modal was never saved) — close the browser and "
                "retry."
            )

    try:
        page.locator(_IMAGES_MODAL_SAVE_SELECTOR).first.click()
    except PlaywrightError as exc:
        raise BrowserSessionError(
            "Could not find/click 'Добавить в кампанию' to commit the "
            "image manager modal — Yandex may have changed the page's "
            "markup. Re-run with --headful to inspect the page. The "
            "campaign's saved image set has NOT been changed (the modal "
            "was never saved)."
        ) from exc

    if _poll_until(
        page,
        lambda: page.locator(_IMAGES_MODAL_SELECTOR).first.count() == 0,
        _IMAGE_MODAL_OPEN_TIMEOUT_MS,
    ):
        return

    raise BrowserSessionError(
        "Clicked 'Добавить в кампанию' but the image manager modal did not "
        f"close within {_IMAGE_MODAL_OPEN_TIMEOUT_MS / 1000:.0f}s — the "
        "commit may not have completed. Verify manually before retrying."
    )


def _verify_image_mismatches(
    page: "Page", *, before_ids: List[str], replaced_ids: Set[str]
) -> List[str]:
    """Re-read the campaign's saved image set and confirm every replaced
    image is actually gone and every untouched image is still present.

    Unlike ``_verify_repeating_value_mismatches``, this is NOT a positional
    comparison — a newly uploaded image always lands at the end of the set
    (see ``_set_image``'s docstring), so "position N now shows something
    different" is not a meaningful check. What IS meaningful, and what
    Yandex's silent-validation-rejection failure mode (module docstring)
    would actually break, is: (a) every content ID this call meant to
    replace is gone from the saved set, (b) every content ID it did NOT
    touch is still there, and (c) the set size is unchanged (removed count
    == added count). A rejected/failed upload would leave a replaced ID
    still present, which (a) catches.

    Thin wrapper over ``_verify_image_set_mismatches``: a point replacement
    is that general absolute-end-state check with ``expected_added_count``
    pinned to ``len(replaced_ids)``. Kept as its own function because
    ``update_master``/``_verify_saved`` call it with the before/replaced
    vocabulary, and because the empty-``replaced_ids`` early return is
    specific to ``--image`` (nothing requested ⇒ nothing to verify),
    whereas the general version must still assert an empty end state for
    ``adimages delete --all``.
    """
    if not replaced_ids:
        return []

    # A point replacement is the special case of the general absolute
    # end-state check where exactly as many images are added back as were
    # removed, so this delegates rather than repeating the three checks.
    # ``_verify_image_set_mismatches`` performs the ``_wait_for_images_editor``
    # settle its own callers need for the same post-reload reason.
    return _verify_image_set_mismatches(
        page,
        expected_kept_ids=[cid for cid in before_ids if cid not in replaced_ids],
        removed_ids=replaced_ids,
        expected_added_count=len(replaced_ids),
    )


def _verify_image_set_mismatches(
    page: "Page",
    *,
    expected_kept_ids: List[str],
    removed_ids: Set[str],
    expected_added_count: int,
) -> List[str]:
    """Re-read the campaign's saved image set and confirm it matches an
    ABSOLUTE expected end state: every ``removed_ids`` gone, every
    ``expected_kept_ids`` still present, and the total size equal to
    ``len(expected_kept_ids) + expected_added_count``.

    Sibling of ``_verify_image_mismatches`` (left untouched — ``update_master``
    /``_verify_saved`` and ``TestVerifyImageMismatches`` depend on its exact
    signature), generalizing that function's hardcoded "removed count ==
    added count" assumption for ``masters adimages add/delete/set``, where
    the two counts routinely differ (e.g. deleting 3 and adding 0, or
    deleting all N and adding M). Uploaded images get a Yandex-assigned
    content ID that is not known ahead of time, so newly added images are
    verified by COUNT only, never by identity — a real limitation of this
    browser surface, not an oversight.

    Unlike ``_verify_image_mismatches``, this does NOT early-return when
    ``removed_ids`` is empty — ``expected_kept_ids=[]`` with
    ``expected_added_count=0`` (the ``delete --all`` / ``set`` with no
    files case) must still assert the saved set is actually empty.
    """
    # ``_verify_saved_images`` re-navigates before calling this, so the
    # section is once again mid-render — reading straight away would
    # report every image as missing (see ``_wait_for_images_editor``).
    _wait_for_images_editor(page)
    actual_ids = set(_read_image_content_ids(page))

    mismatches = []
    still_present = sorted(removed_ids & actual_ids)
    if still_present:
        mismatches.append(
            "image(s) that should have been removed are still present: "
            + ", ".join(still_present)
        )
    missing_kept = sorted(cid for cid in expected_kept_ids if cid not in actual_ids)
    if missing_kept:
        mismatches.append(
            "image(s) that should have been left untouched are now "
            "missing: " + ", ".join(missing_kept)
        )
    expected_size = len(expected_kept_ids) + expected_added_count
    if len(actual_ids) != expected_size:
        mismatches.append(
            f"image set now has {len(actual_ids)} image(s), expected "
            f"{expected_size}"
        )
    return mismatches


def _save_and_verify_images(
    page: "Page",
    campaign_id: int,
    *,
    is_draft: bool,
    expected_kept_ids: List[str],
    removed_ids: Set[str],
    expected_added_count: int,
    launch: bool,
    not_idempotent_noun: str,
) -> List[str]:
    """Click the edit page's terminal save, then confirm the saved image
    set matches the expected end state; return the fresh content ID list.

    The whole post-``_apply_image_operations`` tail shared by
    ``add_master_images``/``delete_master_images``/``set_master_images``:
    resolve the draft-aware button label, click it, verify, and translate a
    mid-verification session expiry into a "do NOT retry" error (these
    commands are not idempotent, so ``_with_session``'s auto-retry must not
    re-run them — same reasoning as ``update_master``'s own wrapper).
    ``not_idempotent_noun`` is the phrase naming what was already applied
    ("image uploads", "image deletions", ...).

    ``is_draft`` MUST be the caller's ``_open_images_editor`` reading, taken
    right after ``_wait_for_edit_form`` — NOT re-derived here. Re-deriving it
    at this point would read the DOM only after ``_apply_image_operations``
    (uploads/removals) has already run, landing back inside the same #726
    DOM-flap race ``_click_save``'s ``is_draft`` contract exists to close.
    """
    clicked_button_label = (
        (_LAUNCH_BUTTON_TEXT if launch else _SAVE_DRAFT_BUTTON_TEXT)
        if is_draft
        else _SAVE_BUTTON_TEXT
    )
    _click_save(page, campaign_id, is_draft=is_draft, launch=launch)

    try:
        return _verify_saved_images(
            page,
            campaign_id,
            expected_kept_ids=expected_kept_ids,
            removed_ids=removed_ids,
            expected_added_count=expected_added_count,
            clicked_button_label=clicked_button_label,
        )
    except BrowserAuthError as exc:
        raise BrowserSessionError(
            f"Clicked '{clicked_button_label}' for campaign {campaign_id}, "
            "but the session was invalidated while verifying the save — "
            "the requested changes were likely already applied; check "
            f"campaign {campaign_id} manually rather than retrying "
            f"({not_idempotent_noun} are not idempotent)."
        ) from exc


def _verify_saved_images(
    page: "Page",
    campaign_id: int,
    *,
    expected_kept_ids: List[str],
    removed_ids: Set[str],
    expected_added_count: int,
    clicked_button_label: str,
) -> List[str]:
    """Reload the edit page, confirm the saved image set matches the
    expected end state, and return the fresh content ID list on success.

    Shared post-save verification for ``add_master_images``/
    ``delete_master_images``/``set_master_images`` — mirrors
    ``_verify_saved``'s re-navigate-and-re-read discipline (never trust the
    save click alone; Yandex's client-side validation can silently reject
    a value) but scoped to just the image set, via
    ``_verify_image_set_mismatches``.
    """
    url = WIZARD_EDIT_URL.format(campaign_id=campaign_id)
    page.goto(url, wait_until="commit")
    assert_not_captcha(page.content())
    assert_authenticated(page.content())
    _wait_for_edit_form(page, campaign_id)

    mismatches = _verify_image_set_mismatches(
        page,
        expected_kept_ids=expected_kept_ids,
        removed_ids=removed_ids,
        expected_added_count=expected_added_count,
    )
    if mismatches:
        raise BrowserSessionError(
            f"Clicked '{clicked_button_label}' for campaign {campaign_id}, "
            "but re-reading the saved campaign shows: "
            + "; ".join(mismatches)
            + ". Yandex may have rejected the change without a visible "
            "error — check the campaign manually."
        )
    return _read_image_content_ids(page)


def _set_region(
    page: "Page", regions: "Sequence[Union[str, Tuple[str, Optional[int]]]]"
) -> None:
    """Select each of ``regions`` in the "Регион показов" tree/tag widget.

    Issue #653 re-recon, 2026-08-02: Yandex replaced the old text-combobox
    (a single input with an autocomplete dropdown) with a tree/tag-group
    widget (``RegionsTreeEditor``/``RegionsTreeTagGroup``) — confirmed live
    this is the one field that still starts genuinely empty (see module
    docstring). Clicks the launcher button to open the tree popup (this
    reveals a SEPARATE contenteditable filter field, ``RegionsTreeTagGroup
    .editor`` — confirmed live it does not exist in the DOM until the popup
    is open), types the region name into that field (confirmed live this
    filters the tree and auto-expands every ancestor/descendant of a text
    match — e.g. typing "Москва" also renders the parent "Москва и область"
    and every district inside Москва), then checks the checkbox whose LABEL
    text is an EXACT match — same fix class as ``update_master``'s
    ``_set_promotion_goal`` (issue #631 review): a checkbox whose label
    merely CONTAINS the region name (a parent or child in the auto-expanded
    tree) is not the same node as the region itself.

    The click targets the LABEL, not the ``<input>`` it wraps: confirmed live
    the input resolves and reports ``is_visible() == True`` but is not
    actionable (Playwright's click times out on it), since the real hit
    target is the styled label. The input is still used to READ state — a
    label click toggles, so an already-checked region would be unchecked, and
    the read-back confirms the region really ended up selected.

    The open→type→poll sequence is retried up to ``_REGION_OPEN_ATTEMPTS``
    times, and each retry is idempotent by construction — see that
    constant's comment for why an unconditional re-click + re-type would
    make attempts 2..N guaranteed no-ops.

    Issue #705 re-recon, 2026-08-04: live re-testing on the account where
    #690/#703 found this section apparently missing confirms it renders
    reliably, and all the testids above are unchanged — the launcher now
    sits one level deeper (``GroupRegionsHyperlocalInput.Tree`` >
    ``RegionsTreeEditor`` > ``RegionsTreeEditor.RegionsTreeTagGroup`` >
    ``RegionsTreeTagGroup``), but every selector this function uses is a
    bare ``data-testid`` match, not a DOM-depth-sensitive path, so the
    extra nesting needed no code change. This function's existing
    retry/actionability-wait already tolerates the section's few-hundred-ms
    render lag after ``_wait_for_step2`` returns.

    Issue #657: each entry in ``regions`` may be a plain ``str`` (matched by
    exact label text only, same as before — this is what plain ``--region``
    gives, since it carries no known RegionId) or a ``(name, region_id)``
    pair (what ``--region-id``, resolved via ``_resolve_region_ids``, gives).
    Exact-text label matching alone only proves the right NAME was clicked —
    Yandex's GeoRegions names are not globally unique, so a same-named
    decoy elsewhere in the auto-expanded tree could in principle be the one
    Playwright's ``is_visible()``/click actually lands on. When a
    ``region_id`` is known, this additionally reads the checked checkbox's
    own ``id`` attribute — confirmed live it is always
    ``id="region-node-<RegionId>"`` — and refuses (raising, without ever
    reaching the terminal "Запустить"/"Сохранить" click) if that id doesn't
    encode the requested RegionId, rather than trusting the label-text match
    alone to mean the right region was actually selected.
    """
    for region in regions:
        if isinstance(region, tuple):
            region, expected_region_id = region
        else:
            expected_region_id = None
        # XPath, not a plain data-testid selector: the tree auto-expands
        # every ancestor/descendant of a text match (see docstring), so
        # multiple RegionsTreeNode.Checkbox.label elements can be on screen
        # at once — this scopes to the one whose FULL text (normalize-space
        # of the element, not merely its direct text-node children — the
        # region name is confirmed live to sit inside a nested <span>, so
        # normalize-space(text()) always evaluates empty and never matches)
        # equals the target region exactly, then descends to its checkbox.
        label_xpath = (
            "xpath=//label[@data-testid='RegionsTreeNode.Checkbox.label']"
            f"[normalize-space(.)={_xpath_literal(region)}]"
        )
        # Click the LABEL, read state from the <input>. Confirmed live (issue
        # #653): the <input type="checkbox" id="region-node-213"> the label
        # wraps resolves and even reports is_visible() == True, but clicking
        # it times out on Playwright's actionability check — it is a custom
        # control whose real hit target is the styled label, not the input.
        # Targeting the input directly is exactly why this failed with
        # "Could not find 'Москва'" even though the locator matched.
        label = page.locator(label_xpath)
        matched_wrong_id = None

        # Live testing (issue #653) found opening the popup and filtering
        # the tree is flaky under real network conditions — the popup can
        # fail to render the editor field on the first launcher click, and
        # the debounced filter can take longer than one poll window to
        # settle. Rather than a single click + single poll window, this
        # retries the whole open→type→poll sequence up to
        # _REGION_OPEN_ATTEMPTS times, so a single stuck attempt doesn't
        # fail the whole call.
        #
        # Each attempt must start from a KNOWN state, not from the previous
        # attempt's leftovers, or the retry is worse than no retry at all:
        #   * the launcher toggles the popup, so clicking it again while the
        #     popup is already open CLOSES it (or is swallowed by the popup
        #     overlay) — only click it when the editor is absent;
        #   * type() APPENDS to a contenteditable, so a second type(region)
        #     on an uncleared field yields "МоскваМосква", which filters the
        #     tree down to zero nodes and can never match.
        clicked = False
        last_open_exc = None
        # Tracks whether _clear_text_field ever reported failure across
        # attempts (issue #656). A failed clear here is NOT immediately
        # fatal the way it is in _add_repeating_values — this field is a
        # scratch filter, not a slot whose stale content would ship
        # unreviewed, and a later attempt's own poll decides success. But
        # if every attempt exhausts with no match, an unset clear means
        # each retype APPENDED onto the previous one ("МоскваМосква"),
        # which can never filter-match anything — surfacing that as "check
        # the region name" would blame the wrong thing when the real cause
        # is an unsupported Playwright version (see _clear_text_field).
        clear_ever_failed = False
        for _ in range(_REGION_OPEN_ATTEMPTS):
            launcher = page.locator(_REGION_LAUNCHER_TESTID).first
            editor = page.locator(_REGION_EDITOR_TESTID).first
            try:
                # The editor only exists in the DOM while the popup is open
                # (confirmed live), so its presence is the open/closed test.
                if not editor.count():
                    launcher.click()
                editor.click(timeout=_REGION_EDITOR_APPEAR_TIMEOUT_MS)
                if not _clear_text_field(editor):
                    clear_ever_failed = True
                editor.type(region)
            except PlaywrightError as exc:
                last_open_exc = exc
                continue

            # The tree re-filters asynchronously (debounced) after typing,
            # so an immediate count() can race the filter and see zero
            # matches even for a region that does exist — poll briefly
            # instead of checking once.
            deadline = _clock.now() + _REGION_FILTER_TIMEOUT_MS / 1000
            count = 0
            while _clock.now() < deadline:
                try:
                    count = label.count()
                except PlaywrightError:
                    count = 0
                if count:
                    break
                page.wait_for_timeout(100)
            for i in range(count):
                handle = label.nth(i)
                try:
                    if not handle.is_visible():
                        continue
                    handle.click()
                except PlaywrightError:
                    continue
                # Clicking a label that is already checked would UNCHECK the
                # region, so confirm the input actually ended up checked
                # rather than trusting the click — same read-back convention
                # as _verify_created/_verify_saved. Scoped off `handle`
                # itself (issue #656), not a second independent top-level
                # locator built from the same xpath: two separate
                # page.locator() calls resolved from the same selector are
                # not guaranteed to enumerate matches in the same order if
                # the tree re-renders between them, so indexing both by `i`
                # could silently pair a label with the WRONG node's
                # checkbox.
                node = handle.locator(
                    f"xpath=.//input[@data-testid='{_REGION_CHECKBOX_TESTID}']"
                ).first
                with contextlib.suppress(PlaywrightError):
                    if not node.is_checked():
                        continue
                    if expected_region_id is None:
                        clicked = True
                        break
                    # Issue #657: exact-text label match alone only proves
                    # the right NAME was clicked — GeoRegions names are not
                    # globally unique, so verify the checked node's own
                    # identity too, via its stable
                    # ``id="region-node-<RegionId>"`` attribute (confirmed
                    # live). Uncheck it immediately on a mismatch so a wrong
                    # region isn't left silently selected alongside whatever
                    # the caller resolves next.
                    node_id = node.get_attribute("id") or ""
                    if node_id == f"region-node-{expected_region_id}":
                        clicked = True
                        break
                    with contextlib.suppress(PlaywrightError):
                        handle.click()
                    matched_wrong_id = node_id
            if clicked:
                break

        if not clicked:
            if matched_wrong_id is not None:
                raise BrowserSessionError(
                    f"Selecting region {region!r} (RegionId "
                    f"{expected_region_id}) matched a tree node by label "
                    f"text, but that node's id ({matched_wrong_id!r}) does "
                    "not encode the requested RegionId — Yandex's "
                    "GeoRegions dictionary has more than one region named "
                    f"{region!r}, and the wrong one was about to be "
                    "selected. Re-run with --headful to inspect the tree "
                    "and disambiguate manually."
                )
            if (
                last_open_exc is not None
                and not page.locator(_REGION_LAUNCHER_TESTID).count()
            ):
                raise BrowserSessionError(
                    "Could not find or open the 'Регион показов' field on "
                    "the Мастер кампаний create page — Yandex may have "
                    "changed the page's markup. Re-run with --headful to "
                    "inspect the page."
                ) from last_open_exc
            if clear_ever_failed:
                raise BrowserSessionError(
                    f"Could not find {region!r} in the 'Регион показов' tree "
                    "after typing it — but the filter field could not be "
                    "cleared before typing (see _clear_text_field), so each "
                    "attempt likely typed into leftover text from the "
                    "previous one instead of a clean field. This usually "
                    "means Playwright is older than 1.44 (the version that "
                    "added the 'ControlOrMeta' modifier) — upgrade with "
                    "'pip install -U playwright' and retry before assuming "
                    "the region name itself is wrong."
                )
            raise BrowserSessionError(
                f"Could not find {region!r} in the 'Регион показов' tree on "
                "the Мастер кампаний create page — check the region name "
                "matches Yandex's own wording."
            )


def _read_region_tags(page: "Page") -> List[str]:
    """Read the "Регион показов" widget's currently selected region tags.

    Issue #653 re-recon, 2026-08-02: confirmed live each accepted selection
    renders as a removable tag inside ``RegionsTreeTagGroup.tags-wrapper``
    (``RegionsTreeTagGroup.tag.{N}``), replacing the earlier
    single-input-value best-effort fallback (issue #632 step 0, never
    live-verified) — this now reads the full accepted set, not just the
    last region typed.
    """
    wrapper = page.locator(_REGION_TAGS_WRAPPER_TESTID)
    try:
        count = wrapper.count()
    except PlaywrightError:
        return []
    if not count:
        return []
    tags = page.locator(_REGION_TAG_TESTID_PATTERN)
    try:
        tag_count = tags.count()
    except PlaywrightError:
        return []
    values = []
    for i in range(tag_count):
        try:
            values.append(tags.nth(i).inner_text())
        except PlaywrightError:
            values.append("")
    return values


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


def _repeating_values_mismatches(
    page: "Page", *, headlines: List[str], texts: List[str]
) -> List[str]:
    """Compare the create page's CURRENT headline/text slot contents against
    what the caller asked for — the one check both a pre-click gate and the
    post-click ``_verify_created`` backstop need (issue #655 round-3 review).

    Every round of this issue's review found a NEW way for a slot's true
    content to diverge from what ``_add_repeating_values`` believes it
    wrote (a click failure, an unused slot, a keypress that succeeds
    without actually clearing anything) — but this comparison itself was
    correct from the start each time. The actual defect was never the
    check, it was that ``create_master`` only ran it AFTER
    ``_click_terminal_button`` had already launched the campaign. Sharing
    this one function between a pre-click gate and the existing post-click
    read lets one fix close every variant, instead of patching each new
    way to reach a stale slot one at a time.

    Both directions matter. A missing value means the form did not take
    what was asked for; an EXTRA non-empty value means a slot still holds
    Yandex's AI-generated copy, which ships as a published ad variant the
    caller never reviewed. Checking only membership let the latter through
    silently (issue #655 review).
    """
    mismatches = []

    actual_headlines = _read_repeating_values(
        page, _HEADLINES_TESTID_TEMPLATE, _HEADLINES_SLOT_COUNT
    )
    for headline in headlines:
        if headline not in actual_headlines:
            mismatches.append(
                f"headline {headline!r} not found among current values "
                f"{actual_headlines!r}"
            )
    extra_headlines = [v for v in actual_headlines if v and v not in headlines]
    if extra_headlines:
        mismatches.append(
            f"unrequested headline variants still on the page: "
            f"{extra_headlines!r} — these are Yandex's AI-generated copy and "
            "would be published alongside yours"
        )

    actual_texts = _read_repeating_values(
        page, _TEXTS_TESTID_TEMPLATE, _TEXTS_SLOT_COUNT
    )
    for text in texts:
        if text not in actual_texts:
            mismatches.append(
                f"text {text!r} not found among current values {actual_texts!r}"
            )
    extra_texts = [v for v in actual_texts if v and v not in texts]
    if extra_texts:
        mismatches.append(
            f"unrequested ad-text variants still on the page: {extra_texts!r} "
            "— these are Yandex's AI-generated copy and would be published "
            "alongside yours"
        )

    return mismatches


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
    post-click destination. Region is intentionally NOT verified here even
    though ``_read_region_tags`` is now live-verified (issue #653): a
    reload-based verification (mirroring ``_verify_saved``) is a bigger,
    separately-scoped change than this issue's markup fix.

    This is the BACKSTOP for divergences that only appear as a side effect
    of the click itself (e.g. Yandex's own post-click validation reverting
    a field) — ``create_master`` also runs
    ``_repeating_values_mismatches`` BEFORE the click, which catches every
    divergence that already existed at click time (see that function's
    docstring).
    """
    mismatches = _repeating_values_mismatches(page, headlines=headlines, texts=texts)

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
    regions: "Sequence[Union[str, Tuple[str, Optional[int]]]]",
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

    # ``wait_until="commit"``, not ``domcontentloaded`` (issue #685):
    # confirmed live the create page can take long enough to hydrate that
    # even ``domcontentloaded`` — which additionally waits for the initial
    # HTML parse — occasionally times out before Playwright's navigation
    # settles. "commit" only waits for the response to start arriving, so
    # the actual page-ready check is the explicit
    # ``_wait_for_create_step1`` below, not the navigation wait itself.
    page.goto(WIZARD_CREATE_URL, wait_until="commit")
    assert_not_captcha(page.content())
    assert_authenticated(page.content())
    _wait_for_create_step1(page)

    _fill_landing_url(page, url)
    _wait_for_step2(page)

    _add_repeating_values(
        page, _HEADLINES_TESTID_TEMPLATE, _HEADLINES_SLOT_COUNT, headlines
    )
    _add_repeating_values(page, _TEXTS_TESTID_TEMPLATE, _TEXTS_SLOT_COUNT, texts)
    # Issue #705 re-recon, 2026-08-04: on the account where #690/#703's
    # re-recon found the "Регион показов" section (and its heading/testids)
    # completely absent from a fully-loaded step 2, that turned out to be a
    # snapshot taken mid-render, not a permanently removed field — live
    # re-testing confirms the section (RegionsTreeEditor/RegionsTreeTagGroup,
    # nested one level deeper under GroupRegionsHyperlocalInput.Tree) renders
    # reliably shortly after _wait_for_step2 returns, and _set_region's
    # existing launcher-click already tolerates that short race (Playwright's
    # default actionability wait covers the ~0.4s gap observed live). No
    # markup change was needed.
    _set_region(page, regions)
    if weekly_budget is not None:
        _set_weekly_budget_on_create(page, weekly_budget)

    # Gate the click, don't just report on it afterwards (issue #655
    # round-3 review): _add_repeating_values believing it wrote the right
    # values is not the same as the page actually holding them — a click
    # failure, an unused slot, or a keypress that succeeds without clearing
    # anything can all leave a slot stale without _add_repeating_values
    # itself raising. Checking here, before the terminal button, means an
    # already-live discrepancy is caught before anything is published,
    # instead of only being reported on by _verify_created afterwards.
    pre_click_mismatches = _repeating_values_mismatches(
        page, headlines=headlines, texts=texts
    )
    if pre_click_mismatches:
        raise BrowserSessionError(
            "Refusing to click the create page's terminal button: before "
            "clicking, the headline/text slots do not currently hold what "
            "was requested: " + "; ".join(pre_click_mismatches) + ". Yandex "
            "may have changed the page's markup, or a slot silently failed "
            "to clear — re-run with --headful to inspect the page."
        )

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
