import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Literal

from spacesim2.core.actor_brain import ActorBrain
from spacesim2.core.actor import Actor
from spacesim2.core.commands import PlaceBuyOrderCommand, PlaceSellOrderCommand, CancelOrderCommand, GovernmentWorkCommand, EconomicCommand, MarketCommand
from spacesim2.core.commodity import CommodityDefinition

# Assumed available from your codebase:
# - ActorBrain, Actor
# - PlaceBuyOrderCommand, PlaceSellOrderCommand, CancelOrderCommand
# - GovernmentWorkCommand
# - CommodityDefinition
# - EconomicCommand, MarketCommand

# ---- Your market fill record -------------------------------------------------

@dataclass
class Transaction:
    """Represents a completed transaction in the market."""
    buyer: 'Actor'
    seller: 'Actor'
    commodity_type: 'CommodityDefinition'  # Must be a CommodityDefinition
    quantity: int
    price: int
    total_amount: int
    turn: int = 0  # The turn when this transaction occurred


# ---- Maker internal state ----------------------------------------------------

Phase = Literal["DISCOVERY", "MAKER"]

@dataclass
class MarketMakerState:
    """
    Per-commodity state for the market maker.

    Discovery tracks a conservative price bracket [lower_bound, upper_bound].
    - If we BUY (our bid fills), sellers exist at ≤ price  -> tighten upper_bound.
    - If we SELL (our ask fills), buyers exist at ≥ price -> raise lower_bound.

    Once the bracket is tight enough (or enough trades observed), we compute a
    discovered midpoint and switch to MAKER mode.
    """
    phase: Phase = "DISCOVERY"

    # Conservative price bracket from observed fills
    lower_bound: int = 1                # buyers exist at ≥ lower_bound
    upper_bound: Optional[int] = None   # sellers exist at ≤ upper_bound

    # Last discovery quotes we placed (1-unit probes)
    last_bid_quote: Optional[int] = None
    last_ask_quote: Optional[int] = None

    # Last observed fill prices on each side (for transition checks)
    last_bid_filled_price: Optional[int] = None
    last_ask_filled_price: Optional[int] = None

    # Counters and regime info
    trades_seen: int = 0
    quiet_ticks: int = 0
    last_sigma: Optional[float] = None

    # Seed for maker mode (midpoint discovered during discovery phase)
    discovered_midpoint: Optional[int] = None


# ---- Market maker brain ------------------------------------------------------

class MarketMakerBrain(ActorBrain):
    """
    Liquidity-first market maker with:
      • No-defaults discovery (1-unit geometric probes) to establish a bracket.
      • Maker mode (mid ± spread ladder with light inventory skew).
      • Real fills via market.get_actor_transaction_history(actor) + cursor.

    Design goals: simplicity, readability, solvency, and stable liquidity.
    """

    # ----------------------------
    # Tunables (kept simple)
    # ----------------------------
    LADDER_LEVELS: int = 5                          # depth per side in MAKER
    CASH_ALLOC_PER_COMMODITY: float = 0.15          # fraction of wallet in maker mode
    VOLATILITY_WIDENER: float = 0.5                 # widen spread by (1 + VOL * sigma/mid)
    INVENTORY_SKEW_CAP: float = 0.10                # cap skew at ±10% of mid
    MAX_NOTIONAL_FRACTION: float = 0.60             # cap exposure vs. cash-only net worth
    MIN_ORDER_QUANTITY: int = 1

    # Discovery behavior
    DISCOVERY_CASH_FRACTION: float = 0.02           # 2% of wallet per tick for probes
    DISCOVERY_TIGHTNESS_EPSILON: int = 2            # switch to maker when U-L <= epsilon
    DISCOVERY_MIN_TRADES: int = 6                   # or after N total fills (any side)
    REVERT_IF_QUIET_TICKS: int = 50                 # revert to discovery if no fills for N ticks
    VOLATILITY_SPIKE_FACTOR: float = 3.0            # revert if sigma jumps ≥ factor×

    # Safety floors
    MIN_PRICE: int = 1
    MIN_ASK_PRICE: int = 2

    def __init__(self) -> None:
        super().__init__()
        # Randomized base spread percentage (now actually used)
        self.spread_percentage: float = random.uniform(0.10, 0.30)

        # Per-commodity state (by commodity name)
        self._state: Dict[str, MarketMakerState] = {}

        # Cursor into the actor's transaction history (acts like get_and_clear)
        self._last_transaction_index: int = 0

    # -------- Required interface ---------------------------------------------

    def decide_economic_action(self, actor:Actor) -> Optional['EconomicCommand']:
        """Market makers only do government work in your sim."""
        return GovernmentWorkCommand()

    def decide_market_actions(self, actor:Actor) -> List['MarketCommand']:
        """Primary decision loop: cancel old orders, ingest new fills, then quote."""
        if not actor.planet:
            return []

        market = actor.planet.market
        commands: List['MarketCommand'] = []

        # Simple cancel/replace (no fees + one maker → acceptable)
        existing_orders = market.get_actor_orders(actor)
        for order in existing_orders["buy"] + existing_orders["sell"]:
            commands.append(CancelOrderCommand(order.order_id))

        # Ingest NEW transactions and group by commodity + side
        new_fills_by_commodity = self._consume_new_transactions(actor, market)

        # Choose commodities (per your current world)
        food = actor.sim.commodity_registry["food"]
        fuel = actor.sim.commodity_registry["nova_fuel"]

        for commodity in (food, fuel):
            state = self._ensure_state_for(commodity)

            # Update state from real fills (tighten bracket, decide phase transitions)
            self._apply_fills_to_state(actor, commodity, state, new_fills_by_commodity)

            if state.phase == "DISCOVERY":
                commands.extend(self._discovery_quotes(actor, commodity, state))
            else:  # MAKER
                commands.extend(self._maker_quotes(actor, market, commodity, state))

        return commands

    # -------- Transaction ingestion ------------------------------------------

    def _consume_new_transactions(self, actor, market) -> Dict[str, Dict[str, List[int]]]:
        """
        Read the actor's full transaction history, slice out only the NEW items since
        the last tick, and group prices by commodity and our side of the trade.

        Returns:
            {
              "<commodity_name>": {
                "buy_prices":  [prices where WE bought],
                "sell_prices": [prices where WE sold]
              },
              ...
            }
        """
        history: List[Transaction] = market.get_actor_transaction_history(actor) or []

        # Handle any history resets conservatively
        if self._last_transaction_index > len(history):
            self._last_transaction_index = 0

        new_transactions = history[self._last_transaction_index:]
        self._last_transaction_index = len(history)

        grouped: Dict[str, Dict[str, List[int]]] = {}
        for txn in new_transactions:
            if txn.buyer is actor:
                side = "buy"
            elif txn.seller is actor:
                side = "sell"
            else:
                continue  # not our fill (shouldn't happen)

            commodity_name = getattr(txn.commodity_type, "name", str(txn.commodity_type))
            bucket = grouped.setdefault(commodity_name, {"buy_prices": [], "sell_prices": []})
            bucket["buy_prices" if side == "buy" else "sell_prices"].append(txn.price)

        return grouped

    def _apply_fills_to_state(
        self,
        actor:Actor,
        commodity: 'CommodityDefinition',
        state: MarketMakerState,
        fills_by_commodity: Dict[str, Dict[str, List[int]]],
    ) -> None:
        """Tighten discovery bracket and handle mode transitions or reversion."""
        commodity_name = getattr(commodity, "name", str(commodity))
        price_lists = fills_by_commodity.get(commodity_name, None)

        market = actor.planet.market
        sigma: Optional[float] = None
        if market.has_history(commodity):
            sigma = max(market.get_30_day_standard_deviation(commodity), 1.0)

        if state.phase == "DISCOVERY":
            if price_lists:
                # If we BOUGHT, sellers exist at ≤ max(buy_fills)  → tighten upper_bound
                if price_lists["buy_prices"]:
                    max_bid_fill = max(price_lists["buy_prices"])
                    state.upper_bound = max_bid_fill if state.upper_bound is None else min(state.upper_bound, max_bid_fill)
                    state.last_bid_filled_price = max_bid_fill
                    state.trades_seen += 1

                # If we SOLD, buyers exist at ≥ min(sell_fills) → raise lower_bound
                if price_lists["sell_prices"]:
                    min_ask_fill = min(price_lists["sell_prices"])
                    state.lower_bound = max(state.lower_bound, min_ask_fill)
                    state.last_ask_filled_price = min_ask_fill
                    state.trades_seen += 1

                # Transition to MAKER when bracket is tight or enough trades observed
                if state.last_bid_filled_price is not None and state.last_ask_filled_price is not None:
                    if (state.upper_bound is not None) and (state.upper_bound - state.lower_bound <= self.DISCOVERY_TIGHTNESS_EPSILON):
                        state.discovered_midpoint = (state.lower_bound + state.upper_bound) // 2
                        state.phase = "MAKER"
                    elif state.trades_seen >= self.DISCOVERY_MIN_TRADES:
                        # If we never observed an upper bound, synthesize from the last bid quote
                        synthetic_upper = (
                            state.upper_bound
                            if state.upper_bound is not None
                            else max(state.lower_bound + 1, (state.last_bid_quote or state.lower_bound + 1))
                        )
                        state.discovered_midpoint = (state.lower_bound + synthetic_upper) // 2
                        state.phase = "MAKER"

            state.last_sigma = sigma  # track regime for later spike detection

        else:  # MAKER
            any_fill = bool(price_lists and (price_lists["buy_prices"] or price_lists["sell_prices"]))
            state.quiet_ticks = 0 if any_fill else (state.quiet_ticks + 1)

            # Revert to discovery if quiet too long or volatility spikes sharply
            revert_to_discovery = False
            if state.quiet_ticks >= self.REVERT_IF_QUIET_TICKS:
                revert_to_discovery = True
            if sigma is not None and state.last_sigma is not None and sigma >= self.VOLATILITY_SPIKE_FACTOR * state.last_sigma:
                revert_to_discovery = True

            state.last_sigma = sigma

            if revert_to_discovery:
                state.phase = "DISCOVERY"
                # Preserve the bracket we discovered; clear quotes so we probe anew
                state.last_bid_quote = None
                state.last_ask_quote = None
                state.trades_seen = 0

    # -------- State helpers ---------------------------------------------------

    def _ensure_state_for(self, commodity: 'CommodityDefinition') -> MarketMakerState:
        """Return (and create if needed) the state object for this commodity."""
        commodity_name = getattr(commodity, "name", str(commodity))
        if commodity_name not in self._state:
            self._state[commodity_name] = MarketMakerState(
                phase="DISCOVERY",
                lower_bound=self.MIN_PRICE,
                upper_bound=None,
                last_bid_quote=None,
                last_ask_quote=None,
                last_bid_filled_price=None,
                last_ask_filled_price=None,
                trades_seen=0,
                quiet_ticks=0,
                last_sigma=None,
                discovered_midpoint=None,
            )
        return self._state[commodity_name]

    # -------- Discovery mode --------------------------------------------------

    def _discovery_quotes(self, actor:Actor, commodity: 'CommodityDefinition', state: MarketMakerState) -> List['MarketCommand']:
        """
        Post 1-unit geometric probes to establish a conservative price bracket.
        - Bid starts at lower_bound and doubles if unfilled (capped by upper_bound).
        - Ask starts at upper_bound (or lower_bound+1) and halves if unfilled (floored at lower_bound+1).
        """
        commands: List['MarketCommand'] = []
        per_tick_probe_budget = max(self.MIN_PRICE, int(actor.money * self.DISCOVERY_CASH_FRACTION))

        # Initialize the upper bound to "what we can pay for 1 unit right now"
        if state.upper_bound is None:
            state.upper_bound = max(self.MIN_ASK_PRICE, per_tick_probe_budget)

        lower_bound = state.lower_bound
        upper_bound = state.upper_bound
        has_inventory = actor.inventory.get_quantity(commodity) > 0

        # --- Probe bid (1 unit) ---
        if per_tick_probe_budget >= max(self.MIN_PRICE, lower_bound):
            next_bid = state.last_bid_quote if state.last_bid_quote is not None else lower_bound
            if state.last_bid_quote is not None:
                # Geometric raise if previous bid didn't fill
                next_bid = min(upper_bound, max(lower_bound, state.last_bid_quote * 2))
            state.last_bid_quote = next_bid

            if per_tick_probe_budget >= next_bid:
                commands.append(PlaceBuyOrderCommand(commodity, 1, next_bid))

        # --- Probe ask (1 unit) if we have inventory ---
        if has_inventory:
            next_ask = state.last_ask_quote if state.last_ask_quote is not None else max(lower_bound + 1, upper_bound)
            if state.last_ask_quote is not None:
                # Geometric lower if previous ask didn't fill
                next_ask = max(lower_bound + 1, min(upper_bound, state.last_ask_quote // 2))
            state.last_ask_quote = next_ask
            commands.append(PlaceSellOrderCommand(commodity, 1, next_ask))

        return commands

    # -------- Maker mode ------------------------------------------------------

    def _maker_quotes(self, actor:Actor, market, commodity: 'CommodityDefinition', state: MarketMakerState) -> List['MarketCommand']:
        """
        Quote a small ladder around a volatility‑adjusted, inventory‑skewed midpoint.
        """
        commands: List['MarketCommand'] = []

        # --- Midpoint: blend discovered midpoint with rolling average if available ---
        midpoint = state.discovered_midpoint if state.discovered_midpoint is not None else self.MIN_PRICE
        sigma = 1.0
        if market.has_history(commodity):
            average_price = market.get_30_day_average_price(commodity)
            sigma = max(market.get_30_day_standard_deviation(commodity), 1.0)
            if average_price is not None:
                midpoint = int(round(0.5 * midpoint + 0.5 * average_price)) if midpoint else int(round(average_price))
        midpoint = max(self.MIN_PRICE, midpoint)

        # --- Spread with volatility widener ---
        half_spread = max(
            1,
            int(self.spread_percentage * midpoint * (1.0 + self.VOLATILITY_WIDENER * (sigma / max(1, midpoint))))
        )

        # --- Inventory-aware skew of the quoted midpoint ---
        current_inventory = actor.inventory.get_quantity(commodity)
        target_inventory = self._target_inventory(market, commodity)
        quoted_midpoint = self._apply_inventory_skew(midpoint, current_inventory, target_inventory)

        # --- Build evenly spaced ladders ---
        levels = self.LADDER_LEVELS
        step = max(1, half_spread // levels)

        bid_prices = [max(self.MIN_PRICE, quoted_midpoint - half_spread - i * step) for i in range(levels)]
        ask_prices = [max(self.MIN_ASK_PRICE, quoted_midpoint + half_spread + i * step) for i in range(levels)]

        # --- Exposure cap versus cash-only net worth (kept simple) ---
        cash_net_worth = max(1, actor.money)
        max_notional_per_commodity = self.MAX_NOTIONAL_FRACTION * cash_net_worth

        # --- SELL: distribute current inventory across asks (front‑load near touch) ---
        if current_inventory > 0:
            remaining_inventory = current_inventory
            weights = [levels - i for i in range(levels)]  # front-load near the touch
            weight_sum = sum(weights)

            for level_index, price in enumerate(ask_prices):
                if remaining_inventory <= 0:
                    break
                allocated_quantity = max(
                    self.MIN_ORDER_QUANTITY,
                    (remaining_inventory * weights[level_index]) // weight_sum
                )
                allocated_quantity = min(allocated_quantity, remaining_inventory)
                if allocated_quantity > 0:
                    commands.append(PlaceSellOrderCommand(commodity, allocated_quantity, price))
                    remaining_inventory -= allocated_quantity

        # --- BUY: allocate a per-commodity cash budget (front‑load near touch) ---
        cash_budget = int(actor.money * self.CASH_ALLOC_PER_COMMODITY)
        if cash_budget > 0 and max_notional_per_commodity > 0:
            remaining_funds = min(cash_budget, int(max_notional_per_commodity))
            weights = [levels - i for i in range(levels)]
            weight_sum = sum(weights)

            for level_index, price in enumerate(bid_prices):
                if remaining_funds < price:
                    break
                # Size roughly proportional to quoted_midpoint/price and the weight
                base_units = max(
                    self.MIN_ORDER_QUANTITY,
                    (weights[level_index] * quoted_midpoint) // (weight_sum * max(1, price))
                )
                quantity = min(base_units, remaining_funds // price)
                if quantity > 0:
                    commands.append(PlaceBuyOrderCommand(commodity, quantity, price))
                    remaining_funds -= quantity * price

        return commands

    # -------- Shared helpers --------------------------------------------------

    def _target_inventory(self, market, commodity: 'CommodityDefinition') -> int:
        """Desired inventory ≈ 30 days of average flow (or small neutral target if thin history)."""
        if market.has_history(commodity):
            average_volume = market.get_30_day_average_volume(commodity) or 0
            average_volume = max(1, int(average_volume))
            return average_volume * 30 + 1
        return 25  # neutral target when history is thin; not a price default

    def _apply_inventory_skew(self, midpoint: int, current_qty: int, target_qty: int) -> int:
        """
        Lightly skew the quoted midpoint based on inventory imbalance:
        - Over-inventoried → skew down; Under-inventoried → skew up.
        """
        if target_qty <= 0:
            return midpoint
        ratio = current_qty / target_qty  # 1.0 == on-target
        raw_skew = -0.25 * (ratio - 1.0)  # gentle slope
        clamped_skew = max(-self.INVENTORY_SKEW_CAP, min(self.INVENTORY_SKEW_CAP, raw_skew))
        return max(self.MIN_PRICE, int(round(midpoint * (1.0 + clamped_skew))))
