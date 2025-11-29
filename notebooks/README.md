# SpaceSim2 Analysis Notebooks

This directory contains Marimo notebooks for analyzing simulation data.

## Available Notebooks

### `ship_economics.py` - Ship Economic Activity and Profitability Analysis

Comprehensive analysis of trading ship performance including:
- Money and profit trajectories over time
- Return on Investment (ROI) calculations
- Trading activity (buy/sell patterns)
- Trade route analysis
- Profit margins by commodity
- Cargo utilization tracking
- Performance summary statistics

## Running Notebooks

### Prerequisites

Install analysis dependencies:
```bash
uv sync --extra analysis
```

### Quick Start

1. **Run a simulation with ship tracking:**
   ```bash
   # Run 100 turns and log ship activity
   uv run spacesim2 analyze --turns 100 --log-actor-types ship --output data/runs/my_run
   ```

2. **Launch the ship economics notebook:**
   ```bash
   # Use the run path from step 1
   SPACESIM_RUN_PATH='data/runs/my_run/run_YYYYMMDD_HHMMSS' marimo edit notebooks/ship_economics.py
   ```

3. **View in your browser** - Marimo will open automatically at http://localhost:8080

### Logging Options

Control which actors/ships are logged:

```bash
# Log only ships
uv run spacesim2 analyze --turns 100 --log-actor-types ship

# Log ships and colonists
uv run spacesim2 analyze --turns 100 --log-actor-types ship colonist

# Log all actors and ships
uv run spacesim2 analyze --turns 100 --log-all

# Log sample of 10 actors plus all ships
uv run spacesim2 analyze --turns 100 --log-sample 10 --log-actor-types ship
```

Available actor types:
- `ship` or `trader` - Trading ships
- `colonist` - Regular population actors
- `industrialist` - Industrial production specialists
- `market_maker` - Market liquidity providers

## Notebook Features

### Interactive Exploration

All notebooks support:
- **Interactive filtering** - Select specific runs, time periods, or actors
- **Dynamic visualizations** - Hover for details, zoom, pan
- **Real-time updates** - Change parameters and see results instantly
- **Export** - Save plots and data for reports

### Ship Economics Notebook Details

Key metrics tracked:
- **Profitability**: Profit per turn, cumulative ROI, total profit from trades
- **Trading Patterns**: Buy/sell volume, transaction frequency, order placement
- **Route Analysis**: Most frequent routes, trip counts
- **Profit Margins**: Per-commodity margins, comparison to 20% target
- **Cargo Management**: Food/fuel levels, total utilization
- **Performance Summary**: Best/worst performing ships, average metrics

### Data Structure

Exported simulation data includes:
- `actor_turns.parquet` - Actor state per turn (money, inventory, location)
- `actor_drives.parquet` - Drive metrics (health, debt, urgency) - empty for ships
- `market_transactions.parquet` - Individual trades
- `market_snapshots.parquet` - Market state per turn (prices, volumes, orders)

## Example: Analyzing Ship Profitability

```python
# In the notebook, ships are automatically identified and analyzed
# You'll see:

# 1. Money trajectory - Are ships gaining or losing money?
# 2. ROI - What's the return on their initial capital?
# 3. Trade frequency - How actively are they trading?
# 4. Profit margins - Are they achieving 20%+ margins?
# 5. Routes - Which planetary pairs are most traveled?
```

## Troubleshooting

**No ship data appearing?**
- Ensure you used `--log-actor-types ship` when running the simulation
- Check that ships are created in the simulation (default is 2 ships for 2 planets)
- Verify the run path points to the correct export directory

**Performance issues with large datasets?**
- Use `--log-sample` instead of `--log-all` for large populations
- Reduce turn count for initial testing
- Polars lazy evaluation handles large files efficiently

**Notebook won't start?**
- Ensure analysis extras are installed: `uv sync --extra analysis`
- Check that Marimo is installed: `uv run marimo --version`

## Creating Custom Notebooks

Use `analysis_template.py` as a starting point for custom analysis:

```bash
cp notebooks/analysis_template.py notebooks/my_analysis.py
marimo edit notebooks/my_analysis.py
```

The `SimulationData` loader provides easy access to all exported data via Polars DataFrames.
