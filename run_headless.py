#!/usr/bin/env python

from spacesim2.core.simulation import Simulation
from spacesim2.ui.headless import HeadlessUI


def main() -> None:
    # Create and initialize simulation
    simulation = Simulation()
    simulation.setup_simple()

    # Run in headless mode for 10 turns
    ui = HeadlessUI(simulation)
    ui.run(10)


if __name__ == "__main__":
    main()
