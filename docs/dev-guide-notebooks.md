# Notebook Development Guide

This guide covers the optional marimo dashboard workflow. The default
change→verify loop is `--summary` + `dev analyze` (see the `sim-evaluation`
skill); marimo notebooks are for interactive human-facing exploration. The
maintained dashboard is `notebooks/analysis_template.py`.

## Quick Reference

| Task | Command |
|------|---------|
| Run sim + open dashboard | `uv run spacesim2 run --notebook` |
| Interactive edit | `uv run marimo edit --no-token notebooks/analysis_template.py` |
| Lint notebook | `uv run marimo check notebooks/file.py` |
| Debug notebook | `uv run marimo export html notebooks/file.py -o /tmp/test.html` |

**Note**: Always use `uv run marimo` to ensure the correct environment, and
install the analysis extras first: `uv sync --extra analysis`.

## Debugging Notebooks

**Key Insight**: Use `marimo export html` instead of `marimo run` for debugging - it executes the notebook headlessly and shows errors immediately in the terminal, avoiding server management overhead.

```bash
# Debug with specific run data
SPACESIM_RUN_PATH=data/runs/test_run uv run marimo export html notebooks/analysis_template.py -o /tmp/test.html
```

## Run Path Management

Notebooks automatically detect the most recent simulation run.

### Priority Order

1. **Environment Variable** (explicit override):
   ```bash
   SPACESIM_RUN_PATH=data/runs/run_20251130_120000 uv run marimo edit --no-token notebooks/analysis_template.py
   ```

2. **Auto-detection** (when env var not set):
   - Scans `data/runs/` for directories matching `run_YYYYMMDD_HHMMSS`
   - Uses the most recent based on parsed timestamp
   - Raises clear error if no runs found

3. **Manual Override**:
   - Edit the "Run Path" text field in the notebook UI
   - Useful for comparing different runs

## Typical Workflow

```bash
# 1. Generate data (export is on by default)
uv run spacesim2 run --turns 100

# 2. Analyze in notebook (auto-detects most recent run)
uv run marimo edit --no-token notebooks/analysis_template.py

# Or do both in one step
uv run spacesim2 run --turns 100 --notebook
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "No valid runs found" | Run `spacesim2 run` (with export enabled) first |
| Wrong run selected | Check directory timestamps or use `SPACESIM_RUN_PATH` |
| Import errors | Run `uv sync --extra analysis` to install dependencies |
| "No module named 'polars'" | Analysis extras not installed |

## Data Files

An exporting `spacesim2 run` writes Parquet files to `data/runs/run_TIMESTAMP/`:

- Market data per turn
- Actor states
- Ship movements
- Transaction history

These files are consumed by notebooks for visualization and analysis.

## Marimo Cell Patterns

### Cell Output Must Be Top-Level

Marimo requires cell output to be a top-level expression, not nested inside conditionals. Use this pattern:

```python
@app.cell
def _(data, px):
    # Do conditional logic, assign to variable
    if data is None:
        fig = None
    else:
        fig = px.line(data.to_pandas(), x='turn', y='value')

    # Output MUST be top-level, not inside if/else
    fig
    return (fig,)
```

**Wrong** (output inside conditional):
```python
@app.cell
def _(data, px):
    if data is None:
        "No data"  # Won't display!
    else:
        px.line(...)  # Won't display!
```

### Handling Missing Data

For cells that might not have data, assign a fallback message:

```python
@app.cell
def _(data, mo, px):
    if data is None:
        output = mo.md("No data available")
    else:
        output = px.bar(data.to_pandas(), x='name', y='value')

    output
    return (output,)
```
