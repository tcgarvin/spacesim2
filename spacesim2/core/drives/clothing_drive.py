import random
from spacesim2.core.drives.actor_drive import ActorDrive, DriveMetrics, clamp01, log_norm_ratio
from spacesim2.core.commodity import CommodityRegistry

# Tunables
BASE_EVENT_PROB     = 1.0 / 60.0   # ~one replacement event per 60 days
DEBT_DECAY_FACTOR   = 0.8
DEBT_MISS_PENALTY   = 0.5          # with 0.8 decay, steady-state cap <= 1
BUFFER_TARGET_DAYS  = 60.0         # "good" wardrobe cushion
BUFFER_MAX_DAYS     = 180.0        # saturates near ~6 months
CLOTHING_NAME       = "clothing"
URGENCY = 1.0  # fixed urgency for clothing drive
DRIVE_NAME = "clothing"

class ClothingDriveMetrics(DriveMetrics):
    def get_name(self):
        return DRIVE_NAME

    def get_score(self):
        # Score is based solely on debt
        return 1 - self.debt

class ClothingDrive(ActorDrive):
    """
    Random-demand clothing replacement.

    - Daily Bernoulli demand:
        p_event = clamp01(BASE_EVENT_PROB * (1 + EVENT_DEBT_BOOST * debt))
    - If event fires, try to consume 1 'clothing' unit; miss -> debt accrues.
    - Health is based on *current stock*, not event outcome:
        health = 1.0 if stock_before >= 1 else 0.0
    - Debt decays every tick; penalty added only on a missed event.
    - Buffer = expected days of coverage = stock_after / max(p_event, eps).
    """

    def __init__(self, commodity_registry: CommodityRegistry):
        super().__init__(commodity_registry=commodity_registry)
        self.clothing_good = commodity_registry.get_commodity(CLOTHING_NAME)
        # Initialize drive-specific metrics instance
        self.metrics = ClothingDriveMetrics(health=1.0, debt=0.0, buffer=0.0, urgency=URGENCY)

    def tick(self, actor) -> DriveMetrics:
        p_event = BASE_EVENT_PROB

        clothing_inventory = actor.inventory.get_available_quantity(self.clothing_good)
        has_clothes = clothing_inventory > 0
        health = 1.0 if has_clothes >= 1 else 0.0

        event_today = (random.random() < p_event)
        if event_today:
            actor.inventory.remove_commodity(self.clothing_good, 1)
            clothing_inventory = actor.inventory.get_available_quantity(self.clothing_good)

        debt = DEBT_DECAY_FACTOR * self.metrics.debt + (not has_clothes) * DEBT_MISS_PENALTY
        debt = clamp01(debt)

        # --- Buffer from post-consumption stock ---
        exp_events_per_day = max(p_event, 1e-9)
        expected_coverage_days = clothing_inventory / exp_events_per_day
        buffer = log_norm_ratio(expected_coverage_days, BUFFER_TARGET_DAYS, BUFFER_MAX_DAYS)

        # urgency fixed at 1.0
        self._update_metrics(health=health, debt=debt, buffer=buffer, urgency=URGENCY)
        return self.metrics
