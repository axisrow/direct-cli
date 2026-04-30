import json

import pytest
from click.testing import CliRunner
from requests import PreparedRequest, Response

from direct_cli.cli import cli
from direct_cli._vendor.tapi_yandex_direct.tapi_yandex_direct import (
    YandexDirectClientAdapter,
)


FIELD_NAMES = ["Month", "Impressions", "Clicks", "Cost"]
REPORT_ROWS = [
    ["2026-03-01", "10", "2", "1500000"],
    ["2026-03-02", "20", "3", "2500000"],
]
EXPECTED_DICTS = [
    {
        "Month": "2026-03-01",
        "Impressions": "10",
        "Clicks": "2",
        "Cost": "1500000",
    },
    {
        "Month": "2026-03-02",
        "Impressions": "20",
        "Clicks": "3",
        "Cost": "2500000",
    },
]


def _report_body(
    *,
    skip_report_header: bool,
    skip_column_header: bool,
    skip_report_summary: bool,
    field_names: list[str] | None = None,
    rows: list[list[str]] | None = None,
) -> str:
    field_names = field_names or FIELD_NAMES
    rows = rows or REPORT_ROWS
    lines = []
    if not skip_report_header:
        lines.extend(['"Test"', ""])
    if not skip_column_header:
        lines.append("\t".join(field_names))
    lines.extend("\t".join(row) for row in rows)
    if not skip_report_summary:
        lines.append(f"Total rows: {len(rows)}")
    return "\n".join(lines) + "\n"


class _ParsedReport:
    def __init__(
        self,
        body: str,
        *,
        field_names: list[str] | None = None,
        skip_column_header: bool = False,
        skip_report_summary: bool = True,
    ):
        self.adapter = YandexDirectClientAdapter()
        self.response = self._make_response(body)
        self.store = {}
        self.data = self.adapter.process_response(
            self.response,
            {
                "data": json.dumps(
                    {"params": {"FieldNames": field_names or FIELD_NAMES}}
                ).encode(),
                "headers": {
                    "skipColumnHeader": str(skip_column_header).lower(),
                    "skipReportSummary": str(skip_report_summary).lower(),
                },
            },
            store=self.store,
        )

    @staticmethod
    def _make_response(body: str) -> Response:
        request = PreparedRequest()
        request.prepare(
            method="POST",
            url="https://api.direct.yandex.com/json/v5/reports",
        )
        response = Response()
        response.status_code = 200
        response._content = body.encode()
        response.request = request
        return response

    def __call__(self):
        return self

    @property
    def columns(self):
        return self.store["columns"]

    def to_dicts(self):
        return self.adapter.to_dicts(
            data=self.data,
            response=self.response,
            store=self.store,
        )

    def to_values(self):
        return self.adapter.to_values(
            data=self.data,
            response=self.response,
            store=self.store,
        )

    def to_lines(self):
        return self.adapter.to_lines(
            data=self.data,
            response=self.response,
            store=self.store,
        )

    def iter_dicts(self):
        return list(
            self.adapter.iter_dicts(
                data=self.data,
                response=self.response,
                store=self.store,
            )
        )


@pytest.mark.parametrize("skip_report_header", [True, False])
@pytest.mark.parametrize("skip_column_header", [True, False])
@pytest.mark.parametrize("skip_report_summary", [True, False])
def test_reports_adapter_parses_rows_for_all_header_summary_combinations(
    skip_report_header,
    skip_column_header,
    skip_report_summary,
):
    report = _ParsedReport(
        _report_body(
            skip_report_header=skip_report_header,
            skip_column_header=skip_column_header,
            skip_report_summary=skip_report_summary,
        ),
        skip_column_header=skip_column_header,
        skip_report_summary=skip_report_summary,
    )

    expected_values = list(REPORT_ROWS)
    expected_dicts = list(EXPECTED_DICTS)
    if not skip_report_summary:
        expected_values.append(["Total rows: 2", "", "", ""])
        expected_dicts.append(
            {
                "Month": "Total rows: 2",
                "Impressions": "",
                "Clicks": "",
                "Cost": "",
            }
        )

    assert report.columns == FIELD_NAMES
    assert report.to_dicts() == expected_dicts
    assert report.iter_dicts() == expected_dicts
    assert report.to_values() == expected_values


def test_reports_adapter_parses_single_field_report_with_header_and_summary():
    report = _ParsedReport(
        _report_body(
            skip_report_header=False,
            skip_column_header=False,
            skip_report_summary=False,
            field_names=["Month"],
            rows=[["2026-03-01"], ["2026-03-02"]],
        ),
        field_names=["Month"],
        skip_report_summary=False,
    )

    assert report.columns == ["Month"]
    assert report.to_dicts() == [
        {"Month": "2026-03-01"},
        {"Month": "2026-03-02"},
        {"Month": "Total rows: 2"},
    ]


def test_reports_get_json_opt_out_uses_columns_not_report_title(monkeypatch):
    reports_module = pytest.importorskip("direct_cli.commands.reports")

    class _FakeReports:
        def post(self, data):
            return _ParsedReport(
                _report_body(
                    skip_report_header=False,
                    skip_column_header=False,
                    skip_report_summary=False,
                ),
                skip_report_summary=False,
            )

    class _FakeClient:
        def reports(self):
            return _FakeReports()

    monkeypatch.setattr(
        reports_module,
        "create_client",
        lambda **kwargs: _FakeClient(),
    )

    result = CliRunner().invoke(
        cli,
        [
            "reports",
            "get",
            "--type",
            "custom_report",
            "--from",
            "2026-03-01",
            "--to",
            "2026-03-31",
            "--name",
            "Test",
            "--fields",
            "Month,Impressions,Clicks,Cost",
            "--format",
            "json",
            "--no-skip-report-header",
            "--no-skip-report-summary",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == [
        *EXPECTED_DICTS,
        {
            "Month": "Total rows: 2",
            "Impressions": "",
            "Clicks": "",
            "Cost": "",
        },
    ]
