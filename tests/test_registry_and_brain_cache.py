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

    def test_skill_change_clears_skill_and_valuation_groups(self) -> None:
        actor, brain, _sim = self._actor_and_brain()
        cache = brain._turn_cache(actor)
        cache.skill_factor["make_food"] = 1.5
        cache.ranked_profits = []
        cache.bid_ask["food"] = (3, 5)

        actor.improve_skill("farming", 0.1)
        cache = brain._turn_cache(actor)
        assert cache.skill_factor == {}
        assert cache.ranked_profits is None
        assert cache.bid_ask == {"food": (3, 5)}

    def test_turn_change_clears_market_and_actor_groups(self) -> None:
        actor, brain, sim = self._actor_and_brain()
        cache = brain._turn_cache(actor)
        cache.bid_ask["food"] = (3, 5)
        cache.replacement_cost["food"] = 7.0
        cache.ranked_profits = []

        sim.current_turn = 1
        cache = brain._turn_cache(actor)
        assert cache.bid_ask == {}
        assert cache.replacement_cost == {}
        assert cache.ranked_profits is None

    def test_skill_factor_survives_turn_and_inventory_changes(self) -> None:
        """Skill factors depend only on skills, so they must outlive both a
        turn boundary and a mid-turn inventory bump."""
        actor, brain, sim = self._actor_and_brain()
        thing = CommodityDefinition(
            id="thing", name="Thing", transportable=True, description=""
        )

        cache = brain._turn_cache(actor)
        cache.skill_factor["make_food"] = 1.5

        actor.inventory.add_commodity(thing, 1)
        cache = brain._turn_cache(actor)
        assert cache.skill_factor == {"make_food": 1.5}

        sim.current_turn = 1
        cache = brain._turn_cache(actor)
        assert cache.skill_factor == {"make_food": 1.5}

    def test_ranked_profits_survives_inventory_change(self) -> None:
        """The valuation ranking is quote/skill-derived, so the mid-turn
        inventory bump from the economic command must not drop it (that is
        the whole point: no second registry scan in decide_market_actions).
        best_result, which reads inventory via can_execute, must drop."""
        actor, brain, _sim = self._actor_and_brain()
        thing = CommodityDefinition(
            id="thing", name="Thing", transportable=True, description=""
        )

        cache = brain._turn_cache(actor)
        cache.ranked_profits = []
        cache.best_result = (None, 0.0)

        actor.inventory.add_commodity(thing, 1)
        cache = brain._turn_cache(actor)
        assert cache.ranked_profits == []
        assert cache.best_result is None

    def test_yield_modifier_is_never_reset(self) -> None:
        actor, brain, sim = self._actor_and_brain()
        cache = brain._turn_cache(actor)
        cache.yield_modifier["gather_biomass"] = 0.7

        actor.improve_skill("farming", 0.1)
        sim.current_turn = 5
        cache = brain._turn_cache(actor)
        assert cache.yield_modifier == {"gather_biomass": 0.7}

    def test_each_brain_owns_one_cache_instance(self) -> None:
        actor, brain, _sim = self._actor_and_brain()
        first = brain._turn_cache(actor)
        assert brain._turn_cache(actor) is first
        assert ColonistBrain()._turn_cache(actor) is not first


class TestBestProcessRankedWalkEquivalence:
    """The ranked-vector walk in _best_process_and_raw_profit must pick
    exactly what the original first-strictly-better registry scan picked,
    including tie-breaking by registry order and the >10.0 profit bar."""

    @staticmethod
    def _brute_force_reference(
        brain: ColonistBrain, actor: Actor, market: object
    ) -> tuple:
        best_process = None
        best_discounted_profit = 10.0
        best_raw_profit = 0.0
        for process in actor.sim.process_registry.all_processes():
            input_cost = 0.0
            for commodity, quantity in process.inputs.items():
                _bid, ask = market.get_bid_ask_spread(commodity)  # type: ignore[attr-defined]
                price = ask if ask is not None else market.get_avg_price(commodity)  # type: ignore[attr-defined]
                input_cost += price * quantity
            output_value = 0.0
            for commodity, quantity in process.outputs.items():
                bid, _ask = market.get_bid_ask_spread(commodity)  # type: ignore[attr-defined]
                price = bid if bid is not None else market.get_avg_price(commodity)  # type: ignore[attr-defined]
                output_value += price * quantity
            expected_value = (
                output_value
                * brain._expected_yield_modifier(actor, process)
                * brain._expected_skill_factor(actor, process)
            )
            discounted_profit = expected_value - input_cost
            if (
                actor.can_execute_process(process.id)
                and discounted_profit > best_discounted_profit
            ):
                best_process = process
                best_discounted_profit = discounted_profit
                best_raw_profit = output_value - input_cost
        return (best_process, best_raw_profit)

    def test_matches_brute_force_scan_on_a_real_sim(self) -> None:
        from spacesim2.core.simulation import Simulation

        sim = Simulation()
        sim.setup_simple(
            num_planets=2, num_regular_actors=10, num_market_makers=1, num_ships=1
        )
        for _ in range(5):
            sim.run_turn()
        # run_turn leaves current_turn at the just-played turn, so brains
        # would (legitimately) serve quotes cached mid-phase, before end-of-
        # turn matching moved the books. Step to the next turn so both the
        # cache-backed path and the brute-force reference read the same
        # post-matching market state, as any real decide_* call would.
        sim.current_turn += 1

        checked = 0
        for planet in sim.planets:
            market = planet.market
            for actor in planet.actors:
                brain = actor.brain
                if not isinstance(brain, ColonistBrain):
                    continue
                expected = self._brute_force_reference(brain, actor, market)
                cache = brain._turn_cache(actor)
                got = brain._best_process_and_raw_profit(actor, market, cache)
                assert got == expected
                # And again from the memoized ranking after an inventory-only
                # change (the mid-turn path that skips the second scan).
                wood = sim.commodity_registry.get_commodity("wood")
                assert wood is not None
                actor.inventory.add_commodity(wood, 1)
                expected_after = self._brute_force_reference(brain, actor, market)
                cache = brain._turn_cache(actor)
                assert cache.ranked_profits is not None  # survived the bump
                got_after = brain._best_process_and_raw_profit(actor, market, cache)
                assert got_after == expected_after
                checked += 1
        assert checked >= 10
