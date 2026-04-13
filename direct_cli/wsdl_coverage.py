"""
WSDL coverage utilities for Direct CLI.

Fetches and parses Yandex Direct API v5 WSDL definitions to verify
that the CLI implements all available services and methods.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

WSDL_BASE_URL = "https://api.direct.yandex.com/v5/{service}?wsdl"
CACHE_DIR = Path(__file__).resolve().parent.parent / "tests" / "wsdl_cache"

# ---------------------------------------------------------------------------
# Mappings
# ---------------------------------------------------------------------------

CLI_TO_API_SERVICE = {
    "campaigns": "campaigns",
    "adgroups": "adgroups",
    "ads": "ads",
    "keywords": "keywords",
    "keywordbids": "keywordbids",
    "bids": "bids",
    "bidmodifiers": "bidmodifiers",
    "audiencetargets": "audiencetargets",
    "retargeting": "retargetinglists",
    "creatives": "creatives",
    "adimages": "adimages",
    "advideos": "advideos",
    "adextensions": "adextensions",
    "sitelinks": "sitelinks",
    "vcards": "vcards",
    "leads": "leads",
    "clients": "clients",
    "agencyclients": "agencyclients",
    "dictionaries": "dictionaries",
    "changes": "changes",
    "turbopages": "turbopages",
    "negativekeywordsharedsets": "negativekeywordsharedsets",
    "feeds": "feeds",
    "smartadtargets": "smartadtargets",
    "businesses": "businesses",
    "keywordsresearch": "keywordsresearch",
    "dynamicads": "dynamictextadtargets",
    # reports excluded — uses JSON API, not WSDL
}

NON_WSDL_SERVICES = {"reports"}

# Canonical CLI alias groups exposed for integrations. These are intentional
# aliases of real CLI groups and should not count as extra API surface.
CLI_ALIAS_GROUPS = {
    "dynamictargets": "dynamicads",
    "smarttargets": "smartadtargets",
    "negativekeywords": "negativekeywordsharedsets",
}

# Non-WSDL service coverage policies. These services still belong to the
# supported API surface, but they require bespoke contract checks rather than
# SOAP/WSDL parity tests.
NON_WSDL_SERVICE_POLICIES = {
    "reports": {
        "kind": "json-api",
        "coverage": "contract-tests+spec-snapshot",
        "spec_snapshot": "tests/reports_cache/spec.json",
        "raw_sources": "tests/reports_cache/raw/",
        "drift_script": "scripts/check_reports_drift.py",
        "refresh_script": "scripts/refresh_reports_cache.py",
        "reason": (
            "Yandex Direct reports use the JSON reporting API. "
            "Coverage mirrors WSDL parity via HTML-doc spec snapshot."
        ),
    }
}

CANONICAL_API_SERVICES = sorted(
    [
        "adextensions",
        "adgroups",
        "adimages",
        "ads",
        "advideos",
        "agencyclients",
        "audiencetargets",
        "bids",
        "bidmodifiers",
        "businesses",
        "campaigns",
        "changes",
        "clients",
        "creatives",
        "dictionaries",
        "dynamictextadtargets",
        "feeds",
        "keywordbids",
        "keywords",
        "keywordsresearch",
        "leads",
        "negativekeywordsharedsets",
        "retargetinglists",
        "sitelinks",
        "smartadtargets",
        "turbopages",
        "vcards",
    ]
)

KNOWN_MISSING_SERVICES = set()

# Intentional CLI-only methods that are not 1:1 SOAP WSDL operations.
# They remain part of the supported CLI UX and must be documented explicitly.
INTENTIONAL_EXTRA_METHODS = {
    ("agencyclients", "delete"): (
        "CLI guard command: the Yandex Direct API does not support deleting "
        "agency clients, so the command aborts with an explicit message."
    ),
    ("bidmodifiers", "toggle"): (
        "JSON-only helper command; no matching SOAP/WSDL operation exists."
    ),
    ("keywords", "archive"): (
        "Legacy lifecycle command preserved for compatibility with existing CLI users."
    ),
    ("keywords", "unarchive"): (
        "Legacy lifecycle command preserved for compatibility with existing CLI users."
    ),
}

METHOD_NAME_OVERRIDES = {
    "add-passport-organization": "addPassportOrganization",
    "add-passport-organization-member": "addPassportOrganizationMember",
    "check-campaigns": "checkCampaigns",
    "checkcamp": "checkCampaigns",
    "check-dictionaries": "checkDictionaries",
    "checkdict": "checkDictionaries",
    "get-geo-regions": "getGeoRegions",
    "has-search-volume": "hasSearchVolume",
    "has-volume": "hasSearchVolume",
    "list": "get",
    "list-names": "get",
    "list-types": "get",
    "set-auto": "setAuto",
    "set-bids": "setBids",
}


def fetch_wsdl(service_name: str, use_cache: bool = True) -> str:
    """Fetch WSDL XML for a service."""
    cache_file = CACHE_DIR / f"{service_name}.xml"

    if use_cache and cache_file.exists():
        return cache_file.read_text(encoding="utf-8")

    import requests

    url = WSDL_BASE_URL.format(service=service_name)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()

    xml_text = resp.text

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(xml_text, encoding="utf-8")

    return xml_text


def parse_wsdl_operations(wsdl_xml: str) -> list:
    """Extract unique API method names from WSDL XML."""
    root = ET.fromstring(wsdl_xml)
    ns = {"wsdl": "http://schemas.xmlsoap.org/wsdl/"}
    ops = set()
    for op in root.findall(".//wsdl:operation", ns):
        name = op.get("name")
        if name:
            ops.add(name)
    return sorted(ops)


def get_cli_methods_for_service(cli_command_name: str) -> set:
    """Get the set of API method names that a CLI service implements."""
    from direct_cli.cli import cli

    group = cli.commands[cli_command_name]
    methods = set()
    for subcmd_name in group.commands:
        mapped = METHOD_NAME_OVERRIDES.get(subcmd_name)
        if mapped:
            methods.add(mapped)
        else:
            methods.add(subcmd_name)
    return methods


def refresh_all_caches() -> dict:
    """Fetch fresh WSDLs for all known services and write to cache."""
    all_services = set(CANONICAL_API_SERVICES) | set(CLI_TO_API_SERVICE.values())
    all_services -= NON_WSDL_SERVICES

    errors = {}
    for service in sorted(all_services):
        try:
            fetch_wsdl(service, use_cache=False)
        except Exception as exc:
            errors[service] = exc
    return errors


def get_api_coverage_policy() -> dict:
    """Return a machine-readable summary of the API coverage model."""
    return {
        "wsdl_base_url": WSDL_BASE_URL,
        "wsdl_services": dict(sorted(CLI_TO_API_SERVICE.items())),
        "canonical_api_services": list(CANONICAL_API_SERVICES),
        "non_wsdl_services": NON_WSDL_SERVICE_POLICIES,
        "cli_alias_groups": dict(sorted(CLI_ALIAS_GROUPS.items())),
        "intentional_extra_methods": {
            f"{service}.{method}": reason
            for (service, method), reason in sorted(INTENTIONAL_EXTRA_METHODS.items())
        },
    }


def _local_name(qname: str | None) -> str | None:
    """Return the local part of a QName-like ``prefix:name`` string."""
    if qname is None:
        return None
    return qname.split(":", 1)[1] if ":" in qname else qname


def _collect_complex_type_fields(complex_types: dict, type_name: str) -> list[dict]:
    """Collect fields from a local XSD complex type, following local inheritance."""
    ns = {"xsd": "http://www.w3.org/2001/XMLSchema"}
    complex_type = complex_types.get(type_name)
    if complex_type is None:
        return []

    fields = []
    extension = complex_type.find("xsd:complexContent/xsd:extension", ns)
    if extension is not None:
        base_type = _local_name(extension.get("base"))
        if base_type and base_type in complex_types:
            fields.extend(_collect_complex_type_fields(complex_types, base_type))
        sequence = extension.find("xsd:sequence", ns)
    else:
        sequence = complex_type.find("xsd:sequence", ns)

    if sequence is None:
        return fields

    for child in sequence.findall("xsd:element", ns):
        fields.append(
            {
                "name": child.get("name"),
                "type": _local_name(child.get("type")),
                "min_occurs": int(child.get("minOccurs", "1")),
                "max_occurs": child.get("maxOccurs", "1"),
            }
        )
    return fields


def get_operation_request_schema(wsdl_xml: str, operation_name: str) -> dict:
    """Return request schema metadata for a WSDL operation.

    Known limitations (documented rather than silent):
    - Types declared in imported XSD namespaces (``<xsd:import>``) are not
      resolved: ``item_fields`` for any field whose type lives in another
      namespace is ``[]``. Nested required-field validation therefore only
      applies to locally-defined inline types.
    - When a request element uses ``xsd:complexContent/xsd:extension``, only
      fields from the extension's own ``xsd:sequence`` are returned; inherited
      base-type fields are dropped. Safe today because no ``get*`` operation
      (the typical extension user) is included in payload coverage tests.
    """
    root = ET.fromstring(wsdl_xml)
    ns = {
        "wsdl": "http://schemas.xmlsoap.org/wsdl/",
        "xsd": "http://www.w3.org/2001/XMLSchema",
    }

    schema = root.find(".//xsd:schema", ns)
    if schema is None:
        raise ValueError("WSDL schema section not found")

    messages = {}
    for message in root.findall(".//wsdl:message", ns):
        part = message.find("wsdl:part", ns)
        if part is not None:
            messages[message.get("name")] = _local_name(part.get("element"))

    operation = None
    for op in root.findall(".//wsdl:portType/wsdl:operation", ns):
        if op.get("name") == operation_name:
            operation = op
            break
    if operation is None:
        raise KeyError(f"Operation not found in WSDL: {operation_name}")

    input_ref = operation.find("wsdl:input", ns)
    if input_ref is None:
        raise ValueError(f"Operation has no input message: {operation_name}")

    message_name = _local_name(input_ref.get("message"))
    element_name = messages.get(message_name)
    if element_name is None:
        raise KeyError(f"Input element not found for operation: {operation_name}")

    elements = {elem.get("name"): elem for elem in schema.findall("xsd:element", ns)}
    complex_types = {
        ctype.get("name"): ctype for ctype in schema.findall("xsd:complexType", ns)
    }

    element = elements.get(element_name)
    if element is None:
        raise KeyError(f"Input element schema not found: {element_name}")

    complex_type = element.find("xsd:complexType", ns)
    if complex_type is None:
        raise ValueError(f"Input element has no inline complex type: {element_name}")

    extension = complex_type.find("xsd:complexContent/xsd:extension", ns)
    sequence = extension.find("xsd:sequence", ns) if extension is not None else complex_type.find("xsd:sequence", ns)

    fields = []
    if sequence is not None:
        for child in sequence.findall("xsd:element", ns):
            type_name = _local_name(child.get("type"))
            fields.append(
                {
                    "name": child.get("name"),
                    "type": type_name,
                    "min_occurs": int(child.get("minOccurs", "1")),
                    "max_occurs": child.get("maxOccurs", "1"),
                    "item_fields": _collect_complex_type_fields(complex_types, type_name),
                }
            )

    return {"input_element": element_name, "fields": fields}
