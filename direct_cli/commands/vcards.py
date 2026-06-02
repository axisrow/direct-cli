"""
VCards commands
"""

from typing import Dict, Optional

import click

from ..api import client_from_ctx, create_client
from ..i18n import t
from ..output import format_output, handle_api_errors
from ..utils import get_default_fields, parse_ids


@click.group()
def vcards():
    """Manage vCards"""


def _build_instant_messenger(
    messenger_client: Optional[str],
    messenger_login: Optional[str],
) -> Optional[Dict[str, str]]:
    if not messenger_client and not messenger_login:
        return None
    if not messenger_client or not messenger_login:
        raise click.UsageError(
            t(
                "--instant-messenger-client and --instant-messenger-login must be "
                "provided together"
            )
        )
    return {
        "MessengerClient": messenger_client,
        "MessengerLogin": messenger_login,
    }


def _build_point_on_map(
    x: Optional[float],
    y: Optional[float],
    x1: Optional[float],
    y1: Optional[float],
    x2: Optional[float],
    y2: Optional[float],
) -> Optional[Dict[str, float]]:
    values = {
        "X": x,
        "Y": y,
        "X1": x1,
        "Y1": y1,
        "X2": x2,
        "Y2": y2,
    }
    provided = {name for name, value in values.items() if value is not None}
    if not provided:
        return None
    if len(provided) != len(values):
        missing = ", ".join(
            f"--point-on-map-{name.lower()}"
            for name in sorted(values.keys() - provided)
        )
        raise click.UsageError(
            t("PointOnMap requires all coordinate flags: {missing}").format(
                missing=missing
            )
        )
    return {name: value for name, value in values.items() if value is not None}


@vcards.command()
@click.option("--ids", help="Comma-separated vCard IDs")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def get(ctx, ids, limit, fetch_all, output_format, output, fields, dry_run):
    """Get vCards"""
    client = client_from_ctx(ctx, create_client)

    field_names = fields.split(",") if fields else get_default_fields("vcards")

    criteria = {}
    if ids:
        criteria["Ids"] = parse_ids(ids)

    params = {"FieldNames": field_names}
    if criteria:
        params["SelectionCriteria"] = criteria

    if limit:
        params["Page"] = {"Limit": limit}

    body = {"method": "get", "params": params}

    if dry_run:
        format_output(body, "json", None)
        return

    result = client.vcards().post(data=body)

    if fetch_all:
        items = []
        for item in result().iter_items():
            items.append(item)
        format_output(items, output_format, output)
    else:
        data = result().extract()
        format_output(data, output_format, output)


@vcards.command()
@click.option("--campaign-id", required=True, type=int, help="Campaign ID")
@click.option("--country", required=True, help="Country")
@click.option("--city", required=True, help="City")
@click.option("--company-name", required=True, help="Company name")
@click.option("--work-time", required=True, help="Work time string")
@click.option("--phone-country-code", required=True, help="Phone country code")
@click.option("--phone-city-code", required=True, help="Phone city code")
@click.option("--phone-number", required=True, help="Phone number")
@click.option("--phone-extension", help="Phone extension")
@click.option("--street", help="Street")
@click.option("--house", help="House")
@click.option("--building", help="Building")
@click.option("--apartment", help="Apartment")
@click.option("--contact-person", help="Contact person")
@click.option("--contact-email", help="Contact email")
@click.option("--extra-message", help="Extra message")
@click.option("--ogrn", help="OGRN")
@click.option("--metro-station-id", type=int, help="Metro station ID")
@click.option(
    "--instant-messenger-client",
    help="Instant messenger client for InstantMessenger.MessengerClient",
)
@click.option(
    "--instant-messenger-login",
    help="Instant messenger login for InstantMessenger.MessengerLogin",
)
@click.option("--point-on-map-x", type=float, help="PointOnMap.X coordinate")
@click.option("--point-on-map-y", type=float, help="PointOnMap.Y coordinate")
@click.option("--point-on-map-x1", type=float, help="PointOnMap.X1 coordinate")
@click.option("--point-on-map-y1", type=float, help="PointOnMap.Y1 coordinate")
@click.option("--point-on-map-x2", type=float, help="PointOnMap.X2 coordinate")
@click.option("--point-on-map-y2", type=float, help="PointOnMap.Y2 coordinate")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def add(
    ctx,
    campaign_id,
    country,
    city,
    company_name,
    work_time,
    phone_country_code,
    phone_city_code,
    phone_number,
    phone_extension,
    street,
    house,
    building,
    apartment,
    contact_person,
    contact_email,
    extra_message,
    ogrn,
    metro_station_id,
    instant_messenger_client,
    instant_messenger_login,
    point_on_map_x,
    point_on_map_y,
    point_on_map_x1,
    point_on_map_y1,
    point_on_map_x2,
    point_on_map_y2,
    dry_run,
):
    """Add vCard"""
    instant_messenger = _build_instant_messenger(
        instant_messenger_client,
        instant_messenger_login,
    )
    point_on_map = _build_point_on_map(
        point_on_map_x,
        point_on_map_y,
        point_on_map_x1,
        point_on_map_y1,
        point_on_map_x2,
        point_on_map_y2,
    )
    vcard = {
        "CampaignId": campaign_id,
        "Country": country,
        "City": city,
        "CompanyName": company_name,
        "WorkTime": work_time,
        "Phone": {
            "CountryCode": phone_country_code,
            "CityCode": phone_city_code,
            "PhoneNumber": phone_number,
        },
    }
    if phone_extension:
        vcard["Phone"]["Extension"] = phone_extension
    if street:
        vcard["Street"] = street
    if house:
        vcard["House"] = house
    if building:
        vcard["Building"] = building
    if apartment:
        vcard["Apartment"] = apartment
    if contact_person:
        vcard["ContactPerson"] = contact_person
    if contact_email:
        vcard["ContactEmail"] = contact_email
    if extra_message:
        vcard["ExtraMessage"] = extra_message
    if ogrn:
        vcard["Ogrn"] = ogrn
    if metro_station_id is not None:
        vcard["MetroStationId"] = metro_station_id
    if instant_messenger:
        vcard["InstantMessenger"] = instant_messenger
    if point_on_map:
        vcard["PointOnMap"] = point_on_map

    body = {"method": "add", "params": {"VCards": [vcard]}}

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = client.vcards().post(data=body)
    format_output(result().extract(), "json", None)


@vcards.command()
@click.option("--id", "vcard_id", required=True, type=int, help="vCard ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def delete(ctx, vcard_id, dry_run):
    """Delete vCard"""
    body = {
        "method": "delete",
        "params": {"SelectionCriteria": {"Ids": [vcard_id]}},
    }

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = client.vcards().post(data=body)
    format_output(result().extract(), "json", None)
