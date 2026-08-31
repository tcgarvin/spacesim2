"""Integration test: full tech tree from raw materials to T3 advanced goods.

Given a single actor on a planet with perfect resource availability, verifies
that every commodity in the production chain can be created by following the
correct sequence of processes.

This test is deterministic: skill checks always succeed and tools never degrade.
"""

from unittest.mock import patch

from spacesim2.core.actor import Actor
from spacesim2.core.commands import ProcessCommand
from spacesim2.core.simulation import Simulation
from tests.helpers import FixedRandom


def _run(process_id: str, actor: Actor, times: int = 1) -> None:
    """Execute a process the given number of times; assert each execution succeeds."""
    for i in range(times):
        result = ProcessCommand(process_id).execute(actor)
        assert result, f"Process '{process_id}' failed on attempt {i + 1}"


def _qty(commodity_id: str, actor: Actor, sim: Simulation) -> int:
    """Return inventory quantity for a commodity by ID."""
    commodity = sim.commodity_registry.get_commodity(commodity_id)
    assert commodity is not None, f"Commodity '{commodity_id}' not found in registry"
    return actor.inventory.get_quantity(commodity)


def _has(commodity_id: str, actor: Actor, sim: Simulation) -> bool:
    return _qty(commodity_id, actor, sim) >= 1


class TestFullTechTree:
    """Verify the complete tech tree can be traversed from scratch."""

    def _setup(self):
        """Create a sim with one actor on a planet with perfect resource availability."""
        sim = Simulation()
        sim.setup_simple(
            num_planets=1,
            num_regular_actors=1,
            num_market_makers=0,
            num_ships=0,
        )
        actor = sim.actors[0]

        # Set all planet resource attributes to 1.0 (perfect planet)
        attrs = actor.planet.attributes
        for field in (
            "biomass",
            "fiber",
            "wood",
            "common_metal_ore",
            "nova_fuel_ore",
            "simple_building_materials",
            "silica",
            "rare_earth_ore",
        ):
            setattr(attrs, field, 1.0)

        return sim, actor

    def test_full_tech_tree_path(self):
        """Walk the full production chain from raw gathering to T3 advanced goods.

        Tiers:
          T0: raw gathering (no tools required)
          T1: first industry — tools, facilities, basic goods
          T2: specialization — 4 new facilities, intermediates, consumer goods
          T3: advanced — advanced factory, computers, luxury goods, etc.
        """
        sim, actor = self._setup()

        # Patch skill checks to always succeed with no multiplier, and disable tool degradation.
        # multiplier_check must also be patched: an unpredicted 2× input multiplier would
        # exhaust resources mid-phase and make the test non-deterministic.
        # actor.rng pinned at 0.5 keeps tool-break threshold (0.01) and resource-success checks safe.
        actor.rng = FixedRandom(0.5)
        with (
            patch("spacesim2.core.skill.SkillCheck.success_check", return_value=True),
            patch(
                "spacesim2.core.skill.SkillCheck.multiplier_check", return_value=False
            ),
        ):
            self._phase_t0_raw_gathering(sim, actor)
            self._phase_t1_basic_industry(sim, actor)
            self._phase_t2_facilities(sim, actor)
            self._phase_t2_production(sim, actor)
            self._phase_t2_consumer_goods(sim, actor)
            self._phase_t3_advanced(sim, actor)

    # -----------------------------------------------------------------------
    # T0: Raw gathering — no tools required
    # -----------------------------------------------------------------------

    def _phase_t0_raw_gathering(self, sim, actor):
        """Gather all T0 raw materials that require no tools."""
        _run("gather_biomass", actor, 30)
        assert _has("biomass", actor, sim)

        _run("harvest_wood", actor, 30)
        assert _has("wood", actor, sim)

        _run("gather_fiber", actor, 20)
        assert _has("fiber", actor, sim)

        # silica and rare_earth_ore require tools — gathered later after T1

    # -----------------------------------------------------------------------
    # T1: Basic industry
    # -----------------------------------------------------------------------

    def _phase_t1_basic_industry(self, sim, actor):
        """Produce all T1 goods: tools, facilities, chemicals, glass, fuel."""
        # Wood tools (no tools or facilities required)
        _run("make_simple_tools_wood", actor, 3)
        assert _has("simple_tools", actor, sim), "Should have crafted wood tools"

        # Now we have tools — gather the remaining raw ores
        _run("mine_common_metal_ore", actor, 30)
        assert _has("common_metal_ore", actor, sim)

        _run("mine_nova_fuel_ore", actor, 20)
        assert _has("nova_fuel_ore", actor, sim)

        _run("mine_silica", actor, 20)
        assert _has("silica", actor, sim)

        _run("mine_rare_earth", actor, 20)
        assert _has("rare_earth_ore", actor, sim)

        # Building materials (wood path, needs tools)
        _run("make_building_materials_wood", actor, 20)
        assert _has("simple_building_materials", actor, sim)

        # Smelting facility
        _run("build_smelting_facility", actor, 1)
        assert _has("smelting_facility", actor, sim), (
            "Should have built smelting facility"
        )

        # Refine enough metal for facilities + tools + later T2 work
        _run("mine_common_metal_ore", actor, 60)
        _run("refine_common_metal", actor, 15)
        assert _has("common_metal", actor, sim)

        # More building materials (metal path — more efficient)
        _run("make_building_materials_metal", actor, 5)

        # Metalworking facility
        _run("build_metalworking_facility", actor, 1)
        assert _has("metalworking_facility", actor, sim), (
            "Should have built metalworking facility"
        )

        # Metal tools (better quality, needs metalworking facility)
        _run("make_simple_tools", actor, 3)
        assert _has("simple_tools", actor, sim)

        # Refine nova fuel (needs tools)
        _run("refine_nova_fuel", actor, 5)
        assert _has("nova_fuel", actor, sim)

        # Basic food
        _run("make_food", actor, 5)
        assert _has("food", actor, sim)

        # Basic clothing (needs tools)
        _run("make_clothing", actor, 3)
        assert _has("clothing", actor, sim)

        # Chemicals (biomass, no tools/facility)
        _run("make_chemicals", actor, 10)
        assert _has("chemicals", actor, sim)

        # Glass (silica + smelting facility)
        _run("make_glass", actor, 5)
        assert _has("glass", actor, sim)

        # Ship supplies (metal + wood + tools)
        _run("make_ship_supplies", actor, 3)
        assert _has("ship_supplies", actor, sim)

    # -----------------------------------------------------------------------
    # T2: Facility construction
    # -----------------------------------------------------------------------

    def _phase_t2_facilities(self, sim, actor):
        """Build all four T2 facilities.

        Total inputs across 4 builds:
          building_materials: 20  (5 each)
          common_metal: 7         (2 + 3 + 2)
          glass: 4                (2 + 2; needs silica: 12)
          chemicals: 2            (for chemistry_lab)
        """
        # Stock up on building materials (20+)
        _run("mine_common_metal_ore", actor, 60)
        _run("refine_common_metal", actor, 15)
        _run("make_building_materials_metal", actor, 25)

        # Stock up on glass (4+ needed; make_glass uses 3 silica each)
        _run("mine_silica", actor, 60)
        _run("make_glass", actor, 10)

        # Stock up on chemicals for chemistry_lab (needs 2)
        _run("gather_biomass", actor, 20)
        _run("make_chemicals", actor, 10)

        # Build all 4 T2 facilities
        _run("build_textile_mill", actor, 1)
        assert _has("textile_mill", actor, sim), "Should have built textile mill"

        _run("build_chemistry_lab", actor, 1)
        assert _has("chemistry_lab", actor, sim), "Should have built chemistry lab"

        _run("build_precision_forge", actor, 1)
        assert _has("precision_forge", actor, sim), "Should have built precision forge"

        _run("build_electronics_workshop", actor, 1)
        assert _has("electronics_workshop", actor, sim), (
            "Should have built electronics workshop"
        )

    # -----------------------------------------------------------------------
    # T2: Intermediate production
    # -----------------------------------------------------------------------

    def _phase_t2_production(self, sim, actor):
        """Produce all T2 intermediate goods."""
        # Ensure raw materials
        _run("gather_fiber", actor, 20)
        _run("gather_biomass", actor, 10)
        _run("mine_common_metal_ore", actor, 20)
        _run("refine_common_metal", actor, 5)
        _run("mine_silica", actor, 10)
        _run("make_glass", actor, 5)
        _run("mine_rare_earth", actor, 20)
        _run("mine_nova_fuel_ore", actor, 10)
        _run("make_chemicals", actor, 10)

        # T2 intermediates
        _run("make_textiles", actor, 3)
        assert _has("textiles", actor, sim)

        _run("refine_chemicals", actor, 3)
        assert _has("refined_chemicals", actor, sim)

        # precision_parts: 3 metal each run; need enough for electronics (2×3),
        # precision_tools (2×2), and ship_parts (2×2) = 6 + 4 + 4 = 14 parts → 7 runs
        _run("mine_common_metal_ore", actor, 40)
        _run("refine_common_metal", actor, 10)
        _run("make_precision_parts", actor, 10)
        assert _has("precision_parts", actor, sim)

        _run("refine_rare_earth", actor, 3)
        assert _has("rare_earth", actor, sim)

        _run("make_polymers", actor, 5)
        assert _has("polymers", actor, sim)

        _run("make_electronics", actor, 3)
        assert _has("electronics", actor, sim)

        _run("make_precision_tools", actor, 2)
        assert _has("precision_tools", actor, sim)

        _run("make_ship_parts", actor, 2)
        assert _has("ship_parts", actor, sim)

    # -----------------------------------------------------------------------
    # T2: Consumer goods
    # -----------------------------------------------------------------------

    def _phase_t2_consumer_goods(self, sim, actor):
        """Produce all T2 consumer goods."""
        # Ensure inputs
        _run("make_food", actor, 5)
        _run("gather_biomass", actor, 5)
        _run("refine_chemicals", actor, 3)
        _run("make_textiles", actor, 3)
        _run("make_polymers", actor, 3)
        _run("mine_silica", actor, 10)
        _run("make_glass", actor, 3)
        _run("make_building_materials_metal", actor, 3)

        _run("make_processed_food", actor, 2)
        assert _has("processed_food", actor, sim)

        _run("make_quality_clothing", actor, 2)
        assert _has("quality_clothing", actor, sim)

        _run("make_medicine", actor, 2)
        assert _has("medicine", actor, sim)

        _run("make_prefab_housing", actor, 2)
        assert _has("prefab_housing", actor, sim)

    # -----------------------------------------------------------------------
    # T3: Advanced goods
    # -----------------------------------------------------------------------

    def _phase_t3_advanced(self, sim, actor):
        """Build the advanced factory and produce all T3 goods."""
        # Stock up all T2 inputs needed across all T3 builds:
        #   build_advanced_factory: building_materials:5, precision_parts:3, electronics:2
        #   make_computers: electronics:2, precision_parts:1, polymers:1
        #   make_luxury_goods: rare_earth:1, textiles:1, glass:1
        #   make_advanced_medicine (x2): medicine:1, electronics:1, refined_chemicals:2
        #   make_ship_components (x2): precision_parts:2, electronics:1, polymers:1
        #   make_advanced_building_materials (x2): metal:2, polymers:1, glass:1
        # Total electronics needed: 2+2+1+1+1 = 7 → make 10 to be safe
        # Total precision_parts: 3+1+2+2 = 8 → make 15
        # Total polymers: 1+1+2 = 4 → make 8
        # Total rare_earth: 1 for luxury + 7 for electronics = 8 → refine 10
        # Mine in bulk to cover all T3 needs without running out mid-phase
        _run("mine_common_metal_ore", actor, 200)
        _run("refine_common_metal", actor, 50)  # 100 metal
        _run("make_building_materials_metal", actor, 15)
        _run("mine_silica", actor, 100)
        _run("make_glass", actor, 20)
        _run("mine_rare_earth", actor, 100)
        _run("refine_rare_earth", actor, 20)
        _run("mine_nova_fuel_ore", actor, 60)
        _run("gather_biomass", actor, 30)
        _run("make_chemicals", actor, 20)
        _run("refine_chemicals", actor, 10)
        _run("make_polymers", actor, 10)
        _run("make_precision_parts", actor, 15)
        _run("make_electronics", actor, 10)

        # Build advanced factory (T3 facility)
        _run("build_advanced_factory", actor, 1)
        assert _has("advanced_factory", actor, sim), (
            "Should have built advanced factory"
        )

        # T3 goods
        _run("make_advanced_building_materials", actor, 2)
        assert _has("advanced_building_materials", actor, sim)

        _run("make_computers", actor, 2)
        assert _has("computers", actor, sim)

        _run("make_textiles", actor, 3)  # ensure textiles for luxury
        _run("make_luxury_goods", actor, 2)
        assert _has("luxury_goods", actor, sim)

        _run("make_medicine", actor, 3)  # ensure medicine for advanced medicine
        _run("refine_chemicals", actor, 3)
        _run("make_electronics", actor, 3)
        _run("make_advanced_medicine", actor, 2)
        assert _has("advanced_medicine", actor, sim)

        _run("make_ship_components", actor, 2)
        assert _has("ship_components", actor, sim)
