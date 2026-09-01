"""Unit tests for the shared galaxy navigation cache (core/navigation.py)."""

import math

from spacesim2.core.commodity import CommodityDefinition, CommodityRegistry
from spacesim2.core.galaxy import StarLaneNetwork
from spacesim2.core.market import Market
from spacesim2.core.navigation import (
    DESTINATION_NEAREST_M,
    DESTINATION_TOP_K,
    Navigator,
    get_navigator,
)
from spacesim2.core.planet import Planet
from spacesim2.core.ship import Ship


def _make_world(planet_specs):
    """Build a registry (nova_fuel + food), planets with markets, and a mock sim."""
    registry = CommodityRegistry()
    fuel = CommodityDefinition(
        id="nova_fuel",
        name="NovaFuel",
        transportable=True,
        description="High-density energy source for starship travel.",
    )
    food = CommodityDefinition(
        id="food", name="Food", transportable=True, description="Basic sustenance."
    )
    registry.add_commodity(fuel)
    registry.add_commodity(food)
    planets = [Planet(name, Market(), x, y) for name, x, y in planet_specs]
    sim = type(
        "MockSim",
        (object,),
        {
            "commodity_registry": registry,
            "planets": planets,
            "star_lanes": StarLaneNetwork.complete(planets),
            "current_turn": 0,
        },
    )()
    return sim, fuel, food, planets


def _direct_distance(a: Planet, b: Planet) -> float:
    return math.sqrt((b.x - a.x) ** 2 + (b.y - a.y) ** 2)


def test_distance_matrix_matches_direct_formula():
    sim, _, _, planets = _make_world(
        [("A", 0, 0), ("B", 100, 0), ("C", -30, 40), ("D", 17, -260)]
    )
    nav = Navigator(sim)
    for a in planets:
        for b in planets:
            assert nav.distance(a, b) == _direct_distance(a, b)
    # Diagonal is zero, matrix is symmetric.
    assert nav.distance(planets[0], planets[0]) == 0.0
    assert nav.distance(planets[1], planets[3]) == nav.distance(planets[3], planets[1])


def test_distance_matrix_rebuilds_when_planets_added():
    sim, _, _, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    nav = Navigator(sim)
    assert nav.distance(a, b) == 100.0
    late = Planet("Late", Market(), 0, 40)
    sim.planets.append(late)
    sim.star_lanes.add_lane(a, late)
    assert nav.distance(a, late) == 40.0
    assert nav.planets_by_proximity(a) == [late, b]


def test_nearest_other_distance_and_proximity_order():
    sim, _, _, (a, b, c) = _make_world([("A", 0, 0), ("B", 100, 0), ("C", 0, 30)])
    nav = Navigator(sim)
    assert nav.nearest_other_distance(a) == 30.0
    assert nav.planets_by_proximity(a) == [c, b]
    assert nav.planets_by_proximity(b) == [a, c]


def test_fuel_purchasable_cached_until_refresh():
    sim, fuel, _, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    nav = Navigator(sim)
    supplier = Ship("Supplier", sim, a)
    supplier.cargo.add_commodity(fuel, 50)

    assert nav.fuel_purchasable_at(a) is False
    a.market.place_sell_order(supplier, fuel, 50, 10)

    # Still False: the answer is cached for the current planning decision...
    assert nav.fuel_purchasable_at(a) is False
    # ...and reflects the live book after a refresh.
    nav.refresh_market_facts()
    assert nav.fuel_purchasable_at(a) is True


def test_nearest_fuel_source_distance_tracks_purchasability():
    sim, fuel, _, (a, b, c) = _make_world([("A", 0, 0), ("B", 100, 0), ("C", 0, 30)])
    nav = Navigator(sim)
    assert nav.nearest_fuel_source_distance(a) is None

    supplier = Ship("Supplier", sim, b)
    supplier.cargo.add_commodity(fuel, 50)
    b.market.place_sell_order(supplier, fuel, 50, 10)
    nav.refresh_market_facts()

    # B is the only fuel source: 100 away from A, and excluded from its own
    # escape options.
    assert nav.nearest_fuel_source_distance(a) == 100.0
    assert nav.nearest_fuel_source_distance(b) is None


def test_fuel_market_scan_reports_asks_and_reference():
    sim, fuel, _, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    nav = Navigator(sim)
    assert nav.cheapest_fuel_ask() is None
    assert nav.fuel_value_reference() is None
    assert nav.fuel_ask_planets() == []

    supplier_a = Ship("SupplierA", sim, a)
    supplier_a.cargo.add_commodity(fuel, 50)
    supplier_b = Ship("SupplierB", sim, b)
    supplier_b.cargo.add_commodity(fuel, 50)
    a.market.place_sell_order(supplier_a, fuel, 50, 12)
    b.market.place_sell_order(supplier_b, fuel, 50, 8)
    nav.refresh_market_facts()

    assert nav.cheapest_fuel_ask() == 8
    assert nav.fuel_value_reference() == 8.0
    assert dict(nav.fuel_ask_planets()) == {a: 12, b: 8}


def test_exportable_commodity_summaries():
    sim, fuel, food, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    nav = Navigator(sim)
    assert nav.exportable_commodities(a) == frozenset()

    seller = Ship("Seller", sim, a)
    seller.cargo.add_commodity(food, 50)
    a.market.place_sell_order(seller, food, 50, 10)
    buyer = Ship("Buyer", sim, b, initial_money=1000)
    b.market.place_buy_order(buyer, food, 10, 15)
    nav.refresh_market_facts()

    assert nav.exportable_commodities(a) == frozenset({food})
    assert nav.candidate_destinations(a, food) == (b,)
    assert fuel not in nav.exportable_commodities(a)


def test_refresh_with_turn_is_a_per_turn_snapshot():
    """Same-turn refresh calls are no-ops; a new turn (or a forced refresh)
    rebuilds the market-fact snapshot."""
    sim, _, food, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    nav = Navigator(sim)
    nav.refresh_market_facts(turn=0)
    assert nav.exportable_commodities(a) == frozenset()
    assert nav.has_any_trade_signal() is False

    seller = Ship("Seller", sim, a)
    seller.cargo.add_commodity(food, 50)
    a.market.place_sell_order(seller, food, 50, 10)
    buyer = Ship("Buyer", sim, b, initial_money=1000)
    b.market.place_buy_order(buyer, food, 10, 15)

    # Same turn: the snapshot is shared and unchanged.
    nav.refresh_market_facts(turn=0)
    assert nav.exportable_commodities(a) == frozenset()

    # Next turn: rebuilt from the live books.
    nav.refresh_market_facts(turn=1)
    assert nav.exportable_commodities(a) == frozenset({food})
    assert nav.has_any_trade_signal() is True

    # A turn-less call always forces a refresh, even within the same turn.
    b.market.cancel_order(b.market.buy_orders[food][0].order_id)
    assert nav.candidate_destinations(a, food) == (b,)  # still snapshotted
    nav.refresh_market_facts()
    assert nav.candidate_destinations(a, food) == ()


def test_cold_galaxy_has_no_trade_signal():
    """With no orders and no trade history anywhere, the index reports a cold
    galaxy and candidate lists are empty."""
    sim, _, food, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    nav = Navigator(sim)
    assert nav.has_any_trade_signal() is False
    assert nav.candidate_destinations(a, food) == ()

    # Supply alone (no demand signal anywhere) is still cold.
    seller = Ship("Seller", sim, a)
    seller.cargo.add_commodity(food, 50)
    a.market.place_sell_order(seller, food, 50, 10)
    nav.refresh_market_facts()
    # The ask itself creates a demand signal nowhere; only planet A gains an
    # exportable entry. B has no bid and no price history.
    assert nav.exportable_commodities(a) == frozenset({food})
    assert nav.candidate_destinations(a, food) == ()


def _demand_world(num_planets: int):
    """A line of planets where planet i rests a food bid at price 10 + i.

    Planet 0 (the origin) also bids so demand-set membership excludes the
    origin itself, not just planets without signals.
    """
    specs = [(f"P{i}", i * 10, 0) for i in range(num_planets)]
    sim, _fuel, food, planets = _make_world(specs)
    for i, planet in enumerate(planets):
        buyer = Ship(f"Buyer{i}", sim, planet, initial_money=10_000)
        planet.market.place_buy_order(buyer, food, 10, 10 + i)
    return sim, food, planets


def test_candidate_destinations_degenerate_to_all_in_small_galaxies():
    """At or below K + M demand planets, the shortlist is every demand planet
    (so small-galaxy behavior matches an exhaustive survey)."""
    count = DESTINATION_TOP_K + DESTINATION_NEAREST_M + 1  # origin + K + M
    sim, food, planets = _demand_world(count)
    nav = Navigator(sim)
    origin = planets[0]
    candidates = nav.candidate_destinations(origin, food)
    assert set(candidates) == set(planets) - {origin}
    # Ranked by demand value (bid price), best first.
    assert list(candidates) == sorted(
        candidates, key=lambda p: -max(o.price for o in p.market.buy_orders[food])
    )


def test_candidate_destinations_match_bruteforce_topk_union_nearest():
    """Above the threshold, candidates equal brute-force top-K-by-value
    united with the M nearest demand planets."""
    sim, food, planets = _demand_world(30)
    nav = Navigator(sim)
    origin = planets[0]
    candidates = set(nav.candidate_destinations(origin, food))

    demand = [p for p in planets if p is not origin]
    top_k = set(
        sorted(
            demand,
            key=lambda p: -max(o.price for o in p.market.buy_orders[food]),
        )[:DESTINATION_TOP_K]
    )
    nearest_m = set(
        sorted(demand, key=lambda p: _direct_distance(origin, p))[
            :DESTINATION_NEAREST_M
        ]
    )
    assert candidates == top_k | nearest_m
    # Bid prices rise with distance here, so the two halves are disjoint and
    # the union genuinely mixes near and high-value planets.
    assert top_k.isdisjoint(nearest_m)
    assert len(candidates) == DESTINATION_TOP_K + DESTINATION_NEAREST_M


def test_candidate_destinations_invalidate_on_new_turn():
    sim, food, planets = _demand_world(30)
    nav = Navigator(sim)
    origin = planets[0]
    nav.refresh_market_facts(turn=0)
    before = nav.candidate_destinations(origin, food)

    # A new far-out bidder appears with the best price in the galaxy.
    newcomer = Planet("New", Market(), 500, 0)
    sim.star_lanes.add_lane(planets[-1], newcomer)
    sim.planets.append(newcomer)
    buyer = Ship("NewBuyer", sim, newcomer, initial_money=10_000)
    newcomer.market.place_buy_order(buyer, food, 10, 99)

    # Same turn: memoized shortlist unchanged.
    nav.refresh_market_facts(turn=0)
    assert nav.candidate_destinations(origin, food) == before
    assert newcomer not in before

    # Next turn: the newcomer leads the shortlist.
    nav.refresh_market_facts(turn=1)
    after = nav.candidate_destinations(origin, food)
    assert after[0] is newcomer


def test_get_navigator_is_shared_per_simulation():
    sim1, _, _, _ = _make_world([("A", 0, 0), ("B", 100, 0)])
    sim2, _, _, _ = _make_world([("A", 0, 0), ("B", 100, 0)])
    assert get_navigator(sim1) is get_navigator(sim1)
    assert get_navigator(sim1) is not get_navigator(sim2)
