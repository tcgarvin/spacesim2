from spacesim2.core.drives.actor_drive import ActorDrive, DriveMetrics, log_norm_ratio
from spacesim2.core.commodity import CommodityRegistry

DAILY_CONSUMPTION = 1
DEBT_DECAY_FACTOR = 0.8
DEBT_MISS_PENALTY = 0.2 # decay vs penalty should keep us lte 1.0 always.
PANTRY_TARGET = 7.0
PANTRY_MAX = 30.0
URGENCY = 1
DRIVE_NAME = "food"

class FoodDriveMetrics(DriveMetrics):

    def get_name(self):
        return DRIVE_NAME

    def get_score(self):
        # Score is based wholy on hunger as measured by the debt metric.
        return 1 - self.debt


class FoodDrive(ActorDrive):
    def __init__(self, commodity_registry:CommodityRegistry):
        super().__init__(commodity_registry=commodity_registry)
        self.metrics = FoodDriveMetrics(health=1.0, debt=0.0, buffer=0.0, urgency=URGENCY)
        self.food_commodity = commodity_registry.get_commodity("food")

    def tick(self, actor) -> DriveMetrics:
        did_eat = actor.inventory.remove_commodity(self.food_commodity, DAILY_CONSUMPTION)
        actor.food_consumed_this_turn = did_eat

        remaining_food = actor.inventory.get_available_quantity(self.food_commodity)
        pantry_days = remaining_food / DAILY_CONSUMPTION

        self._update_metrics(
            health = float(did_eat), 
            debt = self.metrics.debt * DEBT_DECAY_FACTOR + (not did_eat) * DEBT_MISS_PENALTY, 
            buffer = log_norm_ratio(pantry_days, PANTRY_TARGET, PANTRY_MAX),
            urgency = URGENCY
        )

        return self.metrics


