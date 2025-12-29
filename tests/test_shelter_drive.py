"""Unit tests for the ShelterDrive module."""

import pytest
from unittest.mock import Mock, patch
import random

from spacesim2.core.drives.shelter_drive import (
    ShelterDrive,
    BASE_EVENT_PROB,
    DEBT_DECAY_FACTOR,
    DEBT_MISS_PENALTY,
    BUFFER_TARGET_DAYS,
    BUFFER_MAX_DAYS,
    URGENCY,
    WOOD_NAME,
    COMMON_METAL_NAME,
)
from spacesim2.core.drives.actor_drive import DriveMetrics
from spacesim2.core.commodity import CommodityRegistry, CommodityDefinition
from tests.helpers import get_actor


class TestShelterDriveConstants:
    """Test the constants and configuration of ShelterDrive."""

    def test_constants_are_reasonable(self):
        """Test that the constants have reasonable values."""
        assert 0 < BASE_EVENT_PROB < 1
        assert 0 < DEBT_DECAY_FACTOR < 1
        assert 0 < DEBT_MISS_PENALTY <= 1
        assert BUFFER_TARGET_DAYS > 0
        assert BUFFER_MAX_DAYS > BUFFER_TARGET_DAYS
        assert URGENCY > 0
        assert WOOD_NAME == "wood"
        assert COMMON_METAL_NAME == "common_metal"


class TestShelterDrive:
    """Test the ShelterDrive class."""

    @pytest.fixture
    def mock_commodity_registry(self):
        """Create a mock commodity registry with wood and metal."""
        registry = Mock(spec=CommodityRegistry)

        # Create mock commodities
        wood_commodity = Mock()
        wood_commodity.id = WOOD_NAME
        wood_commodity.name = "Wood"

        metal_commodity = Mock()
        metal_commodity.id = COMMON_METAL_NAME
        metal_commodity.name = "Common Metal"

        # Setup registry to return appropriate commodity
        def get_commodity(name):
            if name == WOOD_NAME:
                return wood_commodity
            elif name == COMMON_METAL_NAME:
                return metal_commodity
            raise ValueError(f"Unknown commodity: {name}")

        registry.get_commodity.side_effect = get_commodity
        return registry

    @pytest.fixture
    def shelter_drive(self, mock_commodity_registry):
        """Create a ShelterDrive instance."""
        return ShelterDrive(mock_commodity_registry)

    @pytest.fixture
    def mock_actor(self):
        """Create a mock actor with inventory."""
        actor = get_actor("TestActor")
        # Mock the inventory methods
        actor.inventory.remove_commodity = Mock(return_value=True)
        actor.inventory.get_available_quantity = Mock(return_value=0)
        return actor

    def test_initialization(self, shelter_drive, mock_commodity_registry):
        """Test ShelterDrive initialization."""
        assert isinstance(shelter_drive.metrics, DriveMetrics)
        assert shelter_drive.metrics.health == 1.0
        assert shelter_drive.metrics.debt == 0.0
        assert shelter_drive.metrics.buffer == 0.0
        assert shelter_drive.metrics.urgency == URGENCY

        # Verify both commodities were requested
        assert mock_commodity_registry.get_commodity.call_count == 2

    @patch('random.random')
    def test_tick_no_event(self, mock_random, shelter_drive, mock_actor):
        """Test tick when no maintenance event occurs."""
        mock_random.return_value = 0.9  # High value, no event

        # Setup inventory - has wood
        def get_qty(commodity):
            if commodity.id == WOOD_NAME:
                return 5
            return 0
        mock_actor.inventory.get_available_quantity.side_effect = get_qty

        # Set initial debt to test decay
        shelter_drive.metrics.debt = 0.5

        result = shelter_drive.tick(mock_actor)

        # Has materials, so health = 1.0
        assert result.health == 1.0

        # Debt should decay when inventory > 0
        expected_debt_decay = 0.5 * DEBT_DECAY_FACTOR
        assert abs(result.debt - expected_debt_decay) < 1e-6

        # Should not attempt to remove commodity
        mock_actor.inventory.remove_commodity.assert_not_called()

    @patch('random.random')
    def test_tick_event_successful_maintenance_wood(self, mock_random, shelter_drive, mock_actor):
        """Test tick when maintenance event occurs and wood is used."""
        mock_random.return_value = 0.001  # Low value, event occurs
        mock_actor.inventory.remove_commodity.return_value = True

        # Setup inventory - has wood, no metal
        call_count = [0]
        def get_qty(commodity):
            call_count[0] += 1
            # First calls check what's available
            if call_count[0] <= 2:
                if commodity.id == WOOD_NAME:
                    return 5
                return 0
            # After consumption, wood is reduced
            if commodity.id == WOOD_NAME:
                return 4
            return 0

        mock_actor.inventory.get_available_quantity.side_effect = get_qty

        # Set initial debt
        initial_debt = 0.3
        shelter_drive.metrics.debt = initial_debt

        result = shelter_drive.tick(mock_actor)

        # Successful maintenance should mean health = 1.0
        assert result.health == 1.0

        # Debt should only decay (no penalty added)
        expected_debt = initial_debt * DEBT_DECAY_FACTOR
        assert abs(result.debt - expected_debt) < 1e-6

        # Should attempt to remove wood commodity
        mock_actor.inventory.remove_commodity.assert_called_once()
        call_args = mock_actor.inventory.remove_commodity.call_args
        assert call_args[0][0].id == WOOD_NAME
        assert call_args[0][1] == 1

    @patch('random.random')
    def test_tick_event_failed_maintenance(self, mock_random, shelter_drive, mock_actor):
        """Test tick when maintenance event occurs but fails (no inventory)."""
        mock_random.return_value = 0.001  # Low value, event occurs
        mock_actor.inventory.remove_commodity.return_value = False

        # No inventory
        mock_actor.inventory.get_available_quantity.return_value = 0

        # Set initial debt
        initial_debt = 0.2
        shelter_drive.metrics.debt = initial_debt

        result = shelter_drive.tick(mock_actor)

        # Failed maintenance should mean health = 0.0
        assert result.health == 0.0

        # Debt should decay and add penalty
        expected_debt = min(1.0, initial_debt * DEBT_DECAY_FACTOR + DEBT_MISS_PENALTY)
        assert abs(result.debt - expected_debt) < 1e-6

    def test_choose_material_only_wood(self, shelter_drive, mock_actor):
        """Test material choice when only wood is available."""
        material = shelter_drive._choose_material(mock_actor, wood_qty=5, metal_qty=0)
        assert material.id == WOOD_NAME

    def test_choose_material_only_metal(self, shelter_drive, mock_actor):
        """Test material choice when only metal is available."""
        material = shelter_drive._choose_material(mock_actor, wood_qty=0, metal_qty=5)
        assert material.id == COMMON_METAL_NAME

    def test_choose_material_neither(self, shelter_drive, mock_actor):
        """Test material choice when neither is available."""
        material = shelter_drive._choose_material(mock_actor, wood_qty=0, metal_qty=0)
        assert material is None

    def test_choose_material_both_prefer_cheaper(self, shelter_drive, mock_actor):
        """Test material choice prefers cheaper option when both available."""
        # Setup mock market
        mock_market = Mock()
        mock_market.get_avg_price.side_effect = lambda c: 10.0 if c.id == WOOD_NAME else 20.0
        mock_actor.planet = Mock()
        mock_actor.planet.market = mock_market

        material = shelter_drive._choose_material(mock_actor, wood_qty=5, metal_qty=5)
        assert material.id == WOOD_NAME  # Wood is cheaper

        # Test reverse
        mock_market.get_avg_price.side_effect = lambda c: 30.0 if c.id == WOOD_NAME else 15.0
        material = shelter_drive._choose_material(mock_actor, wood_qty=5, metal_qty=5)
        assert material.id == COMMON_METAL_NAME  # Metal is cheaper

    def test_choose_material_both_no_market(self, shelter_drive, mock_actor):
        """Test material choice defaults to wood when no market data."""
        mock_actor.planet = None

        material = shelter_drive._choose_material(mock_actor, wood_qty=5, metal_qty=5)
        assert material.id == WOOD_NAME  # Default to wood

    def test_buffer_calculation(self, shelter_drive, mock_actor):
        """Test buffer calculation based on combined inventory."""
        # Setup inventory with both wood and metal
        def get_qty(commodity):
            if commodity.id == WOOD_NAME:
                return 50
            elif commodity.id == COMMON_METAL_NAME:
                return 50
            return 0

        mock_actor.inventory.get_available_quantity.side_effect = get_qty

        with patch('random.random', return_value=0.9):  # No event
            result = shelter_drive.tick(mock_actor)

        # Buffer should be based on total 100 units
        # Calculate expected buffer using log_norm_ratio
        from spacesim2.core.drives.actor_drive import log_norm_ratio
        total_units = 100
        expected_coverage_days = total_units / BASE_EVENT_PROB
        expected_buffer = log_norm_ratio(expected_coverage_days, BUFFER_TARGET_DAYS, BUFFER_MAX_DAYS)

        assert abs(result.buffer - expected_buffer) < 1e-6

    def test_buffer_with_zero_inventory(self, shelter_drive, mock_actor):
        """Test buffer calculation with zero inventory."""
        mock_actor.inventory.get_available_quantity.return_value = 0

        with patch('random.random', return_value=0.9):  # No event
            result = shelter_drive.tick(mock_actor)

        # Zero inventory should give zero buffer
        assert result.buffer == 0.0

    def test_debt_no_decay_without_inventory(self, shelter_drive, mock_actor):
        """Test that debt doesn't decay when no inventory and no event."""
        mock_actor.inventory.get_available_quantity.return_value = 0

        # Set initial debt
        initial_debt = 0.6
        shelter_drive.metrics.debt = initial_debt

        with patch('random.random', return_value=0.9):  # No event
            result = shelter_drive.tick(mock_actor)

        # Debt should not decay when no inventory
        assert result.debt == initial_debt

    def test_get_current_score(self, shelter_drive):
        """Test the get_current_score method."""
        # Set specific metrics
        shelter_drive.metrics.debt = 0.3

        score = shelter_drive.get_current_score()

        # Score should be 1 - debt
        expected_score = 1.0 - 0.3
        assert score == expected_score

    def test_get_current_score_edge_cases(self, shelter_drive):
        """Test get_current_score with edge cases."""
        # Test with maximum debt
        shelter_drive.metrics.debt = 1.0
        score = shelter_drive.get_current_score()
        assert score == 0.0

        # Test with zero debt
        shelter_drive.metrics.debt = 0.0
        score = shelter_drive.get_current_score()
        assert score == 1.0


class TestShelterDriveIntegration:
    """Integration tests for ShelterDrive with real components."""

    @pytest.fixture
    def real_registry(self):
        """Create a real commodity registry with wood and metal."""
        registry = CommodityRegistry()

        wood_def = CommodityDefinition(
            id=WOOD_NAME,
            name="Wood",
            transportable=True,
            description="Timber for shelter construction"
        )
        registry.add_commodity(wood_def)

        metal_def = CommodityDefinition(
            id=COMMON_METAL_NAME,
            name="Common Metal",
            transportable=True,
            description="Metal for shelter construction"
        )
        registry.add_commodity(metal_def)

        return registry

    def test_with_real_commodity_registry(self, real_registry):
        """Test ShelterDrive with a real CommodityRegistry."""
        drive = ShelterDrive(real_registry)
        assert drive.wood_commodity.id == WOOD_NAME
        assert drive.metal_commodity.id == COMMON_METAL_NAME

    def test_multiple_ticks_debt_accumulation(self, real_registry):
        """Test debt accumulation over multiple ticks with failed maintenance."""
        drive = ShelterDrive(real_registry)
        actor = get_actor("TestActor")

        # Ensure actor has no shelter materials
        actor.inventory.get_available_quantity = Mock(return_value=0)
        actor.inventory.remove_commodity = Mock(return_value=False)

        # Force events to occur
        with patch('random.random', return_value=0.001):
            debt_progression = []
            for _ in range(5):
                result = drive.tick(actor)
                debt_progression.append(result.debt)

        # Debt should increase over time with failed maintenance
        assert debt_progression[-1] > 0
        # All debt values should be in valid range
        assert all(0 <= debt <= 1 for debt in debt_progression)

    def test_mixed_inventory_consumption(self, real_registry):
        """Test that drive correctly handles mixed wood/metal inventory."""
        drive = ShelterDrive(real_registry)
        actor = get_actor("TestActor")

        # Add both wood and metal to inventory
        wood = real_registry.get_commodity(WOOD_NAME)
        metal = real_registry.get_commodity(COMMON_METAL_NAME)
        actor.inventory.add_commodity(wood, 10)
        actor.inventory.add_commodity(metal, 10)

        # Force event
        with patch('random.random', return_value=0.001):
            result = drive.tick(actor)

        # Should have successfully maintained
        assert result.health == 1.0
        assert result.debt < 1.0

        # One of the materials should have been consumed
        total_remaining = actor.inventory.get_available_quantity(wood) + \
                         actor.inventory.get_available_quantity(metal)
        assert total_remaining == 19  # Started with 20, consumed 1


class TestShelterDriveStochastic:
    """Test stochastic behavior of ShelterDrive."""

    @pytest.fixture
    def setup_drive_and_actor(self):
        """Setup drive and actor for stochastic tests."""
        registry = CommodityRegistry()

        wood_def = CommodityDefinition(
            id=WOOD_NAME,
            name="Wood",
            transportable=True,
            description="Timber for shelter"
        )
        registry.add_commodity(wood_def)

        metal_def = CommodityDefinition(
            id=COMMON_METAL_NAME,
            name="Common Metal",
            transportable=True,
            description="Metal for shelter"
        )
        registry.add_commodity(metal_def)

        drive = ShelterDrive(registry)
        actor = get_actor("TestActor")

        return drive, actor

    def test_event_probability_distribution(self, setup_drive_and_actor):
        """Test that events occur with approximately correct probability."""
        drive, actor = setup_drive_and_actor
        actor.inventory.get_available_quantity = Mock(return_value=100)
        actor.inventory.remove_commodity = Mock(return_value=True)

        # Run many simulations
        num_trials = 1000
        events_occurred = 0

        # Reset random seed for reproducibility
        random.seed(42)

        for _ in range(num_trials):
            drive.tick(actor)

            # If remove_commodity was called, an event occurred
            if actor.inventory.remove_commodity.called:
                events_occurred += 1
                actor.inventory.remove_commodity.reset_mock()

        expected_events = num_trials * BASE_EVENT_PROB

        # Allow for some variance (within 3 standard deviations)
        # For binomial distribution: std = sqrt(n * p * (1-p))
        p = BASE_EVENT_PROB
        std_dev = (num_trials * p * (1 - p)) ** 0.5

        assert abs(events_occurred - expected_events) < 3 * std_dev

    def test_metrics_bounds_over_time(self, setup_drive_and_actor):
        """Test that all metrics stay within valid bounds over many ticks."""
        drive, actor = setup_drive_and_actor

        # Vary inventory randomly
        random.seed(123)
        for _ in range(100):
            inventory_level = random.randint(0, 50)
            actor.inventory.get_available_quantity = Mock(return_value=inventory_level)
            actor.inventory.remove_commodity = Mock(return_value=inventory_level > 0)

            result = drive.tick(actor)

            # All metrics should be in valid range
            assert 0 <= result.health <= 1
            assert 0 <= result.debt <= 1
            assert 0 <= result.buffer <= 1
            assert result.urgency == URGENCY
