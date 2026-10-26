"""No third-party browser automation is named anywhere in the repo (issue #906).

Issue #906: external browser-automation tools (browser-use and similar) must
never be required or recommended in the CLI workflow — not in docs, code
hints, error messages or fixture provenance. This guard fails on the tool
names themselves so a mention cannot quietly return in a future comment,
changelog entry or fixture header. The canonical session paths live in
``direct_cli/_auth_hints.py``; the AST guard in ``tests/test_unified_auth.py``
keeps login-command hints canonical. Skips generated/live caches (VCR
cassettes, Yandex WSDL/Reports snapshots) — everything else, including the
vendor tree, docs and CHANGELOG, is in scope.
"""

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Never interesting for a prose/tool-name scan: VCS, caches, build output.
_SKIP_PARTS = {
    ".git",
    ".claude",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
    "htmlcov",
    "dist",
    "build",
    # Generated/live data: Yandex snapshots and VCR recordings, not our text.
    "cassettes",
    "wsdl_cache",
    "reports_cache",
}
_BINARY_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".mp4",
    ".pdf",
    ".woff",
    ".woff2",
    ".pyc",
}

# Hyphen/underscore forms only: ``browser use`` with a space is ordinary
# English prose ("browser, use ..."), not the tool name.
_EXTERNAL_AUTOMATION_RE = re.compile(r"browser[-_]?use|claude-in-chrome", re.IGNORECASE)


def test_no_external_browser_automation_named():
    # This file must name the tools to ban them — never scan itself.
    guard_path = Path(__file__).resolve()
    hits = []
    for path in sorted(_REPO_ROOT.rglob("*")):
        if path.resolve() == guard_path:
            continue
        if not path.is_file():
            continue
        if any(part in _SKIP_PARTS for part in path.parts):
            continue
        if path.suffix.lower() in _BINARY_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _EXTERNAL_AUTOMATION_RE.search(line):
                hits.append(
                    f"{path.relative_to(_REPO_ROOT)}:{lineno}: " f"{line.strip()[:120]}"
                )
    assert not hits, (
        "third-party browser automation named (issue #906) — rewrite the "
        "mention neutrally, the native paths are direct_cli/_auth_hints.py:\n"
        + "\n".join(hits)
    )
