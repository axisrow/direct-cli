"""Money parsing helpers for Yandex Direct v4 Live finance commands."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import math
import re

import click

_MONEY_RE = re.compile(r"^(?:0|[1-9]\d*)(?:\.\d{1,2})?$")
MAX_OPERATION_NUM = 9223372036854775807


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


def normalize_finance_login(login: str) -> str:
    """Normalize a Yandex login before financial token generation."""
    normalized = (login or "").strip().lower()
    if not normalized:
        raise click.UsageError("--finance-login must not be empty")
    return normalized


def validate_operation_num(operation_num: int) -> int:
    """Validate the v4 Live finance operation counter."""
    if operation_num < 1 or operation_num > MAX_OPERATION_NUM:
        raise click.UsageError(
            "--operation-num must be between 1 and 9223372036854775807"
        )
    return operation_num


def build_finance_token(
    master_token: str,
    operation_num: int,
    method: str,
    login: str,
) -> str:
    """Build a v4 Live finance token from the master token and operation data."""
    normalized_master_token = (master_token or "").strip()
    if not normalized_master_token:
        raise click.UsageError("--master-token must not be empty")
    normalized_operation_num = validate_operation_num(operation_num)
    normalized_method = (method or "").strip()
    if not normalized_method:
        raise click.UsageError("finance method must not be empty")
    normalized_login = normalize_finance_login(login)
    payload = (
        f"{normalized_master_token}"
        f"{normalized_operation_num}"
        f"{normalized_method}"
        f"{normalized_login}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
