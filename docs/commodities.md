# Commodities and Processes

Commodities and production processes are data: `data/commodities.yaml` and
`data/processes.yaml`. The economy can be extended without code changes.

## Commodities

Each entry has `id`, `name`, `transportable` (can ships carry it; false for
facilities) and `description`. `CommodityRegistry` (`core/commodity.py`)
loads them. Everywhere in the codebase a commodity is a
`CommodityDefinition` object, never a string id.

## Processes

Each entry has `id`, `name`, `inputs` and `outputs` (commodity id to
quantity), `tools_required`, `facilities_required`, `labor`,
`relevant_skills` and `description`. `ProcessRegistry` (`core/process.py`)
loads them and needs a `CommodityRegistry` to resolve ids to
`CommodityDefinition` objects. Full schema: the `commodity-process-design`
skill.

## Inventory

`Inventory` (`core/commodity.py`) tracks commodities for actors and ships.
All methods take `CommodityDefinition` objects.

| Method | Purpose |
|--------|---------|
| `add_commodity(commodity, quantity)` | Add stock |
| `remove_commodity(commodity, quantity)` | Remove stock |
| `has_quantity(commodity, quantity)` | Enough in stock? |
| `get_quantity(commodity)` | Total held |
| `get_available_quantity(commodity)` | Unreserved amount |
| `reserve_commodity(commodity, quantity)` | Hold stock for a market order |
| `unreserve_commodity(commodity, quantity)` | Release a hold |

## Process execution

`ProcessCommand.execute(actor)` in `core/commands.py` runs a process. It
checks inputs, tools and facilities, applies the skill check
(`docs/skills.md`) and the planet resource attribute, then consumes inputs
and adds outputs. Brains pick processes by market profitability; see
`_find_most_profitable_process` in `core/brains/colonist.py`.

## Market

Orders, transactions and price histories are keyed by `CommodityDefinition`.
Market makers quote liquidity from their inventory levels. Sellers reserve
inventory while an order rests and unreserve on cancel.

## Facilities

Facilities are commodities with `transportable: false` that appear in a
process's `facilities_required`. They are not consumed when the process runs.
The tier-2 facilities are `textile_mill`, `chemistry_lab`, `chemical_plant`,
`precision_forge`, `electronics_workshop` and `farm`; each has a `build_*`
process taking simple building materials and tier-1 inputs.

`heavy_machinery` is a tier-1-to-2 industrial good, transportable and
consumed, not a facility itself: `build_chemical_plant` and `build_farm` both
take it as a build input, and `process_food` and `farm_biomass` both draw on
it as upkeep (a 0.01 per-run chance of consuming 1 unit; see "Upkeep" in
CLAUDE.md).

## Capital

A process may carry a `capital` mapping of commodity id to an output bonus
fraction, the same shape as `upkeep`:

```yaml
capital:
  computers: 0.25
```

Holding at least 1 unit of the good multiplies the run's output by
`1 + bonus`; holding more adds nothing, and bonuses from several capital
goods sum. Capital is not a precondition and is never consumed by a run: it
breaks with probability `CAPITAL_BREAK_PROBABILITY` (0.005) after a
successful run, a mean life of 200 runs, five times a tool's. Upkeep draws
are never scaled by the bonus.

Every process with a non-empty `facilities_required` lists
`computers: 0.25`, 21 processes in all. Gathering and hand recipes list none:
a computer does not help pick berries. `IndustrialistBrain` keeps 1 unit of
each capital good its chosen recipe lists, bids for it at the extra output
over its expected life (`_capital_willingness_to_pay`), and never lists that
unit for sale. Colonists do not buy computers.

## Adding commodities or processes

Use the `commodity-process-design` skill. It covers the schemas, validation,
the bootstrap-path check and the dependency graph.
