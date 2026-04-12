"""
WSDL coverage utilities for Direct CLI.

Fetches and parses Yandex Direct API v5 WSDL definitions to verify
that the CLI implements all available services and methods.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

WSDL_BASE_URL = "https://api.direct.yandex.com/v5/{service}?wsdl"
CACHE_DIR = Path(__file__).resolve().parent.parent / "tests" / "wsdl_cache"

# ---------------------------------------------------------------------------
# Mappings
# ---------------------------------------------------------------------------

# CLI command name -> API WSDL service name.
# Most are 1:1; divergent mappings are commented.
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

# Services that use the JSON API (no WSDL) — excluded from WSDL coverage.
NON_WSDL_SERVICES = {"reports"}

# All known Yandex Direct API v5 WSDL services.
# Ground truth for Phase 2 "new service" detection.
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

# API services known to be missing from the CLI entirely.
KNOWN_MISSING_SERVICES = set()

# CLI subcommand name -> API method name overrides.
# Most subcommands map 1:1 (get->get, add->add).
METHOD_NAME_OVERRIDES = {
    "check-campaigns": "checkCampaigns",
    "checkcamp": "checkCampaigns",
    "check-dictionaries": "checkDictionaries",
    "checkdict": "checkDictionaries",
    "has-search-volume": "hasSearchVolume",
    "has-volume": "hasSearchVolume",
    "list": "get",
    "list-names": "get",
    "list-types": "get",
}

# ---------------------------------------------------------------------------
# WSDL fetching & parsing
# ---------------------------------------------------------------------------


def fetch_wsdl(service_name: str, use_cache: bool = True) -> str:
    """Fetch WSDL XML for a service.

    If *use_cache* is True and a cached file exists, reads from disk.
    Otherwise fetches from the Yandex API, writes to cache, and returns XML.
    """
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
    """Extract unique API method names from WSDL XML.

    Parses ``<wsdl:operation name="...">`` elements and returns a sorted
    list of unique operation names.
    """
    root = ET.fromstring(wsdl_xml)
    ns = {"wsdl": "http://schemas.xmlsoap.org/wsdl/"}
    ops = set()
    for op in root.findall(".//wsdl:operation", ns):
        name = op.get("name")
        if name:
            ops.add(name)
    return sorted(ops)


def get_cli_methods_for_service(cli_command_name: str) -> set:
    """Get the set of API method names that a CLI service implements.

    Imports the CLI, finds the Click group, iterates its subcommands,
    and maps each subcommand name to the API method name.
    """
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
    """Fetch fresh WSDLs for all known services and write to cache.

    Returns a dict ``{service_name: exception}`` for any failures.
    Services with no error are not in the dict.
    """
    all_services = set(CANONICAL_API_SERVICES) | set(CLI_TO_API_SERVICE.values())
    all_services -= NON_WSDL_SERVICES

    errors = {}
    for service in sorted(all_services):
        try:
            fetch_wsdl(service, use_cache=False)
        except Exception as exc:
            errors[service] = exc
    return errors
