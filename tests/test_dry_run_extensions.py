"""Dry-run payload tests for ad extensions: ``sitelinks``, ``vcards``,
``adextensions`` and ``feeds``.

Split out of the historical monolithic ``tests/test_dry_run.py`` (issue #604).
See :mod:`tests.test_dry_run_shared` for the shared invocation helpers and
``tests/test_dry_run.py`` for the rationale behind the whole suite.
"""

import base64
import json

from click.testing import CliRunner

from direct_cli.cli import cli
from tests.test_dry_run_shared import _dry_run, _read_dry_run, _rejected


def test_feeds_add_payload_uses_nested_urlfeed():
    body = _dry_run(
        "feeds",
        "add",
        "--name",
        "Feed A",
        "--url",
        "https://example.com/feed.xml",
        "--business-type",
        "RETAIL",
    )
    assert body["method"] == "add"
    feed = body["params"]["Feeds"][0]
    # The API requires Name, BusinessType (minOccurs=1 in WSDL), SourceType
    # discriminator, and the nested UrlFeed/FileFeed object carrying the URL.
    assert feed == {
        "Name": "Feed A",
        "BusinessType": "RETAIL",
        "SourceType": "URL",
        "UrlFeed": {"Url": "https://example.com/feed.xml"},
    }


def test_feeds_add_payload_accepts_urlfeed_details():
    body = _dry_run(
        "feeds",
        "add",
        "--name",
        "Feed A",
        "--url",
        "https://example.com/feed.xml",
        "--business-type",
        "RETAIL",
        "--remove-utm-tags",
        "yes",
        "--feed-login",
        "feedbot",
        "--feed-password",
        "secret",
    )
    feed = body["params"]["Feeds"][0]
    assert feed["SourceType"] == "URL"
    assert feed["UrlFeed"] == {
        "Url": "https://example.com/feed.xml",
        "RemoveUtmTags": "YES",
        "Login": "feedbot",
        "Password": "secret",
    }


def test_feeds_add_payload_accepts_filefeed_upload(tmp_path):
    feed_path = tmp_path / "feed.xml"
    feed_bytes = b"<yml_catalog><shop /></yml_catalog>"
    feed_path.write_bytes(feed_bytes)

    body = _dry_run(
        "feeds",
        "add",
        "--name",
        "Feed A",
        "--file-feed-path",
        str(feed_path),
        "--business-type",
        "retail",
    )
    feed = body["params"]["Feeds"][0]
    assert feed == {
        "Name": "Feed A",
        "BusinessType": "RETAIL",
        "SourceType": "FILE",
        "FileFeed": {
            "Data": base64.b64encode(feed_bytes).decode("ascii"),
            "Filename": "feed.xml",
        },
    }


def test_feeds_add_payload_accepts_filefeed_filename_override(tmp_path):
    feed_path = tmp_path / "source.tmp"
    feed_path.write_bytes(b"id,name\n1,chair\n")

    body = _dry_run(
        "feeds",
        "add",
        "--name",
        "Feed A",
        "--file-feed-path",
        str(feed_path),
        "--file-feed-filename",
        "products.csv",
        "--business-type",
        "RETAIL",
    )
    feed = body["params"]["Feeds"][0]
    assert feed["SourceType"] == "FILE"
    assert feed["FileFeed"]["Filename"] == "products.csv"


def test_feeds_add_rejects_url_and_filefeed_mix(tmp_path):
    feed_path = tmp_path / "feed.xml"
    feed_path.write_text("<feed />", encoding="utf-8")

    result = _rejected(
        "feeds",
        "add",
        "--name",
        "Feed A",
        "--url",
        "https://example.com/feed.xml",
        "--file-feed-path",
        str(feed_path),
        "--business-type",
        "RETAIL",
    )
    assert "Use either --url or --file-feed-path" in result.output


def test_feeds_add_rejects_filefeed_filename_without_path():
    result = _rejected(
        "feeds",
        "add",
        "--name",
        "Feed A",
        "--file-feed-filename",
        "feed.xml",
        "--business-type",
        "RETAIL",
    )
    assert "--file-feed-filename requires --file-feed-path" in result.output


def test_feeds_add_rejects_overlong_filefeed_filename(tmp_path):
    feed_path = tmp_path / "feed.xml"
    feed_path.write_text("<feed />", encoding="utf-8")

    result = _rejected(
        "feeds",
        "add",
        "--name",
        "Feed A",
        "--file-feed-path",
        str(feed_path),
        "--file-feed-filename",
        "x" * 256,
        "--business-type",
        "RETAIL",
    )
    assert "FileFeed.Filename must be at most 255 characters" in result.output


def test_feeds_add_rejects_oversized_filefeed_before_reading(tmp_path):
    feed_path = tmp_path / "huge-feed.xml"
    with feed_path.open("wb") as fh:
        fh.truncate((50 * 1024 * 1024) + 1)

    result = _rejected(
        "feeds",
        "add",
        "--name",
        "Feed A",
        "--file-feed-path",
        str(feed_path),
        "--business-type",
        "RETAIL",
    )
    assert "FileFeed.Data must be at most 50 MiB" in result.output


def test_feeds_update_payload_changes_url():
    body = _dry_run(
        "feeds",
        "update",
        "--id",
        "9",
        "--url",
        "https://example.com/feed-v2.xml",
    )
    feed = body["params"]["Feeds"][0]
    assert feed == {"Id": 9, "UrlFeed": {"Url": "https://example.com/feed-v2.xml"}}


def test_feeds_update_payload_accepts_urlfeed_details():
    body = _dry_run(
        "feeds",
        "update",
        "--id",
        "9",
        "--remove-utm-tags",
        "no",
        "--feed-login",
        "feedbot",
        "--feed-password",
        "secret",
    )
    feed = body["params"]["Feeds"][0]
    assert feed == {
        "Id": 9,
        "UrlFeed": {
            "RemoveUtmTags": "NO",
            "Login": "feedbot",
            "Password": "secret",
        },
    }


def test_feeds_update_payload_can_clear_urlfeed_credentials():
    body = _dry_run(
        "feeds",
        "update",
        "--id",
        "9",
        "--clear-feed-login",
        "--clear-feed-password",
    )
    feed = body["params"]["Feeds"][0]
    assert feed == {"Id": 9, "UrlFeed": {"Login": None, "Password": None}}


def test_feeds_update_payload_accepts_filefeed_upload(tmp_path):
    feed_path = tmp_path / "feed.yml"
    feed_bytes = b"offer: 1\n"
    feed_path.write_bytes(feed_bytes)

    body = _dry_run(
        "feeds",
        "update",
        "--id",
        "9",
        "--file-feed-path",
        str(feed_path),
    )
    feed = body["params"]["Feeds"][0]
    assert feed == {
        "Id": 9,
        "FileFeed": {
            "Data": base64.b64encode(feed_bytes).decode("ascii"),
            "Filename": "feed.yml",
        },
    }


def test_feeds_update_rejects_urlfeed_and_filefeed_mix(tmp_path):
    feed_path = tmp_path / "feed.xml"
    feed_path.write_text("<feed />", encoding="utf-8")

    result = _rejected(
        "feeds",
        "update",
        "--id",
        "9",
        "--file-feed-path",
        str(feed_path),
        "--remove-utm-tags",
        "YES",
    )
    assert "FileFeed options cannot be combined with UrlFeed options" in result.output


def test_feeds_update_rejects_setting_and_clearing_login():
    result = CliRunner().invoke(
        cli,
        [
            "feeds",
            "update",
            "--id",
            "9",
            "--feed-login",
            "feedbot",
            "--clear-feed-login",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    combined = (result.output or "") + (
        str(result.exception) if result.exception else ""
    )
    assert "Use either --feed-login or --clear-feed-login" in combined


def test_feeds_update_without_fields_errors():
    result = CliRunner().invoke(
        cli,
        [
            "feeds",
            "update",
            "--id",
            "9",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    combined = (result.output or "") + (
        str(result.exception) if result.exception else ""
    )
    assert "--name" in combined
    assert "--url" in combined
    assert "--file-feed-path" in combined
    assert "--remove-utm-tags" in combined
    assert "--clear-feed-login" in combined


def test_sitelinks_add_parses_links_array():
    body = _dry_run(
        "sitelinks",
        "add",
        "--sitelink",
        "About|https://example.com/about",
        "--sitelink",
        "Contact|https://example.com/contact",
    )
    assert body["method"] == "add"
    sitelinks_set = body["params"]["SitelinksSets"][0]
    assert sitelinks_set == {
        "Sitelinks": [
            {"Title": "About", "Href": "https://example.com/about"},
            {"Title": "Contact", "Href": "https://example.com/contact"},
        ]
    }


def test_sitelinks_add_supports_escaped_pipe_in_href():
    """UTM templates with literal '|' must round-trip via '\\|'. See #221."""
    body = _dry_run(
        "sitelinks",
        "add",
        "--sitelink",
        (
            "Главная|https://example.com/?utm_content=cid"
            "\\|{campaign_id}\\|gid\\|{gbid}|Узнать больше"
        ),
    )
    sitelink = body["params"]["SitelinksSets"][0]["Sitelinks"][0]
    assert sitelink == {
        "Title": "Главная",
        "Href": "https://example.com/?utm_content=cid|{campaign_id}|gid|{gbid}",
        "Description": "Узнать больше",
    }


def test_sitelinks_add_pipe_spec_turbo_page_id():
    """Issue #257: --sitelink exposes Sitelinks.TurboPageId."""
    body = _dry_run(
        "sitelinks",
        "add",
        "--sitelink",
        "Docs|https://example.com/docs|API docs|12345",
    )
    sitelink = body["params"]["SitelinksSets"][0]["Sitelinks"][0]
    assert sitelink == {
        "Title": "Docs",
        "Href": "https://example.com/docs",
        "Description": "API docs",
        "TurboPageId": 12345,
    }


def test_sitelinks_add_pipe_spec_turbo_page_id_without_href():
    """Yandex API allows Href or TurboPageId on a sitelink."""
    body = _dry_run(
        "sitelinks",
        "add",
        "--sitelink",
        "Turbo||Turbo page|12345",
    )
    sitelink = body["params"]["SitelinksSets"][0]["Sitelinks"][0]
    assert sitelink == {
        "Title": "Turbo",
        "Description": "Turbo page",
        "TurboPageId": 12345,
    }


def test_sitelinks_add_pipe_spec_turbo_page_id_without_href_or_description():
    body = _dry_run(
        "sitelinks",
        "add",
        "--sitelink",
        "Turbo|||12345",
    )
    sitelink = body["params"]["SitelinksSets"][0]["Sitelinks"][0]
    assert sitelink == {"Title": "Turbo", "TurboPageId": 12345}


def test_sitelinks_add_pipe_spec_turbo_page_id_invalid_rejected():
    result = _rejected(
        "sitelinks",
        "add",
        "--sitelink",
        "Docs|https://example.com/docs|API docs|not-an-id",
    )
    assert "TurboPageId must be an integer" in result.output


def test_sitelinks_add_pipe_spec_invalid_raises():
    """Unescaped '|' overflowing the 3-part shape must error with a hint."""
    result = _rejected(
        "sitelinks",
        "add",
        "--sitelink",
        "Главная|https://example.com/?utm=cid|{cid}|gid|{gbid}|Узнать",
    )
    assert "Invalid sitelink" in result.output
    assert "\\|" in result.output


def test_sitelinks_add_from_inline_json():
    body = _dry_run(
        "sitelinks",
        "add",
        "--sitelink-json",
        json.dumps(
            [
                {
                    "Title": "Главная",
                    "Href": "https://example.com/?utm=cid|{cid}",
                    "Description": "Узнать",
                },
                {"Title": "Контакты", "Href": "https://example.com/contact"},
            ]
        ),
    )
    assert body["params"]["SitelinksSets"][0]["Sitelinks"] == [
        {
            "Title": "Главная",
            "Href": "https://example.com/?utm=cid|{cid}",
            "Description": "Узнать",
        },
        {"Title": "Контакты", "Href": "https://example.com/contact"},
    ]


def test_sitelinks_add_from_inline_json_turbo_page_id_without_href():
    body = _dry_run(
        "sitelinks",
        "add",
        "--sitelink-json",
        json.dumps([{"Title": "Turbo", "TurboPageId": 12345}]),
    )
    assert body["params"]["SitelinksSets"][0]["Sitelinks"] == [
        {"Title": "Turbo", "TurboPageId": 12345}
    ]


def test_sitelinks_add_from_inline_json_turbo_page_id_string_coerced():
    body = _dry_run(
        "sitelinks",
        "add",
        "--sitelink-json",
        json.dumps([{"Title": "Turbo", "TurboPageId": "12345"}]),
    )
    assert body["params"]["SitelinksSets"][0]["Sitelinks"] == [
        {"Title": "Turbo", "TurboPageId": 12345}
    ]


def test_sitelinks_add_from_inline_json_turbo_page_id_invalid_rejected():
    result = _rejected(
        "sitelinks",
        "add",
        "--sitelink-json",
        json.dumps([{"Title": "Turbo", "TurboPageId": "not-an-id"}]),
    )
    assert "'TurboPageId' must be an integer" in result.output


def test_sitelinks_add_from_inline_json_turbo_page_id_bool_rejected():
    result = _rejected(
        "sitelinks",
        "add",
        "--sitelink-json",
        json.dumps([{"Title": "Turbo", "TurboPageId": False}]),
    )
    assert "'TurboPageId' must be an integer" in result.output


def test_sitelinks_add_from_inline_json_turbo_page_id_float_rejected():
    result = _rejected(
        "sitelinks",
        "add",
        "--sitelink-json",
        json.dumps([{"Title": "Turbo", "TurboPageId": 12.5}]),
    )
    assert "'TurboPageId' must be an integer" in result.output


def test_sitelinks_add_from_file_jsonl(tmp_path):
    jsonl_path = tmp_path / "sitelinks.jsonl"
    jsonl_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "Title": "Главная",
                        "Href": "https://example.com/?utm=cid|{cid}",
                    }
                ),
                "",
                json.dumps(
                    {
                        "Title": "Контакты",
                        "Href": "https://example.com/contact",
                        "Description": "Связаться",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    body = _dry_run(
        "sitelinks",
        "add",
        "--sitelinks-from-file",
        str(jsonl_path),
    )
    assert body["params"]["SitelinksSets"][0]["Sitelinks"] == [
        {"Title": "Главная", "Href": "https://example.com/?utm=cid|{cid}"},
        {
            "Title": "Контакты",
            "Href": "https://example.com/contact",
            "Description": "Связаться",
        },
    ]


def test_sitelinks_add_mixed_sources_rejected():
    result = _rejected(
        "sitelinks",
        "add",
        "--sitelink",
        "About|https://example.com/about",
        "--sitelink-json",
        '[{"Title":"X","Href":"https://example.com/"}]',
    )
    assert "mutually exclusive" in result.output


def test_sitelinks_add_no_source_rejected():
    result = _rejected("sitelinks", "add")
    assert "Provide exactly one of" in result.output


def test_sitelinks_add_json_missing_href_rejected():
    result = _rejected(
        "sitelinks",
        "add",
        "--sitelink-json",
        '[{"Title":"Главная"}]',
    )
    assert "Sitelink #1" in result.output
    assert "Href" in result.output
    assert "TurboPageId" in result.output


def test_sitelinks_add_json_not_array_rejected():
    result = _rejected(
        "sitelinks",
        "add",
        "--sitelink-json",
        '{"Title":"X","Href":"https://example.com/"}',
    )
    assert "must be a JSON array" in result.output


def test_sitelinks_add_rejects_unknown_field():
    """Typo in a JSON key must fail loudly, not silently drop. See PR #223."""
    result = _rejected(
        "sitelinks",
        "add",
        "--sitelink-json",
        json.dumps(
            [
                {
                    "Title": "Главная",
                    "Href": "https://example.com/",
                    "Decsription": "typo",
                }
            ]
        ),
    )
    assert "Unknown field 'Decsription'" in result.output
    assert "sitelink #1" in result.output


def test_sitelinks_add_empty_json_rejected():
    """`--sitelink-json ''` is provided-but-invalid, not absent. See PR #223."""
    result = _rejected("sitelinks", "add", "--sitelink-json", "")
    assert "invalid JSON" in result.output


def test_vcards_add_uses_typed_flags():
    body = _dry_run(
        "vcards",
        "add",
        "--campaign-id",
        "555",
        "--country",
        "Россия",
        "--city",
        "Москва",
        "--company-name",
        "Acme",
        "--work-time",
        "1#5#9#0#18#0",
        "--phone-country-code",
        "+7",
        "--phone-city-code",
        "495",
        "--phone-number",
        "1234567",
    )
    assert body["method"] == "add"
    assert body["params"]["VCards"] == [
        {
            "CampaignId": 555,
            "Country": "Россия",
            "City": "Москва",
            "CompanyName": "Acme",
            "WorkTime": "1#5#9#0#18#0",
            "Phone": {
                "CountryCode": "+7",
                "CityCode": "495",
                "PhoneNumber": "1234567",
            },
        }
    ]


def test_vcards_add_instant_messenger_payload():
    body = _dry_run(
        "vcards",
        "add",
        "--campaign-id",
        "555",
        "--country",
        "Россия",
        "--city",
        "Москва",
        "--company-name",
        "Acme",
        "--work-time",
        "1#5#9#0#18#0",
        "--phone-country-code",
        "+7",
        "--phone-city-code",
        "495",
        "--phone-number",
        "1234567",
        "--instant-messenger-client",
        "telegram",
        "--instant-messenger-login",
        "acme_support",
    )
    vcard = body["params"]["VCards"][0]
    assert vcard["InstantMessenger"] == {
        "MessengerClient": "telegram",
        "MessengerLogin": "acme_support",
    }


def test_vcards_add_instant_messenger_partial_rejected():
    result = _rejected(
        "vcards",
        "add",
        "--campaign-id",
        "555",
        "--country",
        "Россия",
        "--city",
        "Москва",
        "--company-name",
        "Acme",
        "--work-time",
        "1#5#9#0#18#0",
        "--phone-country-code",
        "+7",
        "--phone-city-code",
        "495",
        "--phone-number",
        "1234567",
        "--instant-messenger-client",
        "telegram",
    )
    assert "--instant-messenger-client and --instant-messenger-login" in result.output
    assert result.exit_code == 2


def test_vcards_add_point_on_map_payload():
    body = _dry_run(
        "vcards",
        "add",
        "--campaign-id",
        "555",
        "--country",
        "Россия",
        "--city",
        "Москва",
        "--company-name",
        "Acme",
        "--work-time",
        "1#5#9#0#18#0",
        "--phone-country-code",
        "+7",
        "--phone-city-code",
        "495",
        "--phone-number",
        "1234567",
        "--point-on-map-x",
        "37.6173",
        "--point-on-map-y",
        "55.7558",
        "--point-on-map-x1",
        "37.60",
        "--point-on-map-y1",
        "55.74",
        "--point-on-map-x2",
        "37.63",
        "--point-on-map-y2",
        "55.77",
    )
    vcard = body["params"]["VCards"][0]
    assert vcard["PointOnMap"] == {
        "X": 37.6173,
        "Y": 55.7558,
        "X1": 37.60,
        "Y1": 55.74,
        "X2": 37.63,
        "Y2": 55.77,
    }


def test_vcards_add_point_on_map_partial_rejected():
    result = _rejected(
        "vcards",
        "add",
        "--campaign-id",
        "555",
        "--country",
        "Россия",
        "--city",
        "Москва",
        "--company-name",
        "Acme",
        "--work-time",
        "1#5#9#0#18#0",
        "--phone-country-code",
        "+7",
        "--phone-city-code",
        "495",
        "--phone-number",
        "1234567",
        "--point-on-map-x",
        "37.6173",
    )
    assert "PointOnMap requires all coordinate flags" in result.output
    assert "--point-on-map-y" in result.output
    assert result.exit_code == 2


def test_adextensions_get_callout_field_names_payload():
    body = _read_dry_run(
        "adextensions",
        "get",
        "--types",
        "CALLOUT",
        "--fields",
        "Id,Type,State,Status",
        "--callout-field-names",
        "CalloutText",
    )

    assert body["params"]["SelectionCriteria"] == {"Types": ["CALLOUT"]}
    assert body["params"]["FieldNames"] == ["Id", "Type", "State", "Status"]
    assert "CalloutText" not in body["params"]["FieldNames"]
    assert body["params"]["CalloutFieldNames"] == ["CalloutText"]


def test_adextensions_get_help_exposes_callout_field_names():
    result = CliRunner().invoke(cli, ["adextensions", "get", "--help"])

    assert result.exit_code == 0
    assert "--callout-field-names" in result.output


def test_adextensions_get_rejects_empty_callout_field_names():
    result = CliRunner().invoke(
        cli,
        [
            "adextensions",
            "get",
            "--callout-field-names",
            ",",
            "--dry-run",
        ],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )

    assert result.exit_code != 0
    assert (
        "Provide a non-empty comma-separated CalloutFieldNames list." in result.output
    )


def test_adextensions_add_does_not_send_type_field():
    body = _dry_run(
        "adextensions",
        "add",
        "--callout-text",
        "Free shipping",
    )
    assert body["method"] == "add"
    ext = body["params"]["AdExtensions"][0]
    # The API derives the extension type from the nested field name
    # (Callout).  AdExtensionAddItem only supports Callout per WSDL.
    assert "Type" not in ext
    assert ext == {"Callout": {"CalloutText": "Free shipping"}}


def test_sitelinks_get_sitelink_field_names_payload():
    # WSDL ``tests/wsdl_cache/sitelinks.xml`` SitelinksGetRequest declares
    # ``SitelinkFieldNames`` (SitelinkFieldEnum: Title, Href, Description,
    # TurboPageId) as a top-level field separate from ``FieldNames``
    # (SitelinksSetFieldEnum: Id, Sitelinks). The CLI must keep them
    # independent so the nested SitelinkSet item-field projection can be
    # controlled without overloading ``--fields``.
    body = _read_dry_run(
        "sitelinks",
        "get",
        "--fields",
        "Id,Sitelinks",
        "--sitelink-field-names",
        "Title,Href,Description",
    )

    assert body["params"]["FieldNames"] == ["Id", "Sitelinks"]
    assert body["params"]["SitelinkFieldNames"] == ["Title", "Href", "Description"]


def test_sitelinks_get_default_omits_sitelink_field_names():
    # When --sitelink-field-names is not given the parameter must not be
    # sent — Yandex falls back to its built-in default projection.
    body = _read_dry_run("sitelinks", "get")

    assert "SitelinkFieldNames" not in body["params"]


def test_sitelinks_get_help_exposes_sitelink_field_names():
    result = CliRunner().invoke(cli, ["sitelinks", "get", "--help"])

    assert result.exit_code == 0
    assert "--sitelink-field-names" in result.output


def test_sitelinks_get_rejects_empty_sitelink_field_names():
    result = CliRunner().invoke(
        cli,
        ["sitelinks", "get", "--sitelink-field-names", ",", "--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )

    assert result.exit_code != 0
    assert (
        "Provide a non-empty comma-separated SitelinkFieldNames list." in result.output
    )


def test_feeds_get_nested_field_names_payload():
    # FeedsGetRequest (WSDL tests/wsdl_cache/feeds.xml) declares two
    # nested top-level *FieldNames parameters separate from FieldNames:
    # FileFeedFieldNames (FileFeedFieldEnum: Filename) and
    # UrlFeedFieldNames (UrlFeedFieldEnum: Login, Url, RemoveUtmTags).
    body = _read_dry_run(
        "feeds",
        "get",
        "--file-feed-field-names",
        "Filename",
        "--url-feed-field-names",
        "Login,Url,RemoveUtmTags",
    )

    params = body["params"]
    assert params["FileFeedFieldNames"] == ["Filename"]
    assert params["UrlFeedFieldNames"] == ["Login", "Url", "RemoveUtmTags"]


def test_feeds_get_omits_nested_field_names_by_default():
    body = _read_dry_run("feeds", "get")

    assert "FileFeedFieldNames" not in body["params"]
    assert "UrlFeedFieldNames" not in body["params"]


def test_feeds_get_help_exposes_nested_field_names():
    result = CliRunner().invoke(cli, ["feeds", "get", "--help"])

    assert result.exit_code == 0
    assert "--file-feed-field-names" in result.output
    assert "--url-feed-field-names" in result.output


def test_feeds_get_rejects_empty_file_feed_field_names_csv():
    result = CliRunner().invoke(
        cli,
        ["feeds", "get", "--file-feed-field-names", ",", "--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )

    assert result.exit_code != 0
    assert (
        "Provide a non-empty comma-separated FileFeedFieldNames list." in result.output
    )


def test_feeds_get_rejects_empty_url_feed_field_names_csv():
    result = CliRunner().invoke(
        cli,
        ["feeds", "get", "--url-feed-field-names", ",", "--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )

    assert result.exit_code != 0
    assert (
        "Provide a non-empty comma-separated UrlFeedFieldNames list." in result.output
    )
