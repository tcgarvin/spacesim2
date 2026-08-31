import enum
import math
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional

from spacesim2.core.commodity import CommodityDefinition, Inventory
from spacesim2.core.navigation import (
    FLOW_RECENCY_TURNS,
    Navigator,
    get_navigator,
)
from spacesim2.core.planet import Planet

if TYPE_CHECKING:
    from spacesim2.core.drives.actor_drive import ActorDrive
    from spacesim2.core.market import Market
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

# Multiplier over the galaxy-wide fuel reference price up to which a docked
# ship "bunkers" (fills its tank). Above it fuel is scarcity-priced: paying
# spike prices for a FULL tank is how ships trade themselves broke, so only
# the survival minimum is bought.
FUEL_BUNKER_PREMIUM = 1.3

# Fraction of a ship's money that may go to bunkering fuel beyond the
# survival minimum. Fuel is working capital parked in the tank; cargo margins
# are usually better, so bunkering must not crowd out trading cash.
FUEL_BUNKER_BUDGET_FRACTION = 0.5

# Cargo units a plan may commit to when the destination shows no resting bids
# (revenue is then estimated from the avg price, which often fails to
# realize; unbounded speculation on it was a reliable money-loser).
SPECULATIVE_PLAN_CAP = 10

# Flow-based planning. With deferred end-of-turn matching, the resting book
# holds only what the local auction REJECTED: no asks for goods in local
# demand, lowball leftover bids. Real supply and demand clear in the per-turn
# flow, so plans must estimate from recent traded prices/volume, bid into the
# auction, and fill over several docked turns — trading only against residual
# orders moved ~1.6 units/trip in 100-unit holds and could not pay for fuel.
#
# Turns of destination flow a plan expects to sell into (sizes cargo without
# dumping a hold into a market that clears one unit a turn).
# (The volume-history window that counts as "this good trades here" is
# FLOW_RECENCY_TURNS, shared with spacesim2.core.navigation.)
DEMAND_HORIZON_TURNS = 15
# Docked turns a ship keeps a resting buy order open to fill its plan before
# departing with whatever it has (or replanning if nothing filled).
ACCUMULATION_PATIENCE = 8
# Confidence discount on avg-price revenue estimates and resting asks: the
# flow price is a forecast, not a resting order.
SELL_PRICE_HAIRCUT = 0.9

# How many candidate origin planets an empty repositioning ship surveys, in
# proximity order. Surveying every origin is O(planets^2 x commodities) per
# ship per turn; nearby origins need less fuel to reach anyway, so capping the
# survey bounds cost at large galaxy sizes without changing small-galaxy
# behavior (the cap exceeds the planet count of the default setups).
REPOSITION_ORIGIN_CANDIDATES = 12

# Chance per departure that a ship rolls a maintenance stop, and the fuel
# units the legacy maintenance tier consumes. Used both by
# Ship.check_maintenance and to price expected maintenance into trade plans.
MAINTENANCE_CHANCE = 0.1
MAINTENANCE_FUEL_UNITS = 5


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

    # Expected cost of maintenance rolls over the round trip (2 departures x
    # MAINTENANCE_CHANCE x the fuel-tier repair cost). Ignoring it made
    # penny-margin trades look profitable when a single repair wiped out
    # several trips of profit.
    expected_maintenance_cost: int = 0

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
        return (
            self.expected_revenue
            - self.total_purchase_cost
            - self.total_fuel_cost
            - self.expected_maintenance_cost
        )

    @property
    def profit_margin(self) -> float:
        """Profit as a percentage of costs."""
        total_costs = (
            self.total_purchase_cost
            + self.total_fuel_cost
            + self.expected_maintenance_cost
        )
        if total_costs <= 0:
            return 0.0
        return self.expected_profit / total_costs

    MIN_MARGIN = 0.15

    def is_profitable(self) -> bool:
        """Check if this trade meets the minimum profitability threshold."""
        return self.expected_profit > 0 and self.profit_margin >= self.MIN_MARGIN


@dataclass
class _PairEconomics:
    """Commodity-independent economics of one (origin, destination) pair.

    Everything a trade plan needs that does not depend on the commodity:
    geometry, fuel logistics/safety, and the trading budget. Computed once
    per pair by :meth:`TraderBrain._pair_economics` and reused for every
    commodity evaluated between the two planets.
    """

    distance: float
    fuel_one_way: int
    fuel_price: int
    fuel_to_buy: int
    expected_maintenance_cost: int
    money_for_trading: int
    max_by_cargo: int


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
        # Active trade plan (if any)
        self._current_plan: Optional[TradePlan] = None
        # True once the plan's cargo is aboard (fully or after patience ran
        # out with a partial load) and the ship should fly to the plan's
        # destination rather than keep buying or sell locally.
        self._plan_loaded = False
        # Docked turns left in the current plan phase (accumulating, or
        # loaded-but-unable-to-depart) before the plan is given up on.
        self._plan_turns_left = 0
        # Set while local sell orders from this turn are pending so
        # decide_travel doesn't depart and strand them in the book.
        self._selling_locally = False
        # Shared galaxy geometry / fuel-reachability cache (per simulation).
        self._nav: Navigator = get_navigator(ship.simulation)
        # Memo of the last full plan search: (turn, planet, result). The
        # search runs in decide_trade_actions and, when it found nothing,
        # again in decide_travel the same turn — the memo answers the second
        # call without re-surveying the galaxy.
        self._plan_search_memo: Optional[tuple[int, Planet, Optional[TradePlan]]] = None

    def _recent_flow_per_turn(
        self, market: "Market", commodity: CommodityDefinition
    ) -> float:
        """Mean traded units per turn over the recent volume window."""
        volumes = market.volume_history.get(commodity, [])[-FLOW_RECENCY_TURNS:]
        return sum(volumes) / len(volumes) if volumes else 0.0

    def _flow_value(
        self, market: "Market", commodity: CommodityDefinition
    ) -> Optional[int]:
        """Recent clearing price, or None when the good has never traded here.

        The avg-price default of 10 for a never-traded good is fabricated and
        must not back a valuation.
        """
        if not market.has_price_signal(commodity):
            return None
        return market.get_avg_price(commodity)

    def _get_tradeable_commodities(self) -> List[CommodityDefinition]:
        """Get list of commodities that can be traded between planets."""
        return self._nav.tradeable_commodities()

    def _fuel_commodity(self) -> Optional[CommodityDefinition]:
        """The nova_fuel commodity, or None if it is not defined."""
        return self._nav.fuel_commodity()

    def _fuel_purchasable_at(self, planet: Planet) -> bool:
        """Whether nova_fuel can realistically be bought at ``planet`` right now."""
        return self._nav.fuel_purchasable_at(planet)

    def _min_escape_fuel(self, from_planet: Planet) -> Optional[int]:
        """Fuel needed to reach the nearest fuel-selling planet from ``from_planet``.

        Returns None if fuel is not purchasable anywhere else in the galaxy.
        Fuel burn is monotone in distance, so the nearest source (cached by
        the navigator) minimizes this ship's escape cost too.
        """
        distance = self._nav.nearest_fuel_source_distance(from_planet)
        if distance is None:
            return None
        return self.ship.fuel_required(distance)

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
                self._nav.distance(destination, return_planet)
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
        nearest = self._nav.nearest_other_distance(current_planet)
        if nearest is None:
            return 0
        return 2 * self.ship.fuel_required(nearest)

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

    def _fuel_survival_target(self) -> int:
        """Fuel units to keep on hand to stay reliably mobile.

        Two shortest round trips or the escape leg to a refueling planet,
        whichever is larger, capped by the tank. This is the level worth
        paying scarcity prices for; anything beyond it is bunkering and only
        worth doing when fuel is cheap.
        """
        return min(
            self.ship.fuel_capacity,
            max(2 * self._fuel_reserve_need(), self._fuel_sell_reserve()),
        )

    def _fuel_value_reference(self) -> Optional[float]:
        """Cheapest believable fuel valuation anywhere in the galaxy.

        See :meth:`Navigator.fuel_value_reference` for the rationale.
        """
        return self._nav.fuel_value_reference()

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
        cheapest_ask = self._nav.cheapest_fuel_ask()
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

    def _place_flow_sell_orders(
        self, market: "Market", commodity: CommodityDefinition, quantity: int
    ) -> List[str]:
        """Sell ``quantity`` into both the resting bids and the flow.

        Matching executes at the SELL order's price, so a single ask at the
        top bid liquidates the entire load at that one price — historically
        including whole cargoes dumped into 1-credit probe bids. Instead:
        premium resting bids (above the haircut flow price) are captured by
        an ask priced at each level, and the remainder rests near the recent
        clearing price to be absorbed by the turn flow.

        Returns action strings for the placed orders.
        """
        actions: List[str] = []
        flow_value = self._flow_value(market, commodity)
        flow_px = int(flow_value * SELL_PRICE_HAIRCUT) if flow_value else 0
        remaining = quantity
        for price, level_qty in market.get_bid_levels(commodity):
            if remaining <= 0 or price <= flow_px:
                break
            take = min(level_qty, remaining)
            order_id = market.place_sell_order(self.ship, commodity, take, price)
            if order_id:
                actions.append(f"Selling {take} {commodity.name} at {price}")
                self.ship.active_orders[order_id] = f"sell {commodity.id}"
                remaining -= take
        if remaining > 0:
            if flow_px > 0:
                rest_price = flow_px
            else:
                best_bid, _ = market.get_bid_ask_spread(commodity)
                rest_price = max(1, best_bid or market.get_avg_price(commodity) or 1)
            order_id = market.place_sell_order(
                self.ship, commodity, remaining, rest_price
            )
            if order_id:
                actions.append(f"Offering {remaining} {commodity.name} at {rest_price}")
                self.ship.active_orders[order_id] = f"sell {commodity.id}"
        return actions

    def _opportunistic_fuel_topup(
        self, pending_fuel: int = 0, reserved_cargo: int = 0
    ) -> Optional[str]:
        """Buy fuel with leftover cargo space and money, price-aware.

        When the local ask is near the galaxy's cheapest believable fuel
        price, bunker toward a full tank. When it is scarcity-priced, buy
        only up to the survival target — ships that topped up full tanks at
        spike prices (40-85/unit vs single-digit cargo margins) reliably
        traded themselves broke.

        ``pending_fuel`` and ``reserved_cargo`` account for buy orders already
        placed this turn (their goods arrive at end-of-turn matching), so a
        top-up never crowds out the trade plan's cargo space or spends money
        the plan needs (order placement reserves funds, so ``ship.money``
        already excludes the plan's committed money).
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
        cargo_room = (
            ship.cargo_capacity - ship.cargo.get_total_quantity() - reserved_cargo
        )

        reference = self._fuel_value_reference()
        # The local ask is itself a galaxy signal, so reference is never None
        # here; guard anyway for safety.
        bunkering = reference is not None and fuel_ask <= math.ceil(
            reference * FUEL_BUNKER_PREMIUM
        )

        survival_target = self._fuel_survival_target()
        survival_units = min(
            max(0, survival_target - current_fuel),
            cargo_room,
            int(ship.money * 0.9) // fuel_ask,
        )
        survival_units = max(0, survival_units)

        bunker_units = 0
        if bunkering:
            bunker_budget = (
                int(ship.money * FUEL_BUNKER_BUDGET_FRACTION)
                - survival_units * fuel_ask
            )
            bunker_units = min(
                ship.fuel_capacity - current_fuel - survival_units,
                cargo_room - survival_units,
                max(0, bunker_budget) // fuel_ask,
            )
            bunker_units = max(0, bunker_units)

        quantity = survival_units + bunker_units
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
        for source, ask in self._nav.fuel_ask_planets():
            if source is planet:
                continue
            distance = self._nav.distance(source, planet)
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
        # Bid only up to the survival target, not a full tank: a tank-sized
        # rescue bid at delivery prices reserves most of the ship's money for
        # hundreds of turns if it goes unfilled, locking it out of the very
        # trading that could earn its way out.
        max_units = min(self._fuel_survival_target() - current_fuel, cargo_room)
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

    def _pair_economics(
        self, origin: Planet, destination: Planet
    ) -> Optional["_PairEconomics"]:
        """Commodity-independent economics of trading ``origin`` -> ``destination``.

        Computes geometry, fuel logistics, the fuel-safety gates, and the
        trading budget — everything a plan needs that no commodity choice can
        change — so :meth:`_best_plan_from` can evaluate many commodities per
        pair without redoing this work. Returns None when NO plan over this
        pair can be feasible:
        - round-trip fuel would need buying where fuel is not purchasable
        - the destination would leave the ship without an escape route
        - no money remains for cargo after fuel, refuel floor, expected
          maintenance, and the operating buffer
        """
        fuel_commodity = self._fuel_commodity()
        if fuel_commodity is None:
            return None

        # Distance and fuel needs (efficiency-adjusted: this must match what
        # start_journey will actually consume).
        distance = self._nav.distance(origin, destination)
        fuel_one_way = self.ship.fuel_required(distance)
        fuel_round_trip = fuel_one_way * 2

        origin_market = origin.market
        _, fuel_ask = origin_market.get_bid_ask_spread(fuel_commodity)
        fuel_price = (
            fuel_ask
            if fuel_ask is not None
            else origin_market.get_avg_price(fuel_commodity)
        )
        if fuel_price is None or fuel_price <= 0:
            fuel_price = 10  # Default fuel price if no market data

        current_fuel = self.ship.cargo.get_quantity(fuel_commodity)
        cargo_space = self.ship.cargo_capacity - self.ship.cargo.get_total_quantity()

        # Reserve money for fuel purchase if needed
        fuel_to_buy = max(0, fuel_round_trip - current_fuel)
        if fuel_to_buy > 0 and not self._fuel_purchasable_at(origin):
            # The plan needs fuel that cannot realistically be bought at the
            # origin (no ask AND no recent flow); committing to it would
            # strand the ship with cargo.
            return None
        fuel_cost = fuel_to_buy * fuel_price

        # Never fly somewhere that leaves no escape route: the destination
        # must sell fuel, or the fuel left after arrival must reach a planet
        # that does.
        fuel_after_arrival = max(current_fuel, fuel_round_trip) - fuel_one_way
        if not self._fuel_safe_destination(destination, origin, fuel_after_arrival):
            return None

        # Expected maintenance over the round trip: two departure rolls, each
        # potentially costing the fuel-tier repair at origin fuel prices.
        maintenance_cost = math.ceil(
            2 * MAINTENANCE_CHANCE * MAINTENANCE_FUEL_UNITS * fuel_price
        )

        # Money available for commodity purchase. Withhold the fuel purchase,
        # a cash floor able to re-buy the travel reserve after the trip (a
        # trade that disappoints must never leave the ship broke AND dry —
        # that is the stranding spiral), expected maintenance, and a 10%
        # operating buffer.
        refuel_floor = self._fuel_reserve_need() * fuel_price
        money_for_trading = int(
            (self.ship.money - fuel_cost - refuel_floor - maintenance_cost) * 0.9
        )
        if money_for_trading <= 0:
            return None

        return _PairEconomics(
            distance=distance,
            fuel_one_way=fuel_one_way,
            fuel_price=fuel_price,
            fuel_to_buy=fuel_to_buy,
            expected_maintenance_cost=maintenance_cost,
            money_for_trading=money_for_trading,
            max_by_cargo=cargo_space - fuel_to_buy,  # fuel takes cargo space
        )

    def _evaluate_trade_opportunity(
        self,
        origin: Planet,
        destination: Planet,
        commodity: CommodityDefinition,
        pair: Optional["_PairEconomics"] = None,
    ) -> Optional[TradePlan]:
        """Evaluate a single trade opportunity between two planets.

        Returns a TradePlan if the trade is feasible, None otherwise.
        Feasibility checks:
        - Commodity is actually acquirable at origin (resting ask, or an
          active local flow the ship can bid into)
        - Have enough money for purchase + fuel
        - Have enough cargo space
        - Have/can buy enough fuel for round trip

        Prices and quantities come from the FLOW (recent clearing prices and
        volume) as well as the resting book: the plan's purchase price is the
        bid the ship will post, and matching executes at each seller's ask,
        so fills only ever come in at or below it.

        ``pair`` carries the commodity-independent economics of the
        (origin, destination) pair; :meth:`_best_plan_from` precomputes it
        once per pair, and it is derived on the fly when omitted.
        """
        if pair is None:
            pair = self._pair_economics(origin, destination)
        if pair is None:
            return None

        # Get market data
        origin_market = origin.market
        dest_market = destination.market

        # Acquisition price at origin: the bid the ship will post. A resting
        # ask is directly takeable; an active local flow (recent volume with
        # a real price signal) is biddable-into at the clearing price. Bid
        # the higher of the two — matching executes at each seller's ask, so
        # a generous bid captures more of the flow without paying more for
        # the cheap fills; the margin gate below already prices the worst
        # case (every unit at the bid).
        _, origin_ask = origin_market.get_bid_ask_spread(commodity)
        origin_flow_px = self._flow_value(origin_market, commodity)
        if origin_flow_px is not None and (
            self._recent_flow_per_turn(origin_market, commodity) <= 0
        ):
            origin_flow_px = None  # a price with no recent volume buys nothing
        price_candidates = [
            p for p in (origin_ask, origin_flow_px) if p is not None and p > 0
        ]
        if not price_candidates:
            # Nothing for sale and no active flow to bid into.
            return None
        buy_price = max(price_candidates)

        # Destination demand: resting bids that beat the purchase price...
        bid_levels = [
            (price, qty)
            for price, qty in dest_market.get_bid_levels(commodity)
            if price > buy_price
        ]
        depth = sum(qty for _, qty in bid_levels)
        # ...plus the flow: recent clearing volume at the recent clearing
        # price (haircut — it is a forecast, not a resting order).
        dest_flow_px = self._flow_value(dest_market, commodity)
        flow_px = int(dest_flow_px * SELL_PRICE_HAIRCUT) if dest_flow_px else 0
        flow_qty = 0
        if flow_px > buy_price:
            flow_qty = int(
                self._recent_flow_per_turn(dest_market, commodity)
                * DEMAND_HORIZON_TURNS
            )
        if depth + flow_qty > 0:
            sellable = depth + flow_qty
        elif flow_px > buy_price:
            # Price signal but no recent volume: latent demand is a guess
            # that often fails to realize, so such plans are capped small.
            sellable = SPECULATIVE_PLAN_CAP
        else:
            return None

        # Calculate max quantity we can buy (budget and cargo limits are
        # pair-level facts; only the buy price is commodity-specific).
        max_by_money = pair.money_for_trading // buy_price
        max_quantity = max(0, min(max_by_money, pair.max_by_cargo))

        # Project revenue by walking the resting bids first (their prices are
        # firm), then valuing the remainder at the haircut flow price.
        quantity = min(max_quantity, sellable)
        if quantity <= 0:
            return None
        remaining = quantity
        revenue = 0
        for price, qty in bid_levels:
            take = min(qty, remaining)
            revenue += price * take
            remaining -= take
            if remaining == 0:
                break
        if remaining > 0:
            revenue += flow_px * remaining
        sell_price = revenue // quantity

        return TradePlan(
            origin=origin,
            destination=destination,
            commodity=commodity,
            quantity=quantity,
            purchase_price_per_unit=buy_price,
            expected_sell_price_per_unit=sell_price,
            distance=pair.distance,
            fuel_needed_one_way=pair.fuel_one_way,
            fuel_price_at_origin=pair.fuel_price,
            expected_maintenance_cost=pair.expected_maintenance_cost,
        )

    def _find_best_trade_plan(self) -> Optional[TradePlan]:
        """Survey all possible trades from here and return the most profitable.

        Memoized per (turn, planet): decide_trade_actions runs the survey and,
        when it finds nothing, decide_travel asks again the same turn before
        repositioning — the memo answers that second call directly.
        """
        current_planet = self.ship.planet
        if current_planet is None or not self.ship.simulation.planets:
            return None
        memo = self._plan_search_memo
        turn = self.ship.simulation.current_turn
        if memo is not None and memo[0] == turn and memo[1] is current_planet:
            return memo[2]
        plan = self._best_plan_from(current_planet)
        self._plan_search_memo = (turn, current_planet, plan)
        return plan

    def _best_plan_from(self, origin: Planet) -> Optional[TradePlan]:
        """Most profitable trade plan exporting from ``origin``, if any.

        Only commodities acquirable at the origin are evaluated, and only
        against the navigator's per-turn candidate destinations for each
        commodity (the top-value demand planets united with the nearest ones;
        every demand planet in small galaxies — both are superset filters,
        the evaluation itself re-verifies prices). When the galaxy shows no
        trade signal at all, planning is skipped outright. The
        commodity-independent economics of each (origin, destination) pair
        are computed once and shared across commodities.
        """
        nav = self._nav
        if not nav.has_any_trade_signal():
            return None
        exportable = nav.exportable_commodities(origin)
        if not exportable:
            return None

        best_plan: Optional[TradePlan] = None
        best_profit = 0
        # Hoisted per-pair facts for this search only (the navigator owns all
        # cross-ship, cross-turn caching).
        pair_economics: Dict[Planet, Optional[_PairEconomics]] = {}

        for commodity in self._get_tradeable_commodities():
            if commodity not in exportable:
                continue
            for destination in nav.candidate_destinations(origin, commodity):
                if destination in pair_economics:
                    pair = pair_economics[destination]
                else:
                    pair = self._pair_economics(origin, destination)
                    pair_economics[destination] = pair
                if pair is None:
                    continue
                plan = self._evaluate_trade_opportunity(
                    origin=origin,
                    destination=destination,
                    commodity=commodity,
                    pair=pair,
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

        Buy orders are posted at the plan's bid price and rest in the book,
        filling from the turn's flow of asks (matching executes at each
        seller's ask, never above the bid). Called every accumulating turn,
        it re-posts for whatever the plan still lacks.
        """
        planet = self.ship.planet
        if planet is None:
            return
        market = planet.market
        fuel_commodity = self._fuel_commodity()

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
                fuel_bid = (
                    fuel_ask
                    if fuel_ask is not None
                    else self._flow_value(market, fuel_commodity)
                )

                if fuel_bid is not None and fuel_bid > 0:
                    affordable_fuel = min(fuel_to_buy, self.ship.money // fuel_bid)
                    if affordable_fuel > 0:
                        order_id = market.place_buy_order(
                            self.ship, fuel_commodity, affordable_fuel, fuel_bid
                        )
                        if order_id:
                            actions.append(
                                f"Buying {affordable_fuel} fuel at {fuel_bid}"
                            )
                            self.ship.active_orders[order_id] = "buy fuel"
                            pending_fuel = affordable_fuel

        # Step 2: Buy the plan's remaining cargo at the plan's bid price.
        # The order rests in the book and fills from the flow at sellers'
        # ask prices (never above the bid).
        bid_price = plan.purchase_price_per_unit
        already_held = self._sellable_quantity(plan.commodity)
        still_needed = plan.quantity - already_held
        if bid_price > 0 and still_needed > 0:
            # Recalculate affordable quantity after fuel purchase
            money_available = int(self.ship.money * 0.9)  # Keep 10% reserve
            cargo_available = (
                self.ship.cargo_capacity
                - self.ship.cargo.get_total_quantity()
                - pending_fuel
            )

            quantity = min(still_needed, money_available // bid_price, cargo_available)

            if quantity > 0:
                order_id = market.place_buy_order(
                    self.ship, plan.commodity, quantity, bid_price
                )
                if order_id:
                    actions.append(
                        f"Bidding for {quantity} {plan.commodity.name} at {bid_price} "
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

        # Ensure the galaxy's per-turn market-fact snapshot is current (the
        # first ship deciding this turn rebuilds it; the rest share it).
        self._nav.refresh_market_facts(turn=self.ship.simulation.current_turn)

        market = self.ship.planet.market
        fuel_commodity = self._fuel_commodity()

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

        # --- Plan lifecycle -------------------------------------------------
        # Flow-based plans fill a resting bid over several docked turns, then
        # fly the load to the plan's destination.
        plan = self._current_plan
        if plan is not None:
            if self.ship.planet is plan.destination:
                # Arrived: the sell logic below disposes of the cargo. The
                # plan lingers only to mark a fuel delivery's tank contents
                # as trade cargo (_fuel_delivery_in_progress), and is dropped
                # once the cargo is gone.
                self._plan_loaded = False
                if self._sellable_quantity(plan.commodity) <= 0:
                    self._current_plan = None
            elif self.ship.planet is not plan.origin:
                # Diverted (maintenance/survival reposition): abandon.
                self._current_plan = None
                self._plan_loaded = False
            elif not self._plan_loaded:
                held = self._sellable_quantity(plan.commodity)
                if held >= plan.quantity:
                    self._plan_loaded = True
                    self._plan_turns_left = ACCUMULATION_PATIENCE
                elif self._plan_turns_left > 0:
                    # Keep accumulating: refresh the resting bid, stay docked.
                    self._plan_turns_left -= 1
                    self._execute_trade_plan(plan)
                    return
                elif held > 0:
                    # Patience exhausted: depart with the partial load.
                    self._plan_loaded = True
                    self._plan_turns_left = ACCUMULATION_PATIENCE
                else:
                    # Patience exhausted, nothing filled: replan from scratch.
                    self._current_plan = None
            else:
                # Loaded at origin. Departure happens in decide_travel; being
                # here next turn means it was blocked (usually on fuel). Wait
                # a bounded while, then release the cargo to the legacy
                # sell-or-fly logic.
                if self._plan_turns_left > 0:
                    self._plan_turns_left -= 1
                else:
                    self._current_plan = None
                    self._plan_loaded = False

        # Priority 1: If we have cargo, decide whether to sell here or travel
        # (unless it is a loaded plan's cargo, which flies to plan.destination)
        if has_trade_cargo and not self._plan_loaded:
            # Check if there's a better destination to sell
            should_sell_here = True
            current_planet = self.ship.planet
            fuel_available = self.ship.cargo.get_quantity(fuel_commodity)

            for commodity in self._get_tradeable_commodities():
                quantity = self._sellable_quantity(commodity)
                if quantity <= 0:
                    continue

                local_bid, _ = market.get_bid_ask_spread(commodity)
                # Value at the better of the top resting bid and the recent
                # clearing price: the residual book alone undervalues any
                # good the local auction actually clears.
                local_price = max(
                    local_bid or 0, self._flow_value(market, commodity) or 0
                )

                # Check other planets for better prices
                for planet in self.ship.simulation.planets:
                    if planet == current_planet:
                        continue

                    distance = self._nav.distance(current_planet, planet)
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
                    dest_price = max(
                        dest_bid or 0,
                        self._flow_value(planet.market, commodity) or 0,
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
                        sell_actions = self._place_flow_sell_orders(
                            market, commodity, quantity
                        )
                        if sell_actions:
                            actions.extend(sell_actions)
                            self._selling_locally = True
                            if commodity.id == "nova_fuel":
                                placed_fuel_sell = True
            else:
                # Better price elsewhere - will travel in decide_travel()
                actions.append("Holding cargo for better price elsewhere")

        if not has_trade_cargo:
            # Priority 3: Find and adopt the best trade plan
            plan = self._find_best_trade_plan()
            if plan:
                self._current_plan = plan
                self._plan_loaded = False
                self._plan_turns_left = ACCUMULATION_PATIENCE
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

        # Ensure the galaxy's per-turn market-fact snapshot is current.
        self._nav.refresh_market_facts(turn=self.ship.simulation.current_turn)

        fuel_commodity = self._fuel_commodity()
        if not fuel_commodity:
            return None

        current_planet = self.ship.planet
        fuel_available = self.ship.cargo.get_quantity(fuel_commodity)

        # Plan-driven travel: while a plan is accumulating, stay docked; once
        # loaded, fly to the plan's destination if fuel and safety allow
        # (otherwise stay and let fuel upkeep work — the loaded-phase patience
        # in decide_trade_actions bounds the wait).
        plan = self._current_plan
        if plan is not None and current_planet is plan.origin:
            if not self._plan_loaded:
                return None
            fuel_needed = self.ship.fuel_required(
                self._nav.distance(current_planet, plan.destination)
            )
            if fuel_available >= fuel_needed and self._fuel_safe_destination(
                plan.destination, current_planet, fuel_available - fuel_needed
            ):
                return plan.destination
            return None

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

            distance = self._nav.distance(current_planet, destination)
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
                price = max(bid or 0, self._flow_value(dest_market, commodity) or 0)
                if price > 0:
                    total_value += price * quantity

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
            distance = self._nav.distance(current, planet)
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

        Surveys up to REPOSITION_ORIGIN_CANDIDATES reachable planets, nearest
        first, as candidate origins and finds the best profitable export plan
        available from each. Returns the origin backing the most profitable
        opportunity, or None if none is reachable or profitable.
        """
        current_planet = self.ship.planet
        if current_planet is None:
            return None

        # Cold galaxy: no commodity has both supply and demand anywhere, so
        # no origin can back a plan — skip the per-origin surveys entirely.
        if not self._nav.has_any_trade_signal():
            return None

        best_origin: Optional[Planet] = None
        best_profit = 0
        surveyed = 0

        for origin in self._nav.planets_by_proximity(current_planet):
            if surveyed >= REPOSITION_ORIGIN_CANDIDATES:
                break
            # Must have enough fuel on board to reach this origin empty, and
            # arriving there must leave an escape route.
            distance_to_origin = self._nav.distance(current_planet, origin)
            fuel_to_origin = self.ship.fuel_required(distance_to_origin)
            if fuel_available < fuel_to_origin:
                continue
            if not self._fuel_safe_destination(
                origin, current_planet, fuel_available - fuel_to_origin
            ):
                continue

            surveyed += 1
            plan = self._best_plan_from(origin)
            if plan is not None and plan.expected_profit > best_profit:
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
        self.status = ShipStatus.DOCKED
        self.simulation = simulation  # Reference to the simulation
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
        return random.random() < MAINTENANCE_CHANCE

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

        # No tier has an ask to lift: post standing, scarcity-escalated bids
        # so producers see the demand (the maintenance analogue of the
        # standing fuel rescue bid). Without them a ship needing repairs at a
        # planet where no supplies are for sale is deadlocked forever — it
        # can never trade again to earn its way out. Bid on EVERY completable
        # tier money allows, preferring tiers whose commodity has actually
        # traded somewhere (a bid on a good nobody in the galaxy produces —
        # e.g. ship_components early on — can rest unfilled for hundreds of
        # turns while a fillable tier would have freed the ship). Re-posted
        # each turn; prices grow with scarcity pressure while unfilled.
        candidates: list[tuple[int, int, CommodityDefinition, int, int]] = []
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
            produced_somewhere = any(
                planet.market.has_price_signal(commodity)
                for planet in self.simulation.planets
            )
            candidates.append(
                (
                    0 if produced_somewhere else 1,
                    price * shortfall,
                    commodity,
                    shortfall,
                    price,
                )
            )
        placed: list[str] = []
        for _, _, commodity, shortfall, price in sorted(
            candidates, key=lambda c: (c[0], c[1])
        ):
            if self.money // price < shortfall:
                continue  # can only repair if the whole shortfall is fillable
            order_id = market.place_buy_order(self, commodity, shortfall, price)
            if order_id:
                self.active_orders[order_id] = f"buy {commodity.id} (maintenance bid)"
                placed.append(f"{shortfall} {commodity.id} at {price}")
        if placed:
            self.last_action = "Standing maintenance bid(s): " + ", ".join(placed)

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
