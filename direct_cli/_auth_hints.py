"""Canonical login-command pointers for every auth error and deprecation text.

Leaf module on purpose: it imports nothing from ``direct_cli.commands`` or
``direct_cli.browser``, so any CLI module can use these constants without
import cycles. Every authorization error and deprecation notice must advise
exactly one of these — never a hand-written variant (issue #924: one call
used to print four contradictory suggestions). The AST guard in
``tests/test_unified_auth.py`` bans literal ``direct auth login`` /
``direct playwright login`` strings anywhere else in the package, so a new
hint source fails CI instead of quietly disagreeing with these.

These name the canonical ``auth login api|browser`` surface (issue #924) and
carry the headless contract (``AGENTS.md``, "Authorization Execution Mode"),
which ``tests/test_headless_auth_contract.py`` pins:

- ``HINT_LOGIN_API`` and ``HINT_LOGIN_BROWSER`` / ``HINT_LOGIN_BROWSER_CHROME``
  are headless: the API login prints the authorize URL, the browser login
  imports the Chrome session — neither prompts nor opens a window.
- ``HINT_LOGIN_API_INTERACTIVE`` and ``HINT_LOGIN_BROWSER_MANUAL`` are the two
  explicit opt-ins (terminal dialogs, a visible login window). A terminal never
  selects them on its own.
"""

HINT_LOGIN_API = "direct auth login api"
HINT_LOGIN_API_INTERACTIVE = "direct auth login api --interactive"
HINT_LOGIN_BROWSER = "direct auth login browser"
HINT_LOGIN_BROWSER_CHROME = "direct auth login browser --source chrome"
HINT_LOGIN_BROWSER_MANUAL = "direct auth login browser --source manual"
