"""
AdVideos commands
"""

import click

from ..api import client_from_ctx, create_client
from ..i18n import t
from ..output import format_output, handle_api_errors
from ..utils import (
    build_common_params,
    get_default_fields,
    get_options,
    load_base64_file,
    parse_csv_strings,
)


@click.group()
def advideos():
    """Manage ad videos"""


@advideos.command()
@click.option("--ids", required=True, help="Comma-separated video IDs")
@get_options
@click.pass_context
@handle_api_errors
def get(ctx, ids, limit, fetch_all, output_format, output, fields, dry_run):
    """Get ad videos"""
    client = client_from_ctx(ctx, create_client)

    field_names = parse_csv_strings(fields) or get_default_fields("advideos")

    criteria = {"Ids": parse_csv_strings(ids) or []}

    params = build_common_params(
        criteria=criteria, field_names=field_names, limit=limit
    )

    body = {"method": "get", "params": params}

    if dry_run:
        format_output(body, "json", None)
        return

    result = client.advideos().post(data=body)

    if fetch_all:
        items = []
        for item in result().iter_items():
            items.append(item)
        format_output(items, output_format, output)
    else:
        data = result().extract()
        format_output(data, output_format, output)


@advideos.command()
@click.option(
    "--url", help="Video URL (mutually exclusive with --video-data/--video-file)"
)
@click.option("--video-data", help="Base64-encoded video binary")
@click.option("--video-file", help="Path to a video file to base64-encode")
@click.option("--name", help="Video name")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def add(ctx, url, video_data, video_file, name, dry_run):
    """Add a new ad video (by URL or binary data)"""
    sources = [s for s in (url, video_data, video_file) if s]
    if len(sources) != 1:
        raise click.UsageError(
            t("Provide exactly one of --url, --video-data, or --video-file.")
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

    client = client_from_ctx(ctx, create_client)

    result = client.advideos().post(data=body)
    format_output(result().extract(), "json", None)
