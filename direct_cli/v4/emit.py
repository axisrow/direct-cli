"""Shared v4 Live request emit-helpers.

Centralizes the ``create_v4_client → call_v4 → format_output`` boilerplate (plus
the dry-run preview branch) that every v4 command otherwise duplicates. Two
variants: the plain :func:`emit_or_call_v4` and the finance-backed
:func:`emit_or_call_v4_finance`, which threads the finance token / operation
number and masks the token in dry-run output.
"""

from typing import Any, Optional

import click

from ..api import create_v4_client
from ..output import format_output, handle_api_errors
from . import build_v4_body, call_v4

# Placeholder shown instead of the real finance token in dry-run previews.
FINANCE_TOKEN_MASK = "<redacted>"


def _masked_finance_body(method: str, param: Any, operation_num: int) -> dict:
    """Build a dry-run body without exposing the financial token."""
    body = build_v4_body(method, param)
    body["finance_token"] = FINANCE_TOKEN_MASK
    body["operation_num"] = operation_num
    return body


@handle_api_errors
def emit_or_call_v4(
    ctx: click.Context,
    method: str,
    param: Any,
    dry_run: bool,
    output_format: str,
    output: Optional[str],
) -> None:
    """Print a v4 request preview or execute it against the sandbox API."""
    if dry_run:
        format_output(build_v4_body(method, param), "json", None)
        return

    client = create_v4_client(
        token=ctx.obj.get("token"),
        login=ctx.obj.get("login"),
        profile=ctx.obj.get("profile"),
        sandbox=ctx.obj.get("sandbox"),
    )
    data = call_v4(client, method, param)
    format_output(data, output_format, output)


@handle_api_errors
def emit_or_call_v4_finance(
    ctx: click.Context,
    method: str,
    param: Any,
    finance_token: str,
    operation_num: int,
    dry_run: bool,
    output_format: str,
    output: Optional[str],
) -> None:
    """Preview a finance-backed v4 request or execute it; masks the token."""
    if dry_run:
        format_output(_masked_finance_body(method, param, operation_num), "json", None)
        return

    client = create_v4_client(
        token=ctx.obj.get("token"),
        login=ctx.obj.get("login"),
        profile=ctx.obj.get("profile"),
        sandbox=ctx.obj.get("sandbox"),
        finance_token=finance_token,
        operation_num=operation_num,
    )
    data = call_v4(client, method, param)
    format_output(data, output_format, output)
