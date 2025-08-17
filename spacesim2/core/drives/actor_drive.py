"""
Actors have "needs" or "drives", which govern consumption, and are then exposed for scoring purposes.  The drives have some memory, so are attached to agents.
"""

from dataclasses import dataclass
from math import log1p
from typing import Callable

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

@dataclass
class DriveMetrics:
    """
    All metrics [0,1]
    """
    health: float
    debt: float
    buffer: float
    urgency: float

def get_zero_metrics() -> DriveMetrics:
    return DriveMetrics(
        health=0,
        debt=0,
        buffer=0,
        urgency=0,
    )

class ActorDrive:
    def __init__(self, commodity_registry:CommodityRegistry):
        self.metrics = get_zero_metrics()

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

