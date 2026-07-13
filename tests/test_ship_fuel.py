"""Tests for the ship fuel system.

Covers the three fuel fixes:
- fuel_required: planning uses the same efficiency-adjusted number as
  consumption at departure.
- Fuel-aware route planning: destinations without purchasable fuel are only
  accepted when an escape route remains; plans that need fuel the origin
  cannot sell are rejected; docked ships top up toward a full tank.
- Standing fuel bids: a stranded ship posts a resting buy order priced to
  make delivery profitable for another trader, re-posts it each turn, and
  escalates the fallback price with scarcity pressure.
"""

import math

from spacesim2.core.commodity import CommodityDefinition, CommodityRegistry
from spacesim2.core.market import Market
from spacesim2.core.planet import Planet
from spacesim2.core.ship import FUEL_BID_MARGIN, Ship, TradePlan


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
        {"commodity_registry": registry, "planets": planets},
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


# ---------------------------------------------------------------------------
# Fix 1: fuel_required matches consumption
# ---------------------------------------------------------------------------


def test_fuel_required_applies_efficiency():
    sim, _, _, (a, _) = _make_world([("A", 0, 0), ("B", 50, 0)])
    nominal = _make_ship(sim, a, efficiency=1.0)
    inefficient = _make_ship(sim, a, efficiency=0.8)
    efficient = _make_ship(sim, a, efficiency=1.2)

    assert Ship.calculate_fuel_needed(50.0) == 3
    assert nominal.fuel_required(50.0) == 3
    assert inefficient.fuel_required(50.0) == 4  # ceil(3 / 0.8)
    assert efficient.fuel_required(50.0) == 3  # ceil(3 / 1.2) = ceil(2.5)


def test_departure_consumes_exactly_the_planned_fuel():
    sim, fuel, _, (a, b) = _make_world([("A", 0, 0), ("B", 50, 0)])
    ship = _make_ship(sim, a, fuel_units=10, efficiency=0.8)
    needed = ship.fuel_required(Ship.calculate_distance(a, b))

    assert ship.start_journey(b)
    assert ship.cargo.get_quantity(fuel) == 10 - needed


def test_trade_plan_reserves_efficiency_adjusted_fuel():
    sim, fuel, food, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    seller = _make_ship(sim, a, fuel_units=100, name="Seller")
    seller.cargo.add_commodity(food, 50)
    a.market.place_sell_order(seller, food, 50, 10)
    a.market.place_sell_order(seller, fuel, 50, 5)
    buyer = _make_ship(sim, b, money=2000, name="Buyer")
    b.market.place_buy_order(buyer, food, 50, 25)

    trader = _make_ship(sim, a, efficiency=0.8, name="Trader")
    plan = trader.brain._evaluate_trade_opportunity(a, b, food)

    assert plan is not None
    distance = Ship.calculate_distance(a, b)
    assert plan.fuel_needed_one_way == trader.fuel_required(distance)
    assert plan.fuel_needed_one_way == 7  # ceil(ceil(100/20) / 0.8)


# ---------------------------------------------------------------------------
# Fix 2: fuel-aware route planning
# ---------------------------------------------------------------------------


def test_plan_rejected_when_origin_cannot_sell_needed_fuel():
    sim, fuel, food, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    seller = _make_ship(sim, a, name="Seller")
    seller.cargo.add_commodity(food, 50)
    a.market.place_sell_order(seller, food, 50, 10)
    # Real demand at the destination (plans need visible profitable bids).
    buyer_b = _make_ship(sim, b, money=2000, name="BuyerB")
    b.market.place_buy_order(buyer_b, food, 50, 25)
    # Fuel is only for sale at the destination, not the origin.
    supplier_b = _make_ship(sim, b, fuel_units=100, name="SupplierB")
    b.market.place_sell_order(supplier_b, fuel, 50, 12)

    trader = _make_ship(sim, a, fuel_units=0, name="Trader")
    assert trader.brain._evaluate_trade_opportunity(a, b, food) is None

    # With round-trip fuel already on board, the same trade is feasible.
    trader.cargo.add_commodity(fuel, 20)
    assert trader.brain._evaluate_trade_opportunity(a, b, food) is not None


def test_fuel_safe_destination_requires_escape_route():
    sim, fuel, _, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    supplier = _make_ship(sim, a, fuel_units=100, name="Supplier")
    ship = _make_ship(sim, a, name="Trader")
    escape_cost = ship.fuel_required(Ship.calculate_distance(a, b))

    # No fuel for sale anywhere (early economy): the minimum requirement is
    # retaining the return leg.
    assert not ship.brain._fuel_safe_destination(b, a, escape_cost - 1)
    assert ship.brain._fuel_safe_destination(b, a, escape_cost)

    # Fuel for sale at A: B is safe only with enough fuel to get back to A.
    a.market.place_sell_order(supplier, fuel, 50, 10)
    assert not ship.brain._fuel_safe_destination(b, a, escape_cost - 1)
    assert ship.brain._fuel_safe_destination(b, a, escape_cost)

    # Fuel for sale at B itself: safe even when arriving empty.
    supplier_b = _make_ship(sim, b, fuel_units=100, name="SupplierB")
    b.market.place_sell_order(supplier_b, fuel, 50, 10)
    assert ship.brain._fuel_safe_destination(b, a, 0)


def test_decide_travel_avoids_fuel_dead_end():
    sim, fuel, food, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    # 8 fuel: enough for the outbound leg (5) but not the return leg after
    # arrival (3 left < 5 needed), so B is a dead end while no one sells fuel.
    ship = _make_ship(sim, a, fuel_units=8, name="Trader")
    ship.cargo.add_commodity(food, 20)
    buyer = _make_ship(sim, b, money=2000, name="Buyer")
    b.market.place_buy_order(buyer, food, 20, 30)

    # B pays well for the cargo but sells no fuel, and neither does A:
    # flying there would strand the ship.
    assert ship.brain.decide_travel() is None

    # Once fuel is for sale at B, the trip is safe.
    supplier_b = _make_ship(sim, b, fuel_units=100, name="SupplierB")
    b.market.place_sell_order(supplier_b, fuel, 50, 10)
    assert ship.brain.decide_travel() is b


def test_docked_ship_tops_up_toward_full_tank():
    sim, fuel, _, (a, _) = _make_world([("A", 0, 0), ("B", 100, 0)])
    supplier = _make_ship(sim, a, fuel_units=200, name="Supplier")
    a.market.place_sell_order(supplier, fuel, 100, 10)

    # 30/50 fuel is above the old 50% idle threshold; the ship should still
    # top up toward a full tank.
    ship = _make_ship(sim, a, fuel_units=30, name="Trader")
    ship.brain.decide_trade_actions()

    buys = [o for o in a.market.buy_orders[fuel] if o.actor is ship]
    assert len(buys) == 1
    assert buys[0].quantity == ship.fuel_capacity - 30

    a.market.match_orders()
    assert ship.cargo.get_quantity(fuel) == ship.fuel_capacity


def test_tank_fuel_is_not_trade_cargo_at_ordinary_prices():
    sim, fuel, _, (a, b) = _make_world([("A", 0, 0), ("B", 60, 0)])
    buyer = _make_ship(sim, b, money=2000, name="Buyer")
    # An ordinary low bid (below the scarcity floor of 15).
    b.market.place_buy_order(buyer, fuel, 20, 10)

    # A well-fueled ship with no delivery plan must not dump its tank into
    # the local bid (it would just re-buy at the ask later, bleeding the
    # spread) and must not post a standing bid either.
    ship = _make_ship(sim, b, fuel_units=40, name="Trader")
    ship.brain.decide_trade_actions()

    assert not any(o.actor is ship for o in b.market.sell_orders[fuel])
    assert not any(o.actor is ship for o in b.market.buy_orders[fuel])


def test_tank_fuel_sold_into_scarcity_bid():
    sim, fuel, _, (a, b) = _make_world([("A", 0, 0), ("B", 60, 0)])
    # A stranded neighbor's standing rescue bid, well above the floor.
    stranded = _make_ship(sim, b, fuel_units=0, money=2000, name="Stranded")
    b.market.place_buy_order(stranded, fuel, 20, 30)

    # A well-fueled ship on the same planet offloads its excess (keeping the
    # travel reserve) — same-planet ship-to-ship rescue.
    ship = _make_ship(sim, b, fuel_units=40, name="Trader")
    ship.brain.decide_trade_actions()

    sells = [o for o in b.market.sell_orders[fuel] if o.actor is ship]
    assert len(sells) == 1
    reserve = ship.brain._fuel_sell_reserve()
    assert reserve > 0
    assert sells[0].quantity == 40 - reserve


# ---------------------------------------------------------------------------
# Fix 3: standing fuel bids
# ---------------------------------------------------------------------------


def test_stranded_ship_posts_bid_profitable_for_deliverer():
    sim, fuel, _, (a, b) = _make_world([("A", 0, 0), ("B", 60, 0)])
    supplier = _make_ship(sim, a, fuel_units=200, name="Supplier")
    a.market.place_sell_order(supplier, fuel, 100, 10)

    stranded = _make_ship(sim, b, fuel_units=0, money=1000, name="Stranded")
    stranded.brain.decide_trade_actions()

    bids = [o for o in b.market.buy_orders[fuel] if o.actor is stranded]
    assert len(bids) == 1
    bid = bids[0]
    assert bid.quantity > 0
    assert bid.quantity <= stranded.fuel_capacity
    # Priced at least the source ask plus the delivery margin.
    assert bid.price >= math.ceil(10 * (1 + FUEL_BID_MARGIN))
    # Funds for the bid were reserved, not overspent.
    assert stranded.money >= 0
    assert stranded.reserved_money == bid.quantity * bid.price

    # Seller side: a trader on the fuel-rich planet sees the resting bid and
    # rates the delivery run as its best, profitable plan.
    deliverer = _make_ship(sim, a, fuel_units=30, money=1000, name="Deliverer")
    plan = deliverer.brain._find_best_trade_plan()
    assert plan is not None
    assert plan.commodity.id == "nova_fuel"
    assert plan.destination is b
    assert plan.is_profitable()


def test_standing_bid_fires_below_reserve_not_only_at_zero():
    sim, fuel, _, (a, b) = _make_world([("A", 0, 0), ("B", 60, 0)])
    supplier = _make_ship(sim, a, fuel_units=200, name="Supplier")
    a.market.place_sell_order(supplier, fuel, 100, 10)

    # Below the round-trip reserve (2 * fuel_required(60) = 6): bid fires.
    low = _make_ship(sim, b, fuel_units=2, money=1000, name="Low")
    low.brain.decide_trade_actions()
    assert any(o.actor is low for o in b.market.buy_orders[fuel])

    # Comfortably above the reserve: no bid.
    healthy = _make_ship(sim, b, fuel_units=30, money=1000, name="Healthy")
    healthy.brain.decide_trade_actions()
    assert not any(o.actor is healthy for o in b.market.buy_orders[fuel])


def test_standing_bid_reposts_and_escalates_when_unfilled():
    # No fuel ask anywhere in the galaxy: fallback pricing applies.
    sim, fuel, _, (_, b) = _make_world([("A", 0, 0), ("B", 60, 0)])
    stranded = _make_ship(sim, b, fuel_units=0, money=1000, name="Stranded")

    stranded.brain.decide_trade_actions()
    first = [o for o in b.market.buy_orders[fuel] if o.actor is stranded]
    assert len(first) == 1
    first_price = first[0].price

    # End of turn: the bid goes unfilled, scarcity pressure builds.
    b.market.match_orders()

    stranded.brain.decide_trade_actions()
    second = [o for o in b.market.buy_orders[fuel] if o.actor is stranded]
    assert len(second) == 1
    assert second[0].price > first_price


def test_deliverer_keeps_escape_fuel_when_selling():
    sim, fuel, _, (a, b) = _make_world([("A", 0, 0), ("B", 60, 0)])
    buyer = _make_ship(sim, b, money=2000, name="Buyer")
    b.market.place_buy_order(buyer, fuel, 40, 18)

    deliverer = _make_ship(sim, b, fuel_units=40, name="Deliverer")
    deliverer.brain._current_plan = TradePlan(
        origin=a,
        destination=b,
        commodity=fuel,
        quantity=34,
        purchase_price_per_unit=10,
        expected_sell_price_per_unit=18,
        distance=60.0,
        fuel_needed_one_way=3,
        fuel_price_at_origin=10,
    )
    deliverer.brain.decide_trade_actions()

    sells = [o for o in b.market.sell_orders[fuel] if o.actor is deliverer]
    assert len(sells) == 1
    reserve = deliverer.brain._fuel_sell_reserve()
    assert reserve > 0
    assert sells[0].quantity == 40 - reserve


# ---------------------------------------------------------------------------
# Deadlock fixes: stale-order cleanup, hold/travel consistency, maintenance
# rescue bids
# ---------------------------------------------------------------------------


def test_departure_cancels_resting_orders():
    """Departing must reclaim reserved cargo/money from unfilled local orders.

    Cancellation is local-market-only, so orders left behind imprison their
    reserves forever if the ship never returns (this deadlocked ships in
    needs_maintenance when the fuel they needed sat reserved in a stale ask).
    """
    sim, fuel, _, (a, b) = _make_world([("A", 0, 0), ("B", 50, 0)])
    ship = _make_ship(sim, a, fuel_units=10)
    a.market.place_sell_order(ship, fuel, 8, 99)
    assert ship.cargo.get_available_quantity(fuel) == 2  # below the 3 needed

    assert ship.start_journey(b)

    assert not a.market.sell_orders[fuel]
    assert ship.cargo.get_reserved_quantity(fuel) == 0
    assert ship.cargo.get_quantity(fuel) == 10 - 3


def test_sells_locally_when_better_price_is_fuel_unsafe():
    """A better price at a fuel dead end must not keep cargo on hold forever.

    decide_travel vetoes unsafe destinations, so if the hold decision does
    not apply the same veto the ship waits for a trip it never takes.
    """
    sim, fuel, food, (a, b) = _make_world([("A", 0, 0), ("B", 50, 0)])
    buyer = _make_ship(sim, a, money=2000, name="LocalBuyer")
    a.market.place_buy_order(buyer, food, 20, 10)
    remote_buyer = _make_ship(sim, b, money=5000, name="RemoteBuyer")
    b.market.place_buy_order(remote_buyer, food, 20, 100)

    # Exactly one-way fuel: B is reachable but leaves no escape route.
    ship = _make_ship(sim, a, fuel_units=3, name="Holder")
    ship.cargo.add_commodity(food, 10)

    ship.brain.decide_trade_actions()

    assert any(o.actor is ship for o in a.market.sell_orders[food])
    assert ship.brain.decide_travel() is None


def test_no_departure_same_turn_as_local_sell():
    """Once the brain commits to selling here, it must not depart this turn."""
    sim, fuel, food, (a, b) = _make_world([("A", 0, 0), ("B", 50, 0)])
    buyer = _make_ship(sim, a, money=2000, name="LocalBuyer")
    a.market.place_buy_order(buyer, food, 20, 10)
    remote_buyer = _make_ship(sim, b, money=5000, name="RemoteBuyer")
    # Only 10% better: not enough to hold, so the ship sells locally...
    b.market.place_buy_order(remote_buyer, food, 20, 11)

    ship = _make_ship(sim, a, fuel_units=10, name="Seller")
    ship.cargo.add_commodity(food, 10)

    ship.brain.decide_trade_actions()
    assert any(o.actor is ship for o in a.market.sell_orders[food])

    # ...and must not also fly to B, stranding the just-placed sell order.
    assert ship.brain.decide_travel() is None


def test_maintenance_standing_bid_when_no_asks():
    """A broken ship with no supplies for sale posts an escalating bid."""
    sim, fuel, _, (a, _) = _make_world([("A", 0, 0), ("B", 50, 0)])
    ship = _make_ship(sim, a, fuel_units=0, money=1000)
    ship.maintenance_needed = True

    ship._buy_maintenance_supplies()
    bids = [o for o in a.market.buy_orders[fuel] if o.actor is ship]
    assert len(bids) == 1
    assert bids[0].quantity == 5  # the full nova_fuel tier shortfall
    first_price = bids[0].price
    assert first_price >= 10

    # Unfilled at end of turn: scarcity pressure builds, the re-posted bid
    # escalates.
    a.market.match_orders()
    ship._buy_maintenance_supplies()
    bids = [o for o in a.market.buy_orders[fuel] if o.actor is ship]
    assert len(bids) == 1
    assert bids[0].price > first_price


def test_topup_rations_fuel_at_spike_prices():
    """A scarcity-priced local ask must not be lifted for a FULL tank.

    Ships that bunkered whole tanks at spike prices (40-85/unit) traded
    themselves broke; above the bunker ceiling only the survival target
    is bought.
    """
    sim, fuel, _, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    # Cheap fuel exists at B (galaxy reference ~10)...
    remote_supplier = _make_ship(sim, b, fuel_units=200, name="RemoteSupplier")
    b.market.place_sell_order(remote_supplier, fuel, 100, 10)
    # ...but the local ask at A is spike-priced.
    local_supplier = _make_ship(sim, a, fuel_units=200, name="LocalSupplier")
    a.market.place_sell_order(local_supplier, fuel, 100, 60)

    ship = _make_ship(sim, a, fuel_units=0, money=5000, name="Trader")
    ship.brain.decide_trade_actions()

    buys = [o for o in a.market.buy_orders[fuel] if o.actor is ship]
    assert len(buys) == 1
    # Only the survival target, nowhere near tank capacity.
    assert buys[0].quantity == ship.brain._fuel_survival_target()
    assert buys[0].quantity < ship.fuel_capacity // 2


def test_topup_bunkers_at_cheap_prices():
    """Near the galaxy reference price, the ship fills its tank."""
    sim, fuel, _, (a, _) = _make_world([("A", 0, 0), ("B", 100, 0)])
    supplier = _make_ship(sim, a, fuel_units=200, name="Supplier")
    a.market.place_sell_order(supplier, fuel, 100, 10)

    ship = _make_ship(sim, a, fuel_units=0, money=5000, name="Trader")
    ship.brain.decide_trade_actions()

    buys = [o for o in a.market.buy_orders[fuel] if o.actor is ship]
    assert len(buys) == 1
    assert buys[0].quantity == ship.fuel_capacity


def test_plan_quantity_capped_by_destination_bid_depth():
    """Plans must not buy more cargo than the destination book can absorb."""
    sim, fuel, food, (a, b) = _make_world([("A", 0, 0), ("B", 60, 0)])
    seller = _make_ship(sim, a, fuel_units=200, name="Seller")
    seller.cargo.add_commodity(food, 80)
    a.market.place_sell_order(seller, food, 80, 10)
    a.market.place_sell_order(seller, fuel, 50, 5)
    # Destination demand: only 7 units bid above cost.
    buyer = _make_ship(sim, b, money=2000, name="Buyer")
    b.market.place_buy_order(buyer, food, 7, 30)

    trader = _make_ship(sim, a, money=2000, name="Trader")
    plan = trader.brain._evaluate_trade_opportunity(a, b, food)

    assert plan is not None
    assert plan.quantity == 7
    assert plan.expected_sell_price_per_unit == 30


def test_plan_revenue_walks_the_bid_book():
    """Expected revenue uses each level's price, not top-of-book for all units."""
    sim, fuel, food, (a, b) = _make_world([("A", 0, 0), ("B", 60, 0)])
    seller = _make_ship(sim, a, fuel_units=200, name="Seller")
    seller.cargo.add_commodity(food, 80)
    a.market.place_sell_order(seller, food, 80, 10)
    a.market.place_sell_order(seller, fuel, 50, 5)
    buyer = _make_ship(sim, b, money=5000, name="Buyer")
    b.market.place_buy_order(buyer, food, 5, 40)
    b.market.place_buy_order(buyer, food, 10, 20)

    trader = _make_ship(sim, a, money=5000, name="Trader")
    plan = trader.brain._evaluate_trade_opportunity(a, b, food)

    assert plan is not None
    assert plan.quantity == 15
    # Weighted average of 5@40 + 10@20 = 400/15 = 26.67 -> floor 26.
    assert plan.expected_sell_price_per_unit == (5 * 40 + 10 * 20) // 15


def test_plan_prices_in_expected_maintenance():
    """Round-trip maintenance risk is part of the plan's cost side."""
    sim, fuel, food, (a, b) = _make_world([("A", 0, 0), ("B", 60, 0)])
    seller = _make_ship(sim, a, fuel_units=200, name="Seller")
    seller.cargo.add_commodity(food, 50)
    a.market.place_sell_order(seller, food, 50, 10)
    a.market.place_sell_order(seller, fuel, 50, 20)
    buyer = _make_ship(sim, b, money=5000, name="Buyer")
    b.market.place_buy_order(buyer, food, 20, 30)

    trader = _make_ship(sim, a, money=5000, name="Trader")
    plan = trader.brain._evaluate_trade_opportunity(a, b, food)

    assert plan is not None
    # 2 departures x 10% x 5 fuel units x fuel ask 20 = 20.
    assert plan.expected_maintenance_cost == 20
    assert (
        plan.expected_profit
        == plan.expected_revenue - plan.total_purchase_cost - plan.total_fuel_cost - 20
    )


def test_standing_fuel_bid_capped_at_survival_target():
    """Rescue bids ask for mobility, not a full tank of reserved money."""
    sim, fuel, _, (a, b) = _make_world([("A", 0, 0), ("B", 60, 0)])
    supplier = _make_ship(sim, a, fuel_units=200, name="Supplier")
    a.market.place_sell_order(supplier, fuel, 100, 10)

    stranded = _make_ship(sim, b, fuel_units=0, money=10000, name="Stranded")
    stranded.brain.decide_trade_actions()

    bids = [o for o in b.market.buy_orders[fuel] if o.actor is stranded]
    assert len(bids) == 1
    assert bids[0].quantity == stranded.brain._fuel_survival_target()
    assert bids[0].quantity < stranded.fuel_capacity


def test_maintenance_bids_prefer_produced_tiers_and_cover_all():
    """Standing maintenance bids cover every fundable tier, produced first.

    A ship that bid only on the cheapest tier (ship_components) sat dead for
    hundreds of turns with plenty of money because nobody in the galaxy made
    components; a simultaneous fuel-tier bid would have freed it.
    """
    sim, fuel, _, (a, _) = _make_world([("A", 0, 0), ("B", 50, 0)])
    registry = sim.commodity_registry
    components = CommodityDefinition(
        id="ship_components",
        name="Ship Components",
        transportable=True,
        description="Precision ship repair components.",
    )
    registry.add_commodity(components)
    # Fuel HAS traded here; components never traded anywhere.
    a.market.last_traded_prices[fuel] = [12]

    ship = _make_ship(sim, a, fuel_units=0, money=1000)
    ship.maintenance_needed = True
    ship._buy_maintenance_supplies()

    fuel_bids = [o for o in a.market.buy_orders[fuel] if o.actor is ship]
    comp_bids = [o for o in a.market.buy_orders[components] if o.actor is ship]
    assert len(fuel_bids) == 1
    assert fuel_bids[0].quantity == 5
    assert len(comp_bids) == 1
    assert comp_bids[0].quantity == 1
    # The produced (fuel) tier was funded first: with money to spare both
    # rest in the book, maximizing the chance one fills.


def test_survival_reposition_leaves_fuel_desert():
    """With no trades anywhere, a ship on a planet with no fuel supply flies
    to a planet where fuel is purchasable instead of idling into stranding."""
    sim, fuel, _, (desert, oasis) = _make_world([("A", 0, 0), ("B", 50, 0)])
    supplier = _make_ship(sim, oasis, fuel_units=100, name="Supplier")
    oasis.market.place_sell_order(supplier, fuel, 50, 12)

    ship = _make_ship(sim, desert, fuel_units=10, name="Idler")
    assert ship.brain.decide_travel() is oasis

    # Where fuel IS locally purchasable, idling is fine: stay put.
    desert.market.place_sell_order(
        _make_ship(sim, desert, fuel_units=20, name="LocalSupplier"), fuel, 10, 12
    )
    assert ship.brain.decide_travel() is None
