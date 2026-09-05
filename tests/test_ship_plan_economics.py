"""Tests for how a ship prices a trade plan.

Three rules the plan economics have to keep straight:
- Fuel: the *margin* carries the outbound leg only, since the return leg is
  capital the next trade spends, while the *cash gate* still withholds the
  whole round trip so a disappointing trade cannot leave a ship broke and dry.
- Prices: what the ship bids and what the cargo is expected to cost are
  different numbers. A cheap resting ask is the cost basis; the bid may sit
  above it to win units out of the turn's flow.
- Fuel plans: a nova_fuel plan counts tank fuel above the travel reserve as
  its load at the origin, so it can reach ``_plan_loaded`` and fly.
"""

from spacesim2.core.commodity import CommodityDefinition, CommodityRegistry
from spacesim2.core.galaxy import StarLaneNetwork
from spacesim2.core.market import Market
from spacesim2.core.planet import Planet
from spacesim2.core.ship import ACCUMULATION_PATIENCE, Ship


def _make_world(planet_specs):
    """Build a nova_fuel and food registry, planets with markets, and a mock sim."""
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


def _make_ship(sim, planet, fuel_units=0, efficiency=1.0, money=1000, name="TestShip"):
    ship = Ship(name, sim, planet, fuel_efficiency=efficiency, initial_money=money)
    planet.add_ship(ship)
    if fuel_units:
        fuel = sim.commodity_registry.get_commodity("nova_fuel")
        ship.cargo.add_commodity(fuel, fuel_units)
    ship.check_maintenance = lambda: False  # deterministic departures
    return ship


def _record_flow(market, commodity, price, volume):
    """Give ``commodity`` a believable clearing price and recent volume."""
    market.last_traded_prices[commodity] = [price]
    market.price_history[commodity] = [price]
    market.volume_history[commodity] = [volume]
    market._clear_history_read_caches()


# ---------------------------------------------------------------------------
# Fuel: one way in the margin, round trip in the cash gate
# ---------------------------------------------------------------------------


def test_margin_charges_only_the_outbound_leg_of_fuel():
    sim, fuel, food, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    seller = _make_ship(sim, a, fuel_units=200, name="Seller")
    seller.cargo.add_commodity(food, 50)
    a.market.place_sell_order(seller, food, 50, 10)
    a.market.place_sell_order(seller, fuel, 100, 5)
    buyer = _make_ship(sim, b, money=5000, name="Buyer")
    b.market.place_buy_order(buyer, food, 50, 30)

    trader = _make_ship(sim, a, money=5000, name="Trader")
    plan = trader.brain._evaluate_trade_opportunity(a, b, food)

    assert plan is not None
    # Nothing in the tank, so every unit of the outbound burn is bought here.
    assert plan.fuel_units_from_tank == 0
    assert plan.total_fuel_cost == plan.fuel_needed_one_way * plan.fuel_price_at_origin
    assert plan.total_fuel_cost * 2 == plan.fuel_needed_round_trip * (
        plan.fuel_price_at_origin
    )


def test_fuel_already_aboard_is_charged_at_the_reference_not_the_local_spike():
    sim, fuel, food, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    seller = _make_ship(sim, a, fuel_units=200, name="Seller")
    seller.cargo.add_commodity(food, 50)
    a.market.place_sell_order(seller, food, 50, 10)
    # The only fuel for sale here is priced far above what fuel is worth.
    a.market.place_sell_order(seller, fuel, 100, 200)
    _record_flow(b.market, fuel, 20, 3)
    supplier_b = _make_ship(sim, b, fuel_units=200, name="SupplierB")
    b.market.place_sell_order(supplier_b, fuel, 100, 20)
    buyer = _make_ship(sim, b, money=20000, name="Buyer")
    b.market.place_buy_order(buyer, food, 50, 40)

    # A full tank: the outbound leg costs the ship nothing at the local ask.
    trader = _make_ship(sim, a, fuel_units=60, money=20000, name="Trader")
    trader.brain._nav.refresh_market_facts()
    plan = trader.brain._evaluate_trade_opportunity(a, b, food)

    assert plan is not None
    assert plan.fuel_units_from_tank == plan.fuel_needed_one_way
    assert plan.fuel_price_at_origin == 200
    assert plan.fuel_price_from_tank < plan.fuel_price_at_origin
    assert plan.total_fuel_cost == (
        plan.fuel_needed_one_way * plan.fuel_price_from_tank
    )


def test_cash_gate_still_withholds_the_whole_round_trip():
    sim, fuel, food, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    seller = _make_ship(sim, a, fuel_units=200, name="Seller")
    seller.cargo.add_commodity(food, 50)
    a.market.place_sell_order(seller, food, 50, 10)
    a.market.place_sell_order(seller, fuel, 100, 40)
    buyer = _make_ship(sim, b, money=5000, name="Buyer")
    b.market.place_buy_order(buyer, food, 50, 30)

    rich = _make_ship(sim, a, money=5000, name="Rich")
    pair = rich.brain._pair_economics(a, b)
    assert pair is not None
    fuel_one_way = rich.fuel_required(rich.route_distance(a, b))
    assert pair.fuel_to_buy == fuel_one_way * 2

    # Enough cash for the outbound leg's fuel but not the return leg's: the
    # gate must refuse, or the ship strands at B with no way home.
    one_way_only = fuel_one_way * 40 + 10
    poor = _make_ship(sim, a, money=one_way_only, name="Poor")
    assert poor.brain._pair_economics(a, b) is None


# ---------------------------------------------------------------------------
# Prices: bid versus evaluation
# ---------------------------------------------------------------------------


def test_evaluation_price_uses_the_resting_ask_while_the_bid_chases_the_flow():
    sim, fuel, food, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    seller = _make_ship(sim, a, fuel_units=200, name="Seller")
    seller.cargo.add_commodity(food, 50)
    # A real, deep resting ask at 10 ...
    a.market.place_sell_order(seller, food, 40, 10)
    a.market.place_sell_order(seller, fuel, 100, 5)
    # ... under a flow that has been clearing at 20.
    _record_flow(a.market, food, 20, 6)
    buyer = _make_ship(sim, b, money=20000, name="Buyer")
    b.market.place_buy_order(buyer, food, 40, 30)

    trader = _make_ship(sim, a, money=20000, name="Trader")
    acquisition = trader.brain._origin_acquisition(a, food)
    assert acquisition is not None
    assert acquisition.entry_price == 10
    assert acquisition.bid_price == 20  # posted high to win flow units

    plan = trader.brain._evaluate_trade_opportunity(a, b, food)
    assert plan is not None
    assert plan.bid_price_per_unit == 20
    # The cargo fits inside the resting ask, so it is expected to cost 10.
    assert plan.quantity <= 40
    assert plan.purchase_price_per_unit == 10
    assert plan.total_purchase_cost == plan.quantity * 10


def test_evaluation_price_walks_past_a_thin_ask_into_the_flow():
    sim, fuel, food, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    seller = _make_ship(sim, a, fuel_units=200, name="Seller")
    seller.cargo.add_commodity(food, 60)
    # Only two units resting cheap; the rest has to be won out of the flow.
    a.market.place_sell_order(seller, food, 2, 10)
    a.market.place_sell_order(seller, fuel, 100, 5)
    _record_flow(a.market, food, 20, 6)
    buyer = _make_ship(sim, b, money=20000, name="Buyer")
    b.market.place_buy_order(buyer, food, 40, 30)

    trader = _make_ship(sim, a, money=20000, name="Trader")
    plan = trader.brain._evaluate_trade_opportunity(a, b, food)

    assert plan is not None
    assert plan.quantity > 2
    # Two units at 10, the remainder at the 20 bid, rounded up.
    expected = -(-(2 * 10 + (plan.quantity - 2) * 20) // plan.quantity)
    assert plan.purchase_price_per_unit == expected
    assert 10 < plan.purchase_price_per_unit <= 20


# ---------------------------------------------------------------------------
# Fuel plans load at the origin
# ---------------------------------------------------------------------------


def test_fuel_plan_counts_tank_fuel_above_the_reserve_as_its_load():
    sim, fuel, _, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    seller = _make_ship(sim, a, fuel_units=400, name="Seller")
    a.market.place_sell_order(seller, fuel, 200, 10)
    # B pays well for fuel and has none of its own.
    buyer = _make_ship(sim, b, money=20000, name="Buyer")
    b.market.place_buy_order(buyer, fuel, 60, 40)
    _record_flow(b.market, fuel, 40, 4)

    # Exactly a full tank, so there is no overflow above capacity: before the
    # origin rule this ship's fuel counted as nothing and the plan could
    # never load.
    trader = _make_ship(sim, a, money=5000, name="Trader")
    trader.cargo.add_commodity(fuel, trader.fuel_capacity)
    trader.brain._nav.refresh_market_facts()
    plan = trader.brain._evaluate_trade_opportunity(a, b, fuel)
    assert plan is not None

    trader.brain._current_plan = plan
    trader.brain._plan_loaded = False
    trader.brain._plan_turns_left = ACCUMULATION_PATIENCE

    # At the plan's origin the tank above the travel reserve is the load.
    reserve = trader.brain._fuel_sell_reserve()
    assert reserve > 0
    already_held = trader.fuel_capacity - reserve
    assert trader.brain._sellable_quantity(fuel) == already_held

    # So the plan bids only for the shortfall, and offers nothing for sale
    # here: loading is not selling.
    trader.brain.decide_trade_actions()
    bids = [o for o in a.market.buy_orders[fuel] if o.actor is trader]
    assert [o.quantity for o in bids] == [plan.quantity - already_held]
    assert not [o for o in a.market.sell_orders[fuel] if o.actor is trader]

    # Once the shortfall is aboard the plan is loaded and flies.
    trader.cargo.add_commodity(fuel, plan.quantity - already_held)
    trader.brain.decide_trade_actions()
    assert trader.brain._plan_loaded is True
    assert not [o for o in a.market.sell_orders[fuel] if o.actor is trader]
    assert trader.brain.decide_travel() is b


def test_fuel_outside_a_fuel_plan_is_still_not_trade_cargo():
    sim, fuel, _, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    seller = _make_ship(sim, a, fuel_units=400, name="Seller")
    a.market.place_sell_order(seller, fuel, 200, 10)

    trader = _make_ship(sim, a, money=5000, name="Trader")
    trader.cargo.add_commodity(fuel, trader.fuel_capacity)
    trader.brain._nav.refresh_market_facts()

    # No plan at all, and a full tank: the tank is not for sale. Only
    # overflow above the tank would be, and there is none.
    assert trader.brain._current_plan is None
    assert trader.brain._sellable_quantity(fuel) == 0
