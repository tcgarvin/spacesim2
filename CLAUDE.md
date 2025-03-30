# CLAUDE.md - Agent Instructions

## Project: SpaceSim2
A turn-based economic simulation modeling interplanetary trade with actors, markets, and ships.  Design documents can be found in the docs/ directory.

## Build & Run Commands
- **Install**: `uv pip install -e .`
- **Install Dependencies**: `uv pip install <package-name>`
- **Run**: `uv run hello.py`
- **Run Simulation**: `uv run run_headless.py --turns 10` or `uv run run_ui.py`
- **Test**: `uv run -m pytest tests/`
- **Run Single Test**: `uv run -m pytest tests/test_file.py::test_function -v`
- **Run Python Scripts**: `uv run -c "python_code_here"`
- **Type Check**: `uv run -m mypy .`
- **Lint**: `uv run -m ruff check .`
- **Format**: `uv run -m black .`

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