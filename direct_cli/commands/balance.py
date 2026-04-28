"""Money balance command backed by Yandex Direct v4 Live."""

import click

from ..api import create_v4_client
from ..output import format_output, print_error
from ..utils import parse_csv_strings
from ..v4 import build_v4_body, call_v4
from ..v4_contracts import v4_method_contract


@v4_method_contract("AccountManagement")
@click.command()
@click.option("--logins", help="Comma-separated client logins")
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
def balance(ctx, logins, output_format, output, dry_run):
    """Check account money balance."""
    login_list = parse_csv_strings(logins)
    configured_login = ctx.obj.get("login")
    if not login_list and configured_login:
        login_list = [configured_login]

    param = {
        "Action": "Get",
    }
    if login_list:
        param["SelectionCriteria"] = {"Logins": login_list}
    elif ctx.obj.get("sandbox"):
        raise click.UsageError("Provide --logins or configure YANDEX_DIRECT_LOGIN")

    if dry_run:
        format_output(build_v4_body("AccountManagement", param), "json", None)
        return

    try:
        client = create_v4_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            profile=ctx.obj.get("profile"),
            sandbox=ctx.obj.get("sandbox"),
        )
        data = call_v4(client, "AccountManagement", param)
        format_output(data, output_format, output)
    except Exception as e:
        print_error(str(e))
        raise click.Abort()
