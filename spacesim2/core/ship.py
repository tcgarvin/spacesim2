import random
from typing import Optional, Dict, List, Union, Tuple
import enum
import math

from spacesim2.core.planet import Planet
from spacesim2.core.commodity import Inventory
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
    """Decision-making logic for trader ships that aim to maximize profit."""

    def __init__(self, ship: 'Ship') -> None:
        """Initialize the trader brain."""
        super().__init__(ship)
        # Track average purchase price per commodity for profitability calculations
        self.commodity_purchase_prices: Dict[str, float] = {}

    def _calculate_average_purchase_price(self, commodity) -> Optional[float]:
        """Calculate average purchase price from recent transaction history."""
        if not self.ship.planet:
            return None

        market = self.ship.planet.market
        transactions = market.get_actor_transaction_history(self.ship)

        # Look at last 10 purchases of this commodity
        recent_purchases = [
            t for t in transactions[-10:]
            if t.buyer == self.ship and t.commodity_type == commodity
        ]

        if not recent_purchases:
            return None

        total_cost = sum(t.price * t.quantity for t in recent_purchases)
        total_quantity = sum(t.quantity for t in recent_purchases)

        return total_cost / total_quantity if total_quantity > 0 else None

    def decide_trade_actions(self) -> None:
        """Trade actions at current planet: buy low, sell high with profit margin."""
        if not self.ship.planet:
            return

        market = self.ship.planet.market

        # Get commodity references
        food_commodity = self.ship.simulation.commodity_registry.get_commodity("food")
        fuel_commodity = self.ship.simulation.commodity_registry.get_commodity("nova_fuel")

        if not food_commodity or not fuel_commodity:
            self.ship.last_action = "No trading - commodity definitions not available"
            return

        # Track cargo and money
        food_quantity = self.ship.cargo.get_quantity(food_commodity)
        cargo_space_available = self.ship.cargo_capacity - self.ship.cargo.get_total_quantity()
        fuel_quantity = self.ship.cargo.get_quantity(fuel_commodity)

        # Cancel existing orders
        existing_orders = market.get_actor_orders(self.ship)
        for order in existing_orders["buy"] + existing_orders["sell"]:
            market.cancel_order(order.order_id)

        actions = []

        # Priority 1: Sell food cargo for profit if we have it
        if food_quantity > 0:
            # Calculate our cost basis (what we paid + fuel costs amortized)
            avg_purchase_price = self._calculate_average_purchase_price(food_commodity)

            if avg_purchase_price is not None:
                # Require 20% profit margin to sell
                min_profitable_price = int(avg_purchase_price * 1.20)

                # Check current market conditions
                bid_ask = market.get_bid_ask_spread(food_commodity)
                highest_bid = bid_ask[1]  # Best buy order price

                if highest_bid is not None and highest_bid >= min_profitable_price:
                    # We can sell profitably! Match the best bid
                    sell_price = highest_bid
                    order_id = market.place_sell_order(
                        self.ship, food_commodity, food_quantity, sell_price
                    )
                    if order_id:
                        profit_pct = int((sell_price / avg_purchase_price - 1) * 100)
                        actions.append(f"Selling {food_quantity} food at {sell_price} credits ({profit_pct}% profit)")
                        self.ship.active_orders[order_id] = "sell food"
                else:
                    # Market price not profitable yet, offer slightly above min profitable
                    sell_price = max(min_profitable_price, int(market.get_avg_price(food_commodity) * 1.1))
                    order_id = market.place_sell_order(
                        self.ship, food_commodity, food_quantity, sell_price
                    )
                    if order_id:
                        actions.append(f"Offering {food_quantity} food at {sell_price} credits (waiting for profit)")
                        self.ship.active_orders[order_id] = "sell food"
            else:
                # No purchase history, use market average + 15% as sell price
                avg_price = market.get_avg_price(food_commodity)
                sell_price = max(int(avg_price * 1.15), 3)
                order_id = market.place_sell_order(
                    self.ship, food_commodity, food_quantity, sell_price
                )
                if order_id:
                    actions.append(f"Selling {food_quantity} food at {sell_price} credits")
                    self.ship.active_orders[order_id] = "sell food"

        # Priority 2: Ensure we have fuel for trading
        if cargo_space_available > 0 and self.ship.money > 0:
            if fuel_quantity < self.ship.fuel_capacity * 0.6:  # Keep fuel above 60%
                fuel_to_buy = min(cargo_space_available, self.ship.fuel_capacity - fuel_quantity)

                # Try to match best ask (lowest sell order)
                bid_ask = market.get_bid_ask_spread(fuel_commodity)
                lowest_ask = bid_ask[0]

                if lowest_ask is not None:
                    buy_price = lowest_ask
                    affordable_fuel = min(fuel_to_buy, self.ship.money // buy_price)

                    if affordable_fuel > 0:
                        order_id = market.place_buy_order(
                            self.ship, fuel_commodity, affordable_fuel, buy_price
                        )
                        if order_id:
                            actions.append(f"Buying {affordable_fuel} fuel at {buy_price} credits")
                            self.ship.active_orders[order_id] = "buy fuel"
                            cargo_space_available -= affordable_fuel

        # Priority 3: Buy food cargo only if we expect to sell it profitably
        if cargo_space_available > 0 and self.ship.money > 0 and food_quantity == 0:
            bid_ask = market.get_bid_ask_spread(food_commodity)
            lowest_ask = bid_ask[0]

            if lowest_ask is not None:
                # Only buy if we think we can sell for 20%+ profit elsewhere
                # For now, just buy at good prices (we'll improve route planning in decide_travel)
                buy_price = lowest_ask

                # Reserve some money for fuel and expenses
                money_for_trading = int(self.ship.money * 0.7)  # Use 70% max
                affordable_quantity = min(
                    cargo_space_available,
                    money_for_trading // buy_price
                )

                if affordable_quantity > 0:
                    order_id = market.place_buy_order(
                        self.ship, food_commodity, affordable_quantity, buy_price
                    )
                    if order_id:
                        actions.append(f"Buying {affordable_quantity} food at {buy_price} credits")
                        self.ship.active_orders[order_id] = "buy food"

        # Update last action
        if actions:
            self.ship.last_action = "; ".join(actions)
        else:
            self.ship.last_action = "No trade actions"
    
    def decide_travel(self) -> Optional[Planet]:
        """Decide whether to travel based on expected profit from trade routes."""
        # Don't travel if already traveling or needing maintenance
        if self.ship.status != ShipStatus.DOCKED:
            return None

        # Don't travel if we don't have a planet or planets to travel to
        if not self.ship.planet or not self.ship.simulation.planets:
            return None

        # Get commodity references
        fuel_commodity = self.ship.simulation.commodity_registry.get_commodity("nova_fuel")
        food_commodity = self.ship.simulation.commodity_registry.get_commodity("food")

        if not fuel_commodity or not food_commodity:
            return None

        current_planet = self.ship.planet
        current_market = current_planet.market
        fuel_available = self.ship.cargo.get_quantity(fuel_commodity)
        food_cargo = self.ship.cargo.get_quantity(food_commodity)

        # If we have cargo to sell, evaluate destinations by profit potential
        if food_cargo > 0:
            avg_purchase_price = self._calculate_average_purchase_price(food_commodity)
            if avg_purchase_price is None:
                # Fallback to market average if no purchase history
                avg_purchase_price = current_market.get_avg_price(food_commodity)

            best_planet = None
            best_expected_profit = 0

            for planet in self.ship.simulation.planets:
                if planet == current_planet:
                    continue

                distance = Ship.calculate_distance(current_planet, planet)
                fuel_needed = Ship.calculate_fuel_needed(distance)

                # Can we make the journey?
                if fuel_available < fuel_needed:
                    continue

                # What price can we expect at destination?
                destination_market = planet.market
                bid_ask = destination_market.get_bid_ask_spread(food_commodity)
                expected_sell_price = bid_ask[1] if bid_ask[1] is not None else destination_market.get_avg_price(food_commodity)

                if expected_sell_price is None or expected_sell_price <= 0:
                    continue

                # Calculate fuel cost for this journey
                fuel_price = current_market.get_avg_price(fuel_commodity) or 5
                fuel_cost_per_unit = (fuel_needed * fuel_price) / food_cargo if food_cargo > 0 else 0

                # Expected profit per unit = sell price - (purchase price + fuel cost)
                profit_per_unit = expected_sell_price - (avg_purchase_price + fuel_cost_per_unit)
                total_expected_profit = profit_per_unit * food_cargo

                # Only consider if profit exceeds 15% margin
                if profit_per_unit > avg_purchase_price * 0.15:
                    if total_expected_profit > best_expected_profit:
                        best_expected_profit = total_expected_profit
                        best_planet = planet

            # Travel if we found a profitable destination
            if best_planet:
                return best_planet

            # If no profitable destination, stay and wait for better prices
            return None

        # If we don't have cargo, look for good buying opportunities
        else:
            best_planet = None
            best_deal_score = float('-inf')

            # Only travel if we have enough money to make it worthwhile
            if self.ship.money < 100:
                return None

            for planet in self.ship.simulation.planets:
                if planet == current_planet:
                    continue

                distance = Ship.calculate_distance(current_planet, planet)
                fuel_needed = Ship.calculate_fuel_needed(distance)

                # Can we make the journey?
                if fuel_available < fuel_needed:
                    continue

                # What's the buying opportunity at destination?
                destination_market = planet.market
                bid_ask = destination_market.get_bid_ask_spread(food_commodity)
                buy_price = bid_ask[0] if bid_ask[0] is not None else destination_market.get_avg_price(food_commodity)

                if buy_price is None or buy_price <= 0:
                    continue

                # Calculate fuel cost for round trip (buy there, sell elsewhere)
                fuel_price = current_market.get_avg_price(fuel_commodity) or 5
                round_trip_fuel_cost = fuel_needed * 2 * fuel_price  # Rough estimate

                # How good is this price compared to other markets?
                current_price = current_market.get_avg_price(food_commodity)
                if current_price > 0:
                    price_differential = current_price - buy_price
                    # Deal score = price savings - fuel costs
                    deal_score = (price_differential * 50) - round_trip_fuel_cost  # Assume 50 unit cargo

                    if deal_score > best_deal_score and deal_score > 0:
                        best_deal_score = deal_score
                        best_planet = planet

            # Only travel if we found a good deal
            if best_planet and best_deal_score > 50:  # Minimum expected value
                return best_planet

            # Stay put if no good opportunities
            return None


class Ship:
    """Represents a trading ship that can travel between planets."""
    
    def __init__(
        self,
        name: str,
        simulation: 'Simulation',
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
        self.simulation = simulation  # Reference to the simulation
        self.market_history = []  # Track market activity for compatibility with market code
        self.food_consumed_this_turn = True  # Ships don't eat, but needed for compatibility
        self.drives = []  # Ships don't have drives, but keep empty list for interface compatibility

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
        # Get fuel commodity - simulation always available
        fuel_commodity = self.simulation.commodity_registry.get_commodity("nova_fuel")
        
        if not fuel_commodity:
            self.last_action = "Cannot perform maintenance - fuel commodity not defined"
            return False
            
        # Simple maintenance: costs 5 fuel units
        if self.cargo.has_quantity(fuel_commodity, 5):
            self.cargo.remove_commodity(fuel_commodity, 5)
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
        if self.planet and self not in self.planet.ships:
            self.planet.ships.append(self)
            
        # Check for maintenance needs
        if self.check_maintenance():
            self.maintenance_needed = True
            self.status = ShipStatus.NEEDS_MAINTENANCE
            self.last_action = "Maintenance required before departure"
            return False
            
        # Get fuel commodity - simulation always available
        fuel_commodity = self.simulation.commodity_registry.get_commodity("nova_fuel")
        
        if not fuel_commodity:
            self.last_action = "Cannot start journey - fuel commodity not defined"
            return False
            
        # Calculate distance and fuel requirements
        distance = Ship.calculate_distance(self.planet, destination)
        fuel_needed = Ship.calculate_fuel_needed(distance)
        adjusted_fuel_needed = math.ceil(fuel_needed / self.fuel_efficiency)
        
        # Check if we have enough fuel
        if not self.cargo.has_quantity(fuel_commodity, adjusted_fuel_needed):
            self.last_action = f"Insufficient fuel for journey (need {adjusted_fuel_needed})"
            return False
            
        # Consume fuel
        self.cargo.remove_commodity(fuel_commodity, adjusted_fuel_needed)
        
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
            if old_planet and self in old_planet.ships:
                old_planet.ships.remove(self)
            
            # Make sure destination planet has a ships list and add this ship to it
            if self.planet:
                # Planet should always have ships list initialized
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