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

## Adding commodities or processes

Use the `commodity-process-design` skill. It covers the schemas, validation,
the bootstrap-path check and the dependency graph.
