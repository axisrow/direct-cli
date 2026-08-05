# Changelog

## Unreleased

**Added — `masters add` now returns `CampaignId` and verifies the display region (#744):**

- Live recon confirmed both terminal buttons ("Запустить кампанию" /
  "Сохранить как черновик") redirect `page.url` to the new campaign's
  overview URL (`/wizard/campaigns/{id}/`) — the same redirect `copy_master`
  has relied on since #659, since the clone flow lands on the very same
  step-2 form and terminates through the same `_click_terminal_button`.
  This closes the gap #632's read-only step-0 recon left open, where the
  post-click destination (and therefore the created campaign's ID) was
  undetermined.
- `create_master` now returns `CampaignId` (previously omitted for exactly
  that reason), so callers can find what they just created — which matters
  because this operation is irreversible and not idempotent.
- `_verify_created` now verifies the display region through a **real
  reload** (`page.goto(WIZARD_EDIT_URL...)` + `_read_until_matches` over
  `_read_region_tags`), mirroring `update_master`'s `_verify_saved`. Region
  was previously not verified at all — a region silently dropped by Yandex
  was reported as a clean success. Headlines/texts/budget deliberately stay
  on the pre-navigation read: they are the backstop for divergences caused
  by the click itself, which a reload would discard.
- The reload targets the **edit** page, not the overview page the click
  redirects to: a launched campaign's overview is the stats dashboard and
  renders no region widget at all. Region tags are compared as a subset
  (selecting a region can pull in implied parent/child nodes), and a click
  that never redirects now raises — naming the campaign that may already
  exist — instead of reporting success without an ID.

**Fixed — `masters get` returned the URL of a Yandex promo banner instead of the campaign's landing page (#763):**

- `_extract_landing_url` picked the first anchor whose `href` contained
  `utm_source=`. Live recon confirmed the overview page always also renders
  a Yandex promo banner ("Yandex Neuro Ads") whose own href is itself
  UTM-tagged (`ya.ru/project/yna/?utm_source=yandex&...`). Once the
  campaign's own `LandingUrl` carried no UTM tail of its own (e.g. right
  after `update --landing-url`, per #761), that banner became the *only*
  href-based match and was silently reported as the campaign's `LandingUrl`
  — this was not a caching issue, as the issue's title suggested, the
  selector was simply reading the wrong anchor. When the campaign's URL did
  carry a UTM tail, both anchors matched and the campaign's own link won
  only by DOM order, i.e. the old selector was correct by accident.
- Replaced with `_OVERVIEW_LANDING_LINK_SELECTOR`
  (`[data-testid="CampaignHeader"] a[data-testid="Link"]`), confirmed live
  to resolve to exactly the campaign's own link (1 match) regardless of
  whether its URL carries UTM params. `masters get`'s output format is
  unchanged — `LandingUrl` still carries the full href including any UTM
  tail.

**Changed — `SmartCampaign` bidding-strategy builder dedup (#592):**

- The `build_smart_campaign_search_strategy` / `build_smart_campaign_network_strategy`
  pair each carried a ~200-line copy of the same validation pipeline
  (ExplorationBudget / CustomPeriodBudget all-or-none checks, per-subtype
  field-support enforcement, WSDL `minOccurs=1` gating, `LimitPercent`
  range validation, `BudgetType` update-only gating). This is hoisted
  behind a single `_SmartStrategyConfig` NamedTuple + `_build_smart_strategy_block`
  core, mirroring the `_TextStrategyConfig` / `_DynamicTextStrategyConfig`
  precedent (#581, #591). `_assemble_strategy_block` (the shared
  CustomPeriodBudget/ExplorationBudget/BudgetType tail already extracted
  in #591) continues to own the final block assembly unchanged.
- The `CustomPeriodBudget` / `ExplorationBudget` blocks are now constructed
  via the shared `_build_custom_period_budget` / `_build_exploration_budget`
  helpers (`exploration_yes_only=False`, per the cached WSDL
  `general:YesNoEnum`) instead of a per-builder `*_values` dict + manual
  `len != len` presence check.
- Behavior is byte-for-byte identical: `--help`, `--dry-run` payload and
  every `UsageError` text are unchanged (verified by a before/after diff
  across default-flow, mutex, required-field, LimitPercent, budget-type
  and every-subtype-family scenarios on both Search and Network). This is
  the second of four planned per-campaign-type PRs under #592
  (dynamic_text done in #754); unified_campaign and mobile_app remain as
  follow-up.

**Fixed — `masters update --add-target-action`/`--remove-target-action` verification could trust an incomplete first read of the "Целевые действия" table (#750):**

- Round 3 of cycle-review on #749 found that `_verify_saved`'s add/remove
  verification, while hardened against every *exception*-raising failure
  mode (rounds 1-2), had no *positive* completeness signal for a read that
  raises nothing at all: the table can go through a genuine, non-throwing
  empty/partial interval while hydrating, and a removed goal's absence from
  that snapshot alone was indistinguishable from a real removal.
- Live recon against the test master 'Тест' (campaign 713277109) confirmed
  the race: the row-testid locator's own `.count()` (and even the
  `TargetActionsSection` element itself) can drop to 0 for over a second,
  starting a few seconds after `_wait_for_edit_form` returns, before the
  real row set (re)appears — no section-scoped loading/spinner
  `data-testid` exists to poll instead.
- New `_wait_for_target_actions_settled` (`direct_cli/browser/masters.py`)
  requires 5 consecutive equal row-count reads, 300ms apart, before
  `_verify_saved`'s add/remove retry loop trusts any read of the table —
  same shape as `_wait_for_audience_section`'s tag-count settling
  (issue #681).
- Codex adversarial review of this PR (#753) caught a follow-on gap: the
  settling wait's `bool` return value was being discarded, so a settle
  TIMEOUT fell straight through into the retry loop — which itself stops
  at its first matching read — reproducibly letting a still-hydrating,
  never-settling table report a false "removal confirmed". `_verify_saved`
  now treats a settle timeout as its own mismatch (same reporting path as
  every other verification failure) instead of silently proceeding.
- A second round of Codex adversarial review found the settling wait and
  the retry loop's own read are two genuinely separate DOM reads —
  settling certifying a stable row *count* does not certify that the
  retry loop's next, independent full-snapshot read lands on the same
  settled state (reproduced: a stable pre-dip streak followed by a single
  post-settle empty read was enough to report a no-op removal as
  successful). The add/remove match predicate now requires
  `_TARGET_ACTION_STABLE_STREAK` consecutive matching reads of the full
  requested state, not just one, before accepting it.

**Changed — `DynamicTextCampaign` bidding-strategy builder dedup (#592):**

- The `build_dynamic_text_search_strategy` /
  `build_dynamic_text_network_strategy` pair each carried a ~280-line
  copy of the same validation+assembly pipeline (ExplorationBudget /
  CustomPeriodBudget all-or-none checks, per-subtype field-support
  enforcement, WSDL `minOccurs=1` gating, `BudgetType` handling, final
  `Strategy*Add` block assembly). This is hoisted behind a single
  `_DynamicTextStrategyConfig` NamedTuple + `_build_dynamic_text_strategy_block`
  core, mirroring the already-proven `_TextStrategyConfig` pattern (#581).
- The old `_assemble_dynamic_text_strategy_block` (block-assembly only) is
  replaced by the new core. The `CustomPeriodBudget` / `ExplorationBudget`
  blocks are now constructed via the shared `_build_custom_period_budget` /
  `_build_exploration_budget` helpers (`exploration_yes_only=False`, per the
  cached WSDL `general:YesNoEnum`), instead of a per-builder `*_values` dict
  + manual dict literal.
- Behavior is byte-for-byte identical: `--help`, `--dry-run` payload and
  every `UsageError` text are unchanged (verified by a before/after diff over
  38 representative error+payload scenarios). The one intentional asymmetry
  is preserved as an explicit config flag: the Search side intentionally
  surfaces the wire-level `BudgetType` round-trip error instead of
  pre-checking presence (#362 adversarial-review feedback), while the
  Network side keeps its stricter up-front presence checks
  (`budget_type_presence_checks`).

**Added — `WeeklySpendLimit` support for HighestPosition/ManualCpm strategies (#610):**

- Live WSDL drift check (`scripts/check_wsdl_drift.py`, 2026-08-04) confirmed
  Yandex added a `WeeklySpendLimit`-only `StrategyHighestPosition`/
  `StrategyHighestPositionAdd` subtype to `UnifiedCampaignStrategyAddBase`
  and `MobileAppCampaignStrategyAddBase`, and a `WeeklySpendLimit`-only
  `StrategyManualCpm`/`StrategyManualCpmAdd` subtype to
  `CpmBannerCampaignNetworkStrategyAddBase`. `tests/wsdl_cache/campaigns.xml`
  refreshed accordingly (scoped to these fields only; the unrelated
  `WeeklyBudgetRollover` drift observed in the same check is out of scope
  for this issue).
- `campaigns add`/`update --type UNIFIED_CAMPAIGN --search-strategy
  HIGHEST_POSITION` / `--network-strategy` now accepts the existing
  `--unified-search-weekly-spend-limit` / `--unified-network-weekly-spend-limit`
  flags for `HIGHEST_POSITION` (previously rejected as a no-subtype legacy
  strategy).
- `campaigns add`/`update --type MOBILE_APP_CAMPAIGN --search-strategy
  HIGHEST_POSITION` now accepts the existing
  `--mobile-search-weekly-spend-limit` flag (Network side has no
  `HIGHEST_POSITION` enum value in the WSDL, so it stays Search-only).
- `campaigns add`/`update --type CPM_BANNER_CAMPAIGN --network-strategy
  MANUAL_CPM` now accepts a new `--strategy-weekly-spend-limit` flag; every
  other MANUAL_CPM detail flag remains rejected (`StrategyManualCpmAdd`
  declares only `WeeklySpendLimit`).

**Added — `adgroups suspend`/`adgroups resume` (#573):**

- The AdGroups API service has no `suspend`/`resume` method (WSDL declares
  only `add`/`get`/`update`/`delete`) and `AdGroupUpdateItem` has no
  impression-status field either, so there is no 1:1 WSDL way to pause a
  whole ad group. The new commands emulate it the way the web UI and Direct
  Commander do: resolve the group's ads via `ads.get` and
  suspend/resume them via `ads.suspend`/`ads.resume`, batched in chunks of
  1000. This is a deliberate, documented exception to strict WSDL parity —
  tracked in `INTENTIONAL_EXTRA_METHODS` (`direct_cli/wsdl_coverage.py`),
  not a mis-classified `DRY_RUN_PAYLOAD_EXCLUSIONS` entry.
- `resume` cannot distinguish ads it paused from ads a human suspended by
  hand earlier: it resumes every ad currently in the group. Documented in
  `--help` and the README, not solved with state-tracking.
- An empty group (or one whose ads no longer exist) prints an empty
  `SuspendResults`/`ResumeResults` with no request sent, instead of sending
  an empty `SelectionCriteria.Ids` the live API would reject.
- `--dry-run` never touches the network: since the real `ads.suspend`/
  `ads.resume` body depends on `ads.get`'s result, it prints the `ads.get`
  lookup request that would run first.
- Classified `WRITE_SANDBOX` in `smoke_matrix.py`, matching `ads.suspend`/
  `ads.resume` (both are safely exercisable via `direct --sandbox`), not
  `DANGEROUS`.

**Added — `masters update --add-target-action` / `--remove-target-action` (#717):**

- Live recon (2026-08-04, test campaign 713277109) of the "Целевые
  действия" table's own "Добавить" popup (`--target-action-price` (#707)
  only ever replaced an EXISTING row's price, adding/removing a row was
  explicitly out of scope there). Clicking
  `TargetActions.OTHER.MiniGrid.AddButton` opens
  `AddTargetAction.OTHER` — a list rendered BELOW the table (not a modal)
  of `[role="option"]` entries, one per goal in the campaign's linked
  Metrika counter that ISN'T already a row; Yandex filters already-added
  goals out of this list itself, so there is no "goal already added" error
  state to reproduce — a goal id absent from the list is either not the
  counter's or already present. Confirmed live a freshly clicked option
  renders with an EMPTY price input (not a page default as originally
  guessed) and saving with it still empty is rejected client-side.
  Removing a row via its `CloseButton` needs no confirmation and removes
  it from the DOM immediately.
- `masters update --add-target-action "<goal_id>=<price>"` (repeatable)
  adds a NEW goal row and sets its price in one step — the price is
  REQUIRED (unlike `--target-action-price`, which only ever fills a price
  that's already there), since Yandex has no default for a freshly added
  row and rejects saving one with an empty price. The goal must belong to
  the campaign's linked Metrika counter and not already be a row —
  identified purely by its numeric Metrika goal id, same "never by label"
  rule as `--target-action-price` (goal labels are not unique across an
  account, see #707's CHANGELOG entry).
- `masters update --remove-target-action "<goal_id>"` (repeatable) removes
  an EXISTING goal row. Both flags share `--target-action-price`'s
  `--promotion-goal max-conversions`-only gating (refused up front
  together with `--promotion-goal max-clicks`), and the CLI refuses
  passing the same goal id to more than one of
  `--target-action-price`/`--add-target-action`/`--remove-target-action`
  in the same call. Verified via `_verify_saved`'s existing
  reload-and-reread convention (#704/#716) — a save Yandex silently
  rejects client-side, or that a hydration race under-reads, is
  distinguished from a genuine mismatch by retrying the read before
  reporting a hard error.
- Part of #681/#648 (Этап C, target actions/CPA sub-item); follow-up to
  #707, whose CHANGELOG entry documented add/remove as explicitly out of
  scope.

**BREAKING CHANGES — dropped Python 3.9 support (#737):**

- `vcrpy` 8.1.1 references `aiohttp.streams.AsyncStreamReaderMixin`, removed in
  `aiohttp` 3.14.x, breaking VCR patcher construction for every
  `pytest.mark.vcr` test. The fix (`vcrpy>=8.3.0`) requires Python >=3.10, so
  `requires-python` is now `>=3.10`. The CI test matrix drops 3.9 and adds
  3.14.

**Fixed — `masters add --region-id` verified only by label text, not RegionId identity (#657):**

- `--region-id` resolved to Yandex's canonical `GeoRegionName` (#652) and
  handed that bare name to the browser's `_set_region`, which selects the
  tree/tag-group widget's checkbox by exact label-text match. GeoRegions
  names are not globally unique, so a text-only match could in principle
  click a same-named decoy checkbox belonging to a different RegionId than
  the one requested — `_resolve_region_ids`'s own ambiguity guard already
  refused known-ambiguous names up front, but gave no protection against a
  markup/DOM surprise landing on the wrong same-named node at click time.
- `_resolve_region_ids` now returns `(name, region_id)` pairs instead of
  bare names, threaded through `masters add`/`create_master` into
  `_set_region`. When a `region_id` is known, `_set_region` additionally
  reads the checked checkbox's own `id` attribute (confirmed live it is
  always `id="region-node-<RegionId>"`) and refuses — unchecking the wrong
  node first — if it doesn't encode the requested RegionId, rather than
  trusting the label-text match alone. Plain `--region` text (no known
  RegionId) is unaffected and keeps matching by exact label text only, as
  before.

**Added — `masters update --target-action-price` / `masters targetactions get` (#707):**

- Live recon (2026-08-04, campaign 713234191, `ksamatadirect` account,
  promotion goal `max-conversions`) confirmed the "Целевые действия" table
  is the `max-conversions` counterpart to `--goal-price`'s `max-clicks`-only
  field (#696): a single `<table>` (`TargetActions.OTHER.MiniGrid`) with one
  `<tr data-testid="TargetActions.OTHER.<goalId>">` per goal already added
  to the campaign, where `<goalId>` is Yandex Metrika's own numeric goal id
  (read from the campaign's linked Metrika counter) — confirmed goal LABELS
  are not unique across an account (e.g. "Регистрация"/"Регистрация JS"/
  "Регистрация JS ретаргет" are distinct goals), so a goal can only be
  addressed by this numeric id, never by name. There is no separate
  "select this goal" control — a goal's presence as a row is what makes it
  selected; filling its price is the only action.
- `masters update --target-action-price "<goal_id>=<price>"` (repeatable,
  like `--headline`/`--text` from #665) sets an EXISTING goal row's price.
  Only applies under `--promotion-goal max-conversions`; refused up front
  together with `--promotion-goal max-clicks`, mirroring `--goal-price`'s
  own guard in the opposite direction. The goal must already be a row in
  the table — adding a brand-new goal is not covered by this CLI yet.
  Verified via `_verify_saved`'s existing reload-and-reread convention
  (#704) — a save that Yandex silently rejects client-side is reported as
  a hard error, not a false success.
- `masters targetactions get <campaign_id>` (new group, mirrors
  `masters adimages get`) reads the table read-only — `GoalId`/`Name`/
  `Price` per row — for auditing which goal/price is configured across a
  batch of campaigns, without needing to also fetch/parse `masters get`.
  A new group rather than folded into `masters get`: this data lives only
  on the `/edit/` page (a separate `page.goto` from `masters get`'s
  overview-page read), same reasoning as why `adimages` is its own group.
- Part of #681/#648 (Этап C, target actions/CPA sub-item), split out as
  #707.

**Fixed — `dictionaries get-geo-regions` ignored `--locale`, always returned English names (#658):**

- `GeoRegionName`/`ParentGeoRegionNames` always came back in English regardless
  of `--locale ru`/`en`, unlike the Direct web UI (including the Мастер
  кампаний region widget), which shows Russian names by default.
- The v5 API adapter already supports an `Accept-Language` header
  (`language` client param, same mechanism `reports get --language` uses) —
  `dictionaries get-geo-regions` (`direct_cli/commands/dictionaries.py`) just
  never set it. It now builds its client with
  `language=resolve_locale(ctx)`, so the resolved `--locale` (CLI flag >
  `YANDEX_DIRECT_CLI_LOCALE` env var > `ru` default) reaches the API as
  `Accept-Language`.
- Live-verified against the production API: `--locale ru` now returns
  "Москва"/"Москва и область"/"Россия" for region IDs 213/1/225; `--locale en`
  still returns "Moscow"/"Moscow and Moscow Oblast"/"Russia"; the no-flag
  default now also returns Russian names, matching the CLI's documented `ru`
  default (previously always English regardless of default).
- `dictionaries get` (the generic multi-dictionary command) is unaffected —
  only `get-geo-regions` builds its own client with the resolved locale.

**Fixed — `masters get`'s stat-tile extraction used a tick-stabilization guess instead of a real render marker (#708):**

- `_extract_stat_tiles` (`direct_cli/browser/masters.py`) previously scanned
  every button on the overview page for a 2-line "value\nlabel" shape and
  waited for that found set to stay unchanged for several consecutive poll
  ticks before trusting it as final (issue #697's stopgap) — a heuristic
  that structurally could not distinguish "this campaign genuinely has
  fewer than 5 tiles" from "the tiles just haven't started rendering yet".
- Live recon (12 runs across 9 distinct ACTIVE campaigns in one account)
  found a real DOM marker: each tile carries a stable
  `data-testid="ChartSummary.<key>"` (`shows`/`clicks`/`conversions`/`cpa`/
  `cost`), and all five render atomically in a single React commit — the
  first poll tick that observes any `ChartSummary.*` node always already
  has all five. `_extract_stat_tiles` now waits for that marker directly
  (mirroring `_OVERVIEW_TITLE_SELECTOR`'s convention) and reads the fixed
  testid set, instead of guessing with a tick count. No behavior change for
  the CLI's `Stats` output shape.

**Fixed — `masters get`/`archive`/`suspend`/`resume` on `DRAFT` campaigns (#660):**

- A `DRAFT` Мастер кампаний's overview page (`WIZARD_OVERVIEW_URL` itself, no
  `/edit/`) renders the editable wizard form, not the stats-dashboard
  overview every other status renders — no `CampaignHeader.MenuTrigger`, no
  status text, no stat tiles. This previously made `masters get` degrade to
  `{"CampaignId": ..., "LandingUrl": ...}` (with unhelpful "Could not read
  campaign name"/"Could not determine status" warnings) and made `masters
  archive`/`suspend`/`resume` crash with `BrowserSessionError` on a missing
  selector.
- `fetch_master` (`direct_cli/browser/masters.py`) now detects a `DRAFT`
  overview page via `CampaignHeader.Status` reading "Черновик"
  (`_is_draft_overview_page`) and reads `Name`/`Status`/`WeeklyBudget` from
  the form's header and budget input instead of the dashboard extractors —
  no `LandingUrl`/`Stats` (the form has neither).
- `archive_master`/`suspend_master`/`resume_master` now refuse a `DRAFT`
  campaign with a clear `BrowserSessionError` explaining there is no
  archive/suspend/resume action available for a draft (launch it first via
  `masters update --launch`), instead of crashing on a missing selector.
  No delete action exists for a Мастер кампаний draft anywhere in the UI
  (checked live, both the overview page and the grid row's own menu).
- Live-verified against campaign 713231614 (the draft copy left over from
  #659's recon) — see `tests/fixtures/masters_wizard_draft_overview.html`.
- `_is_draft_overview_page` checks `.count() == 0` before calling
  `inner_text()` on the `CampaignHeader.Status` locator — a non-DRAFT
  overview page has no such node at all, and calling `inner_text()` directly
  would make Playwright auto-wait its full actionability timeout (default
  30s) on every `masters get`/`suspend`/`resume` call before falling through
  to the normal dashboard extractors (caught in review; the module's other
  presence checks, e.g. `_is_draft_edit_page`, already use `.count()` for
  exactly this reason).
- That same `.count() == 0` snapshot, taken immediately after
  `goto(..., wait_until="domcontentloaded")`, raced the SPA's own hydration
  — the same class of bug issue #685 already fixed for the create page's
  step 1 field. `_is_draft_overview_page` now polls (up to 15s) for EITHER
  `CampaignHeader.Status` (DRAFT) or the non-DRAFT dashboard's own status
  body text (`_read_status_text`'s markers) to actually render before
  classifying the page, instead of concluding "not DRAFT" from a page that
  simply hadn't finished rendering yet (caught in review).
- The status-node poll above still only checked node *presence*
  (`.count() > 0`), not its text — a framework can mount
  `CampaignHeader.Status` before filling in its content, which would read
  as "rendered" while the node is still empty and misclassify a real DRAFT
  campaign as non-DRAFT. `_is_draft_overview_page` now polls for the node's
  actual (trimmed) text, not just its presence (caught in review).

**Fixed — images-section "ghost" render pass caused false "no images" reads (#687):**

- `_wait_for_images_editor` (`direct_cli/browser/masters.py`) previously
  trusted "editor present, no `StubN`" as a settled state. Live diagnosis
  found a third, earlier render stage — before any `StubN` placeholder
  round begins, `ImageSuggestionsEditor` briefly mounts with zero `StubN`
  AND zero `ContentImage` elements (observed live: under 1s to ~14.5s) —
  indistinguishable from a genuine empty-set settle by DOM shape alone.
  Confirmed 100% reproducible across 3 consecutive live runs: the
  pre-fix guard returned within ~4s reading `[]` for a campaign with 5
  real images, the exact "no images" false negative #687 describes.
- Fixed by only trusting "no `StubN`" once a real `StubN` round has been
  observed and cleared, OR `ContentImage` elements are already present,
  OR the "nothing yet" reading holds continuously for
  `_IMAGES_GHOST_GRACE_S` (20s) — covering a genuinely empty image set.
  `_IMAGES_EDITOR_TIMEOUT_MS` bumped 30s → 60s to accommodate the
  worst observed combined ghost+real timeline (43.6s, 11 repeat runs).
- Confirmed live 2026-08-03: `masters adimages get` on two campaigns with
  5 images each now correctly reads all images (previously reproducibly
  empty).
- Re-verified live 2026-08-03 in combination with PR #689's `commit` +
  `_wait_for_edit_form` navigation changes (raised as a possible gap by
  issue #695): direct instrumentation and 8 subsequent `masters adimages
  get` runs across both campaigns all correctly read 5 images each
  (12.3s-28.1s elapsed); no occurrence of a stuck/never-hydrating section
  was observed.

**Fixed — grid navigation `domcontentloaded` timeout (#682):**

- `_capture_grid_campaigns_request` (`direct_cli/browser/masters.py`) — the
  single navigation point for the campaigns grid, used by `masters list`,
  `get`, `archive`, and `update` — navigated with
  `wait_until="domcontentloaded"`. Live diagnosis in #671 found the grid is
  a virtualized SPA whose `document.readyState` never advances past
  `"interactive"`, so `domcontentloaded` could wait out its full 30s
  timeout even though the grid's own `GridCampaigns` data request had
  already fired.
- Switched to `wait_until="commit"`, which only waits for the response
  headers and the start of the document body — safe here because the
  actual wait for grid data is `page.expect_response(...)`, not the
  `goto` call itself. `assert_not_captcha`/`assert_authenticated` still
  see valid HTML at `commit` time: both are server-rendered gate pages
  (not part of the grid SPA), so their marker text is present in the
  initial document body before any client-side JS runs.
- Confirmed live 2026-08-03: `direct masters list --status all` completes
  in ~15-25s across repeated runs (previously could exhaust the 30s
  `expect_response` timeout).

**Fixed — `direct playwright login`/`doctor` navigation could time out on
`wait_until="domcontentloaded"` (#686):**

- The three navigations in `direct_cli/browser/session.py`
  (`login_persistent_session`'s Passport tab and poll probe,
  `capture_storage_state`'s grid verification) occasionally timed out on
  `domcontentloaded` during Passport's own slow initial paint — the same
  long-poll-connections issue #634 already worked around for
  `networkidle`, one navigation-event tier down.
- All three now use `wait_until="commit"` (returns as soon as the
  navigation is committed, before the target SPA's own JS runs) followed by
  a new `_wait_for_marker` poll for a concrete DOM marker —
  `[data-testid="auth-logo"]` for Passport, `[data-testid="Sidebar"]` for
  the authenticated Direct/grid shell (confirmed live 2026-08-03). Only
  once the marker is present does the caller trust `page.content()` for its
  captcha/auth checks.
- `login_persistent_session`'s polling loop (re-navigates to the grid every
  tick while the user is still logging in by hand) accepts either marker,
  capped at the poll interval rather than the full marker timeout — an
  unfinished login redirects the grid URL right back to Passport, and
  waiting on the grid's marker alone would burn the full timeout every
  tick until the user finishes.
- The marker poll now fails closed: if neither marker ever appears (a
  blank/unrendered shell, matching none of the captcha/login-page markers
  either), `login_persistent_session`'s initial Passport navigation and
  `capture_storage_state`'s grid verification raise instead of trusting an
  unrendered page's `page.content()`, and the login-completion poll loop
  treats an unrendered tick as "not authenticated yet" rather than a
  successful, verified login (cycle-review on #692).

**Fixed — `wait_until="domcontentloaded"` timeout on `masters` wizard-edit
navigation (#684):**

- All four `WIZARD_EDIT_URL` navigation sites (`_verify_saved`,
  `update_master`, `_open_images_editor`, `_verify_saved_images`) switched
  from `page.goto(url, wait_until="domcontentloaded")` to
  `wait_until="commit"` — `domcontentloaded` was observed to time out under
  real network conditions on this SPA (Yandex holds long-poll connections
  that can make even that early a lifecycle event hang), while `commit`
  only waits on the response itself and never hangs on page-internal
  behaviour.
- `commit` guarantees nothing about the DOM, so every site now polls a new
  `_wait_for_edit_form` helper for the edit form's first headline slot
  (`CampaignTitles0.textarea` — guaranteed present on any rendered edit
  page, DRAFT or not, since headlines are not optional) before touching
  the page, mirroring `_wait_for_images_editor`'s existing "wait for real
  content, not just the navigation call" discipline.
- `fetch_master_images`'s existing `_wait_for_images_editor` call is
  unaffected — confirmed this fix composes cleanly with it (the form-ready
  wait happens first, then the images-specific stub wait, as before).
- Cycle-review follow-up: `_wait_for_edit_form`'s poll loop now re-checks
  `assert_not_captcha`/`assert_authenticated` on every tick, not just once
  right after `goto(..., wait_until="commit")`. A captcha gate or expired
  session that the SPA's own JS renders in *after* that initial commit
  response was previously invisible to the one-shot checks and only
  surfaced as a generic timeout — losing the specific `BrowserCaptchaError`/
  `BrowserAuthError` that `_verify_saved_images`'s post-save caller relies
  on to know not to retry a non-idempotent image mutation.

**Added — `direct masters adimages delete/set` (#648):**

- Completes the `masters adimages` subgroup, so a campaign's image set can
  be managed end-to-end rather than only read (`get`) or appended to
  (`add`):
  - `adimages delete <ID>` removes images addressed by `--position`
    (1-based, as shown by `adimages get`), `--content-id`, or `--all`.
    `--all` on an already-empty set is an idempotent no-op; naming a
    position or content ID that doesn't exist is always an error. `--all`
    cannot be combined with `--position`/`--content-id` — the combination
    is ambiguous and risks silent data loss, so it is a `UsageError`
    rather than a silent "ignore the narrower ones".
  - `adimages set <ID> --image-file PATH` replaces the WHOLE set inside
    one modal session (every current image removed, every given file
    uploaded), so a 5→5 replacement never transiently exceeds the cap.
    With no files it requires `--allow-empty`, guarding against an
    accidentally-empty shell glob wiping the set — the empty end state
    stays reachable, just deliberately (or via `delete --all`).
- **Leaving a campaign with zero images is a valid end state.** This is
  what `_verify_image_set_mismatches`'s absolute end-state check (added
  with `adimages get`) exists for: `delete --all` genuinely asserts the
  saved set is now empty rather than inferring it from a count delta.
- Both accept `--launch` (same draft-publishing semantics as `masters
  update`) and are classified DANGEROUS: they can remove every image in a
  campaign and are not idempotent.
- **Confirmed live 2026-08-03** on DRAFT campaign 713234191:
  `delete --position`, `delete --all`, `set` (full replacement) and
  `set --allow-empty` all round-tripped correctly across a fresh reload.
  This also settles the one previously-unverified risk — Yandex's Save
  control stays clickable when the modal's selection is reduced to zero.

**Added — `direct masters adimages add` (#648):**

- `adimages add <ID> --image-file PATH` (repeatable) appends local
  PNG/JPEG/GIF files to a campaign's image set, refusing if the current
  count plus the new files would exceed Yandex's cap of 5. Works from an
  empty set — the case `masters update --image` refuses outright. Accepts
  `--launch` (same draft-publishing semantics as `masters update`).
- `_apply_image_operations` is the new bulk primitive: open the image
  manager modal ONCE, apply every removal and every upload, click Save
  once. Removals are located by thumb URLs captured before any removal, so
  a later removal in the same batch is not thrown off by the panel
  re-indexing as earlier cards disappear; uploads poll an ABSOLUTE expected
  panel size rather than `_set_image`'s relative "grew back to the original
  size" check, which only happens to work for an exact 1-for-1 swap.
  Nothing commits before the single Save, so any earlier failure leaves the
  saved set untouched. `_set_image` (what `update --image` uses) is left
  untouched.
- `_save_and_verify_images` wraps the shared post-save tail: resolve the
  draft-aware button label, click it, verify against an absolute expected
  end state, and translate a mid-verification session expiry into a "do
  NOT retry" error (uploads are not idempotent, so `_with_session`'s
  auto-retry must not re-run them).
- Classified DANGEROUS in the smoke matrix and listed in
  `scripts/test_dangerous_commands.sh`: Мастер кампаний has no sandbox
  equivalent, real files are uploaded, and a retried `add` appends again.
- **Confirmed live 2026-08-03** on DRAFT campaign 713234191, including
  uploading into a genuinely empty set.

**Added — `direct masters adimages get` (#648):**

- New `direct masters adimages` subgroup, the browser-driven counterpart to
  the API-side `direct adimages` group (Мастер кампаний has no API surface
  at all). `adimages get <CAMPAIGN_ID>` reports the campaign's whole image
  set — `Position` (1-based), `ContentId`, and `ThumbUrl` per image, plus
  `Count` and `MaxCount`.
- **An empty image set is a successful result (`Count: 0`), not an error**,
  unlike `masters update --image` which refuses outright when a campaign
  has no images. Images are optional on a Мастер кампаний campaign, exactly
  like ad images on a text ad via the API — there is no "at least one"
  invariant of the kind headlines and texts have.
- Read-only: the thumbnail URL is not exposed on the edit page itself, so
  this opens the image manager modal to read it and then abandons the modal
  WITHOUT ever clicking Save — nothing commits to the campaign. A campaign
  with no images skips the modal entirely, there being nothing to read.
- `_verify_image_mismatches` now delegates to a new
  `_verify_image_set_mismatches`, which checks an ABSOLUTE expected end
  state (every removed ID gone, every kept ID present, total size as
  expected) rather than assuming "removed count == added count". A point
  replacement is that general check with the two counts pinned equal, so
  the existing behaviour is unchanged.
- `masters adimages get` is the CLI's first three-level command; it is
  classified SAFE in the smoke matrix.

**Fixed — `_wait_for_images_editor` returned during a loading-stub state,
under-reporting a campaign's real image count (#648):**

- The edit page's "Изображения" section renders in TWO stages — first
  `ImageSuggestionsEditor` itself appears with four
  `ImageSuggestionsEditor.CampaignContents.StubN` loading placeholders and
  NEITHER `ContentImage.*` nor `.Open` present yet, then roughly 3s later
  the stubs are replaced by the real content. `_wait_for_images_editor`
  previously returned as soon as the outer container existed — i.e.
  during the stub window — so `_read_image_content_ids` read `[]` for a
  campaign that demonstrably had 4 real images, and `masters update
  --image` then refused to replace anything with "campaign has no images".
- **Confirmed live 2026-08-03, campaigns 713234191 and 713234204** (both
  with 4 real images each): the images section read back as empty before
  this fix and as 4 images after it. The two campaigns and their symptom
  exactly mirror the four-DRAFT regression `_wait_for_images_editor` was
  originally written to guard against (2026-08-02) — the guard just
  didn't cover this second render stage.
- `_wait_for_images_editor` now also polls until no
  `ImageSuggestionsEditor.CampaignContents.StubN` element remains, so
  every caller observes only the settled state, never the transient one.
  The timeout error message now says "did not finish rendering... may
  still be showing loading placeholders" instead of "did not render", to
  describe the stub case accurately.

**Added — `direct masters update --image` (#670, Этап D):**

- New repeatable `--image "N=/path/to/file.png"` flag on `direct masters
  update <CAMPAIGN_ID>` replaces the image currently at position N of the
  campaign's image set with a local PNG/JPEG/GIF file, driven through the
  edit page's image manager modal (`ImageSuggestionsEditorModal`).
- **Known limitation — the image set is reordered.** Yandex has no "replace
  this slot" primitive for images at all, only "remove from the set" and
  "add to the set", so the point replacement is composed from the two.
  Confirmed live 2026-08-02 (campaign 713234191, Save never clicked, no
  campaign mutated): a newly uploaded image is always appended to the END
  of the set, never inserted at the freed position — replacing position 2
  of `[A, B, C, D]` yields `[A, C, D, NEW]`, not `[A, NEW, C, D]`. The
  flag therefore means "replace the image currently at position N" (which
  one to drop), not "put the new image at position N". This has no effect
  on ad delivery — Yandex rotates images by performance regardless of their
  order — but the CLI help, README and this entry say so rather than
  implying a true positional swap.
- **No fixed slot count, unlike headlines/texts.** The edit page renders
  exactly as many `ContentImage` elements as the campaign has images, keyed
  by a Yandex content ID rather than an index, so the real upper bound for
  N is read fresh from the page. `_IMAGES_MAX_COUNT = 5` (Yandex's hard cap
  on set size) bounds CLI parsing only — `--image "5=..."` on a campaign
  with four images is refused by the browser layer as out of range, not
  silently appended as a fifth.
- **An empty image set is a legitimate state** (there is no "at least one"
  invariant as there is for headlines/texts), and it gets its own explicit
  error rather than a generic out-of-range one — this command only replaces
  images that already exist, it does not add the first one.
- The edit page is an SPA: `goto(..., wait_until="domcontentloaded")`
  returns before the images section exists, and reading too early yields an
  empty list indistinguishable from "this campaign genuinely has no
  images". Live-confirmed to produce a false "no images" failure on four
  consecutive campaigns that demonstrably had four images each. Hence
  `_wait_for_images_editor`, which reports a timeout as a hard error
  instead of silently treating it as an empty set.
- Nonexistent paths and extensions Yandex won't accept are rejected as a
  `UsageError` before any browser session opens, with the accepted suffixes
  imported from the browser layer's own `_IMAGE_UPLOAD_SUFFIXES` (mirroring
  the page's `accept="image/png,image/jpeg,image/jpg,image/gif"`, confirmed
  live) so the two can't drift.
- Post-save verification is **set-membership**, not positional, matching
  the append-to-end behaviour above; identity is read from the content ID
  in the `data-testid`, not from the thumbnail's visual availability (a
  broken preview does not mean a missing image — observed live).
- Because both the removal and the upload happen inside the same open
  modal, any failure before `Save` leaves the campaign's saved image set
  untouched — every error message says so explicitly.
- Adding an image beyond the current set, deleting one without replacement,
  picking from the modal's `USER`/`WEB_SITE`/`AI_GENERATED`/`NEURO_STOCK`
  libraries, and video are all out of scope (video is a separate follow-up:
  it uses a different control and a different processing pipeline).
- Each image is replaced through its own open/remove/upload/Save modal
  cycle, so replacing N images costs N cycles. Batching them into a single
  modal session looks possible (`set_input_files` accepts a list) but is
  not live-verified, so it is deliberately left for a follow-up.

**Changed — shared scaffolding in `direct_cli/browser/masters.py` (#670):**

- New `_poll_until` replaces five hand-rolled `deadline` /
  `wait_for_timeout(250)` loops and the two sentinel flags (`removed`,
  `uploaded`) that only existed because those loops were inline. It also
  makes `PlaywrightError` suppression uniform — previously only one of the
  five loops suppressed it.
- New `_read_testid_suffixes` collapses `_read_image_content_ids` and
  `_read_modal_selected_thumb_urls`, which were the same prefix-scraping
  body twice.
- New `_validate_image_paths` lifts the extension/existence check out of
  the Click callback body.

**Added — `direct masters update --headline`/`--text` (#665, Этап B):**

- New `--headline "N=text"` / `--text "N=text"` flags on `direct masters
  update <CAMPAIGN_ID>` replace one existing headline/ad-text variant slot
  at a time (N is the 1-based slot shown on the edit page — 1-5 for
  headlines, 1-3 for ad text). Repeatable for multiple slots in one call.
- **Deliberate departure from this CLI's dominant list-field convention**:
  everywhere else, `update` replaces the WHOLE array in one call (e.g.
  `campaigns update --negative-keywords`, built on
  `_campaigns_base.py::_array_of_string_option`, which never reads the
  existing array before overwriting it). Мастер кампаний has no API at all
  — every mutation is a live page edit through a small, fixed set of slots
  — and forcing every variant to be re-typed to fix one typo would defeat
  the point of a partial update. A future refactor may want to unify this
  with the rest of the CLI's convention, but that isn't settled and is out
  of scope here. See `direct_cli/browser/masters.py::_set_repeating_value`
  for the full rationale.
- Writing to a slot that is currently empty is refused (`UsageError`) —
  this only replaces variants that already exist, it does not add new
  ones. Deleting a variant (clearing a slot) and editing variant weights
  are tracked as separate follow-ups, not implemented here.
- An out-of-range slot number (`--headline "6="`, `--text "4=x"`) is
  rejected at the CLI boundary too, with the bounds imported from the
  browser layer's own `_HEADLINES_SLOT_COUNT`/`_TEXTS_SLOT_COUNT` so the
  two can't drift. Previously only `_set_repeating_value` caught it, so a
  purely invalid argument launched a browser (and possibly an auth prompt)
  before failing as a `BrowserSessionError` instead of a `UsageError`.
- An empty or whitespace-only replacement (`--headline "1="`) is likewise
  refused, at the CLI boundary before any browser session opens and again
  in `_set_repeating_value` for non-CLI callers. Blanking a slot is a
  *delete*, not a replace, and it would have failed silently: the slot is
  cleared, `""` typed, the form saved, and the post-save check compares the
  re-read slot against the requested value — `"" == ""` matches, so the
  deletion of a live ad variant would have been reported as a successful
  update (found in review by both reviewers).
- The edit page's slots (`CampaignTitles{N}.textarea`/
  `CampaignTexts{N}.textarea`, 5/3 slots) turned out identical in shape and
  count to the create page's (#653), confirmed via a read-only recon
  against campaign 107707079 before writing any code — see
  `tests/fixtures/masters_wizard_edit_stage_b.html`.
- Reuses `_clear_text_field`/`_read_repeating_values` from the create-page
  implementation as-is; does NOT reuse `_add_repeating_values` (that
  function's contract — clear and rewrite every slot — is the opposite of
  a point replacement).
- Live-verified end to end against a real DRAFT campaign (713231614): a
  headline slot was replaced, confirmed saved via reload, then reverted to
  its original text the same way.

**Fixed — `direct masters update` on DRAFT campaigns (#668):**

- A DRAFT campaign's edit page has no "Сохранить кампанию" button at all —
  only `CampaignFormControls.saveDraft.button`/`.save.button` (the latter
  labelled "Запустить кампанию" here, which PUBLISHES the campaign — same
  testid suffix as the non-DRAFT save button, different label and
  consequence). `update_master` now detects DRAFT via the presence of
  `saveDraft.button` and clicks it by default (keeping DRAFT status); pass
  `--launch` to publish while saving instead. Previously `update` failed
  cleanly on any DRAFT campaign (issue #660's original gap) — this closes
  that gap for `update` specifically (`get`/`archive`/`suspend`/`resume`
  on DRAFT remain tracked separately in #660).
- Live-recon (2026-08-02, campaign 713231614) found the draft-save click
  redirects away from `/edit/` to the campaign's overview page, and NOT
  instantly (~5s observed) — `update_master`'s original immediate
  post-click reload raced this redirect and produced a false "did not save
  as requested" error even though the edit WAS actually saved server-side.
  Fixed by polling `page.url` until it leaves `/edit/` before re-navigating
  to verify, mirroring the pattern `copy_master` already uses for its own
  post-click redirect.

**Added — `direct masters update --name` (#663):**

- New `--name` flag on `direct masters update <CAMPAIGN_ID>` renames a Мастер
  кампаний, closing the gap `masters copy`'s docstring already pointed to
  (Yandex's own "— N" suffix on clones doesn't increment on repeated clones
  of the same source, so two copies can end up with the identical name).
- Edited via a separate header modal rather than a plain form input like the
  other three Этап A fields, but persisted only by the same terminal save
  action — see `direct_cli/browser/masters.py` module docstring.
- Can be combined with `--weekly-budget`/`--promotion-goal`/
  `--directs-helps` in the same call, sharing the page's single whole-form
  save.

**Added — `direct masters copy` (#659):**

- New `direct masters copy <CAMPAIGN_ID>` clones an existing Мастер кампаний
  via the overview page's "⋮" menu → "Клонировать" (`CampaignHeader.Menu.clone`,
  confirmed live), the same action a human uses in the web UI. Yandex
  pre-fills the new campaign end to end from the source (headlines, texts,
  images, video, display region, Metrika counters, target actions, weekly
  budget) — including the display region **verbatim**, which sidesteps the
  region text-matching issues `add --region`/`--region-id` can hit (issues
  #652/#656/#657) entirely, since nothing is retyped or re-matched.
- Live-verified end to end (campaign 107707079 → draft copy 713231614,
  confirmed both via the post-click URL redirect to the new campaign's
  overview page and via a `fetch_masters_list` grid diff before reporting
  success).
- `--draft`/`--launch` mirror `masters add`'s flag, but with the opposite,
  safer default: the copy is saved as a draft unless `--launch` is passed
  explicitly.
- Scope is intentionally narrow: `copy` is a 1:1 mirror of the web UI's
  clone action only — it does not rename, retarget, or edit any field on the
  copy beyond what Yandex itself does (it appends " — N" to the name). Use
  `masters update` afterwards for any further changes.
- **Not idempotent**, same as `add`: running it twice creates a SECOND copy,
  not an update to the first. No `--sandbox` — Мастер кампаний has no API at
  all, so there is no isolated test copy.
- Follow-up (not in this change): flags to override individual fields on the
  clone form, and a separate gap found during recon — `masters get`/
  `archive`/`suspend`/`resume` do not yet work against a freshly created
  `DRAFT`-status campaign (issue #660).
- If the saved browser session is invalidated in the narrow window between
  the clone's terminal-button click and its post-click grid verification,
  `copy_master` now surfaces a plain error naming the already-created
  campaign instead of letting `_with_session`'s auth-retry silently
  re-run the whole clone (which would create a second copy — or, with
  `--launch`, a second live campaign — with no trace of the first).

**Added — `direct masters add --region-id` (#652):**

- New `--region-id` option resolves a numeric `RegionId` to Yandex's
  canonical `GeoRegionName` via the `GeoRegions` dictionary
  (`dictionaries.getGeoRegions`), instead of requiring the user to guess the
  exact wording the "Регион показов" widget accepts. Repeat for multiple
  regions, same as `--region`. Combines with `--region` — resolved names are
  appended to any `--region` values given.
- At least one of `--region`/`--region-id` is now required (previously only
  `--region`, always required); an unknown `RegionId` raises a `UsageError`
  pointing at `direct dictionaries get-geo-regions`.
- Unlike the rest of `direct masters` (which needs no Yandex Direct API
  credentials — see module docstring), resolving `--region-id` does need
  valid API credentials, since it makes `dictionaries.getGeoRegions`
  call(s) before opening the browser session.
- `GeoRegionName` values are not globally unique in Yandex's dictionary
  (distinct `RegionId`s under different parents can share a name); since
  the browser-side region widget matches by exact name text with no
  `RegionId`/parent verification, a `--region-id` that resolves to an
  ambiguous name now raises a `UsageError` instead of silently risking a
  live launch against the wrong geography — use `--region` with the fully
  qualified text for such names.
- Not a breaking change: `--region`'s existing text-based behavior is
  unchanged.

**Fixed — `direct masters add`: URL field selector (#650):**

- Yandex replaced step 1's plain `<input placeholder="...">` with a Combobox
  whose text control is a `contenteditable` `<div role="textbox">` — the
  placeholder text itself is unchanged, but Playwright's
  `get_by_placeholder()` only matches `<input>`/`<textarea>` elements, so it
  silently stopped finding the field and every `masters add` call failed
  with "Could not find or fill the landing-page URL field".
- Live re-recon (2026-08-02) found the field now carries a stable
  `data-testid="CampaignFormUrl.Textinput"`, and the "Далее" button next to
  it carries `data-testid="CampaignFormUrl.button"` — both selected directly
  now instead of by placeholder text / accessible name. The field is filled
  via `.type()` (keystroke simulation) instead of `.fill()`, since `.fill()`
  does not work on a `contenteditable` element.
- Also confirmed live: unlike before, the "Далее" button only renders once
  the field has text — Playwright's own click-time actionability wait
  handles this without extra polling.

**Fixed — `direct masters add`: step 2 selectors (#653):**

- With #650's step-1 fix in place, `masters add` reached step 2 and failed
  there instead: headlines, texts and the region field had all migrated to
  new markup. Live re-recon (2026-08-02) confirmed each one.
- **Headlines/texts** are no longer a single "current variant" input plus an
  "add another" control. Yandex now pre-renders a FIXED set of
  `contenteditable` slots (5 headlines, 3 texts) addressed by stable
  `data-testid`s (`CampaignTitles{N}.textarea` / `CampaignTexts{N}.textarea`),
  mostly AI-pre-filled from the landing page. Each value is now typed into
  its own slot by index, and read back via `inner_text()` (a
  `contenteditable` `<div>` has no `value`). Passing more values than there
  are slots is now a clear error instead of a silent drop.
- **Every** slot is **cleared before typing** — not just the ones being
  filled. Two separate hazards: `.type()` appends from wherever the click
  left the caret, so an uncleared slot got the value spliced into the middle
  of Yandex's text (confirmed live as `Центр оздоровления и китайско<typed>й
  гимнастики цигун!`); and every non-empty slot is a *published ad variant*,
  so leaving the unused ones pre-filled meant a single `--headline` launched
  that headline plus four AI-written ones the caller never reviewed. Both
  violate this module's contract of never publishing unreviewed copy on a
  page with no sandbox and no rollback.
- A slot that cannot be cleared is now a **hard error** instead of a silent
  best-effort skip: the terminal "Запустить кампанию" click happens before
  any read-back, so a swallowed clear failure would have shipped mangled
  copy and only reported an uncertain result afterwards.
- `_verify_created` now also rejects **unrequested** headline/text variants,
  not just missing ones. The previous membership-only check ("is each
  requested value present?") passed while AI-generated leftovers sat in the
  remaining slots.
- The `browser` extra now requires **`playwright>=1.44`** (was `>=1.40`):
  clearing a slot uses the `ControlOrMeta` modifier, which older versions
  reject server-side with `Unknown modifier`.
- A click failure on an **unused** slot (no caller-supplied value for it) is
  now fatal too, not a soft skip — a click failure does not distinguish
  "not rendered" from "obstructed but still holding AI-generated copy".
- The headline/text state check now runs **before** the terminal
  "Запустить кампанию"/"Сохранить как черновик" click, not only after: a
  clear that reports success without exception (a prevented Backspace, a
  lost selection, a rerender) can leave a slot's stale text intact, and
  `.type()` would append onto it rather than replace it. `create_master`
  now refuses to click the terminal button at all if the headline/text
  slots don't already match what was requested, instead of publishing the
  mismatch and only reporting it afterward.
- **Region** moved from a text combobox with autocomplete to a tree/tag-group
  widget (`RegionsTreeTagGroup`), which needed a genuinely different
  selection flow, not a new selector for the old one: open the popup via its
  launcher, type into the separate filter field that only exists while the
  popup is open, then tick the checkbox whose label is an EXACT match —
  typing a region auto-expands its parents and children, so a "contains"
  match would select the wrong node. Selected regions are read back from the
  widget's tags rather than from an input's value.
- The region click targets the **label**, not the `<input>` it wraps: the
  input resolves and even reports `is_visible() == True`, but clicking it
  times out on Playwright's actionability check, since the real hit target is
  the styled label. The input is still used to read state back — a label
  click toggles, so the read-back confirms the region really ended up
  selected instead of silently unchecking an already-selected one.
- The open→filter→select sequence is retried, and each retry starts from a
  known state: the launcher toggles the popup (so it is only clicked when the
  popup is closed) and typing appends to a `contenteditable` (so the filter
  field is cleared before every retype). Without both, retries could only
  ever be no-ops.
- A step-2 timeout now reports whether the page is still on step 1 (Yandex
  still scanning the landing page) or already past it (markup change),
  instead of leaving `--headful` as the only way to tell.
- Re-verified live and left unchanged: weekly budget, "Директ помогает" and
  "Цель продвижения" still render under real headings, so their existing
  heading-proximity locators were not broken by this migration.

## 0.5.1

**Added — `direct masters archive` (#633):**

- New command that archives a Мастер кампаний. Live recon confirmed Yandex's
  UI has **no separate "delete" action** for it — neither the campaigns
  grid's row menu nor the overview page's own menu has a "Удалить" item,
  only "Архивировать" (issue #633 comment documents the DOM structure
  found live). This is the closest thing to delete Мастер кампаний has.
- Clicks the overview page's "⋮" menu then "Архивировать" — both selected
  via stable, confirmed-live `data-testid` attributes
  (`CampaignHeader.MenuTrigger`/`CampaignHeader.Menu.archive`), unlike
  `suspend`/`resume`'s best-effort text-matched candidate buttons.
- Verifies success by re-reading the campaigns grid (`fetch_masters_list`)
  and confirming the status actually became `ARCHIVED`, rather than
  trusting the click alone. Idempotent: an already-archived campaign is a
  no-op warning, not an error.
- **Irreversible from this CLI** — there is no `masters unarchive`.
  Classified `DANGEROUS` in `direct_cli/smoke_matrix.py` (same as
  `suspend`/`resume`): Мастер кампаний has no API and thus no `--sandbox`
  isolation, so any exercise of this command hits a real account.

**Added — `direct masters update` (#631, Этап A):**

- New command that edits a single Мастер кампаний's settings page
  (`/wizard/campaigns/{id}/edit/`). This first stage covers exactly three
  simple scalar fields: `--weekly-budget` (integer, Недельный бюджет),
  `--promotion-goal` (`max-conversions`/`max-clicks`, Цель продвижения), and
  `--directs-helps`/`--no-directs-helps` (Директ помогает — auto-apply
  Yandex recommendations). At least one flag is required.
- Live investigation (see `tests/fixtures/masters_wizard_edit_stage_a.html`)
  found the edit page is a single form with one "Сохранить кампанию" button
  — there is no per-section independent save. `update_master` therefore
  submits the whole form on every call; fields not passed as flags are left
  untouched (their current on-page value is preserved simply by never
  filling/toggling their input).
- New `direct_cli/browser/masters.py` functions: `update_master` plus
  private `_set_weekly_budget`/`_set_directs_helps`/`_set_promotion_goal`
  setters. Each field setter follows the module's existing "click, then
  verify the change actually took effect" convention (`_suspend_or_resume`)
  rather than trusting a click alone. `update_master` itself also verifies:
  after clicking save it re-navigates to the edit page and re-reads every
  requested field (`_verify_saved`), raising `BrowserSessionError` on any
  mismatch instead of reporting a false success — so a click that doesn't
  actually persist (rejected validation, session/redirect failure) is a
  hard error, not a silent success.
- `_click_save` and `_set_promotion_goal`'s option click use
  `get_by_role(..., exact=True)`, not a substring `get_by_text` match — an
  exact accessible-name match, scoped to the actual button/option role,
  avoids clicking an ancestor container whose text merely contains the
  target label.
- Later Этап (B/C/D) fields — headline/text variant lists, sitelinks,
  audience, Metrika counters/goals, budget adaptation, images/video — are
  tracked separately in issue #631 and not implemented here.
- No `--sandbox` equivalent exists for this browser-driven mutation (same
  rationale as `masters suspend`/`resume`, #630) — classified `DANGEROUS` in
  `direct_cli/smoke_matrix.py` and documented as manual-only in
  `scripts/test_dangerous_commands.sh`.

**Added — `direct masters add` (#632):**

- New command that creates a brand-new "Конверсии и трафик" Мастер кампаний
  by driving the same multi-field create wizard a human uses in the browser
  (`https://direct.yandex.ru/wizard/campaigns/new/`) — Мастер кампаний has no
  API surface at all, same as `list`/`get`/`suspend`/`resume`.
- Live recon (issue #632 step 0, see
  `tests/fixtures/masters_wizard_create.html`) found the create flow is NOT
  the multi-page "Далее" wizard the issue originally assumed: it is one
  micro-step (a landing-page URL field with client-side format validation)
  followed by a single long form, terminating in two buttons — "Запустить
  кампанию" (launch) and "Сохранить как черновик" (save as draft) — instead
  of `masters update`'s one "Сохранить кампанию".
- `--headline`/`--text`/`--region` are required (repeat the flag for
  multiple values) even though Yandex's own wizard can auto-generate
  headlines/texts by scanning the landing page — `add` refuses to silently
  publish AI-written ad copy the caller never reviewed, given there is no
  sandbox or rollback for Мастер кампаний mutations.
- `--weekly-budget` is optional. `--draft`/`--launch` (default `--launch`)
  selects which terminal button is clicked.
- **NOT idempotent**: running this twice with the same arguments creates a
  *second* campaign, not an update to the first — documented prominently in
  the command's own `--help` and in the README, per the issue's explicit
  "Риски" requirement.
- Classified `DANGEROUS` in `direct_cli/smoke_matrix.py` and documented as
  manual-only (verify with `--draft` first) in
  `scripts/test_dangerous_commands.sh` — no `--sandbox` equivalent exists for
  Мастер кампаний.
- After clicking the terminal button, re-reads the headline/text/budget
  fields to confirm the form actually reflects what was requested
  (`_verify_created`) rather than trusting the click alone — ported from
  `masters update`'s `_verify_saved` pattern (issue #631 review finding).
  Dropdown/option clicks (`_fill_landing_url`'s "Далее", `_set_region`'s
  suggestion, `_click_terminal_button`'s launch/draft button) use
  `get_by_role(..., exact=True)`, not a substring `get_by_text` match — same
  fix applied to `update_master`'s `_click_save`/`_set_promotion_goal`, to
  avoid clicking an ancestor container whose text merely contains the
  target label.
- Not end-to-end live-verified: step 0 recon was deliberately read-only (no
  campaign was created or saved during recon) — see the browser module's
  docstring for what remains to be confirmed against a real account before
  relying on this in production. In particular, `_verify_created` cannot
  re-navigate and reload the way `_verify_saved` does (the post-click
  destination URL is unconfirmed), so it only re-reads the current page
  immediately after the click — a strictly weaker check pending a live
  pass.

**Added — `direct masters login` (#635):**

- New interactive command that opens a visible browser window on a
  persistent Chromium profile owned by the CLI
  (`~/.direct-cli/chrome-profile/` by default, overridable with
  `--profile-dir`). Log in by hand once via Yandex Passport; the command
  polls until the session is confirmed authenticated (or times out after
  `--timeout` seconds, default 300) and exits.
- Independent of `direct playwright login`/the macOS Keychain entirely —
  this never touches the user's real Chrome profile, so it works
  identically on macOS/Linux/Windows at the cost of a one-time manual login
  instead of a transparent cookie copy.
- `direct masters` (`list`/`get`/`suspend`/`resume`) prefers this persistent
  profile automatically whenever it exists, ahead of the saved
  `playwright login` session — see the new tier 1.5 in
  `direct_cli/commands/masters.py`'s session-resolution docstring.
- Interactive by design (blocks waiting for a human); classified
  `DANGEROUS` in `direct_cli/smoke_matrix.py` and documented as
  manual-only in `scripts/test_dangerous_commands.sh` — it cannot run in
  any automated smoke tier.
- The profile directory is chmod'd `0700` (it holds a live Yandex session in
  plaintext-readable cookies).
- New `direct masters logout` deletes the profile — the only way to revoke
  the on-disk session short of a manual `rm -rf`. A no-op with a warning
  (not an error) if no profile exists. Also classified `DANGEROUS`
  (local credential-store mutation, same category as `auth login`/`auth
  use`).
- `masters login` refuses to run without a terminal. It waits for a human,
  so in CI or a script it now fails immediately with a clear message instead
  of blocking for the full `--timeout` on a browser window nobody can see.
- `masters login` polls for completion on a separate page instead of the
  one the user is typing into. Previously the loop navigated the visible
  Passport tab to the grid once a second, wiping a half-filled login form
  or a pending 2FA prompt out from under the user.
- `masters login` refuses a `--profile-dir` that already exists without the
  CLI's own marker. Previously the marker was planted into whatever directory
  was named — so `masters login --profile-dir ~` marked the home directory as
  CLI-owned, and `masters logout` on the same path then accepted that marker
  as authorization to `shutil.rmtree` it. A failed login armed it just the
  same, since the marker was written before Chromium even launched.
- `masters login --profile-dir X` is now honoured by the read commands. The
  chosen directory is recorded, and `list`/`get`/`suspend`/`resume` resolve
  the profile through that record. Previously tier 1.5 looked only at the
  default location and passed no directory through, so a custom login path
  reported "Login confirmed" and was then silently ignored by every read —
  falling back to the Keychain the flag exists to avoid. `masters logout`
  clears the record along with the profile.
- The recorded profile path is stored and read as absolute. A relative value
  would have been re-resolved against whatever directory a later command ran
  from, so `masters logout` acted on a different profile depending on where
  the user stood.
- `masters` commands route through the persistent profile only when it holds
  an actual browser session, not merely when the directory exists. An aborted
  `masters login` leaves an empty profile behind; treating that as usable cost
  a wasted browser launch on every later command and bypassed the user's
  working saved session.
- `masters logout` refuses to delete anything `masters login` did not
  create. Every profile now carries a `.direct-cli-profile` marker file,
  and `logout` rejects a target that lacks it, is a symlink, or is not a
  directory. Without this a mistyped or shell-expanded `--profile-dir`
  (`.`, `~`) went straight into `shutil.rmtree` and recursively deleted an
  arbitrary tree.

**Added — `direct masters suspend` / `direct masters resume` (#630):**

- First mutating `masters` commands — stop/resume a Мастер кампаний by
  clicking its overview page's action button, then re-reading the status to
  confirm the change actually took effect (the click alone is never treated
  as success). Both are idempotent: a campaign already in the target status
  is a no-op with a warning, not an error. Neither has a `--sandbox`
  equivalent — Мастер кампаний has no API surface at all, so there is no
  isolated test copy; every mutation hits the real account (classified
  `DANGEROUS` in `direct_cli/smoke_matrix.py`, manual-only per
  `scripts/test_dangerous_commands.sh`).
- **Not live-verified:** the resume button's text ("Возобновить кампанию")
  is confirmed against a live account; the suspend/stop button's exact text
  is not — `direct_cli/browser/masters.py` tries a short list of plausible
  Russian labels and raises a clear error (suggesting `--headful`) if none
  match, rather than clicking the wrong element.

**BREAKING CHANGES — `direct masters` no longer accepts `--login` (#639):**

- `direct masters list`/`get` dropped the `--login` option. Passing your own
  login there built a `?ulogin=<login>` URL, but `ulogin` is Yandex's
  *managed-client* (agency) parameter — passing your own login as the managed
  client produced "Доступ ограничен" and HTTP 401 on the grid's data calls,
  which is exactly why `masters list` found nothing. `direct masters` only
  ever reads the logged-in browser session's own account now; there is no
  agency/managed-client support and no replacement flag.

**Fixed — `direct masters list` found no Мастера кампаний at all (#639):**

- Three independent bugs, found via live diagnosis: (1) the `--login`/
  `ulogin` issue above; (2) the DOM selector
  (`a[href*='/wizard/campaigns/']`) never matched anything, because the
  campaigns grid is a virtualized SPA that renders zero such anchors; (3) the
  `status-filter` URL query parameter was silently ignored by the grid.
  `list` now replays the grid's own JSON data call
  (`POST /web-api/grid/api?operationName=GridCampaigns`) instead of scraping
  the DOM, paginates past its 200-row page limit, and filters status on the
  client side using `status.primaryStatus`.

**Added — `direct masters list --status`:**

- New `--status` option (`not-archived` default, plus `active`, `stopped`,
  `archived`, `all`) lets you see only archived Мастера кампаний, or every
  status at once — previously `list` had no status filtering at all.

**New — `direct playwright login` / `direct playwright doctor`:**

- `direct masters` previously re-decrypted Chrome's Yandex cookies via the
  macOS Keychain on every single call. `direct playwright login` decrypts
  once and persists the result as a Playwright `storage_state` session
  (`~/.direct-cli/playwright/session.json`, `0600`) — `direct masters`
  automatically prefers this saved session over a fresh Keychain round-trip,
  falling back transparently when no session is saved, `--profile-dir`/
  `--chrome-profile` was passed explicitly, or the saved session has expired.
  Purely additive: `direct masters` continues to work with zero setup.
- `direct playwright doctor` reports the health of the whole pipeline
  (playwright/cryptography installed, chromium downloaded, Chrome profile
  found, Keychain key derivable, cookies decryptable, saved session
  present/fresh) without ever logging in, launching a browser, or writing to
  disk.
- Neither command requires a Yandex Direct API token/login.

**Fixed — `direct masters` didn't work on macOS at all (#634):**

- `direct masters list`/`get` previously copied `Cookies` + `Local State`
  into a throwaway Chrome profile, assuming Chromium would decrypt the
  cookies itself. On macOS this silently failed: the cookie AES key lives
  only in the login Keychain (`Chrome Safe Storage`); `Local State`'s
  `os_crypt.encrypted_key` is populated only on Windows. Every cookie was
  discarded, producing an unauthenticated session that landed on Yandex's
  login page and then timed out (`networkidle` never settles there, since
  the login page holds long-poll connections).
- `direct masters` now reads the Keychain password itself, derives Chrome's
  AES-128-CBC key, decrypts only the Yandex Direct cookies it needs, and
  injects them into a fresh bundled-Chromium context via `add_cookies()` —
  no more temp-profile copying, and `channel="chrome"` (which required a
  real Google Chrome install) is no longer needed.
- Login-page and expired-session failures are now reported explicitly
  (`BrowserAuthError`) instead of surfacing as an opaque 30s timeout.
- New optional dependency in the `browser` extra: `cryptography>=41`.
- Linux is supported (Chrome's basic/no-keyring password store only);
  Windows is not yet.

**New — `direct masters` (#628):**

- Added `direct masters list` / `direct masters get <ids>` — read-only access
  to Мастер кампаний (Campaign Wizard), which has **no Yandex Direct API
  surface at all** (do not confuse with `UNIFIED_CAMPAIGN`, an unrelated v5
  API campaign type already supported by `campaigns add/get --type
  unified_campaign`). These commands drive a real Chrome session via
  Playwright, decrypting and reusing the user's own Chrome cookies for
  `yandex.ru` — no separate login flow (see the Fixed entry above for the
  macOS Keychain decryption path added in #634). Requires the optional
  `browser` extra: `pip install "direct-cli[browser]" && playwright install
  chromium`. `direct masters` degrades gracefully (per-section warnings, not
  a hard failure) when Yandex's page markup changes, since this data has no
  API contract to rely on. See `direct_cli/browser/` for the scraping layer.

**Internal — campaigns.py split, step 1 — CPM_BANNER (#613, part of #602):**

- Extracted the `CPM_BANNER_CAMPAIGN` `add`/`update` subtype-block composition
  (the former inline `elif campaign_type_norm == "CPM_BANNER_CAMPAIGN":`
  branches) into a new sibling module
  `direct_cli/commands/_campaigns_cpm_banner.py` (`build_add_block` /
  `build_update_block`). Both commands now snapshot their CLI parameters once
  (`p = dict(locals())`) and delegate. The CLI surface, every flag and every
  `--dry-run` payload is byte-for-byte identical (28 `test_campaigns_*cpm*`
  fixtures green).

**Internal — campaigns.py split, step 3 (#615):**

- Extracted the `SMART_CAMPAIGN` add/update subtype-block composition
  (≈285 lines) into a new sibling module
  `direct_cli/commands/_campaigns_smart.py`
  (`build_add_block` / `build_update_block`). The `add` and `update`
  commands now snapshot their CLI parameters once via `p = dict(locals())`
  and delegate; the SmartCampaign builder pulls only the smart-relevant
  flags from `p`. CLI surface, every flag and every `--dry-run` payload is
  byte-for-byte identical (16 `test_campaigns_*smart*` fixtures green,
  offline tier 2521 passed, WSDL parity + API coverage green).

**Internal — campaigns.py split, step 1 (#602):**

- Extracted all shared constants (`CAMPAIGNS_GET_CRITERIA_LIMITS`, `YES_NO`,
  `ATTRIBUTION_MODELS`, …), typed-flag validators (`_validate_max_length`,
  `_validate_sms_time`), payload builders (`_build_notification`,
  `_build_time_targeting`, `_build_relevant_keywords`,
  `_build_dynamic_placement_types`, `_build_frequency_cap`,
  `_build_package_bidding_strategy`, `_build_smart_package_bidding_strategy`,
  `_priority_goals_update_items`, `_route_cpa_flag`) and the reusable
  TextCampaign strategy `click.option` groups (`_TEXT_*_STRATEGY_OPTIONS` and
  their `*_UPDATE` variants) into a new sibling module
  `direct_cli/commands/_campaigns_base.py`. `campaigns.py` re-imports every
  name, so the CLI surface, every flag and every `--dry-run` payload is
  byte-for-byte identical. First step of an incremental decomposition; the
  per-campaign-type logic (`text`, `unified`, `dynamic`, `smart`,
  `mobile_app`, `cpm_banner`) follows in subsequent PRs.

**Internal — `make_get_command` covers the complex Group-4 `get`s (#588):**

- `adgroups get`, `keywords get`, `creatives get`, `strategies get` and
  `audiencetargets get` now register through the shared `make_get_command`
  factory (net −345 lines). They reuse the existing `extra_options` /
  `criteria_builder` / `criteria_limits` / `require_criteria_message` /
  `nested_field_options` hooks — the `--status`/`--statuses` mutual-exclusion
  guard (adgroups/keywords) lives in the per-module `criteria_builder`, not a
  new factory flag. adgroups (8) and strategies (16) exercise the factory's
  largest nested-`*FieldNames` sets to date.
- Factory ordering fix: nested `*FieldNames` are now parsed (and their
  provided-but-empty-CSV `UsageError` raised) *before* both the criteria-limit
  enforcement and the empty-criteria `require_criteria_message` guard, matching
  the order every hand-rolled command used. So a `--<nested> ""` combined with
  either no filter at all or an over-limit array reports the nested error, not
  the require/limit one (pinned by a new `test_dry_run` regression test). The
  parsed dict is still merged after the common params, so payload key order is
  unchanged, and this also restores the pre-factory nested-before-limits order
  for the already-migrated `bidmodifiers get`. No module lacking both a nested
  option and a `criteria_limits`/`require_criteria_message` is affected.
- No CLI surface change: `--help` (option order, all nested-field options, the
  `--is-archived` choice/default), `--dry-run` payloads, and the error-precedence
  edge cases (empty-nested vs. no-filter and vs. over-limit) are byte-identical,
  verified against 33 pre-migration baselines captured via CliRunner from the
  pre-migration tree. As with every prior `make_get_command` migration, the
  factory resolves the API client only on the live path, so these five `get`s
  now honor `--dry-run` as a token-free test seam (no behavior change vs. the
  other factory-backed commands).
- Two Group-4 `get`s stay hand-rolled as documented carve-outs (see `_get.py`):
  `ads get` (its `TextAdFieldNames` is always emitted with a per-field default,
  like the carved-out `keywordbids`) and `campaigns get` (its `--fields` rejects
  an explicitly empty CSV instead of falling back to the default `FieldNames`).

**Internal — `make_get_command` covers the criteria-limit `get`s `bids` / `bidmodifiers` (completes #587):**

- `bids get` (criteria-limit + require-at-least-one-filter, no `--ids`) and
  `bidmodifiers get` (criteria-limit + 13 optional nested `*FieldNames`
  projections + a defaulted `--levels` criteria) now register through the
  shared `make_get_command` factory, reusing its existing `criteria_limits`,
  `require_criteria_message` and `nested_field_options` hooks (no new factory
  parameters). Net −230 lines.
- No CLI surface change: `--help` (option order, the 13 nested-field options,
  the `--levels` choice/default), `--dry-run` payloads (the criteria-limit
  enforcement, the `bids get` require-filter `UsageError`, the always-present
  `Levels` criteria and nested-field params) are byte-identical (verified
  against pre-migration baselines).
- This closes the migratable surface of #587. The three remaining `get`s stay
  hand-rolled as documented carve-outs, each for a structural reason the shared
  factory deliberately does not encode: `leads get` (`--datetime-from` /
  `--datetime-to` sit between `--limit` and `--fetch-all` — a bespoke option
  order), `keywordbids get` (its nested `SearchFieldNames` / `NetworkFieldNames`
  carry their own per-field defaults and are always emitted, unlike the factory's
  provided-only nested projections), and `reports get` (a custom non-RPC TSV
  stream, not a JSON-RPC `get`).

**Internal — `make_get_command` covers the no-`--ids` / wire-quirk `get`s (part of #587):**

- `agencyclients get` (no `--ids`; filters by `--logins` / `--archived`) and
  `adextensions get` now register through the shared `make_get_command` factory.
  The factory gained two more optional parameters: `include_ids` (set `False`
  for resources with no id filter — the command supplies a custom
  `criteria_builder` from its own options) and `adextensions_wire_layout` (a
  single-command flag that reproduces adextensions' exact recorded wire layout:
  always emit `SelectionCriteria` even when empty, and order nested
  `*FieldNames` before `Page`). The empty `SelectionCriteria` is a recorded API
  contract — the `adextensions_get` read cassette replays it and the API accepts
  it, unlike adgroups/ads/keywords.
- No CLI surface change: `--help`, `--dry-run` payloads (incl. the empty-criteria
  and nested-before-`Page` cases) and the read cassettes are byte-identical
  (verified against pre-migration baselines). Remaining carve-out: `leads get`,
  whose `--datetime-from` / `--datetime-to` options sit between `--limit` and
  `--fetch-all` — a bespoke option order that doesn't fit the shared
  `get_options` stack, so it stays hand-rolled.

**Internal — `make_get_command` covers the nested-`*FieldNames` `get`s (part of #587):**

- `adimages get`, `retargeting get`, `sitelinks get`, `feeds get` and
  `clients get` now register through the shared `make_get_command` factory
  (net −175 lines). The factory gained three optional, generic parameters:
  `nested_field_options` (a tuple of `(flag, WSDL key, help)` for nested
  `*FieldNames` projections, parsed via the existing `parse_nested_field_names`
  and rendered between `--fields` and `--dry-run`), `ids_criteria_key` (the
  SelectionCriteria key for `--ids`; `clients` uses `ClientIds`), and
  `fields_help` (a resource-specific `--fields` wording, e.g. sitelinks'
  "Comma-separated SitelinksSet FieldNames"). The shared `get_options` decorator
  (`utils.py`) gained matching `nested_options` / `fields_help` hooks, both
  defaulting to current behavior so its other callers are unchanged.
- No CLI surface change: `--help` (option order, the nested-field option
  position, the custom `--fields` help), `--dry-run` payloads (including the
  `ClientIds` key and nested-field params), and the provided-but-empty
  `*FieldNames` `UsageError` are byte-identical (verified against
  pre-migration baselines). Deferred to a follow-up: `adextensions` (emits an
  empty `SelectionCriteria` + Page-before-nested key order), and `leads` /
  `agencyclients` (no `--ids`; bespoke required criteria).

**Internal — `make_get_command` covers the criteria-limit ad-target `get`s (part of #587):**

- `dynamicads get`, `smartadtargets get` and `dynamicfeedadtargets get` — three
  byte-for-byte identical command bodies — now register through the shared
  `make_get_command` factory (`direct_cli/commands/_get.py`) instead of hand-rolled
  copies (net −131 lines). The factory gained two optional, generic parameters:
  `criteria_limits` (forwarded to `enforce_criteria_array_limits`, command name
  derived as `"<group> get"`) and `require_criteria_message` (the "provide at
  least one filter" guard), plus a shared `ids_adgroup_campaign_states_criteria`
  builder for the `Ids`/`AdGroupIds`/`CampaignIds`/`States` selection shape.
- No CLI surface change: `--help`, `--dry-run` payloads, the over-limit and
  empty-criteria errors, and module patchability are byte-identical (verified
  against pre-migration baselines). Group 2 (nested `*FieldNames`) and the
  no-`--ids` commands (`bids`, `keywordbids`, `bidmodifiers`) follow in a
  separate PR.

**Features — human-readable `text` output for reference commands (#578):**

- Local reference commands now default to a human-readable `text` format instead
  of raw JSON: `trackingparams` (dynamic tracking-parameter reference) and
  `dictionaries list-names` (previously hardcoded JSON with no `--format`). Both
  expose `--format {text,json,table,csv,tsv}` / `--output` via the new shared
  `reference_output_options` decorator (sibling of `v4_output_options`, default
  `text`). API-data commands keep their `json` default.
- Global `output.py` fix: `--format table/csv/tsv` now render a list of scalar
  values (e.g. dictionary names) as a single `Value` column instead of a Python
  `repr` (`['Currencies', …]`) / empty output. Affects any caller that passes a
  scalar list, not just the reference commands.

**Features — preflight `SelectionCriteria` array caps on remaining read-get commands (#571):**

- `ads`, `adgroups`, `bids`, `bidmodifiers`, `campaigns`, `keywords`,
  `dynamicfeedadtargets`, `audiencetargets` `get` now reject over-long
  `SelectionCriteria` arrays before the request and surface the array name and
  ceiling instead of the opaque API `error_code=4001`. Extends the
  `enforce_criteria_array_limits` discipline added in #555 to the rest of the
  read-get surface. Per-filter caps were measured live against the Yandex Direct
  sandbox on 2026-06-17 (see `scripts/measure_criteria_limits.py` and the
  `*_GET_CRITERIA_LIMITS` constant in each command module for the exact
  transcript).
- Closes a downstream consistency gap: the MCP plugin
  (`axisrow/yandex-direct-mcp-plugin#201`) can now drop its own batch-size
  guard and forward the CLI error.

## 0.4.3

**Fixes — known limitation: clearing a carousel AdImageHash (#574):**

- `ads update --clear-image-hash` builds a valid scalar `AdImageHash: null`
  (visible in `--dry-run`), but the live v5 API can reject it with `Error 5005`
  (`adImageHash=<[<null>]>`). Root cause: the ad carries a **server-side
  carousel image structure** that the documented `Ads.update` API does not
  expose — `TextAd` has only a single `AdImageHash` (no `Carousel` field exists
  anywhere in the v5 WSDL). Such a carousel image cannot be cleared through the
  API; it can only be removed in the Direct web interface. The CLI now surfaces
  a readable hint on `5005`/`AdImageHash` (explaining the carousel cause and the
  workaround) instead of the opaque error. The request payload is unchanged —
  the scalar null the CLI sends is correct; the rejection is the server's.
  Workaround: replace the image with a single `--image-hash <other>`, which the
  API accepts even on an active ad.

**Features — batch `ads add` via `--from-file` / `--ads-json` (#562, #558 follow-up):**

- `ads add` now accepts a batch of flag-form ad rows from a JSONL file
  (`--from-file`) or an inline JSON array (`--ads-json`); each row is the same
  flag set keyed by the kebab flag name without the leading dashes (e.g.
  `{"type":"TEXT_AD","title":"...","text":"...","href":"...","adgroup-id":1}`).
  `--adgroup-id` becomes the batch default and may be overridden per row. Single
  typed-flag mode is unchanged.
- The ~400-line flag→object logic of `ads add` was extracted into a reusable,
  ctx-free `build_ad_object()` so the single-flag command and the batch
  normalizer emit byte-identical ad objects (golden-tested across every
  subtype).
- New shared `direct_cli/commands/_batch.py` engine (JSONL/inline loading,
  chunking, per-chunk send with partial-success reporting, dry-run preview,
  `add`/`update`-aware result key). `keywords add` was migrated onto it with no
  behavior change (its existing batch suite is the proof).
- Chunk size `ADS_ADD_MAX_BATCH = 100` (conservative chunk, not the 1000-object
  API ceiling — a partial failure rolls back at most 100 ads).

**Features — batch `ads update` via `--from-file` / `--ads-json` (#563, #558 follow-up):**

- `ads update` now accepts a batch of flag-form ad-update rows from a JSONL file
  (`--from-file`) or an inline JSON array (`--ads-json`); each row is the same
  flag set keyed by the kebab flag name without the leading dashes plus its own
  `id` and `type` (e.g. `{"id":5,"type":"TEXT_AD","title":"New"}`). The
  `--clear-image-hash` mechanic works per row as a JSON boolean. Single
  typed-flag mode is unchanged.
- The subtype-dispatch body of `ads update` (type validation, the
  incompatible-flag / "does not convert between subtypes" guard, per-subtype
  assembly, and the empty-subtype no-op guard) was extracted into a reusable,
  ctx-free `build_ad_update_object()` so the single-flag command and the batch
  normalizer emit byte-identical ad-update objects (golden-tested across every
  subtype). Reuses the shared `_batch.py` engine with `method="update"` /
  `result_key="UpdateResults"`.
- `--id` and `--type` become per-row in batch mode (each row carries its own);
  single-item mode still requires both. The per-row normalizer reproduces the
  command's `--id`/`--type` required checks, the `--image-hash` /
  `--clear-image-hash` mutex, and the same Click-type coercion as the single
  path (a JSON float `id` is rejected, not truncated).

**Features — batch `adgroups add` via `--from-file` / `--adgroups-json` (#564, #558 follow-up):**

- `adgroups add` now accepts a batch of flag-form ad-group rows from a JSONL
  file (`--from-file`) or an inline JSON array (`--adgroups-json`); each row is
  the same flag set keyed by the kebab flag name without the leading dashes
  (e.g. `{"name":"G","campaign-id":12,"region-ids":"225","type":"TEXT_AD_GROUP"}`).
  `--campaign-id` becomes the batch default and may be overridden per row.
  Single typed-flag mode is unchanged.
- The flag→object logic of `adgroups add` (type validation, the
  incompatible-flag guard, the negative-keyword compatibility check, region IDs,
  and per-subtype assembly) was extracted into a reusable, ctx-free
  `build_adgroup_object()` so the single-flag command and the batch normalizer
  emit byte-identical ad-group objects (golden-tested across every subtype).
  `--name` / `--campaign-id` / `--region-ids` become per-row in batch mode;
  single-item mode still requires them (parity-gate `INTERNAL_VALIDATION`
  entries). Per-row coercion runs every typed field through its single-flag
  Click type (a JSON float `campaign-id` is rejected, not truncated).
- The shared `_batch.send_batch` gained an optional `post` callable so
  `adgroups` keeps its endpoint routing: a `UnifiedAdGroup` payload must use API
  v501 (`_post_adgroups`). Because that routing keys off the whole body, a batch
  may **not** mix `UNIFIED_AD_GROUP` with other ad-group types — the CLI refuses
  the mix up front with a clear `UsageError` rather than send non-unified groups
  to the v501 endpoint.

**Features — batch `adgroups update` via `--from-file` / `--adgroups-json` (#565, #558 follow-up):**

- `adgroups update` now accepts a batch of flag-form ad-group-update rows from a
  JSONL file (`--from-file`) or an inline JSON array (`--adgroups-json`); each
  row is the same flag set keyed by the kebab flag name without the leading
  dashes plus its own `id` (e.g. `{"id":5,"name":"New"}`). The `--dynamic-feed`
  routing works per row as a JSON boolean. Single typed-flag mode is unchanged.
- The subtype-dispatch body of `adgroups update` (the mixed-subtype reject
  guard, per-subtype assembly, the `--dynamic-feed` DynamicTextAdGroup ↔
  DynamicTextFeedAdGroup routing, and the empty-payload no-op guard) was
  extracted into a reusable, ctx-free `build_adgroup_update_object()` so the
  single-flag command and the batch normalizer emit byte-identical objects
  (golden-tested across every subtype). `--id` becomes per-row in batch mode;
  single-item mode still requires it (parity-gate `INTERNAL_VALIDATION` entry).
  Per-row coercion runs every typed field through its single-flag Click type (a
  JSON float `id` is rejected, not truncated).
- Reuses the shared `_batch.send_batch` with `method="update"` /
  `result_key="UpdateResults"` and the `post=_post_adgroups` endpoint routing.
  As with `adgroups add`, a batch may **not** mix `UNIFIED_AD_GROUP` with other
  ad-group types (unified groups use API v501) — the CLI refuses the mix up
  front with a clear `UsageError`.

**Fixes — reject non-positive IDs before the request (#558):**

- Mutating commands and lifecycle ops took their object-ID selector
  (`--id` / `--adgroup-id` / `--campaign-id` / `--keyword-id` / `--client-id`)
  as a bare `int`, which accepted `0` and negatives and forwarded them to the
  API (opaque rejection). Every such selector now uses `click.IntRange(min=1)`
  and rejects a non-positive id with a clear `UsageError` (exit 2) before any
  request. Coverage is the full mutation surface, not a subset:
  - every `delete` / `suspend` / `resume` / `archive` / `unarchive` /
    `moderate` lifecycle command (via the shared `_lifecycle.py` factory);
  - `ads add` / `ads update`, `adgroups add` / `adgroups update`,
    `keywords add` / `keywords update`;
  - `campaigns update`, `feeds update`, `strategies update`,
    `retargeting update`, `negativekeywordsharedsets update`, `vcards add`;
  - `smartadtargets add` / `update` / `set-bids`,
    `audiencetargets add` / `set-bids`, `dynamicads add` / `set-bids`,
    `dynamicfeedadtargets add` / `set-bids`;
  - the bid setters `bids set` / `set-auto`, `keywordbids set` / `set-auto`
    (the `campaign-id` / `adgroup-id` / `keyword-id` "exactly one of" trios),
    `bidmodifiers add` / `set`;
  - `agencyclients update --client-id`.

  The ad-image lifecycle (`--hash`, a string) is unchanged. Secondary
  reference-ID flags that point at *other* objects inside a write payload
  (e.g. `--feed-id`, `--counter-id`, `--vcard-id`, `--region-id`,
  `--retargeting-list-id`) are left as-is for now and tracked as follow-up.
- Batch-size caps (the docs allow up to 1000 objects per add/update and 10000
  ids per delete) are intentionally **not** added: the CLI builds a
  single-item payload for every mutation, so there is no caller-controllable
  array to overflow. Multi-item batch mode (`--from-file`) for ads/adgroups is
  tracked as follow-up work.
- De-staled the `KEYWORDS_ADD_MAX_BATCH` comment: it claimed the API caps a
  `keywords.add` request at 10 (citing an outdated doc page that states no such
  number). The real documented per-call limit is 1000; the value `10` is a
  conservative chunk size for batch add, not the API ceiling — comment fixed,
  value unchanged.

**Fixes — explain Error 8300 on delete/moderate (#548):**

- `raise_for_api_result_errors` now appends a hint when the API returns code
  8300, mirroring the existing 8800 hint: the ad is likely not in `DRAFT`
  status, and `Status=UNKNOWN` is an API fallback value (a status outside the
  v5 enum), not a business status — such ads can only be archived/unarchived,
  not deleted or sent to moderation. Covers `ads delete` / `ads moderate` and
  any command routing through `format_output`. English-only, matching the 8800
  hint (`output.py` does not import i18n).

**Docs — audiencetargets get requires a filter (#554):**

- Clarified that `audiencetargets get` cannot page the whole account: unlike
  `retargeting get --fetch-all`, the live API hard-rejects an empty
  `SelectionCriteria` (error 8000 with no criteria, 4001 with `{}`). The
  required-filter guard now explains this and recommends the `campaigns get` →
  batched `campaign_ids` sweep instead. No API behavior change; message only.

**Fixes — preflight SelectionCriteria array limits on get (#555, P0):**

- `keywordbids get` now rejects `--campaign-ids` >10, `--adgroup-ids` >1000,
  `--keyword-ids` >10000; `dynamicads get` / `smartadtargets get` reject
  `--campaign-ids` >2 — before the request, with a clear `UsageError` (exit 2)
  naming the array and ceiling, instead of the opaque API `error_code=4001`.
  These are runtime ceilings (the WSDL declares the arrays `unbounded`), pinned
  next to each command with a doc/live-4001 citation, the same discipline as
  `KEYWORDS_ADD_MAX_BATCH`. Verified live 2026-06-16. Other `get` arrays
  (`AdGroupIds`/`Ids` on dynamic/smart, etc.) are intentionally **not** capped
  because the live API accepts them.

**Internal — dedup v4 Live output-option stack (#550):**

- Replaced the byte-identical `--format`/`--output`/`--dry-run` trio across the
  standard v4 Live and `balance` commands with a shared `v4_output_options`
  decorator (the v4 analogue of `get_options`, epic #491). The CLI surface is
  unchanged — same option order, names, `click.Choice(["json","table","csv",
  "tsv"])` format, defaults, and help. `v4account enable-shared-account` /
  `account-management` (reversed order, custom `--dry-run` help) and the
  dry-run-only `v4finance transfer-money` / `pay-campaigns` /
  `pay-campaigns-by-card` (no `--format`/`--output`) keep their divergent
  stacks and are intentionally excluded.

**Fixes — `ads update` can now clear AdImageHash (#552):**

- Added `--clear-image-hash` to `ads update`. The flag sends
  `AdImageHash: null` so an image can be removed from an existing ad — e.g.
  unblocking a `TEXT_AD` whose image was restricted in moderation — without
  recreating the ad. Supported for the three subtypes whose WSDL `AdImageHash`
  is nillable: `TEXT_AD`, `DYNAMIC_TEXT_AD`, `MOBILE_APP_AD`. It is **rejected**
  for `TEXT_IMAGE_AD` and `MOBILE_APP_IMAGE_AD`, which share the non-nillable
  `ImageAdUpdateBase.AdImageHash` — the live API returns error 8000
  (`AdImageHash cannot have the null value`) for those, verified directly.
  `--image-hash` and `--clear-image-hash` are mutually exclusive.
  Previously there was no way to reset the image: `--image-hash ""` was dropped
  by a truthy check, and `--image-hash null` sent the literal string `"null"`.

**Fixes — docs-URL drift regression (re-fixes #463):**

- Restored the four WSDL `docs` URLs for `dynamicads`,
  `dynamicfeedadtargets`, `smartadtargets` and `vcards` that the
  `tapi-yandex-direct` 2026.5.29 vendor update silently reverted back to the
  removed `…/dev/direct/doc/ru/<service>` HTML pages (which 404 since Yandex
  dropped those pages in September 2025). The fix from #464 was overwritten by
  the `rm -rf` + `cp -R` vendor sync; preflight
  (`scripts/check_all_docs_urls.py`) caught it. URLs now point back at the live
  `https://api.direct.yandex.com/v5/<service>?wsdl` endpoints — the only
  authoritative source still served.
- Fixed the same URLs at the source in the `axisrow/tapi-yandex-direct` fork so
  the next vendor update no longer re-introduces the dead pages.
- Added an offline regression guard
  (`tests/test_audit_wire_shape.py::test_removed_doc_services_pin_wsdl_url`):
  the four doc-removed services must keep WSDL `docs` URLs, failing in CI before
  the network preflight ever runs.

**Bug Fixes — reject empty-string CSV-ID flags in `adgroups` (#570):**

- `adgroups add` and `adgroups update` now reject an explicitly-provided
  empty/whitespace value for `--region-ids`, `--negative-keyword-shared-set-ids`
  and `--feed-category-ids` (e.g. `--region-ids ""`, `--region-ids " "`,
  `--region-ids ","`, or a batch row `{"region-ids":""}`) with a clear
  `UsageError` instead of silently dropping the field. Previously `parse_ids("")`
  returned `None` and the `if region_ids:` guards treated a provided-but-empty
  value identically to an omitted option; for `RegionIds` (WSDL `minOccurs=1` on
  add) that stripped a required field and sent an invalid body to the live API.
- The fix is centralized in a new `_require_nonempty_ids_option` helper that
  distinguishes `None` (option omitted) from an all-blank value, so single mode
  and `--from-file` / `--adgroups-json` batch mode behave identically for both
  add and update. A genuinely malformed value with real tokens
  (e.g. `225,,226`) still reports the precise `Invalid ID` error, unchanged.

## 0.4.2

**BREAKING CHANGES - get requires SelectionCriteria (#498):**

- `adgroups` / `ads` / `keywords` / `strategies` / `creatives` / `dynamicads` /
  `smartadtargets` / `audiencetargets` `get` now refuse an empty
  `SelectionCriteria` before the API call, raising a `UsageError` that asks for
  at least one filter — instead of sending `{"SelectionCriteria": {}}` (which the
  API rejects with the opaque error 4001 for ad-group/ad/keyword resources).
  Extends the same guard already shipped for `bids` / `keywordbids` in 0.4.1
  (#483). WSDL declares `GetRequest.SelectionCriteria` as `minOccurs=1` for all
  eight resources.
- `retargeting get` gains `--dry-run` and the shared read/pagination option
  stack; its `SelectionCriteria` stays optional (WSDL `minOccurs=0`), so a
  no-filter call is still valid and now omits the empty criteria from the
  payload.
- All eight commands and `retargeting get` build their request via the shared
  `build_common_params` helper, completing the dedup epic #491 (B3c).

**BREAKING CHANGES - auth precedence (#489):**

- Base `YANDEX_DIRECT_TOKEN` / `YANDEX_DIRECT_LOGIN` credentials from the
  environment or current-directory `.env` now win over the active OAuth profile
  selected by `direct auth use` when `--profile` is not passed. Explicit
  `--token`, `--login`, and `--profile` still take priority.
- `direct auth status` reports the selected effective credentials, including
  base env/`.env` and secret-manager fallbacks, instead of reporting only the
  active OAuth profile.
- `direct auth login` can now ask interactive users whether to save the OAuth
  access token and resolved login into the current-directory `.env`; the default
  answer is no.

**Docs — live-write coverage limitation (#538):**

- Documented why the SMART_CAMPAIGN / DYNAMIC_TEXT_CAMPAIGN / `adimages`
  live-write lifecycle (`dynamicads`, `smartadtargets`, `adimages`) stays
  recorded only as 3500/5004 error cassettes. Verified via direct API calls that
  the available sandbox **agency** account has no client accounts under it
  (`agencyclients.get` → empty), cannot create one (3001 "No rights to create
  clients", access by request only), and that without a client login every
  agency-scoped mutation returns 8000. Closed #538 as a documented account-tier
  limitation; no CLI code change. See `tests/MANUAL_COVERAGE.md`.

## 0.4.1

Russian-default CLI localization across all command modules (epic #466).

**Fixed — bug hunt (#483):**

- `bids get` / `keywordbids get`: refuse an empty `SelectionCriteria` before the
  API call, raising a `UsageError` that asks for at least one filter
  (`--campaign-ids` / `--adgroup-ids` / `--keyword-ids` / `--serving-statuses`)
  instead of letting the API reject it with the opaque error 4001.
- `bids set-auto`: require exactly one of `--campaign-id`, `--adgroup-id`, or
  `--keyword-id` via the shared `add_single_id_selector` (the three are mutually
  exclusive per the API docs), matching `bids set`.
- `reports get`: reject a `--fields` value that parses to an empty list (for
  example `",,,"`) before building the request, instead of sending an invalid
  `FieldNames: []` (API error 8000).
- Error-handling consistency: `get`/lifecycle handlers across `bids`,
  `keywordbids`, `negativekeywordsharedsets`, `balance`, `strategies`,
  `retargeting`, `ads` (all 8 commands), and `advideos` now re-raise
  `click.UsageError` / `click.ClickException` before the generic
  `except Exception`, so validation errors keep their Click formatting and
  exit code 2 instead of being downgraded to an `Abort`.
- Vendor `tapi_yandex_direct`: `to_columns()` no longer raises `IndexError` on
  report rows shorter than the header (pads with `""`); the error handler reads
  `error_detail` with `.get()` so an unfamiliar error structure no longer masks
  the original API error with a `KeyError`.
- `utils.parse_priority_goals_spec`: corrected the item type annotation to
  `List[Dict[str, Any]]` (items hold `"YES"/"NO"` strings, not only ints).

**Fixed — `--help` hung on a client-login network call (#480 follow-up):**

- After #480, `get_credentials` resolved the bare Client-Login via a network
  `clients.get` on every CLI invocation — including `<group> --help` — whenever
  an OAuth profile with an email login had not yet been migrated. That call had
  no timeout, so a slow link or a Yandex SmartCaptcha gateway could hang the
  CLI. Help/version passes now skip the resolver, the resolver is capped with a
  hard timeout, and the unit suite neutralizes it so tests never touch the
  network.

**Fixed — auth login saved Passport email, breaking v4 (#480):**

- `direct auth login` (OAuth / PKCE) stored the Passport email
  (`<login>@yandex.ru`) in `auth.json`, which Direct v4 AccountManagement
  rejects with `FaultCode 259` ("This client does not exist") — breaking
  `direct balance` and `direct v4account ...`. Login now resolves the bare
  **Client-Login** via a one-shot v5 `clients.get` (`resolve_account_login`),
  falling back to the Passport login only if that call fails.
- `get_credentials` migrates older profiles in place: when a stored OAuth login
  is an email whose local part matches the token owner's resolved Client-Login,
  it is rewritten to the bare login (one-time, persisted). Agency profiles whose
  login differs from the token owner are never clobbered, and an explicit
  `--login` is never overridden.

**Localized — interpolated error messages (#478), completing epic #466:**

- Rewrote all 121 interpolated `click.UsageError` / `click.BadParameter` /
  `print_*` messages (114 f-strings + 7 string concatenations) across the
  command modules into the stable `t("<template>").format(**kwargs)` pattern,
  with 96 unique English templates translated to Russian (6 shared templates,
  e.g. `Provide a non-empty comma-separated {wsdl_key} list.`, in
  `common.json`). Placeholder names, conversions, and format specs are
  preserved verbatim in both locales, so the rendered English text is
  byte-identical to before and the Russian render fills the same fields.
- `t()` gained `@overload` signatures (`str -> str`, `None -> None`) so
  `t(...).format(...)` type-checks without touching call sites.
- `tests/test_i18n.py` now (a) flags f-string / concat — not just static —
  bare literals in `_RUNTIME_MESSAGE_FUNCS` calls (also covering
  `print_success`), accepting only `t(...)` / `t(...).format(...)`; and
  (b) asserts placeholder parity between every English template key and its
  Russian translation. This completes the error-message localization checklist
  of epic #466.

**Localized — static error messages (#477):**

- Wrapped all 179 static `click.UsageError` / `click.BadParameter` string
  literals (and the `auth` OAuth-code `click.prompt`) across 33 command
  modules in `t(...)`, with Russian translations added to the per-module
  `translations/*.json` catalogs; seven messages shared across modules
  (e.g. `Provide at least one field to update`,
  `--status and --statuses are mutually exclusive`) live in `common.json`.
  Validation errors now render in Russian by default and in English under
  `--locale en`. Flag names, enum values, and WSDL field names are unchanged.
- Extended `tests/test_i18n.py::test_localized_groups_wrap_runtime_messages`
  to also scan `UsageError` / `BadParameter` / `prompt` / `confirm` (bare or
  `click.<Name>`); a bare string literal first argument is rejected. Only
  static `ast.Constant` literals are enforced for now — interpolated
  (f-string / concat) messages are stage B (#478).
- Test suite defaults the CLI locale to English (`tests/conftest.py` autouse
  fixture) so the existing English error-contract assertions stay valid; the
  Russian default remains covered by `tests/test_i18n.py`.

**Added — scalable i18n mechanism (#467):**

- Source-string-keyed translation catalog: the English `help=` / docstring /
  epilog text is the catalog key, with Russian translations in external
  `direct_cli/translations/*.json` files (one per module, plus shared
  `common.json`). No `cls=`/`help_key` edits in command modules —
  `cli._apply_directcli_classes` retypes every plain `click.Option` to
  `LocalizedOption` and localizes command/group docstrings and epilogs at
  render time.
- `t()` is now source-keyed and context-free safe (`set_active_locale`), so
  `print_*` runtime messages localize too. `--locale` is eager so the root
  `--help` epilog honors an inline `--locale`.
- `tests/test_i18n.py` gains a `LOCALIZED_GROUPS` registry with two enforced
  invariants per localized module: translation completeness (no silent English
  leak under the Russian default) and `print_*` runtime-message wrapping.
- `v4finance` migrated to the new mechanism and fully localized as the
  reference module.

**Localized — Core search (#468):**

- Russian help/docstrings for `campaigns`, `ads`, `adgroups`, `keywords`,
  `keywordbids`, and `bids` (510 unique strings across the six modules).
  WSDL field paths, enum values, and flag names are kept verbatim; only
  human-readable text is translated. These groups join `LOCALIZED_GROUPS`,
  so their translation completeness is now enforced by `test_i18n.py`.

**Localized — Targeting & creatives (#469):**

- Russian help/docstrings for `strategies`, `bidmodifiers`, `smartadtargets`,
  `vcards`, `feeds`, `dynamicads`, `audiencetargets`, `dynamicfeedadtargets`,
  `retargeting`, `negativekeywordsharedsets`, `adextensions`, `adimages`,
  `sitelinks`, `creatives`, `advideos`, and `turbopages` (247 unique strings
  across the sixteen modules). WSDL field paths, enum values, and flag names
  are kept verbatim; only human-readable text is translated. These groups
  join `LOCALIZED_GROUPS`, so their translation completeness is now enforced
  by `test_i18n.py`.

**Localized — Account, clients, reporting (#470):**

- Russian help/docstrings for `clients`, `agencyclients`, `reports`, `changes`,
  `auth`, `leads`, `dictionaries`, `keywordsresearch`, `businesses`, and
  `balance` (142 source strings across the ten modules). WSDL field paths,
  enum values, and flag names are kept verbatim; only human-readable text is
  translated.
- First modules with localized **runtime messages**: `print_*` calls carrying a
  human-readable literal (`auth` interactive prompts, the `agencyclients delete`
  not-supported notice) are now wrapped in `t()` so they follow the active
  locale. `print_error(str(e))` API-error passthroughs are unchanged. These
  groups join `LOCALIZED_GROUPS`, enforcing both translation completeness and
  the runtime-message wrapping invariant.

**Localized — v4 Live services (#471), completing epic #466:**

- Russian help/docstrings for `v4account`, `v4tags`, `v4forecast`,
  `v4wordstat`, `v4events`, `v4adimage`, `v4goals`, `v4keywords`, and `v4meta`
  (87 source strings across the nine modules). `v4finance` was already
  localized as the reference module in #467.
- With these groups, **all 42 CLI command groups are in `LOCALIZED_GROUPS`**:
  the completeness invariant now covers the entire command tree, so every
  English help/docstring string ships with a Russian translation under the
  Russian default. The `v4 Live` epilog (single-sourced docs URL) stays
  verbatim per the URL-registry rule. This closes the localization epic #466.

## 0.4.0

Milestone release closing the 0.4.0 roadmap (#123): typed Yandex Direct
API **v4 Live** CLI support and completion of the post-0.3.0 write-command
coverage gates. All public v4 input stays typed and canonical — no `--json`
passthrough — and mirrors `dg-v4/live/*` wire shapes 1:1.

**Added — typed v4 Live CLI:**

- v4 Live command foundation with typed Click groups and a `--dry-run`
  seam that prints the `{method, param}` body before token/locale
  enrichment (#124, closes #111 — typed CLI, not raw JSON passthrough).
- `v4finance` and `v4account` typed finance and shared-account commands
  (#125).
- `v4goals`, `v4events`, `v4wordstat`, and `v4forecast` typed commands
  (#126).
- `v4events get-events-log` and `v4forecast create-new-forecast` now expose
  every documented input field (#456).
- Russian-default CLI help with English opt-in, starting with `v4finance`
  (#458).

**Changed — write-command coverage gates:**

- Extended the WSDL schema gate to mutating operations; `keywordbids.set`
  is now enum-validated against its WSDL `*FieldEnum` (#118).
- Per-method `WRITE_SANDBOX` integration coverage completed — zero
  unexplained `NOT_COVERED` commands in `direct_cli/smoke_matrix.py`
  (#122).
- Closed the remaining mutating `DRY_RUN_PAYLOAD_EXCLUSIONS`; every
  declared WSDL operation now has a `PAYLOAD_CASES` fixture or a
  documented technical exclusion (#127).

**Tests / tooling:**

- Offline VCR cassettes for all v5 read-only commands (#455).
- v4 Live read cassettes and a fix for an unbounded retry-loop (#457,
  closes #454).
- Docs/wire-shape scanner with the 2026-05-29 sweep (#451).

`strict_parity_ok`, `live_model_parity_ok`, and `schema_parity_ok` all
report `true` in `scripts/build_api_coverage_report.py`.

## 0.3.16

**BREAKING CHANGES (regression fix — reverts 0.3.15 wire-shape changes):**

- `direct v4finance transfer-money` now requires `--currency` again and
  re-emits `Currency` on every `FromCampaigns` / `ToCampaigns` item.
  The 0.3.15 removal verified against `dg-v4/reference/TransferMoney`
  (legacy v4); the actual Live 4 docs at
  `dg-v4/live/TransferMoney` define `PayCampElement` with
  `CampaignID`, `Sum`, and `Currency`, and explicitly mark `Currency` as
  obligatory in the Live 4 changelog. The CLI now matches the live
  docs 1:1. See audit comment on #125 for the reproducible diff.
- `direct v4finance pay-campaigns` now requires `--currency` again and
  re-emits `Currency` on every `Payments[]` item. Same root cause:
  `dg-v4/reference/PayCampaigns` (legacy) lacks `Currency`,
  `dg-v4/live/PayCampaigns` (Live 4) requires it.
- `direct v4finance pay-campaigns` accepts `--pay-method Overdraft`
  again. The Live 4 changelog explicitly adds `Overdraft` for direct
  advertisers (paired with `Bank` for agencies). Only `Bank` keeps the
  `--contract-id` requirement.
- `direct v4finance create-invoice` now requires `--currency` again and
  re-emits `Currency` on every `Payments[]` item, mirroring
  `dg-v4/live/CreateInvoice`.

This release reverts the wire-shape changes shipped by PRs #441, #442,
#443 (which closed #432, #433, #434). The CLI lives in the `v4finance`
Live group and must mirror `dg-v4/live/*`, not `dg-v4/reference/*`.

## 0.3.15

**BREAKING CHANGES:**

- `direct v4finance transfer-money` no longer accepts `--currency`, and
  the wire-body no longer carries `Currency` on `FromCampaigns`/
  `ToCampaigns` items. The official v4 docs
  (`dg-v4/reference/TransferMoney`) define `PayCampElement` with only
  `CampaignID` and `Sum`; `Sum` is in conventional units. The CLI now
  matches the docs 1:1. Closes #432.
- `direct v4finance pay-campaigns` no longer accepts `--currency`. The
  v4 documentation (`dg-v4/reference/PayCampaigns`) defines
  `PayCampElement` with only `CampaignID` and `Sum` — `Currency` is not
  part of the wire-body and was never forwarded to the API. The option
  is removed entirely to make the CLI surface 1:1 with the docs.
- `direct v4finance pay-campaigns` no longer accepts `--pay-method
  Overdraft`. The v4 documentation
  (`dg-v4/reference/PayCampaigns#PayMethod`) lists only `"Bank"` as a
  supported value; `Overdraft` was a historical undocumented value
  retained by the CLI for sandbox flow. Strict 1:1 docs alignment
  drops it.
- `direct v4finance create-invoice` no longer accepts `--currency`. The
  v4 documentation (`dg-v4/reference/CreateInvoice`) defines
  `PayCampElement` with only `CampaignID` and `Sum` — `Currency` is not
  part of the wire-body and was never forwarded to the API. The option
  is removed entirely to make the CLI surface 1:1 with the docs.

## 0.3.14

**Fixed:**

- Reports drift checker now points at the canonical Yandex docs URLs
  (`/ru/type`, `/ru/period`, `/ru/fields-list`, `/ru/spec`) after Yandex
  retired the `/ru/reports/<page>` path layout and renamed `spec.html`
  to `spec`. The pre-existing `tests/reports_cache/raw/` had silently
  been captcha-poisoned for three of those pages (~14.6 KB Yandex
  SmartCaptcha gateway in place of real docs); cache is now refetched
  from the live canonical URLs and `spec.json` is byte-equivalent to
  the pre-migration snapshot except for one updated description string.
- Five `RESOURCE_MAPPING_V5[*]["docs"]` URLs that Yandex moved from the
  legacy `…/ru/<group>/<group>` to `…/ru/<group>` single-segment form
  (`dynamictextadtargets`, `dynamicfeedadtargets`, `reports`,
  `smartadtargets`, `vcards`). Closes #426.

**Added (drift protection):**

- `direct_cli/reports_coverage.py::fetch_reports_spec` and
  `direct_cli/wsdl_coverage.py::fetch_wsdl` / `fetch_live_wsdl` now
  refuse responses that look like a Yandex SmartCaptcha gateway (markers
  `showcaptcha`, `smartcaptcha`, `<title>Captcha`) or are suspiciously
  short. This prevents silently poisoning the docs/WSDL cache with
  rate-limited captcha HTML.
- `tests/test_api_coverage.py::TestReportsCoverage::test_reports_cache_files_are_real_content`
  and `TestWsdlCacheFreshness::test_wsdl_cache_files_are_real_content`
  guard the committed cache files against the same poisoning.
- `scripts/check_all_docs_urls.py` — health-checks every URL in
  `RESOURCE_MAPPING_V5` and `REPORTS_SPEC_URLS`. Hard-fails on
  redirect-to-captcha, canonical move (`Location` with a different path
  segment), 4xx, or captcha body; soft-warns on 5xx; paces requests to
  avoid Yandex rate-limit. Wired into `scripts/release_pypi.sh` as a
  mandatory pre-release gate together with `refresh_reports_cache.py`
  and a focused pytest pass.

**Contract** (`CLAUDE.md`):

- New rule "No URL literals outside the registry" — every Yandex
  docs/API URL is declared once in `RESOURCE_MAPPING_V5` or
  `REPORTS_SPEC_URLS`; importers reference the constant.
- New rule "Docs/cache freshness guard" — fetchers and cache files
  enforce minimum-size and no-captcha invariants.
- New section "PyPI Release" — documents the three pre-release health
  checks executed by `release_pypi.sh`.

**Breaking changes:**

- `direct ads get` flag `--text-ad-fields` is **renamed** to the
  WSDL-canonical `--text-ad-field-names` form matching the
  `TextAdFieldNames` request parameter declared by `AdsGetRequest`.
  The old `--text-ad-fields` form is no longer accepted — update
  scripts and automation accordingly. Closes #406.
- `direct campaigns add` / `direct campaigns update` and `direct
  strategies add` / `direct strategies update` now reject `--priority-goals`
  / `--priority-goal` values below 100,000 (0.1 unit in micro-currency).
  Per Yandex Direct API (add-text-campaign, strategies-types),
  `PriorityGoalsItem.Value` is `xsd:long` in advertiser currency
  multiplied by 1,000,000 — the same contract as `--budget`,
  `--average-cpa`, and other money flags after #399/#400. The error
  message suggests the micro-currency conversion (e.g. `Did you mean
  500000000?`). Negative values are also rejected up-front rather than
  reaching the API. Both parsers share a single
  `validate_priority_goal_value` helper. Closes #387.

**Added:**

- `direct sitelinks get` now exposes `--sitelink-field-names` for the
  separate WSDL `SitelinkFieldNames` request parameter
  (`SitelinkFieldEnum`: `Title`, `Href`, `Description`, `TurboPageId`).
  Previously only the top-level `--fields` (mapping to `FieldNames`)
  was available, so the nested `Sitelinks[]` projection could not be
  controlled from CLI.
- `direct keywordbids get` now exposes `--fields`,
  `--search-field-names`, and `--network-field-names` for the
  separate `FieldNames`, `SearchFieldNames`, and `NetworkFieldNames`
  request parameters declared by `KeywordBidsGetRequest`. Defaults
  from `COMMON_FIELDS` are preserved when flags are absent.
- Regression test `test_every_nested_fieldnames_param_has_cli_option`
  (`tests/test_api_coverage.py`) scans every cached WSDL `get`
  request type for `*FieldNames` parameters and verifies that each
  one has a matching kebab-case CLI option. Acknowledged remaining
  gaps are tracked in `NESTED_FIELDNAMES_EXCLUSIONS` and #402 so
  future additions cannot silently slip in.
- `direct feeds get` now exposes `--file-feed-field-names` and
  `--url-feed-field-names` for the separate WSDL `FileFeedFieldNames`
  (`FileFeedFieldEnum`: `Filename`) and `UrlFeedFieldNames`
  (`UrlFeedFieldEnum`: `Login`, `Url`, `RemoveUtmTags`) request
  parameters declared by `FeedsGetRequest`. Previously only the
  top-level `--fields` (mapping to `FieldNames`) was available, so
  the nested `FileFeed` / `UrlFeed` projections could not be
  controlled from CLI. Closes #412.
- `direct keywords get` now exposes
  `--autotargeting-settings-brand-options-field-names`
  (`AutotargetingBrandOptionsFieldEnum`: `WithoutBrands`,
  `WithAdvertiserBrand`, `WithCompetitorsBrand`) and
  `--autotargeting-settings-categories-field-names`
  (`AutotargetingCategoriesFieldEnum`: `Exact`, `Narrow`,
  `Alternative`, `Accessory`, `Broader`) for the separate WSDL
  `*FieldNames` request parameters declared by
  `KeywordsGetRequest`. Previously only the top-level `--fields`
  (mapping to `FieldNames`) was available, so the nested
  `AutotargetingSettings.BrandOptions` / `Categories` projections
  could not be controlled from CLI. Closes #413.
- `direct creatives get` now exposes
  `--cpc-video-creative-field-names`,
  `--cpm-video-creative-field-names`,
  `--smart-creative-field-names`, and
  `--video-extension-creative-field-names` for the four nested
  WSDL `*FieldNames` request parameters declared by
  `CreativesGetRequest` (`CpcVideoCreativeFieldEnum`,
  `CpmVideoCreativeFieldEnum`, `SmartCreativeFieldEnum`,
  `VideoExtensionCreativeFieldEnum`). Previously only the top-level
  `--fields` (mapping to `FieldNames`) was available, so the
  per-subtype projections could not be controlled from CLI.
  Closes #411.
- `direct clients get` now exposes `--contract-field-names`,
  `--contragent-field-names`, `--contragent-tin-info-field-names`,
  `--organization-field-names`, and `--tin-info-field-names` for
  the five nested WSDL `*FieldNames` request parameters declared
  by `ClientsGetRequest` (`ContractInfoFieldEnum`,
  `ContragentInfoFieldEnum`, `TinInfoFieldEnum`,
  `OrgInfoFieldEnum`, `TinInfoFieldEnum`). The command also gains
  `--dry-run` for parity with other read-path commands.
  Previously only the top-level `--fields` (mapping to `FieldNames`)
  was available, so the per-subtype ERIR projections could not be
  controlled from CLI. Closes #410.
- `direct agencyclients get` now exposes `--contract-field-names`,
  `--contragent-field-names`, `--contragent-tin-info-field-names`,
  `--organization-field-names`, and `--tin-info-field-names` for
  the five nested WSDL `*FieldNames` request parameters declared
  by `AgencyClientsGetRequest` (`ContractInfoFieldEnum`,
  `ContragentInfoFieldEnum`, `TinInfoFieldEnum`,
  `OrgInfoFieldEnum`, `TinInfoFieldEnum`). The command also gains
  `--dry-run` for parity with other read-path commands.
  Previously only the top-level `--fields` (mapping to `FieldNames`)
  was available, so the per-subtype ERIR projections could not be
  controlled from CLI. Closes #407.
- `direct adgroups get` now exposes eight additional
  `--*-field-names` flags for the separate WSDL `*FieldNames`
  request parameters declared by `AdGroupsGetRequest`:
  `--autotargeting-settings-brand-options-field-names`,
  `--autotargeting-settings-categories-field-names`,
  `--dynamic-text-ad-group-field-names`,
  `--dynamic-text-feed-ad-group-field-names`,
  `--mobile-app-ad-group-field-names`,
  `--smart-ad-group-field-names`,
  `--text-ad-group-feed-params-field-names`, and
  `--unified-ad-group-field-names`. Previously only the top-level
  `--fields` (mapping to `FieldNames`) was available, so the
  per-subtype ad-group projections could not be controlled from
  CLI. Closes #405.
- `direct ads get` now exposes sixteen additional `--*-field-names`
  flags for the separate WSDL `*FieldNames` request parameters
  declared by `AdsGetRequest`: `--cpc-video-ad-builder-ad-field-names`,
  `--cpm-banner-ad-builder-ad-field-names`,
  `--cpm-video-ad-builder-ad-field-names`,
  `--dynamic-text-ad-field-names`, `--listing-ad-field-names`,
  `--mobile-app-ad-builder-ad-field-names`,
  `--mobile-app-ad-field-names`,
  `--mobile-app-cpc-video-ad-builder-ad-field-names`,
  `--mobile-app-image-ad-field-names`,
  `--responsive-ad-field-names`, `--shopping-ad-field-names`,
  `--smart-ad-builder-ad-field-names`,
  `--text-ad-builder-ad-field-names`,
  `--text-ad-field-names`,
  `--text-ad-price-extension-field-names`, and
  `--text-image-ad-field-names`. Previously only the top-level
  `--fields` (mapping to `FieldNames`) and non-canonical
  `--text-ad-fields` were available, so the per-ad-subtype projections
  could not be controlled from CLI. Closes #406.

**BREAKING CHANGES:**

- `direct campaigns get` flags `--text-campaign-fields`,
  `--mobile-app-campaign-fields`, `--dynamic-text-campaign-fields`,
  `--cpm-banner-campaign-fields`, `--smart-campaign-fields`,
  `--unified-campaign-fields`,
  `--text-campaign-search-strategy-placement-types-fields`,
  `--dynamic-text-campaign-search-strategy-placement-types-fields`,
  `--unified-campaign-search-strategy-placement-types-fields`, and
  `--unified-campaign-package-bidding-strategy-platforms-fields`
  are **renamed** to their kebab-case WSDL-canonical `*-field-names`
  form (`--text-campaign-field-names`,
  `--mobile-app-campaign-field-names`, ...), matching the parameter
  names declared by `CampaignsGetRequest`. The old `--*-fields`
  forms are no longer accepted — update scripts and automation
  accordingly. Closes #409.

**Additional features:**

- `direct bidmodifiers get` now exposes thirteen additional
  `--*-adjustment-field-names` flags for the per-adjustment-subtype
  WSDL `*FieldNames` request parameters declared by
  `BidModifiersGetRequest`: `--ad-group-adjustment-field-names`,
  `--demographics-adjustment-field-names`,
  `--desktop-adjustment-field-names`,
  `--desktop-only-adjustment-field-names`,
  `--income-grade-adjustment-field-names`,
  `--mobile-adjustment-field-names`,
  `--regional-adjustment-field-names`,
  `--retargeting-adjustment-field-names`,
  `--serp-layout-adjustment-field-names`,
  `--smart-ad-adjustment-field-names`,
  `--smart-tv-adjustment-field-names`,
  `--tablet-adjustment-field-names`, and
  `--video-adjustment-field-names`. Previously only the top-level
  `--fields` (mapping to `FieldNames`) was available, so the
  per-adjustment projections could not be controlled from CLI.
  Closes #408.
- `direct strategies get` now exposes sixteen additional
  `--strategy-*-field-names` flags for the separate WSDL
  `*FieldNames` request parameters declared by `StrategiesGetRequest`,
  including `--strategy-average-cpa-field-names`,
  `--strategy-average-cpa-multiple-goals-field-names`,
  `--strategy-average-cpc-field-names`,
  `--strategy-maximum-clicks-field-names`,
  `--strategy-maximum-conversion-rate-field-names`,
  `--strategy-pay-for-conversion-field-names`, and the remaining
  per-campaign / per-filter strategy projections. The command also
  gains `--dry-run` for read-path payload tests. Previously only the
  top-level `--fields` (mapping to `FieldNames`) was available, so
  per-strategy-subtype projections could not be controlled from CLI.
  Closes #414.

Closes #360.

**Tests:**

- `tests/test_integration.py` now gracefully skips the seven read-only
  classes that rely on live-API probes (`TestReadOnlyAdGroups`,
  `TestReadOnlyAds`, `TestReadOnlyKeywords`,
  `TestReadOnlyDynamicFeedAdTargets`, `TestReadOnlyLeads`,
  `TestReadOnlyBusinesses`, `TestReadOnlyAdVideos`) when the probe
  raises — previously a temporary API outage crashed `setUpClass`
  with an opaque traceback.
- `invoke_get` in `tests/test_integration.py` now passes the resolved
  test credentials as explicit `--token`/`--login` flags so the
  integration suite cannot silently fall through to a developer's
  active `direct auth` profile (priority 1 in the CLI credential
  chain wins over the profile, matching CLAUDE.md guidance).
- `tests/test_comprehensive.py` slimmed down: `TestCLIHelp` (full
  duplicate of `tests/test_cli.py`) removed; the unique
  `TestCommandsRegistered`, `TestUtils`, `TestOutputFormatters`,
  `TestAuth`, and `TestErrorHandling` classes are kept.
- `tests/test_smoke_matrix.py` no longer hard-codes
  `total_cli_subcommands == 144` or `wsdl_operations == 112`. Counts
  are derived from the live Click registry and parsed WSDLs.
- `tests/test_sandbox_write_audit.py` no longer hard-codes
  `total == 83`. The count derives from `commands_for_category`.

Closes #396.

## 0.3.13

**Breaking changes:**

- `direct campaigns add` and `direct campaigns update` now require all
  bidding-strategy money flags to be passed directly in micro-rubles,
  matching the existing `--budget`, `--average-cpa`, `--bid-ceiling`, and
  `--filter-average-cpc` contract. The CLI no longer accepts decimal currency
  values or performs unit conversion for campaign money
  inputs. Closes #399.
- `direct ads add` and `direct ads update` now apply the same API-native
  micro-ruble contract to `--price-extension-price` and
  `--price-extension-old-price`; price-extension values are no longer parsed
  as decimal currency amounts.

## 0.3.12

**Added:**

- `direct ads update` now exposes `--callouts-add`, `--callouts-remove`,
  and `--callouts-set` for managing the
  `TextAdUpdateBase.CalloutSetting` field
  (`ext:AdExtensionSetting`). Each flag accepts a comma-separated list
  of `CALLOUT`-type ad-extension IDs; `--callouts-set` replaces the
  full callout list and is mutually exclusive with the incremental
  `--callouts-add` / `--callouts-remove` pair (enforced via
  `click.UsageError` before any request is built). Flags are
  TEXT_AD-only — per-subtype validation rejects them on `TEXT_IMAGE_AD`
  / `MOBILE_APP_AD` with the standard "not compatible with --type"
  message. Empty CSV input is rejected up-front rather than silently
  producing a no-op payload. Closes #238.
- `direct adgroups add` and `direct adgroups update` now expose
  `--tracking-params` for the top-level `AdGroup*.TrackingParams`
  field. Values are limited to the documented 1024-character maximum;
  `update` does not require `--type` because the field belongs to the
  ad group item itself, not a subtype block. Closes #242.
- `direct adgroups add` and `direct adgroups update` now expose
  `--negative-keywords` and `--negative-keyword-shared-set-ids` for
  `NegativeKeywords.Items` and `NegativeKeywordSharedSetIds.Items`.
  Empty list input is rejected, shared-set IDs are parsed as integers,
  and `update` treats either flag as a meaningful field for the
  no-op guard. Closes #243.
- `direct ads update --type TEXT_AD` now exposes
  `--video-extension-creative-id` for `TextAd.VideoExtension.CreativeId`
  and `--price-extension-price`, `--price-extension-old-price`,
  `--price-extension-price-qualifier`, and
  `--price-extension-price-currency` for `TextAd.PriceExtension`.
  These flags are TEXT_AD-only and are rejected on other ad subtypes
  before any request is built. Closes #245.
- `direct vcards add` now exposes `--instant-messenger-client` and
  `--instant-messenger-login` for `InstantMessenger.MessengerClient`
  and `InstantMessenger.MessengerLogin`, plus the six
  `--point-on-map-*` coordinate flags for `PointOnMap`. Partial
  `InstantMessenger` or `PointOnMap` input is rejected with
  `click.UsageError` so required nested WSDL fields are not omitted.
  Closes #246.
- `direct feeds add` and `direct feeds update` now expose
  `--remove-utm-tags`, `--feed-login`, and `--feed-password` for
  `UrlFeed.RemoveUtmTags`, `UrlFeed.Login`, and `UrlFeed.Password`.
  `feeds update` also exposes `--clear-feed-login` and
  `--clear-feed-password` for the nillable credential fields, with
  mutual-exclusion checks against the corresponding set flags.
  `FileFeed` upload/base64 support was split to follow-up #264.
  Closes #253.
- `direct retargeting add` and `direct retargeting update` now expose
  `--description` for the optional retargeting-list `Description`
  field. Description input is validated against the documented maximum
  length before building the request, and update-only description
  changes satisfy the no-op guard. Closes #256.
- `direct sitelinks add` now supports `TurboPageId` for
  `SitelinkAddItem.TurboPageId` through the canonical `--sitelink`
  pipe spec by accepting an optional fourth segment after
  `Title|Href|Description`. Rows must provide either `Href` or
  `TurboPageId`, so Turbo-only sitelinks are accepted without relaxing
  empty-row validation. Closes #257.

**Changed:**

- WSDL parity now includes a soft optional-field audit for issue #239.
  `scripts/build_wsdl_optional_field_audit.py --check` regenerates and
  compares `tests/WSDL_OPTIONAL_FIELD_AUDIT.md`, covering cached mutating
  WSDL item fields at unbounded nesting depth. Confirmed `minOccurs=0`
  gaps are tracked as linked `missing_followup` rows instead of being
  invisible to the required-field gate.

## 0.3.11

**Added:**

- `direct campaigns add` and `direct campaigns update` now expose
  `--tracking-params` for the campaign-level tracking query string
  (`TextCampaign` / `DynamicTextCampaign` / `SmartCampaign` `.TrackingParams`).
  `campaigns update` gained an optional `--type` discriminator —
  required when `--tracking-params` is set, validated against
  the three subtypes supported by the CLI. Backward compatible:
  existing `campaigns update --id N --name X` calls without `--type`
  keep working unchanged. Closes #230.
- `direct v4account account-management` now supports `--action Get`,
  `Deposit`, `Invoice`, and `TransferMoney` in addition to `Update`,
  matching the official v4 Live docs
  (<https://yandex.ru/dev/direct/doc/dg-v4/reference/AccountManagement-docpage/>).
  `Get` is read-only and accepts optional `--logins` / `--account-ids`
  filters. `Deposit`, `Invoice`, and `TransferMoney` are financial
  mutations: they need `--finance-token` (or `--master-token` +
  `--operation-num` + `--finance-login`) and respect the existing
  dry-run-unless-sandbox rule. A Click-side allow-list rejects flags
  that do not belong to the chosen action before any body is built.
  Refs #125.

**Fixed:**

- `direct v4 *` command wrappers now let `click.ClickException`
  (including `UsageError` from `call_v4` shape validation) propagate to
  Click instead of swallowing it in the generic `except Exception`.
  Shape-validation errors keep their usage hint and exit with code 2,
  matching Click's contract; non-Click runtime errors still surface
  through `print_error` + `Abort` (exit 1). Closes #227.

**Breaking changes:**

- `direct v4finance get-credit-limits` no longer accepts `--logins`; the
  request body now omits `param` per the official v4 Live docs
  (<https://yandex.ru/dev/direct/doc/dg-v4/reference/GetCreditLimits.html>),
  which define the body as `method`, `finance_token`, and `operation_num`
  only. Refs #125.

## 0.3.10

**Added:**

- `direct changes check` now exposes all three mutually-exclusive ID
  filters from the WSDL — `--campaign-ids` (≤3000), `--ad-group-ids`
  (≤10 000) and `--ad-ids` (≤50 000); exactly one is required and the
  mutex is enforced via `click.UsageError` (exit code 2) before any
  request is built. `--fields` is now validated against the
  `CheckFieldEnum` (`CampaignIds`, `AdGroupIds`, `AdIds`,
  `CampaignsStat`); unknown values, empty / comma-only inputs and the
  WSDL `minOccurs=1` violation are caught up-front. Refs: Closes #228.
- `direct sitelinks add` accepts `\|` as a literal pipe inside
  `--sitelink` spec strings, so UTM templates like
  `cid|{campaign_id}|gid|{gbid}` survive parsing. Two new structural
  sources mirror the `keywords.add` #218 pattern:
  `--sitelink-json '<JSON-array>'` (inline) and
  `--sitelinks-from-file <path.jsonl>` (one object per line); sources
  are mutually exclusive. Unknown JSON keys are rejected with the
  offending key surfaced (no silent data loss), and missing
  `Title`/`Href` rows are rejected with the row index. Refs:
  Closes #221, Closes #220.
- `direct v4 *` commands now validate request body shape against
  `V4_METHOD_CONTRACTS` before sending. Documented param shapes
  (`PARAM_ARRAY` / `PARAM_OBJECT` / `PARAM_OPTIONAL_OBJECT` /
  `PARAM_SCALAR`) raise `click.UsageError` on mismatch — the request
  never reaches the network. Undocumented-shape methods are split by
  contract safety: `SAFETY_READ` (e.g. `GetKeywordsSuggestion`)
  emits a stderr warning and proceeds; `SAFETY_WRITE` /
  `SAFETY_DANGEROUS` (e.g. `PayCampaignsByCard`) fail-closed with a
  remediation pointer to `V4_METHOD_CONTRACTS`. Refs: Closes #182.
- Regression tests that lock down subtype validation invariants from
  the `#210` umbrella repro matrix. Nine new `SILENT_LOSS_PROBES` in
  `tests/test_wsdl_parity_gate.py` cover per-type rejection across
  `campaigns add`, `adgroups add`, `ads add`, `bidmodifiers add` and
  `strategies add` (test-only — the corrected rejection behavior was
  shipped earlier in 0.3.9 via #198 audit follow-up PRs). Three new
  non-regression tests in `tests/test_dry_run.py` lock down
  `strategies update` field aliases (`AverageCpcPerFilter →
  FilterAverageCpc`, `PayForConversion → Cpa`) and confirm that
  `AverageCpa` update without `--goal-id` stays WSDL-valid
  (`GoalId` is `minOccurs=0` on update). Refs: Closes #210.

**Fixed:**

- `direct keywords add` in bulk mode (`--from-file` / `--keywords-json`,
  shipped in 0.3.9 / #218) now surfaces per-item `Errors` instead of
  swallowing them and exiting 0 with raw JSON. The per-chunk loop now
  calls `raise_for_api_result_errors` and the final response goes
  through `format_output`, so the 8800 Client-Login guidance and the
  full `Errors` payload propagate through the existing exception
  handler. The partial-success diagnostic ("these keywords were
  already created in Yandex Direct") only lists items Yandex actually
  accepted. Refs: Closes #211.
- `direct_cli/auth.py::_write_json` no longer leaks a file descriptor
  when `chmod` fails between `tempfile.mkstemp` and `os.fdopen`.
  Descriptor ownership is now tracked via a sentinel; cleanup errors
  in `os.close` / `os.unlink` use `contextlib.suppress(OSError)` so
  the original exception is preserved. Refs: Closes #154.

## 0.3.9

**Added:**

- `direct keywords add` now supports batch mode via `--from-file PATH`
  (JSONL, one keyword object per line) or `--keywords-json '[…]'`
  (inline JSON array). The CLI splits input into chunks of 10 — the
  Yandex Direct API limit for `keywords.add` documented at
  https://yandex.ru/dev/direct/doc/dg/objects/keyword.html — preserves
  input order, and merges `AddResults` from every chunk into a single
  response. Item-level errors do not abort the batch. If a chunk-level
  exception breaks the loop, already-created Ids are printed to stderr
  with a "Partial success before failure" header so a retry doesn't
  duplicate them. Pre-flight warning when any AdGroupId in the input
  exceeds the per-ad-group limit of 200 keywords (the API rejects the
  excess with per-item errors; warning surfaces this before any chunk
  is sent). Row keys use WSDL CamelCase (`Keyword`, `AdGroupId`,
  `Bid`, `ContextBid`, `UserParam1`, `UserParam2`); unknown keys are
  rejected with the row number, and JSON booleans are explicitly
  rejected to prevent silent `True → 1` coercion. `--adgroup-id` is
  optional in batch mode and acts as a default, overridable per row.
  `--dry-run` prints the first chunk's payload alongside
  `{chunks, totalItems, chunkSize}`. Single-item mode (`--keyword`)
  is unchanged (#203).
- `direct campaigns add` typed flags for CPA strategies and
  cross-cutting `CampaignAddItem` fields: `--goal-id` (single
  Metrika goal), `--crr` (CRR percentage for
  `PAY_FOR_CONVERSION_CRR`),
  `--priority-goals goal_id:value,…` (multi-goal CPA via
  WSDL `PriorityGoalsArray`), `--average-cpa MICRO_RUBLES`,
  `--bid-ceiling MICRO_RUBLES`, `--counter-ids`
  (TextCampaign/DynamicTextCampaign), `--notification JSON`
  (`CampaignBase.Notification` with `SmsSettings`/`EmailSettings`
  shape validation), `--time-targeting JSON`
  (`CampaignAddItem.TimeTargeting` with `HolidaysSchedule`
  shape validation). Strategy-subtype compatibility is enforced
  via `UsageError` at CLI level both ways: WSDL-incompatible flags
  are rejected (e.g. `--average-cpa` for `HIGHEST_POSITION`,
  `--crr` outside `PAY_FOR_CONVERSION_CRR`,
  `--bid-ceiling` for `PayForConversionCrr` /
  `PayForConversionMultipleGoals`), and WSDL `minOccurs=1`
  fields are demanded up-front (e.g. picking `AVERAGE_CPA`
  without `--average-cpa`+`--goal-id`, or `PAY_FOR_CONVERSION_CRR`
  without `--crr`+`--goal-id`, or `*_MULTIPLE_GOALS` without
  `--priority-goals`, all fail at the CLI instead of the API).
  Closes #204.

**Notes:**

- Issue #204 also requested `--goals` (array) and
  `--network-settings`; both were dropped after WSDL audit. Yandex
  `Strategy*Add` complex types declare only scalar `GoalId`, so
  multi-goal CPA is shipped through `--priority-goals` instead
  (correct WSDL path: `TextCampaign.PriorityGoals.Items[].GoalId/Value`).
  No `NetworkSettings` field exists on `CampaignAddItem` /
  `TextCampaignAddItem` / `DynamicTextCampaignAddItem` /
  `SmartCampaignAddItem` in the current `campaigns.xml` WSDL.

**Fixed:**

- Refreshed `TestWriteFeeds` and `TestWriteSmartAdTargets` VCR cassettes against a real sandbox, dropped the `_FEED_REGRESSION_PATTERNS` skip workaround, and updated `sandbox_feed` / `sandbox_smart_adgroup` fixtures to pass the now-WSDL-required `--business-type RETAIL` (FeedAddItem) and `--counter-id` (SmartCampaignAddItem). Tests now skip only on genuine sandbox limitations, not on the missing-option proxy that the workaround papered over (#206, fallout from #201). Test invocation now also passes `--login` and prefers env vars over an active `direct auth` profile, matching the inversion documented in CLAUDE.md.
- WSDL parity gate now fails fast when `COMMAND_WSDL_MAP` points at a container that does not exist in the WSDL request schema. The previous skip-on-empty-required-list silently masked typo'd container names (#206, Copilot follow-up from #205).
- `WSDL_FIELD_TO_CLI_OPTION` no longer references the non-existent generic `--file` flag. `SourceType` maps to `{--url}` and `ImageData` maps to `{--image-data, --image-file}`, matching the real CLI surface (#206, Copilot follow-up from #205).
- `direct bidmodifiers set --help` no longer advertises the rejected `--campaign-id`/`--type` legacy path; the rejection now happens via an eager Click callback (same pattern as deprecated `keywords update` options), preserving the existing `UsageError` message for regression coverage (#206, Copilot follow-up from #214).

**Refs:** Closes issues #122, #138, #198, #202, #203, #204, #206, #207.

## 0.3.8

**BREAKING CHANGES:**

- `direct ads update` now requires `--type {TEXT_AD,TEXT_IMAGE_AD,MOBILE_APP_AD}`. Scripts that called `ads update` with only field flags will fail with `Missing option '--type'`. Mirrors the WSDL one-of choice between TextAd/TextImageAd/MobileAppAd update subtypes (PR #197).
- `direct ads add --type TEXT_IMAGE_AD` rejects `--title/--text` (TEXT_IMAGE_AD has no such WSDL fields). `direct ads update --status` rejected — use `ads suspend/resume/archive/unarchive` for status changes (PR #190).
- `direct ads add --type MOBILE_APP_AD --href` rejected — MobileAppAd uses `--tracking-url`, not `--href` (PR #196).
- `direct feeds add` now requires `--business-type {RETAIL,HOTELS,REALTY,AUTOMOBILES,FLIGHTS,OTHER}`. Mirrors WSDL FeedAddItem.BusinessType (minOccurs=1) (PR #201).

**Schema gate — mutating ops parity:**

- Extended the WSDL `*FieldNames` schema gate (introduced for `get` in 0.3.7) to mutating operations (`add/update/set/setBids/lifecycle`). Added per-operation waiver granularity via `SCHEMA_GATE_OPERATION_WAIVERS` (PR #181).
- Promoted dynamicads, bidmodifiers add/set, adimages/advideos/vcards add (media payloads), adextensions/retargeting/feeds.add typed fixtures to `PAYLOAD_CASES` (PRs #184, #185, #187, #188).
- Added MOBILE_APP_AD branch to `ads add` mirroring WSDL `MobileAppAdAdd` (PR #190).
- `bidmodifiers.delete` correctly classified as a real destructive WSDL operation and added to schema gate (PR #194); the earlier "Helper/legacy surface" rationale was a mis-classification — see post-mortem in #199 / PR #200.

**Strict WSDL parity policy:**

- Documented "Strict WSDL parity" principle in `CLAUDE.md`: `DRY_RUN_PAYLOAD_EXCLUSIONS` may only contain entries from five legitimate categories (read-path `*.get`, runtime-deprecated, v4-not-in-v5-wsdl, custom non-RPC endpoints, methods covered by `tests/test_dry_run.py`). New guard test `test_dry_run_exclusions_have_no_helper_or_legacy_rationale` fails CI if any rationale uses banned phrases (PR #200).

**Integration test coverage:**

- Added read-only sandbox integration tests for `changes`, `keywordsresearch`, `balance` (PR #186).
- Added v5 write integration coverage for `strategies` lifecycle, `retargeting update`, `bids get/set-auto`, plus `auth status/list` read-only tests (PR #189).
- Re-recorded TestWriteBidsRead cassettes against live API and rewrote host to sandbox so the bids endpoints get real coverage in replay mode (PR #193).

**CI infrastructure:**

- Switched Claude code-review GitHub Action from default (Sonnet 4.5) to Claude Opus 4.7 for deeper PR review (PR #192).

**Refs:** Closes issues #118, #136, #137, #175, #176, #180, #183, #191, #199.

## 0.3.3

**BREAKING CHANGE:** OAuth profiles created before 0.3.3 (without `refresh_token` and `expires_at`) are no longer accepted. Any such profile will fail immediately with an "incomplete profile" error. Run `direct auth login --profile <name>` to re-authenticate and create a valid 0.3.3 profile.

- Added refresh token persistence for OAuth profiles.
- Added automatic OAuth access token refresh before expiry.
- Added `expires_in` details to `direct auth status`.
- Added JSON output for `direct auth status`.
- Kept `direct auth login --oauth-token` as a manual access-token import without auto-refresh.
