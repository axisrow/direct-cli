"""Single source of truth for Yandex SmartCaptcha gateway detection.

Yandex rate-limits the docs and WSDL hosts with a SmartCaptcha interstitial. A
captcha page must never be cached as if it were real content — that is how the
docs cache was poisoned in #426. Per CLAUDE.md ("No URL literals outside the
registry"), the marker set is declared here ONCE and shared by
:mod:`direct_cli.reports_coverage`, :mod:`direct_cli.wsdl_coverage`, and their
cache-freshness tests, rather than duplicated as literals in each.

:func:`find_marker` is the generic marker-scan primitive behind
:func:`find_captcha_marker`; other content-sniffing checks that follow the
same "declare markers once, scan once" pattern (e.g.
``direct_cli.browser.session.assert_authenticated``) reuse it too, instead of
each hand-rolling its own scan loop.
"""

from __future__ import annotations

from typing import Optional, Sequence

# Substrings that appear only in a SmartCaptcha interstitial, never in a real
# Yandex docs HTML page or WSDL/XSD XML. Matched case-insensitively. The
# ``<title>Captcha`` marker is HTML-only, so applying the full set to WSDL/XSD
# fetches only tightens detection — real XML can never contain it.
CAPTCHA_MARKERS = ("showcaptcha", "smartcaptcha", "<title>Captcha")


def find_marker(content: str, markers: Sequence[str]) -> Optional[str]:
    """Return the first of ``markers`` present in ``content``, or ``None``.

    Comparison is case-insensitive; the returned value is the canonical
    marker spelling from ``markers``, suitable for the caller's error message.
    """
    lower = content.lower()
    for marker in markers:
        if marker.lower() in lower:
            return marker
    return None


def find_captcha_marker(content: str) -> Optional[str]:
    """Return the first captcha marker present in *content*, or ``None``."""
    return find_marker(content, CAPTCHA_MARKERS)
