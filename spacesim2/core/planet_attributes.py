"""Per-planet attributes that control resource availability."""

import random
from dataclasses import dataclass


def _bimodal_sample(
    low_min: float, low_max: float, high_min: float, high_max: float
) -> float:
    """Sample uniformly from the low range or the high range, 50/50.

    Models resources that are either rare or abundant.
    """
    if random.random() < 0.5:
        return random.uniform(low_min, low_max)
    return random.uniform(high_min, high_max)


@dataclass
class PlanetAttributes:
    """Per-planet resource availability.

    Each resource attribute is a float in [0.0, 1.0]: 0.0 absent, 0.5
    average, 1.0 abundant. Gathering processes use them to scale success
    probability or output quantity, chosen per process.
    """

    # Availability of each extractable resource.
    biomass: float = 1.0
    fiber: float = 1.0
    wood: float = 1.0
    common_metal_ore: float = 1.0
    nova_fuel_ore: float = 1.0
    simple_building_materials: float = 1.0
    silica: float = 1.0
    rare_earth_ore: float = 1.0

    def __post_init__(self) -> None:
        """Validate attribute ranges."""
        resource_attrs = [
            "biomass",
            "fiber",
            "wood",
            "common_metal_ore",
            "nova_fuel_ore",
            "simple_building_materials",
            "silica",
            "rare_earth_ore",
        ]
        for attr_name in resource_attrs:
            value = getattr(self, attr_name)
            if not (0.0 <= value <= 1.0):
                raise ValueError(
                    f"{attr_name} must be between 0.0 and 1.0, got {value}"
                )

    @classmethod
    def generate_random(cls) -> "PlanetAttributes":
        """Roll random attributes with a distribution per resource.

        - biomass: uniform 0.2-1.0, always some organic life
        - fiber, wood, common_metal_ore, silica: uniform 0.0-1.0
        - nova_fuel_ore: bimodal, 0.0-0.3 or 0.7-1.0
        - rare_earth_ore: bimodal, 0.0-0.2 or 0.6-1.0
        - simple_building_materials: uniform 0.3-1.0, always some available
        """
        return cls(
            biomass=random.uniform(0.2, 1.0),
            fiber=random.uniform(0.0, 1.0),
            wood=random.uniform(0.0, 1.0),
            common_metal_ore=random.uniform(0.0, 1.0),
            nova_fuel_ore=_bimodal_sample(0.0, 0.3, 0.7, 1.0),
            simple_building_materials=random.uniform(0.3, 1.0),
            silica=random.uniform(0.0, 1.0),
            rare_earth_ore=_bimodal_sample(0.0, 0.2, 0.6, 1.0),
        )

    @classmethod
    def default(cls) -> "PlanetAttributes":
        """Return attributes with no penalties (all 1.0)."""
        return cls()

    def get_availability(self, commodity_id: str) -> float:
        """Availability for a commodity; 1.0 if it has no attribute."""
        return getattr(self, commodity_id, 1.0)

    def to_dict(self) -> dict:
        """Serialize to a dict of attribute name to value."""
        return {
            "biomass": self.biomass,
            "fiber": self.fiber,
            "wood": self.wood,
            "common_metal_ore": self.common_metal_ore,
            "nova_fuel_ore": self.nova_fuel_ore,
            "simple_building_materials": self.simple_building_materials,
            "silica": self.silica,
            "rare_earth_ore": self.rare_earth_ore,
        }
