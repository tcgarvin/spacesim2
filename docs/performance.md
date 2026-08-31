# Performance

Current posture after the 2026 perf campaign (history and rejected
alternatives: `docs/decision-log.md`). Target scale is 500 planets × 100
actors/planet × 1000 ships; that runs at **~3.2 s/turn** on a free-threaded
interpreter with `--workers 12` (~7.9-8.1 s/turn serial), down from 45+.

## Threaded actor phase (`--workers N`)

`spacesim2 run --workers N` runs each turn's actor phase across a
shared-memory thread pool, sharding planets round-robin (`core/parallel.py`).
Ships, market matching, and export stay serial.

**It needs a free-threaded interpreter.** The actor phase is pure-Python
bytecode; under stock (GIL-enabled) CPython the threads serialize and
`--workers` gives no speedup (the CLI warns). Measured at target scale
(16-core host, CPython 3.14.7t):

| Config | Actor phase s | Total s/turn |
|---|---|---|
| stock 3.13, serial | 7.8 | 8.1 |
| 3.14t, serial | 7.3 | 7.9 |
| 3.14t, `--workers 6` | 3.4 | 4.1 |
| 3.14t, `--workers 12` | 2.65 | 3.2 |

Single-thread penalty of the free-threaded build: ~none on this workload.

**Why threads are safe here:** an actor turn touches only its own state, its
own planet's market (place/cancel only — matching runs serially after the
ship phase), read-only registries, the data logger (per-actor keys, one
writer each), and the lock-wrapped global order-id counter. Planets are
disjoint across shards. Each planet's actors shuffle independently per turn;
cross-planet ordering cannot matter inside the actor phase, so this changes
only the random stream (the sim is already non-reproducible).

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

## Open levers

- **Thread-scaling contention** — thread scaling is only ~2.8x at 12 workers.
  The global `random` module's lock is **ruled out**: a per-actor-RNG
  refactor (69ca496, reverted for simplicity in 286c739) measured no change
  at target scale (3.15 s/turn at `--workers 12` vs 8.71 serial — same
  ratio). The prime remaining suspect is refcount traffic on shared
  read-only objects (registries, commodity/process instances); profile
  (py-spy/perf on 3.14t) before writing code.
- **Sorted/heap order books** — matching still re-sorts both sides of every
  commodity book per turn (including dead books unioned in via
  `volume_history` keys) and uses O(B) `list.pop(0)` per fill.
- Per-turn cost grows ~28-33% over the first ~150 turns then plateaus
  (economy warm-up, not a leak).

## Reference bench numbers (single-thread, 50-turn driver)

| Config | ms/turn (pre-campaign) | ms/turn (current) |
|---|---|---|
| P=5, A=80, S=2/planet | 89 | 54 |
| P=10, A=20, S=2/planet | 86 | 33 |
| P=40, A=20, S=2/planet | 937 | 149 |
