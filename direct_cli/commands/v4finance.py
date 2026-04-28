"""Yandex Direct v4 Live finance commands."""

from typing import Optional

import click

from ..api import create_v4_client
from ..output import format_output, print_error
from ..utils import parse_csv_strings
from ..v4 import build_v4_body, call_v4
from ..v4_contracts import v4_method_contract
from .v4shells import V4_EPILOG

FINANCE_TOKEN_MASK = "<redacted>"


def _logins_param(logins: str) -> list[str]:
    """Build the v4 Live login list parameter."""
    login_list = parse_csv_strings(logins)
    if not login_list:
        raise click.UsageError("--logins must not be empty")
    return login_list


def _require_finance_credentials(
    finance_token: Optional[str],
    operation_num: Optional[int],
) -> None:
    """Validate finance credentials before any v4 Live API call."""
    if finance_token and operation_num is not None:
        return
    raise click.UsageError(
        "Provide --finance-token and --operation-num, or set "
        "YANDEX_DIRECT_FINANCE_TOKEN and YANDEX_DIRECT_OPERATION_NUM"
    )


def _masked_finance_body(method: str, param: list[str], operation_num: int) -> dict:
    """Build a dry-run body without exposing the financial token."""
    body = build_v4_body(method, param)
    body["finance_token"] = FINANCE_TOKEN_MASK
    body["operation_num"] = operation_num
    return body


@click.group(epilog=V4_EPILOG)
def v4finance():
    """Yandex Direct v4 Live finance commands."""


@v4_method_contract("GetCreditLimits")
@v4finance.command(name="get-credit-limits")
@click.option("--logins", required=True, help="Comma-separated client logins")
@click.option(
    "--finance-token",
    envvar="YANDEX_DIRECT_FINANCE_TOKEN",
    help="Financial token",
)
@click.option(
    "--operation-num",
    type=click.IntRange(min=0),
    envvar="YANDEX_DIRECT_OPERATION_NUM",
    help="Financial operation number",
)
@click.option(
    "--format",
    "output_format",
    default="json",
    type=click.Choice(["json", "table", "csv", "tsv"]),
    help="Output format",
)
@click.option("--output", help="Output file")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def get_credit_limits(
    ctx,
    logins,
    finance_token,
    operation_num,
    output_format,
    output,
    dry_run,
):
    """Get client credit limits."""
    login_list = _logins_param(logins)
    _require_finance_credentials(finance_token, operation_num)

    if dry_run:
        format_output(
            _masked_finance_body("GetCreditLimits", login_list, operation_num),
            "json",
            None,
        )
        return

    try:
        client = create_v4_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            profile=ctx.obj.get("profile"),
            sandbox=ctx.obj.get("sandbox"),
            finance_token=finance_token,
            operation_num=operation_num,
        )
        data = call_v4(client, "GetCreditLimits", login_list)
        format_output(data, output_format, output)
    except Exception as e:
        print_error(str(e))
        raise click.Abort()
