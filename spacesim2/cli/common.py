"""Common utilities for CLI commands."""

import argparse
import random
from typing import List, Optional

from spacesim2.core.simulation import Simulation
from spacesim2.core.actor import ActorType


def create_and_setup_simulation(
    planets: int, actors: int, makers: int, ships: int = 1
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


def configure_actor_logging(
    sim: Simulation,
    log_all: bool = False,
    log_sample: Optional[int] = None,
    log_actor_types: Optional[List[str]] = None,
    log_actor_id: Optional[str] = None,
) -> int:
    """Configure which actors should be logged.

    Args:
        sim: Simulation instance
        log_all: Log all actors
        log_sample: Log N randomly selected actors
        log_actor_types: Log specific actor types
        log_actor_id: Log specific actor by name

    Returns:
        Number of actors configured for logging
    """
    if log_actor_id:
        # Find and log specific actor
        for actor in sim.actors:
            if actor.name == log_actor_id:
                sim.data_logger.add_actor_to_log(actor)
                return 1
        raise ValueError(f"Actor '{log_actor_id}' not found")

    if log_all:
        for actor in sim.actors:
            sim.data_logger.add_actor_to_log(actor)
        # Also log all ships
        for ship in sim.ships:
            sim.data_logger.add_actor_to_log(ship)
        return len(sim.actors) + len(sim.ships)

    if log_sample:
        eligible_actors = [
            a
            for a in sim.actors
            if a.actor_type != ActorType.MARKET_MAKER
            or (log_actor_types and "market_maker" in log_actor_types)
        ]
        sample_size = min(log_sample, len(eligible_actors))
        sample = random.sample(eligible_actors, sample_size)
        for actor in sample:
            sim.data_logger.add_actor_to_log(actor)
        return sample_size

    if log_actor_types:
        count = 0
        for actor in sim.actors:
            brain_name = actor.brain.__class__.__name__
            should_log = False

            if "colonist" in log_actor_types and "Colonist" in brain_name:
                should_log = True
            elif "industrialist" in log_actor_types and "Industrialist" in brain_name:
                should_log = True
            elif (
                "market_maker" in log_actor_types
                and actor.actor_type == ActorType.MARKET_MAKER
            ):
                should_log = True

            if should_log:
                sim.data_logger.add_actor_to_log(actor)
                count += 1

        # Also log ships if requested
        if "ship" in log_actor_types or "trader" in log_actor_types:
            for ship in sim.ships:
                sim.data_logger.add_actor_to_log(ship)
                count += 1

        return count

    # Default: log one random non-market-maker actor
    actor = random.choice(sim.actors)
    while actor.actor_type == ActorType.MARKET_MAKER:
        actor = random.choice(sim.actors)
    sim.data_logger.add_actor_to_log(actor)
    return 1


def add_simulation_args(parser: argparse.ArgumentParser) -> None:
    """Add common simulation configuration arguments.

    Args:
        parser: ArgumentParser to add arguments to
    """
    parser.add_argument(
        "--turns", type=int, default=1000, help="Number of turns to simulate"
    )
    parser.add_argument("--planets", type=int, default=5, help="Number of planets")
    parser.add_argument(
        "--actors", type=int, default=100, help="Number of regular actors per planet"
    )
    parser.add_argument(
        "--makers", type=int, default=2, help="Number of market makers per planet"
    )
    parser.add_argument(
        "--ships", type=int, default=1, help="Number of ships per planet"
    )
