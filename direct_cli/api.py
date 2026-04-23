"""
API client wrapper for Direct CLI
"""

from typing import Optional, Dict, Any, List

from direct_cli._vendor.tapi_yandex_direct import YandexDirect
from .auth import get_credentials


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
