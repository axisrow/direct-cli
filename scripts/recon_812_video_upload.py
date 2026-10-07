#!/usr/bin/env python3
"""Staged recon for issue #812 (read-only unless a mutation stage is named).

The core of #812 was never live-verified: ``--add-video``'s upload branch
(``set_input_files``), the Save/commit semantics after an upload, and
``--remove-video``'s persist semantics. PR #856 verified only the read-only
neighbours (2-video limit, library modal). This script is the live-phase
tool: each stage is a separate explicit step so a half-run never leaves a
campaign in an unknown state.

Stages (ONLY the named stage runs):

  recon  (default, read-only)  open the edit page, print the video section's
                               testids and the current video URL list;
  upload --file PATH           set_input_files into the modal's file input
                               and print upload timings/polling observations
                               (NOT saved — follow with commit);
  commit                       click the modal Save AND the page's
                               "Сохранить кампанию", then re-read the list
                               (the Save/commit semantics #812 asks about);
  remove --url URL             remove the video by URL, save, re-read
                               (the persist half of the issue).

Run from the repo root:

    PYTHONPATH=. python3 scripts/recon_812_video_upload.py --campaign-id 123
    PYTHONPATH=. python3 scripts/recon_812_video_upload.py \\
        --campaign-id 123 --stage upload --file /tmp/x.mp4
    PYTHONPATH=. python3 scripts/recon_812_video_upload.py \\
        --campaign-id 123 --stage commit

Every mutation stage prints the pre/post video lists; the fixtures/notes
this recon produces feed the #812 implementation PR
(tests/fixtures/masters_wizard_edit_stage_d_video_upload.html and the
"not a confirmed-live reading" suffix list in commands/masters.py).
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import List, Optional

from direct_cli.browser.masters import (
    _VIDEOS_CLOSE_BUTTON_TESTID_TEMPLATE,
    _VIDEOS_CONTENT_TESTID_PREFIX,
    _VIDEOS_EDITOR_SELECTOR,
    _VIDEOS_MODAL_FILE_INPUT_SELECTOR,
    _VIDEOS_MODAL_SAVE_SELECTOR,
    _VIDEOS_MODAL_SELECTOR,
    _VIDEOS_OPEN_MODAL_SELECTOR,
    WIZARD_EDIT_URL,
)

_SAVE_BUTTON_TEXT = "Сохранить кампанию"


def _wait_edit_form(page) -> None:
    page.wait_for_selector(
        '[data-testid="CampaignTitles0.textarea"]', timeout=30_000
    )


def _goto_edit(page, campaign_id: int) -> None:
    page.goto(WIZARD_EDIT_URL.format(campaign_id=campaign_id), wait_until="commit")
    _wait_edit_form(page)


def _read_video_urls(page) -> Optional[List[str]]:
    """Best-effort read of the video section's current URL list (recon only —
    the CLI's own reader is deliberately not reused: this must show what the
    PAGE says, not what the CLI's parsing does)."""
    try:
        container = page.locator(_VIDEOS_EDITOR_SELECTOR)
        if container.count() == 0:
            return None
        handles = page.locator(
            f'[data-testid^="{_VIDEOS_CONTENT_TESTID_PREFIX}"]'
        )
        urls: List[str] = []
        for i in range(handles.count()):
            urls.append(handles.nth(i).inner_text().strip())
        return urls
    except Exception as exc:  # noqa: PIE786, BLE001 - recon prints, never raises
        print(f"video read failed: {exc}")
        return None


def _open_modal(page) -> None:
    """Retry the open click a few times (the section hydrates for seconds;
    a single blind click can land pre-hydration and be swallowed) and dump
    diagnostics + a screenshot if the modal never shows up."""
    last = None
    for attempt in range(3):
        try:
            page.locator(_VIDEOS_OPEN_MODAL_SELECTOR).first.click(timeout=5000)
        except Exception as exc:  # noqa: BLE001 - recon prints, never raises
            last = exc
            print(f"open-modal click {attempt + 1}: {type(exc).__name__}")
            page.wait_for_timeout(3000)
            continue
        try:
            page.wait_for_selector(_VIDEOS_MODAL_SAVE_SELECTOR, timeout=15000)
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
            print(f"modal save not visible after click {attempt + 1}")
            page.wait_for_timeout(3000)
    print("open button count:", page.locator(_VIDEOS_OPEN_MODAL_SELECTOR).count())
    print("modal count:", page.locator(_VIDEOS_MODAL_SELECTOR).count())
    try:
        page.screenshot(path="/tmp/812_modal_fail.png", full_page=True)
        print("screenshot: /tmp/812_modal_fail.png")
    except Exception as exc:  # noqa: BLE001
        print(f"screenshot failed: {exc}")
    raise RuntimeError(f"modal did not open after 3 attempts: {last}")


def _commit_whole_form(page) -> None:
    # DRAFT campaigns render "Сохранить как черновик" (live-confirmed by the
    # #883 run's own error text); live ones "Сохранить кампанию". Either way
    # it is the whole-form save button.
    for text in ("Сохранить кампанию", "Сохранить как черновик"):
        save = page.get_by_role("button", name=text, exact=True)
        if save.count() > 0:
            save.first.click()
            page.wait_for_timeout(5_000)
            return
    raise RuntimeError(
        "no campaign save button found "
        "(neither 'Сохранить кампанию' nor 'Сохранить как черновик')"
    )


def stage_recon(page, campaign_id: int) -> None:
    _goto_edit(page, campaign_id)
    print("video URLs:", _read_video_urls(page))
    print("editor present:", page.locator(_VIDEOS_EDITOR_SELECTOR).count())
    print(
        "open-modal button present:",
        page.locator(_VIDEOS_OPEN_MODAL_SELECTOR).count(),
    )
    print("close-button testid template:", _VIDEOS_CLOSE_BUTTON_TESTID_TEMPLATE)
    print(
        "file input present (modal closed):",
        page.locator(_VIDEOS_MODAL_FILE_INPUT_SELECTOR).count(),
    )


def stage_upload(page, campaign_id: int, file_path: str) -> None:
    _goto_edit(page, campaign_id)
    print("before:", _read_video_urls(page))
    _open_modal(page)
    file_input = page.locator(_VIDEOS_MODAL_FILE_INPUT_SELECTOR).first
    started = time.monotonic()
    file_input.set_input_files(file_path)
    print(f"set_input_files returned after {time.monotonic() - started:.1f}s")
    # The upload is asynchronous — poll the modal for up to 3 minutes and
    # print every state change the operator can anchor timings on.
    last = None
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        snapshot = page.locator(_VIDEOS_MODAL_SAVE_SELECTOR).first.get_attribute(
            "aria-disabled"
        )
        nodes = page.locator(
            '[data-testid^="VideoSuggestionsEditor.Modal"]'
        ).count()
        state = (snapshot, nodes)
        if state != last:
            elapsed = time.monotonic() - started
            print(f"t+{elapsed:6.1f}s Save[aria-disabled]={snapshot} nodes={nodes}")
            last = state
        if snapshot in (None, "false"):
            print("Save became clickable — upload settled")
            break
        page.wait_for_timeout(2_000)
    else:
        print("upload did NOT settle within 180s — capture a screenshot here")
    print("modal contents (recon read):", _read_video_urls(page))
    print("NOT saved — run --stage commit to persist, or close the tab to abort")


def _settle_upload(page, started: float) -> None:
    """Poll the modal Save button until the upload settles.

    aria-disabled lies here: live run 2026-10-07 showed Save with NO
    aria-disabled attribute while Playwright refused the click with
    "element is not enabled" for minutes — the real gate is the button's
    HTML disabled state (transcoding in progress). Poll is_disabled().
    """
    button = page.locator(_VIDEOS_MODAL_SAVE_SELECTOR).first
    last = None
    deadline = time.monotonic() + 600
    dumped_at = 0.0
    while time.monotonic() < deadline:
        state = (
            button.is_disabled(),
            button.get_attribute("aria-disabled"),
        )
        if state != last:
            print(
                f"t+{time.monotonic() - started:6.1f}s "
                f"Save disabled={state[0]} aria-disabled={state[1]}"
            )
            last = state
        if not state[0]:
            print("Save became enabled — upload settled")
            return
        # Visual dump every 30s: what does the modal SAY is happening?
        if time.monotonic() - dumped_at >= 30:
            dumped_at = time.monotonic()
            nodes = page.locator('[data-testid^="VideoSuggestionsEditor."]')
            for i in range(min(nodes.count(), 30)):
                el = nodes.nth(i)
                testid = el.get_attribute("data-testid") or "?"
                try:
                    text = " ".join(el.inner_text().split())[:120]
                except Exception:  # noqa: BLE001
                    text = "<unreadable>"
                if text:
                    print(f"  [{testid}] {text}")
            shot = f"/tmp/812_settle_{int(dumped_at - started)}.png"
            try:
                page.screenshot(path=shot)
                print(f"  screenshot: {shot}")
            except Exception as exc:  # noqa: BLE001
                print(f"  screenshot failed: {exc}")
        page.wait_for_timeout(2_000)
    raise RuntimeError("upload did not settle within 600s")


def stage_commit(page, campaign_id: int, file_path: str) -> None:
    """A page reload loses an unsaved selection, so the commit stage uploads
    the file ITSELF in this same session (a separate commit-only run saved
    nothing — live finding 2026-10-07)."""
    _goto_edit(page, campaign_id)
    print("before:", _read_video_urls(page))
    _open_modal(page)
    started = time.monotonic()
    page.locator(_VIDEOS_MODAL_FILE_INPUT_SELECTOR).first.set_input_files(file_path)
    print(f"set_input_files returned after {time.monotonic() - started:.1f}s")
    page.wait_for_timeout(15_000)
    if page.locator(_VIDEOS_MODAL_SAVE_SELECTOR).first.is_disabled():
        # Live finding 2026-10-07: setting files directly on the hidden
        # input does NOT start the upload — the UploadZone keeps showing
        # "Перетащите сюда файлы" and Save stays disabled for 10+ minutes.
        # Go through the real user path instead: click the visible
        # "Выбрать файлы" button and hand the file to the native chooser.
        print(
            "direct input set did not start the upload — retrying via the "
            "visible 'Выбрать файлы' button"
        )
        with page.expect_file_chooser() as fc_info:
            page.get_by_text("Выбрать файлы").first.click()
        fc_info.value.set_files(file_path)
        print("file chooser accepted the file")
    _settle_upload(page, started)
    page.locator(_VIDEOS_MODAL_SAVE_SELECTOR).first.click()
    page.wait_for_selector(
        _VIDEOS_MODAL_SAVE_SELECTOR, state="detached", timeout=30_000
    )
    print("modal Save accepted; committing the whole-form save...")
    _commit_whole_form(page)
    _goto_edit(page, campaign_id)
    print("after reload:", _read_video_urls(page))
    print("^ THIS answers #812's commit-semantics question")


def stage_remove(page, campaign_id: int, url: str) -> None:
    _goto_edit(page, campaign_id)
    print("before:", _read_video_urls(page))
    _open_modal(page)
    # The close-button testid is keyed by the video URL itself.
    close_testid = _VIDEOS_CLOSE_BUTTON_TESTID_TEMPLATE.format(video_url=url)
    print(f"clicking close button {close_testid}")
    page.locator(f'[data-testid="{close_testid}"]').first.click()
    page.locator(_VIDEOS_MODAL_SAVE_SELECTOR).first.click()
    page.wait_for_selector(
        _VIDEOS_MODAL_SAVE_SELECTOR, state="detached", timeout=30_000
    )
    _commit_whole_form(page)
    _goto_edit(page, campaign_id)
    print("after reload:", _read_video_urls(page))
    print("^ THIS answers #812's remove-persist question")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-id", type=int, required=True)
    parser.add_argument(
        "--stage",
        choices=["recon", "upload", "commit", "remove"],
        default="recon",
        help="recon is read-only; the others mutate the named campaign",
    )
    parser.add_argument("--file", help="video file for --stage upload")
    parser.add_argument("--url", help="video URL for --stage remove")
    args = parser.parse_args()

    if args.stage == "upload" and not args.file:
        parser.error("--stage upload requires --file")
    if args.stage == "commit" and not args.file:
        parser.error("--stage commit requires --file (the stage uploads the "
                     "file itself — an unsaved selection does not survive a "
                     "page reload)")
    if args.stage == "remove" and not args.url:
        parser.error("--stage remove requires --url")
    if args.stage != "recon":
        answer = input(
            f"MUTATION stage '{args.stage}' on campaign "
            f"{args.campaign_id} — type 'yes' to proceed: "
        )
        if answer.strip().lower() != "yes":
            print("aborted")
            return 1

    from direct_cli.browser.session import open_chrome_session

    # open_chrome_session (fresh Keychain decrypt), not open_saved_session:
    # the saved envelope goes stale within weeks and this recon must not
    # depend on a fresh `playwright login` (live run 2026-10-07).
    with open_chrome_session(headless=False) as page:
        if args.stage == "recon":
            stage_recon(page, args.campaign_id)
        elif args.stage == "upload":
            stage_upload(page, args.campaign_id, args.file)
        elif args.stage == "commit":
            stage_commit(page, args.campaign_id, args.file)
        elif args.stage == "remove":
            stage_remove(page, args.campaign_id, args.url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
