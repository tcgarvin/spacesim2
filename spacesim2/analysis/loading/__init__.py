"""Loading functionality for reading Parquet files into DataFrames."""

from pathlib import Path
from typing import Optional

from spacesim2.analysis.loading.loader import SimulationData
from spacesim2.analysis.loading.utils import (
    NoRunsFoundError,
    find_most_recent_run,
    get_run_path_with_fallback,
)


def load_run(run_path: Optional[Path | str] = None) -> SimulationData:
    """Load a simulation run for analysis with one line.

    Convenience wrapper for Tier-1 analysis scripts: resolves the run path
    (explicit arg > ``SPACESIM_RUN_PATH`` env var > most recent run) and
    returns a lazily-loading ``SimulationData``.

    Args:
        run_path: Explicit run directory. If omitted, auto-detects.

    Returns:
        A ``SimulationData`` exposing ``.actor_turns``, ``.actor_drives``,
        ``.market_transactions``, and ``.market_snapshots`` as Polars frames.
    """
    if run_path is None:
        run_path = get_run_path_with_fallback()
    return SimulationData(run_path)


__all__ = [
    "SimulationData",
    "NoRunsFoundError",
    "find_most_recent_run",
    "get_run_path_with_fallback",
    "load_run",
]
