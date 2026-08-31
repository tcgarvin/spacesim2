# Per-planet parallel actor phase (perf hit list Tier 3)

Design date: 2026-08-31, against main @ 0cd3479. Companion to
`docs/perf-scale-hitlist.md` (Tier 3).

## Why fork-per-turn

A code audit (this session) confirmed:

- The **actor phase is genuinely planet-local**: every brain touches only
  `actor.planet.market` plus read-only registries. It is 97% of turn cost at
  P=100/A=100 (1568 of 1616 ms/turn measured).
- **Market matching is per-planet but must stay serial-side**: it runs *after*
  the ship phase (ships place orders mid-turn), so workers can only run actor
  decisions.
- The object graph blocks pickling planets to persistent shard workers:
  `Actor.sim` back-refs, `Market.actor_orders` keyed by live objects,
  and identity-hashed `CommodityDefinition` (`eq=False`, deliberate perf
  choice) mean object identity does not survive a naive pickle.
- **`os.fork` sidesteps all of that**: children inherit the whole graph at
  correct identities via copy-on-write. Only the *results* cross back, as
  id/name-keyed data.

Spike measurement (P=100, A=100, S=2, 12 workers, fork-context Pool created
per turn): actor phase 1568 → 418 ms/turn including fork, COW faults, pickle
and IPC; result blob ~1.7 MB, ~14 ms to unpickle. Threads are ruled out (pure
CPython bytecode, GIL-bound); persistent workers are ruled out by the object
graph.

## Turn shape

```
parent: set_turn / set_current_turn          (as today)
parent: warm lazy caches, flush exporter buffers
parent: fork pool of W workers (fork context, created per turn)
child k: reseed random; re-base _ORDER_ID_COUNTER to base + k*10**7
child k: for its planets: shuffle planet.actors, run actor.take_turn()
child k: return pickled per-planet state blob (persistent-id pickler)
parent: apply blobs; advance _ORDER_ID_COUNTER past base + W*10**7
parent: ship phase, _process_markets, export   (serial, as today)
```

Sharding: planets round-robin across workers (actor counts are uniform in
`setup_simple`; revisit with greedy bin-packing if planet sizes diverge).
Serial fallback when `workers <= 1`, on non-POSIX platforms, or when
`len(planets) < 2`.

## Hard-won sync lessons (implementation postmortem)

Three omissions each produced a real macro-KPI regression (food drive mean
health ~0.90 → ~0.70 at t200) while passing naive state comparison; all are
now synced and guarded by the round-trip test:

1. **Brain decision memory** — brains are not stateless: an industrialist's
   `chosen_recipe_id`/`turns_since_recipe_evaluation`, a market maker's
   learned `MarketMakerState` price brackets and `_last_transaction_index`
   cursor live on the brain object. Dropping them silently reset every
   actor's strategy each turn. Everything in `vars(brain)` except the
   `_cache` memoization scratch crosses the boundary.
2. **Dict iteration order is behavior** — brains iterate inventory dicts,
   so an apply that patches dicts in place (keeping old key positions)
   steers different decisions than the child actually made (a slot emptied
   and re-acquired moves to the end of a dict). Deltas therefore carry the
   child's full key order and the parent dict is rebuilt in that order.
3. **Order-event deques** are ~75% of a naive blob; only the current turn's
   events cross (both sides share the older ones), scanned from the deque's
   fresh tail to avoid COW-dirtying the retained history in every child.

Diagnostic that settled it: fork a child and deepcopy a twin from the same
parent state with identically seeded RNG, run one phase in each, and
byte-diff order-sensitive state fingerprints — child vs twin must be
IDENTICAL (decisions are pure state+RNG), and parent-after-apply vs twin
must be IDENTICAL too. Anything less regresses macro behavior even when a
normalized comparison says "equal".

## State sync layer (`core/parallel.py`)

Custom `pickle.Pickler`/`Unpickler` with `persistent_id`/`persistent_load`
externalizing: `CommodityDefinition` (by `.id`), `ProcessDefinition` (by id),
`Actor`/`Ship` (by `.name`, resolved via a name→participant map over
`sim.actors + sim.ships`), `Planet` (by name), `Simulation`, registries,
`DataLogger`. Everything else (Orders, OrderEvents, Commands, plain dicts)
pickles by value and re-links to parent objects on load.

Per-planet blob contents (the sync manifest):

- **Per actor**: `money`, `reserved_money`, `inventory.commodities`,
  `inventory.reserved_commodities`, `inventory.version`, `skills`,
  `skills_version`, `active_orders`, `market_history`,
  `food_consumed_this_turn`, `last_action`, `last_market_action`,
  per-drive metrics. Inventories and skills cross as per-key deltas plus
  the child's full key order; drive metrics cross as compact
  (field-name tuple, value tuple) pairs with the field-name tuple shared
  per metrics class so the pickle memo ships it once per blob.
- **Per market**: `buy_orders`, `sell_orders`, `actor_orders`,
  `order_events_by_actor`, `_quote_cache`, `_bid_levels_cache`,
  `drive_anchor_cache`, `scarcity_pressure`. Orders whose terms are
  unchanged but whose timestamp was refreshed (order-churn pruning
  restamps kept orders each turn) cross as a bare `{id: timestamp}` map.
  Order events cross only for actors the data logger reads (their sole
  consumer is `log_actor_market_status`); unlogged actors' parent-side
  deques lack child-phase events — never read, and retention is bounded
  and lossy by design.
- **DataLogger shard**: `_actor_turn_logs` entries for this planet's logged
  actors (merged by dict update in the parent).

Deliberately **not** synced: `price_history` / `volume_history` /
transaction history (mutated only at match time, parent-side), Navigator
state (ship phase, parent-side), per-actor brain caches (per-turn,
`id(actor)`-keyed, rebuilt anyway).

## Cross-process hazards and their fixes

- **`_ORDER_ID_COUNTER`** (module-level `itertools.count`): per-child re-base
  into disjoint ranges; parent advances past the union after applying.
- **Module-level `random`**: children inherit identical state → each child
  reseeds from `os.urandom` (the sim is explicitly non-reproducible).
- **Lazy caches** (`ProcessRegistry._producers_index`): warmed pre-fork.
- **Exporter Parquet handles**: children inherit open fds; they must never
  write or flush them. Pool workers exit without running the parent's
  atexit-registered writer closes; verify no double-flush corruption in the
  export smoke test.
- Order timestamps come from `market.current_turn` (no per-order counter), so
  tie-breaking needs no extra sync.

## Correctness testing

- **Round-trip completeness test** (the load-bearing one):
  `deepcopy(sim)` → run the actor phase in-process on the copy → extract
  blobs from the copy → apply onto the original → re-extract from the
  original → the two blob byte-streams must be identical. Any field
  `take_turn` mutates that the manifest misses shows up as a diff.
- **Parallel smoke test**: small sim, ~10 turns at `workers=2`; assert book
  orders belong to that planet's participants, money/inventory non-negative,
  and turn results structurally sane.
- Macro check: `run --turns 200 --summary` with and without workers must both
  PASS with KPIs in the same family (sim is stochastic; use tolerances).

## Performance reality (2026-08-31, 16-core host)

- P=100, A=100/planet: serial ~1.5-1.7 s/turn → parallel(12) ~1.1-1.5
  s/turn (pre-brain-sync). P=500×100×1000 (target scale), with the full
  correct sync: serial 8.9 s/turn → parallel(12) 7.9-8.9 s/turn — **par**.
  Breakdown per parallel turn at P=500: map 3.4-4.2 s (child actor turns
  0.7-2.4 s with stragglers, extract 0.7-1.5 s, snapshot 0.3 s), parent
  apply 3.3-4.2 s on a ~55 MB blob, ship+match 0.3 s.
- The limiter is not fork or child compute — it is the **sync volume**:
  brains cancel-and-repost their entire order books every turn (perf
  hit-list item 8), so per-turn "deltas" are effectively full books plus
  most actor fields (~10 MB/turn at P=100). Parent-serial apply
  (unpickle-dominated) plus child-side extract rival the actor compute
  they save. Landing item 8 (order diffing in the brains) would shrink
  blobs by ~an order of magnitude and is the prerequisite for this
  parallelism to pay at scale.
- `gc.freeze()` around the fork and `gc.disable()` in children are
  load-bearing: without them, cyclic GC in 12 forked children COW-copies
  the inherited heap and doubles turn cost after a few turns.
- Status: `--workers` is **experimental, off by default** — correct
  (round-trip-exact, macro KPIs in-family) but only ~15-30% faster at
  target scale until item 8 lands.

## Interface

- `Simulation.parallel_workers: int = 1` (set via `setup_simple` arg or
  directly); `run_turn` picks the parallel actor phase when `> 1`.
- CLI: `spacesim2 run --workers N` (default 1). UI paths stay serial.
