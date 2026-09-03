"""Tests for the exporter's single-pass per-turn transaction/volume helpers."""

from unittest.mock import Mock

from spacesim2.analysis.export.exporter import (
    transactions_for_turn,
    volume_by_commodity,
)
from spacesim2.core.commodity import CommodityDefinition
from spacesim2.core.market import Market, Transaction


def _commodity(cid: str) -> CommodityDefinition:
    return CommodityDefinition(
        id=cid, name=cid.title(), transportable=True, description=""
    )


def _tx(commodity: CommodityDefinition, quantity: int, turn: int) -> Transaction:
    price = 10
    return Transaction(
        buyer=Mock(name="buyer"),
        seller=Mock(name="seller"),
        commodity_type=commodity,
        quantity=quantity,
        price=price,
        total_amount=quantity * price,
        turn=turn,
    )


def test_transactions_for_turn_selects_only_that_turns_suffix() -> None:
    food = _commodity("food")
    market = Market()
    older = [_tx(food, 1, 1), _tx(food, 2, 2), _tx(food, 3, 2)]
    this_turn = [_tx(food, 4, 3), _tx(food, 5, 3)]
    market.transaction_history = older + this_turn

    assert transactions_for_turn(market, 3) == this_turn


def test_transactions_for_turn_preserves_execution_order() -> None:
    food = _commodity("food")
    market = Market()
    first, second, third = _tx(food, 1, 7), _tx(food, 2, 7), _tx(food, 3, 7)
    market.transaction_history = [_tx(food, 9, 6), first, second, third]

    assert transactions_for_turn(market, 7) == [first, second, third]


def test_transactions_for_turn_empty_when_no_trades_this_turn() -> None:
    food = _commodity("food")
    market = Market()
    market.transaction_history = [_tx(food, 5, 1)]

    assert transactions_for_turn(market, 2) == []
    assert transactions_for_turn(Market(), 1) == []


def test_volume_by_commodity_sums_per_commodity() -> None:
    food = _commodity("food")
    fuel = _commodity("nova_fuel")
    txs = [_tx(food, 3, 5), _tx(fuel, 7, 5), _tx(food, 2, 5)]

    volumes = volume_by_commodity(txs)

    assert volumes[food] == 5
    assert volumes[fuel] == 7
    assert len(volumes) == 2


def test_volume_matches_old_full_history_scan() -> None:
    """Single-pass volume equals a full history scan per commodity."""
    food = _commodity("food")
    fuel = _commodity("nova_fuel")
    market = Market()
    market.transaction_history = [
        _tx(food, 1, 1),
        _tx(fuel, 4, 1),
        _tx(food, 2, 2),
        _tx(fuel, 6, 2),
        _tx(food, 3, 2),
    ]
    turn = 2

    volumes = volume_by_commodity(transactions_for_turn(market, turn))

    for commodity in (food, fuel):
        old_scan = sum(
            tx.quantity
            for tx in market.transaction_history
            if tx.turn == turn and tx.commodity_type == commodity
        )
        assert volumes.get(commodity, 0) == old_scan
