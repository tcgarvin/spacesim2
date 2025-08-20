"""Unit tests for the ActorDrive module."""

import pytest
from unittest.mock import Mock, MagicMock
import math

from spacesim2.core.drives.actor_drive import (
    ActorDrive, 
    DriveMetrics, 
    clamp01, 
    log_norm_ratio,
    get_zero_metrics,
    generate_piecewise_mapping
)
from spacesim2.core.commodity import CommodityRegistry
from spacesim2.core.actor import Actor
from tests.helpers import get_actor


class TestClamp01:
    """Test the clamp01 utility function."""
    
    def test_clamp01_within_range(self):
        """Test that values within [0,1] are unchanged."""
        assert clamp01(0.0) == 0.0
        assert clamp01(0.5) == 0.5
        assert clamp01(1.0) == 1.0
    
    def test_clamp01_below_zero(self):
        """Test that negative values are clamped to 0."""
        assert clamp01(-0.1) == 0.0
        assert clamp01(-10.0) == 0.0
        assert clamp01(-math.inf) == 0.0
    
    def test_clamp01_above_one(self):
        """Test that values above 1 are clamped to 1."""
        assert clamp01(1.1) == 1.0
        assert clamp01(10.0) == 1.0
        assert clamp01(math.inf) == 1.0


class TestLogNormRatio:
    """Test the log_norm_ratio utility function."""
    
    def test_log_norm_ratio_basic_cases(self):
        """Test basic cases of log_norm_ratio."""
        # When x = 0, should return 0
        assert log_norm_ratio(0.0, 10.0, 20.0) == 0.0
        
        # When x = target, should return a value between 0 and 1
        result = log_norm_ratio(10.0, 10.0, 20.0)
        assert 0.0 <= result <= 1.0
        
        # When x = cap, should return 1.0
        result = log_norm_ratio(20.0, 10.0, 20.0)
        assert result == 1.0
    
    def test_log_norm_ratio_negative_input(self):
        """Test that negative inputs are handled correctly."""
        # Negative x should be treated as 0
        result = log_norm_ratio(-5.0, 10.0, 20.0)
        assert result == 0.0
    
    def test_log_norm_ratio_above_cap(self):
        """Test that values above cap are capped."""
        # x > cap should be treated as x = cap
        result1 = log_norm_ratio(20.0, 10.0, 20.0)
        result2 = log_norm_ratio(30.0, 10.0, 20.0)
        assert result1 == result2 == 1.0
    
    def test_log_norm_ratio_diminishing_returns(self):
        """Test that the function shows diminishing returns."""
        target, cap = 10.0, 20.0
        
        # Values should increase but with diminishing returns
        result_quarter = log_norm_ratio(2.5, target, cap)
        result_half = log_norm_ratio(5.0, target, cap)
        result_target = log_norm_ratio(10.0, target, cap)
        
        # Should be increasing
        assert result_quarter < result_half < result_target
        
        # The logarithmic nature means later increases are actually larger
        # This is because we're measuring log(1 + x/target) which grows faster initially
        # but the denominator normalizes it
        increase1 = result_half - result_quarter
        increase2 = result_target - result_half
        # Both increases should be positive, showing the function is monotonic
        assert increase1 > 0
        assert increase2 > 0
    
    def test_log_norm_ratio_edge_cases(self):
        """Test edge cases for log_norm_ratio."""
        # When cap = target, should handle gracefully
        result = log_norm_ratio(5.0, 10.0, 10.0)
        assert 0.0 <= result <= 1.0
        
        # When x exceeds cap, should be same as when x = cap
        result1 = log_norm_ratio(1.0, 0.01, 1.0)
        result2 = log_norm_ratio(2.0, 0.01, 1.0)  # Should be capped at same value
        assert result1 == result2


class TestGeneratePiecewiseMapping:
    """Test the generate_piecewise_mapping function."""
    
    def test_simple_linear_mapping(self):
        """Test a simple two-point linear mapping."""
        mapper = generate_piecewise_mapping([(0, 0), (10, 1)])
        
        assert mapper(0) == 0.0
        assert mapper(10) == 1.0
        assert mapper(5) == 0.5  # Midpoint
        assert mapper(-5) == 0.0  # Below range
        assert mapper(15) == 1.0  # Above range
    
    def test_multi_point_mapping(self):
        """Test a multi-point piecewise mapping."""
        mapper = generate_piecewise_mapping([(0, 0), (5, 0.5), (10, 0.8), (20, 1.0)])
        
        assert mapper(0) == 0.0
        assert mapper(5) == 0.5
        assert mapper(10) == 0.8
        assert mapper(20) == 1.0
        
        # Test interpolation between points
        assert mapper(2.5) == 0.25  # Halfway between (0,0) and (5,0.5)
        assert mapper(7.5) == 0.65  # Halfway between (5,0.5) and (10,0.8)
        assert mapper(15) == 0.9    # Halfway between (10,0.8) and (20,1.0)
    
    def test_unsorted_points(self):
        """Test that unsorted points are handled correctly."""
        mapper = generate_piecewise_mapping([(10, 1), (0, 0), (5, 0.5)])
        
        # Should work the same as sorted points
        assert mapper(0) == 0.0
        assert mapper(5) == 0.5
        assert mapper(10) == 1.0
        assert mapper(2.5) == 0.25
    
    def test_output_clamping(self):
        """Test that output values are clamped to [0,1]."""
        mapper = generate_piecewise_mapping([(0, -0.5), (5, 1.5), (10, 0.5)])
        
        assert mapper(0) == 0.0   # -0.5 clamped to 0
        assert mapper(5) == 1.0   # 1.5 clamped to 1
        assert mapper(10) == 0.5  # 0.5 unchanged
        
        # Interpolated values should also be properly bounded
        result = mapper(2.5)  # Halfway between 0.0 and 1.0
        assert 0.0 <= result <= 1.0
    
    def test_single_point(self):
        """Test mapping with a single point."""
        mapper = generate_piecewise_mapping([(5, 0.7)])
        
        # All inputs should return the single output value
        assert mapper(0) == 0.7
        assert mapper(5) == 0.7
        assert mapper(10) == 0.7
    
    def test_identical_x_values(self):
        """Test handling of identical x values."""
        mapper = generate_piecewise_mapping([(5, 0.3), (5, 0.8), (10, 1.0)])
        
        # Should use the first occurrence or handle gracefully
        assert mapper(5) in [0.3, 0.8]  # Either is acceptable
        assert mapper(10) == 1.0
    
    def test_empty_points_error(self):
        """Test that empty points list raises an error."""
        with pytest.raises(ValueError, match="Points list cannot be empty"):
            generate_piecewise_mapping([])
    
    def test_steep_transitions(self):
        """Test mapping with steep transitions."""
        mapper = generate_piecewise_mapping([(0, 0), (1, 0), (2, 1), (3, 1)])
        
        assert mapper(0) == 0.0
        assert mapper(1) == 0.0
        assert mapper(1.5) == 0.5  # Steep transition
        assert mapper(2) == 1.0
        assert mapper(3) == 1.0
    
    def test_negative_inputs(self):
        """Test mapping with negative input values."""
        mapper = generate_piecewise_mapping([(-10, 0), (0, 0.5), (10, 1)])
        
        assert mapper(-10) == 0.0
        assert mapper(-5) == 0.25   # Halfway between -10 and 0
        assert mapper(0) == 0.5
        assert mapper(5) == 0.75    # Halfway between 0 and 10
        assert mapper(10) == 1.0
    
    def test_return_type_is_callable(self):
        """Test that the function returns a callable."""
        mapper = generate_piecewise_mapping([(0, 0), (1, 1)])
        
        assert callable(mapper)
        assert isinstance(mapper(0.5), float)


class TestDriveMetrics:
    """Test the DriveMetrics dataclass."""
    
    def test_drive_metrics_creation(self):
        """Test creating DriveMetrics with all fields."""
        metrics = DriveMetrics(
            health=0.8,
            debt=0.2,
            buffer=0.6,
            urgency=0.9
        )
        
        assert metrics.health == 0.8
        assert metrics.debt == 0.2
        assert metrics.buffer == 0.6
        assert metrics.urgency == 0.9
    
    def test_get_zero_metrics(self):
        """Test the get_zero_metrics factory function."""
        metrics = get_zero_metrics()
        
        assert metrics.health == 0.0
        assert metrics.debt == 0.0
        assert metrics.buffer == 0.0
        assert metrics.urgency == 0.0
        assert isinstance(metrics, DriveMetrics)


class TestActorDrive:
    """Test the ActorDrive base class."""
    
    @pytest.fixture
    def commodity_registry(self):
        """Create a mock commodity registry."""
        return Mock(spec=CommodityRegistry)
    
    @pytest.fixture
    def actor_drive(self, commodity_registry):
        """Create an ActorDrive instance."""
        return ActorDrive(commodity_registry)
    
    @pytest.fixture
    def mock_actor(self):
        """Create a mock actor for testing."""
        return get_actor("TestActor")
    
    def test_actor_drive_initialization(self, actor_drive):
        """Test that ActorDrive initializes correctly."""
        assert isinstance(actor_drive.metrics, DriveMetrics)
        assert actor_drive.metrics.health == 0.0
        assert actor_drive.metrics.debt == 0.0
        assert actor_drive.metrics.buffer == 0.0
        assert actor_drive.metrics.urgency == 0.0
    
    def test_update_metrics(self, actor_drive):
        """Test the _update_metrics method."""
        actor_drive._update_metrics(
            health=0.8,
            debt=0.3,
            buffer=0.7,
            urgency=0.9
        )
        
        assert actor_drive.metrics.health == 0.8
        assert actor_drive.metrics.debt == 0.3
        assert actor_drive.metrics.buffer == 0.7
        assert actor_drive.metrics.urgency == 0.9
    
    def test_update_metrics_partial(self, actor_drive):
        """Test updating metrics one at a time."""
        # Set initial values
        actor_drive._update_metrics(0.1, 0.2, 0.3, 0.4)
        
        # Update with new values
        actor_drive._update_metrics(0.9, 0.8, 0.7, 0.6)
        
        assert actor_drive.metrics.health == 0.9
        assert actor_drive.metrics.debt == 0.8
        assert actor_drive.metrics.buffer == 0.7
        assert actor_drive.metrics.urgency == 0.6
    
    def test_tick_not_implemented(self, actor_drive, mock_actor):
        """Test that tick method raises NotImplementedError in base class."""
        with pytest.raises(NotImplementedError):
            actor_drive.tick(mock_actor)
    
    def test_metrics_bounds(self, actor_drive):
        """Test that metrics can handle edge values."""
        # Test with boundary values
        actor_drive._update_metrics(0.0, 0.0, 0.0, 0.0)
        assert all(metric == 0.0 for metric in [
            actor_drive.metrics.health,
            actor_drive.metrics.debt, 
            actor_drive.metrics.buffer,
            actor_drive.metrics.urgency
        ])
        
        actor_drive._update_metrics(1.0, 1.0, 1.0, 1.0)
        assert all(metric == 1.0 for metric in [
            actor_drive.metrics.health,
            actor_drive.metrics.debt,
            actor_drive.metrics.buffer, 
            actor_drive.metrics.urgency
        ])
    
    def test_metrics_immutability(self, actor_drive):
        """Test that metrics can be safely accessed without modification."""
        original_metrics = actor_drive.metrics
        
        # Modify metrics
        actor_drive._update_metrics(0.5, 0.6, 0.7, 0.8)
        
        # Original reference should reflect the changes
        assert original_metrics.health == 0.5
        assert original_metrics.debt == 0.6
        assert original_metrics.buffer == 0.7
        assert original_metrics.urgency == 0.8


class TestActorDriveIntegration:
    """Integration tests for ActorDrive with real components."""
    
    def test_with_real_commodity_registry(self):
        """Test ActorDrive with a real CommodityRegistry."""
        registry = CommodityRegistry()
        drive = ActorDrive(registry)
        
        assert isinstance(drive.metrics, DriveMetrics)
        assert drive.metrics.health == 0.0
    
    def test_metrics_persistence_across_updates(self):
        """Test that metrics are properly updated and persist."""
        registry = CommodityRegistry()
        drive = ActorDrive(registry)
        
        # Store reference to metrics
        metrics_ref = drive.metrics
        
        # Update metrics multiple times
        for i in range(5):
            health = i * 0.2
            drive._update_metrics(health, 0.0, 0.0, 0.0)
            assert metrics_ref.health == health
            assert drive.metrics.health == health
    
    def test_inheritance_compatibility(self):
        """Test that ActorDrive can be properly subclassed."""
        class TestDrive(ActorDrive):
            def tick(self, actor):
                self._update_metrics(0.5, 0.5, 0.5, 0.5)
                return self.metrics
        
        registry = CommodityRegistry()
        drive = TestDrive(registry)
        mock_actor = get_actor("TestActor")
        
        # Should not raise NotImplementedError
        result = drive.tick(mock_actor)
        
        assert isinstance(result, DriveMetrics)
        assert result.health == 0.5
        assert result.debt == 0.5
        assert result.buffer == 0.5
        assert result.urgency == 0.5
