import pytest
from typing import Dict, Tuple

from spacesim2.core.actor import Actor
from spacesim2.core.commodity import CommodityRegistry, CommodityDefinition, Inventory
from spacesim2.core.market import Market

from .helpers import get_actor


@pytest.fixture
def commodity_registry():
    """Create a commodity registry with test commodities."""
    registry = CommodityRegistry()
    registry.load_from_file("data/commodities.yaml")
    return registry


@pytest.fixture
def nova_fuel(commodity_registry):
    """Get the nova_fuel commodity definition."""
    return commodity_registry.get_commodity("nova_fuel")


@pytest.fixture
def market_with_actors(commodity_registry, nova_fuel, mock_sim) -> Tuple[Market, Actor, Actor]:
    """Set up a market with buyer and seller actors."""
    market = Market()
    market.commodity_registry = commodity_registry
    
    buyer = get_actor("Buyer", mock_sim, initial_money=1000)
    seller = get_actor("Seller", mock_sim, initial_money=500)
    
    # Give the seller some nova_fuel
    seller.inventory.add_commodity(nova_fuel, 20)
    
    return market, buyer, seller


def count_total_commodities(market: Market, commodity: CommodityDefinition, *actors: Actor) -> int:
    """Count the total amount of a commodity across all actors."""
    total = 0
    for actor in actors:
        total += actor.inventory.get_quantity(commodity)
    return total


def count_total_money(market: Market, *actors: Actor) -> int:
    """Count the total money across all actors (available + reserved)."""
    total = 0
    for actor in actors:
        total += actor.money + actor.reserved_money
    return total


def test_conservation_in_normal_trade(market_with_actors, nova_fuel):
    """Test that commodity and money are conserved during normal trading."""
    market, buyer, seller = market_with_actors
    
    # Record initial state
    initial_commodity_count = count_total_commodities(market, nova_fuel, buyer, seller)
    initial_money = count_total_money(market, buyer, seller)
    
    # Place orders
    market.place_buy_order(buyer, nova_fuel, 5, 10)
    market.place_sell_order(seller, nova_fuel, 5, 10)
    
    # Before matching, check that totals are unchanged
    assert count_total_commodities(market, nova_fuel, buyer, seller) == initial_commodity_count
    assert count_total_money(market, buyer, seller) == initial_money
    
    # Match orders
    market.match_orders()
    
    # After matching, check that totals are still unchanged
    assert count_total_commodities(market, nova_fuel, buyer, seller) == initial_commodity_count
    assert count_total_money(market, buyer, seller) == initial_money


def test_conservation_with_partial_matches(market_with_actors, nova_fuel):
    """Test that commodity and money are conserved with partial order matches."""
    market, buyer, seller = market_with_actors
    
    # Record initial state
    initial_commodity_count = count_total_commodities(market, nova_fuel, buyer, seller)
    initial_money = count_total_money(market, buyer, seller)
    
    # Place orders with different quantities
    market.place_buy_order(buyer, nova_fuel, 8, 10)
    market.place_sell_order(seller, nova_fuel, 5, 10)
    
    # Match orders
    market.match_orders()
    
    # Check that totals are still unchanged after partial match
    assert count_total_commodities(market, nova_fuel, buyer, seller) == initial_commodity_count
    assert count_total_money(market, buyer, seller) == initial_money


def test_conservation_after_order_cancellation(market_with_actors, nova_fuel):
    """Test that commodity and money are conserved when orders are cancelled."""
    market, buyer, seller = market_with_actors
    
    # Record initial state
    initial_commodity_count = count_total_commodities(market, nova_fuel, buyer, seller)
    initial_money = count_total_money(market, buyer, seller)
    
    # Place orders
    buy_order_id = market.place_buy_order(buyer, nova_fuel, 5, 10)
    sell_order_id = market.place_sell_order(seller, nova_fuel, 5, 10)
    
    # Cancel the orders
    market.cancel_order(buy_order_id)
    market.cancel_order(sell_order_id)
    
    # Check that totals are unchanged after cancellation
    assert count_total_commodities(market, nova_fuel, buyer, seller) == initial_commodity_count
    assert count_total_money(market, buyer, seller) == initial_money


def test_conservation_with_multiple_trades(market_with_actors, nova_fuel):
    """Test that commodity and money are conserved across multiple trading cycles."""
    market, buyer, seller = market_with_actors
    
    # Record initial state
    initial_commodity_count = count_total_commodities(market, nova_fuel, buyer, seller)
    initial_money = count_total_money(market, buyer, seller)
    
    # Execute multiple trade cycles
    for i in range(3):
        # First trade cycle
        market.place_buy_order(buyer, nova_fuel, 2, 10)
        market.place_sell_order(seller, nova_fuel, 2, 10)
        market.match_orders()
        
        # Second trade cycle (reverse direction)
        market.place_buy_order(seller, nova_fuel, 1, 11)
        market.place_sell_order(buyer, nova_fuel, 1, 11)
        market.match_orders()
    
    # Check conservation after multiple trades
    assert count_total_commodities(market, nova_fuel, buyer, seller) == initial_commodity_count
    assert count_total_money(market, buyer, seller) == initial_money


def test_conservation_with_price_changes(market_with_actors, nova_fuel):
    """Test that modifying order prices doesn't affect conservation."""
    market, buyer, seller = market_with_actors
    
    # Record initial state
    initial_commodity_count = count_total_commodities(market, nova_fuel, buyer, seller)
    initial_money = count_total_money(market, buyer, seller)
    
    # Place orders
    buy_order_id = market.place_buy_order(buyer, nova_fuel, 5, 10)
    sell_order_id = market.place_sell_order(seller, nova_fuel, 5, 15)
    
    # Modify prices
    market.modify_order(buy_order_id, 20)
    market.modify_order(sell_order_id, 12)
    
    # Check that totals are unchanged after price modifications
    assert count_total_commodities(market, nova_fuel, buyer, seller) == initial_commodity_count
    assert count_total_money(market, buyer, seller) == initial_money
    
    # Match orders with new prices
    market.match_orders()
    
    # Check conservation after trade with modified prices
    assert count_total_commodities(market, nova_fuel, buyer, seller) == initial_commodity_count
    assert count_total_money(market, buyer, seller) == initial_money


def test_conservation_when_clearing_all_orders(market_with_actors, nova_fuel):
    """Test that clearing all orders properly releases all resources."""
    market, buyer, seller = market_with_actors
    
    # Record initial state
    initial_commodity_count = count_total_commodities(market, nova_fuel, buyer, seller)
    initial_money = count_total_money(market, buyer, seller)
    
    # Place several orders
    market.place_buy_order(buyer, nova_fuel, 3, 10)
    market.place_buy_order(buyer, nova_fuel, 2, 12)
    market.place_sell_order(seller, nova_fuel, 4, 9)
    market.place_sell_order(seller, nova_fuel, 3, 11)
    
    # Clear all orders
    market.clear_orders()
    
    # Check that all resources are properly released
    assert count_total_commodities(market, nova_fuel, buyer, seller) == initial_commodity_count
    assert count_total_money(market, buyer, seller) == initial_money
    
    # Verify that order books are empty
    assert len(market.buy_orders.get(nova_fuel, [])) == 0
    assert len(market.sell_orders.get(nova_fuel, [])) == 0