"""Yandex Direct v4 Live Wordstat report commands."""

from typing import Optional

import click

from ..i18n import t
from ..utils import parse_csv_strings, parse_ids, v4_output_options
from ..v4.emit import emit_or_call_v4
from ..v4_contracts import v4_method_contract
from .v4shells import V4_EPILOG


def _wordstat_report_param(phrases: str, geo_ids: Optional[str]) -> dict:
    """Build the v4 Live CreateNewWordstatReport parameter."""
    phrase_list = parse_csv_strings(phrases)
    if not phrase_list:
        raise click.UsageError(t("--phrases must not be empty"))
    if len(phrase_list) > 10:
        raise click.UsageError(t("--phrases accepts at most 10 phrases"))

    param = {"Phrases": phrase_list}
    if geo_ids:
        try:
            parsed_geo_ids = parse_ids(geo_ids)
        except ValueError as exc:
            raise click.UsageError(str(exc)) from exc
        if parsed_geo_ids:
            param["GeoID"] = parsed_geo_ids
    return param


@click.group(epilog=V4_EPILOG)
def v4wordstat():
    """Yandex Direct v4 Live Wordstat report commands."""


@v4_method_contract("CreateNewWordstatReport")
@v4wordstat.command(name="create-report")
@click.option("--phrases", required=True, help="Comma-separated phrases, up to 10")
@click.option("--geo-ids", help="Comma-separated geo region IDs")
@v4_output_options
@click.pass_context
def create_report(ctx, phrases, geo_ids, output_format, output, dry_run):
    """Create a v4 Live Wordstat report."""
    param = _wordstat_report_param(phrases, geo_ids)
    emit_or_call_v4(
        ctx, "CreateNewWordstatReport", param, dry_run, output_format, output
    )


@v4_method_contract("GetWordstatReportList")
@v4wordstat.command(name="list-reports")
@v4_output_options
@click.pass_context
def list_reports(ctx, output_format, output, dry_run):
    """List v4 Live Wordstat reports."""
    emit_or_call_v4(ctx, "GetWordstatReportList", None, dry_run, output_format, output)


@v4_method_contract("GetWordstatReport")
@v4wordstat.command(name="get-report")
@click.option(
    "--report-id",
    required=True,
    type=click.IntRange(min=1),
    help="Wordstat report ID",
)
@v4_output_options
@click.pass_context
def get_report(ctx, report_id, output_format, output, dry_run):
    """Get a ready v4 Live Wordstat report."""
    emit_or_call_v4(ctx, "GetWordstatReport", report_id, dry_run, output_format, output)


@v4_method_contract("DeleteWordstatReport")
@v4wordstat.command(name="delete-report")
@click.option(
    "--report-id",
    required=True,
    type=click.IntRange(min=1),
    help="Wordstat report ID",
)
@v4_output_options
@click.pass_context
def delete_report(ctx, report_id, output_format, output, dry_run):
    """Delete a v4 Live Wordstat report."""
    emit_or_call_v4(
        ctx, "DeleteWordstatReport", report_id, dry_run, output_format, output
    )
