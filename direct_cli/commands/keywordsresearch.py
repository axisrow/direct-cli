"""
KeywordsResearch commands
"""

import click

from ..api import create_client
from ..output import format_output, print_error


@click.group()
def keywordsresearch():
    """Keyword research tools"""
    pass


@keywordsresearch.command()
@click.option("--keywords", required=True, help="Comma-separated keywords")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.pass_context
def get(ctx, keywords, limit, output_format, output):
    """Get keywords research data"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        params = {"Keywords": [k.strip() for k in keywords.split(",")]}

        if limit:
            params["Limit"] = limit

        body = {"method": "get", "params": params}

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
def has_search_volume(ctx, keywords, output_format, output):
    """Check if keywords have search volume"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        body = {
            "method": "HasSearchVolume",
            "params": {"Keywords": [k.strip() for k in keywords.split(",")]},
        }

        result = client.keywordsresearch().post(data=body)
        format_output(result.data, output_format, output)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()
