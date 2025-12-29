import random
from typing import Optional, List, TYPE_CHECKING
from math import ceil, floor

from scipy.stats import norm
from spacesim2.core.actor_brain import ActorBrain
from spacesim2.core.commands import EconomicCommand, MarketCommand, GovernmentWorkCommand, CancelOrderCommand, PlaceBuyOrderCommand, PlaceSellOrderCommand

if TYPE_CHECKING:
    from spacesim2.core.actor import Actor


class MarketMakerBrain(ActorBrain):
    """Decision-making logic for market maker actors."""
    
    def __init__(self) -> None:
        """Initialize the market maker brain."""
        self.spread_percentage = random.uniform(0.1, 0.3)  # 10-30% spread
    
    def decide_economic_action(self, actor: 'Actor') -> Optional[EconomicCommand]:
        """Market makers only do government work."""
        return GovernmentWorkCommand()
    
    def decide_market_actions(self, actor: 'Actor') -> List[MarketCommand]:
        """Market makers provide liquidity by placing both buy and sell orders based on inventory and market conditions."""
        if not actor.planet:
            return []

        market = actor.planet.market
        commands = []
        
        # Cancel all existing orders before creating new ones
        existing_orders = market.get_actor_orders(actor)
        for order in existing_orders["buy"] + existing_orders["sell"]:
            commands.append(CancelOrderCommand(order.order_id))
        
        food_commodity = actor.sim.commodity_registry["food"]
        fuel_commodity = actor.sim.commodity_registry["nova_fuel"]
        fuel_ore_commodity = actor.sim.commodity_registry["nova_fuel_ore"]
        wood_commodity = actor.sim.commodity_registry["wood"]
        common_metal_commodity = actor.sim.commodity_registry["common_metal"]
        common_metal_ore_commodity = actor.sim.commodity_registry["common_metal_ore"]

        # Handle each commodity type (including intermediate goods to bootstrap supply chains)
        for commodity_type in [food_commodity, fuel_commodity, fuel_ore_commodity, wood_commodity, common_metal_commodity, common_metal_ore_commodity]:
            # Get market statistics (30-day moving averages)
            average_volume = market.get_30_day_average_volume(commodity_type)
            average_price = market.get_30_day_average_price(commodity_type)
            price_sigma = max(market.get_30_day_standard_deviation(commodity_type), 1.0)
    
            # Determine target inventory (30 days of volume + 1) and current inventory ratio
            current_inventory = actor.inventory.get_quantity(commodity_type)
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
                allocated_funds = int(actor.money * 0.15)
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
                allocated_funds = int(actor.money * 0.15)
                for i in [1, 2, 4]:
                    if allocated_funds // i > 0:
                        commands.append(PlaceBuyOrderCommand(commodity_type, 1, allocated_funds // i))

        return commands