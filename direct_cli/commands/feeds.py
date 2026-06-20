"""
Feeds commands
"""

import base64
from pathlib import Path
from typing import Dict, Optional

import click

from ..api import create_client
from ..i18n import t
from ..output import handle_api_errors
from ._execute import execute_request
from ._get import make_get_command
from ._lifecycle import make_lifecycle_command

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


get = make_get_command(
    feeds,
    create_client,
    default_fields_key="feeds",
    help_text="Get feeds",
    ids_help="Comma-separated feed IDs",
    nested_field_options=(
        (
            "--file-feed-field-names",
            "FileFeedFieldNames",
            (
                "Comma-separated FileFeedFieldNames (e.g. Filename). "
                "Sent as separate top-level request parameter per the "
                "FeedsGetRequest WSDL."
            ),
        ),
        (
            "--url-feed-field-names",
            "UrlFeedFieldNames",
            (
                "Comma-separated UrlFeedFieldNames (e.g. Login,Url,RemoveUtmTags). "
                "Sent as separate top-level request parameter per the "
                "FeedsGetRequest WSDL."
            ),
        ),
    ),
)


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
