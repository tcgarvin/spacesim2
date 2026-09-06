# TODO

Genuinely open work only. Closed postmortems live in `docs/decision-log.md`;
perf levers live in `docs/performance.md`.

## Ship trading residuals (post flow-based rework, 2026-08-31)

- 2/5 ships ended lean (6 and 181 credits) despite positive per-trip margins —
  they overpaid for fuel (avg ~50-54/unit vs fleet 42); possible remaining
  bunkering/pricing leak.
- Fleet still pays avg 42 vs 33 best-planet honest fuel cost.
- Fuel-delivery accumulation overbuys: a fuel-run plan's "held" count only sees
  tank overflow above fuel_capacity, so deliverers fill the tank plus the plan
  quantity before departing.

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
  fix it, supply on wood-poor planets is the question. Processed-food
  coverage fell 0.45 -> 0.20 under its 3x food bound.
- Revisit the processed-food substitute bound (`PROCESSED_FOOD_MAX_FOOD_MULTIPLE`
  in `core/drives/prosperity_drive.py`): a flat 3x-food-price cap on the bid
  stopped processed-food makers from bidding staple food away from hungry
  consumers, but it also cut processed-food coverage 0.45 -> 0.20. User
  wants a different mechanism than a hardcoded multiple; not yet designed.
- Prosperity UI tiers (phase 3 of `docs/prosperity-design.md`) not started.

## Dev-loop improvements (from the retired roadmap)

- Test-on-edit `PostToolUse` hook: run `uv run pytest -q` on `core/**` edits,
  bootstrap/graph validation on `data/*.yaml` edits (scope matchers tightly).
- Clean stale `SPACESIM_RUN_PATH` entries in `.claude/settings.local.json`.
- `dev compare RUN_A RUN_B`: print only KPIs that moved beyond ~±0.05.
- Scenario fixtures (tool shortage, autarky, abundant ore) the smoke test can
  iterate.
