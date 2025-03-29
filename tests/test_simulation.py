import pytest

from spacesim2.core.actor import Actor, ActorType
from spacesim2.core.commodity import CommodityType
from spacesim2.core.market import Market
from spacesim2.core.planet import Planet
from spacesim2.core.simulation import Simulation


def test_actor_government_work() -> None:
    """Test that an actor earns money from government work."""
    actor = Actor("Test Actor", initial_money=0.0)
    initial_money = actor.money
    
    # Direct call to government work rather than take_turn
    actor._do_government_work()
    assert actor.money > initial_money


def test_planet_add_actor() -> None:
    """Test that an actor can be added to a planet."""
    planet = Planet("Test Planet")
    actor = Actor("Test Actor")

    planet.add_actor(actor)

    assert actor in planet.actors
    assert actor.planet == planet


def test_simulation_setup() -> None:
    """Test that a simple simulation can be set up."""
    sim = Simulation()
    sim.setup_simple()

    assert len(sim.planets) == 1
    assert len(sim.actors) == 5  # Should have 4 regular + 1 market maker
    
    # Count actor types
    regular_count = 0
    market_maker_count = 0
    for actor in sim.actors:
        if actor.actor_type == ActorType.REGULAR:
            regular_count += 1
        elif actor.actor_type == ActorType.MARKET_MAKER:
            market_maker_count += 1
    
    assert regular_count == 4
    assert market_maker_count == 1

    # All actors should be assigned to the planet
    for actor in sim.actors:
        assert actor.planet == sim.planets[0]

    # The planet should have all actors in its list
    assert len(sim.planets[0].actors) == 5

    # The planet should have a market
    assert sim.planets[0].market is not None


class SimulationTestHelper:
    """Helper class for simulation test setup."""
    
    @staticmethod
    def setup_test_simulation():
        """Set up a test simulation with predictable behavior."""
        sim = Simulation()
        
        # Create planet and market
        planet = Planet("TestPlanet")
        sim.planets.append(planet)
        
        market = Market()
        planet.market = market
        
        # Create a test actor that does government work
        actor = Actor(
            name="TestWorker",
            planet=planet,
            initial_money=0.0,
            actor_type=ActorType.REGULAR
        )
        
        # Override the should_produce_food method to always return False
        # so the actor will always do government work in tests
        original_should_produce = actor._should_produce_food
        actor._should_produce_food = lambda: False
        
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
    assert actor.money == 0.0
    
    # Record initial state
    initial_turn = sim.current_turn
    initial_money = actor.money
    
    # Run a turn
    sim.run_turn()
    
    # Verify turn incremented
    assert sim.current_turn == initial_turn + 1
    
    # Verify actor earned money (from government work)
    assert actor.money > initial_money