"""Common utilities for CLI commands."""

import random

from spacesim2.core.actor import ActorType
from spacesim2.core.simulation import Simulation


def create_and_setup_simulation(
    planets: int,
    actors: int,
    makers: int,
    ships: int = 1,
) -> Simulation:
    """Create and configure a simulation with standard setup.

    Args:
        planets: Number of planets to create
        actors: Number of regular actors per planet
        makers: Number of market makers per planet
        ships: Number of ships to create

    Returns:
        Configured Simulation instance
    """
    sim = Simulation()
    sim.setup_simple(
        num_planets=planets,
        num_regular_actors=actors,
        num_market_makers=makers,
        num_ships=ships,
    )
    return sim


def configure_actor_logging(sim: Simulation, spec: str = "1") -> int:
    """Select actors for the detailed logging pipeline (post-hoc analysis).

    Args:
        sim: Simulation instance
        spec: "all" (every actor and ship), an integer N (random sample of
            N non-market-maker actors; default "1"), or an actor name.

    Returns:
        Number of actors configured for logging

    Raises:
        ValueError: If spec names an actor that does not exist.
    """
    if spec == "all":
        for actor in sim.actors:
            sim.data_logger.add_actor_to_log(actor)
        for ship in sim.ships:
            sim.data_logger.add_actor_to_log(ship)
        return len(sim.actors) + len(sim.ships)

    if spec.isdigit():
        eligible = [a for a in sim.actors if a.actor_type != ActorType.MARKET_MAKER]
        sample = random.sample(eligible, min(int(spec), len(eligible)))
        for actor in sample:
            sim.data_logger.add_actor_to_log(actor)
        return len(sample)

    for actor in sim.actors:
        if actor.name == spec:
            sim.data_logger.add_actor_to_log(actor)
            return 1
    raise ValueError(f"Actor '{spec}' not found")
