from dataclasses import dataclass
from typing import Dict, List

from spacesim2.core.actor import Actor


@dataclass
class Order:
    """Represents a buy or sell order in the market."""

    actor: Actor
    quantity: int
    price: float
    is_buy: bool  # True for buy order, False for sell order


class Market:
    """Represents a commodity market on a planet."""

    def __init__(self) -> None:
        # For Task 2, we'll have a single order book
        # In Task 3, we'll expand to multiple commodities
        self.buy_orders: List[Order] = []  # Bids
        self.sell_orders: List[Order] = []  # Asks
        self.transaction_history: List[Dict] = []  # Track completed trades

    def place_buy_order(self, actor: Actor, quantity: int, price: float) -> None:
        """Place a buy order (bid) in the market."""
        # For Task 2, just store the order with no matching logic
        order = Order(actor=actor, quantity=quantity, price=price, is_buy=True)
        self.buy_orders.append(order)

    def place_sell_order(self, actor: Actor, quantity: int, price: float) -> None:
        """Place a sell order (ask) in the market."""
        # For Task 2, just store the order with no matching logic
        order = Order(actor=actor, quantity=quantity, price=price, is_buy=False)
        self.sell_orders.append(order)

    def match_orders(self) -> None:
        """Match buy and sell orders if possible.

        For Task 2, this is just a placeholder for future implementation.
        """
        # This will be implemented in Task 3
        pass

    def clear_orders(self) -> None:
        """Clear all orders at the end of a turn."""
        self.buy_orders.clear()
        self.sell_orders.clear()
