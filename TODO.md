# TODO

## Cross-planet fuel demand doesn't propagate; fuel supply is thin

**Status:** OPEN (2026-08-30). Successor to the refiner mis-siting bug (below,
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
