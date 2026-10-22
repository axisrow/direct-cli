"""
``direct ad-elements`` — per-element ad restrictions from the web UI (issue #892).

Browser-backed like ``direct masters``/``direct history``: the Direct API
has no per-element display-restriction surface (see
``direct_cli/browser/ad_elements.py``'s module docstring — categories are
assigned at moderation and their regional display restrictions are not
modelled per element anywhere in the WSDL), so the only place the
«какой элемент и по какой причине» data exists is the web interface's own
banners-grid data calls.

A single top-level command rather than a ``masters``/``ads`` subcommand:
the banners grid serves ordinary campaigns (ТГО/ЕПК/перфоманс) just as much
as Мастера, and ``ads`` is the API group — this read shares nothing with it.
The session-resolution stack is imported from ``commands/masters.py`` (same
rationale as ``commands/history.py``).
"""

import click

from ..output import format_output, handle_api_errors
from ..utils import parse_ids
from .masters import _masters_browser_options, _with_session


@click.command(name="adrestrictions")
@click.argument("campaign_id", type=int)
@click.option(
    "--group-ids",
    help="Only these ad groups (comma-separated IDs); default: all the page loads",
)
@_masters_browser_options
@click.pass_context
@handle_api_errors
def ad_elements(
    ctx,
    campaign_id,
    group_ids,
    headful,
    profile_dir,
    chrome_profile,
    output_format,
    output,
):
    """Read a campaign's ads element-by-element with their UI restrictions

    Opens the web UI's banners grid for the campaign and reads its own data
    calls (ads:list + AdDisclaimers + ads:batchGet): every headline, text,
    image and video of every ad, each with the ad's restriction warnings —
    the machine reason (moderation flags, aggregated-status reasons) and
    the UI's verbatim explanation (the «Добавлено предупреждение» popup
    texts, e.g. the «Медицина и фармацевтика» category notice).

    The warning granularity is the ad — that is what the UI's own popup
    shows and what its data calls carry; a per-headline split does not
    exist in any data surface (issue #892).
    """
    from ..browser.ad_elements import fetch_ad_elements

    group_id_list = parse_ids(group_ids) if group_ids else None

    result = _with_session(
        ctx,
        headful,
        profile_dir,
        chrome_profile,
        lambda page: fetch_ad_elements(page, campaign_id, group_ids=group_id_list),
    )
    format_output(result, output_format, output)
