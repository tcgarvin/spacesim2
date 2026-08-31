"""Flattened, integer-indexed economy data for the recipe-evaluation kernel.

Everything in this module is *plain data*: lists of ints/floats/bools plus
integer indices into those lists. No ``Simulation``/``Actor``/``Market``
objects cross into the kernel compute functions (``backend_py``), so a native
(Rust/PyO3) backend can drop in behind the same structures in a later phase.

The only non-plain fields are the ``commodity_defs``/``process_defs`` bridge
lists on :class:`EconomyTable`, which the *Python-side adapters* use to talk
to ``Market`` (quote reads) and to hand results back to brains (the winning
``ProcessDefinition``). The compute functions never touch them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from spacesim2.core.commodity import CommodityDefinition, CommodityRegistry
from spacesim2.core.process import ProcessDefinition, ProcessRegistry

# ---------------------------------------------------------------------------
# Kernel constants (canonical definitions; actor_brain re-exports them for
# backward compatibility). Baked into every EconomyTable so a native backend
# needs no separate constant channel.
# ---------------------------------------------------------------------------

# Opportunity cost floor for a turn of labor (government work wage). Used as
# the labor component of replacement cost when self-producing a good.
GOVERNMENT_WAGE = 10

# Tools wear out after ~100 uses; amortize their cost across that lifespan.
TOOL_EXPECTED_LIFESPAN = 100

# Bound on how deep make-or-buy imputation recurses through production chains.
MAX_IMPUTE_DEPTH = 6

# Default facility amortization horizon for actors that don't set their own
# (industrialists randomize a per-actor value to encode risk appetite).
DEFAULT_FACILITY_AMORTIZATION_HORIZON = 300

# The colonist best-process scan only picks a process whose discounted profit
# strictly exceeds a turn of government work.
COLONIST_PROFIT_FLOOR = 10.0

# Facility commodity id -> build process id. Static economy data that used to
# live source-coded in ActorBrain._get_build_process_for_facility; this is now
# the single source (the brain method delegates here). Must be kept in sync
# with data/processes.yaml.
FACILITY_BUILD_PROCESSES: Dict[str, str] = {
    "smelting_facility": "build_smelting_facility",
    "metalworking_facility": "build_metalworking_facility",
    "textile_mill": "build_textile_mill",
    "chemistry_lab": "build_chemistry_lab",
    "precision_forge": "build_precision_forge",
    "electronics_workshop": "build_electronics_workshop",
    "advanced_factory": "build_advanced_factory",
}


@dataclass
class EconomyTable:
    """Setup-time flattening of the commodity/process registries.

    Iteration orders are load-bearing: ``process_ids`` preserves
    ``ProcessRegistry.all_processes()`` order (the best-process scan's
    first-wins tie-breaking depends on it), ``proc_inputs``/``proc_outputs``
    preserve each process's dict order (float summation order), and
    ``producers_of`` reproduces the registry's producer-index build order.
    """

    # Commodities
    commodity_ids: List[str]
    commodity_index: Dict[str, int]
    transportable: List[bool]
    # Processes (flattened edge lists)
    process_ids: List[str]
    process_index: Dict[str, int]
    proc_inputs: List[List[Tuple[int, int]]]  # per process: (commodity_idx, qty)
    proc_outputs: List[List[Tuple[int, int]]]  # per process: (commodity_idx, qty)
    proc_tools: List[List[int]]  # per process: commodity_idx
    proc_facilities: List[List[int]]  # per process: commodity_idx
    proc_skills: List[List[int]]  # per process: skill_idx
    proc_resource_attr: List[int]  # per process: attr slot, -1 = none
    # Derived indices
    producers_of: List[List[Tuple[int, int]]]  # per commodity: (process_idx, out_qty)
    facility_build_proc: List[int]  # per commodity: build process_idx, -1 = none
    # Skills / planet-attribute slots
    skill_ids: List[str]
    attr_commodities: List[str]  # attr slot -> commodity id (availability lookup)
    # Constants
    government_wage: int
    tool_lifespan: int
    max_impute_depth: int
    colonist_profit_floor: float
    # Python-side bridges (adapters only; never read by kernel compute)
    commodity_defs: List[CommodityDefinition]
    process_defs: List[ProcessDefinition]
    # Identity anchors for cache invalidation: the exact list objects returned
    # by the registries when this table was built. The registries hand out one
    # shared list until their contents change, so an ``is`` check detects
    # staleness in O(1).
    source_processes: List[ProcessDefinition]
    source_commodities: List[CommodityDefinition]


@dataclass
class PlanetSnapshot:
    """Per-(market, turn) constant market state plus run-constant planet data.

    Only fields that cannot move during a turn belong here: ``avg_price`` and
    ``has_signal`` change exclusively during end-of-turn matching, and
    ``attr_avail`` is fixed for the run. Top-of-book bid/ask move intra-turn
    as earlier-acting actors repost orders, so they are deliberately NOT part
    of this snapshot — see :class:`Quotes`.
    """

    turn: int
    avg_price: List[int]  # per commodity; includes the fabricated default 10
    has_signal: List[bool]  # per commodity
    attr_avail: List[float]  # per attr slot (table.attr_commodities)
    table: EconomyTable  # identity anchor for cache validation


@dataclass
class Quotes:
    """Live top-of-book per commodity, read at kernel-invocation time.

    Never cached beyond a single actor-turn: ~25% of bid/ask reads see
    intra-turn movement from earlier-acting actors, and freezing them per
    planet-turn measurably breaks the economy (see kernel interface spec,
    hazard 1). ``None`` = no resting order on that side (a native backend
    would encode this as a sentinel/validity mask).
    """

    bid: List[Optional[int]]
    ask: List[Optional[int]]
    table: EconomyTable  # identity anchor for cache validation


@dataclass
class ActorPack:
    """Per-actor state closure for one kernel invocation.

    ``inventory_available`` is the *available* (unreserved) quantity vector —
    the kernel's ownership/feasibility checks all use available-only
    semantics, mirroring ``Inventory.has_quantity``. Total (available +
    reserved) quantities are a caller-side concern and never enter the kernel.
    """

    skills: List[float]  # per skill_idx; default rating 0.5
    inventory_available: List[int]  # per commodity_idx
    amortization_horizon: int  # brain.facility_amortization_horizon


@dataclass
class ActorEval:
    """Full result of one ``evaluate_actor`` call.

    ``best_process`` is -1 when no process beats the government-work floor.
    ``replacement_cost`` entries are ``None`` when the actor has no
    owned-facility recipe for that commodity (a native backend would use NaN).
    """

    best_process: int
    best_raw_profit: float
    replacement_cost: List[Optional[float]]
    can_execute: List[bool]
    skill_factor: List[float]
    yield_modifier: List[float]
    table: EconomyTable  # bridge so callers can map indices back to defs


def build_economy_table(
    process_registry: ProcessRegistry, commodity_registry: CommodityRegistry
) -> EconomyTable:
    """Flatten the registries into an :class:`EconomyTable`.

    Registries are immutable after setup; callers cache the result keyed on
    the identity of the registries' shared ``all_*()`` lists (see
    ``adapters.get_table``).
    """
    processes = process_registry.all_processes()
    commodities = commodity_registry.all_commodities()

    commodity_ids = [c.id for c in commodities]
    commodity_index = {cid: i for i, cid in enumerate(commodity_ids)}
    transportable = [c.transportable for c in commodities]

    process_ids = [p.id for p in processes]
    process_index = {pid: i for i, pid in enumerate(process_ids)}

    skill_index: Dict[str, int] = {}
    attr_index: Dict[str, int] = {}

    proc_inputs: List[List[Tuple[int, int]]] = []
    proc_outputs: List[List[Tuple[int, int]]] = []
    proc_tools: List[List[int]] = []
    proc_facilities: List[List[int]] = []
    proc_skills: List[List[int]] = []
    proc_resource_attr: List[int] = []
    producers_of: List[List[Tuple[int, int]]] = [[] for _ in commodities]

    for pidx, process in enumerate(processes):
        proc_inputs.append(
            [(commodity_index[c.id], qty) for c, qty in process.inputs.items()]
        )
        outputs = [(commodity_index[c.id], qty) for c, qty in process.outputs.items()]
        proc_outputs.append(outputs)
        # Mirrors ProcessRegistry's producer-index build: registry order over
        # processes, output-dict order within one.
        for cidx, qty in outputs:
            producers_of[cidx].append((pidx, qty))
        proc_tools.append([commodity_index[t.id] for t in process.tools_required])
        proc_facilities.append(
            [commodity_index[f.id] for f in process.facilities_required]
        )
        skills: List[int] = []
        for skill_id in process.relevant_skills:
            if skill_id not in skill_index:
                skill_index[skill_id] = len(skill_index)
            skills.append(skill_index[skill_id])
        proc_skills.append(skills)
        if process.resource_attribute is not None:
            attr_commodity = process.resource_attribute.commodity
            if attr_commodity not in attr_index:
                attr_index[attr_commodity] = len(attr_index)
            proc_resource_attr.append(attr_index[attr_commodity])
        else:
            proc_resource_attr.append(-1)

    # Baked facility -> build-process map. A facility whose build process is
    # unknown (not in the map, or not in the registry) gets -1, which the
    # imputation path treats as "cannot value" — exactly the legacy behavior.
    facility_build_proc = [
        process_index.get(FACILITY_BUILD_PROCESSES.get(cid, ""), -1)
        for cid in commodity_ids
    ]

    return EconomyTable(
        commodity_ids=commodity_ids,
        commodity_index=commodity_index,
        transportable=transportable,
        process_ids=process_ids,
        process_index=process_index,
        proc_inputs=proc_inputs,
        proc_outputs=proc_outputs,
        proc_tools=proc_tools,
        proc_facilities=proc_facilities,
        proc_skills=proc_skills,
        proc_resource_attr=proc_resource_attr,
        producers_of=producers_of,
        facility_build_proc=facility_build_proc,
        skill_ids=list(skill_index),
        attr_commodities=list(attr_index),
        government_wage=GOVERNMENT_WAGE,
        tool_lifespan=TOOL_EXPECTED_LIFESPAN,
        max_impute_depth=MAX_IMPUTE_DEPTH,
        colonist_profit_floor=COLONIST_PROFIT_FLOOR,
        commodity_defs=list(commodities),
        process_defs=list(processes),
        source_processes=processes,
        source_commodities=commodities,
    )
