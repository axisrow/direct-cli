"""
Businesses commands
"""

import click

from ..api import create_client
from ._get import make_get_command


@click.group()
def businesses():
    """Manage businesses"""


get = make_get_command(
    businesses,
    create_client,
    default_fields_key="businesses",
    help_text="Get businesses",
    ids_help="Comma-separated business IDs",
)
