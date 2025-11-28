"""UI command implementation."""

import argparse
import sys

from spacesim2.ui.pygame_ui import PYGAME_AVAILABLE, PygameUI
from spacesim2.cli.common import create_and_setup_simulation
from spacesim2.cli.output import print_error


def add_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:  # type: ignore
    """Add the 'ui' subcommand parser.

    Args:
        subparsers: Subparsers to add this command to

    Returns:
        The created parser
    """
    parser = subparsers.add_parser(
        "ui",
        help="Launch interactive Pygame UI",
        description="Run simulation with interactive graphical interface",
    )

    parser.add_argument(
        "--planets", type=int, default=5, help="Number of planets (default: 5)"
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
        "--auto-turns",
        type=int,
        default=3,
        help="Number of turns to auto-run before pausing (default: 3)",
    )

    parser.set_defaults(func=execute)
    return parser


def execute(args: argparse.Namespace) -> int:
    """Execute the UI command.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    if not PYGAME_AVAILABLE:
        print_error("pygame not available. Install with: uv pip install pygame")
        return 1

    # Create and setup simulation
    simulation = create_and_setup_simulation(
        planets=args.planets,
        actors=args.actors,
        makers=args.makers,
        ships=args.ships,
    )

    # Run with pygame UI
    ui = PygameUI(simulation)
    ui.run(auto_turns=args.auto_turns)

    return 0
