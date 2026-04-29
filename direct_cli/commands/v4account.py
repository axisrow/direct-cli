"""Yandex Direct v4 Live shared-account commands."""

import re
from decimal import Decimal, InvalidOperation
from typing import Optional

import click

from ..output import format_output
from ..v4 import build_v4_body
from ..v4_contracts import v4_method_contract
from .v4shells import V4_EPILOG

YES_NO = ("Yes", "No")
SPEND_MODES = ("Default", "Stretched")
HH_MM_RE = re.compile(r"^(?:[01]\d|2[0-3]):(?:00|15|30|45)$")


@click.group(epilog=V4_EPILOG)
def v4account():
    """Yandex Direct v4 Live account commands."""


def _require_dry_run(dry_run: bool) -> None:
    """Reject shared-account mutations unless dry-run is explicit."""
    if not dry_run:
        raise click.UsageError("--dry-run is required for v4account commands")


def _non_empty(value: str, option_name: str) -> str:
    """Normalize a required string option."""
    normalized = (value or "").strip()
    if not normalized:
        raise click.UsageError(f"{option_name} must not be empty")
    return normalized


def _parse_day_budget(value: Optional[str]) -> Optional[float]:
    """Parse a non-negative v4 shared-account budget amount."""
    if value is None:
        return None
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise click.UsageError("--day-budget must be a non-negative amount") from exc
    if not amount.is_finite() or amount < 0 or (amount == 0 and amount.is_signed()):
        raise click.UsageError("--day-budget must be a non-negative amount")
    return float(amount)


def _parse_hh_mm(value: Optional[str], option_name: str) -> Optional[str]:
    """Validate v4 SMS notification time."""
    if value is None:
        return None
    if not HH_MM_RE.match(value):
        raise click.UsageError(
            f"{option_name} must use HH:MM with minutes 00, 15, 30, or 45"
        )
    return value


def _validate_action(action: str) -> str:
    """Normalize the supported AccountManagement action."""
    normalized = (action or "").strip()
    if normalized != "Update":
        raise click.UsageError("Only --action Update is supported by this command")
    return normalized


def _account_update_param(
    action: str,
    account_id: int,
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
    account = {"AccountID": account_id}

    parsed_day_budget = _parse_day_budget(day_budget)
    if parsed_day_budget is not None or spend_mode is not None:
        if parsed_day_budget is None or spend_mode is None:
            raise click.UsageError(
                "--day-budget and --spend-mode must be provided together"
            )
        account["AccountDayBudget"] = {
            "Amount": parsed_day_budget,
            "SpendMode": spend_mode,
        }

    sms_notification = {}
    if money_in_sms is not None:
        sms_notification["MoneyInSms"] = money_in_sms
    if money_out_sms is not None:
        sms_notification["MoneyOutSms"] = money_out_sms
    if paused_by_day_budget_sms is not None:
        sms_notification["PausedByDayBudgetSms"] = paused_by_day_budget_sms
    if (sms_time_from is None) != (sms_time_to is None):
        raise click.UsageError(
            "--sms-time-from and --sms-time-to must be provided together"
        )
    if sms_time_from is not None:
        sms_notification["SmsTimeFrom"] = _parse_hh_mm(sms_time_from, "--sms-time-from")
    if sms_time_to is not None:
        sms_notification["SmsTimeTo"] = _parse_hh_mm(sms_time_to, "--sms-time-to")
    if sms_notification:
        account["SmsNotification"] = sms_notification

    email_notification = {}
    if email is not None:
        email_notification["Email"] = _non_empty(email, "--email")
    if money_warning_value is not None:
        email_notification["MoneyWarningValue"] = money_warning_value
    if paused_by_day_budget is not None:
        email_notification["PausedByDayBudget"] = paused_by_day_budget
    if email_notification:
        account["EmailNotification"] = email_notification

    if len(account) == 1:
        raise click.UsageError("Provide at least one update field")

    return {"Action": action, "Accounts": [account]}


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
    help="Show request without sending; required for this command",
)
def enable_shared_account(client_login, dry_run):
    """Preview enabling a shared account for a client."""
    _require_dry_run(dry_run)
    param = {"Login": _non_empty(client_login, "--client-login")}
    format_output(build_v4_body("EnableSharedAccount", param), "json", None)


@v4_method_contract("AccountManagement")
@v4account.command(name="account-management")
@click.option("--action", required=True, help="AccountManagement action: Update")
@click.option(
    "--account-id",
    required=True,
    type=click.IntRange(min=1),
    help="Shared account ID",
)
@click.option("--day-budget", help="Shared account daily budget")
@click.option("--spend-mode", type=click.Choice(SPEND_MODES), help="Budget spend mode")
@click.option("--money-in-sms", type=click.Choice(YES_NO), help="Enable money-in SMS")
@click.option("--money-out-sms", type=click.Choice(YES_NO), help="Enable money-out SMS")
@click.option(
    "--paused-by-day-budget-sms",
    type=click.Choice(YES_NO),
    help="Enable day-budget pause SMS",
)
@click.option("--sms-time-from", help="SMS notification start time, HH:MM")
@click.option("--sms-time-to", help="SMS notification end time, HH:MM")
@click.option("--email", help="Notification email")
@click.option(
    "--money-warning-value",
    type=click.IntRange(min=0),
    help="Balance warning percentage",
)
@click.option(
    "--paused-by-day-budget",
    type=click.Choice(YES_NO),
    help="Enable day-budget pause email",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show request without sending; required for this command",
)
def account_management(
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
    dry_run,
):
    """Preview updating shared-account settings."""
    _require_dry_run(dry_run)
    param = _account_update_param(
        _validate_action(action),
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
    format_output(build_v4_body("AccountManagement", param), "json", None)
