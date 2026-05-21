"""
WSDL ↔ CLI parity gate — milestone 0.3.9 (issue #198).

This module enforces four invariants that arose as recurring bug patterns
in mutating CLI commands. Each invariant is a separate parametrized test
class so a failure pinpoints the offending command and pattern.

Pattern A — empty subtype no-op:
    A mutating command must refuse to send a payload that contains only
    the resource ID. ``bids set --keyword-id 5 --dry-run`` printing
    ``{KeywordId: 5}`` is a silent no-op against the live API.

Pattern B — silent data loss:
    A typed flag must either be accepted by the chosen ``--type`` or
    raise UsageError. ``ads update --type TEXT_AD --image-hash X`` must
    not silently discard ``--image-hash``.

Pattern C — WSDL ``minOccurs=1`` not validated:
    Item-level required fields in the WSDL must map onto a Click
    ``required=True`` option (or be derivable from defaults).

Pattern D — strategy enum drift:
    ``STRATEGY_TYPES`` in ``direct_cli/commands/strategies.py`` must equal
    the choice-of-one subtype names declared in ``StrategyAddItem``.

The gate now enforces these invariants directly. Regression failures should
be treated as WSDL/CLI parity breaks, not as expected milestone work.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli.commands.strategies import STRATEGY_TYPES
from direct_cli.smoke_matrix import commands_for_category
from direct_cli.wsdl_coverage import (
    CLI_TO_API_SERVICE,
    RUNTIME_DEPRECATED_METHODS,
    fetch_wsdl,
    get_operation_request_schema,
    get_required_item_fields,
)

# ---------------------------------------------------------------------------
# Pattern A — empty subtype no-op
# ---------------------------------------------------------------------------

# Each entry: (command_key, argv that supplies ONLY the resource ID,
# expected substring in the rejection message). The substring must
# describe the *guard reason* ("no fields", "at least one") so that
# strict-xfail in PR 2 cannot flip green from an unrelated UsageError
# like ``Missing option '--foo'`` introduced for a different reason.
EMPTY_PAYLOAD_PROBES: list[tuple[str, list[str], str]] = [
    (
        "ads.update",
        ["ads", "update", "--id", "1", "--type", "TEXT_AD"],
        "at least one",
    ),
    (
        "adgroups.update",
        ["adgroups", "update", "--id", "1"],
        "at least one",
    ),
    (
        "bids.set",
        ["bids", "set", "--keyword-id", "1"],
        "at least one",
    ),
    (
        "keywordbids.set",
        ["keywordbids", "set", "--keyword-id", "1"],
        "at least one",
    ),
    (
        "keywords.update",
        ["keywords", "update", "--id", "1"],
        "at least one",
    ),
    (
        "strategies.update",
        ["strategies", "update", "--id", "1", "--type", "AverageCpa"],
        "at least one",
    ),
]


@pytest.mark.parametrize(
    ("command_key", "argv", "expected_error"),
    EMPTY_PAYLOAD_PROBES,
    ids=[probe[0] for probe in EMPTY_PAYLOAD_PROBES],
)
def test_empty_payload_no_op_rejected(
    command_key: str, argv: list[str], expected_error: str
) -> None:
    result = CliRunner().invoke(cli, argv + ["--dry-run"])
    assert result.exit_code != 0, (
        f"{command_key}: empty payload accepted as no-op. " f"Output: {result.output!r}"
    )
    assert expected_error.lower() in result.output.lower(), (
        f"{command_key}: rejection happened but the error message lacks the "
        f"guard substring {expected_error!r}. The command must have a real "
        f"empty-payload guard, not just any Click required-option. "
        f"Output: {result.output!r}"
    )


# ---------------------------------------------------------------------------
# Pattern B — silent data loss
# ---------------------------------------------------------------------------

# A flag that does not belong to the chosen ``--type`` must raise
# UsageError rather than be silently dropped. The expected substring
# pins the rejection reason to the per-type validation so strict-xfail
# cannot flip green from an unrelated UsageError.
SILENT_LOSS_PROBES: list[tuple[str, list[str], str]] = [
    (
        "ads.update TEXT_AD + --action",
        [
            "ads",
            "update",
            "--id",
            "1",
            "--type",
            "TEXT_AD",
            "--action",
            "INSTALL",
        ],
        "--action",
    ),
    (
        "campaigns.add TEXT_CAMPAIGN + --counter-id",
        [
            "campaigns",
            "add",
            "--name",
            "C",
            "--start-date",
            "2026-04-10",
            "--type",
            "TEXT_CAMPAIGN",
            "--counter-id",
            "123",
        ],
        "--counter-id",
    ),
    (
        "adgroups.add TEXT_AD_GROUP + --domain-url",
        [
            "adgroups",
            "add",
            "--name",
            "G",
            "--campaign-id",
            "1",
            "--region-ids",
            "225",
            "--type",
            "TEXT_AD_GROUP",
            "--domain-url",
            "example.com",
        ],
        "--domain-url",
    ),
    (
        "ads.add TEXT_AD + --action",
        [
            "ads",
            "add",
            "--adgroup-id",
            "1",
            "--type",
            "TEXT_AD",
            "--title",
            "T",
            "--text",
            "Body",
            "--href",
            "https://example.com",
            "--action",
            "INSTALL",
        ],
        "--action",
    ),
    (
        "bidmodifiers.add MOBILE_ADJUSTMENT + --gender",
        [
            "bidmodifiers",
            "add",
            "--campaign-id",
            "1",
            "--type",
            "MOBILE_ADJUSTMENT",
            "--value",
            "120",
            "--gender",
            "GENDER_MALE",
        ],
        "--gender",
    ),
    (
        "strategies.add WbMaximumClicks + --average-cpc",
        [
            "strategies",
            "add",
            "--name",
            "S",
            "--type",
            "WbMaximumClicks",
            "--average-cpc",
            "1000000",
        ],
        "--average-cpc",
    ),
    (
        "strategies.update PayForConversionMultipleGoals + --goal-id",
        [
            "strategies",
            "update",
            "--id",
            "1",
            "--type",
            "PayForConversionMultipleGoals",
            "--goal-id",
            "123",
        ],
        "--goal-id",
    ),
]


@pytest.mark.parametrize(
    ("probe_id", "argv", "expected_error"),
    SILENT_LOSS_PROBES,
    ids=[probe[0] for probe in SILENT_LOSS_PROBES],
)
def test_silent_data_loss_rejected(
    probe_id: str, argv: list[str], expected_error: str
) -> None:
    result = CliRunner().invoke(cli, argv + ["--dry-run"])
    assert result.exit_code != 0, (
        f"{probe_id}: incompatible flag silently dropped. " f"Output: {result.output!r}"
    )
    assert expected_error.lower() in result.output.lower(), (
        f"{probe_id}: rejection happened but the error message does not "
        f"reference the offending flag {expected_error!r}. The command must "
        f"have per-type flag validation, not just any UsageError. "
        f"Output: {result.output!r}"
    )


# ---------------------------------------------------------------------------
# Pattern C — WSDL minOccurs=1 not validated by CLI
# ---------------------------------------------------------------------------

# Map of (cli_group, cli_op) → (api_service, wsdl_operation, container_field).
# Container is the top-level field in the WSDL request that wraps the
# repeating *Item shape — usually the plural of the resource. Listed once
# here so the parity gate can iterate every WRITE_SANDBOX mutating command
# without re-inferring the container name from the body.
COMMAND_WSDL_MAP: dict[tuple[str, str], tuple[str, str, str]] = {
    ("ads", "add"): ("ads", "add", "Ads"),
    ("ads", "update"): ("ads", "update", "Ads"),
    ("adgroups", "add"): ("adgroups", "add", "AdGroups"),
    ("adgroups", "update"): ("adgroups", "update", "AdGroups"),
    ("adextensions", "add"): ("adextensions", "add", "AdExtensions"),
    ("adimages", "add"): ("adimages", "add", "AdImages"),
    ("advideos", "add"): ("advideos", "add", "AdVideos"),
    ("audiencetargets", "add"): ("audiencetargets", "add", "AudienceTargets"),
    ("bidmodifiers", "add"): ("bidmodifiers", "add", "BidModifiers"),
    ("bidmodifiers", "set"): ("bidmodifiers", "set", "BidModifiers"),
    ("campaigns", "add"): ("campaigns", "add", "Campaigns"),
    ("campaigns", "update"): ("campaigns", "update", "Campaigns"),
    ("creatives", "add"): ("creatives", "add", "Creatives"),
    ("dynamicads", "add"): ("dynamictextadtargets", "add", "Webpages"),
    ("dynamicfeedadtargets", "add"): (
        "dynamicfeedadtargets",
        "add",
        "DynamicFeedAdTargets",
    ),
    ("feeds", "add"): ("feeds", "add", "Feeds"),
    ("feeds", "update"): ("feeds", "update", "Feeds"),
    ("keywords", "add"): ("keywords", "add", "Keywords"),
    ("keywords", "update"): ("keywords", "update", "Keywords"),
    ("negativekeywordsharedsets", "add"): (
        "negativekeywordsharedsets",
        "add",
        "NegativeKeywordSharedSets",
    ),
    ("negativekeywordsharedsets", "update"): (
        "negativekeywordsharedsets",
        "update",
        "NegativeKeywordSharedSets",
    ),
    ("retargeting", "add"): ("retargetinglists", "add", "RetargetingLists"),
    ("retargeting", "update"): ("retargetinglists", "update", "RetargetingLists"),
    ("sitelinks", "add"): ("sitelinks", "add", "SitelinksSets"),
    ("smartadtargets", "add"): ("smartadtargets", "add", "SmartAdTargets"),
    ("smartadtargets", "update"): ("smartadtargets", "update", "SmartAdTargets"),
    ("strategies", "add"): ("strategies", "add", "Strategies"),
    ("strategies", "update"): ("strategies", "update", "Strategies"),
    ("vcards", "add"): ("vcards", "add", "VCards"),
    # Commands intentionally without item-level required fields beyond
    # the wrapper. Empty value means "no WSDL required-item check".
    ("bids", "set"): ("bids", "set", "Bids"),
    ("keywordbids", "set"): ("keywordbids", "set", "KeywordBids"),
    ("clients", "update"): ("clients", "update", "Clients"),
}

# WSDL → CLI option mapping by convention. WSDL uses CamelCase, Click uses
# kebab-case. Listed manually for fields where the conversion is not
# mechanical (compound nouns, abbreviations, multi-source fields).
WSDL_FIELD_TO_CLI_OPTION: dict[str, set[str]] = {
    "AdGroupId": {"--adgroup-id", "--ad-group-id"},
    "CampaignId": {"--campaign-id"},
    "SmartTvAdjustment": {"--type"},
    "RegionIds": {"--region-ids"},
    "Name": {"--name"},
    "StartDate": {"--start-date"},
    "BusinessType": {"--business-type"},
    "SourceType": {"--url"},  # derived inside the command
    "Id": {"--id"},
    "Keyword": {"--keyword"},
    "ImageData": {"--image-data", "--image-file"},
    "BidModifier": {"--value"},
    "VideoExtensionCreative": {"--video-id"},
    "Audience": {"--audience"},
    "Sitelinks": {"--sitelink"},
    "Rules": {"--rule"},
    "NegativeKeywords": {"--keywords"},
    # vCard required block
    "Country": {"--country"},
    "City": {"--city"},
    "CompanyName": {"--company-name"},
    "WorkTime": {"--work-time"},
    "Phone": {
        "--phone-country-code",
        "--phone-city-code",
        "--phone-number",
    },
    # ads add/update typed flags introduced in issue #202
    "Title2": {"--title2"},
    "DisplayUrlPath": {"--display-url-path"},
    "Mobile": {"--mobile"},
    "VCardId": {"--vcard-id"},
    "SitelinkSetId": {"--sitelink-set-id"},
    "TurboPageId": {"--turbo-page-id"},
    "AdExtensionIds": {"--ad-extensions"},
}

# Fields whose required-ness is enforced inside the command body rather
# than via Click ``required=True``. Each entry is the substring that must
# appear in the CLI's UsageError when the field is missing — the gate
# invokes the command without the relevant flags and asserts the error.
INTERNAL_VALIDATION: dict[tuple[str, str, str], str] = {
    (
        "adimages",
        "add",
        "ImageData",
    ): "Provide exactly one of --image-data or --image-file",
    ("bidmodifiers", "set", "Id"): "Provide --id with --value",
    ("bidmodifiers", "set", "BidModifier"): "Missing option '--value'",
    ("retargeting", "add", "Rules"): "Provide at least one --rule",
    ("creatives", "add", "VideoExtensionCreative"): "Missing option '--video-id'",
    ("keywords", "add", "Keyword"): "Provide exactly one of: --keyword",
    ("keywords", "add", "AdGroupId"): "Provide exactly one of: --keyword",
    ("sitelinks", "add", "Sitelinks"): "Provide exactly one of: --sitelink",
}


def _click_command(group_name: str, command_name: str):
    group = cli.commands.get(group_name)
    if group is None or not hasattr(group, "commands"):
        return None
    return group.commands.get(command_name)


def _click_required_options(command) -> set[str]:
    required = set()
    for param in command.params:
        if getattr(param, "required", False):
            for opt in getattr(param, "opts", []):
                required.add(opt)
    return required


@pytest.mark.parametrize(
    "command_key",
    sorted(COMMAND_WSDL_MAP),
    ids=lambda val: ".".join(val),
)
def test_wsdl_required_fields_have_cli_options(
    command_key: tuple[str, str],
) -> None:
    cli_group, cli_op = command_key
    api_service, wsdl_op, container = COMMAND_WSDL_MAP[command_key]
    schema = get_operation_request_schema(fetch_wsdl(api_service), wsdl_op)
    container_names = {field["name"] for field in schema.get("fields", [])}
    assert container in container_names, (
        f"{cli_group}.{cli_op}: COMMAND_WSDL_MAP points at container "
        f"{container!r} but the WSDL request schema for "
        f"{api_service}.{wsdl_op} only declares {sorted(container_names)}. "
        f"Fix the mapping or refresh tests/wsdl_cache/{api_service}.xml."
    )
    wsdl_required = get_required_item_fields(schema, container)
    if not wsdl_required:
        pytest.skip(f"{cli_group}.{cli_op}: WSDL declares no required item fields")

    cli_command = _click_command(cli_group, cli_op)
    assert cli_command is not None, f"CLI command not registered: {command_key}"
    cli_required = _click_required_options(cli_command)

    unmapped = [
        field for field in wsdl_required if field not in WSDL_FIELD_TO_CLI_OPTION
    ]
    assert not unmapped, (
        f"{cli_group}.{cli_op}: WSDL required field(s) {unmapped} "
        "have no entry in WSDL_FIELD_TO_CLI_OPTION. "
        "Add the mapping so the gate can check Click coverage."
    )

    missing = []
    for field in wsdl_required:
        expected_opts = WSDL_FIELD_TO_CLI_OPTION[field]
        if expected_opts & cli_required:
            continue
        # Internal-body validation counts as required-ness too. Skip the
        # field if the command is in INTERNAL_VALIDATION; the dedicated
        # ``test_internal_validation_rejects_missing_field`` exercises
        # that the error is actually raised.
        if (cli_group, cli_op, field) in INTERNAL_VALIDATION:
            continue
        missing.append((field, sorted(expected_opts)))

    assert not missing, (
        f"{cli_group}.{cli_op}: WSDL minOccurs=1 fields not marked Click required: "
        f"{missing}. Either add ``required=True`` to the option, "
        "or add a UsageError check in the command body, "
        "or update WSDL_FIELD_TO_CLI_OPTION if the option name differs."
    )


# Smoke-test that the INTERNAL_VALIDATION entries are accurate — running
# the command without the required field actually yields the documented
# error. Without this check a typo in the expected substring would let
# the parity gate falsely pass.
INTERNAL_VALIDATION_PROBES: dict[tuple[str, str, str], list[str]] = {
    ("adimages", "add", "ImageData"): ["adimages", "add", "--name", "X"],
    ("bidmodifiers", "set", "Id"): ["bidmodifiers", "set", "--value", "50"],
    ("bidmodifiers", "set", "BidModifier"): ["bidmodifiers", "set", "--id", "1"],
    ("retargeting", "add", "Rules"): ["retargeting", "add", "--name", "X"],
    ("creatives", "add", "VideoExtensionCreative"): ["creatives", "add"],
    ("keywords", "add", "Keyword"): ["keywords", "add"],
    ("keywords", "add", "AdGroupId"): ["keywords", "add"],
    ("sitelinks", "add", "Sitelinks"): ["sitelinks", "add"],
}


@pytest.mark.parametrize(
    "field_key",
    sorted(INTERNAL_VALIDATION),
    ids=lambda val: ".".join(val[:2]) + "/" + val[2],
)
def test_internal_validation_rejects_missing_field(
    field_key: tuple[str, str, str],
) -> None:
    expected_error = INTERNAL_VALIDATION[field_key]
    argv = INTERNAL_VALIDATION_PROBES[field_key]
    result = CliRunner().invoke(cli, argv + ["--dry-run"])
    assert result.exit_code != 0, (
        f"{'.'.join(field_key[:2])}: invocation {argv} unexpectedly succeeded "
        f"without the field {field_key[2]}. Output: {result.output!r}"
    )
    assert expected_error in result.output, (
        f"{'.'.join(field_key[:2])}: expected error containing "
        f"{expected_error!r} for missing {field_key[2]}, got {result.output!r}"
    )


# ---------------------------------------------------------------------------
# Pattern D — strategy enum drift
# ---------------------------------------------------------------------------


def _wsdl_strategy_subtype_names() -> list[str]:
    """Return choice-of-one subtype field names from ``StrategyAddItem``.

    The WSDL declares each per-strategy block as an element whose type
    is ``Strategy*AddItem`` (e.g. ``StrategyAverageCpcAddItem``). Scalar
    fields like ``Name`` / ``CounterIds`` use built-in or shared types,
    so a stable filter is "type name ends with ``AddItem``". This keeps
    the gate honest if Yandex adds a new scalar to ``StrategyAddItem``
    or renames a subtype.
    """
    schema = get_operation_request_schema(fetch_wsdl("strategies"), "add")
    strategies_field = next(
        (f for f in schema["fields"] if f["name"] == "Strategies"), None
    )
    assert strategies_field is not None, (
        "WSDL drift: strategies.add request schema has no top-level "
        "'Strategies' field. Refresh tests/wsdl_cache/strategies.xml "
        "and update the gate."
    )
    return [
        itf["name"]
        for itf in (strategies_field.get("item_fields") or [])
        if (itf.get("type") or "").endswith("AddItem")
    ]


def test_strategy_types_match_wsdl() -> None:
    wsdl_types = set(_wsdl_strategy_subtype_names())
    cli_types = set(STRATEGY_TYPES)
    bogus = cli_types - wsdl_types
    missing = wsdl_types - cli_types
    assert not bogus and not missing, (
        "STRATEGY_TYPES drift from WSDL:\n"
        f"  CLI-only (bogus): {sorted(bogus)}\n"
        f"  WSDL-only (missing): {sorted(missing)}\n"
        "Update direct_cli/commands/strategies.py to match StrategyAddItem."
    )


# ---------------------------------------------------------------------------
# Coverage check — every mutating WRITE_SANDBOX command is accounted for
# ---------------------------------------------------------------------------


def _mutating_commands() -> list[str]:
    """Return WRITE_SANDBOX commands likely to need parity gates.

    The gate is meaningful for ``add``/``update``/``set`` style operations.
    Multi-target setter variants (``set-bids``, ``set-auto``) wrap selection
    criteria differently and are evaluated by separate dry-run tests.
    """
    return [
        cmd
        for cmd in commands_for_category("WRITE_SANDBOX")
        if cmd.split(".", 1)[1] in {"add", "update", "set"}
    ]


def _is_runtime_deprecated(cli_command: str) -> bool:
    """Test whether a CLI command maps to a RUNTIME_DEPRECATED API method.

    ``RUNTIME_DEPRECATED_METHODS`` is keyed by ``(api_service, wsdl_op)``
    while CLI commands use the CLI group name. For groups whose name
    differs from the API service (e.g. CLI ``retargeting`` →
    API ``retargetinglists``) the lookup must go through
    ``CLI_TO_API_SERVICE`` first or it silently misses.
    """
    cli_group, cli_op = cli_command.split(".", 1)
    api_service = CLI_TO_API_SERVICE.get(cli_group, cli_group)
    return (api_service, cli_op) in RUNTIME_DEPRECATED_METHODS


def test_command_wsdl_map_covers_known_mutating_commands() -> None:
    """Force new mutating commands to be evaluated against the parity gate.

    Any ``add``/``update``/``set`` command in ``WRITE_SANDBOX`` that is not
    in ``COMMAND_WSDL_MAP`` slips past the WSDL ↔ CLI parity check.
    """
    declared = {f"{group}.{op}" for group, op in COMMAND_WSDL_MAP}
    relevant = {cmd for cmd in _mutating_commands() if not _is_runtime_deprecated(cmd)}
    missing = sorted(relevant - declared)
    assert not missing, (
        "New mutating commands lack a COMMAND_WSDL_MAP entry:\n"
        f"  {missing}\n"
        "Add (cli_group, cli_op) → (api_service, wsdl_op, container_field)."
    )
