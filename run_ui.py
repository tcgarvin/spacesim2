#!/usr/bin/env python

import sys

from spacesim2.core.simulation import Simulation
from spacesim2.ui.pygame_ui import PYGAME_AVAILABLE, PygameUI


def main() -> None:
    if not PYGAME_AVAILABLE:
        print("Error: pygame not available. Please install pygame.")
        sys.exit(1)

    # Create and initialize simulation
    simulation = Simulation()
    simulation.setup_simple()

    # Run with pygame UI
    ui = PygameUI(simulation)
    ui.run(auto_turns=3)  # Auto-run 3 turns then wait for user input


if __name__ == "__main__":
    main()
