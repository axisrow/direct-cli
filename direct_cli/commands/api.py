"""API diagnostics commands.

``direct api units`` shows the remaining API units balance (#919). Yandex has
no dedicated "get units" method: the balance arrives in the HTTP ``Units``
header of every response, and the vendored client does not expose response
headers on success — so this command performs the lightest possible v5 call
(``clients get``) with ``requests`` directly and reads the header. Hosts come
from the endpoint registry, the resource path from ``RESOURCE_MAPPING_V5``.
"""

from typing import Any, Dict

import click
import requests

from .._vendor.tapi_yandex_direct.endpoints import get_direct_api_root
from .._vendor.tapi_yandex_direct.resource_mapping import RESOURCE_MAPPING_V5
from ..auth import get_credentials
from ..output import format_output, handle_api_errors
from ..utils import v4_output_options


@click.group()
def api():
    """API diagnostics: units balance, quota state"""


@api.command(name="units")
@v4_output_options
@click.pass_context
@handle_api_errors
def units(ctx, output_format, output, dry_run):
    """Show remaining API units (Units response header).

    Prints spent/left/limit parsed from the HTTP ``Units`` header of a live
    API response — the only place Yandex exposes the balance.
    """
    url = (
        get_direct_api_root({"is_sandbox": ctx.obj.get("sandbox")})
        + RESOURCE_MAPPING_V5["clients"]["resource"]
    )
    body: Dict[str, Any] = {
        "method": "get",
        "params": {"FieldNames": ["Login"]},
    }
    if dry_run:
        format_output({"url": url, "body": body}, output_format, output)
        return

    token, login = get_credentials(
        ctx.obj.get("token"),
        ctx.obj.get("login"),
        profile=ctx.obj.get("profile"),
    )
    headers = {
        "Authorization": "Bearer {}".format(token),
        "Content-Type": "application/json",
    }
    if login:
        headers["Client-Login"] = login
    response = requests.post(url, json=body, headers=headers, timeout=30)

    units_value = response.headers.get("Units", "")
    if not units_value:
        raise click.ClickException("API response has no Units header")
    if "error" in (response.json() if response.content else {}):
        error = response.json()["error"]
        raise click.ClickException(
            "API error {}: {} — Units: {}".format(
                error.get("error_code"), error.get("error_string"), units_value
            )
        )
    spent, left, limit = (int(part) for part in units_value.split("/"))
    format_output(
        {"spent": spent, "left": left, "limit": limit}, output_format, output
    )
