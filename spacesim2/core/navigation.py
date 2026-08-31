"""Galaxy geometry and fuel-reachability facts shared by ship planning.

Ship planning used to recompute the same galaxy-wide facts per candidate
planet per commodity (distances, "is fuel purchasable here", "how far to the
nearest fuel source"), which made a single planning decision O(planets^3).
This module centralizes those facts in a :class:`Navigator`:

- **Geometry** (planet positions are fixed after setup): a lazily built
  pairwise distance matrix and per-planet proximity orderings, computed once
  per simulation and shared by every ship.
- **Market-derived facts** (order books mutate as brains post orders): fuel
  purchasability, nearest-fuel-source distances, the galaxy fuel price
  reference, and the trade-signal index (per-planet commodity summaries plus
  per-commodity ranked demand shortlists). These are cached **per turn**:
  ship brains call :meth:`Navigator.refresh_market_facts` with the current
  turn number, which rebuilds the snapshot only on the turn's first call, so
  every ship planning that turn shares one consistent view of the galaxy.
  Order execution is deferred to end-of-turn matching, which keeps the
  snapshot a valid superset filter for the whole turn; plan evaluation
  re-verifies exact prices against the live books anyway.

Use :func:`get_navigator` to obtain the per-simulation shared instance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, FrozenSet, List, Optional, Tuple
from weakref import WeakKeyDictionary

if TYPE_CHECKING:
    from spacesim2.core.commodity import CommodityDefinition
    from spacesim2.core.planet import Planet
    from spacesim2.core.simulation import Simulation

# How many recent turns of volume history count as "fuel trades here" when
# judging whether fuel is realistically purchasable at a planet.
FUEL_MARKET_RECENCY_TURNS = 10

# Window of volume history that counts as "this good trades here" for the
# exportable-commodity summary (mirrors TraderBrain's flow recency window).
FLOW_RECENCY_TURNS = 10

# Candidate-destination shortlist sizes for the per-turn trade-signal index.
# For each (origin, commodity) the candidate destinations are the union of
# the DESTINATION_TOP_K demand planets with the highest demand value and the
# DESTINATION_NEAREST_M demand planets nearest the origin (a nearby modest
# market can beat a distant top-value one after fuel costs). When a commodity
# has no more than K + M demand planets in total the shortlist degenerates to
# ALL of them, so galaxies with <= 16 other planets are surveyed exhaustively
# and small-run behavior is unchanged.
DESTINATION_TOP_K = 8
DESTINATION_NEAREST_M = 8


@dataclass
class _TradeSignalIndex:
    """One turn's galaxy-wide supply/demand signal snapshot.

    Built by :meth:`Navigator._trade_signal_index` in a single O(planets x
    commodities) pass over every market, then shared by every ship planning
    during that turn. All fields describe superset filters: plan evaluation
    still re-verifies exact prices against the live books.
    """

    # Per-planet summaries (what the old lazy per-planet caches held).
    exportable_by_planet: Dict["Planet", FrozenSet["CommodityDefinition"]]
    demandable_by_planet: Dict["Planet", FrozenSet["CommodityDefinition"]]
    # Per-commodity: planets where it is plausibly acquirable.
    export_planets: Dict["CommodityDefinition", FrozenSet["Planet"]]
    # Per-commodity: planets with a demand signal, best demand value first
    # (ties keep simulation planet order), plus a set for membership tests.
    demand_ranked: Dict["CommodityDefinition", Tuple["Planet", ...]]
    demand_planets: Dict["CommodityDefinition", FrozenSet["Planet"]]
    # Memo of candidate_destinations results, shared by all ships this turn.
    candidate_memo: Dict[
        Tuple["Planet", "CommodityDefinition"], Tuple["Planet", ...]
    ] = field(default_factory=dict)

    def has_any_trade_signal(self) -> bool:
        """Whether any commodity is exportable somewhere AND demanded somewhere.

        False means the galaxy is cold: no ship can construct a trade plan,
        so planning can be skipped outright this turn.
        """
        return any(
            self.export_planets[commodity] and self.demand_ranked[commodity]
            for commodity in self.export_planets
        )


class Navigator:
    """Cached view of galaxy geometry and fuel reachability for one simulation.

    Geometry is cached for the simulation's lifetime. Market-derived facts
    are cached until the next effective :meth:`refresh_market_facts` call —
    once per turn when called with the turn number, as ship brains do.
    """

    def __init__(self, sim: "Simulation") -> None:
        """Create a navigator bound to ``sim``."""
        self._sim = sim
        # --- static geometry (built lazily, rebuilt if the planet set changes)
        self._planet_index: Dict["Planet", int] = {}
        self._distances: List[List[float]] = []
        self._by_proximity: Dict["Planet", List["Planet"]] = {}
        # --- static commodity facts
        self._tradeable: Optional[List["CommodityDefinition"]] = None
        self._fuel: Optional["CommodityDefinition"] = None
        self._fuel_resolved = False
        # --- market-derived facts (cleared by refresh_market_facts)
        self._fuel_purchasable: Dict["Planet", bool] = {}
        self._nearest_fuel_distance: Dict["Planet", Optional[float]] = {}
        self._fuel_scan: Optional[
            Tuple[List[Tuple["Planet", int]], Optional[int], Optional[float]]
        ] = None
        self._trade_index: Optional[_TradeSignalIndex] = None
        # Turn the current market-fact snapshot belongs to (None = never
        # refreshed, or force-refreshed outside a turn context).
        self._facts_turn: Optional[int] = None

    # ------------------------------------------------------------------
    # Cache lifecycle
    # ------------------------------------------------------------------

    def refresh_market_facts(self, turn: Optional[int] = None) -> None:
        """Drop market-derived caches so the next queries see the live books.

        With ``turn`` given (how ship brains call it), the refresh is a no-op
        when the caches were already refreshed for that turn: market facts are
        a **per-turn shared snapshot**, built once and reused by every ship
        planning that turn. Order books only mutate between turns via deferred
        end-of-turn matching, so within a turn the snapshot stays a valid
        superset filter. Calling without ``turn`` forces a refresh (tests and
        ad-hoc probes use this). Geometry and commodity-registry caches are
        unaffected either way.
        """
        if turn is not None and turn == self._facts_turn:
            return
        self._facts_turn = turn
        self._fuel_purchasable.clear()
        self._nearest_fuel_distance.clear()
        self._fuel_scan = None
        self._trade_index = None

    # ------------------------------------------------------------------
    # Geometry (static after setup)
    # ------------------------------------------------------------------

    def distance(self, a: "Planet", b: "Planet") -> float:
        """Euclidean distance between two planets, from the cached matrix."""
        index = self._planet_index
        i = index.get(a)
        j = index.get(b)
        if i is None or j is None:
            self._rebuild_geometry()
            i = self._planet_index[a]
            j = self._planet_index[b]
        return self._distances[i][j]

    def nearest_other_distance(self, planet: "Planet") -> Optional[float]:
        """Distance to the closest other planet, or None if it is alone."""
        others = self.planets_by_proximity(planet)
        return self.distance(planet, others[0]) if others else None

    def planets_by_proximity(self, planet: "Planet") -> List["Planet"]:
        """All other planets sorted nearest-first from ``planet``."""
        cached = self._by_proximity.get(planet)
        if cached is not None and len(cached) == len(self._sim.planets) - 1:
            return cached
        ordered = sorted(
            (p for p in self._sim.planets if p is not planet),
            key=lambda other: self.distance(planet, other),
        )
        self._by_proximity[planet] = ordered
        return ordered

    def _rebuild_geometry(self) -> None:
        """(Re)build the pairwise distance matrix from planet positions."""
        planets = self._sim.planets
        self._planet_index = {planet: i for i, planet in enumerate(planets)}
        self._distances = [
            [math.sqrt((b.x - a.x) ** 2 + (b.y - a.y) ** 2) for b in planets]
            for a in planets
        ]
        self._by_proximity.clear()

    # ------------------------------------------------------------------
    # Commodity facts (static after setup)
    # ------------------------------------------------------------------

    def tradeable_commodities(self) -> List["CommodityDefinition"]:
        """All transportable commodities (the registry is fixed after setup)."""
        if self._tradeable is None:
            self._tradeable = [
                c
                for c in self._sim.commodity_registry.all_commodities()
                if c.transportable
            ]
        return self._tradeable

    def fuel_commodity(self) -> Optional["CommodityDefinition"]:
        """The nova_fuel commodity, or None if it is not defined."""
        if not self._fuel_resolved:
            self._fuel = self._sim.commodity_registry.get_commodity("nova_fuel")
            self._fuel_resolved = True
        return self._fuel

    # ------------------------------------------------------------------
    # Market-derived facts (cached until refresh_market_facts)
    # ------------------------------------------------------------------

    def fuel_purchasable_at(self, planet: "Planet") -> bool:
        """Whether nova_fuel can realistically be bought at ``planet`` right now.

        True when a standing ask exists, or when the market has a real price
        signal AND recent fuel volume (asks come and go between turns on an
        actively supplied market, so recent trades count as availability).
        """
        cached = self._fuel_purchasable.get(planet)
        if cached is not None:
            return cached
        fuel = self.fuel_commodity()
        if fuel is None:
            result = False
        else:
            market = planet.market
            _, ask = market.get_bid_ask_spread(fuel)
            if ask is not None:
                result = True
            elif not market.has_price_signal(fuel):
                result = False
            else:
                recent = market.volume_history.get(fuel, [])[
                    -FUEL_MARKET_RECENCY_TURNS:
                ]
                result = any(v > 0 for v in recent)
        self._fuel_purchasable[planet] = result
        return result

    def nearest_fuel_source_distance(self, planet: "Planet") -> Optional[float]:
        """Distance from ``planet`` to the nearest OTHER fuel-selling planet.

        Returns None when fuel is purchasable nowhere else in the galaxy.
        Because fuel cost is monotone in distance, the nearest source also
        minimizes any ship's escape-fuel requirement.
        """
        if planet in self._nearest_fuel_distance:
            return self._nearest_fuel_distance[planet]
        result: Optional[float] = None
        for other in self.planets_by_proximity(planet):
            if self.fuel_purchasable_at(other):
                result = self.distance(planet, other)
                break
        self._nearest_fuel_distance[planet] = result
        return result

    def fuel_ask_planets(self) -> List[Tuple["Planet", int]]:
        """Every planet with a resting fuel ask, as (planet, ask) pairs."""
        return self._fuel_market_scan()[0]

    def cheapest_fuel_ask(self) -> Optional[int]:
        """The lowest resting fuel ask anywhere, or None if there is none."""
        return self._fuel_market_scan()[1]

    def fuel_value_reference(self) -> Optional[float]:
        """Cheapest believable fuel valuation anywhere in the galaxy.

        Minimum over every planet's current ask and its 30-day average price
        (where real trades back it). During a local scarcity spike the rolling
        averages stay near the pre-spike level, so this reference is what
        keeps a ship from filling its whole tank at panic prices. Returns
        None when no planet has any signal.
        """
        return self._fuel_market_scan()[2]

    def exportable_commodities(
        self, planet: "Planet"
    ) -> FrozenSet["CommodityDefinition"]:
        """Commodities plausibly acquirable at ``planet`` right now.

        A commodity qualifies with a resting ask or an active local flow
        (real price signal plus recent traded volume). This is a superset
        filter: plan evaluation still verifies exact prices, but commodities
        outside this set are guaranteed unacquirable and can be skipped.
        Served from the per-turn trade-signal index.
        """
        return self._trade_signal_index().exportable_by_planet.get(planet, frozenset())

    def demandable_commodities(
        self, planet: "Planet"
    ) -> FrozenSet["CommodityDefinition"]:
        """Commodities with any demand signal at ``planet`` right now.

        A commodity qualifies with at least one resting bid or a real price
        signal (which lets flow-based demand be projected). Like
        :meth:`exportable_commodities` this is a superset filter for pruning
        plan evaluation, not a substitute for it. Served from the per-turn
        trade-signal index.
        """
        return self._trade_signal_index().demandable_by_planet.get(planet, frozenset())

    def has_any_trade_signal(self) -> bool:
        """Whether any commodity has both an export source and a demand planet.

        False means the galaxy is cold (typically the pre-market bootstrap):
        no trade plan can exist anywhere, so ship planning can early-out for
        the turn instead of surveying every market.
        """
        return self._trade_signal_index().has_any_trade_signal()

    def candidate_destinations(
        self, origin: "Planet", commodity: "CommodityDefinition"
    ) -> Tuple["Planet", ...]:
        """Shortlist of destination planets worth evaluating for ``commodity``.

        The union of the :data:`DESTINATION_TOP_K` demand planets with the
        highest demand value (best resting bid or recent clearing price) and
        the :data:`DESTINATION_NEAREST_M` demand planets nearest ``origin``,
        excluding ``origin`` itself. When the commodity has at most K + M
        demand planets the shortlist is ALL of them, so small galaxies keep
        exhaustive-survey behavior. Results are memoized in the per-turn
        index and shared by every ship.
        """
        index = self._trade_signal_index()
        memo_key = (origin, commodity)
        cached = index.candidate_memo.get(memo_key)
        if cached is not None:
            return cached
        pool = [
            planet
            for planet in index.demand_ranked.get(commodity, ())
            if planet is not origin
        ]
        if len(pool) <= DESTINATION_TOP_K + DESTINATION_NEAREST_M:
            result = tuple(pool)
        else:
            chosen = pool[:DESTINATION_TOP_K]
            chosen_set = set(chosen)
            demand_planets = index.demand_planets.get(commodity, frozenset())
            found_near = 0
            for planet in self.planets_by_proximity(origin):
                if found_near >= DESTINATION_NEAREST_M:
                    break
                if planet in demand_planets:
                    found_near += 1
                    if planet not in chosen_set:
                        chosen.append(planet)
                        chosen_set.add(planet)
            result = tuple(chosen)
        index.candidate_memo[memo_key] = result
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _trade_signal_index(self) -> _TradeSignalIndex:
        """The turn's trade-signal index, built lazily on first use.

        One O(planets x commodities) pass over every market collecting the
        per-planet exportable/demandable summaries and, per commodity, the
        export planets and the demand planets ranked by demand value (the
        better of the best resting bid and the recent clearing price, when a
        real price signal backs it). Cached until the next
        :meth:`refresh_market_facts`, i.e. for the rest of the turn.
        """
        if self._trade_index is not None:
            return self._trade_index
        tradeable = self.tradeable_commodities()
        exportable_by_planet: Dict["Planet", FrozenSet["CommodityDefinition"]] = {}
        demandable_by_planet: Dict["Planet", FrozenSet["CommodityDefinition"]] = {}
        export_lists: Dict["CommodityDefinition", List["Planet"]] = {
            commodity: [] for commodity in tradeable
        }
        # Per commodity: (negated demand value, planet) rows; sorting them is
        # stable, so ties keep simulation planet order without comparing
        # Planet objects.
        demand_rows: Dict["CommodityDefinition", List[Tuple[float, "Planet"]]] = {
            commodity: [] for commodity in tradeable
        }
        for planet in self._sim.planets:
            market = planet.market
            exportable: List["CommodityDefinition"] = []
            demandable: List["CommodityDefinition"] = []
            for commodity in tradeable:
                best_bid, ask = market.get_bid_ask_spread(commodity)
                has_signal = market.has_price_signal(commodity)
                if (ask is not None and ask > 0) or (
                    has_signal
                    and any(
                        v > 0
                        for v in market.volume_history.get(commodity, [])[
                            -FLOW_RECENCY_TURNS:
                        ]
                    )
                ):
                    exportable.append(commodity)
                    export_lists[commodity].append(planet)
                if best_bid is not None or has_signal:
                    demandable.append(commodity)
                    value = float(best_bid or 0)
                    if has_signal:
                        value = max(value, float(market.get_avg_price(commodity)))
                    demand_rows[commodity].append((-value, planet))
            exportable_by_planet[planet] = frozenset(exportable)
            demandable_by_planet[planet] = frozenset(demandable)
        demand_ranked: Dict["CommodityDefinition", Tuple["Planet", ...]] = {}
        demand_planets: Dict["CommodityDefinition", FrozenSet["Planet"]] = {}
        for commodity, rows in demand_rows.items():
            rows.sort(key=lambda row: row[0])
            demand_ranked[commodity] = tuple(planet for _, planet in rows)
            demand_planets[commodity] = frozenset(demand_ranked[commodity])
        self._trade_index = _TradeSignalIndex(
            exportable_by_planet=exportable_by_planet,
            demandable_by_planet=demandable_by_planet,
            export_planets={
                commodity: frozenset(planets)
                for commodity, planets in export_lists.items()
            },
            demand_ranked=demand_ranked,
            demand_planets=demand_planets,
        )
        return self._trade_index

    def _fuel_market_scan(
        self,
    ) -> Tuple[List[Tuple["Planet", int]], Optional[int], Optional[float]]:
        """One O(planets) sweep collecting galaxy-wide fuel market facts.

        Returns (planets with resting asks, cheapest ask, cheapest believable
        valuation), cached until the next refresh.
        """
        if self._fuel_scan is not None:
            return self._fuel_scan
        asks: List[Tuple["Planet", int]] = []
        cheapest_ask: Optional[int] = None
        reference: Optional[float] = None
        fuel = self.fuel_commodity()
        if fuel is not None:
            for planet in self._sim.planets:
                market = planet.market
                _, ask = market.get_bid_ask_spread(fuel)
                if ask is not None and ask > 0:
                    asks.append((planet, ask))
                    if cheapest_ask is None or ask < cheapest_ask:
                        cheapest_ask = ask
                    if reference is None or ask < reference:
                        reference = float(ask)
                if market.has_price_signal(fuel):
                    avg_30 = market.get_30_day_average_price(fuel)
                    if avg_30 > 0 and (reference is None or avg_30 < reference):
                        reference = avg_30
        self._fuel_scan = (asks, cheapest_ask, reference)
        return self._fuel_scan


_navigators: "WeakKeyDictionary[Simulation, Navigator]" = WeakKeyDictionary()


def get_navigator(sim: "Simulation") -> Navigator:
    """Return the shared :class:`Navigator` for ``sim``, creating it on demand.

    Kept in a weak registry so a navigator lives exactly as long as its
    simulation, without the simulation needing to know about navigation.
    """
    navigator = _navigators.get(sim)
    if navigator is None:
        navigator = Navigator(sim)
        _navigators[sim] = navigator
    return navigator
