"""Yandex Direct v4 Live finance commands."""

import re
from typing import Any, Optional

import click

from ..api import create_v4_client
from ..output import format_output, print_error
from ..utils import parse_csv_strings, parse_ids
from ..v4 import build_v4_body, call_v4
from ..v4.money import build_finance_token, parse_v4_money_sum, validate_operation_num
from ..v4_contracts import v4_method_contract
from .v4shells import V4_EPILOG

FINANCE_TOKEN_MASK = "<redacted>"
CUSTOM_TRANSACTION_ID_RE = re.compile(r"[A-Za-z0-9]{32}")
V4_FINANCE_CURRENCIES = ["RUB", "USD", "EUR", "BYN", "KZT", "TRY", "UAH", "CHF"]
V4_PAY_METHODS = ["Bank", "Overdraft"]
FINANCE_HELP_EPILOG = (
    "To issue a master token in the Yandex Direct UI, open Tools -> API -> "
    "Financial operations, enable the 'Allow financial operations' checkbox, "
    "click Save, then issue the master token on the same Financial operations "
    "page and confirm by SMS.\n\n"
    f"{V4_EPILOG}"
)


def _logins_param(logins: str) -> list[str]:
    """Build the v4 Live login list parameter."""
    login_list = parse_csv_strings(logins)
    if not login_list:
        raise click.UsageError("--logins must not be empty")
    return login_list


def _invoice_payments_param(payments: tuple[str, ...], currency: str) -> dict:
    """Build the v4 Live CreateInvoice payment object parameter."""
    if not payments:
        raise click.UsageError("--payment is required")

    parsed_payments = []
    seen_campaign_ids = set()
    normalized_currency = currency.upper()
    for payment in payments:
        spec = (payment or "").strip()
        if "=" not in spec:
            raise click.UsageError("--payment must use CAMPAIGN_ID=AMOUNT")
        campaign_id_text, amount_text = spec.split("=", 1)
        campaign_id_text = campaign_id_text.strip()
        amount_text = amount_text.strip()
        try:
            campaign_id = int(campaign_id_text)
        except ValueError as exc:
            raise click.UsageError(
                "--payment campaign ID must be a positive integer"
            ) from exc
        if campaign_id <= 0:
            raise click.UsageError("--payment campaign ID must be a positive integer")
        if campaign_id in seen_campaign_ids:
            raise click.UsageError("--payment campaign IDs must be unique")
        seen_campaign_ids.add(campaign_id)
        parsed_payments.append(
            {
                "CampaignID": campaign_id,
                "Sum": parse_v4_money_sum(amount_text),
                "Currency": normalized_currency,
            }
        )

    return {"Payments": parsed_payments}


def _finance_credentials(
    finance_token: Optional[str],
    master_token: Optional[str],
    operation_num: Optional[int],
    finance_login: Optional[str],
    method: str,
    fallback_login: Optional[str],
) -> tuple[str, int]:
    """Validate and normalize finance credentials before any v4 Live API call."""
    normalized_token = (finance_token or "").strip()
    normalized_master_token = (master_token or "").strip()
    if normalized_token and normalized_master_token:
        raise click.UsageError("Use either --finance-token or --master-token, not both")
    if operation_num is None:
        raise click.UsageError(_FINANCE_CREDENTIALS_ERROR)
    operation_num = validate_operation_num(operation_num)
    if normalized_token:
        return normalized_token, operation_num
    if normalized_master_token:
        login = (finance_login or fallback_login or "").strip()
        if not login:
            raise click.UsageError(
                "Provide --finance-login or set YANDEX_DIRECT_FINANCE_LOGIN "
                "when using --master-token"
            )
        return (
            build_finance_token(normalized_master_token, operation_num, method, login),
            operation_num,
        )
    raise click.UsageError(_FINANCE_CREDENTIALS_ERROR)


_FINANCE_CREDENTIALS_ERROR = (
    "Provide --finance-token and --operation-num, or provide --master-token, "
    "--operation-num, and --finance-login"
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


def _campaign_ids_param(campaign_ids: str) -> list[int]:
    """Parse one or more campaign IDs."""
    try:
        parsed = parse_ids(campaign_ids)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc
    if not parsed:
        raise click.UsageError("--campaign-ids must not be empty")
    if any(campaign_id <= 0 for campaign_id in parsed):
        raise click.UsageError("--campaign-ids must contain only positive integers")
    return parsed


def _custom_transaction_id_param(custom_transaction_id: str) -> dict:
    """Build the v4 Live CheckPayment parameter."""
    normalized = (custom_transaction_id or "").strip()
    if not CUSTOM_TRANSACTION_ID_RE.fullmatch(normalized):
        raise click.UsageError(
            "--custom-transaction-id must be exactly 32 latin letters or digits"
        )
    return {"CustomTransactionID": normalized}


@click.group(epilog=FINANCE_HELP_EPILOG)
def v4finance():
    """Yandex Direct v4 Live finance commands."""


@v4_method_contract("GetClientsUnits")
@v4finance.command(name="get-clients-units")
@click.option("--logins", required=True, help="Comma-separated client logins")
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
def get_clients_units(ctx, logins, output_format, output, dry_run):
    """Get available API units for clients."""
    login_list = _logins_param(logins)

    if dry_run:
        format_output(build_v4_body("GetClientsUnits", login_list), "json", None)
        return

    try:
        client = create_v4_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            profile=ctx.obj.get("profile"),
            sandbox=ctx.obj.get("sandbox"),
        )
        data = call_v4(client, "GetClientsUnits", login_list)
        format_output(data, output_format, output)
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@v4_method_contract("GetCreditLimits")
@v4finance.command(name="get-credit-limits")
@click.option("--logins", required=True, help="Comma-separated client logins")
@click.option(
    "--finance-token",
    envvar="YANDEX_DIRECT_FINANCE_TOKEN",
    help="Precomputed financial token for this method",
)
@click.option(
    "--master-token",
    envvar="YANDEX_DIRECT_MASTER_TOKEN",
    help=(
        "Financial master token issued after enabling and saving financial "
        "operations in Tools -> API -> Financial operations"
    ),
)
@click.option(
    "--operation-num",
    type=click.IntRange(min=1, max=9223372036854775807),
    envvar="YANDEX_DIRECT_OPERATION_NUM",
    help="Financial operation number",
)
@click.option(
    "--finance-login",
    envvar="YANDEX_DIRECT_FINANCE_LOGIN",
    help="Login used in financial token generation",
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
    master_token,
    operation_num,
    finance_login,
    output_format,
    output,
    dry_run,
):
    """Get client credit limits."""
    login_list = _logins_param(logins)
    finance_token, operation_num = _finance_credentials(
        finance_token,
        master_token,
        operation_num,
        finance_login,
        "GetCreditLimits",
        ctx.obj.get("login"),
    )

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


@v4_method_contract("CheckPayment")
@v4finance.command(name="check-payment")
@click.option(
    "--custom-transaction-id",
    required=True,
    help="32-character latin alphanumeric transaction ID",
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
def check_payment(
    ctx,
    custom_transaction_id,
    output_format,
    output,
    dry_run,
):
    """Check a v4 Live payment transaction."""
    param = _custom_transaction_id_param(custom_transaction_id)
    if dry_run:
        format_output(build_v4_body("CheckPayment", param), "json", None)
        return

    try:
        client = create_v4_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            profile=ctx.obj.get("profile"),
            sandbox=ctx.obj.get("sandbox"),
        )
        data = call_v4(client, "CheckPayment", param)
        format_output(data, output_format, output)
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@v4_method_contract("CreateInvoice")
@v4finance.command(name="create-invoice")
@click.option(
    "--payment",
    "payments",
    multiple=True,
    required=True,
    help="Invoice payment as CAMPAIGN_ID=AMOUNT; repeat for multiple campaigns",
)
@click.option(
    "--currency",
    default="RUB",
    show_default=True,
    type=click.Choice(V4_FINANCE_CURRENCIES, case_sensitive=False),
    help="Payment currency",
)
@click.option(
    "--finance-token",
    envvar="YANDEX_DIRECT_FINANCE_TOKEN",
    help="Precomputed financial token for this method",
)
@click.option(
    "--master-token",
    envvar="YANDEX_DIRECT_MASTER_TOKEN",
    help=(
        "Financial master token issued after enabling and saving financial "
        "operations in Tools -> API -> Financial operations"
    ),
)
@click.option(
    "--operation-num",
    type=click.IntRange(min=1, max=9223372036854775807),
    envvar="YANDEX_DIRECT_OPERATION_NUM",
    help="Financial operation number",
)
@click.option(
    "--finance-login",
    envvar="YANDEX_DIRECT_FINANCE_LOGIN",
    help="Login used in financial token generation",
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
def create_invoice(
    ctx,
    payments,
    currency,
    finance_token,
    master_token,
    operation_num,
    finance_login,
    output_format,
    output,
    dry_run,
):
    """Create a payment invoice for campaigns."""
    finance_token, operation_num = _finance_credentials(
        finance_token,
        master_token,
        operation_num,
        finance_login,
        "CreateInvoice",
        ctx.obj.get("login"),
    )
    param = _invoice_payments_param(payments, currency)

    if dry_run:
        format_output(
            _masked_finance_body("CreateInvoice", param, operation_num),
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
        data = call_v4(client, "CreateInvoice", param)
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
    "--currency",
    default="RUB",
    show_default=True,
    type=click.Choice(V4_FINANCE_CURRENCIES, case_sensitive=False),
    help="Payment currency",
)
@click.option(
    "--finance-token",
    envvar="YANDEX_DIRECT_FINANCE_TOKEN",
    help="Precomputed financial token for this method",
)
@click.option(
    "--master-token",
    envvar="YANDEX_DIRECT_MASTER_TOKEN",
    help=(
        "Financial master token issued after enabling and saving financial "
        "operations in Tools -> API -> Financial operations"
    ),
)
@click.option(
    "--operation-num",
    type=click.IntRange(min=1, max=9223372036854775807),
    envvar="YANDEX_DIRECT_OPERATION_NUM",
    help="Financial operation number",
)
@click.option(
    "--finance-login",
    envvar="YANDEX_DIRECT_FINANCE_LOGIN",
    help="Login used in financial token generation",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show request without sending; required for this command",
)
@click.pass_context
def transfer_money(
    ctx,
    from_campaign_id,
    to_campaign_id,
    amount,
    currency,
    finance_token,
    master_token,
    operation_num,
    finance_login,
    dry_run,
):
    """Preview transferring funds between campaigns."""
    _require_dry_run(dry_run)
    _, operation_num = _finance_credentials(
        finance_token,
        master_token,
        operation_num,
        finance_login,
        "TransferMoney",
        ctx.obj.get("login"),
    )
    parsed_amount = parse_v4_money_sum(amount)
    currency = currency.upper()
    param = {
        "FromCampaigns": [
            {
                "CampaignID": from_campaign_id,
                "Sum": parsed_amount,
                "Currency": currency,
            },
        ],
        "ToCampaigns": [
            {
                "CampaignID": to_campaign_id,
                "Sum": parsed_amount,
                "Currency": currency,
            },
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
    "--campaign-ids",
    required=True,
    help="Comma-separated campaign IDs to pay",
)
@click.option("--amount", required=True, help="Positive amount, for example 100.50")
@click.option(
    "--currency",
    default="RUB",
    show_default=True,
    type=click.Choice(V4_FINANCE_CURRENCIES, case_sensitive=False),
    help="Payment currency",
)
@click.option("--contract-id", help="Agency contract ID; required for Bank")
@click.option(
    "--pay-method",
    required=True,
    type=click.Choice(V4_PAY_METHODS, case_sensitive=False),
    help="Payment method",
)
@click.option(
    "--finance-token",
    envvar="YANDEX_DIRECT_FINANCE_TOKEN",
    help="Precomputed financial token for this method",
)
@click.option(
    "--master-token",
    envvar="YANDEX_DIRECT_MASTER_TOKEN",
    help=(
        "Financial master token issued after enabling and saving financial "
        "operations in Tools -> API -> Financial operations"
    ),
)
@click.option(
    "--operation-num",
    type=click.IntRange(min=1, max=9223372036854775807),
    envvar="YANDEX_DIRECT_OPERATION_NUM",
    help="Financial operation number",
)
@click.option(
    "--finance-login",
    envvar="YANDEX_DIRECT_FINANCE_LOGIN",
    help="Login used in financial token generation",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show request without sending; required for this command",
)
@click.pass_context
def pay_campaigns(
    ctx,
    campaign_ids,
    amount,
    currency,
    contract_id,
    pay_method,
    finance_token,
    master_token,
    operation_num,
    finance_login,
    dry_run,
):
    """Preview paying for a campaign from an agency credit limit."""
    _require_dry_run(dry_run)
    _, operation_num = _finance_credentials(
        finance_token,
        master_token,
        operation_num,
        finance_login,
        "PayCampaigns",
        ctx.obj.get("login"),
    )
    parsed_amount = parse_v4_money_sum(amount)
    parsed_campaign_ids = _campaign_ids_param(campaign_ids)
    currency = currency.upper()
    pay_method = _non_empty_option(pay_method, "--pay-method")
    contract_id = (contract_id or "").strip()
    if pay_method == "Bank" and not contract_id:
        raise click.UsageError("--contract-id is required when --pay-method Bank")
    param = {
        "Payments": [
            {"CampaignID": campaign_id, "Sum": parsed_amount, "Currency": currency}
            for campaign_id in parsed_campaign_ids
        ],
        "PayMethod": pay_method,
    }
    if contract_id:
        param["ContractID"] = contract_id

    format_output(
        _masked_finance_body("PayCampaigns", param, operation_num),
        "json",
        None,
    )
