"""Migration: the mechanics of an actor moving between planets.

The split is deliberate. Brains decide whether, when, and where an actor
moves (``ActorBrain.decide_migration``); this module and the simulation own
what a move does. Nothing here reads a drive or a price to decide anything.

Flow, v1 (no ships involved):

1. During its turn an actor's brain returns a ``MigrationRequest`` or
   ``NO_MIGRATION``. ``Actor.take_turn`` stores the result on
   ``actor.migration_request``. The actor phase is threaded by planet, so
   nothing moves here.
2. After the ship phase and before market matching,
   ``run_migration_phase`` first lands every migrant whose arrival turn has
   come, then scans regular actors: it cancels their orders, charges the
   fare to the origin's spaceport operators, reserves a land at the
   destination, clears the inventory, removes the actor from its planet and
   from ``sim.actors``, and parks it in ``sim.migrants_in_transit`` for one
   turn per lane unit of distance.
3. On arrival ``relocate_actor`` finishes the move: the actor joins the
   destination with the reserved land and a fresh brain cache, and its
   brain's ``on_relocated`` hook runs.

An actor in transit is in neither ``sim.actors`` nor any
``planet.actors``, which keeps the ``core/parallel.py`` invariant that the
two cover each other. Its ``planet`` still points at the origin;
``actor.in_transit`` is the authoritative flag.

v2 will hand step 2 to a ship brain that accepts the request as a passage
contract at the spaceport; ``relocate_actor`` stays the same.

``refresh_planet_stats`` builds one ``PlanetStats`` per planet at the start
of each turn so brains can score destinations without walking every actor.
The stats are mechanical aggregates only; how to weigh them is brain logic.
"""

import math
from dataclasses import dataclass
from statistics import median
from typing import TYPE_CHECKING, Dict, List, Mapping, Union

from spacesim2.core.navigation import get_navigator

# ``Actor`` imports this module for ``NO_MIGRATION``, so anything reachable
# from ``core.actor`` is imported inside the function that needs it.

if TYPE_CHECKING:
    from spacesim2.core.actor import Actor
    from spacesim2.core.land import Land
    from spacesim2.core.planet import Planet
    from spacesim2.core.simulation import Simulation


# Credits per unit of lane distance for passage in v1. Paid to the origin
# planet's spaceport operators (split evenly) so the money stays in the
# economy; if there are none it is destroyed.
PASSAGE_FARE_PER_DISTANCE = 2.0
PASSAGE_FARE_MINIMUM = 20

# Lane distance covered per transit turn; the same speed ships fly at
# (``Ship.travel_time``), so v1 transit takes as long as the v2 passage will.
TRANSIT_DISTANCE_PER_TURN = 20

# Cargo units one migrant occupies on a ship in v2. Unused in v1. The value
# is undecided (10 or 100); keep it a single constant.
MIGRANT_CARGO_UNITS = 10


@dataclass(frozen=True)
class MigrationRequest:
    """A brain's decision to move to ``destination`` for at most ``max_fare``."""

    destination: "Planet"
    max_fare: int


class NoMigration:
    """Sentinel: the brain wants the actor to stay."""

    def __repr__(self) -> str:
        return "NO_MIGRATION"


NO_MIGRATION = NoMigration()

MigrationDecision = Union[MigrationRequest, NoMigration]


@dataclass(frozen=True)
class PlanetStats:
    """Per-planet aggregates over regular residents, rebuilt each turn.

    ``free_land_mean`` maps a resource id to the mean coefficient of the
    unclaimed lands, the expected draw for a newcomer; empty when the pool
    is empty. ``median_need_debt`` is the median over residents of each
    resident's maximum need-drive ``debt``. ``median_prosperity`` is the
    median ``prosperity_index``. Medians are 0.0 with no residents.
    """

    population: int
    free_land_count: int
    free_land_mean: Mapping[str, float]
    median_need_debt: float
    median_prosperity: float
    median_money: float


@dataclass(frozen=True)
class MigrationEvent:
    """One completed departure, for the run log and post-hoc analysis."""

    turn: int
    actor_name: str
    origin_name: str
    destination_name: str
    fare: int


@dataclass
class MigrantInTransit:
    """An actor between planets, with the land already reserved for it."""

    actor: "Actor"
    origin: "Planet"
    destination: "Planet"
    land: "Land"
    arrival_turn: int


def passage_fare(distance: float) -> int:
    """v1 fare for a route of ``distance`` lane units."""
    return max(PASSAGE_FARE_MINIMUM, int(round(distance * PASSAGE_FARE_PER_DISTANCE)))


def refresh_planet_stats(sim: "Simulation") -> Dict["Planet", PlanetStats]:
    """Rebuild ``sim.planet_stats`` for every planet and return it.

    Runs at the top of every turn over every regular resident of every
    planet, so it walks the population once and sorts only what a median
    needs. ``free_land_mean`` is one pass over the unclaimed pool.
    """
    from spacesim2.core.drives.prosperity_drive import prosperity_index

    stats: Dict["Planet", PlanetStats] = {}
    for planet in sim.planets:
        debts: List[float] = []
        prosperities: List[float] = []
        monies: List[float] = []
        for actor in planet.actors:
            if not actor.claims_land:
                continue
            worst_debt = 0.0
            for drive in actor.drives:
                if drive.WELLBEING and drive.metrics.debt > worst_debt:
                    worst_debt = drive.metrics.debt
            debts.append(worst_debt)
            prosperities.append(prosperity_index(actor))
            monies.append(float(actor.money))

        free_lands = planet.free_lands
        sums: Dict[str, float] = {}
        for land in free_lands:
            for resource, value in land.coefficients.items():
                sums[resource] = sums.get(resource, 0.0) + value
        count = len(free_lands)
        free_land_mean = (
            {resource: total / count for resource, total in sums.items()}
            if count
            else {}
        )

        stats[planet] = PlanetStats(
            population=len(debts),
            free_land_count=count,
            free_land_mean=free_land_mean,
            median_need_debt=median(debts) if debts else 0.0,
            median_prosperity=median(prosperities) if prosperities else 0.0,
            median_money=median(monies) if monies else 0.0,
        )

    sim.planet_stats = stats
    return stats


def run_migration_phase(sim: "Simulation") -> None:
    """Depart every actor holding a request it can afford; land arrivals due.

    Arrivals are settled first, so an actor that lands this turn is on its
    new planet before departures are considered and the freed land it left
    behind is already available to someone else.
    """
    _land_arrivals(sim)
    _depart_requesters(sim)


def _land_arrivals(sim: "Simulation") -> None:
    """Place every migrant whose arrival turn has come."""
    still_flying: List[MigrantInTransit] = []
    for migrant in sim.migrants_in_transit:
        if migrant.arrival_turn <= sim.current_turn:
            relocate_actor(migrant.actor, migrant.destination, migrant.land)
        else:
            still_flying.append(migrant)
    sim.migrants_in_transit = still_flying


def _depart_requesters(sim: "Simulation") -> None:
    """Charge, strip, and launch every actor whose request is affordable."""
    navigator = get_navigator(sim)
    for actor in list(sim.actors):
        request = actor.migration_request
        if not isinstance(request, MigrationRequest):
            continue
        actor.migration_request = NO_MIGRATION

        origin = actor.planet
        destination = request.destination
        if origin is None or destination is origin:
            continue
        if not destination.free_lands:
            continue
        distance = navigator.distance(origin, destination)
        fare = passage_fare(distance)
        if fare > request.max_fare or fare > actor.money:
            continue

        _cancel_all_orders(actor, origin)
        actor.money -= fare
        _pay_operators(origin, fare)

        land = destination.claim_land()
        origin.remove_actor(actor)
        sim.actors.remove(actor)
        actor.in_transit = True
        # The migrant travels with nothing. A brain that wants value at the
        # far end liquidates before it asks to move.
        actor.inventory.clear()

        # One turn per lane unit, at least one: the trip is the same length
        # a ship would fly, so a move is a real cost in lost turns.
        arrival_turn = sim.current_turn + max(
            1, math.ceil(distance / TRANSIT_DISTANCE_PER_TURN)
        )
        sim.migrants_in_transit.append(
            MigrantInTransit(
                actor=actor,
                origin=origin,
                destination=destination,
                land=land,
                arrival_turn=arrival_turn,
            )
        )
        sim.migration_departures += 1
        sim.migration_log.append(
            MigrationEvent(
                turn=sim.current_turn,
                actor_name=actor.name,
                origin_name=origin.name,
                destination_name=destination.name,
                fare=fare,
            )
        )


def _cancel_all_orders(actor: "Actor", planet: "Planet") -> None:
    """Cancel every live order the actor holds, releasing money and goods."""
    market = planet.market
    for order_id in list(actor.active_orders):
        market.cancel_order(order_id)


def _pay_operators(planet: "Planet", fare: int) -> None:
    """Split a fare evenly among the planet's spaceport operators.

    Integer division leaves a remainder of at most one credit per operator;
    it is destroyed, which keeps the split symmetric. With no operator on
    the planet the whole fare is destroyed.
    """
    from spacesim2.core.actor import ActorType
    from spacesim2.core.brains import SpaceportOperatorBrain

    operators = [
        actor
        for actor in planet.actors
        if actor.actor_type is ActorType.SERVICE
        and isinstance(actor.brain, SpaceportOperatorBrain)
    ]
    if not operators:
        return
    share = fare // len(operators)
    for operator in operators:
        operator.money += share


def relocate_actor(actor: "Actor", destination: "Planet", land: "Land") -> None:
    """Attach an actor that has left its origin to ``destination`` with ``land``.

    The land was claimed from ``destination`` at departure, so this attaches
    it rather than drawing a second one. The brain cache is dropped whole:
    its ``yield_modifier`` group is keyed on the actor's land and is never
    otherwise reset, so a stale cache would keep valuing the old planet's
    yields. Brain-internal state is the brain's own to reset, via
    ``ActorBrain.on_relocated``.
    """
    destination.add_actor_with_land(actor, land)
    sim = actor.sim
    sim.actors.append(actor)
    actor.in_transit = False
    actor.brain._cache = None
    actor.last_market_check_turn = sim.current_turn
    actor.brain.on_relocated(actor)
    sim.migration_arrivals += 1
