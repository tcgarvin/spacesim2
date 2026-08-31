"""
Actors have "needs" or "drives", which govern consumption, and are then exposed for scoring purposes.  The drives have some memory, so are attached to agents.
"""

from dataclasses import dataclass
from math import log1p
from typing import List

from spacesim2.core.actor import Actor
from spacesim2.core.commodity import CommodityDefinition, CommodityRegistry


def clamp01(x: float) -> float:
    """Clamp a value to the range [0, 1]."""
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def log_norm_ratio(x: float, target: float, cap: float) -> float:
    """
    Buffer→[0,1] with diminishing returns: ln(1 + min(x,cap)/target) / ln(1 + cap/target).
    This is used to calculate a buffer metric that reflects how close a value is to a target
    while capping it at a maximum value. The logarithmic scaling provides diminishing returns,
    meaning that as the value approaches the target, the increase in the buffer metric becomes smaller.
    """
    ratio = min(max(x, 0.0), cap) / target
    denom = log1p(cap / target)
    return 0.0 if denom <= 0 else clamp01(log1p(ratio) / denom)


@dataclass
class DriveMetrics:
    """
    All metrics [0,1]
    """

    health: float
    debt: float
    buffer: float
    urgency: float

    def get_name(self) -> str:
        raise NotImplementedError()

    def get_score(self) -> float:
        raise NotImplementedError()


def get_zero_metrics() -> DriveMetrics:
    return DriveMetrics(
        health=0,
        debt=0,
        buffer=0,
        urgency=0,
    )


class ActorDrive:
    # Welfare lost when a single maintenance event is missed. One consumed unit
    # of a satisfying material avoids exactly one such miss, so this doubles as
    # the per-unit "deprivation stake" used to price buy orders. Subclasses set
    # this to their own DEBT_MISS_PENALTY.
    MISS_PENALTY: float = 0.0

    def __init__(self, commodity_registry: CommodityRegistry):
        self.metrics = get_zero_metrics()

    def deprivation_stake(self) -> float:
        """Welfare value of one consumed unit of this drive's material.

        Each consumption event uses one unit and avoids one miss penalty, so the
        stake is the miss penalty regardless of how often events fire. This is
        the numerator of willingness-to-pay, comparable across drives because all
        drives measure welfare in the same avoided-debt currency.
        """
        return self.MISS_PENALTY

    def materials(self) -> List[CommodityDefinition]:
        """Commodities that satisfy this drive, basic (market) good first.

        The basic good is the workhorse that actually trades; quality upgrades
        (if any) follow. Subclasses override.
        """
        return []

    def target_units(self) -> int:
        """Inventory level the actor aims to keep on hand for this drive."""
        return 0

    def marginal_welfare(self) -> float:
        """Welfare benefit of acquiring one more unit, given current coverage.

        Discounted by the drive's buffer: a well-stocked drive values an extra
        unit less (it just sits in inventory longer before being consumed).
        """
        return self.deprivation_stake() * (1.0 - self.metrics.buffer)

    def _update_metrics(
        self,
        health: float,
        debt: float,
        buffer: float,
        urgency: float,
    ) -> None:
        self.metrics.health = health
        self.metrics.debt = debt
        self.metrics.buffer = buffer
        self.metrics.urgency = urgency

    def tick(self, actor: Actor) -> DriveMetrics:
        """
        Checks needs and calculates satisfaction.  Consumes goods if required.
        """
        raise NotImplementedError()
