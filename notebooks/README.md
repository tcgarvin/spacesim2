# Analysis Notebooks

This directory holds Tier-1 analysis scripts (plain Python, run with
`dev analyze`) and one marimo dashboard. The `sim-evaluation` skill explains
the tiers.

## Tier-1 analysis scripts

Plain scripts that print small aggregates and save figures to `tmp/`. Start
from the template:

```bash
cp notebooks/scratch_template.py notebooks/my_question.py
# edit, then run against the latest exported run:
uv run spacesim2 dev analyze notebooks/my_question.py
```

Kept probes, each with its question in its docstring:

- `healthcheck_probe.py`: economy health trends over a run
- `chem_score_probe.py`: builds and runs its own sim; run it directly with
  `uv run python notebooks/chem_score_probe.py`

## Marimo dashboard

`analysis_template.py` is the maintained dashboard (money, prices, volumes,
drive metrics). Open it with:

```bash
uv run spacesim2 run --notebook              # run + auto-open
# or against an existing run:
uv run marimo edit --no-token notebooks/analysis_template.py
```

Requires `uv sync --extra analysis`. Always use `uv run marimo` so the right
environment is used.

### Run path resolution

1. `SPACESIM_RUN_PATH` env var, if set.
2. Otherwise the most recent `data/runs/run_YYYYMMDD_HHMMSS` directory by
   parsed timestamp. Missing runs raise a clear error.
3. The dashboard's "Run Path" text field overrides both.

### Debugging a notebook

`marimo export html` runs the notebook headlessly and prints errors to the
terminal, which `marimo run` does not:

```bash
SPACESIM_RUN_PATH=data/runs/test_run uv run marimo export html \
    notebooks/analysis_template.py -o /tmp/test.html
```

Lint with `uv run marimo check notebooks/file.py`.

### Marimo cell rules

Cell output must be a top-level expression, never nested inside a
conditional. Branch first, assign to a variable, and put the bare variable on
the last line:

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

## Exported data

Each run under `data/runs/run_TIMESTAMP/` contains Parquet files:

- `actor_turns.parquet`: actor state per turn (money, inventory, location)
- `actor_drives.parquet`: drive metrics (health, debt, buffer, urgency)
- `market_transactions.parquet`: individual trades
- `market_snapshots.parquet`: market state per turn (prices, volumes, orders)

plus `metadata.json`, `planet_attributes.json` and `galaxy.json`. Load the
Parquet files with `from spacesim2.analysis.loading import load_run`.
