"""Native (Rust/PyO3) kernel backend: thin marshalling glue over
``spacesim2_kernel`` (built from ``native/``; see docs/performance.md).

Importing this module raises ``ImportError`` when the compiled extension is
not installed, which is exactly the signal ``kernel/__init__`` uses to fall
back to :mod:`backend_py`. The extension is optional by design — never a
hard dependency.

Marshalling design: each kernel input struct (``EconomyTable``,
``PlanetSnapshot``, ``Quotes``, ``ActorPack``) is converted to a Rust-owned
twin exactly once per struct lifetime and cached on the dataclass's
``native_handle`` slot, so steady-state calls pass only opaque handles plus
scalars. The str-keyed imputation memo stays a Python dict (it must interop
with ``BrainCache.imputed_cost``); the native entry points read it once,
recurse natively, and write newly-memoized entries back.

``expected_skill_factor`` is deliberately re-exported from ``backend_py``:
it is a two-multiply pure function whose FFI marshalling would cost more
than the compute.
"""

from __future__ import annotations

from typing import Dict, Optional, Sequence, cast

import spacesim2_kernel as _native

from spacesim2.core.kernel.backend_py import expected_skill_factor
from spacesim2.core.kernel.table import (
    ActorEval,
    ActorPack,
    EconomyTable,
    PlanetSnapshot,
    Quotes,
)

__all__ = [
    "best_process_scan",
    "evaluate_actor",
    "expected_skill_factor",
    "impute_recipe_cost",
    "imputed_unit_cost",
    "replacement_cost",
]


def _table_handle(table: EconomyTable) -> "_native.KernelTable":
    # The dataclass slot is typed Any (kernel.table must not depend on the
    # optional extension), so each helper casts after filling it.
    handle = cast(Optional["_native.KernelTable"], table.native_handle)
    if handle is None:
        handle = _native.KernelTable(
            table.commodity_ids,
            table.proc_inputs,
            table.proc_outputs,
            table.proc_tools,
            table.proc_facilities,
            table.proc_skills,
            table.proc_resource_attr,
            table.producers_of,
            table.facility_build_proc,
            table.government_wage,
            table.tool_lifespan,
            table.max_impute_depth,
            table.colonist_profit_floor,
        )
        table.native_handle = handle
    return handle


def _snapshot_handle(snapshot: PlanetSnapshot) -> "_native.KernelSnapshot":
    handle = cast(Optional["_native.KernelSnapshot"], snapshot.native_handle)
    if handle is None:
        handle = _native.KernelSnapshot(
            snapshot.avg_price, snapshot.has_signal, snapshot.attr_avail
        )
        snapshot.native_handle = handle
    return handle


def _quotes_handle(quotes: Quotes) -> "_native.KernelQuotes":
    handle = cast(Optional["_native.KernelQuotes"], quotes.native_handle)
    if handle is None:
        handle = _native.KernelQuotes(quotes.bid, quotes.ask)
        quotes.native_handle = handle
    return handle


def _pack_handle(pack: ActorPack) -> "_native.KernelPack":
    handle = cast(Optional["_native.KernelPack"], pack.native_handle)
    if handle is None:
        handle = _native.KernelPack(
            pack.skills, pack.inventory_available, pack.amortization_horizon
        )
        pack.native_handle = handle
    return handle


def best_process_scan(
    table: EconomyTable,
    snapshot: PlanetSnapshot,
    quotes: Quotes,
    pack: ActorPack,
) -> tuple[int, float]:
    """See :func:`backend_py.best_process_scan` (the semantic reference)."""
    return _native.best_process_scan(
        _table_handle(table),
        _snapshot_handle(snapshot),
        _quotes_handle(quotes),
        _pack_handle(pack),
    )


def replacement_cost(
    table: EconomyTable,
    snapshot: PlanetSnapshot,
    quotes: Quotes,
    pack: ActorPack,
    cidx: int,
) -> Optional[float]:
    """See :func:`backend_py.replacement_cost` (the semantic reference)."""
    return _native.replacement_cost(
        _table_handle(table),
        _snapshot_handle(snapshot),
        _quotes_handle(quotes),
        _pack_handle(pack),
        cidx,
    )


def evaluate_actor(
    table: EconomyTable,
    snapshot: PlanetSnapshot,
    quotes: Quotes,
    pack: ActorPack,
) -> ActorEval:
    """See :func:`backend_py.evaluate_actor` (the semantic reference)."""
    (
        best_process,
        best_raw_profit,
        replacement,
        can_execute,
        skill_factor,
        yield_modifier,
    ) = _native.evaluate_actor(
        _table_handle(table),
        _snapshot_handle(snapshot),
        _quotes_handle(quotes),
        _pack_handle(pack),
    )
    return ActorEval(
        best_process=best_process,
        best_raw_profit=best_raw_profit,
        replacement_cost=replacement,
        can_execute=can_execute,
        skill_factor=skill_factor,
        yield_modifier=yield_modifier,
        table=table,
    )


def imputed_unit_cost(
    table: EconomyTable,
    snapshot: PlanetSnapshot,
    quotes: Quotes,
    pack: ActorPack,
    cidx: int,
    depth: int,
    visiting: frozenset[str],
    memo: Dict[str, float],
) -> float:
    """See :func:`backend_py.imputed_unit_cost` (the semantic reference)."""
    return _native.imputed_unit_cost(
        _table_handle(table),
        _snapshot_handle(snapshot),
        _quotes_handle(quotes),
        _pack_handle(pack),
        cidx,
        depth,
        visiting,
        memo,
    )


def impute_recipe_cost(
    table: EconomyTable,
    snapshot: PlanetSnapshot,
    quotes: Quotes,
    pack: ActorPack,
    pidx: int,
    depth: int,
    visiting: frozenset[str],
    memo: Dict[str, float],
) -> float:
    """See :func:`backend_py.impute_recipe_cost` (the semantic reference)."""
    return _native.impute_recipe_cost(
        _table_handle(table),
        _snapshot_handle(snapshot),
        _quotes_handle(quotes),
        _pack_handle(pack),
        pidx,
        depth,
        visiting,
        memo,
    )


# Keep the re-export's signature visible to callers of this module.
_ = expected_skill_factor  # re-exported above


def _unused_typing_guard(ratings: Sequence[float]) -> float:
    """Anchor so mypy keeps Sequence imported for the re-export's signature."""
    return expected_skill_factor(ratings)
