"""
AdVideos commands
"""

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import get_default_fields, load_base64_file


@click.group()
def advideos():
    """Manage ad videos"""


@advideos.command()
@click.option("--ids", help="Comma-separated video IDs")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.pass_context
def get(ctx, ids, limit, fetch_all, output_format, output, fields):
    """Get ad videos"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        field_names = fields.split(",") if fields else get_default_fields("advideos")

        criteria = {}
        if ids:
            criteria["Ids"] = [x.strip() for x in ids.split(",")]

        params = {
            "SelectionCriteria": criteria,
            "FieldNames": field_names,
        }

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        result = client.advideos().post(data=body)

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


@advideos.command()
@click.option("--url", help="Video URL (mutually exclusive with --video-data/--video-file)")
@click.option("--video-data", help="Base64-encoded video binary")
@click.option("--video-file", help="Path to a video file to base64-encode")
@click.option("--name", help="Video name")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(ctx, url, video_data, video_file, name, dry_run):
    """Add a new ad video (by URL or binary data)"""
    try:
        sources = [s for s in (url, video_data, video_file) if s]
        if len(sources) != 1:
            raise click.UsageError(
                "Provide exactly one of --url, --video-data, or --video-file."
            )

        item = {}
        if url:
            item["Url"] = url
        elif video_data:
            item["VideoData"] = video_data
        else:
            item["VideoData"] = load_base64_file(video_file)
        if name:
            item["Name"] = name

        body = {"method": "add", "params": {"AdVideos": [item]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.advideos().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()
