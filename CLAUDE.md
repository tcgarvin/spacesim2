# CLAUDE.md - Agent Instructions

## Project: SpaceSim2
A turn-based economic simulation modeling interplanetary trade with actors, markets, and ships.

## Build & Run Commands
- **Install**: `pip install -e .`
- **Run**: `python hello.py`
- **Test**: `pytest tests/`
- **Run Single Test**: `pytest tests/test_file.py::test_function -v`
- **Type Check**: `mypy .`
- **Lint**: `ruff check .`
- **Format**: `black .`

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

## Development Process
- Implement small, focused changes that maintain a working simulation
- Add tests for new functionality before implementation
- Follow the design document in docs/sim-design.md for simulation details