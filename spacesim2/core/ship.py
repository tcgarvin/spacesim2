import random
from dataclasses import dataclass
from typing import Optional, Dict, List, Union, Tuple, TYPE_CHECKING
import enum
import math

from spacesim2.core.planet import Planet
from spacesim2.core.commodity import Inventory, CommodityDefinition
from spacesim2.core.market import Market

if TYPE_CHECKING:
    from spacesim2.core.simulation import Simulation


@dataclass
class TradePlan:
    """Represents a complete trade opportunity for a ship trader.

    A TradePlan encapsulates everything needed to execute a profitable trade:
    - Where to buy the commodity (origin)
    - Where to sell it (destination)
    - What commodity to trade
    - Expected costs and profits including round-trip fuel
    """
    origin: Planet
    destination: Planet
    commodity: CommodityDefinition

    # Quantities and costs
    quantity: int
    purchase_price_per_unit: int
    expected_sell_price_per_unit: int

    # Fuel calculations
    distance: float
    fuel_needed_one_way: int
    fuel_price_at_origin: int

    @property
    def fuel_needed_round_trip(self) -> int:
        """Fuel needed for round trip (conservative planning)."""
        return self.fuel_needed_one_way * 2

    @property
    def total_fuel_cost(self) -> int:
        """Total fuel cost for round trip."""
        return self.fuel_needed_round_trip * self.fuel_price_at_origin

    @property
    def total_purchase_cost(self) -> int:
        """Total cost to buy the commodity."""
        return self.quantity * self.purchase_price_per_unit

    @property
    def expected_revenue(self) -> int:
        """Expected revenue from selling at destination."""
        return self.quantity * self.expected_sell_price_per_unit

    @property
    def expected_profit(self) -> int:
        """Expected profit after all costs."""
        return self.expected_revenue - self.total_purchase_cost - self.total_fuel_cost

    @property
    def profit_margin(self) -> float:
        """Profit as a percentage of costs."""
        total_costs = self.total_purchase_cost + self.total_fuel_cost
        if total_costs <= 0:
            return 0.0
        return self.expected_profit / total_costs

    def is_profitable(self, min_margin: float = 0.15) -> bool:
        """Check if this trade meets minimum profitability threshold."""
        return self.expected_profit > 0 and self.profit_margin >= min_margin


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
    """Decision-making logic for trader ships that aim to maximize profit.

    Uses plan-driven trading: evaluates complete trade opportunities (buy->travel->sell)
    before committing to purchases. Plans for round-trip fuel to ensure safe return.
    """

    def __init__(self, ship: 'Ship') -> None:
        """Initialize the trader brain."""
        super().__init__(ship)
        # Track average purchase price per commodity for profitability calculations
        self.commodity_purchase_prices: Dict[str, float] = {}
        # Active trade plan (if any)
        self._current_plan: Optional[TradePlan] = None

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

    def _get_tradeable_commodities(self) -> List[CommodityDefinition]:
        """Get list of commodities that can be traded between planets."""
        commodities = []

        # For now, just trade food (most common need across planets)
        food = self.ship.simulation.commodity_registry.get_commodity("food")
        if food:
            commodities.append(food)

        return commodities

    def _evaluate_trade_opportunity(
        self,
        origin: Planet,
        destination: Planet,
        commodity: CommodityDefinition,
    ) -> Optional[TradePlan]:
        """Evaluate a single trade opportunity between two planets.

        Returns a TradePlan if the trade is feasible, None otherwise.
        Feasibility checks:
        - Can actually buy commodity at origin
        - Have enough money for purchase + fuel
        - Have enough cargo space
        - Have/can buy enough fuel for round trip
        """
        fuel_commodity = self.ship.simulation.commodity_registry.get_commodity(
            "nova_fuel"
        )
        if not fuel_commodity:
            return None

        # Get market data
        origin_market = origin.market
        dest_market = destination.market

        # Calculate distance and fuel needs
        distance = Ship.calculate_distance(origin, destination)
        fuel_one_way = Ship.calculate_fuel_needed(distance)
        fuel_round_trip = fuel_one_way * 2

        # Get prices at origin
        _, buy_price = origin_market.get_bid_ask_spread(commodity)
        if buy_price is None:
            # No one selling at origin
            return None

        _, fuel_ask = origin_market.get_bid_ask_spread(fuel_commodity)
        fuel_price = (
            fuel_ask
            if fuel_ask is not None
            else origin_market.get_avg_price(fuel_commodity)
        )
        if fuel_price is None or fuel_price <= 0:
            fuel_price = 10  # Default fuel price if no market data

        # Get expected sell price at destination (highest bid)
        sell_bid, _ = dest_market.get_bid_ask_spread(commodity)
        if sell_bid is None:
            # Use average price as fallback
            sell_bid = dest_market.get_avg_price(commodity)
        if sell_bid is None or sell_bid <= 0:
            return None

        # Calculate how much we can trade
        current_fuel = self.ship.cargo.get_quantity(fuel_commodity)
        cargo_space = self.ship.cargo_capacity - self.ship.cargo.get_total_quantity()

        # Reserve money for fuel purchase if needed
        fuel_to_buy = max(0, fuel_round_trip - current_fuel)
        fuel_cost = fuel_to_buy * fuel_price

        # Money available for commodity purchase (reserve 10% for safety)
        money_for_trading = int((self.ship.money - fuel_cost) * 0.9)
        if money_for_trading <= 0:
            return None

        # Calculate max quantity we can buy
        max_by_money = money_for_trading // buy_price
        max_by_cargo = cargo_space - fuel_to_buy  # Account for fuel taking cargo space
        max_quantity = max(0, min(max_by_money, max_by_cargo))

        if max_quantity <= 0:
            return None

        return TradePlan(
            origin=origin,
            destination=destination,
            commodity=commodity,
            quantity=max_quantity,
            purchase_price_per_unit=buy_price,
            expected_sell_price_per_unit=sell_bid,
            distance=distance,
            fuel_needed_one_way=fuel_one_way,
            fuel_price_at_origin=fuel_price,
        )

    def _find_best_trade_plan(self) -> Optional[TradePlan]:
        """Survey all possible trades and return the most profitable one.

        Evaluates trades from the current planet to all other planets
        for all tradeable commodities.
        """
        if not self.ship.planet or not self.ship.simulation.planets:
            return None

        current_planet = self.ship.planet
        commodities = self._get_tradeable_commodities()

        best_plan: Optional[TradePlan] = None
        best_profit = 0

        for destination in self.ship.simulation.planets:
            if destination == current_planet:
                continue

            for commodity in commodities:
                plan = self._evaluate_trade_opportunity(
                    origin=current_planet,
                    destination=destination,
                    commodity=commodity,
                )

                if plan and plan.is_profitable() and plan.expected_profit > best_profit:
                    best_plan = plan
                    best_profit = plan.expected_profit

        return best_plan

    def _execute_trade_plan(self, plan: TradePlan) -> None:
        """Execute a trade plan by placing appropriate buy orders.

        This method handles:
        1. Buying fuel (if needed for round trip)
        2. Buying the commodity

        Orders are placed at market prices to ensure execution.
        """
        market = self.ship.planet.market
        fuel_commodity = self.ship.simulation.commodity_registry.get_commodity(
            "nova_fuel"
        )

        actions = []

        # Cancel existing orders first
        existing_orders = market.get_actor_orders(self.ship)
        for order in existing_orders["buy"] + existing_orders["sell"]:
            market.cancel_order(order.order_id)

        # Step 1: Buy fuel if needed
        current_fuel = self.ship.cargo.get_quantity(fuel_commodity)
        fuel_needed = plan.fuel_needed_round_trip

        if current_fuel < fuel_needed:
            fuel_to_buy = fuel_needed - current_fuel
            _, fuel_ask = market.get_bid_ask_spread(fuel_commodity)

            if fuel_ask is not None:
                affordable_fuel = min(fuel_to_buy, self.ship.money // fuel_ask)
                if affordable_fuel > 0:
                    order_id = market.place_buy_order(
                        self.ship, fuel_commodity, affordable_fuel, fuel_ask
                    )
                    if order_id:
                        actions.append(f"Buying {affordable_fuel} fuel at {fuel_ask}")
                        self.ship.active_orders[order_id] = "buy fuel"

        # Step 2: Buy commodity
        _, commodity_ask = market.get_bid_ask_spread(plan.commodity)
        if commodity_ask is not None:
            # Recalculate affordable quantity after fuel purchase
            money_available = int(self.ship.money * 0.9)  # Keep 10% reserve
            cargo_available = (
                self.ship.cargo_capacity - self.ship.cargo.get_total_quantity()
            )

            quantity = min(plan.quantity, money_available // commodity_ask, cargo_available)

            if quantity > 0:
                order_id = market.place_buy_order(
                    self.ship, plan.commodity, quantity, commodity_ask
                )
                if order_id:
                    actions.append(
                        f"Buying {quantity} {plan.commodity.name} at {commodity_ask} "
                        f"(plan: sell at {plan.destination.name} for ~{plan.expected_sell_price_per_unit})"
                    )
                    self.ship.active_orders[order_id] = f"buy {plan.commodity.id}"

        if actions:
            self.ship.last_action = "; ".join(actions)
        else:
            self.ship.last_action = "Trade plan execution failed - no orders placed"

    def decide_trade_actions(self) -> None:
        """Execute trading actions based on plan-driven logic.

        Trading behavior:
        1. If we have cargo to sell, sell it (complete the trade)
        2. If no cargo, find the best trade plan and execute it
        3. If no profitable trades exist, maintain fuel and wait
        """
        if not self.ship.planet:
            return

        market = self.ship.planet.market
        fuel_commodity = self.ship.simulation.commodity_registry.get_commodity(
            "nova_fuel"
        )

        if not fuel_commodity:
            self.ship.last_action = "No trading - fuel commodity not available"
            return

        # Cancel existing orders first
        existing_orders = market.get_actor_orders(self.ship)
        for order in existing_orders["buy"] + existing_orders["sell"]:
            market.cancel_order(order.order_id)

        actions = []

        # Check if we have trade cargo
        has_trade_cargo = any(
            self.ship.cargo.get_quantity(c) > 0
            for c in self._get_tradeable_commodities()
        )

        # Priority 1: If we have cargo, decide whether to sell here or travel
        if has_trade_cargo:
            # Check if there's a better destination to sell
            should_sell_here = True
            current_planet = self.ship.planet
            fuel_available = self.ship.cargo.get_quantity(fuel_commodity)

            for commodity in self._get_tradeable_commodities():
                quantity = self.ship.cargo.get_quantity(commodity)
                if quantity <= 0:
                    continue

                local_bid, _ = market.get_bid_ask_spread(commodity)
                local_price = local_bid if local_bid else market.get_avg_price(commodity)

                # Check other planets for better prices
                for planet in self.ship.simulation.planets:
                    if planet == current_planet:
                        continue

                    distance = Ship.calculate_distance(current_planet, planet)
                    fuel_needed = Ship.calculate_fuel_needed(distance)

                    if fuel_available < fuel_needed:
                        continue

                    dest_bid, _ = planet.market.get_bid_ask_spread(commodity)
                    dest_price = dest_bid if dest_bid else planet.market.get_avg_price(commodity)

                    if dest_price and local_price and dest_price > local_price * 1.15:
                        # Better price elsewhere (>15% higher), don't sell here
                        should_sell_here = False
                        break

                if not should_sell_here:
                    break

            if should_sell_here:
                # Sell cargo here - no better destination available
                for commodity in self._get_tradeable_commodities():
                    quantity = self.ship.cargo.get_quantity(commodity)
                    if quantity > 0:
                        highest_bid, _ = market.get_bid_ask_spread(commodity)
                        if highest_bid is not None:
                            order_id = market.place_sell_order(
                                self.ship, commodity, quantity, highest_bid
                            )
                            if order_id:
                                actions.append(
                                    f"Selling {quantity} {commodity.name} at {highest_bid}"
                                )
                                self.ship.active_orders[order_id] = f"sell {commodity.id}"
                        else:
                            avg_price = max(1, market.get_avg_price(commodity) or 1)
                            order_id = market.place_sell_order(
                                self.ship, commodity, quantity, avg_price
                            )
                            if order_id:
                                actions.append(
                                    f"Offering {quantity} {commodity.name} at {avg_price} (no buyers)"
                                )
                                self.ship.active_orders[order_id] = f"sell {commodity.id}"
            else:
                # Better price elsewhere - will travel in decide_travel()
                actions.append("Holding cargo for better price elsewhere")

        if not has_trade_cargo:
            # Priority 3: Find and execute best trade plan
            plan = self._find_best_trade_plan()
            if plan:
                self._current_plan = plan
                self._execute_trade_plan(plan)
                return  # _execute_trade_plan sets last_action
            else:
                # No profitable trades - ensure we have fuel at least
                self._current_plan = None
                fuel_quantity = self.ship.cargo.get_quantity(fuel_commodity)
                if fuel_quantity < self.ship.fuel_capacity * 0.5:
                    _, fuel_ask = market.get_bid_ask_spread(fuel_commodity)
                    if fuel_ask is not None:
                        fuel_to_buy = min(
                            self.ship.fuel_capacity - fuel_quantity,
                            self.ship.money // fuel_ask,
                        )
                        if fuel_to_buy > 0:
                            order_id = market.place_buy_order(
                                self.ship, fuel_commodity, fuel_to_buy, fuel_ask
                            )
                            if order_id:
                                actions.append(
                                    f"Buying {fuel_to_buy} fuel (no profitable trades)"
                                )
                                self.ship.active_orders[order_id] = "buy fuel"

        if actions:
            self.ship.last_action = "; ".join(actions)
        else:
            self.ship.last_action = "No trade actions (waiting for opportunities)"
    
    def decide_travel(self) -> Optional[Planet]:
        """Decide whether to travel based on current cargo and trade plan.

        Travel logic:
        1. Only travel if we have cargo to sell
        2. Find the destination with highest expected value after fuel cost
        3. Stay put if no cargo (buying happens locally via trade plan)
        """
        if self.ship.status != ShipStatus.DOCKED:
            return None

        if not self.ship.planet or not self.ship.simulation.planets:
            return None

        fuel_commodity = self.ship.simulation.commodity_registry.get_commodity(
            "nova_fuel"
        )
        if not fuel_commodity:
            return None

        current_planet = self.ship.planet
        fuel_available = self.ship.cargo.get_quantity(fuel_commodity)

        # Check if we have any cargo to sell
        commodities = self._get_tradeable_commodities()
        cargo_to_sell = {
            c: self.ship.cargo.get_quantity(c)
            for c in commodities
            if self.ship.cargo.get_quantity(c) > 0
        }

        if not cargo_to_sell:
            # No cargo - don't travel (trade plan handles buying locally)
            return None

        # Find best destination for our cargo
        best_planet = None
        best_expected_value = 0

        for destination in self.ship.simulation.planets:
            if destination == current_planet:
                continue

            distance = Ship.calculate_distance(current_planet, destination)
            fuel_needed = Ship.calculate_fuel_needed(distance)

            # Must have fuel for the journey
            if fuel_available < fuel_needed:
                continue

            # Calculate expected value at this destination
            dest_market = destination.market
            total_value = 0

            for commodity, quantity in cargo_to_sell.items():
                bid, _ = dest_market.get_bid_ask_spread(commodity)
                if bid is None:
                    bid = dest_market.get_avg_price(commodity)
                if bid and bid > 0:
                    total_value += bid * quantity

            # Subtract fuel cost (using origin fuel prices)
            origin_fuel_price = (
                current_planet.market.get_avg_price(fuel_commodity) or 10
            )
            fuel_cost = fuel_needed * origin_fuel_price
            net_value = total_value - fuel_cost

            if net_value > best_expected_value:
                best_expected_value = net_value
                best_planet = destination

        return best_planet


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
        # Base calculation: 1 fuel per 20 distance units, rounded up
        return math.ceil(distance / 20)
    
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