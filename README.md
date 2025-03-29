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

## Running the Simulation

The simulation can be run in two modes:

### Headless Mode

Run the simulation without a graphical interface:

```bash
# Run for 10 turns
python -m spacesim2 --headless --turns 10

# Or use the convenience script
python run_headless.py
```

### UI Mode with Pygame

Run the simulation with a graphical interface:

```bash
# Run with UI (press SPACE to advance turn, ESC to quit)
python -m spacesim2

# Auto-run 5 turns then wait for input
python -m spacesim2 --auto-turns 5

# Or use the convenience script
python run_ui.py
```

## Development

### Setup

```bash
# Install development dependencies
pip install -e ".[dev]"
```

### Testing

```bash
# Run all tests
pytest

# Run a specific test
pytest tests/test_file.py::test_function
```