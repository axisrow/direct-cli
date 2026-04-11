"""
AdExtensions commands
"""

import json
import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import parse_ids


@click.group()
def adextensions():
    """Manage ad extensions"""


@adextensions.command()
@click.option("--ids", help="Comma-separated extension IDs")
@click.option("--types", help="Filter by types")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.pass_context
def get(ctx, ids, types, limit, fetch_all, output_format, output, fields):
    """Get ad extensions"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        field_names = fields.split(",") if fields else ["Id", "Type", "Status"]

        criteria = {}
        if ids:
            criteria["Ids"] = parse_ids(ids)
        if types:
            criteria["Types"] = types.split(",")

        params = {"SelectionCriteria": criteria, "FieldNames": field_names}

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        result = client.adextensions().post(data=body)

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


@adextensions.command()
@click.option(
    "--type",
    "ext_type",
    required=True,
    help=(
        "Extension type (UX hint — Callout, Sitelinks, Vcard, …). "
        "Not sent to the API; the API derives the type from the nested "
        "field name inside --json."
    ),
)
@click.option("--json", "extra_json", required=True, help="Extension data in JSON")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(ctx, ext_type, extra_json, dry_run):
    """Add ad extension

    The Yandex Direct API infers the extension type from the top-level
    field of the payload (``Callout`` / ``Sitelinks`` / ``Vcard`` / …),
    so the CLI does **not** forward ``--type`` into the request — it
    is accepted only as a user-facing hint.  Previously direct-cli sent
    ``{"Type": ext_type, ...}`` and the sandbox rejected the extra
    key as ``unknown parameter Type``.
    """
    _ = ext_type  # consumed only for argument validation / UX clarity
    try:
        ext_data = json.loads(extra_json)

        body = {"method": "add", "params": {"AdExtensions": [ext_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.adextensions().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@adextensions.command()
@click.option("--id", "extension_id", required=True, type=int, help="Extension ID")
@click.pass_context
def delete(ctx, extension_id):
    """Delete ad extension"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        body = {
            "method": "delete",
            "params": {"SelectionCriteria": {"Ids": [extension_id]}},
        }

        result = client.adextensions().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


adextensions.add_command(get, name="list")
