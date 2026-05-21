"""Shared helpers for Yandex Direct v4 Live commands."""

from typing import Any, Optional

import click

from direct_cli.v4_contracts import (
    PARAM_UNDOCUMENTED_SHAPE_MSG,
    SAFETY_DANGEROUS,
    SAFETY_WRITE,
    get_v4_contract,
    validate_v4_body_shape,
)

_UNSAFE_SAFETY_LEVELS = frozenset({SAFETY_WRITE, SAFETY_DANGEROUS})


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
    # Hard errors (shape mismatch, method mismatch) always block.
    hard_errors = [e for e in errors if PARAM_UNDOCUMENTED_SHAPE_MSG not in e]
    if hard_errors:
        raise click.UsageError("; ".join(hard_errors))

    if errors:
        # Only undocumented-shape errors remain. Fail-closed when the
        # contract is write/dangerous — we will not blindly post a
        # financial or write operation whose payload shape we cannot
        # verify. For read-class undocumented methods (e.g.
        # GetKeywordsSuggestion) a soft warning is acceptable.
        safety = get_v4_contract(method).safety
        if safety in _UNSAFE_SAFETY_LEVELS:
            raise click.UsageError(
                f"refusing to send v4 method {method!r}: param shape is "
                f"undocumented and safety is {safety!r}. "
                "Add a documented param_shape to V4_METHOD_CONTRACTS "
                "before exposing this method through the CLI."
            )
        click.echo(
            f"warning: v4 method {method!r} has an undocumented param "
            "shape; sending request as-is.",
            err=True,
        )

    result = client.v4live().post(data=body)
    return result().extract()
