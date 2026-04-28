"""Shared helpers for Yandex Direct v4 Live commands."""

from typing import Any, Optional


def build_v4_body(method: str, param: Optional[Any] = None) -> dict:
    """Build a v4 Live request body."""
    body = {"method": method}
    if param is not None:
        body["param"] = param
    return body


def call_v4(client: Any, method: str, param: Optional[Any] = None) -> Any:
    """Call one v4 Live method and return the extracted response payload."""
    result = client.v4live().post(data=build_v4_body(method, param))
    return result().extract()
