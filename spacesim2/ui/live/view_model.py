"""Read-only adapters over :class:`Simulation` for the live view.

This layer is the *only* thing the renderer reads from. It exposes small,
immutable snapshots (plain dataclasses) so rendering code never touches core
objects directly and core stays free of any UI concerns. Nothing here mutates
the simulation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from spacesim2.core.actor import ActorType
from spacesim2.core.planet import Planet
from spacesim2.core.ship import Ship, ShipStatus
from spacesim2.core.simulation import Simulation


@dataclass(frozen=True)
class PlanetSnapshot:
    """Immutable per-frame view of a planet."""

    name: str
    pos: Tuple[float, float]  # map coordinates, 0..100
    wellbeing: float  # mean regular-actor welfare in [0, 1]
    population: int  # regular actors resident


@dataclass(frozen=True)
class ShipSnapshot:
    """Immutable per-frame view of a ship.

    For a docked ship ``origin == dest == its planet``. For a traveling ship the
    core keeps ``ship.planet`` as the origin and ``ship.destination`` as the
    target while ``progress`` advances 0->1 (see ``core/ship.py``); the renderer
    interpolates position between the two.
    """

    name: str
    traveling: bool
    origin: Tuple[float, float]
    dest: Tuple[float, float]
    progress: float  # 0..1 along origin->dest; 0 when docked


def planet_wellbeing(planet: Planet) -> float:
    """Mean welfare of resident regular actors, in [0, 1].

    Averages each actor's drive scores (``drive.metrics.get_score()``), then
    averages across actors. Market makers are excluded — they are economic
    plumbing, not colonists whose wellbeing we care about. Returns 0.0 when the
    planet has no regular actors.
    """
    scores: List[float] = []
    for actor in planet.actors:
        if actor.actor_type == ActorType.MARKET_MAKER:
            continue
        if not actor.drives:
            continue
        actor_score = sum(d.metrics.get_score() for d in actor.drives) / len(
            actor.drives
        )
        scores.append(actor_score)
    if not scores:
        return 0.0
    return max(0.0, min(1.0, sum(scores) / len(scores)))


def _regular_population(planet: Planet) -> int:
    return sum(1 for a in planet.actors if a.actor_type != ActorType.MARKET_MAKER)


def _ship_snapshot(ship: Ship) -> ShipSnapshot:
    traveling = ship.status == ShipStatus.TRAVELING and ship.destination is not None
    origin_planet = ship.planet
    origin = origin_planet.get_position() if origin_planet is not None else (50.0, 50.0)
    if traveling and ship.destination is not None:
        dest = ship.destination.get_position()
        progress = max(0.0, min(1.0, ship.travel_progress))
    else:
        dest = origin
        progress = 0.0
    return ShipSnapshot(
        name=ship.name,
        traveling=traveling,
        origin=origin,
        dest=dest,
        progress=progress,
    )


class GalaxyViewModel:
    """Thin read-only facade the renderer queries each frame."""

    def __init__(self, simulation: Simulation) -> None:
        self._sim = simulation

    @property
    def current_turn(self) -> int:
        return self._sim.current_turn

    def planets(self) -> List[PlanetSnapshot]:
        return [
            PlanetSnapshot(
                name=p.name,
                pos=p.get_position(),
                wellbeing=planet_wellbeing(p),
                population=_regular_population(p),
            )
            for p in self._sim.planets
        ]

    def ships(self) -> List[ShipSnapshot]:
        return [_ship_snapshot(s) for s in self._sim.ships]
