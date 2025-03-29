import pytest

from spacesim2.core.commodity import Commodity, CommodityType, Inventory


def test_commodity_type_properties() -> None:
    """Test that commodity types have proper base properties."""
    # Base price
    assert CommodityType.get_base_price(CommodityType.RAW_FOOD) == 10.0
    
    # Production cost
    assert CommodityType.get_production_cost(CommodityType.RAW_FOOD) == 5.0
    
    # Production quantity
    assert CommodityType.get_production_quantity(CommodityType.RAW_FOOD) == 3


def test_inventory_operations() -> None:
    """Test that inventory operations work correctly."""
    inventory = Inventory()
    
    # Initially empty
    assert inventory.get_quantity(CommodityType.RAW_FOOD) == 0
    assert not inventory.has_quantity(CommodityType.RAW_FOOD, 1)
    
    # Add commodity
    inventory.add_commodity(CommodityType.RAW_FOOD, 5)
    assert inventory.get_quantity(CommodityType.RAW_FOOD) == 5
    assert inventory.has_quantity(CommodityType.RAW_FOOD, 3)
    assert not inventory.has_quantity(CommodityType.RAW_FOOD, 6)
    
    # Remove commodity
    assert inventory.remove_commodity(CommodityType.RAW_FOOD, 2)
    assert inventory.get_quantity(CommodityType.RAW_FOOD) == 3
    
    # Try to remove more than available
    assert not inventory.remove_commodity(CommodityType.RAW_FOOD, 4)
    assert inventory.get_quantity(CommodityType.RAW_FOOD) == 3
    
    # Remove all remaining
    assert inventory.remove_commodity(CommodityType.RAW_FOOD, 3)
    assert inventory.get_quantity(CommodityType.RAW_FOOD) == 0
    assert not inventory.has_quantity(CommodityType.RAW_FOOD, 1)