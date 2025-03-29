import random
from typing import Optional, Dict, List, Union, Tuple
import enum

from spacesim2.core.planet import Planet
from spacesim2.core.commodity import Inventory, CommodityType, Commodity


class ActorType(enum.Enum):
    """Types of actors in the simulation."""
    
    REGULAR = "regular"
    MARKET_MAKER = "market_maker"


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
        
        # Market maker settings
        if actor_type == ActorType.MARKET_MAKER:
            self.money = 200  # Market makers start with more capital (integer)
            self.spread_percentage = random.uniform(0.1, 0.3)  # 10-30% spread

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
        self._do_economic_action()
        
        # Step 3: Perform market actions
        self._do_market_actions()

    def _consume_food(self) -> None:
        """Consume 1 unit of food per turn if available."""
        food_type = CommodityType.RAW_FOOD
        
        # Check if enough food is available (not reserved)
        if self.inventory.has_quantity(food_type, 1):
            self.inventory.remove_commodity(food_type, 1)
            self.food_consumed_this_turn = True
        else:
            # If not enough available food but there's reserved food
            reserved_food = self.inventory.get_reserved_quantity(food_type)
            if reserved_food > 0:
                # Unreserve 1 unit of food and consume it
                self.inventory.unreserve_commodity(food_type, 1)
                
                # Now the food should be available to consume
                if self.inventory.has_quantity(food_type, 1):
                    self.inventory.remove_commodity(food_type, 1)
                    self.food_consumed_this_turn = True
                    return
            
            # If we get here, there's not enough food
            self.food_consumed_this_turn = False
            # In future tasks, we'll add consequences for not consuming food

    def _do_economic_action(self) -> None:
        """Perform a single economic action for this turn."""
        # Market makers don't produce, they only work for the man
        if self.actor_type == ActorType.MARKET_MAKER:
            self._do_government_work()
            return
        
        # Regular actors decide whether to produce food or do government work
        if self._should_produce_food():
            self._produce_food()
        else:
            self._do_government_work()

    def _should_produce_food(self) -> bool:
        """Decide whether to produce food or do government work."""
        # Simple logic: calculate potential profit vs. government wage
        food_price = 0.0
        if self.planet and self.planet.market:
            food_price = self.planet.market.get_avg_price(CommodityType.RAW_FOOD)
        
        # Get standard production quantity and apply efficiency
        standard_output = CommodityType.get_production_quantity(CommodityType.RAW_FOOD)
        actual_output = int(standard_output * self.production_efficiency)
        
        # Calculate potential profit
        production_cost = CommodityType.get_production_cost(CommodityType.RAW_FOOD)
        potential_profit = (actual_output * food_price) - production_cost
        
        # Government wage is fixed
        govt_wage = 10.0
        
        # Also consider if we need food for personal consumption
        need_food = self.inventory.get_quantity(CommodityType.RAW_FOOD) < 3
        
        # Produce if it's profitable or if we need food
        return potential_profit > govt_wage or need_food

    def _produce_food(self) -> None:
        """Produce raw food commodities."""
        # Calculate production output based on efficiency
        standard_output = CommodityType.get_production_quantity(CommodityType.RAW_FOOD)
        actual_output = int(standard_output * self.production_efficiency)
        
        # Add produced food to inventory
        self.inventory.add_commodity(CommodityType.RAW_FOOD, actual_output)
        
        # Record action
        self.last_action = f"Produced {actual_output} food"

    def _do_government_work(self) -> None:
        """Perform government work to earn a fixed wage."""
        wage = 10  # Fixed wage for government work (integer)
        self.money += wage
        
        # Record action
        self.last_action = f"Government work for {wage} credits"
        
    def _do_market_actions(self) -> None:
        """Perform market actions for this turn."""
        if not self.planet or not self.planet.market:
            return  # Can't trade without a market
            
        if self.actor_type == ActorType.MARKET_MAKER:
            self._do_market_maker_actions()
        else:
            self._do_regular_market_actions()

    def _do_regular_market_actions(self) -> None:
        """Regular actors buy what they need and sell excess, matching existing orders when possible."""
        if not self.planet or not self.planet.market:
            return
        
        market = self.planet.market
        commodity_type = CommodityType.RAW_FOOD
        
        # Get existing actor's orders
        existing_orders = market.get_actor_orders(self)
        buy_orders = existing_orders["buy"]
        sell_orders = existing_orders["sell"]
        
        # Track food inventory
        food_quantity = self.inventory.get_quantity(commodity_type)
        available_inventory = self.inventory.get_available_quantity(commodity_type)
        
        # Get current market price for reference
        food_price = market.get_avg_price(commodity_type)
        
        # Cancel existing buy orders if we have enough food now
        total_existing_buy_quantity = sum(order.quantity for order in buy_orders)
        if food_quantity + total_existing_buy_quantity >= 5 and buy_orders:
            for order in buy_orders:
                market.cancel_order(order.order_id)
            self.last_market_action = f"Canceled {len(buy_orders)} buy orders, now have enough food"
            
        # Cancel existing sell orders if we need the food now
        if food_quantity < 5 and sell_orders:
            for order in sell_orders:
                market.cancel_order(order.order_id)
            self.last_market_action = f"Canceled {len(sell_orders)} sell orders, need the food"
            
        # Refresh inventory and orders after cancellations
        available_inventory = self.inventory.get_available_quantity(commodity_type)
        existing_orders = market.get_actor_orders(self)
        buy_orders = existing_orders["buy"]
        sell_orders = existing_orders["sell"]
        
        # Check if we need to buy food (less than 6 units)
        if food_quantity < 6 and not buy_orders:
            # Calculate how much food we need
            quantity_to_buy = 6 - food_quantity
            
            # Get existing sell orders in the market (excluding our own)
            market_sell_orders = sorted(
                [o for o in market.sell_orders.get(commodity_type, []) if o.actor != self],
                key=lambda o: (o.price, o.timestamp)  # Sort by price (lowest first)
            )
            
            # Check if there are any sell orders available
            if market_sell_orders:
                # Start with the lowest price sell order
                best_sell_order = market_sell_orders[0]
                
                # Check if we can afford it
                max_affordable_quantity = min(
                    quantity_to_buy,
                    self.money // best_sell_order.price
                )
                
                if max_affordable_quantity > 0:
                    # Place a matching buy order at exactly the seller's price
                    order_id = market.place_buy_order(
                        self, commodity_type, max_affordable_quantity, best_sell_order.price
                    )
                    if order_id:
                        self.active_orders[order_id] = f"buy {commodity_type.name}"
                        self.last_market_action = f"Matched sell order price: buying {max_affordable_quantity} food at {best_sell_order.price} credits each"
                else:
                    # We can't afford any food at current prices - place a lower buy order
                    # Calculate a price we can afford
                    affordable_price = self.money // quantity_to_buy if quantity_to_buy > 0 else 0
                    
                    if affordable_price > 0:
                        order_id = market.place_buy_order(self, commodity_type, quantity_to_buy, affordable_price)
                        if order_id:
                            self.active_orders[order_id] = f"buy {commodity_type.name}"
                            self.last_market_action = f"Can't afford market price, placed buy order: {quantity_to_buy} food at {affordable_price} credits each"
            else:
                # No sell orders to match, place our own buy order
                # Calculate a reasonable price based on the last traded price or base price
                if self.money >= quantity_to_buy:
                    buy_price = max(int(food_price * 1.05), quantity_to_buy * 2)  # Slightly above market price
                    
                    # Make sure we don't spend all our money
                    max_affordable_quantity = min(quantity_to_buy, self.money // buy_price)
                    
                    if max_affordable_quantity > 0:
                        order_id = market.place_buy_order(self, commodity_type, max_affordable_quantity, buy_price)
                        if order_id:
                            self.active_orders[order_id] = f"buy {commodity_type.name}"
                            self.last_market_action = f"No matching sell orders, placed buy order: {max_affordable_quantity} food at {buy_price} credits each"
        
        # Check if we should sell excess food (more than 6 units)
        if available_inventory > 6 and not sell_orders:
            # Calculate how much food we can sell
            quantity_to_sell = available_inventory - 6
            
            # Get existing buy orders in the market (excluding our own)
            market_buy_orders = sorted(
                [o for o in market.buy_orders.get(commodity_type, []) if o.actor != self],
                key=lambda o: (-o.price, o.timestamp)  # Sort by price (highest first)
            )
            
            # Check if there are any buy orders available
            if market_buy_orders:
                # Start with the highest price buy order
                best_buy_order = market_buy_orders[0]
                
                # Calculate a reasonable minimum sell price
                min_sell_price = max(int(food_price * 0.9), 7)  # At least 90% of average price
                
                # Check if the best buy price is acceptable
                if best_buy_order.price >= min_sell_price:
                    # Place a matching sell order at exactly the buyer's price
                    order_id = market.place_sell_order(
                        self, commodity_type, quantity_to_sell, best_buy_order.price
                    )
                    if order_id:
                        self.active_orders[order_id] = f"sell {commodity_type.name}"
                        self.last_market_action = f"Matched buy order price: selling {quantity_to_sell} food at {best_buy_order.price} credits each"
                else:
                    # The best buy price is too low for us
                    # Place a sell order slightly below market price but above our minimum
                    sell_price = max(int(food_price * 0.95), min_sell_price)  # 95% of market price
                    
                    order_id = market.place_sell_order(self, commodity_type, quantity_to_sell, sell_price)
                    if order_id:
                        self.active_orders[order_id] = f"sell {commodity_type.name}"
                        self.last_market_action = f"Buy prices too low, placed sell order: {quantity_to_sell} food at {sell_price} credits each"
            else:
                # No buy orders to match, place our own sell order
                # Calculate a reasonable price based on the last traded price or base price
                sell_price = max(int(food_price * 0.95), 8)  # Slightly below market price
                
                order_id = market.place_sell_order(self, commodity_type, quantity_to_sell, sell_price)
                if order_id:
                    self.active_orders[order_id] = f"sell {commodity_type.name}"
                    self.last_market_action = f"No matching buy orders, placed sell order: {quantity_to_sell} food at {sell_price} credits each"

    def _do_market_maker_actions(self) -> None:
        """Market makers provide liquidity by placing both buy and sell orders based on inventory and market conditions."""
        if not self.planet or not self.planet.market:
            return
        
        market = self.planet.market
        commodity_type = CommodityType.RAW_FOOD
        
        # Get market statistics
        avg_price = market.get_avg_price(commodity_type)
        current_inventory = self.inventory.get_quantity(commodity_type)
        available_inventory = self.inventory.get_available_quantity(commodity_type)
        
        # Calculate available funds (money minus what's already reserved)
        available_funds = self.money
        
        # Get existing orders
        existing_orders = market.get_actor_orders(self)
        buy_orders = existing_orders["buy"]
        sell_orders = existing_orders["sell"]
        
        # Initialize market action tracking
        buy_actions = []
        sell_actions = []
        
        # Determine if we have sufficient market history to make informed decisions
        if market.has_history(commodity_type):
            # Implement sophisticated market making based on Kotlin example
            
            # 1. Calculate target inventory based on recent volume
            # Target = 30 days of average volume + 1 (like in Kotlin version)
            average_volume = market.get_30_day_average_volume(commodity_type)
            target_inventory = int(average_volume * 30) + 1
            
            # 2. Calculate inventory ratio (current vs target)
            inventory_ratio = current_inventory / target_inventory if target_inventory > 0 else 0
            
            # 3. Calculate price adjustment based on inventory
            # Use a curve where we sell at higher prices when inventory is high
            # and buy at higher prices when inventory is low
            
            # Adjust curve percentile based on inventory ratio (similar to Kotlin's logic)
            # Lower curve_percentile = higher buy prices, lower sell prices
            # Higher curve_percentile = lower buy prices, higher sell prices
            curve_percentile = max(0.1, min(0.9, 1 - (0.5 * inventory_ratio)))
            
            # Get price statistics from market history (like in Kotlin)
            average_price = market.get_30_day_average_price(commodity_type)
            price_sigma = max(market.get_30_day_standard_deviation(commodity_type), 1.0)
            
            # Calculate price points using price_sigma as a measure of volatility
            # Higher sigma = wider spread, lower sigma = tighter spread
            # This approximates the normal distribution approach in Kotlin
            target_buy_price = int(average_price - ((1 - curve_percentile) * price_sigma))
            target_sell_price = int(average_price + (curve_percentile * price_sigma))
            
            # Make sure buy and sell prices are distinct
            if target_buy_price >= target_sell_price:
                target_sell_price = target_buy_price + 1
                
            # Manage existing buy orders - cancel any that are too far from current market
            for order in buy_orders:
                # If the order is older than 5 turns or the price is significantly wrong, cancel it
                age = market.current_turn - order.created_turn
                price_diff_percent = abs(order.price - target_buy_price) / target_buy_price if target_buy_price > 0 else 0
                
                if age > 5 or price_diff_percent > 0.3:  # 30% price difference
                    market.cancel_order(order.order_id)
                    buy_actions.append(f"Canceled {order.quantity}@{order.price}")
            
            # Manage existing sell orders - cancel any that are too far from current market
            for order in sell_orders:
                # If the order is older than 5 turns or the price is significantly wrong, cancel it
                age = market.current_turn - order.created_turn
                price_diff_percent = abs(order.price - target_sell_price) / target_sell_price if target_sell_price > 0 else 0
                
                if age > 5 or price_diff_percent > 0.3:  # 30% price difference
                    market.cancel_order(order.order_id)
                    sell_actions.append(f"Canceled {order.quantity}@{order.price}")
                    
            # Refresh order lists after cancellations
            existing_orders = market.get_actor_orders(self)
            buy_orders = existing_orders["buy"]
            sell_orders = existing_orders["sell"]
            
            # Update available funds and inventory after cancellations
            available_funds = self.money
            available_inventory = self.inventory.get_available_quantity(commodity_type)
            
            # Calculate allocated funds for new orders (30% of available money)
            allocated_funds = int(available_funds * 0.3)
            
            # Create multiple buy orders at different price points
            if allocated_funds > 0:
                MAX_BUY_ORDERS = 5  # Like in Kotlin (simplified from 10)
                curve_percentile_step = curve_percentile / MAX_BUY_ORDERS
                
                buy_percentiles = [curve_percentile - (i * curve_percentile_step) for i in range(MAX_BUY_ORDERS)]
                buy_prices = [max(1, int(average_price - ((1 - p) * price_sigma))) for p in buy_percentiles]
                
                # Group prices to combine orders at the same price point
                buy_price_counts = {}
                for price in buy_prices:
                    buy_price_counts[price] = buy_price_counts.get(price, 0) + 1
                
                # Calculate order size based on allocated funds
                target_order_size = int(allocated_funds / sum(buy_price_counts.keys())) if buy_price_counts else 0
                
                # Place orders
                funds_remaining = allocated_funds
                for price, count in sorted(buy_price_counts.items(), key=lambda x: -x[0]):  # Higher prices first
                    if funds_remaining <= 0:
                        break
                        
                    # Skip if we already have an order at this price point
                    if any(o.price == price for o in buy_orders):
                        continue
                        
                    # Order size is proportional to the number of price points at this price
                    quantity = min(int(funds_remaining / price), target_order_size * count)
                    
                    if quantity > 0:
                        order_id = market.place_buy_order(self, commodity_type, quantity, price)
                        if order_id:  # Only track if order was actually placed
                            funds_remaining -= quantity * price
                            buy_actions.append(f"New {quantity}@{price}")
                            self.active_orders[order_id] = f"buy {commodity_type.name}"
            
            # Create multiple sell orders at different price points
            # Keep at least 3 units for own consumption for a few turns
            if available_inventory > 3:  
                MAX_SELL_ORDERS = 5  # Like in Kotlin (simplified from 10)
                sellable_inventory = available_inventory - 3
                
                curve_percentile_step = (1 - curve_percentile) / MAX_SELL_ORDERS
                sell_percentiles = [curve_percentile + (i * curve_percentile_step) for i in range(MAX_SELL_ORDERS)]
                sell_prices = [max(2, int(average_price + (p * price_sigma))) for p in sell_percentiles]
                
                # Group prices to combine orders at the same price point
                sell_price_counts = {}
                for price in sell_prices:
                    sell_price_counts[price] = sell_price_counts.get(price, 0) + 1
                
                # Calculate order size based on available inventory
                target_order_size = int(sellable_inventory / len(sell_price_counts)) if sell_price_counts else 0
                
                # Place orders
                inventory_remaining = sellable_inventory
                for price, count in sorted(sell_price_counts.items()):  # Lower prices first
                    if inventory_remaining <= 0:
                        break
                        
                    # Skip if we already have an order at this price point
                    if any(o.price == price for o in sell_orders):
                        continue
                        
                    # Order size is proportional to the number of price points at this price
                    quantity = min(inventory_remaining, target_order_size * count)
                    
                    if quantity > 0:
                        order_id = market.place_sell_order(self, commodity_type, quantity, price)
                        if order_id:  # Only track if order was actually placed
                            inventory_remaining -= quantity
                            sell_actions.append(f"New {quantity}@{price}")
                            self.active_orders[order_id] = f"sell {commodity_type.name}"
        else:
            # Bootstrapping mode - cancel existing orders first and start fresh
            for order in buy_orders + sell_orders:
                market.cancel_order(order.order_id)
                
            # Update available funds and inventory after cancellations
            available_funds = self.money
            available_inventory = self.inventory.get_available_quantity(commodity_type)
            
            # Calculate allocated funds for new orders (30% of available money)
            allocated_funds = int(available_funds * 0.3)
            
            # Simple buy orders at different price points
            base_price = CommodityType.get_base_price(commodity_type)
            
            # Place buy orders at 90%, 80%, 70% of base price
            for factor in [0.9, 0.8, 0.7]:
                buy_price = max(1, int(base_price * factor))
                buy_quantity = max(1, int(allocated_funds / (3 * buy_price)))
                
                if buy_quantity > 0:
                    order_id = market.place_buy_order(self, commodity_type, buy_quantity, buy_price)
                    if order_id:
                        buy_actions.append(f"New {buy_quantity}@{buy_price}")
                        self.active_orders[order_id] = f"buy {commodity_type.name}"
            
            # Place sell orders if we have inventory
            if available_inventory > 3:
                # Place sell orders at 110%, 120%, 130% of base price
                for factor in [1.1, 1.2, 1.3]:
                    sell_price = max(1, int(base_price * factor))
                    sell_quantity = max(1, int((available_inventory - 3) / 3))
                    
                    if sell_quantity > 0:
                        order_id = market.place_sell_order(self, commodity_type, sell_quantity, sell_price)
                        if order_id:
                            sell_actions.append(f"New {sell_quantity}@{sell_price}")
                            self.active_orders[order_id] = f"sell {commodity_type.name}"
        
        # Update last market action
        # Count existing orders
        existing_buy_count = len(existing_orders["buy"])
        existing_sell_count = len(existing_orders["sell"])
        
        buy_str = ", ".join(buy_actions) if buy_actions else "none"
        sell_str = ", ".join(sell_actions) if sell_actions else "none"
        self.last_market_action = f"Market maker: {existing_buy_count} buy orders, {existing_sell_count} sell orders - Buy [{buy_str}], Sell [{sell_str}]"