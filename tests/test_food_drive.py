"""Unit tests for the FoodDrive module."""

from unittest.mock import Mock

import pytest

from spacesim2.core.actor import Actor, ActorType
from spacesim2.core.commodity import CommodityRegistry, Inventory
from spacesim2.core.drives.food_drive import (
    DAILY_CONSUMPTION,
    DEBT_DECAY_FACTOR,
    DEBT_MISS_PENALTY,
    PANTRY_MAX,
    PANTRY_TARGET,
    FoodDrive,
    FoodDriveMetrics,
)


class TestFoodDriveMetrics:
    """FoodDriveMetrics."""

    def test_get_name(self):
        """get_name returns food."""
        metrics = FoodDriveMetrics(health=1.0, debt=0.0, buffer=0.0, urgency=1.0)
        assert metrics.get_name() == "food"

    def test_get_score_no_debt(self):
        """Score with no debt is 1.0."""
        metrics = FoodDriveMetrics(health=1.0, debt=0.0, buffer=0.5, urgency=1.0)
        assert metrics.get_score() == 1.0

    def test_get_score_full_debt(self):
        """Score with full debt is 0.0."""
        metrics = FoodDriveMetrics(health=0.0, debt=1.0, buffer=0.0, urgency=1.0)
        assert metrics.get_score() == 0.0

    def test_get_score_partial_debt(self):
        """Score is 1 minus debt."""
        metrics = FoodDriveMetrics(health=0.5, debt=0.3, buffer=0.5, urgency=1.0)
        assert metrics.get_score() == 0.7


class TestFoodDriveInitialization:
    """FoodDrive construction."""

    @pytest.fixture
    def commodity_registry(self):
        """Registry loaded from data/commodities.yaml."""
        registry = CommodityRegistry()
        registry.load_from_file("data/commodities.yaml")
        return registry

    def test_initialization(self, commodity_registry):
        """A new drive resolves the food commodity and starts healthy."""
        drive = FoodDrive(commodity_registry)

        assert drive.food_commodity is not None
        assert drive.food_commodity.id == "food"
        assert isinstance(drive.metrics, FoodDriveMetrics)
        assert drive.metrics.health == 1.0
        assert drive.metrics.debt == 0.0


class TestFoodDriveTick:
    """FoodDrive.tick() behavior."""

    @pytest.fixture
    def commodity_registry(self):
        """Registry loaded from data/commodities.yaml."""
        registry = CommodityRegistry()
        registry.load_from_file("data/commodities.yaml")
        return registry

    @pytest.fixture
    def food_drive(self, commodity_registry):
        """FoodDrive instance."""
        return FoodDrive(commodity_registry)

    @pytest.fixture
    def mock_actor(self, commodity_registry):
        """Mock actor with a real inventory."""
        actor = Mock()
        actor.inventory = Inventory()
        actor.food_consumed_this_turn = False
        return actor

    def test_tick_consumes_food_when_available(
        self, food_drive, mock_actor, commodity_registry
    ):
        """tick() consumes DAILY_CONSUMPTION food when the actor has food."""
        food = commodity_registry.get_commodity("food")
        mock_actor.inventory.add_commodity(food, 5)

        initial_food = mock_actor.inventory.get_quantity(food)
        assert initial_food == 5

        food_drive.tick(mock_actor)

        final_food = mock_actor.inventory.get_quantity(food)
        assert final_food == 5 - DAILY_CONSUMPTION
        assert mock_actor.food_consumed_this_turn is True

    def test_tick_sets_food_consumed_flag_true_when_ate(
        self, food_drive, mock_actor, commodity_registry
    ):
        """food_consumed_this_turn becomes True after eating."""
        food = commodity_registry.get_commodity("food")
        mock_actor.inventory.add_commodity(food, 1)

        assert mock_actor.food_consumed_this_turn is False

        food_drive.tick(mock_actor)

        assert mock_actor.food_consumed_this_turn is True

    def test_tick_sets_food_consumed_flag_false_when_no_food(
        self, food_drive, mock_actor
    ):
        """food_consumed_this_turn becomes False when there is no food."""
        mock_actor.food_consumed_this_turn = True

        food_drive.tick(mock_actor)

        assert mock_actor.food_consumed_this_turn is False

    def test_tick_updates_health_when_ate(
        self, food_drive, mock_actor, commodity_registry
    ):
        """Health is 1.0 after eating."""
        food = commodity_registry.get_commodity("food")
        mock_actor.inventory.add_commodity(food, 1)

        metrics = food_drive.tick(mock_actor)

        assert metrics.health == 1.0

    def test_tick_updates_health_when_did_not_eat(self, food_drive, mock_actor):
        """Health is 0.0 when there is no food."""
        metrics = food_drive.tick(mock_actor)

        assert metrics.health == 0.0

    def test_tick_accumulates_debt_when_not_eating(self, food_drive, mock_actor):
        """Each missed meal sets debt to debt * decay + penalty."""
        food_drive.tick(mock_actor)
        debt_after_one_miss = food_drive.metrics.debt

        assert debt_after_one_miss == DEBT_MISS_PENALTY

        food_drive.tick(mock_actor)
        debt_after_two_misses = food_drive.metrics.debt

        expected = debt_after_one_miss * DEBT_DECAY_FACTOR + DEBT_MISS_PENALTY
        assert abs(debt_after_two_misses - expected) < 0.001

    def test_tick_decays_debt_when_eating(
        self, food_drive, mock_actor, commodity_registry
    ):
        """Eating decays debt by DEBT_DECAY_FACTOR with no penalty."""
        food_drive.tick(mock_actor)  # miss a meal
        initial_debt = food_drive.metrics.debt
        assert initial_debt > 0

        food = commodity_registry.get_commodity("food")
        mock_actor.inventory.add_commodity(food, 1)
        food_drive.tick(mock_actor)

        expected_debt = initial_debt * DEBT_DECAY_FACTOR
        assert abs(food_drive.metrics.debt - expected_debt) < 0.001

    def test_tick_updates_buffer_based_on_pantry(
        self, food_drive, mock_actor, commodity_registry
    ):
        """Buffer is positive at the pantry target and does not fall with more food."""
        food = commodity_registry.get_commodity("food")

        mock_actor.inventory.add_commodity(food, int(PANTRY_TARGET))
        food_drive.tick(mock_actor)
        buffer_with_target = food_drive.metrics.buffer

        assert buffer_with_target > 0

        mock_actor.inventory.add_commodity(food, int(PANTRY_MAX - PANTRY_TARGET))
        food_drive.tick(mock_actor)
        buffer_with_max = food_drive.metrics.buffer

        assert buffer_with_max >= buffer_with_target

    def test_tick_buffer_zero_when_no_food_remaining(
        self, food_drive, mock_actor, commodity_registry
    ):
        """Buffer is 0 when eating leaves no food."""
        food = commodity_registry.get_commodity("food")
        mock_actor.inventory.add_commodity(
            food, DAILY_CONSUMPTION
        )  # enough for one meal

        food_drive.tick(mock_actor)

        assert food_drive.metrics.buffer == 0.0

    def test_tick_returns_metrics(self, food_drive, mock_actor, commodity_registry):
        """tick() returns the drive's own metrics object."""
        food = commodity_registry.get_commodity("food")
        mock_actor.inventory.add_commodity(food, 10)

        result = food_drive.tick(mock_actor)

        assert isinstance(result, FoodDriveMetrics)
        assert result is food_drive.metrics


class TestFoodDriveIntegration:
    """FoodDrive with a real Actor."""

    @pytest.fixture
    def simulation(self):
        """Minimal simulation stand-in with a registry and data logger."""
        from spacesim2.core.data_logger import DataLogger

        registry = CommodityRegistry()
        registry.load_from_file("data/commodities.yaml")
        sim = Mock()
        sim.commodity_registry = registry
        sim.data_logger = DataLogger()
        return sim

    def test_food_consumed_flag_updated_during_actor_turn(self, simulation):
        """take_turn() updates actor.food_consumed_this_turn."""
        food_drive = FoodDrive(simulation.commodity_registry)

        actor = Actor(
            name="TestActor",
            sim=simulation,
            actor_type=ActorType.REGULAR,
            drives=[food_drive],
            brain=Mock(
                decide_economic_action=lambda _: None,
                decide_market_actions=lambda _: [],
            ),
            planet=None,
            initial_money=50,
            initial_skills={},
        )

        assert actor.food_consumed_this_turn is False

        actor.take_turn()

        assert actor.food_consumed_this_turn is False

        food = simulation.commodity_registry.get_commodity("food")
        actor.inventory.add_commodity(food, 5)

        actor.take_turn()

        assert actor.food_consumed_this_turn is True

    def test_multiple_turns_consumption(self, simulation):
        """Three food units feed three turns, then the actor goes hungry."""
        food_drive = FoodDrive(simulation.commodity_registry)
        food = simulation.commodity_registry.get_commodity("food")

        actor = Actor(
            name="TestActor",
            sim=simulation,
            actor_type=ActorType.REGULAR,
            drives=[food_drive],
            brain=Mock(
                decide_economic_action=lambda _: None,
                decide_market_actions=lambda _: [],
            ),
            planet=None,
            initial_money=50,
            initial_skills={},
        )

        actor.inventory.add_commodity(food, 3)

        actor.take_turn()
        assert actor.food_consumed_this_turn is True
        assert actor.inventory.get_quantity(food) == 2

        actor.take_turn()
        assert actor.food_consumed_this_turn is True
        assert actor.inventory.get_quantity(food) == 1

        actor.take_turn()
        assert actor.food_consumed_this_turn is True
        assert actor.inventory.get_quantity(food) == 0

        actor.take_turn()
        assert actor.food_consumed_this_turn is False
        assert actor.inventory.get_quantity(food) == 0


class TestFoodDriveConstants:
    """FoodDrive constants."""

    def test_daily_consumption_is_positive(self):
        """Daily consumption is positive."""
        assert DAILY_CONSUMPTION > 0

    def test_debt_stays_bounded(self):
        """Decay and penalty keep debt at or below 1.0."""
        # The fixed point of debt = debt * decay + penalty is
        # penalty / (1 - decay), which is <= 1 iff decay + penalty <= 1.
        assert DEBT_DECAY_FACTOR + DEBT_MISS_PENALTY <= 1.0

    def test_pantry_target_less_than_max(self):
        """Pantry target is below the max."""
        assert PANTRY_TARGET < PANTRY_MAX
