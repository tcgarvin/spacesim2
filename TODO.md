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

## Medicine / health-drive variance

High run-to-run variance on health (one 800-turn run landed at 0.148 with
medicine spiking to 139 and stockpiling). Likely lever: widen the gap between
medicine's cost floor and the ~40 consumer WTP so it distributes instead of
stockpiling. Scoring probe: `notebooks/chem_score_probe.py`
(`uv run python notebooks/chem_score_probe.py`, ~70s).

## Dev-loop improvements (from the retired roadmap)

- Test-on-edit `PostToolUse` hook: run `uv run pytest -q` on `core/**` edits,
  bootstrap/graph validation on `data/*.yaml` edits (scope matchers tightly).
- Clean stale `SPACESIM_RUN_PATH` entries in `.claude/settings.local.json`.
- Tune verdict thresholds to a real long-run steady state, then add comfort
  drives to `_DRIVE_HEALTH_THRESHOLDS` in `analysis/summary.py` (+ smoke test).
- `dev compare RUN_A RUN_B`: print only KPIs that moved beyond ~±0.05.
- Trade-volume / market-liveness KPIs in the live summary (catch "market froze
  but drives look fine").
- Scenario fixtures (tool shortage, autarky, abundant ore) the smoke test can
  iterate.
