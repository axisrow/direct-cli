"""
Sitelinks commands
"""

import json
from pathlib import Path
from typing import Any, Dict, List

import click

from ..api import client_from_ctx, create_client
from ..i18n import t
from ..output import format_output, handle_api_errors
from ._execute import execute_request
from ._lifecycle import make_lifecycle_command
from ..utils import (
    build_common_params,
    get_default_fields,
    parse_csv_strings,
    parse_ids,
    parse_sitelink_specs,
)

_SITELINK_FIELDS = ("Title", "Href", "Description", "TurboPageId")


def _coerce_turbo_page_id(raw_value: Any, index: int) -> int:
    if isinstance(raw_value, bool):
        raise click.UsageError(
            t("Sitelink #{index}: 'TurboPageId' must be an integer").format(index=index)
        )
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, str) and raw_value.strip().isdigit():
        return int(raw_value.strip())
    raise click.UsageError(
        t("Sitelink #{index}: 'TurboPageId' must be an integer").format(index=index)
    )


def _normalize_sitelink_row(row: Any, index: int) -> Dict[str, Any]:
    if not isinstance(row, dict):
        raise click.UsageError(
            t("Sitelink #{index}: expected a JSON object, got {arg0}").format(
                index=index, arg0=type(row).__name__
            )
        )

    unknown = sorted(set(row) - set(_SITELINK_FIELDS))
    if unknown:
        allowed = ", ".join(_SITELINK_FIELDS)
        raise click.UsageError(
            t("Unknown field {arg0!r} in sitelink #{index}; allowed: {allowed}").format(
                arg0=unknown[0], index=index, allowed=allowed
            )
        )

    if "Title" not in row or not str(row.get("Title") or "").strip():
        raise click.UsageError(
            t("Sitelink #{index}: missing required field 'Title'").format(index=index)
        )
    href = str(row.get("Href") or "").strip()
    raw_turbo_page_id = row.get("TurboPageId")
    if not href and raw_turbo_page_id in (None, ""):
        raise click.UsageError(
            t(
                "Sitelink #{index}: provide at least one of 'Href' or 'TurboPageId'"
            ).format(index=index)
        )

    item: Dict[str, Any] = {
        "Title": str(row["Title"]).strip(),
    }
    if href:
        item["Href"] = href
    description = row.get("Description")
    if description is not None and str(description).strip():
        item["Description"] = str(description).strip()
    if raw_turbo_page_id not in (None, ""):
        item["TurboPageId"] = _coerce_turbo_page_id(raw_turbo_page_id, index)
    return item


def _load_sitelinks_from_inline(json_str: str) -> List[Any]:
    try:
        decoded = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise click.UsageError(
            t("--sitelink-json: invalid JSON: {arg0}").format(arg0=exc.msg)
        )
    if not isinstance(decoded, list):
        raise click.UsageError(
            t("--sitelink-json must be a JSON array of sitelink objects")
        )
    return decoded


def _load_sitelinks_from_file(path: str) -> List[Any]:
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise click.UsageError(
            t("Cannot read --sitelinks-from-file {path!r}: {exc}").format(
                path=path, exc=exc
            )
        )

    rows: List[Any] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise click.UsageError(
                t(
                    "--sitelinks-from-file line {line_number}: invalid JSON: {arg0}"
                ).format(line_number=line_number, arg0=exc.msg)
            )
    return rows


@click.group()
def sitelinks():
    """Manage sitelinks"""


@sitelinks.command()
@click.option("--ids", help="Comma-separated sitelink IDs")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated SitelinksSet FieldNames")
@click.option(
    "--sitelink-field-names",
    help=(
        "Comma-separated SitelinkFieldNames controlling nested "
        "Sitelinks[] item field selection (e.g. Title,Href,Description,"
        "TurboPageId). Sent as a separate top-level request parameter "
        "alongside FieldNames per the SitelinksGetRequest WSDL."
    ),
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def get(
    ctx,
    ids,
    limit,
    fetch_all,
    output_format,
    output,
    fields,
    sitelink_field_names,
    dry_run,
):
    """Get sitelinks"""
    client = client_from_ctx(ctx, create_client)

    field_names = parse_csv_strings(fields) or get_default_fields("sitelinks")
    parsed_sitelink_field_names = parse_csv_strings(sitelink_field_names)
    if sitelink_field_names is not None and not parsed_sitelink_field_names:
        raise click.UsageError(
            t("Provide a non-empty comma-separated SitelinkFieldNames list.")
        )

    criteria = {}
    if ids:
        criteria["Ids"] = parse_ids(ids)

    params = build_common_params(
        criteria=criteria, field_names=field_names, limit=limit
    )
    if parsed_sitelink_field_names:
        params["SitelinkFieldNames"] = parsed_sitelink_field_names

    body = {"method": "get", "params": params}

    if dry_run:
        format_output(body, "json", None)
        return

    result = client.sitelinks().post(data=body)

    if fetch_all:
        items = []
        for item in result().iter_items():
            items.append(item)
        format_output(items, output_format, output)
    else:
        data = result().extract()
        format_output(data, output_format, output)


@sitelinks.command()
@click.option(
    "--sitelink",
    "sitelinks_specs",
    multiple=True,
    help=(
        "Sitelink spec: TITLE|HREF[|DESCRIPTION[|TURBO_PAGE_ID]]. "
        "Escape literal '|' as '\\|'."
    ),
)
@click.option(
    "--sitelink-json",
    "sitelinks_json",
    help="Inline JSON array of sitelink objects: "
    '[{"Title":"...","Href":"...","Description":"..."}]',
)
@click.option(
    "--sitelinks-from-file",
    "sitelinks_from_file",
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="JSONL file with one sitelink object per line",
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def add(ctx, sitelinks_specs, sitelinks_json, sitelinks_from_file, dry_run):
    """Add sitelinks set.

    Provide exactly one source: --sitelink (repeatable), --sitelink-json,
    or --sitelinks-from-file.
    """
    sources_used = (
        (1 if sitelinks_specs else 0)
        + (1 if sitelinks_json is not None else 0)
        + (1 if sitelinks_from_file is not None else 0)
    )
    if sources_used == 0:
        raise click.UsageError(
            t(
                "Provide exactly one of: --sitelink (repeatable), "
                "--sitelink-json (inline JSON array), or --sitelinks-from-file (JSONL)."
            )
        )
    if sources_used > 1:
        raise click.UsageError(
            t(
                "--sitelink, --sitelink-json, and --sitelinks-from-file are "
                "mutually exclusive — provide exactly one."
            )
        )

    if sitelinks_specs:
        try:
            sitelinks_payload = parse_sitelink_specs(list(sitelinks_specs))
        except ValueError as exc:
            raise click.UsageError(str(exc))
    else:
        if sitelinks_json is not None:
            raw_rows = _load_sitelinks_from_inline(sitelinks_json)
        else:
            raw_rows = _load_sitelinks_from_file(sitelinks_from_file)

        if not raw_rows:
            raise click.UsageError(t("Input contains no sitelink rows."))

        sitelinks_payload = [
            _normalize_sitelink_row(row, idx)
            for idx, row in enumerate(raw_rows, start=1)
        ]

    body = {
        "method": "add",
        "params": {"SitelinksSets": [{"Sitelinks": sitelinks_payload}]},
    }

    execute_request(ctx, "sitelinks", body, dry_run, create_client)


delete = make_lifecycle_command(
    sitelinks,
    "delete",
    "Delete sitelinks set",
    "set_id",
    "Sitelinks set ID",
    create_client,
)
