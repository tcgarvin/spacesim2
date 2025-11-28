# CLAUDE.md - Agent Instructions

## Project: SpaceSim2
A turn-based economic simulation modeling interplanetary trade with actors, markets, and ships.  Design documents can be found in the docs/ directory.

## Build & Run Commands
- **Install**: `uv sync`
- **Install with Dependencies**: `uv sync --extra analysis` (for analysis features)
- **Interactive UI**: `uv run spacesim2 ui`
- **Headless Simulation**: `uv run spacesim2 run --turns 10`
- **Batch Analysis**: `uv run spacesim2 analyze --turns 100 --progress`
- **Dev Tools**: `uv run spacesim2 dev validate-market` or `uv run spacesim2 dev graph`
- **Test**: `uv run -m pytest tests/`
- **Run Single Test**: `uv run -m pytest tests/test_file.py::test_function -v`
- **Type Check**: `uv run -m mypy .`
- **Lint**: `uv run -m ruff check .`
- **Format**: `uv run -m black .`

## CLI Usage
SpaceSim2 provides a unified CLI with subcommands:
- `spacesim2 ui` - Launch Pygame graphical interface
- `spacesim2 run` - Headless simulation with text output
- `spacesim2 analyze` - Batch analysis with Parquet export for notebooks
- `spacesim2 dev validate-market` - Market maker behavior validation
- `spacesim2 dev graph` - Generate commodity/process dependency graphs

Run `uv run spacesim2 --help` for all options.

## Code Style Guidelines
- **Python Version**: 3.11+
- **Formatting**: Black (line length 88)
- **Imports**: Organize in standard groups (stdlib, third-party, local)
- **Types**: Use type annotations for all functions and classes
- **Naming**: 
  - snake_case for functions, variables, modules
  - PascalCase for classes
  - UPPER_CASE for constants
- **Error Handling**: Use explicit exception handling with appropriate specificity
- **Documentation**: Docstrings for all public functions, classes, and modules
- **Architecture**: Follow domain-driven design with simulation entities as core abstractions
- **Code structure**: While inheritence certainly makes sense sometimes, algorithms that can be stateless are prefered to be pure functions, whenever suitable.

## Development Process
- Implement small, focused changes that maintain a working simulation
- Add tests for new functionality before implementation
- Follow the design document in docs/sim-design.md for simulation details