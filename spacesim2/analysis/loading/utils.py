"""Utilities for discovering and working with simulation runs."""

from pathlib import Path
from datetime import datetime
from typing import Optional


class NoRunsFoundError(Exception):
    """Raised when no valid simulation runs are found."""

    pass


def get_runs_directory(base_path: Optional[Path | str] = None) -> Path:
    """Get the runs directory path.

    Args:
        base_path: Base path to look for runs directory. Defaults to 'data/runs'

    Returns:
        Path object for the runs directory
    """
    if base_path is None:
        return Path("data/runs")
    return Path(base_path)


def parse_run_timestamp(run_dir: Path) -> Optional[datetime]:
    """Parse timestamp from run directory name.

    Expected format: run_YYYYMMDD_HHMMSS

    Args:
        run_dir: Path to run directory

    Returns:
        datetime object if parsing succeeds, None otherwise
    """
    name = run_dir.name
    if not name.startswith("run_"):
        return None

    timestamp_str = name[4:]  # Remove 'run_' prefix
    try:
        return datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
    except ValueError:
        return None


def find_most_recent_run(base_path: Optional[Path | str] = None) -> Path:
    """Find the most recently created simulation run.

    Sorts runs by timestamp parsed from directory name (run_YYYYMMDD_HHMMSS).
    Only considers directories that match the expected naming pattern.

    Args:
        base_path: Base path to look for runs directory. Defaults to 'data/runs'

    Returns:
        Path to the most recent run directory

    Raises:
        NoRunsFoundError: If no valid runs are found
    """
    runs_dir = get_runs_directory(base_path)

    if not runs_dir.exists():
        raise NoRunsFoundError(
            f"Runs directory not found: {runs_dir}\n"
            f"Run 'spacesim2 analyze' to create simulation data."
        )

    # Find all directories with parseable timestamps
    runs_with_times = []
    for item in runs_dir.iterdir():
        if not item.is_dir():
            continue

        timestamp = parse_run_timestamp(item)
        if timestamp is not None:
            runs_with_times.append((item, timestamp))

    if not runs_with_times:
        raise NoRunsFoundError(
            f"No valid runs found in: {runs_dir}\n"
            f"Run 'spacesim2 analyze' to create simulation data.\n"
            f"Expected directory pattern: run_YYYYMMDD_HHMMSS"
        )

    # Sort by timestamp, most recent first
    runs_with_times.sort(key=lambda x: x[1], reverse=True)
    return runs_with_times[0][0]


def get_run_path_with_fallback(
    env_var: str = "SPACESIM_RUN_PATH", base_path: Optional[Path | str] = None
) -> Path:
    """Get run path from environment variable or auto-detect most recent.

    Precedence:
    1. Environment variable (if set)
    2. Most recent run in base_path/data/runs
    3. Raise NoRunsFoundError if none found

    Args:
        env_var: Environment variable name to check
        base_path: Base path for auto-detection

    Returns:
        Path to the run directory

    Raises:
        NoRunsFoundError: If no runs found and env var not set
    """
    import os

    # Check environment variable first
    env_path = os.getenv(env_var)
    if env_path:
        return Path(env_path)

    # Fall back to auto-detection
    return find_most_recent_run(base_path)
