"""Tests for the fleet fuel KPIs in the summary's `trade` section."""

from typing import Dict

from spacesim2.analysis.summary import _ACTIVITY_WINDOW_TURNS, compute_summary
from spacesim2.core.ship import ShipStatus
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
        "idle_ships",
        "idle_ship_share",
        "departures_window",
        "service_fuel_stock",
        "industrialist_fuel_stock",
        "fuel_sold_by_service_window",
        "fuel_sold_by_service_price",
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

    assert isinstance(trade["idle_ships"], int)
    assert 0 <= trade["idle_ships"] <= len(sim.ships)

    assert isinstance(trade["idle_ship_share"], float)
    assert 0.0 <= trade["idle_ship_share"] <= 1.0

    assert isinstance(trade["departures_window"], int)
    assert trade["departures_window"] >= 0

    assert isinstance(trade["fuel_sold_by_service_window"], int)
    assert trade["fuel_sold_by_service_window"] >= 0

    assert isinstance(trade["fuel_sold_by_service_price"], float)
    assert trade["fuel_sold_by_service_price"] >= 0.0


def test_idle_ships_counts_never_departed_but_not_recently_departed() -> None:
    sim = Simulation()
    sim.setup_simple(
        num_planets=1, num_regular_actors=2, num_market_makers=1, num_ships=2
    )
    sim.current_turn = _ACTIVITY_WINDOW_TURNS + 10
    assert len(sim.ships) == 2

    never_departed, recently_departed = sim.ships
    for ship in sim.ships:
        ship.status = ShipStatus.DOCKED
    never_departed.last_departure_turn = 0
    recently_departed.last_departure_turn = sim.current_turn - 1

    trade_obj = compute_summary(sim)["trade"]
    assert isinstance(trade_obj, dict)
    trade: Dict[str, object] = trade_obj

    assert trade["idle_ships"] == 1
    assert trade["idle_ship_share"] == 0.5
