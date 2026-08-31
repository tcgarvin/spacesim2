# SpaceSim2 Analysis Notebooks

This directory holds two kinds of files: **Tier-1 analysis scripts** (plain
Python, run via `dev analyze`) and one **marimo dashboard** for interactive
human exploration. See the `sim-evaluation` skill for the full tier model.

## Tier-1 Analysis Scripts

Plain scripts that print small aggregates and save figures to `tmp/`. Start
from the template:

```bash
cp notebooks/scratch_template.py notebooks/my_question.py
# edit, then run against the latest exported run:
uv run spacesim2 dev analyze notebooks/my_question.py
```

Kept reference probes (each documents its own question in its docstring):

- `healthcheck_probe.py` - broad economy health readout over a run
- `chem_score_probe.py` - self-contained probe that builds its own sim
- `ship_fuel_wtp_probe.py` - fuel willingness-to-pay vs delivered cost
- `ship_dead_fleet_probe.py` - fleet mobility / stranded-ship check

## Marimo Dashboard

`analysis_template.py` is the maintained interactive dashboard (money, prices,
volumes, drive metrics). Open it with:

```bash
uv run spacesim2 run --notebook              # run + auto-open
# or against an existing run:
uv run marimo edit --no-token notebooks/analysis_template.py
```

Requires `uv sync --extra analysis` (always use `uv run marimo` for the
correct environment).

### Run path resolution (all notebooks/scripts)

1. `SPACESIM_RUN_PATH` env var, if set (explicit override).
2. Auto-detect: most recent `data/runs/run_YYYYMMDD_HHMMSS` directory by
   parsed timestamp; clear error if none found.
3. Manual override via the "Run Path" text field in the dashboard UI.

### Debugging a notebook

Use `marimo export html` instead of `marimo run` — it executes the notebook
headlessly and surfaces errors immediately in the terminal:

```bash
SPACESIM_RUN_PATH=data/runs/test_run uv run marimo export html \
    notebooks/analysis_template.py -o /tmp/test.html
```

Lint with `uv run marimo check notebooks/file.py`.

### Marimo cell gotchas

Cell output must be a **top-level expression**, never nested inside a
conditional. Do conditional logic first, assign to a variable, then put the
bare variable on the last line. For possibly-missing data, assign a fallback:

```python
@app.cell
def _(data, mo, px):
    if data is None:
        output = mo.md("No data available")
    else:
        output = px.bar(data.to_pandas(), x="name", y="value")
    output
    return (output,)
```

## Data Structure

Exported runs (`data/runs/run_TIMESTAMP/`) contain Parquet files:

- `actor_turns.parquet` - actor state per turn (money, inventory, location)
- `actor_drives.parquet` - drive metrics (health, debt, urgency)
- `market_transactions.parquet` - individual trades
- `market_snapshots.parquet` - market state per turn (prices, volumes, orders)

Load them with `from spacesim2.analysis.loading import load_run`.
