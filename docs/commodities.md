# Commodities and Processes System

## Overview

The commodity system in SpaceSim2 uses a data-driven approach to define commodities and production processes. This allows for flexible expansion of the in-game economy without requiring code changes. All commodity and process definitions are stored in YAML files in the `data/` directory.

## Key Concepts

### Commodity Definitions

Commodities represent physical goods and resources in the simulation. They are defined in `data/commodities.yaml` with the following attributes:

- `id`: Unique string identifier (e.g., "food", "nova_fuel")
- `name`: Human-readable name
- `transportable`: Boolean indicating if the commodity can be transported by ships
- `description`: Text description of the commodity

**Implementation Note**: Commodities are loaded and managed by the `CommodityRegistry` class. Throughout the codebase, commodities are always represented by `CommodityDefinition` objects, not by string IDs.

### Process Definitions

Processes represent production activities that transform inputs into outputs. They are defined in `data/processes.yaml` with the following attributes:

- `id`: Unique string identifier (e.g., "make_food", "refine_metal")
- `name`: Human-readable name
- `inputs`: Dictionary mapping commodity IDs to required quantities
- `outputs`: Dictionary mapping commodity IDs to produced quantities
- `tools_required`: List of tool commodity IDs needed (actors must have these)
- `facilities_required`: List of facility commodity IDs needed (actors must have these)
- `labor`: Amount of labor required
- `description`: Text description of the process

**Implementation Note**: Processes are loaded and managed by the `ProcessRegistry` class, which requires a reference to the `CommodityRegistry` to convert string IDs to `CommodityDefinition` objects.

### Inventory Management

The `Inventory` class is used by actors, ships, and other entities to track commodities. Key methods:

- `add_commodity(commodity, quantity)`: Add commodities to the inventory
- `remove_commodity(commodity, quantity)`: Remove commodities from the inventory
- `has_quantity(commodity, quantity)`: Check if the inventory has enough of a commodity
- `get_quantity(commodity)`: Get the total quantity of a commodity
- `get_available_quantity(commodity)`: Get the unreserved quantity of a commodity
- `reserve_commodity(commodity, quantity)`: Reserve commodities for market transactions
- `unreserve_commodity(commodity, quantity)`: Unreserve commodities

**Implementation Note**: All inventory methods require `CommodityDefinition` objects as parameters, not string IDs.

### Actor Process Execution

Actors can execute processes through their brain's `execute_process(process_id)` method. This method:

1. Gets the process definition from the registry
2. Checks if the actor has all required inputs
3. Checks if the actor has all required tools
4. Checks if the actor has access to all required facilities
5. Consumes inputs and produces outputs if all requirements are met

Actors can also evaluate the profitability of processes based on current market prices using the `_find_most_profitable_process()` method.

### Market Integration

The market system has been updated to work with `CommodityDefinition` objects:

- Orders and transactions use `CommodityDefinition` objects
- Price histories are tracked per commodity
- Market makers provide liquidity for commodities based on inventory levels
- Actors can buy and sell using their inventory reserved/unreserve system

## Adding New Commodities and Processes

Use the `commodity-process-design` skill — it covers schemas, validation,
bootstrap-path checks, and the dependency-graph workflow.