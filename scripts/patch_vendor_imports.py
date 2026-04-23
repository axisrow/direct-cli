#!/usr/bin/env python3
"""
Patch vendored tapi_yandex_direct imports after copying upstream files.

The upstream package imports itself as ``tapi_yandex_direct``.  Direct CLI
embeds it under ``direct_cli._vendor``, so those imports must be relative.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

FROM_PACKAGE_RE = re.compile(r"^from tapi_yandex_direct import (.+)$")
FROM_SUBMODULE_RE = re.compile(
    r"^from tapi_yandex_direct\.([A-Za-z0-9_\.]+) import (.+)$"
)


def patch_line(line: str, path: Path, line_number: int) -> str:
    """
    Rewrite a single import line if it references the upstream package.

    Args:
        line: Source line without its trailing newline.
        path: File path used in error messages.
        line_number: One-based line number used in error messages.

    Returns:
        The original or rewritten line.

    Raises:
        ValueError: If an unsupported absolute import form is found.
    """
    match = FROM_PACKAGE_RE.match(line)
    if match:
        return f"from . import {match.group(1)}"

    match = FROM_SUBMODULE_RE.match(line)
    if match:
        return f"from .{match.group(1)} import {match.group(2)}"

    if line.startswith("import tapi_yandex_direct"):
        raise ValueError(f"{path}:{line_number}: unsupported absolute import: {line}")

    return line


def patch_file(path: Path) -> bool:
    """
    Patch all supported upstream absolute imports in a Python file.

    Args:
        path: Python source file to patch.

    Returns:
        True when the file content changed.
    """
    original = path.read_text(encoding="utf-8")
    has_trailing_newline = original.endswith("\n")
    patched_lines = [
        patch_line(line, path, line_number)
        for line_number, line in enumerate(original.splitlines(), 1)
    ]
    patched = "\n".join(patched_lines)
    if has_trailing_newline:
        patched += "\n"

    if patched == original:
        return False

    path.write_text(patched, encoding="utf-8")
    return True


def patch_vendor_dir(vendor_dir: Path) -> int:
    """
    Patch all Python files under a vendored tapi_yandex_direct directory.

    Args:
        vendor_dir: Path to the vendored package directory.

    Returns:
        Number of files changed.

    Raises:
        FileNotFoundError: If the vendor directory does not exist.
    """
    if not vendor_dir.is_dir():
        raise FileNotFoundError(f"Vendor directory not found: {vendor_dir}")

    changed = 0
    for path in sorted(vendor_dir.rglob("*.py")):
        if patch_file(path):
            changed += 1
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Patch vendored tapi_yandex_direct absolute imports."
    )
    parser.add_argument("vendor_dir", type=Path)
    args = parser.parse_args(argv)

    try:
        changed = patch_vendor_dir(args.vendor_dir)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Patched vendor imports in {changed} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
