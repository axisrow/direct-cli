"""Shell command groups for Yandex Direct v4 Live command families."""

import click

from ..v4.emit import emit_or_call_v4
from ..v4_contracts import v4_method_contract

V4_EPILOG = (
    "\b\n"
    "V4 Live commands use typed flags only. Supported methods are listed in "
    "the Yandex Direct v4 Live documentation: "
    "https://yandex.com/dev/direct/doc/dg-v4/en/live/concepts"
)


@click.group(epilog=V4_EPILOG)
def v4wordstat():
    """Yandex Direct v4 Live wordstat commands."""


@click.group(epilog=V4_EPILOG)
def v4meta():
    """Yandex Direct v4 Live metadata commands."""


# No-param v4 Live metadata methods. Each row is (CLI name, RPC method, help).
# The help strings are i18n catalog keys (see translations/v4shells.json).
_META_COMMANDS = (
    ("ping-api", "PingAPI", "Ping the v4 Live API."),
    ("ping-api-x", "PingAPI_X", "Ping the v4 Live API extended endpoint."),
    ("get-version", "GetVersion", "Get the v4 Live API version."),
    (
        "get-available-versions",
        "GetAvailableVersions",
        "Get available v4 Live API versions.",
    ),
)


def _register_meta_command(name, method, help_text):
    """Build and register a no-param v4 Live metadata command on v4meta."""

    @v4meta.command(name=name, help=help_text)
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
    def _command(ctx, output_format, output, dry_run):
        emit_or_call_v4(ctx, method, None, dry_run, output_format, output)

    return v4_method_contract(method)(_command)


for _name, _method, _help in _META_COMMANDS:
    _register_meta_command(_name, _method, _help)
