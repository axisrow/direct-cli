"""Unit tests for `direct changes check` flag validation (#228)."""

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from direct_cli.cli import cli

TIMESTAMP = "2026-05-21T12:00:00"


def _invoke(*extra_args):
    return CliRunner().invoke(
        cli,
        [
            "--token",
            "token",
            "changes",
            "check",
            "--timestamp",
            TIMESTAMP,
            *extra_args,
        ],
    )


def test_check_rejects_missing_all_id_filters():
    """Mutex enforcement: at least one of three ID flags is required."""
    with patch("direct_cli.commands.changes.create_client") as create_client:
        result = _invoke()

    assert result.exit_code != 0
    assert "Provide exactly one of" in result.output
    assert "--campaign-ids" in result.output
    assert "--ad-group-ids" in result.output
    assert "--ad-ids" in result.output
    create_client.assert_not_called()


def test_check_rejects_two_id_filters_together():
    """Mutex enforcement: passing two filters is a UsageError."""
    with patch("direct_cli.commands.changes.create_client") as create_client:
        result = _invoke("--campaign-ids", "1", "--ad-group-ids", "2")

    assert result.exit_code != 0
    assert "mutually exclusive" in result.output
    create_client.assert_not_called()


def test_check_rejects_all_three_id_filters_together():
    """Mutex enforcement: even three at once is rejected with the same wording."""
    with patch("direct_cli.commands.changes.create_client") as create_client:
        result = _invoke("--campaign-ids", "1", "--ad-group-ids", "2", "--ad-ids", "3")

    assert result.exit_code != 0
    assert "mutually exclusive" in result.output
    create_client.assert_not_called()


def _client_with_payload_capture():
    """Build a fake client whose .changes().post() captures the request body."""
    client = MagicMock()
    client.changes.return_value.post.return_value.data = {"ok": True}
    return client


def test_check_with_campaign_ids_sends_campaign_ids_field():
    with patch(
        "direct_cli.commands.changes.create_client",
        return_value=_client_with_payload_capture(),
    ) as create_client:
        result = _invoke("--campaign-ids", "1,2")

    assert result.exit_code == 0, result.output
    body = create_client.return_value.changes.return_value.post.call_args.kwargs["data"]
    assert body["method"] == "check"
    assert body["params"]["CampaignIds"] == [1, 2]
    assert "AdGroupIds" not in body["params"]
    assert "AdIds" not in body["params"]
    assert body["params"]["Timestamp"].endswith("Z")


def test_check_with_ad_group_ids_sends_ad_group_ids_field():
    with patch(
        "direct_cli.commands.changes.create_client",
        return_value=_client_with_payload_capture(),
    ) as create_client:
        result = _invoke("--ad-group-ids", "100,200,300")

    assert result.exit_code == 0, result.output
    body = create_client.return_value.changes.return_value.post.call_args.kwargs["data"]
    assert body["params"]["AdGroupIds"] == [100, 200, 300]
    assert "CampaignIds" not in body["params"]
    assert "AdIds" not in body["params"]


def test_check_with_ad_ids_sends_ad_ids_field():
    with patch(
        "direct_cli.commands.changes.create_client",
        return_value=_client_with_payload_capture(),
    ) as create_client:
        result = _invoke("--ad-ids", "9999")

    assert result.exit_code == 0, result.output
    body = create_client.return_value.changes.return_value.post.call_args.kwargs["data"]
    assert body["params"]["AdIds"] == [9999]
    assert "CampaignIds" not in body["params"]
    assert "AdGroupIds" not in body["params"]


def test_check_default_fields_match_wsdl_enum():
    """Omitting --fields should emit all four CheckFieldEnum values."""
    with patch(
        "direct_cli.commands.changes.create_client",
        return_value=_client_with_payload_capture(),
    ) as create_client:
        result = _invoke("--campaign-ids", "1")

    assert result.exit_code == 0, result.output
    body = create_client.return_value.changes.return_value.post.call_args.kwargs["data"]
    assert sorted(body["params"]["FieldNames"]) == sorted(
        ["CampaignIds", "AdGroupIds", "AdIds", "CampaignsStat"]
    )


def test_check_custom_fields_pass_through_when_in_enum():
    with patch(
        "direct_cli.commands.changes.create_client",
        return_value=_client_with_payload_capture(),
    ) as create_client:
        result = _invoke("--campaign-ids", "1", "--fields", "CampaignIds,AdIds")

    assert result.exit_code == 0, result.output
    body = create_client.return_value.changes.return_value.post.call_args.kwargs["data"]
    assert body["params"]["FieldNames"] == ["CampaignIds", "AdIds"]


def test_check_rejects_unknown_field_name():
    """Typos like 'CmapignIds' must be caught before reaching the API."""
    with patch("direct_cli.commands.changes.create_client") as create_client:
        result = _invoke("--campaign-ids", "1", "--fields", "CmapignIds")

    assert result.exit_code != 0
    assert "Unknown --fields value(s)" in result.output
    assert "CmapignIds" in result.output
    assert "CampaignIds" in result.output
    create_client.assert_not_called()


def test_check_rejects_unknown_field_among_valid():
    """Mixed valid+invalid input still raises and names only the bad token."""
    with patch("direct_cli.commands.changes.create_client") as create_client:
        result = _invoke(
            "--campaign-ids", "1", "--fields", "CampaignIds,BogusField,AdIds"
        )

    assert result.exit_code != 0
    assert "BogusField" in result.output
    create_client.assert_not_called()


def test_check_rejects_commas_only_in_fields():
    """`--fields ,` must not silently send FieldNames=[] (violates WSDL minOccurs=1)."""
    with patch("direct_cli.commands.changes.create_client") as create_client:
        result = _invoke("--campaign-ids", "1", "--fields", ",")

    assert result.exit_code != 0
    assert "empty list" in result.output
    create_client.assert_not_called()


def test_check_rejects_commas_only_in_campaign_ids():
    """`--campaign-ids ,` must produce UsageError (exit 2), not Abort (exit 1)."""
    with patch("direct_cli.commands.changes.create_client") as create_client:
        result = _invoke("--campaign-ids", ",")

    assert result.exit_code != 0
    assert "--campaign-ids" in result.output
    create_client.assert_not_called()
