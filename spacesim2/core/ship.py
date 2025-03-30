import random
from typing import Optional, Dict, List, Union, Tuple
import enum
import math

from spacesim2.core.planet import Planet
from spacesim2.core.commodity import Inventory, CommodityType, Commodity
from spacesim2.core.market import Market


class ShipStatus(enum.Enum):
    """Possible statuses for a ship."""
    DOCKED = "docked"  # Ship is docked at a planet
    TRAVELING = "traveling"  # Ship is traveling between planets
    NEEDS_MAINTENANCE = "needs_maintenance"  # Ship needs maintenance before traveling


class ShipBrain:
    """Base class for ship decision making strategies."""
    
    def __init__(self, ship: 'Ship') -> None:
        """Initialize the brain with a reference to its ship."""
        self.ship = ship
    
    def decide_trade_actions(self) -> None:
        """Decide what trade actions to take at the current planet."""
        raise NotImplementedError("Subclasses must implement this method")
    
    def decide_travel(self) -> Optional[Planet]:
        """Decide whether to travel to another planet, and if so, which one."""
        raise NotImplementedError("Subclasses must implement this method")


class TraderBrain(ShipBrain):
    """Decision-making logic for trader ships."""
    
    def decide_trade_actions(self) -> None:
        """Trade actions at current planet: buy low, sell high."""
        if not self.ship.planet or not self.ship.planet.market:
            return
        
        market = self.ship.planet.market
        commodity_type = CommodityType.RAW_FOOD  # For now, only trade food
        
        # Track cargo and money
        cargo_quantity = self.ship.cargo.get_quantity(commodity_type)
        cargo_space_available = self.ship.cargo_capacity - self.ship.cargo.get_total_quantity()
        fuel_quantity = self.ship.cargo.get_quantity(CommodityType.FUEL)
        
        # Cancel existing orders
        existing_orders = market.get_actor_orders(self.ship)
        for order in existing_orders["buy"] + existing_orders["sell"]:
            market.cancel_order(order.order_id)
        
        actions = []
        
        # If we have cargo to sell, sell it
        if cargo_quantity > 0:
            # Get market price information
            avg_price = market.get_avg_price(commodity_type)
            # Aim to sell above average price if possible
            sell_price = max(int(avg_price * 1.1), 2)
            
            order_id = market.place_sell_order(
                self.ship, commodity_type, cargo_quantity, sell_price
            )
            if order_id:
                actions.append(f"Offering {cargo_quantity} food at {sell_price} credits each")
                self.ship.active_orders[order_id] = f"sell {commodity_type.name}"
        
        # If we have room for cargo and money to spend, buy fuel first then commodities
        if cargo_space_available > 0 and self.ship.money > 0:
            # Prioritize buying fuel if needed
            if fuel_quantity < self.ship.fuel_capacity / 2:
                fuel_to_buy = min(cargo_space_available, self.ship.fuel_capacity - fuel_quantity)
                fuel_price = market.get_avg_price(CommodityType.FUEL) or 5  # Default price if unknown
                affordable_fuel = min(fuel_to_buy, self.ship.money // fuel_price)
                
                if affordable_fuel > 0:
                    order_id = market.place_buy_order(
                        self.ship, CommodityType.FUEL, affordable_fuel, fuel_price
                    )
                    if order_id:
                        actions.append(f"Buying {affordable_fuel} fuel at {fuel_price} credits each")
                        self.ship.active_orders[order_id] = f"buy {CommodityType.FUEL.name}"
                        cargo_space_available -= affordable_fuel
            
            # Buy commodities with remaining space and money
            if cargo_space_available > 0 and self.ship.money > 0:
                # Get market price information
                avg_price = market.get_avg_price(commodity_type)
                # Aim to buy below average price if possible
                buy_price = max(int(avg_price * 0.9), 1)
                
                # Calculate how much we can afford and fit
                affordable_quantity = min(
                    cargo_space_available,
                    self.ship.money // buy_price
                )
                
                if affordable_quantity > 0:
                    order_id = market.place_buy_order(
                        self.ship, commodity_type, affordable_quantity, buy_price
                    )
                    if order_id:
                        actions.append(f"Bidding for {affordable_quantity} food at {buy_price} credits each")
                        self.ship.active_orders[order_id] = f"buy {commodity_type.name}"
        
        # Update the ship's last action summary
        if actions:
            self.ship.last_action = "; ".join(actions)
        else:
            self.ship.last_action = "No trade actions"
    
    def decide_travel(self) -> Optional[Planet]:
        """Decide whether to travel to another planet, and if so, which one."""
        # Don't travel if already traveling or needing maintenance
        if self.ship.status != ShipStatus.DOCKED:
            return None
        
        # Don't travel if we don't have a planet or planets to travel to
        if not self.ship.planet or not self.ship.simulation or not self.ship.simulation.planets:
            return None
        
        # Consider traveling if we have enough fuel and cargo
        current_planet = self.ship.planet
        fuel_available = self.ship.cargo.get_quantity(CommodityType.FUEL)
        food_cargo = self.ship.cargo.get_quantity(CommodityType.RAW_FOOD)
        
        # Find all planets we can reach with our fuel
        reachable_planets = []
        for planet in self.ship.simulation.planets:
            if planet == current_planet:
                continue
                
            distance = Ship.calculate_distance(current_planet, planet)
            fuel_needed = Ship.calculate_fuel_needed(distance)
            
            if fuel_available >= fuel_needed:
                reachable_planets.append((planet, distance))
        
        # Don't travel if no reachable planets
        if not reachable_planets:
            return None
        
        # Decision logic based on cargo and market conditions
        if food_cargo > 0:
            # We have food to sell, find best price
            best_planet = None
            best_price = 0
            
            for planet, _ in reachable_planets:
                if planet.market:
                    price = planet.market.get_avg_price(CommodityType.RAW_FOOD)
                    if price > best_price:
                        best_price = price
                        best_planet = planet
            
            if best_planet and best_price > 0:
                return best_planet
        else:
            # We need to buy food, find cheapest price
            best_planet = None
            best_price = float('inf')
            
            for planet, _ in reachable_planets:
                if planet.market:
                    price = planet.market.get_avg_price(CommodityType.RAW_FOOD)
                    if 0 < price < best_price:  # Ensure price is positive
                        best_price = price
                        best_planet = planet
            
            if best_planet and best_price < float('inf'):
                return best_planet
        
        # If no specific preference based on market conditions, just pick a random reachable planet
        return random.choice(reachable_planets)[0] if reachable_planets else None


class Ship:
    """Represents a trading ship that can travel between planets."""
    
    def __init__(
        self,
        name: str,
        planet: Optional[Planet] = None,
        cargo_capacity: int = 100,
        fuel_capacity: int = 50,
        fuel_efficiency: float = 1.0,
        initial_money: int = 1000
    ) -> None:
        self.name = name
        self.money = initial_money
        self.reserved_money = 0  # Money reserved for market orders
        self.planet = planet
        self.destination = None  # Target planet when traveling
        self.cargo = Inventory()  # Cargo hold for commodities
        self.inventory = self.cargo  # Alias for compatibility with market code
        self.cargo_capacity = cargo_capacity
        self.fuel_capacity = fuel_capacity
        self.fuel_efficiency = fuel_efficiency  # Multiplier for fuel consumption
        self.travel_progress = 0.0  # Progress toward destination (0.0 to 1.0)
        self.travel_time = 0  # Total turns needed for current journey
        self.active_orders: Dict[str, str] = {}  # Track active order IDs and their types
        self.last_action = "None"  # Track the last action performed
        self.maintenance_needed = False  # Whether maintenance is required
        self.status = ShipStatus.DOCKED
        self.simulation = None  # Reference to the simulation
        self.market_history = []  # Track market activity for compatibility with market code
        self.food_consumed_this_turn = True  # Ships don't eat, but needed for compatibility
        
        # Initialize with a brain
        self.brain = TraderBrain(self)
    
    @staticmethod
    def calculate_distance(planet1: Planet, planet2: Planet) -> float:
        """Calculate the distance between two planets."""
        return math.sqrt((planet2.x - planet1.x) ** 2 + (planet2.y - planet1.y) ** 2)
    
    @staticmethod
    def calculate_fuel_needed(distance: float) -> int:
        """Calculate fuel needed for a journey of given distance."""
        # Base calculation: 1 fuel per 10 distance units, rounded up
        return math.ceil(distance / 10)
    
    def check_maintenance(self) -> bool:
        """Check if the ship needs maintenance before departure.
        
        Returns:
            True if maintenance is needed, False otherwise.
        """
        # Random chance of needing maintenance: 10%
        return random.random() < 0.1
    
    def perform_maintenance(self) -> bool:
        """Attempt to perform maintenance on the ship.
        
        Returns:
            True if maintenance was successful, False if we lack resources.
        """
        # Simple maintenance: costs 5 fuel units
        if self.cargo.has_quantity(CommodityType.FUEL, 5):
            self.cargo.remove_commodity(CommodityType.FUEL, 5)
            self.maintenance_needed = False
            self.status = ShipStatus.DOCKED
            self.last_action = "Performed maintenance using 5 fuel units"
            return True
        else:
            self.last_action = "Cannot perform maintenance - insufficient fuel"
            return False
    
    def start_journey(self, destination: Planet) -> bool:
        """Begin a journey to another planet.
        
        Args:
            destination: The target planet
            
        Returns:
            True if journey started successfully, False otherwise
        """
        if self.status != ShipStatus.DOCKED:
            self.last_action = f"Cannot start journey - ship status: {self.status.value}"
            return False
            
        if self.planet == destination:
            self.last_action = "Already at destination"
            return False
            
        # Set origin planet before starting journey - make sure the planet knows this ship
        if self.planet and hasattr(self.planet, 'ships') and self not in self.planet.ships:
            self.planet.ships.append(self)
            
        # Check for maintenance needs
        if self.check_maintenance():
            self.maintenance_needed = True
            self.status = ShipStatus.NEEDS_MAINTENANCE
            self.last_action = "Maintenance required before departure"
            return False
            
        # Calculate distance and fuel requirements
        distance = Ship.calculate_distance(self.planet, destination)
        fuel_needed = Ship.calculate_fuel_needed(distance)
        adjusted_fuel_needed = math.ceil(fuel_needed / self.fuel_efficiency)
        
        # Check if we have enough fuel
        if not self.cargo.has_quantity(CommodityType.FUEL, adjusted_fuel_needed):
            self.last_action = f"Insufficient fuel for journey (need {adjusted_fuel_needed})"
            return False
            
        # Consume fuel
        self.cargo.remove_commodity(CommodityType.FUEL, adjusted_fuel_needed)
        
        # Calculate travel time (1 turn per 20 distance units, minimum 1)
        self.travel_time = max(1, math.ceil(distance / 20))
        self.travel_progress = 0.0
        self.status = ShipStatus.TRAVELING
        self.destination = destination
        
        self.last_action = f"Departed for {destination.name} ({self.travel_time} turns)"
        return True
    
    def update_journey(self) -> bool:
        """Update journey progress.
        
        Returns:
            True if journey is complete, False otherwise
        """
        if self.status != ShipStatus.TRAVELING:
            return False
            
        if not self.destination:
            self.status = ShipStatus.DOCKED
            return False
            
        # Update progress
        progress_increment = 1.0 / self.travel_time
        self.travel_progress += progress_increment
        
        # Check if we've arrived
        if self.travel_progress >= 1.0:
            # Arrive at destination
            old_planet = self.planet
            self.planet = self.destination
            self.destination = None
            self.status = ShipStatus.DOCKED
            self.travel_progress = 0
            
            # Update ship's planet reference - transfer from old planet to new planet
            if old_planet and hasattr(old_planet, 'ships') and self in old_planet.ships:
                old_planet.ships.remove(self)
            
            # Make sure destination planet has a ships list and add this ship to it
            if self.planet:
                if not hasattr(self.planet, 'ships'):
                    self.planet.ships = []
                if self not in self.planet.ships:
                    self.planet.ships.append(self)
            
            self.last_action = f"Arrived at {self.planet.name}"
            return True
        else:
            # Still traveling
            remaining_turns = math.ceil((1.0 - self.travel_progress) * self.travel_time)
            self.last_action = f"En route to {self.destination.name} ({remaining_turns} turns remaining)"
            return False
    
    def take_turn(self) -> None:
        """Perform actions for this turn.
        
        Each turn consists of:
        1. If traveling, update journey
        2. If docked, take trade actions
        3. If docked, consider traveling
        """
        # Handle different statuses
        if self.status == ShipStatus.TRAVELING:
            # Update journey progress
            self.update_journey()
        elif self.status == ShipStatus.NEEDS_MAINTENANCE:
            # Try to perform maintenance
            self.perform_maintenance()
        elif self.status == ShipStatus.DOCKED:
            # Take trade actions at current planet
            self.brain.decide_trade_actions()
            
            # Consider traveling
            destination = self.brain.decide_travel()
            if destination:
                self.start_journey(destination)