#!/usr/bin/env python
"""
Run simulation with Parquet export for batch analysis.

This script runs a simulation and exports data to Parquet files for
later analysis in Marimo notebooks or other tools.
"""

import argparse
import os
import random
import subprocess
from pathlib import Path
from datetime import datetime
from tqdm import tqdm

from spacesim2.core.simulation import Simulation
from spacesim2.core.actor import ActorType
from spacesim2.analysis.export.exporter import SimulationExporter


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run simulation with Parquet export for analysis"
    )

    # Simulation parameters
    parser.add_argument("--turns", type=int, default=100,
                        help="Number of turns to simulate")
    parser.add_argument("--planets", type=int, default=2,
                        help="Number of planets")
    parser.add_argument("--actors", type=int, default=100,
                        help="Number of regular actors per planet")
    parser.add_argument("--makers", type=int, default=2,
                        help="Number of market makers per planet")
    parser.add_argument("--ships", type=int, default=1,
                        help="Number of ships")

    # Logging configuration
    parser.add_argument("--log-all-actors", action="store_true",
                        help="Log all actors (can be memory intensive)")
    parser.add_argument("--log-sample", type=int, default=None,
                        help="Log N randomly selected actors")
    parser.add_argument("--log-actor-types", nargs="+",
                        choices=["colonist", "industrialist", "market_maker"],
                        help="Log specific actor types only")

    # Output configuration
    parser.add_argument("--output", type=str, default="data/runs",
                        help="Output directory for Parquet files")
    parser.add_argument("--run-id", type=str, default=None,
                        help="Custom run ID (default: auto-generated from timestamp)")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress simulation output")
    parser.add_argument("--progress", action="store_true",
                        help="Show progress bar")

    # Notebook options
    parser.add_argument("--notebook", action="store_true",
                        help="Open marimo notebook after simulation")
    parser.add_argument("--notebook-path", type=str,
                        default="notebooks/analysis_template.py",
                        help="Path to marimo notebook to open")

    args = parser.parse_args()

    # Create simulation
    print("Initializing simulation...")
    sim = Simulation()
    sim.setup_simple(
        num_planets=args.planets,
        num_regular_actors=args.actors,
        num_market_makers=args.makers,
        num_ships=args.ships
    )

    # Configure logging
    print("Configuring actor logging...")
    if args.log_all_actors:
        print(f"  Logging all {len(sim.actors)} actors")
        for actor in sim.actors:
            sim.data_logger.add_actor_to_log(actor)
    elif args.log_sample:
        # Sample N actors (excluding market makers unless explicitly requested)
        eligible_actors = [
            a for a in sim.actors
            if a.actor_type != ActorType.MARKET_MAKER or
            (args.log_actor_types and "market_maker" in args.log_actor_types)
        ]
        sample_size = min(args.log_sample, len(eligible_actors))
        sample = random.sample(eligible_actors, sample_size)
        print(f"  Logging {sample_size} sampled actors")
        for actor in sample:
            sim.data_logger.add_actor_to_log(actor)
    elif args.log_actor_types:
        # Log specific actor types
        for actor in sim.actors:
            brain_name = actor.brain.__class__.__name__
            if ("colonist" in args.log_actor_types and
                "Colonist" in brain_name):
                sim.data_logger.add_actor_to_log(actor)
            elif ("industrialist" in args.log_actor_types and
                  "Industrialist" in brain_name):
                sim.data_logger.add_actor_to_log(actor)
            elif ("market_maker" in args.log_actor_types and
                  actor.actor_type == ActorType.MARKET_MAKER):
                sim.data_logger.add_actor_to_log(actor)
        logged_count = len(sim.data_logger.get_all_logged_actors())
        print(f"  Logging {logged_count} actors of types: {', '.join(args.log_actor_types)}")
    else:
        # Default: log one random non-market-maker actor
        actor = random.choice(sim.actors)
        while actor.actor_type == ActorType.MARKET_MAKER:
            actor = random.choice(sim.actors)
        sim.data_logger.add_actor_to_log(actor)
        print(f"  Logging 1 random actor: {actor.name}")

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

    if args.quiet:
        # Suppress simulation output by redirecting stdout
        import sys
        import io
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()

    try:
        iterator = range(args.turns)
        if args.progress:
            iterator = tqdm(iterator, desc="Simulating turns")

        for _ in iterator:
            sim.run_turn()
    finally:
        if args.quiet:
            sys.stdout = old_stdout

    # Finalize export
    print("\n" + "=" * 60)
    print("Finalizing export...")
    exporter.finalize()

    print(f"\n✓ Simulation complete!")
    print(f"  Data exported to: {output_path}")
    print(f"  Run ID: {run_id}")

    if args.notebook:
        print(f"\n🚀 Opening marimo notebook...")

        # Set environment variable for notebook to read
        env = os.environ.copy()
        env["SPACESIM_RUN_PATH"] = str(output_path)

        # Check if notebook exists
        notebook_path = Path(args.notebook_path)
        if not notebook_path.exists():
            print(f"⚠️  Notebook not found: {notebook_path}")
            print(f"   Please create the notebook first or use an existing one.")
            print(f"\nTo analyze manually:")
            print(f"  SPACESIM_RUN_PATH='{output_path}' marimo edit {notebook_path}")
        else:
            try:
                # Launch marimo edit with the notebook
                subprocess.run(
                    ["marimo", "edit", str(notebook_path)],
                    env=env,
                    check=False  # Don't raise error if marimo exits normally
                )
            except FileNotFoundError:
                print("⚠️  marimo not found. Install with: uv pip install -e '.[analysis]'")
                print(f"\nTo analyze manually:")
                print(f"  SPACESIM_RUN_PATH='{output_path}' marimo edit {notebook_path}")
    else:
        print(f"\nTo analyze this run:")
        print(f"  SPACESIM_RUN_PATH='{output_path}' marimo edit {args.notebook_path}")
        print(f"  # Or with auto-load: uv run scripts/run_analysis_batch.py --notebook")


if __name__ == "__main__":
    main()
