"""Tests for the ship fuel system.

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
from spacesim2.core.galaxy import StarLaneNetwork
from spacesim2.core.market import Market
from spacesim2.core.planet import Planet
from spacesim2.core.ship import (
    ACCUMULATION_PATIENCE,
    DISTRESS_PATIENCE,
    FUEL_BID_MARGIN,
    Ship,
    TradePlan,
)


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


# ---------------------------------------------------------------------------
# fuel_required matches consumption
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
    needed = ship.fuel_required(ship.route_distance(a, b))

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
    distance = trader.route_distance(a, b)
    assert plan.fuel_needed_one_way == trader.fuel_required(distance)
    assert plan.fuel_needed_one_way == 7  # ceil(ceil(100/20) / 0.8)


# ---------------------------------------------------------------------------
# Fuel-aware route planning
# ---------------------------------------------------------------------------


def test_plan_rejected_when_origin_cannot_sell_needed_fuel():
    sim, fuel, food, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    seller = _make_ship(sim, a, name="Seller")
    seller.cargo.add_commodity(food, 50)
    a.market.place_sell_order(seller, food, 50, 10)
    # Plans need visible profitable bids at the destination.
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
    escape_cost = ship.fuel_required(ship.route_distance(a, b))

    # No fuel for sale anywhere: the minimum requirement is keeping the
    # return leg.
    assert not ship.brain._fuel_safe_destination(b, a, escape_cost - 1)
    assert ship.brain._fuel_safe_destination(b, a, escape_cost)

    # Fuel for sale at A: B is safe only with enough fuel to get back to A.
    # Market facts are a per-turn shared snapshot, so tests that change the
    # books mid-turn refresh the navigator explicitly.
    a.market.place_sell_order(supplier, fuel, 50, 10)
    ship.brain._nav.refresh_market_facts()
    assert not ship.brain._fuel_safe_destination(b, a, escape_cost - 1)
    assert ship.brain._fuel_safe_destination(b, a, escape_cost)

    # Fuel for sale at B itself: safe even when arriving empty.
    supplier_b = _make_ship(sim, b, fuel_units=100, name="SupplierB")
    b.market.place_sell_order(supplier_b, fuel, 50, 10)
    ship.brain._nav.refresh_market_facts()
    assert ship.brain._fuel_safe_destination(b, a, 0)


def test_decide_travel_avoids_fuel_dead_end():
    sim, fuel, food, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    # 8 fuel covers the outbound leg of 5 but leaves 3, short of the 5 needed
    # to return, so B is a dead end while no one sells fuel.
    ship = _make_ship(sim, a, fuel_units=8, name="Trader")
    ship.cargo.add_commodity(food, 20)
    buyer = _make_ship(sim, b, money=2000, name="Buyer")
    b.market.place_buy_order(buyer, food, 20, 30)

    # B pays well for the cargo but neither planet sells fuel, so flying
    # there would strand the ship.
    assert ship.brain.decide_travel() is None

    # Once fuel is for sale at B, the trip is safe. Refresh the per-turn
    # snapshot so the mid-turn book change is visible now.
    supplier_b = _make_ship(sim, b, fuel_units=100, name="SupplierB")
    b.market.place_sell_order(supplier_b, fuel, 50, 10)
    ship.brain._nav.refresh_market_facts()
    assert ship.brain.decide_travel() is b


def test_docked_ship_tops_up_toward_full_tank():
    sim, fuel, _, (a, _) = _make_world([("A", 0, 0), ("B", 100, 0)])
    supplier = _make_ship(sim, a, fuel_units=200, name="Supplier")
    a.market.place_sell_order(supplier, fuel, 100, 10)

    # At 30/50 fuel the ship still tops up toward a full tank.
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
    # An ordinary low bid, below the scarcity floor of 15.
    b.market.place_buy_order(buyer, fuel, 20, 10)

    # A well-fueled ship with no delivery plan must not dump its tank into
    # the local bid, which would bleed the spread on the later re-buy, and
    # must not post a standing bid either.
    ship = _make_ship(sim, b, fuel_units=40, name="Trader")
    ship.brain.decide_trade_actions()

    assert not any(o.actor is ship for o in b.market.sell_orders[fuel])
    assert not any(o.actor is ship for o in b.market.buy_orders[fuel])


def test_tank_fuel_sold_into_scarcity_bid():
    sim, fuel, _, (a, b) = _make_world([("A", 0, 0), ("B", 60, 0)])
    # A stranded neighbor's standing rescue bid, well above the floor.
    stranded = _make_ship(sim, b, fuel_units=0, money=2000, name="Stranded")
    b.market.place_buy_order(stranded, fuel, 20, 30)

    # A well-fueled ship on the same planet offloads its excess above the
    # travel reserve: a same-planet ship-to-ship rescue.
    ship = _make_ship(sim, b, fuel_units=40, name="Trader")
    ship.brain.decide_trade_actions()

    sells = [o for o in b.market.sell_orders[fuel] if o.actor is ship]
    assert sells
    reserve = ship.brain._fuel_sell_reserve()
    assert reserve > 0
    # The load may be split across bid-level orders; the total is the excess
    # above the travel reserve, and every order sells into the rescue bid.
    assert sum(o.quantity for o in sells) == 40 - reserve
    assert all(o.price == 30 for o in sells)


# ---------------------------------------------------------------------------
# Standing fuel bids
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

    # A trader on the fuel-rich planet sees the resting bid and rates the
    # delivery run as its best, profitable plan. The stranded ship's decision
    # snapshotted the books before its bid was posted, so refresh to see it.
    deliverer = _make_ship(sim, a, fuel_units=30, money=1000, name="Deliverer")
    deliverer.brain._nav.refresh_market_facts()
    plan = deliverer.brain._find_best_trade_plan()
    assert plan is not None
    assert plan.commodity.id == "nova_fuel"
    assert plan.destination is b
    assert plan.is_profitable()


def test_standing_bid_fires_below_reserve_not_only_at_zero():
    sim, fuel, _, (a, b) = _make_world([("A", 0, 0), ("B", 60, 0)])
    supplier = _make_ship(sim, a, fuel_units=200, name="Supplier")
    a.market.place_sell_order(supplier, fuel, 100, 10)

    # Below the round-trip reserve of 2 * fuel_required(60) = 6, the bid fires.
    low = _make_ship(sim, b, fuel_units=2, money=1000, name="Low")
    low.brain.decide_trade_actions()
    assert any(o.actor is low for o in b.market.buy_orders[fuel])

    # Above the reserve: no bid.
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
    """Departing reclaims reserved cargo and money from unfilled local orders.

    Cancellation is local-market-only, so orders left behind hold their
    reserves forever if the ship never returns. Fuel reserved in a stale ask
    otherwise deadlocks a ship in needs_maintenance.
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
    """A better price at a fuel dead end does not keep cargo on hold forever.

    decide_travel vetoes unsafe destinations, so the hold decision must apply
    the same veto or the ship waits for a trip it never takes.
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
    """Once the brain commits to selling here, it does not depart this turn."""
    sim, fuel, food, (a, b) = _make_world([("A", 0, 0), ("B", 50, 0)])
    buyer = _make_ship(sim, a, money=2000, name="LocalBuyer")
    a.market.place_buy_order(buyer, food, 20, 10)
    remote_buyer = _make_ship(sim, b, money=5000, name="RemoteBuyer")
    # Only 10% better is not enough to hold, so the ship sells locally.
    b.market.place_buy_order(remote_buyer, food, 20, 11)

    ship = _make_ship(sim, a, fuel_units=10, name="Seller")
    ship.cargo.add_commodity(food, 10)

    ship.brain.decide_trade_actions()
    assert any(o.actor is ship for o in a.market.sell_orders[food])

    # It must not also fly to B and strand the just-placed sell order.
    assert ship.brain.decide_travel() is None


def test_maintenance_standing_bid_when_no_asks():
    """A broken ship with no supplies for sale posts an escalating bid."""
    sim, fuel, _, (a, _) = _make_world([("A", 0, 0), ("B", 50, 0)])
    ship = _make_ship(sim, a, fuel_units=0, money=1000)

    ship._buy_maintenance_supplies()
    bids = [o for o in a.market.buy_orders[fuel] if o.actor is ship]
    assert len(bids) == 1
    assert bids[0].quantity == 5  # the full nova_fuel tier shortfall
    first_price = bids[0].price
    assert first_price >= 10

    # Unfilled at end of turn: scarcity pressure builds and the re-posted bid
    # escalates.
    a.market.match_orders()
    ship._buy_maintenance_supplies()
    bids = [o for o in a.market.buy_orders[fuel] if o.actor is ship]
    assert len(bids) == 1
    assert bids[0].price > first_price


def test_topup_rations_fuel_at_spike_prices():
    """A scarcity-priced local ask is not lifted for a full tank.

    Above the bunker ceiling only the survival target is bought. Filling a
    whole tank at spike prices bankrupts ships.
    """
    sim, fuel, _, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    # Cheap fuel at B sets the galaxy reference near 10.
    remote_supplier = _make_ship(sim, b, fuel_units=200, name="RemoteSupplier")
    b.market.place_sell_order(remote_supplier, fuel, 100, 10)
    # The local ask at A is spike-priced.
    local_supplier = _make_ship(sim, a, fuel_units=200, name="LocalSupplier")
    a.market.place_sell_order(local_supplier, fuel, 100, 60)

    ship = _make_ship(sim, a, fuel_units=0, money=5000, name="Trader")
    ship.brain.decide_trade_actions()

    buys = [o for o in a.market.buy_orders[fuel] if o.actor is ship]
    assert len(buys) == 1
    # Only the survival target, well below tank capacity.
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
    """Plans buy no more cargo than the destination book can absorb."""
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
    """Round-trip maintenance risk is part of the plan's cost."""
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

    Bidding only on the cheapest tier leaves a ship dead when nobody makes
    that tier; a simultaneous fuel-tier bid frees it.
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
    # Fuel has traded here; components never traded anywhere.
    a.market.last_traded_prices[fuel] = [12]

    ship = _make_ship(sim, a, fuel_units=0, money=1000)
    ship._buy_maintenance_supplies()

    fuel_bids = [o for o in a.market.buy_orders[fuel] if o.actor is ship]
    comp_bids = [o for o in a.market.buy_orders[components] if o.actor is ship]
    assert len(fuel_bids) == 1
    assert fuel_bids[0].quantity == 5
    assert len(comp_bids) == 1
    assert comp_bids[0].quantity == 1
    # The produced fuel tier was funded first. With money to spare both rest
    # in the book, so either can fill.


def test_survival_reposition_leaves_fuel_desert():
    """With no trades anywhere, a ship in a fuel desert flies to a fuel source."""
    sim, fuel, _, (desert, oasis) = _make_world([("A", 0, 0), ("B", 50, 0)])
    supplier = _make_ship(sim, oasis, fuel_units=100, name="Supplier")
    oasis.market.place_sell_order(supplier, fuel, 50, 12)

    ship = _make_ship(sim, desert, fuel_units=10, name="Idler")
    assert ship.brain.decide_travel() is oasis

    # Where fuel is locally purchasable, idling is fine. Refresh the per-turn
    # snapshot to see the mid-turn book change.
    desert.market.place_sell_order(
        _make_ship(sim, desert, fuel_units=20, name="LocalSupplier"), fuel, 10, 12
    )
    ship.brain._nav.refresh_market_facts()
    assert ship.brain.decide_travel() is None


# ---------------------------------------------------------------------------
# Fuel availability is a live ask, not a memory of one
# ---------------------------------------------------------------------------


def _drain_fuel_ask(planet, fuel, supplier, buyer, quantity=20, price=10):
    """Trade ``quantity`` fuel at ``planet`` so volume is recorded and the ask goes."""
    planet.market.place_sell_order(supplier, fuel, quantity, price)
    planet.market.place_buy_order(buyer, fuel, quantity, price)
    planet.market.match_orders()


def test_fuel_not_purchasable_on_recent_volume_without_a_resting_ask():
    sim, fuel, _, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    supplier = _make_ship(sim, a, fuel_units=200, name="Supplier")
    buyer = _make_ship(sim, a, money=5000, name="Buyer")
    nav = _make_ship(sim, b, name="Observer").brain._nav

    _drain_fuel_ask(a, fuel, supplier, buyer)
    nav.refresh_market_facts()

    # The trade that shows in the volume window is the one that emptied the
    # book, so it says nothing about what an arriving ship could buy.
    assert a.market.get_bid_ask_spread(fuel)[1] is None
    assert nav.fuel_traded_recently(a)
    assert not nav.fuel_purchasable_at(a)

    # A live ask restores purchasability.
    a.market.place_sell_order(supplier, fuel, 5, 10)
    nav.refresh_market_facts()
    assert nav.fuel_purchasable_at(a)


def test_fuel_ask_depth_counts_resting_sell_quantity():
    sim, fuel, _, (a, _) = _make_world([("A", 0, 0), ("B", 100, 0)])
    supplier = _make_ship(sim, a, fuel_units=200, name="Supplier")
    nav = supplier.brain._nav

    assert nav.fuel_ask_depth_at(a) == 0
    a.market.place_sell_order(supplier, fuel, 3, 10)
    a.market.place_sell_order(supplier, fuel, 4, 12)
    nav.refresh_market_facts()
    assert nav.fuel_ask_depth_at(a) == 7


def test_fuel_safe_destination_requires_enough_ask_depth_to_leave_again():
    sim, fuel, _, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    supplier_a = _make_ship(sim, a, fuel_units=200, name="SupplierA")
    supplier_b = _make_ship(sim, b, fuel_units=200, name="SupplierB")
    ship = _make_ship(sim, a, name="Trader")
    escape_cost = ship.fuel_required(ship.route_distance(a, b))
    assert escape_cost == 5

    # A sells fuel, so leaving B again costs escape_cost. B's ask is a
    # single unit: a ship arriving dry could never buy its way out.
    a.market.place_sell_order(supplier_a, fuel, 50, 10)
    b.market.place_sell_order(supplier_b, fuel, 1, 10)
    ship.brain._nav.refresh_market_facts()
    assert not ship.brain._fuel_safe_destination(b, a, 0)
    assert not ship.brain._fuel_safe_destination(b, a, escape_cost - 2)

    # A shortfall the local book can actually cover is fine: one unit short
    # of the escape leg is one unit this market can sell.
    assert ship.brain._fuel_safe_destination(b, a, escape_cost - 1)

    # Arriving with the escape leg still aboard needs no local depth.
    assert ship.brain._fuel_safe_destination(b, a, escape_cost)

    # Enough depth to cover the whole shortfall makes B safe when dry.
    b.market.place_sell_order(supplier_b, fuel, escape_cost, 10)
    ship.brain._nav.refresh_market_facts()
    assert ship.brain._fuel_safe_destination(b, a, 0)


# ---------------------------------------------------------------------------
# Fuel upkeep runs whatever the plan state
# ---------------------------------------------------------------------------


def _accumulating_plan(ship, origin, destination, commodity, quantity=10):
    """Adopt a fresh, unloaded plan on ``ship`` as decide_trade_actions would."""
    distance = ship.route_distance(origin, destination)
    plan = TradePlan(
        origin=origin,
        destination=destination,
        commodity=commodity,
        quantity=quantity,
        purchase_price_per_unit=10,
        expected_sell_price_per_unit=30,
        distance=distance,
        fuel_needed_one_way=ship.fuel_required(distance),
        fuel_price_at_origin=10,
    )
    ship.brain._current_plan = plan
    ship.brain._plan_loaded = False
    ship.brain._plan_turns_left = ACCUMULATION_PATIENCE
    return plan


def test_accumulating_plan_still_posts_a_standing_fuel_bid():
    sim, fuel, food, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    seller = _make_ship(sim, a, name="Seller")
    seller.cargo.add_commodity(food, 50)
    a.market.place_sell_order(seller, food, 50, 10)

    ship = _make_ship(sim, a, fuel_units=2, name="Trader")
    _accumulating_plan(ship, a, b, food)
    assert ship.cargo.get_quantity(fuel) < ship.brain._fuel_reserve_need()

    ship.brain.decide_trade_actions()

    # Exactly one fuel bid: the upkeep owns the fuel side of the book, and
    # the plan's own fuel step stands down rather than double-buying.
    fuel_buys = [o for o in a.market.buy_orders[fuel] if o.actor is ship]
    assert len(fuel_buys) == 1
    assert fuel_buys[0].quantity > 0
    # The plan is still being worked: its cargo bid went in too.
    assert [o for o in a.market.buy_orders[food] if o.actor is ship]


def test_accumulating_plan_still_tops_up_from_a_local_ask():
    sim, fuel, food, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    supplier = _make_ship(sim, a, fuel_units=200, name="Supplier")
    a.market.place_sell_order(supplier, fuel, 100, 10)
    seller = _make_ship(sim, a, name="Seller")
    seller.cargo.add_commodity(food, 50)
    a.market.place_sell_order(seller, food, 50, 10)

    ship = _make_ship(sim, a, fuel_units=2, name="Trader")
    _accumulating_plan(ship, a, b, food)

    ship.brain.decide_trade_actions()

    fuel_buys = [o for o in a.market.buy_orders[fuel] if o.actor is ship]
    assert len(fuel_buys) == 1
    a.market.match_orders()
    assert ship.cargo.get_quantity(fuel) >= ship.brain._fuel_reserve_need()


def test_distress_is_not_blocked_by_a_plan_that_never_loads():
    sim, _, food, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    ship = _make_ship(sim, a, fuel_units=30, money=100, name="Trader")

    for _ in range(DISTRESS_PATIENCE):
        assert not ship.brain.is_distressed
        _accumulating_plan(ship, a, b, food)
        ship.brain.decide_trade_actions()

    assert ship.brain.is_distressed


# ---------------------------------------------------------------------------
# is_stranded
# ---------------------------------------------------------------------------


def test_is_stranded_true_when_docked_out_of_fuel_and_no_ask():
    sim, fuel, _food, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    ship = _make_ship(sim, a, fuel_units=0, name="Trader")

    assert ship.brain.is_stranded()


def test_is_stranded_false_once_fuel_exceeds_reserve():
    sim, fuel, _food, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    ship = _make_ship(sim, a, fuel_units=0, name="Trader")
    reserve = ship.brain._fuel_reserve_need()
    ship.cargo.add_commodity(fuel, reserve + 5)

    assert not ship.brain.is_stranded()
