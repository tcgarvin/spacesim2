import unittest
from spacesim2.core.ship import Ship, ShipStatus
from spacesim2.core.planet import Planet
from spacesim2.core.commodity import CommodityType


class TestShip(unittest.TestCase):
    def setUp(self):
        # Create planets for testing
        self.earth = Planet("Earth", 0, 0)
        self.mars = Planet("Mars", 50, 0)  # 50 units away from Earth
        
        # Create a ship
        self.ship = Ship("TestShip", self.earth)
        self.earth.add_ship(self.ship)
        
        # Add fuel to the ship
        self.ship.cargo.add_commodity(CommodityType.FUEL, 50)

    def test_ship_initialization(self):
        self.assertEqual(self.ship.name, "TestShip")
        self.assertEqual(self.ship.planet, self.earth)
        self.assertEqual(self.ship.status, ShipStatus.DOCKED)
        self.assertEqual(self.ship.cargo.get_quantity(CommodityType.FUEL), 50)

    def test_distance_calculation(self):
        distance = Ship.calculate_distance(self.earth, self.mars)
        self.assertEqual(distance, 50.0)

    def test_fuel_calculation(self):
        distance = 50.0
        fuel_needed = Ship.calculate_fuel_needed(distance)
        self.assertEqual(fuel_needed, 5)  # 50 / 10 = 5 units of fuel

    def test_journey_start_and_progress(self):
        # Start a journey to Mars
        self.assertTrue(self.ship.start_journey(self.mars))
        self.assertEqual(self.ship.status, ShipStatus.TRAVELING)
        self.assertEqual(self.ship.destination, self.mars)
        
        # Check fuel was consumed
        fuel_consumed = 5  # For a distance of 50 units
        self.assertEqual(self.ship.cargo.get_quantity(CommodityType.FUEL), 50 - fuel_consumed)
        
        # Journey should take 3 turns (50 / 20 = 2.5, rounded to 3)
        self.assertEqual(self.ship.travel_time, 3)
        
        # Update for 2 turns
        self.assertFalse(self.ship.update_journey())  # Not arrived yet
        self.assertFalse(self.ship.update_journey())  # Not arrived yet
        
        # Third turn should arrive
        self.assertTrue(self.ship.update_journey())  # Arrived
        self.assertEqual(self.ship.status, ShipStatus.DOCKED)
        self.assertEqual(self.ship.planet, self.mars)
        self.assertIn(self.ship, self.mars.ships)
        self.assertNotIn(self.ship, self.earth.ships)

    def test_insufficient_fuel(self):
        # Create a ship with less fuel
        ship2 = Ship("FuellessShip", self.earth)
        self.earth.add_ship(ship2)
        ship2.cargo.add_commodity(CommodityType.FUEL, 2)  # Only 2 units of fuel
        
        # Attempt to start a journey, but should fail due to insufficient fuel
        self.assertFalse(ship2.start_journey(self.mars))
        self.assertEqual(ship2.status, ShipStatus.DOCKED)


if __name__ == '__main__':
    unittest.main()