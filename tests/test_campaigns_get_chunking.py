"""Offline tests for ``campaigns get`` Ids chunking (issue #946).

The upstream batch cap of 10 IDs per request (``CAMPAIGNS_GET_IDS_BATCH_LIMIT``,
observed through the yandex-direct-mcp wrapper) is handled inside the CLI:
longer ``--ids`` lists are split into chunks, the per-chunk requests are sent
sequentially and the results are concatenated in ``--ids`` order. The output
format is unchanged; ``--dry-run`` prints every chunk request.
"""

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli.commands._campaigns_base import CAMPAIGNS_GET_IDS_BATCH_LIMIT


def _ids_csv(count: int, start: int = 1) -> str:
    return ",".join(str(start + i) for i in range(count))


def test_batch_limit_constant_matches_issue_946():
    assert CAMPAIGNS_GET_IDS_BATCH_LIMIT == 10


def test_get_multi_chunk_dry_run_prints_all_chunk_requests():
    result = CliRunner().invoke(
        cli,
        [
            "campaigns",
            "get",
            "--ids",
            _ids_csv(29),
            "--fields",
            "Id,Name",
            "--text-campaign-field-names",
            "BiddingStrategy",
            "--dry-run",
        ],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )

    assert result.exit_code == 0, result.output
    bodies = json.loads(result.output)
    assert isinstance(bodies, list)
    assert [body["params"]["SelectionCriteria"]["Ids"] for body in bodies] == [
        list(range(1, 11)),
        list(range(11, 21)),
        list(range(21, 30)),
    ]
    for body in bodies:
        assert body["method"] == "get"
        assert body["params"]["FieldNames"] == ["Id", "Name"]
        # Per-chunk requests repeat the type-specific field selection.
        assert body["params"]["TextCampaignFieldNames"] == ["BiddingStrategy"]
        assert "Page" not in body["params"]


def test_get_single_chunk_dry_run_keeps_single_body_shape():
    """≤ BATCH_LIMIT ids stay a single request with the historical shape."""
    result = CliRunner().invoke(
        cli,
        [
            "campaigns",
            "get",
            "--ids",
            _ids_csv(10),
            "--fields",
            "Id",
            "--dry-run",
        ],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )

    assert result.exit_code == 0, result.output
    body = json.loads(result.output)
    assert isinstance(body, dict)
    assert body["params"]["SelectionCriteria"]["Ids"] == list(range(1, 11))


def test_get_no_ids_keeps_single_body_without_ids():
    result = CliRunner().invoke(
        cli,
        ["campaigns", "get", "--fields", "Id", "--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )

    assert result.exit_code == 0, result.output
    body = json.loads(result.output)
    assert isinstance(body, dict)
    assert "SelectionCriteria" not in body["params"]


class _FakeResult:
    def __init__(self, items):
        self._items = items

    def extract(self):
        return self._items

    def iter_items(self):
        yield from self._items


class _FakeCampaignsResource:
    """Replays one canned per-chunk response per post() call."""

    def __init__(self, chunk_responses):
        self._chunk_responses = list(chunk_responses)
        self.calls = []

    def post(self, data):
        self.calls.append(data)
        return lambda: _FakeResult(self._chunk_responses.pop(0))


class _FakeClient:
    def __init__(self, chunk_responses):
        self.resource = _FakeCampaignsResource(chunk_responses)

    def campaigns(self):
        return self.resource


def _invoke_get_with_fake(fake, args):
    with patch(
        "direct_cli.commands.campaigns.client_from_ctx", return_value=fake
    ) as mock_client_from_ctx:
        result = CliRunner().invoke(
            cli,
            ["campaigns", "get", "--fields", "Id,Name"] + args,
        )
    assert result.exit_code == 0, result.output
    assert mock_client_from_ctx.called
    return json.loads(result.output)


def test_get_chunks_long_id_list_and_orders_by_input():
    # 23 ids → 3 chunks; the API returns each chunk's rows in reverse to prove
    # the aggregation re-orders to the --ids input order.
    responses = [
        [{"Id": i, "Name": f"c{i}"} for i in range(10, 0, -1)],
        [{"Id": i, "Name": f"c{i}"} for i in range(20, 10, -1)],
        [{"Id": i, "Name": f"c{i}"} for i in range(23, 20, -1)],
    ]
    fake = _FakeClient(responses)

    items = _invoke_get_with_fake(fake, ["--ids", _ids_csv(23)])

    assert [item["Id"] for item in items] == list(range(1, 24))
    assert len(fake.resource.calls) == 3
    assert [
        call["params"]["SelectionCriteria"]["Ids"] for call in fake.resource.calls
    ] == [
        list(range(1, 11)),
        list(range(11, 21)),
        list(range(21, 24)),
    ]
    # No per-chunk Page.Limit: it would cap every chunk, not the total.
    assert all("Page" not in call["params"] for call in fake.resource.calls)


def test_get_chunked_applies_limit_client_side():
    responses = [
        [{"Id": i, "Name": f"c{i}"} for i in range(1, 11)],
        [{"Id": i, "Name": f"c{i}"} for i in range(11, 16)],
    ]
    fake = _FakeClient(responses)

    items = _invoke_get_with_fake(fake, ["--ids", _ids_csv(15), "--limit", "12"])

    assert [item["Id"] for item in items] == list(range(1, 13))


def test_get_chunked_with_fetch_all_aggregates_iter_items():
    responses = [
        [{"Id": i} for i in range(1, 11)],
        [{"Id": 11}, {"Id": 12}],
    ]
    fake = _FakeClient(responses)

    items = _invoke_get_with_fake(fake, ["--ids", _ids_csv(12), "--fetch-all"])

    assert [item["Id"] for item in items] == list(range(1, 13))
    assert len(fake.resource.calls) == 2


def test_get_unchunked_does_not_reorder_api_results():
    """≤ BATCH_LIMIT ids keep the single-request path byte-compatible."""
    fake = _FakeClient([[{"Id": 7, "Name": "x"}, {"Id": 3, "Name": "y"}]])

    items = _invoke_get_with_fake(fake, ["--ids", "3,7"])

    assert items == [{"Id": 7, "Name": "x"}, {"Id": 3, "Name": "y"}]
    assert len(fake.resource.calls) == 1


def test_order_chunk_results_keeps_unknown_ids_at_tail_in_encounter_order():
    from direct_cli.commands.campaigns import _order_chunk_results

    items = [{"Id": 9}, {"Id": 2}, {"Id": None}, {"Name": "no-id"}]
    ordered = _order_chunk_results(items, [2, 3])

    assert ordered == [{"Id": 2}, {"Id": 9}, {"Id": None}, {"Name": "no-id"}]


@pytest.mark.parametrize("count", [1, 10, 11, 29, 41])
def test_get_chunk_boundaries_in_dry_run(count):
    result = CliRunner().invoke(
        cli,
        [
            "campaigns",
            "get",
            "--ids",
            _ids_csv(count),
            "--fields",
            "Id",
            "--dry-run",
        ],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    bodies = parsed if isinstance(parsed, list) else [parsed]
    expected_chunks = (count + CAMPAIGNS_GET_IDS_BATCH_LIMIT - 1) // 10 or 1
    assert len(bodies) == expected_chunks
    sent_ids = [
        campaign_id
        for body in bodies
        for campaign_id in body["params"]["SelectionCriteria"]["Ids"]
    ]
    assert sent_ids == list(range(1, count + 1))
