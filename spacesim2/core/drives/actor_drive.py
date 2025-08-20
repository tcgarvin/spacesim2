"""
Actors have "needs" or "drives", which govern consumption, and are then exposed for scoring purposes.  The drives have some memory, so are attached to agents.
"""

from dataclasses import dataclass
from math import log1p
from typing import Callable, List, Tuple

from spacesim2.core.actor import Actor
from spacesim2.core.commodity import CommodityRegistry

def clamp01(x: float) -> float:
    """Clamp a value to the range [0, 1]."""
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x

def log_norm_ratio(x:float, target:float, cap:float):
    """
    Buffer→[0,1] with diminishing returns: ln(1 + min(x,cap)/target) / ln(1 + cap/target).
    This is used to calculate a buffer metric that reflects how close a value is to a target
    while capping it at a maximum value. The logarithmic scaling provides diminishing returns,
    meaning that as the value approaches the target, the increase in the buffer metric becomes smaller.
    """
    ratio = min(max(x, 0.0), cap) / target
    denom = log1p(cap/target)
    return 0.0 if denom <= 0 else clamp01(log1p(ratio)/denom)

def generate_piecewise_mapping(points: List[Tuple[float, float]]) -> Callable[[float], float]:
    """
    Generate a piecewise linear mapping function from input to [0,1] output.
    
    Args:
        points: List of (input, output) tuples defining the piecewise linear function.
                Points should be sorted by input value. Output values will be clamped to [0,1].
    
    Returns:
        A callable that takes a float input and returns a float output in [0,1].
        
    Example:
        # Create a mapping where 0->0, 10->0.5, 20->1.0
        mapper = generate_piecewise_mapping([(0, 0), (10, 0.5), (20, 1.0)])
        result = mapper(15)  # Returns 0.75 (interpolated between 10->0.5 and 20->1.0)
    """
    if not points:
        raise ValueError("Points list cannot be empty")
    
    # Sort points by input value and clamp output values to [0,1]
    sorted_points = sorted(points, key=lambda p: p[0])
    clamped_points = [(x, clamp01(y)) for x, y in sorted_points]
    
    def mapping_function(x: float) -> float:
        # Handle edge cases
        if x <= clamped_points[0][0]:
            return clamped_points[0][1]
        if x >= clamped_points[-1][0]:
            return clamped_points[-1][1]
        
        # Find the two points to interpolate between
        for i in range(len(clamped_points) - 1):
            x1, y1 = clamped_points[i]
            x2, y2 = clamped_points[i + 1]
            
            if x1 <= x <= x2:
                # Linear interpolation
                if x2 == x1:  # Avoid division by zero
                    return y1
                t = (x - x1) / (x2 - x1)
                return y1 + t * (y2 - y1)
        
        # Should never reach here, but return 0 as fallback
        raise Exception("Unexpected mapping error.  Input: {}".format(x))

    return mapping_function


@dataclass
class DriveMetrics:
    """
    All metrics [0,1]
    """
    health: float
    debt: float
    buffer: float
    urgency: float

    def get_name(self):
        raise NotImplementedError()

    def get_score(self):
        raise NotImplementedError()

def get_zero_metrics() -> DriveMetrics:
    return DriveMetrics(
        health=0,
        debt=0,
        buffer=0,
        urgency=0,
    )

class ActorDrive:
    def __init__(self, commodity_registry:CommodityRegistry):
        pass

    def _update_metrics(
            self,
            health: float,
            debt: float,
            buffer: float,
            urgency: float,
    ):
        self.metrics.health = health
        self.metrics.debt = debt
        self.metrics.buffer = buffer
        self.metrics.urgency = urgency

    def tick(self, actor:Actor) -> DriveMetrics:
        """
        Checks needs and calculates satisfaction.  Consumes goods if required.
        """
        raise NotImplementedError()

    def get_current_score(self):
        """
        Uses metrics to return an overall score between 0 and 1
        """
        raise NotImplementedError()
