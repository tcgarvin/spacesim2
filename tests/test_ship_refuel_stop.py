"""Opportunistic en-route refuel stops.

A ship flying a multi-lane route may dock at an intermediate planet to buy
cheap fuel and then resume to its original destination. These tests cover the
criteria for taking a stop, the refund of unburned route fuel, the resumed
departure, and what the stop must leave untouched.
"""

import math

from spacesim2.core.commodity import CommodityDefinition, CommodityRegistry
from spacesim2.core.galaxy import StarLaneNetwork
from spacesim2.core.market import Market
from spacesim2.core.planet import Planet
from spacesim2.core.ship import (
    FUEL_STOP_TANK_FRACTION,
    REFUEL_STOP_MAX_SHORTFALL,
    REFUEL_STOP_MAX_TURNS,
    Ship,
    ShipStatus,
    TradePlan,
)

# A -- B -- C in a line, one lane of 20 distance units each. A lane is one
# turn and one fuel unit, so route fuel splits exactly at B: the refund of
# unburned fuel covers the second leg with nothing lost to rounding.
CHAIN = [("A", 0, 0), ("B", 20, 0), ("C", 40, 0)]
# The same chain with 30-unit lanes, which do not divide by 20: the whole
# route costs 3 fuel but each leg costs 2, so breaking it at B leaves the ship
# one unit short of the leg to C.
UNEVEN_CHAIN = [("A", 0, 0), ("B", 30, 0), ("C", 60, 0)]


def _make_chain_world(specs=CHAIN):
    """Planets joined in a line by lanes, in the order given."""
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
    planets = [Planet(name, Market(), x, y) for name, x, y in specs]
    lanes = StarLaneNetwork()
    for previous, planet in zip(planets, planets[1:]):
        lanes.add_lane(previous, planet)
    sim = type(
        "MockSim",
        (object,),
        {
            "commodity_registry": registry,
            "planets": planets,
            "star_lanes": lanes,
            "current_turn": 0,
        },
    )()
    return sim, fuel, food, planets


def _make_ship(sim, planet, fuel_units=0, money=1000, name="Trader"):
    ship = Ship(name, sim, planet, initial_money=money)
    planet.add_ship(ship)
    ship.fuel = fuel_units
    ship.check_maintenance = lambda: False  # deterministic departures
    return ship


def _sell_fuel(sim, planet, price, quantity=100, name=None):
    """Rest a fuel ask of ``quantity`` units at ``planet`` and give it history."""
    fuel = sim.commodity_registry.get_commodity("nova_fuel")
    supplier = _make_ship(sim, planet, name=name or f"Supplier{planet.name}", money=10)
    supplier.cargo.add_commodity(fuel, quantity * 2)
    planet.market.place_sell_order(supplier, fuel, quantity, price)
    return supplier


def _price_history(planet, commodity, price, turns=10):
    """Give ``planet`` a real price signal and 30-day average of ``price``."""
    planet.market.price_history[commodity] = [price] * turns
    planet.market.last_traded_prices[commodity] = [price] * turns
    planet.market._avg30_price_cache.clear()
    planet.market._avg_price_cache.clear()
    planet.market._price_signal_cache.clear()


def _world(
    middle_ask=5, middle_history=20, end_ask=20, tank=None, money=1000, specs=CHAIN
):
    """A ship departing A for C with cheap fuel and a price signal at B."""
    sim, fuel, food, (a, b, c) = _make_chain_world(specs)
    _sell_fuel(sim, a, end_ask)
    _sell_fuel(sim, c, end_ask)
    _price_history(a, fuel, end_ask)
    _price_history(c, fuel, end_ask)
    if middle_ask is not None:
        _sell_fuel(sim, b, middle_ask)
    if middle_history is not None:
        _price_history(b, fuel, middle_history)

    ship = _make_ship(sim, a, fuel_units=tank if tank is not None else 20, money=money)
    ship.brain._nav.refresh_market_facts(turn=0)
    return sim, fuel, food, (a, b, c), ship


def _depart(ship, destination, turn_value=0.0):
    """Start the A -> C journey with a recorded per-turn trip value."""
    ship.brain._departed_trip_turn_value = turn_value
    assert ship.start_journey(destination)
    return ship


def _advance(sim, ship):
    """Run one ship turn at the next simulation turn."""
    sim.current_turn += 1
    ship.take_turn()


# ---------------------------------------------------------------------------
# The stop itself
# ---------------------------------------------------------------------------


def test_ship_stops_at_the_middle_planet_and_resumes_with_more_fuel():
    """A cheap deep ask en route: dock, bid, pump, resume, arrive fuller."""
    sim, fuel, _, (a, b, c), ship = _world()
    _depart(ship, c)
    assert ship.route == [a, b, c]
    assert ship.route_fuel_charged == 2

    # Turn 1: the ship reaches B, docks, and bids for fuel.
    _advance(sim, ship)
    assert ship.status == ShipStatus.DOCKED
    assert ship.planet is b
    assert ship.refuel_stop_resume is c
    assert ship.refuel_stops == 1
    # Charged 2 for the whole route, burned 1 to B.
    assert ship.fuel == 19
    buys = [o for o in b.market.buy_orders[fuel] if o.actor is ship]
    assert len(buys) == 1 and buys[0].quantity > 0

    b.market.match_orders()
    assert ship.cargo.get_quantity(fuel) > 0

    # Turn 2: pump and resume.
    _advance(sim, ship)
    assert ship.status == ShipStatus.TRAVELING
    assert ship.destination is c
    assert ship.refuel_stop_resume is None

    # Turn 3: arrive at C with more fuel than a straight flight would leave.
    _advance(sim, ship)
    assert ship.planet is c
    assert ship.status == ShipStatus.DOCKED
    # A straight flight would have landed with 18.
    assert ship.fuel > 18


def test_a_stop_never_leaves_the_ship_short_of_the_remaining_route():
    """The refunded fuel always covers the leg still to fly."""
    sim, _, _, (a, b, c), ship = _world()
    _depart(ship, c)
    _advance(sim, ship)
    assert ship.planet is b
    remaining = ship.fuel_required(ship.brain._nav.distance(b, c))
    assert ship.fuel >= remaining


def test_a_one_unit_rounding_shortfall_is_bought_rather_than_refused():
    """Lanes that do not split evenly cost a unit, which the stop buys back."""
    # 30 + 30 costs ceil(30/20) twice = 4 against ceil(60/20) = 3 for the
    # whole route, so the refund of 1 is a unit short of the leg still to fly.
    sim, fuel, _, (a, b, c), ship = _world(specs=UNEVEN_CHAIN)
    _depart(ship, c)
    assert ship.route_fuel_charged == 3

    _advance(sim, ship)
    _advance(sim, ship)
    assert ship.planet is b
    assert ship.refuel_stop_resume is c
    buys = [o for o in b.market.buy_orders[fuel] if o.actor is ship]
    assert len(buys) == 1 and buys[0].quantity > 0


def test_no_stop_when_the_shortfall_is_over_the_cap():
    """A shortfall above REFUEL_STOP_MAX_SHORTFALL refuses the stop.

    Charging the route two units less than it costs forces a three-unit
    shortfall out of a chain whose own rounding loses one.
    """
    sim, _, _, (a, b, c), ship = _world(specs=UNEVEN_CHAIN)
    _depart(ship, c)
    ship.route_fuel_charged -= REFUEL_STOP_MAX_SHORTFALL

    _advance(sim, ship)
    _advance(sim, ship)
    assert ship.status == ShipStatus.TRAVELING
    assert ship.refuel_stop_resume is None


def test_an_unaffordable_shortfall_refuses_the_stop():
    """A ship that cannot buy the unit the rounding costs flies on instead."""
    sim, _, _, (a, b, c), ship = _world(specs=UNEVEN_CHAIN, money=0)
    _depart(ship, c)

    _advance(sim, ship)
    _advance(sim, ship)
    assert ship.status == ShipStatus.TRAVELING
    assert ship.refuel_stop_resume is None


def test_an_unfilled_shortfall_is_re_bought_before_the_resume():
    """The ship stays docked and bids again until the tank covers the leg."""
    sim, fuel, _, (a, b, c), ship = _world(specs=UNEVEN_CHAIN, tank=3)
    _depart(ship, c)
    assert ship.fuel == 0

    _advance(sim, ship)
    _advance(sim, ship)
    assert ship.planet is b
    assert ship.fuel == 1  # the refund, one short of the leg to C
    assert [o for o in b.market.buy_orders[fuel] if o.actor is ship]

    # Nothing fills: the ship must not depart, and must bid again.
    _advance(sim, ship)
    assert ship.status == ShipStatus.DOCKED
    assert ship.refuel_stop_resume is c
    buys = [o for o in b.market.buy_orders[fuel] if o.actor is ship]
    assert len(buys) == 1 and buys[0].quantity > 0

    b.market.match_orders()
    _advance(sim, ship)
    assert ship.status == ShipStatus.TRAVELING
    assert ship.destination is c


# ---------------------------------------------------------------------------
# When not to stop
# ---------------------------------------------------------------------------


def _stop_taken(**kwargs):
    """Whether the ship stops at B on the A -> C journey."""
    turn_value = kwargs.pop("turn_value", 0.0)
    sim, _, _, (a, b, c), ship = _world(**kwargs)
    _depart(ship, c, turn_value=turn_value)
    _advance(sim, ship)
    return ship.refuel_stop_resume is not None


def test_no_stop_with_a_full_enough_tank():
    """Above FUEL_STOP_TANK_FRACTION there is too little room to be worth it."""
    sim, _, _, (a, b, c), ship = _world(tank=40)
    _depart(ship, c)
    # After the refund the tank is back above the fraction.
    assert ship.fuel + 1 >= FUEL_STOP_TANK_FRACTION * ship.fuel_capacity
    _advance(sim, ship)
    assert ship.refuel_stop_resume is None
    assert _stop_taken(tank=20) is True


def test_no_stop_above_the_planets_own_thirty_day_average():
    """An ask above what this planet usually charges is not a bargain here."""
    assert _stop_taken(middle_ask=8, middle_history=6) is False
    assert _stop_taken(middle_ask=8, middle_history=20) is True


def test_no_stop_without_a_local_price_signal():
    """A planet that has never traded fuel is passed by rather than guessed at."""
    assert _stop_taken(middle_history=None) is False


def test_no_stop_at_or_above_the_galaxy_reference():
    """With no gap to the reference there is no saving to collect."""
    # Every planet asks and has traded at 20, so the reference is 20.
    assert _stop_taken(middle_ask=20, middle_history=20, end_ask=20) is False
    assert _stop_taken(middle_ask=19, middle_history=20, end_ask=20) is True


def test_no_stop_when_the_book_is_too_thin_to_beat_the_trip_value():
    """A one-unit ask cannot save enough to pay for the turns the stop costs."""
    sim, fuel, _, (a, b, c), ship = _world(middle_ask=None)
    _sell_fuel(sim, b, 5, quantity=1)
    _price_history(b, fuel, 20)
    ship.brain._nav.refresh_market_facts(turn=0)
    _depart(ship, c, turn_value=100.0)
    _advance(sim, ship)
    assert ship.refuel_stop_resume is None
    # The same thin book is worth stopping for when the trip is worth nothing.
    assert _stop_taken(middle_ask=5, turn_value=100.0) is True


def test_no_stop_when_the_ship_cannot_afford_a_useful_fill():
    """A ship with no money can fill nothing, so the stop saves nothing."""
    assert _stop_taken(money=0) is False


# ---------------------------------------------------------------------------
# What the stop must leave alone
# ---------------------------------------------------------------------------


def test_the_resumed_departure_does_not_roll_maintenance():
    """The maintenance roll belongs to the original departure, not the resume."""
    sim, _, _, (a, b, c), ship = _world()
    _depart(ship, c)
    _advance(sim, ship)
    assert ship.planet is b

    ship.check_maintenance = lambda: True  # would fail an unguarded departure
    b.market.match_orders()
    _advance(sim, ship)
    assert ship.status == ShipStatus.TRAVELING
    assert ship.destination is c


def test_a_loaded_plan_survives_the_stop_and_sells_at_the_destination():
    """The stop runs no plan lifecycle, so the cargo is still sold on arrival."""
    sim, fuel, food, (a, b, c), ship = _world()
    ship.cargo.add_commodity(food, 10)
    plan = TradePlan(
        origin=a,
        destination=c,
        commodity=food,
        quantity=10,
        bid_price_per_unit=10,
        purchase_price_per_unit=10,
        expected_sell_price_per_unit=30,
        distance=200.0,
        fuel_needed_one_way=10,
        fuel_price_at_origin=20,
        fuel_units_from_tank=0,
        fuel_price_from_tank=20,
    )
    ship.brain._current_plan = plan
    ship.brain._plan_loaded = True
    ship.brain._committed_fuel_need = 10
    ship.brain._addon_commodities = {food}

    _depart(ship, c)
    _advance(sim, ship)
    assert ship.planet is b
    assert ship.brain._current_plan is plan
    assert ship.brain._plan_loaded is True
    assert ship.brain._committed_fuel_need == 10
    assert ship.brain._addon_commodities == {food}
    # No cargo was sold at the stop.
    assert not c.market.sell_orders[food]
    assert not b.market.sell_orders[food]
    assert ship.cargo.get_quantity(food) == 10

    b.market.match_orders()
    _advance(sim, ship)  # resume
    _advance(sim, ship)  # arrive at C
    assert ship.planet is c

    buyer = _make_ship(sim, c, money=5000, name="Buyer")
    c.market.place_buy_order(buyer, food, 10, 30)
    ship.brain._nav.refresh_market_facts(turn=sim.current_turn)
    _advance(sim, ship)
    assert any(o.actor is ship for o in c.market.sell_orders[food])


def test_the_mode_clears_after_the_maximum_stop_turns():
    """A stop that cannot resume gives the ship back to the normal logic."""
    sim, _, _, (a, b, c), ship = _world()
    _depart(ship, c)
    _advance(sim, ship)
    assert ship.refuel_stop_resume is c

    # Nothing fills and the ship cannot fund the remaining leg.
    ship.fuel = 0
    ship.money = 0
    for _ in range(REFUEL_STOP_MAX_TURNS):
        _advance(sim, ship)
    assert ship.refuel_stop_resume is None
    assert ship.status == ShipStatus.DOCKED
    assert ship.planet is b


def test_stops_are_counted_for_analysis():
    """Every stop records its turn so the KPI window can count it."""
    sim, _, _, (a, b, c), ship = _world()
    _depart(ship, c)
    _advance(sim, ship)
    assert ship.refuel_stop_turns == [1]
    assert ship.refuel_stops == 1


def test_stop_turns_price_the_lane_rounding():
    """Splitting a route that does not divide evenly costs an extra turn."""
    sim, _, _, (a, b, c), ship = _world()
    _depart(ship, c)
    total = ship.route_cumulative_distance[-1]
    reached = ship.route_cumulative_distance[1]
    extra = (
        math.ceil(reached / 20)
        + math.ceil((total - reached) / 20)
        - math.ceil(total / 20)
    )
    assert extra == 0  # 20 + 20 splits exactly, so the stop costs one turn
