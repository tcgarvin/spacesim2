from enum import Enum, auto
from dataclasses import dataclass
from typing import Dict, Optional


class CommodityType(Enum):
    """Types of commodities in the simulation."""

    RAW_FOOD = auto()

    @classmethod
    def get_base_price(cls, commodity_type: "CommodityType") -> int:
        """Get the base price for a commodity type."""
        base_prices = {
            CommodityType.RAW_FOOD: 10,  # Base price for food
        }
        return base_prices.get(commodity_type, 0)
    
    @classmethod
    def get_production_cost(cls, commodity_type: "CommodityType") -> int:
        """Get the cost to produce one unit of a commodity."""
        production_costs = {
            CommodityType.RAW_FOOD: 5,  # Cost in labor/time to produce
        }
        return production_costs.get(commodity_type, 0)
    
    @classmethod
    def get_production_quantity(cls, commodity_type: "CommodityType") -> int:
        """Get the standard quantity produced in one action."""
        production_quantities = {
            CommodityType.RAW_FOOD: 3,  # Standard output is 3 units per action
        }
        return production_quantities.get(commodity_type, 0)


@dataclass
class Commodity:
    """Represents a commodity in the simulation."""

    type: CommodityType
    quantity: int = 0

    @property
    def name(self) -> str:
        """Get the name of the commodity."""
        return self.type.name.lower().replace("_", " ")


class Inventory:
    """Manages an actor's inventory of commodities."""

    def __init__(self) -> None:
        self.commodities: Dict[CommodityType, int] = {}

    def add_commodity(self, commodity_type: CommodityType, quantity: int) -> None:
        """Add a quantity of a commodity to the inventory."""
        if quantity <= 0:
            return
            
        current_quantity = self.commodities.get(commodity_type, 0)
        self.commodities[commodity_type] = current_quantity + quantity

    def remove_commodity(
        self, commodity_type: CommodityType, quantity: int
    ) -> bool:
        """
        Remove a quantity of a commodity from the inventory.
        
        Returns:
            bool: True if commodity was successfully removed, False if not enough available.
        """
        if quantity <= 0:
            return True
            
        current_quantity = self.commodities.get(commodity_type, 0)
        
        if current_quantity < quantity:
            return False
            
        self.commodities[commodity_type] = current_quantity - quantity
        
        # Remove the entry if quantity is zero
        if self.commodities[commodity_type] == 0:
            del self.commodities[commodity_type]
            
        return True

    def get_quantity(self, commodity_type: CommodityType) -> int:
        """Get the current quantity of a commodity in the inventory."""
        return self.commodities.get(commodity_type, 0)

    def has_quantity(self, commodity_type: CommodityType, quantity: int) -> bool:
        """Check if the inventory has at least the specified quantity of a commodity."""
        return self.get_quantity(commodity_type) >= quantity