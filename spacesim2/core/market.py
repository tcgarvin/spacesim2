from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import statistics
from collections import defaultdict

from spacesim2.core.actor import Actor
from spacesim2.core.commodity import CommodityType


@dataclass
class Order:
    """Represents a buy or sell order in the market."""

    actor: Actor
    commodity_type: CommodityType
    quantity: int
    price: int
    is_buy: bool  # True for buy order, False for sell order
    timestamp: int = 0  # For ordering when prices are the same
    order_id: str = ""  # Unique identifier for the order
    created_turn: int = 0  # Turn when order was created
    
    def __post_init__(self):
        """Generate a unique order ID if not provided."""
        import uuid
        if not self.order_id:
            self.order_id = str(uuid.uuid4())[:8]  # Short UUID


@dataclass
class Transaction:
    """Represents a completed transaction in the market."""

    buyer: Actor
    seller: Actor
    commodity_type: CommodityType
    quantity: int
    price: int
    total_amount: int
    turn: int = 0  # The turn when this transaction occurred


class Market:
    """Represents a commodity market on a planet."""

    def __init__(self) -> None:
        # Order books for each commodity type
        self.buy_orders: Dict[CommodityType, List[Order]] = defaultdict(list)
        self.sell_orders: Dict[CommodityType, List[Order]] = defaultdict(list)
        
        # Track orders by ID for quick lookup
        self.orders_by_id: Dict[str, Order] = {}
        
        # Track orders by actor
        self.actor_orders: Dict[Actor, Dict[str, List[str]]] = defaultdict(lambda: {"buy": [], "sell": []})
        
        # Track completed trades
        self.transaction_history: List[Transaction] = []
        
        # Track current turn for timestamping orders
        self.current_turn = 0
        
        # Track market statistics
        self.last_traded_prices: Dict[CommodityType, List[int]] = defaultdict(list)
        
        # Extended market history (for sophisticated market makers)
        self.price_history: Dict[CommodityType, List[int]] = defaultdict(list)  # All historical prices
        self.volume_history: Dict[CommodityType, List[int]] = defaultdict(list)  # Daily trading volumes

    def place_buy_order(
        self, actor: Actor, commodity_type: CommodityType, quantity: int, price: int
    ) -> str:
        """Place a buy order (bid) in the market.
        
        Returns:
            str: The order ID if placed successfully, empty string otherwise.
        """
        # Price is already an integer
        
        # Verify the actor has enough money to cover the potential transaction
        total_cost = quantity * price
        if actor.money < total_cost:
            # Adjust quantity based on available money
            quantity = int(actor.money / price) if price > 0 else 0
            
        if quantity <= 0:
            return ""  # Cannot place order with zero or negative quantity
        
        # Reserve the funds from the actor for this order
        actor.money -= total_cost
        actor.reserved_money += total_cost
        
        order = Order(
            actor=actor, 
            commodity_type=commodity_type, 
            quantity=quantity, 
            price=price, 
            is_buy=True,
            timestamp=self.current_turn,
            created_turn=self.current_turn
        )
        
        # Add order to various tracking collections
        self.buy_orders[commodity_type].append(order)
        self.orders_by_id[order.order_id] = order
        self.actor_orders[actor]["buy"].append(order.order_id)
        
        # Add to actor's active orders
        actor.active_orders[order.order_id] = f"buy {commodity_type.name}"
        
        return order.order_id

    def place_sell_order(
        self, actor: Actor, commodity_type: CommodityType, quantity: int, price: int
    ) -> str:
        """Place a sell order (ask) in the market.
        
        Returns:
            str: The order ID if placed successfully, empty string otherwise.
        """
        # Price is already an integer
        
        # Verify the actor has enough of the commodity to sell
        available_quantity = actor.inventory.get_quantity(commodity_type)
        if available_quantity < quantity:
            quantity = available_quantity
            
        if quantity <= 0:
            return ""  # Cannot place order with zero or negative quantity
        
        # Reserve the commodity from the actor's inventory
        actor.inventory.reserve_commodity(commodity_type, quantity)
        
        order = Order(
            actor=actor, 
            commodity_type=commodity_type, 
            quantity=quantity, 
            price=price, 
            is_buy=False,
            timestamp=self.current_turn,
            created_turn=self.current_turn
        )
        
        # Add order to various tracking collections
        self.sell_orders[commodity_type].append(order)
        self.orders_by_id[order.order_id] = order
        self.actor_orders[actor]["sell"].append(order.order_id)
        
        # Add to actor's active orders
        actor.active_orders[order.order_id] = f"sell {commodity_type.name}"
        
        return order.order_id

    def match_orders(self) -> None:
        """Match buy and sell orders for all commodities and update market history."""
        # Record daily volumes for each commodity
        daily_volumes = defaultdict(int)
        daily_prices = defaultdict(list)
        
        # Process orders
        for commodity_type in set(list(self.buy_orders.keys()) + list(self.sell_orders.keys())):
            before_count = len(self.transaction_history)
            self._match_orders_for_commodity(commodity_type)
            after_count = len(self.transaction_history)
            
            # Calculate volume and prices for this turn
            new_transactions = self.transaction_history[before_count:after_count]
            for tx in new_transactions:
                if tx.commodity_type == commodity_type:
                    daily_volumes[commodity_type] += tx.quantity
                    daily_prices[commodity_type].append(tx.price)
        
        # Update history
        for commodity_type, volume in daily_volumes.items():
            self.volume_history[commodity_type].append(volume)
            
            # Average price for the day (or base price if no trades)
            if daily_prices[commodity_type]:
                avg_daily_price = int(statistics.mean(daily_prices[commodity_type]))
                self.price_history[commodity_type].append(avg_daily_price)
            elif self.price_history.get(commodity_type):
                # If no trades today but we have history, use the last price
                self.price_history[commodity_type].append(self.price_history[commodity_type][-1])
            else:
                # No trades ever, use base price
                self.price_history[commodity_type].append(CommodityType.get_base_price(commodity_type))

    def _match_orders_for_commodity(self, commodity_type: CommodityType) -> None:
        """Match buy and sell orders for a specific commodity."""
        # Sort buy orders by price (highest first) and timestamp (oldest first)
        buy_orders = sorted(
            self.buy_orders.get(commodity_type, []),
            key=lambda o: (-o.price, o.timestamp)
        )
        
        # Sort sell orders by price (lowest first) and timestamp (oldest first)
        sell_orders = sorted(
            self.sell_orders.get(commodity_type, []),
            key=lambda o: (o.price, o.timestamp)
        )
        
        # Match orders
        remaining_buy_orders = []
        remaining_sell_orders = []
        
        # Continue matching as long as there are both buy and sell orders
        while buy_orders and sell_orders:
            buy_order = buy_orders[0]
            sell_order = sell_orders[0]
            
            # Check if the orders can be matched (bid >= ask)
            if buy_order.price >= sell_order.price:
                # Determine the transaction quantity
                quantity = min(buy_order.quantity, sell_order.quantity)
                
                # Use the higher of the two prices (sell price) for the transaction
                # This is a very simple pricing model - could be improved
                transaction_price = sell_order.price
                
                # Process the transaction
                self._execute_transaction(
                    buyer=buy_order.actor, 
                    seller=sell_order.actor, 
                    commodity_type=commodity_type, 
                    quantity=quantity, 
                    price=transaction_price,
                    buy_order=buy_order,
                    sell_order=sell_order
                )
                
                # Update the order quantities
                buy_order.quantity -= quantity
                sell_order.quantity -= quantity
                
                # Record the transaction price for market statistics
                self.last_traded_prices[commodity_type].append(transaction_price)
                
                # Keep only the last 10 prices for each commodity
                if len(self.last_traded_prices[commodity_type]) > 10:
                    self.last_traded_prices[commodity_type] = self.last_traded_prices[commodity_type][-10:]
                
                # Handle filled orders
                if buy_order.quantity <= 0:
                    # Remove from master order list
                    if buy_order.order_id in self.orders_by_id:
                        del self.orders_by_id[buy_order.order_id]
                    
                    # Remove from actor's order list
                    buyer = buy_order.actor
                    if buyer in self.actor_orders and buy_order.order_id in self.actor_orders[buyer]["buy"]:
                        self.actor_orders[buyer]["buy"].remove(buy_order.order_id)
                    
                    # Remove from actor's tracking
                    if buy_order.order_id in buyer.active_orders:
                        del buyer.active_orders[buy_order.order_id]
                    
                    # Remove from orders list
                    buy_orders.pop(0)
                
                if sell_order.quantity <= 0:
                    # Remove from master order list
                    if sell_order.order_id in self.orders_by_id:
                        del self.orders_by_id[sell_order.order_id]
                    
                    # Remove from actor's order list
                    seller = sell_order.actor
                    if seller in self.actor_orders and sell_order.order_id in self.actor_orders[seller]["sell"]:
                        self.actor_orders[seller]["sell"].remove(sell_order.order_id)
                    
                    # Remove from actor's tracking
                    if sell_order.order_id in seller.active_orders:
                        del seller.active_orders[sell_order.order_id]
                    
                    # Remove from orders list
                    sell_orders.pop(0)
            else:
                # No more matches possible (highest bid < lowest ask)
                break
                
        # Update remaining orders
        self.buy_orders[commodity_type] = buy_orders
        self.sell_orders[commodity_type] = sell_orders

    def _execute_transaction(
        self, buyer: Actor, seller: Actor, commodity_type: CommodityType, 
        quantity: int, price: int, buy_order: Order = None, sell_order: Order = None
    ) -> None:
        """Execute a transaction between two actors.
        
        Args:
            buyer: The actor buying the commodity
            seller: The actor selling the commodity
            commodity_type: The type of commodity being traded
            quantity: The quantity being traded
            price: The price per unit
            buy_order: The buy order (if any)
            sell_order: The sell order (if any)
        """
        total_amount = quantity * price
        
        # Handle money transfers differently based on whether order exists
        if buy_order:
            # Money is already reserved - adjust from reserved to spent
            # In case of partial fills, calculate the actual amount to unreserve
            reserved_amount = min(quantity * buy_order.price, buyer.reserved_money)
            buyer.reserved_money -= reserved_amount
        else:
            # Immediate transaction - reduce available money
            buyer.money -= total_amount
            
        # Add money to seller (always goes to available money)
        seller.money += total_amount
        
        # Handle commodity transfer differently based on whether order exists
        if sell_order and commodity_type in seller.inventory.reserved_commodities:
            # Commodity is already reserved - just reduce reservation, no transfer needed
            reserved_quantity = min(quantity, seller.inventory.reserved_commodities.get(commodity_type, 0))
            seller.inventory.reserved_commodities[commodity_type] -= reserved_quantity
            
            # Clean up if reserved is now zero
            if seller.inventory.reserved_commodities.get(commodity_type, 0) <= 0:
                del seller.inventory.reserved_commodities[commodity_type]
        else:
            # Immediate transaction - remove from available inventory
            seller.inventory.remove_commodity(commodity_type, quantity)
            
        # Add commodity to buyer (always goes to available inventory)
        buyer.inventory.add_commodity(commodity_type, quantity)
        
        # Record the transaction
        transaction = Transaction(
            buyer=buyer,
            seller=seller,
            commodity_type=commodity_type,
            quantity=quantity,
            price=price,
            total_amount=total_amount,
            turn=self.current_turn
        )
        self.transaction_history.append(transaction)
        
        # Update each actor's market history
        self._record_actor_transaction(buyer, transaction, "buy")
        self._record_actor_transaction(seller, transaction, "sell")
        
    def _record_actor_transaction(self, actor: Actor, transaction: Transaction, side: str) -> None:
        """Record a transaction in an actor's market history.
        
        Args:
            actor: The actor involved in the transaction
            transaction: The transaction
            side: 'buy' or 'sell'
        """
        actor.market_history.append({
            "turn": self.current_turn,
            "side": side,
            "commodity": transaction.commodity_type.name,
            "quantity": transaction.quantity,
            "price": transaction.price,
            "counterparty": transaction.seller.name if side == "buy" else transaction.buyer.name
        })

    def get_avg_price(self, commodity_type: CommodityType) -> int:
        """Get the average price for a commodity based on recent transactions."""
        prices = self.last_traded_prices.get(commodity_type, [])
        if not prices:
            # If no recent trades, use the base price as a fallback
            return CommodityType.get_base_price(commodity_type)
        return int(statistics.mean(prices))
    
    def get_bid_ask_spread(self, commodity_type: CommodityType) -> Tuple[Optional[int], Optional[int]]:
        """Get the current highest bid and lowest ask for a commodity."""
        buy_orders = self.buy_orders.get(commodity_type, [])
        sell_orders = self.sell_orders.get(commodity_type, [])
        
        highest_bid = max(buy_orders, key=lambda o: o.price).price if buy_orders else None
        lowest_ask = min(sell_orders, key=lambda o: o.price).price if sell_orders else None
        
        return highest_bid, lowest_ask
        
    def get_30_day_average_price(self, commodity_type: CommodityType) -> float:
        """Get the 30-day moving average price for a commodity."""
        prices = self.price_history.get(commodity_type, [])
        if not prices:
            return float(CommodityType.get_base_price(commodity_type))
        
        # Take the last 30 days (or as many as we have)
        recent_prices = prices[-30:] if len(prices) >= 30 else prices
        return statistics.mean(recent_prices) if recent_prices else float(CommodityType.get_base_price(commodity_type))
    
    def get_30_day_average_volume(self, commodity_type: CommodityType) -> float:
        """Get the 30-day moving average trading volume for a commodity."""
        volumes = self.volume_history.get(commodity_type, [])
        if not volumes:
            return 1.0  # Default to 1 unit if no history
        
        # Take the last 30 days (or as many as we have)
        recent_volumes = volumes[-30:] if len(volumes) >= 30 else volumes
        return statistics.mean(recent_volumes) if recent_volumes else 1.0
    
    def get_30_day_standard_deviation(self, commodity_type: CommodityType) -> float:
        """Get the standard deviation of prices over the last 30 days."""
        prices = self.price_history.get(commodity_type, [])
        if not prices or len(prices) < 2:  # Need at least 2 prices to calculate std dev
            return float(CommodityType.get_base_price(commodity_type)) * 0.1  # Default to 10% of base price
        
        # Take the last 30 days (or as many as we have)
        recent_prices = prices[-30:] if len(prices) >= 30 else prices
        try:
            return statistics.stdev(recent_prices)
        except statistics.StatisticsError:
            return float(CommodityType.get_base_price(commodity_type)) * 0.1
    
    def has_history(self, commodity_type: CommodityType = None) -> bool:
        """Check if there is sufficient price history for sophisticated market making."""
        if commodity_type is None:
            # Check if any commodity has history
            return any(len(prices) >= 5 for prices in self.price_history.values())
        
        return len(self.price_history.get(commodity_type, [])) >= 5
    
    def set_current_turn(self, turn: int) -> None:
        """Update the current turn for timestamping new orders."""
        self.current_turn = turn

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an existing order and release reserved resources.
        
        Args:
            order_id: The ID of the order to cancel
            
        Returns:
            bool: True if order was found and cancelled, False otherwise
        """
        if order_id not in self.orders_by_id:
            return False
            
        order = self.orders_by_id[order_id]
        actor = order.actor
        commodity_type = order.commodity_type
        
        # Remove from orders by ID
        del self.orders_by_id[order_id]
        
        # Remove from order books
        if order.is_buy:
            buy_orders = self.buy_orders.get(commodity_type, [])
            self.buy_orders[commodity_type] = [o for o in buy_orders if o.order_id != order_id]
            
            # Return reserved money to actor
            actor.reserved_money -= order.quantity * order.price
            actor.money += order.quantity * order.price
            
            # Remove from actor orders
            if actor in self.actor_orders:
                self.actor_orders[actor]["buy"].remove(order_id)
                
        else:  # Sell order
            sell_orders = self.sell_orders.get(commodity_type, [])
            self.sell_orders[commodity_type] = [o for o in sell_orders if o.order_id != order_id]
            
            # Return reserved inventory to actor
            actor.inventory.unreserve_commodity(commodity_type, order.quantity)
            
            # Remove from actor orders
            if actor in self.actor_orders:
                self.actor_orders[actor]["sell"].remove(order_id)
                
        # Update actor's active orders
        if order_id in actor.active_orders:
            del actor.active_orders[order_id]
            
        return True
        
    def modify_order(self, order_id: str, new_price: int) -> bool:
        """Modify an existing order's price.
        
        Args:
            order_id: The ID of the order to modify
            new_price: The new price for the order
            
        Returns:
            bool: True if order was found and modified, False otherwise
        """
        if order_id not in self.orders_by_id:
            return False
            
        order = self.orders_by_id[order_id]
        
        # For buy orders, we need to adjust reserved money
        if order.is_buy:
            actor = order.actor
            old_reserved = order.quantity * order.price
            new_reserved = order.quantity * new_price
            
            # Check if actor has enough money for the price increase
            if new_reserved > old_reserved:
                extra_needed = new_reserved - old_reserved
                if actor.money < extra_needed:
                    return False
                    
                # Adjust money and reserved money
                actor.money -= extra_needed
                actor.reserved_money += extra_needed
            elif old_reserved > new_reserved:
                # Return excess reserved money
                refund = old_reserved - new_reserved
                actor.reserved_money -= refund
                actor.money += refund
        
        # Update the price
        order.price = new_price
        order.timestamp = self.current_turn  # Reset timestamp for priority
        
        return True
        
    def get_actor_orders(self, actor: Actor) -> Dict[str, List[Order]]:
        """Get all active orders for an actor.
        
        Args:
            actor: The actor to get orders for
            
        Returns:
            Dict with 'buy' and 'sell' keys, each containing a list of Order objects
        """
        result = {"buy": [], "sell": []}
        
        if actor not in self.actor_orders:
            return result
            
        for order_id in self.actor_orders[actor]["buy"]:
            if order_id in self.orders_by_id:
                result["buy"].append(self.orders_by_id[order_id])
                
        for order_id in self.actor_orders[actor]["sell"]:
            if order_id in self.orders_by_id:
                result["sell"].append(self.orders_by_id[order_id])
                
        return result
        
    def clear_orders(self) -> None:
        """Clear all orders and release all reserved resources.
        
        WARNING: This should generally not be used with persistent orders.
        Use cancel_order instead to properly handle individual orders.
        """
        # Return all reserved resources first
        for order_id, order in self.orders_by_id.items():
            actor = order.actor
            
            if order.is_buy:
                # Return reserved money
                actor.reserved_money -= order.quantity * order.price
                actor.money += order.quantity * order.price
            else:
                # Return reserved inventory
                actor.inventory.unreserve_commodity(order.commodity_type, order.quantity)
                
            # Clear from actor's tracking
            if order_id in actor.active_orders:
                del actor.active_orders[order_id]
        
        # Clear all order collections
        self.buy_orders.clear()
        self.sell_orders.clear()
        self.orders_by_id.clear()
        self.actor_orders.clear()
