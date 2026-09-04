"""Ship capital sizing and the distress exit from bankruptcy.

- starting_capital / fuel_capacity_for scale a ship to the galaxy it flies
  in, and floor at the values small galaxies were tuned with.
- _pair_economics credits fuel already in the tank against the refuel floor,
  so a full-tank ship is not priced out of every pair by a fuel spike.
- A docked, empty, planless and cash-starved ship becomes distressed and
  liquidates tank fuel above its survival target to trade its way back.
"""

from spacesim2.core.navigation import get_navigator
from spacesim2.core.ship import (
    BASE_FUEL_CAPACITY,
    DISTRESS_PATIENCE,
    SHIP_CAPITAL_FLOOR,
    Ship,
    fuel_capacity_for,
    mean_round_trip_fuel,
    starting_capital,
)
from spacesim2.core.simulation import Simulation
from tests.test_ship_fuel import _make_ship, _make_world

# Mean lane routes, in map units, of a small and a large galaxy. Measured
# with Navigator.mean_pair_distance: about 35 at five planets, about 300 at
# a hundred.
SMALL_GALAXY_DISTANCE = 35.0
LARGE_GALAXY_DISTANCE = 300.0


# ---------------------------------------------------------------------------
# Capital and tank sizing
# ---------------------------------------------------------------------------


def test_starting_capital_floors_at_the_tuned_baseline_in_small_galaxies():
    assert starting_capital(SMALL_GALAXY_DISTANCE, 1.0) == SHIP_CAPITAL_FLOOR
    assert starting_capital(0.0, 1.0) == SHIP_CAPITAL_FLOOR


def test_starting_capital_scales_with_galaxy_size():
    small = starting_capital(SMALL_GALAXY_DISTANCE, 1.0)
    large = starting_capital(LARGE_GALAXY_DISTANCE, 1.0)
    # A hundred-planet galaxy burns roughly six times the fuel per trip, so
    # the purse must grow by several multiples, not a few percent.
    assert large > 3 * small


def test_thirstier_ships_start_with_more_capital():
    thirsty = starting_capital(LARGE_GALAXY_DISTANCE, 0.8)
    frugal = starting_capital(LARGE_GALAXY_DISTANCE, 1.2)
    assert thirsty > frugal


def test_fuel_capacity_grows_only_once_round_trips_outgrow_the_tank():
    assert fuel_capacity_for(SMALL_GALAXY_DISTANCE, 1.0) == BASE_FUEL_CAPACITY
    large = fuel_capacity_for(LARGE_GALAXY_DISTANCE, 0.8)
    assert large > BASE_FUEL_CAPACITY
    # The tank still holds an average round trip with headroom to spare.
    assert large >= mean_round_trip_fuel(LARGE_GALAXY_DISTANCE, 0.8)


def test_directly_constructed_ship_keeps_the_constant_defaults():
    sim, _, _, (a, _) = _make_world([("A", 0, 0), ("B", 60, 0)])
    ship = Ship("Plain", sim, a)
    assert ship.money == SHIP_CAPITAL_FLOOR
    assert ship.fuel_capacity == BASE_FUEL_CAPACITY


def test_setup_scales_capital_with_the_galaxy_it_builds():
    small = Simulation()
    small.setup_simple(
        num_planets=3, num_regular_actors=2, num_market_makers=1, num_ships=1
    )
    large = Simulation()
    large.setup_simple(
        num_planets=40, num_regular_actors=2, num_market_makers=1, num_ships=1
    )

    assert (
        get_navigator(large).mean_pair_distance()
        > get_navigator(small).mean_pair_distance()
    )
    small_money = max(s.money for s in small.ships)
    large_money = min(s.money for s in large.ships)
    # A three-planet galaxy sits at or just above the tuned baseline; a
    # forty-planet one needs a clear multiple of it. Layouts are random, so
    # compare against the floor rather than the small galaxy's draw.
    assert SHIP_CAPITAL_FLOOR <= small_money < 1.5 * SHIP_CAPITAL_FLOOR
    assert large_money > 1.5 * SHIP_CAPITAL_FLOOR
    # Ships launch with a tankful proportional to the tank they were given.
    fuel = large.commodity_registry["nova_fuel"]
    for ship in large.ships:
        held = ship.cargo.get_quantity(fuel)
        assert 0 < held <= ship.fuel_capacity


# ---------------------------------------------------------------------------
# Fuel already held counts against the refuel floor
# ---------------------------------------------------------------------------


def test_pair_economics_credits_fuel_already_in_the_tank():
    """A full tank must not be re-charged in cash at spike prices."""
    sim, fuel, _, (a, b) = _make_world([("A", 0, 0), ("B", 60, 0)])
    # Fuel is dear here: a seller's ask of 200 a unit.
    seller = _make_ship(sim, a, fuel_units=40, money=0, name="Seller")
    a.market.place_sell_order(seller, fuel, 20, 200)

    # Poor ship, but its tank already covers the round trip and the reserve.
    ship = _make_ship(sim, a, fuel_units=40, money=300, name="Trader")
    pair = ship.brain._pair_economics(a, b)

    assert pair is not None
    assert pair.fuel_to_buy == 0
    assert pair.money_for_trading > 0


def test_pair_economics_still_charges_fuel_it_must_buy():
    sim, fuel, _, (a, b) = _make_world([("A", 0, 0), ("B", 60, 0)])
    seller = _make_ship(sim, a, fuel_units=40, money=0, name="Seller")
    a.market.place_sell_order(seller, fuel, 20, 200)

    # Empty tank, same purse: the round trip cannot be funded.
    ship = _make_ship(sim, a, fuel_units=0, money=300, name="Trader")
    assert ship.brain._pair_economics(a, b) is None


# ---------------------------------------------------------------------------
# Distress exit
# ---------------------------------------------------------------------------


def _idle_broke_ship(sim, planet, fuel_units=40):
    """A docked ship with a tank, no cargo, no plan and no money."""
    return _make_ship(sim, planet, fuel_units=fuel_units, money=0, name="Broke")


def test_solvent_ship_never_enters_distress():
    sim, fuel, _, (a, b) = _make_world([("A", 0, 0), ("B", 60, 0)])
    a.market.place_sell_order(_make_ship(sim, a, name="Seller"), fuel, 10, 20)
    ship = _make_ship(sim, a, fuel_units=40, money=5000, name="Rich")

    for _ in range(DISTRESS_PATIENCE + 2):
        ship.brain.decide_trade_actions()

    assert not ship.brain.is_distressed
    assert ship.brain._distress_entries == 0


def test_broke_idle_ship_becomes_distressed_and_sells_tank_fuel():
    sim, fuel, _, (a, b) = _make_world([("A", 0, 0), ("B", 60, 0)])
    # A local buyer of fuel, so the liquidation has somewhere to go.
    buyer = _make_ship(sim, b, money=5000, name="Buyer")
    a.market.place_buy_order(buyer, fuel, 20, 12)

    ship = _idle_broke_ship(sim, a)
    for _ in range(DISTRESS_PATIENCE):
        assert not ship.brain.is_distressed
        ship.brain.decide_trade_actions()

    assert ship.brain.is_distressed
    assert ship.brain._distress_entries == 1

    # Distress makes the tank above the survival target sellable, and the
    # ship offers it to the market rather than sitting on dead capital.
    survival = ship.brain._fuel_survival_target()
    assert ship.brain._sellable_quantity(fuel) == 40 - survival
    ship.brain.decide_trade_actions()
    sells = [o for o in a.market.sell_orders[fuel] if o.actor is ship]
    assert sells
    assert sum(o.quantity for o in sells) == 40 - survival


def test_distress_never_sells_below_the_survival_target():
    sim, fuel, _, (a, b) = _make_world([("A", 0, 0), ("B", 60, 0)])
    ship = _idle_broke_ship(sim, a, fuel_units=3)
    for _ in range(DISTRESS_PATIENCE + 1):
        ship.brain.decide_trade_actions()

    assert ship.brain.is_distressed
    assert ship.brain._sellable_quantity(fuel) == 0


def test_distress_clears_once_the_ship_has_cash_again():
    sim, fuel, _, (a, b) = _make_world([("A", 0, 0), ("B", 60, 0)])
    ship = _idle_broke_ship(sim, a)
    for _ in range(DISTRESS_PATIENCE + 1):
        ship.brain.decide_trade_actions()
    assert ship.brain.is_distressed

    ship.money = 5000
    ship.brain.decide_trade_actions()
    assert not ship.brain.is_distressed
