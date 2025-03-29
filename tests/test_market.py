import pytest

from spacesim2.core.actor import Actor
from spacesim2.core.commodity import CommodityType, Inventory
from spacesim2.core.market import Market, Order, Transaction


def test_market_initialization() -> None:
    """Test that a market can be initialized correctly."""
    market = Market()
    assert len(market.buy_orders) == 0
    assert len(market.sell_orders) == 0
    assert len(market.transaction_history) == 0


def test_place_buy_order() -> None:
    """Test that a buy order can be placed in the market."""
    market = Market()
    actor = Actor("Buyer", initial_money=100.0)
    
    market.place_buy_order(actor, CommodityType.RAW_FOOD, 10, 5.0)
    
    assert len(market.buy_orders[CommodityType.RAW_FOOD]) == 1
    order = market.buy_orders[CommodityType.RAW_FOOD][0]
    assert order.actor == actor
    assert order.commodity_type == CommodityType.RAW_FOOD
    assert order.quantity == 10
    assert order.price == 5.0
    assert order.is_buy is True


def test_place_sell_order() -> None:
    """Test that a sell order can be placed in the market."""
    market = Market()
    actor = Actor("Seller")
    
    # Add some food to inventory
    actor.inventory.add_commodity(CommodityType.RAW_FOOD, 10)
    
    market.place_sell_order(actor, CommodityType.RAW_FOOD, 10, 5.0)
    
    assert len(market.sell_orders[CommodityType.RAW_FOOD]) == 1
    order = market.sell_orders[CommodityType.RAW_FOOD][0]
    assert order.actor == actor
    assert order.commodity_type == CommodityType.RAW_FOOD
    assert order.quantity == 10
    assert order.price == 5.0
    assert order.is_buy is False


def test_order_matching() -> None:
    """Test that orders can be matched and transactions executed."""
    market = Market()
    
    # Create actors
    buyer = Actor("Buyer", initial_money=100.0)
    seller = Actor("Seller")
    
    # Give seller some food
    seller.inventory.add_commodity(CommodityType.RAW_FOOD, 10)
    
    # Place matching orders (buy price >= sell price)
    market.place_buy_order(buyer, CommodityType.RAW_FOOD, 5, 10.0)
    market.place_sell_order(seller, CommodityType.RAW_FOOD, 5, 8.0)
    
    # Match orders
    market.match_orders()
    
    # Check transaction
    assert len(market.transaction_history) == 1
    tx = market.transaction_history[0]
    assert tx.buyer == buyer
    assert tx.seller == seller
    assert tx.commodity_type == CommodityType.RAW_FOOD
    assert tx.quantity == 5
    assert tx.price == 8.0  # Uses the sell price
    assert tx.total_amount == 40.0  # 5 * 8.0
    
    # Check money and inventory changes
    assert buyer.money == 60.0  # 100 - 40
    assert buyer.inventory.get_quantity(CommodityType.RAW_FOOD) == 5
    assert seller.money == 90.0  # 50 + 40 (seller starts with 50 by default)
    assert seller.inventory.get_quantity(CommodityType.RAW_FOOD) == 5


def test_order_partial_matching() -> None:
    """Test that orders can be partially matched."""
    market = Market()
    
    # Create actors
    buyer = Actor("Buyer", initial_money=100.0)
    seller = Actor("Seller")
    
    # Give seller more food than will be sold
    seller.inventory.add_commodity(CommodityType.RAW_FOOD, 10)
    
    # Place orders with different quantities
    market.place_buy_order(buyer, CommodityType.RAW_FOOD, 3, 10.0)
    market.place_sell_order(seller, CommodityType.RAW_FOOD, 8, 8.0)
    
    # Match orders
    market.match_orders()
    
    # Check transaction
    assert len(market.transaction_history) == 1
    tx = market.transaction_history[0]
    assert tx.quantity == 3  # Only matches the buy quantity
    
    # Check inventory
    assert buyer.inventory.get_quantity(CommodityType.RAW_FOOD) == 3
    assert seller.inventory.get_quantity(CommodityType.RAW_FOOD) == 7  # 10 - 3
    
    # Check remaining sell order
    assert len(market.sell_orders[CommodityType.RAW_FOOD]) == 1
    assert market.sell_orders[CommodityType.RAW_FOOD][0].quantity == 5  # 8 - 3


def test_no_match_when_bid_too_low() -> None:
    """Test that orders don't match when the bid is lower than the ask."""
    market = Market()
    
    buyer = Actor("Buyer", initial_money=100.0)
    seller = Actor("Seller")
    
    seller.inventory.add_commodity(CommodityType.RAW_FOOD, 10)
    
    # Place non-matching orders (buy price < sell price)
    market.place_buy_order(buyer, CommodityType.RAW_FOOD, 5, 7.0)
    market.place_sell_order(seller, CommodityType.RAW_FOOD, 5, 8.0)
    
    # Try to match orders
    market.match_orders()
    
    # Check that no transactions occurred
    assert len(market.transaction_history) == 0
    
    # Check that orders are still in place
    assert len(market.buy_orders[CommodityType.RAW_FOOD]) == 1
    assert len(market.sell_orders[CommodityType.RAW_FOOD]) == 1


def test_get_avg_price() -> None:
    """Test that average price calculation works correctly."""
    market = Market()
    
    # When no transactions, should return base price
    assert market.get_avg_price(CommodityType.RAW_FOOD) == CommodityType.get_base_price(CommodityType.RAW_FOOD)
    
    # Add some transaction history (manually)
    market.last_traded_prices[CommodityType.RAW_FOOD] = [8.0, 9.0, 10.0]
    
    # Check average
    assert market.get_avg_price(CommodityType.RAW_FOOD) == 9.0


def test_clear_orders() -> None:
    """Test that orders can be cleared from the market."""
    market = Market()
    
    buyer = Actor("Buyer", initial_money=100.0)
    seller = Actor("Seller")
    
    seller.inventory.add_commodity(CommodityType.RAW_FOOD, 10)
    
    market.place_buy_order(buyer, CommodityType.RAW_FOOD, 5, 10.0)
    market.place_sell_order(seller, CommodityType.RAW_FOOD, 5, 8.0)
    
    assert len(market.buy_orders[CommodityType.RAW_FOOD]) == 1
    assert len(market.sell_orders[CommodityType.RAW_FOOD]) == 1
    
    market.clear_orders()
    
    assert len(market.buy_orders) == 0
    assert len(market.sell_orders) == 0