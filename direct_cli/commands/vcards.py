"""
VCards commands
"""

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import get_default_fields, parse_ids


@click.group()
def vcards():
    """Manage vCards"""


@vcards.command()
@click.option("--ids", help="Comma-separated vCard IDs")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def get(ctx, ids, limit, fetch_all, output_format, output, fields, dry_run):
    """Get vCards"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

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

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


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
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
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
    dry_run,
):
    """Add vCard"""
    try:
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

        body = {"method": "add", "params": {"VCards": [vcard]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.vcards().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@vcards.command()
@click.option("--id", "vcard_id", required=True, type=int, help="vCard ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def delete(ctx, vcard_id, dry_run):
    """Delete vCard"""
    try:
        body = {
            "method": "delete",
            "params": {"SelectionCriteria": {"Ids": [vcard_id]}},
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.vcards().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()
