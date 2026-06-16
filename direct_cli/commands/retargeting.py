"""
RetargetingLists commands
"""

from typing import Optional

import click

from ..api import client_from_ctx, create_client
from ..i18n import t
from ..output import format_output, handle_api_errors
from ._lifecycle import make_lifecycle_command
from ..utils import (
    add_criteria_csv,
    build_common_params,
    get_default_fields,
    get_options,
    parse_csv_strings,
    parse_ids,
    parse_retargeting_rule_specs,
)


@click.group()
def retargeting():
    """Manage retargeting lists"""


@retargeting.command()
@click.option("--ids", help="Comma-separated list IDs")
@click.option("--types", help="Filter by types")
@get_options
@click.pass_context
@handle_api_errors
def get(
    ctx,
    ids,
    types,
    limit,
    fetch_all,
    output_format,
    output,
    fields,
    dry_run,
):
    """Get retargeting lists"""
    client = client_from_ctx(ctx, create_client)

    field_names = parse_csv_strings(fields) or get_default_fields("retargetinglists")

    criteria = {}
    if ids:
        criteria["Ids"] = parse_ids(ids)
    add_criteria_csv(criteria, "Types", types, upper=True)

    params = build_common_params(
        criteria=criteria, field_names=field_names, limit=limit
    )

    body = {"method": "get", "params": params}

    if dry_run:
        format_output(body, "json", None)
        return

    result = client.retargeting().post(data=body)

    if fetch_all:
        items = []
        for item in result().iter_items():
            items.append(item)
        format_output(items, output_format, output)
    else:
        data = result().extract()
        format_output(data, output_format, output)


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
@handle_api_errors
def add(ctx, name, description, list_type, rules, dry_run):
    """Add new retargeting list"""
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


@retargeting.command()
@click.option(
    "--id",
    "list_id",
    required=True,
    type=click.IntRange(min=1),
    help="Retargeting list ID",
)
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
@handle_api_errors
def update(ctx, list_id, name, description, list_type, rules, dry_run):
    """Update retargeting list"""
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


delete = make_lifecycle_command(
    retargeting,
    "delete",
    "Delete retargeting list",
    "list_id",
    "Retargeting list ID",
    create_client,
)
