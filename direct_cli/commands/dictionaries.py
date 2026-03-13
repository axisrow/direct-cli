"""
Dictionaries commands
"""

import click

from ..api import create_client
from ..output import format_output, print_error

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
def get(ctx, names, output_format, output):
    """Get dictionaries"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        dictionary_names = [n.strip() for n in names.split(",")]

        body = {"method": "get", "params": {"DictionaryNames": dictionary_names}}

        result = client.dictionaries().post(data=body)
        format_output(result.data, output_format, output)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@dictionaries.command()
def list_names():
    """List available dictionary names"""
    format_output(DICTIONARY_NAMES, "json", None)
