#!/usr/bin/env python

import argparse
import random
from spacesim2.core.simulation import Simulation
from spacesim2.ui.headless import HeadlessUI
from spacesim2.core.actor import ActorType


def modify_simulation_params(simulation):
    """Modify simulation parameters for better market dynamics."""
    # Update regular actors to be more willing to sell excess food
    for actor in simulation.actors:
        if actor.actor_type == ActorType.REGULAR:
            # Randomize production efficiency to create more varied supply
            actor.production_efficiency = random.uniform(0.8, 1.5)
            
            # Give some initial money variation
            actor.money = random.randint(40, 70)


def main() -> None:
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Run a headless simulation")
    parser.add_argument("--turns", type=int, default=10, help="Number of turns to simulate")
    parser.add_argument("--makers", type=int, default=1, help="Number of market makers")
    parser.add_argument("--actors", type=int, default=4, help="Number of regular actors")
    args = parser.parse_args()

    # Create and initialize simulation
    simulation = Simulation()
    simulation.setup_simple(num_regular_actors=args.actors, num_market_makers=args.makers)
    
    # Modify simulation parameters for more dynamic markets
    modify_simulation_params(simulation)

    # Run in headless mode
    ui = HeadlessUI(simulation)
    ui.run(args.turns)


if __name__ == "__main__":
    main()
