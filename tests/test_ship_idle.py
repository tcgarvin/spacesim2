"""Tests for the idle-ship livelock fixes in ``TraderBrain``.

Two mechanisms used to keep a ship with cargo docked forever:

- the "selling locally" travel veto, which was meant to protect the sell
  orders placed this turn but never expired, and
- the hold-or-sell comparison judging destinations on the fuel in the tank
  alone, which rejected almost every destination for a ship running near its
  survival fuel target.
"""

from tests.test_ship_fuel import _make_ship, _make_world

# ---------------------------------------------------------------------------
# The local-sale veto lasts one turn
# ---------------------------------------------------------------------------


def test_local_sale_veto_lifts_after_an_unfilled_turn():
    """Asks that sat a whole turn untouched stop pinning the ship in place."""
    sim, _fuel, food, (a, b) = _make_world([("A", 0, 0), ("B", 50, 0)])
    buyer = _make_ship(sim, a, money=2000, name="LocalBuyer")
    a.market.place_buy_order(buyer, food, 20, 10)
    remote_buyer = _make_ship(sim, b, money=5000, name="RemoteBuyer")
    # Only 10% better, so the hold-or-sell test lists the cargo here, but
    # decide_travel's own comparison still nets out in B's favor.
    b.market.place_buy_order(remote_buyer, food, 20, 11)

    ship = _make_ship(sim, a, fuel_units=10, name="Seller")
    ship.cargo.add_commodity(food, 10)

    # Turn 1: the sale is fresh, so the ship stays to see it fill.
    ship.brain.decide_trade_actions()
    assert any(o.actor is ship for o in a.market.sell_orders[food])
    assert ship.brain.decide_travel() is None

    # Turn 2, with nothing matched in between: the ask went a full turn
    # unfilled, so it no longer earns the ship's patience.
    ship.brain.decide_trade_actions()
    assert ship.brain._local_sale_stale
    assert ship.brain.decide_travel() is b


def test_local_sale_veto_returns_after_a_fill():
    """A sale that actually fills restarts the one-turn grace period."""
    sim, _fuel, food, (a, b) = _make_world([("A", 0, 0), ("B", 50, 0)])
    buyer = _make_ship(sim, a, money=2000, name="LocalBuyer")
    a.market.place_buy_order(buyer, food, 4, 10)  # takes part of the load
    remote_buyer = _make_ship(sim, b, money=5000, name="RemoteBuyer")
    b.market.place_buy_order(remote_buyer, food, 20, 11)

    ship = _make_ship(sim, a, fuel_units=10, name="Seller")
    ship.cargo.add_commodity(food, 10)

    ship.brain.decide_trade_actions()
    a.market.match_orders()
    assert 0 < ship.cargo.get_quantity(food) < 10

    ship.brain.decide_trade_actions()
    assert not ship.brain._local_sale_stale
    assert ship.brain.decide_travel() is None


def test_stale_local_sale_allows_replanning():
    """Cargo nobody will buy no longer blocks adopting a new trade plan."""
    sim, fuel, food, (a, b) = _make_world([("A", 0, 0), ("B", 50, 0)])
    # Food is for sale at A and pays well at B: a plan exists to be found.
    seller = _make_ship(sim, a, fuel_units=200, name="Seller")
    seller.cargo.add_commodity(food, 50)
    a.market.place_sell_order(seller, food, 50, 10)
    a.market.place_sell_order(seller, fuel, 100, 5)
    buyer_b = _make_ship(sim, b, money=9000, name="BuyerB")
    b.market.place_buy_order(buyer_b, food, 50, 40)

    # The trader holds a load of an unrelated good with only a lowball local
    # bid and no demand anywhere, so it lists it here and it never fills.
    junk = sim.commodity_registry.get_commodity("food")
    ship = _make_ship(sim, a, fuel_units=20, money=4000, name="Trader")
    ship.cargo.add_commodity(junk, 5)

    ship.brain.decide_trade_actions()
    ship.brain.decide_trade_actions()

    assert ship.brain._local_sale_stale
    assert ship.brain._current_plan is not None
    assert ship.brain._current_plan.destination is b


# ---------------------------------------------------------------------------
# Reachability counts fuel the ship could buy here
# ---------------------------------------------------------------------------


def test_hold_considers_destinations_reachable_on_purchasable_fuel():
    """A destination out of reach on tank fuel alone still counts if fuel sells here."""
    sim, fuel, food, (a, _b, c) = _make_world(
        [("A", 0, 0), ("B", 20, 0), ("C", 200, 0)]
    )
    # Fuel is for sale at both ends, so C is never a fuel dead end.
    supplier_a = _make_ship(sim, a, fuel_units=400, name="SupplierA")
    a.market.place_sell_order(supplier_a, fuel, 200, 5)
    supplier_c = _make_ship(sim, c, fuel_units=400, name="SupplierC")
    c.market.place_sell_order(supplier_c, fuel, 200, 5)

    local_buyer = _make_ship(sim, a, money=2000, name="LocalBuyer")
    a.market.place_buy_order(local_buyer, food, 20, 10)
    remote_buyer = _make_ship(sim, c, money=20000, name="RemoteBuyer")
    c.market.place_buy_order(remote_buyer, food, 20, 100)

    ship = _make_ship(sim, a, fuel_units=5, money=2000, name="Holder")
    ship.cargo.add_commodity(food, 10)
    leg = ship.fuel_required(ship.route_distance(a, c))
    assert leg > 5  # out of reach on what is in the tank

    ship.brain.decide_trade_actions()

    # It holds the cargo for C instead of dumping it into the local book...
    assert not any(o.actor is ship for o in a.market.sell_orders[food])
    assert ship.brain._committed_fuel_need == leg
    # ...and buys enough fuel to actually fly there.
    bought = sum(o.quantity for o in a.market.buy_orders[fuel] if o.actor is ship)
    assert ship.cargo.get_quantity(fuel) + bought >= leg


def test_committed_destination_fuel_is_bought_at_spike_prices():
    """Fuel for a committed profitable trip is not speculative bunkering."""
    sim, fuel, _food, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    # Cheap fuel at B sets the galaxy reference near 10; the local ask spikes.
    remote_supplier = _make_ship(sim, b, fuel_units=200, name="RemoteSupplier")
    b.market.place_sell_order(remote_supplier, fuel, 100, 10)
    local_supplier = _make_ship(sim, a, fuel_units=200, name="LocalSupplier")
    a.market.place_sell_order(local_supplier, fuel, 100, 60)

    ship = _make_ship(sim, a, fuel_units=0, money=5000, name="Trader")
    committed = ship.brain._fuel_survival_target() + 3
    ship.brain._committed_fuel_need = committed
    ship.brain._committed_fuel_planet = a

    assert ship.brain._opportunistic_fuel_topup() is not None
    buys = [o for o in a.market.buy_orders[fuel] if o.actor is ship]
    assert len(buys) == 1
    assert buys[0].quantity == committed


def test_committed_fuel_need_ignored_at_another_planet():
    """A commitment made at one planet does not inflate the tank target elsewhere."""
    sim, fuel, _food, (a, b) = _make_world([("A", 0, 0), ("B", 100, 0)])
    remote_supplier = _make_ship(sim, b, fuel_units=200, name="RemoteSupplier")
    b.market.place_sell_order(remote_supplier, fuel, 100, 10)
    local_supplier = _make_ship(sim, a, fuel_units=200, name="LocalSupplier")
    a.market.place_sell_order(local_supplier, fuel, 100, 60)

    ship = _make_ship(sim, a, fuel_units=0, money=5000, name="Trader")
    ship.brain._committed_fuel_need = ship.brain._fuel_survival_target() + 3
    ship.brain._committed_fuel_planet = b  # made at the other planet

    assert ship.brain._opportunistic_fuel_topup() is not None
    buys = [o for o in a.market.buy_orders[fuel] if o.actor is ship]
    assert buys[0].quantity == ship.brain._fuel_survival_target()
