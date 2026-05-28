#!/usr/bin/env python3
"""Health-check every Yandex docs URL we hard-code.

Fails (exit code 1) when:
- a URL returns 3xx with a Location pointing to a different path segment
  (the canonical URL has moved — that's exactly how issue #426 happened);
- a URL returns 4xx (page removed);
- a URL returns 2xx but body looks like a captcha or is < 30 KB.

5xx is reported but does NOT fail — Yandex outages should not block CI/release.

Usage:
    python scripts/check_all_docs_urls.py
"""
from __future__ import annotations

import sys
import time
from urllib.parse import urlparse

import requests

from direct_cli._vendor.tapi_yandex_direct.resource_mapping import RESOURCE_MAPPING_V5
from direct_cli.reports_coverage import REPORTS_SPEC_URLS

USER_AGENT = "Mozilla/5.0 (direct-cli docs-drift checker)"
CAPTCHA_MARKERS = ("showcaptcha", "smartcaptcha", "<title>captcha")
MIN_BODY_BYTES = 30_000
INTER_REQUEST_DELAY = 1.5  # Yandex rate-limits aggressive UA-less scrapers
CAPTCHA_RETRY_DELAY = 30   # captcha lockouts clear after ~30s


def collect_urls() -> dict[str, str]:
    """Return {label: url} from resource_mapping and reports_coverage."""
    urls: dict[str, str] = {}
    for svc, meta in RESOURCE_MAPPING_V5.items():
        if "docs" in meta:
            urls[f"{svc}.docs"] = meta["docs"]
        for k, v in meta.get("docs_pages", {}).items():
            urls[f"{svc}.{k}"] = v
    for k, v in REPORTS_SPEC_URLS.items():
        urls.setdefault(f"reports.{k}", v)
    return urls


def same_path_segment(a: str, b: str) -> bool:
    """Treat redirect target as canonical move when path differs."""
    return urlparse(a).path.rstrip("/") == urlparse(b).path.rstrip("/")


def _is_captcha_redirect(loc: str) -> bool:
    return "showcaptcha" in loc.lower() or "smartcaptcha" in loc.lower()


def _probe(url: str) -> tuple[str, str] | None:
    """One pass. Return (verdict, detail) or None when caller should retry after delay."""
    try:
        head = requests.head(
            url, allow_redirects=False, timeout=15,
            headers={"User-Agent": USER_AGENT},
        )
    except requests.RequestException as exc:
        return ("ERROR", f"network: {exc}")

    if 300 <= head.status_code < 400:
        loc = head.headers.get("Location", "")
        if _is_captcha_redirect(loc):
            return None  # rate-limited — caller retries
        if loc and not same_path_segment(url, loc):
            return ("MOVED", f"{head.status_code} → {loc}")
        return ("OK", f"{head.status_code} same-path redirect")
    if 500 <= head.status_code < 600:
        return ("SERVER", f"HTTP {head.status_code}")

    # Treat any non-redirect, non-5xx response (including HEAD 4xx like 403/405
    # from CDNs that reject HEAD) as "verify via GET" — we can only declare GONE
    # if the GET also confirms it. Keep allow_redirects=False so a canonical
    # move that only surfaces via GET (HEAD 4xx → GET 3xx) is still caught as MOVED.
    try:
        resp = requests.get(
            url, allow_redirects=False, timeout=30,
            headers={"User-Agent": USER_AGENT},
        )
    except requests.RequestException as exc:
        return ("ERROR", f"GET failed: {exc}")

    if 300 <= resp.status_code < 400:
        loc = resp.headers.get("Location", "")
        if _is_captcha_redirect(loc):
            return None
        if loc and not same_path_segment(url, loc):
            return ("MOVED", f"GET {resp.status_code} → {loc}")
        # Same-path redirect (e.g. trailing slash) — follow it once to read body.
        try:
            resp = requests.get(
                url, timeout=30, headers={"User-Agent": USER_AGENT}
            )
        except requests.RequestException as exc:
            return ("ERROR", f"GET (follow) failed: {exc}")
    if 400 <= resp.status_code < 500:
        return ("GONE", f"HTTP {resp.status_code} (HEAD was {head.status_code})")
    if 500 <= resp.status_code < 600:
        return ("SERVER", f"HTTP {resp.status_code}")

    body = resp.text
    lower = body.lower()
    for marker in CAPTCHA_MARKERS:
        if marker in lower:
            return None  # rate-limited
    if len(body) < MIN_BODY_BYTES:
        return ("SMALL", f"{len(body)} bytes < {MIN_BODY_BYTES}")
    return ("OK", f"GET {resp.status_code}, {len(body)} bytes")


def check_one(url: str) -> tuple[str, str]:
    """Return (verdict, detail) with one retry after a captcha rate-limit."""
    result = _probe(url)
    if result is not None:
        return result
    time.sleep(CAPTCHA_RETRY_DELAY)
    result = _probe(url)
    if result is not None:
        return result
    return ("CAPTCHA", f"captcha persisted after {CAPTCHA_RETRY_DELAY}s retry")


def main() -> int:
    urls = collect_urls()
    print(f"Checking {len(urls)} Yandex docs URLs...\n")
    rows: list[tuple[str, str, str, str]] = []
    failed = False
    soft_warned = False
    for label in sorted(urls):
        url = urls[label]
        verdict, detail = check_one(url)
        rows.append((label, url, verdict, detail))
        if verdict in {"MOVED", "GONE", "CAPTCHA", "SMALL", "ERROR"}:
            failed = True
        elif verdict == "SERVER":
            soft_warned = True
        time.sleep(INTER_REQUEST_DELAY)

    width = max(len(label) for label, *_ in rows)
    for label, url, verdict, detail in rows:
        symbol = {"OK": "✓", "MOVED": "→", "GONE": "✗", "CAPTCHA": "🤖",
                  "SMALL": "?", "SERVER": "⚠", "ERROR": "!"}[verdict]
        print(f"  {symbol} {label:<{width}}  {verdict:<8}  {detail}")
        if verdict != "OK":
            print(f"        {url}")

    print()
    if failed:
        print("FAIL — at least one URL has moved, is gone, or returns captcha. "
              "Update RESOURCE_MAPPING_V5 / REPORTS_SPEC_URLS before releasing.")
        return 1
    if soft_warned:
        print("OK with warnings — Yandex returned 5xx for at least one URL; "
              "re-run later to confirm.")
    else:
        print("OK — all URLs canonical.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
