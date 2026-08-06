"""Single indirection point for the wall-clock used by this package's
poll loops (issue #767).

Every ``while <deadline not reached>: ... page.wait_for_timeout(tick)`` loop
in ``masters.py``/``session.py`` has two independent time sources: the
deadline (``time.monotonic()``) and the tick (``page.wait_for_timeout``,
which in production really sleeps inside the browser). Under the offline
test harness the tick is a no-op on a ``FakePage``, but the deadline was
still real ``time.monotonic()`` — so any test whose awaited condition never
becomes true busy-spun for the *full real-world* timeout budget. Five such
tests in ``tests/test_masters.py`` alone burned 135s of wall clock
(``_STAT_TILES_TIMEOUT_MS`` = 30s, ``_OVERVIEW_LOAD_TIMEOUT_MS`` = 30s, …).

Routing every deadline through ``now()`` lets the test harness swap in a
fake clock that only advances when ``wait_for_timeout`` is called, which
makes those loops terminate in the exact number of ticks the timeout
prescribes — deterministically, and in microseconds instead of seconds. It
also removes the CPU-speed dependence that issue #715 patched around
per-call for ``_poll_until``.

Production behaviour is unchanged: ``now()`` is ``time.monotonic``.
"""

import time
from typing import Callable

# Swapped wholesale by tests (see tests/test_masters.py's fake clock).
# Production always leaves it as ``time.monotonic``.
_clock: Callable[[], float] = time.monotonic


def now() -> float:
    """Current monotonic time, in seconds, via the installed clock."""
    return _clock()


def set_clock(clock: Callable[[], float]) -> Callable[[], float]:
    """Install ``clock`` as the package-wide time source; return the previous
    one so a caller can restore it."""
    global _clock
    previous = _clock
    _clock = clock
    return previous
