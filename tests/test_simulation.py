import pytest

from spacesim2.core.actor import Actor, ActorType
from spacesim2.core.commodity import CommodityDefinition, CommodityRegistry
from spacesim2.core.market import Market
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


def test_actor_government_work() -> None:
    """Test that an actor earns money from government work."""
    # Create mock sim
    mock_sim = type('MockSimulation', (object,), {
        'commodity_registry': CommodityRegistry()
    })()
    actor = Actor("Test Actor", mock_sim, initial_money=0)
    initial_money = actor.money
    
    # Test via command pattern
    from spacesim2.core.commands import GovernmentWorkCommand
    command = GovernmentWorkCommand()
    command.execute(actor)
    assert actor.money > initial_money


def test_planet_add_actor() -> None:
    """Test that an actor can be added to a planet."""
    market = Market()
    planet = Planet("Test Planet", market)
    # Create mock sim
    mock_sim = type('MockSimulation', (object,), {
        'commodity_registry': CommodityRegistry()
    })()
    actor = Actor("Test Actor", mock_sim)

    planet.add_actor(actor)

    assert actor in planet.actors
    assert actor.planet == planet


def test_simulation_setup() -> None:
    """Test that a simple simulation can be set up."""
    sim = Simulation()
    sim.setup_simple()

    assert len(sim.planets) == 2  # Two fictional planets
    
    # Total actors should be 10 (4 regular + 1 market maker per planet)
    assert len(sim.actors) == 10
    
    # Count actor types
    regular_count = 0
    market_maker_count = 0
    for actor in sim.actors:
        if actor.actor_type == ActorType.REGULAR:
            regular_count += 1
        elif actor.actor_type == ActorType.MARKET_MAKER:
            market_maker_count += 1
    
    assert regular_count == 8  # 4 regular actors per planet
    assert market_maker_count == 2  # 1 market maker per planet

    # All actors should be assigned to a planet
    planet1_actors = 0
    planet2_actors = 0
    for actor in sim.actors:
        if actor.planet.name == sim.planets[0].name:
            planet1_actors += 1
        elif actor.planet.name == sim.planets[1].name:
            planet2_actors += 1
    
    assert planet1_actors == 5  # 4 regular + 1 market maker
    assert planet2_actors == 5  # 4 regular + 1 market maker

    # Each planet should have a market
    assert sim.planets[0].market is not None
    assert sim.planets[1].market is not None


class SimulationTestHelper:
    """Helper class for simulation test setup."""
    
    @staticmethod
    def setup_test_simulation():
        """Set up a test simulation with predictable behavior."""
        sim = Simulation()
        
        # Create planet and market
        market = Market()
        planet = Planet("TestPlanet", market)
        sim.planets.append(planet)
        
        market = Market()
        planet.market = market
        
        # Initialize commodity registry
        sim.commodity_registry = CommodityRegistry()
        food_commodity = CommodityDefinition(
            id="food",
            name="Food",
            transportable=True,
            description="Basic nourishment required by actors."
        )
        fuel_commodity = CommodityDefinition(
            id="nova_fuel",
            name="Nova Fuel",
            transportable=True,
            description="High-energy fuel for starships."
        )
        sim.commodity_registry._commodities["food"] = food_commodity
        sim.commodity_registry._commodities["nova_fuel"] = fuel_commodity
        market.commodity_registry = sim.commodity_registry
        
        # Create a test actor that does government work
        actor = Actor(
            name="TestWorker",
            sim=sim,
            planet=planet,
            initial_money=0,
            actor_type=ActorType.REGULAR
        )
        
        # Simulation reference already set in constructor
        
        # Override the should_produce_food method to always return False
        # so the actor will always do government work in tests
        actor.brain.should_produce_food = lambda: False
        
        # Override decide_economic_action to always return government work
        from spacesim2.core.commands import GovernmentWorkCommand
        actor.brain.decide_economic_action = lambda: GovernmentWorkCommand()
        
        sim.actors.append(actor)
        planet.add_actor(actor)
        
        return sim


def test_simulation_run_turn() -> None:
    """Test that running a turn advances the simulation state."""
    # Use helper to create a simulation with predictable behavior
    sim = SimulationTestHelper.setup_test_simulation()
    
    # Verify initial state
    assert len(sim.actors) == 1
    actor = sim.actors[0]
    assert actor.money == 0
    
    # Record initial state
    initial_turn = sim.current_turn
    
    # Manually set up the actor to earn money
    from spacesim2.core.commands import GovernmentWorkCommand
    command = GovernmentWorkCommand()
    command.execute(actor)
    assert actor.money == 10
    
    # Reset money to test the turn
    actor.money = 0
    
    # Run a turn
    sim.run_turn()
    
    # Verify turn incremented
    assert sim.current_turn == initial_turn + 1
    
    # The actor should have earned money during the turn (from overridden decide_economic_action)
    assert actor.money == 10  # Should have earned 10 from the turn