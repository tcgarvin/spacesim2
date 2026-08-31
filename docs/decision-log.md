# Decision Log

Append-only record of closed decisions, postmortems, and landed campaigns.
Newest first. Open work lives in `TODO.md`; current reference docs live
alongside this file.

## 2026-08-31 — Perf campaign: scaling toward 500 planets × 100 actors × 1000 ships

**Landed across two waves; target scale now runs at ~3.2 s/turn (was ~45+).**
- Wave 1 (2026-07-12, aaf9350): cached market quotes, identity-hashed
  commodities, memoized brain math → ~1.8x. C/Rust rewrite rejected.
- Wave 2 (2026-08-31, e6c6ddb..2800f43): navigation module with shared
  distance/fuel caches, 500-planet setup, bounded market/logger memory,
  incremental best quotes, whole-turn BrainCache + producer index, single-pass
  exporter, per-turn trade-signal index → 45 → 8.8 s/turn (P=40 bench
  937→151 ms/turn).
- Order-churn pruning (1867675): 66.6% of cancels were identical same-turn
  reposts; dropping the no-op pairs cut book mutations ~10x (~8-10% turn
  time). Lesson: kept orders must be re-timestamped or stable quotes gain
  permanent price-time priority over drifting drive bids (health 0.21→0.14).
- Threaded actor phase (dccfa12, `--workers N`): plain threads over
  per-planet shards on free-threaded CPython 3.14t → 8.1 → **3.2 s/turn**
  (actor phase 7.3 → 2.65 s at 12 workers), ~zero single-thread penalty.
- **Rejected: fork-per-turn worker pool** (parked branch
  `parallel-actor-phase` @ 227cba5): even after shrinking the per-turn
  state-sync blob 53 → 38 MB it managed only 6.05 s/turn — parent-side apply
  and serialization tax are structural. Findings that survive: brains carry
  cross-turn decision state; macro behavior is sensitive to inventory-dict
  iteration order; per-planet sharding needs a planet-coverage invariant.
- Still open (see `docs/performance.md`): per-planet RNG streams (~2.8x
  scaling at 12 threads — global-`random` lock is the suspect), sorted/heap
  order books.

## 2026-08-31 — Flow-based ship trading; cross-planet fuel demand largely fixed

**Verdict: fuel economy VIABLE (993f8f7).** Root cause: ships traded only the
RESIDUAL order book — with deferred end-of-turn matching, resting orders are
what the local auction rejected, so 0 of ~39,600 candidate plans survived the
gates. Execution also bought top-of-book only (~1.6 units/trip) and dumped
loads into 1-credit probe bids. Fix: TraderBrain plans on recent clearing
prices/volume, bids into the auction at plan price, accumulates cargo up to 8
docked turns, and sells at bid levels. 800-turn probe: fleet cargo margin
496 → 35,155 (71x); break-even fuel WTP 3.1 → 141 vs ~33 honest cost; fuel
volume 147 → 461 at ~32.8 ≈ replacement cost; ships ran nova_fuel_ore
arbitrage unprompted, so demand propagation emerged through trade with no
extra plumbing. Utilization 1.6 → ~10 units/trip. Residuals in `TODO.md`.

## 2026-08-31 — Analysis tooling pruned to the Tier-0/1 loop

**Marimo-era Tier-2 tooling removed (a3811c0).** The live loop is `--summary`
(Tier-0 KPI verdict) + `dev analyze` probe scripts (Tier-1);
`notebooks/analysis_template.py` is the only remaining dashboard, kept as an
optional human deliverable. ~16 one-off diagnostic notebooks pruned to a
handful of reference probes; `scripts/` and `dev-tools/` removed outright.

## 2026-08-30 — Refiner mis-siting fixed: impute extraction at expected yield

**FIXED (c0036fc).** Agent-belief bug: the make-branch of
`_imputed_unit_cost` (`core/actor_brain.py`) priced extraction recipes at
nominal yield, ignoring `resource_attribute`, so ore-poor planets believed ore
was cheap — 54 refiners clustered on attr 0.05-0.16 planets. Fix: expected
unit cost divides by the local planet attribute (`recipe_cost / (out_qty *
attr)` for both `output` and `success` effects); attr ≤ 0 → non-viable
locally. No commodity special-casing — the existing 20% entry margin does the
siting. Verified: zero refiners on ore-poor planets, 6 unit tests in
`tests/test_imputed_cost.py`, 4× 800-turn runs PASS with basic drives ≥0.97.
Its successor problem (fuel demand not propagating) closed by flow-based
trading above.

## 2026-07-12 — Ship fuel stranding: five bugs, not one

**LARGELY FIXED (fbef729 + cc95633 + 178f998).** The "correlated fleet
draw-down" decomposed into stale cross-planet orders, a hold livelock, silent
rescue bids, a maintenance deadlock, and fuel-desert idling, plus a
reserved-money leak. Round 3 found fuel (not cargo) was the money sink:
price-aware bunkering/rationing, depth-honest plans, maintenance pricing and
multi-tier repair bids → 0/5 ships broke by t500 (was 3/5); fleet mobile
through t500.

## 2026-07-12 — Imputed replacement cost anchors bids for never-traded goods

**DONE (89689ed + b68e953).** Never-traded intermediates deadlocked cold
starts (no price history → no bids → no production). Producers and consumer
drives now anchor on imputed replacement cost; consumer-side drive-bid anchor
revived the upper tiers — medicine trades ~32-37, produced in the thousands.
3× 800-turn runs: health 0.508/0.148/0.490 vs ~0.044 broken baseline, other
KPIs unregressed, all PASS. Follow-up (medicine variance) tracked in
`TODO.md`.

## 2026-07-11 — Live galaxy view replaces the 3-pane inspector

**Built (f4ebb7b → f8f686b).** The old static pygame inspector
(`ui/pygame_ui.py` + components/renderers, ~3,400 LOC) was deleted in favor
of a live MOO-II-style galaxy view (`spacesim2/ui/live/`): procgen nebula +
parallax starfield, baked painterly planets, ships gliding interpolated
between turns, live price/volume/wellbeing charts, click-to-drill info panel.
Discrete art comes from an offline AI asset pipeline (`tools/assetgen/`,
PixelLab for ships/goods, Gemini "Nano Banana" for planets) with a
palette-snap post-process for cross-provider cohesion; runtime loads only
committed PNGs. See `docs/live-view.md`.

## 2026-06-09 — Price deflation fixed: sellers floor asks at replacement cost

**Markets stopped deflating to 1 credit (58e863e).** Actors now price their
own labor into recipe costs, floor asks at replacement cost, and exit
loss-making production; buyer-side anti-deadlock fixes accompanied. Economy
settled at a stable food ~11 / tools ~25 equilibrium instead of a race to 1.

## 2026-06-06 — Shelter trade gap resolved via drive-backed WTP

**RESOLVED (073ca54, a7481a5, a86da72).** Shelter materials never traded:
brains lacked shelter/health drive coverage and had no willingness-to-pay.
Fix stack: two-layer drive WTP (deprivation stake × buffer discount) +
scarcity pressure + market-maker liquidity scaled across all commodities,
plus ship maintenance-deadlock and repositioning fixes. Shelter deprivation
crushed; ships unstuck.

## 2026-06-06 — Dev-loop tooling landed; bit-exact determinism rejected

**Tranche landed (116306a and follow-ups):** lazy pygame import (no banner on
headless runs), `dev check` umbrella (format → lint → types → pytest → short
`--summary` sim, non-mutating), and later the notebook prune (see 2026-08-31).
**Decided against bit-exact determinism:** randomness flows through
`uuid4`/set iteration; seeding the module RNG gave false determinism, so the
false `--seed` knob was dropped. Population means are stable to ~±0.05 —
assert with tolerances, never exact values. The Tier-0 verdict stays a
deliberate *catastrophe floor* (food + live market), not an aspirational
target.
