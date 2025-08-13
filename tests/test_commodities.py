import pytest
import tempfile
import os
import yaml

from spacesim2.core.commodity import CommodityRegistry, CommodityDefinition, Inventory
from spacesim2.core.commands import ProcessCommand
from spacesim2.core.process import ProcessRegistry, ProcessDefinition
from spacesim2.core.actor import Actor
from spacesim2.core.planet import Planet
from spacesim2.core.market import Market
from spacesim2.core.simulation import Simulation

from .helpers import get_actor


def test_load_commodities_from_yaml():
    """Test loading commodities from YAML file."""
    # Create a temp YAML file
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.yaml') as f:
        yaml.dump([
            {
                'id': 'test_commodity',
                'name': 'Test Commodity',
                'transportable': True,
                'description': 'A test commodity',
            }
        ], f)
        temp_file = f.name
    
    try:
        # Load the file
        registry = CommodityRegistry()
        registry.load_from_file(temp_file)
        
        # Check if commodity was loaded
        commodity = registry.get_commodity('test_commodity')
        assert commodity is not None
        assert commodity.id == 'test_commodity'
        assert commodity.name == 'Test Commodity'
        assert commodity.transportable is True
        assert commodity.description == 'A test commodity'
    finally:
        # Clean up
        os.unlink(temp_file)


def test_load_processes_from_yaml():
    """Test loading processes from YAML file."""
    # First create commodity registry with required commodities
    commodity_registry = CommodityRegistry()
    
    # Add the necessary commodities
    input_commodity = CommodityDefinition(
        id="input_commodity",
        name="Input Commodity",
        transportable=True,
        description="Test input"
    )
    output_commodity = CommodityDefinition(
        id="output_commodity",
        name="Output Commodity",
        transportable=True,
        description="Test output"
    )
    tool_commodity = CommodityDefinition(
        id="tool_commodity",
        name="Tool Commodity",
        transportable=True,
        description="Test tool"
    )
    facility_commodity = CommodityDefinition(
        id="facility_commodity",
        name="Facility Commodity",
        transportable=False,
        description="Test facility"
    )
    
    # Register the commodities
    commodity_registry._commodities["input_commodity"] = input_commodity
    commodity_registry._commodities["output_commodity"] = output_commodity
    commodity_registry._commodities["tool_commodity"] = tool_commodity
    commodity_registry._commodities["facility_commodity"] = facility_commodity
    
    # Create a temp YAML file for processes
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.yaml') as f:
        yaml.dump([
            {
                'id': 'test_process',
                'name': 'Test Process',
                'inputs': {'input_commodity': 2},
                'outputs': {'output_commodity': 1},
                'tools_required': ['tool_commodity'],
                'facilities_required': ['facility_commodity'],
                'labor': 3,
                'description': 'A test process',
            }
        ], f)
        process_file = f.name
    
    try:
        # Load the processes file
        process_registry = ProcessRegistry(commodity_registry)
        process_registry.load_from_file(process_file)
        
        # Check if process was loaded
        process = process_registry.get_process('test_process')
        assert process is not None
        assert process.id == 'test_process'
        assert process.name == 'Test Process'
        assert len(process.inputs) == 1
        assert input_commodity in process.inputs
        assert process.inputs[input_commodity] == 2
        assert len(process.outputs) == 1
        assert output_commodity in process.outputs
        assert process.outputs[output_commodity] == 1
        assert len(process.tools_required) == 1
        assert tool_commodity in process.tools_required
        assert len(process.facilities_required) == 1 
        assert facility_commodity in process.facilities_required
        assert process.labor == 3
        assert process.description == 'A test process'
    finally:
        # Clean up
        os.unlink(process_file)


def test_inventory_commodity_items(mock_sim):
    """Test the Inventory class with string commodity IDs."""
    mock_sim = mock_sim
    inventory = Inventory()
    
    # Add and check commodity
    inventory.add_commodity("test_commodity", 5)
    assert inventory.get_quantity("test_commodity") == 5
    
    # Remove some and check
    inventory.remove_commodity("test_commodity", 2)
    assert inventory.get_quantity("test_commodity") == 3
    
    # Reserve some and check
    assert inventory.reserve_commodity("test_commodity", 1)
    assert inventory.get_available_quantity("test_commodity") == 2
    assert inventory.get_reserved_quantity("test_commodity") == 1
    assert inventory.get_quantity("test_commodity") == 3
    
    # Unreserve and check
    inventory.unreserve_commodity("test_commodity", 1)
    assert inventory.get_available_quantity("test_commodity") == 3
    assert inventory.get_reserved_quantity("test_commodity") == 0
    assert inventory.get_quantity("test_commodity") == 3


def test_actor_execute_process():
    """Test actor executing a process."""
    # Set up simulation
    sim = Simulation()
    
    # Set up commodity registry
    sim.commodity_registry = CommodityRegistry()
    sim.commodity_registry._commodities["input_commodity"] = CommodityDefinition(
        id="input_commodity",
        name="Input Commodity",
        transportable=True,
        description="Test input",
    )
    sim.commodity_registry._commodities["output_commodity"] = CommodityDefinition(
        id="output_commodity",
        name="Output Commodity",
        transportable=True,
        description="Test output",
    )
    sim.commodity_registry._commodities["tool_commodity"] = CommodityDefinition(
        id="tool_commodity",
        name="Tool Commodity",
        transportable=True,
        description="Test tool",
    )
    sim.commodity_registry._commodities["facility_commodity"] = CommodityDefinition(
        id="facility_commodity",
        name="Facility Commodity",
        transportable=False,
        description="Test facility",
    )
    
    # Create process registry
    sim.process_registry = ProcessRegistry(sim.commodity_registry)
    
    # Add a test process
    process_def = ProcessDefinition(
        id="test_process",
        name="Test Process",
        inputs={"input_commodity": 2},
        outputs={"output_commodity": 1},
        tools_required=["tool_commodity"],
        facilities_required=["facility_commodity"],
        labor=1,
        description="A test process",
    )
    sim.process_registry._processes["test_process"] = process_def
    
    # Create planet
    market = Market()
    planet = Planet("Test Planet", market)
    
    # Create actor with required inputs, tools, and facilities  
    actor = get_actor("Test Actor", sim, planet=planet)
    actor.inventory.add_commodity("input_commodity", 5)
    actor.inventory.add_commodity("tool_commodity", 1)
    actor.inventory.add_commodity("facility_commodity", 1)  # Actor has the facility
    
    # Execute process via command pattern
    command = ProcessCommand("test_process")
    result = command.execute(actor)
    assert result is True
    
    # Check results
    assert actor.inventory.get_quantity("input_commodity") == 3  # 5 - 2
    assert actor.inventory.get_quantity("output_commodity") == 1
    assert actor.inventory.get_quantity("tool_commodity") == 1  # Tools aren't consumed
    assert actor.last_action == "Executed process: Test Process"


def test_process_requires_facility():
    """Test that process requires facility."""
    # Set up simulation
    sim = Simulation()
    
    # Set up commodity registry
    sim.commodity_registry = CommodityRegistry()
    sim.commodity_registry._commodities["input_commodity"] = CommodityDefinition(
        id="input_commodity",
        name="Input Commodity",
        transportable=True,
        description="Test input",
    )
    sim.commodity_registry._commodities["output_commodity"] = CommodityDefinition(
        id="output_commodity",
        name="Output Commodity",
        transportable=True,
        description="Test output",
    )
    sim.commodity_registry._commodities["facility_commodity"] = CommodityDefinition(
        id="facility_commodity",
        name="Facility Commodity",
        transportable=False,
        description="Test facility",
    )
    
    # Create process registry
    sim.process_registry = ProcessRegistry(sim.commodity_registry)
    
    # Add a test process requiring a facility
    process_def = ProcessDefinition(
        id="test_process",
        name="Test Process",
        inputs={"input_commodity": 1},
        outputs={"output_commodity": 1},
        tools_required=[],
        facilities_required=["facility_commodity"],
        labor=1,
        description="A test process",
    )
    sim.process_registry._processes["test_process"] = process_def
    
    # Create planet
    market = Market()
    planet = Planet("Test Planet", market)
    
    # Create actor with required inputs but without facility
    actor = get_actor("Test Actor", sim, planet=planet)
    actor.inventory.add_commodity("input_commodity", 5)
    
    # Try to execute process - should fail because actor doesn't have the facility
    command1 = ProcessCommand("test_process")
    result = command1.execute(actor)
    assert result is False
    
    # Add the facility to actor's inventory
    actor.inventory.add_commodity("facility_commodity", 1)
    
    # Try again - should succeed
    command2 = ProcessCommand("test_process")
    result = command2.execute(actor)
    assert result is True
    
    # Check results
    assert actor.inventory.get_quantity("input_commodity") == 4  # 5 - 1
    assert actor.inventory.get_quantity("output_commodity") == 1