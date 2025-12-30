"""Tests for planet attributes functionality."""

import pytest

from spacesim2.core.planet_attributes import PlanetAttributes, _bimodal_sample
from spacesim2.core.process import ResourceAttribute


class TestPlanetAttributes:
    """Tests for the PlanetAttributes dataclass."""

    def test_default_attributes_are_all_one(self):
        """Default attributes should all be 1.0 (no penalty)."""
        attrs = PlanetAttributes()
        assert attrs.biomass == 1.0
        assert attrs.fiber == 1.0
        assert attrs.wood == 1.0
        assert attrs.common_metal_ore == 1.0
        assert attrs.nova_fuel_ore == 1.0
        assert attrs.simple_building_materials == 1.0

    def test_custom_attributes(self):
        """Can create attributes with custom values."""
        attrs = PlanetAttributes(
            biomass=0.5,
            fiber=0.3,
            wood=0.8,
            common_metal_ore=0.0,
            nova_fuel_ore=1.0,
            simple_building_materials=0.6,
        )
        assert attrs.biomass == 0.5
        assert attrs.fiber == 0.3
        assert attrs.wood == 0.8
        assert attrs.common_metal_ore == 0.0
        assert attrs.nova_fuel_ore == 1.0
        assert attrs.simple_building_materials == 0.6

    def test_validation_rejects_values_above_one(self):
        """Attributes above 1.0 should raise ValueError."""
        with pytest.raises(ValueError, match="biomass must be between"):
            PlanetAttributes(biomass=1.5)

    def test_validation_rejects_negative_values(self):
        """Negative attributes should raise ValueError."""
        with pytest.raises(ValueError, match="wood must be between"):
            PlanetAttributes(wood=-0.1)

    def test_generate_random_produces_valid_attributes(self):
        """Random generation should produce valid attributes."""
        for _ in range(100):
            attrs = PlanetAttributes.generate_random()
            assert 0.0 <= attrs.biomass <= 1.0
            assert 0.0 <= attrs.fiber <= 1.0
            assert 0.0 <= attrs.wood <= 1.0
            assert 0.0 <= attrs.common_metal_ore <= 1.0
            assert 0.0 <= attrs.nova_fuel_ore <= 1.0
            assert 0.0 <= attrs.simple_building_materials <= 1.0

    def test_generate_random_respects_minimum_values(self):
        """Some resources should always be above zero."""
        for _ in range(100):
            attrs = PlanetAttributes.generate_random()
            # biomass always >= 0.2
            assert attrs.biomass >= 0.2
            # simple_building_materials always >= 0.3
            assert attrs.simple_building_materials >= 0.3

    def test_get_availability_for_tracked_commodity(self):
        """get_availability returns the correct attribute value."""
        attrs = PlanetAttributes(biomass=0.5, nova_fuel_ore=0.8)
        assert attrs.get_availability("biomass") == 0.5
        assert attrs.get_availability("nova_fuel_ore") == 0.8

    def test_get_availability_for_untracked_commodity_returns_one(self):
        """Untracked commodities return 1.0 (no penalty)."""
        attrs = PlanetAttributes()
        # 'food' is a processed commodity, not a planetary resource
        assert attrs.get_availability("food") == 1.0
        assert attrs.get_availability("nonexistent") == 1.0

    def test_default_returns_all_ones(self):
        """PlanetAttributes.default() returns all 1.0 values."""
        attrs = PlanetAttributes.default()
        assert attrs.biomass == 1.0
        assert attrs.fiber == 1.0
        assert attrs.wood == 1.0
        assert attrs.common_metal_ore == 1.0
        assert attrs.nova_fuel_ore == 1.0
        assert attrs.simple_building_materials == 1.0

    def test_to_dict(self):
        """to_dict() returns correct dictionary representation."""
        attrs = PlanetAttributes(biomass=0.5, wood=0.7)
        d = attrs.to_dict()
        assert d["biomass"] == 0.5
        assert d["wood"] == 0.7
        assert d["fiber"] == 1.0  # default value
        assert len(d) == 6  # all 6 resource attributes


class TestBimodalSample:
    """Tests for the _bimodal_sample helper function."""

    def test_bimodal_sample_in_range(self):
        """Bimodal samples should be in one of the two ranges."""
        for _ in range(100):
            value = _bimodal_sample(0.0, 0.3, 0.7, 1.0)
            assert (0.0 <= value <= 0.3) or (0.7 <= value <= 1.0)


class TestResourceAttribute:
    """Tests for the ResourceAttribute dataclass."""

    def test_valid_success_effect(self):
        """Can create ResourceAttribute with 'success' effect."""
        ra = ResourceAttribute(commodity="nova_fuel_ore", effect="success")
        assert ra.commodity == "nova_fuel_ore"
        assert ra.effect == "success"

    def test_valid_output_effect(self):
        """Can create ResourceAttribute with 'output' effect."""
        ra = ResourceAttribute(commodity="biomass", effect="output")
        assert ra.commodity == "biomass"
        assert ra.effect == "output"

    def test_invalid_effect_raises_error(self):
        """Invalid effect type should raise ValueError."""
        with pytest.raises(ValueError, match="effect must be one of"):
            ResourceAttribute(commodity="biomass", effect="invalid")


class TestSimulationIntegration:
    """Integration tests for planet attributes in simulation."""

    def test_simulation_without_planet_attributes(self):
        """Simulation works without planet attributes enabled."""
        from spacesim2.core.simulation import Simulation

        sim = Simulation()
        sim.setup_simple(
            num_planets=2,
            num_regular_actors=4,
            num_market_makers=1,
            enable_planet_attributes=False,
        )

        assert sim.planet_attributes_enabled is False
        for planet in sim.planets:
            assert planet.attributes is None

    def test_simulation_with_planet_attributes(self):
        """Simulation generates planet attributes when enabled."""
        from spacesim2.core.simulation import Simulation

        sim = Simulation()
        sim.setup_simple(
            num_planets=3,
            num_regular_actors=4,
            num_market_makers=1,
            enable_planet_attributes=True,
        )

        assert sim.planet_attributes_enabled is True
        for planet in sim.planets:
            assert planet.attributes is not None
            assert isinstance(planet.attributes, PlanetAttributes)

    def test_different_planets_have_different_attributes(self):
        """Each planet should have randomly generated unique attributes."""
        from spacesim2.core.simulation import Simulation

        sim = Simulation()
        sim.setup_simple(
            num_planets=5,
            num_regular_actors=4,
            num_market_makers=1,
            enable_planet_attributes=True,
        )

        # With 5 planets, it's extremely unlikely they'd all be identical
        attributes_sets = [
            (p.attributes.biomass, p.attributes.nova_fuel_ore)
            for p in sim.planets
        ]
        # At least 2 different combinations should exist
        assert len(set(attributes_sets)) > 1


class TestProcessCommandIntegration:
    """Integration tests for ProcessCommand with planet attributes."""

    def test_process_with_output_effect_reduces_yield(self):
        """Processes with 'output' effect should have reduced yield on low-availability planets."""
        from spacesim2.core.simulation import Simulation
        from spacesim2.core.commands import ProcessCommand

        sim = Simulation()
        sim.setup_simple(
            num_planets=1,
            num_regular_actors=2,
            num_market_makers=1,
            enable_planet_attributes=True,
        )

        planet = sim.planets[0]
        # Set a known low biomass availability
        planet.attributes = PlanetAttributes(biomass=0.25)

        actor = sim.actors[0]
        actor.planet = planet

        # Give the actor high agriculture skill to ensure success
        actor.improve_skill("agriculture", 10.0)

        # Get initial biomass count
        biomass = sim.commodity_registry["biomass"]
        initial_biomass = actor.inventory.get_quantity(biomass)

        # Execute gather_biomass (base output is 4)
        cmd = ProcessCommand("gather_biomass")
        result = cmd.execute(actor)

        # The process should succeed
        assert result is True, f"Process failed with action: {actor.last_action}"

        # The output should be reduced (4 * 0.25 = 1, with max(1, round(...)))
        new_biomass = actor.inventory.get_quantity(biomass)
        gained = new_biomass - initial_biomass
        # With 0.25 availability, we should get 1 (or 2 if skill multiplier triggered)
        # Base output 4 * 0.25 = 1, or 4 * 2 * 0.25 = 2 with skill multiplier
        assert gained in (1, 2), f"Expected 1 or 2 biomass, got {gained}"

    def test_process_with_success_effect_can_fail(self):
        """Processes with 'success' effect should fail on zero-availability planets."""
        import random
        from spacesim2.core.simulation import Simulation
        from spacesim2.core.commands import ProcessCommand

        # Fix random seed for deterministic test
        random.seed(42)

        sim = Simulation()
        sim.setup_simple(
            num_planets=1,
            num_regular_actors=2,
            num_market_makers=1,
            enable_planet_attributes=True,
        )

        planet = sim.planets[0]
        # Set nova_fuel_ore availability to 0 (mining should always fail)
        planet.attributes = PlanetAttributes(nova_fuel_ore=0.0)

        actor = sim.actors[0]
        actor.planet = planet

        # Execute mine_nova_fuel_ore (should fail due to 0 availability)
        cmd = ProcessCommand("mine_nova_fuel_ore")
        result = cmd.execute(actor)

        # The process should fail
        assert result is False
        assert "insufficient planetary resources" in actor.last_action

    def test_process_without_resource_attribute_unaffected(self):
        """Processes without resource_attribute should work normally."""
        from spacesim2.core.simulation import Simulation
        from spacesim2.core.commands import ProcessCommand

        sim = Simulation()
        sim.setup_simple(
            num_planets=1,
            num_regular_actors=2,
            num_market_makers=1,
            enable_planet_attributes=True,
        )

        planet = sim.planets[0]
        # Even with low attributes, make_food shouldn't be affected
        planet.attributes = PlanetAttributes(biomass=0.1)

        actor = sim.actors[0]
        actor.planet = planet

        # Give actor some biomass to make food
        biomass = sim.commodity_registry["biomass"]
        actor.inventory.add_commodity(biomass, 10)

        food = sim.commodity_registry["food"]
        initial_food = actor.inventory.get_quantity(food)

        # Execute make_food (converts biomass to food, no resource_attribute)
        cmd = ProcessCommand("make_food")
        result = cmd.execute(actor)

        assert result is True
        # make_food outputs 2 food normally
        gained = actor.inventory.get_quantity(food) - initial_food
        # Should get full output (may be doubled by skill multiplier)
        assert gained >= 2
