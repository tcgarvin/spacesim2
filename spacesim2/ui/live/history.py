"""Per-turn time-series recorder feeding the live charts.

The market already keeps an unbounded per-turn ``price_history`` / ``volume_history``
per planet-market, but the live charts need three things those raw lists don't give
cheaply: a *bounded* window (so a long-running session can't grow without limit),
a *galaxy-wide aggregate* across every planet market, and a citizen-wellbeing series
(which the core records nowhere). :class:`HistoryRecorder` samples all of that once
per turn into ring buffers the renderer can read each frame without touching core
internals or re-aggregating.

Sampling is driven by the :class:`~spacesim2.ui.live.director.Director`, which calls
:meth:`sample` immediately after each ``run_turn`` (and once at startup for a turn-0
baseline). Nothing here mutates the simulation.
"""

from __future__ import annotations

from collections import deque
from typing import Deque, Dict, List

from spacesim2.core.actor import ActorType
from spacesim2.core.commodity import CommodityDefinition
from spacesim2.core.planet import Planet
from spacesim2.core.simulation import Simulation
from spacesim2.ui.live.view_model import planet_wellbeing

# How many turns of history to retain. At one point per turn this is plenty for a
# scrolling chart while staying tiny in memory (a few thousand floats per series).
DEFAULT_WINDOW = 2048


def _global_wellbeing(sim: Simulation) -> float:
    """Mean welfare across every regular actor in the galaxy, in [0, 1].

    Averaging each regular actor's mean drive score over the whole population is
    naturally population-weighted (a planet with more colonists counts for more).
    Market makers are excluded — they are economic plumbing, not colonists.
    """
    scores: List[float] = []
    for planet in sim.planets:
        for actor in planet.actors:
            if actor.actor_type == ActorType.MARKET_MAKER or not actor.drives:
                continue
            scores.append(
                sum(d.metrics.get_score() for d in actor.drives) / len(actor.drives)
            )
    if not scores:
        return 0.0
    return max(0.0, min(1.0, sum(scores) / len(scores)))


def _galaxy_price_and_volume(
    sim: Simulation, commodity: CommodityDefinition
) -> tuple[float, float]:
    """Galaxy-wide strike price and total volume for ``commodity`` this turn.

    The strike price is volume-weighted across planet markets (a market that
    actually traded should dominate the headline price). When no market traded
    this turn we fall back to each market's own valuation (``get_avg_price``,
    which carries the last price forward and never returns zero) so the line
    stays continuous instead of dropping to a misleading zero — important for the
    turn-0 baseline, before any market has traded. Returns
    ``(price, total_volume)``.
    """
    weighted_price = 0.0
    total_volume = 0.0
    valuation_sum = 0.0
    market_count = 0
    for planet in sim.planets:
        market = planet.market
        volumes = market.volume_history.get(commodity, [])
        last_volume = float(volumes[-1]) if volumes else 0.0
        if last_volume > 0.0:
            last_price = float(market.price_history[commodity][-1])
            weighted_price += last_price * last_volume
            total_volume += last_volume
        valuation_sum += market.get_avg_price(commodity)
        market_count += 1

    if total_volume > 0.0:
        return weighted_price / total_volume, total_volume
    if market_count > 0:
        return valuation_sum / market_count, 0.0
    return 0.0, 0.0


def _planet_price_and_volume(
    planet: Planet, commodity: CommodityDefinition
) -> tuple[float, float]:
    """One planet market's strike price and volume for ``commodity`` this turn.

    Mirrors the galaxy aggregate's continuity rule: on a turn with no trades the
    price falls back to the market's own valuation (last strike carried forward)
    so the local line never drops to a misleading zero.
    """
    market = planet.market
    volumes = market.volume_history.get(commodity, [])
    last_volume = float(volumes[-1]) if volumes else 0.0
    if last_volume > 0.0:
        return float(market.price_history[commodity][-1]), last_volume
    return float(market.get_avg_price(commodity)), 0.0


class HistoryRecorder:
    """Bounded per-turn time series for the live charts.

    One sample per turn: galaxy-wide strike price and volume for every
    transportable commodity, plus mean citizen wellbeing. Read back as plain
    lists for charting.
    """

    def __init__(self, simulation: Simulation, window: int = DEFAULT_WINDOW) -> None:
        self._sim = simulation
        self._window = window
        self.commodities: List[CommodityDefinition] = [
            c
            for c in simulation.commodity_registry.all_commodities()
            if c.transportable
        ]
        self._turns: Deque[int] = deque(maxlen=window)
        self._price: Dict[str, Deque[float]] = {
            c.id: deque(maxlen=window) for c in self.commodities
        }
        self._volume: Dict[str, Deque[float]] = {
            c.id: deque(maxlen=window) for c in self.commodities
        }
        self._wellbeing: Deque[float] = deque(maxlen=window)
        # Per-planet series, keyed by planet name then commodity id. Sampled in
        # lockstep with the galaxy series so they share the same turn axis.
        self._planet_price: Dict[str, Dict[str, Deque[float]]] = {
            p.name: {c.id: deque(maxlen=window) for c in self.commodities}
            for p in simulation.planets
        }
        self._planet_volume: Dict[str, Dict[str, Deque[float]]] = {
            p.name: {c.id: deque(maxlen=window) for c in self.commodities}
            for p in simulation.planets
        }
        self._planet_wellbeing: Dict[str, Deque[float]] = {
            p.name: deque(maxlen=window) for p in simulation.planets
        }
        # Capture a turn-0 baseline so the charts have a point before any turn runs.
        self.sample()

    def sample(self) -> None:
        """Record one data point for the current simulation state."""
        self._turns.append(self._sim.current_turn)
        self._wellbeing.append(_global_wellbeing(self._sim))
        for commodity in self.commodities:
            price, volume = _galaxy_price_and_volume(self._sim, commodity)
            self._price[commodity.id].append(price)
            self._volume[commodity.id].append(volume)
        for planet in self._sim.planets:
            if planet.name not in self._planet_wellbeing:
                continue  # planet added after startup; not tracked
            self._planet_wellbeing[planet.name].append(planet_wellbeing(planet))
            for commodity in self.commodities:
                price, volume = _planet_price_and_volume(planet, commodity)
                self._planet_price[planet.name][commodity.id].append(price)
                self._planet_volume[planet.name][commodity.id].append(volume)

    def turn_axis(self) -> List[int]:
        return list(self._turns)

    def prices(self, commodity_id: str) -> List[float]:
        return list(self._price.get(commodity_id, ()))

    def volumes(self, commodity_id: str) -> List[float]:
        return list(self._volume.get(commodity_id, ()))

    def wellbeing(self) -> List[float]:
        return list(self._wellbeing)

    def planet_prices(self, planet_name: str, commodity_id: str) -> List[float]:
        return list(self._planet_price.get(planet_name, {}).get(commodity_id, ()))

    def planet_volumes(self, planet_name: str, commodity_id: str) -> List[float]:
        return list(self._planet_volume.get(planet_name, {}).get(commodity_id, ()))

    def planet_wellbeing_series(self, planet_name: str) -> List[float]:
        return list(self._planet_wellbeing.get(planet_name, ()))
