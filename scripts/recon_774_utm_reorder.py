#!/usr/bin/env python3
"""Live recon for issue #774 (UTMInput text REORDERED on input) and #769
(verify reads a stale value after save).

Read-only by default in the sense that it writes ONLY to the UTMInput field
of the test master campaign and restores the original value at the end.

What it measures, in order:

1. Baseline: the current UTMInput value (so it can be restored).
2. ``field.type(value, delay=80)`` — the CLI's current mechanism
   (``_type_landing_url``) — then reads ``textContent`` back and prints an
   aligned diff. Repeats N times to catch an intermittent reorder.
3. Per-keystroke trace: types the same value one character at a time,
   reading ``textContent`` after EVERY character, and prints the first
   index at which the readback stops being a prefix of what was typed.
   That pinpoints exactly which keystroke triggers the reorder.
4. Alternative input mechanisms, each verified the same way:
   - ``insertText`` via CDP-less ``page.keyboard.insert_text`` (no per-key
     key events, but still fires a real ``beforeinput``/``input``).
   - ``fill()`` (known not to fire the widget's listeners; measured for
     completeness).
5. #769: after a save, polls the reloaded page's UTMInput value once per
   second for up to 60s, printing the value and when it converges — i.e.
   how long Yandex actually takes to make the saved value readable.

Usage (coordinated live window ONLY):

    PYTHONPATH=. python3 scripts/recon_774_utm_reorder.py --headful
    PYTHONPATH=. python3 scripts/recon_774_utm_reorder.py --save-latency
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Optional

CAMPAIGN_ID = int(__import__("os").environ.get("RECON_774_CAMPAIGN_ID", "713234191"))
WIZARD_EDIT_URL = f"https://direct.yandex.ru/wizard/campaigns/{CAMPAIGN_ID}/edit/"

UTM_INPUT = '[data-testid="CampaignLinkEditorLite.UTMInput"]'

PROBE = (
    "utm_source=yandex_alexey&utm_medium=cpc&utm_campaign={campaign_id}"
    "&utm_term={gbid}|kw|{keyword}&utm_content={ad_id}"
)


def _open(headless: bool):
    from direct_cli.browser.session import open_saved_session

    return open_saved_session(headless=headless)


def _goto_edit(page) -> None:
    from direct_cli.browser.masters import _wait_for_edit_form
    from direct_cli.browser.session import assert_authenticated, assert_not_captcha

    page.goto(WIZARD_EDIT_URL, wait_until="commit")
    assert_not_captcha(page.content())
    assert_authenticated(page.content())
    _wait_for_edit_form(page, CAMPAIGN_ID)


def _expand(page) -> bool:
    from direct_cli.browser.masters import _expand_utm_spoiler

    return _expand_utm_spoiler(page)


def _read(page) -> Optional[str]:
    loc = page.locator(UTM_INPUT).first
    try:
        return loc.text_content()
    except Exception:  # noqa: PIE786 - recon probe: any read failure means "unreadable"
        return None


def _clear(page) -> bool:
    from direct_cli.browser.masters import _clear_text_field

    field = page.locator(UTM_INPUT).first
    field.click()
    return _clear_text_field(field)


def _diff_report(expected: str, actual: Optional[str]) -> str:
    from direct_cli.browser.masters import describe_value_mismatch

    return describe_value_mismatch(expected, actual)


def _probe_type(page, value: str, *, rounds: int, delay: int) -> None:
    print(f"\n=== [2] field.type(delay={delay}) x{rounds} ===")
    field = page.locator(UTM_INPUT).first
    for r in range(rounds):
        _clear(page)
        field.type(value, delay=delay)
        actual = _read(page)
        ok = actual == value
        print(f"  round {r + 1}: match={ok}")
        if not ok:
            print(f"    typed  : {value!r}")
            print(f"    readback: {actual!r}")
            print(_diff_report(value, actual))


def _probe_per_key(page, value: str, *, delay: int) -> None:
    print(f"\n=== [3] per-keystroke trace (delay={delay}) ===")
    field = page.locator(UTM_INPUT).first
    _clear(page)
    field.click()
    diverged_at = None
    for i, ch in enumerate(value):
        page.keyboard.type(ch, delay=delay)
        actual = _read(page) or ""
        want = value[: i + 1]
        if actual != want and diverged_at is None:
            diverged_at = i
            print(f"  FIRST DIVERGENCE at index {i} (char {ch!r}):")
            print(f"    wanted  : {want!r}")
            print(f"    readback: {actual!r}")
    final = _read(page)
    print(f"  final match={final == value}")
    if final != value:
        print(f"    final readback: {final!r}")
        print(_diff_report(value, final))
    if diverged_at is None:
        print("  no divergence observed during typing")


def _probe_insert_text(page, value: str) -> None:
    print("\n=== [4a] keyboard.insert_text ===")
    _clear(page)
    page.locator(UTM_INPUT).first.click()
    page.keyboard.insert_text(value)
    actual = _read(page)
    print(f"  match={actual == value}")
    if actual != value:
        print(f"    readback: {actual!r}")
        print(_diff_report(value, actual))


def _probe_fill(page, value: str) -> None:
    print("\n=== [4b] fill() ===")
    field = page.locator(UTM_INPUT).first
    try:
        field.fill(value)
    except Exception as exc:  # noqa: PIE786 - recon probe reports, never aborts
        print(f"  fill() raised: {exc!r}")
        return
    actual = _read(page)
    print(f"  match={actual == value}")
    if actual != value:
        print(f"    readback: {actual!r}")
        print(_diff_report(value, actual))


def _save_latency(page, value: str) -> None:
    """#769: measure how long after a save the reloaded page shows the new
    value."""
    from direct_cli.browser.masters import (
        _click_save,
        _set_tracking_params,
        _wait_for_draft_status,
    )

    print("\n=== [5] save -> reload -> convergence latency ===")
    # `_wait_for_draft_status`, not `_is_draft_edit_page`: issue #726
    # replaced the point-in-time read precisely because the DRAFT marker
    # can transiently vanish mid-hydration, and misclassifying a DRAFT
    # campaign makes `_click_save` hunt for a button that isn't there.
    is_draft = _wait_for_draft_status(page, CAMPAIGN_ID)
    _set_tracking_params(page, value)
    typed = _read(page)
    print(f"  typed into field: {typed!r} (match={typed == value})")
    t0 = time.monotonic()
    _click_save(page, CAMPAIGN_ID, is_draft=is_draft)
    print(f"  save clicked at t={time.monotonic() - t0:.1f}s")

    _goto_edit(page)
    _expand(page)
    print(f"  reload complete at t={time.monotonic() - t0:.1f}s")
    last = object()
    converged_at = None
    deadline = t0 + 90
    while time.monotonic() < deadline:
        actual = _read(page)
        if actual != last:
            print(f"    t={time.monotonic() - t0:5.1f}s value={actual!r}")
            last = actual
        if actual == value and converged_at is None:
            converged_at = time.monotonic() - t0
            print(f"  CONVERGED at t={converged_at:.1f}s")
            break
        page.wait_for_timeout(1000)
    if converged_at is None:
        print(f"  NEVER converged within 90s; last={last!r}")
        print(_diff_report(value, last if isinstance(last, str) else None))


def _restore_baseline(page, baseline: Optional[str], *, saved: bool) -> None:
    """Put the campaign back the way it was found.

    The probes below ``--save-latency`` only type into the field, so a plain
    re-navigation discards them and printing the value is enough. But
    ``--save-latency`` CLICKS SAVE, committing ``PROBE`` — whose
    ``{campaign_id}``/``{gbid}``/``{keyword}``/``{ad_id}`` placeholders are
    never interpolated — to a live campaign. Without an actual write-back
    that leaves real, malformed tracking params on a production master
    campaign, recoverable only by a manual ``masters update``. The module
    docstring promises restoration; this is where it has to happen.
    """
    from direct_cli.browser.masters import (
        _click_save,
        _set_tracking_params,
        _wait_for_draft_status,
    )

    print("\n=== restoring baseline ===")
    _goto_edit(page)
    _expand(page)
    if not saved:
        # Nothing was committed: the re-navigation above already dropped
        # every typed-but-unsaved probe value.
        print(f"  no save was performed; UTMInput now = {_read(page)!r}")
        return
    if baseline is None:
        print(
            "  WARNING: the baseline could not be read at the start, so the "
            "saved probe value CANNOT be restored automatically. Fix the "
            "campaign manually with 'masters update --tracking-params'."
        )
        return

    # Same #726 hardening as the probe save above — a misclassified DRAFT
    # here would silently leave the campaign holding the probe value.
    is_draft = _wait_for_draft_status(page, CAMPAIGN_ID)
    _set_tracking_params(page, baseline)
    _click_save(page, CAMPAIGN_ID, is_draft=is_draft)
    _goto_edit(page)
    _expand(page)
    restored = _read(page)
    print(f"  restored UTMInput = {restored!r} (match={restored == baseline})")
    if restored != baseline:
        print(
            "  WARNING: restore did NOT round-trip. The campaign still holds "
            "a probe value — fix it manually before leaving it."
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--delay", type=int, default=80)
    ap.add_argument("--value", default=PROBE)
    ap.add_argument(
        "--save-latency",
        action="store_true",
        help="run the #769 save/reload convergence probe (MUTATES + saves)",
    )
    args = ap.parse_args()

    with _open(headless=not args.headful) as page:
        _goto_edit(page)
        if not _expand(page):
            print("could not expand the 'Дополнительные параметры' spoiler")
            return 1
        baseline = _read(page)
        print(f"=== [1] baseline UTMInput = {baseline!r} ===")

        try:
            _probe_type(page, args.value, rounds=args.rounds, delay=args.delay)
            _probe_per_key(page, args.value, delay=args.delay)
            _probe_insert_text(page, args.value)
            _probe_fill(page, args.value)
            if args.save_latency:
                _save_latency(page, args.value)
        finally:
            _restore_baseline(page, baseline, saved=args.save_latency)

    return 0


if __name__ == "__main__":
    sys.exit(main())
