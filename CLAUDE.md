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
uv run spacesim2 run --no-planet-attributes  # Disable per-planet resource availability (enabled by default)

# Development
uv run pytest tests/                           # Run all tests
uv run pytest tests/test_file.py::test_fn -v   # Run single test
uv run mypy .                                  # Type check (correctness)
uv run ruff format .                           # Format
uv run ruff check .                            # Lint

# Dev Tools
uv run spacesim2 dev validate-market   # Market maker validation
uv run spacesim2 dev graph             # Commodity/process dependency graph (outputs to tmp/)
uv run spacesim2 dev graph --out foo   # Custom output path (creates foo.svg and foo.mmd)
uv run spacesim2 dev graph -f png      # Alternative formats: svg (default), png, pdf
uv run spacesim2 dev analyze FILE.py   # Run a Tier-1 analysis script against latest run
```

## The Dev Loop (for agents)

Canonical change→verify loop. Use these verbatim; see the **`sim-evaluation`**
skill for tiers and the analysis-output contract.

```bash
uv run pytest -q                                                  # 1. unit tests (~2s)
uv run spacesim2 run --turns 200 --no-export --quiet --summary    # 2. macro behavior
# 3. read JSON between ===SUMMARY_BEGIN=== / ===SUMMARY_END=== (verdict + KPIs)
```

- `--summary` prints a compact KPI JSON + `PASS/WARN/FAIL` verdict (also written
  to `summary.json` when exporting). This is the token-efficient "is it broken?"
  readout — prefer it over opening a notebook.
- The sim is **stochastic, not bit-reproducible**; population means are stable to
  ~±0.05. Assert with tolerances, never exact values. `--seed N` reduces variance.
- For open-ended questions, write a **Tier-1** script (`dev analyze`); for human
  dashboards, a **Tier-2** marimo notebook. Keep durable checks as assertions in
  `tests/test_simulation_smoke.py`.

**Note**: The graph command uses `npx @mermaid-js/mermaid-cli` to render diagrams. Requires Node.js with `npx` on PATH. Output defaults to `tmp/commodity-graph.svg` (gitignored).

## Code Style
- **Python**: 3.11+ with type annotations
- **Formatting**: `ruff format` (88 char lines)
- **Naming**: `snake_case` functions/vars, `PascalCase` classes, `UPPER_CASE` constants
- **Architecture**: Domain-driven design; prefer pure functions over stateful classes when suitable

### Tooling
Two tools, two jobs: **`ruff`** for style (lint + format) and **`mypy`** for
correctness (types). Black was removed — `ruff format` is its drop-in
replacement. Don't reintroduce a separate formatter.

## Branching

Work on **`main` only.** Commit directly to `main`; do **not** create feature
branches unless the user explicitly asks for one. This overrides the default
"branch before committing on the default branch" behavior.

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
| Planet attributes | See "Planet Attributes System" below | Per-planet resource availability |
| UI grid | `docs/actor_grid_ui.md` | Pygame UI development |
| **Commodity/process editing** | `.claude/skills/commodity-process-design/` | Modifying commodities, recipes, production chains |
| **Evaluating sim behavior** | `.claude/skills/sim-evaluation/` | Checking macro behavior after a change; KPI summary, analysis scripts, notebooks |

## Key Architecture Facts

These apply to most tasks:

- **Deferred market matching**: Orders execute at END of turn, not immediately
- **Brain pattern**: Actors/ships delegate decisions to pluggable `Brain` classes
- **Core files**: `core/simulation.py` (main loop), `core/actor.py`, `core/ship.py`, `core/market.py`
- **Feature flags**: Some features (like planet attributes) are toggled via CLI args and `setup_simple()` parameters

## Common Implementation Patterns

### Commodity System
Commodities are defined in `data/commodities.yaml` with a simple structure:
```yaml
- id: commodity_name
  name: Display Name
  transportable: true/false
  description: Text description
```

Commodities themselves have no planet-specific attributes. Planet-specific resource availability is controlled separately via the **Planet Attributes** system (see below).

> **To modify commodities or processes**, use the `commodity-process-design` skill which covers schemas, validation, and the graph generation workflow.

### Planet Attributes System

Planet attributes control resource availability per-planet. **Enabled by default** (disable with `--no-planet-attributes`).

**Core file**: `core/planet_attributes.py` - `PlanetAttributes` dataclass

**How it works**:
1. Each planet gets randomly generated attributes (0.0-1.0) for extractable resources
2. Gathering processes in `data/processes.yaml` specify a `resource_attribute` field
3. `ProcessCommand.execute()` applies the effect when the process runs

**Resource attributes** (defined on `PlanetAttributes`):
- `biomass`, `fiber`, `wood` - organic resources (always ≥0.2 or ≥0.0)
- `common_metal_ore`, `nova_fuel_ore` - mineral resources

**Effect types** (per-process in `processes.yaml`):
```yaml
resource_attribute:
  commodity: biomass      # Which planet attribute to check
  effect: output          # "output" = reduced yield, "success" = may fail entirely
```
- `output`: Low availability reduces output quantity (e.g., 0.25 availability → 25% of base output)
- `success`: Low availability causes random failure (e.g., 0.25 availability → 75% chance to fail)

**Current assignments**:
- Gathering processes (biomass, fiber, wood): `effect: output`
- Mining processes (nova_fuel_ore, common_metal_ore): `effect: success`

**Generation distributions** (in `PlanetAttributes.generate_random()`):
- `biomass`: uniform(0.2, 1.0) - always some organic life
- `nova_fuel_ore`: bimodal - either rare (0.0-0.3) or abundant (0.7-1.0)
- Others: uniform(0.0, 1.0)

**Adding a new extractable resource**:
1. Add attribute to `PlanetAttributes` dataclass with appropriate default (1.0)
2. Update `__post_init__` validation list
3. Update `generate_random()` with desired distribution
4. Update `to_dict()` for export
5. Add `resource_attribute` to the gathering process in `processes.yaml`

**Export**: When enabled, `planet_attributes.json` is written alongside other export files.

> **To add new extractable resources**, use the `commodity-process-design` skill for the process schema and validation workflow.

### Tool and Facility Requirements

Processes in `data/processes.yaml` specify `tools_required` and `facilities_required`. The economy is designed with a **wood-first bootstrap path** - actors can start with nothing and build up through wood before transitioning to metal.

**Current requirements**:

| Process | tools_required | facilities_required |
|---------|----------------|---------------------|
| gather_biomass | - | - |
| gather_fiber | - | - |
| harvest_wood | - | - |
| make_food | - | - |
| make_simple_tools_wood | - | - |
| mine_common_metal_ore | simple_tools | - |
| mine_nova_fuel_ore | simple_tools | - |
| make_building_materials_wood | simple_tools | - |
| make_building_materials_metal | simple_tools | - |
| build_smelting_facility | simple_tools | - |
| build_metalworking_facility | simple_tools | - |
| refine_common_metal | - | smelting_facility |
| make_simple_tools | - | metalworking_facility |
| make_clothing | simple_tools | - |
| refine_nova_fuel | simple_tools | - |

**Bootstrap path** (wood-first economy):
1. Harvest wood (no tools needed)
2. Make simple tools from wood (no facility needed)
3. Make building materials from wood (needs tools)
4. Build smelting facility (needs building materials + tools)
5. Mine common metal ore (needs tools)
6. Refine metal (needs smelting facility)
7. Build metalworking facility (needs building materials + tools)
8. Make simple tools from metal (more efficient, needs metalworking facility)

**Tool degradation**: Tools have a ~1% chance of breaking each time they're used. This creates ongoing demand for tool production.

**Brain behavior**:
- ColonistBrain: Prioritizes acquiring tools before profitable work
- IndustrialistBrain: Builds required facilities, acquires tools for chosen recipe

> **To modify process requirements**, use the `commodity-process-design` skill which covers validation and ensuring the bootstrap path remains viable.

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

**Material requirements**:
- FoodDrive: `food`
- ClothingDrive: `clothing`
- ShelterDrive: `simple_building_materials`

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
