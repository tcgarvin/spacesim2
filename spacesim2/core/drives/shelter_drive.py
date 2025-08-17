import random

from spacesim2.core.drives.actor_drive import ActorDrive, generate_linear_plateau, DriveMetrics, clamp01, log_norm_ratio
from spacesim2.core.commodity import CommodityRegistry

# Bernoulli chance of a maintenance event each day under mild climate.
BASE_EVENT_PROB        = 0.01        # ~1% per day => ~1 event every 100 days
PLANET_STRUCTURE_DECAY = 0.5         # Placeholder for future complexity
PLANET_EXPOSURE_RISK   = 0.5         # Placeholder for future complexity
URGENCY_FACTOR         = 2.0         # urgency01 = min(1, climate_factor / URGENCY_REF)

# Debt: choose so steady-state cap stays <= 1.0 when always missing.
DEBT_DECAY_FACTOR      = 0.8 * BASE_EVENT_PROB
DEBT_MISS_PENALTY      = 0.2         # 0.8*debt + 0.2*(miss) => <= 1.0

# Buffer mapping (expected days of coverage = stock / expected_events_per_day)
BUFFER_TARGET_DAYS     = 1/BASE_EVENT_PROB
BUFFER_MAX_DAYS        = 3/BASE_EVENT_PROB

STRUCTURAL_NAME        = "structural_component"   # commodity key


class ShelterDrive(ActorDrive):
    """
    Random-demand shelter maintenance model, matching FoodDrive structure:

    - Each day, a Bernoulli maintenance event occurs with prob p.
      p = BASE_EVENT_PROB * CLIMATE_SEVERITY
    - If an event fires, consume 1 'structural_component' if present.
      If not present, count as a miss and add to decaying shelter_debt.
    - Metrics:
        health = 1.0 if today's maintenance demand was met (or no event) else 0.0
        debt   = decaying debt (if prepared for next event) in [0,1] (miss memory); drives long-run pressure
        buffer = log-normalized expected days of coverage from current stock
        urgency= climate-based multiplier (0..1), surfaced for the translator
    """

    def __init__(self, commodity_registry: CommodityRegistry):
        super().__init__()
        self.structural_good = commodity_registry.get_commodity(STRUCTURAL_NAME)
        self._update_metrics(
            health=1.0,
            debt=0.0,
            buffer=0.0,
            urgency=0.0,
        )

    def tick(self, actor) -> DriveMetrics:
        urgency01 = clamp01(PLANET_EXPOSURE_RISK * URGENCY_FACTOR)
        p_event = BASE_EVENT_PROB * PLANET_STRUCTURE_DECAY

        event_today = (random.random() < p_event)

        if event_today:
            did_maintain = actor.inventory.remove_commodity(self.structural_good, 1)
            # did_maintain should not be used if there's no event

        remaining_units = actor.inventory.get_available_quantity(self.structural_good)

        if event_today:
            debt = DEBT_DECAY_FACTOR * self.metrics.debt
            if not did_maintain:
                debt += DEBT_MISS_PENALTY * urgency01
            debt = clamp01(debt)
            health = 1.0 if did_maintain else 0.0

        else:
            debt *= (DEBT_DECAY_FACTOR if remaining_units > 0 else 1)
            health = 1.0

        # Buffer from inventory → expected days of coverage
        # expected events/day is p_event; avoid div-by-zero
        exp_events_per_day = max(p_event, 1e-9)
        expected_coverage_days = remaining_units / exp_events_per_day
        buffer = log_norm_ratio(expected_coverage_days, BUFFER_TARGET_DAYS, BUFFER_MAX_DAYS)

        # Emit metrics
        self._update_metrics(
            health=health,
            debt=debt,
            buffer=buffer,
            urgency=urgency01,
        )
        return self.metrics
