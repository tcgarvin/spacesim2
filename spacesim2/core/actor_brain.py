import random
from typing import Optional, Dict, List, Union, Tuple, Any, TYPE_CHECKING
from math import ceil, floor

from scipy.stats import norm
from spacesim2.core.commands import EconomicCommand, MarketCommand, ProcessCommand, GovernmentWorkCommand, CancelOrderCommand, PlaceBuyOrderCommand, PlaceSellOrderCommand

if TYPE_CHECKING:
    from spacesim2.core.simulation import Simulation
    from spacesim2.core.process import ProcessDefinition
    from spacesim2.core.skill import Skill
    from spacesim2.core.actor import Actor
    from scipy.stats import norm


class ActorBrain:
    """Base class for actor decision making strategies."""
    
    def __init__(self, actor: 'Actor') -> None:
        """Initialize the brain with a reference to its actor."""
        self.actor = actor
    
    def decide_economic_action(self) -> Optional[EconomicCommand]:
        """Decide which economic action to take this turn."""
        raise NotImplementedError("Subclasses must implement this method")
    
    def decide_market_actions(self) -> List[MarketCommand]:
        """Decide what market actions to take this turn."""
        raise NotImplementedError("Subclasses must implement this method")
    
    def should_produce_food(self) -> bool:
        """Decide whether to produce food or do government work."""
        raise NotImplementedError("Subclasses must implement this method")
        


class ColonistBrain(ActorBrain):
    """Decision-making logic for regular colonist actors."""
    
    def decide_economic_action(self) -> Optional[EconomicCommand]:
        """Decide which economic action to take this turn."""
        # First, try to satisfy basic needs (food)
        # Actor always has sim reference
            
        food_commodity = self.actor.sim.commodity_registry.get_commodity("food")
        biomass_commodity = self.actor.sim.commodity_registry.get_commodity("biomass")
        
        if not food_commodity or not biomass_commodity:
            return GovernmentWorkCommand()
            
        food_quantity = self.actor.inventory.get_quantity(food_commodity)
        if food_quantity < 5:
            # Try to make food
            if self._can_execute_process("make_food"):
                return ProcessCommand("make_food")
                
            # If can't make food directly, try to gather biomass
            biomass_quantity = self.actor.inventory.get_quantity(biomass_commodity)
            if biomass_quantity < 2 and self._can_execute_process("gather_biomass"):
                return ProcessCommand("gather_biomass")

        # Try to find the most profitable process
        market = self.actor.planet.market if self.actor.planet else None
        if market:
            best_process = self._find_most_profitable_process(market)
            
            # Return the most profitable process if better than government work
            if best_process and self._can_execute_process(best_process.id):
                return ProcessCommand(best_process.id)
        
        # If no processes can be executed, do government work
        return GovernmentWorkCommand()
    
    def _find_most_profitable_process(self, market) -> Optional['ProcessDefinition']:
        """Find the most profitable process based on current market prices and available resources."""
        # Actor always has sim reference
            
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
            can_execute = self._can_execute_process(process.id)
            
            if can_execute and potential_profit > best_profit:
                best_process = process
                best_profit = potential_profit
        
        return best_process
    
    def _can_execute_process(self, process_id: str) -> bool:
        """Check if actor can execute a process without actually executing it."""
        # Actor always has sim reference
            
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
        
        return True
    
    def should_produce_food(self) -> bool:
        """Decide whether to produce food or not."""
        # This method is kept for backward compatibility but is no longer used
        return False
    
    def decide_market_actions(self) -> List[MarketCommand]:
        """Regular actors buy what they need and sell excess, matching existing orders when possible."""
        if not self.actor.planet:
            return []
        
        market = self.actor.planet.market
        commands = []
        
        # Get existing actor's orders
        existing_orders = market.get_actor_orders(self.actor)
        
        # Cancel all existing orders
        for order in existing_orders["buy"] + existing_orders["sell"]:
            commands.append(CancelOrderCommand(order.order_id))
        
        # Get commodity references
        # Actor always has sim reference
        food_commodity = self.actor.sim.commodity_registry["food"]
        fuel_commodity = self.actor.sim.commodity_registry["nova_fuel"]
        
        # Handle food trading
        food_commands = self._get_trade_commands(market, food_commodity, min_keep=6)
        commands.extend(food_commands)
        
        # Handle fuel trading - we don't need to keep any fuel for ourselves
        fuel_commands = self._get_trade_commands(market, fuel_commodity, min_keep=0)
        commands.extend(fuel_commands)
        
        return commands
    
    def _get_trade_commands(self, market, commodity_type, min_keep=0) -> List[MarketCommand]:
        """Helper method to generate trading commands for a specific commodity.
        
        Args:
            market: The market to trade in
            commodity_type: The type of commodity to trade
            min_keep: Minimum amount to keep in inventory
            
        Returns:
            List of MarketCommand objects for trading actions
        """
        commands = []
        
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
                    commands.append(PlaceBuyOrderCommand(
                        commodity_type, max_affordable_quantity, best_sell_order.price
                    ))
        
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
                commands.append(PlaceSellOrderCommand(
                    commodity_type, quantity_to_sell, best_buy_order.price
                ))
        
        return commands


class MarketMakerBrain(ActorBrain):
    """Decision-making logic for market maker actors."""
    
    def __init__(self, actor: 'Actor') -> None:
        """Initialize the market maker brain."""
        super().__init__(actor)
        self.spread_percentage = random.uniform(0.1, 0.3)  # 10-30% spread
    
    def decide_economic_action(self) -> Optional[EconomicCommand]:
        """Market makers only do government work."""
        return GovernmentWorkCommand()
    
    def should_produce_food(self) -> bool:
        """Market makers don't produce food."""
        return False
    
    def decide_market_actions(self) -> List[MarketCommand]:
        """Market makers provide liquidity by placing both buy and sell orders based on inventory and market conditions."""
        if not self.actor.planet:
            return []

        market = self.actor.planet.market
        commands = []
        
        # Cancel all existing orders before creating new ones
        existing_orders = market.get_actor_orders(self.actor)
        for order in existing_orders["buy"] + existing_orders["sell"]:
            commands.append(CancelOrderCommand(order.order_id))
        
        food_commodity = self.actor.sim.commodity_registry["food"]
        fuel_commodity = self.actor.sim.commodity_registry["nova_fuel"]
        
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
    
            
            # Compute target prices using the inverse cumulative distribution
            target_sell_price = ceil(norm.ppf(curve_percentile, loc=average_price, scale=price_sigma))
            target_buy_price = floor(norm.ppf(curve_percentile, loc=average_price, scale=price_sigma))
            if target_buy_price <= 0:
                target_buy_price = 1
            if target_buy_price >= target_sell_price:
                target_sell_price = target_buy_price + 1
    
    
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
                        commands.append(PlaceSellOrderCommand(commodity_type, order_size, price))
    
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
                            commands.append(PlaceBuyOrderCommand(commodity_type, order_size, price))
            else:
                # --- Bootstrapping Orders ---
                # In bootstrapping mode (market has no history)
                allocated_funds = int(self.actor.money * 0.15)
                for i in [1, 2, 4]:
                    if allocated_funds // i > 0:
                        commands.append(PlaceBuyOrderCommand(commodity_type, 1, allocated_funds // i))

        return commands