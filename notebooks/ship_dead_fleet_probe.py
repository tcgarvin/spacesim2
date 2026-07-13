"""Diagnostic harness: why does the fleet freeze mid-run and never refuel?

Runs a live sim (like chem_score_probe), tracking per-turn galaxy fuel supply
and ship state; at the end dumps each ship's decision context and each
planet's fuel order book + production capability.

    uv run python notebooks/ship_dead_fleet_probe.py
"""

import contextlib
import io
from collections import Counter

from spacesim2.cli.common import create_and_setup_simulation
from spacesim2.core.actor import ActorType

TURNS = 600
PLANETS = 5
ACTORS = 50
SHIPS = 1  # per planet


def run() -> None:
    sim = create_and_setup_simulation(
        planets=PLANETS,
        actors=ACTORS,
        makers=2,
        ships=SHIPS,
        enable_planet_attributes=True,
    )
    fuel = sim.commodity_registry.get_commodity("nova_fuel")
    assert fuel is not None

    timeline = []  # (turn, n_asks_galaxy, min_ask, fleet_money, fleet_fuel, n_ship_bids)
    with contextlib.redirect_stdout(io.StringIO()):
        for t in range(TURNS):
            sim.run_turn()
            if t % 20 == 0 or t == TURNS - 1:
                n_asks = 0
                min_ask = None
                n_ship_bids = 0
                ship_bid_px = []
                for p in sim.planets:
                    for o in p.market.sell_orders.get(fuel, []):
                        n_asks += 1
                        if min_ask is None or o.price < min_ask:
                            min_ask = o.price
                    for o in p.market.buy_orders.get(fuel, []):
                        if o.actor in sim.ships:
                            n_ship_bids += 1
                            ship_bid_px.append(o.price)
                fleet_money = sum(s.money for s in sim.ships)
                fleet_fuel = sum(s.cargo.get_quantity(fuel) for s in sim.ships)
                timeline.append(
                    (
                        t,
                        n_asks,
                        min_ask,
                        fleet_money,
                        fleet_fuel,
                        n_ship_bids,
                        ship_bid_px,
                    )
                )

    print(
        "=== timeline: turn, galaxy fuel asks, min ask, fleet money, fleet fuel, ship bids ==="
    )
    for row in timeline:
        print(
            f"  t={row[0]:4d} asks={row[1]:2d} min_ask={row[2]!s:>5} "
            f"money={row[3]:6d} fuel={row[4]:3d} ship_bids={row[5]} px={row[6]}"
        )

    print("\n=== end-state ships ===")
    for s in sim.ships:
        planet = s.planet.name if s.planet else "IN TRANSIT"
        cargo = {c.id: q for c, q in s.cargo.commodities.items() if q > 0}
        print(
            f"  {s.name} at {planet} status={s.status.value} money={s.money} "
            f"reserved={s.reserved_money}"
        )
        print(f"      cargo={cargo}")
        print(f"      last_action={s.last_action}")
        if s.planet:
            reserve = s.brain._fuel_reserve_need()
            purch = s.brain._fuel_purchasable_at(s.planet)
            print(f"      fuel_reserve_need={reserve} local_fuel_purchasable={purch}")

    print("\n=== end-state fuel books & production per planet ===")
    for p in sim.planets:
        m = p.market
        bids = sorted(
            (
                (o.price, o.quantity, getattr(o.actor, "name", "?"))
                for o in m.buy_orders.get(fuel, [])
            ),
            reverse=True,
        )
        asks = sorted(
            (o.price, o.quantity, getattr(o.actor, "name", "?"))
            for o in m.sell_orders.get(fuel, [])
        )
        attr = p.attributes.nova_fuel_ore if p.attributes else None
        print(
            f"  {p.name}: ore_attr={attr} scarcity={m.scarcity_pressure_for(fuel):.2f} "
            f"avg_px={m.get_avg_price(fuel)}"
        )
        print(f"      bids={bids[:5]}")
        print(f"      asks={asks[:5]}")

    # who could produce fuel: chosen recipes across industrialists
    print("\n=== industrialist chosen recipes mentioning fuel ===")
    inds = [
        a
        for a in sim.actors
        if a.actor_type == ActorType.REGULAR
        and a.brain.__class__.__name__ == "IndustrialistBrain"
    ]
    chosen = Counter(
        (a.planet.name if a.planet else "?", str(a.brain.chosen_recipe_id))
        for a in inds
        if a.brain.chosen_recipe_id and "fuel" in str(a.brain.chosen_recipe_id)
    )
    for k, n in chosen.most_common():
        print(f"  {k} x{n}")
    if not chosen:
        print("  NONE — no industrialist anywhere has a fuel recipe chosen")
    # overall recipe distribution for context
    print("\n=== all chosen recipes (galaxy) ===")
    for rid, n in Counter(str(a.brain.chosen_recipe_id) for a in inds).most_common(12):
        print(f"  {rid:32} {n}")


if __name__ == "__main__":
    run()
