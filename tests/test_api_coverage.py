"""
API coverage tests — verify CLI coverage against Yandex Direct API v5 WSDL.

Phase 1: For each CLI service, check that all WSDL operations are covered.
Phase 2: Detect new API services not yet covered by the CLI.

Uses cached WSDL files in tests/wsdl_cache/ — no network required in CI.
"""

import pytest

from direct_cli.wsdl_coverage import (
    CLI_TO_API_SERVICE,
    CANONICAL_API_SERVICES,
    KNOWN_MISSING_SERVICES,
    fetch_wsdl,
    get_cli_methods_for_service,
    parse_wsdl_operations,
)

# API methods that exist in WSDL but the CLI does not implement.
# When one is fixed, remove it from this set and the test will still pass.
KNOWN_MISSING_METHODS = {
    ("agencyclients", "addPassportOrganization"),
    ("agencyclients", "addPassportOrganizationMember"),
    ("agencyclients", "update"),
    ("audiencetargets", "setBids"),
    ("bids", "setAuto"),
    ("creatives", "add"),
    ("dictionaries", "getGeoRegions"),
    ("dynamicads", "resume"),
    ("dynamicads", "setBids"),
    ("dynamicads", "suspend"),
    ("keywordbids", "setAuto"),
    ("retargeting", "update"),
    ("smartadtargets", "resume"),
    ("smartadtargets", "setBids"),
    ("smartadtargets", "suspend"),
}

# CLI methods that have no WSDL counterpart but are intentionally present.
ALLOWED_EXTRA_METHODS = {
    ("bidmodifiers", "toggle"),  # JSON-only API method (not in WSDL)
    ("agencyclients", "delete"),  # CLI-side guard that blocks with error
}

# CLI methods that have no WSDL counterpart and may indicate bugs.
# keywords archive/unarchive: WSDL only exposes suspend/resume for keywords
# dynamicads update: dynamictextadtargets WSDL has no update operation
# keywordsresearch get: WSDL has no 'get' (only deduplicate, hasSearchVolume)
KNOWN_EXTRA_CLI_METHODS = {
    ("keywords", "archive"),
    ("keywords", "unarchive"),
    ("dynamicads", "update"),
    ("keywordsresearch", "get"),
}


@pytest.mark.api_coverage
class TestApiCoverage:
    """Verify CLI coverage against Yandex Direct API v5 WSDL."""

    def test_no_missing_services(self):
        """Phase 2: every known API v5 service must be covered by the CLI.

        Fails when Yandex adds a new service that direct-cli does not
        yet implement.  Add a CLI command or update KNOWN_MISSING_SERVICES.
        """
        covered_services = set(CLI_TO_API_SERVICE.values())
        all_known = set(CANONICAL_API_SERVICES)
        missing = all_known - covered_services

        # Remove services we already know about
        unaccounted = missing - KNOWN_MISSING_SERVICES

        assert unaccounted == set(), (
            f"New API services detected (not in CLI and not in "
            f"KNOWN_MISSING_SERVICES): {sorted(unaccounted)}. "
            f"Add CLI commands or update KNOWN_MISSING_SERVICES."
        )

    def test_service_method_coverage(self):
        """Phase 1: for each CLI service, verify method coverage vs WSDL."""
        failures = []

        for cli_name, api_service in sorted(CLI_TO_API_SERVICE.items()):
            try:
                wsdl_xml = fetch_wsdl(api_service)
            except Exception as exc:
                failures.append(
                    f"{cli_name} -> {api_service}: WSDL fetch failed: {exc}"
                )
                continue

            api_methods = set(parse_wsdl_operations(wsdl_xml))
            cli_methods = get_cli_methods_for_service(cli_name)

            missing = api_methods - cli_methods
            extra = cli_methods - api_methods

            # Subtract known gaps
            real_missing = {
                m for m in missing if (cli_name, m) not in KNOWN_MISSING_METHODS
            }
            real_extra = {
                m
                for m in extra
                if (cli_name, m) not in ALLOWED_EXTRA_METHODS
                and (cli_name, m) not in KNOWN_EXTRA_CLI_METHODS
            }

            if real_missing:
                failures.append(
                    f"{cli_name} -> {api_service}: MISSING API methods "
                    f"(not in KNOWN_MISSING_METHODS): {sorted(real_missing)}"
                )
            if real_extra:
                failures.append(
                    f"{cli_name} -> {api_service}: EXTRA CLI methods "
                    f"(not in ALLOWED_EXTRA_METHODS or "
                    f"KNOWN_EXTRA_CLI_METHODS): {sorted(real_extra)}"
                )

        assert failures == [], "API coverage gaps detected:\n" + "\n".join(failures)
