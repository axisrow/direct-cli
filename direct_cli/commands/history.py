"""
``direct history`` — «История изменений» reader (issue #837).

Browser-backed, like ``direct masters``: the Direct API has no per-field
change journal at all (see ``direct_cli/browser/change_history.py``'s module
docstring for why ``changes.check``/``GetEventsLog`` cannot answer "who
changed this field, and to what"). This is a separate command group rather
than a ``masters`` subcommand because the section is account-wide — its
records cover ordinary ТГО/ЕПК campaigns, ad groups and ads just as much as
Мастера, and ``--campaign-ids`` is only a filter over that.

The session-resolution stack (``_open_session``/``_with_session``, the
``--headful``/``--profile-dir``/``--chrome-profile`` options and the
saved-session self-heal) is imported from ``commands/masters.py`` rather than
duplicated: none of it is Мастер-specific, and a second copy would drift.
"""

from typing import Optional

import click

from ..output import format_output, handle_api_errors
from ..utils import parse_ids
from .masters import _masters_browser_options, _with_session

# The API takes naive local datetimes (`2026-08-05T17:00:00`, confirmed
# live). The CLI accepts a plain calendar date and widens it to cover the
# whole day, which is what a user asking for "changes on the 5th" means.
_DAY_START_SUFFIX = "T00:00:00"
_DAY_END_SUFFIX = "T23:59:59"


def _to_datetime(value: Optional[str], suffix: str) -> Optional[str]:
    """Expand a ``YYYY-MM-DD`` date to the datetime the API expects.

    A value that already carries a time component is passed through
    unchanged, so an exact window can still be requested.
    """
    if value is None:
        return None
    return value if "T" in value else f"{value}{suffix}"


@click.group()
def history():
    """История изменений (change history) — browser-only, no API"""


@history.command(name="get")
@click.option(
    "--campaign-ids",
    help="Only records for these campaigns (comma-separated IDs)",
)
@click.option(
    "--date-from",
    help="Start of the period, YYYY-MM-DD (or YYYY-MM-DDTHH:MM:SS)",
)
@click.option(
    "--date-to",
    help="End of the period, YYYY-MM-DD (or YYYY-MM-DDTHH:MM:SS)",
)
@click.option(
    "--logins",
    help="Only changes made by these logins (comma-separated)",
)
@click.option(
    "--change-sources",
    help=(
        "Only changes from these sources, comma-separated (e.g. WEB, API, "
        "OTHER — the section's own vocabulary)"
    ),
)
@click.option(
    "--categories",
    help=(
        "Only these change categories, comma-separated (e.g. "
        "CAMPAIGN_STRATEGY). Default: every category the web interface "
        "itself requests."
    ),
)
@click.option(
    "--limit",
    type=int,
    help="Maximum number of records to return (default: all of them)",
)
@_masters_browser_options
@click.pass_context
@handle_api_errors
def get(
    ctx,
    campaign_ids,
    date_from,
    date_to,
    logins,
    change_sources,
    categories,
    limit,
    headful,
    profile_dir,
    chrome_profile,
    output_format,
    output,
):
    """Read the account's change history

    Returns one record per logged change, newest first, with the event's own
    fields under Event — including the oldStrategy/newStrategy pair that
    shows exactly which strategy goal or Metrika counter a change dropped.

    Without --date-from/--date-to the period the section itself defaults to
    is used. Every filter is applied server-side.
    """
    if limit is not None and limit <= 0:
        raise click.UsageError("--limit must be a positive integer")

    from ..browser.change_history import fetch_change_history

    parsed_campaign_ids = parse_ids(campaign_ids)
    parsed_logins = _split_csv(logins)
    parsed_sources = _split_csv(change_sources)
    parsed_categories = _split_csv(categories)

    result = _with_session(
        ctx,
        headful,
        profile_dir,
        chrome_profile,
        lambda page: fetch_change_history(
            page,
            campaign_ids=parsed_campaign_ids,
            date_from=_to_datetime(date_from, _DAY_START_SUFFIX),
            date_to=_to_datetime(date_to, _DAY_END_SUFFIX),
            categories=parsed_categories,
            logins=parsed_logins,
            change_sources=parsed_sources,
            limit=limit,
        ),
    )

    format_output(result, output_format, output)


def _split_csv(value: Optional[str]) -> Optional[list]:
    """Parse a comma-separated option into a list, or None if unset.

    ``None`` (option absent) and an explicit empty string differ: the former
    leaves the captured request's own value in place, which for
    ``categories`` is the 44-entry list the web interface sends. Returning
    ``[]`` for an empty string would instead filter everything out.
    """
    if value is None:
        return None
    items = [part.strip() for part in value.split(",")]
    return [item for item in items if item]
