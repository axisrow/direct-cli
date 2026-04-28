"""Money parsing helpers for Yandex Direct v4 Live finance commands."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import math
import re

import click

_MONEY_RE = re.compile(r"^(?:0|[1-9]\d*)(?:\.\d{1,2})?$")


def parse_v4_money_sum(value: str) -> float:
    """Parse a positive human-readable money amount for v4 ``Sum`` fields."""
    normalized = (value or "").strip()
    if not _MONEY_RE.fullmatch(normalized):
        raise click.UsageError(
            "--amount must be a positive decimal amount, for example 100.50"
        )

    try:
        amount = Decimal(normalized)
    except InvalidOperation as exc:
        raise click.UsageError(
            "--amount must be a positive decimal amount, for example 100.50"
        ) from exc

    if amount <= 0:
        raise click.UsageError("--amount must be greater than zero")

    result = float(amount)
    if not math.isfinite(result):
        raise click.UsageError("--amount must be a finite decimal amount")
    return result
