"""Pure-Python kernel backend: recipe-evaluation math over plain data.

Every function here reads only :mod:`spacesim2.core.kernel.table` structures
(lists of ints/floats/bools plus integer indices) — no simulation objects, no
RNG, no exceptions as control flow. Failure modes are ``None`` (no
replacement recipe), ``math.inf`` (unvaluable in imputation), and the
fabricated avg-price default already baked into ``PlanetSnapshot.avg_price``.

Semantics mirror the legacy implementations in ``core/actor_brain.py`` and
``core/brains/colonist.py`` exactly, including iteration order and strict
first-wins tie-breaking (float-order determinism); a native backend must
reproduce the same association order for sums.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

from spacesim2.core.kernel.table import (
    ActorEval,
    ActorPack,
    EconomyTable,
    PlanetSnapshot,
    Quotes,
)


def expected_skill_factor(ratings: Sequence[float]) -> float:
    """Expected output per turn of labor relative to a guaranteed run.

    Mirrors the skill check in ProcessCommand: ratings below 1.0 fail (and
    waste the turn) proportionally; ratings above 1.0 sometimes double the
    run. An empty ``ratings`` means the process has no relevant skills and
    always succeeds (factor 1.0). Combined rating is the plain mean, exactly
    ``SkillCheck.get_combined_skill_rating``.
    """
    if not ratings:
        return 1.0
    rating = sum(ratings) / len(ratings)
    success_probability = min(1.0, rating)
    expected_multiplier = 1.0 + max(0.0, rating - 1.0) * 0.5
    return success_probability * expected_multiplier


def _can_execute(table: EconomyTable, inv: List[int], pidx: int) -> bool:
    """Inputs/tools/facilities sufficiency against *available* inventory."""
    for cidx, qty in table.proc_inputs[pidx]:
        if inv[cidx] < qty:
            return False
    for cidx in table.proc_tools[pidx]:
        if inv[cidx] < 1:
            return False
    for cidx in table.proc_facilities[pidx]:
        if inv[cidx] < 1:
            return False
    return True


def _process_factors(
    table: EconomyTable, snapshot: PlanetSnapshot, pack: ActorPack, pidx: int
) -> tuple[float, float]:
    """(skill_factor, yield_modifier) for one process — the single source
    shared by the scan, replacement cost, and the vectorized evaluate_actor.
    """
    skills = pack.skills
    skill = expected_skill_factor([skills[s] for s in table.proc_skills[pidx]])
    slot = table.proc_resource_attr[pidx]
    yield_mod = snapshot.attr_avail[slot] if slot >= 0 else 1.0
    return skill, yield_mod


def best_process_scan(
    table: EconomyTable,
    snapshot: PlanetSnapshot,
    quotes: Quotes,
    pack: ActorPack,
) -> tuple[int, float]:
    """The colonist whole-registry profitability scan.

    Returns (best process index or -1, that process's *raw* profit). Inputs
    priced at ask-else-avg, outputs at bid-else-avg (both deliberately trust
    the fabricated avg default of 10); expected value discounted by yield and
    skill; winner must beat the government-work floor strictly, first-wins on
    ties, in registry iteration order.
    """
    inv = pack.inventory_available
    bid, ask, avg = quotes.bid, quotes.ask, snapshot.avg_price

    best_process = -1
    best_discounted_profit = table.colonist_profit_floor
    best_raw_profit = 0.0
    for p in range(len(table.process_ids)):
        input_cost = 0.0
        for cidx, qty in table.proc_inputs[p]:
            ask_price = ask[cidx]
            price = ask_price if ask_price is not None else avg[cidx]
            input_cost += price * qty
        output_value = 0.0
        for cidx, qty in table.proc_outputs[p]:
            bid_price = bid[cidx]
            price = bid_price if bid_price is not None else avg[cidx]
            output_value += price * qty
        skill_factor, yield_modifier = _process_factors(table, snapshot, pack, p)
        expected_value = output_value * yield_modifier * skill_factor
        discounted_profit = expected_value - input_cost
        if discounted_profit > best_discounted_profit and _can_execute(table, inv, p):
            best_process = p
            best_discounted_profit = discounted_profit
            best_raw_profit = output_value - input_cost
    return best_process, best_raw_profit


def replacement_cost(
    table: EconomyTable,
    snapshot: PlanetSnapshot,
    quotes: Quotes,
    pack: ActorPack,
    cidx: int,
) -> Optional[float]:
    """Per-unit cost for this actor to self-produce one commodity.

    Cheapest producing process whose facilities the actor already owns;
    inputs at ask-else-avg; missing tools amortized over their lifespan;
    labor at the government wage scaled by expected skill throughput; yield
    discounted by planet availability. ``None`` when no owned-facility
    recipe exists.
    """
    inv = pack.inventory_available
    ask, avg = quotes.ask, snapshot.avg_price

    best: Optional[float] = None
    for p, out_qty in table.producers_of[cidx]:
        if out_qty <= 0:
            continue
        if any(inv[f] < 1 for f in table.proc_facilities[p]):
            continue
        input_cost = 0.0
        for in_cidx, qty in table.proc_inputs[p]:
            ask_price = ask[in_cidx]
            price = ask_price if ask_price is not None else avg[in_cidx]
            input_cost += price * qty
        for tool in table.proc_tools[p]:
            if inv[tool] >= 1:
                continue
            ask_price = ask[tool]
            price = ask_price if ask_price is not None else avg[tool]
            input_cost += price / table.tool_lifespan
        skill_factor, yield_modifier = _process_factors(table, snapshot, pack, p)
        expected_out = out_qty * yield_modifier
        if expected_out <= 0:
            continue
        # Inputs are only consumed on success and scale with the output
        # multiplier, so per-unit input cost is independent of skill;
        # labor, by contrast, is spent on failed turns too.
        per_unit = input_cost / expected_out + table.government_wage / (
            expected_out * skill_factor
        )
        if best is None or per_unit < best:
            best = per_unit
    return best


def evaluate_actor(
    table: EconomyTable,
    snapshot: PlanetSnapshot,
    quotes: Quotes,
    pack: ActorPack,
) -> ActorEval:
    """One-shot evaluation of everything the brains ask per actor-turn:
    the colonist best-process scan (winner + raw profit), the full
    per-commodity replacement-cost vector, and the per-process
    can-execute/skill/yield vectors.

    This is the batched Phase-2 (native/FFI) entry point, composed from the
    same lazy functions the Python shim's wrappers call directly
    (``best_process_scan``, ``replacement_cost``): one FFI round-trip
    amortizes everything, whereas in pure Python computing only what a brain
    actually asks for is cheaper.
    """
    inv = pack.inventory_available
    num_processes = len(table.process_ids)

    skill_factor: List[float] = []
    yield_modifier: List[float] = []
    for p in range(num_processes):
        skill, yield_mod = _process_factors(table, snapshot, pack, p)
        skill_factor.append(skill)
        yield_modifier.append(yield_mod)
    can_execute = [_can_execute(table, inv, p) for p in range(num_processes)]

    best_process, best_raw_profit = best_process_scan(table, snapshot, quotes, pack)

    return ActorEval(
        best_process=best_process,
        best_raw_profit=best_raw_profit,
        replacement_cost=[
            replacement_cost(table, snapshot, quotes, pack, cidx)
            for cidx in range(len(table.commodity_ids))
        ],
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
    """Best estimate of the per-unit cost to acquire a commodity: buy it, or,
    if the market can't price it, make it (recursively, cheapest recipe).

    ``memo``/``visiting`` are keyed by commodity *id string* so the memo dict
    is interchangeable with the legacy path's ``BrainCache.imputed_cost``
    (only "make"-branch results are memoized; the buy branch re-reads live
    quotes every call). Returns ``math.inf`` when the commodity can be
    neither bought nor produced.
    """
    # 1. Buy it: a live ask is the truest cost; fall back to last-traded avg,
    #    but only when a real trade set it — otherwise avg is the fabricated
    #    default of 10, which would short-circuit the "make it" branch for
    #    never-traded goods with a bogus price.
    ask_price = quotes.ask[cidx]
    if ask_price is not None:
        return float(ask_price)
    if snapshot.has_signal[cidx]:
        avg = snapshot.avg_price[cidx]
        if avg > 0:
            return float(avg)

    commodity_id = table.commodity_ids[cidx]
    if commodity_id in memo:
        return memo[commodity_id]
    if depth >= table.max_impute_depth or commodity_id in visiting:
        return math.inf  # depth bound or production cycle -> can't value

    # 2. Make it: cheapest producing recipe, costed recursively. Expected
    #    yield divides by the planet's resource availability, so a
    #    resource-poor planet imputes extraction as genuinely expensive.
    visiting = visiting | {commodity_id}
    best = math.inf
    for pidx, out_qty in table.producers_of[cidx]:
        if out_qty <= 0:
            continue
        slot = table.proc_resource_attr[pidx]
        attribute_modifier = snapshot.attr_avail[slot] if slot >= 0 else 1.0
        if attribute_modifier <= 0.0:
            continue  # resource absent here -> can't make it locally
        recipe_cost = impute_recipe_cost(
            table, snapshot, quotes, pack, pidx, depth, visiting, memo
        )
        if math.isinf(recipe_cost):
            continue
        best = min(best, recipe_cost / (out_qty * attribute_modifier))

    if not math.isinf(best):
        memo[commodity_id] = best
    return best


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
    """Total imputed cost to execute a process once: a turn of labor at the
    government wage, recursively-valued inputs, plus amortized tool and
    facility costs. ``math.inf`` if any component can't be valued.
    """
    inv = pack.inventory_available
    total = float(table.government_wage)

    for cidx, quantity in table.proc_inputs[pidx]:
        unit = imputed_unit_cost(
            table, snapshot, quotes, pack, cidx, depth + 1, visiting, memo
        )
        if math.isinf(unit):
            return math.inf
        total += unit * quantity

    # Tools the actor lacks must be acquired; amortize over their lifespan.
    for tool in table.proc_tools[pidx]:
        if inv[tool] >= 1:
            continue
        unit = imputed_unit_cost(
            table, snapshot, quotes, pack, tool, depth + 1, visiting, memo
        )
        if math.isinf(unit):
            return math.inf
        total += unit / table.tool_lifespan

    # Facilities the actor lacks are a lump-sum build cost amortized over
    # this actor's (risk-appetite-dependent) expected usage horizon.
    for facility in table.proc_facilities[pidx]:
        if inv[facility] >= 1:
            continue
        build_pidx = table.facility_build_proc[facility]
        if build_pidx < 0:
            return math.inf
        build_cost = impute_recipe_cost(
            table, snapshot, quotes, pack, build_pidx, depth + 1, visiting, memo
        )
        if math.isinf(build_cost):
            return math.inf
        total += build_cost / pack.amortization_horizon

    return total
