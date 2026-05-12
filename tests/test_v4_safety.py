from direct_cli.smoke_matrix import DANGEROUS, SAFE, WRITE_SANDBOX, command_category


def test_v4finance_money_commands_are_dangerous():
    assert command_category("v4finance.create-invoice") == DANGEROUS
    assert command_category("v4finance.transfer-money") == DANGEROUS
    assert command_category("v4finance.pay-campaigns") == DANGEROUS


def test_v4finance_read_commands_are_safe():
    assert command_category("v4finance.check-payment") == SAFE
    assert command_category("v4finance.get-clients-units") == SAFE


def test_v4account_mutation_commands_are_sandbox_write_only():
    assert command_category("v4account.enable-shared-account") == WRITE_SANDBOX
    assert command_category("v4account.account-management") == WRITE_SANDBOX


def test_v4tags_commands_are_classified_by_mutation_risk():
    assert command_category("v4tags.get-campaigns") == SAFE
    assert command_category("v4tags.get-banners") == SAFE
    assert command_category("v4tags.update-campaigns") == WRITE_SANDBOX
    assert command_category("v4tags.update-banners") == WRITE_SANDBOX


def test_v4forecast_commands_are_classified_by_mutation_risk():
    assert command_category("v4forecast.list") == SAFE
    assert command_category("v4forecast.get") == SAFE
    assert command_category("v4forecast.create") == WRITE_SANDBOX
    assert command_category("v4forecast.delete") == WRITE_SANDBOX
