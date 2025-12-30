"""Run simulation command implementation."""

import argparse
import io
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from spacesim2.cli.common import create_and_setup_simulation, configure_actor_logging
from spacesim2.cli.output import print_success, print_warning
from spacesim2.ui.headless import HeadlessUI

try:
    from spacesim2.analysis.export.exporter import SimulationExporter

    ANALYSIS_AVAILABLE = True
except ImportError:
    ANALYSIS_AVAILABLE = False


def add_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:  # type: ignore
    """Add the 'run' subcommand parser.

    Args:
        subparsers: Subparsers to add this command to

    Returns:
        The created parser
    """
    parser = subparsers.add_parser(
        "run",
        help="Run headless simulation with data export",
        description="Run simulation in headless mode with Parquet export for analysis",
    )

    # Simulation parameters
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
    parser.add_argument(
        "--planet-attributes",
        action="store_true",
        help="Enable per-planet resource attributes affecting gathering yields",
    )

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
    parser.add_argument(
        "--log-actor-id", type=str, default=None, help="Log specific actor by name"
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
        "--no-export",
        action="store_true",
        help="Skip Parquet export (for quick test runs)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed per-turn output for logged actors",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress all output including progress bar",
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
    """Execute the run command.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    # Determine if we should export
    should_export = not args.no_export
    if should_export and not ANALYSIS_AVAILABLE:
        print_warning(
            "Analysis dependencies not available. Skipping export. "
            "Install with: uv sync --extra analysis"
        )
        should_export = False

    # Create simulation
    print("Initializing simulation...")
    sim = create_and_setup_simulation(
        planets=args.planets,
        actors=args.actors,
        makers=args.makers,
        ships=args.ships,
        enable_planet_attributes=args.planet_attributes,
    )
    if args.planet_attributes:
        print("  Planet attributes: enabled")

    # Configure logging
    print("Configuring actor logging...")
    num_logged = configure_actor_logging(
        sim,
        log_all=args.log_all_actors,
        log_sample=args.log_sample,
        log_actor_types=args.log_actor_types,
        log_actor_id=args.log_actor_id,
    )
    print(f"  Logging {num_logged} actor(s)")

    # Setup exporter if needed
    exporter: Any = None
    output_path: Path | None = None
    run_id: str | None = None

    if should_export:
        run_id = args.run_id or f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        output_path = Path(args.output) / run_id

        print(f"\nSetting up export to: {output_path}")
        exporter = SimulationExporter(output_path, run_id)
        exporter.setup(sim)
        sim.exporter = exporter

    # Run simulation
    print(f"\nRunning {args.turns} turns...")
    print("=" * 60)

    if args.verbose:
        # Use HeadlessUI for detailed per-turn output
        ui = HeadlessUI(sim)
        ui.run(args.turns)
    else:
        # Suppress simulation stdout (turn-by-turn prints)
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()

        try:
            # Default: progress bar (unless --quiet)
            iterator = range(args.turns)
            if not args.quiet:
                from tqdm import tqdm

                # tqdm writes to stderr by default, so stdout stays suppressed
                iterator = tqdm(iterator, desc="Simulating turns", file=sys.stderr)

            for _ in iterator:
                sim.run_turn()
        finally:
            sys.stdout = old_stdout

    # Finalize export
    if should_export and exporter is not None:
        print("\n" + "=" * 60)
        print("Finalizing export...")
        exporter.finalize()

        print_success("Simulation complete!")
        print(f"  Data exported to: {output_path}")
        print(f"  Run ID: {run_id}")

        if args.notebook:
            _open_notebook(output_path, args.notebook_path)
        else:
            print(f"\nTo analyze this run:")
            print(
                f"  SPACESIM_RUN_PATH='{output_path}' marimo edit --no-token {args.notebook_path}"
            )
    else:
        print("\n" + "=" * 60)
        print_success("Simulation complete!")

    return 0


def _open_notebook(output_path: Path, notebook_path_str: str) -> None:
    """Open a marimo notebook with the run path set.

    Args:
        output_path: Path to the simulation output directory
        notebook_path_str: Path to the notebook file
    """
    print("\nOpening marimo notebook...")

    # Set environment variable for notebook to read
    env = os.environ.copy()
    env["SPACESIM_RUN_PATH"] = str(output_path)

    # Check if notebook exists
    notebook_path = Path(notebook_path_str)
    if not notebook_path.exists():
        print_warning(f"Notebook not found: {notebook_path}")
        print(f"   Please create the notebook first or use an existing one.")
        print(f"\nTo analyze manually:")
        print(
            f"  SPACESIM_RUN_PATH='{output_path}' marimo edit --no-token {notebook_path}"
        )
    else:
        try:
            # Launch marimo edit with the notebook
            subprocess.run(
                ["marimo", "edit", "--no-token", str(notebook_path)],
                env=env,
                check=False,  # Don't raise error if marimo exits normally
            )
        except FileNotFoundError:
            print_warning(
                "marimo not found. Install with: uv sync --extra analysis"
            )
            print(f"\nTo analyze manually:")
            print(
                f"  SPACESIM_RUN_PATH='{output_path}' marimo edit --no-token {notebook_path}"
            )
