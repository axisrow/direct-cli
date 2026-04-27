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


def _validate_captured(captured: str, path: Path, line_number: int, line: str) -> None:
    """Raise ValueError if the captured import group is unsupported."""
    if captured.rstrip() in ("\\", ""):
        raise ValueError(
            f"{path}:{line_number}: backslash import continuation not supported: {line!r}"
        )


def _relative_from(vendor_dir: Path, path: Path, target_module: str | None) -> str:
    """
    Return the relative import module for an upstream absolute import.

    Args:
        vendor_dir: Root of the vendored ``tapi_yandex_direct`` package.
        path: Python source file containing the import.
        target_module: Module path after ``tapi_yandex_direct.``, or None for
            ``from tapi_yandex_direct import ...``.

    Returns:
        Relative import prefix/module, such as ``.``, ``..``, or
        ``.resource_mapping``.
    """
    current_parts = path.parent.relative_to(vendor_dir).parts
    target_parts = tuple(target_module.split(".")) if target_module else ()

    common = 0
    for current_part, target_part in zip(current_parts, target_parts):
        if current_part != target_part:
            break
        common += 1

    dot_count = len(current_parts) - common + 1
    remainder = target_parts[common:]
    return "." * dot_count + ".".join(remainder)


def patch_line(line: str, path: Path, line_number: int, vendor_dir: Path) -> str:
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
        _validate_captured(captured, path, line_number, line)
        return f"from {_relative_from(vendor_dir, path, None)} import {captured}"

    match = FROM_SUBMODULE_RE.match(line)
    if match:
        captured = match.group(2)
        _validate_captured(captured, path, line_number, line)
        return (
            f"from {_relative_from(vendor_dir, path, match.group(1))} "
            f"import {captured}"
        )

    if line.startswith("import tapi_yandex_direct"):
        raise ValueError(f"{path}:{line_number}: unsupported absolute import: {line}")

    return line


def _compute_patch(path: Path, vendor_dir: Path) -> str | None:
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
        patch_line(line, path, line_number, vendor_dir)
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
        patched = _compute_patch(path, vendor_dir)
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
