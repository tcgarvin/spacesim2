---
name: commodity-process-design
description: Edit commodities and production processes for the economic simulation. Use when adding/modifying commodities, recipes, production chains, tool requirements, facility requirements, or resource attributes. Also covers generating dependency graphs.
---

# Commodity & Process Design

Guide for editing the economic simulation's commodities and production processes.

## Data Files

| File | Purpose |
|------|---------|
| `data/commodities.yaml` | Define tradeable goods and facilities |
| `data/processes.yaml` | Define production recipes |

See `CLAUDE.md` for current state (requirements table, bootstrap path, drive mappings).

## Commodity Schema

```yaml
- id: commodity_id           # snake_case, unique identifier
  name: Display Name         # Human-readable name
  transportable: true/false  # Can ships carry this? (false for facilities)
  description: Text          # What is this commodity?
```

## Process Schema

```yaml
- id: process_id
  name: Display Name
  inputs:                    # Commodities consumed (empty {} for gathering)
    commodity_id: quantity
  outputs:                   # Commodities produced
    commodity_id: quantity
  tools_required: []         # List of tool commodity IDs, or empty []
  facilities_required: []    # List of facility commodity IDs, or empty []
  labor: 1                   # Labor units required
  relevant_skills:           # Skills that improve efficiency
    - skill_name
  description: Text
  resource_attribute:        # Optional: for gathering/mining processes only
    commodity: attribute_id  # Planet attribute to check (see CLAUDE.md)
    effect: output|success   # output=reduced yield, success=may fail
```

## Key Constraints

### Bootstrap Path
The economy must have a **bootstrap path** where actors start with nothing and can reach tools without requiring tools first.

**When modifying processes**: Always verify a tool-free path to initial tools exists. Run the graph command (below) to visualize and confirm.

### Resource Attributes
For new gathering/extraction processes tied to planetary resources:
1. Add attribute to `core/planet_attributes.py` PlanetAttributes dataclass
2. Add `resource_attribute` field to the process in `processes.yaml`

### Drive Dependencies
If changing what commodity a drive consumes, update the corresponding drive class in `core/drives/`. See CLAUDE.md for current drive-to-commodity mappings.

## Workflow

### 1. Make Changes
Edit `data/commodities.yaml` and/or `data/processes.yaml`.

### 2. Verify Syntax
```bash
uv run python -c "import yaml; yaml.safe_load(open('data/commodities.yaml')); yaml.safe_load(open('data/processes.yaml')); print('OK')"
```

### 3. Generate Dependency Graph
```bash
uv run spacesim2 dev graph
```

Outputs `tmp/commodity-graph.svg` and `tmp/commodity-graph.mmd`.

### 4. Review Graph
Check the SVG for:
- All commodities connected to at least one process
- No orphan processes (missing input commodities)
- Bootstrap path exists (path from nothing to tools)
- No impossible cycles

### 5. Run Tests
```bash
uv run pytest tests/ -v
```

### 6. Update Documentation
If the bootstrap path or requirements table changed, update the corresponding section in `CLAUDE.md`.
