"""Shared runtime tail for single-item v5 mutation commands.

Across many resource modules the single-item ``add`` and ``update`` subcommands
end with the same four-step tail: print the request body under ``--dry-run``,
otherwise build the client, post the body, and format the extracted result as
JSON. Only the service name varies (the RPC method lives in ``body`` already).
This helper hoists that tail; the per-command ``body`` construction stays in
each command.

``create_client`` is passed in by the calling command — its own module global,
resolved at call time — so ``patch.object("direct_cli.commands.<module>",
"create_client", ...)`` keeps intercepting the live path (unlike the command
factories, a normal command body re-reads the global on every call).
"""

from __future__ import annotations

from ..api import client_from_ctx
from ..output import format_output


def execute_request(ctx, service, body, dry_run, create_client):
    """Print *body* under ``--dry-run`` or post it and format the result."""
    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)
    result = getattr(client, service)().post(data=body)
    format_output(result().extract(), "json", None)
