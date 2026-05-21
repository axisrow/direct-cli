"""
Keywords commands
"""

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import click

from ..api import create_client
from ..output import format_json, format_output, print_error
from ..utils import add_criteria_csv, parse_ids, get_default_fields, MICRO_RUBLES

# Yandex Direct API "keywords.add" caps a single AddItems request at 10
# items; the WSDL declares maxOccurs="unbounded", so this limit comes from
# the documentation rather than the contract:
# https://yandex.ru/dev/direct/doc/dg/objects/keyword.html
KEYWORDS_ADD_MAX_BATCH = 10

_KEYWORD_ROW_FIELDS: Dict[str, str] = {
    "Keyword": "str",
    "AdGroupId": "int",
    "Bid": "micro",
    "ContextBid": "micro",
    "UserParam1": "str",
    "UserParam2": "str",
}


def _coerce_keyword_field(field: str, raw_value: Any, row_index: int) -> Any:
    kind = _KEYWORD_ROW_FIELDS[field]
    if kind == "str":
        if not isinstance(raw_value, str):
            raise click.UsageError(
                f"Row {row_index} field {field!r}: expected string, "
                f"got {type(raw_value).__name__}"
            )
        return raw_value
    if kind == "int":
        if isinstance(raw_value, bool) or not isinstance(raw_value, int):
            try:
                return int(raw_value)
            except (TypeError, ValueError):
                raise click.UsageError(
                    f"Row {row_index} field {field!r}: expected integer, "
                    f"got {raw_value!r}"
                )
        return raw_value
    if kind == "micro":
        try:
            return MICRO_RUBLES.convert(raw_value, None, None)
        except click.exceptions.BadParameter as exc:
            raise click.UsageError(f"Row {row_index} field {field!r}: {exc.message}")
    raise click.UsageError(
        f"Row {row_index} field {field!r}: unsupported type {kind!r}"
    )


def _normalize_keyword_row(
    row: Any,
    row_index: int,
    default_adgroup_id: Optional[int],
) -> Dict[str, Any]:
    if not isinstance(row, dict):
        raise click.UsageError(
            f"Row {row_index}: expected JSON object, got {type(row).__name__}"
        )

    unknown = sorted(set(row) - set(_KEYWORD_ROW_FIELDS))
    if unknown:
        allowed = ", ".join(_KEYWORD_ROW_FIELDS)
        raise click.UsageError(
            f"Unknown field {unknown[0]!r} in keyword row {row_index}; "
            f"allowed: {allowed}"
        )

    item: Dict[str, Any] = {}
    for field in _KEYWORD_ROW_FIELDS:
        if field in row and row[field] is not None:
            item[field] = _coerce_keyword_field(field, row[field], row_index)

    if "AdGroupId" not in item:
        if default_adgroup_id is None:
            raise click.UsageError(
                f"Row {row_index}: missing 'AdGroupId' and no default "
                "--adgroup-id provided"
            )
        item["AdGroupId"] = default_adgroup_id

    if "Keyword" not in item:
        raise click.UsageError(f"Row {row_index}: missing required field 'Keyword'")

    return item


def _load_keyword_rows_from_file(path: str) -> List[Any]:
    rows: List[Any] = []
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise click.UsageError(f"Cannot read --from-file {path!r}: {exc}")

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise click.UsageError(f"Row {line_number}: invalid JSON: {exc.msg}")
    return rows


def _load_keyword_rows_from_inline(json_str: str) -> List[Any]:
    try:
        decoded = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise click.UsageError(f"--keywords-json: invalid JSON: {exc.msg}")
    if not isinstance(decoded, list):
        raise click.UsageError(
            "--keywords-json must be a JSON array of keyword objects"
        )
    return decoded


def _chunked(items: List[Any], size: int) -> Iterator[List[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _normalize_add_results(raw: Any) -> List[Any]:
    if isinstance(raw, dict):
        results = raw.get("AddResults")
        if isinstance(results, list):
            return results
        return [raw]
    if isinstance(raw, list):
        return raw
    return [raw]


@click.group()
def keywords():
    """Manage keywords"""


@keywords.command()
@click.option("--ids", help="Comma-separated keyword IDs")
@click.option("--adgroup-ids", help="Comma-separated ad group IDs")
@click.option("--campaign-ids", help="Comma-separated campaign IDs")
@click.option("--status", help="Filter by status")
@click.option("--statuses", help="Comma-separated statuses")
@click.option("--states", help="Comma-separated states")
@click.option("--modified-since", help="ModifiedSince datetime")
@click.option("--serving-statuses", help="Comma-separated serving statuses")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def get(
    ctx,
    ids,
    adgroup_ids,
    campaign_ids,
    status,
    statuses,
    states,
    modified_since,
    serving_statuses,
    limit,
    fetch_all,
    output_format,
    output,
    fields,
    dry_run,
):
    """Get keywords"""
    if status and statuses:
        raise click.UsageError("--status and --statuses are mutually exclusive")

    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        field_names = fields.split(",") if fields else get_default_fields("keywords")

        criteria = {}
        if ids:
            criteria["Ids"] = parse_ids(ids)
        if adgroup_ids:
            criteria["AdGroupIds"] = parse_ids(adgroup_ids)
        if campaign_ids:
            criteria["CampaignIds"] = parse_ids(campaign_ids)
        if status:
            criteria["Statuses"] = [status]
        add_criteria_csv(criteria, "Statuses", statuses, upper=True)
        add_criteria_csv(criteria, "States", states, upper=True)
        if modified_since:
            criteria["ModifiedSince"] = modified_since
        add_criteria_csv(criteria, "ServingStatuses", serving_statuses, upper=True)

        params = {"SelectionCriteria": criteria, "FieldNames": field_names}

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        if dry_run:
            format_output(body, "json", None)
            return

        result = client.keywords().post(data=body)

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


@keywords.command()
@click.option("--adgroup-id", type=int, help="Ad group ID (default in batch mode)")
@click.option("--keyword", help="Keyword text (single-item mode)")
@click.option("--bid", type=MICRO_RUBLES, help="Search bid in micro-rubles")
@click.option("--context-bid", type=MICRO_RUBLES, help="Context bid in micro-rubles")
@click.option("--user-param-1", help="User parameter 1")
@click.option("--user-param-2", help="User parameter 2")
@click.option(
    "--from-file",
    "from_file",
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to JSONL file (one keyword object per line)",
)
@click.option(
    "--keywords-json",
    "keywords_json",
    help="Inline JSON array of keyword objects",
)
@click.option(
    "--format",
    "output_format",
    default="json",
    help="Output format (batch mode supports only json)",
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(
    ctx,
    adgroup_id,
    keyword,
    bid,
    context_bid,
    user_param_1,
    user_param_2,
    from_file,
    keywords_json,
    output_format,
    dry_run,
):
    """Add one or many keywords (batch via --from-file / --keywords-json)."""
    modes_used = sum(1 for value in (keyword, from_file, keywords_json) if value)
    if modes_used == 0:
        raise click.UsageError(
            "Provide exactly one of: --keyword (single), --from-file (JSONL), "
            "or --keywords-json (inline JSON array)."
        )
    if modes_used > 1:
        raise click.UsageError(
            "Provide exactly one of: --keyword, --from-file, or "
            "--keywords-json — they are mutually exclusive."
        )

    batch_mode = from_file is not None or keywords_json is not None

    if batch_mode:
        _bulk_add(
            ctx,
            adgroup_id=adgroup_id,
            from_file=from_file,
            keywords_json=keywords_json,
            output_format=output_format,
            dry_run=dry_run,
        )
        return

    if adgroup_id is None:
        raise click.UsageError("Missing option '--adgroup-id'.")

    try:
        keyword_data: Dict[str, Any] = {
            "AdGroupId": adgroup_id,
            "Keyword": keyword,
        }
        if bid is not None:
            keyword_data["Bid"] = bid
        if context_bid is not None:
            keyword_data["ContextBid"] = context_bid
        if user_param_1:
            keyword_data["UserParam1"] = user_param_1
        if user_param_2:
            keyword_data["UserParam2"] = user_param_2

        body = {"method": "add", "params": {"Keywords": [keyword_data]}}

        if dry_run:
            format_output(body, output_format, None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.keywords().post(data=body)
        format_output(result().extract(), output_format, None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


def _bulk_add(
    ctx,
    *,
    adgroup_id: Optional[int],
    from_file: Optional[str],
    keywords_json: Optional[str],
    output_format: str,
    dry_run: bool,
) -> None:
    if output_format != "json":
        raise click.UsageError(
            "--format other than 'json' is not supported in batch mode "
            "(item-level results may include per-row Errors)."
        )

    if from_file is not None:
        raw_rows = _load_keyword_rows_from_file(from_file)
    else:
        raw_rows = _load_keyword_rows_from_inline(keywords_json or "")

    if not raw_rows:
        raise click.UsageError("Input contains no keyword rows.")

    items: List[Dict[str, Any]] = [
        _normalize_keyword_row(row, idx, adgroup_id)
        for idx, row in enumerate(raw_rows, start=1)
    ]

    chunks = list(_chunked(items, KEYWORDS_ADD_MAX_BATCH))

    if dry_run:
        preview = {
            "chunks": len(chunks),
            "totalItems": len(items),
            "chunkSize": KEYWORDS_ADD_MAX_BATCH,
            "firstChunk": {
                "method": "add",
                "params": {"Keywords": chunks[0]},
            },
        }
        print(format_json(preview, indent=2))
        return

    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        all_results: List[Any] = []
        for index, chunk in enumerate(chunks, start=1):
            click.echo(
                f"Sending chunk {index}/{len(chunks)}: {len(chunk)} items",
                err=True,
            )
            body = {"method": "add", "params": {"Keywords": chunk}}
            response = client.keywords().post(data=body)
            all_results.extend(_normalize_add_results(response().extract()))

        print(format_json({"AddResults": all_results}, indent=2))
    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


_DEPRECATED_KEYWORDS_UPDATE_OPTIONS = {
    "bid": "--bid is no longer accepted on 'keywords update'; use: direct bids set --keyword-id ID --bid VALUE",
    "context_bid": "--context-bid is no longer accepted on 'keywords update'; use: direct bids set --keyword-id ID --network-bid VALUE",
    "status": "--status is no longer accepted on 'keywords update'; status is not mutable via the keywords API",
}


def _deprecated_bid_option(ctx, param, value):
    if value is not None:
        raise click.UsageError(_DEPRECATED_KEYWORDS_UPDATE_OPTIONS[param.name])


@keywords.command()
@click.option("--id", "keyword_id", required=True, type=int, help="Keyword ID")
@click.option("--keyword", help="New keyword text")
@click.option("--user-param-1", help="User parameter 1")
@click.option("--user-param-2", help="User parameter 2")
@click.option(
    "--bid",
    default=None,
    expose_value=False,
    callback=_deprecated_bid_option,
    is_eager=True,
    hidden=True,
    help="Removed: use 'bids set --keyword-id ID --bid VALUE'",
)
@click.option(
    "--context-bid",
    default=None,
    expose_value=False,
    callback=_deprecated_bid_option,
    is_eager=True,
    hidden=True,
    help="Removed: use 'bids set --keyword-id ID --network-bid VALUE'",
)
@click.option(
    "--status",
    default=None,
    expose_value=False,
    callback=_deprecated_bid_option,
    is_eager=True,
    hidden=True,
    help="Removed: status is not mutable via keywords update",
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def update(ctx, keyword_id, keyword, user_param_1, user_param_2, dry_run):
    """Update keyword text or user params (use 'bids set' for bid changes)"""
    keyword_data = {"Id": keyword_id}

    if keyword:
        keyword_data["Keyword"] = keyword
    if user_param_1 is not None:
        keyword_data["UserParam1"] = user_param_1
    if user_param_2 is not None:
        keyword_data["UserParam2"] = user_param_2

    # Reject empty-payload no-op (issue #198 H10).
    if len(keyword_data) == 1:
        raise click.UsageError(
            "keywords update requires at least one updatable field "
            "(--keyword, --user-param-1, or --user-param-2)."
        )

    try:
        body = {"method": "update", "params": {"Keywords": [keyword_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.keywords().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@keywords.command()
@click.option("--id", "keyword_id", required=True, type=int, help="Keyword ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def delete(ctx, keyword_id, dry_run):
    """Delete keyword"""
    try:
        body = {
            "method": "delete",
            "params": {"SelectionCriteria": {"Ids": [keyword_id]}},
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.keywords().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@keywords.command()
@click.option("--id", "keyword_id", required=True, type=int, help="Keyword ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def suspend(ctx, keyword_id, dry_run):
    """Suspend keyword"""
    try:
        body = {
            "method": "suspend",
            "params": {"SelectionCriteria": {"Ids": [keyword_id]}},
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.keywords().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@keywords.command()
@click.option("--id", "keyword_id", required=True, type=int, help="Keyword ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def resume(ctx, keyword_id, dry_run):
    """Resume keyword"""
    try:
        body = {
            "method": "resume",
            "params": {"SelectionCriteria": {"Ids": [keyword_id]}},
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.keywords().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()
