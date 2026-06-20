"""Shared factory for v5 lifecycle commands (delete/suspend/resume/archive/...).

Across ~18 resource modules the lifecycle subcommands
(``delete``/``suspend``/``resume``/``archive``/``unarchive`` and ``ads moderate``)
are byte-for-byte identical except for four values: the RPC ``method`` sent in
the request body, the service name on the client, the id argument's name/option,
and the help text. This module hoists the single command body — previously
duplicated as ``campaigns._make_lifecycle_command`` (dedup epic #491, C1) — into
one factory every module can reuse (#491 C9).

The factory preserves the CLI surface exactly: the same command name, the same
required id option (``--id``/``--hash``), the same ``--dry-run`` flag, and the
same English help strings (the i18n catalog keys, localized at render time by
``cli._LocalizedHelpMixin`` / ``LocalizedOption``). The request payload is
unchanged: ``{"method": <method>, "params": {"SelectionCriteria": {<key>: [id]}}}``.

``create_client`` is passed in by the calling module (not imported here) so that
``@patch("direct_cli.commands.<module>.create_client")`` keeps intercepting, the
same patchability contract as :func:`direct_cli.api.client_from_ctx`.
"""

from __future__ import annotations

import click

from ..api import client_from_ctx
from ..output import format_output, handle_api_errors


def make_lifecycle_command(
    group,
    method,
    help_text,
    id_param,
    id_help,
    create_client,
    *,
    service=None,
    id_option="--id",
    id_type=int,
    criteria_key="Ids",
):
    """Build and register a v5 lifecycle command on *group*.

    Args:
        group: the module's Click group; the command registers via
            ``@group.command(name=method, ...)`` and the service defaults to
            ``group.name``.
        method: RPC method sent in the body (``delete``/``suspend``/``resume``/
            ``archive``/``unarchive``/``moderate``).
        help_text: English short help — the i18n catalog key (== the former
            command docstring) localized at render time.
        id_param: the callback parameter name (``ad_id``/``keyword_id``/...),
            kept identical so ``--help`` and tracebacks are unchanged.
        id_help: English help for the id option — the i18n catalog key.
        create_client: the calling module's ``create_client`` symbol, forwarded
            to :func:`client_from_ctx` to preserve per-module patchability.
        service: client service attribute; defaults to ``group.name``.
        id_option: the id option flag (``--id`` by default, ``--hash`` for
            ad images).
        id_type: the id option Click type (``int`` by default, ``str`` for the
            ad-image hash).
        criteria_key: the ``SelectionCriteria`` key (``Ids`` by default,
            ``AdImageHashes`` for ad images).

    Returns:
        The registered Click command (also assigned to a module global so the
        ``@group.command`` registration sticks).
    """

    # A lifecycle id is always a positive object id; type=int used to accept 0
    # and negatives and forward them to the API (opaque rejection). For the
    # integer path, validate min=1 before the request (issue #558). The
    # ad-image path keeps id_type=str (a hash is not an integer) and is
    # untouched.
    option_type = click.IntRange(min=1) if id_type is int else id_type

    @group.command(name=method, help=help_text)
    @click.option(id_option, id_param, required=True, type=option_type, help=id_help)
    @click.option("--dry-run", is_flag=True, help="Show request without sending")
    @click.pass_context
    @handle_api_errors
    def _command(ctx, dry_run, **kwargs):
        identifier = kwargs[id_param]
        body = {
            "method": method,
            "params": {"SelectionCriteria": {criteria_key: [identifier]}},
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = client_from_ctx(ctx, create_client)

        result = getattr(client, service or group.name)().post(data=body)
        format_output(result().extract(), "json", None)

    return _command


def register_lifecycle_commands(group, id_param, id_help, create_client, specs):
    """Register a batch of lifecycle commands sharing one id option.

    Replaces the per-module ``_<resource>_lifecycle`` wrappers: each
    ``(method, help_text)`` pair in *specs* is registered via
    :func:`make_lifecycle_command` with the shared *id_param* / *id_help* /
    *create_client*. The commands register themselves on *group* inside the
    factory, so no return value is needed.
    """
    for method, help_text in specs:
        make_lifecycle_command(
            group, method, help_text, id_param, id_help, create_client
        )
