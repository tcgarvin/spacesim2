import pytest

from spacesim2.core.actor import Actor, ActorType, ColonistBrain, MarketMakerBrain
from spacesim2.core.commodity import CommodityDefinition, CommodityRegistry
from spacesim2.core.market import Market
from spacesim2.core.planet import Planet


@pytest.fixture
def mock_sim():
    """Create a mock simulation for testing."""
    return type('MockSimulation', (object,), {
        'commodity_registry': CommodityRegistry()
    })()


@pytest.fixture
def food_commodity():
    """Create a food commodity for testing."""
    return CommodityDefinition(
        id="food",
        name="Food",
        transportable=True,
        description="Basic nourishment required by actors."
    )

def test_actor_initialization(mock_sim) -> None:
    """Test that an actor can be initialized correctly."""
    actor = Actor("Test Actor", mock_sim, initial_money=50)
    assert actor.name == "Test Actor"
    assert actor.money == 50
    assert actor.inventory is not None
    assert actor.actor_type == ActorType.REGULAR
    assert isinstance(actor.brain, ColonistBrain)
    
    # Test market maker
    market_maker = Actor("Market Maker", mock_sim, actor_type=ActorType.MARKET_MAKER)
    assert market_maker.actor_type == ActorType.MARKET_MAKER
    assert market_maker.money == 200  # Market makers start with more money
    assert isinstance(market_maker.brain, MarketMakerBrain)


def test_actor_consume_food(food_commodity, mock_sim) -> None:
    """Test that an actor can consume food."""
    actor = Actor("Test Actor", mock_sim)
    
    # Set up the simulation reference for commodity registry
    from spacesim2.core.commodity import CommodityRegistry
    commodity_registry = CommodityRegistry()
    commodity_registry._commodities["food"] = food_commodity
    actor.sim = type('obj', (object,), {
        'commodity_registry': commodity_registry
    })
    
    # Initially has no food
    assert not actor.food_consumed_this_turn
    
    actor._consume_food()
    
    # Still has not consumed (no food available)
    assert not actor.food_consumed_this_turn
    
    # Give actor some food
    actor.inventory.add_commodity(food_commodity, 3)
    # Set up the commodity for consumption
    actor.sim = type('obj', (object,), {
        'commodity_registry': type('obj', (object,), {
            'get_commodity': lambda self, id: food_commodity
        })()
    })
    actor._consume_food()
    
    # Should have consumed 1 food
    assert actor.food_consumed_this_turn
    assert actor.inventory.get_quantity(food_commodity) == 2


def test_actor_government_work() -> None:
    """Test that an actor earns money from government work."""
    actor = Actor("Test Actor", mock_sim, initial_money=0)
    
    # Test via command pattern
    from spacesim2.core.commands import GovernmentWorkCommand
    command = GovernmentWorkCommand()
    command.execute(actor)
    
    assert actor.money == 10  # Government wage


def test_market_maker_strategy(food_commodity, mock_sim) -> None:
    """Test that a market maker places appropriate buy/sell orders."""
    # Set up planet and market
    market = Market()
    planet = Planet("Test Planet", market)
    
    # Create commodity registry
    commodity_registry = CommodityRegistry()
    commodity_registry._commodities["food"] = food_commodity
    
    # Add fuel commodity which is now also required
    fuel_commodity = CommodityDefinition(
        id="nova_fuel",
        name="NovaFuel",
        transportable=True,
        description="High-density energy source for starship travel."
    )
    commodity_registry._commodities["nova_fuel"] = fuel_commodity
    market.commodity_registry = commodity_registry
    
    # Create mock simulation
    mock_actor_sim = type('obj', (object,), {
        'commodity_registry': commodity_registry,
    })
    
    # Create a market maker
    actor = Actor(
        "Market Maker",
        mock_actor_sim,
        planet=planet,
        actor_type=ActorType.MARKET_MAKER,
        initial_money=100
    )
    
    # Give some inventory
    actor.inventory.add_commodity(food_commodity, 10)
    
    # Run market maker strategy with no price history (bootstrap mode)
    commands = actor.brain.decide_market_actions()
    
    # Execute the commands
    for command in commands:
        command.execute(actor)
    
    # In bootstrap mode, the market maker should place orders
    # It will try for both food and fuel
    all_orders = market.get_actor_orders(actor)
    total_orders = len(all_orders["buy"]) + len(all_orders["sell"])
    
    # Should have placed some orders
    assert total_orders > 0