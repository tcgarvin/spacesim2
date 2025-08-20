#!/usr/bin/env python

import argparse
import random
from spacesim2.core.simulation import Simulation
from spacesim2.ui.headless import HeadlessUI
from spacesim2.core.actor import ActorType


def main() -> None:
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Run a headless simulation")
    parser.add_argument("--turns", type=int, default=10, help="Number of turns to simulate")
    parser.add_argument("--planets", type=int, default=2, help="Number of planets")
    parser.add_argument("--makers", type=int, default=2, help="Number of market makers per planet")
    parser.add_argument("--actors", type=int, default=50, help="Number of regular actors per planet")
    args = parser.parse_args()

    # Create and initialize simulation
    simulation = Simulation()
    simulation.setup_simple(
        num_planets=args.planets,
        num_regular_actors=args.actors, 
        num_market_makers=args.makers
    )

    # pick a random actor to log (but not a market maker)
    actor = random.choice(simulation.actors)
    while actor.actor_type == ActorType.MARKET_MAKER:
        actor = random.choice(simulation.actors)

    simulation.data_logger.add_actor_to_log(actor)

    
    # Run in headless mode
    ui = HeadlessUI(simulation)
    ui.run(args.turns)


if __name__ == "__main__":
    main()
