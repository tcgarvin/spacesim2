# Agent Dev-Loop Roadmap

Future improvements to the AI-agent development loop (change → unit tests →
run simulation → evaluate behavior). The guiding metric is **tokens per loop
iteration** = *design tokens* (constructing commands) + *context tokens*
(reading output). Each item below is justified by which it reduces.

The first tranche (Tier-0 KPI summary, Tier-1 `dev analyze`, Tier-2 notebooks,
smoke test, `sim-evaluation` skill) already landed — see that skill and
CLAUDE.md "The Dev Loop". What follows is not yet built.

## High value, low effort

### 1. Test-on-edit hook (cuts design tokens)
Add a `PostToolUse` hook in `.claude/settings.json` that runs `uv run pytest -q`
when files under `spacesim2/core/**` change, and the bootstrap/graph validation
when `data/{commodities,processes}.yaml` change. The suite is ~2s, so feedback
is near-free and the agent never has to remember to run it.
- Risk: hook noise on unrelated edits — scope the matcher tightly.

### 2. Clean the stale permission allowlist (cuts prompts)
`.claude/settings.local.json` pins `SPACESIM_RUN_PATH=data/runs/run_2025...`
entries from specific past runs. Generalize to a wildcard and drop the dead
ones. Consider the `fewer-permission-prompts` skill.

### 3. Decouple pygame from the headless path (cuts context tokens) — DONE
The banner came from `cli/main.py` eagerly importing the `ui` command module,
which imported `pygame_ui` at module load. Fixed by making the `ui` command's
pygame import lazy (inside `execute()`), so the banner only appears when the UI
is actually launched, not on `run`/`dev`/`--help`.

### 4. A `dev check` umbrella command (cuts design tokens) — DONE
`spacesim2 dev check` runs the canonical sequence — format → lint → types →
pytest → short in-process `--summary` sim run — and prints a single pass/fail
block (`--fast` skips types+sim). Non-mutating: the format stage checks only.
(The mypy baseline is now clean, so the full `mypy .` stage runs unconditionally.)

## Medium value

### 5. Verdict thresholds tuned to a real steady state
The Tier-0 verdict is intentionally a *catastrophe floor* (food + live market
only). Once a target long-run steady state is defined (run 1000+ turns and
decide what healthy shelter/clothing/health/medicine levels look like), add
those drives to `_DRIVE_HEALTH_THRESHOLDS` in `analysis/summary.py` and mirror
them in `tests/test_simulation_smoke.py`. Until then, leave them reported-only
to avoid alarm fatigue.

### 6. Summary diff / baseline compare (cuts context tokens)
A `dev compare RUN_A RUN_B` (or `--baseline summary.json`) that prints only the
KPIs that moved beyond the noise band (~±0.05). Lets an agent see *what a change
did* without re-reading two full summaries or eyeballing absolute numbers.

### 7. Trade-volume and market-liveness KPIs
The live summary omits trade volume (market history is trimmed in-sim). Surface
total transactions / volume per commodity and bid-ask spread health, either by
tracking a running counter on the sim or by reading the exported Parquet in a
post-run pass. Helps catch "market froze but drives look fine" regressions.

### 8. Retire one-off diagnostic notebooks
`notebooks/` has ~16 files, many single-use diagnoses
(`shelter_supply_chain_diagnosis`, `ship_trading_diagnosis`, …). Fold the
durable insights into Tier-1 scripts or smoke-test assertions and delete the
rest, so the notebook dir reads as "reusable dashboards" not "scratch history".

## Larger / speculative

### 9. Scenario fixtures for targeted evaluation
A small library of seeded starting conditions (e.g. "tool shortage",
"single-planet autarky", "abundant ore") that the summary/smoke test can run
against, so behavioral checks target specific mechanics instead of only the
default world. Express as parameters to `create_and_setup_simulation` plus a
registry the smoke test iterates.

### 10. Give `simulation-analyst` a headless verdict mode
The subagent is notebook-bound and returns browser artifacts. Add a mode where
it runs Tier-0/Tier-1 and returns a compact textual verdict, so it is usable
*inside* an agent loop (returning numbers to the caller), not only as a
human-facing notebook producer.

### 11. Faster runs for tighter iteration
A 1000-turn run is ~58s. If iteration speed becomes a bottleneck, profile
`run_turn` (market matching and per-actor brain calls are the likely hot spots)
before optimizing. Premature here — the 200-turn `--summary` smoke run is
already fast enough for most checks.

## Explicitly decided against

- **Bit-exact determinism.** The sim is stochastic (market `uuid4` order IDs +
  set iteration). Population means over hundreds of actors are stable to
  ~±0.05, which is enough to detect real changes. Seeding `uuid4`/iteration to
  force reproducibility would be dishonest plumbing for no real benefit. Rely
  on aggregate stability + tolerances instead.
