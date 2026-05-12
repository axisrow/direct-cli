"""Yandex Direct v4 Live budget forecast commands."""

from typing import Optional

import click

from ..api import create_v4_client
from ..output import format_output, print_error
from ..utils import parse_csv_strings, parse_ids
from ..v4 import build_v4_body, call_v4
from ..v4_contracts import v4_method_contract
from .v4shells import V4_EPILOG


def _forecast_param(
    phrases: str, geo_ids: Optional[str], currency: str
) -> dict[str, object]:
    """Build the v4 Live CreateNewForecast parameter."""
    phrase_list = parse_csv_strings(phrases)
    if not phrase_list:
        raise click.UsageError("--phrases must not be empty")
    if len(phrase_list) > 100:
        raise click.UsageError("--phrases accepts at most 100 phrases")

    param: dict[str, object] = {
        "Phrases": phrase_list,
        "Currency": currency,
    }
    if geo_ids:
        try:
            parsed_geo_ids = parse_ids(geo_ids)
        except ValueError as exc:
            raise click.UsageError(str(exc)) from exc
        if parsed_geo_ids:
            param["GeoID"] = parsed_geo_ids
    return param


def _call_forecast(
    ctx,
    method: str,
    param,
    output_format: str,
    output: Optional[str],
) -> None:
    """Call one v4 Live budget forecast method and print formatted output."""
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
def v4forecast():
    """Yandex Direct v4 Live budget forecast commands."""


@v4_method_contract("CreateNewForecast")
@v4forecast.command()
@click.option("--phrases", required=True, help="Comma-separated phrases, up to 100")
@click.option("--geo-ids", help="Comma-separated geo region IDs")
@click.option(
    "--currency",
    default="RUB",
    show_default=True,
    help="Forecast currency",
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
def create(ctx, phrases, geo_ids, currency, output_format, output, dry_run):
    """Create a v4 Live budget forecast."""
    param = _forecast_param(phrases, geo_ids, currency)
    if dry_run:
        format_output(build_v4_body("CreateNewForecast", param), "json", None)
        return

    _call_forecast(ctx, "CreateNewForecast", param, output_format, output)


@v4_method_contract("GetForecastList")
@v4forecast.command(name="list")
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
def list_forecasts(ctx, output_format, output, dry_run):
    """List v4 Live budget forecasts."""
    if dry_run:
        format_output(build_v4_body("GetForecastList"), "json", None)
        return

    _call_forecast(ctx, "GetForecastList", None, output_format, output)


@v4_method_contract("GetForecast")
@v4forecast.command()
@click.option(
    "--forecast-id",
    required=True,
    type=click.IntRange(min=1),
    help="Forecast ID",
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
def get(ctx, forecast_id, output_format, output, dry_run):
    """Get a ready v4 Live budget forecast."""
    if dry_run:
        format_output(build_v4_body("GetForecast", forecast_id), "json", None)
        return

    _call_forecast(ctx, "GetForecast", forecast_id, output_format, output)


@v4_method_contract("DeleteForecastReport")
@v4forecast.command()
@click.option(
    "--forecast-id",
    required=True,
    type=click.IntRange(min=1),
    help="Forecast ID",
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
def delete(ctx, forecast_id, output_format, output, dry_run):
    """Delete a v4 Live budget forecast."""
    if dry_run:
        format_output(build_v4_body("DeleteForecastReport", forecast_id), "json", None)
        return

    _call_forecast(ctx, "DeleteForecastReport", forecast_id, output_format, output)
