"""
Businesses commands
"""

import click

from ..api import client_from_ctx, create_client
from ..output import format_output, handle_api_errors
from ..utils import get_default_fields, get_options, parse_ids


@click.group()
def businesses():
    """Manage businesses"""


@businesses.command()
@click.option("--ids", help="Comma-separated business IDs")
@get_options
@click.pass_context
@handle_api_errors
def get(ctx, ids, limit, fetch_all, output_format, output, fields, dry_run):
    """Get businesses"""
    client = client_from_ctx(ctx, create_client)

    field_names = fields.split(",") if fields else get_default_fields("businesses")

    criteria = {}
    if ids:
        criteria["Ids"] = parse_ids(ids)

    params = {"FieldNames": field_names}
    if criteria:
        params["SelectionCriteria"] = criteria

    if limit:
        params["Page"] = {"Limit": limit}

    body = {"method": "get", "params": params}

    if dry_run:
        format_output(body, "json", None)
        return

    result = client.businesses().post(data=body)

    if fetch_all:
        items = []
        for item in result().iter_items():
            items.append(item)
        format_output(items, output_format, output)
    else:
        data = result().extract()
        format_output(data, output_format, output)
