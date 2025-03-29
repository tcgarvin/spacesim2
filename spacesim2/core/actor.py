import random
from typing import Optional, Dict, List, Union, Tuple
import enum

from spacesim2.core.planet import Planet
from spacesim2.core.commodity import Inventory, CommodityType, Commodity


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


class ColonistBrain(ActorBrain):
    """Decision-making logic for regular colonist actors."""
    
    def decide_economic_action(self) -> None:
        """Decide whether to produce food or do government work."""
        if self.should_produce_food():
            self._produce_food()
        else:
            self._do_government_work()
    
    def should_produce_food(self) -> bool:
        """Decide whether to produce food or do government work."""
        # Simple logic: calculate potential profit vs. government wage
        food_price = 0.0
        if self.actor.planet and self.actor.planet.market:
            food_price = self.actor.planet.market.get_avg_price(CommodityType.RAW_FOOD)
        
        # Get standard production quantity and apply efficiency
        standard_output = CommodityType.get_production_quantity(CommodityType.RAW_FOOD)
        actual_output = int(standard_output * self.actor.production_efficiency)
        
        # Calculate potential profit
        production_cost = CommodityType.get_production_cost(CommodityType.RAW_FOOD)
        potential_profit = (actual_output * food_price) - production_cost
        
        # Government wage is fixed
        govt_wage = 10.0
        
        # Also consider if we need food for personal consumption
        need_food = self.actor.inventory.get_quantity(CommodityType.RAW_FOOD) < 3
        
        # Produce if it's profitable or if we need food
        return potential_profit > govt_wage or need_food
    
    def _produce_food(self) -> None:
        """Produce raw food commodities."""
        # Calculate production output based on efficiency
        standard_output = CommodityType.get_production_quantity(CommodityType.RAW_FOOD)
        actual_output = int(standard_output * self.actor.production_efficiency)
        
        # Add produced food to inventory
        self.actor.inventory.add_commodity(CommodityType.RAW_FOOD, actual_output)
        
        # Record action
        self.actor.last_action = f"Produced {actual_output} food"

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
        commodity_type = CommodityType.RAW_FOOD
        
        # Get existing actor's orders
        existing_orders = market.get_actor_orders(self.actor)
        buy_orders = existing_orders["buy"]
        sell_orders = existing_orders["sell"]
        
        # Track food inventory
        food_quantity = self.actor.inventory.get_quantity(commodity_type)
        available_inventory = self.actor.inventory.get_available_quantity(commodity_type)
        
        # Cancel existing buy orders
        for order in buy_orders:
            market.cancel_order(order.order_id)
            
        for order in sell_orders:
            market.cancel_order(order.order_id)
            
        # Refresh inventory and orders after cancellations
        available_inventory = self.actor.inventory.get_available_quantity(commodity_type)
        existing_orders = market.get_actor_orders(self.actor)
        buy_orders = existing_orders["buy"]
        sell_orders = existing_orders["sell"]
        
        # Check if we need to buy food (less than 6 units)
        if food_quantity < 30:
            # Calculate how much food we need
            quantity_to_buy = 6 - food_quantity
            
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
                        self.actor.active_orders[order_id] = f"buy {commodity_type.name}"
                        self.actor.last_market_action = f"Matched sell order price: buying {max_affordable_quantity} food at {best_sell_order.price} credits each"
                else:
                    # If we can't afford the market price, we don't place any order
                    self.actor.last_market_action = f"Can't afford market price of {best_sell_order.price}, no buy order placed"
            else:
                # No sell orders to match, we don't place any order until someone is selling
                self.actor.last_market_action = f"No sell orders available, waiting for market offers"
        
        # Check if we should sell excess food (more than 6 units)
        if available_inventory > 30:
            # Calculate how much food we can sell
            quantity_to_sell = available_inventory - 6
            
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
                    self.actor.active_orders[order_id] = f"sell {commodity_type.name}"
                    self.actor.last_market_action = f"Matched buy order price: selling {quantity_to_sell} food at {best_buy_order.price} credits each"
            else:
                # No buy orders to match, we don't place any order until someone is buying
                self.actor.last_market_action = f"No buy orders available, waiting for market offers"


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
        commodity_type = CommodityType.RAW_FOOD  # adjust as needed

        # Cancel all existing orders before creating new ones
        existing_orders = market.get_actor_orders(self.actor)
        for order in existing_orders["buy"] + existing_orders["sell"]:
            market.cancel_order(order.order_id)
            
        # Get market statistics (30-day moving averages)
        average_volume = market.get_30_day_average_volume(commodity_type)
        average_price = market.get_30_day_average_price(commodity_type)
        price_sigma = max(market.get_30_day_standard_deviation(commodity_type), 1.0)

        # Determine target inventory (30 days of volume + 1) and current inventory ratio
        current_inventory = self.actor.inventory.get_quantity(commodity_type)
        target_inventory = average_volume * 30 + 1
        inventory_ratio = current_inventory / target_inventory

        # Calculate curve percentile as in Kotlin:
        # curvePercentile = max(0.01, min(0.99, 1 - (0.5 * (current_inventory / target_inventory))))

        curve_percentile = max(0.2, min(0.8, 1 - (0.5 * inventory_ratio)))

        from math import ceil, floor
        from scipy.stats import norm

        # Compute target prices using the inverse cumulative distribution (similar to priceDist.inverseCumulativeProbability)
        target_sell_price = ceil(norm.ppf(curve_percentile, loc=average_price, scale=price_sigma))
        target_buy_price = floor(norm.ppf(curve_percentile, loc=average_price, scale=price_sigma))
        if target_buy_price <= 0:
            target_buy_price = 1
        if target_buy_price <= target_sell_price:
            target_sell_price = target_buy_price + 1

        buy_actions = []
        sell_actions = []

        if market.has_history(commodity_type):
            # --- Sell Orders ---
            # Only place sell orders if we have any inventory
            if current_inventory > 0:
                MAX_SELL_ORDERS = 10
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
                        sell_actions.append(f"New {order_size}@{price}")
                        self.actor.active_orders[order_id] = f"sell {commodity_type.name}"

            # --- Buy Orders ---
            # In Kotlin, funds are allocated separately. Here, we use 30% of available funds.
            allocated_funds = int(self.actor.money * 0.3)
            if allocated_funds > 0:
                MAX_BUY_ORDERS = 10
                curve_percentile_step = curve_percentile / MAX_BUY_ORDERS
                buy_percentiles = [curve_percentile - i * curve_percentile_step for i in range(MAX_BUY_ORDERS)]
                # For each percentile, compute a price ensuring a minimum price of 1.
                buy_prices = [max(int(norm.ppf(p, loc=average_price, scale=price_sigma)), 1) for p in buy_percentiles]
                target_order_size = ceil(allocated_funds / target_buy_price)

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
                            buy_actions.append(f"New {order_size}@{price}")
                            self.actor.active_orders[order_id] = f"buy {commodity_type.name}"
        else:
            # --- Bootstrapping Orders ---
            # In bootstrapping mode (market has no history), mimic Kotlin's bootstrappingOrders:
            # Only buy orders are placed at prices determined by dividing allocated funds by 1, 2, and 4.
            allocated_funds = int(self.actor.money * 0.3)
            # Note: We don't need to cancel orders here as they're already canceled at the beginning
            buy_actions = []
            for i in [1, 2, 4]:
                if allocated_funds // i > 0:
                    order_id = market.place_buy_order(self.actor, commodity_type, 1, allocated_funds // i)
                    if order_id:
                        buy_actions.append(f"New 1@{allocated_funds // i}")
                        self.actor.active_orders[order_id] = f"buy {commodity_type.name}"

        # Update the actor's last market action summary.
        existing_orders = market.get_actor_orders(self.actor)
        buy_count = len(existing_orders["buy"])
        sell_count = len(existing_orders["sell"])
        buy_summary = ", ".join(buy_actions) if buy_actions else "none"
        sell_summary = ", ".join(sell_actions) if sell_actions else "none"
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