"""Tests for the live galaxy view's read-only adapters."""

from spacesim2.core.actor import ActorType
from spacesim2.core.ship import ShipStatus
from spacesim2.core.simulation import Simulation
from spacesim2.ui.live.view_model import GalaxyViewModel, planet_wellbeing


def _small_sim() -> Simulation:
    sim = Simulation()
    sim.setup_simple(
        num_planets=2,
        num_regular_actors=8,
        num_market_makers=1,
        num_ships=2,
    )
    return sim


def test_planet_wellbeing_in_unit_range_and_excludes_market_makers() -> None:
    sim = _small_sim()
    sim.run_turn()

    for planet in sim.planets:
        wellbeing = planet_wellbeing(planet)
        assert 0.0 <= wellbeing <= 1.0

        # Recompute over regular actors only and confirm it matches: this is the
        # exclusion guarantee (market makers must not influence the value).
        scores = []
        for actor in planet.actors:
            if actor.actor_type == ActorType.MARKET_MAKER or not actor.drives:
                continue
            scores.append(
                sum(d.metrics.get_score() for d in actor.drives) / len(actor.drives)
            )
        expected = sum(scores) / len(scores) if scores else 0.0
        assert abs(wellbeing - expected) < 1e-9


def test_current_turn_tracks_run_turn() -> None:
    sim = _small_sim()
    vm = GalaxyViewModel(sim)
    start = vm.current_turn
    sim.run_turn()
    sim.run_turn()
    assert vm.current_turn == start + 2


def test_docked_ship_snapshot_has_zero_progress_and_coincident_endpoints() -> None:
    sim = _small_sim()
    vm = GalaxyViewModel(sim)
    # Fresh ships start docked.
    for snap in vm.ships():
        assert not snap.traveling
        assert snap.progress == 0.0
        assert snap.origin == snap.dest


def test_traveling_ship_snapshot_interpolation_fields() -> None:
    sim = _small_sim()
    vm = GalaxyViewModel(sim)
    ship = sim.ships[0]
    origin, dest = sim.planets[0], sim.planets[1]

    # Force a traveling state directly (avoids fuel/decision dependencies).
    ship.planet = origin
    ship.destination = dest
    ship.status = ShipStatus.TRAVELING
    ship.travel_progress = 0.5

    snap = next(s for s in vm.ships() if s.name == ship.name)
    assert snap.traveling
    assert snap.origin == origin.get_position()
    assert snap.dest == dest.get_position()
    assert snap.origin != snap.dest
    assert abs(snap.progress - 0.5) < 1e-9
