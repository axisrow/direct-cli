"""Shared option parsing/validation helpers for v4 Live commands.

Several v4 command modules grew byte-identical (or near-identical) option
validators. They are hoisted here so the logic — and the i18n keys behind each
error message — lives in one place. Every user-facing message is either reused
verbatim (``non_empty``/``parse_positive_ids`` use the templated
``{option_name}`` keys) or passed in by the caller (``parse_id_value_specs``),
so the rendered CLI surface stays byte-identical.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple

import click

from ..i18n import t
from ..utils import parse_ids


def non_empty(value: Optional[str], option_name: str) -> str:
    """Normalize a required string option, rejecting blank/whitespace input."""
    normalized = (value or "").strip()
    if not normalized:
        raise click.UsageError(
            t("{option_name} must not be empty").format(option_name=option_name)
        )
    return normalized


def parse_positive_ids(
    value: Optional[str],
    option_name: str,
    *,
    require_positive: bool = True,
) -> List[int]:
    """Parse a required comma-separated integer ID list.

    The list must be non-empty; when *require_positive* is true (the default)
    every ID must be > 0. Callers wrap the returned ``list[int]`` in whatever
    request shape they need.
    """
    try:
        ids = parse_ids(value)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc
    if not ids:
        raise click.UsageError(
            t("{option_name} must not be empty").format(option_name=option_name)
        )
    if require_positive and any(item <= 0 for item in ids):
        raise click.UsageError(
            t("{option_name} must contain only positive integers").format(
                option_name=option_name
            )
        )
    return ids


def parse_id_value_specs(
    specs: Tuple[str, ...],
    *,
    required_msg: str,
    not_integer_msg: str,
    non_positive_msg: str,
    duplicate_msg: str,
    malformed_msg: Optional[str] = None,
    allow_bare_id: bool = False,
    empty_spec_msg: Optional[str] = None,
    value_parser: Optional[Callable[[Optional[str]], object]] = None,
    max_entries: Optional[int] = None,
    max_entries_msg: Optional[str] = None,
    max_check: str = "before",
) -> List[Tuple[int, object]]:
    """Validate repeated ``ID=VALUE`` specs into ``(id_int, value)`` pairs.

    Shared skeleton for the v4 payment/association parsers: split on ``=``,
    strip, integer + positivity validation, and duplicate-ID rejection in spec
    order. Each caller supplies its exact error strings (preserving its i18n
    keys) and maps the returned pairs to its own WSDL field names.

    Args:
        specs: the raw ``--option`` tuple from Click.
        required_msg: raised when *specs* is empty.
        not_integer_msg: raised when an ID is not an integer.
        non_positive_msg: raised when an ID is <= 0 (same string as
            *not_integer_msg* for callers that share one message).
        duplicate_msg: raised on a repeated ID.
        malformed_msg: raised when a spec lacks ``=`` and *allow_bare_id* is
            false.
        allow_bare_id: when true, a spec without ``=`` yields ``value=None``
            (a bare ID rather than a malformed entry).
        empty_spec_msg: when set, a blank entry raises this instead of being
            treated as malformed.
        value_parser: optional callable applied to the stripped value text
            (after the ID passes all checks), so value parsing keeps the
            original per-entry ordering. Defaults to returning the text as-is.
        max_entries / max_entries_msg: optional cap and its message.
        max_check: ``"before"`` checks the cap up front (on the raw count),
            ``"after"`` checks it once all entries are validated.
    """
    if not specs:
        raise click.UsageError(required_msg)
    if max_entries is not None and max_check == "before" and len(specs) > max_entries:
        raise click.UsageError(max_entries_msg)

    seen: set = set()
    pairs: List[Tuple[int, object]] = []
    for entry in specs:
        spec = (entry or "").strip()
        if not spec and empty_spec_msg is not None:
            raise click.UsageError(empty_spec_msg)
        if "=" in spec:
            id_text, value_text = spec.split("=", 1)
            value_text = value_text.strip()
        elif allow_bare_id:
            id_text, value_text = spec, None
        else:
            raise click.UsageError(malformed_msg)
        id_text = id_text.strip()
        try:
            id_int = int(id_text)
        except ValueError as exc:
            raise click.UsageError(not_integer_msg) from exc
        if id_int <= 0:
            raise click.UsageError(non_positive_msg)
        if id_int in seen:
            raise click.UsageError(duplicate_msg)
        seen.add(id_int)
        value = value_parser(value_text) if value_parser is not None else value_text
        pairs.append((id_int, value))

    if max_entries is not None and max_check == "after" and len(pairs) > max_entries:
        raise click.UsageError(max_entries_msg)
    return pairs
