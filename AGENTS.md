# AGENTS.md - Guidelines for AI Coding Agents

This document provides essential information for AI coding agents working on the Direct CLI codebase.

## Project Overview

Direct CLI is a command-line interface for the Yandex Direct API, built with Python and Click. It provides commands for managing campaigns, ad groups, ads, keywords, reports, and other Yandex Direct resources.

## Build, Test, and Lint Commands

### Installation

```bash
# Install package in development mode
pip install -e .

# Install with development dependencies
pip install -e ".[dev]"
```

### Testing

```bash
# Run all tests
pytest

# Run all tests with verbose output
pytest -v

# Run a single test file
pytest tests/test_cli.py

# Run a single test by name
pytest tests/test_cli.py::TestCLI::test_cli_help

# Run tests matching a pattern
pytest -k "campaigns"

# Run tests with coverage
pytest --cov=direct_cli

# Run tests with coverage report
pytest --cov=direct_cli --cov-report=html
```

### Code Quality

```bash
# Format code with Black
black .

# Format specific files
black direct_cli/ tests/

# Check formatting without changes
black --check .

# Lint with flake8
flake8 direct_cli tests

# Lint specific file
flake8 direct_cli/cli.py
```

### Building

```bash
# Build package
python -m build

# Build wheel only
pip wheel . --no-deps -w dist/
```

## Code Style Guidelines

### Import Organization

Organize imports in three groups, separated by blank lines:

```python
# 1. Standard library imports (alphabetical)
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# 2. Third-party imports (alphabetical)
import click
from dotenv import load_dotenv

# 3. Local imports (alphabetical)
from .api import create_client
from .auth import get_credentials
from .output import format_output, print_error
from .utils import parse_ids, build_selection_criteria
```

### Type Hints

Always use type hints for function parameters and return values:

```python
def parse_ids(ids_str: Optional[str]) -> Optional[List[int]]:
    """Parse comma-separated IDs"""
    if not ids_str:
        return None
    return [int(x.strip()) for x in ids_str.split(",")]


def create_client(
    token: Optional[str] = None,
    login: Optional[str] = None,
    sandbox: bool = False,
) -> YandexDirect:
    """Create YandexDirect client"""
    ...
```

### Docstrings

Use descriptive docstrings with Args, Returns, and Raises sections:

```python
def get_credentials(
    token: Optional[str] = None,
    login: Optional[str] = None,
    env_path: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    """
    Get credentials with priority:
    1. Direct arguments
    2. Environment variables
    3. .env file

    Args:
        token: API access token
        login: Client login (for agency accounts)
        env_path: Path to .env file

    Returns:
        Tuple of (token, login)

    Raises:
        ValueError: If token is not provided
    """
    ...
```

### Naming Conventions

- **Functions and variables**: `snake_case`
- **Classes**: `PascalCase`
- **Constants**: `UPPER_SNAKE_CASE`
- **CLI command names**: `kebab-case` (e.g., `get-campaigns`, `add-adgroup`)

### Error Handling

Use try/except blocks with `print_error()` and `raise click.Abort()`:

```python
try:
    client = create_client(
        token=ctx.obj.get("token"),
        login=ctx.obj.get("login"),
        sandbox=ctx.obj.get("sandbox"),
    )
    result = client.campaigns().post(data=body)
    format_output(result().extract(), output_format, output)
except Exception as e:
    print_error(str(e))
    raise click.Abort()
```

### Click Command Structure

Use Click decorators consistently:

```python
@click.group()
def campaigns():
    """Manage campaigns"""
    pass


@campaigns.command()
@click.option("--ids", help="Comma-separated campaign IDs")
@click.option("--status", help="Filter by status")
@click.option("--limit", type=int, help="Limit number of results")
@click.pass_context
def get(ctx, ids, status, limit):
    """Get campaigns"""
    ...
```

## Project Structure

```
direct-cli/
├── direct_cli/           # Main package
│   ├── __init__.py       # Package initialization
│   ├── cli.py            # Main CLI entry point
│   ├── api.py            # YandexDirect API client wrapper
│   ├── auth.py           # Authentication module
│   ├── utils.py          # Utility functions
│   ├── output.py         # Output formatting (json, table, csv, tsv)
│   └── commands/         # Command modules by resource
│       ├── __init__.py
│       ├── campaigns.py
│       ├── adgroups.py
│       ├── ads.py
│       ├── keywords.py
│       ├── reports.py
│       └── ...           # Other resource commands
├── tests/                # Test directory
│   ├── __init__.py
│   └── test_cli.py
├── pyproject.toml        # Project configuration
└── README.md             # User documentation
```

## Key Patterns

### Creating a New Command Module

1. Create a new file in `direct_cli/commands/`
2. Define a Click group with commands
3. Register in `direct_cli/cli.py`

```python
# direct_cli/commands/newresource.py
import click
from ..api import create_client
from ..output import format_output, print_error


@click.group()
def newresource():
    """Manage new resource"""
    pass


@newresource.command()
@click.pass_context
def get(ctx):
    """Get new resource"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )
        # ... API call
        format_output(data, "json", None)
    except Exception as e:
        print_error(str(e))
        raise click.Abort()
```

Then register in `cli.py`:

```python
from .commands.newresource import newresource
cli.add_command(newresource)
```

### Output Formatting

Use `format_output()` for consistent output:

```python
from ..output import format_output

# JSON output (default)
format_output(data, "json", None)

# Table output
format_output(data, "table", None)

# CSV/TSV to file
format_output(data, "csv", "output.csv")
format_output(data, "tsv", "output.tsv")
```

### Pagination

For large result sets, use `--fetch-all` flag:

```python
if fetch_all:
    items = []
    for item in result().iter_items():
        items.append(item)
    format_output(items, output_format, output)
else:
    data = result().extract()
    format_output(data, output_format, output)
```

## Code Formatting Standards

- **Line length**: 88 characters (Black default)
- **String quotes**: Prefer double quotes (`"`)
- **Indentation**: 4 spaces (no tabs)
- **Blank lines**: 
  - 2 blank lines before class/function definitions at module level
  - 1 blank line between methods
  - 1 blank line between logical sections within functions

## Testing Guidelines

### Test Structure

```python
import unittest
from click.testing import CliRunner
from direct_cli.cli import cli


class TestCLI(unittest.TestCase):
    """Test CLI commands"""

    def setUp(self):
        self.runner = CliRunner()

    def test_command_help(self):
        """Test command help"""
        result = self.runner.invoke(cli, ["command", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("expected text", result.output)
```

### Test Naming

- Test files: `test_*.py`
- Test classes: `Test*`
- Test methods: `test_*`

## Dependencies

Main dependencies (see `pyproject.toml`):
- `tapi-yandex-direct` - Yandex Direct API wrapper
- `click` - CLI framework
- `python-dotenv` - Environment variable management
- `tabulate` - Table formatting
- `colorama` - Terminal colors
- `tqdm` - Progress bars

Development dependencies:
- `pytest` - Testing framework
- `pytest-cov` - Coverage plugin
- `black` - Code formatter
- `flake8` - Linter

## Common Tasks

### Adding a New CLI Option

```python
@campaigns.command()
@click.option("--new-option", help="Description of new option")
@click.pass_context
def get(ctx, new_option):
    """Get campaigns"""
    if new_option:
        # Handle option
        pass
```

### Adding a New Output Format

1. Add format function in `output.py`
2. Update `format_output()` to handle new format type
3. Update `--format` option help text in commands

## Important Notes

- Always handle missing credentials gracefully with helpful error messages
- Use `--dry-run` flag for operations that modify data
- Support pagination for list operations with `--fetch-all` and `--limit`
- Maintain backward compatibility when changing command signatures
- Test changes with both sandbox and production API when possible
