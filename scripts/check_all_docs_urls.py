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
from pathlib import Path
from urllib.parse import urlparse

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from direct_cli._vendor.tapi_yandex_direct.resource_mapping import RESOURCE_MAPPING_V5
from direct_cli.reports_coverage import REPORTS_SPEC_URLS

USER_AGENT = "Mozilla/5.0 (direct-cli docs-drift checker)"
CAPTCHA_MARKERS = ("showcaptcha", "smartcaptcha", "<title>captcha")
MIN_BODY_BYTES = 30_000
# WSDL payloads are XML, much smaller than HTML doc pages. Match the <3 KB
# floor used by wsdl_coverage.fetch_wsdl (CLAUDE.md "Docs/cache freshness guard").
MIN_WSDL_BYTES = 3_072
INTER_REQUEST_DELAY = 1.5  # Yandex rate-limits aggressive UA-less scrapers
CAPTCHA_RETRY_DELAY = 30  # captcha lockouts clear after ~30s


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
            url,
            allow_redirects=False,
            timeout=15,
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
            url,
            allow_redirects=False,
            timeout=30,
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
            resp = requests.get(url, timeout=30, headers={"User-Agent": USER_AGENT})
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

    # WSDL endpoints (used as the docs source for services whose human-readable
    # doc pages Yandex removed — see RESOURCE_MAPPING_V5 / issue #463) are XML,
    # not 30 KB HTML pages. Validate them as real WSDL instead, with the same
    # <3 KB floor the repo's freshness guard uses (wsdl_coverage.fetch_wsdl,
    # per CLAUDE.md) so a truncated body can't pass on marker presence alone.
    if url.rstrip("/").endswith("?wsdl") or url.endswith(".wsdl"):
        has_markers = "wsdl:definitions" in lower or "<definitions" in lower
        if has_markers and len(body) >= MIN_WSDL_BYTES:
            return ("OK", f"GET {resp.status_code}, valid WSDL, {len(body)} bytes")
        return ("SMALL", f"WSDL markers/size insufficient ({len(body)} bytes)")

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
        if verdict in {"MOVED", "GONE", "SMALL", "ERROR"}:
            failed = True
        elif verdict in {"SERVER", "CAPTCHA"}:
            soft_warned = True
        time.sleep(INTER_REQUEST_DELAY)

    width = max(len(label) for label, *_ in rows)
    for label, url, verdict, detail in rows:
        symbol = {
            "OK": "✓",
            "MOVED": "→",
            "GONE": "✗",
            "CAPTCHA": "🤖",
            "SMALL": "?",
            "SERVER": "⚠",
            "ERROR": "!",
        }[verdict]
        print(f"  {symbol} {label:<{width}}  {verdict:<8}  {detail}")
        if verdict != "OK":
            print(f"        {url}")

    print()
    if failed:
        print(
            "FAIL — at least one URL has moved or is gone. "
            "Update RESOURCE_MAPPING_V5 / REPORTS_SPEC_URLS before releasing."
        )
        return 1
    if soft_warned:
        print(
            "OK with warnings — Yandex returned 5xx or captcha for at least "
            "one URL (likely IP rate-limit, not a canonical move); "
            "re-run later to confirm."
        )
    else:
        print("OK — all URLs canonical.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
