"""Yandex Direct v4 Live budget forecast commands."""

from typing import Optional

import click

from ..i18n import t
from ..utils import parse_csv_strings, parse_ids
from ..v4.emit import emit_or_call_v4
from ..v4_contracts import v4_method_contract
from .v4shells import V4_EPILOG


def _forecast_param(
    phrases: str,
    geo_ids: Optional[str],
    currency: str,
    categories: Optional[str] = None,
    auction_bids: Optional[str] = None,
    common_minus_words: Optional[str] = None,
) -> dict[str, object]:
    """Build the v4 Live CreateNewForecast parameter."""
    phrase_list = parse_csv_strings(phrases)
    if not phrase_list:
        raise click.UsageError(t("--phrases must not be empty"))
    if len(phrase_list) > 100:
        raise click.UsageError(t("--phrases accepts at most 100 phrases"))

    param: dict[str, object] = {
        "Phrases": phrase_list,
        "Currency": currency,
    }
    if categories:
        try:
            parsed_categories = parse_ids(categories)
        except ValueError as exc:
            raise click.UsageError(str(exc)) from exc
        if parsed_categories:
            param["Categories"] = parsed_categories
    if geo_ids:
        try:
            parsed_geo_ids = parse_ids(geo_ids)
        except ValueError as exc:
            raise click.UsageError(str(exc)) from exc
        if parsed_geo_ids:
            param["GeoID"] = parsed_geo_ids
    if auction_bids:
        param["AuctionBids"] = auction_bids
    if common_minus_words:
        minus_words = parse_csv_strings(common_minus_words)
        if minus_words:
            param["CommonMinusWords"] = minus_words
    return param


@click.group(epilog=V4_EPILOG)
def v4forecast():
    """Yandex Direct v4 Live budget forecast commands."""


@v4_method_contract("CreateNewForecast")
@v4forecast.command()
@click.option("--phrases", required=True, help="Comma-separated phrases, up to 100")
@click.option(
    "--categories",
    help="Comma-separated Yandex Catalog category IDs (ignored by the API per docs)",
)
@click.option("--geo-ids", help="Comma-separated geo region IDs")
@click.option(
    "--currency",
    default="RUB",
    show_default=True,
    help="Forecast currency",
)
@click.option(
    "--auction-bids",
    type=click.Choice(["Yes", "No"]),
    help="Include auction results in the report — Yes/No (API default: No)",
)
@click.option(
    "--common-minus-words",
    help="Comma-separated common negative keywords",
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
def create(
    ctx,
    phrases,
    categories,
    geo_ids,
    currency,
    auction_bids,
    common_minus_words,
    output_format,
    output,
    dry_run,
):
    """Create a v4 Live budget forecast."""
    param = _forecast_param(
        phrases,
        geo_ids,
        currency,
        categories=categories,
        auction_bids=auction_bids,
        common_minus_words=common_minus_words,
    )
    emit_or_call_v4(ctx, "CreateNewForecast", param, dry_run, output_format, output)


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
    emit_or_call_v4(ctx, "GetForecastList", None, dry_run, output_format, output)


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
    emit_or_call_v4(ctx, "GetForecast", forecast_id, dry_run, output_format, output)


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
    emit_or_call_v4(
        ctx, "DeleteForecastReport", forecast_id, dry_run, output_format, output
    )
