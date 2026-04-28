"""Yandex Direct v4 Live finance commands."""

from typing import Any, Optional

import click

from ..api import create_v4_client
from ..output import format_output, print_error
from ..utils import parse_csv_strings
from ..v4 import build_v4_body, call_v4
from ..v4.money import parse_v4_money_sum
from ..v4_contracts import v4_method_contract
from .v4shells import V4_EPILOG

FINANCE_TOKEN_MASK = "<redacted>"


def _logins_param(logins: str) -> list[str]:
    """Build the v4 Live login list parameter."""
    login_list = parse_csv_strings(logins)
    if not login_list:
        raise click.UsageError("--logins must not be empty")
    return login_list


def _finance_credentials(
    finance_token: Optional[str],
    operation_num: Optional[int],
) -> tuple[str, int]:
    """Validate and normalize finance credentials before any v4 Live API call."""
    normalized_token = (finance_token or "").strip()
    if normalized_token and operation_num is not None:
        return normalized_token, operation_num
    raise click.UsageError(_FINANCE_CREDENTIALS_ERROR)


_FINANCE_CREDENTIALS_ERROR = (
    "Provide --finance-token and --operation-num, or set "
    "YANDEX_DIRECT_FINANCE_TOKEN and YANDEX_DIRECT_OPERATION_NUM"
)


def _masked_finance_body(method: str, param: Any, operation_num: int) -> dict:
    """Build a dry-run body without exposing the financial token."""
    body = build_v4_body(method, param)
    body["finance_token"] = FINANCE_TOKEN_MASK
    body["operation_num"] = operation_num
    return body


def _require_dry_run(dry_run: bool) -> None:
    """Reject v4 finance money mutations unless dry-run is explicit."""
    if not dry_run:
        raise click.UsageError("--dry-run is required for v4finance money commands")


def _non_empty_option(value: str, option_name: str) -> str:
    """Normalize a required string option."""
    normalized = (value or "").strip()
    if not normalized:
        raise click.UsageError(f"{option_name} must not be empty")
    return normalized


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
    finance_token, operation_num = _finance_credentials(finance_token, operation_num)

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


@v4_method_contract("TransferMoney")
@v4finance.command(name="transfer-money")
@click.option(
    "--from-campaign-id",
    required=True,
    type=click.IntRange(min=1),
    help="Source campaign ID",
)
@click.option(
    "--to-campaign-id",
    required=True,
    type=click.IntRange(min=1),
    help="Destination campaign ID",
)
@click.option("--amount", required=True, help="Positive amount, for example 100.50")
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
    "--dry-run",
    is_flag=True,
    help="Show request without sending; required for this command",
)
def transfer_money(
    from_campaign_id,
    to_campaign_id,
    amount,
    finance_token,
    operation_num,
    dry_run,
):
    """Preview transferring funds between campaigns."""
    _require_dry_run(dry_run)
    _, operation_num = _finance_credentials(finance_token, operation_num)
    parsed_amount = parse_v4_money_sum(amount)
    param = {
        "FromCampaigns": [
            {"CampaignID": from_campaign_id, "Sum": parsed_amount},
        ],
        "ToCampaigns": [
            {"CampaignID": to_campaign_id, "Sum": parsed_amount},
        ],
    }

    format_output(
        _masked_finance_body("TransferMoney", param, operation_num),
        "json",
        None,
    )


@v4_method_contract("PayCampaigns")
@v4finance.command(name="pay-campaigns")
@click.option(
    "--campaign-id",
    required=True,
    type=click.IntRange(min=1),
    help="Campaign ID to pay",
)
@click.option("--amount", required=True, help="Positive amount, for example 100.50")
@click.option("--contract-id", required=True, help="Agency contract ID")
@click.option("--pay-method", required=True, help="Payment method")
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
    "--dry-run",
    is_flag=True,
    help="Show request without sending; required for this command",
)
def pay_campaigns(
    campaign_id,
    amount,
    contract_id,
    pay_method,
    finance_token,
    operation_num,
    dry_run,
):
    """Preview paying for a campaign from an agency credit limit."""
    _require_dry_run(dry_run)
    _, operation_num = _finance_credentials(finance_token, operation_num)
    parsed_amount = parse_v4_money_sum(amount)
    param = {
        "Payments": [
            {"CampaignID": campaign_id, "Sum": parsed_amount},
        ],
        "ContractID": _non_empty_option(contract_id, "--contract-id"),
        "PayMethod": _non_empty_option(pay_method, "--pay-method"),
    }

    format_output(
        _masked_finance_body("PayCampaigns", param, operation_num),
        "json",
        None,
    )
