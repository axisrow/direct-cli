"""
Utilities for Direct CLI
"""

import json
from typing import Any, Dict, List, Optional
from datetime import datetime


def parse_ids(ids_str: Optional[str]) -> Optional[List[int]]:
    """Parse comma-separated IDs"""
    if not ids_str:
        return None
    return [int(x.strip()) for x in ids_str.split(",")]


def parse_json(json_str: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse JSON string"""
    if not json_str:
        return None
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")


def build_selection_criteria(
    ids: Optional[List[int]] = None,
    status: Optional[str] = None,
    types: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Build SelectionCriteria from parameters"""
    criteria = {}

    if ids:
        criteria["Ids"] = ids
    if status:
        criteria["Statuses"] = [status]
    if types:
        criteria["Types"] = types.split(",")

    return criteria if criteria else None


def build_common_params(
    criteria: Optional[Dict[str, Any]] = None,
    field_names: Optional[List[str]] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Build common params for get requests"""
    params = {}

    if criteria:
        params["SelectionCriteria"] = criteria
    if field_names:
        params["FieldNames"] = field_names
    if limit:
        params["Page"] = {"Limit": limit}

    return params


def parse_date(date_str: str) -> str:
    """Parse and validate date string"""
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
        return date_str
    except ValueError:
        raise ValueError(f"Invalid date format: {date_str}. Expected: YYYY-MM-DD")


COMMON_FIELDS = {
    "campaigns": [
        "Id",
        "Name",
        "Status",
        "State",
        "StartDate",
        "EndDate",
        "Type",
        "DailyBudget",
        "ClientInfo",
    ],
    "adgroups": ["Id", "Name", "CampaignId", "Status", "Type", "RegionIds"],
    "ads": ["Id", "CampaignId", "AdGroupId", "Status", "State", "Type"],
    "keywords": [
        "Id",
        "Keyword",
        "CampaignId",
        "AdGroupId",
        "Status",
        "ServingStatus",
        "Bid",
        "ContextBid",
    ],
    "clients": ["ClientId", "Login", "CountryId", "Currency", "Status"],
    "creatives": ["Id", "Name", "Type", "Status"],
    "adimages": ["Id", "Name", "Status", "AdImageHash"],
    "adextensions": ["Id", "Type", "Status"],
    "sitelinks": ["Id", "Sitelinks"],
    "vcards": ["Id", "CampaignId", "Country", "City", "CompanyName"],
    "leads": ["Date", "LeadId", "CampaignId", "AdGroupId", "AdId"],
    "turbopages": ["Id", "Name", "Status", "Href"],
    "feeds": ["Id", "Name", "Source", "Status"],
    "smartadtargets": ["Id", "CampaignId", "AdGroupId", "Status", "ServingStatus"],
    "businesses": ["Id", "Name", "Url"],
    "retargetinglists": ["Id", "Name", "Type", "Scope"],
}


def get_default_fields(resource: str) -> List[str]:
    """Get default field names for resource"""
    return COMMON_FIELDS.get(resource, ["Id", "Name"])
