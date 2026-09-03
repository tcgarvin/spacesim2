"""Macro behavioral smoke test for the simulation.

Asserts on population-wide outcomes via the KPI summary, so an economy change
that passes every unit test but wrecks aggregate behavior still fails here.

The simulation is stochastic and has no run-level seed, so assertions use
tolerances, not exact values. Keep the run short so the suite stays fast.
"""

import pytest

from spacesim2.analysis.summary import compute_summary
from spacesim2.cli.common import create_and_setup_simulation


@pytest.fixture(scope="module")
def smoke_summary() -> dict:
    """Run a small simulation and return its KPI summary."""
    sim = create_and_setup_simulation(planets=2, actors=40, makers=1, ships=1)
    for _ in range(120):
        sim.run_turn()
    return compute_summary(sim)


def test_summary_has_expected_shape(smoke_summary: dict) -> None:
    """The summary has the KPI blocks agents and notebooks read."""
    for key in ("turns", "money", "drives", "inventory_totals", "prices", "verdict"):
        assert key in smoke_summary, f"missing summary key: {key}"
    assert smoke_summary["turns"] == 120
    assert smoke_summary["regular_actors"] == 80  # 2 planets * 40 actors


def test_food_economy_is_alive(smoke_summary: dict) -> None:
    """Food mean health stays above the FAIL floor of 0.50 and food trades."""
    food = smoke_summary["drives"]["food"]
    assert food["mean_health"] > 0.55, f"food collapsed: {food}"
    assert "food" in smoke_summary["prices"], "no food market activity"


def test_verdict_not_failing(smoke_summary: dict) -> None:
    """A healthy short run does not trip the FAIL verdict."""
    verdict = smoke_summary["verdict"]
    assert verdict["status"] != "FAIL", f"unexpected FAIL: {verdict['flags']}"


def test_economy_produces_goods(smoke_summary: dict) -> None:
    """The bootstrap path runs: wood is harvested and food is produced."""
    totals = smoke_summary["inventory_totals"]
    assert totals.get("wood", 0) > 0, "no wood harvested (bootstrap broken)"
    assert totals.get("food", 0) > 0, "no food produced"
