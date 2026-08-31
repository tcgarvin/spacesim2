"""Fork-per-turn parallel actor phase.

Design: docs/parallel-actor-phase.md. Workers are forked fresh each turn so
they inherit the whole object graph (object identity intact, no pickling of
inputs); only each planet's post-phase mutable state crosses back to the
parent, as a persistent-id pickle keyed by commodity ids and participant
names so it re-links to the parent's objects on load.
"""

import copy
import gc
import io
import itertools
import os
import pickle
import random
from collections import defaultdict, deque
from multiprocessing import get_context
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import spacesim2.core.market as market_module
from spacesim2.core.actor import Actor
from spacesim2.core.commodity import CommodityDefinition, CommodityRegistry
from spacesim2.core.data_logger import DataLogger
from spacesim2.core.planet import Planet
from spacesim2.core.process import ProcessDefinition, ProcessRegistry
from spacesim2.core.ship import Ship
from spacesim2.core.skill import SkillsRegistry

if TYPE_CHECKING:
    from spacesim2.core.simulation import Simulation

# Disjoint per-worker order-id ranges. A worker turn never places anywhere
# near this many orders, so ranges cannot collide within a turn, and the
# parent advances its counter past the union afterwards.
ORDER_ID_STRIDE = 10_000_000

# Set in the parent immediately before forking the pool; workers read it
# through the inherited address space (fork start method only).
_WORKER_SIM: Optional["Simulation"] = None


class _StatePickler(pickle.Pickler):
    """Externalizes graph anchors so blobs re-link to parent objects.

    Anything not listed pickles by value (Orders, OrderEvents, Commands,
    plain containers); one dumps() per shard lets the pickle memo preserve
    object sharing (e.g. the same Order in a book and an OrderEvent).
    """

    def persistent_id(self, obj: Any) -> Any:
        from spacesim2.core.simulation import Simulation

        if isinstance(obj, CommodityDefinition):
            return ("commodity", obj.id)
        if isinstance(obj, ProcessDefinition):
            return ("process", obj.id)
        if isinstance(obj, (Actor, Ship)):
            return ("participant", obj.name)
        if isinstance(obj, Planet):
            return ("planet", obj.name)
        if isinstance(obj, Simulation):
            return ("simulation",)
        if isinstance(obj, CommodityRegistry):
            return ("commodity_registry",)
        if isinstance(obj, ProcessRegistry):
            return ("process_registry",)
        if isinstance(obj, SkillsRegistry):
            return ("skills_registry",)
        if isinstance(obj, DataLogger):
            return ("data_logger",)
        return None


class _StateUnpickler(pickle.Unpickler):
    """Resolves persistent ids against the parent simulation's objects."""

    def __init__(self, file: io.BytesIO, sim: "Simulation") -> None:
        super().__init__(file)
        self._sim = sim
        self._participants: Dict[str, Any] = {a.name: a for a in sim.actors}
        self._participants.update({s.name: s for s in sim.ships})
        self._planets = {p.name: p for p in sim.planets}

    def persistent_load(self, pid: Any) -> Any:
        kind = pid[0]
        if kind == "commodity":
            commodity = self._sim.commodity_registry.get_commodity(pid[1])
            if commodity is None:
                raise pickle.UnpicklingError(f"Unknown commodity id: {pid[1]}")
            return commodity
        if kind == "process":
            process = self._sim.process_registry.get_process(pid[1])
            if process is None:
                raise pickle.UnpicklingError(f"Unknown process id: {pid[1]}")
            return process
        if kind == "participant":
            return self._participants[pid[1]]
        if kind == "planet":
            return self._planets[pid[1]]
        if kind == "simulation":
            return self._sim
        if kind == "commodity_registry":
            return self._sim.commodity_registry
        if kind == "process_registry":
            return self._sim.process_registry
        if kind == "skills_registry":
            return self._sim.skills_registry
        if kind == "data_logger":
            return self._sim.data_logger
        raise pickle.UnpicklingError(f"Unknown persistent id: {pid!r}")


def _actor_orders_factory() -> Dict[str, List[str]]:
    return {"buy": [], "sell": []}


# Compact wire form for Orders. Participants and commodities inside the
# tuples still go through the persistent-id pickler.
_OrderTuple = Tuple[str, Any, Any, int, int, bool, int, int]
_EventTuple = Tuple[str, str, str, int, _OrderTuple]


def _order_to_tuple(order: "market_module.Order") -> _OrderTuple:
    return (
        order.order_id,
        order.actor,
        order.commodity_type,
        order.quantity,
        order.price,
        order.is_buy,
        order.timestamp,
        order.created_turn,
    )


def _order_from_tuple(data: _OrderTuple) -> "market_module.Order":
    order_id, actor, commodity, quantity, price, is_buy, timestamp, created = data
    return market_module.Order(
        actor=actor,
        commodity_type=commodity,
        quantity=quantity,
        price=price,
        is_buy=is_buy,
        timestamp=timestamp,
        order_id=order_id,
        created_turn=created,
    )


def _event_to_tuple(event: "market_module.OrderEvent") -> _EventTuple:
    return (
        event.order_id,
        event.actor_name,
        event.event_type,
        event.turn,
        _order_to_tuple(event.order),
    )


def _current_turn_events(
    events: "deque[market_module.OrderEvent]", turn: int
) -> List[_EventTuple]:
    """This turn's events, scanning only the deque's fresh tail.

    Events append in turn order, so walking from the newest end and stopping
    at the first older event avoids touching (and COW-dirtying) the long
    retained history in every forked child.
    """
    tail = []
    for event in reversed(events):
        if event.turn != turn:
            break
        tail.append(_event_to_tuple(event))
    tail.reverse()
    return tail


def _extract_brain_state(actor: Actor) -> Dict[str, Any]:
    """The brain's persistent decision memory.

    Brains carry cross-turn state (an industrialist's chosen recipe, a
    market maker's learned price brackets and history cursor) that the
    actor phase mutates and later turns depend on. Omitting it silently
    resets every actor's strategy each turn — measured as a large
    macro-KPI regression before this was synced. Only the ``_cache``
    memoization scratch (rebuilt every actor-turn) is excluded.
    """
    return {k: v for k, v in vars(actor.brain).items() if k != "_cache"}


def _extract_actor_state(actor: Actor) -> Dict[str, Any]:
    """The per-actor sync manifest: every field Actor.take_turn can mutate."""
    return {
        "name": actor.name,
        "money": actor.money,
        "reserved_money": actor.reserved_money,
        "inv_commodities": dict(actor.inventory.commodities),
        "inv_reserved": dict(actor.inventory.reserved_commodities),
        "inv_version": actor.inventory.version,
        "skills": dict(actor.skills),
        "skills_version": actor.skills_version,
        "active_orders": dict(actor.active_orders),
        "market_history": list(actor.market_history),
        "food_consumed_this_turn": actor.food_consumed_this_turn,
        "last_action": actor.last_action,
        "last_market_action": actor.last_market_action,
        "drive_metrics": [dict(vars(d.metrics)) for d in actor.drives],
    }


def snapshot_planet_states(
    sim: "Simulation", planet_indices: List[int]
) -> Dict[int, Dict[str, Any]]:
    """Pre-phase baseline for delta extraction.

    Taken in the forked child *before* running any actor turn, so it is by
    construction identical to the state the parent still holds — everything
    that compares equal to it can be omitted from the blob and the parent's
    copy left untouched.
    """
    baseline: Dict[int, Dict[str, Any]] = {}
    for index in planet_indices:
        market = sim.planets[index].market
        baseline[index] = {
            "actors": [_extract_actor_state(a) for a in sim.planets[index].actors],
            # Deep-copied because brain state (e.g. MarketMakerState) is
            # mutated in place during the phase.
            "brains": [
                copy.deepcopy(_extract_brain_state(a))
                for a in sim.planets[index].actors
            ],
            "orders": {
                order_id: (o.quantity, o.price, o.timestamp)
                for order_id, o in market.orders_by_id.items()
            },
            "actor_orders": {
                p: (tuple(v["buy"]), tuple(v["sell"]))
                for p, v in market.actor_orders.items()
            },
        }
    return baseline


def _extract_market_state(
    market: "market_module.Market", base: Dict[str, Any]
) -> Dict[str, Any]:
    """The per-market sync manifest: state mutated by place/cancel/modify.

    Match-time-only state (price/volume/transaction history, scarcity
    pressure) is deliberately absent: matching runs parent-side after the
    ship phase. Books cross as id sequences plus compact tuples for only
    the new/changed orders; the parent reuses its own Order objects for
    unchanged ids and rebuilds orders_by_id from the books (place/cancel/
    match maintain the two in lockstep).
    """
    base_orders: Dict[str, Tuple[int, int, int]] = base["orders"]
    changed: Dict[str, _OrderTuple] = {}

    def book_ids(
        book: Dict[CommodityDefinition, List["market_module.Order"]],
    ) -> Dict[CommodityDefinition, List[str]]:
        wire: Dict[CommodityDefinition, List[str]] = {}
        for commodity, orders in book.items():
            ids = []
            for order in orders:
                ids.append(order.order_id)
                before = base_orders.get(order.order_id)
                if before is None or before != (
                    order.quantity,
                    order.price,
                    order.timestamp,
                ):
                    changed[order.order_id] = _order_to_tuple(order)
            wire[commodity] = ids
        return wire

    base_actor_orders: Dict[Any, Tuple[Tuple[str, ...], Tuple[str, ...]]]
    base_actor_orders = base["actor_orders"]
    return {
        "buy_books": book_ids(market.buy_orders),
        "sell_books": book_ids(market.sell_orders),
        "orders_changed": changed,
        "actor_orders": {
            participant: {"buy": list(v["buy"]), "sell": list(v["sell"])}
            for participant, v in market.actor_orders.items()
            if base_actor_orders.get(participant) != (tuple(v["buy"]), tuple(v["sell"]))
        },
        # Only this turn's events cross the boundary: the forked child and
        # the parent share all older events already, so the parent appends
        # these to its own deques (identical eviction on both sides). The
        # full deques are by far the heaviest state (~75% of a naive blob).
        "order_events": {
            name: current
            for name, events in market.order_events_by_actor.items()
            if (current := _current_turn_events(events, market.current_turn))
        },
        "quote_cache": dict(market._quote_cache),
        "bid_levels_cache": {
            c: list(levels) for c, levels in market._bid_levels_cache.items()
        },
        "drive_anchor_cache": dict(market.drive_anchor_cache),
    }


def extract_planet_states(
    sim: "Simulation",
    planet_indices: List[int],
    baseline: Dict[int, Dict[str, Any]],
) -> bytes:
    """Serialize what the actor phase changed on the given planets.

    ``baseline`` must be a snapshot_planet_states() result taken before the
    phase ran; per-actor entries carry only the fields that differ from it.
    """
    payload = []
    for index in planet_indices:
        planet = sim.planets[index]
        base = baseline[index]
        actor_deltas = []
        for actor, before, brain_before in zip(
            planet.actors, base["actors"], base["brains"]
        ):
            after = _extract_actor_state(actor)
            delta = {k: v for k, v in after.items() if v != before[k]}
            brain_after = _extract_brain_state(actor)
            if brain_after != brain_before:
                delta["brain_state"] = brain_after
            # Inventories are the largest per-actor payload but usually only
            # a few slots move per turn — send per-key changes plus the
            # child's full key order. The order matters: brains iterate
            # these dicts, and a dict patched in place ends up ordered
            # differently than the child's (a slot emptied and re-acquired
            # moves to the end), which measurably steers later decisions.
            for key in ("inv_commodities", "inv_reserved"):
                if key in delta:
                    old = before[key]
                    new = delta.pop(key)
                    delta[key + "_delta"] = (
                        {c: q for c, q in new.items() if old.get(c) != q},
                        list(new),
                    )
            actor_deltas.append(delta)
        log_shard = {}
        for actor in planet.actors:
            key = f"actor-{actor.name}"
            if key in sim.data_logger._actor_turn_logs:
                log_shard[key] = sim.data_logger._actor_turn_logs[key]
        payload.append(
            {
                "planet_index": index,
                "actors": actor_deltas,
                "market": _extract_market_state(planet.market, base),
                "logs": log_shard,
            }
        )
    buffer = io.BytesIO()
    _StatePickler(buffer, protocol=pickle.HIGHEST_PROTOCOL).dump(payload)
    return buffer.getvalue()


# Delta keys applied as plain attribute assignments on the actor.
_ACTOR_PLAIN_FIELDS = frozenset(
    {
        "money",
        "reserved_money",
        "skills",
        "skills_version",
        "active_orders",
        "market_history",
        "food_consumed_this_turn",
        "last_action",
        "last_market_action",
    }
)


def _apply_actor_state(actor: Actor, state: Dict[str, Any]) -> None:
    """Apply a (possibly partial) per-actor delta."""
    for key, value in state.items():
        if key in _ACTOR_PLAIN_FIELDS:
            setattr(actor, key, value)
        elif key == "inv_commodities_delta":
            changed, key_order = value
            old = actor.inventory.commodities
            actor.inventory.commodities = {
                c: changed[c] if c in changed else old[c] for c in key_order
            }
        elif key == "inv_reserved_delta":
            changed, key_order = value
            old = actor.inventory.reserved_commodities
            actor.inventory.reserved_commodities = {
                c: changed[c] if c in changed else old[c] for c in key_order
            }
        elif key == "inv_version":
            actor.inventory.version = value
        elif key == "brain_state":
            for field_name, field_value in value.items():
                setattr(actor.brain, field_name, field_value)
        elif key == "drive_metrics":
            if len(value) != len(actor.drives):
                raise ValueError(f"Drive count mismatch for actor {actor.name}")
            for drive, metric_values in zip(actor.drives, value):
                for field_name, metric in metric_values.items():
                    setattr(drive.metrics, field_name, metric)
        elif key == "name":
            if actor.name != value:
                raise ValueError(f"Actor state mismatch: {actor.name} != {value}")
        else:
            raise ValueError(f"Unknown actor delta field: {key}")


def _apply_market_state(market: "market_module.Market", state: Dict[str, Any]) -> None:
    old_orders = market.orders_by_id
    changed: Dict[str, _OrderTuple] = state["orders_changed"]
    orders_by_id: Dict[str, market_module.Order] = {}

    def rebuild_book(
        wire: Dict[CommodityDefinition, List[str]],
    ) -> Dict[CommodityDefinition, List[market_module.Order]]:
        book: Dict[CommodityDefinition, List[market_module.Order]]
        book = defaultdict(list)
        for commodity, order_ids in wire.items():
            orders = []
            for order_id in order_ids:
                order = old_orders.get(order_id)
                if order is None:
                    order = _order_from_tuple(changed[order_id])
                elif order_id in changed:
                    # Modified in place (modify_order semantics) so any
                    # older reference to this order sees the new terms.
                    _, _, _, quantity, price, _, timestamp, _ = changed[order_id]
                    order.quantity = quantity
                    order.price = price
                    order.timestamp = timestamp
                orders.append(order)
                orders_by_id[order.order_id] = order
            book[commodity] = orders
        return book

    market.buy_orders = rebuild_book(state["buy_books"])
    market.sell_orders = rebuild_book(state["sell_books"])
    market.orders_by_id = orders_by_id

    # Partial update: only participants whose id lists changed were sent.
    market.actor_orders.update(state["actor_orders"])

    # Append this turn's events onto the deques the parent already holds;
    # the pre-turn contents are identical on both sides of the fork, and
    # the bounded deques evict the same oldest entries either way. An
    # event's order re-links to the live book Order when it still rests
    # there (a "created" that survived), else it becomes a detached copy.
    for name, event_tuples in state["order_events"].items():
        events = market.order_events_by_actor[name]
        for order_id, actor_name, event_type, turn, order_tuple in event_tuples:
            order = orders_by_id.get(order_id)
            if order is None:
                order = _order_from_tuple(order_tuple)
            events.append(
                market_module.OrderEvent(
                    order_id=order_id,
                    actor_name=actor_name,
                    event_type=event_type,
                    turn=turn,
                    order=order,
                )
            )

    market._quote_cache = state["quote_cache"]
    market._bid_levels_cache = state["bid_levels_cache"]
    market.drive_anchor_cache = state["drive_anchor_cache"]


def apply_planet_states(sim: "Simulation", blob: bytes) -> None:
    """Apply a worker's per-planet state blob onto the parent simulation."""
    payload = _StateUnpickler(io.BytesIO(blob), sim).load()
    for entry in payload:
        planet = sim.planets[entry["planet_index"]]
        actor_states: List[Dict[str, Any]] = entry["actors"]
        if len(actor_states) != len(planet.actors):
            raise ValueError(f"Actor count mismatch for planet {planet.name}")
        for actor, state in zip(planet.actors, actor_states):
            _apply_actor_state(actor, state)
        _apply_market_state(planet.market, entry["market"])
        sim.data_logger._actor_turn_logs.update(entry["logs"])


def _warm_shared_caches(sim: "Simulation") -> None:
    """Populate lazily built read-only caches before forking.

    Without this, each child would build its own copy (wasted work) and the
    parent's copy would stay cold.
    """
    for commodity in sim.commodity_registry.all_commodities():
        sim.process_registry.get_processes_producing(commodity)


def _run_shard(task: Tuple[int, int, List[int]]) -> bytes:
    """Worker: run the actor phase for a shard of planets, return the blob."""
    shard_index, id_base, planet_indices = task
    sim = _WORKER_SIM
    if sim is None:
        raise RuntimeError("_run_shard called without a forked simulation")
    # The child is short-lived and its heap is mostly the parent's frozen
    # graph; letting cyclic GC run would COW-dirty huge swaths of inherited
    # pages for no benefit.
    gc.disable()
    # Every forked child inherits the parent's RNG state; without reseeding
    # all workers would draw identical streams.
    random.seed(os.urandom(16))
    # Disjoint order-id range per shard so ids stay unique across workers.
    market_module._ORDER_ID_COUNTER = itertools.count(
        id_base + shard_index * ORDER_ID_STRIDE
    )
    baseline = snapshot_planet_states(sim, planet_indices)
    for index in planet_indices:
        planet = sim.planets[index]
        actors = list(planet.actors)
        random.shuffle(actors)
        for actor in actors:
            actor.take_turn()
    return extract_planet_states(sim, planet_indices, baseline)


def run_actor_phase_parallel(sim: "Simulation", workers: int) -> None:
    """Run every planet's actor turns across a fork-per-turn worker pool.

    Must be called at the point run_turn would otherwise run its serial
    actor loop (after set_turn/set_current_turn, before the ship phase).
    POSIX-only (requires the fork start method).
    """
    global _WORKER_SIM
    num_planets = len(sim.planets)
    workers = min(workers, num_planets)
    if workers <= 1:
        raise ValueError("run_actor_phase_parallel requires workers >= 2")
    _warm_shared_caches(sim)
    # Workers iterate planet.actors; an actor registered on the sim but not
    # on its planet would silently never act again.
    if sum(len(p.actors) for p in sim.planets) != len(sim.actors):
        raise RuntimeError(
            "planet.actors does not cover sim.actors; cannot shard the "
            "actor phase by planet"
        )
    id_base = next(market_module._ORDER_ID_COUNTER) + 1
    shards = [
        (k, id_base, list(range(k, num_planets, workers))) for k in range(workers)
    ]
    _WORKER_SIM = sim
    # Freezing moves the (large, mostly static) object graph out of the GC
    # generations for the duration of the fork, so neither a parent
    # collection during the map nor anything in the children walks — and
    # thereby COW-copies — the whole inherited heap.
    gc.freeze()
    try:
        context = get_context("fork")
        # The `with` block exits via Pool.terminate(): workers are killed by
        # SIGTERM after returning their results, so a child never runs
        # interpreter shutdown — critical when an exporter holds open
        # Parquet writers, whose __del__ would otherwise write a footer to
        # the shared file descriptor from inside the child.
        with context.Pool(processes=workers) as pool:
            blobs = pool.map(_run_shard, shards)
    finally:
        _WORKER_SIM = None
        gc.unfreeze()
    for blob in blobs:
        apply_planet_states(sim, blob)
    market_module._ORDER_ID_COUNTER = itertools.count(
        id_base + workers * ORDER_ID_STRIDE
    )
