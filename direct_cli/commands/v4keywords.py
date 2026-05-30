"""Yandex Direct v4 Live keyword suggestion commands."""

from typing import Optional

import click

from ..api import create_v4_client
from ..i18n import t
from ..output import format_output, print_error
from ..v4 import build_v4_body, call_v4
from ..v4_contracts import v4_method_contract
from .v4shells import V4_EPILOG


def _keywords_param(keywords: tuple[str, ...]) -> dict:
    """Build the v4 Live GetKeywordsSuggestion parameter.

    Docs (dg-v4/reference/GetKeywordsSuggestion): param.Keywords is a UTF-8
    string array of seed phrases — the only documented field.
    """
    seeds = [kw.strip() for kw in keywords if kw and kw.strip()]
    if not seeds:
        raise click.UsageError(t("--keyword must not be empty"))
    return {"Keywords": seeds}


@click.group(epilog=V4_EPILOG)
def v4keywords():
    """Yandex Direct v4 Live keyword suggestion commands."""


@v4_method_contract("GetKeywordsSuggestion")
@v4keywords.command(name="get-suggestion")
@click.option(
    "--keyword",
    "keywords",
    multiple=True,
    required=True,
    help="Seed phrase; repeat for multiple phrases",
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
def get_suggestion(
    ctx,
    keywords: tuple[str, ...],
    output_format: str,
    output: Optional[str],
    dry_run: bool,
):
    """Suggest related keyword phrases for seed phrases.

    Returns up to 20 suggestion phrases. Consumes API points (error_code=152
    when insufficient).
    """
    param = _keywords_param(keywords)
    if dry_run:
        format_output(build_v4_body("GetKeywordsSuggestion", param), "json", None)
        return

    try:
        client = create_v4_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            profile=ctx.obj.get("profile"),
            sandbox=ctx.obj.get("sandbox"),
        )
        data = call_v4(client, "GetKeywordsSuggestion", param)
        format_output(data, output_format, output)
    except click.ClickException:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()
