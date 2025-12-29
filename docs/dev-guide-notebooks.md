# Notebook Development Guide

This guide covers developing and debugging marimo notebooks for simulation analysis.

## Quick Reference

| Task | Command |
|------|---------|
| Debug notebook | `uv run marimo export html notebooks/file.py -o /tmp/test.html` |
| Interactive edit | `uv run marimo edit --no-token notebooks/file.py` |
| Lint notebook | `uv run marimo check notebooks/file.py` |
| Validate data | `python dev-tools/validate_run_data.py data/runs/run_name` |

**Note**: Always use `uv run marimo` to ensure the correct environment.

## Debugging Notebooks

**Key Insight**: Use `marimo export html` instead of `marimo run` for debugging - it executes the notebook headlessly and shows errors immediately in the terminal, avoiding server management overhead.

```bash
# Debug with specific run data
SPACESIM_RUN_PATH=data/runs/test_run uv run marimo export html notebooks/analysis_template.py -o /tmp/test.html

# Quick notebook test (validation + export)
./dev-tools/test_notebook.sh data/runs/test_run
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
# 1. Generate data
uv run spacesim2 analyze --turns 100 --progress

# 2. Analyze in notebook (auto-detects most recent)
uv run marimo edit --no-token notebooks/analysis_template.py
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "No valid runs found" | Run `spacesim2 analyze` first |
| Wrong run selected | Check directory timestamps or use `SPACESIM_RUN_PATH` |
| Import errors | Run `uv sync --extra analysis` to install dependencies |
| "No module named 'polars'" | Analysis extras not installed |

## Data Files

The `spacesim2 analyze` command exports Parquet files to `data/runs/run_TIMESTAMP/`:

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
