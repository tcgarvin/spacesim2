#!/usr/bin/env python
"""Validate simulation run data before loading in notebook."""

import sys
from pathlib import Path
import polars as pl


def validate_run(run_path: Path) -> None:
    """
    Validate that all required parquet files exist and have expected columns.

    Args:
        run_path: Path to simulation run directory

    Raises:
        SystemExit: If validation fails
    """
    required_files = {
        'actor_turns.parquet': ['simulation_id', 'turn', 'actor_id', 'actor_name', 'money'],
        'market_snapshots.parquet': ['simulation_id', 'turn', 'planet_name', 'commodity_id', 'avg_price'],
        'market_transactions.parquet': ['simulation_id', 'turn', 'commodity_id', 'quantity', 'price'],
        'actor_drives.parquet': ['simulation_id', 'turn', 'actor_id', 'drive_name', 'health'],
    }

    for filename, expected_cols in required_files.items():
        filepath = run_path / filename
        if not filepath.exists():
            print(f"❌ Missing: {filename}")
            sys.exit(1)

        df = pl.read_parquet(filepath)
        missing = set(expected_cols) - set(df.columns)
        if missing:
            print(f"❌ {filename} missing columns: {missing}")
            print(f"   Available columns: {df.columns}")
            sys.exit(1)

        print(f"✓ {filename} ({len(df)} rows, {len(df.columns)} columns)")

    print("\n✓ All required files present with correct schema")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python validate_run_data.py <run_path>")
        sys.exit(1)

    validate_run(Path(sys.argv[1]))
