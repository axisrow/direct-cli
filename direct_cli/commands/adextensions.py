"""
AdExtensions commands
"""

import click

from ..api import client_from_ctx, create_client
from ..i18n import t
from ..output import format_output, handle_api_errors
from ..utils import add_criteria_csv, get_default_fields, parse_csv_strings, parse_ids


@click.group()
def adextensions():
    """Manage ad extensions"""


@adextensions.command()
@click.option("--ids", help="Comma-separated extension IDs")
@click.option("--types", help="Filter by types")
@click.option("--states", help="Comma-separated states")
@click.option("--statuses", help="Comma-separated statuses")
@click.option("--modified-since", help="ModifiedSince datetime")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.option(
    "--callout-field-names",
    help="Comma-separated CalloutFieldNames (e.g. CalloutText)",
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def get(
    ctx,
    ids,
    types,
    states,
    statuses,
    modified_since,
    limit,
    fetch_all,
    output_format,
    output,
    fields,
    callout_field_names,
    dry_run,
):
    """Get ad extensions"""
    client = client_from_ctx(ctx, create_client)

    field_names = parse_csv_strings(fields) or get_default_fields("adextensions")
    parsed_callout_field_names = parse_csv_strings(callout_field_names)
    if callout_field_names is not None and not parsed_callout_field_names:
        raise click.UsageError(
            t("Provide a non-empty comma-separated CalloutFieldNames list.")
        )

    criteria = {}
    if ids:
        criteria["Ids"] = parse_ids(ids)
    if types:
        criteria["Types"] = types.split(",")
    add_criteria_csv(criteria, "States", states, upper=True)
    add_criteria_csv(criteria, "Statuses", statuses, upper=True)
    if modified_since:
        criteria["ModifiedSince"] = modified_since

    params = {"SelectionCriteria": criteria, "FieldNames": field_names}
    if parsed_callout_field_names:
        params["CalloutFieldNames"] = parsed_callout_field_names

    if limit:
        params["Page"] = {"Limit": limit}

    body = {"method": "get", "params": params}

    if dry_run:
        format_output(body, "json", None)
        return

    result = client.adextensions().post(data=body)

    if fetch_all:
        items = []
        for item in result().iter_items():
            items.append(item)
        format_output(items, output_format, output)
    else:
        data = result().extract()
        format_output(data, output_format, output)


@adextensions.command()
@click.option("--callout-text", required=True, help="Callout text")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def add(ctx, callout_text, dry_run):
    """Add ad extension (callout)"""
    ext_data = {"Callout": {"CalloutText": callout_text}}

    body = {"method": "add", "params": {"AdExtensions": [ext_data]}}

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = client.adextensions().post(data=body)
    format_output(result().extract(), "json", None)


@adextensions.command()
@click.option("--id", "extension_id", required=True, type=int, help="Extension ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def delete(ctx, extension_id, dry_run):
    """Delete ad extension"""
    body = {
        "method": "delete",
        "params": {"SelectionCriteria": {"Ids": [extension_id]}},
    }

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = client.adextensions().post(data=body)
    format_output(result().extract(), "json", None)
