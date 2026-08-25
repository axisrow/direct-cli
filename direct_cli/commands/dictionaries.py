"""
Dictionaries commands
"""

import click

from ..api import client_from_ctx, create_client
from ..i18n import resolve_locale, t
from ..output import format_output, handle_api_errors
from ..utils import parse_csv_strings, parse_ids, reference_output_options

DICTIONARY_NAMES = [
    "Currencies",
    "MetroStations",
    "GeoRegions",
    "TimeZones",
    "Constants",
    "AdCategories",
    "OperationSystemVersions",
    "ProductivityAssertions",
    "SupplySidePlatforms",
    "Interests",
]


@click.group()
def dictionaries():
    """Get reference dictionaries"""


@dictionaries.command()
@click.option(
    "--names",
    required=True,
    help="Comma-separated dictionary names (Currencies,GeoRegions,...)",
)
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.pass_context
@handle_api_errors
def get(ctx, names, output_format, output):
    """Get dictionaries"""
    client = client_from_ctx(ctx, create_client)

    dictionary_names = parse_csv_strings(names)

    body = {"method": "get", "params": {"DictionaryNames": dictionary_names}}

    result = client.dictionaries().post(data=body)
    format_output(result.data, output_format, output)


@dictionaries.command(name="get-geo-regions")
@click.option("--name", help="Geo region name contains this value")
@click.option("--region-ids", help="Comma-separated geo region IDs")
@click.option("--exact-names", help="Comma-separated exact geo region names")
@click.option("--fields", required=True, help="Comma-separated field names")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.pass_context
@handle_api_errors
def get_geo_regions(ctx, name, region_ids, exact_names, fields, output_format, output):
    """Get GeoRegions dictionary entries"""
    client = create_client(
        token=ctx.obj.get("token"),
        login=ctx.obj.get("login"),
        sandbox=ctx.obj.get("sandbox"),
        language=resolve_locale(ctx),
    )

    params = {"FieldNames": parse_csv_strings(fields)}
    selection_criteria = {}
    if name:
        selection_criteria["Name"] = name
    if region_ids:
        selection_criteria["RegionIds"] = parse_ids(region_ids)
    if exact_names:
        selection_criteria["ExactNames"] = parse_csv_strings(exact_names)
    if selection_criteria:
        params["SelectionCriteria"] = selection_criteria

    body = {"method": "getGeoRegions", "params": params}

    result = client.dictionaries().post(data=body)
    format_output(result.data, output_format, output)


RETARGETING_GOALS_FIELDS = [
    "Id",
    "Name",
    "Type",
    "Description",
    "CoverageType",
    "SuggestionSource",
    "StoreLink",
]


@dictionaries.command(name="get-retargeting-goals")
@click.option("--name", help="Retargeting goal name to search for (e.g. a domain)")
@click.option("--ids", help="Comma-separated retargeting goal IDs to look up")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.pass_context
@handle_api_errors
def get_retargeting_goals(ctx, name, ids, output_format, output):
    """Get RetargetingGoals dictionary entries (undocumented/internal v5 method)

    Resolves a site address or app name into the ExternalId used by
    RetargetingList(Type=AUDIENCE) -> Rules[].Arguments[].ExternalId. Yandex
    does not document this method and gives no stability guarantees for it.

    A search by --name can return multiple goal types with similar names
    (e.g. Type=HOST and Type=APPLICATION) -- pick the entry with the Type
    your use case needs.
    """
    if bool(name) == bool(ids):
        raise click.UsageError(t("Exactly one of --name or --ids is required"))

    client = client_from_ctx(ctx, create_client)

    selection_criteria = {}
    if name:
        selection_criteria["Name"] = name
    else:
        selection_criteria["Ids"] = {"Items": parse_ids(ids)}

    body = {
        "method": "getRetargetingGoals",
        "params": {
            "FieldNames": RETARGETING_GOALS_FIELDS,
            "SelectionCriteria": selection_criteria,
        },
    }

    result = client.dictionaries().post(data=body)
    format_output(result.data, output_format, output)


@dictionaries.command()
@reference_output_options
def list_names(output_format, output):
    """List available dictionary names"""
    format_output(DICTIONARY_NAMES, output_format, output)
