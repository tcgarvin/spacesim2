"""Registry caches (all_commodities/all_processes, producer index) and the
per-actor-turn BrainCache invalidation rules."""

from pathlib import Path
from unittest.mock import Mock

import yaml

from spacesim2.core.actor import Actor, ActorType
from spacesim2.core.actor_brain import _get_bid_ask
from spacesim2.core.brains.colonist import ColonistBrain
from spacesim2.core.commodity import CommodityDefinition, CommodityRegistry
from spacesim2.core.process import ProcessRegistry

DATA_DIR = Path(__file__).parent.parent / "data"


def _load_real_registries() -> tuple[CommodityRegistry, ProcessRegistry]:
    commodity_registry = CommodityRegistry()
    commodity_registry.load_from_file(DATA_DIR / "commodities.yaml")
    process_registry = ProcessRegistry(commodity_registry)
    process_registry.load_from_file(DATA_DIR / "processes.yaml")
    return commodity_registry, process_registry


class TestProcessRegistryProducerIndex:
    def test_index_matches_brute_force_scan_for_every_commodity(self) -> None:
        """The producer index must agree with a full-registry scan."""
        commodity_registry, process_registry = _load_real_registries()
        all_processes = process_registry.all_processes()
        assert all_processes, "real process data should not be empty"

        for commodity in commodity_registry.all_commodities():
            brute_force = [p for p in all_processes if commodity in p.outputs]
            indexed = process_registry.get_processes_producing(commodity)
            assert {p.id for p in indexed} == {p.id for p in brute_force}

    def test_unknown_commodity_has_no_producers(self) -> None:
        _, process_registry = _load_real_registries()
        stranger = CommodityDefinition(
            id="never_registered", name="X", transportable=True, description=""
        )
        assert process_registry.get_processes_producing(stranger) == []


class TestRegistryListCaches:
    def test_all_commodities_reflects_late_registration(self) -> None:
        registry = CommodityRegistry()
        first = CommodityDefinition(
            id="a", name="A", transportable=True, description=""
        )
        registry.add_commodity(first)
        assert registry.all_commodities() == [first]

        late = CommodityDefinition(id="b", name="B", transportable=True, description="")
        registry.add_commodity(late)
        assert late in registry.all_commodities()
        assert len(registry.all_commodities()) == 2

    def test_all_processes_and_index_reflect_late_load(self, tmp_path: Path) -> None:
        commodity_registry, process_registry = _load_real_registries()
        before = list(process_registry.all_processes())
        wood = commodity_registry.get_commodity("wood")
        assert wood is not None
        producers_before = {
            p.id for p in process_registry.get_processes_producing(wood)
        }

        extra = tmp_path / "extra_processes.yaml"
        extra.write_text(
            yaml.dump(
                [
                    {
                        "id": "test_late_wood_process",
                        "name": "Late Wood Process",
                        "inputs": {},
                        "outputs": {"wood": 1},
                        "tools_required": [],
                        "facilities_required": [],
                        "labor": 1,
                        "description": "test",
                    }
                ]
            )
        )
        process_registry.load_from_file(extra)

        after_ids = {p.id for p in process_registry.all_processes()}
        assert after_ids == {p.id for p in before} | {"test_late_wood_process"}
        producers_after = {p.id for p in process_registry.get_processes_producing(wood)}
        assert producers_after == producers_before | {"test_late_wood_process"}


class TestBrainCacheInvalidation:
    """One BrainCache per brain, refreshed each decide_* entry.

    Market-derived entries live for a whole sim turn; actor-state entries are
    additionally dropped when inventory or skills change.
    """

    def _actor_and_brain(self) -> tuple[Actor, ColonistBrain, Mock]:
        sim = Mock()
        sim.current_turn = 0
        brain = ColonistBrain()
        actor = Actor(
            name="CacheTester",
            sim=sim,
            actor_type=ActorType.REGULAR,
            drives=[],
            brain=brain,
        )
        return actor, brain, sim

    def test_market_entries_survive_within_a_turn_but_not_across_turns(self) -> None:
        actor, brain, sim = self._actor_and_brain()
        food = CommodityDefinition(
            id="food", name="Food", transportable=True, description=""
        )
        market = Mock()
        market.get_bid_ask_spread.return_value = (3, 5)

        cache = brain._turn_cache(actor)
        assert _get_bid_ask(market, food, cache) == (3, 5)

        # Market mock changes, but within the same turn the quote is cached.
        market.get_bid_ask_spread.return_value = (4, 6)
        assert _get_bid_ask(market, food, brain._turn_cache(actor)) == (3, 5)

        # New turn: the quote must be re-fetched from the (changed) market.
        sim.current_turn = 1
        assert _get_bid_ask(market, food, brain._turn_cache(actor)) == (4, 6)

    def test_inventory_change_clears_actor_group_but_keeps_market_group(self) -> None:
        actor, brain, _sim = self._actor_and_brain()
        thing = CommodityDefinition(
            id="thing", name="Thing", transportable=True, description=""
        )

        cache = brain._turn_cache(actor)
        cache.bid_ask["food"] = (3, 5)
        cache.replacement_cost["food"] = 7.0
        cache.imputed_cost["food"] = 7.0
        cache.best_result = (None, 0.0)

        # No state change: everything survives.
        cache = brain._turn_cache(actor)
        assert cache.bid_ask == {"food": (3, 5)}
        assert cache.replacement_cost == {"food": 7.0}

        # Inventory mutation (as after a ProcessCommand executes): the
        # actor-state group is dropped, market quotes are kept.
        actor.inventory.add_commodity(thing, 1)
        cache = brain._turn_cache(actor)
        assert cache.bid_ask == {"food": (3, 5)}
        assert cache.replacement_cost == {}
        assert cache.imputed_cost == {}
        assert cache.best_result is None

    def test_skill_change_clears_actor_group(self) -> None:
        actor, brain, _sim = self._actor_and_brain()
        cache = brain._turn_cache(actor)
        cache.skill_factor["make_food"] = 1.5
        cache.bid_ask["food"] = (3, 5)

        actor.improve_skill("farming", 0.1)
        cache = brain._turn_cache(actor)
        assert cache.skill_factor == {}
        assert cache.bid_ask == {"food": (3, 5)}

    def test_turn_change_clears_everything(self) -> None:
        actor, brain, sim = self._actor_and_brain()
        cache = brain._turn_cache(actor)
        cache.bid_ask["food"] = (3, 5)
        cache.replacement_cost["food"] = 7.0

        sim.current_turn = 1
        cache = brain._turn_cache(actor)
        assert cache.bid_ask == {}
        assert cache.replacement_cost == {}

    def test_each_brain_owns_one_cache_instance(self) -> None:
        actor, brain, _sim = self._actor_and_brain()
        first = brain._turn_cache(actor)
        assert brain._turn_cache(actor) is first
        assert ColonistBrain()._turn_cache(actor) is not first
