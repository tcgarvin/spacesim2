"""Unit tests for the FoodDrive module."""

import pytest
from unittest.mock import Mock, MagicMock

from spacesim2.core.drives.food_drive import (
    FoodDrive,
    FoodDriveMetrics,
    DAILY_CONSUMPTION,
    DEBT_DECAY_FACTOR,
    DEBT_MISS_PENALTY,
    PANTRY_TARGET,
    PANTRY_MAX,
)
from spacesim2.core.commodity import CommodityRegistry, CommodityDefinition, Inventory
from spacesim2.core.actor import Actor, ActorType
from tests.helpers import get_actor


class TestFoodDriveMetrics:
    """Test the FoodDriveMetrics class."""

    def test_get_name(self):
        """Test that the metrics name is 'food'."""
        metrics = FoodDriveMetrics(health=1.0, debt=0.0, buffer=0.0, urgency=1.0)
        assert metrics.get_name() == "food"

    def test_get_score_no_debt(self):
        """Test score with no debt is 1.0."""
        metrics = FoodDriveMetrics(health=1.0, debt=0.0, buffer=0.5, urgency=1.0)
        assert metrics.get_score() == 1.0

    def test_get_score_full_debt(self):
        """Test score with full debt is 0.0."""
        metrics = FoodDriveMetrics(health=0.0, debt=1.0, buffer=0.0, urgency=1.0)
        assert metrics.get_score() == 0.0

    def test_get_score_partial_debt(self):
        """Test score with partial debt."""
        metrics = FoodDriveMetrics(health=0.5, debt=0.3, buffer=0.5, urgency=1.0)
        assert metrics.get_score() == 0.7


class TestFoodDriveInitialization:
    """Test FoodDrive initialization."""

    @pytest.fixture
    def commodity_registry(self):
        """Create a commodity registry with food commodity."""
        registry = CommodityRegistry()
        registry.load_from_file("data/commodities.yaml")
        return registry

    def test_initialization(self, commodity_registry):
        """Test FoodDrive initializes correctly."""
        drive = FoodDrive(commodity_registry)

        assert drive.food_commodity is not None
        assert drive.food_commodity.id == "food"
        assert isinstance(drive.metrics, FoodDriveMetrics)
        assert drive.metrics.health == 1.0
        assert drive.metrics.debt == 0.0


class TestFoodDriveTick:
    """Test FoodDrive.tick() behavior."""

    @pytest.fixture
    def commodity_registry(self):
        """Create a commodity registry with food commodity."""
        registry = CommodityRegistry()
        registry.load_from_file("data/commodities.yaml")
        return registry

    @pytest.fixture
    def food_drive(self, commodity_registry):
        """Create a FoodDrive instance."""
        return FoodDrive(commodity_registry)

    @pytest.fixture
    def mock_actor(self, commodity_registry):
        """Create a mock actor with inventory for testing."""
        actor = Mock()
        actor.inventory = Inventory()
        actor.food_consumed_this_turn = False
        return actor

    def test_tick_consumes_food_when_available(self, food_drive, mock_actor, commodity_registry):
        """Test that tick() consumes food when actor has food."""
        food = commodity_registry.get_commodity("food")
        mock_actor.inventory.add_commodity(food, 5)

        initial_food = mock_actor.inventory.get_quantity(food)
        assert initial_food == 5

        food_drive.tick(mock_actor)

        final_food = mock_actor.inventory.get_quantity(food)
        assert final_food == 5 - DAILY_CONSUMPTION
        assert mock_actor.food_consumed_this_turn is True

    def test_tick_sets_food_consumed_flag_true_when_ate(self, food_drive, mock_actor, commodity_registry):
        """Test that food_consumed_this_turn is set to True when food is consumed."""
        food = commodity_registry.get_commodity("food")
        mock_actor.inventory.add_commodity(food, 1)

        assert mock_actor.food_consumed_this_turn is False

        food_drive.tick(mock_actor)

        assert mock_actor.food_consumed_this_turn is True

    def test_tick_sets_food_consumed_flag_false_when_no_food(self, food_drive, mock_actor):
        """Test that food_consumed_this_turn is set to False when no food available."""
        mock_actor.food_consumed_this_turn = True  # Start with True

        food_drive.tick(mock_actor)

        assert mock_actor.food_consumed_this_turn is False

    def test_tick_updates_health_when_ate(self, food_drive, mock_actor, commodity_registry):
        """Test that health metric is 1.0 when food was consumed."""
        food = commodity_registry.get_commodity("food")
        mock_actor.inventory.add_commodity(food, 1)

        metrics = food_drive.tick(mock_actor)

        assert metrics.health == 1.0

    def test_tick_updates_health_when_did_not_eat(self, food_drive, mock_actor):
        """Test that health metric is 0.0 when no food available."""
        metrics = food_drive.tick(mock_actor)

        assert metrics.health == 0.0

    def test_tick_accumulates_debt_when_not_eating(self, food_drive, mock_actor):
        """Test that debt accumulates when actor doesn't eat."""
        # First tick without food - debt should increase
        food_drive.tick(mock_actor)
        debt_after_one_miss = food_drive.metrics.debt

        # Should have penalty but no decay (starting from 0)
        assert debt_after_one_miss == DEBT_MISS_PENALTY

        # Second tick without food - debt should accumulate
        food_drive.tick(mock_actor)
        debt_after_two_misses = food_drive.metrics.debt

        # Should be previous debt * decay + penalty
        expected = debt_after_one_miss * DEBT_DECAY_FACTOR + DEBT_MISS_PENALTY
        assert abs(debt_after_two_misses - expected) < 0.001

    def test_tick_decays_debt_when_eating(self, food_drive, mock_actor, commodity_registry):
        """Test that debt decays when actor eats."""
        # First, accumulate some debt
        food_drive.tick(mock_actor)  # Miss a meal
        initial_debt = food_drive.metrics.debt
        assert initial_debt > 0

        # Now eat - debt should decay
        food = commodity_registry.get_commodity("food")
        mock_actor.inventory.add_commodity(food, 1)
        food_drive.tick(mock_actor)

        # Debt should decay without penalty
        expected_debt = initial_debt * DEBT_DECAY_FACTOR
        assert abs(food_drive.metrics.debt - expected_debt) < 0.001

    def test_tick_updates_buffer_based_on_pantry(self, food_drive, mock_actor, commodity_registry):
        """Test that buffer metric reflects pantry days."""
        food = commodity_registry.get_commodity("food")

        # Add plenty of food
        mock_actor.inventory.add_commodity(food, int(PANTRY_TARGET))
        food_drive.tick(mock_actor)
        buffer_with_target = food_drive.metrics.buffer

        # Buffer should be positive when we have target days of food
        assert buffer_with_target > 0

        # Add more food up to max
        mock_actor.inventory.add_commodity(food, int(PANTRY_MAX - PANTRY_TARGET))
        food_drive.tick(mock_actor)
        buffer_with_max = food_drive.metrics.buffer

        # Buffer should be higher with more food
        assert buffer_with_max >= buffer_with_target

    def test_tick_buffer_zero_when_no_food_remaining(self, food_drive, mock_actor, commodity_registry):
        """Test that buffer is 0 when no food remains after eating."""
        food = commodity_registry.get_commodity("food")
        mock_actor.inventory.add_commodity(food, DAILY_CONSUMPTION)  # Exactly enough for one meal

        food_drive.tick(mock_actor)

        # After eating, no food remains, buffer should be 0
        assert food_drive.metrics.buffer == 0.0

    def test_tick_returns_metrics(self, food_drive, mock_actor, commodity_registry):
        """Test that tick() returns the updated metrics."""
        food = commodity_registry.get_commodity("food")
        mock_actor.inventory.add_commodity(food, 10)

        result = food_drive.tick(mock_actor)

        assert isinstance(result, FoodDriveMetrics)
        assert result is food_drive.metrics


class TestFoodDriveIntegration:
    """Integration tests for FoodDrive with real Actor."""

    @pytest.fixture
    def simulation(self):
        """Create a minimal simulation-like object."""
        from spacesim2.core.data_logger import DataLogger

        registry = CommodityRegistry()
        registry.load_from_file("data/commodities.yaml")
        sim = Mock()
        sim.commodity_registry = registry
        sim.data_logger = DataLogger()
        return sim

    def test_food_consumed_flag_updated_during_actor_turn(self, simulation):
        """Test that actor.food_consumed_this_turn is updated during take_turn()."""
        food_drive = FoodDrive(simulation.commodity_registry)

        actor = Actor(
            name="TestActor",
            sim=simulation,
            actor_type=ActorType.REGULAR,
            drives=[food_drive],
            brain=Mock(
                decide_economic_action=lambda _: None,
                decide_market_actions=lambda _: []
            ),
            planet=None,
            initial_money=50,
            initial_skills={}
        )

        # Actor starts hungry (no food)
        assert actor.food_consumed_this_turn is False

        actor.take_turn()

        # Still hungry - no food to consume
        assert actor.food_consumed_this_turn is False

        # Give actor food
        food = simulation.commodity_registry.get_commodity("food")
        actor.inventory.add_commodity(food, 5)

        actor.take_turn()

        # Now should have eaten
        assert actor.food_consumed_this_turn is True

    def test_multiple_turns_consumption(self, simulation):
        """Test food consumption over multiple turns."""
        food_drive = FoodDrive(simulation.commodity_registry)
        food = simulation.commodity_registry.get_commodity("food")

        actor = Actor(
            name="TestActor",
            sim=simulation,
            actor_type=ActorType.REGULAR,
            drives=[food_drive],
            brain=Mock(
                decide_economic_action=lambda _: None,
                decide_market_actions=lambda _: []
            ),
            planet=None,
            initial_money=50,
            initial_skills={}
        )

        # Give actor 3 units of food
        actor.inventory.add_commodity(food, 3)

        # Turn 1: Eat, 2 remaining
        actor.take_turn()
        assert actor.food_consumed_this_turn is True
        assert actor.inventory.get_quantity(food) == 2

        # Turn 2: Eat, 1 remaining
        actor.take_turn()
        assert actor.food_consumed_this_turn is True
        assert actor.inventory.get_quantity(food) == 1

        # Turn 3: Eat, 0 remaining
        actor.take_turn()
        assert actor.food_consumed_this_turn is True
        assert actor.inventory.get_quantity(food) == 0

        # Turn 4: No food, go hungry
        actor.take_turn()
        assert actor.food_consumed_this_turn is False
        assert actor.inventory.get_quantity(food) == 0


class TestFoodDriveConstants:
    """Test that FoodDrive constants are sensible."""

    def test_daily_consumption_is_positive(self):
        """Daily consumption should be positive."""
        assert DAILY_CONSUMPTION > 0

    def test_debt_stays_bounded(self):
        """Debt decay and penalty should keep debt <= 1.0."""
        # With decay 0.8 and penalty 0.2, max debt is:
        # debt = debt * 0.8 + 0.2
        # At equilibrium: debt = 0.8 * debt + 0.2
        # 0.2 * debt = 0.2
        # debt = 1.0
        assert DEBT_DECAY_FACTOR + DEBT_MISS_PENALTY <= 1.0

    def test_pantry_target_less_than_max(self):
        """Pantry target should be less than max."""
        assert PANTRY_TARGET < PANTRY_MAX
