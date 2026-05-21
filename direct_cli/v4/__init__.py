"""Shared helpers for Yandex Direct v4 Live commands."""

from typing import Any, Optional

import click

from direct_cli.v4_contracts import (
    PARAM_UNDOCUMENTED_SHAPE_MSG,
    validate_v4_body_shape,
)


def build_v4_body(method: str, param: Optional[Any] = None) -> dict:
    """Build a v4 Live request body."""
    body = {"method": method}
    if param is not None:
        body["param"] = param
    return body


def call_v4(client: Any, method: str, param: Optional[Any] = None) -> Any:
    """Call one v4 Live method and return the extracted response payload."""
    body = build_v4_body(method, param)

    errors = validate_v4_body_shape(method, body)
    # Split by error class: "param shape is undocumented" is a soft
    # contract gap (5 real methods like PayCampaignsByCard) — warn and
    # continue. Anything else (shape mismatch, method mismatch) is a
    # caller bug and must block the request.
    hard_errors = [e for e in errors if PARAM_UNDOCUMENTED_SHAPE_MSG not in e]
    if hard_errors:
        raise click.UsageError("; ".join(hard_errors))
    if errors:
        click.echo(
            f"warning: v4 method {method!r} has an undocumented param "
            "shape; sending request as-is.",
            err=True,
        )

    result = client.v4live().post(data=body)
    return result().extract()
