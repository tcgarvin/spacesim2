"""Type stub for the compiled ``spacesim2_kernel`` extension (native/src/lib.rs).

Signatures must stay in lockstep with ``backend_py`` — the semantic reference
the native module mirrors — and with the marshalling glue in
``spacesim2.core.kernel.backend_native``.
"""

from typing import Optional, Sequence

class KernelTable:
    def __init__(
        self,
        commodity_ids: Sequence[str],
        proc_inputs: Sequence[Sequence[tuple[int, int]]],
        proc_outputs: Sequence[Sequence[tuple[int, int]]],
        proc_tools: Sequence[Sequence[int]],
        proc_facilities: Sequence[Sequence[int]],
        proc_skills: Sequence[Sequence[int]],
        proc_resource_attr: Sequence[int],
        producers_of: Sequence[Sequence[tuple[int, int]]],
        facility_build_proc: Sequence[int],
        government_wage: int,
        tool_lifespan: int,
        max_impute_depth: int,
        colonist_profit_floor: float,
    ) -> None: ...

class KernelSnapshot:
    def __init__(
        self,
        avg_price: Sequence[int],
        has_signal: Sequence[bool],
        attr_avail: Sequence[float],
    ) -> None: ...

class KernelQuotes:
    def __init__(
        self, bid: Sequence[Optional[int]], ask: Sequence[Optional[int]]
    ) -> None: ...

class KernelPack:
    def __init__(
        self,
        skills: Sequence[float],
        inventory_available: Sequence[int],
        amortization_horizon: int,
    ) -> None: ...

def expected_skill_factor(ratings: Sequence[float]) -> float: ...
def best_process_scan(
    table: KernelTable,
    snapshot: KernelSnapshot,
    quotes: KernelQuotes,
    pack: KernelPack,
) -> tuple[int, float]: ...
def replacement_cost(
    table: KernelTable,
    snapshot: KernelSnapshot,
    quotes: KernelQuotes,
    pack: KernelPack,
    cidx: int,
) -> Optional[float]: ...
def evaluate_actor(
    table: KernelTable,
    snapshot: KernelSnapshot,
    quotes: KernelQuotes,
    pack: KernelPack,
) -> tuple[
    int,
    float,
    list[Optional[float]],
    list[bool],
    list[float],
    list[float],
]: ...
def imputed_unit_cost(
    table: KernelTable,
    snapshot: KernelSnapshot,
    quotes: KernelQuotes,
    pack: KernelPack,
    cidx: int,
    depth: int,
    visiting: frozenset[str],
    memo: dict[str, float],
) -> float: ...
def impute_recipe_cost(
    table: KernelTable,
    snapshot: KernelSnapshot,
    quotes: KernelQuotes,
    pack: KernelPack,
    pidx: int,
    depth: int,
    visiting: frozenset[str],
    memo: dict[str, float],
) -> float: ...
