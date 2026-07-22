"""Dry-run payload tests for ``clients`` and ``agencyclients``.

Split out of the historical monolithic ``tests/test_dry_run.py`` (issue #604).
See :mod:`tests.test_dry_run_shared` for the shared invocation helpers and
``tests/test_dry_run.py`` for the rationale behind the whole suite.
"""

import pytest
from click.testing import CliRunner

from direct_cli.cli import cli
from tests.test_dry_run_shared import _dry_run, _read_dry_run, _rejected


def test_agencyclients_add_is_runtime_deprecated_even_for_dry_run():
    result = CliRunner().invoke(
        cli,
        [
            "agencyclients",
            "add",
            "--login",
            "client-login",
            "--first-name",
            "Alice",
            "--last-name",
            "Smith",
            "--currency",
            "RUB",
            "--notification-email",
            "ops@example.com",
            "--notification-lang",
            "RU",
            "--send-account-news",
            "--no-send-warnings",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "add-passport-organization" in result.output


def test_clients_update_payload_matches_wsdl_contract():
    body = _dry_run(
        "clients",
        "update",
        "--client-info",
        "Important client",
        "--phone",
        "+70000000000",
        "--notification-email",
        "user@example.com",
        "--notification-lang",
        "EN",
        "--email-subscription",
        "RECEIVE_RECOMMENDATIONS=YES",
        "--setting",
        "DISPLAY_STORE_RATING=NO",
        "--tin-type",
        "LEGAL",
        "--tin",
        "1234567890",
    )
    assert body["method"] == "update"
    client = body["params"]["Clients"][0]
    assert client == {
        "ClientInfo": "Important client",
        "Phone": "+70000000000",
        "Notification": {
            "Email": "user@example.com",
            "Lang": "EN",
            "EmailSubscriptions": [
                {"Option": "RECEIVE_RECOMMENDATIONS", "Value": "YES"}
            ],
        },
        "Settings": [{"Option": "DISPLAY_STORE_RATING", "Value": "NO"}],
        "TinInfo": {"TinType": "LEGAL", "Tin": "1234567890"},
    }
    assert "ClientId" not in client
    assert "Email" not in client
    assert "Fax" not in client
    assert "City" not in client


def test_clients_update_rejects_legacy_flags():
    for flag, value in (
        ("--client-id", "999"),
        ("--email", "user@example.com"),
        ("--fax", "+70000000001"),
        ("--city", "Moscow"),
    ):
        result = CliRunner().invoke(
            cli,
            ["clients", "update", flag, value, "--phone", "+70000000000", "--dry-run"],
        )
        assert result.exit_code != 0
        assert "No such option" in result.output
        assert flag in result.output


def test_clients_update_requires_at_least_one_field():
    result = CliRunner().invoke(cli, ["clients", "update", "--dry-run"])
    assert result.exit_code != 0
    assert "Provide at least one field to update" in result.output


def test_clients_update_notification_only_payload():
    body = _dry_run(
        "clients",
        "update",
        "--notification-email",
        "user@example.com",
        "--notification-lang",
        "EN",
        "--email-subscription",
        "TRACK_POSITION_CHANGES=NO",
    )
    assert body["params"]["Clients"][0] == {
        "Notification": {
            "Email": "user@example.com",
            "Lang": "EN",
            "EmailSubscriptions": [{"Option": "TRACK_POSITION_CHANGES", "Value": "NO"}],
        }
    }


def test_clients_update_repeated_subscription_and_setting_items():
    body = _dry_run(
        "clients",
        "update",
        "--email-subscription",
        "RECEIVE_RECOMMENDATIONS=YES",
        "--email-subscription",
        "TRACK_POSITION_CHANGES=NO",
        "--setting",
        "DISPLAY_STORE_RATING=NO",
        "--setting",
        "CORRECT_TYPOS_AUTOMATICALLY=YES",
    )
    assert body["params"]["Clients"][0] == {
        "Notification": {
            "EmailSubscriptions": [
                {"Option": "RECEIVE_RECOMMENDATIONS", "Value": "YES"},
                {"Option": "TRACK_POSITION_CHANGES", "Value": "NO"},
            ],
        },
        "Settings": [
            {"Option": "DISPLAY_STORE_RATING", "Value": "NO"},
            {"Option": "CORRECT_TYPOS_AUTOMATICALLY", "Value": "YES"},
        ],
    }


def test_clients_update_erir_organization_payload():
    body = _dry_run(
        "clients",
        "update",
        "--erir-organization-name",
        "Advertiser LLC",
        "--erir-organization-kpp",
        "770101001",
        "--erir-organization-epay-number",
        "epay123",
        "--erir-organization-reg-number",
        "1027700132195",
        "--erir-organization-oksm-number",
        "643",
        "--erir-organization-okved-code",
        "62.01",
    )
    assert body["params"]["Clients"][0] == {
        "ErirAttributes": {
            "Organization": {
                "Name": "Advertiser LLC",
                "Kpp": "770101001",
                "EpayNumber": "epay123",
                "RegNumber": "1027700132195",
                "OksmNumber": "643",
                "OkvedCode": "62.01",
            }
        }
    }


def test_clients_update_erir_contract_payload():
    body = _dry_run(
        "clients",
        "update",
        "--erir-contract-number",
        "C-2026-01",
        "--erir-contract-date",
        "2026-01-15",
        "--erir-contract-type",
        "contract",
        "--erir-contract-action-type",
        "commercial",
        "--erir-contract-subject-type",
        "representation",
        "--erir-contract-is-agency-payment",
        "no",
        "--erir-contract-price-amount",
        "120000.5",
        "--erir-contract-price-including-vat",
        "yes",
    )
    assert body["params"]["Clients"][0] == {
        "ErirAttributes": {
            "Contract": {
                "Number": "C-2026-01",
                "Date": "2026-01-15",
                "Type": "CONTRACT",
                "ActionType": "COMMERCIAL",
                "SubjectType": "REPRESENTATION",
                "IsAgencyPayment": "NO",
                "Price": {"Amount": 120000.5, "IncludingVat": "YES"},
            }
        }
    }


def test_clients_update_erir_contract_partial_payload():
    body = _dry_run(
        "clients",
        "update",
        "--erir-contract-number",
        "C-2026-01",
    )
    assert body["params"]["Clients"][0] == {
        "ErirAttributes": {"Contract": {"Number": "C-2026-01"}}
    }


def test_clients_update_erir_contract_price_requires_amount_and_vat():
    for args, missing in (
        (
            [
                "clients",
                "update",
                "--erir-contract-price-amount",
                "120000.5",
                "--dry-run",
            ],
            "--erir-contract-price-including-vat",
        ),
        (
            [
                "clients",
                "update",
                "--erir-contract-price-including-vat",
                "YES",
                "--dry-run",
            ],
            "--erir-contract-price-amount",
        ),
    ):
        result = CliRunner().invoke(cli, args)
        assert result.exit_code != 0
        assert "ErirAttributes.Contract.Price requires" in result.output
        assert missing in result.output


def test_clients_update_erir_contract_price_rejects_non_finite_amount():
    for value in ("nan", "inf", "-inf"):
        result = CliRunner().invoke(
            cli,
            [
                "clients",
                "update",
                "--erir-contract-price-amount",
                value,
                "--erir-contract-price-including-vat",
                "YES",
                "--dry-run",
            ],
        )
        assert result.exit_code != 0
        assert "--erir-contract-price-amount must be a positive decimal amount" in (
            result.output
        )


def test_clients_update_erir_contragent_payload():
    body = _dry_run(
        "clients",
        "update",
        "--erir-contragent-name",
        "Counterparty LLC",
        "--erir-contragent-kpp",
        "770201001",
        "--erir-contragent-phone",
        "+70000000001",
        "--erir-contragent-epay-number",
        "epay456",
        "--erir-contragent-reg-number",
        "1027700132196",
        "--erir-contragent-oksm-number",
        "643",
        "--erir-contragent-tin-type",
        "LEGAL",
        "--erir-contragent-tin",
        "1234567890",
    )
    assert body["params"]["Clients"][0] == {
        "ErirAttributes": {
            "Contragent": {
                "Name": "Counterparty LLC",
                "Kpp": "770201001",
                "Phone": "+70000000001",
                "EpayNumber": "epay456",
                "RegNumber": "1027700132196",
                "OksmNumber": "643",
                "TinInfo": {"TinType": "LEGAL", "Tin": "1234567890"},
            }
        }
    }


def test_clients_update_erir_contragent_tin_info_partial_payload():
    body = _dry_run(
        "clients",
        "update",
        "--erir-contragent-tin-type",
        "LEGAL",
    )
    assert body["params"]["Clients"][0] == {
        "ErirAttributes": {"Contragent": {"TinInfo": {"TinType": "LEGAL"}}}
    }


def test_clients_update_erir_contragent_rejects_invalid_tin_type():
    result = CliRunner().invoke(
        cli,
        [
            "clients",
            "update",
            "--erir-contragent-tin-type",
            "UNKNOWN",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "Invalid tin type" in result.output
    assert "--erir-contragent-tin-type" in result.output


def test_clients_update_rejects_invalid_subscription_or_setting():
    invalid_cases = [
        [
            "clients",
            "update",
            "--email-subscription",
            "UNKNOWN=YES",
            "--dry-run",
        ],
        [
            "clients",
            "update",
            "--setting",
            "DISPLAY_STORE_RATING=yes",
            "--dry-run",
        ],
    ]
    for args in invalid_cases:
        result = CliRunner().invoke(cli, args)
        assert result.exit_code != 0
        assert "Error:" in result.output


def test_agencyclients_add_runtime_deprecated_without_dry_run():
    result = CliRunner().invoke(
        cli,
        [
            "agencyclients",
            "add",
            "--login",
            "client-login",
            "--first-name",
            "Alice",
            "--last-name",
            "Smith",
            "--currency",
            "RUB",
        ],
    )
    assert result.exit_code != 0
    assert "add-passport-organization" in result.output


def test_agencyclients_add_passport_organization_payload():
    body = _dry_run(
        "agencyclients",
        "add-passport-organization",
        "--name",
        "Org",
        "--currency",
        "RUB",
        "--notification-email",
        "ops@example.com",
        "--notification-lang",
        "EN",
        "--no-send-account-news",
        "--send-warnings",
    )
    assert body["method"] == "addPassportOrganization"
    assert body["params"] == {
        "Name": "Org",
        "Currency": "RUB",
        "Notification": {
            "Email": "ops@example.com",
            "Lang": "EN",
            "EmailSubscriptions": [
                {"Option": "RECEIVE_RECOMMENDATIONS", "Value": "NO"},
                {"Option": "TRACK_POSITION_CHANGES", "Value": "YES"},
            ],
        },
    }


def test_agencyclients_add_passport_organization_member_payload():
    body = _dry_run(
        "agencyclients",
        "add-passport-organization-member",
        "--passport-organization-login",
        "org-login",
        "--role",
        "CHIEF",
        "--invite-email",
        "user@example.com",
    )
    assert body["method"] == "addPassportOrganizationMember"
    assert body["params"] == {
        "PassportOrganizationLogin": "org-login",
        "Role": "CHIEF",
        "SendInviteTo": {"Email": "user@example.com"},
    }


def test_agencyclients_update_payload_matches_wsdl_contract():
    body = _dry_run(
        "agencyclients",
        "update",
        "--client-id",
        "42",
        "--client-info",
        "Agency client",
        "--phone",
        "+70000000000",
        "--notification-email",
        "user@example.com",
        "--notification-lang",
        "EN",
        "--email-subscription",
        "TRACK_MANAGED_CAMPAIGNS=YES",
        "--setting",
        "CORRECT_TYPOS_AUTOMATICALLY=NO",
        "--tin-type",
        "INDIVIDUAL",
        "--tin",
        "1234567890",
        "--grant",
        "EDIT_CAMPAIGNS=YES",
        "--grant",
        "IMPORT_XLS=NO",
    )
    item = body["params"]["Clients"][0]
    assert item == {
        "ClientId": 42,
        "ClientInfo": "Agency client",
        "Phone": "+70000000000",
        "Notification": {
            "Email": "user@example.com",
            "Lang": "EN",
            "EmailSubscriptions": [
                {"Option": "TRACK_MANAGED_CAMPAIGNS", "Value": "YES"}
            ],
        },
        "Settings": [{"Option": "CORRECT_TYPOS_AUTOMATICALLY", "Value": "NO"}],
        "TinInfo": {"TinType": "INDIVIDUAL", "Tin": "1234567890"},
        "Grants": [
            {"Privilege": "EDIT_CAMPAIGNS", "Value": "YES"},
            {"Privilege": "IMPORT_XLS", "Value": "NO"},
        ],
    }
    assert "Email" not in item


def test_agencyclients_update_rejects_bare_grant():
    result = CliRunner().invoke(
        cli,
        [
            "agencyclients",
            "update",
            "--client-id",
            "1",
            "--grant",
            "EDIT_CAMPAIGNS",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "Expected format: OPTION=YES|NO" in result.output


def test_agencyclients_update_rejects_legacy_email_flag():
    result = CliRunner().invoke(
        cli,
        [
            "agencyclients",
            "update",
            "--client-id",
            "1",
            "--email",
            "user@example.com",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "No such option" in result.output
    assert "--email" in result.output


def test_agencyclients_update_clear_grants_emits_empty_list():
    body = _dry_run(
        "agencyclients",
        "update",
        "--client-id",
        "42",
        "--clear-grants",
    )
    assert body["params"]["Clients"][0] == {"ClientId": 42, "Grants": []}


def test_agencyclients_update_requires_at_least_one_update_field():
    result = CliRunner().invoke(
        cli,
        ["agencyclients", "update", "--client-id", "1", "--dry-run"],
    )
    assert result.exit_code != 0
    assert "Provide at least one field to update" in result.output


_CLIENTS_GET_NESTED_FIELD_FLAGS = [
    ("--contract-field-names", "ContractFieldNames", "Number,Date,Price"),
    ("--contragent-field-names", "ContragentFieldNames", "Name,Phone,EpayNumber"),
    (
        "--contragent-tin-info-field-names",
        "ContragentTinInfoFieldNames",
        "TinType,Tin",
    ),
    (
        "--organization-field-names",
        "OrganizationFieldNames",
        "Name,EpayNumber,OkvedCode",
    ),
    ("--tin-info-field-names", "TinInfoFieldNames", "TinType,Tin"),
]


def test_clients_get_nested_field_names_payload():
    # ClientsGetRequest (WSDL tests/wsdl_cache/clients.xml) declares five
    # nested top-level *FieldNames parameters separate from FieldNames:
    # ContractFieldNames (ContractInfoFieldEnum), ContragentFieldNames
    # (ContragentInfoFieldEnum), ContragentTinInfoFieldNames
    # (TinInfoFieldEnum), OrganizationFieldNames (OrgInfoFieldEnum), and
    # TinInfoFieldNames (TinInfoFieldEnum). The same five enums are reused
    # on agencyclients.get per #407.
    argv = ["clients", "get"]
    expected = {}
    for flag, wsdl_key, sample in _CLIENTS_GET_NESTED_FIELD_FLAGS:
        argv.extend([flag, sample])
        expected[wsdl_key] = sample.split(",")

    body = _read_dry_run(*argv)

    for wsdl_key, values in expected.items():
        assert body["params"][wsdl_key] == values


def test_clients_get_omits_nested_field_names_by_default():
    body = _read_dry_run("clients", "get")

    for _, wsdl_key, _ in _CLIENTS_GET_NESTED_FIELD_FLAGS:
        assert wsdl_key not in body["params"]


def test_clients_get_help_exposes_nested_field_names():
    result = CliRunner().invoke(cli, ["clients", "get", "--help"])

    assert result.exit_code == 0
    for flag, _, _ in _CLIENTS_GET_NESTED_FIELD_FLAGS:
        assert flag in result.output


@pytest.mark.parametrize(
    "flag,wsdl_key",
    [(flag, key) for flag, key, _ in _CLIENTS_GET_NESTED_FIELD_FLAGS],
)
def test_clients_get_rejects_empty_nested_field_names_csv(flag, wsdl_key):
    result = CliRunner().invoke(
        cli,
        ["clients", "get", flag, ",", "--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )

    assert result.exit_code != 0
    assert f"Provide a non-empty comma-separated {wsdl_key} list." in result.output


_AGENCYCLIENTS_GET_NESTED_FIELD_FLAGS = [
    ("--contract-field-names", "ContractFieldNames", "Number,Date,Type"),
    ("--contragent-field-names", "ContragentFieldNames", "Name,Phone,RegNumber"),
    (
        "--contragent-tin-info-field-names",
        "ContragentTinInfoFieldNames",
        "TinType,Tin",
    ),
    (
        "--organization-field-names",
        "OrganizationFieldNames",
        "Name,EpayNumber,OkvedCode",
    ),
    ("--tin-info-field-names", "TinInfoFieldNames", "TinType,Tin"),
]


def test_agencyclients_get_nested_field_names_payload():
    # AgencyClientsGetRequest (WSDL tests/wsdl_cache/agencyclients.xml)
    # declares five nested top-level *FieldNames parameters separate from
    # FieldNames: ContractFieldNames (ContractInfoFieldEnum),
    # ContragentFieldNames (ContragentInfoFieldEnum),
    # ContragentTinInfoFieldNames (TinInfoFieldEnum),
    # OrganizationFieldNames (OrgInfoFieldEnum), and TinInfoFieldNames
    # (TinInfoFieldEnum). The same five enums are reused on clients.get
    # per #410.
    argv = ["agencyclients", "get"]
    expected = {}
    for flag, wsdl_key, sample in _AGENCYCLIENTS_GET_NESTED_FIELD_FLAGS:
        argv.extend([flag, sample])
        expected[wsdl_key] = sample.split(",")

    body = _read_dry_run(*argv)

    for wsdl_key, values in expected.items():
        assert body["params"][wsdl_key] == values


def test_agencyclients_get_omits_nested_field_names_by_default():
    body = _read_dry_run("agencyclients", "get")

    for _, wsdl_key, _ in _AGENCYCLIENTS_GET_NESTED_FIELD_FLAGS:
        assert wsdl_key not in body["params"]


def test_agencyclients_get_help_exposes_nested_field_names():
    result = CliRunner().invoke(cli, ["agencyclients", "get", "--help"])

    assert result.exit_code == 0
    for flag, _, _ in _AGENCYCLIENTS_GET_NESTED_FIELD_FLAGS:
        assert flag in result.output


@pytest.mark.parametrize(
    "flag,wsdl_key",
    [(flag, key) for flag, key, _ in _AGENCYCLIENTS_GET_NESTED_FIELD_FLAGS],
)
def test_agencyclients_get_rejects_empty_nested_field_names_csv(flag, wsdl_key):
    result = CliRunner().invoke(
        cli,
        ["agencyclients", "get", flag, ",", "--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )

    assert result.exit_code != 0
    assert f"Provide a non-empty comma-separated {wsdl_key} list." in result.output


def test_agencyclients_update_rejects_non_positive_client_id():
    # agencyclients update is a DANGEROUS command — this guard is parse-time
    # validation only (no live mutation is exercised).
    result = _rejected("agencyclients", "update", "--client-id", "0", "--phone", "1")
    assert result.exit_code == 2, result.output


@pytest.mark.parametrize("bad", ["0", "-1"])
def test_agencyclients_delete_rejects_non_positive_id(bad):
    # delete is a runtime-deprecated stub that always Aborts and never builds a
    # payload (no --dry-run support), but its --id selector is guarded for
    # surface consistency. Invoke directly (no --dry-run) and confirm IntRange
    # rejects at parse time, before the Abort.
    result = CliRunner().invoke(cli, ["agencyclients", "delete", "--id", bad])
    assert result.exit_code == 2, result.output
    assert "is not in the range" in result.output
