"""Planet attributes affecting resource availability and other environmental factors."""

import random
from dataclasses import dataclass
from typing import Optional


def _bimodal_sample(low_min: float, low_max: float, high_min: float, high_max: float) -> float:
    """Generate a bimodal distribution sample.

    50% chance of sampling from the low range, 50% from the high range.
    Useful for resources that are either rare or abundant.

    Args:
        low_min: Minimum value for the low range
        low_max: Maximum value for the low range
        high_min: Minimum value for the high range
        high_max: Maximum value for the high range

    Returns:
        A random value from one of the two ranges
    """
    if random.random() < 0.5:
        return random.uniform(low_min, low_max)
    return random.uniform(high_min, high_max)


@dataclass
class PlanetAttributes:
    """Per-planet environmental attributes affecting resource availability.

    All resource attributes are floats in the range [0.0, 1.0] where:
    - 0.0 = resource is absent/unavailable
    - 0.5 = average availability
    - 1.0 = excellent/abundant availability

    These attributes are used by gathering processes to modify success
    probability or output quantity based on per-process configuration.
    """

    # Resource availability (0.0-1.0) for extractable resources
    biomass: float = 1.0
    fiber: float = 1.0
    wood: float = 1.0
    common_metal_ore: float = 1.0
    nova_fuel_ore: float = 1.0
    simple_building_materials: float = 1.0

    # Future: non-resource attributes
    # gravity: float = 1.0
    # atmosphere: float = 1.0
    # temperature: float = 0.5

    def __post_init__(self) -> None:
        """Validate attribute ranges."""
        resource_attrs = [
            "biomass",
            "fiber",
            "wood",
            "common_metal_ore",
            "nova_fuel_ore",
            "simple_building_materials",
        ]
        for attr_name in resource_attrs:
            value = getattr(self, attr_name)
            if not (0.0 <= value <= 1.0):
                raise ValueError(
                    f"{attr_name} must be between 0.0 and 1.0, got {value}"
                )

    @classmethod
    def generate_random(cls) -> "PlanetAttributes":
        """Generate random planet attributes with per-resource distributions.

        Different resources have different generation logic:
        - biomass: Always some organic life (0.2-1.0)
        - fiber: Uniform distribution (0.0-1.0)
        - wood: Uniform distribution (0.0-1.0)
        - common_metal_ore: Uniform distribution (0.0-1.0)
        - nova_fuel_ore: Bimodal - rare or abundant (0.0-0.3 or 0.7-1.0)
        - simple_building_materials: Always some available (0.3-1.0)

        Returns:
            A PlanetAttributes instance with randomly generated values
        """
        return cls(
            biomass=random.uniform(0.2, 1.0),
            fiber=random.uniform(0.0, 1.0),
            wood=random.uniform(0.0, 1.0),
            common_metal_ore=random.uniform(0.0, 1.0),
            nova_fuel_ore=_bimodal_sample(0.0, 0.3, 0.7, 1.0),
            simple_building_materials=random.uniform(0.3, 1.0),
        )

    @classmethod
    def default(cls) -> "PlanetAttributes":
        """Return default attributes (all 1.0 - no penalties).

        Use this when planet attributes feature is disabled.

        Returns:
            A PlanetAttributes instance with all values set to 1.0
        """
        return cls()

    def get_availability(self, commodity_id: str) -> float:
        """Get the availability rating for a commodity.

        Args:
            commodity_id: The ID of the commodity to look up

        Returns:
            The availability value (0.0-1.0), or 1.0 if the commodity
            is not tracked by planet attributes
        """
        return getattr(self, commodity_id, 1.0)

    def to_dict(self) -> dict:
        """Convert attributes to a dictionary for serialization.

        Returns:
            Dictionary mapping attribute names to values
        """
        return {
            "biomass": self.biomass,
            "fiber": self.fiber,
            "wood": self.wood,
            "common_metal_ore": self.common_metal_ore,
            "nova_fuel_ore": self.nova_fuel_ore,
            "simple_building_materials": self.simple_building_materials,
        }
