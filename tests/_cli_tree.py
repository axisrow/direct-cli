"""Typed lookup of registered CLI groups (``cli.commands`` holds Commands)."""

from typing import Any, Dict

import click

from direct_cli.cli import cli


def registered_group(name: str) -> click.Group:
    group = cli.commands[name]
    assert isinstance(group, click.Group), f"{name} is not a click.Group"
    return group


def registered_commands(name: str) -> Dict[str, Any]:
    """Subcommands of *name*, typed Any: v4 commands carry the ad-hoc
    ``v4_method``/``v4_contract`` attributes set by ``v4_method_contract``."""
    return dict(registered_group(name).commands)
