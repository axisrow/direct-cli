"""
AdExtensions commands
"""

import click

from ..api import create_client
from ..output import handle_api_errors
from ._execute import execute_request
from ._get import make_get_command
from ._lifecycle import make_lifecycle_command
from ..utils import add_criteria_csv, parse_ids


@click.group()
def adextensions():
    """Manage ad extensions"""


def _adextensions_criteria(
    ids, types=None, states=None, statuses=None, modified_since=None, **_
):
    """SelectionCriteria for ``adextensions get``: ``Ids`` + upper-cased
    ``Types``/``States``/``Statuses`` + a ``ModifiedSince`` scalar."""
    criteria = {}
    if ids:
        criteria["Ids"] = parse_ids(ids)
    add_criteria_csv(criteria, "Types", types, upper=True)
    add_criteria_csv(criteria, "States", states, upper=True)
    add_criteria_csv(criteria, "Statuses", statuses, upper=True)
    if modified_since:
        criteria["ModifiedSince"] = modified_since
    return criteria


get = make_get_command(
    adextensions,
    create_client,
    default_fields_key="adextensions",
    help_text="Get ad extensions",
    ids_help="Comma-separated extension IDs",
    adextensions_wire_layout=True,
    extra_options=(
        click.option("--types", help="Filter by types"),
        click.option("--states", help="Comma-separated states"),
        click.option("--statuses", help="Comma-separated statuses"),
        click.option("--modified-since", help="ModifiedSince datetime"),
    ),
    criteria_builder=_adextensions_criteria,
    nested_field_options=(
        (
            "--callout-field-names",
            "CalloutFieldNames",
            "Comma-separated CalloutFieldNames (e.g. CalloutText)",
        ),
    ),
)


@adextensions.command()
@click.option("--callout-text", required=True, help="Callout text")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def add(ctx, callout_text, dry_run):
    """Add ad extension (callout)"""
    ext_data = {"Callout": {"CalloutText": callout_text}}

    body = {"method": "add", "params": {"AdExtensions": [ext_data]}}

    execute_request(ctx, "adextensions", body, dry_run, create_client)


delete = make_lifecycle_command(
    adextensions,
    "delete",
    "Delete ad extension",
    "extension_id",
    "Extension ID",
    create_client,
)
