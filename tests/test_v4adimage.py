import json
from unittest.mock import patch

from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli.v4_contracts import get_v4_contract


def _invoke(*args: str):
    return CliRunner().invoke(cli, list(args))


def test_get_dry_run_builds_selection_criteria():
    result = _invoke(
        "v4adimage",
        "get",
        "--logins",
        "client-a,client-b",
        "--ad-image-hashes",
        "hashA,hashB",
        "--status-moderate",
        "Yes",
        "--ad-ids",
        "1,2",
        "--campaign-ids",
        "10,20",
        "--limit",
        "20",
        "--offset",
        "0",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "AdImageAssociation",
        "param": {
            "Action": "Get",
            "SelectionCriteria": {
                "Logins": ["client-a", "client-b"],
                "AdImageHashes": ["hashA", "hashB"],
                "StatusAdImageModerate": ["Yes"],
                "AdIDS": [1, 2],
                "CampaignIDS": [10, 20],
                "Limit": 20,
                "Offset": 0,
            },
        },
    }


def test_get_empty_criteria_is_allowed():
    result = _invoke("v4adimage", "get", "--dry-run")

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "AdImageAssociation",
        "param": {"Action": "Get", "SelectionCriteria": {}},
    }


def test_set_attach_and_detach():
    result = _invoke(
        "v4adimage",
        "set",
        "--association",
        "123=hashA",
        "--association",
        "456",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "AdImageAssociation",
        "param": {
            "Action": "Set",
            "AdImageAssociations": [
                {"AdID": 123, "AdImageHash": "hashA"},
                {"AdID": 456},
            ],
        },
    }


def test_set_requires_association():
    result = _invoke("v4adimage", "set", "--dry-run")

    assert result.exit_code != 0
    assert "Missing option '--association'" in result.output


def test_set_rejects_non_integer_ad_id():
    result = _invoke("v4adimage", "set", "--association", "abc=hash", "--dry-run")

    assert result.exit_code != 0
    assert "integer AD_ID" in result.output


def test_set_rejects_duplicate_ad_id():
    result = _invoke(
        "v4adimage",
        "set",
        "--association",
        "123=hashA",
        "--association",
        "123",
        "--dry-run",
    )

    assert result.exit_code != 0
    assert "unique" in result.output


def test_get_formats_mocked_response():
    with patch("direct_cli.commands.v4adimage.create_v4_client") as create_client:
        with patch(
            "direct_cli.commands.v4adimage.call_v4",
            return_value=[{"AdID": 1, "AdImageHash": "h"}],
        ) as call:
            result = _invoke(
                "--token",
                "token",
                "v4adimage",
                "get",
                "--ad-ids",
                "1",
            )

    assert result.exit_code == 0
    assert json.loads(result.output) == [{"AdID": 1, "AdImageHash": "h"}]
    call.assert_called_once_with(
        create_client.return_value,
        "AdImageAssociation",
        {"Action": "Get", "SelectionCriteria": {"AdIDS": [1]}},
    )


def test_v4adimage_help_has_no_json_input_flag():
    for args in [
        ("v4adimage", "--help"),
        ("v4adimage", "get", "--help"),
        ("v4adimage", "set", "--help"),
    ]:
        result = _invoke(*args)
        assert result.exit_code == 0
        assert "--json" not in result.output


def test_v4adimage_commands_declare_contract():
    commands = cli.commands["v4adimage"].commands
    assert commands["get"].v4_method == "AdImageAssociation"
    assert commands["get"].v4_contract == get_v4_contract("AdImageAssociation")
    assert commands["set"].v4_method == "AdImageAssociation"
