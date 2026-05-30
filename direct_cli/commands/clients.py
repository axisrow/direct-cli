"""
Clients commands
"""

import click

from ..api import create_client
from ..i18n import t
from ..output import format_output, print_error
from ..utils import (
    build_client_update_item,
    build_erir_attributes,
    build_erir_contragent,
    build_erir_contract,
    build_erir_organization,
    build_notification_update,
    CONTRACT_ACTION_TYPES,
    CONTRACT_SUBJECT_TYPES,
    CONTRACT_TYPES,
    get_default_fields,
    parse_client_setting_specs,
    parse_csv_strings,
    parse_email_subscription_specs,
    parse_ids,
    parse_positive_decimal_amount,
    parse_tin_info,
)


@click.group()
def clients():
    """Manage clients"""


@clients.command()
@click.option("--ids", help="Comma-separated client IDs")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.option(
    "--contract-field-names",
    help=(
        "Comma-separated ContractFieldNames "
        "(e.g. Number,Date,Price,Type,ActionType). "
        "Sent as separate top-level request parameter per the "
        "ClientsGetRequest WSDL."
    ),
)
@click.option(
    "--contragent-field-names",
    help=(
        "Comma-separated ContragentFieldNames "
        "(e.g. Name,Phone,EpayNumber,RegNumber). "
        "Sent as separate top-level request parameter per the "
        "ClientsGetRequest WSDL."
    ),
)
@click.option(
    "--contragent-tin-info-field-names",
    help=(
        "Comma-separated ContragentTinInfoFieldNames (e.g. TinType,Tin). "
        "Sent as separate top-level request parameter per the "
        "ClientsGetRequest WSDL."
    ),
)
@click.option(
    "--organization-field-names",
    help=(
        "Comma-separated OrganizationFieldNames "
        "(e.g. Name,EpayNumber,RegNumber,OkvedCode). "
        "Sent as separate top-level request parameter per the "
        "ClientsGetRequest WSDL."
    ),
)
@click.option(
    "--tin-info-field-names",
    help=(
        "Comma-separated TinInfoFieldNames (e.g. TinType,Tin). "
        "Sent as separate top-level request parameter per the "
        "ClientsGetRequest WSDL."
    ),
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def get(
    ctx,
    ids,
    limit,
    fetch_all,
    output_format,
    output,
    fields,
    contract_field_names,
    contragent_field_names,
    contragent_tin_info_field_names,
    organization_field_names,
    tin_info_field_names,
    dry_run,
):
    """Get clients"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        field_names = fields.split(",") if fields else get_default_fields("clients")

        raw_nested = (
            ("ContractFieldNames", contract_field_names),
            ("ContragentFieldNames", contragent_field_names),
            ("ContragentTinInfoFieldNames", contragent_tin_info_field_names),
            ("OrganizationFieldNames", organization_field_names),
            ("TinInfoFieldNames", tin_info_field_names),
        )
        parsed_nested = {}
        for wsdl_key, raw_value in raw_nested:
            parsed = parse_csv_strings(raw_value)
            if raw_value is not None and not parsed:
                raise click.UsageError(
                    t("Provide a non-empty comma-separated {wsdl_key} list.").format(
                        wsdl_key=wsdl_key
                    )
                )
            if parsed:
                parsed_nested[wsdl_key] = parsed

        criteria = {}
        if ids:
            criteria["ClientIds"] = parse_ids(ids)

        params = {"FieldNames": field_names}

        if criteria:
            params["SelectionCriteria"] = criteria

        params.update(parsed_nested)

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        if dry_run:
            format_output(body, "json", None)
            return

        result = client.clients().post(data=body)

        if fetch_all:
            items = []
            for item in result().iter_items():
                items.append(item)
            format_output(items, output_format, output)
        else:
            data = result().extract()
            format_output(data, output_format, output)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@clients.command()
@click.option("--client-info", help="Client information")
@click.option("--phone", help="Client phone")
@click.option("--notification-email", help="Notification email")
@click.option("--notification-lang", help="Notification language")
@click.option(
    "--email-subscription",
    "email_subscriptions",
    multiple=True,
    help="Notification subscription as OPTION=YES|NO",
)
@click.option(
    "--setting",
    "settings",
    multiple=True,
    help="Client setting as OPTION=YES|NO",
)
@click.option("--tin-type", help="TIN type")
@click.option("--tin", help="Taxpayer identification number")
@click.option("--erir-organization-name", help="ErirAttributes.Organization.Name")
@click.option("--erir-organization-kpp", help="ErirAttributes.Organization.Kpp")
@click.option(
    "--erir-organization-epay-number",
    help="ErirAttributes.Organization.EpayNumber",
)
@click.option(
    "--erir-organization-reg-number",
    help="ErirAttributes.Organization.RegNumber",
)
@click.option(
    "--erir-organization-oksm-number",
    help="ErirAttributes.Organization.OksmNumber",
)
@click.option(
    "--erir-organization-okved-code",
    help="ErirAttributes.Organization.OkvedCode",
)
@click.option("--erir-contract-number", help="ErirAttributes.Contract.Number")
@click.option("--erir-contract-date", help="ErirAttributes.Contract.Date (YYYY-MM-DD)")
@click.option(
    "--erir-contract-type",
    type=click.Choice(sorted(CONTRACT_TYPES), case_sensitive=False),
    help="ErirAttributes.Contract.Type",
)
@click.option(
    "--erir-contract-action-type",
    type=click.Choice(sorted(CONTRACT_ACTION_TYPES), case_sensitive=False),
    help="ErirAttributes.Contract.ActionType",
)
@click.option(
    "--erir-contract-subject-type",
    type=click.Choice(sorted(CONTRACT_SUBJECT_TYPES), case_sensitive=False),
    help="ErirAttributes.Contract.SubjectType",
)
@click.option(
    "--erir-contract-is-agency-payment",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="ErirAttributes.Contract.IsAgencyPayment",
)
@click.option(
    "--erir-contract-price-amount",
    help="ErirAttributes.Contract.Price.Amount",
)
@click.option(
    "--erir-contract-price-including-vat",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="ErirAttributes.Contract.Price.IncludingVat",
)
@click.option("--erir-contragent-name", help="ErirAttributes.Contragent.Name")
@click.option("--erir-contragent-kpp", help="ErirAttributes.Contragent.Kpp")
@click.option("--erir-contragent-phone", help="ErirAttributes.Contragent.Phone")
@click.option(
    "--erir-contragent-epay-number",
    help="ErirAttributes.Contragent.EpayNumber",
)
@click.option(
    "--erir-contragent-reg-number",
    help="ErirAttributes.Contragent.RegNumber",
)
@click.option(
    "--erir-contragent-oksm-number",
    help="ErirAttributes.Contragent.OksmNumber",
)
@click.option(
    "--erir-contragent-tin-type",
    help="ErirAttributes.Contragent.TinInfo.TinType",
)
@click.option(
    "--erir-contragent-tin",
    help="ErirAttributes.Contragent.TinInfo.Tin",
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def update(
    ctx,
    client_info,
    phone,
    notification_email,
    notification_lang,
    email_subscriptions,
    settings,
    tin_type,
    tin,
    erir_organization_name,
    erir_organization_kpp,
    erir_organization_epay_number,
    erir_organization_reg_number,
    erir_organization_oksm_number,
    erir_organization_okved_code,
    erir_contract_number,
    erir_contract_date,
    erir_contract_type,
    erir_contract_action_type,
    erir_contract_subject_type,
    erir_contract_is_agency_payment,
    erir_contract_price_amount,
    erir_contract_price_including_vat,
    erir_contragent_name,
    erir_contragent_kpp,
    erir_contragent_phone,
    erir_contragent_epay_number,
    erir_contragent_reg_number,
    erir_contragent_oksm_number,
    erir_contragent_tin_type,
    erir_contragent_tin,
    dry_run,
):
    """Update client settings"""
    try:
        notification = build_notification_update(
            notification_email,
            notification_lang,
            parse_email_subscription_specs(list(email_subscriptions)),
        )
        price_amount = None
        if erir_contract_price_amount is not None:
            price_amount = parse_positive_decimal_amount(
                erir_contract_price_amount,
                "--erir-contract-price-amount",
            )
        client_data = build_client_update_item(
            client_info,
            phone,
            notification,
            parse_client_setting_specs(list(settings)),
            parse_tin_info(tin_type, tin),
            erir_attributes=build_erir_attributes(
                organization=build_erir_organization(
                    erir_organization_name,
                    erir_organization_kpp,
                    erir_organization_epay_number,
                    erir_organization_reg_number,
                    erir_organization_oksm_number,
                    erir_organization_okved_code,
                ),
                contract=build_erir_contract(
                    erir_contract_number,
                    erir_contract_date,
                    erir_contract_type,
                    erir_contract_action_type,
                    erir_contract_subject_type,
                    erir_contract_is_agency_payment,
                    price_amount,
                    erir_contract_price_including_vat,
                ),
                contragent=build_erir_contragent(
                    erir_contragent_name,
                    erir_contragent_kpp,
                    erir_contragent_phone,
                    erir_contragent_epay_number,
                    erir_contragent_reg_number,
                    erir_contragent_oksm_number,
                    parse_tin_info(
                        erir_contragent_tin_type,
                        erir_contragent_tin,
                        "--erir-contragent-tin-type",
                    ),
                ),
            ),
        )
        if not client_data:
            raise click.UsageError(t("Provide at least one field to update"))

        body = {"method": "update", "params": {"Clients": [client_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.clients().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()
