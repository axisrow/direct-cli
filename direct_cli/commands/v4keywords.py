"""Yandex Direct v4 Live keyword suggestion commands."""

from typing import Optional

import click

from ..i18n import t
from ..output import handle_api_errors
from ..v4.emit import emit_or_call_v4
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
@handle_api_errors
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
    emit_or_call_v4(ctx, "GetKeywordsSuggestion", param, dry_run, output_format, output)
