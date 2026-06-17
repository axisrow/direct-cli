"""
Utilities for Direct CLI
"""

import base64
import json
import math
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

import click

from direct_cli._vendor.tapi_yandex_direct.resource_mapping import (
    RESOURCE_MAPPING_V5,
)
from direct_cli.i18n import t


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


def parse_field_names_option(
    wsdl_key: str, raw_value: Optional[str]
) -> Optional[List[str]]:
    """Parse a field-name projection and reject explicitly empty CSV.

    Shared by the ``ads``/``strategies`` get-commands and the nested
    field-name loops in ``adgroups``/``bidmodifiers``/``agencyclients``/
    ``clients``/``creatives``. The error string-key is byte-identical to the
    pre-dedup inline copies so the merged i18n catalog lookup is unchanged.
    """
    parsed = parse_csv_strings(raw_value)
    if raw_value is not None and not parsed:
        raise click.UsageError(
            t("Provide a non-empty comma-separated {wsdl_key} list.").format(
                wsdl_key=wsdl_key
            )
        )
    return parsed


def parse_nested_field_names(
    raw_nested: Iterable[Tuple[str, Optional[str]]],
) -> Dict[str, List[str]]:
    """Parse a sequence of ``(WSDL key, raw CSV)`` nested field-name options.

    Returns only the keys whose CSV resolved to a non-empty list — exactly the
    ``for wsdl_key, raw_value in raw_nested: ... if parsed: out[k] = parsed``
    accumulation previously inlined in several command modules.
    """
    parsed_nested: Dict[str, List[str]] = {}
    for wsdl_key, raw_value in raw_nested:
        parsed = parse_field_names_option(wsdl_key, raw_value)
        if parsed:
            parsed_nested[wsdl_key] = parsed
    return parsed_nested


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


def enforce_criteria_array_limits(
    criteria: Dict[str, Any],
    limits: Dict[str, int],
    *,
    command_name: str,
) -> None:
    """Preflight-reject SelectionCriteria arrays that exceed live API ceilings.

    WSDL declares each such array ``maxOccurs="unbounded"``, but the runtime
    API caps several of them (verified live 2026-06-16) and rejects an
    over-long array with an opaque ``error_code=4001`` ("cannot contain more
    than N elements"). Raising a ``UsageError`` here surfaces the exact array
    and ceiling before the request, mirroring the ``KEYWORDS_ADD_MAX_BATCH``
    discipline in ``keywords.py``.

    ``limits`` maps a SelectionCriteria key (e.g. ``"CampaignIds"``) to its
    maximum element count. Only keys present in both ``limits`` and
    ``criteria`` are checked.
    """
    for key, maximum in limits.items():
        value = criteria.get(key)
        if isinstance(value, list) and len(value) > maximum:
            raise click.UsageError(
                t(
                    "{command_name}: SelectionCriteria.{key} cannot contain "
                    "more than {maximum} elements (got {count})."
                ).format(
                    command_name=command_name,
                    key=key,
                    maximum=maximum,
                    count=len(value),
                )
            )


# Live-audited 2026-06-17 (sandbox, see scripts/measure_criteria_limits.py):
# read-get commands and SelectionCriteria array keys where the API accepted
# N=10000 — no preflight needed today. If Yandex adds a cap in the future,
# the matching `<CMD>_GET_CRITERIA_LIMITS` constant must be added and the key
# moved out of this list. See #571 for context.
UNCAPPED_CRITERIA_KEYS = frozenset(
    {
        "strategies.Ids",
        "sitelinks.Ids",
        "vcards.Ids",
        "adextensions.Ids",
        "ads.Ids",
        "ads.AdExtensionIds",
        "adgroups.Ids",
        "adgroups.TagIds",
        "bids.KeywordIds",
        "bidmodifiers.Ids",
        "bidmodifiers.AdGroupIds",
        "keywords.Ids",
        "dynamicfeedadtargets.Ids",
        "audiencetargets.Ids",
    }
)


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


def parse_changes_datetime(datetime_str: str) -> str:
    """Parse Yandex Direct Changes datetime in API wire format."""
    if not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:\d{2})",
        datetime_str,
    ):
        raise ValueError(
            f"Invalid datetime format: {datetime_str}. "
            "Expected: YYYY-MM-DDTHH:MM:SSZ or YYYY-MM-DDTHH:MM:SS+03:00"
        )
    try:
        if datetime_str.endswith("Z"):
            datetime.strptime(datetime_str, "%Y-%m-%dT%H:%M:%SZ")
            return datetime_str
        parsed = datetime.strptime(datetime_str, "%Y-%m-%dT%H:%M:%S%z")
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise ValueError(
            f"Invalid datetime format: {datetime_str}. "
            "Expected: YYYY-MM-DDTHH:MM:SSZ or YYYY-MM-DDTHH:MM:SS+03:00"
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


def validate_priority_goal_value(value_int: int, error_prefix: str) -> None:
    """Enforce the WSDL PriorityGoalsItem.Value micro-currency contract.

    Used by both `parse_priority_goals_spec` (campaigns `--priority-goals`)
    and the `_parse_priority_goal` parser in `direct strategies` to reject
    raw-ruble inputs (issue #387) at CLI parse time. `error_prefix` is
    prepended to the error message so callers can preserve their own
    "--priority-goals item: 'PAIR'." / "--priority-goal 'SPEC'." phrasing.
    """
    if value_int < 0:
        raise click.UsageError(
            f"{error_prefix} " f"Value must be non-negative, got {value_int}"
        )
    if 0 < value_int < MICRO_RUBLE_MIN:
        raise click.UsageError(
            f"{error_prefix} "
            f"Value {value_int} seems too low for micro-currency "
            f"(min {MICRO_RUBLE_MIN} = 0.1 unit). "
            f"PriorityGoalsItem.Value is advertiser currency × 1,000,000. "
            f"Did you mean {value_int * 1_000_000}?"
        )


def parse_priority_goals_spec(
    value: Optional[str],
) -> Optional[List[Dict[str, Any]]]:
    """Parse goal_id:value[:YES|NO] into WSDL PriorityGoalsItem[] items.

    Per Yandex Direct API contract (add-text-campaign, strategies-types),
    PriorityGoalsItem.Value is xsd:long in advertiser currency multiplied
    by 1,000,000 — same micro-currency contract as --budget and other
    bid/budget money flags. Reject sub-MICRO_RUBLE_MIN values to catch
    raw-ruble inputs at CLI parse time.
    """
    if not value:
        return None

    items: List[Dict[str, Any]] = []
    for pair in value.split(","):
        pair = pair.strip()
        if not pair:
            raise click.UsageError(
                "--priority-goals must be a comma-separated list of goal_id:value pairs"
            )
        parts = [part.strip() for part in pair.split(":")]
        if len(parts) not in (2, 3):
            raise click.UsageError(
                f"Invalid --priority-goals item: '{pair}'. "
                "Expected format: goal_id:value[:YES|NO]"
            )
        goal_part, value_part = parts[0], parts[1]
        if not goal_part or not value_part:
            raise click.UsageError(
                f"Invalid --priority-goals item: '{pair}'. "
                "Both goal_id and value are required"
            )
        metrika_source = None
        if len(parts) == 3:
            metrika_source = parts[2].upper()
            if metrika_source not in {"YES", "NO"}:
                raise click.UsageError(
                    f"Invalid --priority-goals item: '{pair}'. "
                    "IsMetrikaSourceOfValue must be YES or NO"
                )
        try:
            goal_id = int(goal_part)
            value_int = int(value_part)
        except ValueError:
            raise click.UsageError(
                f"Invalid --priority-goals item: '{pair}'. "
                "goal_id and value must be integers"
            )
        validate_priority_goal_value(
            value_int, f"Invalid --priority-goals item: '{pair}'."
        )
        item: Dict[str, Any] = {"GoalId": goal_id, "Value": value_int}
        if metrika_source is not None:
            item["IsMetrikaSourceOfValue"] = metrika_source
        items.append(item)

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
# Compiled decimal patterns keyed by the maximum allowed fractional digits,
# so callers that cap precision (e.g. v4 money, max 2 dp) don't recompile.
_DECIMAL_RE_CACHE: Dict[int, "re.Pattern[str]"] = {}


def _decimal_re(max_decimals: Optional[int]) -> "re.Pattern[str]":
    """Return the decimal validator, optionally capping fractional digits."""
    if max_decimals is None:
        return DECIMAL_RE
    cached = _DECIMAL_RE_CACHE.get(max_decimals)
    if cached is None:
        cached = re.compile(r"^(?:0|[1-9]\d*)(?:\.\d{1," + str(max_decimals) + "})?$")
        _DECIMAL_RE_CACHE[max_decimals] = cached
    return cached


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


def parse_positive_decimal_amount(
    value: str, option_name: str, *, max_decimals: Optional[int] = None
) -> float:
    """Parse a positive finite decimal CLI amount.

    ``max_decimals`` caps the number of fractional digits accepted (``None``
    means unlimited). v4 ``Sum`` fields pass ``max_decimals=2`` via
    :func:`direct_cli.v4.money.parse_v4_money_sum`.
    """
    normalized = (value or "").strip()
    if not _decimal_re(max_decimals).fullmatch(normalized):
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


def get_options(func):
    """Apply the shared read/pagination option stack of a ``get`` command.

    Equivalent to writing, in this exact top-to-bottom order::

        @click.option("--limit", type=int, help="Limit number of results")
        @click.option("--fetch-all", is_flag=True, help="Fetch all pages")
        @click.option("--format", "output_format", default="json", help="Output format")
        @click.option("--output", help="Output file")
        @click.option("--fields", help="Comma-separated field names")
        @click.option("--dry-run", is_flag=True, help="Show request without sending")

    Click applies decorators bottom-up, so the options are added here in
    reverse to keep ``--help`` listing them in the order above. Only commands
    whose six shared options are contiguous and use exactly these definitions
    use this decorator; commands with a divergent ``--fields`` help string,
    interleaved resource options, or a different option subset keep their
    explicit stack so the CLI surface stays byte-identical.
    """
    func = click.option("--dry-run", is_flag=True, help="Show request without sending")(
        func
    )
    func = click.option("--fields", help="Comma-separated field names")(func)
    func = click.option("--output", help="Output file")(func)
    func = click.option(
        "--format", "output_format", default="json", help="Output format"
    )(func)
    func = click.option("--fetch-all", is_flag=True, help="Fetch all pages")(func)
    return click.option("--limit", type=int, help="Limit number of results")(func)


def v4_output_options(func):
    """Apply the shared output/dry-run option stack of a v4 Live command.

    Equivalent to writing, in this exact top-to-bottom order::

        @click.option(
            "--format", "output_format", default="json",
            type=click.Choice(["json", "table", "csv", "tsv"]), help="Output format",
        )
        @click.option("--output", help="Output file")
        @click.option("--dry-run", is_flag=True, help="Show request without sending")

    Distinct from :func:`get_options`: v4 uses a typed ``click.Choice`` format
    and has no ``--limit`` / ``--fetch-all`` / ``--fields``. Click applies
    decorators bottom-up, so the options are added here in reverse to keep
    ``--help`` listing them in the order above. Only commands whose three
    options are contiguous and byte-identical use this decorator. NOT applied to
    ``v4account enable-shared-account`` / ``account-management`` (reversed order
    and a ``"...required outside --sandbox"`` ``--dry-run`` help) or the
    dry-run-only finance commands ``v4finance transfer-money`` /
    ``pay-campaigns`` / ``pay-campaigns-by-card`` (no ``--format`` / ``--output``).
    """
    func = click.option("--dry-run", is_flag=True, help="Show request without sending")(
        func
    )
    func = click.option("--output", help="Output file")(func)
    return click.option(
        "--format",
        "output_format",
        default="json",
        type=click.Choice(["json", "table", "csv", "tsv"]),
        help="Output format",
    )(func)
