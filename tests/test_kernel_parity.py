"""Kernel/legacy parity: the flattened kernel backend must reproduce the
legacy brain valuation math bit-for-bit against a real, mid-run simulation.

The mock-based brain tests exercise the legacy ``*_fallback`` bodies; real
simulations run on the kernel path. This suite is the bridge: it holds the
kernel to the legacy reference on live market/inventory state, so a semantic
drift in either implementation (or a future native backend) fails loudly.
"""

import math

import pytest

from spacesim2.core import kernel
from spacesim2.core.brains.colonist import ColonistBrain
from spacesim2.core.simulation import Simulation


@pytest.fixture(scope="module")
def sim() -> Simulation:
    simulation = Simulation()
    simulation.setup_simple(
        num_planets=2, num_regular_actors=12, num_market_makers=1, num_ships=1
    )
    # A few turns so books, trade history, skills, and inventories are
    # non-trivial (live asks, avg prices with real signal, owned tools).
    for _ in range(8):
        simulation.run_turn()
    return simulation


def _kernel_actors(simulation: Simulation) -> list:
    # Drop caches held over from mid-turn: BrainCache quotes and the market
    # snapshot were captured during the last actor phase, before end-of-turn
    # matching moved the books. Production never calls the kernel in that
    # window (all kernel calls happen inside the actor phase), but this
    # harness does, so make both paths read the same post-matching state.
    for planet in simulation.planets:
        planet.market.kernel_snapshot = None
        planet.market.drive_anchor_cache.clear()
    actors = []
    for a in simulation.actors:
        a.brain._cache = None
        if a.planet is not None and kernel.try_context(a, a.planet.market) is not None:
            actors.append(a)
    assert actors, "expected real actors to take the kernel path"
    return actors


def test_replacement_cost_parity(sim: Simulation) -> None:
    for actor in _kernel_actors(sim):
        market = actor.planet.market
        brain = actor.brain
        for commodity in sim.commodity_registry.all_commodities():
            got = brain._replacement_cost(actor, market, commodity, None)
            want = brain._replacement_cost_fallback(actor, market, commodity, None)
            assert got == want, (actor.name, commodity.id, got, want)


def test_imputed_unit_cost_parity(sim: Simulation) -> None:
    for actor in _kernel_actors(sim):
        market = actor.planet.market
        brain = actor.brain
        for commodity in sim.commodity_registry.all_commodities():
            got = brain._imputed_unit_cost(actor, market, commodity, 0, frozenset(), {})
            want = brain._imputed_unit_cost_fallback(
                actor, market, commodity, 0, frozenset(), {}
            )
            assert got == want or (math.isinf(got) and math.isinf(want)), (
                actor.name,
                commodity.id,
                got,
                want,
            )


def test_impute_recipe_cost_parity(sim: Simulation) -> None:
    for actor in _kernel_actors(sim):
        market = actor.planet.market
        brain = actor.brain
        for process in sim.process_registry.all_processes():
            got = brain._impute_recipe_cost(actor, market, process, 0, frozenset(), {})
            want = brain._impute_recipe_cost_fallback(
                actor, market, process, 0, frozenset(), {}
            )
            assert got == want or (math.isinf(got) and math.isinf(want)), (
                actor.name,
                process.id,
                got,
                want,
            )


def test_best_process_scan_parity(sim: Simulation) -> None:
    checked = 0
    for actor in _kernel_actors(sim):
        if not isinstance(actor.brain, ColonistBrain):
            continue
        market = actor.planet.market
        got = actor.brain._best_process_and_raw_profit(actor, market, None)
        want = actor.brain._best_process_and_raw_profit_fallback(actor, market, None)
        assert got == want, (actor.name, got, want)
        checked += 1
    assert checked, "expected at least one colonist"


def test_can_execute_parity(sim: Simulation) -> None:
    for actor in _kernel_actors(sim):
        market = actor.planet.market
        context = kernel.try_context(actor, market)
        assert context is not None
        table, snapshot = context
        pack = kernel.build_pack(table, actor, 300)
        quotes = kernel.build_quotes(table, market)
        evaluation = kernel.evaluate_actor(table, snapshot, quotes, pack)
        for pidx, process_id in enumerate(table.process_ids):
            assert evaluation.can_execute[pidx] == actor.can_execute_process(
                process_id
            ), (actor.name, process_id)


def test_skill_and_yield_factor_parity(sim: Simulation) -> None:
    for actor in _kernel_actors(sim):
        market = actor.planet.market
        brain = actor.brain
        context = kernel.try_context(actor, market)
        assert context is not None
        table, snapshot = context
        pack = kernel.build_pack(table, actor, 300)
        quotes = kernel.build_quotes(table, market)
        evaluation = kernel.evaluate_actor(table, snapshot, quotes, pack)
        for pidx, process in enumerate(table.process_defs):
            assert evaluation.skill_factor[pidx] == brain._expected_skill_factor(
                actor, process, None
            )
            assert evaluation.yield_modifier[pidx] == brain._expected_yield_modifier(
                actor, process, None
            )
