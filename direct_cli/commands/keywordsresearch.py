"""
KeywordsResearch commands
"""

import click

from ..api import client_from_ctx, create_client
from ..output import format_output, handle_api_errors
from ..utils import get_default_fields, parse_ids


@click.group()
def keywordsresearch():
    """Keyword research tools"""


@keywordsresearch.command()
@click.option("--keywords", required=True, help="Comma-separated keywords")
@click.option(
    "--region-ids",
    required=True,
    help="Comma-separated region IDs (e.g. 213 for Moscow)",
)
@click.option("--fields", help="Comma-separated field names")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.pass_context
@handle_api_errors
def has_search_volume(ctx, keywords, region_ids, fields, output_format, output):
    """Check if keywords have search volume"""
    client = client_from_ctx(ctx, create_client)

    field_names = (
        [f.strip() for f in fields.split(",")]
        if fields
        else get_default_fields("keywordsresearch")
    )

    body = {
        "method": "hasSearchVolume",
        "params": {
            "SelectionCriteria": {
                "RegionIds": parse_ids(region_ids),
                "Keywords": [k.strip() for k in keywords.split(",")],
            },
            "FieldNames": field_names,
        },
    }

    result = client.keywordsresearch().post(data=body)
    format_output(result.data, output_format, output)


@keywordsresearch.command()
@click.option("--keywords", required=True, help="Comma-separated keywords")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.pass_context
@handle_api_errors
def deduplicate(ctx, keywords, output_format, output):
    """Deduplicate keywords"""
    client = client_from_ctx(ctx, create_client)

    body = {
        "method": "deduplicate",
        "params": {"Keywords": [{"Keyword": k.strip()} for k in keywords.split(",")]},
    }

    result = client.keywordsresearch().post(data=body)
    format_output(result.data, output_format, output)
