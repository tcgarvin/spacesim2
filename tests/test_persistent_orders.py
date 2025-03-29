import pytest

from spacesim2.core.actor import Actor, ActorType
from spacesim2.core.commodity import CommodityType, Inventory
from spacesim2.core.market import Market, Order, Transaction
from spacesim2.core.planet import Planet
from spacesim2.core.simulation import Simulation


def test_order_reservation_system() -> None:
    """Test that resources are properly reserved when placing orders."""
    market = Market()
    
    # Create buyer with 100 money
    buyer = Actor("Buyer", initial_money=100)
    
    # Place a buy order for 5 food at 10 credits each
    order_id = market.place_buy_order(buyer, CommodityType.RAW_FOOD, 5, 10)
    
    # Check that money is reserved
    assert buyer.money == 50  # 100 - (5 * 10)
    assert buyer.reserved_money == 50
    assert order_id is not None and order_id != ""
    
    # Create seller with 10 food
    seller = Actor("Seller")
    seller.inventory.add_commodity(CommodityType.RAW_FOOD, 10)
    
    # Before placing order, check inventory
    assert seller.inventory.get_quantity(CommodityType.RAW_FOOD) == 10
    assert seller.inventory.get_available_quantity(CommodityType.RAW_FOOD) == 10
    assert seller.inventory.get_reserved_quantity(CommodityType.RAW_FOOD) == 0
    
    # Place a sell order for 5 food at 8 credits each
    order_id = market.place_sell_order(seller, CommodityType.RAW_FOOD, 5, 8)
    
    # Check that inventory is reserved
    assert seller.inventory.get_quantity(CommodityType.RAW_FOOD) == 10  # Total unchanged
    assert seller.inventory.get_available_quantity(CommodityType.RAW_FOOD) == 5  # Available reduced
    assert seller.inventory.get_reserved_quantity(CommodityType.RAW_FOOD) == 5  # Reserved increased
    assert order_id is not None and order_id != ""
    
    # Match orders
    market.match_orders()
    
    # Check that reserved resources were used properly
    assert buyer.money == 50  # Unchanged (50 reserved was used)
    assert buyer.reserved_money == 0  # All reserved money was spent
    assert buyer.inventory.get_quantity(CommodityType.RAW_FOOD) == 5  # Gained 5 food
    
    assert seller.money == 90  # 50 (default) + (5 * 8)
    assert seller.inventory.get_quantity(CommodityType.RAW_FOOD) == 5  # 10 - 5
    assert seller.inventory.get_available_quantity(CommodityType.RAW_FOOD) == 5
    assert seller.inventory.get_reserved_quantity(CommodityType.RAW_FOOD) == 0  # All reserved was sold


def test_cancel_order() -> None:
    """Test that orders can be canceled and resources unreserved."""
    market = Market()
    
    # Create buyer with 100 money
    buyer = Actor("Buyer", initial_money=100)
    
    # Place a buy order
    order_id = market.place_buy_order(buyer, CommodityType.RAW_FOOD, 5, 10)
    
    # Check reservation
    assert buyer.money == 50
    assert buyer.reserved_money == 50
    
    # Cancel the order
    assert market.cancel_order(order_id)
    
    # Check that money was returned
    assert buyer.money == 100
    assert buyer.reserved_money == 0
    
    # Check that order is gone
    assert len(market.buy_orders[CommodityType.RAW_FOOD]) == 0
    assert order_id not in market.orders_by_id
    
    # Test with sell order
    seller = Actor("Seller")
    seller.inventory.add_commodity(CommodityType.RAW_FOOD, 10)
    
    # Place sell order
    order_id = market.place_sell_order(seller, CommodityType.RAW_FOOD, 5, 8)
    
    # Check reservation
    assert seller.inventory.get_available_quantity(CommodityType.RAW_FOOD) == 5
    assert seller.inventory.get_reserved_quantity(CommodityType.RAW_FOOD) == 5
    
    # Cancel the order
    assert market.cancel_order(order_id)
    
    # Check that inventory was returned
    assert seller.inventory.get_available_quantity(CommodityType.RAW_FOOD) == 10
    assert seller.inventory.get_reserved_quantity(CommodityType.RAW_FOOD) == 0


def test_modify_order() -> None:
    """Test that order modification works correctly."""
    market = Market()
    
    # Create buyer with 100 money
    buyer = Actor("Buyer", initial_money=100)
    
    # Place a buy order
    order_id = market.place_buy_order(buyer, CommodityType.RAW_FOOD, 5, 10)
    
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


def test_order_persistence() -> None:
    """Test that orders persist across market cycles."""
    market = Market()
    
    # Create buyer and seller
    buyer = Actor("Buyer", initial_money=100)
    seller = Actor("Seller")
    seller.inventory.add_commodity(CommodityType.RAW_FOOD, 10)
    
    # Place non-matching orders
    market.place_buy_order(buyer, CommodityType.RAW_FOOD, 5, 7)
    market.place_sell_order(seller, CommodityType.RAW_FOOD, 5, 10)
    
    # Run matching - should not match
    market.match_orders()
    
    # Verify orders still exist
    assert len(market.buy_orders[CommodityType.RAW_FOOD]) == 1
    assert len(market.sell_orders[CommodityType.RAW_FOOD]) == 1
    
    # Update buyer's order to match
    buy_order = market.buy_orders[CommodityType.RAW_FOOD][0]
    market.modify_order(buy_order.order_id, 10)
    
    # Now match should succeed
    market.match_orders()
    
    # Verify transaction occurred
    assert len(market.transaction_history) == 1
    assert market.transaction_history[0].price == 10
    
    # Verify orders are gone (fully matched)
    assert len(market.buy_orders[CommodityType.RAW_FOOD]) == 0
    assert len(market.sell_orders[CommodityType.RAW_FOOD]) == 0


def test_actor_order_tracking() -> None:
    """Test that actors can track their orders."""
    market = Market()
    
    # Create buyer
    buyer = Actor("Buyer", initial_money=100)
    
    # Place buy order
    order_id = market.place_buy_order(buyer, CommodityType.RAW_FOOD, 5, 10)
    
    # Check that actor is tracking the order
    assert order_id in buyer.active_orders
    assert buyer.active_orders[order_id] == "buy RAW_FOOD"
    
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


def test_market_maker_strategy() -> None:
    """Test that market makers manage their orders effectively."""
    # Create a planet with a market
    planet = Planet("Test Planet")
    market = Market()
    planet.market = market
    
    # Create a market maker with some initial inventory
    market_maker = Actor("MM-1", planet=planet, actor_type=ActorType.MARKET_MAKER)
    market_maker.inventory.add_commodity(CommodityType.RAW_FOOD, 20)
    
    # Add price history to trigger sophisticated market making
    market.price_history[CommodityType.RAW_FOOD] = [10, 11, 9, 10, 12]
    market.volume_history[CommodityType.RAW_FOOD] = [5, 6, 4, 7, 8]
    
    # First turn - should place initial orders
    market_maker._do_market_maker_actions()
    
    # Check that orders were placed
    mm_orders = market.get_actor_orders(market_maker)
    initial_buy_count = len(mm_orders["buy"])
    initial_sell_count = len(mm_orders["sell"])
    
    assert initial_buy_count > 0
    assert initial_sell_count > 0
    
    # Record initial orders
    initial_buy_orders = list(mm_orders["buy"])
    initial_sell_orders = list(mm_orders["sell"])
    
    # Advance turn - no market changes, shouldn't cancel orders
    market.current_turn += 1
    market_maker._do_market_maker_actions()
    
    # Check that orders persisted
    mm_orders = market.get_actor_orders(market_maker)
    assert len(mm_orders["buy"]) >= initial_buy_count
    assert len(mm_orders["sell"]) >= initial_sell_count
    
    # Check that at least some initial orders are still there
    current_buy_ids = [o.order_id for o in mm_orders["buy"]]
    current_sell_ids = [o.order_id for o in mm_orders["sell"]]
    
    assert any(o.order_id in current_buy_ids for o in initial_buy_orders)
    assert any(o.order_id in current_sell_ids for o in initial_sell_orders)
    
    # Simulate significant price change to trigger order updates
    market.price_history[CommodityType.RAW_FOOD] = [10, 11, 9, 15, 18]  # Big price increase
    market.current_turn += 5  # Advance 5 turns to trigger age-based cancellation
    
    # Run market maker actions
    market_maker._do_market_maker_actions()
    
    # Check that orders were adjusted
    mm_orders = market.get_actor_orders(market_maker)
    
    # Old orders should be canceled and new ones placed
    assert not all(o.order_id in current_buy_ids for o in mm_orders["buy"])
    assert not all(o.order_id in current_sell_ids for o in mm_orders["sell"])


def test_regular_actor_strategy() -> None:
    """Test that regular actors manage their orders effectively."""
    # Create a planet with a market
    planet = Planet("Test Planet")
    market = Market()
    planet.market = market
    
    # Set market price
    market.last_traded_prices[CommodityType.RAW_FOOD] = [10]
    
    # Create a regular actor with not enough food
    actor = Actor("Actor-1", planet=planet)
    actor.inventory.add_commodity(CommodityType.RAW_FOOD, 3)  # Below threshold of 5
    
    # Should place a buy order
    actor._do_regular_market_actions()
    
    # Check that a buy order was placed
    actor_orders = market.get_actor_orders(actor)
    assert len(actor_orders["buy"]) == 1
    assert len(actor_orders["sell"]) == 0
    
    # Add food to inventory (now has plenty)
    actor.inventory.add_commodity(CommodityType.RAW_FOOD, 10)  # Now has 13
    
    # Should cancel buy order and place a sell order
    actor._do_regular_market_actions()
    
    # Check that buy order was canceled and sell order placed
    actor_orders = market.get_actor_orders(actor)
    assert len(actor_orders["buy"]) == 0
    assert len(actor_orders["sell"]) == 1


def test_integrated_market_simulation() -> None:
    """Test full market simulation with multiple actors trading."""
    # Create simulation with actors
    sim = Simulation()
    sim.setup_simple(num_regular_actors=3, num_market_makers=1)
    
    # Run for several turns to establish market
    for _ in range(10):
        sim.run_turn()
    
    # Check that transactions are occurring
    planet = sim.planets[0]
    assert len(planet.market.transaction_history) > 0
    
    # Verify actors have active orders
    for actor in sim.actors:
        actor_orders = planet.market.get_actor_orders(actor)
        
        # Should have some orders (either buy or sell)
        total_orders = len(actor_orders["buy"]) + len(actor_orders["sell"])
        
        # Market makers should always have orders, regular actors might not
        if actor.actor_type == ActorType.MARKET_MAKER:
            assert total_orders > 0
    
    # Check for reserved resources
    for actor in sim.actors:
        if actor.actor_type == ActorType.MARKET_MAKER:
            # Market makers should be using the reservation system
            if len(planet.market.get_actor_orders(actor)["buy"]) > 0:
                assert actor.reserved_money > 0
            
            if len(planet.market.get_actor_orders(actor)["sell"]) > 0:
                total_reserved = sum(
                    actor.inventory.get_reserved_quantity(c_type)
                    for c_type in [CommodityType.RAW_FOOD]
                )
                assert total_reserved > 0