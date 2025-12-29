import random

from spacesim2.core.drives.actor_drive import ActorDrive, DriveMetrics, clamp01, log_norm_ratio
from spacesim2.core.commodity import CommodityRegistry

# Stochastic maintenance model matching ClothingDrive pattern
BASE_EVENT_PROB = 1.0 / 120.0  # ~1 maintenance event per 120 days (less frequent than clothing)
DEBT_DECAY_FACTOR = 0.8
DEBT_MISS_PENALTY = 0.5  # Shelter debt is serious
BUFFER_TARGET_DAYS = 120.0  # Good cushion = 4 months
BUFFER_MAX_DAYS = 360.0  # Saturation at 1 year
URGENCY = 1.0
DRIVE_NAME = "shelter"

# Shelter material commodity IDs
WOOD_NAME = "wood"
COMMON_METAL_NAME = "common_metal"


class ShelterDriveMetrics(DriveMetrics):
    def get_name(self):
        return DRIVE_NAME

    def get_score(self):
        # Score based on debt (shelter damage/degradation)
        return 1 - self.debt


class ShelterDrive(ActorDrive):
    """
    Shelter maintenance using wood OR common_metal (actor prefers cheaper option).

    - Stochastic maintenance events (~1 per 120 days)
    - If event occurs, consume 1 unit of EITHER wood or common_metal
    - Preference: choose cheaper material based on market prices
    - If neither available, incur debt
    - Metrics: health (has materials), debt (accumulated neglect), buffer (coverage days)
    """

    def __init__(self, commodity_registry: CommodityRegistry):
        super().__init__(commodity_registry=commodity_registry)
        self.wood_commodity = commodity_registry.get_commodity(WOOD_NAME)
        self.metal_commodity = commodity_registry.get_commodity(COMMON_METAL_NAME)
        self.metrics = ShelterDriveMetrics(health=1.0, debt=0.0, buffer=0.0, urgency=URGENCY)

    def tick(self, actor) -> DriveMetrics:
        """Process shelter maintenance for this turn."""
        p_event = BASE_EVENT_PROB

        # Determine current shelter material inventory
        wood_qty = actor.inventory.get_available_quantity(self.wood_commodity)
        metal_qty = actor.inventory.get_available_quantity(self.metal_commodity)
        has_shelter_materials = (wood_qty > 0 or metal_qty > 0)

        # Health based on whether we HAVE materials (not consumption)
        health = 1.0 if has_shelter_materials else 0.0

        # Check for maintenance event
        event_today = (random.random() < p_event)
        did_maintain = False

        if event_today:
            # Choose which material to use (prefer cheaper, then wood as fallback)
            material_to_use = self._choose_material(actor, wood_qty, metal_qty)

            if material_to_use:
                did_maintain = actor.inventory.remove_commodity(material_to_use, 1)
                # Update quantities after consumption
                wood_qty = actor.inventory.get_available_quantity(self.wood_commodity)
                metal_qty = actor.inventory.get_available_quantity(self.metal_commodity)

        # Update debt
        if event_today:
            debt = DEBT_DECAY_FACTOR * self.metrics.debt
            if not did_maintain:
                debt += DEBT_MISS_PENALTY
            debt = clamp01(debt)
        else:
            # Decay debt only if we have materials
            decay_rate = DEBT_DECAY_FACTOR if has_shelter_materials else 1.0
            debt = self.metrics.debt * decay_rate

        # Calculate buffer from remaining inventory (combined wood + metal)
        total_shelter_units = wood_qty + metal_qty
        exp_events_per_day = max(p_event, 1e-9)
        expected_coverage_days = total_shelter_units / exp_events_per_day
        buffer = log_norm_ratio(expected_coverage_days, BUFFER_TARGET_DAYS, BUFFER_MAX_DAYS)

        self._update_metrics(health=health, debt=debt, buffer=buffer, urgency=URGENCY)
        return self.metrics

    def _choose_material(self, actor, wood_qty: float, metal_qty: float):
        """Choose which shelter material to consume based on availability and price.

        Strategy:
        1. If only one material available, use that
        2. If both available, prefer cheaper material (based on market price)
        3. If market prices unavailable, prefer wood (simpler material)

        Args:
            actor: The actor making the choice
            wood_qty: Current wood inventory
            metal_qty: Current metal inventory

        Returns:
            Commodity to consume, or None if neither available
        """
        # Check what we have
        has_wood = wood_qty > 0
        has_metal = metal_qty > 0

        if not has_wood and not has_metal:
            return None

        if has_wood and not has_metal:
            return self.wood_commodity

        if has_metal and not has_wood:
            return self.metal_commodity

        # Both available - check prices
        if actor.planet and actor.planet.market:
            market = actor.planet.market
            wood_price = market.get_avg_price(self.wood_commodity)
            metal_price = market.get_avg_price(self.metal_commodity)

            # If we have price data, choose cheaper
            if wood_price is not None and metal_price is not None:
                return self.wood_commodity if wood_price <= metal_price else self.metal_commodity

        # Default: prefer wood (simpler, more primitive material)
        return self.wood_commodity

    def get_current_score(self):
        """Return the current score from metrics."""
        return self.metrics.get_score()
