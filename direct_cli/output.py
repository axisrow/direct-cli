"""
Output formatting module for Direct CLI
"""

import csv
import functools
import json
import re
import sys
from io import StringIO
from typing import Any, Iterator, List, Optional

import click

from .i18n import t

try:
    from tabulate import tabulate
except ImportError:
    tabulate = None


class DirectAPIResultError(RuntimeError):
    """Raised when a Direct API action response contains item-level errors."""


def format_output(
    data: Any,
    format_type: str = "json",
    output_file: Optional[str] = None,
    headers: Optional[List[str]] = None,
) -> str:
    """
    Format data for output

    Args:
        data: Data to format
        format_type: Output format ('text', 'json', 'table', 'csv', 'tsv')
        output_file: Output file path (if None, print to stdout)
        headers: Column headers for table/csv/tsv format

    Returns:
        Formatted string
    """
    raise_for_api_result_errors(data)
    warn_for_api_result_warnings(data)

    if format_type == "json":
        output = format_json(data)
    elif format_type == "text":
        output = format_text(data)
    elif format_type == "table":
        output = format_table(data, headers)
    elif format_type == "csv":
        output = format_csv(data, headers)
    elif format_type == "tsv":
        output = format_tsv(data, headers)
    else:
        output = str(data)

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(output)
    else:
        print(output)

    return output


def raise_for_api_result_errors(data: Any) -> None:
    """Raise a human-readable error for embedded Direct API action errors."""
    result_errors = list(_iter_api_result_errors(data))
    if not result_errors:
        return

    lines = ["Yandex Direct API returned errors; operation was not applied."]
    for error in result_errors:
        lines.append(_format_api_result_error(error))

    if any(_error_code(error) == 8800 for error in result_errors):
        lines.append(
            "Code 8800 means the object is not available under the current "
            "Client-Login/account. Check --login, YANDEX_DIRECT_LOGIN, or "
            "the selected auth profile for the target client."
        )

    if any(_error_code(error) == 8300 for error in result_errors):
        lines.append(
            "Code 8300 on delete/moderate usually means the ad is not in DRAFT "
            "status. Status=UNKNOWN is an API fallback value (a status outside "
            "the v5 enum), not a business status — such ads can only be "
            "archived/unarchived, not deleted or sent to moderation."
        )

    if any(_error_mentions_adimagehash(error) for error in result_errors):
        lines.append(
            "Code 5005 on AdImageHash: the image cannot be cleared via the API "
            "(typically a server-side carousel image, removable only in the "
            "Direct web interface). Workaround: replace it with a single image "
            "via --image-hash <hash>."
        )

    raise DirectAPIResultError("\n".join(lines))


def _iter_api_result_errors(data: Any) -> Iterator[dict]:
    if isinstance(data, dict):
        errors = data.get("Errors")
        if isinstance(errors, list):
            for error in errors:
                if isinstance(error, dict):
                    yield error
                else:
                    yield {"Message": str(error)}
        for key, value in data.items():
            if key != "Errors":
                yield from _iter_api_result_errors(value)
    elif isinstance(data, list):
        for item in data:
            yield from _iter_api_result_errors(item)


# Yandex Direct Warning codes that get a human-readable explanation appended
# to the raw ``Code``/``Message`` pair (issue #850). Both are emitted by
# ``ads add``/``ads update`` when text-ad creation is closed and Yandex
# silently substitutes/edits a combinatorial banner instead.
_KNOWN_API_WARNINGS = {
    10251: (
        "Ad created as a combinatorial banner, not TEXT_AD as requested "
        "(Yandex has closed text-banner creation). Layout and limits differ "
        "from a text ad; `ads get` will still report Type: TEXT_AD."
    ),
    10252: (
        "This ad is a combinatorial banner and was just edited through the "
        "legacy text-ad update API. This path may stop working once Yandex "
        "retires it."
    ),
}


def warn_for_api_result_warnings(data: Any) -> None:
    """Print embedded Direct API action ``Warnings`` to stderr.

    Mirrors :func:`raise_for_api_result_errors`'s tree walk, but warnings
    don't block the result (unlike ``Errors``) — they're only surfaced so a
    silent type/behavior substitution (e.g. #850's TEXT_AD-to-combinatorial
    swap) isn't visible only by reading the JSON result body.
    """
    for warning in _iter_api_result_warnings(data):
        code = _error_code(warning)
        message = warning.get("Message", "")
        known = _KNOWN_API_WARNINGS.get(code) if code is not None else None
        if known:
            print_warning_stderr(
                t("Warning {code}: {message} — {known}").format(
                    code=code, message=message, known=t(known)
                )
            )
        else:
            print_warning_stderr(
                t("Warning {code}: {message}").format(code=code, message=message)
            )


def _iter_api_result_warnings(data: Any) -> Iterator[dict]:
    if isinstance(data, dict):
        warnings = data.get("Warnings")
        if isinstance(warnings, list):
            for warning in warnings:
                if isinstance(warning, dict):
                    yield warning
                else:
                    yield {"Message": str(warning)}
        for key, value in data.items():
            if key != "Warnings":
                yield from _iter_api_result_warnings(value)
    elif isinstance(data, list):
        for item in data:
            yield from _iter_api_result_warnings(item)


def _format_api_result_error(error: dict) -> str:
    code = _error_code(error)
    message = error.get("Message")
    details = error.get("Details")

    if code is not None and message and details:
        return f"Error {code}: {message}. Details: {details}"
    if code is not None and message:
        return f"Error {code}: {message}"
    if message and details:
        return f"Error: {message}. Details: {details}"
    if message:
        return f"Error: {message}"
    if code is not None:
        return f"Error {code}"
    return f"Error: {format_json(error, indent=0)}"


def _error_mentions_adimagehash(error: dict) -> bool:
    # Code 5005 ("Field set incorrectly") is generic, so the AdImageHash hint
    # must only fire when the error actually names that field — otherwise it
    # would mis-attach to any 5005. The live envelope reports it as
    # ``adImageHash=<[<null>]>`` in Details.
    if _error_code(error) != 5005:
        return False
    blob = f"{error.get('Message', '')} {error.get('Details', '')}".lower()
    return "adimagehash" in blob


def _error_code(error: dict) -> Optional[int]:
    code = error.get("Code")
    if isinstance(code, int):
        return code
    if isinstance(code, str) and code.isdigit():
        return int(code)
    return None


def format_json(data: Any, indent: Optional[int] = 2) -> str:
    """Format data as JSON"""
    return json.dumps(data, ensure_ascii=False, indent=indent, default=str)


def format_text(data: Any) -> str:
    """Format data as a human-readable plain-text block.

    The default for reference commands — the same kind of flat plain-text the
    ``auth status`` / ``auth list`` commands print by hand (stylistic mirror, not
    shared code): a list of records prints each record as ``key: value`` lines
    separated by a blank line; a list of scalars prints one per line; a mapping
    prints ``key: value`` lines; anything else falls back to ``str``.
    """
    if isinstance(data, list):
        if not data:
            return ""
        if isinstance(data[0], dict):
            blocks = [
                "\n".join(f"{key}: {value}" for key, value in item.items())
                for item in data
            ]
            return "\n\n".join(blocks)
        return "\n".join(str(item) for item in data)
    if isinstance(data, dict):
        return "\n".join(f"{key}: {value}" for key, value in data.items())
    return str(data)


_PLAIN_DECIMAL_RE = re.compile(r"[+-]?\d+(?:\.\d+)?")


def _table_cell(value: Any) -> str:
    """Render a table cell to text without losing precision (#901).

    API money/identifier values arrive as strings and pass through verbatim;
    ``str()`` on anything else is the same shortest round-trip repr json
    prints. ``None`` stays an empty cell (tabulate's missingval default).
    """
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _grid(matrix: List[List[str]], hdrs: List[str]) -> str:
    """tabulate a text matrix with numeric parsing disabled (#901).

    tabulate aligns typed numbers right; with all-text cells it would
    left-align everything, so columns whose non-blank cells are all plain
    decimals (the shape tabulate's numparse used to classify as numbers)
    keep their right alignment via ``colalign``. Blank cells (missing keys,
    ``None``) don't break a numeric column, matching numparse's treatment
    of missing values.
    """
    if not tabulate:  # unreachable via format_table's own fallback
        return format_json(matrix)
    colalign = []
    for i in range(len(matrix[0]) if matrix else 0):
        numbers = [row[i] for row in matrix if i < len(row) and row[i]]
        colalign.append(
            "right"
            if numbers and all(_PLAIN_DECIMAL_RE.fullmatch(cell) for cell in numbers)
            else "left"
        )
    return tabulate(
        matrix, headers=hdrs, tablefmt="grid", colalign=colalign, disable_numparse=True
    )


def format_table(data: Any, headers: Optional[List[str]] = None) -> str:
    """Format data as table.

    Cells keep the exact API text (#901): tabulate's default numparse parses
    numeric strings into floats and prints six significant digits
    ("123456.78" -> 123457), so every cell is rendered to its exact text
    before tabulate sees it and numparse is disabled.
    """
    if not tabulate:
        return format_json(data)

    if isinstance(data, list) and len(data) > 0:
        if isinstance(data[0], dict):
            keys = list(dict.fromkeys(key for row in data for key in row))
            matrix = [[_table_cell(row.get(key)) for key in keys] for row in data]
            return _grid(matrix, keys)
        elif isinstance(data[0], list):
            return _grid([[_table_cell(v) for v in row] for row in data], headers or [])
        else:
            # list of scalars -> a single "Value" column
            return _grid([[_table_cell(item)] for item in data], headers or ["Value"])
    elif isinstance(data, dict):
        # Convert dict to list of lists for table display
        return _grid(
            [[str(k), _table_cell(v)] for k, v in data.items()], ["Key", "Value"]
        )

    return str(data)


def _format_delimited(data: Any, headers: Optional[List[str]], delimiter: str) -> str:
    """Shared CSV/TSV writer — only the delimiter differs between the two."""
    output = StringIO()

    if isinstance(data, list) and len(data) > 0:
        if isinstance(data[0], dict):
            if headers:
                fieldnames = headers
            else:
                # Union of keys across ALL records in first-seen order (#900):
                # optional fields (e.g. TextAd) may exist only in later
                # records, so data[0] alone under-reports columns. Records
                # missing a field get an empty cell (DictWriter restval).
                fieldnames = list(dict.fromkeys(key for row in data for key in row))
            writer = csv.DictWriter(output, fieldnames=fieldnames, delimiter=delimiter)
            writer.writeheader()
            writer.writerows(data)
        elif isinstance(data[0], list):
            writer = csv.writer(output, delimiter=delimiter)
            if headers:
                writer.writerow(headers)
            writer.writerows(data)
        else:
            writer = csv.writer(output, delimiter=delimiter)
            writer.writerow(headers or ["Value"])
            for item in data:
                writer.writerow([item])
    elif isinstance(data, dict):
        writer = csv.writer(output, delimiter=delimiter)
        writer.writerow(["Key", "Value"])
        for k, v in data.items():
            writer.writerow([k, v])

    return output.getvalue()


def format_csv(data: Any, headers: Optional[List[str]] = None) -> str:
    """Format data as CSV"""
    return _format_delimited(data, headers, delimiter=",")


def format_tsv(data: Any, headers: Optional[List[str]] = None) -> str:
    """Format data as TSV"""
    return _format_delimited(data, headers, delimiter="\t")


def print_success(message: str) -> None:
    """Print success message"""
    print(f"\033[32m✓ {message}\033[0m")


def print_error(message: str) -> None:
    """Print error message"""
    print(f"\033[31m✗ {message}\033[0m", file=sys.stderr)


def print_warning(message: str) -> None:
    """Print warning message"""
    print(f"\033[33m⚠ {message}\033[0m")


def print_warning_stderr(message: str) -> None:
    """Print warning message to stderr.

    Unlike :func:`print_warning` (stdout, same stream as JSON results),
    this keeps the machine-readable stdout payload clean for scripted/batch
    callers while still surfacing the warning to a human running the command
    interactively (#850).
    """
    print(f"\033[33m⚠ {message}\033[0m", file=sys.stderr)


def print_info(message: str) -> None:
    """Print info message"""
    print(f"ℹ {message}")


def units_error_hint(e: Exception) -> str:
    """Append the API ``Units`` balance from the response to an error message.

    Every vendored API exception carries the raw ``requests.Response`` in
    ``.response``; Yandex returns ``Units: spent/left/limit`` on every call.
    A limit error (56/152/506) is only diagnosable with that number:
    nothing left = daily quota exhausted (retries pointless until Yandex
    replenishes units), units left = per-method throttling or a concurrent
    client on the same token (#919).
    """
    response = getattr(e, "response", None)
    headers = getattr(response, "headers", None) or {}
    units = headers.get("Units")
    if not units:
        return ""
    parts = units.split("/")
    if len(parts) == 3 and parts[1].strip() == "0":
        hint = (
            "daily balance exhausted; retries cannot succeed "
            "until Yandex replenishes units"
        )
    else:
        hint = (
            "units remain; the limit is per-method throttling "
            "or a concurrent client on the same token"
        )
    return f"\nAPI units (spent/left/limit): {units} — {hint}"


def handle_api_errors(func):
    """Convert uncaught exceptions into a printed error + ``click.Abort``.

    ``click.ClickException`` (including ``click.UsageError``) and
    ``click.Abort`` are re-raised unchanged so Click renders them normally
    (usage text, exit code 2; "Aborted!", exit code 1). Abort in particular
    is raised only after the command already printed its own error — printing
    a second, empty message for it would be noise. Any other exception is
    printed via :func:`print_error` and converted to ``click.Abort``
    (exit code 1), matching the canonical command error-handling block this
    decorator replaces. When the exception carries an API response with a
    ``Units`` header, the balance is appended (#919).
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (click.ClickException, click.Abort):
            raise
        except Exception as e:
            print_error(str(e) + units_error_hint(e))
            raise click.Abort()

    return wrapper
