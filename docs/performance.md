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

- **Thread scaling (~3x at 12 workers) is largely a hardware ceiling on the
  dev host**, not a software-contention bug. Two hypotheses tested and ruled
  out at target scale: the global `random` lock (per-actor-RNG refactor
  69ca496, reverted in 286c739 — no change), and refcount traffic on shared
  commodity/process definition objects (per-planet registry copies + id-based
  hash/eq, parked on branch `per-planet-registries` — 12-worker 3.36→3.26
  s/turn i.e. noise, while costing ~8-17% serial from the Python-level
  `__hash__`). The dev host is an i5-1340P laptop: 4 P-cores + 8 E-cores,
  HT, and heavy thermal downclock under all-core load — that alone explains
  most of the ~3.4x CPU-seconds inflation observed at 12 workers. Re-test
  scaling on server hardware before chasing further contention theories.
- **Serial work reduction (2026-09-01 pass, ~1.2x at P=40): landed as
  behavior-exact caching**, verified by an equivalence test against the old
  scan (`tests/test_registry_and_brain_cache.py`). What landed: BrainCache
  split into finer invalidation groups (skill factors keyed on
  `skills_version` — they survive turns and inventory bumps; a successful
  ProcessCommand bumps skills *every* time, so the quote-derived per-process
  input-cost/output-value table got its own inventory- and skill-independent
  group, making the mid-turn re-rank a cheap multiply+sort instead of a
  second full registry scan); ranked-walk `_best_process_and_raw_profit`
  (sorted valuation vector + lazy `can_execute` walk); `Actor.can_execute`
  taking the definition (the id re-resolution was ~1M lookups/50 turns);
  per-market per-turn memos for the trade-history reads (`get_avg_price`,
  `has_price_signal`, `get_30_day_*` — written only inside `match_orders`,
  so exact); float stdev in `get_30_day_standard_deviation` (was
  exact-Fraction `statistics.stdev`, 6.7% of wall). NOT pursued: sharing
  quote-derived valuations across actors per (planet, turn) — order books
  mutate actor-by-actor (posting is immediate, only matching is deferred),
  so that is a behavior change, and the exact alternative (keying on live
  quote values) re-fetches the quotes that make up the cost. Remaining
  serial headroom is diffuse: `_drive_buy_commands` chain (~17% cum,
  `_replacement_cost` could get the same quote-part split), and
  `_cheapest_material_ask`/direct book scans.
- **Order cancel/repost churn** — was ~14% of wall as a cluster
  (`prune_unchanged_order_commands` top self-time + `cancel_order` +
  `_record_order_event` + command construction). Landed 2026-09-01:
  order-event recording is now gated on the data logger's logged-actor set
  (`Market.order_event_filter`; events were only ever read back for
  `--log-actors` actors, default 1), and the per-command `isinstance`
  checks in the prune/take_turn loops became exact-class checks (ABC
  `__instancecheck__` was ~1% of wall). Still open: ~65-70k
  `cancel_order` calls/turn each rebuilding the whole book list —
  lazy-delete (mark-dead + id index) is the contained fix. (Stale-claim
  correction: matching does **not** re-sort uncrossed books — the sort is
  guarded — and `list.pop(0)` was already replaced by index cursors. The
  remaining unconditional matching costs are the dead-book union via
  `volume_history` keys, which is self-perpetuating, and an O(book)
  quantity sum per commodity for scarcity pressure.)
- Per-turn cost grows ~28-33% over the first ~150 turns then plateaus
  (economy warm-up, not a leak).
- Profiling on this box: `perf` is blocked (`perf_event_paranoid=4`) and
  py-spy cannot read 3.14t — use CPU-accounting (`/proc/<pid>/stat` deltas,
  pidstat) and stock-interpreter py-spy for serial attribution.

## Reference bench numbers (single-thread, 50-turn driver)

| Config | ms/turn (pre-campaign) | ms/turn (current) |
|---|---|---|
| P=5, A=80, S=2/planet | 89 | 54 |
| P=10, A=20, S=2/planet | 86 | 33 |
| P=40, A=20, S=2/planet | 937 | 149 |
