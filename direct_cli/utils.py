"""
Utilities for Direct CLI
"""

import base64
import json
import math
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Union

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


def assert_not_runtime_deprecated(cli_group: str, method: str) -> None:
    """Raise a stable usage error for methods known to fail at API runtime."""
    from direct_cli.wsdl_coverage import RUNTIME_DEPRECATED_METHODS

    policy = RUNTIME_DEPRECATED_METHODS.get((cli_group, method))
    if not policy:
        return

    message = (
        f"direct {cli_group} {method} is deprecated by the Yandex Direct API "
        f"and fails at runtime with error_code={policy['error_code']}. "
        f"Use {policy['replacement']}."
    )
    raise click.UsageError(message)


def parse_csv_strings(value: Optional[str]) -> Optional[List[str]]:
    """Parse comma-separated strings, trimming whitespace."""
    if not value:
        return None

    items = [item.strip() for item in value.split(",")]
    result = [item for item in items if item]
    return result or None


def parse_csv_upper(value: Optional[str]) -> Optional[List[str]]:
    """Parse comma-separated enum-like strings and uppercase each item."""
    parsed = parse_csv_strings(value)
    return [item.upper() for item in parsed] if parsed else None


def add_criteria_csv(
    criteria: Dict[str, Any],
    key: str,
    value: Optional[str],
    *,
    integers: bool = False,
    upper: bool = False,
) -> None:
    """Add a comma-separated CLI value to a SelectionCriteria dict."""
    if not value:
        return
    if integers:
        criteria[key] = parse_ids(value)
        return
    parsed = parse_csv_upper(value) if upper else parse_csv_strings(value)
    if parsed:
        criteria[key] = parsed


def add_single_id_selector(
    item: Dict[str, Any],
    *,
    campaign_id: Optional[int],
    adgroup_id: Optional[int],
    keyword_id: Optional[int],
    command_name: str,
) -> None:
    """Add exactly one campaign, ad group, or keyword selector to an item."""
    selectors = [
        ("CampaignId", campaign_id, "--campaign-id"),
        ("AdGroupId", adgroup_id, "--adgroup-id"),
        ("KeywordId", keyword_id, "--keyword-id"),
    ]
    provided = [
        (field_name, value, option_name)
        for field_name, value, option_name in selectors
        if value is not None
    ]
    if len(provided) != 1:
        options = ", ".join(option for _, _, option in selectors)
        raise click.UsageError(
            f"{command_name} requires exactly one selector: {options}"
        )

    field_name, value, _ = provided[0]
    item[field_name] = value


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
            return  # unreachable; satisfies type checkers
        if val < 0:
            self.fail(f"Bid must be non-negative, got {val}")
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


def parse_priority_goals_spec(
    value: Optional[str],
) -> Optional[List[Dict[str, int]]]:
    """Parse `goal_id:value,...` into WSDL PriorityGoalsItem[] (GoalId/Value)."""
    if not value:
        return None

    items: List[Dict[str, int]] = []
    for pair in value.split(","):
        pair = pair.strip()
        if not pair:
            raise click.UsageError(
                "--priority-goals must be a comma-separated list of "
                "goal_id:value pairs"
            )
        goal_part, separator, value_part = pair.partition(":")
        if not separator:
            raise click.UsageError(
                f"Invalid --priority-goals item: '{pair}'. "
                "Expected format: goal_id:value"
            )
        goal_part = goal_part.strip()
        value_part = value_part.strip()
        if not goal_part or not value_part:
            raise click.UsageError(
                f"Invalid --priority-goals item: '{pair}'. "
                "Both goal_id and value are required"
            )
        try:
            goal_id = int(goal_part)
            value_int = int(value_part)
        except ValueError:
            raise click.UsageError(
                f"Invalid --priority-goals item: '{pair}'. "
                "goal_id and value must be integers"
            )
        items.append({"GoalId": goal_id, "Value": value_int})

    if not items:
        raise click.UsageError(
            "--priority-goals must contain at least one goal_id:value pair"
        )
    return items


EMAIL_SUBSCRIPTION_OPTIONS = {
    "RECEIVE_RECOMMENDATIONS",
    "TRACK_MANAGED_CAMPAIGNS",
    "TRACK_POSITION_CHANGES",
}

CLIENT_SETTING_OPTIONS = {
    "CORRECT_TYPOS_AUTOMATICALLY",
    "DISPLAY_STORE_RATING",
}

AGENCY_CLIENT_GRANT_OPTIONS = {
    "EDIT_CAMPAIGNS",
    "IMPORT_XLS",
    "TRANSFER_MONEY",
}

TIN_TYPES = {
    "PHYSICAL",
    "FOREIGN_PHYSICAL",
    "LEGAL",
    "FOREIGN_LEGAL",
    "INDIVIDUAL",
}

YES_NO_VALUES = {"YES", "NO"}

DECIMAL_RE = re.compile(r"^(?:0|[1-9]\d*)(?:\.\d+)?$")

CONTRACT_TYPES = {
    "CONTRACT",
    "INTERMEDIARY_CONTRACT",
    "ADDITIONAL_AGREEMENT",
}

CONTRACT_ACTION_TYPES = {
    "COMMERCIAL",
    "DISTRIBUTION",
    "CONCLUDE",
    "OTHER",
}

CONTRACT_SUBJECT_TYPES = {
    "REPRESENTATION",
    "MEDIATION",
    "DISTRIBUTION",
    "ORG_DISTRIBUTION",
    "OTHER",
}


def parse_yes_no_spec(
    spec: str,
    allowed_options: Iterable[str],
    label: str,
) -> Dict[str, str]:
    """Parse and validate one OPTION=YES|NO update spec."""
    option, separator, value = spec.partition("=")
    if not separator:
        raise click.UsageError(
            f"Invalid {label}: '{spec}'. Expected format: OPTION=YES|NO"
        )

    option = option.strip()
    value = value.strip()
    allowed_options = set(allowed_options)
    if option not in allowed_options:
        allowed = ", ".join(sorted(allowed_options))
        raise click.UsageError(
            f"Invalid {label} option: '{option}'. Expected one of: {allowed}"
        )
    if value not in YES_NO_VALUES:
        raise click.UsageError(f"Invalid {label} value: '{value}'. Expected YES or NO")

    return {"Option": option, "Value": value}


def parse_email_subscription_specs(
    specs: Optional[List[str]],
) -> Optional[List[Dict[str, str]]]:
    """Parse repeated Notification.EmailSubscriptions OPTION=YES|NO specs."""
    if not specs:
        return None
    return [
        parse_yes_no_spec(spec, EMAIL_SUBSCRIPTION_OPTIONS, "email subscription")
        for spec in specs
    ]


def parse_client_setting_specs(
    specs: Optional[List[str]],
) -> Optional[List[Dict[str, str]]]:
    """Parse repeated client Settings OPTION=YES|NO specs."""
    if not specs:
        return None
    return [
        parse_yes_no_spec(spec, CLIENT_SETTING_OPTIONS, "client setting")
        for spec in specs
    ]


def parse_grant_specs(specs: Optional[List[str]]) -> Optional[List[Dict[str, str]]]:
    """Parse repeated agency client Grants PRIVILEGE=YES|NO specs."""
    if not specs:
        return None
    grants = []
    for spec in specs:
        parsed = parse_yes_no_spec(spec, AGENCY_CLIENT_GRANT_OPTIONS, "grant")
        grants.append({"Privilege": parsed["Option"], "Value": parsed["Value"]})
    return grants


def parse_tin_info(
    tin_type: Optional[str],
    tin: Optional[str],
    option_name: str = "--tin-type",
) -> Optional[Dict[str, str]]:
    """Build TinInfo from typed flags."""
    tin_info = {}
    if tin_type:
        if tin_type not in TIN_TYPES:
            allowed = ", ".join(sorted(TIN_TYPES))
            raise click.UsageError(
                f"Invalid tin type for {option_name}: "
                f"'{tin_type}'. Expected one of: {allowed}"
            )
        tin_info["TinType"] = tin_type
    if tin:
        tin_info["Tin"] = tin
    return tin_info or None


def build_erir_organization(
    name: Optional[str],
    kpp: Optional[str],
    epay_number: Optional[str],
    reg_number: Optional[str],
    oksm_number: Optional[str],
    okved_code: Optional[str],
) -> Optional[Dict[str, str]]:
    """Build ErirAttributes.Organization from typed flags."""
    organization = {}
    if name:
        organization["Name"] = name
    if kpp:
        organization["Kpp"] = kpp
    if epay_number:
        organization["EpayNumber"] = epay_number
    if reg_number:
        organization["RegNumber"] = reg_number
    if oksm_number:
        organization["OksmNumber"] = oksm_number
    if okved_code:
        organization["OkvedCode"] = okved_code
    return organization or None


def build_erir_contract(
    number: Optional[str],
    date: Optional[str],
    contract_type: Optional[str],
    action_type: Optional[str],
    subject_type: Optional[str],
    is_agency_payment: Optional[str],
    price_amount: Optional[float],
    price_including_vat: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Build ErirAttributes.Contract from typed flags."""
    contract = {}
    if number:
        contract["Number"] = number
    if date:
        contract["Date"] = date
    if contract_type:
        contract["Type"] = contract_type.upper()
    if action_type:
        contract["ActionType"] = action_type.upper()
    if subject_type:
        contract["SubjectType"] = subject_type.upper()
    if is_agency_payment:
        contract["IsAgencyPayment"] = is_agency_payment.upper()

    price_fields = {
        "--erir-contract-price-amount": price_amount,
        "--erir-contract-price-including-vat": price_including_vat,
    }
    provided_price_fields = {
        option for option, value in price_fields.items() if value is not None
    }
    if provided_price_fields and len(provided_price_fields) != len(price_fields):
        missing = ", ".join(sorted(set(price_fields) - provided_price_fields))
        raise click.UsageError(f"ErirAttributes.Contract.Price requires {missing}")
    if price_amount is not None and price_including_vat is not None:
        contract["Price"] = {
            "Amount": price_amount,
            "IncludingVat": price_including_vat.upper(),
        }

    return contract or None


def build_erir_contragent(
    name: Optional[str],
    kpp: Optional[str],
    phone: Optional[str],
    epay_number: Optional[str],
    reg_number: Optional[str],
    oksm_number: Optional[str],
    tin_info: Optional[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    """Build ErirAttributes.Contragent from typed flags."""
    contragent = {}
    if name:
        contragent["Name"] = name
    if kpp:
        contragent["Kpp"] = kpp
    if phone:
        contragent["Phone"] = phone
    if epay_number:
        contragent["EpayNumber"] = epay_number
    if reg_number:
        contragent["RegNumber"] = reg_number
    if oksm_number:
        contragent["OksmNumber"] = oksm_number
    if tin_info:
        contragent["TinInfo"] = tin_info
    return contragent or None


def parse_positive_decimal_amount(value: str, option_name: str) -> float:
    """Parse a positive finite decimal CLI amount."""
    normalized = (value or "").strip()
    if not DECIMAL_RE.fullmatch(normalized):
        raise click.UsageError(
            f"{option_name} must be a positive decimal amount, for example 100.50"
        )

    try:
        amount = Decimal(normalized)
    except InvalidOperation as exc:
        raise click.UsageError(
            f"{option_name} must be a positive decimal amount, for example 100.50"
        ) from exc

    if amount <= 0:
        raise click.UsageError(f"{option_name} must be greater than zero")

    result = float(amount)
    if not math.isfinite(result):
        raise click.UsageError(f"{option_name} must be a finite decimal amount")
    return result


def build_erir_attributes(
    organization: Optional[Dict[str, Any]] = None,
    contract: Optional[Dict[str, Any]] = None,
    contragent: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Build ErirAttributes from typed child objects."""
    erir_attributes = {}
    if organization:
        erir_attributes["Organization"] = organization
    if contract:
        erir_attributes["Contract"] = contract
    if contragent:
        erir_attributes["Contragent"] = contragent
    return erir_attributes or None


def build_notification_update(
    email: Optional[str],
    lang: Optional[str],
    email_subscriptions: Optional[List[Dict[str, str]]],
) -> Optional[Dict[str, Any]]:
    """Build Notification update object from typed flags."""
    notification = {}
    if email:
        notification["Email"] = email
    if lang:
        notification["Lang"] = lang
    if email_subscriptions:
        notification["EmailSubscriptions"] = email_subscriptions
    return notification or None


def build_client_update_item(
    client_info: Optional[str],
    phone: Optional[str],
    notification: Optional[Dict[str, Any]],
    settings: Optional[List[Dict[str, str]]],
    tin_info: Optional[Dict[str, str]],
    erir_attributes: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a generalclients ClientUpdateItem with WSDL-valid keys only."""
    item = {}
    if client_info:
        item["ClientInfo"] = client_info
    if phone:
        item["Phone"] = phone
    if notification:
        item["Notification"] = notification
    if settings:
        item["Settings"] = settings
    if tin_info:
        item["TinInfo"] = tin_info
    if erir_attributes:
        item["ErirAttributes"] = erir_attributes
    return item


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


def _split_sitelink_spec(spec: str) -> List[str]:
    """Split a sitelink spec by '|', treating '\\|' as a literal pipe.

    UTM templates in Yandex Direct use literal '|' inside URLs
    (e.g. cid|{campaign_id}|gid|{gbid}); allow users to escape it as '\\|'.
    """
    parts: List[str] = []
    current: List[str] = []
    i = 0
    while i < len(spec):
        ch = spec[i]
        if ch == "\\" and i + 1 < len(spec) and spec[i + 1] == "|":
            current.append("|")
            i += 2
            continue
        if ch == "|":
            parts.append("".join(current))
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    parts.append("".join(current))
    return parts


def parse_sitelink_specs(specs: Optional[List[str]]) -> Optional[List[Dict[str, Any]]]:
    """Parse repeated TITLE|HREF[|DESCRIPTION[|TURBO_PAGE_ID]] specs.

    Literal '|' characters inside any field can be escaped as '\\|'.
    """
    if not specs:
        return None

    sitelinks = []
    for spec in specs:
        parts = [part.strip() for part in _split_sitelink_spec(spec)]
        if len(parts) not in (2, 3, 4):
            raise ValueError(
                "Invalid sitelink: "
                f"'{spec}'. Expected format: "
                "TITLE|HREF[|DESCRIPTION[|TURBO_PAGE_ID]]. "
                "Escape a literal '|' inside a field as '\\|'."
            )

        if not parts[0]:
            raise ValueError(f"Invalid sitelink: '{spec}'. Title is required.")

        sitelink: Dict[str, Any] = {"Title": parts[0]}
        if parts[1]:
            sitelink["Href"] = parts[1]
        if len(parts) == 3 and parts[2]:
            sitelink["Description"] = parts[2]
        if len(parts) == 4:
            if parts[2]:
                sitelink["Description"] = parts[2]
            if not parts[3]:
                raise ValueError(
                    f"Invalid sitelink: '{spec}'. TurboPageId must be an integer."
                )
            try:
                sitelink["TurboPageId"] = int(parts[3])
            except ValueError:
                raise ValueError(
                    f"Invalid sitelink: '{spec}'. TurboPageId must be an integer."
                )

        if "Href" not in sitelink and "TurboPageId" not in sitelink:
            raise ValueError(
                f"Invalid sitelink: '{spec}'. Provide Href or TurboPageId."
            )
        sitelinks.append(sitelink)
    return sitelinks


COMMON_FIELDS: Dict[str, Union[List[str], Dict[str, List[str]]]] = {
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
    "ads": {
        "FieldNames": ["Id", "CampaignId", "AdGroupId", "Status", "State", "Type"],
        "TextAdFieldNames": ["Title", "Title2", "Text", "Href"],
    },
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
    "agencyclients": ["ClientId", "Login", "CountryId", "Currency"],
    "creatives": ["Id", "Name", "Type"],
    "adimages": ["AdImageHash", "Name"],
    "adextensions": ["Id", "Type", "State", "Status"],
    "negativekeywordsharedsets": ["Id", "Name", "NegativeKeywords"],
    "sitelinks": ["Id", "Sitelinks"],
    "vcards": ["Id", "CampaignId", "Country", "City", "CompanyName"],
    "leads": ["Id", "SubmittedAt", "TurboPageId", "TurboPageName"],
    "turbopages": [
        "Id",
        "Name",
        "Href",
        "TurboSiteHref",
        "PreviewHref",
        "BoundWithHref",
    ],
    "feeds": ["Id", "Name", "BusinessType", "SourceType", "Status"],
    "smartadtargets": ["Id", "CampaignId", "AdGroupId", "State"],
    "businesses": ["Id", "Name", "Address", "Phone", "ProfileUrl"],
    "changes": ["CampaignIds", "AdGroupIds", "AdIds", "CampaignsStat"],
    "retargetinglists": ["Id", "Name", "Type", "Scope"],
    "advideos": ["Id", "Status"],
    "bids": ["CampaignId", "AdGroupId", "KeywordId", "Bid"],
    "bidmodifiers": ["Id", "CampaignId", "AdGroupId", "Level", "Type"],
    "audiencetargets": [
        "Id",
        "AdGroupId",
        "RetargetingListId",
        "State",
        "ContextBid",
    ],
    "dynamicads": ["Id", "AdGroupId", "Conditions", "Bid"],
    "strategies": ["Id", "Name", "Type", "StatusArchived"],
    "dynamicfeedadtargets": [
        "Id",
        "AdGroupId",
        "CampaignId",
        "Name",
        "Bid",
        "ContextBid",
    ],
    # Multi-FieldNames resources: WSDL exposes more than one ``*FieldNames``
    # request param (e.g. SearchFieldNames + NetworkFieldNames). Each key is
    # the WSDL request-field name; values are the default enum-validated lists.
    "keywordbids": {
        "FieldNames": [
            "KeywordId",
            "AdGroupId",
            "CampaignId",
            "ServingStatus",
            "StrategyPriority",
        ],
        "SearchFieldNames": ["Bid"],
        "NetworkFieldNames": ["Bid"],
    },
    "keywordsresearch": ["Keyword", "AllDevices"],
}


def get_default_fields(resource: str, request_field: str = "FieldNames") -> List[str]:
    """Return default field names for a resource's WSDL request param.

    For single-FieldNames resources, ``COMMON_FIELDS[resource]`` is a list and
    ``request_field`` is ignored. For multi-FieldNames resources (like
    ``keywordbids`` with ``SearchFieldNames``/``NetworkFieldNames``), the
    value is a dict keyed by request-field name.
    """
    entry = COMMON_FIELDS.get(resource)
    if entry is None:
        return ["Id", "Name"]
    if isinstance(entry, dict):
        return entry.get(request_field, ["Id", "Name"])
    return entry


def get_docs_url(service: str) -> Optional[str]:
    """Return documentation URL for a service from tapi resource mapping."""
    entry = RESOURCE_MAPPING_V5.get(service)
    return entry.get("docs") if entry else None


def get_docs_pages(service: str) -> Dict[str, str]:
    """Return documentation page URLs for a service from tapi resource mapping."""
    entry = RESOURCE_MAPPING_V5.get(service)
    docs_pages = entry.get("docs_pages") if entry else None
    return dict(docs_pages) if docs_pages else {}
