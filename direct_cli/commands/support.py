"""
``direct support`` — переписка со службой поддержки (issue #897).

Browser-backed, like ``direct masters`` and ``direct history``: Yandex Direct's
API has no support surface. The chat in the Direct UI is a Yandex Messenger
widget, and this group reads and writes the same private chat through the
saved browser session (see ``direct_cli/browser/support.py`` for the recon and
``direct_cli/_support_chat.py`` for how conversations are derived — the chat is
one continuous thread with no ticket ids, so ids are message sequence numbers).

The session-resolution stack (``_with_session`` and ``--headful``) is imported
from ``commands/masters.py`` rather than duplicated, exactly as ``history``
does. There is no ``--login``/agency support: the chat belongs to the
logged-in browser account.
"""

import datetime

import click

from ..output import format_output, handle_api_errors
from .masters import _masters_browser_options, _stdin_is_interactive, _with_session


@click.group()
def support():
    """Переписка со службой поддержки (support chat) — browser-only, no API"""


def _confirm_or_abort(yes: bool, action: str, question: str) -> None:
    """Gate a real, irreversible chat action behind a confirmation."""
    if yes:
        return
    if not _stdin_is_interactive():
        raise click.UsageError(
            f"{action} needs confirmation, but no terminal is attached to "
            "prompt for it. Pass --yes to confirm non-interactively."
        )
    if not click.confirm(question):
        raise click.Abort()


@support.command(name="list")
@click.option(
    "--limit",
    type=int,
    default=10,
    show_default=True,
    help="Maximum number of conversations to return (newest first)",
)
@_masters_browser_options
@click.pass_context
@handle_api_errors
def list_conversations(
    ctx, limit, headful, profile_dir, chrome_profile, output_format, output
):
    """List the conversations with Yandex Direct support

    The support chat is one continuous thread without ticket numbers, so the
    conversations are inferred: one ends when you rate the support's work
    (`support rate`) or the bot closes the request for lack of an answer
    ("Напишите нам, если вопрос ещё актуален"), and your next message starts
    the next one. A low rating does not end it, and a request that was
    neither rated nor closed ends after two days of support silence. The id
    is the sequence number of the conversation's first message — pass it to
    `support get`.

    Each row has id, started, updated, status (open/closed), messages and a
    preview of what you asked.
    """
    if limit <= 0:
        raise click.UsageError("--limit must be a positive integer")

    from ..browser.support import fetch_support_threads

    today = datetime.date.today()
    result = _with_session(
        ctx,
        headful,
        profile_dir,
        chrome_profile,
        lambda page: fetch_support_threads(page, limit=limit, today=today),
    )

    format_output(result, output_format, output)


@support.command(name="get")
@click.argument("conversation_id", type=int)
@_masters_browser_options
@click.pass_context
@handle_api_errors
def get(
    ctx, conversation_id, headful, profile_dir, chrome_profile, output_format, output
):
    """Read one conversation with support, oldest message first

    CONVERSATION_ID is the id from `support list`. Each message has id,
    from (me or support), date, time and text; attachments show up as media
    and links, and the answer options of a bot message as buttons.
    """
    from ..browser.support import fetch_support_thread

    today = datetime.date.today()
    result = _with_session(
        ctx,
        headful,
        profile_dir,
        chrome_profile,
        lambda page: fetch_support_thread(page, conversation_id, today=today),
    )

    format_output(result, output_format, output)


@support.command(name="send")
@click.option(
    "--message",
    required=True,
    help="Text to send to Yandex Direct support",
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
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
def send(
    ctx,
    message,
    dry_run,
    yes,
    headful,
    profile_dir,
    chrome_profile,
    output_format,
    output,
):
    """Send a message to Yandex Direct support

    Types the text into the support chat and presses Enter, but only after
    the input field reads back as exactly that text (a leftover draft stops
    it: nothing is sent). The message goes to the support team and cannot be
    recalled, and a second run sends a second message — it is never retried,
    and if delivery cannot be confirmed the error says so. Writing after a
    closed conversation starts a new one.

    Always asks for confirmation before touching the browser: interactively
    by default, or pass --yes in a non-interactive context. --dry-run only
    shows what would be sent.
    """
    text = message.strip()
    if not text:
        raise click.UsageError("--message must not be empty")

    from ..browser.support import chat_url, send_support_message

    if dry_run:
        format_output({"chat": chat_url(), "message": text}, output_format, output)
        return

    _confirm_or_abort(
        yes,
        "Sending a message to Yandex Direct support",
        "Send this message to Yandex Direct support? It cannot be recalled.",
    )

    result = _with_session(
        ctx,
        headful,
        profile_dir,
        chrome_profile,
        lambda page: send_support_message(page, text),
    )

    format_output(result, output_format, output)


@support.command(name="rate")
@click.argument("rating", type=click.IntRange(1, 5))
@click.option("--dry-run", is_flag=True, help="Show what would be pressed")
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
def rate(
    ctx,
    rating,
    dry_run,
    yes,
    headful,
    profile_dir,
    chrome_profile,
    output_format,
    output,
):
    """Rate the support's work: press a button of the bot's rating request

    RATING is 1 (worst) to 5 (best). It answers the bot's "Хотим убедиться,
    что помогли. Оцените, пожалуйста, нашу работу." request by pressing that
    button in the chat. Only the newest message counts: if it is not such a
    request (it never came, or it was already answered), nothing is pressed.

    A rating cannot be changed and ends the conversation; a low rating makes
    the bot ask what went wrong, and the dialog goes on (answer it with
    `support send`). It is never retried, and if the rating cannot be
    confirmed the error says so.

    Always asks for confirmation before touching the browser: interactively
    by default, or pass --yes in a non-interactive context. --dry-run only
    shows what would be pressed.
    """
    from ..browser.support import chat_url, rate_support

    if dry_run:
        format_output({"chat": chat_url(), "rating": rating}, output_format, output)
        return

    _confirm_or_abort(
        yes,
        "Rating Yandex Direct support",
        f"Rate Yandex Direct support {rating}/5? It cannot be changed.",
    )

    today = datetime.date.today()
    result = _with_session(
        ctx,
        headful,
        profile_dir,
        chrome_profile,
        lambda page: rate_support(page, rating, today=today),
    )

    format_output(result, output_format, output)
