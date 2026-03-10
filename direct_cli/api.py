"""
API client wrapper for Direct CLI
"""

from typing import Optional, Dict, Any, List

from tapi_yandex_direct import YandexDirect
from .auth import get_credentials


def create_client(
    token: Optional[str] = None,
    login: Optional[str] = None,
    sandbox: bool = False,
) -> YandexDirect:
    """
    Create YandexDirect client

    Args:
        token: API access token
        login: Client login (for agency accounts)
        sandbox: Use sandbox API

    Returns:
        YandexDirect client instance
    """
    final_token, final_login = get_credentials(token, login)

    return YandexDirect(
        access_token=final_token,
        login=final_login,
        is_sandbox=sandbox,
        retry_if_exceeded_limit=True,
        retries_if_server_error=5,
        # Report settings
        processing_mode="auto",
        wait_report=True,
        return_money_in_micros=False,
        skip_report_header=True,
        skip_column_header=False,
        skip_report_summary=True,
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
