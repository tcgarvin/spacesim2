"""Government freight: routine short-haul jobs posted on every board.

A broke ship on a poor planet has no income and nothing worth exporting.
The government keeps one open job at every planet, priced at a leg of fuel
plus a quarter, so such a ship always has a paid move available. The
payload is a :class:`ConsignmentPayload`, an abstract lot that never
touches the goods economy: only hold space and money move.

Posting is all this module does. Whether a ship takes a job is
``TraderBrain``'s decision, and what a taken job does is
``core/contracts.py``'s.

Sizing. The advance covers one leg's fuel at the galaxy's typical fuel
price and a quarter more. A trade plan needs 15% on its purchase cost,
which at the cargo values ships move is several times a leg's fuel, so a
job beats a trade only when there is no trade.
"""

import math
import random
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple
from weakref import WeakKeyDictionary

from spacesim2.core.contracts import GOVERNMENT, ConsignmentPayload, Contract
from spacesim2.core.navigation import FUEL_BID_FALLBACK_FLOOR, get_navigator

if TYPE_CHECKING:
    from spacesim2.core.planet import Planet
    from spacesim2.core.simulation import Simulation


# Open government jobs kept on each planet's board. A taken job is replaced
# the next turn, so the supply is one job per planet at a time, not one per
# ship.
GOVERNMENT_JOBS_PER_PLANET = 1

# Hold space one freight lot occupies.
GOVERNMENT_JOB_UNITS = 20

# Longest job, in lanes of the shortest route. Short hauls keep the advance
# small and put the ship back on a board quickly.
GOVERNMENT_JOB_MAX_HOPS = 2

# Fraction above the leg's fuel cost the advance pays.
GOVERNMENT_JOB_MARGIN = 0.25

# Turns an unaccepted job stands before it expires and is re-rolled to a
# new destination and a current fuel price.
GOVERNMENT_JOB_TTL = 30


# Destinations within GOVERNMENT_JOB_MAX_HOPS of each planet, per
# simulation. The lane graph is static after setup, so this is computed
# once; the key records the galaxy it was computed for so a world that
# grows afterwards is recomputed rather than answered from stale data.
_destinations: "WeakKeyDictionary[Simulation, _DestinationCache]" = WeakKeyDictionary()


class _DestinationCache:
    """In-range destinations per planet, valid for one galaxy shape."""

    def __init__(self, shape: Tuple[int, int]) -> None:
        self.shape = shape
        self.by_planet: Dict["Planet", List["Planet"]] = {}


def _galaxy_shape(sim: "Simulation") -> Tuple[int, int]:
    return (len(sim.planets), len(sim.star_lanes))


def _in_range_destinations(sim: "Simulation", origin: "Planet") -> List["Planet"]:
    """Planets whose shortest lane route from ``origin`` is 1..MAX_HOPS lanes.

    Candidates come from a breadth-first walk of the lane graph, which
    bounds the search: a planet the shortest route reaches in two lanes is
    at most two lanes away by hop count too. The route decides membership,
    since the route is what a ship actually flies.
    """
    shape = _galaxy_shape(sim)
    cache = _destinations.get(sim)
    if cache is None or cache.shape != shape:
        cache = _DestinationCache(shape)
        _destinations[sim] = cache

    cached = cache.by_planet.get(origin)
    if cached is not None:
        return cached

    navigator = get_navigator(sim)
    candidates: List["Planet"] = []
    seen = {origin}
    frontier = [origin]
    for _ in range(GOVERNMENT_JOB_MAX_HOPS):
        next_frontier: List["Planet"] = []
        for planet in frontier:
            for neighbor in sim.star_lanes.neighbors(planet):
                if neighbor in seen:
                    continue
                seen.add(neighbor)
                candidates.append(neighbor)
                next_frontier.append(neighbor)
        frontier = next_frontier

    in_range = [
        planet
        for planet in candidates
        if 1 <= len(navigator.route(origin, planet)) - 1 <= GOVERNMENT_JOB_MAX_HOPS
    ]
    cache.by_planet[origin] = in_range
    return in_range


def government_job_advance(
    sim: "Simulation", origin: "Planet", destination: "Planet"
) -> int:
    """What the government pays a carrier to fly this leg.

    One leg of fuel at the galaxy's typical fuel valuation, plus
    ``GOVERNMENT_JOB_MARGIN``. Fuel is the baseline burn at efficiency 1.0,
    so an efficient ship keeps the difference. Before anything has traded
    there is no reference, and ``FUEL_BID_FALLBACK_FLOOR`` stands in, the
    same fabricated-price guard the fuel bids use.
    """
    from spacesim2.core.ship import Ship

    navigator = get_navigator(sim)
    reference: Optional[float] = navigator.fuel_value_reference()
    if reference is None:
        reference = float(FUEL_BID_FALLBACK_FLOOR)
    fuel_needed = Ship.calculate_fuel_needed(navigator.distance(origin, destination))
    return math.ceil(fuel_needed * reference * (1 + GOVERNMENT_JOB_MARGIN))


def _open_government_jobs(planet: "Planet") -> int:
    return sum(
        1
        for contract in planet.contracts.open_contracts()
        if contract.poster is GOVERNMENT
    )


def refresh_government_jobs(sim: "Simulation") -> None:
    """Top every planet's board back up to its quota of open freight jobs.

    Runs at the top of the turn, after board expiry, so a job taken last
    turn is replaced this turn and an expired one is re-rolled to a new
    destination at a current fuel price. A planet with nothing in range
    posts nothing.
    """
    for planet in sim.planets:
        destinations = _in_range_destinations(sim, planet)
        if not destinations:
            continue
        while _open_government_jobs(planet) < GOVERNMENT_JOBS_PER_PLANET:
            destination = random.choice(destinations)
            advance = government_job_advance(sim, planet, destination)
            if advance <= 0:
                break
            planet.contracts.post(
                Contract(
                    poster=GOVERNMENT,
                    origin=planet,
                    destination=destination,
                    payload=ConsignmentPayload(units=GOVERNMENT_JOB_UNITS),
                    advance=advance,
                    on_delivery=0,
                    posted_turn=sim.current_turn,
                    expires_turn=sim.current_turn + GOVERNMENT_JOB_TTL,
                )
            )
            sim.contracts_posted += 1
