"""``TokenTransactionType`` gains ``WITHDRAW`` (S79 D5).

Generic ledger vocabulary alongside PURCHASE/REFUND/ADJUSTMENT — tokens
are core-owned, so this is not a plugin-vocab leak. The DB column is a
native Postgres enum, so the value is added by the core migration
``20260612_1100_withdraw_tx_type`` (resolves standalone, plugin-free).
"""
from vbwd.models.enums import TokenTransactionType


def test_withdraw_is_a_token_transaction_type():
    assert TokenTransactionType.WITHDRAW.value == "WITHDRAW"


def test_withdraw_parses_from_its_canonical_value():
    assert TokenTransactionType("WITHDRAW") is TokenTransactionType.WITHDRAW
