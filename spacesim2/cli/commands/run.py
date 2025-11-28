"""Headless run command implementation."""

import argparse

from spacesim2.ui.headless import HeadlessUI
from spacesim2.cli.common import create_and_setup_simulation, configure_actor_logging
from spacesim2.cli.output import print_section, print_success


def add_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:  # type: ignore
    """Add the 'run' subcommand parser.

    Args:
        subparsers: Subparsers to add this command to

    Returns:
        The created parser
    """
    parser = subparsers.add_parser(
        "run",
        help="Run headless simulation",
        description="Run simulation in headless mode with text output",
    )

    parser.add_argument(
        "--turns", type=int, default=10, help="Number of turns to simulate (default: 10)"
    )
    parser.add_argument(
        "--planets", type=int, default=2, help="Number of planets (default: 2)"
    )
    parser.add_argument(
        "--actors",
        type=int,
        default=50,
        help="Number of regular actors per planet (default: 50)",
    )
    parser.add_argument(
        "--makers",
        type=int,
        default=2,
        help="Number of market makers per planet (default: 2)",
    )
    parser.add_argument(
        "--ships", type=int, default=1, help="Number of ships (default: 1)"
    )
    parser.add_argument(
        "--log-actor-id", type=str, default=None, help="Log specific actor by name"
    )

    parser.set_defaults(func=execute)
    return parser


def execute(args: argparse.Namespace) -> int:
    """Execute the run command.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    # Create and setup simulation
    simulation = create_and_setup_simulation(
        planets=args.planets,
        actors=args.actors,
        makers=args.makers,
        ships=args.ships,
    )

    # Configure logging
    num_logged = configure_actor_logging(simulation, log_actor_id=args.log_actor_id)

    print_section("Simulation Setup")
    print(f"Planets: {args.planets}")
    print(f"Actors per planet: {args.actors}")
    print(f"Market makers per planet: {args.makers}")
    print(f"Ships: {args.ships}")
    print(f"Logging {num_logged} actor(s)")

    # Run in headless mode
    ui = HeadlessUI(simulation)
    ui.run(args.turns)

    print_success("Simulation complete!")
    return 0
