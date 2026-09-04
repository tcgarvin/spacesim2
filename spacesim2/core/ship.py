import enum
import math
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence

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

# Margin over delivered cost for a stranded ship's standing fuel bid. Above
# the 15% TraderBrain arbitrage threshold so a fuel-delivery TradePlan passes
# ``is_profitable()`` for any deliverer.
FUEL_BID_MARGIN = 0.30

# Fuel price for standing bids when no ask exists anywhere in the galaxy and
# the local market has never traded fuel. Its avg-price default of 10 is
# fabricated and cannot be trusted.
FUEL_BID_FALLBACK_FLOOR = 15

# Ships are created with fuel_efficiency in [0.8, 1.2]. When estimating an
# unknown deliverer's burn, assume the worst so the bid stays enticing.
DELIVERER_WORST_FUEL_EFFICIENCY = 0.8

# A docked ship fills its tank only while the local ask is within this
# multiple of the galaxy fuel reference price. Above it, it buys only the
# survival minimum. Filling a whole tank at spike prices bankrupts ships.
FUEL_BUNKER_PREMIUM = 1.3

# Fraction of a ship's money that may go to fuel beyond the survival
# minimum. Fuel is working capital parked in the tank and cargo margins are
# usually better, so bunkering must not crowd out trading cash.
FUEL_BUNKER_BUDGET_FRACTION = 0.5

# Max cargo units for a plan whose destination has no resting bids. Revenue
# is then a guess from the average price, so the exposure is capped.
SPECULATIVE_PLAN_CAP = 10

# Flow-based planning. With deferred end-of-turn matching, the resting book
# holds only what the local auction rejected: no asks for goods in local
# demand, lowball leftover bids. Real supply and demand clear in the per-turn
# flow, so plans estimate from recent traded prices and volume, bid into the
# auction, and fill over several docked turns. Trading only the residual
# book cannot pay for fuel.
#
# Turns of destination flow a plan expects to sell into. Sizes cargo so a
# hold is not dumped into a market that clears one unit a turn. The
# volume-history window that counts a good as trading is FLOW_RECENCY_TURNS,
# shared with spacesim2.core.navigation.
DEMAND_HORIZON_TURNS = 15
# Docked turns a ship keeps a resting buy order open to fill its plan before
# departing with what it has, or replanning if nothing filled.
ACCUMULATION_PATIENCE = 8
# Confidence discount on avg-price revenue estimates and resting asks. The
# flow price is a forecast, not a resting order.
SELL_PRICE_HAIRCUT = 0.9

# Candidate origin planets an empty repositioning ship surveys, in proximity
# order. Surveying every origin is O(planets^2 x commodities) per ship per
# turn, and nearby origins need less fuel to reach anyway. Galaxies with
# fewer planets than the cap are still surveyed exhaustively.
REPOSITION_ORIGIN_CANDIDATES = 12

# Chance per departure that a ship rolls a maintenance stop, and the fuel
# units the legacy maintenance tier consumes. Used by Ship.check_maintenance
# and to price expected maintenance into trade plans.
MAINTENANCE_CHANCE = 0.1
MAINTENANCE_FUEL_UNITS = 5

# Consecutive docked turns with no cargo, no plan and less cash than one
# short round trip's fuel before a ship counts as distressed. A distressed
# ship may liquidate the working capital parked in its tank, selling fuel
# down to its survival target instead of holding a full tank it cannot
# trade around. Below the survival target it would strand, so that is the
# floor; selling only to the target also keeps the next turn's fuel top-up
# from re-buying what was just sold.
DISTRESS_PATIENCE = 5

# Starting capital, scaled to galaxy geometry. Every trade plan must fund
# round-trip fuel, a refuel floor and expected maintenance before a credit
# goes to cargo, so a fixed purse silently grounds the fleet as lane routes
# grow: at 100 planets a mean round trip burns roughly six times the fuel it
# does at five. Capital is SHIP_CAPITAL_ROUND_TRIPS average round trips of
# fuel at a reference price, plus a working-capital fraction for cargo.
SHIP_CAPITAL_ROUND_TRIPS = 3
# Credits per fuel unit assumed when sizing capital at setup, where no market
# has traded yet. Calibrated so a five-planet galaxy reproduces the 1000
# credits the economy was originally tuned with.
SHIP_CAPITAL_FUEL_PRICE_REFERENCE = 40
SHIP_CAPITAL_RESERVE_FRACTION = 0.25
SHIP_CAPITAL_FLOOR = 1000

# Tank size. The baseline holds a mean round trip with room to spare in
# small galaxies; larger ones scale it so an average round trip still fits
# with headroom. Sizing to the p90 route instead would fill most of the
# 100-unit hold with fuel, so long cross-galaxy hauls stay out of reach by
# design and ships trade their neighbourhood.
BASE_FUEL_CAPACITY = 50
FUEL_CAPACITY_ROUND_TRIP_HEADROOM = 1.5
# Share of the tank a new ship is launched with.
INITIAL_FUEL_FRACTION = 0.6


@dataclass
class TradePlan:
    """A complete trade opportunity for a ship trader.

    Holds where to buy, where to sell, the commodity, and the expected costs
    and profit including round-trip fuel.
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

    # Expected cost of maintenance rolls over the round trip: 2 departures x
    # MAINTENANCE_CHANCE x the fuel-tier repair cost. Without it penny-margin
    # trades look profitable when one repair wipes out several trips of
    # profit.
    expected_maintenance_cost: int = 0

    @property
    def fuel_needed_round_trip(self) -> int:
        """Fuel for the round trip, which plans always budget for."""
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
        """Whether the trade meets the minimum profitability threshold."""
        return self.expected_profit > 0 and self.profit_margin >= self.MIN_MARGIN


@dataclass
class _PairEconomics:
    """Commodity-independent economics of one (origin, destination) pair.

    Everything a trade plan needs that does not depend on the commodity:
    geometry, fuel logistics and safety, and the trading budget. Computed
    once per pair by :meth:`TraderBrain._pair_economics` and reused for every
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

    DOCKED = "docked"
    TRAVELING = "traveling"
    NEEDS_MAINTENANCE = "needs_maintenance"


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
    """Trader ship brain that maximizes profit.

    Plan-driven: evaluates complete buy, travel, sell opportunities before
    committing to purchases, and budgets round-trip fuel so the ship can
    return.
    """

    def __init__(self, ship: "Ship") -> None:
        """Initialize the trader brain."""
        super().__init__(ship)
        self._current_plan: Optional[TradePlan] = None
        # True once the plan's cargo is aboard, fully or as a partial load
        # after patience ran out, and the ship should fly to the plan's
        # destination rather than keep buying or sell locally.
        self._plan_loaded = False
        # Docked turns left in the current plan phase, accumulating or loaded
        # but unable to depart, before the plan is abandoned.
        self._plan_turns_left = 0
        # Set while this turn's local sell orders are pending so decide_travel
        # does not depart and strand them in the book.
        self._selling_locally = False
        # Shared per-simulation geometry and fuel-reachability cache.
        self._nav: Navigator = get_navigator(ship.simulation)
        # Memo of the last full plan search: (turn, planet, result). The
        # search runs in decide_trade_actions and, when it found nothing,
        # again in decide_travel the same turn; the memo answers the second
        # call without re-surveying the galaxy.
        self._plan_search_memo: Optional[tuple[int, Planet, Optional[TradePlan]]] = None
        # Consecutive turns the ship has been docked, empty, planless and too
        # poor to fund a short round trip. Past DISTRESS_PATIENCE the ship is
        # distressed and may sell tank fuel down to its survival target.
        self._distress_turns = 0
        # How many times this ship has entered distress. Exposed for analysis;
        # a rising count across the fleet means capital is mis-sized.
        self._distress_entries = 0

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
        """Commodities that can be traded between planets."""
        return self._nav.tradeable_commodities()

    def _fuel_commodity(self) -> Optional[CommodityDefinition]:
        """The nova_fuel commodity, or None if it is not defined."""
        return self._nav.fuel_commodity()

    def _fuel_purchasable_at(self, planet: Planet) -> bool:
        """Whether nova_fuel can be lifted from ``planet``'s book right now."""
        return self._nav.fuel_purchasable_at(planet)

    def _refuel_need_at(self, planet: Planet) -> int:
        """Fuel a ship sitting at ``planet`` must be able to obtain to stay free.

        The leg to the nearest other fuel-selling planet, or, when there is
        no other, the shortest lane hop out. A market that cannot supply
        this much is not an escape route, however cheap its top ask looks.
        """
        escape_fuel = self._min_escape_fuel(planet)
        if escape_fuel is not None:
            return escape_fuel
        nearest = self._nav.nearest_other_distance(planet)
        if nearest is None:
            return 0
        return self.ship.fuel_required(nearest)

    def _min_escape_fuel(self, from_planet: Planet) -> Optional[int]:
        """Fuel needed to reach the nearest fuel-selling planet from ``from_planet``.

        Returns None if fuel is not purchasable anywhere else in the galaxy.
        Fuel burn is monotone in distance, so the navigator's nearest source
        minimizes this ship's escape cost too.
        """
        distance = self._nav.nearest_fuel_source_distance(from_planet)
        if distance is None:
            return None
        return self.ship.fuel_required(distance)

    def _fuel_safe_destination(
        self, destination: Planet, return_planet: Planet, fuel_after_arrival: int
    ) -> bool:
        """Whether flying to ``destination`` leaves the ship an escape route.

        Safe when the destination's resting ask holds enough fuel to cover
        what the ship would still need to leave again, or when the fuel left
        after arrival already reaches the nearest planet where fuel is
        purchasable. A live ask on its own is not enough: a one-unit ask is
        a market a ship lands in and never leaves, which is how ships ended
        up parked with empty tanks and full purses. When fuel is purchasable
        nowhere in the galaxy yet, grounding the fleet would be worse than
        the risk, so the minimum requirement is retaining the return leg to
        ``return_planet``.
        """
        if self._fuel_purchasable_at(destination):
            shortfall = max(0, self._refuel_need_at(destination) - fuel_after_arrival)
            if shortfall <= 0 or self._nav.fuel_ask_depth_at(destination) >= shortfall:
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

        Below this the ship risks stranding: it cannot make even the shortest
        round trip.
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
        where fuel is purchasable; they can differ on fuel-poor planets.
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
        """Fuel units to keep on hand to stay mobile.

        The larger of two shortest round trips and the escape leg to a
        refueling planet, capped by the tank. This is the level worth paying
        scarcity prices for; anything beyond it is bunkering, only worth
        doing when fuel is cheap.
        """
        return min(
            self.ship.fuel_capacity,
            max(2 * self._fuel_reserve_need(), self._fuel_sell_reserve()),
        )

    @property
    def is_distressed(self) -> bool:
        """Whether the ship has been idle and cash-starved long enough to act.

        See DISTRESS_PATIENCE. Distress only widens what the ship may sell;
        it never relaxes a fuel-safety gate.
        """
        return self._distress_turns >= DISTRESS_PATIENCE

    def _short_trip_cash_floor(self) -> int:
        """Cash needed to fund the shortest round trip's fuel from here.

        Priced at the local fuel market, ignoring the tank: a ship whose
        whole purse is worth less than one short trip of fuel cannot fund a
        trade even with a full tank, because cargo must be paid for too.
        """
        planet = self.ship.planet
        fuel_commodity = self._fuel_commodity()
        if planet is None or fuel_commodity is None:
            return 0
        _, ask = planet.market.get_bid_ask_spread(fuel_commodity)
        price = (
            ask if ask is not None else self._flow_value(planet.market, fuel_commodity)
        )
        if price is None or price <= 0:
            reference = self._fuel_value_reference()
            price = math.ceil(reference) if reference else FUEL_BID_FALLBACK_FLOOR
        return self._fuel_reserve_need() * price

    def _update_distress(self, idle_and_broke: bool) -> None:
        """Advance or clear the distress counter for this docked turn."""
        if not idle_and_broke:
            self._distress_turns = 0
            return
        self._distress_turns += 1
        if self._distress_turns == DISTRESS_PATIENCE:
            self._distress_entries += 1

    def _fuel_value_reference(self) -> Optional[float]:
        """Cheapest believable fuel valuation anywhere in the galaxy.

        See :meth:`Navigator.fuel_value_reference` for the rationale.
        """
        return self._nav.fuel_value_reference()

    def _fuel_delivery_in_progress(self) -> bool:
        """Whether the ship is at the destination of an active fuel-run plan.

        Only then is tank fuel above the travel reserve trade cargo. At the
        origin the overflow-above-tank rule in :meth:`_sellable_quantity`
        already marks a loaded deliverer's excess fuel as cargo, so no origin
        case is needed here.
        """
        plan = self._current_plan
        if plan is None or plan.commodity.id != "nova_fuel":
            return False
        return self.ship.planet is plan.destination

    def _local_fuel_bid_is_scarcity_priced(self) -> bool:
        """Whether the local fuel bid clearly rewards offloading tank fuel.

        True when a standing local bid meets the delivery-margin markup over
        the cheapest ask anywhere in the galaxy, or the fallback floor when
        no ask exists. Such a bid can only rest in a book with no matching
        asks, typically another ship's standing rescue bid, so selling into
        it cannot create a sell-at-bid, re-buy-at-ask churn loop.
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
        - The travel reserve is never sellable. Selling the return-leg fuel
          strands ships, including fuel deliverers, which would otherwise
          dump their whole tank at a fuel-poor destination.
        - Tank fuel is trade cargo only during an explicit fuel-delivery plan
          or when the local bid is scarcity-priced, such as another ship's
          standing rescue bid; otherwise only overflow above a full tank is.
          Without that guard a topped-up ship sells its own tank at the
          local bid and re-buys at the ask every other turn, bleeding the
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
            # A distressed ship's tank is the only capital it has left, so it
            # may sell down to the survival target; see DISTRESS_PATIENCE.
            floor = (
                self._fuel_survival_target()
                if self.is_distressed
                else self.ship.fuel_capacity
            )
            reserve = max(reserve, floor)
        return max(0, quantity - reserve)

    def _place_flow_sell_orders(
        self, market: "Market", commodity: CommodityDefinition, quantity: int
    ) -> List[str]:
        """Sell ``quantity`` into both the resting bids and the flow.

        Matching executes at the sell order's price, so a single ask at the
        top bid liquidates the entire load at that one price, even into a
        1-credit probe bid. Instead, premium resting bids above the haircut
        flow price are captured by an ask priced at each level, and the
        remainder rests near the recent clearing price to be absorbed by the
        turn flow.

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
        only up to the survival target; filling tanks at spike prices
        bankrupts ships.

        ``pending_fuel`` and ``reserved_cargo`` account for buy orders
        already placed this turn, whose goods arrive at end-of-turn matching,
        so a top-up never crowds out the plan's cargo space or spends money
        the plan needs. Order placement reserves funds, so ``ship.money``
        already excludes the plan's committed money.
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
        # here; the guard is defensive.
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
        deliverer's round-trip burn at worst-case efficiency, amortized over
        ``quantity``, marked up by FUEL_BID_MARGIN so the delivery clears the
        15% arbitrage threshold. If no ask exists anywhere, falls back to a
        reference price escalated by local scarcity pressure, which grows
        each turn the bid goes unfilled.
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

        Anchors on a real local signal if one exists, never the fabricated
        default avg of 10, and escalates with scarcity pressure, which grows
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
        travel reserve and no local ask to lift. The bid rests in the book so
        other traders' cross-planet scans see it as a sell opportunity.
        decide_trade_actions re-posts it every docked turn while the
        condition holds, and the fallback price escalates via scarcity
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
        # Bid only up to the survival target, not a full tank. A tank-sized
        # rescue bid at delivery prices reserves most of the ship's money for
        # as long as it goes unfilled, locking it out of the trading that
        # could earn its way out.
        max_units = min(self._fuel_survival_target() - current_fuel, cargo_room)
        if max_units <= 0:
            return None

        budget = int(ship.money * 0.9)  # keep a small operating buffer
        price = self._fuel_bid_price(planet, max_units)
        quantity = min(max_units, budget // price) if price > 0 else 0
        if 0 < quantity < max_units:
            # Smaller bids amortize the delivery burn over fewer units, so
            # reprice once for the quantity we can afford.
            price = self._fuel_bid_price(planet, quantity)
            quantity = min(quantity, budget // price)
        if quantity <= 0:
            # Too poor for a delivery-viable bid; a 1-unit rescue run can
            # never amortize its burn. A local producer needs no delivery
            # margin, so bid the scarcity-escalated local reference with the
            # money that remains rather than going silent.
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
        trading budget, so :meth:`_best_plan_from` can evaluate many
        commodities per pair without redoing this work. Returns None when no
        plan over this pair can be feasible:
        - round-trip fuel would need buying where fuel is not purchasable
        - the destination would leave the ship without an escape route
        - no money remains for cargo after fuel, refuel floor, expected
          maintenance, and the operating buffer
        """
        fuel_commodity = self._fuel_commodity()
        if fuel_commodity is None:
            return None

        # Efficiency-adjusted fuel must match what start_journey consumes.
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

        fuel_to_buy = max(0, fuel_round_trip - current_fuel)
        if fuel_to_buy > 0 and not self._fuel_purchasable_at(origin):
            # The plan needs fuel that cannot be bought at the origin: no ask
            # and no recent flow. Committing would strand the ship with cargo.
            return None
        fuel_cost = fuel_to_buy * fuel_price

        # Never fly somewhere that leaves no escape route: the destination
        # must sell fuel, or the fuel left after arrival must reach a planet
        # that does.
        fuel_after_arrival = max(current_fuel, fuel_round_trip) - fuel_one_way
        if not self._fuel_safe_destination(destination, origin, fuel_after_arrival):
            return None

        # Expected maintenance over the round trip: two departure rolls, each
        # possibly costing the fuel-tier repair at origin fuel prices.
        maintenance_cost = math.ceil(
            2 * MAINTENANCE_CHANCE * MAINTENANCE_FUEL_UNITS * fuel_price
        )

        # Money for cargo. Withhold the fuel purchase, a cash floor that can
        # re-buy the travel reserve after the trip, expected maintenance, and
        # a 10% operating buffer. A trade that disappoints must never leave
        # the ship both broke and dry; that is the stranding spiral.
        # Only the reserve the trip does not leave in the tank has to be
        # re-bought. Charging the whole reserve in cash on top of fuel the
        # ship already holds is double counting, and it locked full-tank
        # ships out of every pair whenever fuel prices spiked.
        fuel_left_after_trip = max(current_fuel, fuel_round_trip) - fuel_round_trip
        refuel_shortfall = max(0, self._fuel_reserve_need() - fuel_left_after_trip)
        refuel_floor = refuel_shortfall * fuel_price
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
        - Commodity is acquirable at origin: a resting ask, or an active
          local flow the ship can bid into
        - Enough money for purchase plus fuel
        - Enough cargo space
        - Enough fuel for the round trip, held or purchasable

        Prices and quantities come from the flow, recent clearing prices and
        volume, as well as the resting book. The plan's purchase price is the
        bid the ship will post; matching executes at each seller's ask, so
        fills only come in at or below it.

        ``pair`` carries the commodity-independent economics of the pair;
        :meth:`_best_plan_from` precomputes it once per pair, and it is
        derived on the fly when omitted.
        """
        if pair is None:
            pair = self._pair_economics(origin, destination)
        if pair is None:
            return None

        origin_market = origin.market
        dest_market = destination.market

        # Acquisition price at origin: the bid the ship will post. A resting
        # ask is directly takeable; an active local flow, recent volume with
        # a real price signal, is biddable at the clearing price. Bid the
        # higher of the two: matching executes at each seller's ask, so a
        # generous bid captures more of the flow without paying more for the
        # cheap fills, and the margin gate below prices the worst case of
        # every unit at the bid.
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
        # ...plus the flow: recent clearing volume at the haircut clearing
        # price, a forecast rather than a resting order.
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

        # Budget and cargo limits are pair-level facts; only the buy price
        # is commodity-specific.
        max_by_money = pair.money_for_trading // buy_price
        max_quantity = max(0, min(max_by_money, pair.max_by_cargo))

        # Project revenue from the resting bids first, since their prices are
        # firm, then value the remainder at the haircut flow price.
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
        repositioning. The memo answers that second call.
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
        commodity: the top-value demand planets united with the nearest
        ones, or every demand planet in small galaxies. Both are superset
        filters; the evaluation re-verifies prices. When the galaxy shows no
        trade signal at all, planning is skipped. The commodity-independent
        economics of each pair are computed once and shared across
        commodities.
        """
        nav = self._nav
        if not nav.has_any_trade_signal():
            return None
        exportable = nav.exportable_commodities(origin)
        if not exportable:
            return None

        best_plan: Optional[TradePlan] = None
        best_profit = 0
        # Per-pair facts for this search only; the navigator owns all
        # cross-ship, cross-turn caching.
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

    def _maintain_fuel(self) -> List[str]:
        """Keep the tank viable at the docked planet, returning action strings.

        Top up when fuel is for sale locally; otherwise, below the stranding
        reserve, post a standing bid priced to entice a delivery run. Callers
        must not run this in the same turn as a fuel sell: buying into our
        own ask would self-trade.
        """
        planet = self.ship.planet
        fuel_commodity = self._fuel_commodity()
        if planet is None or fuel_commodity is None:
            return []
        market = planet.market
        actions: List[str] = []
        _, fuel_ask = market.get_bid_ask_spread(fuel_commodity)
        if fuel_ask is not None:
            if self._opportunistic_fuel_topup() is not None:
                actions.append("Topping up fuel tank")
        elif self.ship.cargo.get_quantity(fuel_commodity) < self._fuel_reserve_need():
            bid_order = self._post_standing_fuel_bid()
            if bid_order:
                order = market.orders_by_id[bid_order]
                actions.append(
                    f"Standing fuel bid: {order.quantity} at {order.price} "
                    "(no local fuel for sale)"
                )
        return actions

    def _execute_trade_plan(
        self,
        plan: TradePlan,
        fuel_handled: bool = False,
        prior_actions: Sequence[str] = (),
    ) -> None:
        """Execute a trade plan by placing buy orders for fuel and cargo.

        Buy orders are posted at the plan's bid price and rest in the book,
        filling from the turn's flow of asks; matching executes at each
        seller's ask, never above the bid. Called every accumulating turn,
        it re-posts for whatever the plan still lacks.

        With ``fuel_handled`` the fuel steps are skipped: the caller ran
        :meth:`_maintain_fuel` first because the tank was below the
        stranding reserve, and that bid owns the fuel side of the book this
        turn. Two fuel bids would double-buy and double-reserve the money
        the plan's cargo needs.

        The caller cancels this ship's resting orders before calling, so
        orders placed earlier this turn survive; ``prior_actions`` carries
        what those orders were, since this method owns ``last_action``.
        """
        planet = self.ship.planet
        if planet is None:
            return
        market = planet.market
        fuel_commodity = self._fuel_commodity()

        actions = list(prior_actions)

        # Step 1: buy fuel if needed.
        pending_fuel = 0
        pending_cargo = 0
        if fuel_commodity is not None and not fuel_handled:
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

        # Step 2: bid for the plan's remaining cargo at the plan's price. The
        # order rests in the book and fills at sellers' asks, never above the
        # bid.
        bid_price = plan.purchase_price_per_unit
        already_held = self._sellable_quantity(plan.commodity)
        still_needed = plan.quantity - already_held
        if bid_price > 0 and still_needed > 0:
            # Recompute what is affordable after the fuel purchase.
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

        # Step 3: top up toward a full tank with the space and money the plan
        # left over, unless the plan is itself a fuel run or the caller
        # already ran fuel upkeep this turn.
        if plan.commodity.id != "nova_fuel" and not fuel_handled:
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
        """Take this turn's trading actions at the current planet.

        1. If there is cargo to sell, sell it here or hold it for a better
           market
        2. Otherwise find the best trade plan and execute it
        3. If no profitable trade exists, maintain fuel and wait
        """
        if not self.ship.planet:
            return

        # The first ship deciding this turn rebuilds the market-fact snapshot;
        # the rest share it.
        self._nav.refresh_market_facts(turn=self.ship.simulation.current_turn)

        market = self.ship.planet.market
        fuel_commodity = self._fuel_commodity()

        if not fuel_commodity:
            self.ship.last_action = "No trading - fuel commodity not available"
            return

        existing_orders = market.get_actor_orders(self.ship)
        for order in existing_orders["buy"] + existing_orders["sell"]:
            market.cancel_order(order.order_id)

        actions = []
        self._selling_locally = False

        # Distress bookkeeping, before anything reads is_distressed. A ship
        # that is docked, empty of trade goods and poorer than one short
        # round trip of fuel is locked out of the planner: every pair fails
        # the cash gate and there is no income without a sale. After
        # DISTRESS_PATIENCE such turns it may sell tank fuel down to its
        # survival target and trade its way back.
        #
        # Holding a plan does not clear the condition. A plan whose bid
        # never fills is re-adopted turn after turn, so requiring
        # ``_current_plan is None`` meant the ships most in need of the exit
        # were exactly the ones that could never reach it. Filling cargo,
        # not merely intending to, is what proves a ship is trading again.
        non_fuel_cargo = any(
            self.ship.cargo.get_quantity(c) > 0
            for c in self._get_tradeable_commodities()
            if c.id != "nova_fuel"
        )
        self._update_distress(
            not non_fuel_cargo and self.ship.money < self._short_trip_cash_floor()
        )

        # Fuel below the travel reserve is not trade cargo; see
        # _sellable_quantity.
        has_trade_cargo = any(
            self._sellable_quantity(c) > 0 for c in self._get_tradeable_commodities()
        )

        placed_fuel_sell = False

        # Fuel upkeep first, whenever the tank is under the stranding
        # reserve. Every branch below can return early - an accumulating plan
        # holds the turn for up to ACCUMULATION_PATIENCE turns, and adopting
        # a plan returns outright - so upkeep placed after them never ran for
        # the ships that needed it, and a dry ship with a plan it could not
        # fly posted no rescue bid at all. No fuel sell can have happened
        # yet, and none can happen later this turn either: below the reserve
        # _sellable_quantity yields no fuel, so there is no self-trade to
        # guard against here.
        fuel_upkeep_ran = (
            self.ship.cargo.get_quantity(fuel_commodity) < self._fuel_reserve_need()
        )
        if fuel_upkeep_ran:
            actions.extend(self._maintain_fuel())

        # Plan lifecycle. Flow-based plans fill a resting bid over several
        # docked turns, then fly the load to the plan's destination.
        plan = self._current_plan
        if plan is not None:
            if self.ship.planet is plan.destination:
                # Arrived: the sell logic below disposes of the cargo. The
                # plan lingers only so _fuel_delivery_in_progress marks a fuel
                # delivery's tank as trade cargo, and is dropped once the
                # cargo is gone.
                self._plan_loaded = False
                if self._sellable_quantity(plan.commodity) <= 0:
                    self._current_plan = None
            elif self.ship.planet is not plan.origin:
                # Diverted by a maintenance or survival reposition: abandon.
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
                    self._execute_trade_plan(
                        plan, fuel_handled=fuel_upkeep_ran, prior_actions=actions
                    )
                    return
                elif held > 0:
                    # Patience exhausted: depart with the partial load.
                    self._plan_loaded = True
                    self._plan_turns_left = ACCUMULATION_PATIENCE
                else:
                    # Patience exhausted, nothing filled: replan from scratch.
                    self._current_plan = None
            else:
                # Loaded at origin. Departure happens in decide_travel, so
                # being here next turn means it was blocked, usually on fuel.
                # Wait a bounded while, then release the cargo to the plain
                # sell-or-fly logic.
                if self._plan_turns_left > 0:
                    self._plan_turns_left -= 1
                else:
                    self._current_plan = None
                    self._plan_loaded = False

        # Cargo: sell here or travel. A loaded plan's cargo flies to
        # plan.destination instead.
        if has_trade_cargo and not self._plan_loaded:
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
                # good the local auction clears.
                local_price = max(
                    local_bid or 0, self._flow_value(market, commodity) or 0
                )

                for planet in self.ship.simulation.planets:
                    if planet == current_planet:
                        continue

                    distance = self._nav.distance(current_planet, planet)
                    fuel_needed = self.ship.fuel_required(distance)

                    if fuel_available < fuel_needed:
                        continue

                    # Only a destination decide_travel would fly to can
                    # justify holding cargo. It also vetoes fuel dead ends;
                    # without the same check here the ship holds forever for
                    # a trip it never departs on.
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

                    # Compare net values the way decide_travel does:
                    # destination revenue minus the fuel to get there, against
                    # revenue here. A bare unit-price comparison holds tiny
                    # cargoes forever for trips whose fuel cost decide_travel
                    # never approves.
                    origin_fuel_price = market.get_avg_price(fuel_commodity) or 10
                    dest_net = dest_price * quantity - fuel_needed * origin_fuel_price
                    if dest_net > local_price * quantity * 1.15:
                        should_sell_here = False
                        break

                if not should_sell_here:
                    break

            if should_sell_here:
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
                # decide_travel will fly it there.
                actions.append("Holding cargo for better price elsewhere")

        if not has_trade_cargo:
            # No cargo: adopt the best trade plan.
            plan = self._find_best_trade_plan()
            if plan:
                self._current_plan = plan
                self._plan_loaded = False
                self._plan_turns_left = ACCUMULATION_PATIENCE
                self._execute_trade_plan(
                    plan, fuel_handled=fuel_upkeep_ran, prior_actions=actions
                )
                return  # _execute_trade_plan sets last_action
            self._current_plan = None

        # Fuel upkeep for the ships that did not need it before the plan
        # branches: above the stranding reserve this is opportunistic
        # bunkering, and it must not run in the same turn as a fuel sell,
        # since buying into our own ask would self-trade.
        if not fuel_upkeep_ran and not placed_fuel_sell:
            actions.extend(self._maintain_fuel())

        if actions:
            self.ship.last_action = "; ".join(actions)
        else:
            self.ship.last_action = "No trade actions (waiting for opportunities)"

    def decide_travel(self) -> Optional[Planet]:
        """Decide whether to travel, and where.

        1. Stay docked while a plan is accumulating; buying happens locally
        2. With cargo, pick the destination with the highest value after
           fuel cost
        3. Empty and with nothing to source here, reposition
        """
        if self.ship.status != ShipStatus.DOCKED:
            return None

        if not self.ship.planet or not self.ship.simulation.planets:
            return None

        # We committed to selling here this turn. Departing would strand the
        # fresh sell orders in the book, or with cancel-on-depart abort the
        # sale decide_trade_actions just chose.
        if self._selling_locally:
            return None

        # Ensure the galaxy's per-turn market-fact snapshot is current.
        self._nav.refresh_market_facts(turn=self.ship.simulation.current_turn)

        fuel_commodity = self._fuel_commodity()
        if not fuel_commodity:
            return None

        current_planet = self.ship.planet
        fuel_available = self.ship.cargo.get_quantity(fuel_commodity)

        # Plan-driven travel: stay docked while accumulating; once loaded,
        # fly to the destination if fuel and safety allow. Otherwise stay and
        # let fuel upkeep work; the loaded-phase patience in
        # decide_trade_actions bounds the wait.
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

        # Reserve fuel is not cargo.
        commodities = self._get_tradeable_commodities()
        cargo_to_sell = {
            c: self._sellable_quantity(c)
            for c in commodities
            if self._sellable_quantity(c) > 0
        }

        if not cargo_to_sell:
            # No cargo. If a profitable export can be sourced here, stay and
            # let decide_trade_actions buy it. Otherwise reposition empty
            # toward the best sourcing planet rather than sit where nothing is
            # worth exporting.
            if self._find_best_trade_plan() is not None:
                return None
            reposition = self._find_reposition_target(fuel_available, fuel_commodity)
            if reposition is not None:
                return reposition
            # Nothing profitable anywhere. Idling is only safe where fuel can
            # be bought. On a fuel desert every waiting turn risks the tank
            # dropping below the escape threshold, and no local producer can
            # answer a rescue bid. Move to where refueling is plausible while
            # we still can. A supplier who traded recently counts here even
            # with an empty book: the question is whether anyone local can
            # ever fill a standing bid, not whether fuel is liftable today.
            if not (
                self._fuel_purchasable_at(current_planet)
                or self._nav.fuel_traded_recently(current_planet)
            ):
                return self._survival_reposition_target(fuel_available)
            return None

        best_planet = None
        best_expected_value = 0

        for destination in self.ship.simulation.planets:
            if destination == current_planet:
                continue

            distance = self._nav.distance(current_planet, destination)
            fuel_needed = self.ship.fuel_required(distance)

            if fuel_available < fuel_needed:
                continue

            # Never fly cargo into a fuel dead end.
            if not self._fuel_safe_destination(
                destination, current_planet, fuel_available - fuel_needed
            ):
                continue

            dest_market = destination.market
            total_value = 0

            for commodity, quantity in cargo_to_sell.items():
                bid, _ = dest_market.get_bid_ask_spread(commodity)
                price = max(bid or 0, self._flow_value(dest_market, commodity) or 0)
                if price > 0:
                    total_value += price * quantity

            # Fuel is costed at origin prices.
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

        This is the last resort, so it accepts weaker evidence than a plan
        gate does. First choice is a planet with a live fuel ask; second is
        one where fuel traded in the recent window; third is one that has
        ever traded fuel, since a producer there can answer a standing
        rescue bid, unlike on a never-traded fuel desert. Returns None when
        no such planet is in range; then staying put and posting a standing
        bid is all that is left.
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
            elif self._nav.fuel_traded_recently(planet):
                tier = 1
            elif planet.market.has_price_signal(fuel_commodity):
                tier = 2
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
        from each. Returns the origin backing the most profitable one, or
        None if none is reachable or profitable.
        """
        current_planet = self.ship.planet
        if current_planet is None:
            return None

        # Cold galaxy: no commodity has both supply and demand anywhere, so
        # no origin can back a plan; skip the per-origin surveys.
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
    """A trading ship that travels between planets."""

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
        self.reserved_money = 0
        self.planet = planet
        self.destination: Optional[Planet] = None  # None while docked
        # Lane route being flown: origin first, destination last, every
        # consecutive pair joined by a star lane. Empty while docked.
        self.route: List[Planet] = []
        self.cargo = Inventory()
        self.inventory = self.cargo  # Alias for compatibility with market code
        self.cargo_capacity = cargo_capacity
        self.fuel_capacity = fuel_capacity
        self.fuel_efficiency = fuel_efficiency  # Fuel burn is divided by this
        self.travel_progress = 0.0  # 0.0 to 1.0
        self.travel_time = 0  # Turns for the current journey
        self.active_orders: Dict[
            str, str
        ] = {}  # Track active order IDs and their types
        self.last_action = "None"
        self.status = ShipStatus.DOCKED
        self.simulation = simulation
        self.food_consumed_this_turn = (
            True  # Ships don't eat, but needed for compatibility
        )
        self.drives: list[
            "ActorDrive"
        ] = []  # Ships don't have drives, but keep empty list for interface compatibility

        self.brain = TraderBrain(self)

    def route_distance(self, origin: Planet, destination: Planet) -> float:
        """Length of the shortest star-lane route between two planets.

        Ships fly along lanes, so fuel and travel time are charged on this,
        not the straight-line distance.
        """
        return get_navigator(self.simulation).distance(origin, destination)

    @staticmethod
    def calculate_fuel_needed(distance: float) -> int:
        """Baseline fuel for a journey of ``distance``, ignoring efficiency.

        Planning for a specific ship must use :meth:`fuel_required`, which
        applies the ship's fuel efficiency the same way departure does.
        """
        # 1 fuel per 20 distance units, rounded up.
        return math.ceil(distance / 20)

    def fuel_required(self, distance: float) -> int:
        """Efficiency-adjusted fuel this ship burns for a journey of ``distance``.

        Uses the same rounding as departure so planning and consumption
        never disagree; otherwise ships with efficiency < 1.0 under-reserve
        fuel and strand.
        """
        return math.ceil(Ship.calculate_fuel_needed(distance) / self.fuel_efficiency)

    def check_maintenance(self) -> bool:
        """Roll whether the ship needs maintenance before this departure."""
        return random.random() < MAINTENANCE_CHANCE

    def perform_maintenance(self) -> bool:
        """Attempt to perform maintenance on the ship.

        Tries tiered maintenance goods from best to worst:
        - ship_components, 1 unit: best quality
        - ship_parts, 2 units: medium quality
        - ship_supplies, 3 units: basic quality
        - nova_fuel, 5 units: legacy fallback

        Returns True if maintenance succeeded, False if supplies are lacking.
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

        A ship that rolls a maintenance need on departure is locked out of
        the trading branch until repaired, so without this it could never
        acquire the supplies to repair itself. Buys the cheapest available
        maintenance tier; the order fills at end of turn and
        perform_maintenance succeeds next turn.
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
        # so producers see the demand, the maintenance analogue of the
        # standing fuel rescue bid. Without them a ship needing repairs where
        # no supplies are for sale is deadlocked forever, unable to trade its
        # way out. Bid on every completable tier money allows, preferring
        # tiers whose commodity has traded somewhere: a bid on a good nobody
        # in the galaxy produces, such as ship_components early on, can rest
        # unfilled indefinitely while a fillable tier would have freed the
        # ship. Re-posted each turn; prices grow with scarcity pressure while
        # unfilled.
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
        """Begin a journey to ``destination``.

        Returns True if the journey started, False otherwise.
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

        # Make sure the origin planet lists this ship.
        if self.planet and self not in self.planet.ships:
            self.planet.ships.append(self)

        if self.check_maintenance():
            self.status = ShipStatus.NEEDS_MAINTENANCE
            self.last_action = "Maintenance required before departure"
            return False

        # Cancel resting orders before departing. Cancellation is
        # local-market-only, so a ship that leaves with orders in the book
        # can never reclaim their reserved money or cargo unless it returns;
        # otherwise ships strand in needs_maintenance because the fuel they
        # need is reserved by a stale sell order elsewhere. This runs before
        # the fuel check so fuel held by such an order counts as available.
        origin_market = self.planet.market
        resting = origin_market.get_actor_orders(self)
        for order in resting["buy"] + resting["sell"]:
            origin_market.cancel_order(order.order_id)

        fuel_commodity = self.simulation.commodity_registry.get_commodity("nova_fuel")

        if not fuel_commodity:
            self.last_action = "Cannot start journey - fuel commodity not defined"
            return False

        # The whole route is fuelled up front; intermediate planets are flown
        # past, not visited.
        navigator = get_navigator(self.simulation)
        route = navigator.route(self.planet, destination)
        distance = navigator.distance(self.planet, destination)
        adjusted_fuel_needed = self.fuel_required(distance)

        if not self.cargo.has_quantity(fuel_commodity, adjusted_fuel_needed):
            self.last_action = (
                f"Insufficient fuel for journey (need {adjusted_fuel_needed})"
            )
            return False

        self.cargo.remove_commodity(fuel_commodity, adjusted_fuel_needed)

        # 1 turn per 20 distance units, minimum 1.
        self.travel_time = max(1, math.ceil(distance / 20))
        self.travel_progress = 0.0
        self.status = ShipStatus.TRAVELING
        self.destination = destination
        self.route = route

        hops = len(route) - 1
        self.last_action = (
            f"Departed for {destination.name} "
            f"({self.travel_time} turns, {hops} lane{'s' if hops != 1 else ''})"
        )
        return True

    def update_journey(self) -> bool:
        """Advance the journey by one turn.

        Returns True on arrival, False otherwise.
        """
        if self.status != ShipStatus.TRAVELING:
            return False

        if not self.destination:
            self.status = ShipStatus.DOCKED
            return False

        progress_increment = 1.0 / self.travel_time
        self.travel_progress += progress_increment

        if self.travel_progress >= 1.0:
            old_planet = self.planet
            self.planet = self.destination
            self.destination = None
            self.route = []
            self.status = ShipStatus.DOCKED
            self.travel_progress = 0

            # Move the ship between the planets' ship lists.
            if old_planet and self in old_planet.ships:
                old_planet.ships.remove(self)

            if self.planet:
                if self not in self.planet.ships:
                    self.planet.ships.append(self)

            self.last_action = f"Arrived at {self.planet.name}"
            return True
        else:
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
        if self.status == ShipStatus.TRAVELING:
            self.update_journey()
        elif self.status == ShipStatus.NEEDS_MAINTENANCE:
            # Buy supplies locally when repair fails so the ship can repair
            # next turn instead of stranding.
            if not self.perform_maintenance():
                self._buy_maintenance_supplies()
        elif self.status == ShipStatus.DOCKED:
            self.brain.decide_trade_actions()

            destination = self.brain.decide_travel()
            if destination:
                self.start_journey(destination)


def mean_round_trip_fuel(mean_pair_distance: float, fuel_efficiency: float) -> int:
    """Fuel a ship of ``fuel_efficiency`` burns on an average round trip.

    ``mean_pair_distance`` is the mean shortest lane route between planets,
    from :meth:`Navigator.mean_pair_distance`.
    """
    one_way = math.ceil(
        Ship.calculate_fuel_needed(mean_pair_distance) / fuel_efficiency
    )
    return 2 * one_way


def starting_capital(mean_pair_distance: float, fuel_efficiency: float) -> int:
    """Starting money for a ship launched into a galaxy of this size.

    Sized as SHIP_CAPITAL_ROUND_TRIPS average round trips of fuel plus the
    maintenance those trips expect, valued at
    SHIP_CAPITAL_FUEL_PRICE_REFERENCE, marked up by a working-capital
    fraction for cargo, and floored at the small-galaxy baseline.
    """
    fuel_units = mean_round_trip_fuel(mean_pair_distance, fuel_efficiency) + (
        2 * MAINTENANCE_CHANCE * MAINTENANCE_FUEL_UNITS
    )
    budget = (
        SHIP_CAPITAL_ROUND_TRIPS
        * fuel_units
        * SHIP_CAPITAL_FUEL_PRICE_REFERENCE
        * (1.0 + SHIP_CAPITAL_RESERVE_FRACTION)
    )
    return max(SHIP_CAPITAL_FLOOR, int(budget))


def fuel_capacity_for(mean_pair_distance: float, fuel_efficiency: float) -> int:
    """Tank size for a galaxy of this size, never below the baseline."""
    return max(
        BASE_FUEL_CAPACITY,
        math.ceil(
            FUEL_CAPACITY_ROUND_TRIP_HEADROOM
            * mean_round_trip_fuel(mean_pair_distance, fuel_efficiency)
        ),
    )
