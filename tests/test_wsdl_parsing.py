"""Parsing reuse must preserve fresh, independent public WSDL results."""

import xml.etree.ElementTree as ET
from unittest.mock import patch

import pytest

from direct_cli import wsdl_coverage


@pytest.fixture
def wsdl_xml() -> str:
    """A small schema with namespaces, enums and nested request fields."""
    return """<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/"
        xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:tns="urn:parsing-test">
      <wsdl:message name="getRequest">
        <wsdl:part name="parameters" element="tns:get" />
      </wsdl:message>
      <wsdl:portType>
        <wsdl:operation name="get"><wsdl:input message="tns:getRequest" /></wsdl:operation>
      </wsdl:portType>
      <xsd:schema targetNamespace="urn:parsing-test">
        <xsd:simpleType name="ItemFieldEnum"><xsd:restriction base="xsd:string">
          <xsd:enumeration value="Id" /><xsd:enumeration value="Name" />
        </xsd:restriction></xsd:simpleType>
        <xsd:complexType name="Item"><xsd:sequence>
          <xsd:element name="Id" type="xsd:long" />
        </xsd:sequence></xsd:complexType>
        <xsd:element name="get"><xsd:complexType><xsd:sequence>
          <xsd:element name="FieldNames" type="tns:ItemFieldEnum" maxOccurs="unbounded" />
          <xsd:element name="Items" type="tns:Item" maxOccurs="unbounded" />
        </xsd:sequence></xsd:complexType></xsd:element>
      </xsd:schema>
    </wsdl:definitions>"""


def test_schema_and_enum_checks_reuse_the_same_xml_parse(wsdl_xml: str) -> None:
    wsdl_coverage._parse_xml.cache_clear()
    with patch.object(ET, "iterparse", wraps=ET.iterparse) as parse:
        for _ in range(2):
            assert wsdl_coverage.parse_wsdl_operations(wsdl_xml) == ["get"]
            schema = wsdl_coverage.get_operation_request_schema(wsdl_xml, "get")
            assert schema["fields"][1]["item_fields"][0]["name"] == "Id"
            enums = wsdl_coverage.get_operation_field_name_enums(wsdl_xml, "get")
            assert enums["FieldNames"]["values"] == ["Id", "Name"]
        assert parse.call_count == 1


def test_callers_cannot_mutate_subsequent_schema_or_enum_results(wsdl_xml: str) -> None:
    expected_schema = wsdl_coverage.get_operation_request_schema(wsdl_xml, "get")
    schema = wsdl_coverage.get_operation_request_schema(wsdl_xml, "get")
    schema["fields"][1]["item_fields"][0]["name"] = "Changed"
    schema["fields"].clear()
    enums = wsdl_coverage.get_operation_field_name_enums(wsdl_xml, "get")
    enums["FieldNames"]["values"].append("Changed")
    wsdl_coverage.parse_wsdl_field_enums(wsdl_xml)["ItemFieldEnum"].clear()
    wsdl_coverage.parse_wsdl_operations(wsdl_xml).clear()

    assert (
        wsdl_coverage.get_operation_request_schema(wsdl_xml, "get") == expected_schema
    )
    assert wsdl_coverage.get_operation_field_name_enums(wsdl_xml, "get") == {
        "FieldNames": {"enum_type": "ItemFieldEnum", "values": ["Id", "Name"]}
    }
    assert wsdl_coverage.parse_wsdl_operations(wsdl_xml) == ["get"]


def test_changed_xml_content_is_visible_without_clearing_cache(wsdl_xml: str) -> None:
    assert wsdl_coverage.get_operation_field_name_enums(wsdl_xml, "get")["FieldNames"][
        "values"
    ] == ["Id", "Name"]
    changed = wsdl_xml.replace('value="Name"', 'value="Title"')
    assert wsdl_coverage.get_operation_field_name_enums(changed, "get")["FieldNames"][
        "values"
    ] == ["Id", "Title"]


def test_malformed_xml_still_raises_parse_error() -> None:
    with pytest.raises(ET.ParseError):
        wsdl_coverage.parse_wsdl_operations("<unclosed>")
