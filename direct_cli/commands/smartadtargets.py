"""
SmartAdTargets commands
"""

import json
import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import parse_ids


@click.group()
def smartadtargets():
    """Manage smart ad targets"""


@smartadtargets.command()
@click.option("--ids", help="Comma-separated target IDs")
@click.option("--adgroup-ids", help="Comma-separated ad group IDs")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.pass_context
def get(ctx, ids, adgroup_ids, limit, fetch_all, output_format, output, fields):
    """Get smart ad targets"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        field_names = (
            fields.split(",")
            if fields
            else ["Id", "CampaignId", "AdGroupId", "Status", "ServingStatus"]
        )

        criteria = {}
        if ids:
            criteria["Ids"] = parse_ids(ids)
        if adgroup_ids:
            criteria["AdGroupIds"] = parse_ids(adgroup_ids)

        params = {"SelectionCriteria": criteria, "FieldNames": field_names}

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        result = client.smartadtargets().post(data=body)

        if fetch_all:
            items = []
            for item in result().iter_items():
                items.append(item)
            format_output(items, output_format, output)
        else:
            data = result().extract()
            format_output(data, output_format, output)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@smartadtargets.command()
@click.option("--adgroup-id", required=True, type=int, help="Ad group ID")
@click.option(
    "--type",
    "target_type",
    help=(
        "Legacy UX hint; NOT forwarded to the API. SmartAdTargetAddItem "
        "has no top-level Type field — pass real fields like "
        "``TargetingId`` (e.g. 'VIEWED_PRODUCT'), ``Bid`` and "
        "``Priority`` via --json instead."
    ),
)
@click.option("--json", "extra_json", help="Additional JSON parameters")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(ctx, adgroup_id, target_type, extra_json, dry_run):
    """Add smart ad target"""
    try:
        # SmartAdTargetAddItem in the Yandex Direct API does NOT have a
        # top-level "Type" field. Real fields are AdGroupId, TargetingId
        # (e.g. "VIEWED_PRODUCT"), Bid, Priority. The legacy --type CLI
        # option was previously ``required=True`` but immediately discarded
        # — actively hostile UX. It is now optional, documented as a
        # legacy hint, and not forwarded. See axisrow/direct-cli#23.
        target_data = {"AdGroupId": adgroup_id}
        _ = target_type  # intentionally unused — kept as UX hint only

        if extra_json:
            extra = json.loads(extra_json)
            target_data.update(extra)

        # Without real fields from --json the payload would only contain
        # AdGroupId, which the API rejects with an opaque "required field
        # missing" error.  Fail early and tell the user what's missing.
        if len(target_data) == 1:
            raise click.UsageError(
                "Provide --json with SmartAdTargetAddItem fields "
                '(e.g. \'{"TargetingId":"VIEWED_PRODUCT"}\').'
            )

        body = {"method": "add", "params": {"SmartAdTargets": [target_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.smartadtargets().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@smartadtargets.command()
@click.option("--id", "target_id", required=True, type=int, help="Target ID")
@click.option(
    "--type",
    "target_type",
    help=(
        "Legacy UX hint; NOT forwarded to the API. SmartAdTargetAddItem "
        "has no top-level Type field — pass real fields via --json."
    ),
)
@click.option("--json", "extra_json", help="Additional JSON parameters")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def update(ctx, target_id, target_type, extra_json, dry_run):
    """Update smart ad target"""
    try:
        target_data = {"Id": target_id}

        # See note in `add` above — Type is not a real field on
        # SmartAdTargetAddItem; the legacy --type CLI option is kept
        # for backward compatibility but no longer forwarded.
        _ = target_type  # intentionally unused — kept as UX hint only
        if extra_json:
            extra = json.loads(extra_json)
            target_data.update(extra)
        if len(target_data) == 1:
            raise click.UsageError("Provide --json with fields to update")

        body = {"method": "update", "params": {"SmartAdTargets": [target_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.smartadtargets().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@smartadtargets.command()
@click.option("--id", "target_id", required=True, type=int, help="Target ID")
@click.pass_context
def delete(ctx, target_id):
    """Delete smart ad target"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        body = {
            "method": "delete",
            "params": {"SelectionCriteria": {"Ids": [target_id]}},
        }

        result = client.smartadtargets().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


smartadtargets.add_command(get, name="list")
