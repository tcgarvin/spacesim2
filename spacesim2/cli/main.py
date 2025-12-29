"""Main CLI entry point for SpaceSim2."""

import argparse
import sys
from typing import Optional

from spacesim2.cli.commands import run, ui
from spacesim2.cli.commands.dev import graph, validate_market


def create_parser() -> argparse.ArgumentParser:
    """Create the main argument parser with all subcommands.

    Returns:
        Configured ArgumentParser
    """
    parser = argparse.ArgumentParser(
        prog="spacesim2",
        description="SpaceSim2 - Interplanetary Economic Simulation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--version", action="version", version="%(prog)s 0.1.0"
    )

    subparsers = parser.add_subparsers(
        dest="command", help="Available commands", required=True
    )

    # Main commands
    ui.add_parser(subparsers)
    run.add_parser(subparsers)

    # Dev tools
    dev_parser = subparsers.add_parser("dev", help="Development tools")
    dev_subparsers = dev_parser.add_subparsers(
        dest="dev_command", help="Development subcommands", required=True
    )
    validate_market.add_parser(dev_subparsers)
    graph.add_parser(dev_subparsers)

    return parser


def main(argv: Optional[list] = None) -> int:
    """Main CLI entry point.

    Args:
        argv: Command line arguments (defaults to sys.argv)

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    parser = create_parser()
    args = parser.parse_args(argv)

    # Dispatch to appropriate command handler
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
