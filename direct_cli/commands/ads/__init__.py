"""``direct ads`` command package (#603).

``ads.py`` grew past 3 000 lines mixing the Click surface with per-subtype
payload assembly and batch-row handling. The package splits those apart:

- :mod:`._cli` — the Click group and the ``get``/``add``/``update``/lifecycle
  commands (the thin router);
- :mod:`.objects` — ``build_ad_object`` / ``build_ad_update_object``, the pure
  item builders shared by the single-item and batch paths;
- :mod:`.batch` — ``--from-file`` / ``--ads-json`` row normalization and chunked
  sending;
- :mod:`.base`, :mod:`.text`, :mod:`.responsive`, :mod:`.shopping`,
  :mod:`.mobile_app`, :mod:`.builder` — shared helpers and per-subtype payloads.

The public surface is unchanged: importing ``ads``, ``build_ad_object`` or
``build_ad_update_object`` from ``direct_cli.commands.ads`` works as before.
"""

from ._cli import ads, create_client
from .objects import build_ad_object, build_ad_update_object

__all__ = ["ads", "build_ad_object", "build_ad_update_object", "create_client"]
