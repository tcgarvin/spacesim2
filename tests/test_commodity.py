import pytest
import os
import yaml

from spacesim2.core.commodity import CommodityDefinition, CommodityRegistry, Inventory
from spacesim2.core.process import ProcessRegistry
from spacesim2.core.simulation import Simulation


def test_commodity_registry_loading() -> None:
    """Test that the commodity registry can load commodities from a YAML file."""
    # Create a test YAML file
    test_yaml_path = "temp_test_commodities.yaml"
    test_commodities = [
        {
            "id": "test_commodity",
            "name": "Test Commodity",
            "transportable": True,
            "description": "A test commodity"
        },
        {
            "id": "test_facility",
            "name": "Test Facility",
            "transportable": False,
            "description": "A test facility"
        }
    ]
    
    with open(test_yaml_path, 'w') as f:
        yaml.dump(test_commodities, f)
    
    # Load the commodities
    registry = CommodityRegistry()
    registry.load_from_file(test_yaml_path)
    
    # Clean up the test file
    os.remove(test_yaml_path)
    
    # Check that the commodities were loaded correctly
    test_commodity = registry.get_commodity("test_commodity")
    test_facility = registry.get_commodity("test_facility")
    
    assert test_commodity is not None
    assert test_facility is not None
    
    assert test_commodity.id == "test_commodity"
    assert test_commodity.name == "Test Commodity"
    assert test_commodity.transportable == True
    
    assert test_facility.id == "test_facility"
    assert test_facility.name == "Test Facility"
    assert test_facility.transportable == False
    
    # Test all_commodities method
    all_commodities = registry.all_commodities()
    assert len(all_commodities) == 2
    assert test_commodity in all_commodities
    assert test_facility in all_commodities


def test_inventory_operations() -> None:
    """Test that inventory operations work correctly with CommodityDefinition objects."""
    # Create some test commodities
    food = CommodityDefinition(
        id="food",
        name="Food",
        transportable=True,
        description="Basic nourishment required by actors."
    )
    
    tools = CommodityDefinition(
        id="simple_tools",
        name="Simple Tools",
        transportable=True,
        description="Basic hand tools used in simple production processes."
    )
    
    # Create an inventory with clean state
    inventory = Inventory()
    
    # Initially empty
    assert inventory.get_quantity(food) == 0
    assert not inventory.has_quantity(food, 1)
    
    # Add commodity
    inventory.add_commodity(food, 5)
    assert inventory.get_quantity(food) == 5
    assert inventory.has_quantity(food, 3)
    assert not inventory.has_quantity(food, 6)
    
    # Add another commodity
    inventory.add_commodity(tools, 2)
    assert inventory.get_quantity(tools) == 2
    
    # Test get_total_quantity
    assert inventory.get_total_quantity() == 7
    
    # Remove commodity
    assert inventory.remove_commodity(food, 2)
    assert inventory.get_quantity(food) == 3
    
    # Try to remove more than available
    assert not inventory.remove_commodity(food, 4)
    assert inventory.get_quantity(food) == 3
    
    # Remove all remaining
    assert inventory.remove_commodity(food, 3)
    assert inventory.get_quantity(food) == 0
    assert not inventory.has_quantity(food, 1)
    
    # No more testing with string IDs as we've removed that functionality


def test_inventory_reservation() -> None:
    """Test that inventory reservation works correctly."""
    # Create a test commodity
    food = CommodityDefinition(
        id="food",
        name="Food",
        transportable=True,
        description="Basic nourishment required by actors."
    )
    
    # Create an inventory
    inventory = Inventory()
    
    # Add some food
    inventory.add_commodity(food, 10)
    assert inventory.get_quantity(food) == 10
    assert inventory.get_available_quantity(food) == 10
    assert inventory.get_reserved_quantity(food) == 0
    
    # Reserve some food
    assert inventory.reserve_commodity(food, 3)
    assert inventory.get_quantity(food) == 10
    assert inventory.get_available_quantity(food) == 7
    assert inventory.get_reserved_quantity(food) == 3
    
    # Try to reserve more than available
    assert not inventory.reserve_commodity(food, 8)
    assert inventory.get_quantity(food) == 10
    assert inventory.get_available_quantity(food) == 7
    assert inventory.get_reserved_quantity(food) == 3
    
    # Unreserve some food
    inventory.unreserve_commodity(food, 2)
    assert inventory.get_quantity(food) == 10
    assert inventory.get_available_quantity(food) == 9
    assert inventory.get_reserved_quantity(food) == 1
    
    # Unreserve all remaining reserved food
    inventory.unreserve_commodity(food, 1)
    assert inventory.get_quantity(food) == 10
    assert inventory.get_available_quantity(food) == 10
    assert inventory.get_reserved_quantity(food) == 0


def test_process_registry_loading() -> None:
    """Test that the process registry can load processes from a YAML file."""
    # Create a commodity registry
    commodity_registry = CommodityRegistry()
    
    # Add test commodities
    test_commodities = [
        {
            "id": "test_input",
            "name": "Test Input",
            "transportable": True,
            "description": "A test input commodity"
        },
        {
            "id": "test_output",
            "name": "Test Output",
            "transportable": True,
            "description": "A test output commodity"
        },
        {
            "id": "test_tool",
            "name": "Test Tool",
            "transportable": True,
            "description": "A test tool commodity"
        },
        {
            "id": "test_facility",
            "name": "Test Facility",
            "transportable": False,
            "description": "A test facility commodity"
        }
    ]
    
    test_commodity_path = "temp_test_commodities.yaml"
    with open(test_commodity_path, 'w') as f:
        yaml.dump(test_commodities, f)
    
    commodity_registry.load_from_file(test_commodity_path)
    os.remove(test_commodity_path)
    
    # Create a test process YAML file
    test_yaml_path = "temp_test_processes.yaml"
    test_processes = [
        {
            "id": "test_process",
            "name": "Test Process",
            "inputs": {
                "test_input": 2
            },
            "outputs": {
                "test_output": 1
            },
            "tools_required": ["test_tool"],
            "facilities_required": ["test_facility"],
            "labor": 1,
            "description": "A test process"
        }
    ]
    
    with open(test_yaml_path, 'w') as f:
        yaml.dump(test_processes, f)
    
    # Load the processes
    process_registry = ProcessRegistry(commodity_registry)
    process_registry.load_from_file(test_yaml_path)
    
    # Clean up the test file
    os.remove(test_yaml_path)
    
    # Check that the process was loaded correctly
    test_process = process_registry.get_process("test_process")
    
    assert test_process is not None
    assert test_process.id == "test_process"
    assert test_process.name == "Test Process"
    
    # Get the commodities
    test_input = commodity_registry.get_commodity("test_input")
    test_output = commodity_registry.get_commodity("test_output")
    test_tool = commodity_registry.get_commodity("test_tool")
    test_facility = commodity_registry.get_commodity("test_facility")
    
    # Check that the inputs and outputs are using CommodityDefinition objects
    assert test_input in test_process.inputs
    assert test_process.inputs[test_input] == 2
    
    assert test_output in test_process.outputs
    assert test_process.outputs[test_output] == 1
    
    assert test_tool in test_process.tools_required
    assert test_facility in test_process.facilities_required
    
    # Test the process search methods
    producing_processes = process_registry.get_processes_producing(test_output)
    consuming_processes = process_registry.get_processes_consuming(test_input)
    
    assert len(producing_processes) == 1
    assert producing_processes[0] == test_process
    
    assert len(consuming_processes) == 1
    assert consuming_processes[0] == test_process