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

## Notebook Development
marimo notebooks are Python files that can be debugged efficiently using headless execution:

- **Debug notebooks**: Export to HTML for headless execution with immediate error feedback
  ```bash
  SPACESIM_RUN_PATH=data/runs/test_run marimo export html notebooks/analysis_template.py -o /tmp/test.html
  ```
- **Validate data**: Check parquet files exist and have correct schema before running
  ```bash
  python dev-tools/validate_run_data.py data/runs/test_run
  ```
- **Quick notebook test**: Run both validation and export in one command
  ```bash
  ./dev-tools/test_notebook.sh data/runs/test_run
  ```
- **Quick check**: Lint notebook before execution
  ```bash
  marimo check notebooks/analysis_template.py
  ```
- **Interactive editing**: Auto-reload on file changes during development
  ```bash
  marimo edit notebooks/analysis_template.py --watch
  ```
- **Test notebooks**: Run automated tests (when implemented)
  ```bash
  uv run pytest tests/test_notebooks.py
  ```

**Key Insight**: Use `marimo export html` instead of `marimo run` for debugging - it executes the notebook headlessly and shows errors immediately in the terminal, avoiding server management overhead.

## Notebook Run Path Management

Notebooks automatically detect the most recent simulation run:

1. **Environment Variable** (explicit override):
   ```bash
   SPACESIM_RUN_PATH=data/runs/run_20251130_120000 marimo edit notebooks/analysis_template.py
   ```

2. **Auto-detection** (when env var not set):
   - Scans `data/runs/` for directories matching `run_YYYYMMDD_HHMMSS`
   - Uses the most recent based on parsed timestamp
   - Raises clear error if no runs found

3. **Manual Override**:
   - Edit the "Run Path" text field in the notebook UI
   - Useful for comparing different runs

**Workflow**:
```bash
# Generate data
uv run spacesim2 analyze --turns 100 --progress

# Later: analyze in notebook (auto-detects most recent)
marimo edit notebooks/analysis_template.py
```

**Troubleshooting**:
- **"No valid runs found"**: Run `spacesim2 analyze` first
- **Wrong run selected**: Check directory timestamps or use `SPACESIM_RUN_PATH` to override