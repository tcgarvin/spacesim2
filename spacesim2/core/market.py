import itertools
import random
import statistics
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Deque, Dict, List, Optional, Tuple, Union

from spacesim2.core.actor import Actor

if TYPE_CHECKING:
    from spacesim2.core.commodity import CommodityDefinition, CommodityRegistry
    from spacesim2.core.ship import Ship

# Anything that can place orders and trade in a market. Ships participate in
# markets via the same duck-typed interface as actors (name, money, inventory,
# active_orders, reserved_money).
MarketParticipant = Union[Actor, "Ship"]

# Scarcity pressure: a per-(market, commodity) signal that grows when local buy
# demand goes unfilled turn over turn (importers failing to serve this market)
# and decays when demand is met. Buyers use it to escalate bids toward their
# willingness-to-pay ceiling until supply arrives, which is what makes ships
# divert cargo to starved planets. Recurrence: p' = p*DECAY + STEP*unmet, so the
# fully-starved steady state is STEP/(1-DECAY) (clamped to MAX) and a served
# commodity decays geometrically back to zero.
SCARCITY_PRESSURE_STEP = 0.5
SCARCITY_PRESSURE_DECAY = 0.9
SCARCITY_PRESSURE_MAX = 3.0

# Bounded-history sizes. Consumers of price/volume history read at most a
# 30-turn window (get_30_day_*), a 10-turn flow window (FLOW_RECENCY_TURNS in
# navigation/ship planning), or just the last entry, so retaining the last
# HISTORY_KEEP entries is more than enough. Trimming happens only when a series
# exceeds HISTORY_TRIM_THRESHOLD, keeping the amortized cost per append O(1).
HISTORY_KEEP = 120
HISTORY_TRIM_THRESHOLD = 240

# Per-actor order-event retention. The only live consumer is the data logger's
# per-turn snapshot (Actor.get_market_activity_this_turn), which needs the
# current turn's events for one actor (~20 events/actor/turn at the high end).
# The deque bound exists purely to stop unbounded growth over long runs.
ORDER_EVENTS_PER_ACTOR = 100

# Global/per-actor transaction retention (unchanged policy from the historical
# per-turn trim: last 1000 market-wide, last 100 per actor name).
TRANSACTIONS_KEEP_GLOBAL = 1000
TRANSACTIONS_KEEP_PER_ACTOR = 100


# Monotonic order-id source. Cheap replacement for the former per-order uuid4;
# module-level so ids are unique across every market in the process. Lock-
# wrapped because the threaded actor phase (core/parallel.py) places orders
# from multiple threads; itertools.count alone is only atomic under the GIL.
class _LockedCounter:
    def __init__(self, start: int) -> None:
        self._it = itertools.count(start)
        self._lock = threading.Lock()

    def __next__(self) -> int:
        with self._lock:
            return next(self._it)


_ORDER_ID_COUNTER = _LockedCounter(1)


@dataclass
class Order:
    """Represents a buy or sell order in the market."""

    actor: MarketParticipant
    commodity_type: "CommodityDefinition"  # Must be a CommodityDefinition
    quantity: int
    price: int
    is_buy: bool  # True for buy order, False for sell order
    timestamp: int = 0  # For ordering when prices are the same
    order_id: str = ""  # Unique identifier for the order
    created_turn: int = 0  # Turn when order was created

    def __post_init__(self) -> None:
        """Generate a unique order ID if not provided."""
        if not self.order_id:
            self.order_id = str(next(_ORDER_ID_COUNTER))


@dataclass
class OrderEvent:
    """Represents an order lifecycle event."""

    order_id: str
    actor_name: str
    event_type: str  # "created", "filled", "cancelled"
    turn: int
    order: Order  # Direct reference to the order object


@dataclass
class Transaction:
    """Represents a completed transaction in the market."""

    buyer: MarketParticipant
    seller: MarketParticipant
    commodity_type: "CommodityDefinition"  # Must be a CommodityDefinition
    quantity: int
    price: int
    total_amount: int
    turn: int = 0  # The turn when this transaction occurred
    buy_order_id: Optional[str] = None  # Order ID for the buy order that was filled
    sell_order_id: Optional[str] = None  # Order ID for the sell order that was filled


class Market:
    """Represents a commodity market on a planet."""

    def __init__(self) -> None:
        # Order books for each commodity type
        self.buy_orders: Dict["CommodityDefinition", List[Order]] = defaultdict(list)
        self.sell_orders: Dict["CommodityDefinition", List[Order]] = defaultdict(list)

        # Track orders by ID for quick lookup
        self.orders_by_id: Dict[str, Order] = {}

        # Track orders by actor
        self.actor_orders: Dict[MarketParticipant, Dict[str, List[str]]] = defaultdict(
            lambda: {"buy": [], "sell": []}
        )

        # Track completed trades
        self.transaction_history: List[Transaction] = []
        self.actor_transaction_history: Dict[str, List[Transaction]] = defaultdict(list)

        # Track recent order lifecycle events per actor, bounded so long runs
        # cannot accumulate events (each event pins its Order object). The only
        # in-repo consumer reads the current turn's events for one actor via
        # get_actor_order_events, which ORDER_EVENTS_PER_ACTOR comfortably
        # covers. (The old market-wide chronological list had no readers and
        # was removed.)
        self.order_events_by_actor: Dict[str, Deque[OrderEvent]] = defaultdict(
            lambda: deque(maxlen=ORDER_EVENTS_PER_ACTOR)
        )

        # Track current turn for timestamping orders
        self.current_turn = 0

        # Track market statistics
        self.last_traded_prices: Dict["CommodityDefinition", List[int]] = defaultdict(
            list
        )

        # Extended market history (for sophisticated market makers)
        self.price_history: Dict["CommodityDefinition", List[int]] = defaultdict(
            list
        )  # All historical prices
        self.volume_history: Dict["CommodityDefinition", List[int]] = defaultdict(
            list
        )  # Daily trading volumes

        # Lifetime count of turns with nonzero traded volume per commodity.
        # Backs has_history() in O(1); the histories above are trimmed to a
        # recent window, so this counter is the durable record.
        self._active_volume_days: Dict["CommodityDefinition", int] = defaultdict(int)

        # Per-commodity scarcity pressure (see SCARCITY_PRESSURE_* constants).
        self.scarcity_pressure: Dict["CommodityDefinition", float] = defaultdict(float)

        # Per-turn cache of drive-bid reference anchors for never-traded goods
        # (commodity_id -> (turn, anchor)). Written and read by
        # ActorBrain._drive_bid_reference; imputing replacement cost recurses
        # over the process graph, far too hot to redo per actor per turn.
        self.drive_anchor_cache: Dict[str, Tuple[int, float]] = {}

        # Cache of (highest_bid, lowest_ask) per commodity for get_bid_ask_spread,
        # by far the hottest market read. Maintained INCREMENTALLY where cheap
        # and exact: placing an order can only improve the cached best (O(1)
        # max/min update); cancelling or filling an order only invalidates the
        # cache when the removed order sat at the cached best, in which case the
        # entry is dropped and lazily recomputed by one O(book) rescan on the
        # next read. This is mutation-tracked, NOT turn-scoped: orders placed
        # mid-turn are visible to later-acting actors (matching is deferred to
        # end of turn), so any per-turn cache would change behavior. The cached
        # value, when present, always equals the true best bid/ask.
        self._quote_cache: Dict[
            "CommodityDefinition", Tuple[Optional[int], Optional[int]]
        ] = {}

        # Sorted (price, quantity) bid levels per commodity, dropped on any
        # buy-book mutation (place/cancel/modify/match). Backs get_bid_levels:
        # ship planners call it repeatedly between mutations, so repeat calls
        # avoid a per-call re-sort of the book.
        self._bid_levels_cache: Dict["CommodityDefinition", List[Tuple[int, int]]] = {}

        # Reference to commodity registry (will be set by simulation)
        self.commodity_registry: Optional["CommodityRegistry"] = None

    def _trim_transaction_history(self) -> None:
        """Trim transaction histories in place (last 1000 global, 100 per actor).

        Uses ``del list[:-keep]`` rather than slice-and-copy so an untrimmed
        list costs only a length check and a trimmed one a single memmove.
        """
        if len(self.transaction_history) > TRANSACTIONS_KEEP_GLOBAL:
            del self.transaction_history[:-TRANSACTIONS_KEEP_GLOBAL]

        for actor_transactions in self.actor_transaction_history.values():
            if len(actor_transactions) > TRANSACTIONS_KEEP_PER_ACTOR:
                del actor_transactions[:-TRANSACTIONS_KEEP_PER_ACTOR]

    def get_actor_transaction_history(
        self, actor: MarketParticipant
    ) -> List[Transaction]:
        """Get the transaction history for a specific actor."""
        return self.actor_transaction_history.get(actor.name, [])

    def _record_order_event(self, event_type: str, order: Order) -> None:
        """Internal: record an order lifecycle event for the order's actor."""
        event = OrderEvent(
            order_id=order.order_id,
            actor_name=order.actor.name,
            event_type=event_type,
            turn=self.current_turn,
            order=order,
        )
        self.order_events_by_actor[order.actor.name].append(event)

    def get_actor_current_orders(self, actor: MarketParticipant) -> Dict[str, Dict]:
        """Market's authority: what orders are currently open for this actor."""
        result = {}

        # Get buy orders
        for order_id in self.actor_orders[actor]["buy"]:
            if order_id in self.orders_by_id:  # Still active
                order = self.orders_by_id[order_id]
                result[order_id] = {
                    "type": "buy",
                    "commodity": order.commodity_type.id,
                    "quantity": order.quantity,
                    "price": order.price,
                    "created_turn": order.created_turn,
                }

        # Get sell orders
        for order_id in self.actor_orders[actor]["sell"]:
            if order_id in self.orders_by_id:  # Still active
                order = self.orders_by_id[order_id]
                result[order_id] = {
                    "type": "sell",
                    "commodity": order.commodity_type.id,
                    "quantity": order.quantity,
                    "price": order.price,
                    "created_turn": order.created_turn,
                }

        return result

    def get_actor_order_events(
        self,
        actor: MarketParticipant,
        since_turn: int = 0,
        until_turn: Optional[int] = None,
    ) -> List[OrderEvent]:
        """Efficient time-range query for actor order events using chronological ordering.

        Retention is bounded (the most recent ORDER_EVENTS_PER_ACTOR events per
        actor), so queries reaching far into the past may be truncated; the
        current-turn window used by the data logger is always complete.
        """
        actor_events = self.order_events_by_actor[actor.name]

        if until_turn is None:
            until_turn = self.current_turn

        result = []
        # Use reverse iteration + early stopping for efficiency
        for event in reversed(actor_events):
            if event.turn < since_turn:
                break  # Stop - everything before is older
            if event.turn <= until_turn:
                result.append(event)

        return list(reversed(result))  # Return in chronological order

    def get_actor_transactions_range(
        self,
        actor: MarketParticipant,
        since_turn: int = 0,
        until_turn: Optional[int] = None,
    ) -> List[Transaction]:
        """Efficient time-range query for actor transactions using chronological ordering."""
        actor_transactions = self.actor_transaction_history[actor.name]

        if until_turn is None:
            until_turn = self.current_turn

        result = []
        # Use reverse iteration + early stopping for efficiency
        for transaction in reversed(actor_transactions):
            if transaction.turn < since_turn:
                break  # Stop - everything before is older
            if transaction.turn <= until_turn:
                result.append(transaction)

        return list(reversed(result))  # Return in chronological order

    def place_buy_order(
        self,
        actor: MarketParticipant,
        commodity_type: "CommodityDefinition",
        quantity: int,
        price: int,
    ) -> str:
        """Place a buy order (bid) in the market.

        Args:
            actor: The actor placing the order
            commodity_type: A CommodityDefinition object
            quantity: The quantity to buy
            price: The price per unit

        Returns:
            str: The order ID if placed successfully, empty string otherwise.
        """
        # Price is already an integer

        # Verify the actor has enough money to cover the potential transaction
        total_cost = quantity * price
        if actor.money < total_cost:
            # Adjust quantity based on available money, and recompute the cost
            # for the clamped quantity — reserving the original cost would
            # drive the actor's money negative and orphan the difference in
            # reserved_money forever.
            quantity = int(actor.money / price) if price > 0 else 0
            total_cost = quantity * price

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
            created_turn=self.current_turn,
        )

        # Add order to various tracking collections
        self.buy_orders[commodity_type].append(order)
        self._on_buy_book_changed(commodity_type)
        cached = self._quote_cache.get(commodity_type)
        if cached is not None:
            best_bid, best_ask = cached
            if best_bid is None or price > best_bid:
                self._quote_cache[commodity_type] = (price, best_ask)
        self.orders_by_id[order.order_id] = order
        self.actor_orders[actor]["buy"].append(order.order_id)

        # Add to actor's active orders
        actor.active_orders[order.order_id] = f"buy {commodity_type.id}"

        # Record order creation event
        self._record_order_event("created", order)

        return order.order_id

    def place_sell_order(
        self,
        actor: MarketParticipant,
        commodity_type: "CommodityDefinition",
        quantity: int,
        price: int,
    ) -> str:
        """Place a sell order (ask) in the market.

        Args:
            actor: The actor placing the order
            commodity_type: A CommodityDefinition object
            quantity: The quantity to sell
            price: The price per unit

        Returns:
            str: The order ID if placed successfully, empty string otherwise.
        """
        # Price is already an integer

        # Verify the actor has enough of the commodity to sell
        available_quantity = actor.inventory.get_available_quantity(commodity_type)
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
            created_turn=self.current_turn,
        )

        # Add order to various tracking collections
        self.sell_orders[commodity_type].append(order)
        cached = self._quote_cache.get(commodity_type)
        if cached is not None:
            best_bid, best_ask = cached
            if best_ask is None or price < best_ask:
                self._quote_cache[commodity_type] = (best_bid, price)
        self.orders_by_id[order.order_id] = order
        self.actor_orders[actor]["sell"].append(order.order_id)

        # Add to actor's active orders
        actor.active_orders[order.order_id] = f"sell {commodity_type.id}"

        # Record order creation event
        self._record_order_event("created", order)

        return order.order_id

    def match_orders(self) -> None:
        """Match buy and sell orders for all commodities and update market history."""
        self._trim_transaction_history()

        # Process orders for all commodity types (both enum and string IDs)
        all_commodities = (
            set(list(self.buy_orders.keys()))
            .union(self.sell_orders.keys())
            .union(self.volume_history.keys())
        )

        # Process orders
        for commodity_type in all_commodities:
            buy_book = self.buy_orders.get(commodity_type)
            sell_book = self.sell_orders.get(commodity_type)

            # Capture buy demand standing before matching consumes it.
            requested_buy_qty = sum(o.quantity for o in buy_book) if buy_book else 0

            daily_volume = 0
            average_price_numerator = 0

            # Matching can only produce fills when both sides exist and the
            # best bid crosses the best ask; skipping the sort-and-scan
            # otherwise is behavior-neutral (an uncrossed book yields no
            # transactions, and order books are untouched by a no-fill match).
            if buy_book and sell_book:
                best_bid, best_ask = self.get_bid_ask_spread(commodity_type)
                if (
                    best_bid is not None
                    and best_ask is not None
                    and (best_bid >= best_ask)
                ):
                    before_count = len(self.transaction_history)
                    self._match_orders_for_commodity(commodity_type)

                    # Calculate volume and prices for this turn
                    for tx in self.transaction_history[before_count:]:
                        if tx.commodity_type == commodity_type:
                            daily_volume += tx.quantity
                            average_price_numerator += tx.total_amount

            self._update_scarcity_pressure(
                commodity_type, requested_buy_qty, daily_volume
            )

            price_series = self.price_history[commodity_type]
            volume_series = self.volume_history[commodity_type]
            if daily_volume > 0:
                volume_series.append(daily_volume)
                price_series.append(average_price_numerator // daily_volume)
                self._active_volume_days[commodity_type] += 1
            elif volume_series:
                # Append 0 volume and last known price
                volume_series.append(0)
                price_series.append(price_series[-1])

            # Keep the per-turn series bounded; consumers only read recent
            # windows (<=30 turns) or the latest entry. Trimming with del on
            # threshold keeps the amortized cost O(1) per turn.
            if len(volume_series) > HISTORY_TRIM_THRESHOLD:
                del volume_series[:-HISTORY_KEEP]
                del price_series[:-HISTORY_KEEP]

    def _match_orders_for_commodity(
        self, commodity_type: "CommodityDefinition"
    ) -> None:
        """Match buy and sell orders for a specific commodity."""
        # Sort buy orders by price (highest first) and timestamp (oldest
        # first). Exact (price, timestamp) ties are broken randomly each
        # matching pass: before order-churn pruning, brains reposted their
        # whole book every turn and the per-turn actor shuffle rotated those
        # ties; kept orders now sit at a fixed book position, so without the
        # random key the same actor would win a contested price level every
        # turn (measurably starving thin markets like medicine).
        buy_orders = sorted(
            self.buy_orders.get(commodity_type, []),
            key=lambda o: (-o.price, o.timestamp, random.random()),
        )

        # Sort sell orders by price (lowest first) and timestamp (oldest first)
        sell_orders = sorted(
            self.sell_orders.get(commodity_type, []),
            key=lambda o: (o.price, o.timestamp, random.random()),
        )

        # Index cursors into the sorted books; advancing a cursor is the O(1)
        # equivalent of the old list.pop(0) on a fully filled order.
        buy_index = 0
        sell_index = 0

        # Continue matching as long as there are both buy and sell orders
        while buy_index < len(buy_orders) and sell_index < len(sell_orders):
            buy_order = buy_orders[buy_index]
            sell_order = sell_orders[sell_index]

            # Check if the orders can be matched (bid >= ask)
            if buy_order.price >= sell_order.price:
                # Determine the transaction quantity
                quantity = min(buy_order.quantity, sell_order.quantity)

                # Use the lower of the two prices (sell price) for the transaction
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
                    sell_order=sell_order,
                )

                # Update the order quantities
                buy_order.quantity -= quantity
                sell_order.quantity -= quantity

                # Record the transaction price for market statistics
                self.last_traded_prices[commodity_type].append(transaction_price)

                # Keep only the last 10 prices for each commodity
                if len(self.last_traded_prices[commodity_type]) > 10:
                    self.last_traded_prices[commodity_type] = self.last_traded_prices[
                        commodity_type
                    ][-10:]

                # Handle filled orders
                if buy_order.quantity <= 0:
                    # Record filled event before removing
                    self._record_order_event("filled", buy_order)

                    # Remove from master order list
                    if buy_order.order_id in self.orders_by_id:
                        del self.orders_by_id[buy_order.order_id]

                    # Remove from actor's order list
                    buyer = buy_order.actor
                    if (
                        buyer in self.actor_orders
                        and buy_order.order_id in self.actor_orders[buyer]["buy"]
                    ):
                        self.actor_orders[buyer]["buy"].remove(buy_order.order_id)

                    # Remove from actor's tracking
                    if buy_order.order_id in buyer.active_orders:
                        del buyer.active_orders[buy_order.order_id]

                    # Advance past the filled order
                    buy_index += 1

                if sell_order.quantity <= 0:
                    # Record filled event before removing
                    self._record_order_event("filled", sell_order)

                    # Remove from master order list
                    if sell_order.order_id in self.orders_by_id:
                        del self.orders_by_id[sell_order.order_id]

                    # Remove from actor's order list
                    seller = sell_order.actor
                    if (
                        seller in self.actor_orders
                        and sell_order.order_id in self.actor_orders[seller]["sell"]
                    ):
                        self.actor_orders[seller]["sell"].remove(sell_order.order_id)

                    # Remove from actor's tracking
                    if sell_order.order_id in seller.active_orders:
                        del seller.active_orders[sell_order.order_id]

                    # Advance past the filled order
                    sell_index += 1
            else:
                # No more matches possible (highest bid < lowest ask)
                break

        # Update remaining orders
        self.buy_orders[commodity_type] = buy_orders[buy_index:]
        self.sell_orders[commodity_type] = sell_orders[sell_index:]
        self._quote_cache.pop(commodity_type, None)
        self._on_buy_book_changed(commodity_type)

    def _update_scarcity_pressure(
        self,
        commodity_type: "CommodityDefinition",
        requested_buy_qty: int,
        filled_volume: int,
    ) -> None:
        """Update the scarcity pressure for a commodity after matching.

        Grows when buy demand goes unfilled (no supply arriving), decays toward
        zero when demand is met or absent. See SCARCITY_PRESSURE_* constants.
        """
        pressure = self.scarcity_pressure[commodity_type]
        if requested_buy_qty <= 0:
            pressure *= SCARCITY_PRESSURE_DECAY
        else:
            unmet = 1.0 - min(filled_volume, requested_buy_qty) / requested_buy_qty
            pressure = (
                pressure * SCARCITY_PRESSURE_DECAY + SCARCITY_PRESSURE_STEP * unmet
            )
        self.scarcity_pressure[commodity_type] = max(
            0.0, min(SCARCITY_PRESSURE_MAX, pressure)
        )

    def scarcity_pressure_for(self, commodity_type: "CommodityDefinition") -> float:
        """Current scarcity pressure for a commodity (0 if never under-served)."""
        return self.scarcity_pressure[commodity_type]

    def _execute_transaction(
        self,
        buyer: MarketParticipant,
        seller: MarketParticipant,
        commodity_type: "CommodityDefinition",
        quantity: int,
        price: int,
        buy_order: Order,
        sell_order: Order,
    ) -> None:
        """Execute a transaction between two actors.

        Args:
            buyer: The actor buying the commodity
            seller: The actor selling the commodity
            commodity_type: The commodity being traded
            quantity: The quantity being traded
            price: The price per unit
            buy_order: The buy order (if any)
            sell_order: The sell order (if any)
        """
        # Handle commodity transfer first to determine actual quantity
        actual_quantity = quantity  # Track the actual quantity being transferred

        if sell_order:
            # For sell orders, we need to unreserve the commodity (which makes it available again)
            # and then remove it from the seller's inventory
            reserved_quantity = min(
                quantity, seller.inventory.get_reserved_quantity(commodity_type)
            )
            if reserved_quantity < quantity:
                # This should not happen, but log it if it does
                actual_quantity = reserved_quantity
                print(
                    f"WARNING: Reserved quantity ({reserved_quantity}) less than transfer quantity ({quantity})"
                )

            # First unreserve the commodity (moves from reserved to available)
            seller.inventory.unreserve_commodity(commodity_type, actual_quantity)

            # Then remove from available inventory
            if not seller.inventory.remove_commodity(commodity_type, actual_quantity):
                print(
                    f"ERROR: Failed to remove {actual_quantity} of {commodity_type.id} from seller inventory"
                )
                actual_quantity = 0
        else:
            # Immediate transaction - remove directly from available inventory
            if not seller.inventory.remove_commodity(commodity_type, quantity):
                # This should not happen, but log it if it does
                print(
                    f"ERROR: Failed to remove {quantity} of {commodity_type.id} from seller inventory"
                )
                actual_quantity = 0

        # Calculate the actual price based on the quantity that was transferred
        total_amount = actual_quantity * price

        # Handle money transfers differently based on whether order exists
        if buy_order:
            # Money is already reserved - adjust from reserved to spent
            # Calculate the exact amount to unreserve based on the actual quantity transferred
            reserved_amount = min(
                actual_quantity * buy_order.price, buyer.reserved_money
            )
            buyer.reserved_money -= reserved_amount

            # If transaction price differs from order price, adjust the difference
            price_diff = buy_order.price - price
            if price_diff > 0 and actual_quantity > 0:
                # Buyer pays less than reserved, return the difference
                refund = actual_quantity * price_diff
                buyer.money += refund
        else:
            # Immediate transaction - reduce available money
            buyer.money -= total_amount

        # Add money to seller (always goes to available money)
        seller.money += total_amount

        # Add commodity to buyer (only the amount actually taken from seller)
        buyer.inventory.add_commodity(commodity_type, actual_quantity)

        # Record the transaction (with the actual quantity transferred)
        transaction = Transaction(
            buyer=buyer,
            seller=seller,
            commodity_type=commodity_type,
            quantity=actual_quantity,
            price=price,
            total_amount=total_amount,
            turn=self.current_turn,
            buy_order_id=buy_order.order_id,
            sell_order_id=sell_order.order_id,
        )
        self.transaction_history.append(transaction)
        self.actor_transaction_history[buyer.name].append(transaction)
        self.actor_transaction_history[seller.name].append(transaction)

    def get_avg_price(self, commodity_type: "CommodityDefinition") -> int:
        """Get the average price for a commodity based on recent transactions."""
        prices = self.last_traded_prices.get(commodity_type, [])
        if not prices:
            # If no recent trades, use the price history or a default base price
            if (
                commodity_type in self.price_history
                and self.price_history[commodity_type]
            ):
                return self.price_history[commodity_type][-1]

            # Use a default price of 10 if no history exists
            return 10

        # Equivalent to int(statistics.mean(prices)) for the non-negative int
        # prices stored here, but avoids statistics' exact-Fraction arithmetic,
        # which dominated the profile on these tiny lists.
        return sum(prices) // len(prices)

    def has_price_signal(self, commodity_type: "CommodityDefinition") -> bool:
        """Whether a real trade has ever set a price for ``commodity_type``.

        ``get_avg_price`` returns a hardcoded default of 10 for never-traded
        goods, which is indistinguishable from a genuine ~10 market price.
        Callers that must not trust that fabricated default (e.g. imputed
        replacement-cost procurement) use this to tell the two apart. True only
        when ``last_traded_prices`` or ``price_history`` holds real data, both
        of which are populated exclusively when a transaction clears.
        """
        if self.last_traded_prices.get(commodity_type):
            return True
        return bool(self.price_history.get(commodity_type))

    def get_bid_ask_spread(
        self, commodity_type: "CommodityDefinition"
    ) -> Tuple[Optional[int], Optional[int]]:
        """Get the current highest bid and lowest ask for a commodity."""
        cached = self._quote_cache.get(commodity_type)
        if cached is not None:
            return cached

        buy_orders = self.buy_orders.get(commodity_type, [])
        sell_orders = self.sell_orders.get(commodity_type, [])

        highest_bid = max((o.price for o in buy_orders), default=None)
        lowest_ask = min((o.price for o in sell_orders), default=None)

        result = (highest_bid, lowest_ask)
        self._quote_cache[commodity_type] = result
        return result

    def _on_buy_book_changed(self, commodity_type: "CommodityDefinition") -> None:
        """Internal: note a buy-book mutation, invalidating the bid-levels cache."""
        self._bid_levels_cache.pop(commodity_type, None)

    def get_bid_levels(
        self, commodity_type: "CommodityDefinition"
    ) -> List[Tuple[int, int]]:
        """Resting buy orders as (price, quantity) pairs, best price first.

        Lets planners see bid DEPTH, not just the top of book: selling more
        units than the book holds at acceptable prices means walking down the
        levels (or not filling at all), so revenue projected from the top bid
        alone systematically overestimates.

        The sorted levels are cached until the next buy-book mutation: ship
        planners call this many times per turn between mutations, so repeat
        calls cost one list copy instead of a re-sort.
        """
        cached = self._bid_levels_cache.get(commodity_type)
        if cached is None:
            cached = [
                (o.price, o.quantity) for o in self.buy_orders.get(commodity_type, [])
            ]
            cached.sort(key=lambda level: -level[0])
            self._bid_levels_cache[commodity_type] = cached
        return list(cached)

    def get_30_day_average_price(self, commodity_type: "CommodityDefinition") -> float:
        """Get the 30-day moving average price for a commodity."""
        prices = self.price_history.get(commodity_type, [])
        if not prices:
            return 10.0  # Default base price

        # Take the last 30 days (or as many as we have)
        recent_prices = prices[-30:] if len(prices) >= 30 else prices
        return sum(recent_prices) / len(recent_prices) if recent_prices else 10.0

    def get_30_day_average_volume(self, commodity_type: "CommodityDefinition") -> float:
        """Get the 30-day moving average trading volume for a commodity."""
        volumes = self.volume_history.get(commodity_type, [])
        if not volumes:
            return 1.0  # Default to 1 unit if no history

        # Take the last 30 days (or as many as we have)
        recent_volumes = volumes[-30:] if len(volumes) >= 30 else volumes
        return sum(recent_volumes) / len(recent_volumes) if recent_volumes else 1.0

    def get_30_day_standard_deviation(
        self, commodity_type: "CommodityDefinition"
    ) -> float:
        """Get the standard deviation of prices over the last 30 days."""
        prices = self.price_history.get(commodity_type, [])
        if not prices or len(prices) < 2:  # Need at least 2 prices to calculate std dev
            # Default to 10% of average price or 1.0
            avg_price = self.get_30_day_average_price(commodity_type)
            return max(1.0, avg_price * 0.1)

        # Take the last 30 days (or as many as we have)
        recent_prices = prices[-30:] if len(prices) >= 30 else prices
        try:
            return statistics.stdev(recent_prices)
        except statistics.StatisticsError:
            return 1.0  # Default in case of error

    def has_history(self, commodity_type: "CommodityDefinition") -> bool:
        """Check if there is sufficient price history for sophisticated market making.

        True after the commodity has traded on at least 5 turns over the
        market's lifetime, answered in O(1) from a counter maintained as
        volume history is appended (the raw series is trimmed to a recent
        window, so it cannot be recounted).
        """
        return self._active_volume_days.get(commodity_type, 0) >= 5

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

        # Record order cancellation event before removing
        self._record_order_event("cancelled", order)

        # Removing this order only disturbs the cached best bid/ask when it
        # sat AT the cached best price; any other removal leaves the cached
        # quote exact, so the cache survives the common cancel-and-repost
        # churn of non-best orders.
        cached = self._quote_cache.get(commodity_type)
        if cached is not None:
            cached_bid, cached_ask = cached
            if order.price == (cached_bid if order.is_buy else cached_ask):
                self._quote_cache.pop(commodity_type, None)

        # Remove from orders by ID
        del self.orders_by_id[order_id]

        # Remove from order books
        if order.is_buy:
            buy_orders = self.buy_orders.get(commodity_type, [])
            self.buy_orders[commodity_type] = [
                o for o in buy_orders if o.order_id != order_id
            ]
            self._on_buy_book_changed(commodity_type)

            # Return reserved money to actor
            actor.reserved_money -= order.quantity * order.price
            actor.money += order.quantity * order.price

            # Remove from actor orders
            if actor in self.actor_orders:
                self.actor_orders[actor]["buy"].remove(order_id)

        else:  # Sell order
            sell_orders = self.sell_orders.get(commodity_type, [])
            self.sell_orders[commodity_type] = [
                o for o in sell_orders if o.order_id != order_id
            ]

            # Return reserved inventory to actor
            actor.inventory.unreserve_commodity(commodity_type, order.quantity)

            # Remove from actor orders
            if actor in self.actor_orders:
                self.actor_orders[actor]["sell"].remove(order_id)

        # Update actor's active orders
        if order_id in actor.active_orders:
            del actor.active_orders[order_id]

        return True

    def get_actor_orders(self, actor: MarketParticipant) -> Dict[str, List[Order]]:
        """Get all active orders for an actor.

        Args:
            actor: The actor to get orders for

        Returns:
            Dict with 'buy' and 'sell' keys, each containing a list of Order objects
        """
        result: dict[str, list[Order]] = {"buy": [], "sell": []}

        if actor not in self.actor_orders:
            return result

        for order_id in self.actor_orders[actor]["buy"]:
            if order_id in self.orders_by_id:
                result["buy"].append(self.orders_by_id[order_id])

        for order_id in self.actor_orders[actor]["sell"]:
            if order_id in self.orders_by_id:
                result["sell"].append(self.orders_by_id[order_id])

        return result
