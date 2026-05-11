import json
from unittest.mock import patch

from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli.v4_contracts import get_v4_contract


def _invoke(*args: str):
    return CliRunner().invoke(cli, list(args))


def test_get_campaigns_tags_dry_run_uses_campaign_ids_param():
    result = _invoke(
        "v4tags",
        "get-campaigns",
        "--campaign-ids",
        "3193279,1634563",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "GetCampaignsTags",
        "param": {"CampaignIDS": [3193279, 1634563]},
    }


def test_get_banners_tags_dry_run_uses_banner_ids_param():
    result = _invoke(
        "v4tags",
        "get-banners",
        "--banner-ids",
        "2571700,2571745",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "GetBannersTags",
        "param": {"BannerIDS": [2571700, 2571745]},
    }


def test_get_banners_tags_dry_run_accepts_campaign_ids_selector():
    result = _invoke(
        "v4tags",
        "get-banners",
        "--campaign-ids",
        "3193279",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "GetBannersTags",
        "param": {"CampaignIDS": [3193279]},
    }


def test_get_banners_tags_requires_exactly_one_selector():
    missing = _invoke("v4tags", "get-banners", "--dry-run")
    both = _invoke(
        "v4tags",
        "get-banners",
        "--campaign-ids",
        "1",
        "--banner-ids",
        "2",
        "--dry-run",
    )

    assert missing.exit_code != 0
    assert both.exit_code != 0
    assert "Use exactly one of --campaign-ids or --banner-ids" in missing.output
    assert "Use exactly one of --campaign-ids or --banner-ids" in both.output


def test_update_campaigns_tags_dry_run_uses_campaign_tag_info_array():
    result = _invoke(
        "v4tags",
        "update-campaigns",
        "--campaign-id",
        "3193279",
        "--tag",
        "0=akapulko",
        "--tag",
        "16590=orange",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "UpdateCampaignsTags",
        "param": [
            {
                "CampaignID": 3193279,
                "Tags": [
                    {"TagID": 0, "Tag": "akapulko"},
                    {"TagID": 16590, "Tag": "orange"},
                ],
            }
        ],
    }


def test_update_campaigns_tags_clear_dry_run_uses_empty_tags_array():
    result = _invoke(
        "v4tags",
        "update-campaigns",
        "--campaign-id",
        "3193279",
        "--clear-tags",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "UpdateCampaignsTags",
        "param": [{"CampaignID": 3193279, "Tags": []}],
    }


def test_update_campaigns_tags_rejects_invalid_tag_specs():
    missing = _invoke(
        "v4tags",
        "update-campaigns",
        "--campaign-id",
        "1",
        "--dry-run",
    )
    duplicate = _invoke(
        "v4tags",
        "update-campaigns",
        "--campaign-id",
        "1",
        "--tag",
        "0=Sale",
        "--tag",
        "0=sale",
        "--dry-run",
    )
    too_long = _invoke(
        "v4tags",
        "update-campaigns",
        "--campaign-id",
        "1",
        "--tag",
        "0=abcdefghijklmnopqrstuvwxyz",
        "--dry-run",
    )

    assert missing.exit_code != 0
    assert "--tag is required unless --clear-tags is used" in missing.output
    assert duplicate.exit_code != 0
    assert "--tag texts must be unique ignoring case" in duplicate.output
    assert too_long.exit_code != 0
    assert "--tag text must be 25 characters or fewer" in too_long.output


def test_update_banners_tags_dry_run_uses_banner_tag_info_array():
    result = _invoke(
        "v4tags",
        "update-banners",
        "--banner-ids",
        "2571700,2571745",
        "--tag-ids",
        "16590,16734",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "UpdateBannersTags",
        "param": [
            {"BannerID": 2571700, "TagIDS": [16590, 16734]},
            {"BannerID": 2571745, "TagIDS": [16590, 16734]},
        ],
    }


def test_update_banners_tags_clear_dry_run_uses_empty_tag_ids_array():
    result = _invoke(
        "v4tags",
        "update-banners",
        "--banner-ids",
        "2571700",
        "--clear-tags",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "UpdateBannersTags",
        "param": [{"BannerID": 2571700, "TagIDS": []}],
    }


def test_update_banners_tags_rejects_missing_or_empty_tag_ids():
    missing = _invoke(
        "v4tags",
        "update-banners",
        "--banner-ids",
        "2571700",
        "--dry-run",
    )
    empty = _invoke(
        "v4tags",
        "update-banners",
        "--banner-ids",
        "2571700",
        "--tag-ids",
        "",
        "--dry-run",
    )

    assert missing.exit_code != 0
    assert "--tag-ids is required unless --clear-tags is used" in missing.output
    assert empty.exit_code != 0
    assert "--tag-ids must not be empty" in empty.output


def test_v4tags_formats_mocked_response_as_json():
    with patch("direct_cli.commands.v4tags.create_v4_client") as create_client:
        with patch(
            "direct_cli.commands.v4tags.call_v4",
            return_value=[{"CampaignID": 1, "Tags": [{"TagID": 10, "Tag": "Sale"}]}],
        ) as call:
            result = _invoke(
                "--token",
                "token",
                "v4tags",
                "get-campaigns",
                "--campaign-ids",
                "1",
            )

    assert result.exit_code == 0
    assert json.loads(result.output) == [
        {"CampaignID": 1, "Tags": [{"TagID": 10, "Tag": "Sale"}]}
    ]
    call.assert_called_once_with(
        create_client.return_value,
        "GetCampaignsTags",
        {"CampaignIDS": [1]},
    )


def test_v4tags_with_login_keeps_method_param_schema():
    with patch("direct_cli.commands.v4tags.create_v4_client") as create_client:
        with patch("direct_cli.commands.v4tags.call_v4", return_value=1) as call:
            result = _invoke(
                "--token",
                "token",
                "--login",
                "client-login",
                "v4tags",
                "update-banners",
                "--banner-ids",
                "2571700",
                "--tag-ids",
                "16590",
            )

    assert result.exit_code == 0
    create_client.assert_called_once_with(
        token="token",
        login="client-login",
        profile=None,
        sandbox=False,
    )
    call.assert_called_once_with(
        create_client.return_value,
        "UpdateBannersTags",
        [{"BannerID": 2571700, "TagIDS": [16590]}],
    )


def test_v4tags_help_contains_no_json_input_flag():
    for args in [
        ("v4tags", "--help"),
        ("v4tags", "get-campaigns", "--help"),
        ("v4tags", "get-banners", "--help"),
        ("v4tags", "update-campaigns", "--help"),
        ("v4tags", "update-banners", "--help"),
    ]:
        result = _invoke(*args)
        assert result.exit_code == 0
        assert "--json" not in result.output


def test_v4tags_commands_declare_v4_contracts():
    commands = cli.commands["v4tags"].commands

    assert commands["get-campaigns"].v4_method == "GetCampaignsTags"
    assert commands["get-campaigns"].v4_contract == get_v4_contract("GetCampaignsTags")
    assert commands["get-banners"].v4_method == "GetBannersTags"
    assert commands["get-banners"].v4_contract == get_v4_contract("GetBannersTags")
    assert commands["update-campaigns"].v4_method == "UpdateCampaignsTags"
    assert commands["update-campaigns"].v4_contract == get_v4_contract(
        "UpdateCampaignsTags"
    )
    assert commands["update-banners"].v4_method == "UpdateBannersTags"
    assert commands["update-banners"].v4_contract == get_v4_contract(
        "UpdateBannersTags"
    )


def test_adgroups_tags_are_filter_only_not_mutable():
    get_help = _invoke("adgroups", "get", "--help")
    add_help = _invoke("adgroups", "add", "--help")
    update_help = _invoke("adgroups", "update", "--help")

    assert get_help.exit_code == 0
    assert "--tag-ids" in get_help.output
    assert "--tags" in get_help.output
    assert add_help.exit_code == 0
    assert "--tag" not in add_help.output
    assert update_help.exit_code == 0
    assert "--tag" not in update_help.output
