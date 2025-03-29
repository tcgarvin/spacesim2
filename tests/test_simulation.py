from spacesim2.core.actor import Actor
from spacesim2.core.planet import Planet
from spacesim2.core.simulation import Simulation


def test_actor_government_work() -> None:
    """Test that an actor earns money from government work."""
    actor = Actor("Test Actor")
    initial_money = actor.money
    actor.take_turn()
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
    assert len(sim.actors) == 5  # Now should have 5 actors

    # All actors should be assigned to the planet
    for actor in sim.actors:
        assert actor.planet == sim.planets[0]

    # The planet should have all actors in its list
    assert len(sim.planets[0].actors) == 5

    # The planet should have a market
    assert sim.planets[0].market is not None


def test_simulation_run_turn() -> None:
    """Test that running a turn advances the simulation state."""
    sim = Simulation()
    sim.setup_simple()

    initial_turn = sim.current_turn
    initial_money = {actor.name: actor.money for actor in sim.actors}

    sim.run_turn()

    assert sim.current_turn == initial_turn + 1

    # All actors should have earned money
    for actor in sim.actors:
        assert actor.money > initial_money[actor.name]
