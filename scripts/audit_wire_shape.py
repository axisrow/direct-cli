#!/usr/bin/env python3
"""Full-project Yandex Direct docs/wire-shape audit.

Parses official Yandex Direct documentation HTML, compares the documented
JSON request schema against the contracts declared in this CLI
(``direct_cli.v4_contracts`` + payload builders in ``direct_cli.commands.*``)
and reports diffs by category, the same model that surfaced the v4 Currency
regression (issue #125 / PR #450).

Modes
-----
* ``--v4``       — audit all 32 v4 Live methods against ``dg-v4/live/<Method>``.
* ``--v5``       — audit each v5 WSDL operation against its docs page.
* ``--reports``  — audit the Reports surface against ``ru/spec``.
* ``--all``      — run all three.

Outputs
-------
* JSON artefact (``--json PATH``).
* Markdown table (``--markdown PATH``).

Captcha handling
----------------
Yandex docs hosts a SmartCaptcha gateway. When the fetcher detects captcha
markers (``showcaptcha``, ``smartcaptcha``, ``<title>Captcha``) or a body
smaller than 30 KB, the URL is retried up to three times with a
configurable pause; the final failure is recorded as
``status=captcha-after-retries`` in the report. The audit never aborts on
captcha — it logs and continues so partial results stay usable.

Network
-------
Requires outbound HTTPS to ``yandex.ru``. No Yandex Direct OAuth needed.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Optional


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import requests  # noqa: E402

from direct_cli._vendor.tapi_yandex_direct.v4 import SUPPORTED_V4_METHODS  # noqa: E402
from direct_cli._vendor.tapi_yandex_direct.resource_mapping import (  # noqa: E402
    RESOURCE_MAPPING_V5,
)
from direct_cli.reports_coverage import REPORTS_SPEC_URLS  # noqa: E402
from direct_cli.v4_contracts import (  # noqa: E402
    PARAM_UNDOCUMENTED,
    V4_METHOD_CONTRACTS,
)
from direct_cli.wsdl_coverage import CLI_TO_API_SERVICE  # noqa: E402


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

V4_LIVE_BASE = "https://yandex.ru/dev/direct/doc/dg-v4/live/{method}.html"
V4_REFERENCE_BASE = "https://yandex.ru/dev/direct/doc/dg-v4/reference/{method}.html"
# Single source of truth: the Reports spec URL lives in the registry
# (direct_cli.reports_coverage.REPORTS_SPEC_URLS) per CLAUDE.md's
# "No URL literals outside the registry" rule — never duplicate it here.
REPORTS_SPEC_URL = REPORTS_SPEC_URLS["spec"]

CAPTCHA_MARKERS = ("showcaptcha", "smartcaptcha", "<title>captcha")
MIN_HTML_SIZE = 30_000
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_PAUSE_SECS = 5.0
HTTP_TIMEOUT_SECS = 30
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (direct-cli/audit_wire_shape)"}

# Live 4 changelog marker proves the page is actually the Live version,
# not the legacy /reference/ variant which silently lacks it.
LIVE4_MARKER = "Новое в версии Live 4"


# ---------------------------------------------------------------------------
# Fetcher with captcha-retry guard
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class FetchResult:
    url: str
    status: str  # "ok" | "captcha-after-retries" | "thin" | "http-{code}" | "error"
    html: Optional[str]
    attempts: int
    note: str = ""


def looks_like_captcha(html: str) -> bool:
    lower = html.lower()
    return any(marker in lower for marker in CAPTCHA_MARKERS)


def fetch_doc(
    url: str,
    retries: int = DEFAULT_RETRY_ATTEMPTS,
    pause: float = DEFAULT_RETRY_PAUSE_SECS,
) -> FetchResult:
    """GET *url* with captcha/thin guard and exponential-ish retry.

    Detects three failure modes:
        * captcha gateway (markers in body),
        * suspiciously thin body (< 30 KB),
        * HTTP error.

    Each attempt sleeps ``pause * attempt_index`` seconds before retrying
    (so 5s, 10s, 15s by default). The final attempt's diagnosis is
    surfaced as ``FetchResult.status``.
    """
    last_diag = "no-attempts"
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, timeout=HTTP_TIMEOUT_SECS, headers=HTTP_HEADERS)
        except requests.RequestException as exc:
            last_diag = f"error: {exc!s}"
            if attempt < retries:
                time.sleep(pause * attempt)
                continue
            return FetchResult(url, "error", None, attempt, last_diag)

        if resp.status_code >= 400:
            last_diag = f"http-{resp.status_code}"
            if attempt < retries and resp.status_code in (429, 500, 502, 503, 504):
                time.sleep(pause * attempt)
                continue
            return FetchResult(url, last_diag, None, attempt, "")

        html = resp.text
        if looks_like_captcha(html):
            last_diag = "captcha"
            if attempt < retries:
                time.sleep(pause * attempt)
                continue
            return FetchResult(url, "captcha-after-retries", html, attempt, "")

        if len(html) < MIN_HTML_SIZE:
            last_diag = f"thin ({len(html)} bytes)"
            if attempt < retries:
                time.sleep(pause * attempt)
                continue
            return FetchResult(url, "thin", html, attempt, last_diag)

        return FetchResult(url, "ok", html, attempt, "")

    return FetchResult(url, last_diag, None, retries, last_diag)


# ---------------------------------------------------------------------------
# HTML → plain text + Yandex-docs JSON-schema parser
# ---------------------------------------------------------------------------


_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>", re.S)
_STYLE_RE = re.compile(r"<style[^>]*>.*?</style>", re.S)
_WS_RE = re.compile(r"\s+")


def strip_html(html: str) -> str:
    text = _SCRIPT_RE.sub("", html)
    text = _STYLE_RE.sub("", text)
    text = _TAG_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


# Yandex docs render schema blocks like:
#     /* TypeName */ "Field1" : (int), "Field2" : (float), "Currency" : (string)
# Capture everything between the "/* TypeName */" comment and the matching
# closing brace (single-level — Yandex never nests beyond one level inside
# one `param` block).
# Match the schema fragment starting with "/* TypeName */" and the body
# that follows up to the next `/*` comment or the request closing marker.
# Yandex docs nest items inside a single "param" block, and the body may
# itself contain `{}` for array items — capturing everything up to the
# next type marker is correct and avoids losing nested keys.
_SCHEMA_BLOCK_RE = re.compile(
    r"/\*\s*(?P<type>[A-Za-z][A-Za-z0-9_]*)\s*\*/(?P<body>.*?)(?=/\*\s*[A-Za-z]|\}\s*\}\s*$|Ниже\s+приведено\s+описание|Результирующие\s+данные|Выходные\s+данные)",
    re.S,
)
# Yandex renders JSON keys as both `"Field"` and HTML-entity `&quot;Field&quot;`
# depending on whether we feed raw HTML or tag-stripped text into the parser.
_FIELD_RE = re.compile(
    r"(?:&quot;|\")([A-Za-z][A-Za-z0-9_]*)(?:&quot;|\")\s*:"
)
# The text between «Входные данные» and «Результирующие данные»/«Выходные
# данные»/«Описание параметров» is the request section. Everything after
# is response. We only audit request.
_REQUEST_SECTION_RE = re.compile(
    r"Входные\s+данные(?P<body>.*?)(?:Результирующие\s+данные|Выходные\s+данные|Примеры\s+входных)",
    re.S,
)


def extract_request_section(text_or_html: str) -> str:
    """Cut out the «Входные данные» … «Результирующие данные» portion.

    Yandex docs render a table of contents inline that repeats every
    section name, so both markers appear multiple times in the body. The
    schema block always sits between the LAST «Входные данные» heading
    and the FIRST «Результирующие данные» / «Выходные данные» that
    follows it — i.e. the latest opening + the next closing. Falls back
    to the whole document on legacy `/reference/` pages that omit the
    Russian section headers.
    """
    request_matches = list(re.finditer(r"Входные\s+данные", text_or_html))
    if not request_matches:
        return text_or_html
    request_start = request_matches[-1].end()
    response_marker = re.search(
        r"Результирующие\s+данные|Выходные\s+данные",
        text_or_html[request_start:],
    )
    if not response_marker:
        return text_or_html[request_start:]
    return text_or_html[request_start: request_start + response_marker.start()]


def parse_schema_blocks(text_or_html: str) -> dict[str, list[str]]:
    """Return ``{TypeName: [field names…]}`` from Yandex docs JSON schema blocks.

    Only inspects the request section (between «Входные данные» and
    «Результирующие данные»), so response-side field names do not leak
    into the per-request audit.
    """
    section = extract_request_section(text_or_html)
    blocks: dict[str, list[str]] = {}
    for match in _SCHEMA_BLOCK_RE.finditer(section):
        type_name = match.group("type")
        body = match.group("body")
        fields = _FIELD_RE.findall(body)
        if type_name not in blocks:
            blocks[type_name] = list(dict.fromkeys(fields))
    return blocks


# Detect the changelog "Currency stал обязательным" / "Добавлен метод X"
# entries to surface enum drift even when the table is rendered into a
# generic blob of text after tag stripping.
_REQUIRED_HINT_RE = re.compile(r"Входной параметр (\w+) стал обязательным")
_ADDED_ENUM_RE = re.compile(r"Добавлен[ао]? метод оплаты [«\"]?(\w+)[»\"]?")


def parse_live4_hints(text: str) -> dict[str, list[str]]:
    """Extract «Новое в версии Live 4» mentions of newly-required fields
    and newly-added enum values, both of which are common change types."""
    return {
        "newly_required": _REQUIRED_HINT_RE.findall(text),
        "added_enum_values": _ADDED_ENUM_RE.findall(text),
    }


# ---------------------------------------------------------------------------
# Payload-builder inspection (light AST grep over commands/*.py)
# ---------------------------------------------------------------------------


_PARAMS_ASSIGN_RE = re.compile(
    r"(?:params|param)\s*\[\s*&quot;?(?P<key>[A-Za-z][A-Za-z0-9_]*)&quot;?",
)
_PARAMS_LIT_RE = re.compile(
    r"['\"](?P<key>[A-Z][A-Za-z0-9_]*)['\"]\s*:",
)


def collect_payload_keys_from_source(file_path: Path) -> set[str]:
    """Grep payload keys (CapitalCase) from a command-module source file.

    Heuristic: every CapitalCase string literal followed by ``:`` is treated
    as a candidate payload key. This is intentionally over-inclusive — we
    use it only to **confirm** that a docs-required key is mentioned
    somewhere in the module, never to assert exclusivity.
    """
    if not file_path.exists():
        return set()
    src = file_path.read_text(encoding="utf-8")
    return set(_PARAMS_LIT_RE.findall(src))


# ---------------------------------------------------------------------------
# Comparison / finding model
# ---------------------------------------------------------------------------


FINDING_DOCS_HAS_CODE_LACKS = "docs_field_missing_in_code"
FINDING_CODE_HAS_DOCS_LACKS = "code_field_missing_in_docs"
FINDING_REQUIRED_MISSING_IN_PAYLOAD = "required_field_missing_in_payload_module"
FINDING_NOTES_REFERENCE_URL = "notes_points_at_reference_url"
FINDING_DOCS_UNREACHABLE = "docs_unreachable"
FINDING_LIVE4_MARKER_ABSENT = "live4_marker_absent"
FINDING_ENUM_VALUE_MISSING = "enum_value_in_docs_missing_in_choice"


@dataclasses.dataclass
class Finding:
    layer: str  # "v4" | "v5" | "reports"
    method: str
    url: str
    kind: str
    detail: str
    snippet: Optional[str] = None


# ---------------------------------------------------------------------------
# v4 audit
# ---------------------------------------------------------------------------


# Map vendored v4 method -> CLI command module file.
V4_METHOD_TO_MODULE: dict[str, str] = {
    "GetClientsUnits":         "direct_cli/commands/v4finance.py",
    "GetCreditLimits":         "direct_cli/commands/v4finance.py",
    "CheckPayment":            "direct_cli/commands/v4finance.py",
    "CreateInvoice":           "direct_cli/commands/v4finance.py",
    "TransferMoney":           "direct_cli/commands/v4finance.py",
    "PayCampaigns":            "direct_cli/commands/v4finance.py",
    "PayCampaignsByCard":      "",  # not exposed by policy
    "AccountManagement":       "direct_cli/commands/v4account.py",
    "EnableSharedAccount":     "direct_cli/commands/v4account.py",
    "GetEventsLog":            "direct_cli/commands/v4events.py",
    "GetStatGoals":            "direct_cli/commands/v4goals.py",
    "GetRetargetingGoals":     "direct_cli/commands/v4goals.py",
    "GetCampaignsTags":        "direct_cli/commands/v4tags.py",
    "GetBannersTags":          "direct_cli/commands/v4tags.py",
    "UpdateCampaignsTags":     "direct_cli/commands/v4tags.py",
    "UpdateBannersTags":       "direct_cli/commands/v4tags.py",
    "CreateNewWordstatReport": "direct_cli/commands/v4wordstat.py",
    "GetWordstatReportList":   "direct_cli/commands/v4wordstat.py",
    "GetWordstatReport":       "direct_cli/commands/v4wordstat.py",
    "DeleteWordstatReport":    "direct_cli/commands/v4wordstat.py",
    "CreateNewForecast":       "direct_cli/commands/v4forecast.py",
    "GetForecastList":         "direct_cli/commands/v4forecast.py",
    "GetForecast":             "direct_cli/commands/v4forecast.py",
    "DeleteForecastReport":    "direct_cli/commands/v4forecast.py",
    "GetKeywordsSuggestion":   "direct_cli/commands/keywordsresearch.py",
    "DeleteReport":            "direct_cli/commands/reports.py",
    "DeleteOfflineReport":     "direct_cli/commands/reports.py",
    "AdImageAssociation":      "direct_cli/commands/adimages.py",
    "PingAPI":                 "direct_cli/commands/v4shells.py",
    "PingAPI_X":               "",  # internal alias
    "GetVersion":              "direct_cli/commands/v4shells.py",
    "GetAvailableVersions":    "direct_cli/commands/v4shells.py",
}


def _collect_example_keys(example_param: Any) -> set[str]:
    """Recursive set of all dict keys in a docs-style example_param.

    None / scalar / list-of-scalar examples return empty set. Lists with
    dict children traverse into the children.
    """
    if example_param is None:
        return set()
    if isinstance(example_param, dict):
        out: set[str] = set()
        for key, value in example_param.items():
            out.add(key)
            out.update(_collect_example_keys(value))
        return out
    if isinstance(example_param, list):
        out = set()
        for item in example_param:
            out.update(_collect_example_keys(item))
        return out
    return set()


def audit_v4(
    retries: int,
    pause: float,
    methods: Optional[Iterable[str]] = None,
) -> list[Finding]:
    findings: list[Finding] = []
    target = list(methods) if methods else sorted(SUPPORTED_V4_METHODS)
    for method in target:
        contract = V4_METHOD_CONTRACTS.get(method)
        if contract is None:
            findings.append(
                Finding(
                    "v4", method, "",
                    "missing_contract",
                    "method is in SUPPORTED_V4_METHODS but absent from V4_METHOD_CONTRACTS",
                )
            )
            continue

        if contract.param_shape == PARAM_UNDOCUMENTED:
            # Policy: do not probe undocumented methods. Just record.
            findings.append(
                Finding(
                    "v4", method, "",
                    "skipped_undocumented_by_policy",
                    f"param_shape={contract.param_shape}; not audited",
                )
            )
            continue

        notes = contract.notes or ""
        live_url = V4_LIVE_BASE.format(method=method)
        reference_url = V4_REFERENCE_BASE.format(method=method)

        # Try Live 4 page first (financial methods), fall back to reference
        # (non-financial v4 methods that pre-date Live 4 and never moved).
        fetched = fetch_doc(live_url, retries=retries, pause=pause)
        url_used = live_url
        if fetched.status in {"http-404", "http-410"}:
            fetched_ref = fetch_doc(reference_url, retries=retries, pause=pause)
            if fetched_ref.status == "ok":
                fetched = fetched_ref
                url_used = reference_url

        # notes-points-at-reference only fires when the Live URL was actually
        # read (status ok) and the contract still pins reference — i.e. the
        # exact #125 bug. Gating on status==ok avoids asserting "live exists,
        # drop reference" on the basis of a captcha-blocked page we never
        # verified (15/16 v4 methods were captcha'd in the 2026-05-29 run).
        if (
            "dg-v4/reference/" in notes
            and url_used == live_url
            and fetched.status == "ok"
        ):
            findings.append(
                Finding(
                    "v4", method, live_url,
                    FINDING_NOTES_REFERENCE_URL,
                    "contract.notes references dg-v4/reference/ but "
                    "dg-v4/live/ exists — Live 4 schema must be used",
                    snippet=notes[:200],
                )
            )

        if fetched.status != "ok":
            findings.append(
                Finding(
                    "v4", method, live_url,
                    FINDING_DOCS_UNREACHABLE,
                    f"fetcher status={fetched.status} attempts={fetched.attempts} "
                    f"note={fetched.note!r}",
                )
            )
            continue

        text = strip_html(fetched.html or "")
        is_live_page = url_used == live_url
        if is_live_page and LIVE4_MARKER not in text:
            # Live page reachable but no Live 4 changelog block — possible
            # silent redirect or docs change. Reference pages legitimately
            # lack it.
            findings.append(
                Finding(
                    "v4", method, url_used,
                    FINDING_LIVE4_MARKER_ABSENT,
                    "live page reachable but lacks «Новое в версии Live 4»",
                )
            )

        # Docs schema fields (TypeName → keys).
        blocks = parse_schema_blocks(fetched.html or "")
        # Re-scan the stripped text as a backup: helps for pages where the
        # raw HTML uses non-standard quoting that the entity regex misses.
        text_blocks = parse_schema_blocks(text)
        for type_name, keys in text_blocks.items():
            blocks.setdefault(type_name, []).extend(
                k for k in keys if k not in blocks.get(type_name, [])
            )

        docs_field_set: set[str] = set()
        for keys in blocks.values():
            docs_field_set.update(keys)

        example_keys = _collect_example_keys(contract.example_param)

        # Only flag fields that look like first-class request keys — drop
        # noise from generic JSON example types (e.g. "method", "param").
        for key in sorted(docs_field_set - example_keys):
            if key in {"method", "param", "finance_token", "operation_num"}:
                continue
            findings.append(
                Finding(
                    "v4", method, url_used,
                    FINDING_DOCS_HAS_CODE_LACKS,
                    f"docs schema mentions {key!r} but contract.example_param does not",
                    snippet=f"types={sorted(blocks)} → has {key}",
                )
            )
        for key in sorted(example_keys - docs_field_set):
            findings.append(
                Finding(
                    "v4", method, url_used,
                    FINDING_CODE_HAS_DOCS_LACKS,
                    f"contract.example_param has {key!r} but live docs schema does not",
                )
            )

        hints = parse_live4_hints(text)
        # Newly-required fields surface as concrete recommendations:
        for new_req in hints.get("newly_required", []):
            if new_req not in example_keys:
                findings.append(
                    Finding(
                        "v4", method, live_url,
                        FINDING_REQUIRED_MISSING_IN_PAYLOAD,
                        f"Live 4 changelog marks {new_req!r} required but "
                        f"contract.example_param does not include it",
                    )
                )

        # Enum drift: scan command module for added values like Overdraft.
        module_path = V4_METHOD_TO_MODULE.get(method)
        if module_path:
            module_keys = collect_payload_keys_from_source(REPO_ROOT / module_path)
            for new_enum in hints.get("added_enum_values", []):
                if new_enum not in module_keys:
                    findings.append(
                        Finding(
                            "v4", method, live_url,
                            FINDING_ENUM_VALUE_MISSING,
                            f"Live 4 changelog adds enum value {new_enum!r}; "
                            f"not found in {module_path}",
                        )
                    )
    return findings


# ---------------------------------------------------------------------------
# v5 audit  (skeleton — operates per service/operation page)
# ---------------------------------------------------------------------------


def _v5_per_method_url(docs_base: str, method: str) -> str:
    """Yandex renders per-operation docs at ``<resource_base>/<method>``.

    Most registry ``docs`` entries are doubled (``…/ru/campaigns/campaigns``);
    there the per-method page is ``…/ru/campaigns/add``, so the trailing
    duplicate segment is chopped before appending the method. Single-segment
    bases (``…/ru/vcards``, ``…/ru/smartadtargets``) must NOT lose their
    resource name — appending blindly after rpartition would yield
    ``…/ru/add`` and silently mis-audit the whole group. We chop the tail
    only when it duplicates its parent segment.
    """
    base = docs_base.rstrip("/")
    parent, _, tail = base.rpartition("/")
    if parent:
        grandparent, _, parent_tail = parent.rpartition("/")
        if tail == parent_tail:
            return f"{parent}/{method}"
    return f"{base}/{method}"


def audit_v5(retries: int, pause: float) -> list[Finding]:
    findings: list[Finding] = []
    for cli_group, wsdl_service in CLI_TO_API_SERVICE.items():
        info = RESOURCE_MAPPING_V5.get(cli_group) or RESOURCE_MAPPING_V5.get(wsdl_service)
        if info is None:
            findings.append(
                Finding(
                    "v5", wsdl_service, "",
                    "missing_docs_url",
                    f"RESOURCE_MAPPING_V5 has no entry for CLI group "
                    f"{cli_group!r} (service {wsdl_service!r})",
                )
            )
            continue

        docs_base = info.get("docs", "")
        docs_pages = info.get("docs_pages") or {}
        methods = info.get("methods") or []

        seen_urls: set[str] = set()
        targets: list[tuple[str, str]] = []
        # Services whose human-readable doc pages Yandex removed (#463) carry a
        # WSDL endpoint as `docs`. Per-method URL derivation assumes a
        # `…/ru/<svc>` page shape and would emit garbage like `…?wsdl/get`, so
        # treat a WSDL base as a single group-level target instead.
        wsdl_base = docs_base.rstrip("/").endswith("?wsdl") or docs_base.endswith(
            ".wsdl"
        )
        if wsdl_base:
            targets.append(("__group__", docs_base))
        else:
            for op in methods:
                # docs_pages override > derived URL from docs base
                url = (docs_pages or {}).get(op)
                if not url and docs_base:
                    url = _v5_per_method_url(docs_base, op)
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                targets.append((op, url))
            if not targets and docs_base:
                targets.append(("__group__", docs_base))

        for op_name, url in targets:
            # WSDL bases (#463: services whose doc pages Yandex removed) are
            # XML, not 30 KB HTML doc pages — fetch_doc would flag them as
            # "thin". Validate them as real WSDL instead and record coverage.
            if wsdl_base:
                fetched = fetch_doc(url, retries=retries, pause=pause)
                html = fetched.html or ""
                lower = html.lower()
                if fetched.status in ("ok", "thin") and (
                    "wsdl:definitions" in lower or "<definitions" in lower
                ):
                    findings.append(
                        Finding(
                            "v5", f"{cli_group}.{op_name}", url,
                            "v5_wsdl_group_ok",
                            f"WSDL endpoint reachable ({len(html)} bytes); "
                            "doc page removed by Yandex (see #463)",
                        )
                    )
                else:
                    findings.append(
                        Finding(
                            "v5", f"{cli_group}.{op_name}", url,
                            FINDING_DOCS_UNREACHABLE,
                            f"WSDL fetch status={fetched.status} "
                            f"attempts={fetched.attempts}",
                        )
                    )
                continue

            fetched = fetch_doc(url, retries=retries, pause=pause)
            if fetched.status != "ok":
                findings.append(
                    Finding(
                        "v5", f"{cli_group}.{op_name}", url,
                        FINDING_DOCS_UNREACHABLE,
                        f"fetcher status={fetched.status} attempts={fetched.attempts} "
                        f"note={fetched.note!r}",
                    )
                )
                continue
            blocks = parse_schema_blocks(fetched.html or "")
            if not blocks:
                # Group-level pages often summarise without an inline schema
                # block; not finding one is informational, not an error.
                findings.append(
                    Finding(
                        "v5", f"{cli_group}.{op_name}", url,
                        "v5_schema_not_extracted",
                        "page reachable but no /* TypeName */ schema block found",
                    )
                )
                continue
            # Positive coverage line — the human reviewer can sample these
            # to confirm the scraper picked the right types per operation.
            findings.append(
                Finding(
                    "v5", f"{cli_group}.{op_name}", url,
                    "v5_schema_seen",
                    f"types={sorted(blocks)}",
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Reports audit (skeleton — sanity-check ru/spec parses)
# ---------------------------------------------------------------------------


def audit_reports(retries: int, pause: float) -> list[Finding]:
    findings: list[Finding] = []
    fetched = fetch_doc(REPORTS_SPEC_URL, retries=retries, pause=pause)
    if fetched.status != "ok":
        findings.append(
            Finding(
                "reports", "spec", REPORTS_SPEC_URL,
                FINDING_DOCS_UNREACHABLE,
                f"fetcher status={fetched.status} attempts={fetched.attempts}",
            )
        )
        return findings
    text = strip_html(fetched.html or "")
    # Smoke check: spec must mention at least one of the core report fields
    # to confirm the page is still the right content type.
    required_text_markers = ("ReportName", "SelectionCriteria", "FieldNames")
    for marker in required_text_markers:
        if marker not in text:
            findings.append(
                Finding(
                    "reports", "spec", REPORTS_SPEC_URL,
                    "reports_spec_marker_absent",
                    f"docs page does not mention {marker!r}",
                )
            )
    if not findings:
        findings.append(
            Finding(
                "reports", "spec", REPORTS_SPEC_URL,
                "reports_spec_ok",
                "spec page reachable and contains core markers",
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def emit_json(findings: list[Finding], path: Path) -> None:
    payload = [dataclasses.asdict(f) for f in findings]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def emit_markdown(findings: list[Finding], path: Path, header_lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[str] = []
    rows.extend(header_lines)
    rows.append("")
    rows.append("| Layer | Method | Kind | Detail | URL |")
    rows.append("|---|---|---|---|---|")
    for f in findings:
        detail = f.detail.replace("|", "\\|").replace("\n", " ")
        url = f.url or "—"
        rows.append(f"| {f.layer} | `{f.method}` | `{f.kind}` | {detail} | {url} |")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--v4", action="store_true", help="audit v4 Live methods")
    parser.add_argument("--v5", action="store_true", help="audit v5 WSDL services")
    parser.add_argument("--reports", action="store_true", help="audit Reports surface")
    parser.add_argument("--all", action="store_true", help="run v4 + v5 + reports")
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRY_ATTEMPTS,
        help=f"captcha/thin retry attempts (default: {DEFAULT_RETRY_ATTEMPTS})",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=DEFAULT_RETRY_PAUSE_SECS,
        help=f"base pause between retries in seconds (default: {DEFAULT_RETRY_PAUSE_SECS})",
    )
    parser.add_argument("--json", type=Path, default=None, help="JSON output path")
    parser.add_argument("--markdown", type=Path, default=None, help="Markdown output path")
    parser.add_argument(
        "--methods",
        default="",
        help="comma-separated subset of v4 method names (debug; v4 mode only)",
    )

    args = parser.parse_args(argv)
    if not (args.v4 or args.v5 or args.reports or args.all):
        parser.error("specify at least one of --v4 / --v5 / --reports / --all")

    do_v4 = args.v4 or args.all
    do_v5 = args.v5 or args.all
    do_reports = args.reports or args.all

    findings: list[Finding] = []
    if do_v4:
        subset = [m.strip() for m in args.methods.split(",") if m.strip()] or None
        print(
            f"[v4] auditing {len(subset) if subset else len(SUPPORTED_V4_METHODS)} "
            f"methods (retries={args.retries}, pause={args.pause}s)…",
            file=sys.stderr,
        )
        findings.extend(audit_v4(args.retries, args.pause, subset))
    if do_v5:
        print(
            f"[v5] auditing {len(CLI_TO_API_SERVICE)} CLI groups…",
            file=sys.stderr,
        )
        findings.extend(audit_v5(args.retries, args.pause))
    if do_reports:
        print("[reports] auditing reports surface…", file=sys.stderr)
        findings.extend(audit_reports(args.retries, args.pause))

    counts: dict[str, int] = {}
    for f in findings:
        counts[f.kind] = counts.get(f.kind, 0) + 1
    header = [
        "# Project docs / wire-shape audit",
        "",
        f"Total findings: **{len(findings)}**",
        "",
        "## Findings by kind",
        "",
    ]
    for kind, count in sorted(counts.items(), key=lambda x: -x[1]):
        header.append(f"- `{kind}`: {count}")

    if args.json:
        emit_json(findings, args.json)
    if args.markdown:
        emit_markdown(findings, args.markdown, header)
    if not args.json and not args.markdown:
        for line in header:
            print(line)
        print()
        for f in findings:
            print(f"[{f.layer}] {f.method} {f.kind}: {f.detail}")

    error_kinds = {
        FINDING_DOCS_HAS_CODE_LACKS,
        FINDING_REQUIRED_MISSING_IN_PAYLOAD,
        FINDING_NOTES_REFERENCE_URL,
        FINDING_ENUM_VALUE_MISSING,
    }
    return 1 if any(f.kind in error_kinds for f in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
