"""
API client wrapper for Direct CLI
"""

import random
import sys
import time
from typing import Optional, Dict, Any, List, Callable

import click

from direct_cli._vendor.tapi_yandex_direct import YandexDirect
from direct_cli._vendor.tapi_yandex_direct import exceptions as tapi_exceptions
from direct_cli._vendor.tapi_yandex_direct.v4 import YandexDirectV4Live
from .auth import get_credentials
from .output import print_warning_stderr


def create_client(
    token: Optional[str] = None,
    login: Optional[str] = None,
    profile: Optional[str] = None,
    sandbox: bool = False,
    op_token_ref: Optional[str] = None,
    op_login_ref: Optional[str] = None,
    processing_mode: str = "auto",
    return_money_in_micros: bool = False,
    skip_report_header: bool = True,
    skip_column_header: bool = False,
    skip_report_summary: bool = True,
    language: Optional[str] = None,
) -> YandexDirect:
    """
    Create YandexDirect client

    Args:
        token: API access token
        login: Client login (for agency accounts)
        profile: Credential profile name
        sandbox: Use sandbox API
        op_token_ref: 1Password secret reference for token
        op_login_ref: 1Password secret reference for login
        processing_mode: Report processing mode (auto/online/offline)
        return_money_in_micros: Return monetary values in micros
        skip_report_header: Omit report header row
        skip_column_header: Omit column header row
        skip_report_summary: Omit report summary row
        language: Accept-Language for report (ru/en)

    Returns:
        YandexDirect client instance
    """
    final_token, final_login = get_credentials(
        token,
        login,
        profile=profile,
        op_token_ref=op_token_ref,
        op_login_ref=op_login_ref,
    )

    return YandexDirect(
        access_token=final_token,
        login=final_login,
        is_sandbox=sandbox,
        retry_if_exceeded_limit=True,
        retries_if_server_error=5,
        # Report settings
        processing_mode=processing_mode,
        wait_report=True,
        return_money_in_micros=return_money_in_micros,
        skip_report_header=skip_report_header,
        skip_column_header=skip_column_header,
        skip_report_summary=skip_report_summary,
        language=language,
    )


def client_from_ctx(ctx, create_client_fn) -> YandexDirect:
    """Build a YandexDirect client from the standard CLI context.

    ``create_client_fn`` is the calling module's own ``create_client`` symbol,
    so test patches on ``direct_cli.commands.<module>.create_client`` keep
    intercepting the call and existing
    ``assert_called_once_with(token=..., login=..., sandbox=...)`` assertions
    stay valid.

    Args:
        ctx: Click context whose ``obj`` carries ``token``/``login``/``sandbox``
        create_client_fn: the caller's ``create_client`` (passed for patchability)

    Returns:
        YandexDirect client instance
    """
    return create_client_fn(
        token=ctx.obj.get("token"),
        login=ctx.obj.get("login"),
        sandbox=ctx.obj.get("sandbox"),
    )


def resolve_module_create_client(module_name: str, fallback):
    """Return a command module's *current* ``create_client``, for patchability.

    The command factories (:mod:`direct_cli.commands._get`, and eventually the
    lifecycle factory) capture ``create_client`` as a closure value at import
    time. That pins the original function and would bypass a later
    ``patch.object("direct_cli.commands.<module>", "create_client", ...)`` — the
    patchability contract that unit tests and the coverage wire-payload capture
    (``scripts/build_api_coverage_report.py``) rely on. Re-reading the attribute
    from the live module at call time restores it. *fallback* is returned if the
    module is somehow absent or lacks the attribute (it never should for a
    registered command).
    """
    module = sys.modules.get(module_name)
    if module is None:
        return fallback
    return getattr(module, "create_client", fallback)


def create_v4_client(
    token: Optional[str] = None,
    login: Optional[str] = None,
    profile: Optional[str] = None,
    sandbox: bool = False,
    op_token_ref: Optional[str] = None,
    op_login_ref: Optional[str] = None,
    bw_token_ref: Optional[str] = None,
    bw_login_ref: Optional[str] = None,
    language: Optional[str] = None,
    retry_if_exceeded_limit: bool = True,
    retries_if_server_error: int = 5,
    finance_token: Optional[str] = None,
    operation_num: Optional[int] = None,
) -> YandexDirectV4Live:
    """
    Create YandexDirect v4 Live client.

    Args:
        token: API access token
        login: Client login (for agency accounts)
        profile: Credential profile name
        sandbox: Use sandbox API
        op_token_ref: 1Password secret reference for token
        op_login_ref: 1Password secret reference for login
        bw_token_ref: Bitwarden item name/ID for token
        bw_login_ref: Bitwarden item name/ID for login
        language: API locale
        retry_if_exceeded_limit: Retry when the API limit is exceeded
        retries_if_server_error: Number of retries for server errors
        finance_token: Financial token for v4 Live finance methods
        operation_num: Financial operation number for v4 Live finance methods

    Returns:
        YandexDirect v4 Live client instance
    """
    final_token, final_login = get_credentials(
        token,
        login,
        profile=profile,
        op_token_ref=op_token_ref,
        op_login_ref=op_login_ref,
        bw_token_ref=bw_token_ref,
        bw_login_ref=bw_login_ref,
    )

    return YandexDirectV4Live(
        access_token=final_token,
        login=final_login,
        is_sandbox=sandbox,
        language=language or "en",
        retry_if_exceeded_limit=retry_if_exceeded_limit,
        retries_if_server_error=retries_if_server_error,
        finance_token=finance_token,
        operation_num=operation_num,
    )


def fetch_all_pages(
    client: YandexDirect,
    resource_name: str,
    method: str = "get",
    params: Dict[str, Any] = None,
    field_names: Optional[List[str]] = None,
    progress: bool = False,
) -> List[Dict[str, Any]]:
    """
    Fetch all pages of results

    Args:
        client: YandexDirect client
        resource_name: Resource name (e.g., 'campaigns', 'adgroups')
        method: API method ('get')
        params: Request params
        field_names: Field names to include
        progress: Show progress bar

    Returns:
        List of all items from all pages
    """
    if params is None:
        params = {}

    body = {
        "method": method,
        "params": params,
    }

    if field_names:
        body["params"]["FieldNames"] = field_names

    resource = getattr(client, resource_name)()
    result = resource.post(data=body)

    # Get items from first page
    items = result().extract()

    # Check if there are more pages
    if hasattr(result, "iter_items") and callable(result().iter_items):
        all_items = []

        # Use iter_items for pagination
        for item in result().iter_items():
            all_items.append(item)

        return all_items

    return items if isinstance(items, list) else [items]


# Error 56 = "Exceeded limit of method requests" — the per-method quota
# ("This method can't be requested more than 1 times in 10 seconds"). Several
# `direct` CLI / MCP sessions sharing one account trip each other's window,
# so the transport retries on 56 with exponential backoff + jitter (#918).
# The vendored client has retry branches for 56 in ``retry_request``, but they
# read the code from ``error.code`` while Yandex v5 payloads carry
# ``error.error_code`` — those branches never fire, which is why the CLI used
# to die on the first 56 with no retries at all.
ERROR_56_ATTEMPTS = 5
ERROR_56_BASE_DELAY = 10.0
# Each retry waits base * 2**(attempt-1) seconds plus up to +50% jitter.
ERROR_56_JITTER = 0.5


def _error_56_delay(attempt: int, base_delay: float = ERROR_56_BASE_DELAY) -> float:
    """Exponential backoff for the Nth failed attempt (1-based), with jitter."""
    return base_delay * 2 ** (attempt - 1) + random.uniform(
        0, base_delay * ERROR_56_JITTER
    )


def post_with_retry(
    resource,
    *,
    data,
    attempts: int = ERROR_56_ATTEMPTS,
    base_delay: float = ERROR_56_BASE_DELAY,
    sleep: Optional[Callable[[float], None]] = None,
) -> Any:
    """POST ``data`` on ``resource``, retrying API error 56 with backoff (#918).

    Error 56 is the per-method quota (1 request / 10 seconds): with several
    clients sharing one account, an immediate re-request keeps losing the
    window, so each retry waits ``base_delay * 2**(attempt-1)`` seconds plus
    jitter. Every other error — including the sibling limit codes 53/152/506/
    9000 — propagates on the first occurrence, unchanged. After ``attempts``
    failures a ``click.ClickException`` reports the original error together
    with the likely cause (another client/session consuming the same
    account's method limit).

    ``sleep`` is injectable so tests never wait real time; production uses
    :func:`time.sleep`.
    """
    sleep_fn = sleep or time.sleep
    for attempt in range(1, attempts + 1):
        try:
            return resource.post(data=data)
        except tapi_exceptions.YandexDirectClientError as exc:
            if getattr(exc, "error_code", None) != 56:
                raise
            if attempt >= attempts:
                # The next backoff step is what this client would have waited,
                # so it is the honest "wait N sec" advice (#920). Live evidence
                # from #920: a persistent 56 can outlast minutes-long waits
                # with no other client running — a stuck server-side limit —
                # so the message says so instead of blaming the account only.
                next_wait = round(_error_56_delay(attempts, base_delay))
                raise click.ClickException(
                    "API error 56 persisted after {} attempts: this method "
                    "allows only 1 request per 10 seconds, and another client "
                    "or session working with the same Yandex Direct account is "
                    "likely consuming that limit. Wait at least {}s before the "
                    "next attempt; if no other client is running and the error "
                    "still persists, the limit is stuck on the API side — "
                    "retry later. Last error: {}".format(attempts, next_wait, exc)
                ) from exc
            delay = _error_56_delay(attempt, base_delay)
            print_warning_stderr(
                "attempt {}/{} failed with error 56 (1 request per 10 "
                "seconds); retrying in {:.0f}s".format(attempt, attempts, delay)
            )
            sleep_fn(delay)
