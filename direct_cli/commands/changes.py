"""
Changes commands
"""

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import get_default_fields, parse_changes_datetime, parse_ids


@click.group()
def changes():
    """Check for changes"""


_CHECK_FIELD_NAMES = frozenset({"CampaignIds", "AdGroupIds", "AdIds", "CampaignsStat"})


@changes.command()
@click.option(
    "--campaign-ids",
    help="Comma-separated campaign IDs (up to 3000). Mutually exclusive with "
    "--ad-group-ids and --ad-ids.",
)
@click.option(
    "--ad-group-ids",
    help="Comma-separated ad group IDs (up to 10000). Mutually exclusive with "
    "--campaign-ids and --ad-ids.",
)
@click.option(
    "--ad-ids",
    help="Comma-separated ad IDs (up to 50000). Mutually exclusive with "
    "--campaign-ids and --ad-group-ids.",
)
@click.option(
    "--timestamp",
    required=True,
    help="Timestamp for Changes.check (YYYY-MM-DDTHH:MM:SSZ)",
)
@click.option(
    "--fields",
    help="Comma-separated FieldNames; allowed values: "
    "CampaignIds, AdGroupIds, AdIds, CampaignsStat. "
    "Defaults to all four when omitted.",
)
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.pass_context
def check(
    ctx, campaign_ids, ad_group_ids, ad_ids, timestamp, fields, output_format, output
):
    """Check changes for campaigns, ad groups, or ads.

    Exactly one of --campaign-ids, --ad-group-ids, --ad-ids must be provided —
    the Yandex Direct ``Changes.check`` method declares these three filters as
    mutually exclusive.
    """
    sources_used = (
        (1 if campaign_ids else 0) + (1 if ad_group_ids else 0) + (1 if ad_ids else 0)
    )
    if sources_used == 0:
        raise click.UsageError(
            "Provide exactly one of: --campaign-ids, --ad-group-ids, --ad-ids."
        )
    if sources_used > 1:
        raise click.UsageError(
            "--campaign-ids, --ad-group-ids, and --ad-ids are mutually "
            "exclusive — provide exactly one."
        )

    if fields:
        field_names = [f.strip() for f in fields.split(",") if f.strip()]
        if not field_names:
            raise click.UsageError(
                "--fields produced an empty list; provide at least one of: "
                f"{', '.join(sorted(_CHECK_FIELD_NAMES))}."
            )
        unknown = [f for f in field_names if f not in _CHECK_FIELD_NAMES]
        if unknown:
            raise click.UsageError(
                "Unknown --fields value(s): "
                f"{', '.join(unknown)}. Allowed: "
                f"{', '.join(sorted(_CHECK_FIELD_NAMES))}."
            )
    else:
        field_names = get_default_fields("changes")

    if campaign_ids:
        id_field, id_flag, id_raw = "CampaignIds", "--campaign-ids", campaign_ids
    elif ad_group_ids:
        id_field, id_flag, id_raw = "AdGroupIds", "--ad-group-ids", ad_group_ids
    else:
        id_field, id_flag, id_raw = "AdIds", "--ad-ids", ad_ids
    try:
        id_value = parse_ids(id_raw)
    except ValueError as exc:
        raise click.UsageError(f"{id_flag}: {exc}")
    if not id_value:
        raise click.UsageError(f"{id_flag} produced no valid IDs.")

    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        params = {
            id_field: id_value,
            "Timestamp": parse_changes_datetime(timestamp),
            "FieldNames": field_names,
        }

        body = {"method": "check", "params": params}

        result = client.changes().post(data=body)
        format_output(result.data, output_format, output)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@changes.command()
@click.option(
    "--timestamp",
    required=True,
    help="Timestamp for Changes.checkCampaigns (YYYY-MM-DDTHH:MM:SSZ)",
)
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.pass_context
def check_campaigns(ctx, timestamp, output_format, output):
    """Check campaigns changes"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        params = {"Timestamp": parse_changes_datetime(timestamp)}

        body = {"method": "checkCampaigns", "params": params}

        result = client.changes().post(data=body)
        format_output(result.data, output_format, output)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@changes.command()
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.pass_context
def check_dictionaries(ctx, output_format, output):
    """Check dictionaries changes"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        body = {"method": "checkDictionaries", "params": {}}

        result = client.changes().post(data=body)
        format_output(result.data, output_format, output)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()
