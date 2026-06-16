"""Shared JSONL/inline batch engine for multi-item ``add``/``update`` commands.

Extracted from the ``keywords add`` batch machinery (issue #562) so ``ads`` and
``adgroups`` reuse one loader/chunker/sender instead of duplicating it. Only the
resource-specific pieces (the row normalizer and any overflow warning) stay in
the command module and are passed in.

Message strings are NOT hardcoded with a resource name: ``load_inline_rows`` and
``send_batch`` take the catalog keys / nouns from the caller, so each command
keeps its own (already-translated) wording byte-identical.
"""

import json
from pathlib import Path
from typing import Any, Callable, Iterator, List, Optional

import click

from ..api import client_from_ctx
from ..i18n import t
from ..output import (
    format_json,
    format_output,
    print_error,
    raise_for_api_result_errors,
)


def load_jsonl_rows(path: str) -> List[Any]:
    """Read a JSONL file into a list of decoded rows (one JSON value per line).

    Blank lines are skipped. A read error or a malformed line raises a
    ``click.UsageError`` with the same catalog keys ``keywords`` used.
    """
    rows: List[Any] = []
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise click.UsageError(
            t("Cannot read --from-file {path!r}: {exc}").format(path=path, exc=exc)
        )

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise click.UsageError(
                t("Row {line_number}: invalid JSON: {arg0}").format(
                    line_number=line_number, arg0=exc.msg
                )
            )
    return rows


def load_inline_rows(
    json_str: str,
    *,
    invalid_json_key: str,
    not_array_key: str,
) -> List[Any]:
    """Parse an inline JSON array of rows.

    ``invalid_json_key`` / ``not_array_key`` are the EN catalog keys for the two
    error cases, so each command keeps its own ``--<resource>-json`` wording
    (and its existing RU translation) unchanged.
    """
    try:
        decoded = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise click.UsageError(t(invalid_json_key).format(arg0=exc.msg))
    if not isinstance(decoded, list):
        raise click.UsageError(t(not_array_key))
    return decoded


def chunked(items: List[Any], size: int) -> Iterator[List[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def normalize_results(raw: Any, result_key: str) -> List[Any]:
    """Unwrap the per-item result list from an ``add``/``update`` response.

    ``result_key`` is ``"AddResults"`` for ``add`` and ``"UpdateResults"`` for
    ``update`` — Yandex names the list after the method.
    """
    if isinstance(raw, dict):
        results = raw.get(result_key)
        if isinstance(results, list):
            return results
        return [raw]
    if isinstance(raw, list):
        return raw
    return [raw]


def send_batch(
    ctx,
    *,
    resource: str,
    method: str,
    payload_key: str,
    items: List[Any],
    max_batch: int,
    create_client: Callable,
    dry_run: bool,
    noun: str,
    result_key: str = "AddResults",
    on_warn: Optional[Callable[[List[Any]], None]] = None,
) -> None:
    """Chunk ``items`` and send each chunk through ``client.<resource>()``.

    ``--dry-run`` prints the chunk preview and returns. Otherwise each chunk is
    posted in a loop; on failure any already-created items are reported (so a
    retry does not silently duplicate them). ``noun`` is the plural object name
    used in that partial-success message (e.g. ``"keywords"``, ``"ads"``).
    ``result_key`` is the response list name (``"AddResults"`` for ``add``,
    ``"UpdateResults"`` for ``update``).
    """
    chunks = list(chunked(items, max_batch))

    if on_warn is not None:
        on_warn(items)

    if dry_run:
        preview = {
            "chunks": len(chunks),
            "totalItems": len(items),
            "chunkSize": max_batch,
            "firstChunk": {"method": method, "params": {payload_key: chunks[0]}},
        }
        print(format_json(preview, indent=2))
        return

    all_results: List[Any] = []
    try:
        client = client_from_ctx(ctx, create_client)

        for index, chunk in enumerate(chunks, start=1):
            click.echo(
                f"Sending chunk {index}/{len(chunks)}: {len(chunk)} items",
                err=True,
            )
            body = {"method": method, "params": {payload_key: chunk}}
            response = getattr(client, resource)().post(data=body)
            chunk_results = normalize_results(response().extract(), result_key)
            # Only items without per-item Errors are "already applied" — the
            # partial-success diagnostic must not lie about failed items.
            all_results.extend(
                item
                for item in chunk_results
                if not (isinstance(item, dict) and item.get("Errors"))
            )
            raise_for_api_result_errors(chunk_results)

        format_output({result_key: all_results}, "json", None)
    except click.UsageError:
        raise
    except Exception as e:
        if all_results:
            click.echo(
                f"Partial success before failure — these {noun} were already "
                "applied in Yandex Direct (retrying may duplicate them):",
                err=True,
            )
            click.echo(format_json({result_key: all_results}, indent=2), err=True)
        print_error(str(e))
        raise click.Abort()
