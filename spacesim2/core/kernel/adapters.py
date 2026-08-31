"""Python-side bridge between live simulation objects and the kernel.

The kernel compute functions (``backend_py``) accept only plain data; this
module builds that data from real ``Actor``/``Market``/registry objects and
owns the caching/invalidation policy:

* :class:`EconomyTable` — built once per registry pair, cached weakly and
  invalidated by identity of the registries' shared ``all_*()`` lists.
* :class:`PlanetSnapshot` — per (market, turn), stored on the market itself so
  it stays planet-sharded under the threaded actor phase. Holds only fields
  that cannot move intra-turn (avg price, price signal, planet attributes).
* :class:`Quotes` — live top-of-book, built at kernel-invocation time (brains
  may hold one for at most a single actor-turn via ``BrainCache``, matching
  the legacy per-actor-turn quote memo; books never move within one
  actor-turn because command execution happens outside ``decide_*``).
* :class:`ActorPack` — per-actor vectors, rebuilt whenever ``BrainCache``
  detects an inventory/skills change.

``try_context`` is also the kernel/legacy dispatch gate: brains fall back to
the legacy implementations when handed anything but real simulation objects
(unit tests drive brains with ``Mock`` doubles whose duck-typing the
flattening step cannot honor). The checks are exact-type on purpose —
``Mock(spec=X)`` passes ``isinstance``.
"""

from __future__ import annotations

import weakref
from typing import TYPE_CHECKING, Optional, Tuple

from spacesim2.core.commodity import CommodityRegistry, Inventory
from spacesim2.core.kernel.table import (
    ActorPack,
    EconomyTable,
    PlanetSnapshot,
    Quotes,
    build_economy_table,
)
from spacesim2.core.market import Market
from spacesim2.core.planet_attributes import PlanetAttributes
from spacesim2.core.process import ProcessRegistry

if TYPE_CHECKING:
    from spacesim2.core.actor import Actor
    from spacesim2.core.planet import Planet

# One table per process registry. Weak keys so short-lived test simulations
# don't accumulate; a stale table (registry reloaded) is detected by identity
# of the registries' shared list objects and rebuilt.
_TABLES: "weakref.WeakKeyDictionary[ProcessRegistry, EconomyTable]" = (
    weakref.WeakKeyDictionary()
)


def get_table(
    process_registry: ProcessRegistry, commodity_registry: CommodityRegistry
) -> EconomyTable:
    """The cached :class:`EconomyTable` for a registry pair, rebuilt on change."""
    processes = process_registry.all_processes()
    commodities = commodity_registry.all_commodities()
    table = _TABLES.get(process_registry)
    if (
        table is not None
        and table.source_processes is processes
        and table.source_commodities is commodities
    ):
        return table
    table = build_economy_table(process_registry, commodity_registry)
    _TABLES[process_registry] = table
    return table


def get_snapshot(
    table: EconomyTable, market: Market, planet: "Planet"
) -> PlanetSnapshot:
    """The per-(market, turn) snapshot, built at most once per planet-turn.

    ``avg_price``/``has_signal`` change only during end-of-turn matching and
    planet attributes are run-constant, so caching per (market, turn) is
    exact. Keyed on ``market.current_turn`` like ``drive_anchor_cache``.
    """
    snapshot = market.kernel_snapshot
    if (
        snapshot is not None
        and snapshot.turn == market.current_turn
        and snapshot.table is table
    ):
        return snapshot
    attributes = planet.attributes
    snapshot = PlanetSnapshot(
        turn=market.current_turn,
        avg_price=[market.get_avg_price(c) for c in table.commodity_defs],
        has_signal=[market.has_price_signal(c) for c in table.commodity_defs],
        attr_avail=[attributes.get_availability(cid) for cid in table.attr_commodities],
        table=table,
    )
    market.kernel_snapshot = snapshot
    return snapshot


def build_quotes(table: EconomyTable, market: Market) -> Quotes:
    """Live top-of-book vectors, read at kernel-invocation time."""
    bid: list[Optional[int]] = []
    ask: list[Optional[int]] = []
    for commodity in table.commodity_defs:
        best_bid, best_ask = market.get_bid_ask_spread(commodity)
        bid.append(best_bid)
        ask.append(best_ask)
    return Quotes(bid=bid, ask=ask, table=table)


def build_pack(
    table: EconomyTable, actor: "Actor", amortization_horizon: int
) -> ActorPack:
    """Flatten one actor's kernel closure: skills + available inventory.

    Available-only quantities on purpose — every kernel ownership/feasibility
    check mirrors ``Inventory.has_quantity`` semantics.
    """
    inventory_available = [0] * len(table.commodity_ids)
    index = table.commodity_index
    for commodity, quantity in actor.inventory.commodities.items():
        cidx = index.get(commodity.id)
        if cidx is not None:
            inventory_available[cidx] = quantity
    skills = [actor.get_skill_rating(skill_id) for skill_id in table.skill_ids]
    return ActorPack(
        skills=skills,
        inventory_available=inventory_available,
        amortization_horizon=amortization_horizon,
    )


def try_context(
    actor: "Actor", market: Market
) -> Optional[Tuple[EconomyTable, PlanetSnapshot]]:
    """Kernel/legacy dispatch gate: table + snapshot for real sim objects,
    ``None`` (-> legacy fallback) for anything else.
    """
    # getattr with defaults (not plain attribute access) on purpose: this is
    # boundary code handling externally-provided doubles — Mock(spec=Actor)
    # raises on instance-only attributes a test didn't set, and any such
    # double belongs on the legacy path anyway.
    planet = getattr(actor, "planet", None)
    if planet is None:
        return None
    sim = getattr(actor, "sim", None)
    process_registry = getattr(sim, "process_registry", None)
    if type(process_registry) is not ProcessRegistry:
        return None
    commodity_registry = getattr(sim, "commodity_registry", None)
    if type(commodity_registry) is not CommodityRegistry:
        return None
    if type(market) is not Market:
        return None
    if type(getattr(actor, "inventory", None)) is not Inventory:
        return None
    if type(getattr(planet, "attributes", None)) is not PlanetAttributes:
        return None
    table = get_table(process_registry, commodity_registry)
    return table, get_snapshot(table, market, planet)
