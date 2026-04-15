"""
Clients commands
"""

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import get_default_fields, parse_ids


@click.group()
def clients():
    """Manage clients"""


@clients.command()
@click.option("--ids", help="Comma-separated client IDs")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.pass_context
def get(ctx, ids, limit, fetch_all, output_format, output, fields):
    """Get clients"""
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

        result = client.clients().post(data=body)

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


@clients.command()
@click.option("--client-id", required=True, type=int, help="Client ID")
@click.option("--phone", help="Client phone")
@click.option("--fax", help="Client fax")
@click.option("--email", help="Client email")
@click.option("--city", help="Client city")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def update(ctx, client_id, phone, fax, email, city, dry_run):
    """Update client settings"""
    try:
        client_data = {"ClientId": client_id}
        if phone:
            client_data["Phone"] = phone
        if fax:
            client_data["Fax"] = fax
        if email:
            client_data["Email"] = email
        if city:
            client_data["City"] = city
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

        result = client.clients().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()
