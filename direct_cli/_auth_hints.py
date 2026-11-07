"""Canonical login-command pointers for every auth error and deprecation text.

Leaf module on purpose: it imports nothing from ``direct_cli.commands`` or
``direct_cli.browser``, so any CLI module can use these constants without
import cycles. Every authorization error and deprecation notice must advise
exactly one of these — never a hand-written variant (issue #924: one call
used to print four contradictory suggestions). The AST guard in
``tests/test_unified_auth.py`` bans literal ``direct auth login`` /
``direct playwright login`` strings anywhere else in the package, so a new
hint source fails CI instead of quietly disagreeing with these.

Canonical forms (issue #962): the plain login commands are headless;
``--interactive`` and the visible login window exist only behind the
explicit flags these constants spell out.
"""

HINT_LOGIN_API = "direct auth login api"
HINT_LOGIN_API_INTERACTIVE = "direct auth login api --interactive"
HINT_LOGIN_BROWSER = "direct auth login browser"
HINT_LOGIN_BROWSER_CHROME = "direct auth login browser --source chrome"
HINT_LOGIN_BROWSER_MANUAL = "direct auth login browser --source manual"
