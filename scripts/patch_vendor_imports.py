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
        captured = match.group(1)
        if captured.startswith("("):
            raise ValueError(
                f"{path}:{line_number}: multi-line import not supported: {line!r}"
            )
        return f"from . import {captured}"

    match = FROM_SUBMODULE_RE.match(line)
    if match:
        captured = match.group(2)
        if captured.startswith("("):
            raise ValueError(
                f"{path}:{line_number}: multi-line import not supported: {line!r}"
            )
        return f"from .{match.group(1)} import {captured}"

    if line.startswith("import tapi_yandex_direct"):
        raise ValueError(f"{path}:{line_number}: unsupported absolute import: {line}")

    return line


def _compute_patch(path: Path) -> str | None:
    """
    Compute patched content for a file, without writing.

    Args:
        path: Python source file to patch.

    Returns:
        Patched content string, or None if no changes are needed.

    Raises:
        ValueError: If an unsupported import form is found.
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
        return None

    return patched


def patch_vendor_dir(vendor_dir: Path) -> int:
    """
    Patch all Python files under a vendored tapi_yandex_direct directory.

    Computes all patches before writing any files so that a ValueError on
    any file prevents partial (broken) writes.

    Args:
        vendor_dir: Path to the vendored package directory.

    Returns:
        Number of files changed.

    Raises:
        FileNotFoundError: If the vendor directory does not exist.
        ValueError: If an unsupported import form is found.
    """
    if not vendor_dir.is_dir():
        raise FileNotFoundError(f"Vendor directory not found: {vendor_dir}")

    patches: dict[Path, str] = {}
    for path in sorted(vendor_dir.rglob("*.py")):
        patched = _compute_patch(path)
        if patched is not None:
            patches[path] = patched

    for path, content in patches.items():
        path.write_text(content, encoding="utf-8")

    return len(patches)


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
