"""Shared CLI subtype-flag incompatibility guard.

``campaigns``, ``adgroups`` and ``bidmodifiers`` all reject typed flags that do
not belong to the chosen ``--type``, with a per-resource error string keyed on
the resource's own placeholder (``{command_type}`` / ``{group_type}`` /
``{modifier_type}``). The caller owns the i18n source string so every
translation-catalog entry stays referenced byte-for-byte; this module owns only
the ``(allowed, provided) -> incompatible-list`` computation and the raise.

``ads`` keeps its own variant: it additionally maps internal field names to
flags and lists the allowed flags in the message (a distinct i18n key), so it is
intentionally NOT routed through here.
"""

from typing import Iterable, Mapping

import click

from .i18n import t


def reject_incompatible_flags(
    allowed_flags: Iterable[str],
    provided_flags: Mapping[str, object],
    *,
    message: str,
    type_value: str,
    type_field: str,
) -> None:
    """Raise ``UsageError`` if any provided flag is outside ``allowed_flags``.

    A flag counts as "provided" iff its value is not in ``(None, ())`` — the
    union of the three pre-dedup conditions (``is not None``, ``!= ()``,
    ``not in (None, ())``), proven equivalent at every routed call site
    (``campaigns`` and ``bidmodifiers`` never pass ``()``; ``adgroups`` must
    filter it).

    ``message`` is the English source string the caller passes to :func:`t`
    (e.g. ``"{arg0} is not compatible with --type {group_type}."``); it is
    formatted with ``arg0`` plus ``{type_field: type_value}`` so each resource
    keeps its own catalog key and rendered output unchanged.
    """
    incompatible = [
        flag
        for flag, value in provided_flags.items()
        if value not in (None, ()) and flag not in allowed_flags
    ]
    if incompatible:
        raise click.UsageError(
            t(message).format(
                **{"arg0": ", ".join(sorted(incompatible)), type_field: type_value}
            )
        )
