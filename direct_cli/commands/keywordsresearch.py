"""
KeywordsResearch commands
"""

import click

from ..api import create_client
from ..output import format_output, print_error


@click.group()
def keywordsresearch():
    """Keyword research tools"""


@keywordsresearch.command()
@click.option("--keywords", required=True, help="Comma-separated keywords")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.pass_context
def has_search_volume(ctx, keywords, output_format, output):
    """Check if keywords have search volume"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        body = {
            "method": "hasSearchVolume",
            "params": {
                "SelectionCriteria": {
                    "Keywords": [k.strip() for k in keywords.split(",")]
                }
            },
        }

        result = client.keywordsresearch().post(data=body)
        format_output(result.data, output_format, output)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@keywordsresearch.command()
@click.option("--keywords", required=True, help="Comma-separated keywords")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.pass_context
def deduplicate(ctx, keywords, output_format, output):
    """Deduplicate keywords"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        body = {
            "method": "deduplicate",
            "params": {
                "Keywords": [{"Keyword": k.strip()} for k in keywords.split(",")]
            },
        }

        result = client.keywordsresearch().post(data=body)
        format_output(result.data, output_format, output)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()
