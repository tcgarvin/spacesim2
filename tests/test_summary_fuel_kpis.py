"""Tests for the fleet fuel KPIs in the summary's `trade` section."""

from typing import Dict

from spacesim2.analysis.summary import compute_summary
from spacesim2.core.simulation import Simulation


def test_fleet_fuel_kpis_present_and_in_range() -> None:
    sim = Simulation()
    sim.setup_simple(
        num_planets=3, num_regular_actors=6, num_market_makers=1, num_ships=2
    )
    for _ in range(20):
        sim.run_turn()

    trade_obj = compute_summary(sim)["trade"]
    assert isinstance(trade_obj, dict)
    trade: Dict[str, object] = trade_obj

    for key in (
        "fuel_ask_planets",
        "stranded_ships",
        "stranded_ship_share",
        "service_fuel_stock",
        "industrialist_fuel_stock",
    ):
        assert key in trade, f"missing trade key: {key}"

    assert isinstance(trade["fuel_ask_planets"], int)
    assert 0 <= trade["fuel_ask_planets"] <= len(sim.planets)

    assert isinstance(trade["stranded_ships"], int)
    assert 0 <= trade["stranded_ships"] <= len(sim.ships)

    assert isinstance(trade["stranded_ship_share"], float)
    assert 0.0 <= trade["stranded_ship_share"] <= 1.0

    assert isinstance(trade["service_fuel_stock"], int)
    assert trade["service_fuel_stock"] >= 0

    assert isinstance(trade["industrialist_fuel_stock"], int)
    assert trade["industrialist_fuel_stock"] >= 0
