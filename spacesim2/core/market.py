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


@dataclass
class Transaction:
    """Represents a completed transaction in the market."""

    buyer: Actor
    seller: Actor
    commodity_type: CommodityType
    quantity: int
    price: int
    total_amount: int


class Market:
    """Represents a commodity market on a planet."""

    def __init__(self) -> None:
        # Order books for each commodity type
        self.buy_orders: Dict[CommodityType, List[Order]] = defaultdict(list)
        self.sell_orders: Dict[CommodityType, List[Order]] = defaultdict(list)
        
        # Track completed trades
        self.transaction_history: List[Transaction] = []
        
        # Track current turn for timestamping orders
        self.current_turn = 0
        
        # Track market statistics
        self.last_traded_prices: Dict[CommodityType, List[int]] = defaultdict(list)

    def place_buy_order(
        self, actor: Actor, commodity_type: CommodityType, quantity: int, price: int
    ) -> None:
        """Place a buy order (bid) in the market."""
        # Price is already an integer
        
        # Verify the actor has enough money to cover the potential transaction
        total_cost = quantity * price
        if actor.money < total_cost:
            # Adjust quantity based on available money
            quantity = int(actor.money / price) if price > 0 else 0
            
        if quantity <= 0:
            return  # Cannot place order with zero or negative quantity
        
        order = Order(
            actor=actor, 
            commodity_type=commodity_type, 
            quantity=quantity, 
            price=price, 
            is_buy=True,
            timestamp=self.current_turn
        )
        self.buy_orders[commodity_type].append(order)

    def place_sell_order(
        self, actor: Actor, commodity_type: CommodityType, quantity: int, price: int
    ) -> None:
        """Place a sell order (ask) in the market."""
        # Price is already an integer
        
        # Verify the actor has enough of the commodity to sell
        available_quantity = actor.inventory.get_quantity(commodity_type)
        if available_quantity < quantity:
            quantity = available_quantity
            
        if quantity <= 0:
            return  # Cannot place order with zero or negative quantity
        
        order = Order(
            actor=actor, 
            commodity_type=commodity_type, 
            quantity=quantity, 
            price=price, 
            is_buy=False,
            timestamp=self.current_turn
        )
        self.sell_orders[commodity_type].append(order)

    def match_orders(self) -> None:
        """Match buy and sell orders for all commodities."""
        for commodity_type in set(list(self.buy_orders.keys()) + list(self.sell_orders.keys())):
            self._match_orders_for_commodity(commodity_type)

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
                    buy_order.actor, 
                    sell_order.actor, 
                    commodity_type, 
                    quantity, 
                    transaction_price
                )
                
                # Update the order quantities
                buy_order.quantity -= quantity
                sell_order.quantity -= quantity
                
                # Record the transaction price for market statistics
                self.last_traded_prices[commodity_type].append(transaction_price)
                
                # Keep only the last 10 prices for each commodity
                if len(self.last_traded_prices[commodity_type]) > 10:
                    self.last_traded_prices[commodity_type] = self.last_traded_prices[commodity_type][-10:]
                
                # Remove filled orders, keep partially filled ones
                if buy_order.quantity > 0:
                    buy_orders[0] = buy_order  # Update the order
                else:
                    buy_orders.pop(0)  # Remove the order
                    
                if sell_order.quantity > 0:
                    sell_orders[0] = sell_order  # Update the order
                else:
                    sell_orders.pop(0)  # Remove the order
            else:
                # No more matches possible (highest bid < lowest ask)
                break
                
        # Update remaining orders
        self.buy_orders[commodity_type] = buy_orders
        self.sell_orders[commodity_type] = sell_orders

    def _execute_transaction(
        self, buyer: Actor, seller: Actor, commodity_type: CommodityType, 
        quantity: int, price: int
    ) -> None:
        """Execute a transaction between two actors."""
        total_amount = quantity * price
        
        # Transfer money from buyer to seller
        buyer.money -= total_amount
        seller.money += total_amount
        
        # Transfer commodity from seller to buyer
        seller.inventory.remove_commodity(commodity_type, quantity)
        buyer.inventory.add_commodity(commodity_type, quantity)
        
        # Record the transaction
        transaction = Transaction(
            buyer=buyer,
            seller=seller,
            commodity_type=commodity_type,
            quantity=quantity,
            price=price,
            total_amount=total_amount
        )
        self.transaction_history.append(transaction)

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
    
    def set_current_turn(self, turn: int) -> None:
        """Update the current turn for timestamping new orders."""
        self.current_turn = turn

    def clear_orders(self) -> None:
        """Clear all orders at the end of a turn."""
        self.buy_orders.clear()
        self.sell_orders.clear()
