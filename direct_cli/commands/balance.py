"""Balance command backed by Yandex Direct v4 Live."""

import click

from ..api import create_v4_client
from ..output import format_output, print_error
from ..utils import parse_csv_strings
from ..v4 import build_v4_body, call_v4


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
    """Check client units balance."""
    login_list = parse_csv_strings(logins)
    if not login_list:
        configured_login = ctx.obj.get("login")
        if not configured_login:
            raise click.UsageError("Provide --logins or configure YANDEX_DIRECT_LOGIN")
        login_list = [configured_login]

    param = {"Logins": login_list}
    if dry_run:
        format_output(build_v4_body("GetClientsUnits", param), "json", None)
        return

    try:
        client = create_v4_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            profile=ctx.obj.get("profile"),
            sandbox=ctx.obj.get("sandbox"),
        )
        data = call_v4(client, "GetClientsUnits", param)
        format_output(data, output_format, output)
    except Exception as e:
        print_error(str(e))
        raise click.Abort()
