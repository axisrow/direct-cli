from direct_cli.smoke_matrix import DANGEROUS, command_category


def test_v4finance_money_commands_are_dangerous():
    assert command_category("v4finance.transfer-money") == DANGEROUS
    assert command_category("v4finance.pay-campaigns") == DANGEROUS
