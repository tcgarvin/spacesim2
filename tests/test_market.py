from spacesim2.core.actor import Actor
from spacesim2.core.market import Market


def test_market_initialization() -> None:
    """Test that a market can be initialized correctly."""
    market = Market()
    assert len(market.buy_orders) == 0
    assert len(market.sell_orders) == 0
    assert len(market.transaction_history) == 0


def test_place_buy_order() -> None:
    """Test that a buy order can be placed in the market."""
    market = Market()
    actor = Actor("Buyer")

    market.place_buy_order(actor, quantity=10, price=5.0)

    assert len(market.buy_orders) == 1
    assert market.buy_orders[0].actor == actor
    assert market.buy_orders[0].quantity == 10
    assert market.buy_orders[0].price == 5.0
    assert market.buy_orders[0].is_buy is True


def test_place_sell_order() -> None:
    """Test that a sell order can be placed in the market."""
    market = Market()
    actor = Actor("Seller")

    market.place_sell_order(actor, quantity=10, price=5.0)

    assert len(market.sell_orders) == 1
    assert market.sell_orders[0].actor == actor
    assert market.sell_orders[0].quantity == 10
    assert market.sell_orders[0].price == 5.0
    assert market.sell_orders[0].is_buy is False


def test_clear_orders() -> None:
    """Test that orders can be cleared from the market."""
    market = Market()
    buyer = Actor("Buyer")
    seller = Actor("Seller")

    market.place_buy_order(buyer, quantity=10, price=5.0)
    market.place_sell_order(seller, quantity=10, price=5.0)

    assert len(market.buy_orders) == 1
    assert len(market.sell_orders) == 1

    market.clear_orders()

    assert len(market.buy_orders) == 0
    assert len(market.sell_orders) == 0
