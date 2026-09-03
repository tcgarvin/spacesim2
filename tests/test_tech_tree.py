"""Integration test: full tech tree from raw materials to T3 advanced goods.

A single actor on a planet with perfect resource availability produces every
commodity in the chain by running processes in order. Skill checks always
succeed and tools never degrade, so the test is deterministic.
"""

from unittest.mock import patch

from spacesim2.core.actor import Actor
from spacesim2.core.commands import ProcessCommand
from spacesim2.core.simulation import Simulation


def _run(process_id: str, actor: Actor, times: int = 1) -> None:
    """Execute a process `times` times, asserting each run succeeds."""
    for i in range(times):
        result = ProcessCommand(process_id).execute(actor)
        assert result, f"Process '{process_id}' failed on attempt {i + 1}"


def _qty(commodity_id: str, actor: Actor, sim: Simulation) -> int:
    """Inventory quantity of a commodity by id."""
    commodity = sim.commodity_registry.get_commodity(commodity_id)
    assert commodity is not None, f"Commodity '{commodity_id}' not found in registry"
    return actor.inventory.get_quantity(commodity)


def _has(commodity_id: str, actor: Actor, sim: Simulation) -> bool:
    return _qty(commodity_id, actor, sim) >= 1


class TestFullTechTree:
    """The complete tech tree can be traversed from scratch."""

    def _setup(self):
        """One actor on a planet with every resource attribute at 1.0."""
        sim = Simulation()
        sim.setup_simple(
            num_planets=1,
            num_regular_actors=1,
            num_market_makers=0,
            num_ships=0,
        )
        actor = sim.actors[0]

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
        """Walk the full production chain from raw gathering to T3 goods.

        Tiers:
          T0: raw gathering, no tools required
          T1: first industry: tools, facilities, basic goods
          T2: specialization: 4 new facilities, intermediates, consumer goods
          T3: advanced factory, computers, luxury goods
        """
        sim, actor = self._setup()

        # Skill checks always succeed with no multiplier, and tools never break.
        # multiplier_check must be patched too: an unpredicted 2x input
        # multiplier would exhaust resources mid-phase. random.random = 0.5
        # stays above the 0.01 tool-break threshold and resource-success rolls.
        with (
            patch("spacesim2.core.skill.SkillCheck.success_check", return_value=True),
            patch(
                "spacesim2.core.skill.SkillCheck.multiplier_check", return_value=False
            ),
            patch("spacesim2.core.commands.random.random", return_value=0.5),
        ):
            self._phase_t0_raw_gathering(sim, actor)
            self._phase_t1_basic_industry(sim, actor)
            self._phase_t2_facilities(sim, actor)
            self._phase_t2_production(sim, actor)
            self._phase_t2_consumer_goods(sim, actor)
            self._phase_t3_advanced(sim, actor)

    # -----------------------------------------------------------------------
    # T0: Raw gathering, no tools required
    # -----------------------------------------------------------------------

    def _phase_t0_raw_gathering(self, sim, actor):
        """Gather the T0 raw materials that need no tools."""
        _run("gather_biomass", actor, 30)
        assert _has("biomass", actor, sim)

        _run("harvest_wood", actor, 30)
        assert _has("wood", actor, sim)

        _run("gather_fiber", actor, 20)
        assert _has("fiber", actor, sim)

        # silica and rare_earth_ore need tools, so they are mined in T1.

    # -----------------------------------------------------------------------
    # T1: Basic industry
    # -----------------------------------------------------------------------

    def _phase_t1_basic_industry(self, sim, actor):
        """Produce the T1 goods: tools, facilities, chemicals, glass, fuel."""
        # Wood tools need no tools or facilities.
        _run("make_simple_tools_wood", actor, 3)
        assert _has("simple_tools", actor, sim), "Should have crafted wood tools"

        # With tools, mine the remaining raw ores.
        _run("mine_common_metal_ore", actor, 30)
        assert _has("common_metal_ore", actor, sim)

        _run("mine_nova_fuel_ore", actor, 20)
        assert _has("nova_fuel_ore", actor, sim)

        _run("mine_silica", actor, 20)
        assert _has("silica", actor, sim)

        _run("mine_rare_earth", actor, 20)
        assert _has("rare_earth_ore", actor, sim)

        _run("make_building_materials_wood", actor, 20)
        assert _has("simple_building_materials", actor, sim)

        _run("build_smelting_facility", actor, 1)
        assert _has("smelting_facility", actor, sim), (
            "Should have built smelting facility"
        )

        # Enough metal for facilities, tools, and later T2 work.
        _run("mine_common_metal_ore", actor, 60)
        _run("refine_common_metal", actor, 15)
        assert _has("common_metal", actor, sim)

        _run("make_building_materials_metal", actor, 5)

        _run("build_metalworking_facility", actor, 1)
        assert _has("metalworking_facility", actor, sim), (
            "Should have built metalworking facility"
        )

        # Metal tools need the metalworking facility.
        _run("make_simple_tools", actor, 3)
        assert _has("simple_tools", actor, sim)

        _run("refine_nova_fuel", actor, 5)
        assert _has("nova_fuel", actor, sim)

        _run("make_food", actor, 5)
        assert _has("food", actor, sim)

        _run("make_clothing", actor, 3)
        assert _has("clothing", actor, sim)

        _run("make_chemicals", actor, 10)
        assert _has("chemicals", actor, sim)

        _run("make_glass", actor, 5)
        assert _has("glass", actor, sim)

        _run("make_ship_supplies", actor, 3)
        assert _has("ship_supplies", actor, sim)

    # -----------------------------------------------------------------------
    # T2: Facility construction
    # -----------------------------------------------------------------------

    def _phase_t2_facilities(self, sim, actor):
        """Build all four T2 facilities.

        Total inputs across the 4 builds:
          building_materials: 20, 5 each
          common_metal: 7, as 2 + 3 + 2
          glass: 4, as 2 + 2, needing 12 silica
          chemicals: 2, for chemistry_lab
        """
        _run("mine_common_metal_ore", actor, 60)
        _run("refine_common_metal", actor, 15)
        _run("make_building_materials_metal", actor, 25)

        # make_glass uses 3 silica each.
        _run("mine_silica", actor, 60)
        _run("make_glass", actor, 10)

        _run("gather_biomass", actor, 20)
        _run("make_chemicals", actor, 10)

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
        """Produce the T2 intermediate goods."""
        _run("gather_fiber", actor, 20)
        _run("gather_biomass", actor, 10)
        _run("mine_common_metal_ore", actor, 20)
        _run("refine_common_metal", actor, 5)
        _run("mine_silica", actor, 10)
        _run("make_glass", actor, 5)
        _run("mine_rare_earth", actor, 20)
        _run("mine_nova_fuel_ore", actor, 10)
        _run("make_chemicals", actor, 10)

        _run("make_textiles", actor, 3)
        assert _has("textiles", actor, sim)

        _run("refine_chemicals", actor, 3)
        assert _has("refined_chemicals", actor, sim)

        # precision_parts take 3 metal per run. Electronics need 2x3, precision
        # tools 2x2, and ship parts 2x2, so 14 parts, which is 7 runs.
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
        """Produce the T2 consumer goods."""
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
        """Build the advanced factory and produce the T3 goods."""
        # T2 inputs across the T3 builds:
        #   build_advanced_factory: building_materials 5, precision_parts 3,
        #     electronics 2
        #   make_computers: electronics 2, precision_parts 1, polymers 1
        #   make_luxury_goods: rare_earth 1, textiles 1, glass 1
        #   make_advanced_medicine x2: medicine 1, electronics 1,
        #     refined_chemicals 2
        #   make_ship_components x2: precision_parts 2, electronics 1, polymers 1
        #   make_advanced_building_materials x2: metal 2, polymers 1, glass 1
        # Totals: electronics 7, precision_parts 8, polymers 4, rare_earth 8
        # including 7 for electronics. Everything is made with a margin so no
        # input runs out mid-phase.
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

        _run("build_advanced_factory", actor, 1)
        assert _has("advanced_factory", actor, sim), (
            "Should have built advanced factory"
        )

        _run("make_advanced_building_materials", actor, 2)
        assert _has("advanced_building_materials", actor, sim)

        _run("make_computers", actor, 2)
        assert _has("computers", actor, sim)

        _run("make_textiles", actor, 3)  # textiles for luxury goods
        _run("make_luxury_goods", actor, 2)
        assert _has("luxury_goods", actor, sim)

        _run("make_medicine", actor, 3)  # medicine for advanced medicine
        _run("refine_chemicals", actor, 3)
        _run("make_electronics", actor, 3)
        _run("make_advanced_medicine", actor, 2)
        assert _has("advanced_medicine", actor, sim)

        _run("make_ship_components", actor, 2)
        assert _has("ship_components", actor, sim)
