"""Yandex Direct v4 Live Wordstat report commands."""

from typing import Optional

import click

from ..api import create_v4_client
from ..output import format_output, print_error
from ..utils import parse_csv_strings, parse_ids
from ..v4 import build_v4_body, call_v4
from ..v4_contracts import v4_method_contract
from .v4shells import V4_EPILOG


def _wordstat_report_param(phrases: str, geo_ids: Optional[str]) -> dict:
    """Build the v4 Live CreateNewWordstatReport parameter."""
    phrase_list = parse_csv_strings(phrases)
    if not phrase_list:
        raise click.UsageError("--phrases must not be empty")
    if len(phrase_list) > 10:
        raise click.UsageError("--phrases accepts at most 10 phrases")

    param = {"Phrases": phrase_list}
    if geo_ids:
        try:
            parsed_geo_ids = parse_ids(geo_ids)
        except ValueError as exc:
            raise click.UsageError(str(exc)) from exc
        if parsed_geo_ids:
            param["GeoID"] = parsed_geo_ids
    return param


def _call_wordstat(
    ctx,
    method: str,
    param,
    output_format: str,
    output: Optional[str],
) -> None:
    """Call one v4 Live Wordstat method and print formatted output."""
    try:
        client = create_v4_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            profile=ctx.obj.get("profile"),
            sandbox=ctx.obj.get("sandbox"),
        )
        data = call_v4(client, method, param)
        format_output(data, output_format, output)
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@click.group(epilog=V4_EPILOG)
def v4wordstat():
    """Yandex Direct v4 Live Wordstat report commands."""


@v4_method_contract("CreateNewWordstatReport")
@v4wordstat.command(name="create-report")
@click.option("--phrases", required=True, help="Comma-separated phrases, up to 10")
@click.option("--geo-ids", help="Comma-separated geo region IDs")
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
def create_report(ctx, phrases, geo_ids, output_format, output, dry_run):
    """Create a v4 Live Wordstat report."""
    param = _wordstat_report_param(phrases, geo_ids)
    if dry_run:
        format_output(build_v4_body("CreateNewWordstatReport", param), "json", None)
        return

    _call_wordstat(ctx, "CreateNewWordstatReport", param, output_format, output)


@v4_method_contract("GetWordstatReportList")
@v4wordstat.command(name="list-reports")
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
def list_reports(ctx, output_format, output, dry_run):
    """List v4 Live Wordstat reports."""
    if dry_run:
        format_output(build_v4_body("GetWordstatReportList"), "json", None)
        return

    _call_wordstat(ctx, "GetWordstatReportList", None, output_format, output)


@v4_method_contract("GetWordstatReport")
@v4wordstat.command(name="get-report")
@click.option(
    "--report-id",
    required=True,
    type=click.IntRange(min=1),
    help="Wordstat report ID",
)
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
def get_report(ctx, report_id, output_format, output, dry_run):
    """Get a ready v4 Live Wordstat report."""
    if dry_run:
        format_output(build_v4_body("GetWordstatReport", report_id), "json", None)
        return

    _call_wordstat(ctx, "GetWordstatReport", report_id, output_format, output)


@v4_method_contract("DeleteWordstatReport")
@v4wordstat.command(name="delete-report")
@click.option(
    "--report-id",
    required=True,
    type=click.IntRange(min=1),
    help="Wordstat report ID",
)
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
def delete_report(ctx, report_id, output_format, output, dry_run):
    """Delete a v4 Live Wordstat report."""
    if dry_run:
        format_output(build_v4_body("DeleteWordstatReport", report_id), "json", None)
        return

    _call_wordstat(ctx, "DeleteWordstatReport", report_id, output_format, output)
