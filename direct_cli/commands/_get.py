"""Shared factory for v5 read (``get``) commands.

Across many resource modules the ``get`` subcommand body is the same skeleton:
resolve the field names, build a ``SelectionCriteria`` dict, assemble the common
params, then either print the request (``--dry-run``) or post it and format the
extracted / iterated result. Only a few values vary per resource: the service
name, the default-field key, the ``--ids`` help / required-ness, any extra
criteria options, and how the criteria dict is built. This factory hoists the
single body — modeled on :func:`direct_cli.commands._lifecycle.make_lifecycle_command`
— so each module registers its ``get`` with one call.

``create_client`` is passed in by the calling module (not imported here), the
same contract as the lifecycle factory: the ``--dry-run`` path needs no client,
and the live path runs the module's real ``create_client`` (the VCR cassette
read-tests replay it at the ``requests`` transport, so they are unaffected).
"""

from __future__ import annotations

import click

from ..api import client_from_ctx, resolve_module_create_client
from ..output import format_output, handle_api_errors
from ..utils import (
    build_common_params,
    get_default_fields,
    get_options,
    parse_csv_strings,
    parse_ids,
)


def _default_ids_criteria(ids):
    """Standard SelectionCriteria: an optional integer ``Ids`` list."""
    criteria = {}
    if ids:
        criteria["Ids"] = parse_ids(ids)
    return criteria


def make_get_command(
    group,
    create_client,
    *,
    default_fields_key,
    help_text=None,
    ids_help="Comma-separated IDs",
    ids_required=False,
    extra_options=(),
    criteria_builder=None,
):
    """Build and register a v5 ``get`` command on *group*.

    Args:
        group: the module's Click group; the command registers as ``get`` and
            the client service defaults to ``group.name``.
        create_client: the calling module's ``create_client`` symbol, forwarded
            to :func:`client_from_ctx` (lifecycle-factory patchability contract).
        default_fields_key: key passed to :func:`get_default_fields` for the
            default ``FieldNames``.
        help_text: English short help (the i18n catalog key) — the former ``get``
            docstring, localized at render time.
        ids_help: help text for the ``--ids`` option.
        ids_required: whether ``--ids`` is required.
        extra_options: extra ``click.option`` decorators for resource criteria,
            given in ``--help`` display order. They are applied between ``--ids``
            and the shared :func:`get_options` stack so the option order is kept.
        criteria_builder: callable mapping the parsed options to a
            ``SelectionCriteria`` dict. It receives ``ids`` plus every extra
            option as keyword args; defaults to an optional ``Ids`` list.

    Returns:
        The registered Click command.
    """
    svc = group.name
    module_name = group.callback.__module__
    build_criteria = criteria_builder or (lambda ids, **_: _default_ids_criteria(ids))

    @click.pass_context
    @handle_api_errors
    def get(
        ctx, ids, limit, fetch_all, output_format, output, fields, dry_run, **kwargs
    ):
        field_names = parse_csv_strings(fields) or get_default_fields(
            default_fields_key
        )
        criteria = build_criteria(ids, **kwargs)
        params = build_common_params(
            criteria=criteria, field_names=field_names, limit=limit
        )
        body = {"method": "get", "params": params}

        if dry_run:
            format_output(body, "json", None)
            return

        # Resolve ``create_client`` from the live command module so a
        # ``patch.object(<module>, "create_client", ...)`` intercepts the live
        # path (the closure would otherwise pin the import-time function).
        resolved_create_client = resolve_module_create_client(
            module_name, create_client
        )
        client = client_from_ctx(ctx, resolved_create_client)
        result = getattr(client, svc)().post(data=body)

        if fetch_all:
            items = []
            for item in result().iter_items():
                items.append(item)
            format_output(items, output_format, output)
        else:
            format_output(result().extract(), output_format, output)

    # Apply the option decorators in the original stack order so ``--help`` lists
    # ``--ids``, then any resource options, then the six ``get_options`` entries.
    get = get_options(get)
    for option in reversed(extra_options):
        get = option(get)
    get = click.option("--ids", required=ids_required, help=ids_help)(get)
    return group.command(name="get", help=help_text)(get)
