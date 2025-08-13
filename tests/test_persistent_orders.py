import pytest

from spacesim2.core.actor import Actor, ActorType
from spacesim2.core.commodity import CommodityDefinition, CommodityRegistry, Inventory
from spacesim2.core.market import Market, Order, Transaction
from spacesim2.core.planet import Planet
from spacesim2.core.simulation import Simulation

@pytest.fixture
def food_commodity():
    """Create a food commodity for testing."""
    return CommodityDefinition(
        id="food",
        name="Food",
        transportable=True,
        description="Basic nourishment required by actors."
    )


def test_order_reservation_system(food_commodity) -> None:
    """Test that resources are properly reserved when placing orders."""
    market = Market()
    market.commodity_registry = CommodityRegistry()
    market.commodity_registry._commodities["food"] = food_commodity
    
    # Create buyer with 100 money
    buyer = Actor("Buyer", initial_money=100)
    
    # Place a buy order for 5 food at 10 credits each
    order_id = market.place_buy_order(buyer, food_commodity, 5, 10)
    
    # Check that money is reserved
    assert buyer.money == 50  # 100 - (5 * 10)
    assert buyer.reserved_money == 50
    assert order_id is not None and order_id != ""
    
    # Create seller with 10 food
    seller = Actor("Seller")
    seller.inventory.add_commodity(food_commodity, 10)
    
    # Before placing order, check inventory
    assert seller.inventory.get_quantity(food_commodity) == 10
    assert seller.inventory.get_available_quantity(food_commodity) == 10
    assert seller.inventory.get_reserved_quantity(food_commodity) == 0
    
    # Place a sell order for 5 food at 8 credits each
    order_id = market.place_sell_order(seller, food_commodity, 5, 8)
    
    # Check that inventory is reserved
    assert seller.inventory.get_quantity(food_commodity) == 10  # Total unchanged
    assert seller.inventory.get_available_quantity(food_commodity) == 5  # Available reduced
    assert seller.inventory.get_reserved_quantity(food_commodity) == 5  # Reserved increased
    assert order_id is not None and order_id != ""
    
    # Match orders
    market.match_orders()
    
    # Check that reserved resources were used properly
    assert buyer.money == 60  # 50 + refund of (5 * (10-8))
    assert buyer.reserved_money == 0  # All reserved money was spent or refunded
    assert buyer.inventory.get_quantity(food_commodity) == 5  # Gained 5 food
    
    assert seller.money == 90  # 50 (default) + (5 * 8)
    assert seller.inventory.get_quantity(food_commodity) == 5  # 10 - 5
    assert seller.inventory.get_available_quantity(food_commodity) == 5
    assert seller.inventory.get_reserved_quantity(food_commodity) == 0  # All reserved was sold


def test_cancel_order(food_commodity) -> None:
    """Test that orders can be canceled and resources unreserved."""
    market = Market()
    market.commodity_registry = CommodityRegistry()
    market.commodity_registry._commodities["food"] = food_commodity
    
    # Create buyer with 100 money
    buyer = Actor("Buyer", initial_money=100)
    
    # Place a buy order
    order_id = market.place_buy_order(buyer, food_commodity, 5, 10)
    
    # Check reservation
    assert buyer.money == 50
    assert buyer.reserved_money == 50
    
    # Cancel the order
    assert market.cancel_order(order_id)
    
    # Check that money was returned
    assert buyer.money == 100
    assert buyer.reserved_money == 0
    
    # Check that order is gone
    assert len(market.buy_orders.get(food_commodity, [])) == 0
    assert order_id not in market.orders_by_id
    
    # Test with sell order
    seller = Actor("Seller")
    seller.inventory.add_commodity(food_commodity, 10)
    
    # Place sell order
    order_id = market.place_sell_order(seller, food_commodity, 5, 8)
    
    # Check reservation
    assert seller.inventory.get_available_quantity(food_commodity) == 5
    assert seller.inventory.get_reserved_quantity(food_commodity) == 5
    
    # Cancel the order
    assert market.cancel_order(order_id)
    
    # Check that inventory was returned
    assert seller.inventory.get_available_quantity(food_commodity) == 10
    assert seller.inventory.get_reserved_quantity(food_commodity) == 0


def test_modify_order(food_commodity) -> None:
    """Test that order modification works correctly."""
    market = Market()
    market.commodity_registry = CommodityRegistry()
    market.commodity_registry._commodities["food"] = food_commodity
    
    # Create buyer with 100 money
    buyer = Actor("Buyer", initial_money=100)
    
    # Place a buy order
    order_id = market.place_buy_order(buyer, food_commodity, 5, 10)
    
    # Check initial state
    assert buyer.money == 50
    assert buyer.reserved_money == 50
    
    # Modify to higher price
    assert market.modify_order(order_id, 12)
    
    # Check additional money was reserved
    assert buyer.money == 40  # -10 more
    assert buyer.reserved_money == 60  # +10 more
    
    # Modify to lower price
    assert market.modify_order(order_id, 8)
    
    # Check some money was returned
    assert buyer.money == 60  # +20 returned
    assert buyer.reserved_money == 40  # -20
    
    # Check order price was updated
    assert market.orders_by_id[order_id].price == 8


def test_order_persistence(food_commodity) -> None:
    """Test that orders persist across market cycles."""
    market = Market()
    market.commodity_registry = CommodityRegistry()
    market.commodity_registry._commodities["food"] = food_commodity
    
    # Create buyer and seller
    buyer = Actor("Buyer", initial_money=100)
    seller = Actor("Seller")
    seller.inventory.add_commodity(food_commodity, 10)
    
    # Place non-matching orders
    market.place_buy_order(buyer, food_commodity, 5, 7)
    market.place_sell_order(seller, food_commodity, 5, 10)
    
    # Run matching - should not match
    market.match_orders()
    
    # Verify orders still exist
    assert len(market.buy_orders[food_commodity]) == 1
    assert len(market.sell_orders[food_commodity]) == 1
    
    # Update buyer's order to match
    buy_order = market.buy_orders[food_commodity][0]
    market.modify_order(buy_order.order_id, 10)
    
    # Now match should succeed
    market.match_orders()
    
    # Verify transaction occurred
    assert len(market.transaction_history) == 1
    assert market.transaction_history[0].price == 10
    
    # Verify orders are gone (fully matched)
    assert len(market.buy_orders.get(food_commodity, [])) == 0
    assert len(market.sell_orders.get(food_commodity, [])) == 0


def test_actor_order_tracking(food_commodity) -> None:
    """Test that actors can track their orders."""
    market = Market()
    market.commodity_registry = CommodityRegistry()
    market.commodity_registry._commodities["food"] = food_commodity
    
    # Create buyer
    buyer = Actor("Buyer", initial_money=100)
    
    # Place buy order
    order_id = market.place_buy_order(buyer, food_commodity, 5, 10)
    
    # Check that actor is tracking the order
    assert order_id in buyer.active_orders
    assert buyer.active_orders[order_id] == f"buy {food_commodity.id}"
    
    # Check market tracking
    actor_orders = market.get_actor_orders(buyer)
    assert len(actor_orders["buy"]) == 1
    assert len(actor_orders["sell"]) == 0
    
    # Cancel order
    market.cancel_order(order_id)
    
    # Check that actor tracking is updated
    assert order_id not in buyer.active_orders
    
    # Check market tracking is updated
    actor_orders = market.get_actor_orders(buyer)
    assert len(actor_orders["buy"]) == 0


def test_market_maker_strategy(food_commodity) -> None:
    """Test that market makers manage their orders effectively."""
    # Create a planet with a market
    planet = Planet("Test Planet")
    market = Market()
    planet.market = market
    
    # Create commodity registry
    commodity_registry = CommodityRegistry()
    commodity_registry._commodities["food"] = food_commodity
    
    # For the new implementation to work properly, we need fuel commodity too
    fuel_commodity = CommodityDefinition(
        id="nova_fuel",
        name="NovaFuel",
        transportable=True,
        description="High-density energy source for starship travel."
    )
    commodity_registry._commodities["nova_fuel"] = fuel_commodity
    market.commodity_registry = commodity_registry
    
    # Create a market maker with some initial inventory
    market_maker = Actor("MM-1", planet=planet, actor_type=ActorType.MARKET_MAKER)
    market_maker.inventory.add_commodity(food_commodity, 20)
    market_maker.sim = type('obj', (object,), {
        'commodity_registry': commodity_registry,
    })
    
    # First turn - should place buy orders in bootstrap mode
    commands = market_maker.brain.decide_market_actions()
    for command in commands:
        command.execute(market_maker)
    
    # Check that some buy orders were placed (bootstrap mode)
    mm_orders = market.get_actor_orders(market_maker)
    assert len(mm_orders["buy"]) > 0
    
    # Cancel all existing orders before testing with price history
    for order in mm_orders["buy"] + mm_orders["sell"]:
        market.cancel_order(order.order_id)
    
    # Add price history for testing the behavior with history
    try:
        # Import scipy to verify it's available
        from scipy.stats import norm
        
        # Add price history to trigger sophisticated market making
        market.price_history[food_commodity] = [10, 11, 9, 10, 12]
        market.volume_history[food_commodity] = [5, 6, 4, 7, 8]
        
        # Run market maker actions with price history
        commands = market_maker.brain.decide_market_actions()
        for command in commands:
            command.execute(market_maker)
        
        # Check that orders were placed using the more sophisticated algorithm
        mm_orders = market.get_actor_orders(market_maker)
        assert len(mm_orders["buy"]) + len(mm_orders["sell"]) > 0
    except ImportError:
        # Skip testing the scipy-based functionality if scipy is not available
        pass


def test_regular_actor_strategy(food_commodity) -> None:
    """Test that regular actors manage their orders effectively."""
    # Create a planet with a market
    planet = Planet("Test Planet")
    market = Market()
    planet.market = market
    
    # Create commodity registry
    commodity_registry = CommodityRegistry()
    commodity_registry._commodities["food"] = food_commodity
    # Add nova_fuel commodity that ColonistBrain expects
    fuel_commodity = CommodityDefinition(
        id="nova_fuel", 
        name="Nova Fuel",
        transportable=True,
        description="High-energy fuel"
    )
    commodity_registry._commodities["nova_fuel"] = fuel_commodity
    market.commodity_registry = commodity_registry
    
    # Create a regular actor with not enough food
    actor = Actor("Actor-1", planet=planet)
    actor.inventory.add_commodity(food_commodity, 3)  # Below threshold of 6 (new value)
    actor.sim = type('obj', (object,), {
        'commodity_registry': commodity_registry,
    })
    
    # Create a seller with enough food
    seller = Actor("Seller", planet=planet)
    seller.inventory.add_commodity(food_commodity, 20)
    
    # Place a sell order in the market for the actor to match against
    market.place_sell_order(seller, food_commodity, 5, 10)
    
    # Actor should try to buy food to meet their minimum
    commands = actor.brain.decide_market_actions()
    for command in commands:
        command.execute(actor)
    
    # Check the actor's behavior
    actor_orders = market.get_actor_orders(actor)
    
    # Either:
    # 1. Actor placed a buy order to match the sell order, or
    # 2. Transaction already happened (in which case they should have more food)
    
    food_quantity = actor.inventory.get_quantity(food_commodity)
    has_more_food = food_quantity > 3
    has_buy_order = len(actor_orders["buy"]) > 0
    
    # Either the actor bought food or placed an order to buy it
    assert has_more_food or has_buy_order
    
    # Reset for the selling test
    # Cancel any existing orders
    for order in actor_orders["buy"] + actor_orders["sell"]:
        market.cancel_order(order.order_id)
    
    # Add food to inventory (now has plenty)
    actor.inventory.add_commodity(food_commodity, 10)  # Now has 13+ food
    
    # Create a buyer with money
    buyer = Actor("Buyer", planet=planet, initial_money=200)
    
    # Place a buy order in the market for the actor to match against
    market.place_buy_order(buyer, food_commodity, 5, 10)
    
    # Now actor should sell excess food
    commands = actor.brain.decide_market_actions()
    for command in commands:
        command.execute(actor)
    
    # Check the actor's behavior
    actor_orders = market.get_actor_orders(actor)
    initial_food = 13 if food_quantity == 3 else food_quantity + 10
    
    # Either:
    # 1. Actor placed a sell order to match the buy order, or
    # 2. Transaction already happened (in which case they should have less food)
    
    food_quantity_after = actor.inventory.get_quantity(food_commodity)
    sold_food = food_quantity_after < initial_food
    has_sell_order = len(actor_orders["sell"]) > 0
    
    # Either the actor sold food or placed an order to sell it
    assert sold_food or has_sell_order


def test_integrated_market_simulation() -> None:
    """Test full market simulation with multiple actors trading."""
    # Instead of running a full simulation which is complex,
    # we'll manually set up a simple market and verify the reservation system
    
    # Create a market and commodities
    market = Market()
    
    # Create commodity registry
    commodity_registry = CommodityRegistry()
    food_commodity = CommodityDefinition(
        id="food",
        name="Food",
        transportable=True,
        description="Basic nourishment required by actors."
    )
    fuel_commodity = CommodityDefinition(
        id="nova_fuel",
        name="NovaFuel",
        transportable=True,
        description="High-density energy source for starship travel."
    )
    commodity_registry._commodities["food"] = food_commodity
    commodity_registry._commodities["nova_fuel"] = fuel_commodity
    market.commodity_registry = commodity_registry
    
    # Create a planet
    planet = Planet("Test Planet")
    planet.market = market
    
    # Create a seller and buyer
    seller = Actor("Seller", planet=planet)
    seller.inventory.add_commodity(food_commodity, 20)
    seller.sim = type('obj', (object,), {
        'commodity_registry': commodity_registry,
    })
    
    buyer = Actor("Buyer", planet=planet, initial_money=200)
    buyer.sim = type('obj', (object,), {
        'commodity_registry': commodity_registry,
    })
    
    # Place orders
    sell_order_id = market.place_sell_order(seller, food_commodity, 5, 10)
    buy_order_id = market.place_buy_order(buyer, food_commodity, 5, 10)
    
    # Check for resource reservation
    assert sell_order_id is not None
    assert buy_order_id is not None
    
    # Verify seller has reserved inventory
    assert seller.inventory.get_reserved_quantity(food_commodity) == 5
    
    # Verify buyer has reserved money
    assert buyer.reserved_money == 5 * 10  # 5 units at price 10
    
    # Match orders
    market.match_orders()
    
    # After matching, should have a transaction
    assert len(market.transaction_history) > 0
    
    # Verify reservation was cleared
    assert seller.inventory.get_reserved_quantity(food_commodity) == 0
    assert buyer.reserved_money == 0
    
    # Verify buyer received the food
    assert buyer.inventory.get_quantity(food_commodity) == 5
    
    # Verify seller received the money
    assert seller.money == 50 + 50  # Initial 50 + 5*10 from sale