import random
from typing import Optional, Dict, List, Union, Tuple, Any, TYPE_CHECKING
import enum

from spacesim2.core.planet import Planet
from spacesim2.core.commodity import Inventory, CommodityDefinition

if TYPE_CHECKING:
    from spacesim2.core.simulation import Simulation
    from spacesim2.core.process import ProcessDefinition


class ActorType(enum.Enum):
    """Types of actors in the simulation."""
    
    REGULAR = "regular"
    MARKET_MAKER = "market_maker"


class ActorBrain:
    """Base class for actor decision making strategies."""
    
    def __init__(self, actor: 'Actor') -> None:
        """Initialize the brain with a reference to its actor."""
        self.actor = actor
    
    def decide_economic_action(self) -> None:
        """Decide which economic action to take this turn."""
        raise NotImplementedError("Subclasses must implement this method")
    
    def decide_market_actions(self) -> None:
        """Decide what market actions to take this turn."""
        raise NotImplementedError("Subclasses must implement this method")
    
    def should_produce_food(self) -> bool:
        """Decide whether to produce food or do government work."""
        raise NotImplementedError("Subclasses must implement this method")
        
    def execute_process(self, process_id: str) -> bool:
        """Execute a production process.
        
        Returns:
            bool: True if process was executed successfully, False otherwise
        """
        if not hasattr(self.actor, 'sim') or not self.actor.sim:
            return False
            
        process = self.actor.sim.process_registry.get_process(process_id)
        if not process:
            return False
            
        # Check if actor has required inputs
        for commodity, quantity in process.inputs.items():
            if not self.actor.inventory.has_quantity(commodity, quantity):
                return False
                
        # Check if actor has required tools
        for tool in process.tools_required:
            if not self.actor.inventory.has_quantity(tool, 1):
                return False
                
        # Check if actor has access to required facilities in their inventory
        for facility in process.facilities_required:
            if not self.actor.inventory.has_quantity(facility, 1):
                return False
        
        # Consume inputs
        for commodity, quantity in process.inputs.items():
            self.actor.inventory.remove_commodity(commodity, quantity)
            
        # Add outputs
        for commodity, quantity in process.outputs.items():
            self.actor.inventory.add_commodity(commodity, quantity)
            
        # Record action
        self.actor.last_action = f"Executed process: {process.name}"
        return True


class ColonistBrain(ActorBrain):
    """Decision-making logic for regular colonist actors."""
    
    def decide_economic_action(self) -> None:
        """Decide which economic action to take this turn."""
        # First, try to satisfy basic needs (food)
        if not hasattr(self.actor, 'sim') or not self.actor.sim:
            return
            
        food_commodity = self.actor.sim.commodity_registry.get_commodity("food")
        biomass_commodity = self.actor.sim.commodity_registry.get_commodity("biomass")
        
        if not food_commodity or not biomass_commodity:
            return
            
        food_quantity = self.actor.inventory.get_quantity(food_commodity)
        if food_quantity < 5:
            # Try to make food
            if self.execute_process("make_food"):
                return
                
            # If can't make food directly, try to gather biomass
            biomass_quantity = self.actor.inventory.get_quantity(biomass_commodity)
            if biomass_quantity < 2 and self.execute_process("gather_biomass"):
                return
                
            # If we gathered biomass and now have enough, try to make food again
            if self.actor.inventory.get_quantity(biomass_commodity) >= 2 and self.execute_process("make_food"):
                return

        # Try to find the most profitable process
        if hasattr(self.actor, 'sim') and self.actor.sim and hasattr(self.actor.sim, 'process_registry'):
            market = self.actor.planet.market if self.actor.planet else None
            if market:
                best_process = self._find_most_profitable_process(market)
                
                # Execute the most profitable process if better than government work
                if best_process and self.execute_process(best_process.id):
                    return
        
        # If no processes can be executed, do government work
        self._do_government_work()
    
    def _find_most_profitable_process(self, market) -> Optional['ProcessDefinition']:
        """Find the most profitable process based on current market prices and available resources."""
        if not hasattr(self.actor, 'sim') or not self.actor.sim or not hasattr(self.actor.sim, 'process_registry'):
            return None
            
        best_process = None
        best_profit = 10  # Must exceed government work profit
        
        for process in self.actor.sim.process_registry.all_processes():
            # Calculate potential profit
            input_cost = 0
            for commodity_id, quantity in process.inputs.items():
                input_cost += market.get_avg_price(commodity_id) * quantity
                
            output_value = 0
            for commodity_id, quantity in process.outputs.items():
                output_value += market.get_avg_price(commodity_id) * quantity
                
            potential_profit = output_value - input_cost
            
            # Check if we can execute this process
            can_execute = True
            
            # Check if we have the inputs
            for commodity_id, quantity in process.inputs.items():
                if not self.actor.inventory.has_quantity(commodity_id, quantity):
                    can_execute = False
                    break
            
            # Check if we have the tools
            for tool_id in process.tools_required:
                if not self.actor.inventory.has_quantity(tool_id, 1):
                    can_execute = False
                    break
            
            # Check if we have access to required facilities in our inventory
            for facility_id in process.facilities_required:
                if not self.actor.inventory.has_quantity(facility_id, 1):
                    can_execute = False
                    break
            
            if can_execute and potential_profit > best_profit:
                best_process = process
                best_profit = potential_profit
        
        return best_process
    
    def should_produce_food(self) -> bool:
        """Decide whether to produce food or not."""
        # This method is kept for backward compatibility but is no longer used
        return False

    def _do_government_work(self) -> None:
        """Perform government work to earn a fixed wage."""
        wage = 10  # Fixed wage for government work (integer)
        self.actor.money += wage
        
        # Record action
        self.actor.last_action = f"Government work for {wage} credits"
    
    def decide_market_actions(self) -> None:
        """Regular actors buy what they need and sell excess, matching existing orders when possible."""
        if not self.actor.planet or not self.actor.planet.market:
            return
        
        market = self.actor.planet.market
        
        # Get existing actor's orders
        existing_orders = market.get_actor_orders(self.actor)
        
        # Cancel all existing orders
        for order in existing_orders["buy"] + existing_orders["sell"]:
            market.cancel_order(order.order_id)
        
        # Keep track of all market actions
        market_actions = []
        
        # Get commodity references
        food_commodity = None
        fuel_commodity = None
        
        if self.actor.sim and hasattr(self.actor.sim, 'commodity_registry'):
            food_commodity = self.actor.sim.commodity_registry.get_commodity("food")
            fuel_commodity = self.actor.sim.commodity_registry.get_commodity("nova_fuel")
        
        # Handle food trading
        if food_commodity:
            food_action = self._trade_commodity(market, food_commodity, min_keep=6)
            if food_action:
                market_actions.append(food_action)
        
        # Handle fuel trading - we don't need to keep any fuel for ourselves
        if fuel_commodity:
            fuel_action = self._trade_commodity(market, fuel_commodity, min_keep=0)
            if fuel_action:
                market_actions.append(fuel_action)
        
        # Update the actor's last market action summary
        if market_actions:
            self.actor.last_market_action = "; ".join(market_actions)
        else:
            self.actor.last_market_action = "No market actions"
    
    def _trade_commodity(self, market, commodity_type, min_keep=0):
        """Helper method to handle buying and selling of a specific commodity.
        
        Args:
            market: The market to trade in
            commodity_type: The type of commodity to trade
            min_keep: Minimum amount to keep in inventory
            
        Returns:
            String describing the market action taken or None
        """
        # Track inventory
        quantity = self.actor.inventory.get_quantity(commodity_type)
        available_inventory = self.actor.inventory.get_available_quantity(commodity_type)
        
        # Handle buying if we're below our minimum
        if quantity < min_keep:
            # Calculate how much we need
            quantity_to_buy = min_keep - quantity
            
            # Get existing sell orders in the market (excluding our own)
            market_sell_orders = sorted(
                [o for o in market.sell_orders.get(commodity_type, []) if o.actor != self.actor],
                key=lambda o: (o.price, o.timestamp)  # Sort by price (lowest first)
            )
            
            # Check if there are any sell orders available
            if market_sell_orders:
                # Start with the lowest price sell order
                best_sell_order = market_sell_orders[0]
                
                # Check if we can afford it
                max_affordable_quantity = min(
                    quantity_to_buy,
                    self.actor.money // best_sell_order.price
                )
                
                if max_affordable_quantity > 0:
                    # Place a matching buy order at exactly the seller's price
                    order_id = market.place_buy_order(
                        self.actor, commodity_type, max_affordable_quantity, best_sell_order.price
                    )
                    if order_id:
                        commodity_name = commodity_type.id if hasattr(commodity_type, 'id') else str(commodity_type)
                        self.actor.active_orders[order_id] = f"buy {commodity_name}"
                        return f"Buying {max_affordable_quantity} {commodity_name} at {best_sell_order.price}"
                else:
                    commodity_name = commodity_type.id if hasattr(commodity_type, 'id') else str(commodity_type)
                    return f"Can't afford {commodity_name} at {best_sell_order.price}"
            else:
                commodity_name = commodity_type.id if hasattr(commodity_type, 'id') else str(commodity_type)
                return f"No {commodity_name} sell orders available"
        
        # Handle selling if we have excess
        if available_inventory > min_keep:
            # Calculate how much we can sell
            quantity_to_sell = available_inventory - min_keep
            
            # Get existing buy orders in the market (excluding our own)
            market_buy_orders = sorted(
                [o for o in market.buy_orders.get(commodity_type, []) if o.actor != self.actor],
                key=lambda o: (-o.price, o.timestamp)  # Sort by price (highest first)
            )
            
            # Check if there are any buy orders available
            if market_buy_orders:
                # Start with the highest price buy order
                best_buy_order = market_buy_orders[0]
                
                # Accept any price - regular actors are price takers
                # Place a matching sell order at exactly the buyer's price
                order_id = market.place_sell_order(
                    self.actor, commodity_type, quantity_to_sell, best_buy_order.price
                )
                if order_id:
                    commodity_name = commodity_type.id if hasattr(commodity_type, 'id') else str(commodity_type)
                    self.actor.active_orders[order_id] = f"sell {commodity_name}"
                    return f"Selling {quantity_to_sell} {commodity_name} at {best_buy_order.price}"
            else:
                commodity_name = commodity_type.id if hasattr(commodity_type, 'id') else str(commodity_type)
                return f"No {commodity_name} buy orders available"
        
        return None


class MarketMakerBrain(ActorBrain):
    """Decision-making logic for market maker actors."""
    
    def __init__(self, actor: 'Actor') -> None:
        """Initialize the market maker brain."""
        super().__init__(actor)
        self.spread_percentage = random.uniform(0.1, 0.3)  # 10-30% spread
    
    def decide_economic_action(self) -> None:
        """Market makers only do government work."""
        self._do_government_work()
    
    def should_produce_food(self) -> bool:
        """Market makers don't produce food."""
        return False
    
    def _do_government_work(self) -> None:
        """Perform government work to earn a fixed wage."""
        wage = 10  # Fixed wage for government work (integer)
        self.actor.money += wage
        
        # Record action
        self.actor.last_action = f"Government work for {wage} credits"
    
    def decide_market_actions(self) -> None:
        """Market makers provide liquidity by placing both buy and sell orders based on inventory and market conditions."""
        if not self.actor.planet or not self.actor.planet.market:
            return

        market = self.actor.planet.market
        
        # Cancel all existing orders before creating new ones
        existing_orders = market.get_actor_orders(self.actor)
        for order in existing_orders["buy"] + existing_orders["sell"]:
            market.cancel_order(order.order_id)
        
        # Track overall actions
        all_buy_actions = []
        all_sell_actions = []
        
        # Get commodity definitions from registry
        if not hasattr(self.actor, 'sim') or not self.actor.sim:
            return
            
        food_commodity = self.actor.sim.commodity_registry.get_commodity("food")
        fuel_commodity = self.actor.sim.commodity_registry.get_commodity("nova_fuel")
        
        if not food_commodity or not fuel_commodity:
            return
            
        # Handle each commodity type
        for commodity_type in [food_commodity, fuel_commodity]:
            # Get market statistics (30-day moving averages)
            average_volume = market.get_30_day_average_volume(commodity_type)
            average_price = market.get_30_day_average_price(commodity_type)
            price_sigma = max(market.get_30_day_standard_deviation(commodity_type), 1.0)
    
            # Determine target inventory (30 days of volume + 1) and current inventory ratio
            current_inventory = self.actor.inventory.get_quantity(commodity_type)
            target_inventory = average_volume * 30 + 1
            inventory_ratio = current_inventory / target_inventory if target_inventory > 0 else 0
    
            # Calculate curve percentile
            curve_percentile = max(0.2, min(0.8, 1 - (0.5 * inventory_ratio)))
    
            from math import ceil, floor
            from scipy.stats import norm
    
            # Compute target prices using the inverse cumulative distribution
            target_sell_price = ceil(norm.ppf(curve_percentile, loc=average_price, scale=price_sigma))
            target_buy_price = floor(norm.ppf(curve_percentile, loc=average_price, scale=price_sigma))
            if target_buy_price <= 0:
                target_buy_price = 1
            if target_buy_price >= target_sell_price:
                target_sell_price = target_buy_price + 1
    
            buy_actions = []
            sell_actions = []
    
            if market.has_history(commodity_type):
                # --- Sell Orders ---
                # Only place sell orders if we have any inventory
                if current_inventory > 0:
                    MAX_SELL_ORDERS = 5  # Reduced to handle multiple commodities
                    curve_percentile_step = (1 - curve_percentile) / MAX_SELL_ORDERS
                    sell_percentiles = [curve_percentile + i * curve_percentile_step for i in range(MAX_SELL_ORDERS)]
                    # For each percentile, determine a price using the normal distribution inverse, ensuring a minimum price of 2.
                    sell_prices = [max(int(norm.ppf(p, loc=average_price, scale=price_sigma)) + 1, 2) for p in sell_percentiles]
                    target_order_size = ceil(current_inventory / MAX_SELL_ORDERS)
    
                    # Group orders by identical price (combine orders at the same price)
                    sell_price_counts = {}
                    for price in sell_prices:
                        sell_price_counts[price] = sell_price_counts.get(price, 0) + 1
    
                    amount_remaining = current_inventory
                    for price, count in sell_price_counts.items():
                        if amount_remaining <= 0:
                            break
                        order_size = min(amount_remaining, target_order_size * count)
                        amount_remaining -= order_size
                        order_id = market.place_sell_order(self.actor, commodity_type, order_size, price)
                        if order_id:
                            action = f"{commodity_type.id} {order_size}@{price}"
                            sell_actions.append(action)
                            all_sell_actions.append(action)
                            self.actor.active_orders[order_id] = f"sell {commodity_type.id}"
    
                # --- Buy Orders ---
                # Allocate 15% of funds per commodity (30% total for two commodities)
                allocated_funds = int(self.actor.money * 0.15)
                if allocated_funds > 0:
                    MAX_BUY_ORDERS = 5  # Reduced to handle multiple commodities
                    curve_percentile_step = curve_percentile / MAX_BUY_ORDERS
                    buy_percentiles = [curve_percentile - i * curve_percentile_step for i in range(MAX_BUY_ORDERS)]
                    # For each percentile, compute a price ensuring a minimum price of 1.
                    buy_prices = [max(int(norm.ppf(p, loc=average_price, scale=price_sigma)), 1) for p in buy_percentiles]
                    target_order_size = ceil(allocated_funds / target_buy_price) if target_buy_price > 0 else 0
    
                    # Group orders by identical price.
                    buy_price_counts = {}
                    for price in buy_prices:
                        buy_price_counts[price] = buy_price_counts.get(price, 0) + 1
    
                    funds_remaining = allocated_funds
                    for price, count in buy_price_counts.items():
                        if funds_remaining <= 0:
                            break
                        order_size = min(funds_remaining // price, target_order_size * count)
                        if order_size > 0:
                            funds_remaining -= order_size * price
                            order_id = market.place_buy_order(self.actor, commodity_type, order_size, price)
                            if order_id:
                                action = f"{commodity_type.id} {order_size}@{price}"
                                buy_actions.append(action)
                                all_buy_actions.append(action)
                                self.actor.active_orders[order_id] = f"buy {commodity_type.id}"
            else:
                # --- Bootstrapping Orders ---
                # In bootstrapping mode (market has no history)
                allocated_funds = int(self.actor.money * 0.15)
                for i in [1, 2, 4]:
                    if allocated_funds // i > 0:
                        order_id = market.place_buy_order(self.actor, commodity_type, 1, allocated_funds // i)
                        if order_id:
                            action = f"{commodity_type.id} 1@{allocated_funds // i}"
                            buy_actions.append(action)
                            all_buy_actions.append(action)
                            self.actor.active_orders[order_id] = f"buy {commodity_type.id}"

        # Update the actor's last market action summary.
        existing_orders = market.get_actor_orders(self.actor)
        buy_count = len(existing_orders["buy"])
        sell_count = len(existing_orders["sell"])
        buy_summary = ", ".join(all_buy_actions) if all_buy_actions else "none"
        sell_summary = ", ".join(all_sell_actions) if all_sell_actions else "none"
        self.actor.last_market_action = (
            f"Market maker: {buy_count} buy orders, {sell_count} sell orders - Buy [{buy_summary}], Sell [{sell_summary}]"
        )



class Actor:
    """Represents an economic actor in the simulation."""

    def __init__(
        self, 
        name: str, 
        planet: Optional[Planet] = None,
        actor_type: ActorType = ActorType.REGULAR,
        production_efficiency: float = 1.0,
        initial_money: int = 50
    ) -> None:
        self.name = name
        self.money = initial_money
        self.reserved_money = 0  # Money reserved for market orders
        self.planet = planet
        self.inventory = Inventory()
        self.actor_type = actor_type
        self.production_efficiency = production_efficiency  # Multiplier for production output
        self.market_history: List[Dict] = []  # Track this actor's market activity
        self.active_orders: Dict[str, str] = {}  # Track active order IDs and their types
        self.food_consumed_this_turn = False  # Track if actor has consumed food this turn
        self.last_action = "None"  # Track the last action performed
        self.last_market_action = "None"  # Track the last market action
        self.sim: Optional['Simulation'] = None  # Reference to the simulation
        
        # Give actor a brain based on type
        if actor_type == ActorType.MARKET_MAKER:
            self.money = 200  # Market makers start with more capital (integer)
            self.brain = MarketMakerBrain(self)
        else:
            self.brain = ColonistBrain(self)

    def take_turn(self) -> None:
        """Perform actions for this turn.

        Each turn consists of:
        1. Consume food
        2. One economic action (e.g., government work, production)
        3. Optional market actions
        """
        # Step 1: Consume food if available
        self._consume_food()
        
        # Step 2: Perform economic action
        self.brain.decide_economic_action()
        
        # Step 3: Perform market actions
        self.brain.decide_market_actions()

    def _consume_food(self) -> None:
        """Consume 1 unit of food per turn if available."""
        # Check if the actor has food in inventory
        if not self.sim or not hasattr(self.sim, 'commodity_registry'):
            self.food_consumed_this_turn = False
            return
            
        food_commodity = self.sim.commodity_registry.get_commodity("food")
        if not food_commodity:
            self.food_consumed_this_turn = False
            return
            
        # Try to consume from available food
        if self.inventory.has_quantity(food_commodity, 1):
            self.inventory.remove_commodity(food_commodity, 1)
            self.food_consumed_this_turn = True
            return
        
        # Check if there's reserved food
        reserved_food = self.inventory.get_reserved_quantity(food_commodity)
        if reserved_food > 0:
            # Unreserve 1 unit of food and consume it
            self.inventory.unreserve_commodity(food_commodity, 1)
            
            # Now the food should be available to consume
            if self.inventory.has_quantity(food_commodity, 1):
                self.inventory.remove_commodity(food_commodity, 1)
                self.food_consumed_this_turn = True
                return
        
        # If we get here, there's not enough food
        self.food_consumed_this_turn = False
        # In future tasks, we'll add consequences for not consuming food