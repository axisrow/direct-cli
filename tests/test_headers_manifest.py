"""Transport-layer guard: manifest of documented Yandex Direct HTTP headers (#922).

The API-coverage model sees "WSDL operation ↔ CLI command" but is blind to the
transport layer: ``Units`` rode through the vendored client on every response
for years while the CLI never showed it (#919), because a header is not an
endpoint. This module holds the manifest of every HTTP header Yandex documents
and fails when documentation and manifest drift apart in either direction:

- a header documented by Yandex but missing from the manifest (the silent
  blind zone this guard exists for);
- a manifest entry no longer documented on its cited page (renamed/removed);
- a ``surfaced`` entry whose cited code modules no longer exist.

Documentation sources (both declared in the vendored resource registry and
cached in ``tests/reports_cache/raw/`` for offline runs):

- ``headers`` — the «HTTP-заголовки» page (request/response headers of the
  API and of Reports); header names are its ``h3`` sections plus the intro
  sentence listing the basic request headers.
- ``units`` — the «Ограничения, баллы» concepts page, which documents
  ``Units``/``Units-Used-Login``/``Use-Operator-Units`` (NOT the headers page,
  that was the original #922 finding); header names appear as ``<code>``
  elements in its «Баллы» section.
"""

import importlib
import re

from bs4 import BeautifulSoup

from direct_cli._vendor.tapi_yandex_direct.resource_mapping import RESOURCE_MAPPING_V5
from direct_cli.reports_coverage import REPORTS_CACHE_DIR, REPORTS_SPEC_URLS

STATUSES = ("surfaced", "planned", "declined")
DIRECTIONS = ("request", "response")
SOURCES = ("headers", "units")

VENDORED_TRANSPORT = "direct_cli._vendor.tapi_yandex_direct.tapi_yandex_direct"

# Every HTTP header Yandex documents, with where the CLI currently handles it.
# A documented header that belongs here and is missing = the guard fails.
HEADERS_MANIFEST = {
    "Authorization": {
        "direction": "request",
        "source": "headers",
        "status": "surfaced",
        "detail": "vendored client sets it from the access token on every call",
        "code": ["direct_cli.api", VENDORED_TRANSPORT],
    },
    "Client-Login": {
        "direction": "request",
        "source": "headers",
        "status": "surfaced",
        "detail": "vendored client sets it from the agency login on every call",
        "code": ["direct_cli.api", VENDORED_TRANSPORT],
    },
    "Accept-Language": {
        "direction": "request",
        "source": "headers",
        "status": "surfaced",
        "detail": "reports --language → create_client(language=…) → vendored client",
        "code": ["direct_cli.commands.reports", "direct_cli.api"],
    },
    "processingMode": {
        "direction": "request",
        "source": "headers",
        "status": "surfaced",
        "detail": (
            "reports --processing-mode; other commands send the create_client "
            "default (auto)"
        ),
        "code": ["direct_cli.commands.reports", "direct_cli.api"],
    },
    "returnMoneyInMicros": {
        "direction": "request",
        "source": "headers",
        "status": "surfaced",
        "detail": (
            "reports exposes a flag; other commands send the create_client "
            "default (false)"
        ),
        "code": ["direct_cli.commands.reports", "direct_cli.api"],
    },
    "skipReportHeader": {
        "direction": "request",
        "source": "headers",
        "status": "surfaced",
        "detail": (
            "reports exposes a flag; other commands send the create_client "
            "default (true)"
        ),
        "code": ["direct_cli.commands.reports", "direct_cli.api"],
    },
    "skipColumnHeader": {
        "direction": "request",
        "source": "headers",
        "status": "surfaced",
        "detail": (
            "reports exposes a flag; other commands send the create_client "
            "default (false)"
        ),
        "code": ["direct_cli.commands.reports", "direct_cli.api"],
    },
    "skipReportSummary": {
        "direction": "request",
        "source": "headers",
        "status": "surfaced",
        "detail": (
            "reports exposes a flag; other commands send the create_client "
            "default (true)"
        ),
        "code": ["direct_cli.commands.reports", "direct_cli.api"],
    },
    "Accept-Encoding": {
        "direction": "request",
        "source": "headers",
        "status": "surfaced",
        "detail": "sent automatically by the requests transport (gzip); the CLI adds nothing",
        "code": [],
    },
    "retryIn": {
        "direction": "response",
        "source": "headers",
        "status": "surfaced",
        "detail": (
            "vendored client report polling (wait_report) re-requests after "
            "retryIn seconds on HTTP 201/202"
        ),
        "code": [VENDORED_TRANSPORT],
    },
    "reportsInQueue": {
        "direction": "response",
        "source": "headers",
        "status": "planned",
        "issue": "#922",
        "detail": (
            "not read anywhere; future optional-output channel (noted in "
            "optional_output.py CHANNELS docstring)"
        ),
    },
    "Units": {
        "direction": "response",
        "source": "units",
        "status": "surfaced",
        "detail": (
            "direct api units (#919/#921); appended to API error messages "
            "(output.py); successful calls via DIRECT_SHOW_UNITS (optional_output)"
        ),
        "code": ["direct_cli.commands.api", "direct_cli.output", "direct_cli.optional_output"],
    },
    "Units-Used-Login": {
        "direction": "response",
        "source": "units",
        "status": "surfaced",
        "detail": "DIRECT_SHOW_UNITS success channel appends used-login (optional_output)",
        "code": ["direct_cli.optional_output"],
    },
    "Use-Operator-Units": {
        "direction": "request",
        "source": "units",
        "status": "planned",
        "issue": "#922",
        "detail": (
            "vendored client supports api_param use_operator_units; no CLI "
            "flag exposes it yet"
        ),
    },
}


def _load_cached_page(source: str) -> BeautifulSoup:
    html = (REPORTS_CACHE_DIR / "raw" / f"{source}.html").read_text(encoding="utf-8")
    return BeautifulSoup(html, "lxml")


def _header_name(heading_text: str) -> str:
    """'returnMoneyInMicros: false' → 'returnMoneyInMicros'."""
    return heading_text.split(":", 1)[0].strip()


def _headers_page_documented(soup) -> dict[str, str]:
    """{header name: direction} documented by the «HTTP-заголовки» page.

    Each header is an ``h3`` section under «Заголовки запроса» or «Заголовки
    ответа»; the basic request headers (Authorization, Accept-Language,
    Client-Login) are named in the intro sentence instead.
    """
    documented: dict[str, str] = {}
    direction = None
    for heading in soup.find_all(["h2", "h3"]):
        text = heading.get_text(" ", strip=True)
        if heading.name == "h2":
            if "Заголовки запроса" in text:
                direction = "request"
            elif "Заголовки ответа" in text:
                direction = "response"
            continue
        if direction and text and "Была ли" not in text:
            documented[_header_name(text)] = direction

    intro = re.search(r"к заголовкам ([^.]+?) можно указать", soup.get_text(" "))
    if intro:
        for name in intro.group(1).split(","):
            documented.setdefault(name.strip(), "request")
    return documented


def _units_page_documented(soup) -> set[str]:
    """Header names documented by the concepts/units page.

    They appear as inline ``<code>`` elements in the «Баллы» section
    (``Use-Operator-Units: true``, ``Units``, ``Units: 10/20828/64000``,
    ``Units-Used-Login``). The same section's rates table also ``<code>``s
    service and method names, so table cells are excluded; method-call
    examples (``Bids.get``) fail the header-name shape.
    """
    section = next(
        (
            h
            for h in soup.find_all("h2")
            if h.get_text(" ", strip=True) == "Баллы"
        ),
        None,
    )
    if section is None:
        return set()
    names = set()
    for node in section.find_next_siblings():
        if node.name == "h2":
            break
        for code in node.find_all("code"):
            if code.find_parent("table") is not None:
                continue
            token = code.get_text(strip=True).split(":", 1)[0].split(" ", 1)[0]
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*", token):
                names.add(token)
    return names


def test_manifest_sources_are_declared_in_the_registry():
    """Every manifest source is a registry URL — no URL literals here (#426)."""
    docs_pages = RESOURCE_MAPPING_V5["reports"]["docs_pages"]
    for name, entry in HEADERS_MANIFEST.items():
        source = entry["source"]
        assert source in SOURCES, f"{name}: unknown source {source!r}"
        assert source in docs_pages, f"{name}: {source!r} missing from docs_pages"
        assert docs_pages[source] == REPORTS_SPEC_URLS[source]
    # The original #922 finding: Units headers are documented on the concepts
    # page, not on the reports/HTTP-headers page — the manifest must cite it.
    assert "/concepts/units" in docs_pages["units"]


def test_manifest_entries_are_well_formed():
    for name, entry in HEADERS_MANIFEST.items():
        assert entry["status"] in STATUSES, name
        assert entry["direction"] in DIRECTIONS, name
        assert entry["detail"].strip(), name
        if entry["status"] == "planned":
            assert entry.get("issue"), f"{name}: planned entry must cite an issue"
        if entry["status"] == "surfaced":
            assert "code" in entry, f"{name}: surfaced entry must cite code"


def test_surfaced_entries_cite_importable_code():
    for name, entry in HEADERS_MANIFEST.items():
        for module in entry.get("code", []):
            try:
                importlib.import_module(module)
            except ImportError:
                raise AssertionError(
                    f"{name}: surfaced entry cites gone module {module}"
                )


def test_every_manifest_entry_is_documented_on_its_source_page():
    for name, entry in HEADERS_MANIFEST.items():
        soup = _load_cached_page(entry["source"])
        assert name in soup.get_text(" "), (
            f"{name} is no longer documented on the {entry['source']!r} page — "
            "Yandex renamed or removed it; update HEADERS_MANIFEST"
        )


def test_headers_page_documentation_is_fully_manifested():
    soup = _load_cached_page("headers")
    documented = _headers_page_documented(soup)
    assert len(documented) >= 11, (
        "headers-page extraction regressed — only "
        f"{sorted(documented)} found; fix _headers_page_documented"
    )
    unaccounted = set(documented) - set(HEADERS_MANIFEST)
    assert not unaccounted, (
        "New documented HTTP header(s) on the «HTTP-заголовки» page: "
        f"{sorted(unaccounted)}. Add HEADERS_MANIFEST entries (surfaced/planned/"
        "declined) before the header rides through the transport unseen (#922)."
    )
    for name, direction in documented.items():
        if name in HEADERS_MANIFEST:
            assert HEADERS_MANIFEST[name]["direction"] == direction, (
                f"{name}: manifest says {HEADERS_MANIFEST[name]['direction']}, "
                f"page documents it under {direction}"
            )


def test_units_page_documentation_is_fully_manifested():
    soup = _load_cached_page("units")
    documented = _units_page_documented(soup)
    assert {"Units", "Units-Used-Login", "Use-Operator-Units"} <= documented, (
        "units-page extraction regressed — only "
        f"{sorted(documented)} found; fix _units_page_documented"
    )
    unaccounted = documented - set(HEADERS_MANIFEST)
    assert not unaccounted, (
        "New documented HTTP header(s) on the concepts/units page: "
        f"{sorted(unaccounted)}. Add HEADERS_MANIFEST entries (surfaced/planned/"
        "declined) before the header rides through the transport unseen (#922)."
    )
