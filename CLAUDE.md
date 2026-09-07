# CLAUDE.md - Agent Instructions

## Project: SpaceSim2
A turn-based economic simulation of interplanetary trade with actors, markets, and ships.

## Commands

```bash
# Build & Run
uv sync                              # Install dependencies
uv sync --extra analysis             # Install with analysis features
uv run spacesim2 ui                  # Interactive UI (Pygame)
uv run spacesim2 run                 # Headless sim with progress bar (default)
uv run spacesim2 run --quiet         # Suppress all output
uv run spacesim2 run --no-export     # Quick run without data export
uv run spacesim2 run --log-actors all  # Detailed per-actor logging (also: N, or an actor name)
uv run spacesim2 run --planets 5     # Smaller galaxy (default is 100 planets)
uv run spacesim2 run --arms 4 --lane-density 0.3  # Spiral arm count / extra star lanes beyond the spanning tree

# Development
uv run pytest tests/                           # Run all tests
uv run pytest tests/test_file.py::test_fn -v   # Run single test
uv run mypy .                                  # Type check (correctness)
uv run ruff format .                           # Format
uv run ruff check .                            # Lint

# Dev Tools
uv run spacesim2 dev graph             # Commodity/process dependency graph (outputs to tmp/)
uv run spacesim2 dev graph --out foo   # Custom output path (creates foo.svg and foo.mmd)
uv run spacesim2 dev graph -f png      # Alternative formats: svg (default), png, pdf
uv run spacesim2 dev analyze FILE.py   # Run a Tier-1 analysis script against latest run
uv run spacesim2 dev check             # Umbrella: format+lint+types+pytest+short sim run
uv run spacesim2 dev check --fast      # Skip the slower types and sim stages
```

## The Dev Loop

Change, then verify:

```bash
uv run pytest -q                                                  # 1. unit tests (~2s)
uv run spacesim2 run --turns 200 --no-export --quiet --summary    # 2. macro behavior
# 3. read JSON between ===SUMMARY_BEGIN=== / ===SUMMARY_END=== (verdict + KPIs)
```

`uv run spacesim2 dev check` runs format, lint, types, pytest, and a short
`--summary` sim as one pass/fail gate. It only checks formatting, it does not
rewrite files. Use the three steps above when you need the KPI JSON itself.

- `--summary` prints compact KPI JSON and a `PASS/WARN/FAIL` verdict. When
  exporting it is also written to `summary.json`. Prefer it over a notebook.
- The sim is stochastic and not bit-reproducible. Population means are stable
  to about ±0.05. Assert with tolerances, never exact values. There is no seed
  knob; most randomness comes from `uuid4` and set iteration.
- For open-ended questions write a Tier-1 script and run it with
  `dev analyze`. For human dashboards write a Tier-2 marimo notebook. Durable
  checks go in `tests/test_simulation_smoke.py`. See the `sim-evaluation`
  skill for the tiers and output contract.

The graph command renders with `npx @mermaid-js/mermaid-cli`, so Node.js with
`npx` must be on PATH. Output defaults to `tmp/commodity-graph.svg` (gitignored).

## Code Style
- Python 3.11+ with type annotations
- `ruff format`, 88 char lines
- `snake_case` functions and variables, `PascalCase` classes, `UPPER_CASE` constants
- Domain-driven design; prefer pure functions over stateful classes where it fits

### Tooling
`ruff` handles style (lint and format). `mypy` handles correctness (types).
Do not add a separate formatter.

`hooks/pre-commit` runs `ruff format` and `ruff check` on staged Python files
and `uv run mypy .` over the whole project. mypy is blocking and the project is
clean; keep it that way. A fresh clone must wire the hook once:

```bash
git config core.hooksPath hooks
```

Bypass a single commit with `git commit --no-verify`.

Ruff config: `E501` is ignored because the formatter owns line length.
`notebooks/**` is exempt from lint (still formatted) because marimo's
cross-cell variables trigger false `F401`/`F821`/`I001`.

## Branching

Work on `main` only. Commit directly to `main`. Do not create feature branches
unless the user asks for one. This overrides the default "branch before
committing on the default branch" behavior.

## Documentation Index

| Topic | Document | When to Read |
|-------|----------|--------------|
| Simulation design | `docs/sim-design.md` | Game mechanics and rules |
| Turn flow & testing | `docs/dev-guide-simulation.md` | Debugging AI, market mechanics, testing |
| Ship trading AI | `docs/dev-guide-ships.md` | Ship brains, fuel and trade logic |
| Notebook analysis | `notebooks/README.md` | Marimo notebooks |
| Needs/drives system | `docs/needs.md` | Actor consumption |
| Skills system | `docs/skills.md` | Actor skill levels, production |
| Commodities | `docs/commodities.md` | Adding or modifying goods |
| Planet attributes | "Planet Attributes" below | Per-planet resource availability |
| Live galaxy UI | `docs/live-view.md` | Pygame UI development |
| Performance | `docs/performance.md` | Threaded actor phase, caches, open levers |
| Decision log | `docs/decision-log.md` | Why past changes were made |
| Commodity/process editing | `.claude/skills/commodity-process-design/` | Commodities, recipes, production chains |
| Evaluating sim behavior | `.claude/skills/sim-evaluation/` | KPI summary, analysis scripts, notebooks |

## Key Architecture Facts

- **Deferred market matching**: orders are matched at the end of the turn, not when placed.
- **Brain pattern**: actors and ships delegate decisions to pluggable `Brain` classes.
- **Core files**: `core/simulation.py` (main loop), `core/actor.py`, `core/ship.py`, `core/market.py`.
- **Star-lane galaxy**: `core/galaxy.py` builds a spiral layout and a connected planar lane graph. `core/navigation.py` routes along lanes, so distance is always the shortest lane route. Ships fly whole routes without docking at intermediate planets. Default is 100 planets (`--planets`, `--arms`, `--lane-density`).

## Common Implementation Patterns

### Commodities
Defined in `data/commodities.yaml`:
```yaml
- id: commodity_name
  name: Display Name
  transportable: true/false
  description: Text description
```

Commodities have no planet-specific attributes. Per-planet availability comes
from Planet Attributes below. Use the `commodity-process-design` skill to
modify commodities or processes.

### Planet Attributes

Every planet gets random attributes at setup. A directly constructed `Planet`
defaults to all availabilities 1.0.

Core file: `core/planet_attributes.py`, `PlanetAttributes` dataclass.

How it works:
1. Each planet gets a random attribute (0.0-1.0) per extractable resource.
2. Gathering processes in `data/processes.yaml` set a `resource_attribute` field.
3. `ProcessCommand.execute()` applies the effect when the process runs.

Attributes: `biomass`, `fiber`, `wood` (organic), `common_metal_ore`,
`nova_fuel_ore` (mineral).

Effect types:
```yaml
resource_attribute:
  commodity: biomass      # which planet attribute to check
  effect: output          # "output" or "success"
```
- `output`: output quantity scales with availability (0.25 gives 25% of base output).
- `success`: the process fails with probability 1 - availability.

Gathering processes (biomass, fiber, wood) use `output`. Mining processes
(nova_fuel_ore, common_metal_ore) use `success`.

Distributions in `PlanetAttributes.generate_random()`: `biomass` is
uniform(0.2, 1.0), `nova_fuel_ore` is bimodal (0.0-0.3 or 0.7-1.0), the rest
are uniform(0.0, 1.0).

Adding a new extractable resource:
1. Add the attribute to `PlanetAttributes` with default 1.0.
2. Add it to the `__post_init__` validation list.
3. Add its distribution to `generate_random()`.
4. Add it to `to_dict()` for export.
5. Add `resource_attribute` to the gathering process in `processes.yaml`.

`planet_attributes.json` is written with the other export files.

### Tool and Facility Requirements

Processes in `data/processes.yaml` specify `tools_required` and
`facilities_required`. The economy has a wood-first bootstrap path, so actors
can start with nothing:

1. Harvest wood (no tools)
2. Make simple tools from wood (no facility)
3. Make building materials from wood (needs tools)
4. Build smelting facility (needs building materials and tools)
5. Mine common metal ore (needs tools)
6. Refine metal (needs smelting facility)
7. Build metalworking facility (needs building materials and tools)
8. Make simple tools from metal (more efficient, needs metalworking facility)

Tools break with 1% probability per use, which keeps tool demand alive.
`ColonistBrain` acquires tools before profitable work. `IndustrialistBrain`
builds the facilities and acquires the tools its chosen recipe needs.

When changing requirements, use the `commodity-process-design` skill and keep
the bootstrap path viable.

#### Upkeep

A process may also carry an `upkeep` mapping of commodity id to a per-run
probability:

```yaml
upkeep:
  heavy_machinery: 0.01
```

Each entry is rolled once per run, after the input, tool, and facility checks
and before anything is consumed. A hit consumes 1 unit of that commodity; if
the actor does not hold it, the run fails with no side effects, the same way a
missing tool fails. The skill multiplier never doubles an upkeep draw.

Upkeep is not a precondition, so `can_execute_process` ignores it. Recipe
valuation charges the expected cost, probability times the imputed unit cost,
in both `_impute_recipe_cost` and the replacement-cost path. The industrialist
keeps 1 unit of each upkeep good its chosen recipe needs and does not sell that
unit off.

### Drives (Needs)

Drives live in `core/drives/` and inherit from `ActorDrive`.

- `FoodDrive` consumes 1 food every turn.
- `ClothingDrive`, `ShelterDrive`, and `HealthDrive` consume on random events
  with probability `BASE_EVENT_PROB` per turn (1/60, 1/120, and 1/90).

Every drive tracks four 0-1 metrics: `health` (immediate status), `debt`
(accumulated neglect), `buffer` (log-normalized days of supply), and `urgency`
(priority multiplier).

Materials: food uses `food`; clothing uses `clothing`; shelter uses
`simple_building_materials` or `prefab_housing`; health uses `medicine` or
`advanced_medicine`.

Adding a drive needs the whole supply chain:
1. Raw material and finished good in `data/commodities.yaml`.
2. Gathering and production processes in `data/processes.yaml`.
3. A drive class in `core/drives/`.
4. `colonist.py` and `industrialist.py` considering the need in `decide_economic_action()`.
5. Brains trading the new commodities (they iterate the registry, so no hardcoded list).

Drives fail silently if their commodity is missing from the registry
(`get_commodity()` returns `None`). Check the commodity exists first.

### Dynamic Commodity Handling

Market makers and actor brains iterate the registry rather than a hardcoded list:

```python
# GOOD
all_commodities = [c for c in actor.sim.commodity_registry.all_commodities() if c.transportable]
for commodity in all_commodities:
    ...

# BAD
for commodity in (food, fuel, wood):
    ...
```

## Analysis

The default loop is the Dev Loop above: `--summary` for the verdict, a
`dev analyze` script for open-ended questions. Marimo notebooks are an optional
human-facing dashboard.

```bash
uv run spacesim2 run --notebook          # export and open notebooks/analysis_template.py
# or
uv run spacesim2 run
uv run marimo edit --no-token notebooks/analysis_template.py   # finds the latest run via SPACESIM_RUN_PATH
```

Before handing a notebook to the user, run `uv run marimo check` on it and
start the server. Marimo pitfalls: prefix cell-local variables with `_`,
assign conditional outputs to a named variable before displaying, and do not
return unused variables.

When to use what:
- `--summary`: did my change break the economy?
- `dev analyze` script: open-ended behavioral questions, debugging
- Marimo notebook: interactive charts for a human
- pytest: durable assertions, for example:
```python
def test_specific_behavior():
    sim = Simulation()
    sim.setup_simple(num_planets=2, num_regular_actors=10, num_market_makers=1, num_ships=1)
    sim.run_turn()
    # ... assertions
```
