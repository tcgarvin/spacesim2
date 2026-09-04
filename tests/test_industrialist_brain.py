from unittest.mock import Mock

import pytest

from spacesim2.core.actor import Actor, ActorType
from spacesim2.core.actor_brain import GOVERNMENT_WAGE, ActorBrain
from spacesim2.core.brains.industrialist import (
    RECIPE_COOLDOWN_TURNS,
    RECIPE_STUCK_TURNS,
    IndustrialistBrain,
)
from spacesim2.core.commands import (
    GovernmentWorkCommand,
    PlaceBuyOrderCommand,
    ProcessCommand,
)
from spacesim2.core.commodity import CommodityDefinition, Inventory
from spacesim2.core.market import Market
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

    def security(self, actor, unit_price):
        return self._buffer


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
        # Default the depth-aware output valuation to "the book cannot absorb
        # a run", and route its trade-history fallback to the same stub the
        # tests below already set, so they keep asserting on one price.
        actor.planet.market.get_bid_price_at_depth.return_value = None
        actor.planet.market.get_30_day_average_price.side_effect = (
            lambda commodity: float(actor.planet.market.get_avg_price(commodity))
        )
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
        # A healthy market: demand is being met and the good still turns over.
        market.scarcity_pressure_for.return_value = 0.0
        market.get_30_day_average_volume.return_value = 5.0

        commands = brain._buy_command(actor, market, refined, 1)

        assert len(commands) == 1
        assert commands[0].price == 12

    def test_stalled_traded_input_gets_the_bootstrap_premium(self, brain):
        """A traded good with no ask, unmet demand and no turnover is bid up.

        The stale average (11) sits below every supplier's 1.2x entry
        threshold, because suppliers cost the good off the same average. The
        bid escalates by the bootstrap margin: ceil(11 * 1.25) = 14.
        """
        actor = self._actor(money=1000)
        refined = self._commodity("refined_chemicals")

        market = Mock()
        market.sell_orders = {}
        market.get_bid_ask_spread.return_value = (None, None)
        market.has_price_signal.return_value = True
        market.get_avg_price.return_value = 11
        market.scarcity_pressure_for.return_value = 3.0
        market.get_30_day_average_volume.return_value = 0.0

        commands = brain._buy_command(actor, market, refined, 1)

        assert len(commands) == 1
        assert commands[0].price == 14

    def test_stalled_premium_needs_both_scarcity_and_no_turnover(self, brain):
        """Scarcity pressure alone, with the good still trading, is not enough.

        The premium is inflationary where supply exists, so a good that still
        turns over keeps its average-anchored bid.
        """
        actor = self._actor(money=1000)
        refined = self._commodity("refined_chemicals")

        market = Mock()
        market.sell_orders = {}
        market.get_bid_ask_spread.return_value = (None, None)
        market.has_price_signal.return_value = True
        market.get_avg_price.return_value = 11
        market.scarcity_pressure_for.return_value = 3.0
        market.get_30_day_average_volume.return_value = 4.0

        commands = brain._buy_command(actor, market, refined, 1)

        assert len(commands) == 1
        assert commands[0].price == 11

    def test_stalled_premium_does_not_apply_when_an_ask_rests(self, brain):
        """A resting ask is still lifted, however starved the market looks."""
        actor = self._actor(money=1000)
        refined = self._commodity("refined_chemicals")

        ask_order = Mock()
        ask_order.price = 8
        ask_order.actor = "someone_else"
        ask_order.timestamp = 0
        ask_order.cancelled = False

        market = Mock()
        market.sell_orders = {refined: [ask_order]}
        market.scarcity_pressure_for.return_value = 3.0
        market.get_30_day_average_volume.return_value = 0.0

        commands = brain._buy_command(actor, market, refined, 1)

        assert commands[0].price == 8

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


class TestDepthAwareOutputValuation:
    """Recipe output is valued at the bid level that can actually absorb it.

    A market maker seeding an illiquid good posts one-unit probes far above
    fair value. Read as the top of book they look like demand, and producers
    pile into a good nobody buys. See _output_unit_value.
    """

    @pytest.fixture
    def brain(self):
        return IndustrialistBrain()

    @staticmethod
    def _commodity(cid):
        return CommodityDefinition(id=cid, name=cid, transportable=True, description="")

    @staticmethod
    def _actor():
        actor = Mock(spec=Actor)
        actor.name = "TestIndustrialist"
        actor.actor_type = ActorType.REGULAR
        actor.money = 100
        actor.planet = Mock()
        actor.sim = Mock()
        _wire_producer_index(actor.sim)
        actor.sim.process_registry.all_processes.return_value = []
        actor.inventory = Mock(spec=Inventory)
        return actor

    @staticmethod
    def _bidder():
        bidder = Mock()
        bidder.name = "Bidder"
        bidder.money = 1_000_000
        bidder.reserved_money = 0
        bidder.active_orders = {}
        return bidder

    @staticmethod
    def _process(output_commodity, quantity=1):
        """A recipe with no inputs, so its cost is exactly a turn of labor."""
        process = Mock(spec=ProcessDefinition)
        process.id = "make_output"
        process.inputs = {}
        process.outputs = {output_commodity: quantity}
        process.tools_required = []
        process.facilities_required = []
        process.resource_attribute = None
        return process

    def test_phantom_top_bid_is_ignored_in_favor_of_depth(self, brain):
        """A 1-unit bid at 150 over a deep book at 20 scores against 20."""
        actor = self._actor()
        medicine = self._commodity("medicine")
        market = Market()
        bidder = self._bidder()

        market.place_buy_order(bidder, medicine, 1, 150)  # discovery probe
        market.place_buy_order(bidder, medicine, 20, 20)  # real demand

        assert market.get_bid_ask_spread(medicine)[0] == 150

        score = brain._calculate_recipe_score(actor, market, self._process(medicine))

        # Output valued at 20, not 150, minus a turn of labor at the
        # government wage.
        assert score == pytest.approx(10.0)

    def test_thin_book_below_cost_triggers_exit(self, brain):
        """Depth pricing is what the exit check sees too, so it goes negative."""
        actor = self._actor()
        medicine = self._commodity("medicine")
        market = Market()
        bidder = self._bidder()

        market.place_buy_order(bidder, medicine, 1, 150)
        market.place_buy_order(bidder, medicine, 20, 5)

        raw = brain._calculate_recipe_score(
            actor, market, self._process(medicine), require_entry_margin=False
        )

        assert raw == pytest.approx(-5.0)

    def test_never_traded_good_scores_via_reference_price(self, brain):
        """With no bids and no history, fall back to the reference price."""
        actor = self._actor()
        widget = self._commodity("widget")
        market = Market()

        assert not market.has_price_signal(widget)

        score = brain._calculate_recipe_score(
            actor, market, self._process(widget, quantity=4)
        )

        # 4 units at the reference price of 10, minus a turn of labor.
        assert score == pytest.approx(30.0)

    def test_never_traded_good_scores_via_a_bootstrap_bid(self, brain):
        """A lone procurement bid still enables a cold-start intermediate.

        Depth cannot cover the sales horizon here, and there is no trade
        history, so the resting bid is the only demand signal there is.
        Refusing it would re-open the producer/consumer standoff.
        """
        actor = self._actor()
        refined = self._commodity("refined_chemicals")
        market = Market()
        market.place_buy_order(self._bidder(), refined, 1, 28)

        score = brain._calculate_recipe_score(actor, market, self._process(refined))

        assert score == pytest.approx(18.0)

    def test_liquid_good_still_uses_the_top_bid(self, brain):
        """Turnover above the horizon means the top bid is backed by flow."""
        actor = self._actor()
        food = self._commodity("food")
        market = Market()
        market.place_buy_order(self._bidder(), food, 1, 40)

        # 30 turns of heavy trade: the book is thin only because it is being
        # rebuilt around us, not because demand is absent.
        market.price_history[food] = [10] * 30
        market.volume_history[food] = [50] * 30

        score = brain._calculate_recipe_score(actor, market, self._process(food))

        assert score == pytest.approx(30.0)

    def test_never_traded_output_is_capped_at_its_make_cost(self, brain):
        """A discovery probe above any plausible production cost is discounted."""
        actor = self._actor()
        widget = self._commodity("widget")
        process = self._process(widget)
        process.id = "make_widget"
        actor.sim.process_registry.all_processes.return_value = [process]
        actor.inventory.has_quantity.return_value = True

        market = Market()
        market.place_buy_order(self._bidder(), widget, 1, 150)

        capped = brain._output_unit_value(actor, market, widget, 1.0, {})
        uncapped = market.get_bid_ask_spread(widget)[0]

        assert uncapped == 150
        # Making one widget costs a turn of labor, so 150 is not demand.
        assert capped == pytest.approx(GOVERNMENT_WAGE * 1.5)


class TestBidDepthPricing:
    """Market.get_bid_price_at_depth walks the book instead of the top of it."""

    @staticmethod
    def _market_with_levels(commodity, levels):
        market = Market()
        bidder = Mock()
        bidder.name = "Bidder"
        bidder.money = 1_000_000
        bidder.reserved_money = 0
        bidder.active_orders = {}
        for price, quantity in levels:
            market.place_buy_order(bidder, commodity, quantity, price)
        return market

    def test_walks_down_to_the_level_that_covers_the_quantity(self):
        commodity = CommodityDefinition(
            id="medicine", name="medicine", transportable=True, description=""
        )
        market = self._market_with_levels(commodity, [(150, 1), (30, 2), (20, 10)])

        assert market.get_bid_price_at_depth(commodity, 1) == 150
        assert market.get_bid_price_at_depth(commodity, 3) == 30
        assert market.get_bid_price_at_depth(commodity, 4) == 20
        assert market.get_bid_price_at_depth(commodity, 13) == 20

    def test_returns_none_when_the_book_is_too_thin(self):
        commodity = CommodityDefinition(
            id="medicine", name="medicine", transportable=True, description=""
        )
        market = self._market_with_levels(commodity, [(150, 1)])

        assert market.get_bid_price_at_depth(commodity, 2) is None
        assert market.get_bid_price_at_depth(commodity, 0) is None

    def test_cancelled_bids_do_not_count_as_depth(self):
        commodity = CommodityDefinition(
            id="medicine", name="medicine", transportable=True, description=""
        )
        market = self._market_with_levels(commodity, [(150, 1), (20, 10)])
        deep_order = next(o for o in market.buy_orders[commodity] if o.price == 20)
        market.cancel_order(deep_order.order_id)

        assert market.get_bid_price_at_depth(commodity, 3) is None


class TestStuckRecipeAbandonment:
    """An industrialist drops a recipe it can never run.

    The exit check only fires on a negative score, so a recipe that scores
    well but is permanently missing an input was held forever while the actor
    fell through to government work every turn.
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

    def _actor(self, quantities, facilities=()):
        """Actor whose inventory holds ``quantities`` (commodity id -> units)."""
        actor = Mock(spec=Actor)
        actor.name = "TestIndustrialist"
        actor.actor_type = ActorType.REGULAR
        actor.money = 1000
        actor.planet = Mock()
        actor.sim = Mock()
        actor.sim.current_turn = 100
        _wire_producer_index(actor.sim)
        actor.inventory = Mock(spec=Inventory)
        actor.inventory.get_quantity.side_effect = lambda c: quantities.get(c.id, 0)
        actor.inventory.has_quantity.side_effect = (
            lambda c, q=1: quantities.get(c.id, 0) >= q
        )
        actor.can_execute.side_effect = lambda p: all(
            quantities.get(c.id, 0) >= q for c, q in p.requirements
        )
        return actor

    def _process(self, pid, inputs, facilities=()):
        process = Mock(spec=ProcessDefinition)
        process.id = pid
        process.inputs = dict(inputs)
        process.outputs = {}
        process.tools_required = []
        process.facilities_required = list(facilities)
        process.resource_attribute = None
        process.requirements = [(c, q) for c, q in inputs.items()] + [
            (f, 1) for f in facilities
        ]
        return process

    def test_unrunnable_static_recipe_is_abandoned_and_cooled_down(self, brain):
        chem = self._commodity("chemicals")
        quantities = {}
        actor = self._actor(quantities)
        process = self._process("make_medicine", {chem: 3})
        actor.sim.process_registry.get_process.return_value = process

        brain.chosen_recipe_id = "make_medicine"
        for _ in range(RECIPE_STUCK_TURNS):
            brain._update_stuck_tracking(actor)
            assert brain.chosen_recipe_id == "make_medicine"

        brain._update_stuck_tracking(actor)

        assert brain.chosen_recipe_id is None
        assert brain.recipe_cooldown_until["make_medicine"] == (
            actor.sim.current_turn + RECIPE_COOLDOWN_TURNS
        )

    def test_procurement_progress_resets_the_stuck_counter(self, brain):
        chem = self._commodity("chemicals")
        quantities = {}
        actor = self._actor(quantities)
        process = self._process("make_medicine", {chem: 3})
        actor.sim.process_registry.get_process.return_value = process

        brain.chosen_recipe_id = "make_medicine"
        for turn in range(RECIPE_STUCK_TURNS * 3):
            # One unit trickles in every 10 turns: slow, but not stuck.
            if turn % 10 == 9:
                quantities["chemicals"] = quantities.get("chemicals", 0) + 1
            brain._update_stuck_tracking(actor)

        assert brain.chosen_recipe_id == "make_medicine"
        assert brain.recipe_cooldown_until == {}

    def test_facility_build_progress_is_not_stuck(self, brain):
        """Assembling a facility's build inputs counts as progress."""
        lab = self._commodity("chemistry_lab")
        lab.transportable = False
        bricks = self._commodity("simple_building_materials")
        quantities = {}
        actor = self._actor(quantities)
        process = self._process("make_medicine", {}, facilities=[lab])
        build = self._process("build_chemistry_lab", {bricks: 20})

        def get_process(pid):
            return {"make_medicine": process, "build_chemistry_lab": build}[pid]

        actor.sim.process_registry.get_process.side_effect = get_process
        actor.sim.process_registry.all_processes.return_value = [process, build]
        _wire_producer_index(actor.sim)

        brain.chosen_recipe_id = "make_medicine"
        for turn in range(RECIPE_STUCK_TURNS * 2):
            if turn % 5 == 4:
                quantities["simple_building_materials"] = (
                    quantities.get("simple_building_materials", 0) + 1
                )
            brain._update_stuck_tracking(actor)

        assert brain.chosen_recipe_id == "make_medicine"

    def test_runnable_recipe_is_never_stuck(self, brain):
        chem = self._commodity("chemicals")
        actor = self._actor({"chemicals": 5})
        process = self._process("make_medicine", {chem: 3})
        actor.sim.process_registry.get_process.return_value = process

        brain.chosen_recipe_id = "make_medicine"
        for _ in range(RECIPE_STUCK_TURNS * 2):
            brain._update_stuck_tracking(actor)

        assert brain.chosen_recipe_id == "make_medicine"
        assert brain.stuck_turns == 0

    def test_cooled_down_recipe_is_excluded_then_selectable_again(self, brain):
        chem = self._commodity("chemicals")
        actor = self._actor({})
        process = self._process("make_medicine", {chem: 3})
        actor.sim.process_registry.all_processes.return_value = [process]
        actor.sim.process_registry.get_process.return_value = process

        brain.recipe_cooldown_until["make_medicine"] = actor.sim.current_turn + 10
        assert brain._recipes_on_cooldown(actor) == {"make_medicine"}
        assert brain._select_new_recipe(actor) is None

        actor.sim.current_turn += 20
        assert brain._recipes_on_cooldown(actor) == set()
        assert brain.recipe_cooldown_until == {}
