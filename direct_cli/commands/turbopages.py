"""
TurboPages commands

NOTE: The Yandex Direct API ``turbopages`` service is read-only — it only
exposes ``get``.  Turbo pages themselves are created via the Yandex Direct
web UI and can only be referenced from the API (e.g. via ``TurboPageId`` in
sitelinks).  No ``add``/``update``/``delete`` methods exist on this service.
"""

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import parse_ids


@click.group()
def turbopages():
    """Manage Turbo Pages"""


@turbopages.command()
@click.option("--ids", help="Comma-separated Turbo Page IDs")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.pass_context
def get(ctx, ids, limit, fetch_all, output_format, output, fields):
    """Get Turbo Pages"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        field_names = fields.split(",") if fields else ["Id", "Name", "Status", "Href"]

        criteria = {}
        if ids:
            criteria["Ids"] = parse_ids(ids)

        params = {"SelectionCriteria": criteria, "FieldNames": field_names}

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        result = client.turbopages().post(data=body)

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

