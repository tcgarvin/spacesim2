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
  reference, and per-planet commodity summaries. These are cached per
  *planning decision*: each ship brain calls :meth:`Navigator.refresh_market_facts`
  when it starts deciding, then every candidate evaluated inside that decision
  reuses the snapshot. A decision therefore sees one consistent view of the
  galaxy instead of re-scanning it per (origin, destination, commodity).

Use :func:`get_navigator` to obtain the per-simulation shared instance.
"""

from __future__ import annotations

import math
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


class Navigator:
    """Cached view of galaxy geometry and fuel reachability for one simulation.

    Geometry is cached for the simulation's lifetime. Market-derived facts
    are cached until the next :meth:`refresh_market_facts` call (ship brains
    refresh once per planning decision).
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
        self._exportable: Dict["Planet", FrozenSet["CommodityDefinition"]] = {}
        self._demandable: Dict["Planet", FrozenSet["CommodityDefinition"]] = {}

    # ------------------------------------------------------------------
    # Cache lifecycle
    # ------------------------------------------------------------------

    def refresh_market_facts(self) -> None:
        """Drop market-derived caches so the next queries see the live books.

        Ship brains call this once at the start of each planning decision;
        geometry and commodity-registry caches are unaffected.
        """
        self._fuel_purchasable.clear()
        self._nearest_fuel_distance.clear()
        self._fuel_scan = None
        self._exportable.clear()
        self._demandable.clear()

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
        """
        cached = self._exportable.get(planet)
        if cached is not None:
            return cached
        market = planet.market
        exportable = []
        for commodity in self.tradeable_commodities():
            _, ask = market.get_bid_ask_spread(commodity)
            if ask is not None and ask > 0:
                exportable.append(commodity)
                continue
            if market.has_price_signal(commodity) and any(
                v > 0
                for v in market.volume_history.get(commodity, [])[-FLOW_RECENCY_TURNS:]
            ):
                exportable.append(commodity)
        result = frozenset(exportable)
        self._exportable[planet] = result
        return result

    def demandable_commodities(
        self, planet: "Planet"
    ) -> FrozenSet["CommodityDefinition"]:
        """Commodities with any demand signal at ``planet`` right now.

        A commodity qualifies with at least one resting bid or a real price
        signal (which lets flow-based demand be projected). Like
        :meth:`exportable_commodities` this is a superset filter for pruning
        plan evaluation, not a substitute for it.
        """
        cached = self._demandable.get(planet)
        if cached is not None:
            return cached
        market = planet.market
        result = frozenset(
            commodity
            for commodity in self.tradeable_commodities()
            if market.buy_orders.get(commodity) or market.has_price_signal(commodity)
        )
        self._demandable[planet] = result
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

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
