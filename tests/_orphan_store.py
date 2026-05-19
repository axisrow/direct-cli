"""Persistent registry of test-created resource IDs awaiting cleanup.

When an opt-in live-write test creates a Yandex Direct resource (e.g. a v4
Wordstat report) and is interrupted before the matching ``delete`` call
completes, the resource is left behind in the account. This module keeps a
JSON file in ``~/.direct-cli/test-orphans.json`` so the next test run can
finish the cleanup.

File format::

    {"v4wordstat": [123, 456], "v4forecast": [789]}

The store is best-effort: callers add an ID right after a successful
create, remove it on successful delete, and call :func:`drain` at the
start of a test to retry pending deletions from previous interrupted
runs. All read/write errors are swallowed silently so tests are never
broken by store corruption.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List

ORPHAN_STORE_PATH = Path.home() / ".direct-cli" / "test-orphans.json"


def _read(path: Path = ORPHAN_STORE_PATH) -> Dict[str, List[int]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        k: [int(x) for x in v if isinstance(x, (int, str))]
        for k, v in data.items()
        if isinstance(k, str) and isinstance(v, list)
    }


def _write(data: Dict[str, List[int]], path: Path = ORPHAN_STORE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        os.chmod(tmp, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2))
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def add(kind: str, id_: int, path: Path = ORPHAN_STORE_PATH) -> None:
    """Record a freshly-created resource ID for cleanup if the test crashes."""
    data = _read(path)
    bucket = data.setdefault(kind, [])
    if id_ not in bucket:
        bucket.append(int(id_))
    try:
        _write(data, path)
    except OSError:
        pass  # best-effort; never fail a test on store IO


def remove(kind: str, id_: int, path: Path = ORPHAN_STORE_PATH) -> None:
    """Drop an ID after a successful delete."""
    data = _read(path)
    bucket = data.get(kind)
    if not bucket:
        return
    data[kind] = [x for x in bucket if x != id_]
    if not data[kind]:
        del data[kind]
    try:
        _write(data, path)
    except OSError:
        pass


def drain(
    kind: str,
    deleter: Callable[[int], Any],
    path: Path = ORPHAN_STORE_PATH,
) -> None:
    """Best-effort cleanup of IDs left behind by previous interrupted runs.

    For each pending ID of ``kind``, call ``deleter(id_)``. If it returns
    without raising, the ID is dropped from the store; if it raises, the
    ID stays so a later run can retry. Any store IO failure is ignored.
    """
    data = _read(path)
    bucket = data.get(kind)
    if not bucket:
        return
    survived: List[int] = []
    for id_ in bucket:
        try:
            deleter(id_)
        except Exception:
            survived.append(id_)
    if survived:
        data[kind] = survived
    else:
        data.pop(kind, None)
    try:
        _write(data, path)
    except OSError:
        pass
