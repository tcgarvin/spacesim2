# Threaded actor phase (`--workers N`)

`spacesim2 run --workers N` runs each turn's actor phase across a
shared-memory thread pool, sharding planets round-robin (`core/parallel.py`).
Ships, market matching, and export stay serial.

## It needs a free-threaded interpreter

The actor phase is pure-Python bytecode. Under stock (GIL-enabled) CPython,
threads serialize and `--workers` gives **no speedup** (the CLI warns). On a
free-threaded build (3.13t+/3.14t, officially supported since 3.14) the
threads genuinely run in parallel.

Measured at target scale (500 planets × 100 actors/planet × 1000 ships,
16-core host, CPython 3.14.7t):

| Config | Actor phase s | Total s/turn |
|---|---|---|
| stock 3.13, serial | 7.8 | 8.1 |
| 3.14t, serial | 7.3 | 7.9 |
| 3.14t, `--workers 6` | 3.4 | 4.1 |
| 3.14t, `--workers 12` | 2.65 | 3.2 |

Single-thread penalty of the free-threaded build measured ~none on this
workload. Scaling is sublinear (~2.8x at 12 threads): the global `random`
module (internally locked on free-threaded builds, called constantly by
actor code) and reference-count traffic on shared registries are the main
contention suspects. Per-planet RNG streams are the obvious next lever.

## Running under 3.14t

`uv sync` can't build the full project on a free-threaded interpreter yet —
pygame has no free-threaded build — so use a side venv for headless runs
(the UI stays on the stock interpreter):

```bash
uv python install 3.14t
uv venv --python 3.14t .venv-ft
uv pip install --python .venv-ft/bin/python pyyaml tqdm numpy typing-extensions
.venv-ft/bin/python -m spacesim2.cli.main run --turns 200 --no-export --workers 12
```

(`.venv-ft` is gitignored. Add pandas/pyarrow to the install list if you
need export; verify free-threaded wheels resolve.) Guard rail: importing any
C extension without free-threaded support silently **re-enables the GIL**;
the CLI checks `sys._is_gil_enabled()` and warns.

## Why threads are safe here

The isolation argument, proven out by the earlier fork-per-turn prototype
(branch `parallel-actor-phase`, superseded by this implementation): an actor
turn touches only its own state, its own planet's market (place/cancel only
— matching runs serially after the ship phase), read-only registries, the
data logger (per-actor keys, one writer each; per-key dict ops are atomic on
free-threaded CPython), and the lock-wrapped global order-id counter.
Planets are disjoint across shards, so no market is shared between threads.

Ordering semantics: instead of one global shuffle of `sim.actors`, each
planet's actors shuffle independently per turn. Cross-planet ordering cannot
matter inside the actor phase (actors never observe another planet), so this
changes only the random stream — the sim is already non-reproducible.

## History: the fork-per-turn prototype

Branch `parallel-actor-phase` holds the pre-free-threading attempt: fork a
worker pool per turn (COW-shared object graph in), pickle per-planet state
deltas back. Even after shrinking the sync blob 53 → 38 MB/turn it managed
only 6.05 s/turn at target scale — the parent-side apply and the
serialization tax are structural. Its correctness findings carried over:
brains hold cross-turn decision state, macro behavior is sensitive to
inventory-dict iteration order, and per-planet sharding needs the
planet-coverage invariant checked. Design + postmortem:
`docs/parallel-actor-phase.md` on that branch.
