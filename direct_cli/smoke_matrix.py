"""
Smoke-test category matrix for every Direct CLI subcommand.

The matrix answers two separate questions:

* which CLI commands may be exercised automatically; and
* which API surface each command belongs to when auditing WSDL parity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

SAFE = "SAFE"
WRITE_SANDBOX = "WRITE_SANDBOX"
DANGEROUS = "DANGEROUS"


SMOKE_MATRIX = {
    SAFE: [
        "balance",
        "adextensions.get",
        "adgroups.get",
        "adimages.get",
        "ads.get",
        "advideos.get",
        "agencyclients.get",
        "audiencetargets.get",
        "auth.list",
        "auth.status",
        "bidmodifiers.get",
        "bids.get",
        "businesses.get",
        "campaigns.get",
        "changes.check",
        "changes.check-campaigns",
        "changes.check-dictionaries",
        "clients.get",
        "creatives.get",
        "dictionaries.get",
        "dictionaries.get-geo-regions",
        "dictionaries.list-names",
        "dynamicads.get",
        "dynamicfeedadtargets.get",
        "feeds.get",
        "keywordbids.get",
        "keywords.get",
        "keywordsresearch.deduplicate",
        "keywordsresearch.has-search-volume",
        "leads.get",
        "negativekeywordsharedsets.get",
        "reports.get",
        "reports.list-types",
        "retargeting.get",
        "sitelinks.get",
        "smartadtargets.get",
        "strategies.get",
        "turbopages.get",
        "v4goals.get-retargeting-goals",
        "v4goals.get-stat-goals",
        "vcards.get",
    ],
    WRITE_SANDBOX: [
        "adextensions.add",
        "adextensions.delete",
        "adgroups.add",
        "adgroups.delete",
        "adgroups.update",
        "adimages.add",
        "adimages.delete",
        "ads.add",
        "ads.archive",
        "ads.delete",
        "ads.moderate",
        "ads.resume",
        "ads.suspend",
        "ads.unarchive",
        "ads.update",
        "advideos.add",
        "audiencetargets.add",
        "audiencetargets.delete",
        "audiencetargets.resume",
        "audiencetargets.set-bids",
        "audiencetargets.suspend",
        "bidmodifiers.add",
        "bidmodifiers.delete",
        "bidmodifiers.set",
        "bids.set",
        "bids.set-auto",
        "campaigns.add",
        "campaigns.archive",
        "campaigns.delete",
        "campaigns.resume",
        "campaigns.suspend",
        "campaigns.unarchive",
        "campaigns.update",
        "clients.update",
        "creatives.add",
        "dynamicads.add",
        "dynamicads.delete",
        "dynamicads.resume",
        "dynamicads.set-bids",
        "dynamicads.suspend",
        "dynamicfeedadtargets.add",
        "dynamicfeedadtargets.delete",
        "dynamicfeedadtargets.resume",
        "dynamicfeedadtargets.set-bids",
        "dynamicfeedadtargets.suspend",
        "feeds.add",
        "feeds.delete",
        "feeds.update",
        "keywordbids.set",
        "keywordbids.set-auto",
        "keywords.add",
        "keywords.delete",
        "keywords.resume",
        "keywords.suspend",
        "keywords.update",
        "negativekeywordsharedsets.add",
        "negativekeywordsharedsets.delete",
        "negativekeywordsharedsets.update",
        "retargeting.add",
        "retargeting.delete",
        "retargeting.update",
        "sitelinks.add",
        "sitelinks.delete",
        "smartadtargets.add",
        "smartadtargets.delete",
        "smartadtargets.resume",
        "smartadtargets.set-bids",
        "smartadtargets.suspend",
        "smartadtargets.update",
        "strategies.add",
        "strategies.archive",
        "strategies.unarchive",
        "strategies.update",
        "vcards.add",
        "vcards.delete",
    ],
    DANGEROUS: [
        # Runtime-deprecated by Yandex (error_code=3500). The CLI itself
        # rejects this command via direct_cli.utils.assert_not_runtime_deprecated;
        # registry: direct_cli.wsdl_coverage.RUNTIME_DEPRECATED_METHODS.
        "agencyclients.add",
        "agencyclients.add-passport-organization",
        "agencyclients.add-passport-organization-member",
        "agencyclients.delete",
        "agencyclients.update",
        "auth.login",
        "auth.use",
    ],
}


@dataclass(frozen=True)
class SmokeCommand:
    """A single command-to-category entry in the smoke matrix."""

    command: str
    category: str


def command_key(group_name: str, command_name: str) -> str:
    """Build the canonical matrix key for a Click subcommand."""
    return f"{group_name}.{command_name}"


def command_entries() -> list[SmokeCommand]:
    """Return all matrix entries as stable command/category records."""
    return [
        SmokeCommand(command=command, category=category)
        for category, commands in SMOKE_MATRIX.items()
        for command in commands
    ]


def command_category(command: str) -> str:
    """Return the smoke category for a command key."""
    for entry in command_entries():
        if entry.command == command:
            return entry.category
    raise KeyError(f"Command is not present in smoke matrix: {command}")


def commands_for_category(category: str) -> list[str]:
    """Return matrix commands for one category."""
    if category not in SMOKE_MATRIX:
        raise KeyError(f"Unknown smoke category: {category}")
    return list(SMOKE_MATRIX[category])


def _registered_cli_commands() -> set[str]:
    from direct_cli.cli import cli

    registered = set()
    for group_name, group in cli.commands.items():
        if hasattr(group, "commands"):
            for command_name in group.commands:
                registered.add(command_key(group_name, command_name))
        else:
            registered.add(group_name)
    return registered


def _wsdl_operations_count() -> int:
    from direct_cli.wsdl_coverage import fetch_wsdl, parse_wsdl_operations
    from direct_cli.wsdl_coverage import CANONICAL_API_SERVICES

    return sum(
        len(parse_wsdl_operations(fetch_wsdl(service, use_cache=True)))
        for service in CANONICAL_API_SERVICES
    )


def smoke_summary() -> dict:
    """Return current CLI/API smoke matrix metrics."""
    from direct_cli.cli import cli
    from direct_cli.wsdl_coverage import CANONICAL_API_SERVICES, NON_WSDL_SERVICES

    registered = _registered_cli_commands()
    non_api_groups = {"auth"}
    api_commands = {
        command
        for command in registered
        if command.split(".", 1)[0] not in non_api_groups
    }

    return {
        "total_cli_groups": len(cli.commands),
        "total_cli_subcommands": len(registered),
        "api_cli_subcommands": len(api_commands),
        "wsdl_services": len(CANONICAL_API_SERVICES),
        "non_wsdl_services": sorted(NON_WSDL_SERVICES),
        "api_services_total": len(CANONICAL_API_SERVICES) + len(NON_WSDL_SERVICES),
        "wsdl_operations": _wsdl_operations_count(),
        "categories": {
            category: len(commands) for category, commands in SMOKE_MATRIX.items()
        },
    }


def validate_matrix(commands: Iterable[str] | None = None) -> list[str]:
    """Return human-readable smoke matrix coverage errors."""
    expected = set(commands or _registered_cli_commands())
    seen = [entry.command for entry in command_entries()]
    errors = []

    duplicates = sorted({command for command in seen if seen.count(command) > 1})
    if duplicates:
        errors.append(f"Duplicate smoke matrix entries: {duplicates}")

    missing = sorted(expected - set(seen))
    if missing:
        errors.append(f"Commands missing from smoke matrix: {missing}")

    stale = sorted(set(seen) - expected)
    if stale:
        errors.append(f"Stale smoke matrix entries: {stale}")

    return errors
