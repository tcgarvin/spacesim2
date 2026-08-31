# TODO

## Cross-planet fuel demand doesn't propagate; fuel supply is thin

**Status:** LARGELY FIXED (2026-08-31) via the flow-based ship trading rework
(see below). 800-turn probe run `fuelwtp2`: fleet cargo margin 496 → 35,155
(71×), break-even fuel WTP 3.1 → 141 vs ~33 honest cost → **VIABLE**; fuel
volume 147 → 461 units trading at avg 32.8 ≈ replacement cost; ships ran
nova_fuel_ore arbitrage unprompted (33 units at 3 → 12), so demand propagation
emerged through trade itself (fix direction 1) with no extra plumbing.
Verdict PASS, health drive 0.80 at t800 (vs 0.49 baseline).

**Residuals to watch:**
- 2/5 ships ended lean (6 and 181 credits) despite positive per-trip margins —
  they overpaid for fuel (avg ~50-54/unit vs fleet 42); possible remaining
  bunkering/pricing leak.
- Fleet still pays avg 42 vs 33 best-planet honest cost.
- Fuel-delivery accumulation overbuys: a fuel-run plan's "held" count only
  sees tank overflow above fuel_capacity, so deliverers fill the tank plus
  the plan quantity before departing.

**Root cause (found 2026-08-31):** ships traded only against the RESIDUAL
order book. With deferred end-of-turn matching, resting orders are what the
local auction rejected — no asks for goods in demand, lowball leftover bids —
while real supply/demand clears in the per-turn flow. Gate instrumentation
showed 0 of ~39,600 candidate plans surviving: 49% no resting origin ask, 37%
no resting dest bid above the origin ask, 14% money reserves. Execution also
bought at best-ask price only (fills only the cheapest ask level), departed
with any nonzero cargo (~1.6 units/trip), and dumped whole loads at the top
bid (matching executes at the SELL price, so a 1-credit probe bid could
absorb a full cargo at 1 credit).

**Fix (flow-based TraderBrain, `core/ship.py`):** plans price/size from
recent clearing prices and volume (`has_price_signal` + volume_history
guarded), bid into the auction at the plan price (matching executes at each
seller's ask, never above the bid), accumulate cargo over up to
ACCUMULATION_PATIENCE=8 docked turns before flying to the plan destination,
and sell via `_place_flow_sell_orders` (premium resting bids captured at
each level's price, remainder rested at 0.9× the recent clearing price).
Hold-vs-sell and travel valuations also use max(bid, flow price).

**Original statement (2026-08-30):** Successor to the refiner mis-siting bug (below,
now FIXED). With imputation corrected, refiners no longer cluster on ore-poor
planets — but in some galaxies nobody refines fuel *anywhere*, including
ore-rich planets, and that is locally rational: fuel's honest replacement cost
is ~33 (4 ore × ~5.6 imputed + labor + tools) while the ore-rich planet's local
price signal is ~6 with only 1-credit MM probe bids. The real demand — ships
bidding 8–12 — sits docked on ore-poor planets with no mechanism to signal
across the gap. Note ships' 8–12 fuel bids also sit below the ~33 honest cost,
which raises a design question: can ship trade margins pay for fuel at its true
labor cost, or does the fuel chain need better yields / ship WTP?

**Evidence:** `notebooks/ship_dead_fleet_probe.py` run post-fix: zero fuel
recipes chosen galaxy-wide, ships solvent (~1,100 credits) but immobile with
standing bids. However, 4× 800-turn `--summary` runs all PASS with fuel
*trading* (avg 18.6–59.2) and ~15 units end-state inventory — so the fuel
economy survives in most galaxies, thinly. High price variance (59 in one run)
says supply is marginal.

**Viability test: DONE (2026-08-30).** Probe:
`notebooks/ship_fuel_wtp_probe.py` against 800-turn run `fuelwtp`
(`--log-actor-types ship trader`). Findings:

- **Realized** fleet economics are wildly unviable: 5 ships, 56 trips, total
  cargo margin 496 credits, 160 fuel burned → break-even fuel WTP **3.1/unit**
  vs best-planet honest cost **32.1** (Corvenn, attr 0.94). Ships actually
  paid avg **60/unit** (scarcity bunkering; galaxy avg fuel trade 35, max
  300) — they fly by burning down starting capital.
- **But the unviability is endogenous, not structural.** Per-unit spreads
  ships did capture are healthy (tools +15.6, clothing +17.5, bldg mat +9.2),
  and big deep arbitrage sat unharvested all run: clothing avg 8.1 at Krylos
  (~14 sell orders standing) vs 64.3 at Tavrelis (~49 buy orders, 0.6
  units/turn trading). The failure is **volume**: the fleet moved 92 cargo
  units in 800 turns against 100-unit holds — ~1.6 units/trip, ~2% hold
  utilization. At 20 units/trip on observed spreads, margin/trip is ~300+ vs
  ~3 fuel/trip × 32 honest cost ≈ 96 — comfortably viable.

**Revised diagnosis:** make-ships-profitable is upstream of make-fuel-work.
Two levers, in order:
1. **Hold utilization / plan sizing**: find why depth-honest plans buy ~1-2
   units when order books show real multi-unit depth at profitable spreads
   (top-of-book-only sizing? reserved-money caps? the 15% `is_profitable`
   threshold interacting with fuel scarcity prices?). Fixing this raises ship
   WTP above honest fuel cost and funds the fuel chain from real demand.
2. **Fuel-side**: ships overpay 2x (avg 60 vs 35) via scarcity bunkering while
   refiners exist essentially only on the ore-rich planet; revisit after (1) —
   with real margins ships can afford 32-fuel and demand-propagation (ore
   arbitrage, repositioning) becomes worth plumbing.

**Fix directions to explore (in "pure" order of preference):**
1. Ship-side ore/fuel arbitrage: ships already haul transportable goods — if
   they bid on cheap ore at ore-rich planets and haul it toward their own fuel
   demand, the price signal propagates through trade itself.
2. Ships repositioning toward cheap-fuel planets to bunker (partially exists —
   check why it didn't rescue the probe galaxy).
3. Recipe/yield rebalance if fuel's honest cost structurally exceeds ship WTP.

## Fuel refiners site themselves on ore-poor planets

**Status:** FIXED (2026-08-30). Root cause was an agent-belief bug: the
make-branch of `_imputed_unit_cost` (`core/actor_brain.py`) priced extraction
recipes at nominal yield, ignoring `resource_attribute`, so ore-poor planets
believed ore was cheap and refiners clustered there (54 on attr 0.05–0.16
planets). Fix: expected unit cost now divides by the local planet attribute
(both `output` and `success` effects reduce to `recipe_cost / (out_qty *
attr)`); attr ≤ 0 makes the recipe non-viable locally; feature-off
(`--no-planet-attributes`) unchanged. No commodity special-casing — the
existing 20% entry margin does the siting.

**Verification:** probe shows zero refiners on ore-poor planets and no false
entries; 6 new unit tests in `tests/test_imputed_cost.py`; 4× 800-turn
`--summary` runs all PASS with food/clothing/shelter drives ≥0.97 mean health
and health-drive within its known variance band.

## Procurement bids for never-traded intermediates should use imputed replacement cost

**Status:** DONE (2026-07-11), committed as 89689ed + b68e953 (consumer-side
anchor). Verification: 3× 800-turn runs → health 0.508 / 0.148 / 0.490 (vs
~0.044 broken baseline; target ~0.54), medicine produced in the thousands,
food/shelter/clothing KPIs unregressed, all verdicts PASS.

**Remaining follow-up:** high run-to-run variance on health (one run landed at
0.148 with medicine spiking to 139 and stockpiling). Likely lever: widen the
gap between medicine's cost floor and the ~40 consumer WTP so it distributes
instead of stockpiling. Scoring probe: `notebooks/chem_score_probe.py`
(`uv run python notebooks/chem_score_probe.py`, ~70s).
