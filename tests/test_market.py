import pytest

from spacesim2.core.actor import Actor
from spacesim2.core.commodity import CommodityDefinition, Inventory, CommodityRegistry
from spacesim2.core.market import Market, Order, Transaction


@pytest.fixture
def commodity_registry():
    """Create a commodity registry with test commodities."""
    registry = CommodityRegistry()
    registry.load_from_file("data/commodities.yaml")
    return registry


@pytest.fixture
def food_commodity(commodity_registry):
    """Get the food commodity definition."""
    return commodity_registry.get_commodity("food")


def test_market_initialization() -> None:
    """Test that a market can be initialized correctly."""
    market = Market()
    assert len(market.buy_orders) == 0
    assert len(market.sell_orders) == 0
    assert len(market.transaction_history) == 0


def test_place_buy_order(commodity_registry, food_commodity, mock_sim) -> None:
    """Test that a buy order can be placed in the market."""
    market = Market()
    market.commodity_registry = commodity_registry
    actor = Actor("Buyer", mock_sim, initial_money=100)
    
    market.place_buy_order(actor, food_commodity, 10, 5)
    
    assert len(market.buy_orders[food_commodity]) == 1
    order = market.buy_orders[food_commodity][0]
    assert order.actor == actor
    assert order.commodity_type == food_commodity
    assert order.quantity == 10
    assert order.price == 5
    assert order.is_buy is True


def test_place_sell_order(commodity_registry, food_commodity, mock_sim) -> None:
    """Test that a sell order can be placed in the market."""
    market = Market()
    market.commodity_registry = commodity_registry
    actor = Actor("Seller", mock_sim)
    
    # Add some food to inventory
    actor.inventory.add_commodity(food_commodity, 10)
    
    market.place_sell_order(actor, food_commodity, 10, 5)
    
    assert len(market.sell_orders[food_commodity]) == 1
    order = market.sell_orders[food_commodity][0]
    assert order.actor == actor
    assert order.commodity_type == food_commodity
    assert order.quantity == 10
    assert order.price == 5
    assert order.is_buy is False


def test_order_matching(commodity_registry, food_commodity, mock_sim) -> None:
    """Test that orders can be matched and transactions executed."""
    market = Market()
    market.commodity_registry = commodity_registry
    
    # Create actors
    buyer = Actor("Buyer", mock_sim, initial_money=100)
    seller = Actor("Seller", mock_sim)
    
    # Give seller some food
    seller.inventory.add_commodity(food_commodity, 10)
    
    # Place matching orders (buy price >= sell price)
    market.place_buy_order(buyer, food_commodity, 5, 10)
    market.place_sell_order(seller, food_commodity, 5, 8)
    
    # Match orders
    market.match_orders()
    
    # Check transaction
    assert len(market.transaction_history) == 1
    tx = market.transaction_history[0]
    assert tx.buyer == buyer
    assert tx.seller == seller
    assert tx.commodity_type == food_commodity
    assert tx.quantity == 5
    assert tx.price == 8  # Uses the sell price
    assert tx.total_amount == 40  # 5 * 8
    
    # Check money and inventory changes
    # With price difference refund: 100 - (5*10) + (5*(10-8)) = 100 - 50 + 10 = 60
    assert buyer.money == 60
    assert buyer.inventory.get_quantity(food_commodity) == 5
    assert seller.money == 90  # 50 + 40 (seller starts with 50 by default)
    assert seller.inventory.get_quantity(food_commodity) == 5


def test_order_partial_matching(commodity_registry, food_commodity, mock_sim) -> None:
    """Test that orders can be partially matched."""
    market = Market()
    market.commodity_registry = commodity_registry
    
    # Create actors
    buyer = Actor("Buyer", mock_sim, initial_money=100)
    seller = Actor("Seller", mock_sim)
    
    # Give seller more food than will be sold
    seller.inventory.add_commodity(food_commodity, 10)
    
    # Place orders with different quantities
    market.place_buy_order(buyer, food_commodity, 3, 10)
    market.place_sell_order(seller, food_commodity, 8, 8)
    
    # Match orders
    market.match_orders()
    
    # Check transaction
    assert len(market.transaction_history) == 1
    tx = market.transaction_history[0]
    assert tx.quantity == 3  # Only matches the buy quantity
    
    # Check inventory
    assert buyer.inventory.get_quantity(food_commodity) == 3
    assert seller.inventory.get_quantity(food_commodity) == 7  # 10 - 3
    
    # Check remaining sell order
    assert len(market.sell_orders[food_commodity]) == 1
    assert market.sell_orders[food_commodity][0].quantity == 5  # 8 - 3


def test_no_match_when_bid_too_low(commodity_registry, food_commodity, mock_sim) -> None:
    """Test that orders don't match when the bid is lower than the ask."""
    market = Market()
    market.commodity_registry = commodity_registry
    
    buyer = Actor("Buyer", mock_sim, initial_money=100)
    seller = Actor("Seller", mock_sim)
    
    seller.inventory.add_commodity(food_commodity, 10)
    
    # Place non-matching orders (buy price < sell price)
    market.place_buy_order(buyer, food_commodity, 5, 7)
    market.place_sell_order(seller, food_commodity, 5, 8)
    
    # Try to match orders
    market.match_orders()
    
    # Check that no transactions occurred
    assert len(market.transaction_history) == 0
    
    # Check that orders are still in place
    assert len(market.buy_orders[food_commodity]) == 1
    assert len(market.sell_orders[food_commodity]) == 1


def test_get_avg_price(commodity_registry, food_commodity) -> None:
    """Test that average price calculation works correctly."""
    market = Market()
    market.commodity_registry = commodity_registry
    
    # When no transactions, should return base price (now 10 by default)
    assert market.get_avg_price(food_commodity) == 10
    
    # Add some transaction history (manually)
    market.last_traded_prices[food_commodity] = [8, 9, 10]
    
    # Check average
    assert market.get_avg_price(food_commodity) == 9


def test_clear_orders(commodity_registry, food_commodity, mock_sim) -> None:
    """Test that orders can be cleared from the market."""
    market = Market()
    market.commodity_registry = commodity_registry
    
    buyer = Actor("Buyer", mock_sim, initial_money=100)
    seller = Actor("Seller", mock_sim)
    
    seller.inventory.add_commodity(food_commodity, 10)
    
    market.place_buy_order(buyer, food_commodity, 5, 10)
    market.place_sell_order(seller, food_commodity, 5, 8)
    
    assert len(market.buy_orders[food_commodity]) == 1
    assert len(market.sell_orders[food_commodity]) == 1
    
    market.clear_orders()
    
    assert len(market.buy_orders) == 0
    assert len(market.sell_orders) == 0