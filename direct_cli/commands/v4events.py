"""Yandex Direct v4 Live events commands."""

import re
from datetime import datetime
from typing import Optional

import click

from ..api import create_v4_client
from ..i18n import t
from ..output import format_output, print_error
from ..utils import parse_csv_strings, parse_ids
from ..v4 import build_v4_body, call_v4
from ..v4_contracts import v4_method_contract
from .v4shells import V4_EPILOG

V4_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S"
V4_DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

# Documented GetEventsLogFilter.EventType enum (dg-v4/live/GetEventsLog).
EVENT_TYPES = [
    "BannerModerated",
    "CampaignFinished",
    "LowCTR",
    "MoneyOut",
    "MoneyWarning",
    "MoneyIn",
    "PausedByDayBudget",
    "WarnMinPrice",
    "WarnPlace",
]


def _events_log_filter(
    campaign_ids: Optional[str],
    banner_ids: Optional[str],
    phrase_ids: Optional[str],
    account_ids: Optional[str],
    event_type: Optional[str],
) -> Optional[dict]:
    """Build the GetEventsLogFilter object; None when no filter is provided."""
    filter_obj: dict = {}
    for option_name, raw, key in (
        ("--filter-campaign-ids", campaign_ids, "CampaignIDS"),
        ("--filter-banner-ids", banner_ids, "BannerIDS"),
        ("--filter-phrase-ids", phrase_ids, "PhraseIDS"),
        ("--filter-account-ids", account_ids, "AccountIDS"),
    ):
        if not raw:
            continue
        try:
            parsed = parse_ids(raw)
        except ValueError as exc:
            raise click.UsageError(
                t("{option_name}: {exc}").format(option_name=option_name, exc=exc)
            ) from exc
        if parsed:
            filter_obj[key] = parsed
    if event_type:
        types = parse_csv_strings(event_type)
        if types:
            unknown = [value for value in types if value not in EVENT_TYPES]
            if unknown:
                raise click.UsageError(
                    t(
                        "--filter-event-type has unknown values: {arg0}. Valid values: {arg1}"
                    ).format(arg0=", ".join(unknown), arg1=", ".join(EVENT_TYPES))
                )
            filter_obj["EventType"] = types
    return filter_obj or None


def _parse_v4_datetime(value: str, option_name: str) -> datetime:
    """Parse a strict v4 Live CLI datetime token."""
    if not V4_DATETIME_RE.fullmatch(value):
        raise click.UsageError(
            t("Invalid {option_name}: {value}. Expected YYYY-MM-DDTHH:MM:SS").format(
                option_name=option_name, value=value
            )
        )
    try:
        return datetime.strptime(value, V4_DATETIME_FORMAT)
    except ValueError:
        raise click.UsageError(
            t("Invalid {option_name}: {value}. Expected YYYY-MM-DDTHH:MM:SS").format(
                option_name=option_name, value=value
            )
        )


def _events_log_param(
    timestamp_from: str,
    timestamp_to: str,
    currency: str,
    limit: Optional[int],
    offset: Optional[int],
    last_event_only: Optional[str] = None,
    with_text_description: Optional[str] = None,
    logins: Optional[str] = None,
    campaign_ids: Optional[str] = None,
    banner_ids: Optional[str] = None,
    phrase_ids: Optional[str] = None,
    account_ids: Optional[str] = None,
    event_type: Optional[str] = None,
) -> dict:
    """Build the v4 Live GetEventsLog parameter."""
    from_dt = _parse_v4_datetime(timestamp_from, "--from")
    to_dt = _parse_v4_datetime(timestamp_to, "--to")
    if from_dt > to_dt:
        raise click.UsageError(t("--from must be earlier than or equal to --to"))

    param = {
        "TimestampFrom": timestamp_from,
        "TimestampTo": timestamp_to,
        "Currency": currency,
    }
    if last_event_only:
        param["LastEventOnly"] = last_event_only
    if with_text_description:
        param["WithTextDescription"] = with_text_description
    if logins:
        login_list = parse_csv_strings(logins)
        if login_list:
            param["Logins"] = login_list
    filter_obj = _events_log_filter(
        campaign_ids, banner_ids, phrase_ids, account_ids, event_type
    )
    if filter_obj is not None:
        param["Filter"] = filter_obj
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
@click.option(
    "--last-event-only",
    type=click.Choice(["Yes", "No"]),
    help="Return only the latest record per event type — Yes/No",
)
@click.option(
    "--with-text-description",
    type=click.Choice(["Yes", "No"]),
    help="Include event text descriptions in the response — Yes/No",
)
@click.option("--currency", default="RUB", show_default=True, help="Currency")
@click.option("--logins", help="Comma-separated client logins")
@click.option("--filter-campaign-ids", help="Filter: comma-separated campaign IDs")
@click.option("--filter-banner-ids", help="Filter: comma-separated banner IDs")
@click.option("--filter-phrase-ids", help="Filter: comma-separated phrase IDs")
@click.option("--filter-account-ids", help="Filter: comma-separated account IDs")
@click.option(
    "--filter-event-type",
    help="Filter: comma-separated event types (" + ", ".join(EVENT_TYPES) + ")",
)
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
    last_event_only,
    with_text_description,
    currency,
    logins,
    filter_campaign_ids,
    filter_banner_ids,
    filter_phrase_ids,
    filter_account_ids,
    filter_event_type,
    limit,
    offset,
    output_format,
    output,
    dry_run,
):
    """Get v4 Live events log entries."""
    param = _events_log_param(
        timestamp_from,
        timestamp_to,
        currency,
        limit,
        offset,
        last_event_only=last_event_only,
        with_text_description=with_text_description,
        logins=logins,
        campaign_ids=filter_campaign_ids,
        banner_ids=filter_banner_ids,
        phrase_ids=filter_phrase_ids,
        account_ids=filter_account_ids,
        event_type=filter_event_type,
    )
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
    except click.ClickException:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()
