# SpaceSim2

A turn-based economic simulation modeling interplanetary trade with actors, markets, and ships.

## Overview

The simulation models an interplanetary economy with:
- **Planets** with unique resources and local markets
- **Actors** performing economic actions and trading
- **Ships** facilitating interplanetary trade
- **Markets** matching buy/sell orders for commodities
- **Commodities** that can be produced, refined, and traded

See [docs/sim-design.md](docs/sim-design.md) for the simulation design document.

## Installation

```bash
# Install the package
uv sync

# Install with analysis dependencies (for batch analysis and notebooks)
uv sync --extra analysis
```

## Usage

```bash
# Live galaxy view (Pygame)
uv run spacesim2 ui

# Headless run with data export
uv run spacesim2 run --turns 200

# Compact KPI summary with PASS/WARN/FAIL verdict
uv run spacesim2 run --turns 200 --no-export --quiet --summary

# Run an ad-hoc analysis script against the latest exported run
uv run spacesim2 dev analyze notebooks/healthcheck_probe.py

# Run with data export and open the Marimo dashboard notebook
uv run spacesim2 run --notebook

# Generate commodity/process dependency graph
uv run spacesim2 dev graph

# See all commands and options
uv run spacesim2 --help
```

Galaxy size is adjustable on both `ui` and `run` via `--planets`, `--actors`,
`--makers`, and `--ships`.

## Development

See [CLAUDE.md](CLAUDE.md) for the full development workflow (test, type-check,
lint, and simulation-evaluation loop). Quick start:

```bash
uv sync --all-extras       # dev + analysis dependencies
uv run pytest              # tests
uv run spacesim2 dev check # full verify: format, lint, types, tests, sim run
```
