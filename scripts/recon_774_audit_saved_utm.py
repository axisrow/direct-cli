#!/usr/bin/env python3
"""Read-only audit for issues #774/#769: print the CURRENTLY SAVED UTMInput
value of every named master campaign, and classify it against an expected
value.

Answers #774's investigation point 3 — "re-check the campaigns from the
#769/#770 runs where verify reported an empty field vs a reordered one" —
without mutating anything: it only opens each campaign's edit page, expands
the "Дополнительные параметры" spoiler, and reads the field.

Usage (coordinated live window ONLY, read-only):

    PYTHONPATH=. python3 scripts/recon_774_audit_saved_utm.py --all
    PYTHONPATH=. python3 scripts/recon_774_audit_saved_utm.py 713234041 713232132
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

EXPECTED = (
    "utm_source=yandex_alexey&utm_medium=cpc&utm_campaign={campaign_id}"
    "&utm_term={gbid}|kw|{keyword}&utm_content={ad_id}"
)


def _read_one(page, campaign_id: int) -> Optional[str]:
    from direct_cli.browser.masters import (
        WIZARD_EDIT_URL,
        _expand_utm_spoiler,
        _read_tracking_params,
        _wait_for_edit_form,
    )
    from direct_cli.browser.session import assert_authenticated, assert_not_captcha

    page.goto(WIZARD_EDIT_URL.format(campaign_id=campaign_id), wait_until="commit")
    assert_not_captcha(page.content())
    assert_authenticated(page.content())
    _wait_for_edit_form(page, campaign_id)
    # Same settle-wait _verify_saved uses: the spoiler is not guaranteed
    # ready by _wait_for_edit_form.
    page.wait_for_timeout(3_000)
    if not _expand_utm_spoiler(page):
        return None
    return _read_tracking_params(page)


def _list_master_ids(page) -> List[int]:
    from direct_cli.browser.masters import fetch_masters_list

    rows = fetch_masters_list(page, status="all")
    return [int(r["CampaignId"]) for r in rows]


def main() -> int:
    from direct_cli.browser.masters import describe_value_mismatch
    from direct_cli.browser.session import open_saved_session

    ap = argparse.ArgumentParser()
    ap.add_argument("campaign_ids", nargs="*", type=int)
    ap.add_argument("--all", action="store_true", help="audit every master campaign")
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--expected", default=EXPECTED)
    args = ap.parse_args()

    if not args.campaign_ids and not args.all:
        ap.error("pass campaign ids or --all")

    with open_saved_session(headless=not args.headful) as page:
        ids = args.campaign_ids or _list_master_ids(page)
        print(f"auditing {len(ids)} campaign(s)\n")
        empty, exact, other = [], [], []
        for campaign_id in ids:
            try:
                value = _read_one(page, campaign_id)
            except Exception as exc:  # noqa: PIE786 - recon sweep must not abort
                print(f"{campaign_id}: ERROR {exc!r}")
                continue
            if value == args.expected:
                exact.append(campaign_id)
                print(f"{campaign_id}: EXACT MATCH")
            elif value in ("", None):
                empty.append(campaign_id)
                print(f"{campaign_id}: EMPTY/UNREADABLE ({value!r})")
            else:
                other.append(campaign_id)
                print(f"{campaign_id}: DIFFERS")
                print(f"    saved: {value!r}")
                print(describe_value_mismatch(args.expected, value))

        print(f"\nsummary: exact={len(exact)} empty={len(empty)} differs={len(other)}")
        if empty:
            print(f"  empty: {empty}")
        if other:
            print(f"  differs: {other}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
