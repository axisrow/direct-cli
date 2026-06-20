"""
AdVideos commands
"""

import click

from ..api import create_client
from ..i18n import t
from ..output import handle_api_errors
from ..utils import load_base64_file, parse_csv_strings
from ._execute import execute_request
from ._get import make_get_command


@click.group()
def advideos():
    """Manage ad videos"""


get = make_get_command(
    advideos,
    create_client,
    default_fields_key="advideos",
    help_text="Get ad videos",
    ids_help="Comma-separated video IDs",
    ids_required=True,
    criteria_builder=lambda ids, **_: {"Ids": parse_csv_strings(ids) or []},
)


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

    execute_request(ctx, "advideos", body, dry_run, create_client)
