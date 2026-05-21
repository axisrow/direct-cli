"""Tests for direct_cli.auth._write_json cleanup semantics."""

import errno
import fcntl
import json
import os
import stat
import tempfile
from pathlib import Path

import pytest

from direct_cli.auth import _write_json


def _wrap_mkstemp(monkeypatch, captured):
    real_mkstemp = tempfile.mkstemp

    def wrapper(*args, **kwargs):
        fd, tmp = real_mkstemp(*args, **kwargs)
        captured["fd"] = fd
        captured["tmp"] = tmp
        return fd, tmp

    monkeypatch.setattr("direct_cli.auth.tempfile.mkstemp", wrapper)


def _selective_chmod(monkeypatch, captured):
    """Fail chmod only when targeting the captured tmp path."""
    real_chmod = os.chmod

    def fake_chmod(target, mode):
        if "tmp" in captured and str(target) == str(captured["tmp"]):
            raise PermissionError("simulated chmod failure")
        return real_chmod(target, mode)

    monkeypatch.setattr("direct_cli.auth.os.chmod", fake_chmod)


def _assert_fd_closed(fd):
    # fcntl.F_GETFD is a non-destructive probe: a live fd returns flags, a
    # closed fd raises OSError(EBADF). Unlike os.close, it never closes an
    # unrelated fd that the OS may have reassigned to the same number.
    with pytest.raises(OSError) as exc_info:
        fcntl.fcntl(fd, fcntl.F_GETFD)
    assert exc_info.value.errno == errno.EBADF


class TestWriteJsonCleanup:
    def test_chmod_failure_closes_fd_and_removes_tmp(self, tmp_path, monkeypatch):
        captured: dict = {}
        _wrap_mkstemp(monkeypatch, captured)
        _selective_chmod(monkeypatch, captured)

        target = tmp_path / "auth.json"
        with pytest.raises(PermissionError, match="simulated chmod failure"):
            _write_json(target, {"any": "payload"})

        assert "fd" in captured and "tmp" in captured
        assert not Path(captured["tmp"]).exists()
        assert not target.exists()
        _assert_fd_closed(captured["fd"])

    def test_unlink_failure_preserves_original_exception(self, tmp_path, monkeypatch):
        captured: dict = {}
        _wrap_mkstemp(monkeypatch, captured)
        _selective_chmod(monkeypatch, captured)

        def failing_unlink(*_args, **_kwargs):
            raise OSError(errno.EIO, "simulated unlink failure")

        monkeypatch.setattr("direct_cli.auth.os.unlink", failing_unlink)

        target = tmp_path / "auth.json"
        with pytest.raises(PermissionError, match="simulated chmod failure"):
            _write_json(target, {"any": "payload"})

        _assert_fd_closed(captured["fd"])

    def test_happy_path_writes_payload_with_0600(self, tmp_path, monkeypatch):
        captured: dict = {}
        _wrap_mkstemp(monkeypatch, captured)

        target = tmp_path / "sub" / "auth.json"
        payload = {"a": 1, "b": "ы"}
        _write_json(target, payload)

        assert target.exists()
        assert json.loads(target.read_text("utf-8")) == payload
        mode = stat.S_IMODE(target.stat().st_mode)
        assert mode == 0o600
        # ensure_ascii=False => the raw cyrillic byte sequence is present
        assert "ы".encode("utf-8") in target.read_bytes()
        _assert_fd_closed(captured["fd"])
