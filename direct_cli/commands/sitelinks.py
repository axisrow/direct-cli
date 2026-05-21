"""
Sitelinks commands
"""

import json
from pathlib import Path
from typing import Any, Dict, List

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import get_default_fields, parse_ids, parse_sitelink_specs


def _normalize_sitelink_row(row: Any, index: int) -> Dict[str, str]:
    if not isinstance(row, dict):
        raise click.UsageError(
            f"Sitelink #{index}: expected a JSON object, got {type(row).__name__}"
        )
    if "Title" not in row or not str(row.get("Title") or "").strip():
        raise click.UsageError(f"Sitelink #{index}: missing required field 'Title'")
    if "Href" not in row or not str(row.get("Href") or "").strip():
        raise click.UsageError(f"Sitelink #{index}: missing required field 'Href'")

    item: Dict[str, str] = {
        "Title": str(row["Title"]).strip(),
        "Href": str(row["Href"]).strip(),
    }
    description = row.get("Description")
    if description is not None and str(description).strip():
        item["Description"] = str(description).strip()
    return item


def _load_sitelinks_from_inline(json_str: str) -> List[Any]:
    try:
        decoded = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise click.UsageError(f"--sitelink-json: invalid JSON: {exc.msg}")
    if not isinstance(decoded, list):
        raise click.UsageError(
            "--sitelink-json must be a JSON array of sitelink objects"
        )
    return decoded


def _load_sitelinks_from_file(path: str) -> List[Any]:
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise click.UsageError(f"Cannot read --sitelinks-from-file {path!r}: {exc}")

    rows: List[Any] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise click.UsageError(
                f"--sitelinks-from-file line {line_number}: invalid JSON: {exc.msg}"
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
@click.option("--fields", help="Comma-separated field names")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def get(ctx, ids, limit, fetch_all, output_format, output, fields, dry_run):
    """Get sitelinks"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        field_names = fields.split(",") if fields else get_default_fields("sitelinks")

        criteria = {}
        if ids:
            criteria["Ids"] = parse_ids(ids)

        params = {"FieldNames": field_names}
        if criteria:
            params["SelectionCriteria"] = criteria

        if limit:
            params["Page"] = {"Limit": limit}

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

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@sitelinks.command()
@click.option(
    "--sitelink",
    "sitelinks_specs",
    multiple=True,
    help="Sitelink spec: TITLE|HREF[|DESCRIPTION]. Escape literal '|' as '\\|'.",
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
def add(ctx, sitelinks_specs, sitelinks_json, sitelinks_from_file, dry_run):
    """Add sitelinks set.

    Provide exactly one source: --sitelink (repeatable), --sitelink-json,
    or --sitelinks-from-file.
    """
    sources_used = sum(
        1
        for value in (
            sitelinks_specs or None,
            sitelinks_json,
            sitelinks_from_file,
        )
        if value
    )
    if sources_used == 0:
        raise click.UsageError(
            "Provide exactly one of: --sitelink (repeatable), "
            "--sitelink-json (inline JSON array), or --sitelinks-from-file (JSONL)."
        )
    if sources_used > 1:
        raise click.UsageError(
            "--sitelink, --sitelink-json, and --sitelinks-from-file are "
            "mutually exclusive — provide exactly one."
        )

    try:
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
                raise click.UsageError("Input contains no sitelink rows.")

            sitelinks_payload = [
                _normalize_sitelink_row(row, idx)
                for idx, row in enumerate(raw_rows, start=1)
            ]

        body = {
            "method": "add",
            "params": {"SitelinksSets": [{"Sitelinks": sitelinks_payload}]},
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.sitelinks().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@sitelinks.command()
@click.option("--id", "set_id", required=True, type=int, help="Sitelinks set ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def delete(ctx, set_id, dry_run):
    """Delete sitelinks set"""
    try:
        body = {"method": "delete", "params": {"SelectionCriteria": {"Ids": [set_id]}}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.sitelinks().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()
