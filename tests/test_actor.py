import pytest

from spacesim2.core.actor import Actor, ActorType, ColonistBrain, MarketMakerBrain
from spacesim2.core.commodity import CommodityType
from spacesim2.core.market import Market
from spacesim2.core.planet import Planet


def test_actor_initialization() -> None:
    """Test that an actor can be initialized correctly."""
    actor = Actor("Test Actor", initial_money=50.0)
    assert actor.name == "Test Actor"
    assert actor.money == 50.0
    assert actor.inventory is not None
    assert actor.actor_type == ActorType.REGULAR
    assert isinstance(actor.brain, ColonistBrain)
    
    # Test market maker
    market_maker = Actor("Market Maker", actor_type=ActorType.MARKET_MAKER)
    assert market_maker.actor_type == ActorType.MARKET_MAKER
    assert market_maker.money == 200.0  # Market makers start with more money
    assert isinstance(market_maker.brain, MarketMakerBrain)


def test_actor_consume_food() -> None:
    """Test that an actor can consume food."""
    actor = Actor("Test Actor")
    
    # Initially has no food
    assert not actor.food_consumed_this_turn
    
    actor._consume_food()
    
    # Still has not consumed (no food available)
    assert not actor.food_consumed_this_turn
    
    # Give actor some food
    actor.inventory.add_commodity(CommodityType.RAW_FOOD, 3)
    actor._consume_food()
    
    # Should have consumed 1 food
    assert actor.food_consumed_this_turn
    assert actor.inventory.get_quantity(CommodityType.RAW_FOOD) == 2


def test_actor_produce_food() -> None:
    """Test that an actor can produce food."""
    actor = Actor("Test Actor", production_efficiency=1.0)
    
    # Produce food
    actor.brain._produce_food()
    
    # Check standard production
    expected_output = CommodityType.get_production_quantity(CommodityType.RAW_FOOD)
    assert actor.inventory.get_quantity(CommodityType.RAW_FOOD) == expected_output
    
    # Test with different efficiency
    efficient_actor = Actor("Efficient", production_efficiency=1.5)
    efficient_actor.brain._produce_food()
    
    # Should produce more
    assert efficient_actor.inventory.get_quantity(CommodityType.RAW_FOOD) > expected_output


def test_actor_government_work() -> None:
    """Test that an actor earns money from government work."""
    actor = Actor("Test Actor", initial_money=0.0)
    
    actor.brain._do_government_work()
    
    assert actor.money == 10.0  # Government wage


def test_market_maker_strategy() -> None:
    """Test that a market maker places appropriate buy/sell orders."""
    # Set up planet and market
    planet = Planet("Test Planet")
    market = Market()
    planet.market = market
    
    # Create a market maker
    actor = Actor(
        "Market Maker", 
        planet=planet, 
        actor_type=ActorType.MARKET_MAKER,
        initial_money=100.0
    )
    
    # Give some inventory
    actor.inventory.add_commodity(CommodityType.RAW_FOOD, 10)
    
    # Run market maker strategy
    actor.brain.decide_market_actions()
    
    # Should have placed both buy and sell orders
    assert len(market.buy_orders.get(CommodityType.RAW_FOOD, [])) > 0
    assert len(market.sell_orders.get(CommodityType.RAW_FOOD, [])) > 0
    
    # Buy order should have food price above 0
    buy_order = market.buy_orders[CommodityType.RAW_FOOD][0]
    assert buy_order.price > 0
    
    # Sell order should have higher price than buy order
    sell_order = market.sell_orders[CommodityType.RAW_FOOD][0]
    assert sell_order.price > buy_order.price