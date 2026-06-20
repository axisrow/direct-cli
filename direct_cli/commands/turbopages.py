"""
TurboPages commands

NOTE: The Yandex Direct API ``turbopages`` service is read-only — it only
exposes ``get``.  Turbo pages themselves are created via the Yandex Direct
web UI and can only be referenced from the API (e.g. via ``TurboPageId`` in
sitelinks).  No ``add``/``update``/``delete`` methods exist on this service.
"""

import click

from ..api import create_client
from ..utils import parse_csv_strings, parse_ids
from ._get import make_get_command


@click.group()
def turbopages():
    """Manage Turbo Pages"""


def _turbopages_criteria(ids, bound_with_hrefs=None):
    criteria = {}
    if ids:
        criteria["Ids"] = parse_ids(ids)
    if bound_with_hrefs:
        criteria["BoundWithHrefs"] = parse_csv_strings(bound_with_hrefs) or []
    return criteria


get = make_get_command(
    turbopages,
    create_client,
    default_fields_key="turbopages",
    help_text="Get Turbo Pages",
    ids_help="Comma-separated Turbo Page IDs",
    extra_options=[
        click.option(
            "--bound-with-hrefs",
            help="Comma-separated hrefs bound with Turbo Pages",
        )
    ],
    criteria_builder=_turbopages_criteria,
)
