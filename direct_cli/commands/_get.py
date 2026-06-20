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
from ..i18n import t
from ..output import format_output, handle_api_errors
from ..utils import (
    build_common_params,
    enforce_criteria_array_limits,
    get_default_fields,
    get_options,
    parse_csv_strings,
    parse_csv_upper,
    parse_ids,
    parse_nested_field_names,
)


def _default_ids_criteria(ids, key="Ids"):
    """Standard SelectionCriteria: an optional integer id list under *key*.

    *key* is ``"Ids"`` for almost every resource; ``clients`` labels the same
    ``--ids`` option ``ClientIds`` in its SelectionCriteria.
    """
    criteria = {}
    if ids:
        criteria[key] = parse_ids(ids)
    return criteria


def ids_adgroup_campaign_states_criteria(
    ids, adgroup_ids=None, campaign_ids=None, states=None, **_
):
    """SelectionCriteria for the dynamic/smart ad-target ``get`` commands.

    Optional integer ``Ids`` / ``AdGroupIds`` / ``CampaignIds`` lists plus an
    upper-cased ``States`` list (an empty ``--states`` CSV maps to ``[]``), in
    that key order — the shared shape of ``dynamicads``, ``smartadtargets`` and
    ``dynamicfeedadtargets``.
    """
    criteria = _default_ids_criteria(ids)
    if adgroup_ids:
        criteria["AdGroupIds"] = parse_ids(adgroup_ids)
    if campaign_ids:
        criteria["CampaignIds"] = parse_ids(campaign_ids)
    if states:
        criteria["States"] = parse_csv_upper(states) or []
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
    criteria_limits=None,
    require_criteria_message=None,
    nested_field_options=(),
    ids_criteria_key="Ids",
    fields_help="Comma-separated field names",
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
        criteria_limits: optional ``{SelectionCriteria key: max count}`` dict
            enforced via :func:`enforce_criteria_array_limits` (command name
            ``"<group> get"``) before the request is built.
        require_criteria_message: optional i18n key; when set, an empty
            ``SelectionCriteria`` raises ``UsageError`` with this message
            (the "provide at least one filter" guard).
        nested_field_options: tuple of ``(flag, WSDL key, help)`` for nested
            ``*FieldNames`` projections (e.g. ``("--sitelink-field-names",
            "SitelinkFieldNames", "…")``). Each renders a ``click.option``
            between ``--fields`` and ``--dry-run`` and is parsed via
            :func:`parse_nested_field_names` (which rejects a provided-but-empty
            CSV), then merged into the request params after the common params.
        ids_criteria_key: SelectionCriteria key for the default ``--ids``
            builder (``"Ids"`` by default; ``clients`` uses ``"ClientIds"``).
            Ignored when a custom *criteria_builder* is given.
        fields_help: help text for the ``--fields`` option (a few resources use
            a resource-specific wording instead of the shared default).

    Returns:
        The registered Click command.
    """
    # svc doubles as the client service attribute (``getattr(client, svc)``) and
    # the ``criteria_limits`` error prefix (``f"{svc} get"``); both assume the
    # group name matches the API service name, which holds for every current
    # resource module.
    svc = group.name
    module_name = group.callback.__module__
    build_criteria = criteria_builder or (
        lambda ids, **_: _default_ids_criteria(ids, ids_criteria_key)
    )
    # (WSDL key, callback kwarg) for each nested *FieldNames option; Click maps
    # ``--sitelink-field-names`` to the ``sitelink_field_names`` kwarg.
    nested_specs = tuple(
        (wsdl_key, flag[2:].replace("-", "_"))
        for flag, wsdl_key, _help in nested_field_options
    )

    @click.pass_context
    @handle_api_errors
    def get(
        ctx, ids, limit, fetch_all, output_format, output, fields, dry_run, **kwargs
    ):
        field_names = parse_csv_strings(fields) or get_default_fields(
            default_fields_key
        )
        criteria = build_criteria(ids, **kwargs)
        if criteria_limits:
            enforce_criteria_array_limits(
                criteria, criteria_limits, command_name=f"{svc} get"
            )
        if require_criteria_message and not criteria:
            raise click.UsageError(t(require_criteria_message))
        params = build_common_params(
            criteria=criteria, field_names=field_names, limit=limit
        )
        if nested_specs:
            raw_nested = tuple(
                (wsdl_key, kwargs[kwarg]) for wsdl_key, kwarg in nested_specs
            )
            params.update(parse_nested_field_names(raw_nested))
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
    # ``--ids``, then any resource options, then the ``get_options`` entries (with
    # any nested ``*FieldNames`` options rendered between ``--fields`` and
    # ``--dry-run``).
    nested_click_options = tuple(
        click.option(flag, help=help_text)
        for flag, _wsdl_key, help_text in nested_field_options
    )
    get = get_options(get, nested_options=nested_click_options, fields_help=fields_help)
    for option in reversed(extra_options):
        get = option(get)
    get = click.option("--ids", required=ids_required, help=ids_help)(get)
    return group.command(name="get", help=help_text)(get)
