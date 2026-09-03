# Decision Log

Append-only record of closed decisions, postmortems, and landed campaigns.
Newest first. Open work lives in `TODO.md`; current reference docs live
alongside this file.

## 2026-09-02 - Live UI: simulation moved off the render thread

Landed on branch `spiral-galaxy-star-lanes`. At 100 planets `run_turn` ran
inline in `Director.update` on the render thread and took longer than the
1 turn/s pacing, so the catch-up loop ran several turns per frame and the
UI froze for seconds. A paused frame also re-swept every actor's drives
for wellbeing twice per frame.

Decision: a thin protocol, not a whole-sim snapshot. A `SimulationWorker`
thread owns the sim and publishes one immutable `TurnFrame` per turn
boundary, sized to what the screen shows. Drill-down detail rides along
only for subscribed entities. The director paces turn requests with no
catch-up debt and interpolates ships between frames. The wellbeing sweep
runs once per turn and is shared with the history recorder. The render
thread never reads core objects; a test pins this by stubbing the sim out
after a frame is built. The GIL means a running turn still steals render
time; smoothness at this scale needs a faster sim (`docs/performance.md`).

## 2026-09-01 - Exact-caching passes on the serial path

Landed on main. Three passes replaced repeated scans with caches that
return what a fresh computation would (the current design is described in
`docs/performance.md`): finer `BrainCache` invalidation groups, a ranked
colonist scan, per-turn trade-history memos, a float stdev in
`get_30_day_standard_deviation`, the `replacement_quote_parts` split,
lazy order cancels, order-event gating on logged actors, precomputed
process-definition tuples, and a shared per-market process quote table
keyed on `(turn, quote_version)`. The first pass gained about 1.2x on the
P=40 bench; each later pass gained 1-7% serial at target scale and did not
regress under threads.

Rejected: sharing quote-derived valuations across actors per
`(planet, turn)`. Order posting is immediate and only matching is
deferred, so the shared snapshot would freeze mid-phase book moves. The
user wants actor-specific valuation intact.

## 2026-09-01 - Spike: spiral galaxy with star lanes replaces the open plane

Landed on branch `spiral-galaxy-star-lanes`. Planets were scattered on a
square with straight-line travel between every pair. Now `core/galaxy.py`
places them on a log-spiral and builds a connected planar lane graph
(Delaunay, then Kruskal MST, then a Gabriel-graph filter sampled at
`lane_density`). `Navigator` is the single seam: it runs all-pairs
Dijkstra over the lanes, so every brain that asks for distance gets route
length with no per-brain change, and it raises if the network is ever
disconnected. Ships fuel the whole route at departure and fly past
intermediate planets; per-hop docking is out of scope. Default galaxy size
rose from 5 to 100 planets for `run` and `ui`; `dev check` stays at 5.
5-planet KPIs were unchanged within noise. `galaxy.json` is exported
alongside `planet_attributes.json`.

## 2026-08-31 - Perf campaign: scaling toward 500 planets

Landed across two waves; target scale went from 45+ s/turn to about 3.2.

- Wave 1 (aaf9350): cached market quotes, identity-hashed commodities,
  memoized brain math. C/Rust rewrite rejected.
- Wave 2 (e6c6ddb..2800f43): navigation module with shared distance/fuel
  caches, bounded market and logger memory, incremental best quotes,
  whole-turn `BrainCache` and producer index, single-pass exporter,
  per-turn trade-signal index.
- Order-churn pruning (1867675): two thirds of cancels were identical
  same-turn reposts, so the no-op pairs are dropped. Kept orders must be
  re-timestamped, or stable quotes gain permanent price-time priority over
  drifting drive bids.
- Threaded actor phase (dccfa12, `--workers N`): plain threads over
  per-planet shards on free-threaded CPython 3.14t, no single-thread
  penalty.
- Rejected: fork-per-turn worker pool (parked branch `parallel-actor-phase`
  at 227cba5). Parent-side apply and serialization cost are structural.
  Findings that survive: brains carry cross-turn decision state; macro
  behavior is sensitive to inventory-dict iteration order; per-planet
  sharding needs a planet-coverage invariant.
- Later ruled out as thread-scaling causes: the global `random` lock and
  refcount traffic on shared definitions. See `docs/performance.md`.

## 2026-08-31 - Flow-based ship trading

Landed (993f8f7). Ships traded only the residual order book. With deferred
matching, resting orders are what the local auction rejected, so almost no
candidate plan survived the gates, execution bought top-of-book only, and
loads were dumped into probe bids. Fix: `TraderBrain` plans on recent
clearing prices and volume, bids into the auction at plan price,
accumulates cargo over several docked turns, and sells at bid levels. The
fuel economy became viable and ships ran ore arbitrage unprompted, so
demand propagation emerged through trade with no extra plumbing. Residuals
in `TODO.md`.

## 2026-08-31 - Analysis tooling pruned to the Tier-0/1 loop

Marimo-era Tier-2 tooling removed (a3811c0). The live loop is `--summary`
plus `dev analyze` probe scripts; `notebooks/analysis_template.py` is the
only remaining dashboard. `scripts/` and `dev-tools/` were removed.

## 2026-08-30 - Refiner mis-siting fixed: impute extraction at expected yield

Fixed (c0036fc). The make-branch of `_imputed_unit_cost`
(`core/actor_brain.py`) priced extraction recipes at nominal yield and
ignored `resource_attribute`, so ore-poor planets believed ore was cheap
and refiners clustered there. Expected unit cost now divides by the local
planet attribute for both `output` and `success` effects; an attribute of
zero is non-viable locally. No commodity special-casing; the existing 20%
entry margin does the siting. Tests in `tests/test_imputed_cost.py`.

## 2026-07-12 - Ship fuel stranding: five bugs, not one

Largely fixed (fbef729, cc95633, 178f998). The correlated fleet draw-down
was stale cross-planet orders, a hold livelock, silent rescue bids, a
maintenance deadlock, fuel-desert idling, and a reserved-money leak. Fuel,
not cargo, was the money sink: price-aware bunkering and rationing,
depth-honest plans, maintenance pricing, and multi-tier repair bids ended
ships going broke.

## 2026-07-12 - Imputed replacement cost anchors bids for never-traded goods

Done (89689ed, b68e953). Never-traded intermediates deadlocked cold starts:
no price history, so no bids, so no production. Producers and consumer
drives now anchor on imputed replacement cost, which revived the upper
tiers. Medicine variance follow-up is in `TODO.md`.

## 2026-07-11 - Live galaxy view replaces the 3-pane inspector

Built (f4ebb7b to f8f686b). The static pygame inspector was deleted for a
live MOO-II-style galaxy view (`spacesim2/ui/live/`). Art comes from an
offline asset pipeline (`tools/assetgen/`) with a palette-snap
post-process; runtime loads only committed PNGs. See `docs/live-view.md`.

## 2026-06-09 - Price deflation fixed: sellers floor asks at replacement cost

Markets stopped deflating to 1 credit (58e863e). Actors price their own
labor into recipe costs, floor asks at replacement cost, and exit
loss-making production; buyer-side anti-deadlock fixes accompanied.

## 2026-06-06 - Shelter trade gap resolved via drive-backed WTP

Resolved (073ca54, a7481a5, a86da72). Shelter materials never traded
because brains had no shelter or health drive coverage and no
willingness-to-pay. Fix: two-layer drive WTP (deprivation stake times
buffer discount), scarcity pressure, market-maker liquidity across all
commodities, and ship maintenance-deadlock and repositioning fixes.

## 2026-06-06 - Dev-loop tooling landed; bit-exact determinism rejected

Landed (116306a and follow-ups): lazy pygame import, the `dev check`
umbrella, and later the notebook prune. Decided against bit-exact
determinism: randomness flows through `uuid4` and set iteration, so
seeding the module RNG gave false determinism and the `--seed` knob was
dropped. Assert with tolerances. The Tier-0 verdict is a catastrophe floor
(food and a live market), not an aspirational target.
