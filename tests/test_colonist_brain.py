import pytest
from unittest.mock import Mock, MagicMock

from spacesim2.core.brains.colonist import ColonistBrain
from spacesim2.core.actor import Actor, ActorType
from spacesim2.core.commands import ProcessCommand, GovernmentWorkCommand, PlaceBuyOrderCommand
from spacesim2.core.commodity import CommodityDefinition, Inventory
from spacesim2.core.process import ProcessDefinition


class TestColonistBrainToolMarket:
    """Tests for colonist brain tool market behavior."""

    @pytest.fixture
    def mock_actor(self):
        """Create a mock actor for testing."""
        actor = Mock(spec=Actor)
        actor.name = "TestColonist"
        actor.actor_type = ActorType.REGULAR
        actor.money = 100
        actor.planet = Mock()
        actor.planet.market = Mock()
        actor.sim = Mock()
        actor.inventory = Mock(spec=Inventory)
        return actor

    @pytest.fixture
    def brain(self):
        return ColonistBrain()

    @pytest.fixture
    def mock_commodities(self):
        """Create mock commodities used in tests."""
        food = Mock(spec=CommodityDefinition)
        food.id = "food"
        food.transportable = True

        biomass = Mock(spec=CommodityDefinition)
        biomass.id = "biomass"
        biomass.transportable = True

        tools = Mock(spec=CommodityDefinition)
        tools.id = "simple_tools"
        tools.transportable = True

        common_metal = Mock(spec=CommodityDefinition)
        common_metal.id = "common_metal"
        common_metal.transportable = True

        return {
            "food": food,
            "biomass": biomass,
            "simple_tools": tools,
            "common_metal": common_metal,
        }

    def test_calculates_turn_opportunity_cost_minimum(self, brain, mock_actor):
        """Test that opportunity cost returns at least govt wage when no profitable processes."""
        # No planet = return govt wage
        actor_no_planet = Mock(spec=Actor)
        actor_no_planet.planet = None
        assert brain._calculate_turn_opportunity_cost(actor_no_planet) == 10

        # With planet but no profitable processes
        mock_actor.planet.market.get_bid_ask_spread.return_value = (None, None)
        mock_actor.planet.market.get_avg_price.return_value = 10
        mock_actor.sim.process_registry.all_processes.return_value = []
        mock_actor.can_execute_process.return_value = False

        result = brain._calculate_turn_opportunity_cost(mock_actor)
        assert result == 10  # Government wage

    def test_calculates_turn_opportunity_cost_from_profitable_process(self, brain, mock_actor):
        """Test that opportunity cost reflects profit from best available process."""
        # Create a profitable process
        input_commodity = Mock()
        input_commodity.id = "input1"
        output_commodity = Mock()
        output_commodity.id = "output1"

        process = Mock(spec=ProcessDefinition)
        process.id = "profitable_process"
        process.inputs = {input_commodity: 1}
        process.outputs = {output_commodity: 1}

        mock_actor.sim.process_registry.all_processes.return_value = [process]
        mock_actor.can_execute_process.return_value = True

        # Input costs 5, output sells for 30 = 25 profit
        def get_spread(commodity):
            if commodity == input_commodity:
                return (None, 5)  # Ask = 5
            if commodity == output_commodity:
                return (30, None)  # Bid = 30
            return (None, None)

        mock_actor.planet.market.get_bid_ask_spread.side_effect = get_spread
        mock_actor.planet.market.get_avg_price.return_value = 10

        result = brain._calculate_turn_opportunity_cost(mock_actor)
        assert result == 25  # Profit from process

    def test_calculates_tool_willingness_to_pay(self, brain, mock_actor, mock_commodities):
        """Test willingness to pay includes input cost + opportunity cost."""

        def get_commodity(name):
            return mock_commodities.get(name)

        mock_actor.sim.commodity_registry.get_commodity.side_effect = get_commodity

        # Metal costs 15 each (ask price)
        mock_actor.planet.market.get_bid_ask_spread.return_value = (None, 15)
        mock_actor.planet.market.get_avg_price.return_value = 15

        # No profitable processes, so opportunity cost = 10 (govt wage)
        mock_actor.sim.process_registry.all_processes.return_value = []
        mock_actor.can_execute_process.return_value = False

        willingness = brain._calculate_tool_willingness_to_pay(mock_actor)

        # input_cost = 15 * 2 = 30, opportunity_cost = 10
        assert willingness == 40

    def test_skips_making_tools_when_market_price_is_lower(
        self, brain, mock_actor, mock_commodities
    ):
        """Test that actor prefers buying tools when market price <= willingness to pay."""

        def get_commodity(name):
            return mock_commodities.get(name)

        mock_actor.sim.commodity_registry.get_commodity.side_effect = get_commodity

        # Setup: actor has low tool inventory
        def get_quantity(commodity):
            if commodity == mock_commodities["simple_tools"]:
                return 0  # No tools
            if commodity == mock_commodities["food"]:
                return 10  # Plenty of food
            return 10

        mock_actor.inventory.get_quantity.side_effect = get_quantity

        # Metal costs 10 each, willingness = 10*2 + 10 = 30
        # Tools available for 25 (below willingness to pay)
        def get_spread(commodity):
            if commodity == mock_commodities["common_metal"]:
                return (None, 10)
            if commodity == mock_commodities["simple_tools"]:
                return (None, 25)  # Ask = 25, below willingness
            return (None, None)

        mock_actor.planet.market.get_bid_ask_spread.side_effect = get_spread
        mock_actor.planet.market.get_avg_price.return_value = 10

        mock_actor.sim.process_registry.all_processes.return_value = []
        mock_actor.can_execute_process.return_value = True

        action = brain.decide_economic_action(mock_actor)

        # Should NOT be ProcessCommand("make_simple_tools") since buying is cheaper
        if isinstance(action, ProcessCommand):
            assert action.process_id != "make_simple_tools"

    def test_makes_tools_when_market_price_too_high(
        self, brain, mock_actor, mock_commodities
    ):
        """Test that actor makes tools when market price > willingness to pay."""

        def get_commodity(name):
            return mock_commodities.get(name)

        mock_actor.sim.commodity_registry.get_commodity.side_effect = get_commodity

        # Setup: actor has low tool inventory
        def get_quantity(commodity):
            if commodity == mock_commodities["simple_tools"]:
                return 0  # No tools
            if commodity == mock_commodities["food"]:
                return 10
            return 10

        mock_actor.inventory.get_quantity.side_effect = get_quantity

        # Metal costs 10 each, willingness = 10*2 + 10 = 30
        # Tools available for 50 (above willingness to pay)
        def get_spread(commodity):
            if commodity == mock_commodities["common_metal"]:
                return (None, 10)
            if commodity == mock_commodities["simple_tools"]:
                return (None, 50)  # Ask = 50, above willingness
            return (None, None)

        mock_actor.planet.market.get_bid_ask_spread.side_effect = get_spread
        mock_actor.planet.market.get_avg_price.return_value = 10

        mock_actor.sim.process_registry.all_processes.return_value = []
        mock_actor.can_execute_process.return_value = True

        action = brain.decide_economic_action(mock_actor)

        # Should make tools since market price is too high
        assert isinstance(action, ProcessCommand)
        assert action.process_id == "make_simple_tools"

    def test_places_buy_order_for_tools_at_willingness_to_pay_when_no_sellers(
        self, brain, mock_actor, mock_commodities
    ):
        """Test that actor places bid at willingness-to-pay when no sell orders exist."""

        def get_commodity(name):
            return mock_commodities.get(name)

        mock_actor.sim.commodity_registry.get_commodity.side_effect = get_commodity
        mock_actor.sim.commodity_registry.all_commodities.return_value = [
            mock_commodities["simple_tools"]
        ]

        # Setup: no sell orders for tools
        mock_actor.planet.market.sell_orders = {mock_commodities["simple_tools"]: []}
        mock_actor.planet.market.buy_orders = {mock_commodities["simple_tools"]: []}
        mock_actor.planet.market.get_actor_orders.return_value = {"buy": [], "sell": []}

        # Low tool inventory
        mock_actor.inventory.get_quantity.return_value = 0
        mock_actor.inventory.get_available_quantity.return_value = 0

        # Metal costs 15 each
        mock_actor.planet.market.get_bid_ask_spread.return_value = (None, 15)
        mock_actor.planet.market.get_avg_price.return_value = 15

        # No profitable processes
        mock_actor.sim.process_registry.all_processes.return_value = []
        mock_actor.can_execute_process.return_value = False

        commands = brain.decide_market_actions(mock_actor)

        buy_commands = [c for c in commands if isinstance(c, PlaceBuyOrderCommand)]
        assert len(buy_commands) == 1

        buy_cmd = buy_commands[0]
        assert buy_cmd.commodity_type == mock_commodities["simple_tools"]
        # willingness = 15*2 + 10 = 40
        assert buy_cmd.price == 40

    def test_places_buy_order_at_market_price_when_below_willingness(
        self, brain, mock_actor, mock_commodities
    ):
        """Test that actor matches market price when it's below willingness to pay."""

        def get_commodity(name):
            return mock_commodities.get(name)

        mock_actor.sim.commodity_registry.get_commodity.side_effect = get_commodity
        mock_actor.sim.commodity_registry.all_commodities.return_value = [
            mock_commodities["simple_tools"]
        ]

        # Setup: sell order for tools at 25
        sell_order = Mock()
        sell_order.price = 25
        sell_order.actor = Mock()  # Different actor
        sell_order.timestamp = 0

        mock_actor.planet.market.sell_orders = {
            mock_commodities["simple_tools"]: [sell_order]
        }
        mock_actor.planet.market.buy_orders = {mock_commodities["simple_tools"]: []}
        mock_actor.planet.market.get_actor_orders.return_value = {"buy": [], "sell": []}

        # Low tool inventory
        mock_actor.inventory.get_quantity.return_value = 0
        mock_actor.inventory.get_available_quantity.return_value = 0

        # Metal costs 15 each, willingness = 15*2 + 10 = 40
        mock_actor.planet.market.get_bid_ask_spread.return_value = (None, 15)
        mock_actor.planet.market.get_avg_price.return_value = 15

        mock_actor.sim.process_registry.all_processes.return_value = []
        mock_actor.can_execute_process.return_value = False

        commands = brain.decide_market_actions(mock_actor)

        buy_commands = [c for c in commands if isinstance(c, PlaceBuyOrderCommand)]
        assert len(buy_commands) == 1

        buy_cmd = buy_commands[0]
        assert buy_cmd.commodity_type == mock_commodities["simple_tools"]
        # Should match the market price, not willingness
        assert buy_cmd.price == 25

    def test_does_not_buy_tools_when_price_exceeds_willingness(
        self, brain, mock_actor, mock_commodities
    ):
        """Test that actor doesn't buy tools when market price > willingness."""

        def get_commodity(name):
            return mock_commodities.get(name)

        mock_actor.sim.commodity_registry.get_commodity.side_effect = get_commodity
        mock_actor.sim.commodity_registry.all_commodities.return_value = [
            mock_commodities["simple_tools"]
        ]

        # Setup: sell order for tools at 100 (way above willingness)
        sell_order = Mock()
        sell_order.price = 100
        sell_order.actor = Mock()
        sell_order.timestamp = 0

        mock_actor.planet.market.sell_orders = {
            mock_commodities["simple_tools"]: [sell_order]
        }
        mock_actor.planet.market.buy_orders = {mock_commodities["simple_tools"]: []}
        mock_actor.planet.market.get_actor_orders.return_value = {"buy": [], "sell": []}

        # Low tool inventory
        mock_actor.inventory.get_quantity.return_value = 0
        mock_actor.inventory.get_available_quantity.return_value = 0

        # Metal costs 15 each, willingness = 15*2 + 10 = 40
        mock_actor.planet.market.get_bid_ask_spread.return_value = (None, 15)
        mock_actor.planet.market.get_avg_price.return_value = 15

        mock_actor.sim.process_registry.all_processes.return_value = []
        mock_actor.can_execute_process.return_value = False

        commands = brain.decide_market_actions(mock_actor)

        # Should not place any buy order for tools (price too high)
        tool_buy_commands = [
            c
            for c in commands
            if isinstance(c, PlaceBuyOrderCommand)
            and c.commodity_type == mock_commodities["simple_tools"]
        ]
        assert len(tool_buy_commands) == 0
