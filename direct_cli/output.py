"""
Output formatting module for Direct CLI
"""

import json
import csv
import sys
from typing import Any, List, Dict, Optional
from io import StringIO

try:
    from tabulate import tabulate
except ImportError:
    tabulate = None


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
