"""
Env-switchable optional output channels (issue #925).

Everything "optional" the CLI learns beyond the requested payload — e.g. the
API Units points a successful call consumed — is hidden by default and lives
only on stderr, so stdout stays byte-identical for pipes and JSON parsing.

- Default (no env) is quiet: optional output suppressed.
- ``DIRECT_SHOW_<X>=1`` turns a single channel on, even under
  ``DIRECT_QUIET=1``; ``=0`` turns it off under ``DIRECT_QUIET=0``.
- ``DIRECT_QUIET=0`` is the master switch back to the legacy behaviour, for
  channels that had one (``legacy_default=True``).

Safety output — credential warnings (#909), sandbox notices, API warnings —
does not route through this registry and is never suppressed.
"""

import os
import sys
from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class OptionalChannel:
    """One optional-output channel: env -> what it shows -> where -> default.

    A future channel (``retryIn``/``reportsInQueue`` report headers, …) is
    added as one entry in :data:`CHANNELS`.
    """

    name: str
    env: str  # DIRECT_SHOW_<X>
    stream: str  # "stderr" (or "stdout") — stdout must stay untouched
    # Whether DIRECT_QUIET=0 alone shows the channel, i.e. it had visible
    # output before #925. Units never printed on successful calls, so its
    # entry is False: DIRECT_QUIET=0 without an explicit DIRECT_SHOW_UNITS
    # must keep successful-call output exactly as before.
    legacy_default: bool
    describe: str  # what the channel shows (README/docs)


CHANNELS: Dict[str, OptionalChannel] = {
    "units": OptionalChannel(
        name="units",
        env="DIRECT_SHOW_UNITS",
        stream="stderr",
        legacy_default=False,
        describe=(
            "API Units points spent/rest/limit of each successful call, "
            "plus used-login for agency accounts (Units-Used-Login)"
        ),
    ),
}

_FALSY = ("0", "false", "no", "off")


def quiet_mode() -> bool:
    """True unless ``DIRECT_QUIET=0`` — quiet is the default (issue #925)."""
    raw = os.environ.get("DIRECT_QUIET")
    if raw is None or raw.strip() == "":
        return True
    return raw.strip().lower() not in _FALSY


def channel_enabled(name: str) -> bool:
    """Resolve a channel: explicit ``DIRECT_SHOW_<X>`` beats the master switch."""
    channel = CHANNELS[name]
    raw = os.environ.get(channel.env)
    if raw is not None and raw.strip() != "":
        return raw.strip().lower() not in _FALSY
    return not quiet_mode() and channel.legacy_default


def emit(name: str, message: str) -> None:
    """Print one optional-output line if its channel is enabled."""
    channel = CHANNELS[name]
    if channel_enabled(name):
        # Resolve the stream at call time: sys.stderr may be swapped after
        # import (capsys, CliRunner, redirectors).
        print(message, file=getattr(sys, channel.stream))


def on_api_response(response) -> None:
    """Vendor success hook: surface API Units of a successful call.

    Installed as ``tapi_yandex_direct.SUCCESS_RESPONSE_HOOK`` (see
    :func:`install_vendor_hook`); fires only on successful responses, so the
    limit-error Units reporting (#921) stays the sole owner of error output.
    """
    units = response.headers.get("Units")
    if not units:
        return
    line = f"API units: {units}"
    used_login = response.headers.get("Units-Used-Login")
    if used_login:
        line += f" (used-login: {used_login})"
    emit("units", line)


def install_vendor_hook() -> None:
    """Wire the emitter into the vendored client, once per process."""
    from ._vendor.tapi_yandex_direct import tapi_yandex_direct as _vendored

    if _vendored.SUCCESS_RESPONSE_HOOK is None:
        _vendored.SUCCESS_RESPONSE_HOOK = on_api_response
