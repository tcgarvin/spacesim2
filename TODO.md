# TODO

Genuinely open work only. Closed postmortems live in `docs/decision-log.md`;
perf levers live in `docs/performance.md`.

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
