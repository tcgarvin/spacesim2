"""Threaded per-planet actor phase (perf hit-list Tier 3).

Runs each turn's actor phase across a shared-memory thread pool, sharding
planets round-robin. This only yields real parallelism on a free-threaded
CPython build (3.13t+/3.14t): the actor phase is pure-Python bytecode, so
under a GIL-enabled interpreter the threads serialize and the phase runs at
roughly serial speed. The code is correct either way, which keeps the tests
runnable on stock interpreters.

Why threads are safe here — the isolation argument, originally proven out by
the fork-per-turn prototype (branch ``parallel-actor-phase``): an actor turn
touches only

- the actor's own state (inventory, money, skills, drives, brain memory),
- its own planet's market (place/cancel; matching runs later, serially),
- read-only registries (commodities, processes, skills),
- the data logger, which is written under per-actor keys with a single
  writer each (per-key dict ops are atomic on free-threaded CPython),
- the global order-id counter, which is lock-wrapped (market._LockedCounter).

Planets are disjoint across shards, so no market is touched by two threads.
Ships, market matching, and export stay serial in ``Simulation.run_turn``.

Ordering semantics differ from the serial path: instead of one global
shuffle of ``sim.actors``, each planet's actors are shuffled independently
(per-shard RNG). Within the actor phase, cross-planet ordering cannot matter
— actors never observe another planet — so this changes no observable
behavior, only the (already non-reproducible) random stream. In-actor code
draws from ``Actor.rng`` (a per-actor ``random.Random``) rather than the
module-level ``random``, whose internal lock on free-threaded builds was a
contention suspect for the sub-linear thread scaling.
"""

import random
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from spacesim2.core.planet import Planet
    from spacesim2.core.simulation import Simulation


def _warm_shared_caches(sim: "Simulation") -> None:
    """Populate lazily built read-only caches before threads race to do it.

    Concurrent lazy initialization would at worst duplicate work, but warming
    once up front keeps the shards' first turns from all paying it.
    """
    for commodity in sim.commodity_registry.all_commodities():
        sim.process_registry.get_processes_producing(commodity)


def _run_shard(planets: List["Planet"], rng: random.Random) -> None:
    """Run the actor phase for one shard's planets, in shuffled actor order."""
    for planet in planets:
        actors = list(planet.actors)
        rng.shuffle(actors)
        for actor in actors:
            actor.take_turn()


def _get_pool(sim: "Simulation", workers: int) -> ThreadPoolExecutor:
    """The sim's persistent actor-phase pool, (re)built if the size changed."""
    pool = sim._actor_phase_pool
    if pool is None or sim._actor_phase_pool_size != workers:
        if pool is not None:
            pool.shutdown(wait=True)
        pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="actor-phase")
        sim._actor_phase_pool = pool
        sim._actor_phase_pool_size = workers
    return pool


def run_actor_phase_threaded(sim: "Simulation", workers: int) -> None:
    """Run every planet's actor turns across a thread pool.

    Must be called at the point run_turn would otherwise run its serial
    actor loop (after set_current_turn, before the ship phase).
    """
    if workers <= 1:
        raise ValueError("run_actor_phase_threaded requires workers >= 2")
    # Shards iterate planet.actors; an actor registered on the sim but not
    # on its planet would silently never act again.
    if sum(len(p.actors) for p in sim.planets) != len(sim.actors):
        raise RuntimeError(
            "planet.actors does not cover sim.actors; cannot shard the "
            "actor phase by planet"
        )
    _warm_shared_caches(sim)
    workers = min(workers, len(sim.planets))
    shards = [sim.planets[k::workers] for k in range(workers)]
    rngs = [random.Random(random.random()) for _ in shards]
    pool = _get_pool(sim, workers)
    futures = [pool.submit(_run_shard, shard, rng) for shard, rng in zip(shards, rngs)]
    # result() re-raises the first shard failure; let it propagate loudly.
    for future in futures:
        future.result()
