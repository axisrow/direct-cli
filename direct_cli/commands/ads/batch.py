"""Batch (``--from-file`` / ``--ads-json``) row handling for ``ads`` (#603).

A batch row is the single-item flag set keyed by the kebab flag name without the
leading dashes. Each row is coerced through the *same* Click ParamType as the
single-flag path and then handed to :mod:`.objects`, so batch and single-item
mode emit byte-identical payloads.

The param-type maps are built lazily from the registered commands (imported
inside the function) — the command module imports this one, so a module-level
import here would be circular.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import click

from ...i18n import t
from .. import _batch
from .objects import (
    _ADS_ADD_FLAG_FOR,
    _ADS_UPDATE_FLAG_FOR,
    build_ad_object,
    build_ad_update_object,
)

# Documented per-call limit for ads.add is 1000 (Yandex docs, ads/add page);
# the WSDL declares the Ads array unbounded. ADS_ADD_MAX_BATCH is a conservative
# CHUNK SIZE (not the ceiling): a partial failure rolls back at most this many
# ads. 100 keeps round-trips reasonable for hundred-ad uploads while bounding
# the partial-failure blast radius.
ADS_ADD_MAX_BATCH = 100


def _create_client():
    """Return the command module's ``create_client``, resolved at call time.

    The bulk helpers must go through the *command module's* global (not a copy
    imported here) so ``patch("direct_cli.commands.ads._cli.create_client", ...)``
    keeps intercepting the batch path exactly as it does the single-item path.
    """
    from . import _cli

    return _cli.create_client


# Batch row keys are the kebab flag names without the leading "--" (so a row
# reads like `ads add --help`); map them to build_ad_object's dest names.
_ADS_ROW_KEY_TO_DEST = {label[2:]: dest for dest, label in _ADS_ADD_FLAG_FOR.items()}
_ADS_ROW_ALLOWED_KEYS = frozenset({"type", "adgroup-id", *_ADS_ROW_KEY_TO_DEST})
# Multi-value flags accept a JSON list of the existing micro-format strings; keep
# this in sync with the `multiple=True` add options (--mobile-app-feature,
# --feed-filter-condition).
_ADS_ROW_MULTI_KEYS = {"mobile-app-feature", "feed-filter-condition"}


def _ads_add_param_types():
    """Map each ``ads add`` row key (kebab, no ``--``) to its Click ParamType.

    Built lazily from the registered command so a batch row is coerced through
    the *exact same* type as the single-flag path (issue #562 review): a value
    like ``--price-extension-price`` (MICRO_RUBLES) or ``--adgroup-id``
    (IntRange(min=1)) gets the identical conversion/validation, so batch and
    single produce byte-identical payloads instead of forwarding raw JSON.
    """
    from ._cli import add

    types: Dict[str, click.ParamType] = {}
    for param in add.params:
        if not isinstance(param, click.Option):
            continue
        key = param.opts[0].lstrip("-")
        # click.STRING is the no-op default; only typed options need coercion.
        if param.type is not click.STRING:
            types[key] = param.type
    return types


_ADS_ROW_PARAM_TYPES: Optional[Dict[str, click.ParamType]] = None


def _coerce_ad_row_field(key: str, value: Any, row_index: int) -> Any:
    """Coerce one scalar batch-row value to its single-flag form.

    The CLI only ever sees string tokens, so a batch row must too: this rejects
    JSON arrays/objects/``null`` for any scalar field, stringifies JSON
    int/float/bool scalars, then runs typed fields (``param_type is not None``)
    through their single-flag Click type. The result is that batch and single
    emit byte-identical payloads — e.g. ``"title": 123`` becomes ``"123"`` (as a
    CLI token would), ``"adgroup-id": 1.9`` is rejected (not truncated to ``1``),
    and ``"adgroup-id": null`` / ``[1]`` raise a clear ``Ad row N field`` error
    instead of an uncaught ``TypeError``. Mirrors keywords' ``_coerce_keyword_field``.
    """
    global _ADS_ROW_PARAM_TYPES
    if _ADS_ROW_PARAM_TYPES is None:
        _ADS_ROW_PARAM_TYPES = _ads_add_param_types()
    param_type = _ADS_ROW_PARAM_TYPES.get(key)

    # A scalar flag never accepts a JSON array/object/null — the single-flag CLI
    # can only express a scalar token. Reject with row/field context up front.
    if value is None or isinstance(value, (list, dict)):
        raise click.UsageError(
            t("Ad row {row_index} field {key!r}: expected a scalar, got {arg0}").format(
                row_index=row_index, key=key, arg0=type(value).__name__
            )
        )

    # The CLI passes every value as a string token; match that so a JSON int for
    # a string field becomes "123" (not 123) and a typed field parses identically.
    token = str(value)

    if param_type is None:
        return token

    if isinstance(value, bool):
        raise click.UsageError(
            t("Ad row {row_index} field {key!r}: expected {arg0}, got bool").format(
                row_index=row_index, key=key, arg0=param_type.name
            )
        )
    try:
        return param_type.convert(token, None, None)
    except click.exceptions.BadParameter as exc:
        raise click.UsageError(
            t("Ad row {row_index} field {key!r}: {arg0}").format(
                row_index=row_index, key=key, arg0=exc.format_message()
            )
        )


def _normalize_ad_row(
    row: Any, row_index: int, default_adgroup_id: Optional[int]
) -> Dict[str, Any]:
    """Translate one flag-form batch row into a built ad object.

    The row keys are kebab flag names without "--" plus ``type`` and
    ``adgroup-id``. Each typed field is coerced through its single-flag Click
    type so batch and single emit byte-identical payloads. Unknown keys are
    rejected; ``build_ad_object`` does the subtype validation, with its
    UsageError re-raised under an ``Ad row N`` prefix so the operator sees which
    row failed.
    """
    if not isinstance(row, dict):
        raise click.UsageError(
            t("Ad row {row_index}: expected JSON object, got {arg0}").format(
                row_index=row_index, arg0=type(row).__name__
            )
        )

    unknown = sorted(set(row) - _ADS_ROW_ALLOWED_KEYS)
    if unknown:
        raise click.UsageError(
            t(
                "Unknown field {arg0!r} in ad row {row_index}; allowed: {allowed}"
            ).format(
                arg0=unknown[0],
                row_index=row_index,
                allowed=", ".join(sorted(_ADS_ROW_ALLOWED_KEYS)),
            )
        )

    if "adgroup-id" in row:
        adgroup_id = _coerce_ad_row_field("adgroup-id", row["adgroup-id"], row_index)
    else:
        adgroup_id = default_adgroup_id
    if adgroup_id is None:
        raise click.UsageError(
            t(
                "Ad row {row_index}: missing 'adgroup-id' and no default "
                "--adgroup-id provided"
            ).format(row_index=row_index)
        )

    ad_type = row.get("type")
    flags: Dict[str, Any] = {}
    for key, dest in _ADS_ROW_KEY_TO_DEST.items():
        if key not in row:
            continue
        value = row[key]
        if key in _ADS_ROW_MULTI_KEYS:
            # A repeatable flag (--mobile-app-feature/--feed-filter-condition) is
            # a JSON list of the existing micro-format strings; reject anything
            # else with row/field context instead of crashing downstream.
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                raise click.UsageError(
                    t(
                        "Ad row {row_index} field {key!r}: expected a JSON array "
                        "of strings"
                    ).format(row_index=row_index, key=key)
                )
            value = tuple(value)
        else:
            value = _coerce_ad_row_field(key, value, row_index)
        flags[dest] = value

    mobile_provided = flags.pop("mobile", None)

    try:
        return build_ad_object(
            adgroup_id=adgroup_id,
            ad_type=ad_type,
            mobile_provided=mobile_provided,
            flags=flags,
            flag_for=_ADS_ADD_FLAG_FOR,
        )
    except click.UsageError as exc:
        raise click.UsageError(
            t("Ad row {row_index}: {arg0}").format(
                row_index=row_index, arg0=exc.format_message()
            )
        )


def _bulk_add_ads(ctx, *, adgroup_id, from_file, ads_json, dry_run):
    if from_file is not None:
        raw_rows = _batch.load_jsonl_rows(from_file)
    else:
        raw_rows = _batch.load_inline_rows(
            ads_json or "",
            invalid_json_key="--ads-json: invalid JSON: {arg0}",
            not_array_key="--ads-json must be a JSON array of ad objects",
        )

    if not raw_rows:
        raise click.UsageError(t("Input contains no ad rows."))

    items = [
        _normalize_ad_row(row, idx, adgroup_id)
        for idx, row in enumerate(raw_rows, start=1)
    ]

    _batch.send_batch(
        ctx,
        resource="ads",
        method="add",
        payload_key="Ads",
        items=items,
        max_batch=ADS_ADD_MAX_BATCH,
        create_client=_create_client(),
        dry_run=dry_run,
        noun="ads",
    )


# Batch row keys for `ads update` are the kebab flag names without "--" plus
# "id" and "type"; map them to build_ad_update_object's dest names.
_ADS_UPDATE_ROW_KEY_TO_DEST = {
    label[2:]: dest for dest, label in _ADS_UPDATE_FLAG_FOR.items()
}
_ADS_UPDATE_ROW_ALLOWED_KEYS = frozenset({"id", "type", *_ADS_UPDATE_ROW_KEY_TO_DEST})
# Repeatable flags accept a JSON list of the existing micro-format strings; keep
# in sync with the `multiple=True` update options.
_ADS_UPDATE_ROW_MULTI_KEYS = {"mobile-app-feature", "feed-filter-condition"}
# --clear-image-hash is a boolean flag (is_flag=True): a row expresses it as a
# JSON bool, not a string token, so it bypasses _coerce_ad_update_row_field.
_ADS_UPDATE_ROW_BOOL_KEYS = {"clear-image-hash"}


def _ads_update_param_types():
    """Map each ``ads update`` row key (kebab, no ``--``) to its Click ParamType.

    Built lazily from the registered command so a batch row is coerced through
    the *exact same* type as the single-flag path (issue #563): e.g.
    ``--price-extension-price`` (MICRO_RUBLES) or ``--id`` (IntRange(min=1)) get
    the identical conversion/validation, so batch and single produce
    byte-identical payloads instead of forwarding raw JSON. Boolean flags
    (``--clear-image-hash``) are excluded — they are handled as JSON bools.
    """
    from ._cli import update

    types: Dict[str, click.ParamType] = {}
    for param in update.params:
        if not isinstance(param, click.Option):
            continue
        if param.is_flag:
            continue
        key = param.opts[0].lstrip("-")
        # click.STRING is the no-op default; only typed options need coercion.
        if param.type is not click.STRING:
            types[key] = param.type
    return types


_ADS_UPDATE_ROW_PARAM_TYPES: Optional[Dict[str, click.ParamType]] = None


def _coerce_ad_update_row_field(key: str, value: Any, row_index: int) -> Any:
    """Coerce one scalar batch-row value to its single-flag form (issue #563).

    Mirrors ``_coerce_ad_row_field``: rejects JSON arrays/objects/``null`` for
    any scalar field, stringifies JSON int/float/bool scalars, then runs typed
    fields through their single-flag Click type so batch and single emit
    byte-identical payloads (``"id": 1.9`` is rejected, not truncated to ``1``;
    ``"id": null`` / ``[1]`` raise a clear ``Ad update row N field`` error
    instead of an uncaught ``TypeError``).
    """
    global _ADS_UPDATE_ROW_PARAM_TYPES
    if _ADS_UPDATE_ROW_PARAM_TYPES is None:
        _ADS_UPDATE_ROW_PARAM_TYPES = _ads_update_param_types()
    param_type = _ADS_UPDATE_ROW_PARAM_TYPES.get(key)

    if value is None or isinstance(value, (list, dict)):
        raise click.UsageError(
            t(
                "Ad update row {row_index} field {key!r}: expected a scalar, "
                "got {arg0}"
            ).format(row_index=row_index, key=key, arg0=type(value).__name__)
        )

    token = str(value)

    if param_type is None:
        return token

    if isinstance(value, bool):
        raise click.UsageError(
            t(
                "Ad update row {row_index} field {key!r}: expected {arg0}, got bool"
            ).format(row_index=row_index, key=key, arg0=param_type.name)
        )
    try:
        return param_type.convert(token, None, None)
    except click.exceptions.BadParameter as exc:
        raise click.UsageError(
            t("Ad update row {row_index} field {key!r}: {arg0}").format(
                row_index=row_index, key=key, arg0=exc.format_message()
            )
        )


def _normalize_ad_update_row(row: Any, row_index: int) -> Dict[str, Any]:
    """Translate one flag-form batch row into a built ad-update object.

    The row keys are kebab flag names without "--" plus ``id`` (required, the
    update target) and ``type`` (required). Each typed field is coerced through
    its single-flag Click type so batch and single emit byte-identical payloads.
    Unknown keys are rejected; ``build_ad_update_object`` does the subtype
    validation, its UsageError re-raised under an ``Ad update row N`` prefix.
    """
    if not isinstance(row, dict):
        raise click.UsageError(
            t("Ad update row {row_index}: expected JSON object, got {arg0}").format(
                row_index=row_index, arg0=type(row).__name__
            )
        )

    unknown = sorted(set(row) - _ADS_UPDATE_ROW_ALLOWED_KEYS)
    if unknown:
        raise click.UsageError(
            t(
                "Unknown field {arg0!r} in ad update row {row_index}; "
                "allowed: {allowed}"
            ).format(
                arg0=unknown[0],
                row_index=row_index,
                allowed=", ".join(sorted(_ADS_UPDATE_ROW_ALLOWED_KEYS)),
            )
        )

    if "id" not in row:
        raise click.UsageError(
            t("Ad update row {row_index}: missing required 'id'").format(
                row_index=row_index
            )
        )
    ad_id = _coerce_ad_update_row_field("id", row["id"], row_index)

    ad_type = row.get("type")

    flags: Dict[str, Any] = {}
    for key, dest in _ADS_UPDATE_ROW_KEY_TO_DEST.items():
        if key not in row:
            continue
        value = row[key]
        if key in _ADS_UPDATE_ROW_BOOL_KEYS:
            # A boolean flag (--clear-image-hash) is a JSON bool in a row.
            if not isinstance(value, bool):
                raise click.UsageError(
                    t(
                        "Ad update row {row_index} field {key!r}: expected a JSON "
                        "boolean"
                    ).format(row_index=row_index, key=key)
                )
            # clear-image-hash:false is the flag-absent state (skip it); only a
            # true value sets the flag, matching the single-flag command.
            if not value:
                continue
        elif key in _ADS_UPDATE_ROW_MULTI_KEYS:
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                raise click.UsageError(
                    t(
                        "Ad update row {row_index} field {key!r}: expected a JSON "
                        "array of strings"
                    ).format(row_index=row_index, key=key)
                )
            value = tuple(value)
        else:
            value = _coerce_ad_update_row_field(key, value, row_index)
        flags[dest] = value

    # Match single-mode ordering: the command validates --type before the
    # --image-hash/--clear-image-hash mutex, so check the missing 'type' first.
    if ad_type is None:
        raise click.UsageError(
            t("Ad update row {row_index}: missing required 'type'").format(
                row_index=row_index
            )
        )

    # Reproduce the command-level --image-hash/--clear-image-hash mutex per row.
    if flags.get("image_hash") and flags.get("clear_image_hash"):
        raise click.UsageError(
            t(
                "Ad update row {row_index}: use either 'image-hash' or "
                "'clear-image-hash', not both"
            ).format(row_index=row_index)
        )

    try:
        return build_ad_update_object(
            ad_id=ad_id,
            ad_type=ad_type,
            flags=flags,
            flag_for=_ADS_UPDATE_FLAG_FOR,
        )
    except click.UsageError as exc:
        raise click.UsageError(
            t("Ad update row {row_index}: {arg0}").format(
                row_index=row_index, arg0=exc.format_message()
            )
        )


def _bulk_update_ads(ctx, *, from_file, ads_json, dry_run):
    if from_file is not None:
        raw_rows = _batch.load_jsonl_rows(from_file)
    else:
        raw_rows = _batch.load_inline_rows(
            ads_json or "",
            invalid_json_key="--ads-json: invalid JSON: {arg0}",
            not_array_key="--ads-json must be a JSON array of ad objects",
        )

    if not raw_rows:
        raise click.UsageError(t("Input contains no ad rows."))

    items = [
        _normalize_ad_update_row(row, idx) for idx, row in enumerate(raw_rows, start=1)
    ]

    _batch.send_batch(
        ctx,
        resource="ads",
        method="update",
        payload_key="Ads",
        items=items,
        max_batch=ADS_ADD_MAX_BATCH,
        create_client=_create_client(),
        dry_run=dry_run,
        noun="ads",
        result_key="UpdateResults",
    )
