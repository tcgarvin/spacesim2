"""Tests for the fork-per-turn parallel actor phase (core/parallel.py)."""

import copy
import os
from collections import deque
from typing import Any

import pytest

from spacesim2.core.actor import Actor
from spacesim2.core.commodity import CommodityDefinition
from spacesim2.core.market import Market
from spacesim2.core.parallel import (
    apply_planet_states,
    extract_planet_states,
    snapshot_planet_states,
)
from spacesim2.core.planet import Planet
from spacesim2.core.ship import Ship
from spacesim2.core.simulation import Simulation


def _normalize(value: Any) -> Any:
    """Reduce live simulation state to a comparable value-form.

    Graph anchors become their stable ids so a deepcopied twin and the
    original can be compared; containers normalize recursively. Empty and
    zero-valued dict entries are dropped because defaultdict *reads* during
    a turn (e.g. scarcity_pressure_for) insert default entries on whichever
    sim happened to be read.
    """
    if isinstance(value, CommodityDefinition):
        return f"commodity:{value.id}"
    if isinstance(value, (Actor, Ship)):
        return f"participant:{value.name}"
    if isinstance(value, Planet):
        return f"planet:{value.name}"
    if isinstance(value, dict):
        out = {}
        for key, entry in value.items():
            normalized = _normalize(entry)
            if normalized == {} or normalized == []:
                continue
            if (
                isinstance(normalized, (int, float))
                and not isinstance(normalized, bool)
                and normalized == 0
            ):
                continue
            out[_normalize(key)] = normalized
        return out
    if isinstance(value, (list, tuple, deque)):
        return [_normalize(entry) for entry in value]
    if hasattr(value, "__dict__"):
        return {"__type__": type(value).__name__, **_normalize(vars(value))}
    return value


# Actor fields excluded from the state comparison: object-graph refs that are
# compared elsewhere or are per-turn scratch (the brain holds id()-keyed
# caches that are meaningless across copies).
_ACTOR_SKIP_FIELDS = {"sim", "planet", "brain", "drives", "inventory"}


def _actor_state(actor: Actor) -> Any:
    state = {
        name: _normalize(value)
        for name, value in vars(actor).items()
        if name not in _ACTOR_SKIP_FIELDS
    }
    state["inventory"] = _normalize(vars(actor.inventory))
    state["drive_metrics"] = [_normalize(vars(d.metrics)) for d in actor.drives]
    # Brains carry persistent decision memory (chosen recipe, learned price
    # brackets); only the _cache memoization scratch is per-turn.
    state["brain"] = _normalize(
        {k: v for k, v in vars(actor.brain).items() if k != "_cache"}
    )
    return state


def _market_state(market: Market, logged_names: frozenset[str] = frozenset()) -> Any:
    """Comparable market state.

    order_events_by_actor is filtered to logged actors: the sync manifest
    deliberately drops unlogged actors' events (they have no consumer), so
    only logged actors' deques are expected to match a serial twin.
    """
    state = {
        name: _normalize(value)
        for name, value in vars(market).items()
        if name not in ("commodity_registry", "order_events_by_actor")
    }
    state["order_events_by_actor"] = _normalize(
        {
            name: events
            for name, events in market.order_events_by_actor.items()
            if name in logged_names
        }
    )
    return state


def _make_sim(num_planets: int = 4) -> Simulation:
    sim = Simulation()
    sim.setup_simple(
        num_planets=num_planets,
        num_regular_actors=6,
        num_market_makers=1,
        num_ships=1,
    )
    return sim


def _begin_turn(sim: Simulation) -> None:
    """The run_turn preamble that precedes the actor phase."""
    sim.current_turn += 1
    sim.data_logger.set_turn(sim.current_turn)
    for planet in sim.planets:
        planet.market.set_current_turn(sim.current_turn)


def test_extract_apply_round_trip_covers_all_actor_phase_state() -> None:
    """apply(extract(twin)) must make the parent's state identical to the twin.

    A deepcopied twin runs its actor phase in-process; its extracted blob is
    applied onto the untouched original, and the original's live actor and
    market state must then match the twin's (normalized: commodities by id,
    participants by name). Any field mutated by Actor.take_turn but missing
    from the sync manifest shows up as a diff here.
    """
    sim = _make_sim()
    # Log a couple of actors so the DataLogger shard is exercised too.
    for actor in sim.planets[0].actors[:2]:
        sim.data_logger.add_actor_to_log(actor)
    for _ in range(3):  # warm the economy so books and drives have content
        sim.run_turn()

    twin = copy.deepcopy(sim)
    _begin_turn(sim)
    _begin_turn(twin)
    indices = list(range(len(twin.planets)))
    baseline = snapshot_planet_states(twin, indices)
    for actor in twin.actors:
        actor.take_turn()

    blob = extract_planet_states(twin, indices, baseline)
    apply_planet_states(sim, blob)

    logged = frozenset(sim.data_logger._actors_to_log)
    for planet, twin_planet in zip(sim.planets, twin.planets):
        for actor, twin_actor in zip(planet.actors, twin_planet.actors):
            assert actor.name == twin_actor.name
            assert _actor_state(actor) == _actor_state(twin_actor)
        assert _market_state(planet.market, logged) == _market_state(
            twin_planet.market, logged
        )

    # DataLogger shard came across for the logged actors.
    twin_keys = set(twin.data_logger._actor_turn_logs)
    assert set(sim.data_logger._actor_turn_logs) == twin_keys
    assert len(twin_keys) == 2


def test_restamped_orders_cross_as_bare_timestamps() -> None:
    """Kept orders (unchanged terms, refreshed timestamp) must use the
    compact {id: timestamp} wire path, not full order tuples, and must
    round-trip the refreshed timestamp exactly."""
    import io

    from spacesim2.core.parallel import _StateUnpickler

    sim = _make_sim()
    for _ in range(5):  # warm enough that brains keep standing orders
        sim.run_turn()

    twin = copy.deepcopy(sim)
    _begin_turn(sim)
    _begin_turn(twin)
    indices = list(range(len(twin.planets)))
    baseline = snapshot_planet_states(twin, indices)
    for actor in twin.actors:
        actor.take_turn()
    blob = extract_planet_states(twin, indices, baseline)

    payload = _StateUnpickler(io.BytesIO(blob), twin).load()
    all_restamped: dict[str, int] = {}
    for entry in payload:
        market_state = entry["market"]
        restamped = market_state["orders_restamped"]
        # The two paths are disjoint: a restamped order is by definition
        # not in orders_changed.
        assert not set(restamped) & set(market_state["orders_changed"])
        all_restamped.update(restamped)
    # Order-churn pruning keeps and restamps standing orders every turn in
    # a warmed economy; the compact path must actually be exercised.
    assert all_restamped
    assert all(ts == twin.current_turn for ts in all_restamped.values())

    apply_planet_states(sim, blob)
    for planet, twin_planet in zip(sim.planets, twin.planets):
        for order_id, twin_order in twin_planet.market.orders_by_id.items():
            assert planet.market.orders_by_id[order_id].timestamp == (
                twin_order.timestamp
            )


def test_unlogged_actor_events_do_not_cross() -> None:
    """Only logged actors' order events cross the sync boundary."""
    sim = _make_sim()
    logged_actor = sim.planets[0].actors[0]
    sim.data_logger.add_actor_to_log(logged_actor)
    for _ in range(3):
        sim.run_turn()

    twin = copy.deepcopy(sim)
    _begin_turn(sim)
    _begin_turn(twin)
    indices = list(range(len(twin.planets)))
    baseline = snapshot_planet_states(twin, indices)
    for actor in twin.actors:
        actor.take_turn()
    apply_planet_states(sim, extract_planet_states(twin, indices, baseline))

    turn = twin.current_turn
    twin_current = {
        name: [e for e in events if e.turn == turn]
        for planet in twin.planets
        for name, events in planet.market.order_events_by_actor.items()
    }
    # The twin's phase produced current-turn events for unlogged actors.
    assert any(
        events for name, events in twin_current.items() if name != logged_actor.name
    )
    for planet, twin_planet in zip(sim.planets, twin.planets):
        for name, events in planet.market.order_events_by_actor.items():
            current = [e for e in events if e.turn == turn]
            if name == logged_actor.name:
                twin_events = [
                    e
                    for e in twin_planet.market.order_events_by_actor[name]
                    if e.turn == turn
                ]
                assert len(current) == len(twin_events)
            else:
                assert current == []


def test_applied_orders_reference_parent_objects() -> None:
    """Orders coming back through a blob must point at the parent's actors
    and commodity definitions (identity, not copies)."""
    sim = _make_sim(num_planets=2)
    for _ in range(3):
        sim.run_turn()

    twin = copy.deepcopy(sim)
    _begin_turn(sim)
    _begin_turn(twin)
    baseline = snapshot_planet_states(twin, [0, 1])
    for actor in twin.actors:
        actor.take_turn()

    apply_planet_states(sim, extract_planet_states(twin, [0, 1], baseline))

    participants = set(map(id, sim.actors)) | set(map(id, sim.ships))
    commodities = set(map(id, sim.commodity_registry.all_commodities()))
    for planet in sim.planets:
        for order in planet.market.orders_by_id.values():
            assert id(order.actor) in participants
            assert id(order.commodity_type) in commodities
        for participant in planet.market.actor_orders:
            assert id(participant) in participants


@pytest.mark.skipif(os.name != "posix", reason="fork start method required")
def test_parallel_turns_run_and_preserve_invariants() -> None:
    sim = _make_sim(num_planets=4)
    sim.parallel_workers = 2
    turns = 10
    for _ in range(turns):
        sim.run_turn()
    assert sim.current_turn == turns

    seen_order_ids: set[str] = set()
    for planet in sim.planets:
        market = planet.market
        for book in (market.buy_orders, market.sell_orders):
            for orders in book.values():
                for order in orders:
                    assert order.order_id in market.orders_by_id
                    # Ids must be unique across all planets' books even
                    # though workers mint them independently.
                    assert order.order_id not in seen_order_ids
                    seen_order_ids.add(order.order_id)
        for actor in planet.actors:
            assert actor.money >= 0
            assert all(q >= 0 for q in actor.inventory.commodities.values())
            # Orders the actor believes are active exist in its market.
            for order_id in actor.active_orders:
                assert order_id in market.orders_by_id

    # The economy actually ran: actors acted and orders exist somewhere.
    assert any(a.last_action != "None" for a in sim.actors)
    assert seen_order_ids


@pytest.mark.skipif(os.name != "posix", reason="fork start method required")
def test_parallel_and_serial_paths_toggle_correctly() -> None:
    sim = _make_sim(num_planets=2)
    assert not sim._use_parallel_actor_phase()
    sim.parallel_workers = 4
    assert sim._use_parallel_actor_phase()
    single = _make_sim(num_planets=1)
    single.parallel_workers = 4
    assert not single._use_parallel_actor_phase()
