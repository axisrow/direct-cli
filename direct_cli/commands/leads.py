"""
Leads commands
"""

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import get_default_fields, parse_ids


@click.group()
def leads():
    """Manage leads"""


@leads.command()
@click.option(
    "--turbo-page-ids",
    required=True,
    help="Comma-separated turbo page IDs",
)
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--datetime-from", help="DateTimeFrom in YYYY-MM-DDTHH:MM:SS format")
@click.option("--datetime-to", help="DateTimeTo in YYYY-MM-DDTHH:MM:SS format")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def get(
    ctx,
    turbo_page_ids,
    limit,
    datetime_from,
    datetime_to,
    fetch_all,
    output_format,
    output,
    fields,
    dry_run,
):
    """Get leads"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        field_names = fields.split(",") if fields else get_default_fields("leads")

        criteria = {"TurboPageIds": parse_ids(turbo_page_ids)}
        if datetime_from:
            criteria["DateTimeFrom"] = datetime_from
        if datetime_to:
            criteria["DateTimeTo"] = datetime_to

        params = {"SelectionCriteria": criteria, "FieldNames": field_names}

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        if dry_run:
            format_output(body, "json", None)
            return

        result = client.leads().post(data=body)

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
