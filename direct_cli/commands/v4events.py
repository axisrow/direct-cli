"""Yandex Direct v4 Live events commands."""

import re
from datetime import datetime
from typing import Optional

import click

from ..api import create_v4_client
from ..output import format_output, print_error
from ..v4 import build_v4_body, call_v4
from ..v4_contracts import v4_method_contract
from .v4shells import V4_EPILOG

V4_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S"
V4_DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _parse_v4_datetime(value: str, option_name: str) -> datetime:
    """Parse a strict v4 Live CLI datetime token."""
    if not V4_DATETIME_RE.fullmatch(value):
        raise click.UsageError(
            f"Invalid {option_name}: {value}. Expected YYYY-MM-DDTHH:MM:SS"
        )
    try:
        return datetime.strptime(value, V4_DATETIME_FORMAT)
    except ValueError:
        raise click.UsageError(
            f"Invalid {option_name}: {value}. Expected YYYY-MM-DDTHH:MM:SS"
        )


def _events_log_param(
    timestamp_from: str,
    timestamp_to: str,
    currency: str,
    limit: Optional[int],
    offset: Optional[int],
) -> dict:
    """Build the v4 Live GetEventsLog parameter."""
    from_dt = _parse_v4_datetime(timestamp_from, "--from")
    to_dt = _parse_v4_datetime(timestamp_to, "--to")
    if from_dt > to_dt:
        raise click.UsageError("--from must be earlier than or equal to --to")

    param = {
        "TimestampFrom": timestamp_from,
        "TimestampTo": timestamp_to,
        "Currency": currency,
    }
    if limit is not None:
        param["Limit"] = limit
    if offset is not None:
        param["Offset"] = offset
    return param


@click.group(epilog=V4_EPILOG)
def v4events():
    """Yandex Direct v4 Live events commands."""


@v4_method_contract("GetEventsLog")
@v4events.command(name="get-events-log")
@click.option(
    "--from",
    "timestamp_from",
    required=True,
    help="Start timestamp in YYYY-MM-DDTHH:MM:SS format",
)
@click.option(
    "--to",
    "timestamp_to",
    required=True,
    help="End timestamp in YYYY-MM-DDTHH:MM:SS format",
)
@click.option("--currency", default="RUB", show_default=True, help="Currency")
@click.option("--limit", type=click.IntRange(min=0), help="Result limit")
@click.option("--offset", type=click.IntRange(min=0), help="Result offset")
@click.option(
    "--format",
    "output_format",
    default="json",
    type=click.Choice(["json", "table", "csv", "tsv"]),
    help="Output format",
)
@click.option("--output", help="Output file")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def get_events_log(
    ctx,
    timestamp_from,
    timestamp_to,
    currency,
    limit,
    offset,
    output_format,
    output,
    dry_run,
):
    """Get v4 Live events log entries."""
    param = _events_log_param(timestamp_from, timestamp_to, currency, limit, offset)
    if dry_run:
        format_output(build_v4_body("GetEventsLog", param), "json", None)
        return

    try:
        client = create_v4_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            profile=ctx.obj.get("profile"),
            sandbox=ctx.obj.get("sandbox"),
        )
        data = call_v4(client, "GetEventsLog", param)
        format_output(data, output_format, output)
    except Exception as e:
        print_error(str(e))
        raise click.Abort()
