import pytest

from spacesim2.core.actor import Actor, ActorType
from spacesim2.core.brains.colonist import ColonistBrain
from spacesim2.core.brains import MarketMakerBrain
from spacesim2.core.commodity import CommodityDefinition, CommodityRegistry
from spacesim2.core.market import Market
from spacesim2.core.planet import Planet

from .helpers import get_actor


@pytest.fixture
def food_commodity():
    """Create a food commodity for testing."""
    return CommodityDefinition(
        id="food",
        name="Food",
        transportable=True,
        description="Basic nourishment required by actors."
    )

def test_actor_initialization(mock_sim, mock_brain) -> None:
    """Test that an actor can be initialized correctly."""
    actor = Actor("Test Actor", mock_sim, ActorType.REGULAR, [], mock_brain, initial_money=50)
    assert actor.name == "Test Actor"
    assert actor.money == 50
    assert actor.inventory is not None
    assert actor.actor_type == ActorType.REGULAR
    

def test_actor_consume_food(food_commodity, mock_sim) -> None:
    """Test that an actor can consume food."""
    actor = get_actor()
    
    # Set up the simulation reference for commodity registry
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
    actor = get_actor(initial_money=0)
    
    # Test via command pattern
    from spacesim2.core.commands import GovernmentWorkCommand
    command = GovernmentWorkCommand()
    command.execute(actor)
    
    assert actor.money == 10  # Government wage