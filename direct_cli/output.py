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
        format_type: Output format ('json', 'table', 'csv', 'tsv')
        output_file: Output file path (if None, print to stdout)
        headers: Column headers for table/csv/tsv format

    Returns:
        Formatted string
    """
    raise_for_api_result_errors(data)

    if format_type == "json":
        output = format_json(data)
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


def format_table(data: Any, headers: Optional[List[str]] = None) -> str:
    """Format data as table"""
    if not tabulate:
        return format_json(data)

    if isinstance(data, list) and len(data) > 0:
        if isinstance(data[0], dict):
            return tabulate(data, headers="keys", tablefmt="grid")
        elif isinstance(data[0], list):
            return tabulate(data, headers=headers or [], tablefmt="grid")
    elif isinstance(data, dict):
        # Convert dict to list of lists for table display
        rows = [[k, v] for k, v in data.items()]
        return tabulate(rows, headers=["Key", "Value"], tablefmt="grid")

    return str(data)


def format_csv(data: Any, headers: Optional[List[str]] = None) -> str:
    """Format data as CSV"""
    output = StringIO()

    if isinstance(data, list) and len(data) > 0:
        if isinstance(data[0], dict):
            fieldnames = headers or list(data[0].keys())
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)
        elif isinstance(data[0], list):
            writer = csv.writer(output)
            if headers:
                writer.writerow(headers)
            writer.writerows(data)
    elif isinstance(data, dict):
        writer = csv.writer(output)
        writer.writerow(["Key", "Value"])
        for k, v in data.items():
            writer.writerow([k, v])

    return output.getvalue()


def format_tsv(data: Any, headers: Optional[List[str]] = None) -> str:
    """Format data as TSV"""
    output = StringIO()

    if isinstance(data, list) and len(data) > 0:
        if isinstance(data[0], dict):
            fieldnames = headers or list(data[0].keys())
            writer = csv.DictWriter(output, fieldnames=fieldnames, delimiter="\t")
            writer.writeheader()
            writer.writerows(data)
        elif isinstance(data[0], list):
            writer = csv.writer(output, delimiter="\t")
            if headers:
                writer.writerow(headers)
            writer.writerows(data)
    elif isinstance(data, dict):
        writer = csv.writer(output, delimiter="\t")
        writer.writerow(["Key", "Value"])
        for k, v in data.items():
            writer.writerow([k, v])

    return output.getvalue()


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
