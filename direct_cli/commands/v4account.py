"""Yandex Direct v4 Live shared-account commands."""

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

import click

from ..api import create_v4_client
from ..i18n import t
from ..output import format_output, handle_api_errors
from ..utils import parse_csv_strings, parse_ids
from ..v4 import build_v4_body, call_v4
from ..v4.money import parse_v4_money_sum
from ..v4_contracts import v4_method_contract

# Cross-module helpers shared with v4finance commands. AccountManagement's
# financial sub-actions (Deposit/Invoice/TransferMoney) need the same
# finance_token / operation_num plumbing as v4finance methods.
from .v4finance import (  # noqa: E402
    _finance_credentials,
    _masked_finance_body,
)
from .v4shells import V4_EPILOG

YES_NO = ("Yes", "No")
SPEND_MODES = ("Default", "Stretched")
HH_MM_RE = re.compile(r"^(?:[01]\d|2[0-3]):(?:00|15|30|45)$")

V4_ACCOUNT_ACTIONS = ("Get", "Update", "Deposit", "Invoice", "TransferMoney")
V4_ACCOUNT_FINANCIAL_ACTIONS = frozenset({"Deposit", "Invoice", "TransferMoney"})
V4_ACCOUNT_CURRENCIES = (
    "RUB",
    "CHF",
    "EUR",
    "KZT",
    "TRY",
    "UAH",
    "USD",
    "BYN",
)
V4_ACCOUNT_ORIGINS = ("Overdraft",)

_COMMON_PARAMS = frozenset({"action", "dry_run", "output_format", "output"})
_FINANCE_PARAMS = frozenset(
    {"finance_token", "master_token", "operation_num", "finance_login"}
)
_UPDATE_PARAMS = frozenset(
    {
        "account_id",
        "day_budget",
        "spend_mode",
        "money_in_sms",
        "money_out_sms",
        "paused_by_day_budget_sms",
        "sms_time_from",
        "sms_time_to",
        "email",
        "money_warning_value",
        "paused_by_day_budget",
    }
)
_GET_PARAMS = frozenset({"logins", "account_ids"})
_DEPOSIT_PARAMS = frozenset(
    {"payments", "currency", "origin", "contract"} | _FINANCE_PARAMS
)
_INVOICE_PARAMS = frozenset({"payments", "currency"} | _FINANCE_PARAMS)
_TRANSFER_PARAMS = frozenset(
    {"from_account_id", "to_account_id", "amount", "currency"} | _FINANCE_PARAMS
)

_ACCOUNT_ACTION_ALLOWED_FLAGS: dict[str, frozenset[str]] = {
    "Get": _GET_PARAMS,
    "Update": _UPDATE_PARAMS,
    "Deposit": _DEPOSIT_PARAMS,
    "Invoice": _INVOICE_PARAMS,
    "TransferMoney": _TRANSFER_PARAMS,
}

_PARAM_TO_FLAG = {
    "account_id": "--account-id",
    "day_budget": "--day-budget",
    "spend_mode": "--spend-mode",
    "money_in_sms": "--money-in-sms",
    "money_out_sms": "--money-out-sms",
    "paused_by_day_budget_sms": "--paused-by-day-budget-sms",
    "sms_time_from": "--sms-time-from",
    "sms_time_to": "--sms-time-to",
    "email": "--email",
    "money_warning_value": "--money-warning-value",
    "paused_by_day_budget": "--paused-by-day-budget",
    "logins": "--logins",
    "account_ids": "--account-ids",
    "payments": "--payment",
    "currency": "--currency",
    "origin": "--origin",
    "contract": "--contract",
    "from_account_id": "--from-account-id",
    "to_account_id": "--to-account-id",
    "amount": "--amount",
    "finance_token": "--finance-token",
    "master_token": "--master-token",
    "operation_num": "--operation-num",
    "finance_login": "--finance-login",
}


@click.group(epilog=V4_EPILOG)
def v4account():
    """Yandex Direct v4 Live account commands."""


def _require_dry_run_or_sandbox(dry_run: bool, sandbox: bool) -> None:
    """Reject shared-account mutations outside explicit dry-run or sandbox."""
    if not dry_run and not sandbox:
        raise click.UsageError(t("--dry-run is required unless --sandbox is set"))


@handle_api_errors
def _emit_or_call_v4(
    ctx: click.Context,
    method: str,
    param: dict,
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
def _emit_or_call_v4_finance(
    ctx: click.Context,
    method: str,
    param: dict,
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


def _non_empty(value: str, option_name: str) -> str:
    """Normalize a required string option."""
    normalized = (value or "").strip()
    if not normalized:
        raise click.UsageError(
            t("{option_name} must not be empty").format(option_name=option_name)
        )
    return normalized


def _parse_day_budget(value: Optional[str]) -> Optional[float]:
    """Parse a non-negative v4 shared-account budget amount."""
    if value is None:
        return None
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise click.UsageError(t("--day-budget must be a non-negative amount")) from exc
    if not amount.is_finite() or amount < 0 or (amount == 0 and amount.is_signed()):
        raise click.UsageError(t("--day-budget must be a non-negative amount"))
    return float(amount)


def _parse_hh_mm(value: Optional[str], option_name: str) -> Optional[str]:
    """Validate v4 SMS notification time."""
    if value is None:
        return None
    if not HH_MM_RE.match(value):
        raise click.UsageError(
            t("{option_name} must use HH:MM with minutes 00, 15, 30, or 45").format(
                option_name=option_name
            )
        )
    return value


def _validate_action(action: str) -> str:
    """Normalize the v4 Live AccountManagement Action enum."""
    normalized = (action or "").strip()
    if normalized not in V4_ACCOUNT_ACTIONS:
        raise click.UsageError(
            t("--action must be one of: {arg0}").format(
                arg0=", ".join(V4_ACCOUNT_ACTIONS)
            )
        )
    return normalized


def _flag_supplied(ctx: click.Context, name: str, value: Any) -> bool:
    """Detect whether an action-specific Click parameter was supplied by the user.

    Values sourced from envvars or defaults are NOT counted as "supplied" —
    only ones the user typed on the command line. This lets users keep
    ``YANDEX_DIRECT_FINANCE_TOKEN`` & friends exported in their shell while
    still running ``--action Get`` / ``--action Update`` without spurious
    "flag not valid for action" errors.
    """
    if value is None:
        return False
    if isinstance(value, tuple) and len(value) == 0:
        return False
    source = ctx.get_parameter_source(name)
    return source == click.core.ParameterSource.COMMANDLINE


def _reject_disallowed_flags(
    ctx: click.Context, action: str, supplied: dict[str, Any]
) -> None:
    """Fail fast when a flag is set that does not apply to the chosen Action."""
    allowed = _ACCOUNT_ACTION_ALLOWED_FLAGS[action] | _COMMON_PARAMS
    offenders = sorted(
        _PARAM_TO_FLAG.get(name, f"--{name.replace('_', '-')}")
        for name, value in supplied.items()
        if name not in allowed and _flag_supplied(ctx, name, value)
    )
    if offenders:
        valid_flags = sorted(
            _PARAM_TO_FLAG[name] for name in allowed if name in _PARAM_TO_FLAG
        )
        raise click.UsageError(
            t(
                "{arg0} not valid for --action {action}. Valid flags for {action}: {arg1}"
            ).format(
                arg0=", ".join(offenders), action=action, arg1=", ".join(valid_flags)
            )
        )


def _account_selection_criteria(
    logins: Optional[str], account_ids: Optional[str]
) -> Optional[dict]:
    """Build the Get SelectionCriteria object; None when no filter is provided."""
    parsed_logins = parse_csv_strings(logins)
    if logins is not None and not parsed_logins:
        raise click.UsageError(t("--logins must not be empty when provided"))

    if account_ids is not None:
        try:
            parsed_ids = parse_ids(account_ids)
        except ValueError as exc:
            raise click.UsageError(str(exc)) from exc
        if not parsed_ids:
            raise click.UsageError(t("--account-ids must not be empty when provided"))
        if any(account_id <= 0 for account_id in parsed_ids):
            raise click.UsageError(
                t("--account-ids must contain only positive integers")
            )
    else:
        parsed_ids = None

    if parsed_logins and len(parsed_logins) > 50:
        raise click.UsageError(t("--logins accepts at most 50 entries"))
    if parsed_ids and len(parsed_ids) > 100:
        raise click.UsageError(t("--account-ids accepts at most 100 entries"))

    criteria: dict = {}
    if parsed_logins:
        criteria["Logins"] = parsed_logins
    if parsed_ids:
        criteria["AccountIDS"] = parsed_ids
    return criteria or None


def _account_get_param(logins: Optional[str], account_ids: Optional[str]) -> dict:
    """Build the Get param object."""
    criteria = _account_selection_criteria(logins, account_ids)
    param: dict = {"Action": "Get"}
    if criteria is not None:
        param["SelectionCriteria"] = criteria
    return param


def _account_update_param(
    action: str,
    account_id: Optional[int],
    day_budget: Optional[str],
    spend_mode: Optional[str],
    money_in_sms: Optional[str],
    money_out_sms: Optional[str],
    paused_by_day_budget_sms: Optional[str],
    sms_time_from: Optional[str],
    sms_time_to: Optional[str],
    email: Optional[str],
    money_warning_value: Optional[int],
    paused_by_day_budget: Optional[str],
) -> dict:
    """Build the AccountManagement Update parameter object."""
    if account_id is None:
        raise click.UsageError(t("--account-id is required for --action Update"))
    account: dict = {"AccountID": account_id}

    parsed_day_budget = _parse_day_budget(day_budget)
    if parsed_day_budget is not None or spend_mode is not None:
        if parsed_day_budget is None or spend_mode is None:
            raise click.UsageError(
                t("--day-budget and --spend-mode must be provided together")
            )
        account["AccountDayBudget"] = {
            "Amount": parsed_day_budget,
            "SpendMode": spend_mode,
        }

    sms_notification: dict = {}
    if money_in_sms is not None:
        sms_notification["MoneyInSms"] = money_in_sms
    if money_out_sms is not None:
        sms_notification["MoneyOutSms"] = money_out_sms
    if paused_by_day_budget_sms is not None:
        sms_notification["PausedByDayBudgetSms"] = paused_by_day_budget_sms
    if (sms_time_from is None) != (sms_time_to is None):
        raise click.UsageError(
            t("--sms-time-from and --sms-time-to must be provided together")
        )
    if sms_time_from is not None:
        sms_notification["SmsTimeFrom"] = _parse_hh_mm(sms_time_from, "--sms-time-from")
    if sms_time_to is not None:
        sms_notification["SmsTimeTo"] = _parse_hh_mm(sms_time_to, "--sms-time-to")
    if sms_notification:
        account["SmsNotification"] = sms_notification

    email_notification: dict = {}
    if email is not None:
        email_notification["Email"] = _non_empty(email, "--email")
    if money_warning_value is not None:
        email_notification["MoneyWarningValue"] = money_warning_value
    if paused_by_day_budget is not None:
        email_notification["PausedByDayBudget"] = paused_by_day_budget
    if email_notification:
        account["EmailNotification"] = email_notification

    if len(account) == 1:
        raise click.UsageError(t("Provide at least one update field"))

    return {"Action": action, "Accounts": [account]}


def _parse_account_payments(payments: tuple[str, ...], currency: str) -> list[dict]:
    """Parse repeated --payment ACCOUNT_ID=AMOUNT into PayCampElement-shaped items."""
    if not payments:
        raise click.UsageError(t("--payment is required"))
    if len(payments) > 50:
        raise click.UsageError(t("--payment accepts at most 50 entries per call"))

    normalized_currency = currency.upper()
    parsed_items: list[dict] = []
    seen_account_ids: set[int] = set()
    for entry in payments:
        spec = (entry or "").strip()
        if "=" not in spec:
            raise click.UsageError(t("--payment must use ACCOUNT_ID=AMOUNT"))
        account_id_text, amount_text = spec.split("=", 1)
        account_id_text = account_id_text.strip()
        amount_text = amount_text.strip()
        try:
            account_id = int(account_id_text)
        except ValueError as exc:
            raise click.UsageError(
                t("--payment account ID must be a positive integer")
            ) from exc
        if account_id <= 0:
            raise click.UsageError(t("--payment account ID must be a positive integer"))
        if account_id in seen_account_ids:
            raise click.UsageError(t("--payment account IDs must be unique"))
        seen_account_ids.add(account_id)
        parsed_items.append(
            {
                "AccountID": account_id,
                "Amount": parse_v4_money_sum(amount_text, option_name="--payment"),
                "Currency": normalized_currency,
            }
        )

    return parsed_items


def _account_deposit_param(
    payments: tuple[str, ...],
    currency: str,
    origin: Optional[str],
    contract: Optional[str],
) -> dict:
    """Build the Deposit param object."""
    items = _parse_account_payments(payments, currency)
    contract_clean = (contract or "").strip()
    if origin is not None:
        for item in items:
            item["Origin"] = origin
    if contract_clean:
        for item in items:
            item["Contract"] = contract_clean
    return {"Action": "Deposit", "Payments": items}


def _account_invoice_param(payments: tuple[str, ...], currency: str) -> dict:
    """Build the Invoice param object."""
    return {
        "Action": "Invoice",
        "Payments": _parse_account_payments(payments, currency),
    }


def _account_transfer_param(
    from_account_id: int,
    to_account_id: int,
    amount: str,
    currency: str,
) -> dict:
    """Build the TransferMoney param object (single transfer per call)."""
    if from_account_id == to_account_id:
        raise click.UsageError(t("--from-account-id and --to-account-id must differ"))
    return {
        "Action": "TransferMoney",
        "Transfers": [
            {
                "FromAccountID": from_account_id,
                "ToAccountID": to_account_id,
                "Amount": parse_v4_money_sum(amount),
                "Currency": currency.upper(),
            }
        ],
    }


@v4_method_contract("EnableSharedAccount")
@v4account.command(name="enable-shared-account")
@click.option(
    "--client-login",
    required=True,
    help="Client login to enable the shared account for",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show request without sending; required outside --sandbox",
)
@click.option(
    "--format",
    "output_format",
    default="json",
    type=click.Choice(["json", "table", "csv", "tsv"]),
    help="Output format",
)
@click.option("--output", help="Output file")
@click.pass_context
def enable_shared_account(ctx, client_login, dry_run, output_format, output):
    """Enable a shared account for a client in sandbox, or preview the request."""
    _require_dry_run_or_sandbox(dry_run, ctx.obj.get("sandbox"))
    param = {"Login": _non_empty(client_login, "--client-login")}
    _emit_or_call_v4(
        ctx,
        "EnableSharedAccount",
        param,
        dry_run,
        output_format,
        output,
    )


@v4_method_contract("AccountManagement")
@v4account.command(name="account-management")
@click.option(
    "--action",
    required=True,
    help="AccountManagement action: Get / Update / Deposit / Invoice / TransferMoney",
)
@click.option("--logins", help="Comma-separated client logins (Get only)")
@click.option(
    "--account-ids",
    help="Comma-separated shared account IDs (Get only)",
)
@click.option(
    "--account-id",
    type=click.IntRange(min=1),
    help="Shared account ID (Update only)",
)
@click.option("--day-budget", help="Shared account daily budget (Update only)")
@click.option(
    "--spend-mode",
    type=click.Choice(SPEND_MODES),
    help="Budget spend mode (Update only)",
)
@click.option(
    "--money-in-sms",
    type=click.Choice(YES_NO),
    help="Enable money-in SMS (Update only)",
)
@click.option(
    "--money-out-sms",
    type=click.Choice(YES_NO),
    help="Enable money-out SMS (Update only)",
)
@click.option(
    "--paused-by-day-budget-sms",
    type=click.Choice(YES_NO),
    help="Enable day-budget pause SMS (Update only)",
)
@click.option(
    "--sms-time-from", help="SMS notification start time, HH:MM (Update only)"
)
@click.option("--sms-time-to", help="SMS notification end time, HH:MM (Update only)")
@click.option("--email", help="Notification email (Update only)")
@click.option(
    "--money-warning-value",
    type=click.IntRange(min=0),
    help="Balance warning percentage (Update only)",
)
@click.option(
    "--paused-by-day-budget",
    type=click.Choice(YES_NO),
    help="Enable day-budget pause email (Update only)",
)
@click.option(
    "--payment",
    "payments",
    multiple=True,
    help=(
        "Payment as ACCOUNT_ID=AMOUNT; repeat for multiple accounts (Deposit / Invoice)"
    ),
)
@click.option(
    "--currency",
    type=click.Choice(V4_ACCOUNT_CURRENCIES, case_sensitive=False),
    help="Payment currency (Deposit / Invoice / TransferMoney)",
)
@click.option(
    "--origin",
    type=click.Choice(V4_ACCOUNT_ORIGINS),
    help="Funding origin (Deposit only)",
)
@click.option("--contract", help="Contract number (Deposit only)")
@click.option(
    "--from-account-id",
    type=click.IntRange(min=1),
    help="Source account ID (TransferMoney only)",
)
@click.option(
    "--to-account-id",
    type=click.IntRange(min=1),
    help="Destination account ID (TransferMoney only)",
)
@click.option("--amount", help="Positive amount, e.g. 100.50 (TransferMoney only)")
@click.option(
    "--finance-token",
    envvar="YANDEX_DIRECT_FINANCE_TOKEN",
    help="Precomputed financial token (Deposit / Invoice / TransferMoney)",
)
@click.option(
    "--master-token",
    envvar="YANDEX_DIRECT_MASTER_TOKEN",
    help=(
        "Financial master token; computes the per-request token from "
        "operation_num + method + login (Deposit / Invoice / TransferMoney)"
    ),
)
@click.option(
    "--operation-num",
    type=click.IntRange(min=1, max=9223372036854775807),
    envvar="YANDEX_DIRECT_OPERATION_NUM",
    help="Financial operation number (Deposit / Invoice / TransferMoney)",
)
@click.option(
    "--finance-login",
    envvar="YANDEX_DIRECT_FINANCE_LOGIN",
    help="Login used in financial token generation",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show request without sending; required outside --sandbox",
)
@click.option(
    "--format",
    "output_format",
    default="json",
    type=click.Choice(["json", "table", "csv", "tsv"]),
    help="Output format",
)
@click.option("--output", help="Output file")
@click.pass_context
def account_management(
    ctx,
    action,
    logins,
    account_ids,
    account_id,
    day_budget,
    spend_mode,
    money_in_sms,
    money_out_sms,
    paused_by_day_budget_sms,
    sms_time_from,
    sms_time_to,
    email,
    money_warning_value,
    paused_by_day_budget,
    payments,
    currency,
    origin,
    contract,
    from_account_id,
    to_account_id,
    amount,
    finance_token,
    master_token,
    operation_num,
    finance_login,
    dry_run,
    output_format,
    output,
):
    """Manage shared accounts: Get / Update / Deposit / Invoice / TransferMoney.

    ⚠ Finance actions (Deposit / Invoice / TransferMoney) not tested against
    the live API.
    """
    action = _validate_action(action)

    supplied = {
        "logins": logins,
        "account_ids": account_ids,
        "account_id": account_id,
        "day_budget": day_budget,
        "spend_mode": spend_mode,
        "money_in_sms": money_in_sms,
        "money_out_sms": money_out_sms,
        "paused_by_day_budget_sms": paused_by_day_budget_sms,
        "sms_time_from": sms_time_from,
        "sms_time_to": sms_time_to,
        "email": email,
        "money_warning_value": money_warning_value,
        "paused_by_day_budget": paused_by_day_budget,
        "payments": payments,
        "currency": currency,
        "origin": origin,
        "contract": contract,
        "from_account_id": from_account_id,
        "to_account_id": to_account_id,
        "amount": amount,
        "finance_token": finance_token,
        "master_token": master_token,
        "operation_num": operation_num,
        "finance_login": finance_login,
    }
    _reject_disallowed_flags(ctx, action, supplied)

    if action == "Get":
        param = _account_get_param(logins, account_ids)
        _emit_or_call_v4(
            ctx, "AccountManagement", param, dry_run, output_format, output
        )
        return

    _require_dry_run_or_sandbox(dry_run, ctx.obj.get("sandbox"))

    if action == "Update":
        param = _account_update_param(
            action,
            account_id,
            day_budget,
            spend_mode,
            money_in_sms,
            money_out_sms,
            paused_by_day_budget_sms,
            sms_time_from,
            sms_time_to,
            email,
            money_warning_value,
            paused_by_day_budget,
        )
        _emit_or_call_v4(
            ctx, "AccountManagement", param, dry_run, output_format, output
        )
        return

    # Deposit / Invoice / TransferMoney — financial sub-actions.
    if currency is None:
        raise click.UsageError(
            t("--currency is required for --action {action}").format(action=action)
        )
    resolved_token, resolved_op_num = _finance_credentials(
        finance_token,
        master_token,
        operation_num,
        finance_login,
        "AccountManagement",
        ctx.obj.get("login"),
    )

    if action == "Deposit":
        param = _account_deposit_param(payments, currency, origin, contract)
    elif action == "Invoice":
        param = _account_invoice_param(payments, currency)
    else:  # TransferMoney
        if from_account_id is None or to_account_id is None or amount is None:
            raise click.UsageError(
                t(
                    "--from-account-id, --to-account-id, and --amount are required "
                    "for --action TransferMoney"
                )
            )
        param = _account_transfer_param(
            from_account_id, to_account_id, amount, currency
        )

    _emit_or_call_v4_finance(
        ctx,
        "AccountManagement",
        param,
        resolved_token,
        resolved_op_num,
        dry_run,
        output_format,
        output,
    )
