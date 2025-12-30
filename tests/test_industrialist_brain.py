import pytest
from unittest.mock import Mock, MagicMock

from spacesim2.core.brains.industrialist import IndustrialistBrain
from spacesim2.core.actor import Actor, ActorType
from spacesim2.core.commands import ProcessCommand, GovernmentWorkCommand, PlaceBuyOrderCommand, PlaceSellOrderCommand
from spacesim2.core.commodity import CommodityDefinition, Inventory
from spacesim2.core.process import ProcessDefinition


class TestIndustrialistBrain:
    
    @pytest.fixture
    def mock_actor(self):
        """Create a mock actor for testing."""
        actor = Mock(spec=Actor)
        actor.name = "TestIndustrialist"
        actor.actor_type = ActorType.REGULAR
        actor.money = 100
        actor.planet = Mock()
        actor.planet.market = Mock()
        actor.sim = Mock()
        actor.inventory = Mock(spec=Inventory)
        return actor
    
    @pytest.fixture
    def mock_food_commodity(self):
        """Create a mock food commodity."""
        food = Mock(spec=CommodityDefinition)
        food.id = "food"
        return food
    
    @pytest.fixture
    def brain(self):
        """Create an IndustrialistBrain instance."""
        return IndustrialistBrain()
    
    def test_initial_state(self, brain):
        """Test that brain starts with no chosen recipe."""
        assert brain.chosen_recipe_id is None
        assert brain.turns_since_recipe_evaluation == 0
    
    def test_recipe_reevaluation_chance(self, brain):
        """Test that recipe reevaluation has roughly 1% chance."""
        # Run many iterations to test probability
        reevaluations = 0
        iterations = 1000
        
        for _ in range(iterations):
            if brain._should_reevaluate_recipe():
                reevaluations += 1
        
        # Should be roughly 1% (allow some variance)
        reevaluation_rate = reevaluations / iterations
        assert 0.005 < reevaluation_rate < 0.02  # Between 0.5% and 2%
    
    def test_food_shortage_emergency_action(self, brain, mock_actor, mock_food_commodity):
        """Test that actor tries to make food in emergency (< 2 food)."""
        # Setup: Very low food, can make food
        mock_actor.sim.commodity_registry.get_commodity.return_value = mock_food_commodity
        mock_actor.sim.process_registry.all_processes.return_value = []  # No processes available for recipe selection
        mock_actor.inventory.get_quantity.return_value = 1  # Critical shortage
        mock_actor.can_execute_process.return_value = True
        
        # No chosen recipe yet
        brain.chosen_recipe_id = None
        
        action = brain.decide_economic_action(mock_actor)
        
        assert isinstance(action, ProcessCommand)
        assert action.process_id == "make_food"
    
    def test_executes_chosen_recipe_when_possible(self, brain, mock_actor, mock_food_commodity):
        """Test that actor executes chosen recipe when possible."""
        # Setup: Adequate food, has chosen recipe, can execute it
        mock_actor.sim.commodity_registry.get_commodity.return_value = mock_food_commodity
        mock_actor.inventory.get_quantity.return_value = 10  # Plenty of food
        mock_actor.can_execute_process.return_value = True
        
        brain.chosen_recipe_id = "test_recipe"
        
        action = brain.decide_economic_action(mock_actor)
        
        assert isinstance(action, ProcessCommand)
        assert action.process_id == "test_recipe"
    
    def test_falls_back_to_government_work(self, brain, mock_actor, mock_food_commodity):
        """Test that actor does government work when can't execute recipe."""
        # Setup: Adequate food, has recipe but can't execute it
        mock_actor.sim.commodity_registry.get_commodity.return_value = mock_food_commodity
        mock_actor.inventory.get_quantity.return_value = 10  # Plenty of food
        mock_actor.can_execute_process.return_value = False  # Can't execute recipe
        
        brain.chosen_recipe_id = "test_recipe"
        
        action = brain.decide_economic_action(mock_actor)
        
        assert isinstance(action, GovernmentWorkCommand)
    
    def test_recipe_viability_calculation(self, brain, mock_actor):
        """Test that recipe viability is calculated correctly."""
        # Create mock commodities with id attribute
        input_commodity = Mock()
        input_commodity.id = "input1"
        output_commodity = Mock()
        output_commodity.id = "output1"

        # Create a mock process with known inputs/outputs
        process = Mock(spec=ProcessDefinition)
        process.inputs = {input_commodity: 2}  # Needs 2 units of input1
        process.outputs = {output_commodity: 1}  # Produces 1 unit of output1
        process.resource_attribute = None  # No planet attribute dependency

        market = mock_actor.planet.market

        # Mock get_bid_ask_spread to return None (no spread data)
        market.get_bid_ask_spread.return_value = (None, None)

        # Test viable recipe (profitable)
        # Input costs 10 each (total = 20), output sells for 30, margin = 50%
        def viable_prices(commodity):
            if commodity is input_commodity:
                return 10
            if commodity is output_commodity:
                return 30
            return 0

        market.get_avg_price.side_effect = viable_prices

        assert brain._is_recipe_viable(mock_actor, market, process) == True

        # Test non-viable recipe (unprofitable)
        # Input costs 15 each (total = 30), output sells for 25, loss
        def unprofitable_prices(commodity):
            if commodity is input_commodity:
                return 15
            if commodity is output_commodity:
                return 25
            return 0

        market.get_avg_price.side_effect = unprofitable_prices

        assert brain._is_recipe_viable(mock_actor, market, process) == False
    
    def test_market_actions_cancel_existing_orders(self, brain, mock_actor):
        """Test that existing orders are cancelled first."""
        # Setup mock market with existing orders
        existing_buy_order = Mock()
        existing_buy_order.order_id = "buy123"
        existing_sell_order = Mock() 
        existing_sell_order.order_id = "sell456"
        
        mock_actor.planet.market.get_actor_orders.return_value = {
            "buy": [existing_buy_order],
            "sell": [existing_sell_order]
        }
        mock_actor.sim.commodity_registry.get_commodity.return_value = None  # No food commodity
        
        commands = brain.decide_market_actions(mock_actor)
        
        # Should have cancel commands for both orders
        cancel_commands = [cmd for cmd in commands if cmd.__class__.__name__ == "CancelOrderCommand"]
        assert len(cancel_commands) == 2
        order_ids = [cmd.order_id for cmd in cancel_commands]
        assert "buy123" in order_ids
        assert "sell456" in order_ids
    
    def test_food_purchase_behavior(self, brain, mock_actor, mock_food_commodity):
        """Test that industrialist tries to buy food from market."""
        # Setup: Low food, market has food for sale
        mock_actor.inventory.get_quantity.return_value = 3  # Below target of 6
        mock_actor.money = 100
        
        # Mock market sell order for food
        sell_order = Mock()
        sell_order.price = 5
        sell_order.actor = "different_actor"  # Not our actor
        sell_order.timestamp = 0
        
        mock_actor.planet.market.sell_orders = {mock_food_commodity: [sell_order]}
        mock_actor.planet.market.get_actor_orders.return_value = {"buy": [], "sell": []}
        mock_actor.sim.commodity_registry.get_commodity.return_value = mock_food_commodity
        
        commands = brain.decide_market_actions(mock_actor)
        
        # Should have a buy command for food
        buy_commands = [cmd for cmd in commands if isinstance(cmd, PlaceBuyOrderCommand)]
        assert len(buy_commands) > 0
        
        food_buy_command = next((cmd for cmd in buy_commands if cmd.commodity_type == mock_food_commodity), None)
        assert food_buy_command is not None
        assert food_buy_command.quantity == 3  # Need 3 more to reach target of 6
        assert food_buy_command.price == 5

    def test_recipe_viability_considers_planet_attributes(self, brain, mock_actor):
        """Test that recipe viability considers planet resource attributes."""
        from spacesim2.core.process import ResourceAttribute

        # Create mock commodity for a gathering process
        output_commodity = Mock()
        output_commodity.id = "biomass"

        # Create a gathering process with resource_attribute
        process = Mock(spec=ProcessDefinition)
        process.inputs = {}  # Gathering process - no inputs
        process.outputs = {output_commodity: 4}  # Produces 4 biomass
        process.resource_attribute = ResourceAttribute(commodity="biomass", effect="output")

        market = mock_actor.planet.market
        market.get_bid_ask_spread.return_value = (None, None)
        market.get_avg_price.return_value = 10  # Biomass sells for 10 each

        # Test with good planet attributes (biomass = 0.9)
        mock_actor.planet.attributes = Mock()
        mock_actor.planet.attributes.get_availability.return_value = 0.9

        # Expected output: 4 * 0.9 = 3.6, value = 3.6 * 10 = 36
        score_good = brain._calculate_recipe_score(mock_actor, market, process)
        assert score_good > 0
        assert score_good == pytest.approx(36.0, rel=0.01)

        # Test with poor planet attributes (biomass = 0.2)
        mock_actor.planet.attributes.get_availability.return_value = 0.2

        # Expected output: 4 * 0.2 = 0.8, value = 0.8 * 10 = 8
        score_poor = brain._calculate_recipe_score(mock_actor, market, process)
        assert score_poor > 0
        assert score_poor == pytest.approx(8.0, rel=0.01)

        # Good planet should have much higher score
        assert score_good > score_poor * 4

    def test_recipe_selection_prefers_profitable_recipes(self, brain, mock_actor):
        """Test that recipe selection weights by profitability."""
        from spacesim2.core.process import ResourceAttribute

        # Create two gathering processes
        biomass_commodity = Mock()
        biomass_commodity.id = "biomass"
        fiber_commodity = Mock()
        fiber_commodity.id = "fiber"

        biomass_process = Mock(spec=ProcessDefinition)
        biomass_process.id = "gather_biomass"
        biomass_process.inputs = {}
        biomass_process.outputs = {biomass_commodity: 4}
        biomass_process.resource_attribute = ResourceAttribute(commodity="biomass", effect="output")

        fiber_process = Mock(spec=ProcessDefinition)
        fiber_process.id = "gather_fiber"
        fiber_process.inputs = {}
        fiber_process.outputs = {fiber_commodity: 3}
        fiber_process.resource_attribute = ResourceAttribute(commodity="fiber", effect="output")

        mock_actor.sim.process_registry.all_processes.return_value = [biomass_process, fiber_process]

        market = mock_actor.planet.market
        market.get_bid_ask_spread.return_value = (None, None)
        market.get_avg_price.return_value = 10  # Both sell for 10

        # Planet is great for biomass, poor for fiber
        def get_availability(commodity_id):
            if commodity_id == "biomass":
                return 0.9
            if commodity_id == "fiber":
                return 0.1
            return 1.0

        mock_actor.planet.attributes = Mock()
        mock_actor.planet.attributes.get_availability.side_effect = get_availability

        # Run recipe selection many times to check bias
        import random
        random.seed(42)

        selections = {"gather_biomass": 0, "gather_fiber": 0}
        for _ in range(100):
            recipe = brain._select_new_recipe(mock_actor)
            if recipe:
                selections[recipe] += 1

        # Biomass should be selected much more often (9x score advantage)
        assert selections["gather_biomass"] > selections["gather_fiber"] * 3