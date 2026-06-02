"""
AgencyClients commands
"""

import click

from ..api import client_from_ctx, create_client
from ..i18n import t
from ..output import format_output, handle_api_errors, print_error
from ..utils import (
    assert_not_runtime_deprecated,
    build_client_update_item,
    build_notification_update,
    get_default_fields,
    parse_client_setting_specs,
    parse_csv_strings,
    parse_email_subscription_specs,
    parse_grant_specs,
    parse_tin_info,
)


def _build_notification(
    notification_email,
    notification_lang,
    send_account_news,
    send_warnings,
):
    """Build Notification object from typed flags."""
    notification = {}
    if notification_email:
        notification["Email"] = notification_email
    if notification_lang:
        notification["Lang"] = notification_lang
    if notification_email:
        subscriptions = []
        if send_account_news is not None:
            subscriptions.append(
                {
                    "Option": "RECEIVE_RECOMMENDATIONS",
                    "Value": "YES" if send_account_news else "NO",
                }
            )
        if send_warnings is not None:
            subscriptions.append(
                {
                    "Option": "TRACK_POSITION_CHANGES",
                    "Value": "YES" if send_warnings else "NO",
                }
            )
        if subscriptions:
            notification["EmailSubscriptions"] = subscriptions
    return notification


@click.group()
def agencyclients():
    """Manage agency clients"""


@agencyclients.command()
@click.option("--logins", help="Comma-separated client logins")
@click.option(
    "--archived",
    type=click.Choice(["YES", "NO"]),
    default="NO",
    show_default=True,
    help="Filter archived clients",
)
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.option(
    "--contract-field-names",
    help=(
        "Comma-separated ContractFieldNames "
        "(e.g. Number,Date,Price,Type,ActionType). "
        "Sent as separate top-level request parameter per the "
        "AgencyClientsGetRequest WSDL."
    ),
)
@click.option(
    "--contragent-field-names",
    help=(
        "Comma-separated ContragentFieldNames "
        "(e.g. Name,Phone,EpayNumber,RegNumber). "
        "Sent as separate top-level request parameter per the "
        "AgencyClientsGetRequest WSDL."
    ),
)
@click.option(
    "--contragent-tin-info-field-names",
    help=(
        "Comma-separated ContragentTinInfoFieldNames (e.g. TinType,Tin). "
        "Sent as separate top-level request parameter per the "
        "AgencyClientsGetRequest WSDL."
    ),
)
@click.option(
    "--organization-field-names",
    help=(
        "Comma-separated OrganizationFieldNames "
        "(e.g. Name,EpayNumber,RegNumber,OkvedCode). "
        "Sent as separate top-level request parameter per the "
        "AgencyClientsGetRequest WSDL."
    ),
)
@click.option(
    "--tin-info-field-names",
    help=(
        "Comma-separated TinInfoFieldNames (e.g. TinType,Tin). "
        "Sent as separate top-level request parameter per the "
        "AgencyClientsGetRequest WSDL."
    ),
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def get(
    ctx,
    logins,
    archived,
    limit,
    fetch_all,
    output_format,
    output,
    fields,
    contract_field_names,
    contragent_field_names,
    contragent_tin_info_field_names,
    organization_field_names,
    tin_info_field_names,
    dry_run,
):
    """Get agency clients"""
    client = client_from_ctx(ctx, create_client)

    field_names = parse_csv_strings(fields) or get_default_fields("agencyclients")

    raw_nested = (
        ("ContractFieldNames", contract_field_names),
        ("ContragentFieldNames", contragent_field_names),
        ("ContragentTinInfoFieldNames", contragent_tin_info_field_names),
        ("OrganizationFieldNames", organization_field_names),
        ("TinInfoFieldNames", tin_info_field_names),
    )
    parsed_nested = {}
    for wsdl_key, raw_value in raw_nested:
        parsed = parse_csv_strings(raw_value)
        if raw_value is not None and not parsed:
            raise click.UsageError(
                t("Provide a non-empty comma-separated {wsdl_key} list.").format(
                    wsdl_key=wsdl_key
                )
            )
        if parsed:
            parsed_nested[wsdl_key] = parsed

    criteria = {"Archived": archived}
    if logins:
        criteria["Logins"] = parse_csv_strings(logins)

    params = {"SelectionCriteria": criteria, "FieldNames": field_names}
    params.update(parsed_nested)

    if limit:
        params["Page"] = {"Limit": limit}

    body = {"method": "get", "params": params}

    if dry_run:
        format_output(body, "json", None)
        return

    result = client.agencyclients().post(data=body)

    if fetch_all:
        items = []
        for item in result().iter_items():
            items.append(item)
        format_output(items, output_format, output)
    else:
        data = result().extract()
        format_output(data, output_format, output)


@agencyclients.command()
@click.option("--login", required=True, help="Client login")
@click.option("--first-name", required=True, help="First name")
@click.option("--last-name", required=True, help="Last name")
@click.option("--currency", required=True, help="Account currency")
@click.option("--notification-email", help="Notification email")
@click.option("--notification-lang", help="Notification language")
@click.option(
    "--send-account-news/--no-send-account-news",
    default=None,
    help="Enable or disable account news notifications",
)
@click.option(
    "--send-warnings/--no-send-warnings",
    default=None,
    help="Enable or disable warning notifications",
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def add(
    ctx,
    login,
    first_name,
    last_name,
    currency,
    notification_email,
    notification_lang,
    send_account_news,
    send_warnings,
    dry_run,
):
    """Add agency client"""
    assert_not_runtime_deprecated("agencyclients", "add")

    body = {
        "method": "add",
        "params": {
            "Login": login,
            "FirstName": first_name,
            "LastName": last_name,
            "Currency": currency,
            "Notification": _build_notification(
                notification_email,
                notification_lang,
                send_account_news,
                send_warnings,
            ),
        },
    }

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = client.agencyclients().post(data=body)
    format_output(result().extract(), "json", None)


@agencyclients.command(name="add-passport-organization")
@click.option("--name", required=True, help="Organization name")
@click.option("--currency", required=True, help="Account currency")
@click.option("--notification-email", help="Notification email")
@click.option("--notification-lang", help="Notification language")
@click.option(
    "--send-account-news/--no-send-account-news",
    default=None,
    help="Enable or disable account news notifications",
)
@click.option(
    "--send-warnings/--no-send-warnings",
    default=None,
    help="Enable or disable warning notifications",
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def add_passport_organization(
    ctx,
    name,
    currency,
    notification_email,
    notification_lang,
    send_account_news,
    send_warnings,
    dry_run,
):
    """Add passport organization agency client"""
    params = {
        "Name": name,
        "Currency": currency,
        "Notification": _build_notification(
            notification_email,
            notification_lang,
            send_account_news,
            send_warnings,
        ),
    }

    body = {"method": "addPassportOrganization", "params": params}

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)
    result = client.agencyclients().post(data=body)
    format_output(result().extract(), "json", None)


@agencyclients.command(name="add-passport-organization-member")
@click.option(
    "--passport-organization-login", required=True, help="Passport organization login"
)
@click.option("--role", required=True, help="Organization member role")
@click.option("--invite-email", help="Invitation email")
@click.option("--invite-phone", help="Invitation phone")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def add_passport_organization_member(
    ctx, passport_organization_login, role, invite_email, invite_phone, dry_run
):
    """Invite user to passport organization"""
    if not invite_email and not invite_phone:
        raise click.UsageError(
            t("Provide at least one of --invite-email or --invite-phone")
        )

    send_invite_to = {}
    if invite_email:
        send_invite_to["Email"] = invite_email
    if invite_phone:
        send_invite_to["Phone"] = invite_phone

    body = {
        "method": "addPassportOrganizationMember",
        "params": {
            "PassportOrganizationLogin": passport_organization_login,
            "Role": role,
            "SendInviteTo": send_invite_to,
        },
    }

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)
    result = client.agencyclients().post(data=body)
    format_output(result().extract(), "json", None)


@agencyclients.command()
@click.option("--client-id", required=True, type=int, help="Client ID")
@click.option("--client-info", help="Client information")
@click.option("--phone", help="Client phone")
@click.option("--notification-email", help="Notification email")
@click.option("--notification-lang", help="Notification language")
@click.option(
    "--email-subscription",
    "email_subscriptions",
    multiple=True,
    help="Notification subscription as OPTION=YES|NO",
)
@click.option(
    "--setting",
    "settings",
    multiple=True,
    help="Client setting as OPTION=YES|NO",
)
@click.option("--tin-type", help="TIN type")
@click.option("--tin", help="Taxpayer identification number")
@click.option("--grant", "grants", multiple=True, help="Grant as PRIVILEGE=YES|NO")
@click.option("--clear-grants", is_flag=True, help="Clear all grants")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def update(
    ctx,
    client_id,
    client_info,
    phone,
    notification_email,
    notification_lang,
    email_subscriptions,
    settings,
    tin_type,
    tin,
    grants,
    clear_grants,
    dry_run,
):
    """Update agency client"""
    if grants and clear_grants:
        raise click.UsageError(t("--grant and --clear-grants are mutually exclusive"))

    notification = build_notification_update(
        notification_email,
        notification_lang,
        parse_email_subscription_specs(list(email_subscriptions)),
    )
    client_data = {
        "ClientId": client_id,
        **build_client_update_item(
            client_info,
            phone,
            notification,
            parse_client_setting_specs(list(settings)),
            parse_tin_info(tin_type, tin),
        ),
    }
    if grants:
        client_data["Grants"] = parse_grant_specs(list(grants))
    if clear_grants:
        client_data["Grants"] = []
    if len(client_data) == 1:
        raise click.UsageError(t("Provide at least one field to update"))

    body = {"method": "update", "params": {"Clients": [client_data]}}

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)
    result = client.agencyclients().post(data=body)
    format_output(result().extract(), "json", None)


@agencyclients.command()
@click.option("--id", "client_id", required=True, type=int, help="Client ID")
@click.pass_context
def delete(ctx, client_id):
    """Delete agency client (not supported by API)"""
    print_error(
        t(
            "Agency clients cannot be deleted via the Yandex Direct API. "
            "The API only supports add, update, and get operations."
        )
    )
    raise click.Abort()
