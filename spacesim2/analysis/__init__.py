"""Analysis package for exporting and analyzing simulation data."""

from typing import Any

__all__ = ["SimulationData"]


def __getattr__(name: str) -> Any:
    # Lazy (PEP 562) so subpackages that don't need the optional analysis
    # extra — e.g. analysis.summary, imported by the headless CLI's
    # --summary path — work in environments without polars installed
    # (docs/performance.md's free-threaded side venv).
    if name == "SimulationData":
        from spacesim2.analysis.loading.loader import SimulationData

        return SimulationData
    raise AttributeError(name)
