"""
Utilities for Direct CLI
"""

import base64
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import click

from direct_cli._vendor.tapi_yandex_direct.resource_mapping import (
    RESOURCE_MAPPING_V5,
)


def parse_ids(ids_str: Optional[str]) -> Optional[List[int]]:
    """Parse comma-separated IDs"""
    if not ids_str:
        return None
    result = []
    for x in ids_str.split(","):
        x = x.strip()
        try:
            result.append(int(x))
        except ValueError:
            raise ValueError(f"Invalid ID: '{x}'. IDs must be integers.")
    return result


def parse_json(json_str: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse JSON string"""
    if not json_str:
        return None
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")


def parse_csv_strings(value: Optional[str]) -> Optional[List[str]]:
    """Parse comma-separated strings, trimming whitespace."""
    if not value:
        return None

    items = [item.strip() for item in value.split(",")]
    result = [item for item in items if item]
    return result or None


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


def parse_datetime(datetime_str: str) -> str:
    """Parse canonical CLI datetime and normalize it for the API."""
    try:
        datetime.strptime(datetime_str, "%Y-%m-%dT%H:%M:%S")
        return f"{datetime_str}Z"
    except ValueError:
        raise ValueError(
            "Invalid datetime format: " f"{datetime_str}. Expected: YYYY-MM-DDTHH:MM:SS"
        )


MICRO_RUBLE_MIN = 100_000  # 0.1 RUB — below this is almost certainly a mistake


class MicroRublesParamType(click.ParamType):
    """Click type that validates bid/budget values are in micro-rubles."""

    name = "MICRO_RUBLES"

    def convert(self, value, param, ctx):
        try:
            val = int(value)
        except (ValueError, TypeError):
            self.fail(f"Expected integer (micro-rubles), got '{value}'")
        if 0 < val < MICRO_RUBLE_MIN:
            self.fail(
                f"{val} seems too low for micro-rubles "
                f"(min {MICRO_RUBLE_MIN} = 0.1 RUB). "
                f"Did you mean {val * 1_000_000}?"
            )
        return val


MICRO_RUBLES = MicroRublesParamType()


def load_base64_file(file_path: str) -> str:
    """Read a file and return its base64-encoded contents."""
    with open(file_path, "rb") as file_obj:
        return base64.b64encode(file_obj.read()).decode("ascii")


def parse_setting_specs(specs: Optional[List[str]]) -> Optional[List[Dict[str, str]]]:
    """Parse repeated OPTION=VALUE campaign setting specs."""
    if not specs:
        return None

    settings = []
    for spec in specs:
        option, separator, value = spec.partition("=")
        if not separator:
            raise ValueError(
                f"Invalid setting: '{spec}'. Expected format: OPTION=VALUE"
            )
        settings.append({"Option": option.strip(), "Value": value.strip()})
    return settings


def parse_condition_specs(specs: Optional[List[str]]) -> Optional[List[Dict[str, Any]]]:
    """Parse repeated OPERAND:OPERATOR:ARG1|ARG2 condition specs."""
    if not specs:
        return None

    conditions = []
    for spec in specs:
        parts = spec.split(":", 2)
        if len(parts) != 3:
            raise ValueError(
                "Invalid condition: "
                f"'{spec}'. Expected format: OPERAND:OPERATOR:ARG1|ARG2"
            )

        operand, operator, arguments = [part.strip() for part in parts]
        parsed_arguments = [arg.strip() for arg in arguments.split("|") if arg.strip()]
        if not parsed_arguments:
            raise ValueError(
                f"Invalid condition: '{spec}'. Provide at least one argument."
            )

        conditions.append(
            {
                "Operand": operand,
                "Operator": operator,
                "Arguments": parsed_arguments,
            }
        )
    return conditions


def parse_retargeting_rule_specs(
    specs: Optional[List[str]],
) -> Optional[List[Dict[str, Any]]]:
    """Parse repeated OPERATOR:EXTERNAL_ID[:LIFESPAN][|...] rule specs."""
    if not specs:
        return None

    rules = []
    for spec in specs:
        operator, separator, arguments_spec = spec.partition(":")
        if not separator:
            raise ValueError(
                "Invalid rule: "
                f"'{spec}'. Expected format: OPERATOR:EXTERNAL_ID[:LIFESPAN][|...]"
            )

        arguments = []
        for argument_spec in arguments_spec.split("|"):
            parts = [part.strip() for part in argument_spec.split(":") if part.strip()]
            if not parts:
                continue
            if len(parts) > 2:
                raise ValueError(
                    "Invalid rule argument: "
                    f"'{argument_spec}'. Expected EXTERNAL_ID[:LIFESPAN]"
                )

            argument = {"ExternalId": int(parts[0])}
            if len(parts) == 2:
                argument["MembershipLifeSpan"] = int(parts[1])
            arguments.append(argument)

        if not arguments:
            raise ValueError(
                f"Invalid rule: '{spec}'. Provide at least one rule argument."
            )

        rules.append({"Operator": operator.strip(), "Arguments": arguments})
    return rules


def parse_sitelink_specs(specs: Optional[List[str]]) -> Optional[List[Dict[str, str]]]:
    """Parse repeated TITLE|HREF[|DESCRIPTION] sitelink specs."""
    if not specs:
        return None

    sitelinks = []
    for spec in specs:
        parts = [part.strip() for part in spec.split("|")]
        if len(parts) not in (2, 3):
            raise ValueError(
                "Invalid sitelink: "
                f"'{spec}'. Expected format: TITLE|HREF[|DESCRIPTION]"
            )

        sitelink = {"Title": parts[0], "Href": parts[1]}
        if len(parts) == 3 and parts[2]:
            sitelink["Description"] = parts[2]
        sitelinks.append(sitelink)
    return sitelinks


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
    "ads": ["Id", "CampaignId", "AdGroupId", "Status", "State", "Type", "TextAd"],
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
    "clients": ["ClientId", "Login", "CountryId", "Currency"],
    "creatives": ["Id", "Name", "Type"],
    "adimages": ["AdImageHash", "Name"],
    "adextensions": ["Id", "Type", "Status"],
    "sitelinks": ["Id", "Sitelinks"],
    "vcards": ["Id", "CampaignId", "Country", "City", "CompanyName"],
    "leads": ["Id", "SubmittedAt", "TurboPageId", "TurboPageName"],
    "turbopages": ["Id", "Name", "Href", "TurboSiteHref", "PreviewHref", "BoundWithHref"],
    "feeds": ["Id", "Name", "BusinessType", "SourceType", "Status"],
    "smartadtargets": ["Id", "CampaignId", "AdGroupId", "Status", "ServingStatus"],
    "businesses": ["Id", "Name", "Type", "Address", "Phone", "ProfileUrl"],
    "retargetinglists": ["Id", "Name", "Type", "Scope"],
    "advideos": ["Id", "Status"],
}


def get_default_fields(resource: str) -> List[str]:
    """Get default field names for resource"""
    return COMMON_FIELDS.get(resource, ["Id", "Name"])


def get_docs_url(service: str) -> Optional[str]:
    """Return documentation URL for a service from tapi resource mapping."""
    entry = RESOURCE_MAPPING_V5.get(service)
    return entry.get("docs") if entry else None
