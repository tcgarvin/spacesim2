"""Unit tests for the ShelterDrive module."""

import pytest
from unittest.mock import Mock, patch, MagicMock
import random

from spacesim2.core.drives.shelter_drive import (
    ShelterDrive,
    BASE_EVENT_PROB,
    PLANET_STRUCTURE_DECAY,
    PLANET_EXPOSURE_RISK,
    URGENCY_FACTOR,
    DEBT_DECAY_FACTOR,
    DEBT_MISS_PENALTY,
    BUFFER_TARGET_DAYS,
    BUFFER_MAX_DAYS,
    STRUCTURAL_NAME,
    buffer_mapping
)
from spacesim2.core.drives.actor_drive import DriveMetrics
from spacesim2.core.commodity import CommodityRegistry
from tests.helpers import get_actor


class TestShelterDriveConstants:
    """Test the constants and configuration of ShelterDrive."""
    
    def test_constants_are_reasonable(self):
        """Test that the constants have reasonable values."""
        assert 0 < BASE_EVENT_PROB < 1
        assert 0 < PLANET_STRUCTURE_DECAY <= 1
        assert 0 < PLANET_EXPOSURE_RISK <= 1
        assert URGENCY_FACTOR > 0
        assert 0 < DEBT_DECAY_FACTOR < 1
        assert 0 < DEBT_MISS_PENALTY <= 1
        assert BUFFER_TARGET_DAYS > 0
        assert BUFFER_MAX_DAYS > BUFFER_TARGET_DAYS
        assert STRUCTURAL_NAME == "structural_component"
    
    def test_buffer_mapping_function(self):
        """Test the buffer mapping function."""
        # Test key points
        assert buffer_mapping(0) == 0.0
        assert buffer_mapping(BUFFER_TARGET_DAYS) == 0.2
        assert buffer_mapping(BUFFER_MAX_DAYS) == 1.0
        
        # Test intermediate values
        mid_point = (BUFFER_TARGET_DAYS + BUFFER_MAX_DAYS) / 2
        mid_value = buffer_mapping(mid_point)
        assert 0.2 < mid_value < 1.0
        
        # Test out of range values
        assert buffer_mapping(-10) == 0.0  # Below range
        assert buffer_mapping(BUFFER_MAX_DAYS * 2) == 1.0  # Above range


class TestShelterDrive:
    """Test the ShelterDrive class."""
    
    @pytest.fixture
    def mock_commodity_registry(self):
        """Create a mock commodity registry."""
        registry = Mock(spec=CommodityRegistry)
        mock_commodity = Mock()
        mock_commodity.name = STRUCTURAL_NAME
        registry.get_commodity.return_value = mock_commodity
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
        assert shelter_drive.metrics.urgency == 0.0
        
        # Verify commodity was requested
        mock_commodity_registry.get_commodity.assert_called_once_with(STRUCTURAL_NAME)
    
    def test_urgency_calculation(self, shelter_drive):
        """Test that urgency is calculated correctly."""
        expected_urgency = min(1.0, PLANET_EXPOSURE_RISK * URGENCY_FACTOR)
        
        # Since urgency is calculated in tick, we need to call it
        mock_actor = Mock()
        mock_actor.inventory.remove_commodity.return_value = True
        mock_actor.inventory.get_available_quantity.return_value = 0
        
        with patch('random.random', return_value=0.9):  # No event
            shelter_drive.tick(mock_actor)
        
        assert shelter_drive.metrics.urgency == expected_urgency
    
    @patch('random.random')
    def test_tick_no_event(self, mock_random, shelter_drive, mock_actor):
        """Test tick when no maintenance event occurs."""
        mock_random.return_value = 0.9  # High value, no event
        mock_actor.inventory.get_available_quantity.return_value = 5
        
        # Set initial debt to test decay
        shelter_drive.metrics.debt = 0.5
        
        result = shelter_drive.tick(mock_actor)
        
        # No event should mean health = 1.0
        assert result.health == 1.0
        
        # Debt should decay when inventory > 0
        expected_debt_decay = 0.5 * DEBT_DECAY_FACTOR
        assert abs(result.debt - expected_debt_decay) < 1e-6
        
        # Should not attempt to remove commodity
        mock_actor.inventory.remove_commodity.assert_not_called()
    
    @patch('random.random')
    def test_tick_event_successful_maintenance(self, mock_random, shelter_drive, mock_actor):
        """Test tick when maintenance event occurs and is successfully handled."""
        mock_random.return_value = 0.001  # Low value, event occurs
        mock_actor.inventory.remove_commodity.return_value = True  # Successful removal
        mock_actor.inventory.get_available_quantity.return_value = 4  # Remaining after removal
        
        # Set initial debt
        initial_debt = 0.3
        shelter_drive.metrics.debt = initial_debt
        
        result = shelter_drive.tick(mock_actor)
        
        # Successful maintenance should mean health = 1.0
        assert result.health == 1.0
        
        # Debt should only decay (no penalty added)
        expected_debt = initial_debt * DEBT_DECAY_FACTOR
        assert abs(result.debt - expected_debt) < 1e-6
        
        # Should attempt to remove commodity
        mock_actor.inventory.remove_commodity.assert_called_once_with(
            shelter_drive.structural_good, 1
        )
    
    @patch('random.random')
    def test_tick_event_failed_maintenance(self, mock_random, shelter_drive, mock_actor):
        """Test tick when maintenance event occurs but fails (no inventory)."""
        mock_random.return_value = 0.001  # Low value, event occurs
        mock_actor.inventory.remove_commodity.return_value = False  # Failed removal
        mock_actor.inventory.get_available_quantity.return_value = 0
        
        # Set initial debt
        initial_debt = 0.2
        shelter_drive.metrics.debt = initial_debt
        
        result = shelter_drive.tick(mock_actor)
        
        # Failed maintenance should mean health = 0.0
        assert result.health == 0.0
        
        # Debt should decay and add penalty
        urgency01 = min(1.0, PLANET_EXPOSURE_RISK * URGENCY_FACTOR)
        expected_debt = min(1.0, initial_debt * DEBT_DECAY_FACTOR + DEBT_MISS_PENALTY * urgency01)
        assert abs(result.debt - expected_debt) < 1e-6
        
        # Should attempt to remove commodity
        mock_actor.inventory.remove_commodity.assert_called_once_with(
            shelter_drive.structural_good, 1
        )
    
    def test_buffer_calculation(self, shelter_drive, mock_actor):
        """Test buffer calculation based on inventory."""
        mock_actor.inventory.get_available_quantity.return_value = 100
        
        with patch('random.random', return_value=0.9):  # No event
            result = shelter_drive.tick(mock_actor)
        
        # Calculate expected buffer
        p_event = BASE_EVENT_PROB * PLANET_STRUCTURE_DECAY
        exp_events_per_day = max(p_event, 1e-9)
        expected_coverage_days = 100 / exp_events_per_day
        expected_buffer = buffer_mapping(expected_coverage_days)
        
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
        shelter_drive.metrics.buffer = 0.7

        score = shelter_drive.get_current_score()

        # Score should be 1 - debt + buffer, clamped to [0, 1]
        # 1 - 0.3 + 0.7 = 1.4, clamped to 1.0
        expected_score = 1.0
        assert score == expected_score
    
    def test_get_current_score_edge_cases(self, shelter_drive):
        """Test get_current_score with edge cases."""
        # Test with maximum debt and zero buffer
        shelter_drive.metrics.debt = 1.0
        shelter_drive.metrics.buffer = 0.0
        score = shelter_drive.get_current_score()
        assert score == 0.0  # 1 - 1 + 0 = 0

        # Test with zero debt and maximum buffer
        shelter_drive.metrics.debt = 0.0
        shelter_drive.metrics.buffer = 1.0
        score = shelter_drive.get_current_score()
        # 1 - 0 + 1 = 2.0, clamped to 1.0
        assert score == 1.0


class TestShelterDriveIntegration:
    """Integration tests for ShelterDrive with real components."""
    
    def test_with_real_commodity_registry(self):
        """Test ShelterDrive with a real CommodityRegistry."""
        registry = CommodityRegistry()
        # Add the structural component commodity
        from spacesim2.core.commodity import CommodityDefinition
        structural_def = CommodityDefinition(
            id=STRUCTURAL_NAME,
            name="Structural Component",
            transportable=True,
            description="Materials for shelter maintenance"
        )
        registry.add_commodity(structural_def)
        
        drive = ShelterDrive(registry)
        assert drive.structural_good.id == STRUCTURAL_NAME
    
    def test_multiple_ticks_debt_accumulation(self):
        """Test debt accumulation over multiple ticks with failed maintenance."""
        registry = CommodityRegistry()
        from spacesim2.core.commodity import CommodityDefinition
        structural_def = CommodityDefinition(
            id=STRUCTURAL_NAME,
            name="Structural Component", 
            transportable=True,
            description="Materials for shelter maintenance"
        )
        registry.add_commodity(structural_def)
        
        drive = ShelterDrive(registry)
        actor = get_actor("TestActor")
        
        # Ensure actor has no structural components
        actor.inventory.get_available_quantity = Mock(return_value=0)
        actor.inventory.remove_commodity = Mock(return_value=False)
        
        # Force events to occur
        with patch('random.random', return_value=0.001):
            debt_progression = []
            for _ in range(5):
                result = drive.tick(actor)
                debt_progression.append(result.debt)
        
        # Debt should generally increase (may fluctuate due to decay)
        assert debt_progression[-1] > 0
        # All debt values should be in valid range
        assert all(0 <= debt <= 1 for debt in debt_progression)
    
    def test_buffer_mapping_consistency(self):
        """Test that buffer mapping is consistent with expectations."""
        registry = CommodityRegistry()
        from spacesim2.core.commodity import CommodityDefinition
        structural_def = CommodityDefinition(
            id=STRUCTURAL_NAME,
            name="Structural Component",
            transportable=True, 
            description="Materials for shelter maintenance"
        )
        registry.add_commodity(structural_def)
        
        drive = ShelterDrive(registry)
        actor = get_actor("TestActor")
        
        # Test different inventory levels
        inventory_levels = [0, 50, 100, 500, 1000]
        
        with patch('random.random', return_value=0.9):  # No events
            for level in inventory_levels:
                actor.inventory.get_available_quantity = Mock(return_value=level)
                result = drive.tick(actor)
                
                # Buffer should be in valid range
                assert 0 <= result.buffer <= 1
                
                # Higher inventory should generally mean higher buffer
                # (though this may not be strictly true due to the piecewise mapping)
                if level == 0:
                    assert result.buffer == 0


class TestShelterDriveStochastic:
    """Test stochastic behavior of ShelterDrive."""
    
    @pytest.fixture
    def setup_drive_and_actor(self):
        """Setup drive and actor for stochastic tests."""
        registry = CommodityRegistry()
        from spacesim2.core.commodity import CommodityDefinition
        structural_def = CommodityDefinition(
            id=STRUCTURAL_NAME,
            name="Structural Component",
            transportable=True,
            description="Materials for shelter maintenance"
        )
        registry.add_commodity(structural_def)
        
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
            initial_health = drive.metrics.health
            drive.tick(actor)
            
            # If health went from 1.0 to something else, or remove_commodity was called,
            # an event likely occurred
            if actor.inventory.remove_commodity.called:
                events_occurred += 1
                actor.inventory.remove_commodity.reset_mock()
        
        expected_events = num_trials * BASE_EVENT_PROB * PLANET_STRUCTURE_DECAY
        
        # Allow for some variance (within 3 standard deviations)
        # For binomial distribution: std = sqrt(n * p * (1-p))
        p = BASE_EVENT_PROB * PLANET_STRUCTURE_DECAY
        std_dev = (num_trials * p * (1 - p)) ** 0.5
        
        assert abs(events_occurred - expected_events) < 3 * std_dev
    
    def test_metrics_bounds_over_time(self, setup_drive_and_actor):
        """Test that all metrics stay within valid bounds over many ticks."""
        drive, actor = setup_drive_and_actor
        
        # Vary inventory randomly
        for _ in range(100):
            inventory_level = random.randint(0, 50)
            actor.inventory.get_available_quantity = Mock(return_value=inventory_level)
            actor.inventory.remove_commodity = Mock(return_value=inventory_level > 0)
            
            result = drive.tick(actor)
            
            # All metrics should be in valid range
            assert 0 <= result.health <= 1
            assert 0 <= result.debt <= 1
            assert 0 <= result.buffer <= 1
            assert 0 <= result.urgency <= 1
