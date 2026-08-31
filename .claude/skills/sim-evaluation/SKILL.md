---
name: sim-evaluation
description: Run the simulation and evaluate whether it behaves as intended, token-efficiently. Use after changing economy data, drives, brains, or market logic to check macro behavior; for "did my change break the economy", "is the economy healthy", running a quick behavioral check, or writing ad-hoc analysis over a run. Covers the Tier-0 KPI summary, Tier-1 analysis scripts, and Tier-2 human notebooks.
---

# Simulation Evaluation

How to evaluate simulation behavior with the fewest tokens. Two token costs
matter: **design tokens** (constructing commands) and **context tokens**
(reading output). Use the lowest tier that answers the question.

## The dev loop

```bash
uv run pytest -q                                   # 1. unit tests (~2s)
uv run spacesim2 run --turns 200 --no-export --quiet --summary   # 2. behavior
# 3. read the JSON between ===SUMMARY_BEGIN=== / ===SUMMARY_END===
```

The simulation is stochastic and **not bit-reproducible** (and that's fine).
Population means over ~hundreds of actors are stable to ~±0.05, which is
plenty to detect real changes. There is no run-level seed knob — most
randomness flows through `uuid4`/set iteration, so seeding the module RNG only
gave false determinism. Never assert exact values; use tolerances.

## Tier 0 — built-in KPI summary (cheapest)

For "is it broken / is the economy healthy". One recalled command, ~20
numbers, a `PASS/WARN/FAIL` verdict.

```bash
uv run spacesim2 run --turns 200 --no-export --quiet --summary
```

Returns turns, money distribution, per-drive mean health/debt/deprivation,
population inventory totals, mean prices, and a `verdict`. The verdict is a
**catastrophe floor** (food survival + live market), not an aspirational
target — `PASS` means "not obviously broken", not "optimal". Comfort drives
(shelter/clothing/health) are reported but not pass/failed.

Implemented in `spacesim2/analysis/summary.py` — edit thresholds there, and
mirror them in `tests/test_simulation_smoke.py`.

## Tier 1 — ad-hoc analysis script (flexible, still cheap)

For open-ended questions the fixed summary can't answer ("does tool breakage
drive the price cycle, broken down by planet attribute?"). This is the
token-controlled "notebook" for agents.

```bash
uv run spacesim2 run --turns 300 --run-id myrun        # produces Parquet
cp notebooks/scratch_template.py notebooks/my_question.py
# edit my_question.py: load_run() -> Polars frames
uv run spacesim2 dev analyze notebooks/my_question.py  # runs it, relays stdout
```

`load_run()` (from `spacesim2.analysis.loading`) auto-detects the latest run
and exposes `.actor_turns`, `.actor_drives`, `.market_transactions`,
`.market_snapshots` as Polars frames.

**Output contract — this is what keeps tokens bounded:**
- PRINT small aggregates only — `.describe()`, grouped means, `.head(N)`.
  Never print a raw full DataFrame.
- SAVE figures to `tmp/` with `savefig()` (Agg backend); never display them.
  `dev analyze` reports the saved paths for the human to open. You reason over
  the printed numbers, not the pixels.

## Tier 2 — marimo notebook (human-facing, zero agent tokens)

Optional human dashboard, not part of the agent loop. The maintained dashboard
is `notebooks/analysis_template.py`; extend it (or a copy) only when a human
wants interactive charts, and hand off the open command — do **not** read its
HTML export back into context.

```bash
uv run marimo edit --no-token notebooks/analysis_template.py
```

Use the `simulation-analyst` subagent for substantial notebook work.

## Picking a tier

| Question | Tier |
|----------|------|
| Did my change break the economy? | 0 |
| Is food/shelter/money in a healthy range? | 0 |
| Why is commodity X's price doing Y, by planet/turn? | 1 |
| One-off correlation / breakdown / distribution | 1 |
| Interactive dashboard for a human to explore | 2 |

Encode any check worth keeping as an assertion in
`tests/test_simulation_smoke.py` so it runs free in the unit loop.
