"""Macro behavioral smoke test for the simulation.

Unlike the unit tests (which check individual drives/brains/markets), this
asserts on *emergent* population-wide outcomes via the KPI summary. It is the
safety net for economy changes: a tweak can pass every unit test yet wreck
aggregate behavior, and this catches that.

Assertions use tolerances, not exact values: the simulation is stochastic and
aggregate means over the population are stable but not bit-reproducible (see
docs / the `--seed` caveat). Keep the run short so the suite stays fast.
"""

import random

import pytest

from spacesim2.analysis.summary import compute_summary
from spacesim2.cli.common import create_and_setup_simulation


@pytest.fixture(scope="module")
def smoke_summary() -> dict:
    """Run a small seeded simulation and return its KPI summary."""
    random.seed(1234)
    sim = create_and_setup_simulation(
        planets=2, actors=40, makers=1, ships=1, enable_planet_attributes=True
    )
    for _ in range(120):
        sim.run_turn()
    return compute_summary(sim)


def test_summary_has_expected_shape(smoke_summary: dict) -> None:
    """The summary exposes the KPI blocks agents/notebooks depend on."""
    for key in ("turns", "money", "drives", "inventory_totals", "prices", "verdict"):
        assert key in smoke_summary, f"missing summary key: {key}"
    assert smoke_summary["turns"] == 120
    assert smoke_summary["regular_actors"] == 80  # 2 planets * 40 actors


def test_food_economy_is_alive(smoke_summary: dict) -> None:
    """Survival floor: people are fed and the food market trades.

    This is the catastrophe guard. Food mean health stays comfortably above
    the FAIL floor (0.50) across seeds, and food must have market activity.
    """
    food = smoke_summary["drives"]["food"]
    assert food["mean_health"] > 0.55, f"food collapsed: {food}"
    assert "food" in smoke_summary["prices"], "no food market activity"


def test_verdict_not_failing(smoke_summary: dict) -> None:
    """A healthy short run should not trip the catastrophe verdict."""
    verdict = smoke_summary["verdict"]
    assert verdict["status"] != "FAIL", f"unexpected FAIL: {verdict['flags']}"


def test_economy_produces_goods(smoke_summary: dict) -> None:
    """The bootstrap path runs: wood is harvested and food is produced."""
    totals = smoke_summary["inventory_totals"]
    assert totals.get("wood", 0) > 0, "no wood harvested (bootstrap broken)"
    assert totals.get("food", 0) > 0, "no food produced"
