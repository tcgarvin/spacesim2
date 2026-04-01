"""Integration tests for tool and facility economy."""

import pytest
from unittest.mock import patch

from spacesim2.core.simulation import Simulation
from spacesim2.core.commands import ProcessCommand


class TestBootstrapPath:
    """Test that actors can bootstrap from nothing to having tools."""

    def test_harvest_wood_works_without_tools(self):
        """Test that harvesting wood requires no tools (bootstrap entry point)."""
        sim = Simulation()
        sim.setup_simple(
            num_planets=1,
            num_regular_actors=1,
            num_market_makers=0,
            num_ships=0,
        )

        actor = sim.actors[0]

        # Harvest wood should be possible with no tools
        can_execute = actor.can_execute_process("harvest_wood")
        assert can_execute, "Should be able to harvest wood without tools"

    def test_make_simple_tools_wood_works_without_tools(self):
        """Test that making wood tools requires no tools (bootstrap step 2)."""
        sim = Simulation()
        sim.setup_simple(
            num_planets=1,
            num_regular_actors=1,
            num_market_makers=0,
            num_ships=0,
        )

        actor = sim.actors[0]

        # Give actor enough wood
        wood = sim.commodity_registry.get_commodity("wood")
        actor.inventory.add_commodity(wood, 10)

        # Making wood tools should be possible with no tools
        can_execute = actor.can_execute_process("make_simple_tools_wood")
        assert can_execute, "Should be able to make simple tools from wood without existing tools"

    def test_build_smelting_facility_requires_tools(self):
        """Test that building a smelting facility requires tools."""
        sim = Simulation()
        sim.setup_simple(
            num_planets=1,
            num_regular_actors=1,
            num_market_makers=0,
            num_ships=0,
        )

        actor = sim.actors[0]

        building_materials = sim.commodity_registry.get_commodity("simple_building_materials")
        actor.inventory.add_commodity(building_materials, 10)

        # Without tools, cannot build
        can_execute = actor.can_execute_process("build_smelting_facility")
        assert not can_execute, "Should not be able to build smelting facility without tools"

        # With tools, can build
        simple_tools = sim.commodity_registry.get_commodity("simple_tools")
        actor.inventory.add_commodity(simple_tools, 1)
        can_execute = actor.can_execute_process("build_smelting_facility")
        assert can_execute, "Should be able to build smelting facility with tools"

    def test_build_metalworking_facility_requires_tools(self):
        """Test that building a metalworking facility requires tools."""
        sim = Simulation()
        sim.setup_simple(
            num_planets=1,
            num_regular_actors=1,
            num_market_makers=0,
            num_ships=0,
        )

        actor = sim.actors[0]

        building_materials = sim.commodity_registry.get_commodity("simple_building_materials")
        actor.inventory.add_commodity(building_materials, 10)

        # Without tools, cannot build
        can_execute = actor.can_execute_process("build_metalworking_facility")
        assert not can_execute, "Should not be able to build metalworking facility without tools"

        # With tools, can build
        simple_tools = sim.commodity_registry.get_commodity("simple_tools")
        actor.inventory.add_commodity(simple_tools, 1)
        can_execute = actor.can_execute_process("build_metalworking_facility")
        assert can_execute, "Should be able to build metalworking facility with tools"

    def test_make_simple_tools_without_tools(self):
        """Test that making tools doesn't require tools (at metalworking facility)."""
        sim = Simulation()
        sim.setup_simple(
            num_planets=1,
            num_regular_actors=1,
            num_market_makers=0,
            num_ships=0,
        )

        actor = sim.actors[0]

        # Give actor required resources
        common_metal = sim.commodity_registry.get_commodity("common_metal")
        metalworking_facility = sim.commodity_registry.get_commodity("metalworking_facility")

        actor.inventory.add_commodity(common_metal, 10)
        actor.inventory.add_commodity(metalworking_facility, 1)

        # Making tools should work without existing tools
        can_execute = actor.can_execute_process("make_simple_tools")
        assert can_execute, "Should be able to make simple tools without existing tools"

    def test_refine_common_metal_without_tools(self):
        """Test that refining common metal doesn't require tools (at smelting facility)."""
        sim = Simulation()
        sim.setup_simple(
            num_planets=1,
            num_regular_actors=1,
            num_market_makers=0,
            num_ships=0,
        )

        actor = sim.actors[0]

        # Give actor required resources
        common_metal_ore = sim.commodity_registry.get_commodity("common_metal_ore")
        smelting_facility = sim.commodity_registry.get_commodity("smelting_facility")

        actor.inventory.add_commodity(common_metal_ore, 10)
        actor.inventory.add_commodity(smelting_facility, 1)

        # Refining should work without tools
        can_execute = actor.can_execute_process("refine_common_metal")
        assert can_execute, "Should be able to refine common metal without tools"

    def test_full_bootstrap_path(self):
        """Test the complete bootstrap path from nothing to metal tools.

        Path: harvest_wood -> make_simple_tools_wood -> (use tools for everything else)
        -> make_building_materials_wood -> build_smelting_facility
        -> mine_common_metal_ore -> refine_common_metal
        -> build_metalworking_facility -> make_simple_tools (metal)
        """
        sim = Simulation()
        sim.setup_simple(
            num_planets=1,
            num_regular_actors=1,
            num_market_makers=0,
            num_ships=0,
        )

        actor = sim.actors[0]

        # Disable skill checks and planet attribute effects for deterministic testing
        with patch('spacesim2.core.skill.SkillCheck.success_check', return_value=True), \
             patch('spacesim2.core.commands.random.random', return_value=0.5):

            if actor.planet and actor.planet.attributes:
                actor.planet.attributes.wood = 1.0
                actor.planet.attributes.common_metal_ore = 1.0

            # Step 1: Harvest wood (no tools needed) - need 4 for tools + more for building materials
            for _ in range(20):
                ProcessCommand("harvest_wood").execute(actor)

            wood = sim.commodity_registry.get_commodity("wood")
            assert actor.inventory.get_quantity(wood) >= 4, "Should have harvested wood"

            # Step 2: Make simple tools from wood (no tools needed)
            ProcessCommand("make_simple_tools_wood").execute(actor)
            simple_tools = sim.commodity_registry.get_commodity("simple_tools")
            assert actor.inventory.get_quantity(simple_tools) >= 1, "Should have wood tools"

            # Step 3: Make building materials (requires tools)
            for _ in range(10):
                ProcessCommand("make_building_materials_wood").execute(actor)

            building_materials = sim.commodity_registry.get_commodity("simple_building_materials")
            assert actor.inventory.get_quantity(building_materials) >= 5, \
                "Should have building materials"

            # Step 4: Build smelting facility (requires tools + building materials)
            ProcessCommand("build_smelting_facility").execute(actor)
            smelting_facility = sim.commodity_registry.get_commodity("smelting_facility")
            assert actor.inventory.get_quantity(smelting_facility) >= 1, \
                "Should have built smelting facility"

            # Step 5: Mine common metal ore (requires tools)
            for _ in range(20):
                ProcessCommand("mine_common_metal_ore").execute(actor)

            common_metal_ore = sim.commodity_registry.get_commodity("common_metal_ore")
            assert actor.inventory.get_quantity(common_metal_ore) >= 3, \
                "Should have mined ore"

            # Step 6: Refine metal (requires smelting facility, no tools)
            while actor.inventory.get_quantity(common_metal_ore) >= 3:
                ProcessCommand("refine_common_metal").execute(actor)

            common_metal = sim.commodity_registry.get_commodity("common_metal")
            assert actor.inventory.get_quantity(common_metal) >= 2, \
                "Should have refined metal"

            # Step 7: Make more building materials and build metalworking facility
            for _ in range(10):
                ProcessCommand("make_building_materials_wood").execute(actor)

            ProcessCommand("build_metalworking_facility").execute(actor)
            metalworking_facility = sim.commodity_registry.get_commodity("metalworking_facility")
            assert actor.inventory.get_quantity(metalworking_facility) >= 1, \
                "Should have built metalworking facility"

            # Step 8: Make metal tools (requires metalworking facility, no tools)
            ProcessCommand("make_simple_tools").execute(actor)
            assert actor.inventory.get_quantity(simple_tools) >= 1, \
                "Should have bootstrapped to metal tools!"


class TestToolRequirements:
    """Test that tool requirements are enforced for the right processes."""

    def test_mine_common_metal_ore_requires_tools(self):
        """Test that mining common metal ore requires tools."""
        sim = Simulation()
        sim.setup_simple(
            num_planets=1,
            num_regular_actors=1,
            num_market_makers=0,
            num_ships=0,
        )

        actor = sim.actors[0]

        # Without tools, should not be able to mine
        can_execute = actor.can_execute_process("mine_common_metal_ore")
        assert not can_execute, "Should not be able to mine common metal ore without tools"

        # With tools, should be able to
        simple_tools = sim.commodity_registry.get_commodity("simple_tools")
        actor.inventory.add_commodity(simple_tools, 1)
        can_execute = actor.can_execute_process("mine_common_metal_ore")
        assert can_execute, "Should be able to mine common metal ore with tools"

    def test_mine_nova_fuel_ore_requires_tools(self):
        """Test that mining nova fuel ore requires tools."""
        sim = Simulation()
        sim.setup_simple(
            num_planets=1,
            num_regular_actors=1,
            num_market_makers=0,
            num_ships=0,
        )

        actor = sim.actors[0]

        # Without tools, should not be able to mine nova fuel
        can_execute = actor.can_execute_process("mine_nova_fuel_ore")
        assert not can_execute, "Should not be able to mine nova fuel ore without tools"

        # With tools, should be able to
        simple_tools = sim.commodity_registry.get_commodity("simple_tools")
        actor.inventory.add_commodity(simple_tools, 1)
        can_execute = actor.can_execute_process("mine_nova_fuel_ore")
        assert can_execute, "Should be able to mine nova fuel ore with tools"

    def test_make_clothing_requires_tools(self):
        """Test that making clothing requires tools."""
        sim = Simulation()
        sim.setup_simple(
            num_planets=1,
            num_regular_actors=1,
            num_market_makers=0,
            num_ships=0,
        )

        actor = sim.actors[0]
        fiber = sim.commodity_registry.get_commodity("fiber")
        actor.inventory.add_commodity(fiber, 10)

        # Without tools, should not be able to make clothing
        can_execute = actor.can_execute_process("make_clothing")
        assert not can_execute, "Should not be able to make clothing without tools"

        # With tools, should be able to
        simple_tools = sim.commodity_registry.get_commodity("simple_tools")
        actor.inventory.add_commodity(simple_tools, 1)
        can_execute = actor.can_execute_process("make_clothing")
        assert can_execute, "Should be able to make clothing with tools"

    def test_refine_nova_fuel_requires_tools(self):
        """Test that refining nova fuel requires tools."""
        sim = Simulation()
        sim.setup_simple(
            num_planets=1,
            num_regular_actors=1,
            num_market_makers=0,
            num_ships=0,
        )

        actor = sim.actors[0]
        nova_fuel_ore = sim.commodity_registry.get_commodity("nova_fuel_ore")
        actor.inventory.add_commodity(nova_fuel_ore, 10)

        # Without tools, should not be able to refine
        can_execute = actor.can_execute_process("refine_nova_fuel")
        assert not can_execute, "Should not be able to refine nova fuel without tools"

        # With tools, should be able to
        simple_tools = sim.commodity_registry.get_commodity("simple_tools")
        actor.inventory.add_commodity(simple_tools, 1)
        can_execute = actor.can_execute_process("refine_nova_fuel")
        assert can_execute, "Should be able to refine nova fuel with tools"


class TestFacilityRequirements:
    """Test that facility requirements are enforced."""

    def test_refine_common_metal_requires_smelting_facility(self):
        """Test that refining common metal requires smelting facility."""
        sim = Simulation()
        sim.setup_simple(
            num_planets=1,
            num_regular_actors=1,
            num_market_makers=0,
            num_ships=0,
        )

        actor = sim.actors[0]
        common_metal_ore = sim.commodity_registry.get_commodity("common_metal_ore")
        actor.inventory.add_commodity(common_metal_ore, 10)

        # Without facility, should not be able to refine
        can_execute = actor.can_execute_process("refine_common_metal")
        assert not can_execute, "Should not be able to refine without smelting facility"

        # With facility, should be able to
        smelting_facility = sim.commodity_registry.get_commodity("smelting_facility")
        actor.inventory.add_commodity(smelting_facility, 1)
        can_execute = actor.can_execute_process("refine_common_metal")
        assert can_execute, "Should be able to refine with smelting facility"

    def test_make_simple_tools_requires_metalworking_facility(self):
        """Test that making tools requires metalworking facility."""
        sim = Simulation()
        sim.setup_simple(
            num_planets=1,
            num_regular_actors=1,
            num_market_makers=0,
            num_ships=0,
        )

        actor = sim.actors[0]
        common_metal = sim.commodity_registry.get_commodity("common_metal")
        actor.inventory.add_commodity(common_metal, 10)

        # Without facility, should not be able to make tools
        can_execute = actor.can_execute_process("make_simple_tools")
        assert not can_execute, "Should not be able to make tools without metalworking facility"

        # With facility, should be able to
        metalworking_facility = sim.commodity_registry.get_commodity("metalworking_facility")
        actor.inventory.add_commodity(metalworking_facility, 1)
        can_execute = actor.can_execute_process("make_simple_tools")
        assert can_execute, "Should be able to make tools with metalworking facility"
