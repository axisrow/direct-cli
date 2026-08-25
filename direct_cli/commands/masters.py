"""
Мастер кампаний (Campaign Wizard) commands.

Мастер кампаний has no Yandex Direct API surface at all — it exists only in
the web interface, and must not be confused with ``UNIFIED_CAMPAIGN``, an
unrelated v5 API campaign type already supported by ``campaigns add/get
--type unified_campaign`` (see ``direct_cli/commands/_campaigns_unified.py``).
This group reads Мастер кампаний by driving a real Chrome session (via
Playwright) with the user's own Yandex cookies decrypted and injected — see
``direct_cli/browser/`` for the browser layer this group is a thin Click
wrapper around.

Read-only: ``list`` and ``get``. Mutations: ``suspend``/``resume`` (issue
#630) and ``add`` (issue #632, create — NOT idempotent, no sandbox/rollback,
see ``add``'s own docstring). ``update`` (issue #631) edits a campaign's
settings, including point-replacement of individual images via
``--image``. ``adimages get/add/delete/set`` (issue #648) is the full CRUD
counterpart for a campaign's whole image set — mirrors the API-side
``direct adimages get/add/delete`` vocabulary, treats an empty image set as
legitimate on both ends (unlike ``update --image``), and is likewise NOT
idempotent for ``add``/``delete``/``set``.

No ``--login``/agency support (issue #639): this group only ever reads the
logged-in user's own account, so it needs no Yandex Direct credentials at
all — see ``direct_cli/browser/masters.py`` module docstring for why an
explicit login actually broke ``list`` (HTTP 401 "Доступ ограничен" when the
user's own login was passed as Yandex's managed-client ``ulogin`` param).

Session resolution (``_open_session``) is multi-tiered — see
``direct_cli/commands/browser_session.py`` for ``direct playwright login``
(tier 2) and this module's own ``masters login`` command (tier 1.5, issue
#635):

1. Explicit ``--profile-dir``/``--chrome-profile`` on the command line ->
   always decrypt fresh from that specific Chrome profile (the user pointed
   at it deliberately; silently using a stale saved session instead would be
   a surprise).
1.5. Otherwise, if the CLI's own persistent Chromium profile exists (set up
   via ``direct masters login``) -> use it. Keychain-free and platform-
   independent (unlike tiers 2/3, which both decrypt the user's real Chrome
   profile), so it's preferred whenever present.
2. Otherwise, a saved session from ``direct playwright login`` that isn't
   known-expired -> use it (skips the Keychain round-trip entirely).
3. Otherwise -> decrypt fresh from Chrome, same as before this tier system
   existed. Zero-config `direct masters list` keeps working unchanged.

A ``BrowserAuthError`` from tier 1.5 or tier 2 is retried once via tier 3
before surfacing — a stale saved session should self-heal rather than break
`masters` until the user notices and reruns `playwright login`/`masters
login` by hand. The
retry happens at the *operation* level (``_with_session``), not inside
``_open_session`` itself: ``BrowserAuthError`` from ``assert_authenticated``
is raised by the caller's fetch call, deep inside the ``with page:`` body,
not just on session-open. A ``@contextlib.contextmanager`` generator can
``yield`` only once per invocation — attempting a second ``yield`` after
catching an exception thrown back in via ``.throw()`` raises ``RuntimeError:
generator didn't stop after throw()`` instead of falling back. So the retry
boundary must wrap the whole ``with _open_session(...): operation(page)``
call, re-entering ``_open_session`` a second time for the fresh-decrypt
fallback rather than trying to yield twice from one generator call.
"""

import contextlib
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import click
from click.core import ParameterSource

from ..api import create_client
from ..browser.masters import _BATCH_UPDATE_PACING_MS as _BATCH_UPDATE_PACING_MS_DEFAULT
from ..browser.masters import AGE_FROM_CHOICES as _AGE_FROM_CHOICES
from ..browser.masters import AGE_TO_CHOICES as _AGE_TO_CHOICES
from ..browser.masters import DEVICE_OPTION_VALUES as _DEVICE_OPTION_VALUES
from ..browser.masters import GENDER_CHOICES as _GENDER_CHOICES
from ..browser.masters import PROMOTION_GOAL_CHOICES as _PROMOTION_GOAL_CHOICES
from ..output import (
    format_output,
    handle_api_errors,
    print_error,
    print_info,
    print_warning,
)
from ..utils import parse_ids

_BROWSER_INSTALL_HINT = (
    'pip install "direct-cli[browser]" && playwright install chromium'
)


def _profile_options_explicit(ctx: click.Context) -> bool:
    """True if --profile-dir or --chrome-profile was passed on the command line.

    Tier 1 of ``_open_session``: an explicit profile means the user is
    deliberately pointing at a specific Chrome profile, so a saved session
    (which may be stale, or from a different profile entirely) must not be
    silently substituted.
    """
    return any(
        ctx.get_parameter_source(name) is ParameterSource.COMMANDLINE
        for name in ("profile_dir", "chrome_profile")
    )


@contextlib.contextmanager
def _open_session(
    ctx: click.Context, headful: bool, profile_dir: Optional[str], chrome_profile: str
):
    """Open a browser session, converting session errors to ClickException.

    Wrapping the *whole* ``with open_..._session(...)`` block (rather than
    only the call that constructs it) matters because both
    ``open_chrome_session`` and ``open_saved_session`` are themselves
    contextmanagers: an error raised inside their generator body
    (Keychain/decryption failures, and BrowserAuthError/BrowserCaptchaError
    raised by callers using this session) only surfaces on ``__enter__``,
    which is outside a try/except placed around the bare function call (see
    the regression test for #634 in tests/test_masters.py).

    Tier 2's ``BrowserAuthError`` is deliberately NOT caught here and
    retried via tier 3 inside this same generator -- a
    ``@contextlib.contextmanager`` generator can only ``yield`` once per
    invocation, and ``BrowserAuthError`` from ``assert_authenticated`` is
    raised by the caller deep inside the ``with page:`` body, not just on
    session-open. Catching it here and falling through to a second ``yield``
    would raise ``RuntimeError: generator didn't stop after throw()``,
    masking the original error. The tier-2-to-3 retry instead happens one
    level up, in :func:`_with_session`, which re-enters this function a
    second time for the fresh-decrypt fallback.
    """
    try:
        from ..browser.session import (
            BrowserSessionError,
            open_chrome_session,
            open_persistent_session,
            open_saved_session,
        )
    except ImportError as exc:
        raise click.UsageError(
            "playwright is required for `direct masters` but is not "
            f"installed. Run: {_BROWSER_INSTALL_HINT}"
        ) from exc

    resolved_profile_dir = Path(profile_dir) if profile_dir else None

    def _fresh():
        return open_chrome_session(
            profile_dir=resolved_profile_dir,
            chrome_profile=chrome_profile,
            headless=not headful,
        )

    # Tier 1: an explicit --profile-dir/--chrome-profile always decrypts
    # fresh from that specific profile.
    if _profile_options_explicit(ctx):
        try:
            with _fresh() as page:
                yield page
        except BrowserSessionError as exc:
            raise click.ClickException(str(exc)) from exc
        return

    from ..browser.session import persistent_profile_is_usable

    persistent_dir = _configured_persistent_profile_dir()

    # Tier 1.5: the CLI's own persistent profile (issue #635, `direct masters
    # login`) — Keychain-free and platform-independent, so it's preferred
    # over the saved storage_state session whenever it has been set up.
    # BrowserAuthError (a stale on-disk session) propagates to _with_session
    # uncaught, exactly like tier 2's, so the same self-heal fallback
    # applies.
    #
    # Tested for an actual session, not mere directory existence: an aborted
    # `masters login` leaves an empty profile behind, and routing through it
    # would cost a wasted browser launch on every command.
    if persistent_profile_is_usable(persistent_dir):
        with _fresh_or_saved(
            open_persistent_session,
            headless=not headful,
            profile_dir=persistent_dir,
        ) as page:
            yield page
        return

    from ..browser import store

    status = store.session_status()
    use_saved = (
        status["exists"] and not status["error"] and status["expired"] is not True
    )

    # Tier 2: a saved, not-known-expired session -- skips the Keychain
    # round-trip entirely. BrowserAuthError propagates to _with_session
    # uncaught (see docstring above); every other BrowserSessionError is a
    # hard failure reported as-is.
    if use_saved:
        with _fresh_or_saved(open_saved_session, headless=not headful) as page:
            yield page
        return

    # Tier 3: zero-config fallback, identical to pre-tier-system behaviour.
    try:
        with _fresh() as page:
            yield page
        if not use_saved:
            print_info(
                "Tip: run `direct playwright login` to save this session "
                "and skip the Keychain prompt next time."
            )
    except BrowserSessionError as exc:
        raise click.ClickException(str(exc)) from exc


def _configured_persistent_profile_dir() -> Path:
    """Where `masters login` last saved a session (default if never set)."""
    from ..browser.session import configured_persistent_profile_dir

    return configured_persistent_profile_dir()


@contextlib.contextmanager
def _fresh_or_saved(open_saved_session, *, headless: bool, **kwargs):
    """Tier 2 body: run ``open_saved_session``, converting non-auth errors.

    ``BrowserAuthError`` is intentionally left to propagate to the caller
    (:func:`_with_session`) uncaught -- it is not a hard failure, it is the
    self-heal-via-fresh-decrypt signal. Every other ``BrowserSessionError``
    is a real failure, reported the same way tier 1/3 report it.
    """
    from ..browser.session import BrowserAuthError, BrowserSessionError

    try:
        with open_saved_session(headless=headless, **kwargs) as page:
            yield page
    except BrowserAuthError:
        raise
    except BrowserSessionError as exc:
        raise click.ClickException(str(exc)) from exc


def _with_session(
    ctx: click.Context,
    headful: bool,
    profile_dir: Optional[str],
    chrome_profile: str,
    operation,
):
    """Run ``operation(page)`` under a resolved browser session, retrying once.

    A saved session (tier 2) that turns out to be stale server-side raises
    ``BrowserAuthError`` from *inside* ``operation`` (via
    ``assert_authenticated``), not from opening the session -- so the retry
    has to re-run ``operation`` itself under a fresh session (tier 3), not
    just re-enter the context manager. See :func:`_open_session`'s docstring
    for why the retry can't live inside a single ``@contextmanager`` call.
    """
    from ..browser.session import BrowserAuthError

    try:  # noqa: SIM105 -- must fall through to the retry below, not suppress
        with _open_session(ctx, headful, profile_dir, chrome_profile) as page:
            return operation(page)
    except BrowserAuthError:
        # Stale saved session despite passing the expiry check (Yandex
        # invalidated it server-side) -- self-heal below by re-running the
        # whole operation against a forced fresh decrypt, rather than
        # surfacing an error the user has to interpret and retry by hand.
        # contextlib.suppress would swallow this and return None instead of
        # falling through to the fresh-session retry code below.
        pass

    from ..browser.session import BrowserSessionError, open_chrome_session

    resolved_profile_dir = Path(profile_dir) if profile_dir else None
    try:
        with open_chrome_session(
            profile_dir=resolved_profile_dir,
            chrome_profile=chrome_profile,
            headless=not headful,
        ) as page:
            return operation(page)
    except BrowserSessionError as exc:
        raise click.ClickException(str(exc)) from exc


def _masters_browser_options(func):
    """Apply the option stack shared by every ``masters`` subcommand.

    Equivalent to, top-to-bottom::

        @click.option("--headful", is_flag=True, help="...")
        @click.option("--profile-dir", help="...")
        @click.option("--chrome-profile", default="Default", help="...")
        @click.option("--format", "output_format", default="json", help="...")
        @click.option("--output", help="...")

    Mirrors the shared-decorator convention in ``direct_cli.utils``
    (``v4_output_options`` / ``reference_output_options``) instead of
    repeating this five-option stack on both ``list`` and ``get``. No
    ``--login`` (issue #639): this group only ever reads the logged-in
    user's own account — see module docstring.
    """
    func = click.option("--output", help="Output file")(func)
    func = click.option(
        "--format", "output_format", default="json", help="Output format"
    )(func)
    func = click.option(
        "--chrome-profile",
        default="Default",
        help="Chrome profile subdirectory to read cookies from (e.g. 'Profile 1')",
    )(func)
    func = click.option(
        "--profile-dir", help="Chrome user-data-dir to read cookies from"
    )(func)
    return click.option(
        "--headful", is_flag=True, help="Show the browser window (for debugging)"
    )(func)


@click.group()
def masters():
    """Мастер кампаний (Campaign Wizard) — browser-only, no API"""


def _run_per_id(
    ctx,
    ids,
    action,
    *,
    headful,
    profile_dir,
    chrome_profile,
    output_format,
    output,
    verb: str,
):
    """Run ``action(page, campaign_id)`` for every ID, never stopping at the
    first failure, then report every outcome.

    Extracted from ``launch``/``archive``, which each had their own copy of
    this loop (issue #645), and now shared with ``suspend``/``resume`` too
    (issue #766: a batch of eight IDs aborted on the first one, leaving the
    caller with no idea whether the other seven had been attempted, let
    alone what happened to them).

    Every ID is attempted even if an earlier one fails: these are real
    account mutations, so a fail-fast loop would silently lose the report
    that earlier IDs already changed in production before a later one
    errored. Each ID's outcome — the resulting row, or an ``Error`` entry —
    goes into the formatted output; if any ID failed, the command exits
    non-zero after printing every outcome, never just the last error.
    """

    def _all(page):
        from ..browser.session import BrowserAuthError, BrowserSessionError
        from ..browser.masters import PlaywrightError

        results = []
        errors = []
        for campaign_id in ids:
            try:
                results.append(action(page, campaign_id))
            except BrowserAuthError:
                # A stale saved session must keep propagating to
                # _with_session's whole-operation retry (issue #816
                # follow-up) -- BrowserAuthError is a BrowserSessionError
                # subclass, so a bare `except BrowserSessionError` below
                # would swallow it per-campaign and defeat the self-heal.
                raise
            except (BrowserSessionError, PlaywrightError) as exc:
                errors.append((campaign_id, exc))
                results.append({"CampaignId": campaign_id, "Error": str(exc)})
        return results, errors

    results, errors = _with_session(ctx, headful, profile_dir, chrome_profile, _all)

    format_output(results if len(results) != 1 else results[0], output_format, output)

    if errors:
        for campaign_id, exc in errors:
            print_error(f"Campaign {campaign_id}: {exc}")
        error = click.ClickException(
            f"Failed to {verb} {len(errors)} of {len(ids)} campaign(s); "
            "see per-ID results above."
        )
        # Keep exit 1 for a completely failed batch, while giving consumers a
        # distinct status for output that contains both successes and errors.
        error.exit_code = 2 if len(errors) < len(ids) else 1
        raise error
    return results


def _stdin_is_interactive() -> bool:
    """Return whether a human is present to complete a browser login.

    Mirrors ``direct_cli/commands/auth.py``'s helper of the same name.
    """
    return sys.stdin.isatty()


@masters.command()
@click.option(
    "--profile-dir",
    help="Directory for the CLI's own persistent Chrome profile "
    "(default: ~/.direct-cli/chrome-profile/)",
)
@click.option(
    "--timeout",
    "timeout_seconds",
    type=int,
    default=300,
    show_default=True,
    help="Seconds to wait for manual login to complete",
)
def login(profile_dir, timeout_seconds):
    """Log in once via a visible browser window, saved for future `masters` calls

    Opens Yandex Passport in a persistent Chromium profile owned by the CLI
    (issue #635) — separate from your real Chrome profile, so it needs no
    Keychain access and works the same on macOS/Linux/Windows. Log in by
    hand in the window that opens; the command exits once the session is
    confirmed. Subsequent `direct masters` calls reuse this profile
    automatically (see the module docstring's tier 1.5).

    Requires a terminal: if run from CI or a script it fails immediately
    rather than blocking on a browser window nobody can see.
    """
    # The command's whole purpose is to wait for a human. Without a TTY there
    # is nobody to log in, so blocking for the full --timeout on an invisible
    # window is never useful (issue #635, Риски -> Интерактивность).
    if not _stdin_is_interactive():
        raise click.ClickException(
            "`direct masters login` needs an interactive terminal — it opens a "
            "browser window and waits for you to log in by hand. Run it from a "
            "terminal, not from CI or a script."
        )

    try:
        from ..browser.session import BrowserSessionError, login_persistent_session
    except ImportError as exc:
        raise click.UsageError(
            "playwright is required for `direct masters login` but is not "
            f"installed. Run: {_BROWSER_INSTALL_HINT}"
        ) from exc

    resolved_profile_dir = Path(profile_dir) if profile_dir else None
    try:
        login_persistent_session(
            profile_dir=resolved_profile_dir,
            timeout_ms=timeout_seconds * 1000,
        )
    except BrowserSessionError as exc:
        raise click.ClickException(str(exc)) from exc

    print_info(
        "Login confirmed. `direct masters` commands will now reuse this session."
    )


@masters.command()
@click.option(
    "--profile-dir",
    help="Directory for the CLI's own persistent Chrome profile "
    "(default: ~/.direct-cli/chrome-profile/)",
)
def logout(profile_dir):
    """Delete the persistent Chrome profile created by `masters login`

    The only way to revoke the on-disk Yandex session `masters login`
    creates (issue #635) short of a manual `rm -rf`. A no-op (with a
    warning, not an error) if no profile exists.

    Refuses to touch anything `masters login` did not create: the target
    must carry the CLI's own marker file, and must not be a symlink. A
    mistyped or shell-expanded `--profile-dir` is rejected rather than
    recursively deleted.
    """
    from ..browser.session import PROFILE_MARKER_NAME, PROFILE_POINTER_PATH

    resolved_profile_dir = (
        Path(profile_dir) if profile_dir else _configured_persistent_profile_dir()
    )

    if not resolved_profile_dir.exists():
        print_warning(f"No persistent browser profile found at {resolved_profile_dir}")
        return

    # A symlink would have rmtree follow it out of the directory the user named.
    if resolved_profile_dir.is_symlink():
        raise click.ClickException(
            f"Refusing to delete {resolved_profile_dir}: it is a symlink, not a "
            "profile directory created by `direct masters login`."
        )

    if not resolved_profile_dir.is_dir():
        raise click.ClickException(
            f"Refusing to delete {resolved_profile_dir}: not a directory."
        )

    # Ownership marker: written by `masters login`, absent from every other
    # directory on the machine. Without it a recursive delete is never safe.
    if not (resolved_profile_dir / PROFILE_MARKER_NAME).is_file():
        raise click.ClickException(
            f"Refusing to delete {resolved_profile_dir}: it has no "
            f"{PROFILE_MARKER_NAME} marker, so it was not created by "
            "`direct masters login`. Delete it by hand if you are sure."
        )

    import shutil

    # Read before the delete: an explicit --profile-dir may name a directory
    # that isn't the one the pointer records (e.g. an old profile from before
    # a later `login --profile-dir` moved it elsewhere). Only clear the
    # pointer when it actually points at what's being deleted -- otherwise a
    # cleanup of a stale profile would strand reads without their live one.
    try:
        pointer_target = PROFILE_POINTER_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        pointer_target = None

    shutil.rmtree(resolved_profile_dir)
    if pointer_target and Path(pointer_target) == resolved_profile_dir.resolve():
        PROFILE_POINTER_PATH.unlink(missing_ok=True)
    print_info(f"Deleted persistent browser profile at {resolved_profile_dir}")


_STATUS_CHOICES = ("not-archived", "active", "stopped", "archived", "all")


@masters.command(name="list")
@click.option(
    "--status",
    type=click.Choice(_STATUS_CHOICES),
    default="not-archived",
    help="Filter by campaign status (default: everything except archived)",
)
@_masters_browser_options
@click.pass_context
@handle_api_errors
def list_masters(
    ctx, status, headful, profile_dir, chrome_profile, output_format, output
):
    """List every Мастер кампаний in the account"""
    from ..browser.masters import fetch_masters_list

    result = _with_session(
        ctx,
        headful,
        profile_dir,
        chrome_profile,
        lambda page: fetch_masters_list(page, status),
    )

    format_output(result, output_format, output)


@masters.command()
@click.argument("campaign_ids")
@click.option(
    "--moderation-statuses",
    is_flag=True,
    help=(
        "Also report ad elements individually rejected on moderation "
        "(images). Adds RejectedElements/RejectedCount to each result."
    ),
)
@click.option(
    "--tracking-params",
    is_flag=True,
    help=(
        'Also read the campaign\'s "UTM-метки и параметры URL" field from '
        "its edit page. Adds TrackingParams to each result; omitted if the "
        "field could not be confirmed readable (issue #824)."
    ),
)
@_masters_browser_options
@click.pass_context
@handle_api_errors
def get(
    ctx,
    campaign_ids,
    moderation_statuses,
    tracking_params,
    headful,
    profile_dir,
    chrome_profile,
    output_format,
    output,
):
    """Get one or more Мастер кампаний by ID (comma-separated)

    With --moderation-statuses, additionally reads each campaign's edit page
    for ad elements that moderation rejected individually (the campaign keeps
    running on its remaining approved elements, so this does not show up in
    the campaign-level status). Only images carry such a marker today; see
    UnsupportedTypes in the output.

    With --tracking-params, additionally reads the campaign's UTM field from
    its edit page (the overview page this command otherwise reads has no
    such field at all — see issue #824).

    Every ID is attempted even if an earlier one fails, and each ID's
    outcome (the row, or its error) is reported — see ``_run_per_id``
    (issue #816: a failure reading one campaign used to discard every
    already-read campaign in the same batch).
    """
    from ..browser.masters import (
        fetch_master,
        fetch_master_moderation_statuses,
        fetch_master_tracking_params,
    )

    ids = parse_ids(campaign_ids) or []

    def _fetch_one(page, campaign_id):
        result = fetch_master(page, campaign_id)
        if moderation_statuses:
            # A second navigation on purpose: the rejection markers live on
            # the edit page, while fetch_master reads the overview page.
            # Merged into the SAME result object so the flag stays a slice of
            # `get`'s output rather than a separate command (issue #814).
            result.update(
                {
                    key: value
                    for key, value in fetch_master_moderation_statuses(
                        page, campaign_id
                    ).items()
                    if key != "CampaignId"
                }
            )
        if tracking_params:
            # Same "merge into this result" shape as --moderation-statuses
            # above, one more edit-page navigation (issue #824).
            result.update(
                {
                    key: value
                    for key, value in fetch_master_tracking_params(
                        page, campaign_id
                    ).items()
                    if key != "CampaignId"
                }
            )
        return result

    _run_per_id(
        ctx,
        ids,
        _fetch_one,
        headful=headful,
        profile_dir=profile_dir,
        chrome_profile=chrome_profile,
        output_format=output_format,
        output=output,
        verb="read",
    )


@masters.command()
@click.argument("campaign_ids")
@_masters_browser_options
@click.pass_context
@handle_api_errors
def suspend(
    ctx,
    campaign_ids,
    headful,
    profile_dir,
    chrome_profile,
    output_format,
    output,
):
    """Stop one or more Мастер кампаний by ID (comma-separated)

    Live-verified 2026-08-06 (issue #766): clicks the overview page's
    "Остановить кампанию" button (``CampaignHeader.ActionButton.stop``, a
    confirmed stable testid — the earlier best-effort label guessing from
    #630 is now only a fallback). Verifies the status actually changed
    before reporting success, re-clicking if the first click was a silent
    no-op; idempotent if already stopped.

    Every ID is attempted even if an earlier one fails, and each ID's
    outcome (the row, or its error) is reported — see ``_run_per_id``.
    """
    from ..browser.masters import suspend_master

    ids = parse_ids(campaign_ids) or []

    _run_per_id(
        ctx,
        ids,
        suspend_master,
        headful=headful,
        profile_dir=profile_dir,
        chrome_profile=chrome_profile,
        output_format=output_format,
        output=output,
        verb="suspend",
    )


def _parse_repeating_slot_options(
    option_name: str,
    values: "tuple[str, ...]",
    slot_count: int,
    *,
    value_label: str = "text",
    value_example: str = "New headline",
    empty_hint: str = (
        "which would DELETE that ad variant rather than replace it. "
        "Removing a variant is not supported — pass the replacement text, "
        "or edit the campaign with --headful."
    ),
) -> "dict[int, str]":
    """Parse repeated ``"N=<value_label>"`` CLI values into a 0-based slot
    index map.

    N is the 1-based slot number shown to the user (matches how a person
    would count "headline 1, headline 2, ..." reading the edit page); the
    browser layer (``update_master``/``_set_repeating_value``/``_set_image``)
    works in 0-based indices like the rest of ``masters.py``'s slot
    machinery, so the conversion happens here, at the CLI boundary. All
    format errors are raised as ``click.UsageError`` before any browser
    session is opened, rather than surfacing mid-session as a
    ``BrowserSessionError``.

    ``slot_count`` is the upper bound this field can ever have — for
    headlines/texts that's the page's fixed slot count (5/3, from the
    browser layer's own constants so the two can't drift apart); for images
    (issue #670, Этап D) there are no fixed slots at all, so this is
    ``_IMAGES_MAX_COUNT`` (Yandex's hard cap on the set size) — the actual,
    possibly-empty, per-campaign ceiling is only known once the browser
    layer reads the live page, and is enforced there
    (``_set_image``/``_read_image_content_ids``). Rejecting an
    obviously-oversized slot number here is still worth doing eagerly: it is
    a purely invalid CLI argument, and letting it through would launch a
    browser (and possibly an auth prompt) only to fail downstream —
    contradicting this helper's fail-fast contract.

    ``value_label``/``value_example``/``empty_hint``
    parameterize the two messages that are specific to what "N=..." holds
    (headline/ad-text copy vs. an image file path) — added for ``--image``
    (issue #670). Defaults keep the original Этап B (``--headline``/
    ``--text``) wording byte-for-byte; only ``--image`` passes overrides.
    """
    parsed: "dict[int, str]" = {}
    for raw in values:
        if "=" not in raw:
            raise click.UsageError(
                f"{option_name} value {raw!r} must be in the form "
                f'"N={value_label}" (e.g. "2={value_example}").'
            )
        index_part, text = raw.split("=", 1)
        try:
            slot_number = int(index_part.strip())
        except ValueError:
            raise click.UsageError(
                f"{option_name} slot number {index_part!r} must be an " "integer."
            )
        if slot_number < 1:
            raise click.UsageError(
                f"{option_name} slot number {slot_number} must be 1 or "
                f"greater (this field has slots 1-{slot_count})."
            )
        if slot_number > slot_count:
            raise click.UsageError(
                f"{option_name} slot number {slot_number} is out of range — "
                f"this field has slots (1-{slot_count})."
            )
        index = slot_number - 1
        if index in parsed:
            raise click.UsageError(
                f"{option_name} slot {slot_number} was specified more than " "once."
            )
        if not text.strip():
            raise click.UsageError(
                f"{option_name} slot {slot_number} was given an empty "
                f"replacement, {empty_hint}"
            )
        parsed[index] = text
    return parsed


def _parse_clear_slot_options(
    option_name: str, values: "tuple[int, ...]", slot_count: int
) -> "list[int]":
    """Parse repeated ``--clear-headline``/``--clear-text`` 1-based slot
    numbers into a 0-based index list (issue #786, Этап B follow-up).

    Mirrors ``_parse_repeating_slot_options``'s bounds-checking and
    duplicate-slot rejection, but for a plain integer list rather than
    ``"N=value"`` pairs — there is no replacement value to parse here, the
    whole point of ``--clear-*`` is that it deletes rather than replaces.
    """
    parsed: "list[int]" = []
    seen: "set[int]" = set()
    for slot_number in values:
        if slot_number < 1:
            raise click.UsageError(
                f"{option_name} slot number {slot_number} must be 1 or "
                f"greater (this field has slots 1-{slot_count})."
            )
        if slot_number > slot_count:
            raise click.UsageError(
                f"{option_name} slot number {slot_number} is out of range — "
                f"this field has slots (1-{slot_count})."
            )
        index = slot_number - 1
        if index in seen:
            raise click.UsageError(
                f"{option_name} slot {slot_number} was specified more than " "once."
            )
        seen.add(index)
        parsed.append(index)
    return parsed


def _reject_overlapping_slots(
    set_slots: "dict[int, str]",
    clear_slots: "list[int]",
    set_option_name: str,
    clear_option_name: str,
) -> None:
    """Refuse a slot number passed to both a ``--headline``/``--text``-style
    setter and its ``--clear-*`` counterpart in the same call (issue #786).

    Ambiguous otherwise — Yandex's edit page has no "set then immediately
    clear" concept, and silently picking one order to apply them in would
    make the CLI's behaviour depend on an implementation detail the caller
    can't see. Mirrors the target-action goal-id overlap guard above this
    function's own call site.
    """
    overlap = sorted(set(set_slots) & set(clear_slots))
    if overlap:
        slots = ", ".join(str(index + 1) for index in overlap)
        raise click.UsageError(
            f"Slot(s) {slots} passed to both {set_option_name} and "
            f"{clear_option_name} — a slot can only be set or cleared in "
            "the same call, not both."
        )


def _parse_target_action_price_options(
    values: "tuple[str, ...]",
) -> "dict[int, float]":
    """Parse repeated ``--target-action-price "goal_id=price"`` CLI values
    into a goal-id-keyed price map.

    Unlike ``_parse_repeating_slot_options`` (1-based slot NUMBER, a fixed
    small range), the key here is Yandex Metrika's own numeric goal id
    (unbounded, no fixed count known ahead of time — see
    ``direct_cli/browser/masters.py::_read_target_actions``'s docstring for
    why a goal can only be identified by this id, never by its label). All
    format errors are raised as ``click.UsageError`` before any browser
    session is opened, mirroring every other CLI-boundary parse in this
    module.
    """
    parsed: "dict[int, float]" = {}
    for raw in values:
        if "=" not in raw:
            raise click.UsageError(
                f"--target-action-price value {raw!r} must be in the form "
                '"goal_id=price" (e.g. "159614149=150").'
            )
        goal_part, price_part = raw.split("=", 1)
        try:
            goal_id = int(goal_part.strip())
        except ValueError:
            raise click.UsageError(
                f"--target-action-price goal_id {goal_part!r} must be an "
                "integer (the Yandex Metrika goal ID, as shown by "
                "`masters targetactions get`)."
            )
        try:
            price = float(price_part.strip())
        except ValueError:
            raise click.UsageError(
                f"--target-action-price price {price_part!r} for goal "
                f"{goal_id} must be a number."
            )
        if goal_id in parsed:
            raise click.UsageError(
                f"--target-action-price goal {goal_id} was specified more " "than once."
            )
        parsed[goal_id] = price
    return parsed


def _parse_add_target_action_options(
    values: "tuple[str, ...]",
) -> "dict[int, float]":
    """Parse repeated ``--add-target-action "goal_id=price"`` CLI values into
    a goal-id-keyed price map.

    Same shape as ``_parse_target_action_price_options`` (goal id, never a
    label — see that function's docstring), but the price is NOT optional
    here, and on both pages that use this parse. On the EDIT page live recon
    (issue #717) confirmed a freshly added row's price input starts empty
    and Yandex's own client-side validation rejects saving it empty. On the
    CREATE page (issue #777 recon) it instead arrives pre-filled with a
    Yandex suggestion — but that is not a documented default either, and
    publishing a CPA the caller never chose is worse than requiring one. So
    neither page offers a default worth inheriting: always require
    ``"goal_id=price"``, never a bare goal id.
    """
    parsed: "dict[int, float]" = {}
    for raw in values:
        if "=" not in raw:
            raise click.UsageError(
                f"--add-target-action value {raw!r} must be in the form "
                '"goal_id=price" (e.g. "159614149=150") — a price is '
                "required, Yandex has no default for a newly added goal."
            )
        goal_part, price_part = raw.split("=", 1)
        try:
            goal_id = int(goal_part.strip())
        except ValueError:
            raise click.UsageError(
                f"--add-target-action goal_id {goal_part!r} must be an "
                "integer (the Yandex Metrika goal ID)."
            )
        try:
            price = float(price_part.strip())
        except ValueError:
            raise click.UsageError(
                f"--add-target-action price {price_part!r} for goal "
                f"{goal_id} must be a number."
            )
        if goal_id in parsed:
            raise click.UsageError(
                f"--add-target-action goal {goal_id} was specified more " "than once."
            )
        parsed[goal_id] = price
    return parsed


#: PascalCase batch key -> ``update_master`` keyword. The batch surface is a
#: strict 1:1 mirror of the single-campaign flags (issue #834): every key here
#: has exactly one ``--flag`` counterpart, and adding a flag without adding its
#: key would silently drop the field from a JSONL plan.
_UPDATE_FILE_FIELDS = {
    "CampaignId": "campaign_id",
    "WeeklyBudget": "weekly_budget",
    "PromotionGoal": "promotion_goal",
    "GoalPrice": "goal_price",
    "TargetActionPrices": "target_action_prices",
    "AddTargetActions": "add_target_actions",
    "RemoveTargetActionGoalIds": "remove_target_action_goal_ids",
    "DirectsHelps": "directs_helps",
    "Name": "name",
    "LandingUrl": "landing_url",
    "TrackingParams": "tracking_params",
    "Headlines": "headlines",
    "Texts": "texts",
    "ClearHeadlines": "clear_headlines",
    "ClearTexts": "clear_texts",
    "Images": "images",
    "AddVideo": "add_video",
    "AddVideoUrl": "add_video_url",
    "RemoveVideos": "remove_videos",
    "Gender": "gender",
    "AgeFrom": "age_from",
    "AgeTo": "age_to",
    "Devices": "devices",
    "AddAudienceTags": "add_audience_tags",
    "RemoveAudienceTags": "remove_audience_tags",
    "AddMetrikaCounters": "add_metrika_counters",
    "RemoveMetrikaCounters": "remove_metrika_counters",
    "AddSitelinks": "add_sitelinks",
    "RemoveSitelinks": "remove_sitelinks",
    "Launch": "launch",
}

#: The CLI flag each batch key mirrors, used to keep an error message pointing
#: at something the reader can act on in either mode.
_UPDATE_FILE_FIELD_FLAGS = {
    "WeeklyBudget": "--weekly-budget",
    "PromotionGoal": "--promotion-goal",
    "GoalPrice": "--goal-price",
    "TargetActionPrices": "--target-action-price",
    "AddTargetActions": "--add-target-action",
    "RemoveTargetActionGoalIds": "--remove-target-action",
    "DirectsHelps": "--directs-helps",
    "Name": "--name",
    "LandingUrl": "--landing-url",
    "TrackingParams": "--tracking-params",
    "Headlines": "--headline",
    "Texts": "--text",
    "ClearHeadlines": "--clear-headline",
    "ClearTexts": "--clear-text",
    "Images": "--image",
    "AddVideo": "--add-video",
    "AddVideoUrl": "--add-video-url",
    "RemoveVideos": "--remove-video",
    "Gender": "--gender",
    "AgeFrom": "--age-from",
    "AgeTo": "--age-to",
    "Devices": "--device",
    "AddAudienceTags": "--add-audience-tag",
    "RemoveAudienceTags": "--remove-audience-tag",
    "AddMetrikaCounters": "--add-metrika-counter",
    "RemoveMetrikaCounters": "--remove-metrika-counter",
    "AddSitelinks": "--add-sitelink",
    "RemoveSitelinks": "--remove-sitelink",
    "Launch": "--launch",
}


def _row_error(row_index: int, message: str) -> click.UsageError:
    """Build the batch's one and only error shape: row number, then cause.

    Every batch validation failure names its row — a plan is edited as a file,
    so "which line" is the first thing the reader needs (mirrors ``keywords
    add``'s ``Row {row_index}: ...`` wording).
    """
    return click.UsageError(f"Row {row_index}: {message}")


def _require_type(
    value: Any,
    expected: type,
    *,
    key: str,
    row_index: int,
    expected_label: str,
) -> Any:
    """Reject a JSON value whose type can't be what ``update_master`` expects.

    ``bool`` is excluded from the ``int`` check on purpose: Python's ``bool``
    is an ``int`` subclass, so ``{"WeeklyBudget": true}`` would otherwise pass
    a type check and reach the browser as the budget ``1``.
    """
    if expected is int and isinstance(value, bool):
        raise _row_error(row_index, f"{key} must be {expected_label}, got a boolean")
    if expected is float and isinstance(value, bool):
        raise _row_error(row_index, f"{key} must be {expected_label}, got a boolean")
    if expected is float and isinstance(value, int):
        return float(value)
    if not isinstance(value, expected):
        raise _row_error(
            row_index,
            f"{key} must be {expected_label}, got {type(value).__name__}",
        )
    return value


def _coerce_slot_map(
    value: Any,
    *,
    key: str,
    row_index: int,
    slot_count: int,
    value_label: str,
) -> "dict[int, str]":
    """Convert a ``{"1": "value"}`` slot object into the 0-based index map the
    browser layer takes, enforcing the SAME bounds as the single-campaign
    ``--headline``/``--text``/``--image`` flags.

    Slot numbers are 1-based in both modes, deliberately: a JSONL plan is
    usually written by transcribing the equivalent ``--headline "2=..."``
    invocation, and letting the same number mean slot 2 in one mode and slot 3
    in the other is exactly the silent mis-write the CLAUDE.md "no divergent
    forms" rule exists to prevent. JSON object keys are always strings, so the
    digits are parsed here rather than by Click's ``type=int``.
    """
    if not isinstance(value, dict):
        raise _row_error(
            row_index,
            f"{key} must be a JSON object keyed by 1-based slot number "
            f'(e.g. {{"1": "{value_label}"}}), got {type(value).__name__}',
        )
    parsed: "dict[int, str]" = {}
    for raw_slot, raw_value in value.items():
        try:
            slot_number = int(str(raw_slot).strip())
        except ValueError:
            raise _row_error(
                row_index, f"{key} slot key {raw_slot!r} must be an integer"
            )
        if slot_number < 1 or slot_number > slot_count:
            raise _row_error(
                row_index,
                f"{key} slot number {slot_number} is out of range — this "
                f"field has slots (1-{slot_count}).",
            )
        if not isinstance(raw_value, str) or not raw_value.strip():
            raise _row_error(
                row_index,
                f"{key} slot {slot_number} must be a non-empty string — "
                "removing a variant is not supported here, pass the "
                "replacement value instead.",
            )
        parsed[slot_number - 1] = raw_value
    return parsed


def _coerce_slot_list(
    value: Any, *, key: str, row_index: int, slot_count: int
) -> "list[int]":
    """Convert a ``ClearHeadlines``/``ClearTexts`` array of 1-based slot
    numbers into the 0-based index list the browser layer takes, rejecting a
    duplicate exactly like ``_parse_clear_slot_options`` does."""
    if not isinstance(value, list):
        raise _row_error(
            row_index,
            f"{key} must be a JSON array of 1-based slot numbers, got "
            f"{type(value).__name__}",
        )
    parsed: "list[int]" = []
    seen: "set[int]" = set()
    for raw_slot in value:
        slot_number = _require_type(
            raw_slot, int, key=key, row_index=row_index, expected_label="an integer"
        )
        if slot_number < 1 or slot_number > slot_count:
            raise _row_error(
                row_index,
                f"{key} slot number {slot_number} is out of range — this "
                f"field has slots (1-{slot_count}).",
            )
        if slot_number in seen:
            raise _row_error(
                row_index, f"{key} slot {slot_number} was specified more than once."
            )
        seen.add(slot_number)
        parsed.append(slot_number - 1)
    return parsed


def _coerce_position_list(value: Any, *, key: str, row_index: int) -> "list[int]":
    """Convert a ``Remove*`` array of 1-based positions into the 0-based list
    the browser layer takes.

    Duplicates are rejected for the reason spelled out in
    ``_parse_remove_audience_tag_options``: positions resolve against a single
    pre-mutation snapshot, so a repeated position would silently remove two
    DIFFERENT items rather than being a harmless no-op.
    """
    if not isinstance(value, list):
        raise _row_error(
            row_index,
            f"{key} must be a JSON array of 1-based positions, got "
            f"{type(value).__name__}",
        )
    parsed: "list[int]" = []
    seen: "set[int]" = set()
    for raw_position in value:
        position = _require_type(
            raw_position, int, key=key, row_index=row_index, expected_label="an integer"
        )
        if position < 1:
            raise _row_error(
                row_index, f"{key} position {position} must be 1 or greater."
            )
        if position in seen:
            raise _row_error(
                row_index, f"{key} position {position} was specified more than once."
            )
        seen.add(position)
        parsed.append(position - 1)
    return parsed


def _coerce_goal_price_map(
    value: Any, *, key: str, row_index: int
) -> "dict[int, float]":
    """Convert a ``{"<goal id>": price}`` object into the goal-id-keyed price
    map ``update_master`` takes, mirroring
    ``_parse_target_action_price_options``' checks."""
    if not isinstance(value, dict):
        raise _row_error(
            row_index,
            f"{key} must be a JSON object keyed by Metrika goal id, got "
            f"{type(value).__name__}",
        )
    parsed: "dict[int, float]" = {}
    for raw_goal, raw_price in value.items():
        try:
            goal_id = int(str(raw_goal).strip())
        except ValueError:
            raise _row_error(
                row_index, f"{key} goal id {raw_goal!r} must be an integer"
            )
        price = _require_type(
            raw_price, float, key=key, row_index=row_index, expected_label="a number"
        )
        if price <= 0:
            raise _row_error(
                row_index, f"{key} price for goal {goal_id} must be greater than 0."
            )
        parsed[goal_id] = price
    return parsed


def _coerce_string_list(value: Any, *, key: str, row_index: int) -> "list[str]":
    if not isinstance(value, list):
        raise _row_error(
            row_index,
            f"{key} must be a JSON array of strings, got {type(value).__name__}",
        )
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            raise _row_error(row_index, f"{key} entries must be non-empty strings")
    return list(value)


def _coerce_sitelink_list(
    value: Any, *, key: str, row_index: int
) -> "list[dict[str, str]]":
    """Validate ``AddSitelinks`` — the typed JSON form of ``--add-sitelink
    "Title|Href|Description"``.

    All three parts stay mandatory here for the same not-live-confirmed reason
    documented on ``_parse_add_sitelink_options``; only the surface differs
    (named keys instead of a pipe-separated string).
    """
    if not isinstance(value, list):
        raise _row_error(
            row_index,
            f"{key} must be a JSON array of sitelink objects, got "
            f"{type(value).__name__}",
        )
    required = ("Title", "Href", "Description")
    parsed: "list[dict[str, str]]" = []
    for entry in value:
        if not isinstance(entry, dict):
            raise _row_error(
                row_index,
                f"{key} entries must be JSON objects with keys "
                f"{', '.join(required)}",
            )
        unknown = sorted(set(entry) - set(required))
        if unknown:
            raise _row_error(
                row_index,
                f"{key} entry has unknown key {unknown[0]!r}; allowed: "
                f"{', '.join(required)}",
            )
        for part in required:
            if part not in entry:
                raise _row_error(
                    row_index, f"{key} entry is missing required key {part!r}"
                )
            if not isinstance(entry[part], str) or not entry[part].strip():
                raise _row_error(
                    row_index, f"{key} entry key {part!r} must be a non-empty string"
                )
        parsed.append({part: entry[part] for part in required})
    return parsed


def _coerce_choice(
    value: Any, *, key: str, row_index: int, choices: "tuple[Any, ...]"
) -> Any:
    """Enforce the same value set the single-campaign flag's ``click.Choice``
    enforces, so a typo fails at the CLI boundary instead of mid-session."""
    if value not in choices:
        rendered = ", ".join(repr(choice) for choice in choices)
        raise _row_error(row_index, f"{key} must be one of: {rendered} (got {value!r})")
    return value


def _normalize_master_update_row(row: Any, row_index: int) -> Dict[str, Any]:
    """Normalize and fully validate one PascalCase batch row.

    Mirrors ``keywords add``'s ``_normalize_keyword_row``: a whitelist of
    allowed keys (an unknown key is an error naming the row and the allowed
    set, never a silent skip), then a per-field coercion into exactly the
    shapes ``update_master`` takes.

    Every check the single-campaign flags get from Click's own types
    (``type=int``, ``click.Choice``, the ``_parse_*_options`` helpers) is
    re-applied here by hand, because a JSONL value never passes through Click.
    Without that, ``{"AgeFrom": "999"}`` or ``{"WeeklyBudget": "abc"}`` would
    reach the browser as-is and fail mid-mutation — the batch surface would be
    strictly less safe than the flags it mirrors.
    """
    from ..browser.masters import (
        _HEADLINES_SLOT_COUNT,
        _IMAGES_MAX_COUNT,
        _TEXTS_SLOT_COUNT,
    )

    if not isinstance(row, dict):
        raise _row_error(row_index, f"expected JSON object, got {type(row).__name__}")

    unknown = sorted(set(row) - set(_UPDATE_FILE_FIELDS))
    if unknown:
        allowed = ", ".join(_UPDATE_FILE_FIELDS)
        raise click.UsageError(
            f"Unknown field {unknown[0]!r} in masters row {row_index}; "
            f"allowed: {allowed}"
        )

    if "CampaignId" not in row:
        raise _row_error(row_index, "missing required field 'CampaignId'")
    campaign_id = _require_type(
        row["CampaignId"],
        int,
        key="CampaignId",
        row_index=row_index,
        expected_label="an integer",
    )

    update_keys = [key for key in row if key != "CampaignId"]
    if not update_keys:
        raise _row_error(
            row_index,
            "provide at least one update field besides CampaignId; allowed: "
            + ", ".join(key for key in _UPDATE_FILE_FIELDS if key != "CampaignId"),
        )

    item: Dict[str, Any] = {"campaign_id": campaign_id}
    for key in update_keys:
        value = row[key]
        target = _UPDATE_FILE_FIELDS[key]
        if key in ("Name", "LandingUrl", "TrackingParams", "AddVideo", "AddVideoUrl"):
            item[target] = _require_type(
                value,
                str,
                key=key,
                row_index=row_index,
                expected_label="a string",
            )
        elif key == "WeeklyBudget":
            item[target] = _require_type(
                value, int, key=key, row_index=row_index, expected_label="an integer"
            )
        elif key == "GoalPrice":
            item[target] = _require_type(
                value, float, key=key, row_index=row_index, expected_label="a number"
            )
        elif key in ("DirectsHelps", "Launch"):
            item[target] = _require_type(
                value, bool, key=key, row_index=row_index, expected_label="a boolean"
            )
        elif key in ("TargetActionPrices", "AddTargetActions"):
            item[target] = _coerce_goal_price_map(value, key=key, row_index=row_index)
        elif key == "RemoveTargetActionGoalIds":
            goal_ids: "list[int]" = []
            if not isinstance(value, list):
                raise _row_error(
                    row_index,
                    f"{key} must be a JSON array of Metrika goal ids, got "
                    f"{type(value).__name__}",
                )
            for raw_goal in value:
                goal_id = _require_type(
                    raw_goal,
                    int,
                    key=key,
                    row_index=row_index,
                    expected_label="an integer",
                )
                if goal_id in goal_ids:
                    raise _row_error(
                        row_index, f"{key} goal {goal_id} was specified more than once."
                    )
                goal_ids.append(goal_id)
            item[target] = goal_ids
        elif key in ("Headlines", "Texts"):
            item[target] = _coerce_slot_map(
                value,
                key=key,
                row_index=row_index,
                slot_count=(
                    _HEADLINES_SLOT_COUNT if key == "Headlines" else _TEXTS_SLOT_COUNT
                ),
                value_label="New headline" if key == "Headlines" else "New text",
            )
        elif key == "Images":
            item[target] = _coerce_slot_map(
                value,
                key=key,
                row_index=row_index,
                slot_count=_IMAGES_MAX_COUNT,
                value_label="/path/to/image.jpg",
            )
        elif key in ("ClearHeadlines", "ClearTexts"):
            item[target] = _coerce_slot_list(
                value,
                key=key,
                row_index=row_index,
                slot_count=(
                    _HEADLINES_SLOT_COUNT
                    if key == "ClearHeadlines"
                    else _TEXTS_SLOT_COUNT
                ),
            )
        elif key in (
            "RemoveAudienceTags",
            "RemoveMetrikaCounters",
            "RemoveSitelinks",
        ):
            item[target] = _coerce_position_list(value, key=key, row_index=row_index)
        elif key in ("RemoveVideos", "AddAudienceTags", "AddMetrikaCounters"):
            item[target] = _coerce_string_list(value, key=key, row_index=row_index)
        elif key == "AddSitelinks":
            item[target] = _coerce_sitelink_list(value, key=key, row_index=row_index)
        elif key == "PromotionGoal":
            item[target] = _coerce_choice(
                value,
                key=key,
                row_index=row_index,
                choices=tuple(_PROMOTION_GOAL_CHOICES),
            )
        elif key == "Gender":
            item[target] = _coerce_choice(
                value, key=key, row_index=row_index, choices=tuple(_GENDER_CHOICES)
            )
        elif key == "Devices":
            devices = _coerce_string_list(value, key=key, row_index=row_index)
            for device in devices:
                _coerce_choice(
                    device,
                    key=key,
                    row_index=row_index,
                    choices=tuple(_DEVICE_OPTION_VALUES),
                )
            item[target] = set(devices)
        elif key == "AgeFrom":
            item[target] = _coerce_choice(
                value,
                key=key,
                row_index=row_index,
                choices=tuple(_AGE_FROM_CHOICES),
            )
            # ``update_master`` distinguishes "not requested" from an
            # explicitly requested bound, exactly as the flag path does via
            # ``age_from is not None``.
            item["age_from_requested"] = True
        elif key == "AgeTo":
            # "unlimited" is the flag's spelling of AgeTo=None ("55+"); the
            # browser layer takes None, so translate at this boundary rather
            # than teaching it a second spelling.
            choices = tuple(
                "unlimited" if choice is None else choice for choice in _AGE_TO_CHOICES
            )
            chosen = _coerce_choice(
                value, key=key, row_index=row_index, choices=choices
            )
            item[target] = None if chosen == "unlimited" else chosen
            item["age_to_requested"] = True
        else:  # pragma: no cover - defensive, every key is handled above
            raise _row_error(row_index, f"{key} is not supported in batch mode")

    _reject_conflicting_row_fields(item, row_index)
    return item


def _reject_conflicting_row_fields(item: Dict[str, Any], row_index: int) -> None:
    """Re-apply the single-campaign cross-field guards to one batch row.

    These are the checks the flag path performs after parsing (goal/price
    compatibility, a goal targeted twice, a slot both set and cleared). They
    are duplicated per row rather than skipped because the underlying page
    behaviour is identical in either mode — a conflict that is ambiguous
    enough to refuse from the CLI is just as ambiguous inside a plan file.
    """
    promotion_goal = item.get("promotion_goal")
    if item.get("goal_price") is not None and promotion_goal == "max-conversions":
        raise _row_error(
            row_index,
            "GoalPrice has no effect under PromotionGoal 'max-conversions' — "
            "that goal's price is set per-target-action via "
            "TargetActionPrices instead.",
        )
    if promotion_goal == "max-clicks" and (
        item.get("target_action_prices")
        or item.get("add_target_actions")
        or item.get("remove_target_action_goal_ids")
    ):
        raise _row_error(
            row_index,
            "TargetActionPrices/AddTargetActions/RemoveTargetActionGoalIds "
            "have no effect under PromotionGoal 'max-clicks' — that goal's "
            "price is set once for the whole campaign via GoalPrice instead.",
        )

    seen_goals: "dict[int, str]" = {}
    for field, goals in (
        ("TargetActionPrices", item.get("target_action_prices") or {}),
        ("AddTargetActions", item.get("add_target_actions") or {}),
        ("RemoveTargetActionGoalIds", item.get("remove_target_action_goal_ids") or []),
    ):
        for goal_id in goals:
            if goal_id in seen_goals:
                raise _row_error(
                    row_index,
                    f"Goal {goal_id} was passed to both {seen_goals[goal_id]} "
                    f"and {field} — a goal can only be targeted by one of "
                    "TargetActionPrices/AddTargetActions/"
                    "RemoveTargetActionGoalIds in the same row.",
                )
            seen_goals[goal_id] = field

    for set_field, clear_field, set_key, clear_key in (
        ("Headlines", "ClearHeadlines", "headlines", "clear_headlines"),
        ("Texts", "ClearTexts", "texts", "clear_texts"),
    ):
        overlap = sorted(set(item.get(set_key) or {}) & set(item.get(clear_key) or []))
        if overlap:
            raise _row_error(
                row_index,
                f"slot {overlap[0] + 1} was passed to both {set_field} and "
                f"{clear_field} — set it or clear it, not both.",
            )


def _reject_duplicate_campaign_ids(rows: List[Dict[str, Any]]) -> None:
    """Refuse a plan naming the same campaign twice.

    Two rows for one campaign would mean two full edit-page saves, and the
    retry bookkeeping in :func:`_run_update_file_batch` keys completion by
    campaign id — so a duplicate is also the one input that could make a
    replay skip a row that never ran. Merge the rows instead.
    """
    seen: "dict[int, int]" = {}
    for index, row in enumerate(rows, start=1):
        campaign_id = row["campaign_id"]
        if campaign_id in seen:
            raise click.UsageError(
                f"Campaign {campaign_id} appears in more than one row "
                f"(rows {seen[campaign_id]} and {index}) — merge them into a "
                "single row: each campaign is saved once per batch."
            )
        seen[campaign_id] = index


def _batch_row_report(row: Dict[str, Any]) -> Dict[str, Any]:
    """Render one normalized row back into the PascalCase report shape.

    The report is the plan's own vocabulary, not the browser layer's: internal
    snake_case keys, 0-based indices and the ``*_requested`` bookkeeping flags
    are implementation detail that must not leak into ``--dry-run`` output.
    """
    report: Dict[str, Any] = {"CampaignId": row["campaign_id"]}
    for key, target in _UPDATE_FILE_FIELDS.items():
        if key == "CampaignId" or target not in row:
            continue
        value = row[target]
        if key in ("Headlines", "Texts", "Images"):
            value = {str(index + 1): slot_value for index, slot_value in value.items()}
        elif key in ("ClearHeadlines", "ClearTexts"):
            value = [index + 1 for index in value]
        elif key in ("RemoveAudienceTags", "RemoveMetrikaCounters", "RemoveSitelinks"):
            value = [position + 1 for position in value]
        elif key in ("TargetActionPrices", "AddTargetActions"):
            value = {str(goal_id): price for goal_id, price in value.items()}
        elif key == "Devices":
            value = sorted(value)
        elif key == "AgeTo" and value is None:
            value = "unlimited"
        report[key] = value
    return report


def _parse_update_file_rows(path: str) -> List[Dict[str, Any]]:
    """Decode and validate JSONL rows using the shared batch loader."""
    from . import _batch

    rows = _batch.load_jsonl_rows(path)
    if not rows:
        raise click.UsageError(f"--from-file {path!r} contains no campaign rows.")
    parsed = [
        _normalize_master_update_row(row, index)
        for index, row in enumerate(rows, start=1)
    ]
    _reject_duplicate_campaign_ids(parsed)
    return parsed


def _parse_update_inline_rows(value: str) -> List[Dict[str, Any]]:
    from . import _batch

    rows = _batch.load_inline_rows(
        value,
        invalid_json_key="--masters-json: invalid JSON: {arg0}",
        not_array_key="--masters-json must be a JSON array of campaign objects",
    )
    if not rows:
        raise click.UsageError("Input contains no campaign rows.")
    parsed = [
        _normalize_master_update_row(row, index)
        for index, row in enumerate(rows, start=1)
    ]
    _reject_duplicate_campaign_ids(parsed)
    return parsed


#: Placeholder left in a row's report when the campaign WAS saved but the
#: follow-up ``--moderation-statuses`` read could not complete (the session
#: went stale mid-read, and the save is not replayed on retry). Reporting the
#: save with an explicit "not read" beats omitting the key, which reads as
#: "nothing to report" for a campaign that was in fact mutated.
_MODERATION_READ_INTERRUPTED = (
    "not read — session expired after this campaign was saved; "
    "re-read with `masters get --moderation-statuses`"
)


def _run_update_file_batch(
    ctx,
    rows: List[Dict[str, Any]],
    *,
    headful: bool,
    profile_dir: Optional[str],
    chrome_profile: str,
    moderation_statuses: bool,
    dry_run: bool,
    pacing_ms: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Apply a validated update plan to every campaign in ONE browser session.

    One session for the whole plan is the point of the command (issue #834):
    the live failures it exists to avoid correlated with how often a profile
    re-entered Yandex, not with how many campaigns were edited.

    ``completed``/``outcomes`` deliberately live OUTSIDE the operation handed
    to ``_with_session``, whose ``BrowserAuthError`` retry re-runs the whole
    operation under a fresh session. For a read-only fetch that replay is
    free; here every replayed row is a second real save of a campaign already
    saved in production. Keeping both maps across the retry lets the replay
    skip finished campaigns and, just as importantly, keeps their results in
    the report — a mutation that happened but goes unreported is the failure
    mode issue #816 was filed for.
    """
    from ..browser.masters import (
        PlaywrightError,
        _BATCH_UPDATE_PACING_MS,
        fetch_master_moderation_statuses,
        update_master,
    )
    from ..browser.session import BrowserAuthError, BrowserSessionError

    pause_ms = _BATCH_UPDATE_PACING_MS if pacing_ms is None else pacing_ms

    for index, row in enumerate(rows, start=1):
        try:
            _validate_image_paths(row.get("images") or {})
            if (
                row.get("add_video") is not None
                and row.get("add_video_url") is not None
            ):
                raise click.UsageError(
                    "AddVideo and AddVideoUrl are mutually exclusive — "
                    "provide a local file path to upload a new video, or "
                    "an existing video's URL to select it from the "
                    "account's video library, not both."
                )
            if row.get("add_video") is not None:
                _validate_video_path(row["add_video"])
        except click.UsageError as exc:
            # Local-file checks run for the WHOLE plan before the first save,
            # so a typo in the last row cannot leave the first ones already
            # mutated (the flag path gets this for free -- it only ever has
            # one campaign to validate).
            raise _row_error(index, exc.format_message()) from exc

    if dry_run:
        return [_batch_row_report(row) for row in rows]

    completed: "set[int]" = set()
    outcomes: Dict[int, Dict[str, Any]] = {}

    def operation(page):
        for position, row in enumerate(rows):
            campaign_id = row["campaign_id"]
            if campaign_id in completed:
                continue
            kwargs = {key: value for key, value in row.items() if key != "campaign_id"}
            try:
                result = update_master(page, campaign_id, **kwargs)
                # Record the save as both done AND reportable before the
                # optional moderation read: that read navigates again and can
                # raise BrowserAuthError, and a save already applied in
                # production must neither be replayed nor vanish from the
                # report just because the follow-up read failed.
                completed.add(campaign_id)
                outcomes[campaign_id] = result
                if moderation_statuses:
                    # Marked pending first so that if this read is what raises
                    # BrowserAuthError, the retry (which skips the completed
                    # save) still reports WHY the statuses are missing rather
                    # than silently omitting the key.
                    result["ModerationStatuses"] = _MODERATION_READ_INTERRUPTED
                    result["ModerationStatuses"] = fetch_master_moderation_statuses(
                        page, campaign_id
                    )
            except BrowserAuthError:
                raise
            except (BrowserSessionError, PlaywrightError) as exc:
                completed.add(campaign_id)
                outcomes[campaign_id] = {"CampaignId": campaign_id, "Error": str(exc)}
            if pause_ms and position != len(rows) - 1:
                # Pace after EVERY attempt, including a failed one: the live
                # failures behind issue #829 tracked how often the profile hit
                # Yandex, and a row that failed still navigated there.
                page.wait_for_timeout(pause_ms)
        return [
            outcomes[row["campaign_id"]]
            for row in rows
            if row["campaign_id"] in outcomes
        ]

    return _with_session(ctx, headful, profile_dir, chrome_profile, operation)


def _parse_remove_target_action_options(values: "tuple[str, ...]") -> "list[int]":
    """Parse repeated ``--remove-target-action "goal_id"`` CLI values into a
    list of goal ids, identified the same way as every other target-action
    option (numeric Yandex Metrika goal id, never a label)."""
    parsed: "list[int]" = []
    seen: "set[int]" = set()
    for raw in values:
        try:
            goal_id = int(raw.strip())
        except ValueError:
            raise click.UsageError(
                f"--remove-target-action value {raw!r} must be an integer "
                "(the Yandex Metrika goal ID, as shown by `masters "
                "targetactions get`)."
            )
        if goal_id in seen:
            raise click.UsageError(
                f"--remove-target-action goal {goal_id} was specified more "
                "than once."
            )
        seen.add(goal_id)
        parsed.append(goal_id)
    return parsed


def _parse_remove_audience_tag_options(values: "tuple[int, ...]") -> "list[int]":
    """Parse repeated ``--remove-audience-tag`` CLI values into a list of
    0-based positions, rejecting a duplicate the same way
    ``_parse_remove_target_action_options`` rejects a duplicate goal id —
    positions are resolved against a single pre-mutation snapshot
    (``update_master``'s ``audience_tags_before``), so a repeated position
    would silently remove two DIFFERENT tags (the one originally at that
    position, then whatever shifted into it after the first removal)
    instead of raising."""
    seen: "set[int]" = set()
    for position in values:
        if position in seen:
            raise click.UsageError(
                f"--remove-audience-tag position {position + 1} was "
                "specified more than once."
            )
        seen.add(position)
    return list(values)


def _parse_remove_metrika_counter_options(values: "tuple[int, ...]") -> "list[int]":
    """Parse repeated ``--remove-metrika-counter`` CLI values into a list of
    0-based positions — mirrors ``_parse_remove_audience_tag_options``
    exactly, for the same "positions resolve against a single pre-mutation
    snapshot" reason (``update_master``'s ``metrika_counters_before``)."""
    seen: "set[int]" = set()
    for position in values:
        if position in seen:
            raise click.UsageError(
                f"--remove-metrika-counter position {position + 1} was "
                "specified more than once."
            )
        seen.add(position)
    return list(values)


def _parse_add_sitelink_options(
    values: "tuple[str, ...]",
) -> "list[dict[str, str]]":
    """Parse repeated ``--add-sitelink "Title|Href|Description"`` CLI values.

    Requires exactly 3 pipe-separated parts (2 pipes) — unlike the WSDL-API
    ``direct sitelinks add --sitelink`` command's ``parse_sitelink_specs``
    (``direct_cli/utils.py``), which accepts 2-4 parts and treats
    Description/TurboPageId as optional. This is a DIFFERENT feature (see
    module docstring: browser-driven Мастер кампаний sitelinks, not the WSDL
    ``SitelinksSet`` resource) with no live confirmation that the edit
    page's inline form tolerates an omitted field the way the WSDL request
    does, so the format is deliberately stricter here: all three parts —
    Title, Href, AND Description — must be non-empty. This may be loosened
    once the inline form's actual behaviour with a blank description is
    live-verified (see ``direct_cli/browser/masters.py``'s
    ``_SITELINKS_EDITOR_TESTID`` module comment).

    No escape syntax for a literal ``|`` (unlike ``parse_sitelink_specs``'s
    ``\\|``) — added only if a real need for one shows up, to keep this
    format as simple as possible for now.
    """
    parsed: "list[dict[str, str]]" = []
    for raw in values:
        parts = raw.split("|")
        if len(parts) != 3:
            raise click.UsageError(
                f"--add-sitelink value {raw!r} must be in the form "
                "\"Title|Href|Description\" (exactly 2 '|' separators, e.g. "
                '"Об авторе|https://example.com/about|Узнайте больше").'
            )
        title, href, description = (part.strip() for part in parts)
        if not title:
            raise click.UsageError(
                f"--add-sitelink value {raw!r} has an empty Title — Title "
                "is required."
            )
        if not href:
            raise click.UsageError(
                f"--add-sitelink value {raw!r} has an empty Href — Href is " "required."
            )
        if not description:
            raise click.UsageError(
                f"--add-sitelink value {raw!r} has an empty Description — "
                "Description is required (this may be relaxed once the "
                "edit page's actual behaviour with a blank description is "
                "confirmed; for now pass some text)."
            )
        parsed.append({"Title": title, "Href": href, "Description": description})
    return parsed


def _parse_remove_sitelink_options(values: "tuple[int, ...]") -> "list[int]":
    """Parse repeated ``--remove-sitelink`` CLI values into a list of 0-based
    positions, rejecting a duplicate — mirrors
    ``_parse_remove_audience_tag_options``: positions are resolved against a
    single pre-mutation snapshot (``update_master``'s ``sitelinks_before``),
    so a repeated position would silently remove two DIFFERENT sitelinks
    (the one originally at that position, then whatever shifted into it
    after the first removal) instead of raising."""
    seen: "set[int]" = set()
    for position in values:
        if position in seen:
            raise click.UsageError(
                f"--remove-sitelink position {position + 1} was specified "
                "more than once."
            )
        seen.add(position)
    return list(values)


def _validate_image_path(raw_path: str, *, option_name: str, context: str) -> None:
    """Reject one image path that doesn't exist or that Yandex won't accept.

    Runs before any browser session (and possibly an auth prompt) is opened,
    mirroring every other format error in this command. The accepted
    extensions come from the browser layer's own ``_IMAGE_UPLOAD_SUFFIXES``
    (imported here rather than at module load, matching this module's other
    deferred browser imports) so the CLI's check can't drift from what
    Yandex's file input actually accepts.

    Shared by ``_validate_image_paths`` (``--image "N=path"``, slot-indexed)
    and ``_validate_image_files`` (``--image-file path``, no slot) — ``context``
    supplies whatever slot/position wording the caller wants appended to the
    error, or an empty string for none.
    """
    from ..browser.masters import _IMAGE_UPLOAD_SUFFIXES

    path = Path(raw_path)
    if not path.is_file():
        raise click.UsageError(
            f"{option_name} path {raw_path!r}{context} does not exist or "
            "is not a file."
        )
    if path.suffix.lower() not in _IMAGE_UPLOAD_SUFFIXES:
        raise click.UsageError(
            f"{option_name} path {raw_path!r}{context} has an unsupported "
            f"extension {path.suffix!r} — Yandex accepts PNG, JPEG, or GIF."
        )


def _validate_image_paths(parsed_images: "dict[int, str]") -> None:
    """Reject ``--image "N=path"`` paths that don't exist or that Yandex
    won't accept. See ``_validate_image_path`` for the per-path check."""
    for index, raw_path in parsed_images.items():
        _validate_image_path(
            raw_path, option_name="--image", context=f" (slot {index + 1})"
        )


def _validate_image_files(paths: "tuple[str, ...]") -> None:
    """Reject ``--image-file`` paths that don't exist or that Yandex won't
    accept. See ``_validate_image_path`` for the per-path check."""
    for raw_path in paths:
        _validate_image_path(raw_path, option_name="--image-file", context="")


def _validate_video_path(raw_path: str) -> None:
    """Reject an ``--add-video`` path that doesn't exist or that this
    command doesn't recognize as a video file.

    Mirrors ``_validate_image_path``, but the extension allowlist
    (``_VIDEO_UPLOAD_SUFFIXES``) is NOT a confirmed-live reading of the
    video modal's file input the way ``_IMAGE_UPLOAD_SUFFIXES`` is for
    images — see that constant's module comment in
    ``direct_cli/browser/masters.py``. It is a conservative guess (common
    Yandex video-creative formats), so this check may reject a file Yandex
    would actually accept, or (less likely) accept one it would reject.
    """
    from ..browser.masters import _VIDEO_UPLOAD_SUFFIXES

    path = Path(raw_path)
    if not path.is_file():
        raise click.UsageError(
            f"--add-video path {raw_path!r} does not exist or is not a file."
        )
    if path.suffix.lower() not in _VIDEO_UPLOAD_SUFFIXES:
        raise click.UsageError(
            f"--add-video path {raw_path!r} has an unsupported extension "
            f"{path.suffix!r}. This command expects one of "
            f"{sorted(_VIDEO_UPLOAD_SUFFIXES)} — NOTE this list is not "
            "live-confirmed against Yandex's actual upload widget (see "
            "direct_cli/browser/masters.py's _VIDEO_UPLOAD_SUFFIXES "
            "comment), so a genuinely valid video file may still be "
            "rejected here."
        )


@masters.group("adimages")
def adimages():
    """Manage a Мастер кампаний campaign's image set (browser-driven, no API)

    Мастер кампаний has no Yandex Direct API surface (see this module's own
    docstring), so unlike ``direct adimages get/add/delete`` (API-backed ad
    images, ``direct_cli/commands/adimages.py``) every subcommand here drives
    a real browser session against the campaign's edit page. The vocabulary
    is deliberately the same — ``get``/``add``/``delete``, plus ``set`` for a
    whole-set replacement the API-side group has no equivalent for — but
    there is no ``--dry-run``: there is no request payload to preview for a
    browser-driven mutation, matching ``masters update``'s existing
    precedent.

    Unlike ``masters update --image`` (point-replacement of one existing
    image only, refuses on an empty set), these commands treat an empty
    image set as a completely normal state on both ends — a campaign can
    start with zero images, and every image can be deleted, exactly like ad
    images on a text ad via the API.
    """


@adimages.command("get")
@click.argument("campaign_id", type=int)
@_masters_browser_options
@click.pass_context
@handle_api_errors
def adimages_get(
    ctx, campaign_id, headful, profile_dir, chrome_profile, output_format, output
):
    """Get a Мастер кампаний campaign's current image set

    An empty set is a valid, successful result (``Count: 0``), not an
    error — see the ``adimages`` group's docstring.
    """
    from ..browser.masters import fetch_master_images

    result = _with_session(
        ctx,
        headful,
        profile_dir,
        chrome_profile,
        lambda page: fetch_master_images(page, campaign_id),
    )

    format_output(result, output_format, output)


@adimages.command("add")
@click.argument("campaign_id", type=int)
@click.option(
    "--image-file",
    "image_files",
    multiple=True,
    required=True,
    help=(
        "Local PNG/JPEG/GIF file to append to the campaign's image set — "
        "repeat for multiple files. Works even if the campaign currently "
        "has no images."
    ),
)
@click.option(
    "--launch",
    is_flag=True,
    default=False,
    help=(
        "If CAMPAIGN_ID is currently a DRAFT, publish it while saving "
        "(default: keep it a DRAFT). Has no effect on a non-DRAFT campaign."
    ),
)
@_masters_browser_options
@click.pass_context
@handle_api_errors
def adimages_add(
    ctx,
    campaign_id,
    image_files,
    launch,
    headful,
    profile_dir,
    chrome_profile,
    output_format,
    output,
):
    """Append one or more local images to a Мастер кампаний campaign"""
    from ..browser.masters import _IMAGES_MAX_COUNT, add_master_images

    if len(image_files) > _IMAGES_MAX_COUNT:
        raise click.UsageError(
            f"--image-file was passed {len(image_files)} times — Yandex's "
            f"cap is {_IMAGES_MAX_COUNT} images per campaign."
        )
    _validate_image_files(image_files)

    result = _with_session(
        ctx,
        headful,
        profile_dir,
        chrome_profile,
        lambda page: add_master_images(
            page, campaign_id, paths=list(image_files), launch=launch
        ),
    )

    format_output(result, output_format, output)


@adimages.command("delete")
@click.argument("campaign_id", type=int)
@click.option(
    "--position",
    "positions",
    multiple=True,
    type=int,
    help=(
        "1-based position of an image to delete, as shown by `masters "
        "adimages get` — repeat for multiple. Mutually exclusive with --all."
    ),
)
@click.option(
    "--content-id",
    "content_ids",
    multiple=True,
    help=(
        "Yandex content ID of an image to delete, as shown by `masters "
        "adimages get` — repeat for multiple. The positional analogue of "
        "the API group's `adimages delete --hash`. Mutually exclusive "
        "with --all."
    ),
)
@click.option(
    "--all",
    "all_images",
    is_flag=True,
    default=False,
    help=(
        "Delete EVERY image in the campaign. Leaving a campaign with zero "
        "images is a valid state. Mutually exclusive with --position/"
        "--content-id. Idempotent if the campaign already has no images."
    ),
)
@click.option(
    "--launch",
    is_flag=True,
    default=False,
    help=(
        "If CAMPAIGN_ID is currently a DRAFT, publish it while saving "
        "(default: keep it a DRAFT). Has no effect on a non-DRAFT campaign."
    ),
)
@_masters_browser_options
@click.pass_context
@handle_api_errors
def adimages_delete(
    ctx,
    campaign_id,
    positions,
    content_ids,
    all_images,
    launch,
    headful,
    profile_dir,
    chrome_profile,
    output_format,
    output,
):
    """Delete one or more images from a Мастер кампаний campaign"""
    from ..browser.masters import _IMAGES_MAX_COUNT, delete_master_images

    if not positions and not content_ids and not all_images:
        raise click.UsageError(
            "Provide at least one of --position, --content-id, or --all."
        )
    if all_images and (positions or content_ids):
        raise click.UsageError(
            "--all cannot be combined with --position/--content-id — "
            "pass --all on its own to delete every image, or list "
            "specific --position/--content-id values without --all."
        )
    if len(set(positions)) != len(positions):
        raise click.UsageError(
            "--position was specified more than once for the same slot."
        )
    for position in positions:
        if position < 1 or position > _IMAGES_MAX_COUNT:
            raise click.UsageError(
                f"--position {position} is out of range — expected "
                f"1-{_IMAGES_MAX_COUNT}."
            )

    result = _with_session(
        ctx,
        headful,
        profile_dir,
        chrome_profile,
        lambda page: delete_master_images(
            page,
            campaign_id,
            positions=[p - 1 for p in positions] or None,
            content_ids=list(content_ids) or None,
            all_images=all_images,
            launch=launch,
        ),
    )

    format_output(result, output_format, output)


@adimages.command("set")
@click.argument("campaign_id", type=int)
@click.option(
    "--image-file",
    "image_files",
    multiple=True,
    help="Local PNG/JPEG/GIF file — repeat for multiple. Replaces the WHOLE image set.",
)
@click.option(
    "--allow-empty",
    is_flag=True,
    default=False,
    help=(
        "Permit `set` with no --image-file, i.e. delete every image. "
        "Without this flag, `set` with no files is refused as a likely "
        "mistake (e.g. an empty shell glob)."
    ),
)
@click.option(
    "--launch",
    is_flag=True,
    default=False,
    help=(
        "If CAMPAIGN_ID is currently a DRAFT, publish it while saving "
        "(default: keep it a DRAFT). Has no effect on a non-DRAFT campaign."
    ),
)
@_masters_browser_options
@click.pass_context
@handle_api_errors
def adimages_set(
    ctx,
    campaign_id,
    image_files,
    allow_empty,
    launch,
    headful,
    profile_dir,
    chrome_profile,
    output_format,
    output,
):
    """Replace a Мастер кампаний campaign's ENTIRE image set

    Every current image is removed and every ``--image-file`` is uploaded,
    inside one modal session. With no ``--image-file`` this deletes every
    image — pass ``--allow-empty`` to confirm, or use ``masters adimages
    delete --all`` instead.
    """
    from ..browser.masters import _IMAGES_MAX_COUNT, set_master_images

    if not image_files and not allow_empty:
        raise click.UsageError(
            "'set' with no --image-file would delete every image. Pass "
            "--allow-empty to confirm, or use 'masters adimages delete "
            "--all'."
        )
    if len(image_files) > _IMAGES_MAX_COUNT:
        raise click.UsageError(
            f"--image-file was passed {len(image_files)} times — Yandex's "
            f"cap is {_IMAGES_MAX_COUNT} images per campaign."
        )
    _validate_image_files(image_files)

    result = _with_session(
        ctx,
        headful,
        profile_dir,
        chrome_profile,
        lambda page: set_master_images(
            page, campaign_id, paths=list(image_files), launch=launch
        ),
    )

    format_output(result, output_format, output)


@masters.group("targetactions")
def targetactions():
    """Read a Мастер кампаний campaign's "Целевые действия" (target action /
    CPA) table (browser-driven, no API)

    Мастер кампаний has no Yandex Direct API surface (see this module's own
    docstring), and this table lives only on the campaign's edit page (issue
    #707) — same reasoning as the ``adimages`` group above. Read-only: this
    group only reads the table. Writing an existing goal's price is
    ``masters update --target-action-price``; adding/removing a row is
    ``masters update --add-target-action``/``--remove-target-action``
    (issue #717).
    """


@targetactions.command("get")
@click.argument("campaign_id", type=int)
@_masters_browser_options
@click.pass_context
@handle_api_errors
def targetactions_get(
    ctx, campaign_id, headful, profile_dir, chrome_profile, output_format, output
):
    """Get a Мастер кампаний campaign's current target-action (CPA) goals

    An empty list is a valid, successful result (``Count: 0``) — either the
    campaign's promotion goal is not "max-conversions" (the table doesn't
    exist on the page at all), or no goal has been added to it yet. Use
    ``masters get`` to check the campaign's current promotion goal.
    """
    from ..browser.masters import fetch_master_target_actions

    result = _with_session(
        ctx,
        headful,
        profile_dir,
        chrome_profile,
        lambda page: fetch_master_target_actions(page, campaign_id),
    )

    format_output(result, output_format, output)


@masters.group("counters")
def counters():
    """Read a Мастер кампаний campaign's linked "Счетчики Яндекс Метрики"
    (browser-driven, no API)

    Sibling of the ``targetactions``/``audience`` groups above, and the
    missing half of the target-action story (issue #842): a goal can only be
    added from a LINKED counter's goals, so "``--add-target-action`` can't
    find the goal" and "no counter is linked at all" are different problems
    that used to look identical from the CLI. Read-only: linking a counter
    is ``masters update --add-metrika-counter``.
    """


@counters.command("get")
@click.argument("campaign_id", type=int)
@_masters_browser_options
@click.pass_context
@handle_api_errors
def counters_get(
    ctx, campaign_id, headful, profile_dir, chrome_profile, output_format, output
):
    """Get a Мастер кампаний campaign's currently linked Metrika counters

    ``SectionPresent: false`` means the "Счетчики Яндекс Метрики" section
    does not exist on the page at all — live-confirmed (issue #840/#843)
    to be an ordinary consequence of the campaign's promotion goal being
    "max-clicks", NOT markup drift: the whole block mounts only under
    "max-conversions". In that state no counter can be linked (and
    ``--add-metrika-counter`` would fail), so pass ``--promotion-goal
    max-conversions`` in the same ``masters update`` call.

    ``SectionPresent: true`` with ``Count: 0`` is the genuinely
    counter-less case.

    Each entry carries the raw two-line tag ``Text`` plus the ``CounterId``
    and ``Domain`` parsed from it. ``Text`` is NOT the same shape as the
    autocomplete suggestion (the linked tag carries no label), so compare
    on ``CounterId`` — and pass that same ``CounterId`` straight to
    ``--add-metrika-counter``, which matches numeric ids exactly (#846).
    """
    from ..browser.masters import fetch_master_metrika_counters

    result = _with_session(
        ctx,
        headful,
        profile_dir,
        chrome_profile,
        lambda page: fetch_master_metrika_counters(page, campaign_id),
    )

    format_output(result, output_format, output)


@masters.group("audience")
def audience():
    """Read a Мастер кампаний campaign's "Аудитория" manual-targeting
    settings (browser-driven, no API)

    Мастер кампаний has no Yandex Direct API surface (see this module's own
    docstring), and this section lives only on the campaign's edit page
    (issue #681) — same reasoning as the ``targetactions`` group above.
    Read-only for now: writing gender/age/devices/interest-and-search-term
    tags is ``masters update --gender``/``--age-from``/``--age-to``/
    ``--device``/``--add-audience-tag``/``--remove-audience-tag``.
    """


@audience.command("get")
@click.argument("campaign_id", type=int)
@_masters_browser_options
@click.pass_context
@handle_api_errors
def audience_get(
    ctx, campaign_id, headful, profile_dir, chrome_profile, output_format, output
):
    """Get a Мастер кампаний campaign's current "Аудитория" settings

    Returns gender, age bounds, the interests-and-search-terms tag list (in
    0-based on-page order — use these positions with
    ``--remove-audience-tag``), and the selected device types. This section
    only exists on the page while the campaign's audience mode is "Настроить
    вручную" (the default); this command does not check or change that
    top-level mode.
    """
    from ..browser.masters import fetch_master_audience

    result = _with_session(
        ctx,
        headful,
        profile_dir,
        chrome_profile,
        lambda page: fetch_master_audience(page, campaign_id),
    )

    format_output(result, output_format, output)


@masters.command()
@click.argument("campaign_id", type=int, required=False)
@click.option(
    "--from-file",
    "from_file",
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help=(
        "JSONL plan file: one campaign to update per line, with the same "
        "typed fields as this command's own flags (PascalCase names). Every "
        "campaign is updated in ONE browser session. Batch mode requires "
        "--format json."
    ),
)
@click.option(
    "--masters-json",
    help=(
        "Same plan as --from-file, inline as a JSON array of campaign "
        "objects. Mutually exclusive with --from-file and CAMPAIGN_ID."
    ),
)
@click.option(
    "--moderation-statuses",
    is_flag=True,
    help=(
        "After each save, also read that campaign's CURRENT moderation "
        "statuses (batch mode only). Right after a save moderation has "
        "usually not run yet — a rejection can appear later, so this is a "
        "snapshot, NOT a final verdict."
    ),
)
@click.option(
    "--dry-run",
    is_flag=True,
    help=(
        "Validate the plan (including that local image/video files exist) and "
        "print what would be applied, without opening a browser."
    ),
)
@click.option(
    "--pacing-ms",
    type=click.IntRange(min=0),
    default=None,
    help=(
        "Pause between campaigns in a batch, in milliseconds (default: "
        f"{_BATCH_UPDATE_PACING_MS_DEFAULT}). Raise it if a long plan starts "
        "hitting session failures; 0 disables the pause."
    ),
)
@click.option(
    "--weekly-budget",
    type=int,
    help="Weekly budget in account currency (Недельный бюджет)",
)
@click.option(
    "--promotion-goal",
    type=click.Choice(sorted(_PROMOTION_GOAL_CHOICES)),
    help="Promotion goal (Цель продвижения)",
)
@click.option(
    "--goal-price",
    type=float,
    help=(
        "Target price for the promotion goal (Цена целевого действия / "
        "Цена перехода), in account currency. Only exists on the page "
        "when the campaign's promotion goal is (or is being set to via "
        "--promotion-goal in this same call) 'max-clicks' — under "
        "'max-conversions' the price is set per-goal in the 'Целевые "
        "действия' table instead, see --target-action-price."
    ),
)
@click.option(
    "--target-action-price",
    "target_action_prices",
    multiple=True,
    help=(
        "Set an EXISTING target action's (goal's) CPA price: \"goal_id="
        'price" where goal_id is the Yandex Metrika goal ID shown by '
        "`masters targetactions get`. Repeat for multiple goals. Only "
        "exists on the page when the campaign's promotion goal is (or is "
        "being set to via --promotion-goal in this same call) "
        "'max-conversions'; under 'max-clicks' the price is set once for "
        "the whole campaign via --goal-price instead. The goal must "
        "already be listed in the 'Целевые действия' table — to add a "
        "brand-new row use --add-target-action instead."
    ),
)
@click.option(
    "--add-target-action",
    "add_target_actions",
    multiple=True,
    help=(
        'Add a NEW target action (goal): "goal_id=price" where goal_id is '
        "the Yandex Metrika goal ID (a bare goal_id with no price is "
        "rejected — a newly added row's price is required, Yandex has no "
        "default for it). Repeat for multiple goals. The goal must belong "
        "to the campaign's linked Metrika counter and must NOT already be "
        "listed — Yandex's own picker only ever offers goals that aren't "
        "already rows; use --target-action-price to change an EXISTING "
        "row's price instead. Same 'max-conversions' promotion-goal gating "
        "as --target-action-price."
    ),
)
@click.option(
    "--remove-target-action",
    "remove_target_actions",
    multiple=True,
    help=(
        "Remove an EXISTING target action (goal) by its Yandex Metrika "
        "goal ID, as shown by `masters targetactions get`. Repeat for "
        "multiple goals. Same 'max-conversions' promotion-goal gating as "
        "--target-action-price."
    ),
)
@click.option(
    "--directs-helps/--no-directs-helps",
    "directs_helps",
    default=None,
    help="Auto-apply Yandex recommendations (Директ помогает)",
)
@click.option(
    "--name",
    help="New campaign name (Название кампании)",
)
@click.option(
    "--landing-url",
    help=(
        "New landing page URL (Ссылка на продвигаемую страницу). Replaces "
        "the field's WHOLE value. Pass an empty string ('') to clear the "
        "field entirely. Read-only while the campaign is ARCHIVED — resume "
        "it first via `masters resume`. See --tracking-params for the "
        "separate UTM query-string field."
    ),
)
@click.option(
    "--tracking-params",
    help=(
        "UTM query string for this campaign (UTM-метки и параметры URL), "
        "e.g. 'utm_source=yandex&utm_medium=cpc'. This is a SEPARATE field "
        "from --landing-url, under 'Дополнительные параметры' on the "
        "campaign edit page — it does not modify the landing page URL "
        "itself. Pass an empty string ('') to clear it."
    ),
)
@click.option(
    "--headline",
    "headlines",
    multiple=True,
    help=(
        'Replace an EXISTING headline variant: "N=text" where N is the '
        "1-based slot number (1-5). Repeat for multiple slots. Writing to "
        "an empty slot is refused — this only replaces variants that "
        "already exist, it does not add new ones. Other headline variants "
        "are left untouched."
    ),
)
@click.option(
    "--text",
    "texts",
    multiple=True,
    help=(
        'Replace an EXISTING ad-text variant: "N=text" where N is the '
        "1-based slot number (1-3). Repeat for multiple slots. Writing to "
        "an empty slot is refused — this only replaces variants that "
        "already exist, it does not add new ones. Other ad-text variants "
        "are left untouched."
    ),
)
@click.option(
    "--clear-headline",
    "clear_headlines",
    multiple=True,
    type=int,
    help=(
        "DELETE an EXISTING headline variant by its 1-based slot number "
        "(1-5). Repeat for multiple slots. A slot number already passed to "
        "--headline in the same call is refused — that would be a set and "
        "a delete on the same slot. Deleting an already-empty slot is "
        "refused too (there is nothing there to delete)."
    ),
)
@click.option(
    "--clear-text",
    "clear_texts",
    multiple=True,
    type=int,
    help=(
        "DELETE an EXISTING ad-text variant by its 1-based slot number "
        "(1-3). Repeat for multiple slots. A slot number already passed to "
        "--text in the same call is refused — that would be a set and a "
        "delete on the same slot. Deleting an already-empty slot is "
        "refused too (there is nothing there to delete)."
    ),
)
@click.option(
    "--image",
    "images",
    multiple=True,
    help=(
        'Replace an EXISTING image: "N=path" where N is the 1-based '
        "position of the image currently shown on the edit page (position "
        "count is whatever the campaign actually has — up to 5, and may be "
        "0 if the campaign has no images at all, in which case this "
        "refuses). Repeat for multiple positions. path must be a local "
        "PNG/JPEG/GIF file. Writing to a position beyond the campaign's "
        "current image count is refused — this only replaces images that "
        "already exist, it does not add new ones. NOTE: Yandex has no "
        "in-place image replacement — the image at position N is removed "
        "and the new one is appended to the END of the set, so the set's "
        "order changes (this has no effect on ad delivery: Yandex rotates "
        "images by performance regardless of position). Other images are "
        "left untouched."
    ),
)
@click.option(
    "--add-video",
    help=(
        "Upload a local video file, appending it to the 'Варианты видео' "
        "section (Yandex's own UI states a maximum of 2 videos per "
        "campaign, live-confirmed via --add-video-url's selection path). "
        "Refused if the campaign already has 2 videos. UNLIKE --image, "
        "this is a plain add, not a positional replacement — Yandex "
        "assigns the new video's URL, which is not known ahead of time. "
        "Mutually exclusive with --add-video-url. NOTE: this command's "
        "actual file-upload sequence (upload → poll for the new card → "
        "Save) has NOT been confirmed against the real Yandex UI, only "
        "the surrounding modal's DOM was observed live; see "
        "direct_cli/browser/masters.py's module comments above "
        "_VIDEOS_SLOT_COUNT for exactly what is/isn't confirmed. If the "
        "video you want is already in the account's video library (e.g. "
        "used on another campaign), prefer --add-video-url instead — that "
        "path is fully live-verified."
    ),
)
@click.option(
    "--add-video-url",
    help=(
        "Add a video the account has already uploaded to some campaign, "
        "by its exact URL (as shown by another campaign's edit page, or "
        "in this command's own JSON output under AddedVideo/AddedVideoUrl "
        "after a prior --add-video/--add-video-url call). Yandex keeps a "
        "single account-wide video library shared across all campaigns, "
        "not a per-campaign one. Selects it via the 'Варианты видео' "
        "modal's 'Ваши кампании' tab instead of uploading a new file — no "
        "asynchronous processing wait needed, since the video already "
        "exists server-side. Subject to the same 2-video cap as "
        "--add-video (live-confirmed: exceeding it disables the modal's "
        "Save button). Mutually exclusive with --add-video."
    ),
)
@click.option(
    "--remove-video",
    "remove_videos",
    multiple=True,
    help=(
        "Remove a video by its exact URL as shown on the edit page (repeat "
        "for multiple). There is no CLI command yet to list a campaign's "
        "current video URLs — inspect the edit page directly (e.g. "
        "--headful) to find them. Refused if the URL is not currently in "
        "the campaign's video set."
    ),
)
@click.option(
    "--gender",
    type=click.Choice(sorted(_GENDER_CHOICES)),
    help="Target gender (Пол)",
)
@click.option(
    "--age-from",
    type=click.Choice([str(v) for v in _AGE_FROM_CHOICES]),
    help="Minimum target age (от), one of the page's fixed age brackets",
)
@click.option(
    "--age-to",
    type=click.Choice(
        [str(v) for v in _AGE_TO_CHOICES if v is not None] + ["unlimited"]
    ),
    help=(
        "Maximum target age (до), one of the page's fixed age brackets, or "
        "'unlimited' for no upper bound (Без ограничений)"
    ),
)
@click.option(
    "--device",
    "devices",
    multiple=True,
    type=click.Choice(_DEVICE_OPTION_VALUES),
    help=(
        "Target device type (Устройства пользователей). Repeat to select "
        "multiple; passing this REPLACES the whole selection with exactly "
        "the device(s) given (at least one is required — Yandex has no "
        "'zero devices' state)."
    ),
)
@click.option(
    "--add-audience-tag",
    "add_audience_tags",
    multiple=True,
    help=(
        "Add a keyword or interest tag to 'Интересы и поисковые запросы' — "
        "the exact text of one of Yandex's own autocomplete suggestions for "
        "that text (repeat for multiple). Yandex resolves whether it's a "
        "search-term keyword or an interest category; a tag with no "
        "matching suggestion is refused."
    ),
)
@click.option(
    "--remove-audience-tag",
    "remove_audience_tags",
    multiple=True,
    type=int,
    help=(
        "Remove a tag from 'Интересы и поисковые запросы' by its CURRENT "
        "0-based position (see `masters audience get`). Repeat for multiple "
        "positions; positions refer to the list as it exists BEFORE this "
        "command runs, not after earlier removals in the same call."
    ),
)
@click.option(
    "--add-metrika-counter",
    "add_metrika_counters",
    multiple=True,
    help=(
        "Add a Yandex Metrika counter to 'Счетчики Яндекс Метрики' by its "
        "NUMERIC COUNTER ID, e.g. --add-metrika-counter 72112213 (repeat "
        "for multiple). The id is matched exactly against Yandex's own "
        "suggestion, so it is the spelling to prefer: it is what Metrika "
        "shows and what `masters counters get` reports as `CounterId`. The "
        "full suggestion line ('{label} • {domain/path} • {numeric counter "
        "id}') is also accepted verbatim. The section exists only under "
        "--promotion-goal max-conversions — pass that in the SAME call if "
        "the campaign is on max-clicks. A value with no matching "
        "suggestion is refused, and the error lists what Yandex offered."
    ),
)
@click.option(
    "--remove-metrika-counter",
    "remove_metrika_counters",
    multiple=True,
    type=int,
    help=(
        "Remove a counter from 'Счетчики Яндекс Метрики' by its CURRENT "
        "0-based position. There is no dedicated read command for this "
        "section yet — inspect current positions with --headful. Repeat "
        "for multiple positions; positions refer to the list as it exists "
        "BEFORE this command runs, not after earlier removals in the same "
        "call. NOT LIVE-VERIFIED — see --add-metrika-counter's help text."
    ),
)
@click.option(
    "--add-sitelink",
    "add_sitelinks",
    multiple=True,
    help=(
        'Add a quick link to "Быстрые ссылки": "Title|Href|Description" '
        "(repeat for multiple), e.g. "
        '"Об авторе|https://example.com/about|Узнайте больше о нас". All '
        "three parts are required and non-empty (NOT LIVE-VERIFIED whether "
        "Yandex's inline form actually requires a non-empty description — "
        "this CLI is conservative pending confirmation). Refused once the "
        "campaign already has the UI-stated maximum of 5 sitelinks."
    ),
)
@click.option(
    "--remove-sitelink",
    "remove_sitelinks",
    multiple=True,
    type=int,
    help=(
        "Remove a sitelink from 'Быстрые ссылки' by its CURRENT 0-based "
        "position. Repeat for multiple positions; positions refer to the "
        "list as it exists BEFORE this command runs, not after earlier "
        "removals in the same call."
    ),
)
@click.option(
    "--launch",
    is_flag=True,
    default=False,
    help=(
        "If CAMPAIGN_ID is currently a DRAFT, publish it while saving "
        "(default: keep it a DRAFT). Has no effect on a non-DRAFT campaign. "
        "To publish a DRAFT without changing any field, use "
        "'masters launch' instead."
    ),
)
@_masters_browser_options
@click.pass_context
@handle_api_errors
def update(
    ctx,
    campaign_id,
    from_file,
    masters_json,
    moderation_statuses,
    dry_run,
    pacing_ms,
    weekly_budget,
    promotion_goal,
    goal_price,
    target_action_prices,
    add_target_actions,
    remove_target_actions,
    directs_helps,
    name,
    landing_url,
    tracking_params,
    headlines,
    texts,
    clear_headlines,
    clear_texts,
    images,
    add_video,
    add_video_url,
    remove_videos,
    gender,
    age_from,
    age_to,
    devices,
    add_audience_tags,
    remove_audience_tags,
    add_metrika_counters,
    remove_metrika_counters,
    add_sitelinks,
    remove_sitelinks,
    launch,
    headful,
    profile_dir,
    chrome_profile,
    output_format,
    output,
):
    """Update settings of one or many Мастер кампаний campaigns

    Takes either a single CAMPAIGN_ID with typed flags, or a whole plan via
    ``--from-file``/``--masters-json`` (issue #834).

    \b
    Batch mode — one browser session for the WHOLE plan:
      direct masters update --from-file plan.jsonl
      direct masters update --masters-json '[{"CampaignId": 1, "Name": "x"}]'

    Each plan row is one campaign: a ``CampaignId`` plus at least one field,
    keyed in PascalCase (``Name``, ``LandingUrl``, ``Headlines``, ...) — the
    1:1 counterpart of this command's own flags, with slot numbers and
    positions 1-based exactly as in ``--headline "2=..."``. An unknown key is
    an error naming the row, never a silent skip. Every row is validated
    before the first save, so a typo in the last row cannot leave earlier
    campaigns already mutated; ``--dry-run`` stops there and prints the plan.

    Campaigns are updated one after another over a single browser session
    (that is the point — repeated re-entry, not the edit itself, is what
    failed live in issue #829), with a short pause between them. A campaign
    that fails is reported with an ``Error`` and does NOT stop the rest; the
    command exits non-zero afterwards. If the session goes stale mid-plan it
    is re-opened once and the run continues from the first campaign that was
    never saved — already-saved campaigns are never saved twice.

    Covers weekly budget, promotion goal (plus its target price), the
    "Директ помогает" auto-recommendations toggle, the campaign name,
    per-slot headline/ad-text variant replacement, and per-position image
    replacement. The edit page has a single whole-form save (no per-section
    save) — see ``direct_cli/browser/masters.py`` module docstring — so
    only the fields passed here are changed; every other on-page field
    keeps its current value.

    ``--goal-price`` (issue #696) sets the "Цель продвижения" block's
    target price — but that field only exists on the page when the
    campaign's promotion goal is 'max-clicks': under 'max-conversions' the
    price is per-goal in the separate "Целевые действия" table instead, see
    ``--target-action-price``. Passing ``--goal-price`` together with
    ``--promotion-goal max-conversions`` is therefore refused up front, and
    passing ``--goal-price`` alone (no ``--promotion-goal``) fails against a
    campaign whose CURRENT goal isn't already 'max-clicks' — the field
    genuinely is not on the page yet.

    ``--target-action-price`` (issue #707) is the 'max-conversions'
    counterpart: sets an EXISTING goal's CPA price in the "Целевые
    действия" table, keyed by the goal's Yandex Metrika id (see `masters
    targetactions get`). Only exists on the page under 'max-conversions' —
    passing it together with ``--promotion-goal max-clicks`` is refused up
    front, mirroring ``--goal-price``'s own guard. The goal must already be
    a row in the table.

    ``--add-target-action``/``--remove-target-action`` (issue #717) add/
    remove rows in that same table rather than only replacing an existing
    row's price — same 'max-conversions' gating as ``--target-action-price``.
    ``--add-target-action "goal_id=price"`` requires a price (Yandex has no
    default for a freshly added row) and the goal must belong to the
    campaign's linked Metrika counter and not already be listed.
    ``--remove-target-action "goal_id"`` requires the goal to already be
    listed. The same goal id cannot be passed to more than one of
    ``--target-action-price``/``--add-target-action``/
    ``--remove-target-action`` in the same call.

    ``--landing-url`` (issue #757) replaces the "Ссылка на продвигаемую
    страницу" field's WHOLE value; pass an empty string to clear it
    entirely. Read-only while the campaign is ARCHIVED — resume it first
    via `masters resume`.

    ``--tracking-params`` (issue #761) sets the SEPARATE "UTM-метки и
    параметры URL" field under "Дополнительные параметры" — the dedicated
    place for a campaign's UTM query string, independent of
    ``--landing-url``. Pass an empty string to clear it.

    ``--headline``/``--text``/``--image`` each replace ONE existing
    slot/position at a time rather than the whole list — unlike this CLI's
    usual list-field convention (e.g. ``campaigns update
    --negative-keywords``, which replaces the entire array). This is
    deliberate: Мастер кампаний has no API, variant sets can be large, and
    forcing every variant to be re-typed to fix one typo defeats the point
    of a partial update — see
    ``direct_cli/browser/masters.py::_set_repeating_value`` for the full
    rationale. ``--image`` additionally has NO in-place replacement at all
    on Yandex's side — see its own help text and
    ``direct_cli/browser/masters.py::_set_image`` for why the image set's
    order changes as a result. Later fields (sitelinks, Metrika
    counters/goals, budget adaptation) are tracked separately, see issue
    #648.

    ``--add-video``/``--remove-video`` (issue #648, Этап D / #788) manage the
    "Варианты видео" section — UNLIKE ``--image``, this is a plain
    add/remove pair rather than a positional point-replacement (Yandex's
    own UI caps this at 2 videos per campaign, and 2026-08-06 recon found
    the remove control lives outside any modal, directly on the edit
    page — see ``direct_cli/browser/masters.py::update_master``'s
    docstring for the full reasoning). ``--add-video`` takes a local file
    path and is refused once the campaign already has 2 videos.
    ``--remove-video`` takes the video's exact URL (repeat for multiple);
    there is no CLI command yet to list a campaign's current video URLs.
    The upload modal's own DOM (open, Save/Cancel, file input, accepted
    MIME types) is now CONFIRMED LIVE (2026-08-07, #788 follow-up) — see
    ``direct_cli/browser/masters.py``'s module comment above
    ``_VIDEOS_MODAL_SELECTOR`` for the corrections this made to PR #806's
    original guesses. **Still NOT LIVE-VERIFIED**: an actual file upload
    was never attempted (no rollback on this account), so the upload
    poll → Save sequence, and whether ``--remove-video``'s click commits
    immediately or needs the page's own Save, remain unconfirmed — see
    ``direct_cli/browser/masters.py``'s module comments above
    ``_VIDEOS_SLOT_COUNT`` for the exact confirmed-vs-assumed breakdown.

    ``--clear-headline``/``--clear-text`` (issue #786) DELETE an existing
    headline/ad-text variant by its 1-based slot number, the counterpart
    ``--headline``/``--text`` deliberately refuse (an empty replacement
    there is treated as a mistake, not a delete request — see their own
    help text). A slot number cannot be passed to both a set flag and its
    clear counterpart in the same call. Adding a brand-new variant beyond
    the page's fixed slot count (5 headlines / 3 texts) is not supported —
    Yandex's edit page has no "add another" control. Per-variant weights
    are also not supported: confirmed live, Мастер кампаний has no
    weight/priority UI at all for these slots.

    ``--gender``/``--age-from``/``--age-to``/``--device``/
    ``--add-audience-tag``/``--remove-audience-tag`` (issue #681) cover the
    "Аудитория" section's manual-targeting fields — see `masters audience
    get` to read a campaign's current values (including the tag list's
    0-based positions ``--remove-audience-tag`` expects). ``--device``
    REPLACES the whole device selection with exactly what's given (repeat
    for multiple); it does not add/remove individual device types. A tag
    passed to ``--add-audience-tag`` must be the exact text of one of
    Yandex's own autocomplete suggestions — Yandex decides whether it
    resolves to a search-term keyword or an interest category, and a tag
    with no matching suggestion is refused rather than added as free text.

    ``--add-metrika-counter``/``--remove-metrika-counter`` (issue #648)
    cover the "Счетчики Яндекс Метрики" section, mirroring
    ``--add-audience-tag``/``--remove-audience-tag`` above field-for-field.
    ``--add-metrika-counter`` takes the counter's NUMERIC ID (matched
    exactly against Yandex's own suggestion) or the full suggestion line;
    ``--remove-metrika-counter`` takes 0-based positions into the counter
    list as it exists BEFORE this command runs. The section only exists
    under ``--promotion-goal max-conversions``, and counters are applied
    BEFORE target actions (#844) so both can be set in one call.
    LIVE-VERIFIED through linking the counter on the page (#846); see
    ``direct_cli/browser/masters.py``'s ``_add_metrika_counter``.

    ``--add-sitelink``/``--remove-sitelink`` (issue #648, Этап C) cover the
    "Быстрые ссылки" section. ``--add-sitelink "Title|Href|Description"``
    appends a new card (repeat for multiple) — all three parts are
    required and non-empty, see the option's own help text for why this is
    stricter than the WSDL-API ``direct sitelinks add --sitelink`` command
    (a different feature entirely — see
    ``direct_cli/browser/masters.py`` module docstring). A significant
    part of this section's behaviour is NOT LIVE-VERIFIED — see
    ``direct_cli/browser/masters.py``'s ``_SITELINKS_EDITOR_TESTID`` module
    comment for specifics (in particular: how the inline edit form closes,
    and whether the real maximum is genuinely 5). ``--remove-sitelink``
    takes a 0-based position into the card list as it exists BEFORE this
    command runs, same convention as ``--remove-audience-tag``.

    A DRAFT campaign's edit page has no "Сохранить кампанию" button at all —
    only a save-as-draft/launch pair (issue #668). ``update`` saves it as a
    draft by default (keeping DRAFT status); pass ``--launch`` to publish it
    instead while saving. Has no effect on a non-DRAFT campaign. To publish a
    DRAFT without changing any field, use ``masters launch`` (issue #704)
    instead of passing ``--launch`` here with an unchanged field value.
    """
    from ..browser.masters import update_master

    modes_used = sum(
        value is not None for value in (campaign_id, from_file, masters_json)
    )
    if modes_used == 0:
        raise click.UsageError(
            "Provide exactly one of: CAMPAIGN_ID (single), --from-file (JSONL), "
            "or --masters-json (inline JSON array)."
        )
    if modes_used > 1:
        raise click.UsageError(
            "Provide exactly one of: CAMPAIGN_ID, --from-file, or "
            "--masters-json — they are mutually exclusive."
        )

    batch_mode = from_file is not None or masters_json is not None
    if batch_mode:
        # Keyed by the batch field name, so this stays in lockstep with
        # _UPDATE_FILE_FIELDS/_UPDATE_FILE_FIELD_FLAGS by NAME rather than by
        # argument order (a positional pairing would mislabel every flag after
        # an inserted field, and still look correct).
        direct_values = {
            "WeeklyBudget": weekly_budget,
            "PromotionGoal": promotion_goal,
            "GoalPrice": goal_price,
            "TargetActionPrices": target_action_prices,
            "AddTargetActions": add_target_actions,
            "RemoveTargetActionGoalIds": remove_target_actions,
            "DirectsHelps": directs_helps,
            "Name": name,
            "LandingUrl": landing_url,
            "TrackingParams": tracking_params,
            "Headlines": headlines,
            "Texts": texts,
            "ClearHeadlines": clear_headlines,
            "ClearTexts": clear_texts,
            "Images": images,
            "AddVideo": add_video,
            "AddVideoUrl": add_video_url,
            "RemoveVideos": remove_videos,
            "Gender": gender,
            "AgeFrom": age_from,
            "AgeTo": age_to,
            "Devices": devices,
            "AddAudienceTags": add_audience_tags,
            "RemoveAudienceTags": remove_audience_tags,
            "AddMetrikaCounters": add_metrika_counters,
            "RemoveMetrikaCounters": remove_metrika_counters,
            "AddSitelinks": add_sitelinks,
            "RemoveSitelinks": remove_sitelinks,
            "Launch": launch,
        }
        if any(value not in (None, False, (), "") for value in direct_values.values()):
            # Field values belong in the plan, not alongside it: a flag here
            # would apply to every row or to none, and both readings are
            # defensible -- so refuse instead of picking one silently.
            unsupported = ", ".join(
                _UPDATE_FILE_FIELD_FLAGS[key]
                for key, value in direct_values.items()
                if value not in (None, False, (), "")
            )
            raise click.UsageError(
                f"{unsupported} supported only with CAMPAIGN_ID single-item "
                "mode; put the field in the --from-file/--masters-json plan "
                "instead."
            )
        if output_format != "json":
            raise click.UsageError(
                "--format other than 'json' is not supported in batch mode "
                "(item-level results may include per-row Errors)."
            )
        rows = (
            _parse_update_file_rows(from_file)
            if from_file is not None
            else _parse_update_inline_rows(masters_json or "")
        )
        result = _run_update_file_batch(
            ctx,
            rows,
            headful=headful,
            profile_dir=profile_dir,
            chrome_profile=chrome_profile,
            moderation_statuses=moderation_statuses,
            dry_run=dry_run,
            pacing_ms=pacing_ms,
        )
        format_output(result, output_format, output)
        errors = [row for row in result if row.get("Error")]
        if errors:
            raise click.ClickException(
                f"Failed to update {len(errors)} of {len(rows)} campaign(s); "
                "see per-campaign results above."
            )
        return

    if moderation_statuses:
        raise click.UsageError(
            "--moderation-statuses is supported only with --from-file/"
            "--masters-json batch mode; use `masters get "
            "--moderation-statuses` for a single campaign."
        )
    if pacing_ms is not None:
        raise click.UsageError(
            "--pacing-ms paces the gap BETWEEN campaigns and is supported "
            "only with --from-file/--masters-json batch mode."
        )

    if (
        weekly_budget is None
        and promotion_goal is None
        and goal_price is None
        and not target_action_prices
        and not add_target_actions
        and not remove_target_actions
        and directs_helps is None
        and name is None
        and landing_url is None
        and tracking_params is None
        and not headlines
        and not texts
        and not clear_headlines
        and not clear_texts
        and not images
        and add_video is None
        and add_video_url is None
        and not remove_videos
        and gender is None
        and age_from is None
        and age_to is None
        and not devices
        and not add_audience_tags
        and not remove_audience_tags
        and not add_metrika_counters
        and not remove_metrika_counters
        and not add_sitelinks
        and not remove_sitelinks
    ):
        raise click.UsageError(
            "Provide at least one of --weekly-budget, --promotion-goal, "
            "--goal-price, --target-action-price, --add-target-action, "
            "--remove-target-action, --directs-helps/--no-directs-helps, "
            "--name, --landing-url, --tracking-params, --headline, --text, "
            "--clear-headline, --clear-text, --image, --add-video, "
            "--add-video-url, --remove-video, --gender, --age-from, "
            "--age-to, --device, "
            "--add-audience-tag, --remove-audience-tag, "
            "--add-metrika-counter, --remove-metrika-counter, "
            "--add-sitelink, --remove-sitelink."
        )

    if goal_price is not None and promotion_goal == "max-conversions":
        raise click.UsageError(
            "--goal-price has no effect under --promotion-goal "
            "max-conversions — that goal's price is set per-target-action "
            "via --target-action-price instead. --goal-price only applies "
            "to --promotion-goal max-clicks."
        )

    if (
        target_action_prices or add_target_actions or remove_target_actions
    ) and promotion_goal == "max-clicks":
        raise click.UsageError(
            "--target-action-price/--add-target-action/"
            "--remove-target-action have no effect under --promotion-goal "
            "max-clicks — that goal's price is set once for the whole "
            "campaign via --goal-price instead. They only apply to "
            "--promotion-goal max-conversions."
        )

    parsed_target_action_prices = _parse_target_action_price_options(
        target_action_prices
    )
    parsed_add_target_actions = _parse_add_target_action_options(add_target_actions)
    parsed_remove_target_actions = _parse_remove_target_action_options(
        remove_target_actions
    )

    _target_action_goal_ids_seen: "dict[int, str]" = {}
    for goal_id in parsed_target_action_prices:
        _target_action_goal_ids_seen[goal_id] = "--target-action-price"
    for goal_id in parsed_add_target_actions:
        if goal_id in _target_action_goal_ids_seen:
            raise click.UsageError(
                f"Goal {goal_id} was passed to both "
                f"{_target_action_goal_ids_seen[goal_id]} and "
                "--add-target-action — a goal can only be targeted by one "
                "of --target-action-price/--add-target-action/"
                "--remove-target-action in the same call."
            )
        _target_action_goal_ids_seen[goal_id] = "--add-target-action"
    for goal_id in parsed_remove_target_actions:
        if goal_id in _target_action_goal_ids_seen:
            raise click.UsageError(
                f"Goal {goal_id} was passed to both "
                f"{_target_action_goal_ids_seen[goal_id]} and "
                "--remove-target-action — a goal can only be targeted by "
                "one of --target-action-price/--add-target-action/"
                "--remove-target-action in the same call."
            )
        _target_action_goal_ids_seen[goal_id] = "--remove-target-action"

    # Slot counts come from the browser layer's own constants (imported here
    # rather than at module load, matching this module's other deferred
    # browser imports) so the CLI's bound can't drift from the page's.
    from ..browser.masters import (
        _HEADLINES_SLOT_COUNT,
        _IMAGES_MAX_COUNT,
        _TEXTS_SLOT_COUNT,
    )

    parsed_headlines = _parse_repeating_slot_options(
        "--headline", headlines, _HEADLINES_SLOT_COUNT
    )
    parsed_texts = _parse_repeating_slot_options("--text", texts, _TEXTS_SLOT_COUNT)
    parsed_clear_headlines = _parse_clear_slot_options(
        "--clear-headline", clear_headlines, _HEADLINES_SLOT_COUNT
    )
    parsed_clear_texts = _parse_clear_slot_options(
        "--clear-text", clear_texts, _TEXTS_SLOT_COUNT
    )
    _reject_overlapping_slots(
        parsed_headlines, parsed_clear_headlines, "--headline", "--clear-headline"
    )
    _reject_overlapping_slots(
        parsed_texts, parsed_clear_texts, "--text", "--clear-text"
    )
    parsed_images = _parse_repeating_slot_options(
        "--image",
        images,
        _IMAGES_MAX_COUNT,
        value_label="path",
        value_example="/path/to/image.jpg",
        empty_hint=(
            "which is not a valid image path. Removing an image without a "
            "replacement is not supported — pass a replacement file, or "
            "edit the campaign with --headful."
        ),
    )
    _validate_image_paths(parsed_images)
    if add_video is not None and add_video_url is not None:
        raise click.UsageError(
            "--add-video and --add-video-url are mutually exclusive — "
            "pass a local file path to upload a new video, or an existing "
            "video's URL to select it from the account's video library, "
            "not both."
        )
    if add_video is not None:
        _validate_video_path(add_video)

    parsed_age_from = int(age_from) if age_from is not None else None
    parsed_age_to = (
        None if age_to == "unlimited" else (int(age_to) if age_to is not None else None)
    )
    parsed_remove_audience_tags = _parse_remove_audience_tag_options(
        remove_audience_tags
    )
    parsed_remove_metrika_counters = _parse_remove_metrika_counter_options(
        remove_metrika_counters
    )
    parsed_add_sitelinks = _parse_add_sitelink_options(add_sitelinks)
    parsed_remove_sitelinks = _parse_remove_sitelink_options(remove_sitelinks)

    if dry_run:
        # Same report shape as a batch plan of one, so a caller can preview a
        # single command and a plan file with one reader (and so the batch
        # renderer stays the only place the PascalCase mapping lives).
        single_row = {
            "campaign_id": campaign_id,
            **{
                key: value
                for key, value in {
                    "weekly_budget": weekly_budget,
                    "promotion_goal": promotion_goal,
                    "goal_price": goal_price,
                    "target_action_prices": parsed_target_action_prices or None,
                    "add_target_actions": parsed_add_target_actions or None,
                    "remove_target_action_goal_ids": parsed_remove_target_actions
                    or None,
                    "directs_helps": directs_helps,
                    "name": name,
                    "landing_url": landing_url,
                    "tracking_params": tracking_params,
                    "headlines": parsed_headlines or None,
                    "texts": parsed_texts or None,
                    "clear_headlines": parsed_clear_headlines or None,
                    "clear_texts": parsed_clear_texts or None,
                    "images": parsed_images or None,
                    "add_video": add_video,
                    "add_video_url": add_video_url,
                    "remove_videos": list(remove_videos) or None,
                    "gender": gender,
                    "devices": set(devices) if devices else None,
                    "add_audience_tags": list(add_audience_tags) or None,
                    "remove_audience_tags": parsed_remove_audience_tags or None,
                    "add_metrika_counters": list(add_metrika_counters) or None,
                    "remove_metrika_counters": parsed_remove_metrika_counters or None,
                    "add_sitelinks": parsed_add_sitelinks or None,
                    "remove_sitelinks": parsed_remove_sitelinks or None,
                    "launch": launch or None,
                }.items()
                if value is not None
            },
        }
        # An explicitly requested bound is reported even when it resolves to
        # None ("unlimited"), matching what update_master would be told.
        if age_from is not None:
            single_row["age_from"] = parsed_age_from
        if age_to is not None:
            single_row["age_to"] = parsed_age_to
        format_output(_batch_row_report(single_row), output_format, output)
        return

    result = _with_session(
        ctx,
        headful,
        profile_dir,
        chrome_profile,
        lambda page: update_master(
            page,
            campaign_id,
            weekly_budget=weekly_budget,
            promotion_goal=promotion_goal,
            goal_price=goal_price,
            target_action_prices=parsed_target_action_prices,
            add_target_actions=parsed_add_target_actions,
            remove_target_action_goal_ids=parsed_remove_target_actions,
            directs_helps=directs_helps,
            name=name,
            landing_url=landing_url,
            tracking_params=tracking_params,
            headlines=parsed_headlines,
            texts=parsed_texts,
            clear_headlines=parsed_clear_headlines or None,
            clear_texts=parsed_clear_texts or None,
            images=parsed_images,
            add_video=add_video,
            add_video_url=add_video_url,
            remove_videos=list(remove_videos) or None,
            gender=gender,
            age_from=parsed_age_from,
            age_from_requested=age_from is not None,
            age_to=parsed_age_to,
            age_to_requested=age_to is not None,
            devices=set(devices) if devices else None,
            add_audience_tags=list(add_audience_tags) or None,
            remove_audience_tags=parsed_remove_audience_tags or None,
            add_metrika_counters=list(add_metrika_counters) or None,
            remove_metrika_counters=parsed_remove_metrika_counters or None,
            add_sitelinks=parsed_add_sitelinks or None,
            remove_sitelinks=parsed_remove_sitelinks or None,
            launch=launch,
        ),
    )

    format_output(result, output_format, output)


@masters.command()
@click.argument("campaign_ids")
@_masters_browser_options
@click.pass_context
@handle_api_errors
def resume(
    ctx,
    campaign_ids,
    headful,
    profile_dir,
    chrome_profile,
    output_format,
    output,
):
    """Resume one or more stopped Мастер кампаний by ID (comma-separated)

    Clicks the overview page's "Возобновить кампанию" button
    (``CampaignHeader.ActionButton.resume``, confirmed live — see
    ``direct_cli/browser/masters.py`` module docstring). Verifies the status
    actually changed before reporting success, re-clicking if the first
    click was a silent no-op (issue #766); idempotent if already active.
    An ARCHIVED campaign is unarchived to SUSPENDED first (issue #758).

    Every ID is attempted even if an earlier one fails, and each ID's
    outcome (the row, or its error) is reported — see ``_run_per_id``.
    """
    from ..browser.masters import resume_master

    ids = parse_ids(campaign_ids) or []

    _run_per_id(
        ctx,
        ids,
        resume_master,
        headful=headful,
        profile_dir=profile_dir,
        chrome_profile=chrome_profile,
        output_format=output_format,
        output=output,
        verb="resume",
    )


@masters.command()
@click.argument("campaign_ids")
@_masters_browser_options
@click.pass_context
@handle_api_errors
def launch(
    ctx,
    campaign_ids,
    headful,
    profile_dir,
    chrome_profile,
    output_format,
    output,
):
    """Publish one or more DRAFT Мастер кампаний by ID (comma-separated)

    Clicks the DRAFT edit page's "Запустить кампанию" button (issue #668's
    ``_click_draft_terminal_button``), sending the campaign to moderation.
    Verifies the status actually became MODERATION before reporting success
    (issue #704); idempotent no-op on a campaign that is not currently a
    DRAFT (there is no un-launch).

    Every ID is attempted even if an earlier one fails — irreversible, so a
    naive fail-fast loop would silently lose the report that earlier IDs
    already launched before a later one errored (mirrors ``archive``, issue
    #645 review). Each ID's outcome (the launched row, or its error) is
    reported; if any ID failed, the command exits non-zero after printing
    every outcome, never just the last error.
    """
    from ..browser.masters import launch_master

    ids = parse_ids(campaign_ids) or []

    _run_per_id(
        ctx,
        ids,
        launch_master,
        headful=headful,
        profile_dir=profile_dir,
        chrome_profile=chrome_profile,
        output_format=output_format,
        output=output,
        verb="launch",
    )


@masters.command()
@click.argument("campaign_ids")
@_masters_browser_options
@click.pass_context
@handle_api_errors
def archive(
    ctx,
    campaign_ids,
    headful,
    profile_dir,
    chrome_profile,
    output_format,
    output,
):
    """Archive one or more Мастер кампаний by ID (comma-separated)

    Мастер кампаний has no separate "delete" for a non-DRAFT campaign —
    archiving is the only destructive/lifecycle action beyond
    suspend/resume (issue #633 live recon: the overview page's own "⋮" menu
    has no "Удалить" item, only "Архивировать"). A DRAFT campaign is
    different — see `masters delete` (issue #782): the campaigns GRID's own
    row menu (a separate menu from the overview page's) does offer "Удалить"
    there; #633's original recon predates DRAFT support (#668) and evidently
    only checked non-DRAFT rows. Irreversible from this CLI:
    there is no `masters unarchive`. Clicks the overview page's "⋮" menu then
    "Архивировать" (both confirmed live via stable `data-testid` attributes —
    see `direct_cli/browser/masters.py` module docstring), and verifies via
    the campaigns grid that the status actually became ARCHIVED before
    reporting success; idempotent if already archived.

    Every ID is attempted even if an earlier one fails: since archiving is
    irreversible, a naive fail-fast loop would silently lose the report that
    earlier IDs were already archived in production before a later one
    errored (issue #645 review). Each ID's outcome (the archived row, or its
    error) is reported; if any ID failed, the command exits non-zero after
    printing every outcome, never just the last error.
    """
    from ..browser.masters import archive_master

    ids = parse_ids(campaign_ids) or []

    _run_per_id(
        ctx,
        ids,
        archive_master,
        headful=headful,
        profile_dir=profile_dir,
        chrome_profile=chrome_profile,
        output_format=output_format,
        output=output,
        verb="archive",
    )


@masters.command()
@click.argument("campaign_id", type=int)
@click.option(
    "--yes",
    is_flag=True,
    default=False,
    help="Skip the interactive confirmation prompt (required in "
    "non-interactive contexts, e.g. scripts/CI).",
)
@_masters_browser_options
@click.pass_context
@handle_api_errors
def delete(
    ctx,
    campaign_id,
    yes,
    headful,
    profile_dir,
    chrome_profile,
    output_format,
    output,
):
    """Permanently delete a DRAFT Мастер кампаний (issue #782)

    Мастер кампаний has no delete for any status other than DRAFT — see
    `masters archive`'s own docstring and issue #633; for a non-DRAFT
    campaign this refuses and points at `masters archive` instead.

    DRAFT is otherwise a one-way door in this CLI: its overview page has no
    "⋮" menu to archive from (issue #660), so a mistaken `masters add
    --draft` previously had no way back short of launching it (spending real
    money) just to gain access to archive. This command instead uses the
    campaigns GRID's own row menu, which does offer "Удалить" for a DRAFT
    row (live-confirmed 2026-08-06, issue #782).

    Irreversible, and unlike every other `masters` mutation Yandex itself
    shows NO confirmation dialog before deleting — the campaign is gone the
    instant the click lands. This command therefore always asks for its own
    confirmation before touching the browser: interactively by default, or
    pass --yes to skip the prompt in a non-interactive context (the prompt
    itself would otherwise hang forever with no TTY to answer it).
    """
    if not yes:
        if not _stdin_is_interactive():
            raise click.UsageError(
                f"Deleting campaign {campaign_id} needs confirmation, but "
                "no terminal is attached to prompt for it. Pass --yes to "
                "confirm non-interactively."
            )
        if not click.confirm(
            f"Permanently delete DRAFT campaign {campaign_id}? This cannot "
            "be undone."
        ):
            raise click.Abort()

    from ..browser.masters import delete_master

    result = _with_session(
        ctx,
        headful,
        profile_dir,
        chrome_profile,
        lambda page: delete_master(page, campaign_id),
    )

    format_output(result, output_format, output)


@masters.command()
@click.argument("campaign_id", type=int)
@click.option(
    "--launch/--draft",
    "launch",
    default=False,
    help="Launch the clone immediately (Запустить кампанию) instead of "
    "saving it as a draft (Сохранить как черновик, the default)",
)
@_masters_browser_options
@click.pass_context
@handle_api_errors
def copy(
    ctx,
    campaign_id,
    launch,
    headful,
    profile_dir,
    chrome_profile,
    output_format,
    output,
):
    """Clone an existing Мастер кампаний by ID (Клонировать)

    Mirrors the web UI's overview-page "⋮" menu → "Клонировать": Yandex
    pre-fills a new campaign from the source's headlines, texts, images,
    region, budget, and everything else — including the display region
    verbatim, which sidesteps the text-matching issues `masters add
    --region`/`--region-id` can hit (issues #652/#656/#657). Nothing on the
    copy is renamed or edited beyond what Yandex itself does (it appends
    " — N" to the name) — use `masters update` afterwards for any further
    changes.

    NOT idempotent: running this twice creates a SECOND copy, not an update
    to the first — there is no sandbox and no rollback for Мастер кампаний
    mutations.

    By default the copy is saved as a draft (--draft) without going live.
    Pass --launch to launch it immediately in production instead.
    """
    from ..browser.masters import copy_master

    result = _with_session(
        ctx,
        headful,
        profile_dir,
        chrome_profile,
        lambda page: copy_master(page, campaign_id, launch=launch),
    )

    format_output(result, output_format, output)


def _resolve_region_ids(
    ctx: click.Context, region_ids: "tuple[int, ...]"
) -> "list[tuple[str, int]]":
    """Resolve RegionId values to Yandex's canonical GeoRegionName via the
    GeoRegions dictionary — the exact text the Мастер кампаний region widget
    accepts, so callers don't have to guess Yandex's own wording (issue #652).

    Returns ``(name, region_id)`` pairs, not bare names (issue #657): the
    resolved RegionId travels alongside its name all the way into
    ``_set_region``, which checks it against the DOM node it actually
    clicked (``id="region-node-<RegionId>"``) rather than trusting an
    exact-text label match alone — text match only proves the right NAME was
    clicked, not the right underlying region, since GeoRegions names are not
    globally unique (see the ambiguity check below).

    Unlike the rest of this group (see module docstring — masters needs no
    Yandex Direct API credentials), this one lookup does require valid API
    credentials, resolved the same way as any other command: it is only
    reached when the caller actually passes ``--region-id``.

    The lookup is pinned to ``language="ru"`` (issue #775). It used to go
    through ``client_from_ctx``, which passes no ``language`` at all — and
    the vendored client omits the ``Accept-Language`` header entirely when
    it is ``None`` (``_vendor/tapi_yandex_direct/tapi_yandex_direct.py``),
    leaving the locale to Yandex. In practice Yandex answered in English,
    resolving 213 to "Moscow" — a name the Russian-language Мастер кампаний
    region widget cannot match, and one Yandex's own ``ExactNames`` lookup
    does not round-trip either.
    """
    if not region_ids:
        return []
    client = create_client(
        token=ctx.obj.get("token"),
        login=ctx.obj.get("login"),
        sandbox=ctx.obj.get("sandbox"),
        language="ru",
    )
    body = {
        "method": "getGeoRegions",
        "params": {
            "FieldNames": ["GeoRegionId", "GeoRegionName"],
            "SelectionCriteria": {"RegionIds": list(region_ids)},
        },
    }
    result = client.dictionaries().post(data=body)
    found = {
        item["GeoRegionId"]: item["GeoRegionName"]
        for item in (result.data["result"] or {}).get("GeoRegions") or []
    }
    missing = [rid for rid in region_ids if rid not in found]
    if missing:
        raise click.UsageError(
            "Unknown --region-id value(s): "
            f"{', '.join(str(m) for m in missing)} — check `direct "
            "dictionaries get-geo-regions` for valid IDs."
        )

    # Yandex's GeoRegions names are not globally unique (distinct IDs under
    # different parents can share a name, e.g. several "Сосновка" entries).
    # Issue #657: `_set_region` no longer trusts an exact-text label match
    # alone — it now confirms the clicked checkbox's own
    # ``id="region-node-<RegionId>"`` equals the requested RegionId, so an
    # ambiguous name can no longer silently select the WRONG region live.
    # This pre-flight check stays as defense in depth: it fails fast with a
    # clear API-level error before a browser is even opened, rather than
    # deferring to `_set_region`'s harder-to-diagnose in-page identity
    # mismatch. Look up every GeoRegions entry sharing one of the resolved
    # names and refuse rather than guess if any name has more than one
    # distinct owning RegionId.
    #
    # The criterion is `Name` (substring search), NOT `ExactNames`. Confirmed
    # live 2026-08-06 (issue #775): `ExactNames` returns **no rows at all**,
    # for any spelling, even for a region that demonstrably exists —
    # `ExactNames["Москва"]` yields `result == {}` while `RegionIds[213]`
    # resolves to exactly that name. Built on `ExactNames`, this pre-flight
    # could therefore never fire: every name looked "unchecked", so the
    # check was dead code that only produced a warning on every ordinary run.
    # `Name` does return rows and does surface real ambiguity (measured: 97
    # distinct RegionIds named "Сосновка"), so exact matches are filtered
    # client-side from its substring hits.
    #
    # `Name` takes a single string, not a list, so this is one request per
    # distinct name — in practice one, since `--region-id` is rarely repeated.
    resolved = [found[rid] for rid in region_ids]
    name_owners = {}
    for name in sorted(set(resolved)):
        name_check = client.dictionaries().post(
            data={
                "method": "getGeoRegions",
                "params": {
                    "FieldNames": ["GeoRegionId", "GeoRegionName"],
                    "SelectionCriteria": {"Name": name},
                },
            }
        )
        # Yandex omits the `GeoRegions` key entirely (``result == {}``) when
        # nothing matches — it does NOT return an empty list. Indexing the key
        # unconditionally turned every `--region-id` run into a bare
        # ``KeyError: 'GeoRegions'`` before a browser was ever opened (#775).
        for item in (name_check.data["result"] or {}).get("GeoRegions") or []:
            if item["GeoRegionName"] == name:
                name_owners.setdefault(name, set()).add(item["GeoRegionId"])

    # A name with no rows is NOT reported: `Name` legitimately returns nothing
    # for top-level regions (confirmed live — `Name="Москва"` matches only
    # "Новая Москва"/"Менеуз-Москва", never Москва itself), so warning here
    # would fire on the most common `--region-id` values and train the user to
    # ignore it. Absence of rows means "could not check", and the real
    # guarantee is downstream anyway: `_set_region` confirms the clicked
    # node's ``id="region-node-<RegionId>"`` matches the requested RegionId
    # and refuses before any save click.
    ambiguous = sorted(
        {name for name in resolved if len(name_owners.get(name, ())) > 1}
    )
    if ambiguous:
        raise click.UsageError(
            "--region-id resolved to ambiguous region name(s): "
            f"{', '.join(ambiguous)} — multiple RegionIds share this name "
            "in Yandex's GeoRegions dictionary, so the region widget cannot "
            "be matched reliably. Use --region with the fully qualified "
            "text instead."
        )
    return list(zip(resolved, region_ids))


@masters.command()
@click.argument("url")
@click.option(
    "--headline",
    "headlines",
    multiple=True,
    required=True,
    help="Ad headline variant (Варианты заголовков) — repeat for multiple",
)
@click.option(
    "--text",
    "texts",
    multiple=True,
    required=True,
    help="Ad text variant (Варианты текстов объявлений) — repeat for multiple",
)
@click.option(
    "--region",
    "regions",
    multiple=True,
    help="Display region (Регион показов) by exact Yandex wording — repeat "
    "for multiple. At least one of --region/--region-id is required.",
)
@click.option(
    "--region-id",
    "region_ids",
    multiple=True,
    type=int,
    help="Display region by RegionId (GeoRegions dictionary) — repeat for "
    "multiple, resolved to Yandex's canonical region name via `direct "
    "dictionaries get-geo-regions`. Requires Yandex Direct API credentials "
    "(unlike the rest of `masters`). Combines with --region.",
)
@click.option(
    "--add-target-action",
    "add_target_actions",
    multiple=True,
    required=True,
    help=(
        'Conversion goal to optimize for: "goal_id=price" where goal_id is '
        "the Yandex Metrika goal ID and price is its CPA in account "
        "currency. Repeat for multiple goals. REQUIRED — Yandex's create "
        "form silently refuses to submit without at least one goal. The "
        "goal must belong to the Metrika counter Yandex auto-discovers "
        "from the landing page's domain, so a domain with no counter "
        "installed cannot be used. Same flag name and syntax as `masters "
        "update --add-target-action`."
    ),
)
@click.option(
    "--weekly-budget",
    type=int,
    required=True,
    help=(
        "Weekly budget in account currency (Недельный бюджет). REQUIRED "
        "(issue #796) — Yandex's create form silently refuses to submit "
        "without one, the same silent-rejection shape as the target-action "
        "goal requirement above."
    ),
)
@click.option(
    "--draft/--launch",
    "draft",
    default=False,
    help="Save as a draft (Сохранить как черновик) instead of launching "
    "immediately (Запустить кампанию, the default)",
)
@_masters_browser_options
@click.pass_context
@handle_api_errors
def add(
    ctx,
    url,
    headlines,
    texts,
    regions,
    region_ids,
    add_target_actions,
    weekly_budget,
    draft,
    headful,
    profile_dir,
    chrome_profile,
    output_format,
    output,
):
    """Create a new Мастер кампаний ("Конверсии и трафик" type)

    NOT idempotent: running this twice with the same arguments creates a
    SECOND campaign, not an update to the first — Мастер кампаний has no
    API-level duplicate detection the way `campaigns add` does. There is no
    sandbox and no rollback for Мастер кампаний mutations (issue #632) —
    double check --region/--region-id/--headline/--text before running this
    for real.

    --headline/--text are required even though Yandex's own wizard can
    auto-generate them by scanning the landing page: this command refuses
    to silently publish AI-written ad copy you never reviewed. If you want
    the AI-suggested text, open the wizard once in a browser, copy what it
    proposes, and pass it back explicitly.

    At least one of --region/--region-id is required. --region-id is
    resolved to Yandex's canonical region name via the GeoRegions dictionary
    (issue #652) — use it instead of --region to avoid guessing the exact
    wording the region widget expects; it requires Yandex Direct API
    credentials, unlike the rest of this command.

    --add-target-action is required (issue #777): Yandex's create form
    refuses to submit without at least one conversion goal, and refuses
    SILENTLY — both terminal buttons stay visible and enabled in the
    rejected state, so a goal-less run could only ever surface as an
    unexplained timeout. It takes the same "goal_id=price" syntax as
    `masters update --add-target-action`.

    --weekly-budget is required (issue #796): the SAME silent-rejection
    shape as the goal requirement above — Yandex's create form refuses to
    submit without a weekly budget, with no visible error until AFTER a
    submit attempt (a `[data-testid="BudgetWithSuggest.ErrorMessage"]`
    element reading "Не задан недельный бюджет" only appears in the DOM
    post-click), so an unset-budget run previously surfaced only as an
    unexplained redirect timeout with no campaign ever created.

    By default the campaign is launched immediately (--launch). Pass
    --draft to save it as a draft instead (Сохранить как черновик) without
    going live.
    """
    from ..browser.masters import create_master

    if not regions and not region_ids:
        raise click.UsageError("At least one of --region/--region-id is required.")

    parsed_target_actions = _parse_add_target_action_options(add_target_actions)

    # (name, region_id) pairs — plain --region text has no known RegionId
    # (region_id=None), so `_set_region` can only verify it by exact-text
    # label match; --region-id-resolved entries carry their RegionId through
    # so `_set_region` can additionally confirm DOM node identity (#657).
    all_regions = [(region, None) for region in regions] + _resolve_region_ids(
        ctx, region_ids
    )

    result = _with_session(
        ctx,
        headful,
        profile_dir,
        chrome_profile,
        lambda page: create_master(
            page,
            url,
            headlines=list(headlines),
            texts=list(texts),
            regions=all_regions,
            target_actions=parsed_target_actions,
            weekly_budget=weekly_budget,
            launch=not draft,
        ),
    )

    format_output(result, output_format, output)
