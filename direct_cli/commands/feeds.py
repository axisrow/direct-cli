"""
Feeds commands
"""

import base64
from pathlib import Path
from typing import Dict, Optional

import click

from ..api import client_from_ctx, create_client
from ..i18n import t
from ..output import format_output, handle_api_errors
from ._execute import execute_request
from ._lifecycle import make_lifecycle_command
from ..utils import (
    build_common_params,
    get_default_fields,
    parse_csv_strings,
    parse_ids,
)

_YES_NO = ["YES", "NO"]
# Yandex Direct docs cap FileFeed.Data by total request size. This
# pre-read guard rejects definitely oversized local files; the API remains
# the final validator for the base64-encoded request envelope.
_FILE_FEED_MAX_BYTES = 50 * 1024 * 1024
# feeds.add/update docs define FileFeed.Filename as at most 255 characters.
_FILE_FEED_MAX_FILENAME_LENGTH = 255


def _url_feed_payload(
    url: Optional[str] = None,
    remove_utm_tags: Optional[str] = None,
    login: Optional[str] = None,
    password: Optional[str] = None,
    clear_login: bool = False,
    clear_password: bool = False,
) -> Dict[str, object]:
    payload: Dict[str, object] = {}
    if url:
        payload["Url"] = url
    if remove_utm_tags:
        payload["RemoveUtmTags"] = remove_utm_tags.upper()
    if clear_login:
        payload["Login"] = None
    elif login:
        payload["Login"] = login
    if clear_password:
        payload["Password"] = None
    elif password:
        payload["Password"] = password
    return payload


def _file_feed_payload(
    file_feed_path: str,
    file_feed_filename: Optional[str] = None,
) -> Dict[str, object]:
    path = Path(file_feed_path)
    filename = file_feed_filename or path.name
    if not filename:
        raise click.UsageError(t("FileFeed.Filename cannot be empty."))
    if len(filename) > _FILE_FEED_MAX_FILENAME_LENGTH:
        raise click.UsageError(
            t(
                "FileFeed.Filename must be at most {_FILE_FEED_MAX_FILENAME_LENGTH} characters."
            ).format(_FILE_FEED_MAX_FILENAME_LENGTH=_FILE_FEED_MAX_FILENAME_LENGTH)
        )

    try:
        file_size = path.stat().st_size
    except OSError as exc:
        raise click.UsageError(
            t("Cannot read --file-feed-path {file_feed_path!r}: {exc}").format(
                file_feed_path=file_feed_path, exc=exc
            )
        )

    if file_size > _FILE_FEED_MAX_BYTES:
        raise click.UsageError(
            t("FileFeed.Data must be at most 50 MiB before base64 encoding.")
        )

    try:
        data = path.read_bytes()
    except OSError as exc:
        raise click.UsageError(
            t("Cannot read --file-feed-path {file_feed_path!r}: {exc}").format(
                file_feed_path=file_feed_path, exc=exc
            )
        )

    return {
        "Data": base64.b64encode(data).decode("ascii"),
        "Filename": filename,
    }


def _has_url_feed_options(
    url: Optional[str],
    remove_utm_tags: Optional[str],
    feed_login: Optional[str],
    feed_password: Optional[str],
    clear_feed_login: bool = False,
    clear_feed_password: bool = False,
) -> bool:
    return any(
        (
            url,
            remove_utm_tags,
            feed_login,
            feed_password,
            clear_feed_login,
            clear_feed_password,
        )
    )


@click.group()
def feeds():
    """Manage feeds"""


@feeds.command()
@click.option("--ids", help="Comma-separated feed IDs")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.option(
    "--file-feed-field-names",
    help=(
        "Comma-separated FileFeedFieldNames (e.g. Filename). "
        "Sent as separate top-level request parameter per the "
        "FeedsGetRequest WSDL."
    ),
)
@click.option(
    "--url-feed-field-names",
    help=(
        "Comma-separated UrlFeedFieldNames (e.g. Login,Url,RemoveUtmTags). "
        "Sent as separate top-level request parameter per the "
        "FeedsGetRequest WSDL."
    ),
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def get(
    ctx,
    ids,
    limit,
    fetch_all,
    output_format,
    output,
    fields,
    file_feed_field_names,
    url_feed_field_names,
    dry_run,
):
    """Get feeds"""
    client = client_from_ctx(ctx, create_client)

    field_names = parse_csv_strings(fields) or get_default_fields("feeds")

    parsed_file_feed_field_names = parse_csv_strings(file_feed_field_names)
    if file_feed_field_names is not None and not parsed_file_feed_field_names:
        raise click.UsageError(
            t("Provide a non-empty comma-separated FileFeedFieldNames list.")
        )

    parsed_url_feed_field_names = parse_csv_strings(url_feed_field_names)
    if url_feed_field_names is not None and not parsed_url_feed_field_names:
        raise click.UsageError(
            t("Provide a non-empty comma-separated UrlFeedFieldNames list.")
        )

    criteria = {}
    if ids:
        criteria["Ids"] = parse_ids(ids)

    params = build_common_params(
        criteria=criteria, field_names=field_names, limit=limit
    )
    if parsed_file_feed_field_names:
        params["FileFeedFieldNames"] = parsed_file_feed_field_names
    if parsed_url_feed_field_names:
        params["UrlFeedFieldNames"] = parsed_url_feed_field_names

    body = {"method": "get", "params": params}

    if dry_run:
        format_output(body, "json", None)
        return

    result = client.feeds().post(data=body)

    if fetch_all:
        items = []
        for item in result().iter_items():
            items.append(item)
        format_output(items, output_format, output)
    else:
        data = result().extract()
        format_output(data, output_format, output)


@feeds.command()
@click.option("--name", required=True, help="Feed name")
@click.option("--url", help="Feed URL")
@click.option(
    "--file-feed-path",
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to feed file for FileFeed.Data base64 upload.",
)
@click.option(
    "--file-feed-filename",
    help="FileFeed.Filename; defaults to the basename of --file-feed-path.",
)
@click.option(
    "--remove-utm-tags",
    type=click.Choice(_YES_NO, case_sensitive=False),
    help="UrlFeed.RemoveUtmTags: delete UTM tags from feed links, YES or NO.",
)
@click.option("--feed-login", help="UrlFeed.Login for protected feed URL")
@click.option("--feed-password", help="UrlFeed.Password for protected feed URL")
@click.option(
    "--business-type",
    required=True,
    type=click.Choice(
        ["RETAIL", "HOTELS", "REALTY", "AUTOMOBILES", "FLIGHTS", "OTHER"],
        case_sensitive=False,
    ),
    help="Business type (BusinessTypeEnum)",
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def add(
    ctx,
    name,
    url,
    file_feed_path,
    file_feed_filename,
    remove_utm_tags,
    feed_login,
    feed_password,
    business_type,
    dry_run,
):
    """Add feed"""
    if file_feed_filename and not file_feed_path:
        raise click.UsageError(t("--file-feed-filename requires --file-feed-path."))
    if url and file_feed_path:
        raise click.UsageError(t("Use either --url or --file-feed-path, not both."))
    if not url and not file_feed_path:
        raise click.UsageError(t("Provide exactly one of --url or --file-feed-path."))
    if file_feed_path and _has_url_feed_options(
        None, remove_utm_tags, feed_login, feed_password
    ):
        raise click.UsageError(
            t(
                "--remove-utm-tags, --feed-login, and --feed-password are "
                "only valid with --url feeds."
            )
        )

    feed_data = {
        "Name": name,
        "BusinessType": business_type.upper(),
        "SourceType": "FILE" if file_feed_path else "URL",
    }
    if file_feed_path:
        feed_data["FileFeed"] = _file_feed_payload(file_feed_path, file_feed_filename)
    else:
        feed_data["UrlFeed"] = _url_feed_payload(
            url, remove_utm_tags, feed_login, feed_password
        )

    body = {"method": "add", "params": {"Feeds": [feed_data]}}

    execute_request(ctx, "feeds", body, dry_run, create_client)


@feeds.command()
@click.option(
    "--id", "feed_id", required=True, type=click.IntRange(min=1), help="Feed ID"
)
@click.option("--name", help="Feed name")
@click.option(
    "--url",
    help="Feed URL for an existing URL feed; Yandex Direct rejects source switches.",
)
@click.option(
    "--file-feed-path",
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help=(
        "Path to feed file for an existing FILE feed; Yandex Direct rejects "
        "source switches."
    ),
)
@click.option(
    "--file-feed-filename",
    help="FileFeed.Filename; defaults to the basename of --file-feed-path.",
)
@click.option(
    "--remove-utm-tags",
    type=click.Choice(_YES_NO, case_sensitive=False),
    help="UrlFeed.RemoveUtmTags: delete UTM tags from feed links, YES or NO.",
)
@click.option("--feed-login", help="UrlFeed.Login for protected feed URL")
@click.option("--feed-password", help="UrlFeed.Password for protected feed URL")
@click.option("--clear-feed-login", is_flag=True, help="Set UrlFeed.Login to null")
@click.option(
    "--clear-feed-password", is_flag=True, help="Set UrlFeed.Password to null"
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def update(
    ctx,
    feed_id,
    name,
    url,
    file_feed_path,
    file_feed_filename,
    remove_utm_tags,
    feed_login,
    feed_password,
    clear_feed_login,
    clear_feed_password,
    dry_run,
):
    """Update feed"""
    if feed_login is not None and clear_feed_login:
        raise click.UsageError(
            t("Use either --feed-login or --clear-feed-login, not both")
        )
    if feed_password is not None and clear_feed_password:
        raise click.UsageError(
            t("Use either --feed-password or --clear-feed-password, not both")
        )
    if file_feed_filename and not file_feed_path:
        raise click.UsageError(t("--file-feed-filename requires --file-feed-path."))
    if file_feed_path and _has_url_feed_options(
        url,
        remove_utm_tags,
        feed_login,
        feed_password,
        clear_feed_login,
        clear_feed_password,
    ):
        raise click.UsageError(
            t("FileFeed options cannot be combined with UrlFeed options.")
        )

    feed_data = {"Id": feed_id}

    if name:
        feed_data["Name"] = name
    url_feed = _url_feed_payload(
        url,
        remove_utm_tags,
        feed_login,
        feed_password,
        clear_feed_login,
        clear_feed_password,
    )
    if url_feed:
        feed_data["UrlFeed"] = url_feed
    if file_feed_path:
        feed_data["FileFeed"] = _file_feed_payload(file_feed_path, file_feed_filename)
    if len(feed_data) == 1:
        raise click.UsageError(
            t(
                "Provide at least one of --name, --url, --file-feed-path, "
                "--remove-utm-tags, --feed-login, --feed-password, "
                "--clear-feed-login, or --clear-feed-password"
            )
        )

    body = {"method": "update", "params": {"Feeds": [feed_data]}}

    execute_request(ctx, "feeds", body, dry_run, create_client)


delete = make_lifecycle_command(
    feeds, "delete", "Delete feed", "feed_id", "Feed ID", create_client
)
