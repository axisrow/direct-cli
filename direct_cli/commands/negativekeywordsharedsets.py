"""
NegativeKeywordSharedSets commands
"""

import click

from ..api import client_from_ctx, create_client
from ..output import format_output, handle_api_errors
from ..utils import parse_csv_strings
from ._get import make_get_command
from ._lifecycle import make_lifecycle_command


@click.group()
def negativekeywordsharedsets():
    """Manage negative keyword shared sets"""


get = make_get_command(
    negativekeywordsharedsets,
    create_client,
    default_fields_key="negativekeywordsharedsets",
    help_text="Get negative keyword shared sets",
    ids_help="Comma-separated set IDs",
)


@negativekeywordsharedsets.command()
@click.option("--name", required=True, help="Set name")
@click.option("--keywords", required=True, help="Comma-separated negative keywords")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def add(ctx, name, keywords, dry_run):
    """Add negative keyword shared set"""
    set_data = {
        "Name": name,
        "NegativeKeywords": parse_csv_strings(keywords),
    }

    body = {"method": "add", "params": {"NegativeKeywordSharedSets": [set_data]}}

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = client.negativekeywordsharedsets().post(data=body)
    format_output(result().extract(), "json", None)


@negativekeywordsharedsets.command()
@click.option(
    "--id", "set_id", required=True, type=click.IntRange(min=1), help="Set ID"
)
@click.option("--name", help="Set name")
@click.option("--keywords", help="Comma-separated negative keywords")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def update(ctx, set_id, name, keywords, dry_run):
    """Update negative keyword shared set"""
    set_data = {"Id": set_id}

    if name:
        set_data["Name"] = name
    if keywords:
        set_data["NegativeKeywords"] = parse_csv_strings(keywords)
    if len(set_data) == 1:
        raise click.ClickException("Provide at least one of --name or --keywords")

    body = {
        "method": "update",
        "params": {"NegativeKeywordSharedSets": [set_data]},
    }

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = client.negativekeywordsharedsets().post(data=body)
    format_output(result().extract(), "json", None)


delete = make_lifecycle_command(
    negativekeywordsharedsets,
    "delete",
    "Delete negative keyword shared set",
    "set_id",
    "Set ID",
    create_client,
)
