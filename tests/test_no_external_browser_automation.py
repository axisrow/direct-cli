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

import os
import re
from pathlib import Path
from typing import Iterator

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Never interesting for a prose/tool-name scan: VCS, caches, build output.
_SKIP_PARTS = {
    ".git",
    ".claude",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
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
_EXTERNAL_AUTOMATION_RE = re.compile(
    r"browser[-_]?use|claude[-_]in[-_]chrome", re.IGNORECASE
)


def _scan_files(root: Path) -> Iterator[Path]:
    """Prune excluded trees before descending, including installed dependencies."""
    for directory, subdirs, files in os.walk(root):
        subdirs[:] = sorted(name for name in subdirs if name not in _SKIP_PARTS)
        for name in sorted(files):
            path = Path(directory) / name
            if name not in _SKIP_PARTS and path.suffix.lower() not in _BINARY_SUFFIXES:
                yield path


def test_no_external_browser_automation_named():
    # This file must name the tools to ban them — never scan itself.
    guard_path = Path(__file__).resolve()
    hits = []
    for path in _scan_files(_REPO_ROOT):
        if path.resolve() == guard_path:
            continue
        if not path.is_file():
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


def test_scan_includes_owned_text_and_vendor_but_prunes_excluded_trees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    included = {"README.md", "docs/nested/guide.md", "direct_cli/_vendor/client.py"}
    excluded = {f"{part}/nested/file.txt" for part in _SKIP_PARTS}
    for name in included | excluded | {"docs/image.PNG"}:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")

    visited = []
    original_walk = os.walk

    def recording_walk(root: Path) -> Iterator[tuple[str, list[str], list[str]]]:
        for directory, subdirs, files in original_walk(root):
            visited.append(Path(directory).relative_to(root))
            yield directory, subdirs, files

    monkeypatch.setattr(os, "walk", recording_walk)
    assert {
        path.relative_to(tmp_path).as_posix() for path in _scan_files(tmp_path)
    } == included
    assert all(not (_SKIP_PARTS & set(path.parts)) for path in visited)
