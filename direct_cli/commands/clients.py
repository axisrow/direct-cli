"""
Clients commands
"""

import click

from ..api import create_client
from ._execute import execute_request
from ._get import make_get_command
from ..i18n import t
from ..output import handle_api_errors
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
    parse_client_setting_specs,
    parse_email_subscription_specs,
    parse_positive_decimal_amount,
    parse_tin_info,
)


@click.group()
def clients():
    """Manage clients"""


get = make_get_command(
    clients,
    create_client,
    default_fields_key="clients",
    help_text="Get clients",
    ids_help="Comma-separated client IDs",
    ids_criteria_key="ClientIds",
    nested_field_options=(
        (
            "--contract-field-names",
            "ContractFieldNames",
            (
                "Comma-separated ContractFieldNames "
                "(e.g. Number,Date,Price,Type,ActionType). "
                "Sent as separate top-level request parameter per the "
                "ClientsGetRequest WSDL."
            ),
        ),
        (
            "--contragent-field-names",
            "ContragentFieldNames",
            (
                "Comma-separated ContragentFieldNames "
                "(e.g. Name,Phone,EpayNumber,RegNumber). "
                "Sent as separate top-level request parameter per the "
                "ClientsGetRequest WSDL."
            ),
        ),
        (
            "--contragent-tin-info-field-names",
            "ContragentTinInfoFieldNames",
            (
                "Comma-separated ContragentTinInfoFieldNames (e.g. TinType,Tin). "
                "Sent as separate top-level request parameter per the "
                "ClientsGetRequest WSDL."
            ),
        ),
        (
            "--organization-field-names",
            "OrganizationFieldNames",
            (
                "Comma-separated OrganizationFieldNames "
                "(e.g. Name,EpayNumber,RegNumber,OkvedCode). "
                "Sent as separate top-level request parameter per the "
                "ClientsGetRequest WSDL."
            ),
        ),
        (
            "--tin-info-field-names",
            "TinInfoFieldNames",
            (
                "Comma-separated TinInfoFieldNames (e.g. TinType,Tin). "
                "Sent as separate top-level request parameter per the "
                "ClientsGetRequest WSDL."
            ),
        ),
    ),
)


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
@handle_api_errors
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

    execute_request(ctx, "clients", body, dry_run, create_client)
