"""
Creatives commands
"""

import click

from ..api import create_client
from ._execute import execute_request
from ._get import make_get_command
from ..output import handle_api_errors
from ..utils import (
    parse_csv_upper,
    parse_ids,
)


@click.group()
def creatives():
    """Manage creatives"""


def _creatives_get_criteria(ids=None, types=None, **_):
    """SelectionCriteria for ``creatives get``: optional ``Ids`` plus an
    upper-cased ``Types`` list (an empty ``--types`` CSV maps to ``[]``)."""
    criteria = {}
    if ids:
        criteria["Ids"] = parse_ids(ids)
    if types:
        criteria["Types"] = parse_csv_upper(types) or []
    return criteria


get = make_get_command(
    creatives,
    create_client,
    default_fields_key="creatives",
    help_text="Get creatives",
    ids_help="Comma-separated creative IDs",
    extra_options=(
        click.option("--types", help="Comma-separated creative types"),
    ),
    criteria_builder=_creatives_get_criteria,
    require_criteria_message="Provide at least one typed filter",
    nested_field_options=(
        (
            "--cpc-video-creative-field-names",
            "CpcVideoCreativeFieldNames",
            "Comma-separated CpcVideoCreativeFieldNames (e.g. Duration). "
            "Sent as separate top-level request parameter per the "
            "CreativesGetRequest WSDL.",
        ),
        (
            "--cpm-video-creative-field-names",
            "CpmVideoCreativeFieldNames",
            "Comma-separated CpmVideoCreativeFieldNames (e.g. Duration). "
            "Sent as separate top-level request parameter per the "
            "CreativesGetRequest WSDL.",
        ),
        (
            "--smart-creative-field-names",
            "SmartCreativeFieldNames",
            "Comma-separated SmartCreativeFieldNames "
            "(e.g. CreativeGroupId,CreativeGroupName,BusinessType). "
            "Sent as separate top-level request parameter per the "
            "CreativesGetRequest WSDL.",
        ),
        (
            "--video-extension-creative-field-names",
            "VideoExtensionCreativeFieldNames",
            "Comma-separated VideoExtensionCreativeFieldNames (e.g. Duration). "
            "Sent as separate top-level request parameter per the "
            "CreativesGetRequest WSDL.",
        ),
    ),
)


@creatives.command()
@click.option("--video-id", required=True, help="Video extension creative video ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def add(ctx, video_id, dry_run):
    """Add creative"""
    body = {
        "method": "add",
        "params": {"Creatives": [{"VideoExtensionCreative": {"VideoId": video_id}}]},
    }

    execute_request(ctx, "creatives", body, dry_run, create_client)
