"""
AgencyClients commands
"""

import json
import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import parse_ids, get_default_fields


@click.group()
def agencyclients():
    """Manage agency clients"""


@agencyclients.command()
@click.option("--ids", help="Comma-separated client IDs")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.pass_context
def get(ctx, ids, limit, fetch_all, output_format, output, fields):
    """Get agency clients"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        field_names = fields.split(",") if fields else get_default_fields("clients")

        criteria = {}
        if ids:
            criteria["ClientIds"] = parse_ids(ids)

        params = {"FieldNames": field_names}

        if criteria:
            params["SelectionCriteria"] = criteria

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
@click.option("--json", "client_json", required=True, help="Agency client data in JSON")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(ctx, client_json, dry_run):
    """Add agency client"""
    try:
        body = {"method": "add", "params": {"Clients": [json.loads(client_json)]}}

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


agencyclients.add_command(get, name="list")
