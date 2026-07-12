import enum
import math
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional

from spacesim2.core.commodity import CommodityDefinition, Inventory
from spacesim2.core.planet import Planet

if TYPE_CHECKING:
    from spacesim2.core.drives.actor_drive import ActorDrive
    from spacesim2.core.simulation import Simulation

# Margin over the delivered cost used when a stranded ship posts a standing
# fuel bid. Comfortably above the 15% TraderBrain arbitrage threshold so a
# fuel-delivery TradePlan passes ``is_profitable()`` for any deliverer.
FUEL_BID_MARGIN = 0.30

# Reference fuel price used for standing bids when no ask exists anywhere in
# the galaxy and the local market has never traded fuel (its avg-price default
# of 10 is fabricated and cannot be trusted).
FUEL_BID_FALLBACK_FLOOR = 15

# Ships are created with fuel_efficiency in [0.8, 1.2]; when estimating another
# (unknown) ship's delivery burn, assume the worst so the bid stays enticing.
DELIVERER_WORST_FUEL_EFFICIENCY = 0.8

# How many recent turns of volume history count as "fuel trades here" when
# judging whether fuel is realistically purchasable at a planet.
FUEL_MARKET_RECENCY_TURNS = 10


@dataclass
class TradePlan:
    """Represents a complete trade opportunity for a ship trader.

    A TradePlan encapsulates everything needed to execute a profitable trade:
    - Where to buy the commodity (origin)
    - Where to sell it (destination)
    - What commodity to trade
    - Expected costs and profits including round-trip fuel
    """

    origin: Planet
    destination: Planet
    commodity: CommodityDefinition

    # Quantities and costs
    quantity: int
    purchase_price_per_unit: int
    expected_sell_price_per_unit: int

    # Fuel calculations
    distance: float
    fuel_needed_one_way: int
    fuel_price_at_origin: int

    @property
    def fuel_needed_round_trip(self) -> int:
        """Fuel needed for round trip (conservative planning)."""
        return self.fuel_needed_one_way * 2

    @property
    def total_fuel_cost(self) -> int:
        """Total fuel cost for round trip."""
        return self.fuel_needed_round_trip * self.fuel_price_at_origin

    @property
    def total_purchase_cost(self) -> int:
        """Total cost to buy the commodity."""
        return self.quantity * self.purchase_price_per_unit

    @property
    def expected_revenue(self) -> int:
        """Expected revenue from selling at destination."""
        return self.quantity * self.expected_sell_price_per_unit

    @property
    def expected_profit(self) -> int:
        """Expected profit after all costs."""
        return self.expected_revenue - self.total_purchase_cost - self.total_fuel_cost

    @property
    def profit_margin(self) -> float:
        """Profit as a percentage of costs."""
        total_costs = self.total_purchase_cost + self.total_fuel_cost
        if total_costs <= 0:
            return 0.0
        return self.expected_profit / total_costs

    def is_profitable(self, min_margin: float = 0.15) -> bool:
        """Check if this trade meets minimum profitability threshold."""
        return self.expected_profit > 0 and self.profit_margin >= min_margin


class ShipStatus(enum.Enum):
    """Possible statuses for a ship."""

    DOCKED = "docked"  # Ship is docked at a planet
    TRAVELING = "traveling"  # Ship is traveling between planets
    NEEDS_MAINTENANCE = "needs_maintenance"  # Ship needs maintenance before traveling


class ShipBrain:
    """Base class for ship decision making strategies."""

    def __init__(self, ship: "Ship") -> None:
        """Initialize the brain with a reference to its ship."""
        self.ship = ship

    def decide_trade_actions(self) -> None:
        """Decide what trade actions to take at the current planet."""
        raise NotImplementedError("Subclasses must implement this method")

    def decide_travel(self) -> Optional[Planet]:
        """Decide whether to travel to another planet, and if so, which one."""
        raise NotImplementedError("Subclasses must implement this method")


class TraderBrain(ShipBrain):
    """Decision-making logic for trader ships that aim to maximize profit.

    Uses plan-driven trading: evaluates complete trade opportunities (buy->travel->sell)
    before committing to purchases. Plans for round-trip fuel to ensure safe return.
    """

    def __init__(self, ship: "Ship") -> None:
        """Initialize the trader brain."""
        super().__init__(ship)
        # Track average purchase price per commodity for profitability calculations
        self.commodity_purchase_prices: Dict[str, float] = {}
        # Active trade plan (if any)
        self._current_plan: Optional[TradePlan] = None
        # Set while local sell orders from this turn are pending so
        # decide_travel doesn't depart and strand them in the book.
        self._selling_locally = False

    def _calculate_average_purchase_price(
        self, commodity: CommodityDefinition
    ) -> Optional[float]:
        """Calculate average purchase price from recent transaction history."""
        if not self.ship.planet:
            return None

        market = self.ship.planet.market
        transactions = market.get_actor_transaction_history(self.ship)

        # Look at last 10 purchases of this commodity
        recent_purchases = [
            t
            for t in transactions[-10:]
            if t.buyer == self.ship and t.commodity_type == commodity
        ]

        if not recent_purchases:
            return None

        total_cost = sum(t.price * t.quantity for t in recent_purchases)
        total_quantity = sum(t.quantity for t in recent_purchases)

        return total_cost / total_quantity if total_quantity > 0 else None

    def _get_tradeable_commodities(self) -> List[CommodityDefinition]:
        """Get list of commodities that can be traded between planets."""
        return [
            c
            for c in self.ship.simulation.commodity_registry.all_commodities()
            if c.transportable
        ]

    def _fuel_commodity(self) -> Optional[CommodityDefinition]:
        """The nova_fuel commodity, or None if it is not defined."""
        return self.ship.simulation.commodity_registry.get_commodity("nova_fuel")

    def _fuel_purchasable_at(self, planet: Planet) -> bool:
        """Whether nova_fuel can realistically be bought at ``planet`` right now.

        True when a standing ask exists, or when the market has a real price
        signal AND recent fuel volume (asks come and go between turns on an
        actively supplied market, so recent trades count as availability).
        """
        fuel_commodity = self._fuel_commodity()
        if fuel_commodity is None:
            return False
        market = planet.market
        _, ask = market.get_bid_ask_spread(fuel_commodity)
        if ask is not None:
            return True
        if not market.has_price_signal(fuel_commodity):
            return False
        recent_volumes = market.volume_history.get(fuel_commodity, [])[
            -FUEL_MARKET_RECENCY_TURNS:
        ]
        return any(v > 0 for v in recent_volumes)

    def _min_escape_fuel(self, from_planet: Planet) -> Optional[int]:
        """Fuel needed to reach the nearest fuel-selling planet from ``from_planet``.

        Returns None if fuel is not purchasable anywhere else in the galaxy.
        """
        costs = [
            self.ship.fuel_required(Ship.calculate_distance(from_planet, planet))
            for planet in self.ship.simulation.planets
            if planet is not from_planet and self._fuel_purchasable_at(planet)
        ]
        return min(costs) if costs else None

    def _fuel_safe_destination(
        self, destination: Planet, return_planet: Planet, fuel_after_arrival: int
    ) -> bool:
        """Whether flying to ``destination`` leaves the ship an escape route.

        A destination is safe if fuel can be bought there, or if the ship will
        still hold enough fuel on arrival to reach the nearest planet where
        fuel IS purchasable. When fuel is not purchasable anywhere in the
        galaxy yet (early economy), grounding the fleet would be worse than
        the risk, so the minimum requirement is retaining the return leg to
        ``return_planet``.
        """
        if self._fuel_purchasable_at(destination):
            return True
        escape_fuel = self._min_escape_fuel(destination)
        if escape_fuel is None:
            return_leg = self.ship.fuel_required(
                Ship.calculate_distance(destination, return_planet)
            )
            return fuel_after_arrival >= return_leg
        return fuel_after_arrival >= escape_fuel

    def _fuel_reserve_need(self) -> int:
        """Round-trip fuel to the nearest other planet.

        Below this level the ship is at risk of stranding: it can no longer
        make even the shortest round trip.
        """
        current_planet = self.ship.planet
        if current_planet is None:
            return 0
        distances = [
            Ship.calculate_distance(current_planet, planet)
            for planet in self.ship.simulation.planets
            if planet is not current_planet
        ]
        if not distances:
            return 0
        return 2 * self.ship.fuel_required(min(distances))

    def _fuel_sell_reserve(self) -> int:
        """Fuel units to withhold from any sale so the ship can still leave.

        Covers both the shortest round trip and the leg to the nearest planet
        where fuel is purchasable (they can differ on fuel-poor planets).
        """
        current_planet = self.ship.planet
        if current_planet is None:
            return 0
        reserve = self._fuel_reserve_need()
        escape_fuel = self._min_escape_fuel(current_planet)
        if escape_fuel is not None:
            reserve = max(reserve, escape_fuel)
        return reserve

    def _fuel_delivery_in_progress(self) -> bool:
        """Whether the ship is at the destination of an active fuel-run plan.

        Only then is the tank's contents (above the travel reserve) trade
        cargo. At the origin the overflow-above-tank rule in
        :meth:`_sellable_quantity` already marks a loaded deliverer's excess
        fuel as cargo, so no origin case is needed here.
        """
        plan = self._current_plan
        if plan is None or plan.commodity.id != "nova_fuel":
            return False
        return self.ship.planet is plan.destination

    def _local_fuel_bid_is_scarcity_priced(self) -> bool:
        """Whether the local fuel bid clearly rewards offloading tank fuel.

        True when a standing local bid meets the delivery-margin markup over
        the cheapest ask anywhere in the galaxy (or the fallback floor when
        no ask exists). Such a bid can only rest in a book with no matching
        asks — typically another ship's standing rescue bid — so selling into
        it cannot create a sell-at-bid/re-buy-at-ask churn loop.
        """
        planet = self.ship.planet
        fuel_commodity = self._fuel_commodity()
        if planet is None or fuel_commodity is None:
            return False
        highest_bid, _ = planet.market.get_bid_ask_spread(fuel_commodity)
        if highest_bid is None:
            return False
        cheapest_ask: Optional[int] = None
        for source in self.ship.simulation.planets:
            _, ask = source.market.get_bid_ask_spread(fuel_commodity)
            if (
                ask is not None
                and ask > 0
                and (cheapest_ask is None or ask < cheapest_ask)
            ):
                cheapest_ask = ask
        threshold = (
            math.ceil(cheapest_ask * (1.0 + FUEL_BID_MARGIN))
            if cheapest_ask is not None
            else FUEL_BID_FALLBACK_FLOOR
        )
        return highest_bid >= threshold

    def _sellable_quantity(self, commodity: CommodityDefinition) -> int:
        """Cargo units of ``commodity`` the ship may treat as trade goods.

        Fuel is special-cased two ways:
        - The travel reserve is never sellable: selling the return-leg fuel
          is how ships used to strand themselves (including fuel deliverers,
          which would dump their whole tank at a fuel-poor destination).
        - Tank fuel is only trade cargo during an explicit fuel-delivery
          plan or when the local bid is scarcity-priced (e.g. another ship's
          standing rescue bid); otherwise only overflow above a full tank is.
          Without that guard a topped-up ship would sell its own tank at the
          local bid and re-buy at the ask every other turn, bleeding the
          spread.
        """
        quantity = self.ship.cargo.get_quantity(commodity)
        if commodity.id != "nova_fuel":
            return max(0, quantity)
        reserve = self._fuel_sell_reserve()
        if not (
            self._fuel_delivery_in_progress()
            or self._local_fuel_bid_is_scarcity_priced()
        ):
            reserve = max(reserve, self.ship.fuel_capacity)
        return max(0, quantity - reserve)

    def _opportunistic_fuel_topup(
        self, pending_fuel: int = 0, reserved_cargo: int = 0
    ) -> Optional[str]:
        """Buy fuel toward a full tank with leftover cargo space and money.

        Ships keep their tank near full whenever docked somewhere fuel is
        actually for sale. ``pending_fuel`` and ``reserved_cargo`` account for
        buy orders already placed this turn (their goods arrive at end-of-turn
        matching), so a top-up never crowds out the trade plan's cargo space
        or spends money the plan needs (order placement reserves funds, so
        ``ship.money`` already excludes the plan's committed money).
        """
        ship = self.ship
        planet = ship.planet
        if planet is None:
            return None
        fuel_commodity = self._fuel_commodity()
        if fuel_commodity is None:
            return None
        market = planet.market
        _, fuel_ask = market.get_bid_ask_spread(fuel_commodity)
        if fuel_ask is None or fuel_ask <= 0:
            return None

        current_fuel = ship.cargo.get_quantity(fuel_commodity) + pending_fuel
        tank_headroom = ship.fuel_capacity - current_fuel
        cargo_room = (
            ship.cargo_capacity - ship.cargo.get_total_quantity() - reserved_cargo
        )
        budget = int(ship.money * 0.9)  # keep a small operating buffer
        quantity = min(tank_headroom, cargo_room, budget // fuel_ask)
        if quantity <= 0:
            return None

        order_id = market.place_buy_order(ship, fuel_commodity, quantity, fuel_ask)
        if not order_id:
            return None
        ship.active_orders[order_id] = "buy fuel"
        return order_id

    def _fuel_bid_price(self, planet: Planet, quantity: int) -> int:
        """Price for a standing fuel bid that makes delivery profitable.

        Anchors on the cheapest ask anywhere else in the galaxy plus the
        deliverer's round-trip burn (worst-case efficiency, amortized over
        ``quantity``), marked up by FUEL_BID_MARGIN so the delivery clears the
        15% arbitrage threshold with room to spare. If no ask exists anywhere,
        falls back to a reference price escalated by local scarcity pressure,
        which grows each turn the bid goes unfilled.
        """
        fuel_commodity = self._fuel_commodity()
        if fuel_commodity is None:
            return FUEL_BID_FALLBACK_FLOOR

        best_delivered_cost: Optional[float] = None
        for source in self.ship.simulation.planets:
            if source is planet:
                continue
            _, ask = source.market.get_bid_ask_spread(fuel_commodity)
            if ask is None or ask <= 0:
                continue
            distance = Ship.calculate_distance(source, planet)
            leg_fuel = math.ceil(
                Ship.calculate_fuel_needed(distance) / DELIVERER_WORST_FUEL_EFFICIENCY
            )
            delivered_cost = ask + (2 * leg_fuel * ask) / max(quantity, 1)
            if best_delivered_cost is None or delivered_cost < best_delivered_cost:
                best_delivered_cost = delivered_cost

        if best_delivered_cost is not None:
            return max(1, math.ceil(best_delivered_cost * (1.0 + FUEL_BID_MARGIN)))

        # No ask anywhere: fall back to what a local producer would need.
        return self._local_fuel_reference_price(planet)

    def _local_fuel_reference_price(self, planet: Planet) -> int:
        """Scarcity-escalated price a local fuel producer would plausibly take.

        Anchors on a real local signal if one exists (never the fabricated
        default avg of 10) and escalates with scarcity pressure, which grows
        each turn demand goes unmet.
        """
        fuel_commodity = self._fuel_commodity()
        if fuel_commodity is None:
            return FUEL_BID_FALLBACK_FLOOR
        market = planet.market
        reference = float(FUEL_BID_FALLBACK_FLOOR)
        if market.has_price_signal(fuel_commodity):
            reference = max(reference, float(market.get_avg_price(fuel_commodity)))
        escalated = reference * (1.0 + market.scarcity_pressure_for(fuel_commodity))
        return max(1, math.ceil(escalated))

    def _post_standing_fuel_bid(self) -> Optional[str]:
        """Post a standing buy order for fuel priced to entice a supply run.

        This is the escape hatch for the stranding condition: fuel below the
        travel reserve and no local ask to lift. The bid rests in the order
        book so other traders' cross-planet scans see it as a sell
        opportunity; decide_trade_actions re-posts it every docked turn while
        the condition holds, and the fallback price escalates via scarcity
        pressure if it keeps going unfilled.
        """
        ship = self.ship
        planet = ship.planet
        if planet is None:
            return None
        fuel_commodity = self._fuel_commodity()
        if fuel_commodity is None:
            return None
        market = planet.market

        current_fuel = ship.cargo.get_quantity(fuel_commodity)
        cargo_room = ship.cargo_capacity - ship.cargo.get_total_quantity()
        max_units = min(ship.fuel_capacity - current_fuel, cargo_room)
        if max_units <= 0:
            return None

        budget = int(ship.money * 0.9)  # keep a small operating buffer
        price = self._fuel_bid_price(planet, max_units)
        quantity = min(max_units, budget // price) if price > 0 else 0
        if 0 < quantity < max_units:
            # Smaller bids amortize the delivery burn over fewer units, so
            # reprice once for the quantity we can actually afford.
            price = self._fuel_bid_price(planet, quantity)
            quantity = min(quantity, budget // price)
        if quantity <= 0:
            # Too poor for a delivery-viable bid (a 1-unit rescue run can
            # never amortize its burn) — but a LOCAL producer needs no
            # delivery margin. Bid the scarcity-escalated local reference
            # with whatever money remains rather than going silent.
            price = self._local_fuel_reference_price(planet)
            quantity = min(max_units, budget // price) if price > 0 else 0
        if quantity <= 0:
            return None

        order_id = market.place_buy_order(ship, fuel_commodity, quantity, price)
        if not order_id:
            return None
        ship.active_orders[order_id] = "buy fuel (standing bid)"
        return order_id

    def _evaluate_trade_opportunity(
        self,
        origin: Planet,
        destination: Planet,
        commodity: CommodityDefinition,
    ) -> Optional[TradePlan]:
        """Evaluate a single trade opportunity between two planets.

        Returns a TradePlan if the trade is feasible, None otherwise.
        Feasibility checks:
        - Can actually buy commodity at origin
        - Have enough money for purchase + fuel
        - Have enough cargo space
        - Have/can buy enough fuel for round trip
        """
        fuel_commodity = self.ship.simulation.commodity_registry.get_commodity(
            "nova_fuel"
        )
        if not fuel_commodity:
            return None

        # Get market data
        origin_market = origin.market
        dest_market = destination.market

        # Calculate distance and fuel needs (efficiency-adjusted: this must
        # match what start_journey will actually consume)
        distance = Ship.calculate_distance(origin, destination)
        fuel_one_way = self.ship.fuel_required(distance)
        fuel_round_trip = fuel_one_way * 2

        # Get prices at origin
        _, buy_price = origin_market.get_bid_ask_spread(commodity)
        if buy_price is None:
            # No one selling at origin
            return None

        _, fuel_ask = origin_market.get_bid_ask_spread(fuel_commodity)
        fuel_price = (
            fuel_ask
            if fuel_ask is not None
            else origin_market.get_avg_price(fuel_commodity)
        )
        if fuel_price is None or fuel_price <= 0:
            fuel_price = 10  # Default fuel price if no market data

        # Get expected sell price at destination (highest bid)
        sell_bid, _ = dest_market.get_bid_ask_spread(commodity)
        if sell_bid is None:
            # Use average price as fallback
            sell_bid = dest_market.get_avg_price(commodity)
        if sell_bid is None or sell_bid <= 0:
            return None

        # Calculate how much we can trade
        current_fuel = self.ship.cargo.get_quantity(fuel_commodity)
        cargo_space = self.ship.cargo_capacity - self.ship.cargo.get_total_quantity()

        # Reserve money for fuel purchase if needed
        fuel_to_buy = max(0, fuel_round_trip - current_fuel)
        if fuel_to_buy > 0 and fuel_ask is None:
            # The plan needs fuel that cannot actually be bought at the
            # origin; committing to it would strand the ship with cargo.
            return None
        fuel_cost = fuel_to_buy * fuel_price

        # Never fly somewhere that leaves no escape route: the destination
        # must sell fuel, or the fuel left after arrival must reach a planet
        # that does.
        fuel_after_arrival = max(current_fuel, fuel_round_trip) - fuel_one_way
        if not self._fuel_safe_destination(destination, origin, fuel_after_arrival):
            return None

        # Money available for commodity purchase. Withhold the fuel purchase,
        # a cash floor able to re-buy the travel reserve after the trip (a
        # trade that disappoints must never leave the ship broke AND dry —
        # that is the stranding spiral), and a 10% operating buffer.
        refuel_floor = self._fuel_reserve_need() * fuel_price
        money_for_trading = int((self.ship.money - fuel_cost - refuel_floor) * 0.9)
        if money_for_trading <= 0:
            return None

        # Calculate max quantity we can buy
        max_by_money = money_for_trading // buy_price
        max_by_cargo = cargo_space - fuel_to_buy  # Account for fuel taking cargo space
        max_quantity = max(0, min(max_by_money, max_by_cargo))

        if max_quantity <= 0:
            return None

        return TradePlan(
            origin=origin,
            destination=destination,
            commodity=commodity,
            quantity=max_quantity,
            purchase_price_per_unit=buy_price,
            expected_sell_price_per_unit=sell_bid,
            distance=distance,
            fuel_needed_one_way=fuel_one_way,
            fuel_price_at_origin=fuel_price,
        )

    def _find_best_trade_plan(self) -> Optional[TradePlan]:
        """Survey all possible trades and return the most profitable one.

        Evaluates trades from the current planet to all other planets
        for all tradeable commodities.
        """
        if not self.ship.planet or not self.ship.simulation.planets:
            return None

        current_planet = self.ship.planet
        commodities = self._get_tradeable_commodities()

        best_plan: Optional[TradePlan] = None
        best_profit = 0

        for destination in self.ship.simulation.planets:
            if destination == current_planet:
                continue

            for commodity in commodities:
                plan = self._evaluate_trade_opportunity(
                    origin=current_planet,
                    destination=destination,
                    commodity=commodity,
                )

                if plan and plan.is_profitable() and plan.expected_profit > best_profit:
                    best_plan = plan
                    best_profit = plan.expected_profit

        return best_plan

    def _execute_trade_plan(self, plan: TradePlan) -> None:
        """Execute a trade plan by placing appropriate buy orders.

        This method handles:
        1. Buying fuel (if needed for round trip)
        2. Buying the commodity

        Orders are placed at market prices to ensure execution.
        """
        planet = self.ship.planet
        if planet is None:
            return
        market = planet.market
        fuel_commodity = self.ship.simulation.commodity_registry.get_commodity(
            "nova_fuel"
        )

        actions = []

        # Cancel existing orders first
        existing_orders = market.get_actor_orders(self.ship)
        for order in existing_orders["buy"] + existing_orders["sell"]:
            market.cancel_order(order.order_id)

        # Step 1: Buy fuel if needed
        pending_fuel = 0
        pending_cargo = 0
        if fuel_commodity is not None:
            current_fuel = self.ship.cargo.get_quantity(fuel_commodity)
            fuel_needed = plan.fuel_needed_round_trip

            if current_fuel < fuel_needed:
                fuel_to_buy = fuel_needed - current_fuel
                _, fuel_ask = market.get_bid_ask_spread(fuel_commodity)

                if fuel_ask is not None:
                    affordable_fuel = min(fuel_to_buy, self.ship.money // fuel_ask)
                    if affordable_fuel > 0:
                        order_id = market.place_buy_order(
                            self.ship, fuel_commodity, affordable_fuel, fuel_ask
                        )
                        if order_id:
                            actions.append(
                                f"Buying {affordable_fuel} fuel at {fuel_ask}"
                            )
                            self.ship.active_orders[order_id] = "buy fuel"
                            pending_fuel = affordable_fuel

        # Step 2: Buy commodity
        _, commodity_ask = market.get_bid_ask_spread(plan.commodity)
        if commodity_ask is not None:
            # Recalculate affordable quantity after fuel purchase
            money_available = int(self.ship.money * 0.9)  # Keep 10% reserve
            cargo_available = (
                self.ship.cargo_capacity
                - self.ship.cargo.get_total_quantity()
                - pending_fuel
            )

            quantity = min(
                plan.quantity, money_available // commodity_ask, cargo_available
            )

            if quantity > 0:
                order_id = market.place_buy_order(
                    self.ship, plan.commodity, quantity, commodity_ask
                )
                if order_id:
                    actions.append(
                        f"Buying {quantity} {plan.commodity.name} at {commodity_ask} "
                        f"(plan: sell at {plan.destination.name} for ~{plan.expected_sell_price_per_unit})"
                    )
                    self.ship.active_orders[order_id] = f"buy {plan.commodity.id}"
                    pending_cargo = quantity

        # Step 3: Opportunistic top-up toward a full tank with whatever space
        # and money the plan left over (unless the plan itself is a fuel run,
        # in which case the cargo already is fuel).
        if plan.commodity.id != "nova_fuel":
            topup_order = self._opportunistic_fuel_topup(
                pending_fuel=pending_fuel, reserved_cargo=pending_cargo
            )
            if topup_order:
                actions.append("Topping up fuel tank")

        if actions:
            self.ship.last_action = "; ".join(actions)
        else:
            self.ship.last_action = "Trade plan execution failed - no orders placed"

    def decide_trade_actions(self) -> None:
        """Execute trading actions based on plan-driven logic.

        Trading behavior:
        1. If we have cargo to sell, sell it (complete the trade)
        2. If no cargo, find the best trade plan and execute it
        3. If no profitable trades exist, maintain fuel and wait
        """
        if not self.ship.planet:
            return

        market = self.ship.planet.market
        fuel_commodity = self.ship.simulation.commodity_registry.get_commodity(
            "nova_fuel"
        )

        if not fuel_commodity:
            self.ship.last_action = "No trading - fuel commodity not available"
            return

        # Cancel existing orders first
        existing_orders = market.get_actor_orders(self.ship)
        for order in existing_orders["buy"] + existing_orders["sell"]:
            market.cancel_order(order.order_id)

        actions = []
        self._selling_locally = False

        # Check if we have trade cargo (fuel below the travel reserve is not
        # trade cargo — see _sellable_quantity)
        has_trade_cargo = any(
            self._sellable_quantity(c) > 0 for c in self._get_tradeable_commodities()
        )

        placed_fuel_sell = False

        # Priority 1: If we have cargo, decide whether to sell here or travel
        if has_trade_cargo:
            # Check if there's a better destination to sell
            should_sell_here = True
            current_planet = self.ship.planet
            fuel_available = self.ship.cargo.get_quantity(fuel_commodity)

            for commodity in self._get_tradeable_commodities():
                quantity = self._sellable_quantity(commodity)
                if quantity <= 0:
                    continue

                local_bid, _ = market.get_bid_ask_spread(commodity)
                local_price = (
                    local_bid if local_bid else market.get_avg_price(commodity)
                )

                # Check other planets for better prices
                for planet in self.ship.simulation.planets:
                    if planet == current_planet:
                        continue

                    distance = Ship.calculate_distance(current_planet, planet)
                    fuel_needed = self.ship.fuel_required(distance)

                    if fuel_available < fuel_needed:
                        continue

                    # Only a destination decide_travel would actually fly to
                    # can justify holding cargo. Without this the two methods
                    # disagree (travel additionally vetoes fuel dead ends) and
                    # the ship holds forever for a trip it never departs on.
                    if not self._fuel_safe_destination(
                        planet, current_planet, fuel_available - fuel_needed
                    ):
                        continue

                    dest_bid, _ = planet.market.get_bid_ask_spread(commodity)
                    dest_price = (
                        dest_bid if dest_bid else planet.market.get_avg_price(commodity)
                    )

                    if not dest_price or not local_price:
                        continue

                    # Compare NET values the way decide_travel does: revenue
                    # at the destination minus the fuel burned to get there,
                    # vs revenue here. A bare unit-price comparison held tiny
                    # cargoes forever for trips whose fuel cost decide_travel
                    # would never approve.
                    origin_fuel_price = market.get_avg_price(fuel_commodity) or 10
                    dest_net = dest_price * quantity - fuel_needed * origin_fuel_price
                    if dest_net > local_price * quantity * 1.15:
                        # Meaningfully better elsewhere, don't sell here
                        should_sell_here = False
                        break

                if not should_sell_here:
                    break

            if should_sell_here:
                # Sell cargo here - no better destination available
                for commodity in self._get_tradeable_commodities():
                    quantity = self._sellable_quantity(commodity)
                    if quantity > 0:
                        highest_bid, _ = market.get_bid_ask_spread(commodity)
                        if highest_bid is not None:
                            order_id = market.place_sell_order(
                                self.ship, commodity, quantity, highest_bid
                            )
                            if order_id:
                                actions.append(
                                    f"Selling {quantity} {commodity.name} at {highest_bid}"
                                )
                                self.ship.active_orders[order_id] = (
                                    f"sell {commodity.id}"
                                )
                                self._selling_locally = True
                                if commodity.id == "nova_fuel":
                                    placed_fuel_sell = True
                        else:
                            avg_price = max(1, market.get_avg_price(commodity) or 1)
                            order_id = market.place_sell_order(
                                self.ship, commodity, quantity, avg_price
                            )
                            if order_id:
                                actions.append(
                                    f"Offering {quantity} {commodity.name} at {avg_price} (no buyers)"
                                )
                                self.ship.active_orders[order_id] = (
                                    f"sell {commodity.id}"
                                )
                                self._selling_locally = True
                                if commodity.id == "nova_fuel":
                                    placed_fuel_sell = True
            else:
                # Better price elsewhere - will travel in decide_travel()
                actions.append("Holding cargo for better price elsewhere")

        if not has_trade_cargo:
            # Priority 3: Find and execute best trade plan
            plan = self._find_best_trade_plan()
            if plan:
                self._current_plan = plan
                self._execute_trade_plan(plan)
                return  # _execute_trade_plan sets last_action
            self._current_plan = None

        # Fuel upkeep (runs whether or not we hold cargo, but never in the
        # same turn as a fuel sell — buying into our own ask would self-trade):
        # top up toward a full tank when fuel is for sale locally; otherwise,
        # if we're below the stranding reserve, post a standing bid priced to
        # entice a delivery run.
        if not placed_fuel_sell:
            _, fuel_ask = market.get_bid_ask_spread(fuel_commodity)
            if fuel_ask is not None:
                topup_order = self._opportunistic_fuel_topup()
                if topup_order:
                    actions.append("Topping up fuel tank")
            elif (
                self.ship.cargo.get_quantity(fuel_commodity) < self._fuel_reserve_need()
            ):
                bid_order = self._post_standing_fuel_bid()
                if bid_order:
                    order = market.orders_by_id[bid_order]
                    actions.append(
                        f"Standing fuel bid: {order.quantity} at {order.price} "
                        "(no local fuel for sale)"
                    )

        if actions:
            self.ship.last_action = "; ".join(actions)
        else:
            self.ship.last_action = "No trade actions (waiting for opportunities)"

    def decide_travel(self) -> Optional[Planet]:
        """Decide whether to travel based on current cargo and trade plan.

        Travel logic:
        1. Only travel if we have cargo to sell
        2. Find the destination with highest expected value after fuel cost
        3. Stay put if no cargo (buying happens locally via trade plan)
        """
        if self.ship.status != ShipStatus.DOCKED:
            return None

        if not self.ship.planet or not self.ship.simulation.planets:
            return None

        # We committed to selling here this turn; departing now would either
        # strand the fresh sell orders in the book or (with cancel-on-depart)
        # pointlessly abort the sale decide_trade_actions just chose.
        if self._selling_locally:
            return None

        fuel_commodity = self.ship.simulation.commodity_registry.get_commodity(
            "nova_fuel"
        )
        if not fuel_commodity:
            return None

        current_planet = self.ship.planet
        fuel_available = self.ship.cargo.get_quantity(fuel_commodity)

        # Check if we have any cargo to sell (reserve fuel is not cargo)
        commodities = self._get_tradeable_commodities()
        cargo_to_sell = {
            c: self._sellable_quantity(c)
            for c in commodities
            if self._sellable_quantity(c) > 0
        }

        if not cargo_to_sell:
            # No cargo. If a profitable export can be sourced right here, stay
            # and let decide_trade_actions buy it. Otherwise reposition empty
            # toward the planet with the best sourcing opportunity so the ship
            # doesn't strand on a planet that has nothing worth exporting.
            if self._find_best_trade_plan() is not None:
                return None
            reposition = self._find_reposition_target(fuel_available, fuel_commodity)
            if reposition is not None:
                return reposition
            # Nothing profitable anywhere. Idling is only safe where fuel can
            # be bought; on a fuel desert every turn spent waiting risks the
            # tank dropping below the escape threshold (and a standing rescue
            # bid posted here cannot be answered by local producers). Move to
            # where refueling is plausible while we still can.
            if not self._fuel_purchasable_at(current_planet):
                return self._survival_reposition_target(fuel_available)
            return None

        # Find best destination for our cargo
        best_planet = None
        best_expected_value = 0

        for destination in self.ship.simulation.planets:
            if destination == current_planet:
                continue

            distance = Ship.calculate_distance(current_planet, destination)
            fuel_needed = self.ship.fuel_required(distance)

            # Must have fuel for the journey
            if fuel_available < fuel_needed:
                continue

            # Never fly cargo into a fuel dead end
            if not self._fuel_safe_destination(
                destination, current_planet, fuel_available - fuel_needed
            ):
                continue

            # Calculate expected value at this destination
            dest_market = destination.market
            total_value = 0

            for commodity, quantity in cargo_to_sell.items():
                bid, _ = dest_market.get_bid_ask_spread(commodity)
                if bid is None:
                    bid = dest_market.get_avg_price(commodity)
                if bid and bid > 0:
                    total_value += bid * quantity

            # Subtract fuel cost (using origin fuel prices)
            origin_fuel_price = (
                current_planet.market.get_avg_price(fuel_commodity) or 10
            )
            fuel_cost = fuel_needed * origin_fuel_price
            net_value = total_value - fuel_cost

            if net_value > best_expected_value:
                best_expected_value = net_value
                best_planet = destination

        return best_planet

    def _survival_reposition_target(self, fuel_available: int) -> Optional[Planet]:
        """Nearest reachable planet where refueling is plausible.

        First choice is a planet where fuel is purchasable right now; second
        is one where fuel has traded before (producers exist there who can
        answer a standing rescue bid, unlike on a never-traded fuel desert).
        Returns None when no such planet is in range — then staying put and
        posting a standing bid is all that is left.
        """
        current = self.ship.planet
        if current is None:
            return None
        fuel_commodity = self._fuel_commodity()
        if fuel_commodity is None:
            return None
        best: Optional[tuple[int, float, Planet]] = None
        for planet in self.ship.simulation.planets:
            if planet is current:
                continue
            distance = Ship.calculate_distance(current, planet)
            if fuel_available < self.ship.fuel_required(distance):
                continue
            if self._fuel_purchasable_at(planet):
                tier = 0
            elif planet.market.has_price_signal(fuel_commodity):
                tier = 1
            else:
                continue
            if best is None or (tier, distance) < (best[0], best[1]):
                best = (tier, distance, planet)
        return best[2] if best is not None else None

    def _find_reposition_target(
        self, fuel_available: int, fuel_commodity: "CommodityDefinition"
    ) -> Optional[Planet]:
        """Pick a planet to fly to empty when nothing here is worth exporting.

        Surveys every other planet as a candidate origin and finds the best
        profitable export plan available from it. Returns the reachable origin
        backing the most profitable opportunity, or None if none is reachable
        or profitable.
        """
        current_planet = self.ship.planet
        if current_planet is None:
            return None

        commodities = self._get_tradeable_commodities()
        best_origin: Optional[Planet] = None
        best_profit = 0

        for origin in self.ship.simulation.planets:
            if origin == current_planet:
                continue

            # Must have enough fuel on board to reach this origin empty, and
            # arriving there must leave an escape route.
            distance_to_origin = Ship.calculate_distance(current_planet, origin)
            fuel_to_origin = self.ship.fuel_required(distance_to_origin)
            if fuel_available < fuel_to_origin:
                continue
            if not self._fuel_safe_destination(
                origin, current_planet, fuel_available - fuel_to_origin
            ):
                continue

            for destination in self.ship.simulation.planets:
                if destination == origin:
                    continue
                for commodity in commodities:
                    plan = self._evaluate_trade_opportunity(
                        origin=origin,
                        destination=destination,
                        commodity=commodity,
                    )
                    if (
                        plan
                        and plan.is_profitable()
                        and plan.expected_profit > best_profit
                    ):
                        best_profit = plan.expected_profit
                        best_origin = origin

        return best_origin


class Ship:
    """Represents a trading ship that can travel between planets."""

    def __init__(
        self,
        name: str,
        simulation: "Simulation",
        planet: Optional[Planet] = None,
        cargo_capacity: int = 100,
        fuel_capacity: int = 50,
        fuel_efficiency: float = 1.0,
        initial_money: int = 1000,
    ) -> None:
        self.name = name
        self.money = initial_money
        self.reserved_money = 0  # Money reserved for market orders
        self.planet = planet
        self.destination: Optional[Planet] = None  # Target planet when traveling
        self.cargo = Inventory()  # Cargo hold for commodities
        self.inventory = self.cargo  # Alias for compatibility with market code
        self.cargo_capacity = cargo_capacity
        self.fuel_capacity = fuel_capacity
        self.fuel_efficiency = fuel_efficiency  # Multiplier for fuel consumption
        self.travel_progress = 0.0  # Progress toward destination (0.0 to 1.0)
        self.travel_time = 0  # Total turns needed for current journey
        self.active_orders: Dict[
            str, str
        ] = {}  # Track active order IDs and their types
        self.last_action = "None"  # Track the last action performed
        self.maintenance_needed = False  # Whether maintenance is required
        self.status = ShipStatus.DOCKED
        self.simulation = simulation  # Reference to the simulation
        self.market_history: list[
            dict
        ] = []  # Track market activity for compatibility with market code
        self.food_consumed_this_turn = (
            True  # Ships don't eat, but needed for compatibility
        )
        self.drives: list[
            "ActorDrive"
        ] = []  # Ships don't have drives, but keep empty list for interface compatibility

        # Initialize with a brain
        self.brain = TraderBrain(self)

    @staticmethod
    def calculate_distance(planet1: Planet, planet2: Planet) -> float:
        """Calculate the distance between two planets."""
        return math.sqrt((planet2.x - planet1.x) ** 2 + (planet2.y - planet1.y) ** 2)

    @staticmethod
    def calculate_fuel_needed(distance: float) -> int:
        """Calculate baseline fuel needed for a journey of given distance.

        This is the raw, efficiency-independent number. Any planning for a
        specific ship must use :meth:`fuel_required` instead, which applies
        the ship's own fuel efficiency exactly as departure does.
        """
        # Base calculation: 1 fuel per 20 distance units, rounded up
        return math.ceil(distance / 20)

    def fuel_required(self, distance: float) -> int:
        """Efficiency-adjusted fuel this ship burns for a journey of ``distance``.

        Uses the exact rounding applied at departure so planning and
        consumption can never disagree (ships with efficiency < 1.0 used to
        under-reserve fuel and strand).
        """
        return math.ceil(Ship.calculate_fuel_needed(distance) / self.fuel_efficiency)

    def check_maintenance(self) -> bool:
        """Check if the ship needs maintenance before departure.

        Returns:
            True if maintenance is needed, False otherwise.
        """
        # Random chance of needing maintenance: 10%
        return random.random() < 0.1

    def perform_maintenance(self) -> bool:
        """Attempt to perform maintenance on the ship.

        Tries tiered maintenance goods from best to worst:
        - ship_components (1 unit) — best quality
        - ship_parts (2 units) — medium quality
        - ship_supplies (3 units) — basic quality
        - nova_fuel (5 units) — legacy fallback

        Returns:
            True if maintenance was successful, False if we lack resources.
        """
        registry = self.simulation.commodity_registry
        # Tiered maintenance: (commodity_id, quantity_needed, label)
        tiers = [
            ("ship_components", 1, "ship components"),
            ("ship_parts", 2, "ship parts"),
            ("ship_supplies", 3, "ship supplies"),
            ("nova_fuel", 5, "fuel"),
        ]

        for commodity_id, qty, label in tiers:
            commodity = registry.get_commodity(commodity_id)
            if commodity and self.cargo.has_quantity(commodity, qty):
                self.cargo.remove_commodity(commodity, qty)
                self.maintenance_needed = False
                self.status = ShipStatus.DOCKED
                self.last_action = f"Performed maintenance using {qty} {label}"
                return True

        self.last_action = "Cannot perform maintenance - insufficient supplies"
        return False

    def _buy_maintenance_supplies(self) -> None:
        """Buy maintenance goods from the local market when stranded.

        A ship that rolls a maintenance need on departure is locked out of the
        trading branch until it is repaired, so without this it can never
        acquire the supplies to repair itself (a deadlock once its cargo fuel
        runs low). Buys the cheapest available maintenance tier; the order fills
        at end of turn and perform_maintenance succeeds next turn.
        """
        if self.planet is None:
            return
        market = self.planet.market
        registry = self.simulation.commodity_registry

        # Release any money reserved by stale orders so it can fund supplies.
        existing = market.get_actor_orders(self)
        for order in existing["buy"] + existing["sell"]:
            market.cancel_order(order.order_id)

        tiers = [
            ("ship_components", 1),
            ("ship_parts", 2),
            ("ship_supplies", 3),
            ("nova_fuel", 5),
        ]
        for commodity_id, qty_needed in tiers:
            commodity = registry.get_commodity(commodity_id)
            if commodity is None:
                continue
            shortfall = qty_needed - self.cargo.get_quantity(commodity)
            if shortfall <= 0:
                continue
            _, ask = market.get_bid_ask_spread(commodity)
            if ask is None or ask <= 0:
                continue
            affordable = min(shortfall, self.money // ask)
            if affordable > 0:
                order_id = market.place_buy_order(self, commodity, affordable, ask)
                if order_id:
                    self.active_orders[order_id] = f"buy {commodity_id} (maintenance)"
                    self.last_action = (
                        f"Buying {affordable} {commodity_id} to enable maintenance"
                    )
                    return

        # No tier has an ask to lift: post a standing, scarcity-escalated bid
        # for the cheapest completable tier so local producers see the demand
        # (the maintenance analogue of the standing fuel rescue bid). Without
        # it a ship needing repairs at a planet where no supplies are for
        # sale is deadlocked forever — it can never trade again to earn its
        # way out. Re-posted each turn; the price grows with scarcity
        # pressure while it goes unfilled.
        best_bid_plan: Optional[tuple[int, CommodityDefinition, int, int]] = None
        for commodity_id, qty_needed in tiers:
            commodity = registry.get_commodity(commodity_id)
            if commodity is None:
                continue
            shortfall = qty_needed - self.cargo.get_quantity(commodity)
            if shortfall <= 0:
                continue
            price = max(
                1,
                math.ceil(
                    max(10, market.get_avg_price(commodity))
                    * (1.0 + market.scarcity_pressure_for(commodity))
                ),
            )
            if self.money // price < shortfall:
                continue  # can only repair if the whole shortfall is fillable
            expected_cost = price * shortfall
            if best_bid_plan is None or expected_cost < best_bid_plan[0]:
                best_bid_plan = (expected_cost, commodity, shortfall, price)
        if best_bid_plan is not None:
            _, commodity, shortfall, price = best_bid_plan
            order_id = market.place_buy_order(self, commodity, shortfall, price)
            if order_id:
                self.active_orders[order_id] = f"buy {commodity.id} (maintenance bid)"
                self.last_action = (
                    f"Standing maintenance bid: {shortfall} {commodity.id} at {price}"
                )

    def start_journey(self, destination: Planet) -> bool:
        """Begin a journey to another planet.

        Args:
            destination: The target planet

        Returns:
            True if journey started successfully, False otherwise
        """
        if self.status != ShipStatus.DOCKED:
            self.last_action = (
                f"Cannot start journey - ship status: {self.status.value}"
            )
            return False

        if self.planet is None:
            self.last_action = "Cannot start journey - ship is not at a planet"
            return False

        if self.planet == destination:
            self.last_action = "Already at destination"
            return False

        # Set origin planet before starting journey - make sure the planet knows this ship
        if self.planet and self not in self.planet.ships:
            self.planet.ships.append(self)

        # Check for maintenance needs
        if self.check_maintenance():
            self.maintenance_needed = True
            self.status = ShipStatus.NEEDS_MAINTENANCE
            self.last_action = "Maintenance required before departure"
            return False

        # Cancel any resting orders before departing: order cancellation is
        # local-market-only, so a ship that leaves with orders in the book
        # can never reclaim their reserved money or cargo unless it happens
        # to return (ships have stranded permanently in needs_maintenance
        # because the very fuel they needed was reserved by a stale sell
        # order at another planet). This runs before the fuel check so fuel
        # held by such an order counts as available for the journey.
        origin_market = self.planet.market
        resting = origin_market.get_actor_orders(self)
        for order in resting["buy"] + resting["sell"]:
            origin_market.cancel_order(order.order_id)

        # Get fuel commodity - simulation always available
        fuel_commodity = self.simulation.commodity_registry.get_commodity("nova_fuel")

        if not fuel_commodity:
            self.last_action = "Cannot start journey - fuel commodity not defined"
            return False

        # Calculate distance and fuel requirements
        distance = Ship.calculate_distance(self.planet, destination)
        adjusted_fuel_needed = self.fuel_required(distance)

        # Check if we have enough fuel
        if not self.cargo.has_quantity(fuel_commodity, adjusted_fuel_needed):
            self.last_action = (
                f"Insufficient fuel for journey (need {adjusted_fuel_needed})"
            )
            return False

        # Consume fuel
        self.cargo.remove_commodity(fuel_commodity, adjusted_fuel_needed)

        # Calculate travel time (1 turn per 20 distance units, minimum 1)
        self.travel_time = max(1, math.ceil(distance / 20))
        self.travel_progress = 0.0
        self.status = ShipStatus.TRAVELING
        self.destination = destination

        self.last_action = f"Departed for {destination.name} ({self.travel_time} turns)"
        return True

    def update_journey(self) -> bool:
        """Update journey progress.

        Returns:
            True if journey is complete, False otherwise
        """
        if self.status != ShipStatus.TRAVELING:
            return False

        if not self.destination:
            self.status = ShipStatus.DOCKED
            return False

        # Update progress
        progress_increment = 1.0 / self.travel_time
        self.travel_progress += progress_increment

        # Check if we've arrived
        if self.travel_progress >= 1.0:
            # Arrive at destination
            old_planet = self.planet
            self.planet = self.destination
            self.destination = None
            self.status = ShipStatus.DOCKED
            self.travel_progress = 0

            # Update ship's planet reference - transfer from old planet to new planet
            if old_planet and self in old_planet.ships:
                old_planet.ships.remove(self)

            # Make sure destination planet has a ships list and add this ship to it
            if self.planet:
                # Planet should always have ships list initialized
                if self not in self.planet.ships:
                    self.planet.ships.append(self)

            self.last_action = f"Arrived at {self.planet.name}"
            return True
        else:
            # Still traveling
            remaining_turns = math.ceil((1.0 - self.travel_progress) * self.travel_time)
            self.last_action = f"En route to {self.destination.name} ({remaining_turns} turns remaining)"
            return False

    def take_turn(self) -> None:
        """Perform actions for this turn.

        Each turn consists of:
        1. If traveling, update journey
        2. If docked, take trade actions
        3. If docked, consider traveling
        """
        # Handle different statuses
        if self.status == ShipStatus.TRAVELING:
            # Update journey progress
            self.update_journey()
        elif self.status == ShipStatus.NEEDS_MAINTENANCE:
            # Try to perform maintenance; if we lack supplies, buy them locally
            # so we can repair next turn instead of stranding indefinitely.
            if not self.perform_maintenance():
                self._buy_maintenance_supplies()
        elif self.status == ShipStatus.DOCKED:
            # Take trade actions at current planet
            self.brain.decide_trade_actions()

            # Consider traveling
            destination = self.brain.decide_travel()
            if destination:
                self.start_journey(destination)
