"""
Output formatting module for Direct CLI
"""

import csv
import functools
import json
import sys
from io import StringIO
from typing import Any, Iterator, List, Optional

import click

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


def format_json(data: Any, indent: int = 2) -> str:
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


def format_table(data: Any, headers: Optional[List[str]] = None) -> str:
    """Format data as table"""
    if not tabulate:
        return format_json(data)

    if isinstance(data, list) and len(data) > 0:
        if isinstance(data[0], dict):
            return tabulate(data, headers="keys", tablefmt="grid")
        elif isinstance(data[0], list):
            return tabulate(data, headers=headers or [], tablefmt="grid")
        else:
            # list of scalars -> a single "Value" column
            rows = [[item] for item in data]
            return tabulate(rows, headers=headers or ["Value"], tablefmt="grid")
    elif isinstance(data, dict):
        # Convert dict to list of lists for table display
        rows = [[k, v] for k, v in data.items()]
        return tabulate(rows, headers=["Key", "Value"], tablefmt="grid")

    return str(data)


def _format_delimited(data: Any, headers: Optional[List[str]], delimiter: str) -> str:
    """Shared CSV/TSV writer — only the delimiter differs between the two."""
    output = StringIO()

    if isinstance(data, list) and len(data) > 0:
        if isinstance(data[0], dict):
            fieldnames = headers or list(data[0].keys())
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


def print_info(message: str) -> None:
    """Print info message"""
    print(f"ℹ {message}")


def handle_api_errors(func):
    """Convert uncaught exceptions into a printed error + ``click.Abort``.

    ``click.ClickException`` (including ``click.UsageError``) is re-raised
    unchanged so Click renders it normally (usage text, exit code 2). Any other
    exception is printed via :func:`print_error` and converted to
    ``click.Abort`` (exit code 1), matching the canonical command
    error-handling block this decorator replaces.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except click.ClickException:
            raise
        except Exception as e:
            print_error(str(e))
            raise click.Abort()

    return wrapper
