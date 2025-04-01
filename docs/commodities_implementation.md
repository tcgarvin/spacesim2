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

To add new commodities and processes to the simulation:

1. Add new commodity definitions to `data/commodities.yaml`
2. Add new process definitions to `data/processes.yaml`
3. Ensure that all used commodity IDs match between the files
4. The simulation will automatically load these at startup

## Design Considerations

1. **Strict Type Safety**: The implementation only allows `CommodityDefinition` objects to be used throughout the code, not string IDs. This provides better type checking and prevents errors.

2. **Registry Access**: Most components access the commodity and process registries through the `Simulation` instance, which is passed to actors, ships, and planets.

3. **Facilities Ownership**: Facilities are owned by actors, not planets. This means actors must personally own any facilities required by their processes.

4. **Dynamic Pricing**: Commodity prices are determined by market forces (supply and demand) rather than by fixed base prices. Market makers help provide liquidity.

5. **Memory Efficiency**: `CommodityDefinition` objects are shared references, so multiple inventory entries for the same commodity type don't duplicate the definition data.