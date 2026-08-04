"""Shared factory for v5 ``set-bids`` commands.

Across ``dynamicads``, ``audiencetargets``, ``smartadtargets`` and
``dynamicfeedadtargets`` the ``set-bids`` subcommand body is the same
skeleton: collect an optional target selector (``--id``/``--adgroup-id``/
``--campaign-id``), collect a resource-specific set of optional bid fields,
require at least one of each group, then post ``{"method": "setBids",
"params": {"Bids": [bid_data]}}``. Only the bid field set (and the exact
error text listing them) varies per resource. This factory hoists the single
body — modeled on :func:`direct_cli.commands._lifecycle.make_lifecycle_command`
— so each module registers its ``set-bids`` with one call.

``create_client`` is passed in by the calling module (not imported here), the
same contract as the lifecycle/get factories.
"""

from __future__ import annotations

from typing import NamedTuple

import click

from ._execute import execute_request
from ..i18n import t
from ..output import handle_api_errors


class BidField(NamedTuple):
    cli_option: str
    kwarg_name: str
    wsdl_key: str
    click_type: object
    help_text: str
    truthy: bool = False


_SELECTOR_FIELDS = (
    BidField("--id", "target_id", "Id", click.IntRange(min=1), "Target ID"),
    BidField(
        "--adgroup-id", "adgroup_id", "AdGroupId", click.IntRange(min=1), "Ad group ID"
    ),
    BidField(
        "--campaign-id",
        "campaign_id",
        "CampaignId",
        click.IntRange(min=1),
        "Campaign ID",
    ),
)


def make_set_bids_command(
    group,
    service,
    help_text,
    bid_fields,
    create_client,
    *,
    selector_error,
    bid_error,
    require_selector=True,
):
    """Build and register a v5 ``set-bids`` command on *group*.

    Args:
        group: the module's Click group; the command registers via
            ``@group.command(name="set-bids", help=help_text)``.
        service: client service attribute (``group.name`` for all four
            current callers, passed explicitly for the same patchability
            reasons as :func:`make_lifecycle_command`).
        help_text: English short help — the i18n catalog key.
        bid_fields: tuple of :class:`BidField` for the resource-specific bid
            options, in the exact order they must render in ``--help``.
            ``truthy`` (default ``False``) selects a truthy check
            (``if value:``) instead of ``is not None`` — needed for the
            untyped ``--priority`` string option, which the original
            per-module commands treated as absent on an empty string.
        create_client: the calling module's ``create_client`` symbol.
        selector_error: English error text (i18n catalog key) raised when the
            selector requirement (see *require_selector*) is not met.
        bid_error: English error text (i18n catalog key) raised when no bid
            field is provided.
        require_selector: when ``True`` (the default — ``dynamicads``,
            ``audiencetargets``, ``dynamicfeedadtargets``), a target selector
            (``--id``/``--adgroup-id``/``--campaign-id``) is required
            independent of the bid fields. ``smartadtargets`` instead only
            requires *some* field (selector or bid) to be present — its
            original command checked ``if not bid_data`` rather than the
            selector group specifically — so it passes ``False`` here to
            keep that behavior byte-identical.
    """

    bid_fields = tuple(
        field if isinstance(field, BidField) else BidField(*field)
        for field in bid_fields
    )
    all_fields = _SELECTOR_FIELDS + bid_fields

    selector_keys = {field.wsdl_key for field in _SELECTOR_FIELDS}
    bid_keys = {field.wsdl_key for field in bid_fields}

    def _command(ctx, dry_run, **kwargs):
        bid_data = {}
        for field in all_fields:
            value = kwargs[field.kwarg_name]
            present = value if field.truthy else value is not None
            if present:
                bid_data[field.wsdl_key] = value

        if require_selector:
            if not (selector_keys & bid_data.keys()):
                raise click.UsageError(t(selector_error))
        elif not bid_data:
            raise click.UsageError(t(selector_error))
        if not (bid_keys & bid_data.keys()):
            raise click.UsageError(t(bid_error))

        body = {"method": "setBids", "params": {"Bids": [bid_data]}}
        execute_request(ctx, service, body, dry_run, create_client)

    _command.__name__ = "set_bids"
    _command.__qualname__ = "set_bids"

    _command = handle_api_errors(_command)
    _command = click.pass_context(_command)
    _command = click.option(
        "--dry-run", is_flag=True, help="Show request without sending"
    )(_command)
    for field in reversed(all_fields):
        _command = click.option(
            field.cli_option,
            field.kwarg_name,
            type=field.click_type,
            help=field.help_text,
        )(_command)

    return group.command(name="set-bids", help=help_text)(_command)
