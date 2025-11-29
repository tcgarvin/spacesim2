"""Batch analysis command implementation."""

import argparse
import io
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from spacesim2.cli.common import create_and_setup_simulation, configure_actor_logging
from spacesim2.cli.output import print_error, print_success, print_warning

try:
    from spacesim2.analysis.export.exporter import SimulationExporter

    ANALYSIS_AVAILABLE = True
except ImportError:
    ANALYSIS_AVAILABLE = False


def add_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:  # type: ignore
    """Add the 'analyze' subcommand parser.

    Args:
        subparsers: Subparsers to add this command to

    Returns:
        The created parser
    """
    parser = subparsers.add_parser(
        "analyze",
        help="Run simulation with Parquet export for analysis",
        description="Run simulation and export data to Parquet files for batch analysis",
    )

    # Simulation parameters
    parser.add_argument(
        "--turns", type=int, default=100, help="Number of turns to simulate"
    )
    parser.add_argument("--planets", type=int, default=2, help="Number of planets")
    parser.add_argument(
        "--actors", type=int, default=100, help="Number of regular actors per planet"
    )
    parser.add_argument(
        "--makers", type=int, default=2, help="Number of market makers per planet"
    )
    parser.add_argument("--ships", type=int, default=1, help="Number of ships")

    # Logging configuration
    parser.add_argument(
        "--log-all-actors",
        action="store_true",
        help="Log all actors (can be memory intensive)",
    )
    parser.add_argument(
        "--log-sample", type=int, default=None, help="Log N randomly selected actors"
    )
    parser.add_argument(
        "--log-actor-types",
        nargs="+",
        choices=["colonist", "industrialist", "market_maker", "ship", "trader"],
        help="Log specific actor types only",
    )

    # Output configuration
    parser.add_argument(
        "--output",
        type=str,
        default="data/runs",
        help="Output directory for Parquet files",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Custom run ID (default: auto-generated from timestamp)",
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Suppress simulation output"
    )
    parser.add_argument(
        "--progress", action="store_true", help="Show progress bar"
    )

    # Notebook options
    parser.add_argument(
        "--notebook", action="store_true", help="Open marimo notebook after simulation"
    )
    parser.add_argument(
        "--notebook-path",
        type=str,
        default="notebooks/analysis_template.py",
        help="Path to marimo notebook to open",
    )

    parser.set_defaults(func=execute)
    return parser


def execute(args: argparse.Namespace) -> int:
    """Execute the analyze command.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    if not ANALYSIS_AVAILABLE:
        print_error(
            "Analysis dependencies not available. Install with: uv pip install -e '.[analysis]'"
        )
        return 1

    # Create simulation
    print("Initializing simulation...")
    sim = create_and_setup_simulation(
        planets=args.planets,
        actors=args.actors,
        makers=args.makers,
        ships=args.ships,
    )

    # Configure logging
    print("Configuring actor logging...")
    num_logged = configure_actor_logging(
        sim,
        log_all=args.log_all_actors,
        log_sample=args.log_sample,
        log_actor_types=args.log_actor_types,
    )
    print(f"  Logging {num_logged} actor(s)")

    # Setup exporter
    run_id = args.run_id or f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    output_path = Path(args.output) / run_id

    print(f"\nSetting up export to: {output_path}")
    exporter = SimulationExporter(output_path, run_id)
    exporter.setup(sim)
    sim.exporter = exporter

    # Run simulation
    print(f"\nRunning {args.turns} turns...")
    print("=" * 60)

    old_stdout = None
    if args.quiet:
        # Suppress simulation output by redirecting stdout
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()

    try:
        iterator = range(args.turns)
        if args.progress:
            try:
                from tqdm import tqdm

                iterator = tqdm(iterator, desc="Simulating turns")
            except ImportError:
                print_warning(
                    "tqdm not available. Install with: uv pip install -e '.[analysis]'"
                )

        for _ in iterator:
            sim.run_turn()
    finally:
        if old_stdout:
            sys.stdout = old_stdout

    # Finalize export
    print("\n" + "=" * 60)
    print("Finalizing export...")
    exporter.finalize()

    print_success("Simulation complete!")
    print(f"  Data exported to: {output_path}")
    print(f"  Run ID: {run_id}")

    if args.notebook:
        print("\n🚀 Opening marimo notebook...")

        # Set environment variable for notebook to read
        env = os.environ.copy()
        env["SPACESIM_RUN_PATH"] = str(output_path)

        # Check if notebook exists
        notebook_path = Path(args.notebook_path)
        if not notebook_path.exists():
            print_warning(f"Notebook not found: {notebook_path}")
            print(f"   Please create the notebook first or use an existing one.")
            print(f"\nTo analyze manually:")
            print(
                f"  SPACESIM_RUN_PATH='{output_path}' marimo edit {notebook_path}"
            )
        else:
            try:
                # Launch marimo edit with the notebook
                subprocess.run(
                    ["marimo", "edit", str(notebook_path)],
                    env=env,
                    check=False,  # Don't raise error if marimo exits normally
                )
            except FileNotFoundError:
                print_warning(
                    "marimo not found. Install with: uv pip install -e '.[analysis]'"
                )
                print(f"\nTo analyze manually:")
                print(
                    f"  SPACESIM_RUN_PATH='{output_path}' marimo edit {notebook_path}"
                )
    else:
        print(f"\nTo analyze this run:")
        print(
            f"  SPACESIM_RUN_PATH='{output_path}' marimo edit {args.notebook_path}"
        )

    return 0
