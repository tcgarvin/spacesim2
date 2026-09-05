import enum
import math
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple

from spacesim2.core.commodity import CommodityDefinition, Inventory
from spacesim2.core.navigation import (
    DELIVERER_WORST_FUEL_EFFICIENCY,  # noqa: F401  re-exported for callers
    FLOW_RECENCY_TURNS,
    FUEL_BID_FALLBACK_FLOOR,
    FUEL_BID_MARGIN,
    Navigator,
    get_navigator,
)
from spacesim2.core.planet import Planet

if TYPE_CHECKING:
    from spacesim2.core.drives.actor_drive import ActorDrive
    from spacesim2.core.market import Market
    from spacesim2.core.simulation import Simulation

# FUEL_BID_MARGIN, FUEL_BID_FALLBACK_FLOOR and DELIVERER_WORST_FUEL_EFFICIENCY
# live in core/navigation.py, next to the delivery-bid pricing they
# parameterize, and are re-exported here because ships and their tests have
# always read them from this module.

# A docked ship fills its tank only while the local ask is within this
# multiple of the galaxy fuel reference price, the median believable
# per-planet valuation. Above it, it buys only the survival minimum:
# filling a whole tank at spike prices bankrupts ships. A typical planet
# sits near the reference and bunkers; only a real spike is priced out.
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
    and profit of one haul.

    Two prices per unit, deliberately distinct:
    - ``bid_price_per_unit`` is what the ship posts in the book. It may sit
      above the cheapest resting ask so the order also wins units out of the
      turn's flow; matching executes at each seller's ask, so bidding high
      never overpays for the cheap fills.
    - ``purchase_price_per_unit`` is what the cargo is expected to *cost*:
      the resting asks walked for ``quantity`` units, any remainder priced at
      the bid. Judging the margin on the bid inflated the cost basis of every
      plan that had a real cheap ask behind it, and that inflated number also
      filtered the destination's bids and flow.

    Fuel is charged one way, not round trip. This cargo rides the outbound
    leg only; the return leg is capital the *next* trade spends. Charging
    both legs to one haul killed genuine spreads whose quantity was
    flow-capped to a handful of units. The round trip still has to be
    *funded*: that gate lives in :meth:`TraderBrain._pair_economics`, which
    reserves round-trip fuel cash and a refuel floor before a credit reaches
    cargo.
    """

    origin: Planet
    destination: Planet
    commodity: CommodityDefinition

    # Quantities and costs
    quantity: int
    bid_price_per_unit: int
    purchase_price_per_unit: int
    expected_sell_price_per_unit: int

    # Fuel calculations. Of the outbound leg's burn, ``fuel_units_from_tank``
    # units are already aboard and are valued at ``fuel_price_from_tank`` -
    # the galaxy fuel reference, what replacing them typically costs. The
    # rest must be bought here at ``fuel_price_at_origin``, the local ask,
    # however spiked that is.
    distance: float
    fuel_needed_one_way: int
    fuel_price_at_origin: int
    fuel_units_from_tank: int
    fuel_price_from_tank: int

    # Expected cost of maintenance rolls over the round trip: 2 departures x
    # MAINTENANCE_CHANCE x the fuel-tier repair cost. Without it penny-margin
    # trades look profitable when one repair wipes out several trips of
    # profit.
    expected_maintenance_cost: int = 0

    @property
    def fuel_needed_round_trip(self) -> int:
        """Fuel for the round trip, which the cash gate budgets for."""
        return self.fuel_needed_one_way * 2

    @property
    def total_fuel_cost(self) -> int:
        """Cost of the outbound leg's fuel, the only leg this cargo rides.

        Units already aboard are charged at the fuel reference, units that
        must be bought at the local ask. Both are charged: fuel burned is
        value spent, whenever it was bought.
        """
        from_tank = min(self.fuel_units_from_tank, self.fuel_needed_one_way)
        to_buy = self.fuel_needed_one_way - from_tank
        return (
            from_tank * self.fuel_price_from_tank + to_buy * self.fuel_price_at_origin
        )

    @property
    def total_purchase_cost(self) -> int:
        """Expected cost of the cargo, at the evaluation price."""
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
    def return_leg_fuel_cost(self) -> int:
        """Cost of buying the return leg's fuel at the origin's ask.

        The haul itself is charged one way (see the class docstring), because
        the return leg is capital the next trade spends. A ship with no
        capital has no next trade to spend it: the profit of this haul is the
        only money the return leg can come from, so a distressed ship judges
        the haul against this too. Priced at the origin ask, which is what
        such a ship actually pays before it leaves.
        """
        return self.fuel_needed_one_way * self.fuel_price_at_origin

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


@dataclass(frozen=True)
class _RepositionIntent:
    """An empty reposition chosen but not yet flown.

    ``origin`` is the planet the choice was made at, so the intent can be
    recognised as stale anywhere else. One record rather than a target and a
    separate marker keeps the two from disagreeing.
    """

    origin: Planet
    target: Planet


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
    # Local ask (or the avg-price fallback): what fuel bought here costs.
    fuel_price: int
    # Typical believable fuel price across the galaxy: what fuel already in
    # the tank is worth, and what replacing it normally costs.
    fuel_reference_price: int
    # Round-trip shortfall the ship buys here, at ``fuel_price``.
    fuel_to_buy: int
    # Units of the outbound leg's burn already aboard. The rest come out of
    # ``fuel_to_buy`` and are charged at the local ask.
    fuel_from_tank_one_way: int
    expected_maintenance_cost: int
    money_for_trading: int
    max_by_cargo: int


@dataclass
class _OriginAcquisition:
    """What one commodity costs to acquire at one origin planet.

    Commodity-specific but destination-independent, so
    :meth:`TraderBrain._best_plan_from` computes it once per commodity and
    reuses it across every candidate destination.
    """

    # Resting asks as (price, quantity), cheapest first: the units the ship
    # could lift right now, and at what price.
    ask_levels: List[Tuple[int, int]]
    # Recent clearing price at the origin, 0 when nothing is flowing. Units
    # beyond the resting asks have to be won out of the flow at this price.
    flow_price: int
    # Price the ship posts, max(best ask, flow price); see TradePlan.
    bid_price: int
    # Cheapest liftable unit price: the best resting ask when one exists,
    # else the flow price. Screens destination demand before the exact
    # quantity, and so the exact walked cost, is known.
    entry_price: int


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
        # does not depart and strand them in the book. It lasts one turn: see
        # _refresh_local_sale_staleness.
        self._selling_locally = False
        # Local-sale bookkeeping: the raw held units of each commodity listed
        # here last turn, and the planet they were listed at. Comparing held
        # units, not sellable ones, is what tells a fill from a change of
        # mind - sellable fuel moves with the local bid, not with fills.
        # _local_sale_stale means every listed good went a full turn untouched.
        self._local_sale_held: Dict[CommodityDefinition, int] = {}
        self._local_sale_planet_name = ""
        self._local_sale_stale = False
        # Fuel the trip this ship has committed its cargo to will need at
        # departure. Recomputed from scratch every docked turn, before any
        # fuel order is placed, so it can never speak for a planet or a plan
        # the ship has moved on from. Fuel for a committed profitable trip is
        # not speculative bunkering, so the top-up buys it even at a scarcity
        # price.
        self._committed_fuel_need = 0
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
        # Empty reposition the ship has chosen but cannot fly yet because the
        # fuel for it is still in the local ask book rather than the tank.
        # Held across turns so decide_trade_actions can fund it through
        # ``_committed_fuel_need``, and kept while it stays viable so the
        # ship does not re-aim at a new target every turn it waits for fuel;
        # dropped as soon as the ship is anywhere other than the planet the
        # choice was made at.
        self._reposition_intent: Optional[_RepositionIntent] = None

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

    def _arrival_fuel_requirement(
        self, destination: Planet, return_planet: Planet
    ) -> int:
        """Fuel that must remain on arrival for ``destination`` to be safe.

        The single source of truth behind :meth:`_fuel_safe_destination`, so
        callers that have to *fund* a trip ask the same question the gate
        that approves it asks, instead of guessing.

        The requirement is the escape leg: fuel enough, on arrival, to reach
        the nearest *other* planet that sells fuel. It is a hard floor, and
        depth in the destination's own ask book never lowers it. Ask depth
        used to waive the reserve outright, and that is what stranded the
        fleet: approval reads the book several turns before the ship lands,
        the depth is gone by arrival in a sixth of cases, and the ship
        touches down dry on a planet with no seller. Standing rescue bids
        almost never fill, so there is no way back out. Depth is a transient
        market fact; the escape leg is a property of the galaxy.

        Only when fuel is purchasable nowhere else in the galaxy is there no
        escape leg to demand. Grounding the whole fleet would then be worse
        than the risk, so the requirement falls back to the return leg to
        ``return_planet``, which the destination's own ask depth may still
        offset.
        """
        escape_fuel = self._min_escape_fuel(destination)
        if escape_fuel is not None:
            return escape_fuel
        requirement = self.ship.fuel_required(
            self._nav.distance(destination, return_planet)
        )
        if self._fuel_purchasable_at(destination):
            depth = self._nav.fuel_ask_depth_at(destination)
            unsupplied = self._refuel_need_at(destination) - depth
            requirement = min(requirement, max(0, unsupplied))
        return requirement

    def _fuel_safe_destination(
        self, destination: Planet, return_planet: Planet, fuel_after_arrival: int
    ) -> bool:
        """Whether flying to ``destination`` leaves the ship an escape route."""
        return fuel_after_arrival >= self._arrival_fuel_requirement(
            destination, return_planet
        )

    def _departure_fuel_requirement(self, destination: Planet) -> int:
        """Fuel the departure gate will demand before flying to ``destination``.

        The one-way leg plus the escape fuel the destination requires on
        arrival, capped by the tank. :meth:`decide_travel` departs exactly
        when the tank holds this much, so a hold decision that judges reach
        by this number and a top-up that buys up to it agree with the gate by
        construction. Committing to the bare leg was what left ships holding
        cargo forever: they bought one leg's worth, and the gate then refused
        them for the arrival reserve they had never funded. Since the arrival
        reserve is now an unconditional escape leg, hold-cargo trips, plan
        departures and empty repositions all fund the same number, and
        :meth:`_opportunistic_fuel_topup` buys up to it via
        ``_committed_fuel_need``.
        """
        origin = self.ship.planet
        if origin is None:
            return 0
        leg = self.ship.fuel_required(self._nav.distance(origin, destination))
        return min(
            self.ship.fuel_capacity,
            leg + self._arrival_fuel_requirement(destination, origin),
        )

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

    def is_stranded(self) -> bool:
        """Whether this ship is docked, fuel-short, and has no local ask.

        True when the ship is docked (not traveling), holds less fuel than
        its round-trip reserve need, and its current planet has no live
        nova_fuel ask to buy up from. Used by the KPI summary to count ships
        at risk of being unable to leave.
        """
        planet = self.ship.planet
        if planet is None or self.ship.destination is not None:
            return False
        fuel_commodity = self._fuel_commodity()
        fuel_on_hand = (
            self.ship.cargo.get_quantity(fuel_commodity)
            if fuel_commodity is not None
            else 0
        )
        if fuel_on_hand >= self._fuel_reserve_need():
            return False
        return not self._nav.fuel_purchasable_at(planet)

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

    def _affordable_local_fuel(self, planet: Planet) -> int:
        """Fuel units the ship could buy at ``planet`` right now.

        The reach of a docked ship is the tank plus this: ships run near the
        survival target, so judging any trip on tank fuel alone rejects trips
        the ship could trivially fund from the book in front of it. Bounded
        by hold room, 90% of money at the local ask - the same operating
        buffer every other buy keeps - and the tank's remaining capacity.
        Zero where fuel is not purchasable.
        """
        ship = self.ship
        fuel_commodity = self._fuel_commodity()
        if fuel_commodity is None or not self._fuel_purchasable_at(planet):
            return 0
        _, ask = planet.market.get_bid_ask_spread(fuel_commodity)
        if ask is None or ask <= 0:
            return 0
        cargo_room = ship.cargo_capacity - ship.cargo.get_total_quantity()
        tank_room = ship.fuel_capacity - ship.cargo.get_quantity(fuel_commodity)
        return max(0, min(cargo_room, tank_room, int(ship.money * 0.9) // ask))

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

    def _fuel_escape_target(self) -> Optional[int]:
        """Tank level that buys a way off this planet and no more, or None.

        The rationed alternative to :meth:`_fuel_survival_target` when the
        local ask is spiked: the leg to the nearest planet that sells fuel
        plus that planet's own arrival floor, so the ship is not merely
        moved to a second trap. It is exactly the number
        :meth:`_departure_fuel_requirement` would demand for that hop, which
        is the number the departure gate checks, so a ship that funds this
        can actually leave.

        Returns None when there is no such hop the arrival floor approves
        (typically because the requirement exceeds the tank). Callers must
        then buy the full survival target: overpaying beats dying in place.

        Only the nearest fuel seller is considered. Fuel burn is monotone in
        distance, so a farther seller costs strictly more leg fuel, and the
        point of rationing is to spend as little as possible at a spiked ask.
        """
        origin = self.ship.planet
        if origin is None:
            return None
        for candidate in self._nav.planets_by_proximity(origin):
            if not self._fuel_purchasable_at(candidate):
                continue
            target = self._departure_fuel_requirement(candidate)
            leg = self.ship.fuel_required(self._nav.distance(origin, candidate))
            if self._fuel_safe_destination(candidate, origin, target - leg):
                return target
            return None
        return None

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
        With no local price at all, falls back to the galaxy's typical
        believable fuel price rather than its cheapest, so the floor
        reflects what fuel really costs.
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
        """Advance or clear the distress counter for this docked turn.

        Entering and leaving are deliberately different tests, and so are
        entering and *staying*. ``idle_and_broke`` only gates the first turn
        of the count: a ship starts the clock when it is idle *and* poorer
        than one short round trip of fuel, but once the count is running it
        advances every docked turn the purse stays under that floor, whether
        or not the ship is idle. Winning cargo is not the same as being able
        to fund a trip, and the count must not restart every time a bid
        fills. It leaves only when its purse clears the floor again. Clearing
        on cargo alone was the bug: a distressed ship that won a few units
        into its hold dropped straight out of distress while still unable to
        fund a trip, lost the wider selling and margin rules that were about
        to get it moving, and fell back in a turn later. Cash above the floor
        is the only evidence that the ship can trade unaided.
        """
        if self.ship.money >= self._short_trip_cash_floor():
            self._distress_turns = 0
            return
        if self._distress_turns == 0 and not idle_and_broke:
            # Below the floor but still working a hold of cargo: not idle, so
            # the clock has not started.
            return
        self._distress_turns += 1
        if self._distress_turns == DISTRESS_PATIENCE:
            self._distress_entries += 1

    def _fuel_value_reference(self) -> Optional[float]:
        """Typical believable fuel valuation across the galaxy.

        The median of the per-planet believable valuations, not the galaxy
        minimum. See :meth:`Navigator.fuel_value_reference` for the
        rationale.
        """
        return self._nav.fuel_value_reference()

    def _fuel_delivery_in_progress(self) -> bool:
        """Whether the ship is at either end of an active fuel-run plan.

        At both ends, tank fuel above the travel reserve is the plan's trade
        cargo. The origin case matters as much as the destination: the plan
        counts its load through :meth:`_sellable_quantity`, so while only
        overflow above a full tank counted at the origin, a fuel plan could
        never reach ``_plan_loaded`` and timed out after
        ACCUMULATION_PATIENCE every time. Fuel arbitrage was structurally
        dead, on a map where dozens of planets have no fuel ask at all.

        Being at the origin of a fuel plan is not a licence to sell the tank
        here: the plan lifecycle in :meth:`decide_trade_actions` marks such a
        ship loaded and routes it to the destination instead.
        """
        plan = self._current_plan
        if plan is None or plan.commodity.id != "nova_fuel":
            return False
        return self.ship.planet is plan.destination or self.ship.planet is plan.origin

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

    def _committed_fuel_floor(self) -> int:
        """Fuel the departure this ship is committed to from here will need.

        Derived live from the loaded plan or the reposition intent rather
        than read off ``_committed_fuel_need``: that field is rebuilt part
        way through the docked turn, so the first reads of a turn - the ones
        that decide whether the tank counts as trade cargo - would otherwise
        still be answering for the planet the ship just left. Both sources
        here name their own planet, so neither can speak for another one.
        """
        planet = self.ship.planet
        if planet is None:
            return 0
        need = 0
        plan = self._current_plan
        if plan is not None and self._plan_loaded and planet is plan.origin:
            need = max(need, self._departure_fuel_requirement(plan.destination))
        intent = self._reposition_intent
        if intent is not None and planet is intent.origin:
            need = max(need, self._departure_fuel_requirement(intent.target))
        return min(need, self.ship.fuel_capacity)

    def _sellable_quantity(self, commodity: CommodityDefinition) -> int:
        """Cargo units of ``commodity`` the ship may treat as trade goods.

        Fuel is special-cased two ways:
        - The travel reserve is never sellable. Selling the return-leg fuel
          strands ships, including fuel deliverers, which would otherwise
          dump their whole tank at a fuel-poor destination.
        - Tank fuel counts as trade cargo only at either end of an explicit
          fuel-delivery plan, or when the local bid is scarcity-priced, such
          as another ship's standing rescue bid; otherwise only overflow
          above a full tank does. Without that guard a topped-up ship sells
          its own tank at the local bid and re-buys at the ask every other
          turn, bleeding the spread. The origin end counts too, so a fuel
          plan can reach ``_plan_loaded`` and fly; see
          :meth:`_fuel_delivery_in_progress`.
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
            # Never below what this planet's committed departure needs,
            # though: the top-up buys that fuel at the local ask, and without
            # this floor the ship listed the same units at the bid, blocked
            # its own departure on the sell veto, and re-bought them next
            # turn, bleeding the spread every round.
            floor = (
                max(self._fuel_survival_target(), self._committed_fuel_floor())
                if self.is_distressed
                else self.ship.fuel_capacity
            )
            reserve = max(reserve, floor)
        return max(0, quantity - reserve)

    def _refresh_local_sale_staleness(self) -> None:
        """Judge whether last turn's local asks went a full turn unfilled.

        Call once per docked turn, after resting orders are cancelled and
        before new ones are placed, so the cargo counted here is the whole
        hold rather than the part not tied up in an order.

        The one-turn sell veto exists so a ship does not depart and abort the
        sale it just placed. Left unqualified it became permanent: the ask
        rested at a price nobody took, the ship never departed, and it could
        not replan while holding cargo. A sale that survived a full turn with
        nothing filled is stale, and the veto no longer applies to it. Any
        fill, a move to another planet, or an empty hold clears the flag.

        Staleness is judged per listed commodity against the raw units held
        when the asks went in, so only a fill can clear it. Judging it on the
        sellable total instead let unrelated events flip the verdict: a
        rescue bid appearing in the local fuel book turns tank fuel into
        sellable cargo, which is not a fill and must not reset the clock.
        """
        planet = self.ship.planet
        listed = self._local_sale_held
        if not listed or planet is None or self._local_sale_planet_name != planet.name:
            self._local_sale_stale = False
            self._clear_local_sale_record()
            return
        filled = any(
            self.ship.cargo.get_quantity(commodity) < held_at_listing
            for commodity, held_at_listing in listed.items()
        )
        self._local_sale_stale = not filled
        if filled:
            # Something filled: the book is working, start the clock over.
            self._clear_local_sale_record()

    def _clear_local_sale_record(self) -> None:
        """Forget the local asks being tracked for staleness."""
        self._local_sale_held = {}
        self._local_sale_planet_name = ""

    def _record_local_sale(
        self, planet: Planet, commodities: Sequence[CommodityDefinition]
    ) -> None:
        """Note the asks just placed at ``planet`` so next turn can judge fills."""
        self._local_sale_held = {
            commodity: self.ship.cargo.get_quantity(commodity)
            for commodity in commodities
        }
        self._local_sale_planet_name = planet.name

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

        When the local ask is within FUEL_BUNKER_PREMIUM of the galaxy's
        typical believable fuel price, the median over planets, bunker
        toward a full tank. When it is priced well above that median, buy
        only up to the survival target, raised to cover the destination the
        ship has committed its cargo to; filling tanks at spike prices
        bankrupts ships.

        Above the premium the survival portion is rationed further, to
        :meth:`_fuel_escape_target`: enough to reach the nearest planet that
        sells fuel and still clear its arrival floor, rather than two round
        trips' worth. The survival top-up was the last unguarded fuel
        purchase in the ship, spending ``money * 0.9`` at any ask; measured
        over 300 turns it was where insolvent ships lost their capital,
        paying 88 credits a unit against a reference near 54, with spiked
        buys alone exceeding their starting purse. Buying the way out and
        refuelling properly at the next market costs strictly less than
        stockpiling here at spike prices.

        Two guards keep this from grounding the fleet the way rationing
        *plan* fuel to one leg did. Committed-destination fuel is exempt, so
        a ship with a profitable trip still funds the whole trip. And the
        escape hop must clear :meth:`_fuel_safe_destination` with the
        rationed tank; if no hop does, the full survival target is bought
        anyway, since overpaying beats stranding. A ship that would rather
        wait for a cheaper price still has :meth:`_post_standing_fuel_bid`.

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

        # Fuel the ship must have to fly the destination it is holding cargo
        # for is as non-negotiable as the survival minimum: the hold-or-sell
        # comparison already proved that trip profitable at this ask, so it
        # is not speculative bunkering and the premium gate does not apply.
        survival_target = self._fuel_survival_target()
        if not bunkering:
            escape_target = self._fuel_escape_target()
            if escape_target is not None:
                survival_target = min(survival_target, escape_target)
        required_target = min(
            ship.fuel_capacity,
            max(survival_target, self._committed_fuel_need),
        )
        required_units = min(
            max(0, required_target - current_fuel),
            cargo_room,
            int(ship.money * 0.9) // fuel_ask,
        )
        required_units = max(0, required_units)

        bunker_units = 0
        if bunkering:
            bunker_budget = (
                int(ship.money * FUEL_BUNKER_BUDGET_FRACTION)
                - required_units * fuel_ask
            )
            bunker_units = min(
                ship.fuel_capacity - current_fuel - required_units,
                cargo_room - required_units,
                max(0, bunker_budget) // fuel_ask,
            )
            bunker_units = max(0, bunker_units)

        quantity = required_units + bunker_units
        if quantity <= 0:
            return None

        order_id = market.place_buy_order(ship, fuel_commodity, quantity, fuel_ask)
        if not order_id:
            return None
        ship.active_orders[order_id] = "buy fuel"
        return order_id

    def _fuel_bid_price(self, planet: Planet, quantity: int) -> int:
        """Price for a standing fuel bid that makes delivery profitable.

        Delegates to :meth:`Navigator.fuel_delivery_bid_price`, which spaceport
        operators use for the same purpose.
        """
        return self._nav.fuel_delivery_bid_price(planet, quantity)

    def _local_fuel_reference_price(self, planet: Planet) -> int:
        """Scarcity-escalated price a local fuel producer would plausibly take.

        Delegates to :meth:`Navigator.local_fuel_reference_price`.
        """
        return self._nav.local_fuel_reference_price(planet)

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

        The cash gate below is deliberately round-trip: a trade that
        disappoints must never leave the ship both broke and dry. Only the
        *margin* is charged one way, in :class:`TradePlan`.
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
        reference = self._fuel_value_reference()
        fuel_reference_price = math.ceil(reference) if reference else fuel_price

        current_fuel = self.ship.cargo.get_quantity(fuel_commodity)
        cargo_space = self.ship.cargo_capacity - self.ship.cargo.get_total_quantity()

        round_trip_shortfall = max(0, fuel_round_trip - current_fuel)
        if round_trip_shortfall > 0 and not self._fuel_purchasable_at(origin):
            # The plan needs fuel that cannot be bought at the origin: no ask
            # and no recent flow. Committing would strand the ship with cargo.
            return None

        # The ship buys the whole round-trip shortfall, even where the local
        # ask is scarcity-priced. Rationing to this leg's shortfall and
        # refuelling at the far end was tried, gated on the destination still
        # being fuel-safe on that much, and it grounded the fleet: over a
        # 200-turn 30-planet run stranded ships went 3 -> 14 and departures 68
        # -> 22. A fuel-safe destination is a market that has depth *now*,
        # and by arrival it usually does not. Only the *margin* is charged one
        # way; the tank is still filled for the round trip.
        fuel_to_buy = round_trip_shortfall
        fuel_cost = fuel_to_buy * fuel_price

        # Never fly somewhere that leaves no escape route: the destination
        # must sell fuel, or the fuel left after arrival must reach a planet
        # that does.
        fuel_after_arrival = current_fuel + fuel_to_buy - fuel_one_way
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
            fuel_reference_price=fuel_reference_price,
            fuel_to_buy=fuel_to_buy,
            fuel_from_tank_one_way=min(current_fuel, fuel_one_way),
            expected_maintenance_cost=maintenance_cost,
            money_for_trading=money_for_trading,
            max_by_cargo=cargo_space - fuel_to_buy,  # fuel takes cargo space
        )

    def _origin_acquisition(
        self, origin: Planet, commodity: CommodityDefinition
    ) -> Optional["_OriginAcquisition"]:
        """What acquiring ``commodity`` at ``origin`` costs, and what to bid.

        A resting ask is directly liftable at its own price; an active local
        flow - recent volume with a real price signal - has to be bid for at
        the clearing price. The ship posts the higher of the two, since
        matching executes at each seller's ask and a generous bid wins flow
        without overpaying for the cheap fills. What the units are expected
        to *cost* is a different number, and the two are kept apart here.

        This ship's own asks are excluded from the walk. Matching has no
        buyer-is-seller guard, so pricing an entry off a book that contains
        our own ask puts the bid at or above it and the ship buys its own
        cargo back - which is exactly what a ship listing stale cargo and
        replanning in the same turn would otherwise do.

        Returns None when the commodity cannot be acquired at all: no ask
        resting and no flow to bid into.
        """
        market = origin.market
        _, origin_ask = market.get_bid_ask_spread(commodity)
        origin_flow_px = self._flow_value(market, commodity)
        if origin_flow_px is not None and (
            self._recent_flow_per_turn(market, commodity) <= 0
        ):
            origin_flow_px = None  # a price with no recent volume buys nothing
        flow_price = origin_flow_px if origin_flow_px and origin_flow_px > 0 else 0

        ask_levels = (
            market.get_ask_levels(commodity, exclude_actor=self.ship)
            if origin_ask is not None and origin_ask > 0
            else []
        )
        if not ask_levels and flow_price <= 0:
            return None

        entry_price = ask_levels[0][0] if ask_levels else flow_price
        bid_price = max(entry_price, flow_price)
        return _OriginAcquisition(
            ask_levels=ask_levels,
            flow_price=flow_price,
            bid_price=bid_price,
            entry_price=entry_price,
        )

    def _walked_purchase_price(
        self, acquisition: "_OriginAcquisition", quantity: int
    ) -> int:
        """Expected per-unit cost of lifting ``quantity`` units at the origin.

        Walks the resting asks cheapest first, then prices whatever the book
        cannot supply at the bid, which is what winning it out of the flow
        costs. Rounded up, so the margin gate never flatters the plan.
        """
        if quantity <= 0:
            return acquisition.bid_price
        remaining = quantity
        cost = 0
        for price, qty in acquisition.ask_levels:
            take = min(qty, remaining)
            cost += price * take
            remaining -= take
            if remaining == 0:
                break
        cost += acquisition.bid_price * remaining
        return math.ceil(cost / quantity)

    def _evaluate_trade_opportunity(
        self,
        origin: Planet,
        destination: Planet,
        commodity: CommodityDefinition,
        pair: Optional["_PairEconomics"] = None,
        acquisition: Optional["_OriginAcquisition"] = None,
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
        volume, as well as the resting book. Costs are judged on what the
        cargo is expected to cost - the resting asks walked for the planned
        quantity - not on the bid the ship posts, which is deliberately
        higher so the order also wins units out of the flow.

        ``pair`` carries the commodity-independent economics of the pair and
        ``acquisition`` the destination-independent origin prices;
        :meth:`_best_plan_from` precomputes both, and each is derived on the
        fly when omitted.
        """
        if pair is None:
            pair = self._pair_economics(origin, destination)
        if pair is None:
            return None
        if acquisition is None:
            acquisition = self._origin_acquisition(origin, commodity)
        if acquisition is None:
            # Nothing for sale and no active flow to bid into.
            return None

        dest_market = destination.market
        # Screen demand against what the cargo costs, not what the ship bids.
        entry_price = acquisition.entry_price

        # Destination demand: resting bids that beat the purchase price...
        bid_levels = [
            (price, qty)
            for price, qty in dest_market.get_bid_levels(commodity)
            if price > entry_price
        ]
        depth = sum(qty for _, qty in bid_levels)
        # ...plus the flow: recent clearing volume at the haircut clearing
        # price, a forecast rather than a resting order.
        dest_flow_px = self._flow_value(dest_market, commodity)
        flow_px = int(dest_flow_px * SELL_PRICE_HAIRCUT) if dest_flow_px else 0
        flow_qty = 0
        if flow_px > entry_price:
            flow_qty = int(
                self._recent_flow_per_turn(dest_market, commodity)
                * DEMAND_HORIZON_TURNS
            )
        if depth + flow_qty > 0:
            sellable = depth + flow_qty
        elif flow_px > entry_price:
            # Price signal but no recent volume: latent demand is a guess
            # that often fails to realize, so such plans are capped small.
            sellable = SPECULATIVE_PLAN_CAP
        else:
            return None

        # Budget and cargo limits are pair-level facts; only the price is
        # commodity-specific. Budget against the bid, since that is what an
        # order actually reserves.
        max_by_money = pair.money_for_trading // acquisition.bid_price
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
            bid_price_per_unit=acquisition.bid_price,
            purchase_price_per_unit=self._walked_purchase_price(acquisition, quantity),
            expected_sell_price_per_unit=sell_price,
            distance=pair.distance,
            fuel_needed_one_way=pair.fuel_one_way,
            fuel_price_at_origin=pair.fuel_price,
            fuel_units_from_tank=pair.fuel_from_tank_one_way,
            fuel_price_from_tank=pair.fuel_reference_price,
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

    def _plan_acceptable(self, plan: TradePlan) -> bool:
        """Whether this ship will adopt ``plan``.

        Normally the plan must clear ``TradePlan.MIN_MARGIN``, which is a
        quality bar for a ship that has alternatives. A distressed ship has
        none: it is parked, out of cash, and every turn it waits for a
        15%-margin haul is a turn of no income at all. For it the bar drops
        to round-trip honesty rather than to zero: the haul's expected profit
        must also cover :attr:`TradePlan.return_leg_fuel_cost`, the return
        leg the ship has to buy out of it.

        Dropping the bar to bare profitability was a distress trap. The haul
        is costed one way, while the cash gate makes the ship buy the round
        trip, so a haul earning less than the return leg leaves the ship
        poorer than it started, still under the cash floor, and still
        distressed - which re-qualifies it for the same kind of haul, for
        good.

        Nothing about safety is relaxed: the round-trip cash gate and the
        refuel floor in :meth:`_pair_economics` still size the haul to the
        cash the ship actually has, and the fuel-safety gates are untouched.
        """
        if plan.expected_profit <= 0:
            return False
        if plan.is_profitable():
            return True
        return self.is_distressed and plan.expected_profit > plan.return_leg_fuel_cost

    def _best_plan_from(self, origin: Planet) -> Optional[TradePlan]:
        """Most profitable trade plan exporting from ``origin``, if any.

        Only commodities acquirable at the origin are evaluated, and only
        against the navigator's per-turn candidate destinations for each
        commodity: the top-value demand planets united with the nearest
        ones, or every demand planet in small galaxies. Both are superset
        filters; the evaluation re-verifies prices. When the galaxy shows no
        trade signal at all, planning is skipped. The commodity-independent
        economics of each pair are computed once and shared across
        commodities, and the destination-independent origin prices once per
        commodity.

        Goods this ship is itself offering here are skipped. A ship cannot
        profitably buy what it is trying to sell in the same book, and
        planning to would have it bid against - and match - its own ask.
        """
        nav = self._nav
        if not nav.has_any_trade_signal():
            return None
        exportable = nav.exportable_commodities(origin)
        if not exportable:
            return None
        listing_here = {
            order.commodity_type
            for order in origin.market.get_actor_orders(self.ship)["sell"]
        }

        best_plan: Optional[TradePlan] = None
        best_profit = 0
        # Per-pair facts for this search only; the navigator owns all
        # cross-ship, cross-turn caching.
        pair_economics: Dict[Planet, Optional[_PairEconomics]] = {}

        for commodity in self._get_tradeable_commodities():
            if commodity not in exportable or commodity in listing_here:
                continue
            acquisition = self._origin_acquisition(origin, commodity)
            if acquisition is None:
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
                    acquisition=acquisition,
                )
                if (
                    plan
                    and self._plan_acceptable(plan)
                    and plan.expected_profit > best_profit
                ):
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

        # Step 2: bid for the plan's remaining cargo at the plan's bid price
        # - not its evaluation price, which is what the cargo is expected to
        # cost. The order rests in the book and fills at sellers' asks, never
        # above the bid.
        bid_price = plan.bid_price_per_unit
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

    def _cargo_disposition(self, market: "Market") -> Tuple[bool, int]:
        """Decide whether to sell the hold here, and what fuel that commits.

        Returns ``(should_sell_here, committed_fuel_need)``. The commitment is
        the departure requirement of the trip the cargo is being held for,
        the same number :meth:`decide_travel` gates on, so a ship that funds
        it can actually leave. Zero when selling here.
        """
        ship = self.ship
        current_planet = ship.planet
        fuel_commodity = self._fuel_commodity()
        if current_planet is None or fuel_commodity is None:
            return True, 0
        fuel_in_tank = ship.cargo.get_quantity(fuel_commodity)

        # Reachability is about the fuel the ship can have when it leaves,
        # not only what is in the tank. Ships run near the survival target, a
        # handful of units, so judging destinations on tank fuel alone
        # rejected almost every one of them and the cargo was dumped into a
        # local book that had no buyer.
        _, local_fuel_ask = market.get_bid_ask_spread(fuel_commodity)
        fuel_available = fuel_in_tank + self._affordable_local_fuel(current_planet)

        for commodity in self._get_tradeable_commodities():
            quantity = self._sellable_quantity(commodity)
            if quantity <= 0:
                continue

            local_bid, _ = market.get_bid_ask_spread(commodity)
            # Value at the better of the top resting bid and the recent
            # clearing price: the residual book alone undervalues any good the
            # local auction clears.
            local_price = max(local_bid or 0, self._flow_value(market, commodity) or 0)

            for planet in ship.simulation.planets:
                if planet == current_planet:
                    continue

                # Only a trip decide_travel would approve can justify holding
                # cargo: leg plus the escape fuel the destination demands on
                # arrival. Judging reach on the leg alone held cargo for trips
                # the departure gate then refused, forever.
                required_fuel = self._departure_fuel_requirement(planet)
                if fuel_available < required_fuel:
                    continue

                dest_bid, _ = planet.market.get_bid_ask_spread(commodity)
                dest_price = max(
                    dest_bid or 0,
                    self._flow_value(planet.market, commodity) or 0,
                )

                if not dest_price or not local_price:
                    continue

                # Compare net values the way decide_travel does: destination
                # revenue minus the fuel to get there, against revenue here. A
                # bare unit-price comparison holds tiny cargoes forever for
                # trips whose fuel cost decide_travel never approves. Fuel
                # already in the tank is charged at the local clearing price,
                # fuel that has to be bought at the price it would actually
                # cost. Only the leg is burned; the arrival reserve is carried,
                # not spent, so it is not a cost of the trip.
                fuel_needed = ship.fuel_required(
                    self._nav.distance(current_planet, planet)
                )
                origin_fuel_price = market.get_avg_price(fuel_commodity) or 10
                from_tank = min(fuel_needed, fuel_in_tank)
                to_buy = fuel_needed - from_tank
                fuel_cost = from_tank * origin_fuel_price + to_buy * (
                    local_fuel_ask or origin_fuel_price
                )
                dest_net = dest_price * quantity - fuel_cost
                if dest_net > local_price * quantity * 1.15:
                    # The trip this cargo is being held for is profitable at
                    # the local fuel ask, so the top-up must buy every unit
                    # the departure gate will ask for.
                    return False, required_fuel

        return True, 0

    def _list_cargo_locally(
        self, market: "Market", skip: frozenset[str] = frozenset()
    ) -> Tuple[List[str], List[CommodityDefinition], int]:
        """Offer sellable cargo into the local book, skipping ``skip`` ids.

        Returns the action strings, the commodities that got an order, and the
        units listed. ``skip`` serves the accumulation window, where the
        plan's own commodity is being bought rather than sold.
        """
        actions: List[str] = []
        listed: List[CommodityDefinition] = []
        quantity_listed = 0
        for commodity in self._get_tradeable_commodities():
            if commodity.id in skip:
                continue
            quantity = self._sellable_quantity(commodity)
            if quantity <= 0:
                continue
            sell_actions = self._place_flow_sell_orders(market, commodity, quantity)
            if sell_actions:
                actions.extend(sell_actions)
                listed.append(commodity)
                quantity_listed += quantity
        return actions, listed, quantity_listed

    def decide_trade_actions(self) -> None:
        """Take this turn's trading actions at the current planet.

        The order matters and is deliberate: cancel resting orders, judge
        last turn's asks, run the plan lifecycle, decide what the cargo is
        for (which fixes this turn's fuel commitment), then fuel upkeep, then
        the orders each branch places. Fuel upkeep sits after the commitment
        so a low-fuel ship funds the trip it just chose, and before every
        early return so the ships that need a rescue bid always post one.

        1. If there is cargo to sell, sell it here or hold it for a better
           market
        2. Otherwise find the best trade plan and execute it
        3. If no profitable trade exists, maintain fuel and wait
        """
        current_planet = self.ship.planet
        if current_planet is None:
            return

        # The first ship deciding this turn rebuilds the market-fact snapshot;
        # the rest share it.
        self._nav.refresh_market_facts(turn=self.ship.simulation.current_turn)

        market = current_planet.market
        fuel_commodity = self._fuel_commodity()

        if not fuel_commodity:
            self.ship.last_action = "No trading - fuel commodity not available"
            return

        existing_orders = market.get_actor_orders(self.ship)
        for order in existing_orders["buy"] + existing_orders["sell"]:
            market.cancel_order(order.order_id)

        actions = []
        self._selling_locally = False
        # Now that the hold is whole again, judge last turn's local asks.
        self._refresh_local_sale_staleness()

        # A reposition intent speaks for one planet only. Anywhere else - the
        # ship flew, or was diverted - it is stale and must not fund fuel.
        intent = self._reposition_intent
        if intent is not None and intent.origin is not current_planet:
            self._clear_reposition_intent()

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

        placed_fuel_sell = False

        # Whether the tank is under the stranding reserve. The upkeep itself
        # runs further down, once this turn's fuel commitment is known; see
        # the ordering comment there.
        fuel_upkeep_ran = (
            self.ship.cargo.get_quantity(fuel_commodity) < self._fuel_reserve_need()
        )

        # Plan lifecycle. Flow-based plans fill a resting bid over several
        # docked turns, then fly the load to the plan's destination.
        accumulating = False
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
                    # The bid goes in below, after fuel upkeep.
                    self._plan_turns_left -= 1
                    accumulating = True
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

        # Fuel below the travel reserve is not trade cargo; see
        # _sellable_quantity. Judged after the plan lifecycle, which can drop
        # a fuel plan and with it the tank's standing as cargo.
        has_trade_cargo = any(
            self._sellable_quantity(c) > 0 for c in self._get_tradeable_commodities()
        )

        # What this turn's cargo is for, and so what fuel the ship has
        # committed to buying. Recomputed from scratch, before any fuel order
        # goes in, so a stale commitment can never fund the wrong trip.
        should_sell_here = True
        self._committed_fuel_need = 0
        if accumulating:
            pass  # the plan's own fuel step funds the trip it is loading for
        elif plan is not None and self._plan_loaded:
            # Loaded and still here: the departure gate refused, almost always
            # on fuel. Commit to exactly what that gate asks for, or the ship
            # tops up to the survival target and is refused again next turn.
            self._committed_fuel_need = self._departure_fuel_requirement(
                plan.destination
            )
        elif has_trade_cargo:
            should_sell_here, self._committed_fuel_need = self._cargo_disposition(
                market
            )
        elif self._reposition_intent is not None:
            # Empty, but committed to flying somewhere worth trading from and
            # short of the fuel for it. Same commitment a held cargo makes, so
            # the top-up buys what the departure gate will ask for.
            self._committed_fuel_need = self._departure_fuel_requirement(
                self._reposition_intent.target
            )

        # Fuel upkeep, whenever the tank is under the stranding reserve, and
        # ahead of every branch that can end the turn: an accumulating plan
        # holds the turn for up to ACCUMULATION_PATIENCE turns and adopting a
        # plan returns outright, so upkeep placed after them never ran for the
        # ships that needed it, and a dry ship with a plan it could not fly
        # posted no rescue bid at all. It runs after the commitment above so
        # the top-up funds this turn's decision rather than last turn's. No
        # fuel sell can have happened yet, and none can happen later this turn
        # either: below the reserve _sellable_quantity yields no fuel, so
        # there is no self-trade to guard against here.
        if fuel_upkeep_ran:
            actions.extend(self._maintain_fuel())

        listed_locally = 0
        if accumulating and plan is not None:
            # Cargo the plan is not about would otherwise sit unlisted for the
            # whole accumulation window. Fuel is held back: the plan's own
            # fuel bid goes in below and must not meet an ask of ours.
            sell_actions, listed, _ = self._list_cargo_locally(
                market, skip=frozenset({plan.commodity.id, "nova_fuel"})
            )
            if listed:
                actions.extend(sell_actions)
                self._record_local_sale(current_planet, listed)
            self._execute_trade_plan(
                plan, fuel_handled=fuel_upkeep_ran, prior_actions=actions
            )
            return

        # Cargo: sell here or travel. A loaded plan's cargo flies to
        # plan.destination instead.
        if has_trade_cargo and not self._plan_loaded:
            if should_sell_here:
                sell_actions, listed, listed_locally = self._list_cargo_locally(market)
                if listed:
                    actions.extend(sell_actions)
                    # Hold the ship here only while the sale is fresh. A sale
                    # that already sat a full turn unfilled has earned no more
                    # patience.
                    if not self._local_sale_stale:
                        self._selling_locally = True
                    placed_fuel_sell = any(c.id == "nova_fuel" for c in listed)
                    self._record_local_sale(current_planet, listed)
            else:
                # decide_travel will fly it there.
                actions.append("Holding cargo for better price elsewhere")

        # No cargo, or cargo listed locally that nobody has taken for a full
        # turn: look for a plan. Without the second case a ship holding an
        # unsellable load could never replan, which is the other half of the
        # idle livelock. Plan sizing already treats the held cargo as
        # occupied hold space (see _pair_economics).
        if not has_trade_cargo or (listed_locally > 0 and self._local_sale_stale):
            # Adopt the best trade plan. The search skips whatever this ship
            # is listing here, so it cannot plan to buy back its own cargo.
            plan = self._find_best_trade_plan()
            if plan:
                self._current_plan = plan
                self._plan_loaded = False
                self._plan_turns_left = ACCUMULATION_PATIENCE
                # The commitment spoke for cargo the ship was holding for a
                # trip, or for a reposition it no longer needs; the plan's own
                # fuel step owns the tank now.
                self._committed_fuel_need = 0
                self._clear_reposition_intent()
                self._execute_trade_plan(
                    plan,
                    # A fuel ask of ours is resting: bidding for fuel now
                    # would buy from ourselves.
                    fuel_handled=fuel_upkeep_ran or placed_fuel_sell,
                    prior_actions=actions,
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
        # sale decide_trade_actions just chose. This holds for one turn only:
        # once the asks have sat a full turn unfilled, decide_trade_actions
        # stops setting the flag and the destination logic below runs.
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
                # Sourcing here beats repositioning, so any standing intent is
                # abandoned now. Leaving it set had the next docked turn
                # commit fuel to a target this ship had already given up on,
                # and buy it before plan adoption cleared the intent.
                self._clear_reposition_intent()
                return None
            reposition = self._reposition_intent_target(
                fuel_available
            ) or self._find_reposition_target(fuel_available, fuel_commodity)
            if reposition is not None:
                return self._reposition_destination(reposition, fuel_available)
            self._clear_reposition_intent()
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

        Candidates that also clear :meth:`_fuel_safe_destination` sort ahead
        of ones that do not, so a hop that leaves an escape route always
        beats an equally plausible hop that does not. The unsafe ones are
        still offered rather than dropped: a ship already below the escape
        floor cannot meet it, and sitting on a fuel desert is worse than a
        hop to a planet that at least has a fuel producer.
        """
        current = self.ship.planet
        if current is None:
            return None
        fuel_commodity = self._fuel_commodity()
        if fuel_commodity is None:
            return None
        best: Optional[tuple[int, int, float, Planet]] = None
        for planet in self.ship.simulation.planets:
            if planet is current:
                continue
            distance = self._nav.distance(current, planet)
            leg = self.ship.fuel_required(distance)
            if fuel_available < leg:
                continue
            if self._fuel_purchasable_at(planet):
                tier = 0
            elif self._nav.fuel_traded_recently(planet):
                tier = 1
            elif planet.market.has_price_signal(fuel_commodity):
                tier = 2
            else:
                continue
            unsafe = (
                0
                if self._fuel_safe_destination(planet, current, fuel_available - leg)
                else 1
            )
            key = (unsafe, tier, distance)
            if best is None or key < (best[0], best[1], best[2]):
                best = (unsafe, tier, distance, planet)
        return best[3] if best is not None else None

    def _find_reposition_target(
        self, fuel_available: int, fuel_commodity: "CommodityDefinition"
    ) -> Optional[Planet]:
        """Pick a planet to fly to empty when nothing here is worth exporting.

        Surveys up to REPOSITION_ORIGIN_CANDIDATES reachable planets, nearest
        first, as candidate origins and finds the best profitable export plan
        from each. Returns the origin backing the most profitable one, or
        None if none is reachable or profitable.

        Reach is the tank *plus* the fuel the ship could buy here, since
        repositioning may buy fuel like any other trip. Judging it on the
        tank alone was the single biggest source of idle turns: ships running
        at a couple of units of fuel, with hundreds of credits and a fuel ask
        in the book in front of them, could neither plan (the round-trip cash
        gate refuses a plan they cannot fund) nor move. The purchase is not
        free, so it is charged against the plan the origin backs, and the
        arrival floor in :meth:`_fuel_safe_destination` is applied to the
        fuel the ship would actually land with.

        Buying it is the caller's job: :meth:`_reposition_destination` records
        the intent so the next docked turn commits ``_committed_fuel_need``
        to it, exactly as a ship holding cargo for a trip does.
        """
        current_planet = self.ship.planet
        if current_planet is None:
            return None

        # Cold galaxy: no commodity has both supply and demand anywhere, so
        # no origin can back a plan; skip the per-origin surveys.
        if not self._nav.has_any_trade_signal():
            return None

        buyable_fuel = self._affordable_local_fuel(current_planet)
        _, local_fuel_ask = current_planet.market.get_bid_ask_spread(fuel_commodity)
        fuel_price = local_fuel_ask if buyable_fuel > 0 and local_fuel_ask else 0
        reach = fuel_available + buyable_fuel

        best_origin: Optional[Planet] = None
        best_profit = 0
        surveyed = 0

        for origin in self._nav.planets_by_proximity(current_planet):
            if surveyed >= REPOSITION_ORIGIN_CANDIDATES:
                break
            # Must be able to reach this origin empty, out of the tank or the
            # local book, and arriving there must leave an escape route.
            distance_to_origin = self._nav.distance(current_planet, origin)
            fuel_to_origin = self.ship.fuel_required(distance_to_origin)
            if reach < fuel_to_origin:
                continue
            # The departure gate asks for the leg plus the arrival reserve, so
            # that is what the trip has to be funded to.
            departure_need = self._departure_fuel_requirement(origin)
            if reach < departure_need:
                continue
            fuel_to_buy = max(0, departure_need - fuel_available)
            if not self._fuel_safe_destination(
                origin, current_planet, fuel_available + fuel_to_buy - fuel_to_origin
            ):
                continue

            surveyed += 1
            plan = self._best_plan_from(origin)
            if plan is None:
                continue
            net_profit = plan.expected_profit - fuel_to_buy * fuel_price
            if net_profit > best_profit:
                best_profit = net_profit
                best_origin = origin

        return best_origin

    def _reposition_destination(
        self, target: Planet, fuel_available: int
    ) -> Optional[Planet]:
        """Fly the empty reposition now, or stay a turn and fund its fuel.

        :meth:`_find_reposition_target` counts fuel the ship could buy here,
        so the chosen origin is often out of reach until that purchase
        settles. Recording the intent makes the next docked turn commit
        ``_committed_fuel_need`` to this trip, which is the mechanism
        :meth:`_opportunistic_fuel_topup` honours even at a scarcity price.
        """
        current_planet = self.ship.planet
        if current_planet is None:
            return None
        leg = self.ship.fuel_required(self._nav.distance(current_planet, target))
        if fuel_available >= leg and self._fuel_safe_destination(
            target, current_planet, fuel_available - leg
        ):
            self._clear_reposition_intent()
            return target
        self._reposition_intent = _RepositionIntent(
            origin=current_planet, target=target
        )
        return None

    def _reposition_intent_target(self, fuel_available: int) -> Optional[Planet]:
        """The standing reposition target, if it is still worth waiting for.

        The intent is sticky. Re-surveying every turn let a ship waiting for
        its fuel order to fill re-aim at a different origin each turn, so the
        fuel it had committed to was never the fuel the next turn's trip
        needed and it never left. The survey only runs again once the
        standing target stops being reachable and fundable from here, which
        is the same pair of tests :meth:`_find_reposition_target` applies.
        """
        intent = self._reposition_intent
        current_planet = self.ship.planet
        if intent is None or current_planet is None:
            return None
        if intent.origin is not current_planet:
            return None
        reach = fuel_available + self._affordable_local_fuel(current_planet)
        departure_need = self._departure_fuel_requirement(intent.target)
        if reach < departure_need:
            return None
        leg = self.ship.fuel_required(self._nav.distance(current_planet, intent.target))
        fuel_to_buy = max(0, departure_need - fuel_available)
        if not self._fuel_safe_destination(
            intent.target, current_planet, fuel_available + fuel_to_buy - leg
        ):
            return None
        return intent.target

    def _clear_reposition_intent(self) -> None:
        """Forget any pending empty reposition."""
        self._reposition_intent = None


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
        # Turn this ship last began a journey; 0 until its first departure.
        # Activity KPIs use this to spot ships that sit docked indefinitely
        # even when they are not "stranded" by the fuel-ask definition.
        self.last_departure_turn = 0
        # Every turn a journey actually started, oldest first. Uncapped: the
        # summary KPI only ever looks at a short recent window, and the list
        # is small relative to a run's other per-actor bookkeeping.
        self.departure_turns: List[int] = []
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
        self.last_departure_turn = self.simulation.current_turn
        self.departure_turns.append(self.simulation.current_turn)

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
