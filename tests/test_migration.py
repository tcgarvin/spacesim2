"""Tests for the core mechanics of actor migration.

Brain reasoning (whether and where to move) is tested elsewhere; these
cover what a move does: the land pools, the fare, the transit, and the
invariants the rest of the sim relies on.
"""

import pytest

from spacesim2.core.actor import Actor, ActorType
from spacesim2.core.actor_brain import ActorBrain
from spacesim2.core.brains import SpaceportOperatorBrain
from spacesim2.core.land import Land, NoFreeLandError
from spacesim2.core.market import Market
from spacesim2.core.migration import (
    NO_MIGRATION,
    MigrationRequest,
    passage_fare,
    refresh_planet_stats,
    run_migration_phase,
)
from spacesim2.core.planet import Planet
from spacesim2.core.simulation import Simulation


class StayPutBrain(ActorBrain):
    """A brain that does nothing, with a record of its relocation hook."""

    def __init__(self) -> None:
        self.relocated_count = 0

    def decide_economic_action(self, actor: Actor):
        return None

    def decide_market_actions(self, actor: Actor):
        return []

    def on_relocated(self, actor: Actor) -> None:
        self.relocated_count += 1


def _regular(sim: Simulation, name: str, money: int = 1000) -> Actor:
    return Actor(
        name=name,
        sim=sim,
        actor_type=ActorType.REGULAR,
        drives=[],
        brain=StayPutBrain(),
        initial_money=money,
    )


def _operator(sim: Simulation, name: str) -> Actor:
    return Actor(
        name=name,
        sim=sim,
        actor_type=ActorType.SERVICE,
        drives=[],
        brain=SpaceportOperatorBrain(),
        initial_money=0,
    )


def _two_planet_sim(lands: int = 10, operators: int = 2) -> Simulation:
    """A galaxy of two lane-joined planets with no automatic setup."""
    sim = Simulation()
    for name in ("Origin", "Destination"):
        market = Market()
        market.commodity_registry = sim.commodity_registry
        planet = Planet(name, market, x=0.0, y=0.0, num_lands=lands)
        sim.planets.append(planet)
    sim.planets[1].x = 30.0
    sim.star_lanes.add_lane(sim.planets[0], sim.planets[1])

    for index, planet in enumerate(sim.planets):
        for i in range(operators):
            operator = _operator(sim, f"{planet.name}Operator-{i}")
            sim.actors.append(operator)
            planet.add_actor(operator)
        for i in range(2):
            actor = _regular(sim, f"{planet.name}Regular-{index}{i}")
            sim.actors.append(actor)
            planet.add_actor(actor)
    return sim


class TestPlanetLandPool:
    def test_release_and_claim_round_trip(self) -> None:
        planet = Planet("P", Market(), num_lands=3)
        land = planet.claim_land()
        assert len(planet.free_lands) == 2
        planet.release_land(land)
        assert len(planet.free_lands) == 3
        assert any(other is land for other in planet.free_lands)

    def test_remove_actor_returns_land_to_pool(self) -> None:
        sim = Simulation()
        planet = Planet("P", Market(), num_lands=3)
        actor = _regular(sim, "A")
        planet.add_actor(actor)
        claimed = actor.land
        assert len(planet.free_lands) == 2

        planet.remove_actor(actor)
        assert actor not in planet.actors
        assert len(planet.free_lands) == 3
        assert any(land is claimed for land in planet.free_lands)
        assert actor.land.coefficients == Land.default().coefficients

    def test_service_actor_removal_touches_no_land(self) -> None:
        sim = Simulation()
        planet = Planet("P", Market(), num_lands=3)
        operator = _operator(sim, "Op")
        planet.add_actor(operator)
        assert len(planet.free_lands) == 3
        planet.remove_actor(operator)
        assert len(planet.free_lands) == 3

    def test_remove_actor_on_wrong_planet_raises(self) -> None:
        sim = Simulation()
        home = Planet("Home", Market(), num_lands=3)
        elsewhere = Planet("Elsewhere", Market(), num_lands=3)
        actor = _regular(sim, "A")
        home.add_actor(actor)
        with pytest.raises(ValueError):
            elsewhere.remove_actor(actor)

    def test_add_actor_with_land_does_not_draw_a_second(self) -> None:
        sim = Simulation()
        planet = Planet("P", Market(), num_lands=3)
        reserved = planet.claim_land()
        actor = _regular(sim, "A")
        planet.add_actor_with_land(actor, reserved)
        assert actor.land is reserved
        assert len(planet.free_lands) == 2
        assert actor.planet is planet

    def test_exhausted_pool_raises(self) -> None:
        planet = Planet("P", Market(), num_lands=1)
        planet.claim_land()
        with pytest.raises(NoFreeLandError):
            planet.claim_land()


class TestPlanetStats:
    def test_stats_over_regular_residents(self) -> None:
        sim = Simulation()
        sim.setup_simple(
            num_planets=2,
            num_regular_actors=4,
            num_market_makers=1,
            num_spaceport_operators=1,
            num_ships=0,
            lands_per_planet=20,
        )
        stats = refresh_planet_stats(sim)

        assert stats is sim.planet_stats
        assert set(stats) == set(sim.planets)
        for planet in sim.planets:
            entry = stats[planet]
            assert entry.population == 4  # service actors excluded
            assert entry.free_land_count == 20 - 4
            assert entry.free_land_mean  # non-empty pool
            assert all(0.0 <= v <= 1.0 for v in entry.free_land_mean.values())
            assert entry.median_money == 50.0
            assert 0.0 <= entry.median_need_debt <= 1.0
            assert 0.0 <= entry.median_prosperity <= 1.0

    def test_empty_pool_gives_empty_means(self) -> None:
        sim = _two_planet_sim(lands=2)
        stats = refresh_planet_stats(sim)
        entry = stats[sim.planets[0]]
        assert entry.free_land_count == 0
        assert entry.free_land_mean == {}
        assert entry.population == 2


class TestForcedMove:
    def test_move_conserves_money_land_and_membership(self) -> None:
        sim = _two_planet_sim(lands=10)
        origin, destination = sim.planets
        actor = next(a for a in origin.actors if a.claims_land)
        operators = [a for a in origin.actors if not a.claims_land]

        before_money = actor.money
        origin_free = len(origin.free_lands)
        destination_free = len(destination.free_lands)
        operator_money = sum(o.money for o in operators)
        old_land = actor.land

        sim.current_turn = 1
        actor.migration_request = MigrationRequest(destination, max_fare=10_000)
        run_migration_phase(sim)

        fare = passage_fare(30.0)
        assert actor.money == before_money - fare
        assert sum(o.money for o in operators) == operator_money + fare
        assert actor.migration_request is NO_MIGRATION

        # Left every list, but still points at the origin it departed from.
        assert actor not in sim.actors
        assert actor not in origin.actors
        assert actor not in destination.actors
        assert actor.in_transit is True
        assert actor.planet is origin

        # One land back to the origin pool, one reserved out of the destination.
        assert len(origin.free_lands) == origin_free + 1
        assert any(land is old_land for land in origin.free_lands)
        assert len(destination.free_lands) == destination_free - 1

        assert sim.migration_departures == 1
        assert sim.migration_arrivals == 0
        assert len(sim.migrants_in_transit) == 1
        event = sim.migration_log[-1]
        assert (event.origin_name, event.destination_name, event.fare) == (
            "Origin",
            "Destination",
            fare,
        )

    def test_arrival_places_the_actor_with_a_fresh_cache(self) -> None:
        sim = _two_planet_sim(lands=10)
        origin, destination = sim.planets
        actor = next(a for a in origin.actors if a.claims_land)
        brain = actor.brain
        assert isinstance(brain, StayPutBrain)
        # A stale yield_modifier entry would survive without the cache drop.
        brain._turn_cache(actor).yield_modifier["gather_wood"] = 0.5

        sim.current_turn = 1
        actor.migration_request = MigrationRequest(destination, max_fare=10_000)
        run_migration_phase(sim)
        migrant = sim.migrants_in_transit[0]
        assert migrant.arrival_turn > sim.current_turn
        reserved = migrant.land

        # Nothing happens before the arrival turn.
        for turn in range(2, migrant.arrival_turn):
            sim.current_turn = turn
            run_migration_phase(sim)
            assert actor.in_transit is True

        sim.current_turn = migrant.arrival_turn
        run_migration_phase(sim)

        assert actor.in_transit is False
        assert actor.planet is destination
        assert actor in destination.actors
        assert actor in sim.actors
        assert actor.land is reserved
        assert not any(land is reserved for land in destination.free_lands)
        assert brain._cache is None
        assert brain.relocated_count == 1
        assert actor.last_market_check_turn == sim.current_turn
        assert sim.migration_arrivals == 1
        assert not sim.migrants_in_transit

    def test_departure_cancels_orders_and_strips_inventory(self) -> None:
        sim = _two_planet_sim(lands=10)
        origin, destination = sim.planets
        actor = next(a for a in origin.actors if a.claims_land)
        wood = sim.commodity_registry.get_commodity("wood")
        food = sim.commodity_registry.get_commodity("food")
        assert wood is not None and food is not None

        actor.inventory.add_commodity(wood, 5)
        origin.market.place_sell_order(actor, wood, 5, 12)
        origin.market.place_buy_order(actor, food, 3, 7)
        assert actor.reserved_money == 21
        assert actor.active_orders

        money_before = actor.money
        sim.current_turn = 1
        actor.migration_request = MigrationRequest(destination, max_fare=10_000)
        run_migration_phase(sim)

        fare = passage_fare(30.0)
        # Reserved money came back before the fare was charged.
        assert actor.reserved_money == 0
        assert actor.money == money_before + 21 - fare
        assert not actor.active_orders
        assert actor.inventory.get_quantity(wood) == 0

    def test_unaffordable_fare_is_refused(self) -> None:
        sim = _two_planet_sim(lands=10)
        origin, destination = sim.planets
        actor = next(a for a in origin.actors if a.claims_land)
        actor.money = 1

        sim.current_turn = 1
        actor.migration_request = MigrationRequest(destination, max_fare=10_000)
        run_migration_phase(sim)

        assert actor.migration_request is NO_MIGRATION
        assert actor in sim.actors
        assert actor in origin.actors
        assert actor.money == 1
        assert sim.migration_departures == 0

    def test_fare_over_the_cap_is_refused(self) -> None:
        sim = _two_planet_sim(lands=10)
        origin, destination = sim.planets
        actor = next(a for a in origin.actors if a.claims_land)

        sim.current_turn = 1
        actor.migration_request = MigrationRequest(destination, max_fare=1)
        run_migration_phase(sim)

        assert actor.migration_request is NO_MIGRATION
        assert actor in origin.actors
        assert sim.migration_departures == 0

    def test_full_destination_is_refused(self) -> None:
        sim = _two_planet_sim(lands=10)
        origin, destination = sim.planets
        destination.free_lands.clear()
        actor = next(a for a in origin.actors if a.claims_land)

        sim.current_turn = 1
        actor.migration_request = MigrationRequest(destination, max_fare=10_000)
        run_migration_phase(sim)

        assert actor.migration_request is NO_MIGRATION
        assert actor in origin.actors
        assert sim.migration_departures == 0

    def test_request_for_the_current_planet_is_refused(self) -> None:
        sim = _two_planet_sim(lands=10)
        origin = sim.planets[0]
        actor = next(a for a in origin.actors if a.claims_land)

        sim.current_turn = 1
        actor.migration_request = MigrationRequest(origin, max_fare=10_000)
        run_migration_phase(sim)

        assert actor.migration_request is NO_MIGRATION
        assert actor in origin.actors
        assert sim.migration_departures == 0

    def test_fare_with_no_operators_is_destroyed(self) -> None:
        sim = _two_planet_sim(lands=10, operators=0)
        origin, destination = sim.planets
        actor = next(a for a in origin.actors if a.claims_land)
        money_before = actor.money

        sim.current_turn = 1
        actor.migration_request = MigrationRequest(destination, max_fare=10_000)
        run_migration_phase(sim)

        assert actor.money == money_before - passage_fare(30.0)
        assert sim.migration_departures == 1


class TestSimulationIntegration:
    def test_parallel_invariant_holds_with_a_migrant_in_transit(self) -> None:
        sim = Simulation()
        sim.setup_simple(
            num_planets=2,
            num_regular_actors=4,
            num_market_makers=1,
            num_spaceport_operators=1,
            num_ships=0,
            lands_per_planet=20,
        )
        origin, destination = sim.planets
        actor = next(a for a in origin.actors if a.claims_land)
        actor.money = 5_000
        actor.migration_request = MigrationRequest(destination, max_fare=10_000)
        run_migration_phase(sim)
        assert len(sim.migrants_in_transit) == 1

        # The parallel actor phase refuses to shard unless the two lists
        # cover each other exactly.
        assert sum(len(p.actors) for p in sim.planets) == len(sim.actors)

        sim.parallel_workers = 2
        sim.run_turn()
        assert sum(len(p.actors) for p in sim.planets) == len(sim.actors)

    def test_default_brains_run_turns_without_error(self) -> None:
        sim = Simulation()
        sim.setup_simple(
            num_planets=3,
            num_regular_actors=5,
            num_market_makers=1,
            num_spaceport_operators=1,
            num_ships=1,
            lands_per_planet=20,
        )
        for _ in range(5):
            sim.run_turn()

        assert sim.planet_stats
        placed = sum(len(p.actors) for p in sim.planets)
        assert placed == len(sim.actors)
        assert sim.migration_departures - sim.migration_arrivals == len(
            sim.migrants_in_transit
        )
