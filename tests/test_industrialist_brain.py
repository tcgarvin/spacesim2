from unittest.mock import Mock

import pytest

from spacesim2.core.actor import Actor, ActorType
from spacesim2.core.actor_brain import ActorBrain
from spacesim2.core.brains.industrialist import IndustrialistBrain
from spacesim2.core.commands import (
    GovernmentWorkCommand,
    PlaceBuyOrderCommand,
    ProcessCommand,
)
from spacesim2.core.commodity import CommodityDefinition, Inventory
from spacesim2.core.process import ProcessDefinition


def _wire_producer_index(sim_mock):
    """Derive the mock's get_processes_producing from all_processes.return_value.

    Evaluated lazily, so tests may set the list after the fixture runs.
    Mirrors the id-keyed producer index in ProcessRegistry.
    """
    registry = sim_mock.process_registry
    registry.get_processes_producing.side_effect = lambda commodity: [
        p
        for p in registry.all_processes.return_value
        if any(out.id == commodity.id for out in p.outputs)
    ]


class _StubDrive:
    """Minimal drive with the interface ActorBrain pricing uses."""

    def __init__(self, name, materials, target, miss_penalty=0.2, buffer=0.0):
        self._materials = materials
        self._target = target
        self._stake = miss_penalty
        self._buffer = buffer
        self.metrics = Mock()
        self.metrics.get_name.return_value = name
        self.metrics.buffer = buffer

    def materials(self):
        return list(self._materials)

    def target_units(self):
        return self._target

    def deprivation_stake(self):
        return self._stake

    def marginal_welfare(self):
        return self._stake * (1.0 - self._buffer)


class TestIndustrialistBrain:
    @pytest.fixture
    def mock_actor(self):
        """Mock actor with a mocked planet, market, sim, and inventory."""
        actor = Mock(spec=Actor)
        actor.name = "TestIndustrialist"
        actor.actor_type = ActorType.REGULAR
        actor.money = 100
        actor.planet = Mock()
        actor.planet.market = Mock()
        actor.sim = Mock()
        _wire_producer_index(actor.sim)
        actor.inventory = Mock(spec=Inventory)
        actor.drives = []
        return actor

    @pytest.fixture
    def mock_food_commodity(self):
        """Mock food commodity."""
        food = Mock(spec=CommodityDefinition)
        food.id = "food"
        return food

    @pytest.fixture
    def brain(self):
        """IndustrialistBrain instance."""
        return IndustrialistBrain()

    def test_initial_state(self, brain):
        """A new brain has no chosen recipe."""
        assert brain.chosen_recipe_id is None
        assert brain.turns_since_recipe_evaluation == 0

    def test_recipe_reevaluation_chance(self, brain):
        """Recipe reevaluation fires about 1% of the time."""
        reevaluations = 0
        iterations = 5000

        for _ in range(iterations):
            if brain._should_reevaluate_recipe():
                reevaluations += 1

        # Wide band around 1% to absorb sampling variance.
        reevaluation_rate = reevaluations / iterations
        assert 0.003 < reevaluation_rate < 0.025

    def test_food_shortage_emergency_action(
        self, brain, mock_actor, mock_food_commodity
    ):
        """With under 2 food the actor makes food before anything else."""
        mock_actor.sim.commodity_registry.get_commodity.return_value = (
            mock_food_commodity
        )
        mock_actor.sim.process_registry.all_processes.return_value = []
        mock_actor.inventory.get_quantity.return_value = 1
        mock_actor.can_execute_process.return_value = True

        brain.chosen_recipe_id = None

        action = brain.decide_economic_action(mock_actor)

        assert isinstance(action, ProcessCommand)
        assert action.process_id == "make_food"

    def test_executes_chosen_recipe_when_possible(
        self, brain, mock_actor, mock_food_commodity
    ):
        """The actor runs its chosen recipe when it can."""
        mock_actor.sim.commodity_registry.get_commodity.return_value = (
            mock_food_commodity
        )
        mock_actor.inventory.get_quantity.return_value = 10
        mock_actor.inventory.has_quantity.return_value = True
        mock_actor.can_execute_process.return_value = True

        mock_process = Mock(spec=ProcessDefinition)
        mock_process.tools_required = []
        mock_process.facilities_required = []
        mock_actor.sim.process_registry.get_process.return_value = mock_process

        brain.chosen_recipe_id = "test_recipe"

        action = brain.decide_economic_action(mock_actor)

        assert isinstance(action, ProcessCommand)
        assert action.process_id == "test_recipe"

    def test_falls_back_to_government_work(
        self, brain, mock_actor, mock_food_commodity
    ):
        """The actor does government work when it cannot run its recipe."""
        mock_actor.sim.commodity_registry.get_commodity.return_value = (
            mock_food_commodity
        )
        mock_actor.inventory.get_quantity.return_value = 10
        mock_actor.inventory.has_quantity.return_value = True
        mock_actor.can_execute_process.return_value = False

        mock_process = Mock(spec=ProcessDefinition)
        mock_process.tools_required = []
        mock_process.facilities_required = []
        mock_actor.sim.process_registry.get_process.return_value = mock_process

        brain.chosen_recipe_id = "test_recipe"

        action = brain.decide_economic_action(mock_actor)

        assert isinstance(action, GovernmentWorkCommand)

    def test_recipe_score_includes_labor_cost(self, brain, mock_actor):
        """Recipe scoring charges a turn of labor on top of input costs."""
        input_commodity = Mock()
        input_commodity.id = "input1"
        output_commodity = Mock()
        output_commodity.id = "output1"

        process = Mock(spec=ProcessDefinition)
        process.inputs = {input_commodity: 2}
        process.outputs = {output_commodity: 1}
        process.tools_required = []
        process.facilities_required = []
        process.resource_attribute = None

        market = mock_actor.planet.market

        market.get_bid_ask_spread.return_value = (None, None)

        # Viable recipe: inputs 2 x 10 + labor 10 = 30 cost, output sells for
        # 40, which clears the 20% margin, so the score is the profit of 10.
        def viable_prices(commodity):
            if commodity is input_commodity:
                return 10
            if commodity is output_commodity:
                return 40
            return 0

        market.get_avg_price.side_effect = viable_prices

        score = brain._calculate_recipe_score(mock_actor, market, process)
        assert score == pytest.approx(10.0, rel=0.01)

        # Covers inputs but not the turn of labor: cost 30, output sells for
        # 25, so not viable.
        def below_wage_prices(commodity):
            if commodity is input_commodity:
                return 10
            if commodity is output_commodity:
                return 25
            return 0

        market.get_avg_price.side_effect = below_wage_prices

        assert brain._calculate_recipe_score(mock_actor, market, process) == 0.0
        # The exit check sees the raw negative profit without the entry margin.
        raw = brain._calculate_recipe_score(
            mock_actor, market, process, require_entry_margin=False
        )
        assert raw == pytest.approx(-5.0, rel=0.01)

    def test_market_actions_cancel_existing_orders(self, brain, mock_actor):
        """decide_market_actions cancels the actor's existing orders."""
        existing_buy_order = Mock()
        existing_buy_order.order_id = "buy123"
        existing_sell_order = Mock()
        existing_sell_order.order_id = "sell456"

        mock_actor.planet.market.get_actor_orders.return_value = {
            "buy": [existing_buy_order],
            "sell": [existing_sell_order],
        }
        mock_actor.sim.commodity_registry.get_commodity.return_value = (
            None  # no food commodity
        )

        commands = brain.decide_market_actions(mock_actor)

        cancel_commands = [
            cmd for cmd in commands if cmd.__class__.__name__ == "CancelOrderCommand"
        ]
        assert len(cancel_commands) == 2
        order_ids = [cmd.order_id for cmd in cancel_commands]
        assert "buy123" in order_ids
        assert "sell456" in order_ids

    def test_food_purchase_behavior(self, brain, mock_actor, mock_food_commodity):
        """Drive-backed food demand lifts the resting ask up to the target."""
        mock_actor.inventory.get_quantity.return_value = 3  # below target of 6
        mock_actor.money = 100

        mock_actor.drives = [
            _StubDrive("food", [mock_food_commodity], target=6, miss_penalty=0.2)
        ]

        sell_order = Mock()
        sell_order.price = 5
        sell_order.actor = "different_actor"
        sell_order.timestamp = 0
        sell_order.cancelled = False

        mock_actor.planet.market.sell_orders = {mock_food_commodity: [sell_order]}
        mock_actor.planet.market.get_bid_ask_spread.return_value = (None, 5)
        mock_actor.planet.market.get_actor_orders.return_value = {"buy": [], "sell": []}
        # No resting own orders: the cheapest-ask fast path checks this map.
        mock_actor.planet.market.actor_orders = {}
        mock_actor.sim.commodity_registry.get_commodity.return_value = (
            mock_food_commodity
        )
        # Food trades around 10, so willingness of price * (1 - buffer) = 10
        # sits above the 5 ask. No recipe produces food locally, so no make cap.
        mock_actor.planet.market.get_avg_price.return_value = 10
        mock_actor.sim.process_registry.all_processes.return_value = []

        commands = brain.decide_market_actions(mock_actor)

        buy_commands = [
            cmd for cmd in commands if isinstance(cmd, PlaceBuyOrderCommand)
        ]
        assert len(buy_commands) > 0

        food_buy_command = next(
            (cmd for cmd in buy_commands if cmd.commodity_type == mock_food_commodity),
            None,
        )
        assert food_buy_command is not None
        assert food_buy_command.quantity == 3  # 3 more reaches the target of 6
        assert food_buy_command.price == 5

    def test_recipe_viability_considers_planet_attributes(self, brain, mock_actor):
        """Recipe score scales gathering output by planet availability."""
        from spacesim2.core.process import ResourceAttribute

        output_commodity = Mock()
        output_commodity.id = "biomass"

        process = Mock(spec=ProcessDefinition)
        process.inputs = {}
        process.outputs = {output_commodity: 4}
        process.tools_required = []
        process.facilities_required = []
        process.resource_attribute = ResourceAttribute(
            commodity="biomass", effect="output"
        )

        mock_actor.inventory.has_quantity.return_value = True

        market = mock_actor.planet.market
        market.get_bid_ask_spread.return_value = (None, None)
        market.get_avg_price.return_value = 10

        mock_actor.planet.attributes = Mock()
        mock_actor.planet.attributes.get_availability.return_value = 0.9

        # Output 4 * 0.9 = 3.6, value 36, minus a turn of labor at the
        # government wage gives profit 26.
        score_good = brain._calculate_recipe_score(mock_actor, market, process)
        assert score_good > 0
        assert score_good == pytest.approx(26.0, rel=0.01)

        mock_actor.planet.attributes.get_availability.return_value = 0.2

        # Output 4 * 0.2 = 0.8, value 8, below the cost of the labor turn, so
        # gathering here is not viable.
        score_poor = brain._calculate_recipe_score(mock_actor, market, process)
        assert score_poor == 0.0

    def test_recipe_selection_prefers_profitable_recipes(self, brain, mock_actor):
        """Recipe selection is weighted by score."""
        from spacesim2.core.process import ResourceAttribute

        biomass_commodity = Mock()
        biomass_commodity.id = "biomass"
        fiber_commodity = Mock()
        fiber_commodity.id = "fiber"

        biomass_process = Mock(spec=ProcessDefinition)
        biomass_process.id = "gather_biomass"
        biomass_process.inputs = {}
        biomass_process.outputs = {biomass_commodity: 4}
        biomass_process.tools_required = []
        biomass_process.facilities_required = []
        biomass_process.resource_attribute = ResourceAttribute(
            commodity="biomass", effect="output"
        )

        fiber_process = Mock(spec=ProcessDefinition)
        fiber_process.id = "gather_fiber"
        fiber_process.inputs = {}
        fiber_process.outputs = {fiber_commodity: 3}
        fiber_process.tools_required = []
        fiber_process.facilities_required = []
        fiber_process.resource_attribute = ResourceAttribute(
            commodity="fiber", effect="output"
        )

        mock_actor.sim.process_registry.all_processes.return_value = [
            biomass_process,
            fiber_process,
        ]

        mock_actor.inventory.has_quantity.return_value = True

        market = mock_actor.planet.market
        market.get_bid_ask_spread.return_value = (None, None)
        market.get_avg_price.return_value = 10

        # The planet is rich in biomass and poor in fiber.
        def get_availability(commodity_id):
            if commodity_id == "biomass":
                return 0.9
            if commodity_id == "fiber":
                return 0.1
            return 1.0

        mock_actor.planet.attributes = Mock()
        mock_actor.planet.attributes.get_availability.side_effect = get_availability

        import random

        random.seed(42)

        selections = {"gather_biomass": 0, "gather_fiber": 0}
        for _ in range(100):
            recipe = brain._select_new_recipe(mock_actor)
            if recipe:
                selections[recipe] += 1

        # Biomass has a 9x score advantage.
        assert selections["gather_biomass"] > selections["gather_fiber"] * 3


class TestImputedProcurementBids:
    """Cold-start bids for never-traded intermediates use imputed replacement cost.

    get_avg_price returns a default of 10 with no trades, which must not be
    used as the bid.
    """

    @pytest.fixture
    def brain(self):
        return IndustrialistBrain()

    @staticmethod
    def _commodity(cid):
        c = Mock(spec=CommodityDefinition)
        c.id = cid
        c.transportable = True
        return c

    @staticmethod
    def _actor(money=100):
        actor = Mock(spec=Actor)
        actor.name = "TestIndustrialist"
        actor.actor_type = ActorType.REGULAR
        actor.money = money
        actor.planet = Mock()
        actor.sim = Mock()
        _wire_producer_index(actor.sim)
        actor.inventory = Mock(spec=Inventory)
        return actor

    def _refined_chain(self, actor):
        """refined_chemicals made from 3 chemicals with a live ask of 4.

        Imputed cost is labor 10 + 3 * 4 = 22.
        """
        refined = self._commodity("refined_chemicals")
        chem = self._commodity("chemicals")

        process = Mock(spec=ProcessDefinition)
        process.id = "refine_chemicals"
        process.inputs = {chem: 3}
        process.outputs = {refined: 1}
        process.tools_required = []
        process.facilities_required = []
        process.resource_attribute = None
        actor.sim.process_registry.all_processes.return_value = [process]
        return refined, chem

    def test_never_traded_input_bids_imputed_cost_not_default(self, brain):
        """With no ask and no price signal, bid imputed cost times the margin.

        The bootstrap margin must clear a supplier's 1.2x entry threshold:
        ceil(22 * 1.25) = 28.
        """
        actor = self._actor()
        refined, chem = self._refined_chain(actor)

        market = Mock()
        market.sell_orders = {}

        def spread(commodity):
            # chemicals has a live ask as its cost anchor; refined has none.
            return (None, 4) if commodity is chem else (None, None)

        market.get_bid_ask_spread.side_effect = spread
        market.has_price_signal.return_value = False
        market.get_avg_price.return_value = 10  # the no-trade default

        commands = brain._buy_command(actor, market, refined, 1)

        assert len(commands) == 1
        assert isinstance(commands[0], PlaceBuyOrderCommand)
        assert commands[0].commodity_type is refined
        assert commands[0].price == 28  # ceil(22 * PROCUREMENT_BOOTSTRAP_MARGIN)
        assert commands[0].quantity == 1

    def test_traded_input_lifts_resting_ask(self, brain):
        """A resting ask is lifted directly without imputation."""
        actor = self._actor()
        refined = self._commodity("refined_chemicals")

        ask_order = Mock()
        ask_order.price = 8
        ask_order.actor = "someone_else"
        ask_order.timestamp = 0
        ask_order.cancelled = False

        market = Mock()
        market.sell_orders = {refined: [ask_order]}

        commands = brain._buy_command(actor, market, refined, 1)

        assert len(commands) == 1
        assert commands[0].price == 8

    def test_traded_input_with_price_signal_uses_avg(self, brain):
        """With no ask but a real price signal, the bid anchors on the average."""
        actor = self._actor()
        refined = self._commodity("refined_chemicals")

        market = Mock()
        market.sell_orders = {}
        market.get_bid_ask_spread.return_value = (None, None)
        market.has_price_signal.return_value = True
        market.get_avg_price.return_value = 12

        commands = brain._buy_command(actor, market, refined, 1)

        assert len(commands) == 1
        assert commands[0].price == 12

    def test_imputation_falls_through_when_no_price_signal(self, brain):
        """_imputed_unit_cost recurses into the recipe when there is no price signal."""
        actor = self._actor()
        refined, chem = self._refined_chain(actor)

        market = Mock()

        def spread(commodity):
            return (None, 4) if commodity is chem else (None, None)

        market.get_bid_ask_spread.side_effect = spread
        market.has_price_signal.return_value = False
        market.get_avg_price.return_value = 10

        cost = brain._imputed_unit_cost(actor, market, refined, 0, frozenset(), {})
        assert cost == pytest.approx(22.0)

    def test_imputation_trusts_avg_when_price_signal_exists(self, brain):
        """With a real price signal, the average is trusted."""
        actor = self._actor()
        refined = self._commodity("refined_chemicals")

        market = Mock()
        market.get_bid_ask_spread.return_value = (None, None)
        market.has_price_signal.return_value = True
        market.get_avg_price.return_value = 10

        cost = brain._imputed_unit_cost(actor, market, refined, 0, frozenset(), {})
        assert cost == pytest.approx(10.0)


class TestDriveBidReference:
    """Consumer-side twin of TestImputedProcurementBids.

    The reference a standing drive bid escalates from anchors on the buyer's
    imputed replacement cost for never-traded goods, not the get_avg_price
    default, and is cached per market and turn.
    """

    @pytest.fixture
    def brain(self):
        # Base-class behavior, inherited by every ActorBrain subclass.
        return ActorBrain()

    @staticmethod
    def _commodity(cid):
        c = Mock(spec=CommodityDefinition)
        c.id = cid
        c.transportable = True
        return c

    @staticmethod
    def _actor():
        actor = Mock(spec=Actor)
        actor.sim = Mock()
        _wire_producer_index(actor.sim)
        actor.inventory = Mock(spec=Inventory)
        actor.inventory.has_quantity.return_value = False
        return actor

    def _refined_chain(self, actor):
        """refined_chemicals made from 3 chemicals with a live ask of 4.

        Imputed cost is labor 10 + 3 * 4 = 22.
        """
        refined = self._commodity("refined_chemicals")
        chem = self._commodity("chemicals")

        process = Mock(spec=ProcessDefinition)
        process.id = "refine_chemicals"
        process.inputs = {chem: 3}
        process.outputs = {refined: 1}
        process.tools_required = []
        process.facilities_required = []
        process.resource_attribute = None
        actor.sim.process_registry.all_processes.return_value = [process]
        return refined, chem

    @staticmethod
    def _market(chem):
        market = Mock()
        market.current_turn = 5
        market.drive_anchor_cache = {}

        def spread(commodity):
            # chemicals has a live ask as its cost anchor; nothing else does.
            return (None, 4) if commodity is chem else (None, None)

        market.get_bid_ask_spread.side_effect = spread
        market.get_avg_price.return_value = 10  # the no-trade default
        return market

    def test_never_traded_good_anchors_on_imputed_cost(self, brain):
        """With no price signal the anchor is the imputed cost of 22, not 10."""
        actor = self._actor()
        refined, chem = self._refined_chain(actor)
        market = self._market(chem)
        market.has_price_signal.return_value = False

        ref = brain._drive_bid_reference(actor, market, refined)

        assert ref == pytest.approx(22.0)

    def test_price_signal_uses_avg_directly(self, brain):
        """With a real trade history the average is used without imputation."""
        actor = self._actor()
        refined, chem = self._refined_chain(actor)
        market = self._market(chem)
        market.has_price_signal.return_value = True
        market.get_avg_price.return_value = 15

        ref = brain._drive_bid_reference(actor, market, refined)

        assert ref == pytest.approx(15.0)

    def test_anchor_is_cached_per_turn_and_recomputed_next_turn(self, brain):
        """The imputed anchor is memoized per market and turn.

        The first call on turn 5 imputes 22 and caches it. Removing the
        producing recipe makes the good un-imputable, but a same-turn call
        still returns the cached 22. The next turn recomputes and, with no
        recipe, falls back to the default. A floor beats no bid.
        """
        actor = self._actor()
        refined, chem = self._refined_chain(actor)
        market = self._market(chem)
        market.has_price_signal.return_value = False

        first = brain._drive_bid_reference(actor, market, refined)
        assert first == pytest.approx(22.0)
        assert market.drive_anchor_cache[refined.id] == (5, pytest.approx(22.0))

        # With the recipe gone, fresh imputation yields inf and falls back.
        actor.sim.process_registry.all_processes.return_value = []

        # Same turn: served from cache, still 22.
        assert brain._drive_bid_reference(actor, market, refined) == pytest.approx(22.0)

        # New turn: recompute; with no recipe, fall back to the default.
        market.current_turn = 6
        assert brain._drive_bid_reference(actor, market, refined) == pytest.approx(10.0)
