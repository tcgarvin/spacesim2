import random

from spacesim2.core.commodity import CommodityRegistry
from spacesim2.core.drives.actor_drive import (
    ActorDrive,
    DriveMetrics,
    clamp01,
    log_norm_ratio,
)

# Stochastic maintenance model matching ClothingDrive pattern
BASE_EVENT_PROB = (
    1.0 / 120.0
)  # ~1 maintenance event per 120 days (less frequent than clothing)
DEBT_DECAY_FACTOR = 0.8
QUALITY_DEBT_DECAY_FACTOR = 0.5
DEBT_MISS_PENALTY = 0.5  # Shelter debt is serious
BUFFER_TARGET_DAYS = 120.0  # Good cushion = 4 months
BUFFER_MAX_DAYS = 360.0  # Saturation at 1 year
URGENCY = 1.0
DRIVE_NAME = "shelter"

# Shelter material commodity IDs
BUILDING_MATERIALS_NAME = "simple_building_materials"
PREFAB_HOUSING_NAME = "prefab_housing"


class ShelterDriveMetrics(DriveMetrics):
    def get_name(self):
        return DRIVE_NAME

    def get_score(self):
        # Score based on debt (shelter damage/degradation)
        return 1 - self.debt


class ShelterDrive(ActorDrive):
    """
    Shelter maintenance with quality tiers.

    - Stochastic maintenance events (~1 per 120 days)
    - Prefers prefab_housing (quality), falls back to simple_building_materials
    - Quality materials provide faster debt recovery
    """

    def __init__(self, commodity_registry: CommodityRegistry):
        super().__init__(commodity_registry=commodity_registry)
        self.building_materials = commodity_registry.get_commodity(
            BUILDING_MATERIALS_NAME
        )
        self.quality_materials = commodity_registry.get_commodity(PREFAB_HOUSING_NAME)
        self.metrics = ShelterDriveMetrics(
            health=1.0, debt=0.0, buffer=0.0, urgency=URGENCY
        )

    def tick(self, actor) -> DriveMetrics:
        """Process shelter maintenance for this turn."""
        p_event = BASE_EVENT_PROB

        # Count both material types for inventory
        materials_qty = actor.inventory.get_available_quantity(self.building_materials)
        quality_qty = (
            actor.inventory.get_available_quantity(self.quality_materials)
            if self.quality_materials
            else 0
        )
        total_qty = materials_qty + quality_qty
        has_shelter_materials = total_qty > 0

        health = 1.0 if has_shelter_materials else 0.0

        event_today = random.random() < p_event
        did_maintain = False
        used_quality = False

        if event_today and has_shelter_materials:
            # Try quality first, fall back to basic
            if self.quality_materials and actor.inventory.remove_commodity(
                self.quality_materials, 1
            ):
                did_maintain = True
                used_quality = True
            elif actor.inventory.remove_commodity(self.building_materials, 1):
                did_maintain = True

            # Recalculate post-consumption
            materials_qty = actor.inventory.get_available_quantity(
                self.building_materials
            )
            quality_qty = (
                actor.inventory.get_available_quantity(self.quality_materials)
                if self.quality_materials
                else 0
            )
            total_qty = materials_qty + quality_qty

        # Update debt
        if event_today:
            decay = QUALITY_DEBT_DECAY_FACTOR if used_quality else DEBT_DECAY_FACTOR
            debt = decay * self.metrics.debt
            if not did_maintain:
                debt += DEBT_MISS_PENALTY
            debt = clamp01(debt)
        else:
            decay_rate = DEBT_DECAY_FACTOR if has_shelter_materials else 1.0
            debt = self.metrics.debt * decay_rate

        # Buffer from remaining inventory (both types)
        exp_events_per_day = max(p_event, 1e-9)
        expected_coverage_days = total_qty / exp_events_per_day
        buffer = log_norm_ratio(
            expected_coverage_days, BUFFER_TARGET_DAYS, BUFFER_MAX_DAYS
        )

        self._update_metrics(health=health, debt=debt, buffer=buffer, urgency=URGENCY)
        return self.metrics

    def get_current_score(self):
        """Return the current score from metrics."""
        return self.metrics.get_score()
