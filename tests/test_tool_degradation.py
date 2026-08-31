"""Tests for tool degradation during process execution."""

from unittest.mock import MagicMock

from spacesim2.core.commands import ProcessCommand
from spacesim2.core.commodity import CommodityDefinition, CommodityRegistry
from spacesim2.core.market import Market
from spacesim2.core.planet import Planet
from spacesim2.core.process import ProcessDefinition, ProcessRegistry
from spacesim2.core.simulation import Simulation

from .helpers import FixedRandom, get_actor


def create_sim_with_tool_process():
    """Helper to create a simulation with a process that requires tools."""
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
    sim.commodity_registry._commodities["simple_tools"] = CommodityDefinition(
        id="simple_tools",
        name="Simple Tools",
        transportable=True,
        description="Test tool",
    )

    # Create process registry
    sim.process_registry = ProcessRegistry(sim.commodity_registry)

    # Add a test process that requires tools
    process_def = ProcessDefinition(
        id="test_process",
        name="Test Process",
        inputs={"input_commodity": 1},
        outputs={"output_commodity": 1},
        tools_required=["simple_tools"],
        facilities_required=[],
        labor=1,
        description="A test process requiring tools",
    )
    sim.process_registry._processes["test_process"] = process_def

    return sim


def test_tool_not_consumed_on_successful_process():
    """Test that tools are not automatically consumed when process succeeds."""
    sim = create_sim_with_tool_process()

    # Create planet
    market = Market()
    planet = Planet("Test Planet", market)

    # Create actor with inputs and tools
    actor = get_actor("Test Actor", sim, planet=planet)
    actor.inventory.add_commodity("input_commodity", 5)
    actor.inventory.add_commodity("simple_tools", 3)

    # Execute process with controlled randomness (no degradation):
    # pin the actor's RNG above the 0.01 tool-break threshold.
    actor.rng = FixedRandom(0.5)
    command = ProcessCommand("test_process")
    result = command.execute(actor)

    assert result is True
    assert actor.inventory.get_quantity("simple_tools") == 3  # Tools not consumed


def test_tool_breaks_when_random_below_threshold():
    """Test that tool breaks when random value is below threshold."""
    sim = create_sim_with_tool_process()

    # Create planet
    market = Market()
    planet = Planet("Test Planet", market)

    # Create actor with inputs and tools
    actor = get_actor("Test Actor", sim, planet=planet)
    actor.inventory.add_commodity("input_commodity", 5)
    actor.inventory.add_commodity("simple_tools", 3)

    # Execute process with controlled randomness (force degradation):
    # pin the actor's RNG below the 0.01 tool-break threshold.
    actor.rng = FixedRandom(0.005)
    command = ProcessCommand("test_process")
    result = command.execute(actor)

    assert result is True
    assert actor.inventory.get_quantity("simple_tools") == 2  # One tool broke


def test_tool_break_logged_when_data_logger_present():
    """Test that tool breakage is logged via data_logger."""
    sim = create_sim_with_tool_process()

    # Add mock data logger
    mock_logger = MagicMock()
    sim.data_logger = mock_logger

    # Create planet
    market = Market()
    planet = Planet("Test Planet", market)

    # Create actor with inputs and tools
    actor = get_actor("Test Actor", sim, planet=planet)
    actor.inventory.add_commodity("input_commodity", 5)
    actor.inventory.add_commodity("simple_tools", 3)

    # Execute process with controlled randomness (force degradation):
    # pin the actor's RNG below the 0.01 tool-break threshold.
    actor.rng = FixedRandom(0.005)
    command = ProcessCommand("test_process")
    result = command.execute(actor)

    assert result is True
    # Check that log_actor_note was called
    mock_logger.log_actor_note.assert_called_once()
    call_args = mock_logger.log_actor_note.call_args
    assert call_args[0][0] == actor
    assert "Tool broke" in call_args[0][1]
    assert "simple_tools" in call_args[0][1]  # String ID in test setup


def test_tool_degradation_only_after_successful_process():
    """Test that tools don't degrade if the process fails."""
    sim = create_sim_with_tool_process()

    # Create planet
    market = Market()
    planet = Planet("Test Planet", market)

    # Create actor with tools but NO inputs - process should fail
    actor = get_actor("Test Actor", sim, planet=planet)
    actor.inventory.add_commodity("simple_tools", 3)
    # Note: no input_commodity added

    # Try to execute process - should fail due to missing inputs
    actor.rng = FixedRandom(0.005)  # Would cause degradation on success
    command = ProcessCommand("test_process")
    result = command.execute(actor)

    assert result is False
    assert actor.inventory.get_quantity("simple_tools") == 3  # Tools unchanged


def test_tool_degradation_probability_is_independent_per_tool():
    """Test that with multiple tools required, each has independent degradation chance."""
    sim = Simulation()

    # Set up commodity registry with two tool types
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
    sim.commodity_registry._commodities["tool_a"] = CommodityDefinition(
        id="tool_a",
        name="Tool A",
        transportable=True,
        description="First tool",
    )
    sim.commodity_registry._commodities["tool_b"] = CommodityDefinition(
        id="tool_b",
        name="Tool B",
        transportable=True,
        description="Second tool",
    )

    # Create process registry
    sim.process_registry = ProcessRegistry(sim.commodity_registry)

    # Add a process requiring both tools
    process_def = ProcessDefinition(
        id="multi_tool_process",
        name="Multi Tool Process",
        inputs={"input_commodity": 1},
        outputs={"output_commodity": 1},
        tools_required=["tool_a", "tool_b"],
        facilities_required=[],
        labor=1,
        description="Process requiring two tools",
    )
    sim.process_registry._processes["multi_tool_process"] = process_def

    # Create planet
    market = Market()
    planet = Planet("Test Planet", market)

    # Create actor
    actor = get_actor("Test Actor", sim, planet=planet)
    actor.inventory.add_commodity("input_commodity", 5)
    actor.inventory.add_commodity("tool_a", 3)
    actor.inventory.add_commodity("tool_b", 3)

    # Both tools break (every roll below the 0.01 threshold)
    actor.rng = FixedRandom(0.005)
    command = ProcessCommand("multi_tool_process")
    result = command.execute(actor)

    assert result is True
    assert actor.inventory.get_quantity("tool_a") == 2  # One broke
    assert actor.inventory.get_quantity("tool_b") == 2  # One broke


def test_process_without_tools_has_no_degradation():
    """Test that processes without tool requirements don't trigger degradation."""
    sim = Simulation()

    # Set up commodity registry
    sim.commodity_registry = CommodityRegistry()
    sim.commodity_registry._commodities["biomass"] = CommodityDefinition(
        id="biomass",
        name="Biomass",
        transportable=True,
        description="Raw biomass",
    )

    # Create process registry
    sim.process_registry = ProcessRegistry(sim.commodity_registry)

    # Add a gathering process (no tools required)
    process_def = ProcessDefinition(
        id="gather_biomass",
        name="Gather Biomass",
        inputs={},
        outputs={"biomass": 4},
        tools_required=[],
        facilities_required=[],
        labor=1,
        description="Gather biomass by hand",
    )
    sim.process_registry._processes["gather_biomass"] = process_def

    # Create planet
    market = Market()
    planet = Planet("Test Planet", market)

    # Create actor
    actor = get_actor("Test Actor", sim, planet=planet)

    # Execute process (should work fine with no tools)
    command = ProcessCommand("gather_biomass")
    result = command.execute(actor)

    assert result is True
    assert actor.inventory.get_quantity("biomass") == 4


def test_statistical_tool_degradation_rate():
    """Test that tool degradation rate is approximately 1% over many runs."""
    sim = create_sim_with_tool_process()

    # Create planet
    market = Market()
    planet = Planet("Test Planet", market)

    # Run many processes and count degradation events
    num_runs = 10000
    degradation_count = 0

    for _ in range(num_runs):
        actor = get_actor("Test Actor", sim, planet=planet)
        actor.inventory.add_commodity("input_commodity", 1)
        actor.inventory.add_commodity("simple_tools", 1)

        command = ProcessCommand("test_process")
        command.execute(actor)

        # Check if tool broke
        if actor.inventory.get_quantity("simple_tools") == 0:
            degradation_count += 1

    # Expected rate is 1% (0.01)
    # With 10000 runs, expect ~100 degradations
    # Allow for statistical variance (roughly 3 standard deviations)
    expected = num_runs * 0.01
    std_dev = (num_runs * 0.01 * 0.99) ** 0.5
    tolerance = 4 * std_dev  # Very generous tolerance

    assert abs(degradation_count - expected) < tolerance, (
        f"Degradation rate {degradation_count / num_runs:.4f} "
        f"differs significantly from expected 0.01"
    )
