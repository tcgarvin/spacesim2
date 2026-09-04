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
- Tier 3 goods (electronics, computers, ship parts, prefab housing,
  advanced medicine) still barely appear by turn 600.

## Dev-loop improvements (from the retired roadmap)

- Test-on-edit `PostToolUse` hook: run `uv run pytest -q` on `core/**` edits,
  bootstrap/graph validation on `data/*.yaml` edits (scope matchers tightly).
- Clean stale `SPACESIM_RUN_PATH` entries in `.claude/settings.local.json`.
- `dev compare RUN_A RUN_B`: print only KPIs that moved beyond ~±0.05.
- Scenario fixtures (tool shortage, autarky, abundant ore) the smoke test can
  iterate.
