---
name: sim-evaluation
description: Run the simulation and evaluate whether it behaves as intended, token-efficiently. Use after changing economy data, drives, brains, or market logic to check macro behavior; for "did my change break the economy", "is the economy healthy", running a quick behavioral check, or writing ad-hoc analysis over a run. Covers the Tier-0 KPI summary, Tier-1 analysis scripts, and Tier-2 human notebooks.
---

# Simulation Evaluation

How to evaluate simulation behavior with the fewest tokens. Two costs
matter: constructing commands and reading output. Use the lowest tier that
answers the question.

## The dev loop

```bash
uv run pytest -q                                   # 1. unit tests (~2s)
uv run spacesim2 run --turns 200 --no-export --quiet --summary   # 2. behavior
# 3. read the JSON between ===SUMMARY_BEGIN=== / ===SUMMARY_END===
```

The simulation is stochastic and not bit-reproducible. Population means over
hundreds of actors are stable to about ±0.05, enough to detect real changes.
There is no run-level seed knob: most randomness flows through `uuid4` and
set iteration, so seeding the module RNG gave false determinism. Assert with
tolerances, never exact values.

## Tier 0: built-in KPI summary

For "is it broken" and "is the economy healthy". One command, about 20
numbers, a `PASS/WARN/FAIL` verdict.

```bash
uv run spacesim2 run --turns 200 --no-export --quiet --summary
```

Returns turns, money distribution, per-drive mean health/debt/deprivation,
population inventory totals, mean prices, and a `verdict`. The verdict is a
catastrophe floor (food survival and a live market), not a target: `PASS`
means not obviously broken. Comfort drives (shelter, clothing, health) are
reported but not judged.

Thresholds live in `spacesim2/analysis/summary.py`; mirror any change in
`tests/test_simulation_smoke.py`.

## Tier 1: ad-hoc analysis script

For open-ended questions the fixed summary cannot answer, such as "does tool
breakage drive the price cycle, by planet attribute?". This is the agent's
notebook.

```bash
uv run spacesim2 run --turns 300                        # exports Parquet to data/runs/
cp notebooks/scratch_template.py notebooks/my_question.py
# edit my_question.py: load_run() -> Polars frames
uv run spacesim2 dev analyze notebooks/my_question.py  # runs it, relays stdout
```

`dev analyze` uses the most recent run; pass `--run DIR` for another.
`load_run()` (from `spacesim2.analysis.loading`) auto-detects the latest run
and exposes `.actor_turns`, `.actor_drives`, `.market_transactions`,
`.market_snapshots` as Polars frames.

**Output contract, which keeps tokens bounded:**
- PRINT small aggregates only: `.describe()`, grouped means, `.head(N)`.
  Never print a raw full DataFrame.
- SAVE figures to `tmp/` with `savefig()` (Agg backend); never display them.
  `dev analyze` reports the saved paths for the human to open. Reason over
  the printed numbers, not the pixels.

## Tier 2: marimo notebook (human-facing)

Optional human dashboard, not part of the agent loop. The maintained
dashboard is `notebooks/analysis_template.py`. Extend it, or a copy, only
when a human wants interactive charts, then hand off the open command. Do
not read its HTML export back into context.

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
