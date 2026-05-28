"""Runtime shape validation for V4 Live calls. See issue #182."""

from unittest.mock import MagicMock, patch

import click
import pytest

from direct_cli.v4 import call_v4
from direct_cli.v4_contracts import (
    PARAM_ARRAY,
    PARAM_OBJECT,
    PARAM_OPTIONAL_OBJECT,
    PARAM_SCALAR,
    PARAM_UNDOCUMENTED,
    PARAM_UNDOCUMENTED_SHAPE_MSG,
    SAFETY_DANGEROUS,
    SAFETY_READ,
    SAFETY_WRITE,
    V4_METHOD_CONTRACTS,
)


def _first_method_with_shape(shape: str) -> str:
    """Pick a registry method by shape — keeps tests resilient to edits."""
    for method, contract in V4_METHOD_CONTRACTS.items():
        if contract.param_shape == shape:
            return method
    raise AssertionError(f"No v4 method registered with param_shape={shape!r}")


def _first_method_with_shape_and_safety(shape: str, safety: str) -> str:
    """Pick a registry method by (shape, safety)."""
    for method, contract in V4_METHOD_CONTRACTS.items():
        if contract.param_shape == shape and contract.safety == safety:
            return method
    raise AssertionError(
        f"No v4 method registered with param_shape={shape!r} and safety={safety!r}"
    )


def _first_method_with_shape_and_safety_or_skip(shape: str, safety: str) -> str:
    """Like _first_method_with_shape_and_safety but skip when no entry exists.

    Used by behaviour tests that assert a runtime path which only fires for a
    given (shape, safety) combination. If the registry currently has no entry
    matching that pair, the behaviour is unreachable from real callers and the
    test would be testing nothing — skip rather than fail.
    """
    for method, contract in V4_METHOD_CONTRACTS.items():
        if contract.param_shape == shape and contract.safety == safety:
            return method
    pytest.skip(
        f"No v4 method registered with param_shape={shape!r} and "
        f"safety={safety!r}; behaviour path is currently unreachable."
    )


def _fake_client(extract_value=None):
    client = MagicMock()
    client.v4live.return_value.post.return_value.return_value.extract.return_value = (
        extract_value if extract_value is not None else {"result": "ok"}
    )
    return client


def test_call_v4_rejects_array_method_with_dict():
    method = _first_method_with_shape(PARAM_ARRAY)
    client = _fake_client()
    with pytest.raises(click.UsageError, match=f"{method} param must be an array"):
        call_v4(client, method, param={"foo": 1})
    client.v4live.return_value.post.assert_not_called()


def test_call_v4_rejects_object_method_with_list():
    method = _first_method_with_shape(PARAM_OBJECT)
    client = _fake_client()
    with pytest.raises(click.UsageError, match=f"{method} param must be an object"):
        call_v4(client, method, param=[1, 2, 3])
    client.v4live.return_value.post.assert_not_called()


def test_call_v4_rejects_scalar_method_with_list():
    method = _first_method_with_shape(PARAM_SCALAR)
    client = _fake_client()
    with pytest.raises(click.UsageError, match=f"{method} param must be a scalar"):
        call_v4(client, method, param=[1, 2, 3])
    client.v4live.return_value.post.assert_not_called()


def test_call_v4_rejects_optional_object_with_list():
    method = _first_method_with_shape(PARAM_OPTIONAL_OBJECT)
    client = _fake_client()
    with pytest.raises(
        click.UsageError, match=f"{method} param must be omitted or an object"
    ):
        call_v4(client, method, param=[1, 2, 3])
    client.v4live.return_value.post.assert_not_called()


def test_call_v4_warns_on_undocumented_read_method_but_proceeds(capfd):
    """READ-class undocumented methods are soft: warn + proceed."""
    method = _first_method_with_shape_and_safety_or_skip(
        PARAM_UNDOCUMENTED, SAFETY_READ
    )
    sentinel = {"undocumented": "passthrough"}
    client = _fake_client(extract_value=sentinel)

    result = call_v4(client, method, param={"any": "shape"})

    assert result is sentinel
    client.v4live.return_value.post.assert_called_once()
    err = capfd.readouterr().err
    assert "warning" in err.lower()
    assert method in err
    assert "undocumented param" in err


def test_call_v4_refuses_undocumented_write_method():
    """WRITE-class undocumented methods are hard: refuse to send. See Codex review."""
    method = _first_method_with_shape_and_safety(PARAM_UNDOCUMENTED, SAFETY_WRITE)
    client = _fake_client()

    with pytest.raises(click.UsageError, match="refusing to send"):
        call_v4(client, method, param={"any": "shape"})
    client.v4live.return_value.post.assert_not_called()


def test_call_v4_refuses_undocumented_dangerous_method():
    """DANGEROUS-class undocumented methods are hard: refuse to send.

    PayCampaignsByCard is financial — blind shape pass-through is unacceptable
    even with a stderr warning. See Codex adversarial review on issue #182.
    """
    method = _first_method_with_shape_and_safety(PARAM_UNDOCUMENTED, SAFETY_DANGEROUS)
    client = _fake_client()

    with pytest.raises(click.UsageError, match="refusing to send"):
        call_v4(client, method, param={"arbitrary": ["payload"]})
    client.v4live.return_value.post.assert_not_called()


def test_call_v4_undocumented_still_rejects_hard_errors():
    """A hard error coexisting with the undocumented marker must still raise.

    If the validator returns BOTH a hard shape error and the undocumented
    marker, call_v4's gate must classify by message content and raise
    UsageError — not silently warn. See issue #182 review.
    """
    method = _first_method_with_shape_and_safety_or_skip(
        PARAM_UNDOCUMENTED, SAFETY_READ
    )
    client = _fake_client()
    mixed_errors = [
        "method mismatch: 'WrongMethod' != 'ActualMethod'",
        f"{method} {PARAM_UNDOCUMENTED_SHAPE_MSG}",
    ]
    with patch("direct_cli.v4.validate_v4_body_shape", return_value=mixed_errors):
        with pytest.raises(click.UsageError, match="method mismatch"):
            call_v4(client, method, param={"any": "shape"})
    client.v4live.return_value.post.assert_not_called()


def test_call_v4_accepts_correct_array_shape():
    method = _first_method_with_shape(PARAM_ARRAY)
    client = _fake_client(extract_value=["ok"])
    assert call_v4(client, method, param=[1]) == ["ok"]
    client.v4live.return_value.post.assert_called_once()


def test_call_v4_accepts_correct_object_shape():
    method = _first_method_with_shape(PARAM_OBJECT)
    client = _fake_client(extract_value={"ok": True})
    assert call_v4(client, method, param={"key": "value"}) == {"ok": True}
    client.v4live.return_value.post.assert_called_once()


def test_call_v4_accepts_correct_optional_object_shape_with_param():
    method = _first_method_with_shape(PARAM_OPTIONAL_OBJECT)
    client = _fake_client(extract_value={"ok": True})
    assert call_v4(client, method, param={"key": "value"}) == {"ok": True}
    client.v4live.return_value.post.assert_called_once()


def test_call_v4_accepts_correct_optional_object_shape_without_param():
    method = _first_method_with_shape(PARAM_OPTIONAL_OBJECT)
    client = _fake_client(extract_value={"ok": True})
    assert call_v4(client, method) == {"ok": True}
    client.v4live.return_value.post.assert_called_once()


def test_call_v4_accepts_correct_scalar_shape():
    method = _first_method_with_shape(PARAM_SCALAR)
    client = _fake_client(extract_value={"ok": True})
    assert call_v4(client, method, param=42) == {"ok": True}
    client.v4live.return_value.post.assert_called_once()


def test_call_v4_rejects_array_method_with_missing_param():
    """A PARAM_ARRAY method must reject param=None (omitted)."""
    method = _first_method_with_shape(PARAM_ARRAY)
    client = _fake_client()
    with pytest.raises(click.UsageError, match=f"{method} param must be an array"):
        call_v4(client, method, param=None)
    client.v4live.return_value.post.assert_not_called()


def test_validate_v4_body_shape_is_exported():
    """Public API guarantee from issue #182."""
    from direct_cli.v4_contracts import validate_v4_body_shape  # noqa: F401
