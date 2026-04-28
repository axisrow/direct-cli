"""
AgencyClients commands
"""

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import get_default_fields


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
@click.pass_context
def get(ctx, logins, archived, limit, fetch_all, output_format, output, fields):
    """Get agency clients"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        field_names = (
            fields.split(",") if fields else get_default_fields("agencyclients")
        )

        criteria = {"Archived": archived}
        if logins:
            criteria["Logins"] = [login.strip() for login in logins.split(",")]

        params = {"SelectionCriteria": criteria, "FieldNames": field_names}

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        result = client.agencyclients().post(data=body)

        if fetch_all:
            items = []
            for item in result().iter_items():
                items.append(item)
            format_output(items, output_format, output)
        else:
            data = result().extract()
            format_output(data, output_format, output)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


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
    try:
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

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.agencyclients().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


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
    try:
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

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )
        result = client.agencyclients().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@agencyclients.command(name="add-passport-organization-member")
@click.option(
    "--passport-organization-login", required=True, help="Passport organization login"
)
@click.option("--role", required=True, help="Organization member role")
@click.option("--invite-email", help="Invitation email")
@click.option("--invite-phone", help="Invitation phone")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add_passport_organization_member(
    ctx, passport_organization_login, role, invite_email, invite_phone, dry_run
):
    """Invite user to passport organization"""
    try:
        if not invite_email and not invite_phone:
            raise click.UsageError(
                "Provide at least one of --invite-email or --invite-phone"
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

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )
        result = client.agencyclients().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@agencyclients.command()
@click.option("--client-id", required=True, type=int, help="Client ID")
@click.option("--phone", help="Client phone")
@click.option("--email", help="Client email")
@click.option("--grant", "grants", multiple=True, help="Grant value")
@click.option("--clear-grants", is_flag=True, help="Clear all grants")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def update(ctx, client_id, phone, email, grants, clear_grants, dry_run):
    """Update agency client"""
    try:
        client_data = {"ClientId": client_id}

        if phone:
            client_data["Phone"] = phone
        if email:
            client_data["Email"] = email
        if grants and clear_grants:
            raise click.UsageError("--grant and --clear-grants are mutually exclusive")
        if grants:
            client_data["Grants"] = list(grants)
        if clear_grants:
            client_data["Grants"] = []
        if len(client_data) == 1:
            raise click.UsageError("Provide at least one field to update")

        body = {"method": "update", "params": {"Clients": [client_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )
        result = client.agencyclients().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@agencyclients.command()
@click.option("--id", "client_id", required=True, type=int, help="Client ID")
@click.pass_context
def delete(ctx, client_id):
    """Delete agency client (not supported by API)"""
    print_error(
        "Agency clients cannot be deleted via the Yandex Direct API. "
        "The API only supports add, update, and get operations."
    )
    raise click.Abort()
