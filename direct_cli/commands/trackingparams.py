"""
Tracking parameters reference command (local, no API call).
"""

import click

from ..output import format_output
from ..tracking_params import TRACKING_PARAMS, TRACKING_PARAMS_DOCS_URL


@click.command(
    name="trackingparams",
    epilog=f"\b\nDocumentation: {TRACKING_PARAMS_DOCS_URL}",
)
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
def tracking_params(output_format, output):
    """Dynamic tracking parameters reference (UTM template placeholders).

    Подстановочные переменные Яндекс Директа для ссылок/UTM-меток:
    {campaign_id}, {keyword}, {source_type} и т.п. Подставляются в URL
    объявления (включая UTM-метки) в момент клика.
    """
    format_output(TRACKING_PARAMS, output_format, output)
