# TODO

Genuinely open work only. Closed postmortems live in `docs/decision-log.md`;
perf levers live in `docs/performance.md`.

## Land (2026-09-10)

- Migration: actors move between planets and claim from the destination's
  `free_lands`. Needs a release path (`Planet.add_actor` only claims today)
  and a rule for a full planet (`NoFreeLandError`).
- The min-one-unit output floor in `ProcessCommand.execute` means a low
  land draw barely affects 1 to 3 unit recipes (`harvest_wood`,
  `gather_fiber`, mining) and bites `gather_biomass` (8) and `farm_biomass`
  (64) hard. Decide whether to keep that asymmetry.
- Refiner siting now imputes ore cost from the actor's own draw, not the
  planet mean. Check the refiner-on-rich-planet fraction at 100 planets.

## Ship trading residuals (post fuel-station and cost-basis selling rework, 2026-09-08)

- Plan expectations are inflated: median expected profit 1346 per plan trip
  versus a median realized cycle net of 0 (mean +147) at 100 planets
  (`trip_probe.py` in the 2026-09-08 session). Plan revenue counts
  destination bid depth plus 15 turns of flow at a 10% haircut; the ladder
  on arrival realizes far less. Value plans with `_realizable_value` plus a
  shorter flow horizon and see whether fewer, better plans beat more plans.
- Refuel repositions cost a mean 858 credits per cycle (fuel bought at the
  station plus the leg) and happen 270 times per 300 turns. Ships still
  arrive short at stations that other ships drained between departure and
  arrival (89% of the residual spiked bids). A station test on operator
  stock or a depth margin above one ship's fill would cut this.
- Bunker orders reserve up to 80% of cash for a full 60-unit tank whenever
  fuel is cheap; tanks hold ~2.6k units fleet-wide (~100k credits) at turn
  400. Cap bunkering at two round trips' worth unless cash is above the
  capital floor.
- Add-on cargo (2026-09-07) is chosen once per plan and not re-bid on later
  accumulating turns; a partly filled add-on flies as is. Re-bidding the
  shortfall is untested.
- Operators still hold ~2k fuel units at turn 400 and never post delivery
  bids that a ship acts on; fuel does not move between planets by ship.
- Fuel burn rounds twice: `Ship.fuel_required` is
  `ceil(ceil(distance / 20) / fuel_efficiency)`, layered in fbef729 on the
  older `calculate_fuel_needed`. On lane hops (mean 41 distance) a
  1.2-efficiency ship burns 2.56 fuel per leg against 2.60 for a 1.0 ship.
  Measured over 3030 real legs of an 800-turn 100-planet run, a 20%
  efficiency gain saves 14.3% of fleet fuel under the double ceil and 18.5%
  under a single `ceil(distance / (20 * efficiency))`. Legs at 3 fuel or
  less are 30% of legs but 8% of fuel burned, so efficiency matters for
  the fleet, not for the short staple hops. Move to a single ceil and a
  named distance-per-fuel constant (travel time keeps its own 20 per turn);
  a 20-25% fuel saving is then the constant at 24-25 or the efficiency
  range shifted from [0.8, 1.2] to [1.0, 1.5]. Keep planning and departure
  on the one function.
- Ships sit docked a median 10 turns per visit (`ACCUMULATION_PATIENCE` is
  8) while rich planets rest 500-1700 units of processed_food asks at 1-3
  credits; the delivery cycle is 22 turns (12 transit) and the median load
  is 19 of 100. Unverified: if the docked turns are spent accumulating
  against a book that already covers the plan, lifting the resting asks in
  one turn when depth covers the quantity would shorten the cycle and
  raise fleet throughput up to about 2x. Probe where the docked turns go
  (accumulating, laddering the sell, waiting on fuel) before changing it.

## Food imports to biomass-poor planets (2026-09-08)

Displacement bids landed: an actor that hand-makes a drive good posts a
standing bid for every material of that drive, priced with its labor
opportunity cost. Poor-planet processed_food resting depth rose from a
median 6-15 to 14-140 units, but ship imports there stayed at about 0.15
units a turn against 100 eaten. Left open:

- Local hand-food sellers fill most of the new bids at 10-15 credits, so
  the resting depth a ship can plan against is 14-50 units, which does not
  cover fuel for even a 2-3 fuel hop; every processed_food plan the gate
  probe saw sized under 25 units and lost money. The 34 units a turn of
  hand-cooked `food` that clears on those planets is the real demand for
  the drive, and no ship counts it.
- 21-24 of about 60 docked ships have no plan at all: median money 19-158
  credits and tanks at 4-6% of capacity, so every pair fails the cash
  gate. Any fleet-share goal is capped by this underclass first.
- Ships hauled 60% fewer biomass units after the change (A/B, 4 reps, 400
  turns: 318 -> 128 per 50-turn window) while ship sales value in the same
  window was flat to up (249k -> 266k credits in one paired export): the mix
  moved to fiber, tools and building materials. Confirm with a value KPI in
  the summary before treating `ship_delivered_total` as a regression.

## Medicine / upper tier (post 2026-09-03 fixes)

The WTP ceiling and phantom-bid entry are fixed (`FoodDrive.security`,
`_output_unit_value`). Left open:

- Producers still outrun consumption: fewer, more capable medicine makers
  keep stock growing. Entry scoring is inventory-blind; a producer sitting on
  unsold output still scores positive when the depth price covers cost. A
  stock-aware discount on output value is the next lever.
- `ship_supplies` demand now comes from the proactive repair kit
  (`_buy_repair_kit`, 2026-09-08); check that producers enter the recipe.
- nova_fuel clears at 58-287 for ships while they resell at ~50. Probe the
  refiner side: is the t50-150 spike a supply gap?
- Prosperity (post 2026-09-06 surplus money discount; see the decision
  log): processed food, quality clothing, prefab housing, and luxury goods
  trade; advanced medicine (coverage ~0.03) and computers (~0.01) do not.
  Electronics is 55-85% of their cost and is imputed at 1.6-2.5x its own
  thin ask. Rare-earth miners never enter because a miner scores ore at
  the ore's own thin price, never the refiner's netback
  (`notebooks/rare_earth_chain_probe.py`); a netback output valuation for
  raw materials is the next lever. Shelter need lost ~0.04 health to
  prefab makers absorbing building materials on wood-poor planets
  (`notebooks/substitute_bound_probe.py`); a 9x substitute bound did not
  fix it, supply on wood-poor planets is the question. Prosperity food
  coverage is now coverage of hand-cooked `food`, the premium good.
- Food refresh (2026-09-07, see the decision log): the industrial track
  exists but barely runs at 300 turns on 12 planets. `process_food` is
  0.1-0.3% of process runs and chemical plants stand on 2-5 of 12 planets;
  heavy machinery trades at 175-260 credits, so a plant is a 200+ credit
  build plus upkeep. Hand food carries the staple almost everywhere. Open:
  (1) the transition is slow, not blocked: a 600-turn run had 137 plants
  and 162 farms on 12 planets, but common metal reached 217 credits and
  the health drive fell to 0.25 (WARN), so metal supply under machinery
  demand and the medicine chain are the next bottlenecks; 100 planets
  unchecked; (2) a plant out-produces its planet (one held
  16,990 processed food at turn 300) and the surplus is not exported.
  Answered 2026-09-07 (see the decision log): at 100 planets it never
  leaves. Not per-unit margin on the demand side; substitute bids now put
  45 resting bids per poor planet at the discounted food price and ships
  still carry 10 units per 100 turns. 92% of (origin, destination) pair
  evaluations fail on fuel or cash (`notebooks/processed_food_export_pairs.py`),
  and the shippable spread is 1-3 credits, one hop's worth. Next: fleet
  fuel and cash at plant planets, then plan ranking by margin per
  trip-turn instead of absolute profit. Then, once imports land, do
  biomass-poor planets still build farms? A farm scores against its own
  planet's biomass price, where hand gathering at attribute 0.2 yields
  1.6 per turn, so a local farm looks good even when a farm two
  lanes away yields 64; (3) latent numeraire
  risk: `_cheapest_effective_price` anchors lambda on the cheapest food, so
  when plants become common and the staple reaches ~2 credits every need
  drive's credit WTP falls in proportion while seller floors stay
  wage-denominated. Anchoring lambda on the hand-food make cost is the
  candidate fix; re-measure once `process_food` has real volume.
- Prosperity UI tiers (phase 3 of `docs/prosperity-design.md`) not started.

## Dev-loop improvements (from the retired roadmap)

- Test-on-edit `PostToolUse` hook: run `uv run pytest -q` on `core/**` edits,
  bootstrap/graph validation on `data/*.yaml` edits (scope matchers tightly).
- Clean stale `SPACESIM_RUN_PATH` entries in `.claude/settings.local.json`.
- `dev compare RUN_A RUN_B`: print only KPIs that moved beyond ~±0.05.
- Scenario fixtures (tool shortage, autarky, abundant ore) the smoke test can
  iterate.
