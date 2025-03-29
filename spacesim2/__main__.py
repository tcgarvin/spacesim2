import argparse
import sys

from spacesim2.core.simulation import Simulation
from spacesim2.ui.headless import HeadlessUI
from spacesim2.ui.pygame_ui import PYGAME_AVAILABLE, PygameUI


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SpaceSim2 - A turn-based economic simulation"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run in headless mode (no UI)"
    )
    parser.add_argument(
        "--turns",
        type=int,
        default=10,
        help="Number of turns to simulate in headless mode"
    )
    parser.add_argument(
        "--auto-turns",
        type=int,
        default=0,
        help="Number of turns to automatically run in UI mode before pausing"
    )
    args = parser.parse_args()

    # Create and initialize simulation
    simulation = Simulation()
    simulation.setup_simple()

    # Run in appropriate mode
    if args.headless:
        ui = HeadlessUI(simulation)
        ui.run(args.turns)
    else:
        if not PYGAME_AVAILABLE:
            print("Error: pygame not available. Install pygame or use --headless mode.")
            sys.exit(1)

        pygame_ui = PygameUI(simulation)
        pygame_ui.run(args.auto_turns)


if __name__ == "__main__":
    main()
