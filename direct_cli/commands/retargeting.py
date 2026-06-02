"""
RetargetingLists commands
"""

from typing import Optional

import click

from ..api import client_from_ctx, create_client
from ..i18n import t
from ..output import format_output, print_error
from ..utils import get_default_fields, parse_ids, parse_retargeting_rule_specs


@click.group()
def retargeting():
    """Manage retargeting lists"""


@retargeting.command()
@click.option("--ids", help="Comma-separated list IDs")
@click.option("--types", help="Filter by types")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.pass_context
def get(ctx, ids, types, limit, fetch_all, output_format, output, fields):
    """Get retargeting lists"""
    try:
        client = client_from_ctx(ctx, create_client)

        field_names = (
            fields.split(",") if fields else get_default_fields("retargetinglists")
        )

        criteria = {}
        if ids:
            criteria["Ids"] = parse_ids(ids)
        if types:
            criteria["Types"] = types.split(",")

        params = {"SelectionCriteria": criteria, "FieldNames": field_names}

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        result = client.retargeting().post(data=body)

        if fetch_all:
            items = []
            for item in result().iter_items():
                items.append(item)
            format_output(items, output_format, output)
        else:
            data = result().extract()
            format_output(data, output_format, output)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


_RETARGETING_LIST_TYPES = ["RETARGETING", "AUDIENCE"]
_RETARGETING_DESCRIPTION_MAX_LENGTH = 4096


def _validate_description(description: Optional[str]) -> None:
    """Validate RetargetingList*.Description documented API constraints."""
    if (
        description is not None
        and len(description) > _RETARGETING_DESCRIPTION_MAX_LENGTH
    ):
        raise click.UsageError(
            t(
                "--description must be at most {_RETARGETING_DESCRIPTION_MAX_LENGTH} characters"
            ).format(
                _RETARGETING_DESCRIPTION_MAX_LENGTH=_RETARGETING_DESCRIPTION_MAX_LENGTH
            )
        )


@retargeting.command()
@click.option("--name", required=True, help="List name")
@click.option(
    "--description",
    help=(
        "Retargeting list description for RetargetingListAddItem.Description "
        "(max 4096 chars)"
    ),
)
@click.option(
    "--type",
    "list_type",
    default="RETARGETING",
    type=click.Choice(_RETARGETING_LIST_TYPES, case_sensitive=False),
    help=(
        "Retargeting list type (case-insensitive). Yandex Direct accepts "
        "only RETARGETING (default — Metrica goals/segments + Audience "
        "segments, usable in text & image / mobile-app campaigns) or "
        "AUDIENCE (any goals/segments, usable in display campaigns). "
        "See axisrow/direct-cli#25."
    ),
)
@click.option(
    "--rule",
    "rules",
    multiple=True,
    help="Rule spec: OPERATOR:EXTERNAL_ID[:LIFESPAN][|EXTERNAL_ID[:LIFESPAN]]",
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(ctx, name, description, list_type, rules, dry_run):
    """Add new retargeting list"""
    try:
        _validate_description(description)
        if not rules:
            raise click.UsageError(t("Provide at least one --rule"))
        list_data = {
            "Name": name,
            "Type": list_type,
            "Rules": parse_retargeting_rule_specs(list(rules)),
        }
        if description is not None:
            list_data["Description"] = description

        body = {"method": "add", "params": {"RetargetingLists": [list_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = client_from_ctx(ctx, create_client)
        result = client.retargeting().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@retargeting.command()
@click.option("--id", "list_id", required=True, type=int, help="Retargeting list ID")
@click.option("--name", help="List name")
@click.option(
    "--description",
    help=(
        "Retargeting list description for RetargetingListUpdateItem.Description "
        "(max 4096 chars)"
    ),
)
@click.option(
    "--type",
    "list_type",
    type=click.Choice(_RETARGETING_LIST_TYPES, case_sensitive=False),
    help="Retargeting list type",
)
@click.option(
    "--rule",
    "rules",
    multiple=True,
    help="Rule spec: OPERATOR:EXTERNAL_ID[:LIFESPAN][|EXTERNAL_ID[:LIFESPAN]]",
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def update(ctx, list_id, name, description, list_type, rules, dry_run):
    """Update retargeting list"""
    try:
        _validate_description(description)
        list_data = {"Id": list_id}
        if name:
            list_data["Name"] = name
        if description is not None:
            list_data["Description"] = description
        if list_type:
            list_data["Type"] = list_type
        if rules:
            list_data["Rules"] = parse_retargeting_rule_specs(list(rules))
        if len(list_data) == 1:
            raise click.UsageError(t("Provide at least one field to update"))

        body = {"method": "update", "params": {"RetargetingLists": [list_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = client_from_ctx(ctx, create_client)
        result = client.retargeting().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@retargeting.command()
@click.option("--id", "list_id", required=True, type=int, help="Retargeting list ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def delete(ctx, list_id, dry_run):
    """Delete retargeting list"""
    try:
        body = {"method": "delete", "params": {"SelectionCriteria": {"Ids": [list_id]}}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = client_from_ctx(ctx, create_client)

        result = client.retargeting().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()
