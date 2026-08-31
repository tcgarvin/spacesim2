# Performance hit list — scaling to 500 planets × 100 actors × 1000 ships

> **Progress 2026-08-31** (branch worktree-perf-scale-analysis, 5 commits on
> top of 993f8f7): Tier 0 items 1-4 and Tier 1 items 5-7,9 and Tier 2 items
> 10-12 largely landed — navigation module (shared distance/fuel caches,
> capped reposition survey), 500-planet setup (procedural names, scaled map),
> bounded market/logger memory + incremental best quotes, whole-turn
> BrainCache + producer index, single-pass exporter volumes. Benches:
> P=40 937→151 ms/turn, P=10 86→34, P=5/A=80 89→54. Wave 3 added a
> per-turn trade-signal index (per-commodity supply/demand candidates,
> top-8-value ∪ 8-nearest destination shortlists, cold-galaxy early-out):
> 500×100×1000 went 45 → **8.8 s/turn**, with ships now ~21% of turn cost
> and actors dominating again. Tier 3 (per-planet parallelism) not started —
> it is the next lever (actor phase is the linear floor, ~6-7 s/turn at
> target scale, embarrassingly parallel per planet).
>
> **Item 8 landed 2026-08-31** (order churn pruning): measurement showed
> 66.6% of all cancels were followed the same turn by a repost with
> identical side/commodity/price/quantity. `prune_unchanged_order_commands`
> (commands.py, called from `Actor.take_turn`) drops those cancel+repost
> pairs and keeps the standing order — a market-state no-op, since cancel
> refunds exactly what the repost re-reserves and no other actor acts
> between the two commands. Identical-pair churn 66.6% → 2.7% (residual is
> ship-side direct calls, ~16 pairs/turn, structurally different: ships
> recompute quantities from live post-cancel money/cargo — left alone).
> Bench: P=10 37.2→33.3, P=40 161.3→149.1 ms/turn (~8-10%); the larger
> payoff is ~10x fewer book mutations for the parked
> `parallel-actor-phase` state-sync blob. Behavior lesson: a first version
> let kept orders retain their original timestamp, which gave stable quotes
> (market makers) permanent price-time priority over drive bids whose
> quantities drift — replicated sims showed health mean_health dropping
> 0.21→0.14 (n=8 vs n=13, t≈2.8) via the thin medicine market. Fixed by
> stamping kept orders with the current turn (as a repost would) and
> breaking exact (price, timestamp) ties randomly at match time, restoring
> the rotation the per-turn actor shuffle used to provide.
>
> **Tier 3 update 2026-08-31**: a fork-per-turn parallel actor phase was
> built, verified correct, and **parked on branch `parallel-actor-phase`**
> (commit 227cba5) rather than merged: at target scale it only breaks even
> (8.9 → ~8.4 s/turn) because cancel-and-repost brains make the per-turn
> state-sync blob ~55 MB and parent-side apply eats the parallel win.
> Hard-won findings that survive regardless: brains carry
> cross-turn decision state (recipe choice, learned price brackets), and
> macro behavior is measurably sensitive to inventory-dict iteration
> order in brains.
>
> **Tier 3 LANDED 2026-08-31 — threaded actor phase** (`--workers N`,
> `core/parallel.py`, docs/threaded-actor-phase.md). Post-item-8
> measurement showed the fork branch's blob did NOT shrink (~53 MB; churn
> was never dominant, and pruning's timestamp restamps counted as changes);
> a targeted shrink pass (53→38 MB, checkpointed on the branch) got it to
> 6.05 s/turn vs 8.1 serial. A free-threaded probe then beat that outright:
> plain threads over the same per-planet shards on CPython 3.14t, no
> serialization at all — **3.2 s/turn at 12 threads** (actor phase 7.3 →
> 2.65 s), ~zero single-thread penalty, books consistent. That design is
> now on main; the fork branch is superseded. Scaling is ~2.8x at 12
> threads — global-`random` lock contention and shared-object refcount
> traffic are the suspects; per-planet RNG streams are the next lever.

Analysis date: 2026-08-30, against main @ 178f998. Sources: cProfile + scaling
sweeps (driver timing `sim.run_turn()` directly) and a line-level code audit.

## Where we stand

- Actor phase is healthy: **~209 µs per actor-turn, exactly linear** in total
  actor count (P-sweep with S=0 has log-log slope 1.005). 50,500 actors →
  ~14 s/turn.
- Ship phase is the problem: the 178f998/cc95633 fuel-safety logic added O(P)
  galaxy scans *inside* already-quadratic planners. Ships are 41% of runtime at
  P=15/S=45 and per-ship cost grows ~O(P^1.2) empirically, O(P²·C)–O(P³·C)
  structurally. At P=40 the ship phase measured **63× slower** than pre-rework.
- Best-estimate target-scale cost today: **35–65 s/turn ship-dominated**, and
  that is a floor — one `_find_reposition_target` call at P=500 evaluates ~3.7M
  trade plans (structurally minutes per call; it fired on ~15% of ship-turns).
- Several unbounded accumulators will OOM a 500-planet, 1000-turn run outright.
- Setup code silently caps at 100 planets.

## Tier 0 — blockers (can't even run the target scale)

1. **Ship reposition search is O(P²·C) with O(P) fuel scans inside → O(P³·C)**
   — `ship.py:1156-1209` (`_find_reposition_target`), reached from
   `decide_travel` (ship.py:1023). Origin × destination × commodity triple
   loop; each `_evaluate_trade_opportunity` (ship.py:588, 1.92M calls in a
   50-turn profile) calls `_fuel_safe_destination`/`_min_escape_fuel`
   (ship.py:233-245, O(P)) and uncached `get_bid_levels` (sort per call).
   Fix: once per turn, compute shared tables — P×P distance matrix,
   per-planet fuel-purchasable bitmap, per-planet nearest-fuel distance,
   per-planet best-export/import quote vectors — and have all ships plan
   against those snapshots; and/or restrict candidate origins to k-nearest.
   Also memoize `_evaluate_trade_opportunity` per (origin, dest, commodity,
   turn) across ships.

2. **Unbounded `order_events` retaining Orders** — `market.py:96,163`.
   ~20 events/actor/turn, never trimmed, events hold strong refs to Orders.
   Target scale ≈ 10⁹ objects → OOM. Bound with deque(maxlen) or make
   logging opt-in.

3. **Unbounded `DataLogger._actor_sim_log`** — `data_logger.py:33`. Keyed by
   (turn, actor), never flushed; also `log_actor_market_status` does market
   queries per actor per turn even when discarded. Flush per turn to disk or
   cap.

4. **Setup silently mis-sizes the galaxy** — `simulation.py:182` caps planets
   at 100 fictional names; `_generate_separated_positions`
   (simulation.py:189-241) can't fit 500 disks at min_distance=10 on a
   100×100 map and returns fewer positions after O(n²) rejection sampling.
   Generate names procedurally, scale the map or shrink min-distance, use a
   grid/Poisson-disc sampler.

## Tier 1 — big single-process wins

5. **Widen `BrainCache` to a whole actor-turn** — a fresh cache is built in
   each `decide_economic_action` and `decide_market_actions`
   (colonist.py:35/288; same for industrialist), so
   `_best_process_and_raw_profit` (colonist.py:148, still 20% cum) and
   `_replacement_cost` (actor_brain.py:321, 8%) recompute ~1.5× per turn.

6. **Incremental best-bid/best-ask per (market, commodity)** — the
   `_quote_cache` (market.py:130) is invalidated on every book mutation, and
   every brain cancels + reposts its full order set every turn
   (colonist/industrialist/market_maker_2/ship), so hit rate is poor and the
   O(B) max/min scan (market.py:673-678) reruns constantly; B grows with A.
   Keep sorted books or maintain best-quote incrementally on insert/cancel/
   fill. Also: ships call `market.get_bid_ask_spread` directly (5.6M calls)
   and bypass the actor-side `BrainCache` memo.

7. **Reverse index `commodity → producing processes`** —
   `actor_brain.py:350/517` scan `all_processes()` (42 entries) to find
   producers of one commodity; `process.py:148 get_processes_producing`
   exists but is unused there.

8. **Stop cancel-and-repost of unchanged orders** — every brain rebuilds its
   entire book every turn, paying order allocation, uuid4 (market.py:46),
   event recording, and reserve/unreserve for quotes that didn't change.
   Diff against last turn's orders; integer ids via itertools.count.
   **DONE 2026-08-31** — see progress note at top.

9. **Object churn** — `all_commodities()` (commodity.py:61) and
   `all_processes()` (process.py:144) return fresh lists per call, thousands
   of times per turn (also rebuilt inside ship loops via
   `_get_tradeable_commodities`, ship.py:200/883/895/950). Return cached
   tuples. `calculate_distance` (ship.py:1254, 4.2M calls) → distance matrix
   (covered by #1).

## Tier 2 — per-turn overhead and long-run degradation

10. **Exporter volume aggregation** — `exporter.py:140-173` rescans the full
    transaction history per planet × commodity per turn: O(P·C·1000) ≈ 2×10⁷
    comparisons/turn at target scale (measured +108% turn time with
    `--log-all-actors` at P=10). Aggregate this turn's transactions in one
    pass.

11. **`has_history` is O(T) per call** — market.py:745 builds a list over the
    entire price history; called per commodity per market-maker per turn
    (market_maker_2.py) and P·C times in summary.py:134. Track a counter.
    Related: `price_history`/`volume_history` (market.py:371-381) grow one
    entry per commodity per turn forever — cap or use running aggregates.

12. **Main-loop scaffolding** — simulation.py:470 unconditional print;
    `_print_status` does four O(A) passes per turn; run.py:198 redirects
    stdout to a never-truncated StringIO for the whole run (hundreds of MB at
    P=500); global `random.shuffle` of 50k actors/1000 ships per turn
    (simulation.py:478/485) — shuffle per planet instead (also unlocks
    locality for parallelism). `_trim_transaction_history` (market.py:121)
    visits every actor per market per turn — use deques.

13. **Per-turn full re-sort of order books** — market.py:388-397 sorts both
    sides for every commodity ever traded (loop unions `volume_history`
    keys, so even dead books); `list.pop(0)` per fill is O(B). Falls out of
    #6 if books become sorted/heaps.

## Tier 3 — the big lever after the above: per-planet parallelism

Actor decisions and market matching are already cleanly per-planet
(`_process_markets` is a loop over independent Markets). Measured actor cost
is flat per actor, so parallelizing over planets is near-linear headroom
(~14 s/turn actor phase → seconds on a pool). Coupling points to resolve:

- Ships read remote markets mid-turn (ship.py:196/895-915/1083-1120) → plan
  against per-turn quote snapshots (same infrastructure as #1).
- Ship arrival/departure mutates two planets (ship.py:776, 844-851) → defer
  to a serial barrier phase.
- Single global DataLogger → shard per planet, merge at barrier.
- Global `random` module state everywhere → per-worker RNG streams (sim is
  already non-reproducible, so this changes outcomes but not guarantees).
- Registries (commodity/process/skills) are read-only after load — safe to
  share.

## Measured reference numbers (current main)

| Config (50 turns) | ms/turn |
|---|---|
| P=5, A=20, S=2/planet | 24.0 |
| P=40, A=20, S=2/planet | 377.2 |
| P=40, A=20, S=0 | 176.5 |
| P=5, A=80, S=2 | 88.7 |

Exponents: planets-with-ships 1.37, planets-no-ships 1.005, actors 0.94.
Per-turn cost grows ~28-33% over the first ~150 turns then plateaus (economy
warm-up, not a leak). Profile artifacts live in the session scratchpad
(`driver.py`, `sweep2_results.jsonl`, `profile_report2.txt`).
