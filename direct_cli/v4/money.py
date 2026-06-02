"""Money parsing helpers for Yandex Direct v4 Live finance commands."""

from __future__ import annotations

import hashlib

import click

from ..utils import parse_positive_decimal_amount

MAX_OPERATION_NUM = 9223372036854775807


def parse_v4_money_sum(value: str, option_name: str = "--amount") -> float:
    """Parse a positive API-native decimal amount for v4 ``Sum`` fields.

    v4 ``Sum`` fields allow at most two fractional digits, so this delegates to
    the shared :func:`direct_cli.utils.parse_positive_decimal_amount` with
    ``max_decimals=2``. ``option_name`` controls the CLI flag label that appears
    in error messages so callers (e.g. ``--payment ACCOUNT_ID=AMOUNT`` parsers)
    get a diagnostic that names the flag the user actually typed.
    """
    return parse_positive_decimal_amount(value, option_name, max_decimals=2)


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
