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

# --- Local stub patch: the `timeout` kwarg that the upstream fork drops ---
#
# auth._resolve_client_login_via_api passes ``timeout=`` to ``clients().post()``
# on the credential-resolution hot path. tapi2 forwards it straight to
# ``requests`` at runtime, but the hand-maintained ``.pyi`` stub omits it, so
# mypy (the CI "Quality" gate) rejects the call. ``update_vendor.sh`` rebuilds
# the vendor dir with ``rm -rf`` + ``cp -R`` of the fork, which has no such
# edit, so the fix is wiped on every bump (it last survived ~10 minutes — see
# the #480 follow-up). Re-applying it here, after the copy, makes it
# self-healing. Keep the fork carrying it too as belt-and-braces.
#
# Scope is the *client* executor only — the type auth.py calls. The report
# executor and v4 adapter never receive ``timeout``, so they stay untouched.
_TIMEOUT_PARAM = "timeout: float = None"
_TIMEOUT_DOC = (
    "        :param timeout: forwarded to requests as the connect+read timeout"
)
_STUB_CLASS = "class YandexDirectClientExecutor"

# Upstream emits the param list on a single line; match it so we can append the
# kwarg. The guard against an already-present ``timeout`` keeps this idempotent.
_EXECUTOR_SIG_RE = re.compile(
    r"^(?P<head>\s*self, \*, params: dict = None, data: dict = None, "
    r"headers: dict = None)(?P<tail>\s*)$"
)
_PARAM_DATA_RE = re.compile(r"^\s*:param data:")

# --- Local runtime patch: to_columns must tolerate short report rows ---
#
# A report data row can carry fewer tab-separated cells than the column header
# (Yandex omits trailing empty fields). Upstream's ``to_columns`` indexes
# ``values[i]`` unconditionally and raises IndexError on such rows; our fix
# pads the missing cells with "". Like the timeout stub, the upstream fork
# drops this, so ``update_vendor.sh`` wipes it on every bump — re-apply here.
# Covered by tests/test_reports_parsing.py::...to_columns_handles_short_rows.
_TO_COLUMNS_UPSTREAM = "                col.append(values[i])"
_TO_COLUMNS_PATCHED = '                col.append(values[i] if i < len(values) else "")'


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
            f"from {_relative_from(vendor_dir, path, match.group(1))} import {captured}"
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

    patched = _patch_runtime_text(patched)

    if patched == original:
        return None

    return patched


def _patch_runtime_text(text: str) -> str:
    """Re-apply local runtime patches to a vendored ``*.py`` source.

    Currently restores the short-row guard in ``to_columns`` (see the
    ``_TO_COLUMNS_*`` constants). Idempotent: a line already carrying the
    guard is left unchanged, so repeated runs are a no-op.
    """
    if _TO_COLUMNS_PATCHED in text:
        return text
    return text.replace(_TO_COLUMNS_UPSTREAM, _TO_COLUMNS_PATCHED)


def _patch_stub_text(text: str) -> str:
    """Re-add the ``timeout`` kwarg to ``YandexDirectClientExecutor.get/post``.

    Idempotent and scope-safe:

    * A signature line that already mentions ``timeout`` is left untouched.
    * The ``:param timeout:`` docstring line is inserted after ``:param data:``
      only when it is not already the following line.
    * Only lines inside the ``YandexDirectClientExecutor`` class body are
      considered, so the report executor and v4 adapter signatures (which look
      alike but never receive ``timeout``) are never modified.

    Returns the text unchanged when there is nothing to patch.
    """
    lines = text.splitlines()
    out: list[str] = []
    in_stub_class = False
    for i, line in enumerate(lines):
        # Track which class body we are in. A new ``class`` statement always
        # appears at column 0, so this never trips on nested defs.
        if line.startswith("class "):
            in_stub_class = line.startswith(_STUB_CLASS)

        if in_stub_class and "timeout" not in line:
            sig = _EXECUTOR_SIG_RE.match(line)
            if sig:
                line = f"{sig.group('head')}, {_TIMEOUT_PARAM}{sig.group('tail')}"

        out.append(line)

        # Insert the docstring line right after ``:param data:`` — but only
        # inside the stub class and only if it is not already there. Dedup
        # against the next *source* line (lines[i + 1]) keeps repeated runs a
        # no-op regardless of how many lines we have already appended.
        if in_stub_class and _PARAM_DATA_RE.match(line):
            next_source = lines[i + 1] if i + 1 < len(lines) else ""
            if next_source.strip() != _TIMEOUT_DOC.strip():
                out.append(_TIMEOUT_DOC)

    patched = "\n".join(out)
    if text.endswith("\n"):
        patched += "\n"
    return patched


def patch_vendor_dir(vendor_dir: Path) -> int:
    """
    Patch all Python files under a vendored tapi_yandex_direct directory.

    Rewrites upstream absolute imports in ``*.py`` files to relative ones and
    re-applies the local ``timeout`` stub patch to ``*.pyi`` files (see
    :func:`_patch_stub_text`). Computes all patches before writing any file so
    that a ValueError on any file prevents partial (broken) writes.

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

    for path in sorted(vendor_dir.rglob("*.pyi")):
        original = path.read_text(encoding="utf-8")
        patched = _patch_stub_text(original)
        if patched != original:
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
