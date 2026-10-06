#!/usr/bin/env python3
"""Read-only recon for issue #871 (NO mutation, ever).

The cached WSDL (tests/wsdl_cache/bidmodifiers.xml, refreshed 2026-10-06) does
NOT declare RETARGETING_SEARCH_ADJUSTMENT, but the live API accepts the type
(see the issue's live `bidmodifiers get` evidence). Before the CLI can mirror
the type, its NESTED FIELD NAME must be confirmed from the live API — guessing
it would violate strict WSDL parity with an invented name.

This script calls the live API READ-ONLY via the same vendor client the CLI
uses (body shaped exactly like `bidmodifiers get`'s, method="get"), with the
type injected past the CLI's click.Choice, and prints:

1. the raw BidModifiers.get response for the type over a campaign the
   operator names (--campaign-id, or env YANDEX_DIRECT_TEST_CAMPAIGN_ID);
2. on API error 8000 — Yandex's own canonical enum list from the message
   (the feedback_live_readonly_verification convention);
3. the exact nested key(s) the response uses (expected shape
   RetargetingSearchAdjustment(s) — TO BE CONFIRMED, never assumed).

Run from the repo root:

    PYTHONPATH=. python3 scripts/recon_871_bidmodifiers_enum.py --campaign-id 123

Paste the output into #871 as the evidence for the implementation PR.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

TYPE = "RETARGETING_SEARCH_ADJUSTMENT"
CAMEL = TYPE.title().replace("_", "")  # RetargetingSearchAdjustment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--campaign-id",
        type=int,
        default=int(os.environ.get("YANDEX_DIRECT_TEST_CAMPAIGN_ID", 0) or 0),
        help="Campaign whose bid modifiers to read (read-only); omit to "
        "read ALL campaigns' campaign-level modifiers of the type in one "
        "call (still read-only)",
    )
    parser.add_argument(
        "--ids-file",
        help="JSON file with a campaigns get output ([{\"Id\": ...}]); reads "
        "the type across ALL those campaigns in one call (read-only)",
    )
    args = parser.parse_args()

    from direct_cli.api import create_client

    # Shaped exactly like bidmodifiers get's own body (utils.build_common_
    # params output), with the live-only type injected past the CLI's
    # click.Choice — that gate is precisely what #871 reports.
    campaign_ids = [args.campaign_id] if args.campaign_id else []
    if args.ids_file:
        with open(args.ids_file) as fh:
            campaign_ids = [row["Id"] for row in json.load(fh) if row.get("Id")]
    body = {
        "method": "get",
        "params": {
            # Levels lives INSIDE SelectionCriteria (WSDL lines 131-135: the
            # criteria complexType carries AdGroupIds/Ids/Types/Levels), not
            # at the request top level — top-level Levels gets error 8000
            # "Omitted required parameter Levels" even when present.
            #
            # Second live probe (2026-10-06): a top-level
            # "RetargetingSearchAdjustmentFieldNames" is rejected with
            # "Unknown parameter" — the live get request has NO per-type
            # FieldNames slot for this type (the cached WSDL agrees), so the
            # type is selected via SelectionCriteria.Types and the response's
            # real nested key is what this probe must surface.
            "SelectionCriteria": {
                **({"CampaignIds": campaign_ids} if campaign_ids else {}),
                "Levels": ["CAMPAIGN"],
                "Types": [TYPE],
            },
            "FieldNames": ["Id", "CampaignId", "AdGroupId", "Type", "Level"],
        },
    }
    scope = (
        f"{len(campaign_ids)} campaign(s)" if campaign_ids else "ALL campaigns"
    )
    print(f"GET BidModifiers for {scope}, type {TYPE}")
    print("request body:", json.dumps(body, ensure_ascii=False))

    client = create_client()
    result = client.bidmodifiers().post(data=body)
    # Mirror _execute.py's call shape: post() returns a callable whose
    # result carries .extract().
    data = result().extract() if callable(result) else result
    if hasattr(data, "extract"):
        data = data.extract()  # type: ignore[union-attr]

    print("raw response:")
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))

    rows = data if isinstance(data, list) else (data or {}).get("result", data)
    nested = sorted(
        {
            key
            for row in (rows or [])
            if isinstance(row, dict)
            for key in row
            if CAMEL in key
        }
    )
    print("nested keys seen:", nested or "NONE — paste the raw response above")
    return 0


if __name__ == "__main__":
    sys.exit(main())
