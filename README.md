# SpaceSim2

A turn-based economic simulation modeling interplanetary trade with actors, markets, and ships.

## Overview

The simulation models an interplanetary economy with:
- **Planets** with unique resources and local markets
- **Actors** performing economic actions and trading
- **Ships** facilitating interplanetary trade
- **Markets** matching buy/sell orders for commodities
- **Commodities** that can be produced, refined, and traded

See [docs/sim-design.md](docs/sim-design.md) for the full simulation design document.

## Installation

```bash
# Install the package
uv sync

# Install with analysis dependencies (for batch analysis and notebooks)
uv sync --extra analysis
```

## Running the Simulation

SpaceSim2 provides a unified CLI with multiple modes:

### Interactive UI Mode

Launch the Pygame graphical interface:

```bash
# Launch UI with default settings
uv run spacesim2 ui

# Customize simulation parameters
uv run spacesim2 ui --planets 5 --actors 100 --makers 2

# Control auto-advance behavior
uv run spacesim2 ui --auto-turns 5
```

Press SPACE to advance turns, ESC to quit.

### Headless Mode

Run without a graphical interface for quick testing:

```bash
# Run for 10 turns
uv run spacesim2 run --turns 10

# Customize simulation parameters
uv run spacesim2 run --turns 50 --planets 3 --actors 75
```

### Batch Analysis Mode

Run simulations with data export for analysis in notebooks:

```bash
# Run with comprehensive logging and export to Parquet
uv run spacesim2 analyze --turns 100 --log-all-actors --progress

# Run and automatically open Marimo notebook
uv run spacesim2 analyze --turns 100 --notebook

# Customize logging and output
uv run spacesim2 analyze --turns 200 --log-sample 20 --output data/my_run
```

### Development Tools

Validate and visualize simulation behavior:

```bash
# Validate market maker behavior
uv run spacesim2 dev validate-market --turns 20

# Generate commodity/process dependency graph
uv run spacesim2 dev graph --out diagram --format png
```

### Help

```bash
# View all commands
uv run spacesim2 --help

# View command-specific options
uv run spacesim2 run --help
uv run spacesim2 analyze --help
```

## Development

### Setup

```bash
# Install with development dependencies
uv sync --extra dev

# Install with all dependencies (dev + analysis)
uv sync --all-extras
```

### Testing

```bash
# Run all tests
uv run -m pytest

# Run a specific test
uv run -m pytest tests/test_file.py::test_function -v
```

### Code Quality

```bash
# Type checking
uv run -m mypy .

# Linting
uv run -m ruff check .

# Formatting
uv run -m black .
```