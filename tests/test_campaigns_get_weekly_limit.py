"""Offline WSDL guards for reading the weekly campaign budget limit (#946).

``WeeklySpendLimit`` is NOT a valid root ``FieldNames`` value for
``campaigns get`` — the live API rejects it with err 8000 "An item in the
FieldNames array contains an invalid enumeration value" (issue #946), and the
cached WSDL agrees: the root ``CampaignFieldEnum`` does not declare it. The
weekly limit lives in the shared ``Strategy*`` GET structs, reachable only via
the type-specific ``BiddingStrategy`` field (``--text-campaign-field-names
BiddingStrategy`` and its per-type siblings).

The tests below pin that map so it cannot silently drift: if Yandex ever adds
``WeeklySpendLimit`` to the root enum (or drops it from the strategy structs),
the documented honest-fail guidance and ``COMMON_FIELDS`` must be revisited.
Whether the live API actually populates the value inside ``BiddingStrategy``
responses is WSDL-declared but not live-verified here (offline change).
"""

import xml.etree.ElementTree as ET  # noqa: N817 - standard stdlib alias
from functools import lru_cache
from pathlib import Path

from direct_cli.utils import COMMON_FIELDS

XSD = "{http://www.w3.org/2001/XMLSchema}"
WSDL_PATH = Path(__file__).resolve().parent / "wsdl_cache" / "campaigns.xml"


@lru_cache(maxsize=1)
def _root():
    return ET.parse(WSDL_PATH).getroot()


def _enum_values(name: str) -> list:
    for simple in _root().iter(f"{XSD}simpleType"):
        if simple.get("name") == name:
            return [el.get("value") for el in simple.iter(f"{XSD}enumeration")]
    raise AssertionError(f"simpleType {name} not found in {WSDL_PATH}")


def _element_decls(complex_type_name: str) -> list:
    """Direct child element declarations of a named complexType.

    Uses findall on the (possibly extension-wrapped) sequence rather than
    iter(), so inline anonymous types of sibling elements are not traversed.
    """
    for ctype in _root().iter(f"{XSD}complexType"):
        if ctype.get("name") != complex_type_name:
            continue
        extension = ctype.find(f"{XSD}complexContent/{XSD}extension")
        parent = extension if extension is not None else ctype
        sequence = parent.find(f"{XSD}sequence")
        if sequence is None:
            raise AssertionError(f"no xsd:sequence in {complex_type_name}")
        return [
            (el.get("name"), el.get("type")) for el in sequence.findall(f"{XSD}element")
        ]
    raise AssertionError(f"complexType {complex_type_name} not found in {WSDL_PATH}")


def test_weekly_spend_limit_is_not_a_root_campaign_field():
    """The honest fail: root FieldNames cannot carry WeeklySpendLimit."""
    assert "WeeklySpendLimit" not in _enum_values("CampaignFieldEnum")


def test_weekly_spend_limit_stays_out_of_default_common_fields():
    """COMMON_FIELDS["campaigns"] must not request it — every default call
    would fail with API err 8000."""
    assert "WeeklySpendLimit" not in COMMON_FIELDS["campaigns"]


def test_bidding_strategy_is_a_valid_type_specific_get_field():
    """The field that actually returns the weekly limit on every subtype."""
    for enum_name in (
        "TextCampaignFieldEnum",
        "UnifiedCampaignFieldEnum",
        "MobileAppCampaignFieldEnum",
        "DynamicTextCampaignFieldEnum",
        "CpmBannerCampaignFieldEnum",
        "SmartCampaignFieldEnum",
    ):
        assert "BiddingStrategy" in _enum_values(enum_name), enum_name


def test_text_campaign_get_item_routes_bidding_strategy_to_shared_strategies():
    """WSDL chain: TextCampaignGetItem.BiddingStrategy → TextCampaignStrategy
    → Search/Network → (extension of) TextCampaignStrategyBase → shared
    ``Strategy*`` structs that declare WeeklySpendLimit."""
    assert (
        "BiddingStrategy",
        "ns:TextCampaignStrategy",
    ) in _element_decls("TextCampaignGetItem")

    search_base = _extension_base("TextCampaignSearchStrategy")
    network_base = _extension_base("TextCampaignNetworkStrategy")
    assert search_base == network_base == "ns:TextCampaignStrategyBase"


def _extension_base(name: str):
    for ctype in _root().iter(f"{XSD}complexType"):
        if ctype.get("name") == name:
            extension = ctype.find(f"{XSD}complexContent/{XSD}extension")
            if extension is None:
                return None
            return extension.get("base")
    raise AssertionError(f"complexType {name} not found in {WSDL_PATH}")


def test_shared_strategy_structs_declare_weekly_spend_limit():
    base_types = [
        local_type.split(":")[1]
        for _, local_type in _element_decls("TextCampaignStrategyBase")
    ]
    with_weekly = {
        local_name
        for local_name in base_types
        if "WeeklySpendLimit" in _element_names_including_bases(local_name)
    }
    # Weekly-budget text-campaign strategies read their limit from these
    # GET-side structs: the WEEKLY_BUDGET base declares it directly, and
    # WB_MAXIMUM_CLICKS → WbMaximumClicks inherits it from that base.
    assert {"StrategyMaximumClicks", "StrategyAverageCpc"} <= with_weekly
    assert "WeeklySpendLimit" in _element_names_including_bases(
        "StrategyWeeklyBudgetBase"
    )


def _element_names_including_bases(complex_type_name: str) -> list:
    """Element names of a complexType plus every xsd:extension base it
    inherits from (e.g. StrategyMaximumClicks extends
    StrategyWeeklyBudgetBase, which declares WeeklySpendLimit)."""
    names = [el_name for el_name, _ in _element_decls(complex_type_name)]
    base = _extension_base(complex_type_name)
    if base is not None:
        names.extend(_element_names_including_bases(base.split(":")[1]))
    return names
