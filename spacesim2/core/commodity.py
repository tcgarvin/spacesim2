from dataclasses import dataclass
from typing import Dict, Optional, List, Any

import yaml


@dataclass(frozen=True)
class CommodityDefinition:
    """Definition of a commodity in the simulation."""
    id: str
    name: str
    transportable: bool
    description: str
    
    def __str__(self) -> str:
        return self.name
    

class CommodityRegistry:
    """Registry that loads and manages commodity definitions."""
    
    def __init__(self):
        self._commodities: Dict[str, CommodityDefinition] = {}
        
    def load_from_file(self, filepath: str) -> None:
        """Load commodity definitions from a YAML file."""
        try:
            with open(filepath, 'r') as f:
                commodities_data = yaml.safe_load(f)
                
            for commodity_data in commodities_data:
                commodity_def = CommodityDefinition(
                    id=commodity_data['id'],
                    name=commodity_data['name'],
                    transportable=commodity_data['transportable'],
                    description=commodity_data['description']
                )
                self._commodities[commodity_def.id] = commodity_def
        except Exception as e:
            print(f"Error loading commodities from {filepath}: {e}")
    
    def get_commodity(self, commodity_id: str) -> Optional[CommodityDefinition]:
        """Get a commodity definition by ID."""
        return self._commodities.get(commodity_id)
        
    def all_commodities(self) -> List[CommodityDefinition]:
        """Get all commodity definitions."""
        return list(self._commodities.values())

    def __getitem__(self, commodity_id: str) -> CommodityDefinition:
        """Get a commodity definition by ID using dictionary-like access."""
        returnable = self.get_commodity(commodity_id)
        if returnable is None:
            raise KeyError(f"Commodity with ID '{commodity_id}' not found.")
        return returnable


class Inventory:
    """Manages an actor's inventory of commodities."""

    def __init__(self) -> None:
        # Only store CommodityDefinition objects
        self.commodities: Dict[CommodityDefinition, int] = {}
        self.reserved_commodities: Dict[CommodityDefinition, int] = {}  # For market orders

    def add_commodity(self, commodity: CommodityDefinition, quantity: int) -> None:
        """Add a quantity of a commodity to the inventory."""
        if quantity <= 0:
            return
        
        # Only handle CommodityDefinition objects
        current_quantity = self.commodities.get(commodity, 0)
        self.commodities[commodity] = current_quantity + quantity

    def remove_commodity(self, commodity: CommodityDefinition, quantity: int) -> bool:
        """
        Remove a quantity of a commodity from the inventory.
        
        Returns:
            bool: True if commodity was successfully removed, False if not enough available.
        """
        if quantity <= 0:
            return True
        
        # Only handle CommodityDefinition objects
        current_quantity = self.commodities.get(commodity, 0)
        if current_quantity < quantity:
            return False
        
        self.commodities[commodity] = current_quantity - quantity
        
        # Remove the entry if quantity is zero
        if self.commodities[commodity] == 0:
            del self.commodities[commodity]
        
        return True
        
    def reserve_commodity(self, commodity: CommodityDefinition, quantity: int) -> bool:
        """Reserve a quantity of a commodity for a market order.
        
        Returns:
            bool: True if reservation was successful, False if not enough available.
        """
        # Only handle CommodityDefinition objects
        available = self.get_available_quantity(commodity)
        if available < quantity:
            return False
        
        # Update actual inventory
        self.commodities[commodity] -= quantity
        
        # Update reservation
        current_reserved = self.reserved_commodities.get(commodity, 0)
        self.reserved_commodities[commodity] = current_reserved + quantity
        
        # Clean up if inventory is zero
        if self.commodities[commodity] == 0:
            del self.commodities[commodity]
        
        return True
        
    def unreserve_commodity(self, commodity: CommodityDefinition, quantity: int) -> None:
        """Return a reserved commodity to available inventory."""
        if quantity <= 0:
            return
        
        # Only handle CommodityDefinition objects
        current_reserved = self.reserved_commodities.get(commodity, 0)
        quantity_to_unreserve = min(quantity, current_reserved)
        
        if quantity_to_unreserve > 0:
            # Update reservation
            self.reserved_commodities[commodity] = current_reserved - quantity_to_unreserve
            
            # Add back to available inventory
            current_quantity = self.commodities.get(commodity, 0)
            self.commodities[commodity] = current_quantity + quantity_to_unreserve
            
            # Clean up if reserved is zero
            if self.reserved_commodities[commodity] == 0:
                del self.reserved_commodities[commodity]

    def get_quantity(self, commodity: CommodityDefinition) -> int:
        """Get the total quantity of a commodity in the inventory (available + reserved)."""
        # Only handle CommodityDefinition objects
        available = self.commodities.get(commodity, 0)
        reserved = self.reserved_commodities.get(commodity, 0)
        return available + reserved
        
    def get_available_quantity(self, commodity: CommodityDefinition) -> int:
        """Get the available (unreserved) quantity of a commodity in the inventory."""
        # Only handle CommodityDefinition objects
        return self.commodities.get(commodity, 0)
        
    def get_reserved_quantity(self, commodity: CommodityDefinition) -> int:
        """Get the quantity of a commodity that is reserved for market orders."""
        # Only handle CommodityDefinition objects
        return self.reserved_commodities.get(commodity, 0)

    def has_quantity(self, commodity: CommodityDefinition, quantity: int) -> bool:
        """Check if the inventory has at least the specified quantity of a commodity (available only)."""
        return self.get_available_quantity(commodity) >= quantity
        
    def get_total_quantity(self) -> int:
        """Get the total quantity of all commodities in the inventory (available + reserved)."""
        total = 0
        
        # Sum available quantities
        for quantity in self.commodities.values():
            total += quantity
            
        # Sum reserved quantities
        for quantity in self.reserved_commodities.values():
            total += quantity
            
        return total