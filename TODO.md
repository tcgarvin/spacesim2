# TODO

Genuinely open work only. Closed postmortems live in `docs/decision-log.md`;
perf levers live in `docs/performance.md`.

## Ship trading residuals (post flow-based rework, 2026-08-31)

- 2/5 ships ended lean (6 and 181 credits) despite positive per-trip margins —
  they overpaid for fuel (avg ~50-54/unit vs fleet 42); possible remaining
  bunkering/pricing leak.
- Fleet still pays avg 42 vs 33 best-planet honest fuel cost.
- Spiked survival top-ups (2026-09-07): the ration branch of
  `_opportunistic_fuel_topup` still buys the survival target at any price
  (252k of a 266k fuel premium over 600 turns at 100 planets before the
  tank split), and a poor ship's standing rescue bid amortizes a deliverer's
  round trip over 1-3 units, pricing at 15x reference. Next lever after the
  tank split: cap ration buys by price when a cheaper ask is reachable on
  the tank, and floor rescue-bid quantity.
- Add-on cargo (2026-09-07) is chosen once per plan and not re-bid on later
  accumulating turns; a partly filled add-on flies as is. Re-bidding the
  shortfall is untested.

## Medicine / upper tier (post 2026-09-03 fixes)

The WTP ceiling and phantom-bid entry are fixed (`FoodDrive.security`,
`_output_unit_value`). Left open:

- Producers still outrun consumption: fewer, more capable medicine makers
  keep stock growing. Entry scoring is inventory-blind; a producer sitting on
  unsold output still scores positive when the depth price covers cost. A
  stock-aware discount on output value is the next lever.
- `ship_supplies` has no consumer. Ships buy maintenance goods only when
  already stranded, and the `nova_fuel` maintenance tier always succeeds, so
  the tier is never reached. Give ships a standing supplies buffer.
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
  16,990 processed food at turn 300) and the surplus is not exported. Two
  questions, in order, both needing the 100-planet galaxy since trade KPIs
  mean nothing at 12: does processed food ever leave a plant planet, and if
  not, does the ship planner reject it on per-unit margin (2-3 credits at
  the plant against 5-9 for hand food on a poor planet)? Then, once imports
  land, do biomass-poor planets still build farms? A farm scores against
  its own planet's biomass price, where hand gathering at attribute 0.2
  yields 1.6 per turn, so a local farm looks good even when a farm two
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
