# CLAUDE.md - Agent Instructions

## Project: SpaceSim2
A turn-based economic simulation modeling interplanetary trade with actors, markets, and ships.

## Commands

```bash
# Build & Run
uv sync                              # Install dependencies
uv sync --extra analysis             # Install with analysis features
uv run spacesim2 ui                  # Interactive UI (Pygame)
uv run spacesim2 run                 # Headless sim with progress bar (default)
uv run spacesim2 run --quiet         # Suppress all output
uv run spacesim2 run --verbose       # Per-turn detailed output
uv run spacesim2 run --no-export     # Quick run without data export

# Development
uv run pytest tests/                           # Run all tests
uv run pytest tests/test_file.py::test_fn -v   # Run single test
uv run mypy .                                  # Type check
uv run black .                                 # Format
uv run ruff check .                            # Lint

# Dev Tools
uv run spacesim2 dev validate-market   # Market maker validation
uv run spacesim2 dev graph             # Commodity/process graphs
```

## Code Style
- **Python**: 3.11+ with type annotations
- **Formatting**: Black (88 char lines)
- **Naming**: `snake_case` functions/vars, `PascalCase` classes, `UPPER_CASE` constants
- **Architecture**: Domain-driven design; prefer pure functions over stateful classes when suitable

## Documentation Index

Read the relevant guide when working on specific areas:

| Topic | Document | When to Read |
|-------|----------|--------------|
| Simulation design | `docs/sim-design.md` | Understanding game mechanics, rules |
| Turn flow & testing | `docs/dev-guide-simulation.md` | Debugging AI, market mechanics, testing |
| Ship trading AI | `docs/dev-guide-ships.md` | Developing ship brains, fuel/trade logic |
| Notebook analysis | `docs/dev-guide-notebooks.md` | Working with marimo notebooks |
| Needs/drives system | `docs/needs.md` | Actor consumption, hunger, clothing |
| Skills system | `docs/skills.md` | Actor skill levels, production |
| Commodities | `docs/commodities_implementation.md` | Adding/modifying tradeable goods |
| UI grid | `docs/actor_grid_ui.md` | Pygame UI development |

## Key Architecture Facts

These apply to most tasks:

- **Deferred market matching**: Orders execute at END of turn, not immediately
- **Brain pattern**: Actors/ships delegate decisions to pluggable `Brain` classes
- **Core files**: `core/simulation.py` (main loop), `core/actor.py`, `core/ship.py`, `core/market.py`

## Common Implementation Patterns

### Commodity System
Commodities are defined in `data/commodities.yaml` with a simple structure:
```yaml
- id: commodity_name
  name: Display Name
  transportable: true/false
  description: Text description
```

**Important**: Commodities have NO built-in "availability" or planet-specific attributes. All gathering/mining processes currently work on all planets equally (e.g., `gather_biomass`, `mine_nova_fuel_ore`).

**Note**: `docs/sim-design.md` mentions "Resources distributed randomly; specialization can emerge naturally" but this is NOT yet implemented. Planet-specific resource availability would need to be added as a future enhancement.

### Process Requirements
Processes in `data/processes.yaml` can specify `tools_required` and `facilities_required`, but **most processes don't require them**:
- Gathering processes (biomass, wood, ores): No requirements
- Basic refining (food, fuel, iron, steel): No requirements
- Only `refine_common_metal` requires `smelting_facility`

When adding new processes, default to no tool/facility requirements unless there's a specific game design reason.

### Drive (Needs) System
Drives live in `core/drives/` and inherit from `ActorDrive`. Two consumption patterns:

**Deterministic (FoodDrive)**:
- Consume fixed amount every turn (1 food/turn)
- Predictable, constant demand

**Stochastic (ClothingDrive, ShelterDrive)**:
- Random consumption events with probability `p` per turn
- Example: `BASE_EVENT_PROB = 1.0 / 120.0` = ~3 events/year
- Creates variable demand, more realistic for durable goods

**Drive metrics** (all drives track these):
- `health`: 0-1, immediate status (e.g., has materials available)
- `debt`: 0-1, accumulated neglect from missed consumption
- `buffer`: 0-1, log-normalized inventory coverage (days of supply)
- `urgency`: 0-1, context-dependent priority multiplier

**Material choice**: Drives can accept multiple commodities (e.g., wood OR steel for shelter). Implement `_choose_material()` to select based on availability and market prices.

**Adding a new drive requires a complete supply chain:**
1. **Commodities**: Add both raw material (e.g., `fiber`) and finished good (e.g., `clothing`) to `data/commodities.yaml`
2. **Processes**: Add gathering process (e.g., `gather_fiber`) and production process (e.g., `make_clothing`) to `data/processes.yaml`
3. **Drive class**: Create drive in `core/drives/` inheriting from `ActorDrive`
4. **Actor brains**: Update `colonist.py` and `industrialist.py` to consider the new need in `decide_economic_action()`
5. **Market trading**: Ensure actor brains trade the new commodities (use dynamic commodity iteration, not hardcoded lists)

**Critical**: Drives silently fail if their expected commodity doesn't exist in the registry (`get_commodity()` returns `None`). Always verify commodities exist before implementing drives that depend on them.

### Dynamic Commodity Handling

**Market makers and actor brains should use dynamic commodity lists**, not hardcoded ones:

```python
# GOOD - handles all commodities automatically
all_commodities = [c for c in actor.sim.commodity_registry.all_commodities() if c.transportable]
for commodity in all_commodities:
    # ... trade logic

# BAD - requires manual updates when adding commodities
for commodity in (food, fuel, wood):  # hardcoded list
    # ... trade logic
```

## Running Simulations - Notebook-First Approach

**IMPORTANT**: When running simulations for analysis, testing, or debugging, ALWAYS use marimo notebooks instead of test scripts or one-off Python invocations.

### Standard Workflow

```bash
# 1. Run simulation with data export (auto-opens notebook)
uv run spacesim2 run --notebook

# 2. Or run without auto-opening, then open manually
uv run spacesim2 run
uv run marimo edit --no-token notebooks/analysis_template.py  # Auto-detects latest run

# 3. Use specific notebook for specialized analysis
uv run spacesim2 run --notebook --notebook-path notebooks/ship_economics.py

# 4. Quick sanity check without export
uv run spacesim2 run --turns 10 --no-export --verbose
```

### Creating New Analysis Notebooks

```bash
# Copy template
cp notebooks/analysis_template.py notebooks/my_analysis.py

# Run simulation and open your notebook
uv run spacesim2 run --notebook --notebook-path notebooks/my_analysis.py
```

### Notebook Validation and Delivery

**Always validate notebooks before delivering them:**
```bash
uv run marimo check notebooks/my_notebook.py
```

Common issues to avoid:
- **Multiple definitions**: Use `_` prefix for cell-local variables (`_fig`, `_data`)
- **Branch expressions**: Assign conditional outputs to a named variable, then display it at cell end
- **Unused returns**: Don't return variables that aren't used by other cells

**When user requests a notebook, always:**
1. Run `marimo check` to validate
2. Start the notebook server for them: `uv run marimo edit --no-token notebooks/notebook.py`

### Why Notebooks?

- **Persistent**: Results survive between runs, easy to revisit
- **Interactive**: Modify analysis without re-running expensive simulations
- **Integrated**: Auto-connects to simulation data via `SPACESIM_RUN_PATH`
- **Reproducible**: Version-controlled, shareable analysis workflows
- **MCP-friendly**: `--no-token` flag enables MCP server integration

### When to Use Notebooks vs Tests

**Use notebooks** anytime you want to examine the way the simulation is functioning:
- Exploring actor behavior, market dynamics, or ship trading patterns
- Debugging unexpected simulation outcomes
- Performance analysis and optimization
- Validating game mechanics
- Economic analysis and visualization

**Use pytest** for automated assertions on expected behavior:
```python
# tests/test_component.py
def test_specific_behavior():
    sim = Simulation()
    sim.setup_simple(num_planets=2, num_regular_actors=10, num_market_makers=1, num_ships=1)
    sim.run_turn()
    # ... assertions
```
