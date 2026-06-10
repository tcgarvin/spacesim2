"""Read-only adapters over :class:`Simulation` for the live view.

This layer is the *only* thing the renderer reads from. It exposes small,
immutable snapshots (plain dataclasses) so rendering code never touches core
objects directly and core stays free of any UI concerns. Nothing here mutates
the simulation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from spacesim2.core.actor import ActorType
from spacesim2.core.planet import Planet
from spacesim2.core.ship import Ship, ShipStatus
from spacesim2.core.simulation import Simulation

FUEL_COMMODITY_ID = "nova_fuel"


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


@dataclass(frozen=True)
class DriveStat:
    """One drive's wellbeing across a planet's regular actors."""

    name: str
    mean_score: float  # mean of drive.get_score() in [0, 1]
    worst_score: float  # the single worst-off actor, in [0, 1]


@dataclass(frozen=True)
class MarketRow:
    """One commodity's local-market readout."""

    commodity_id: str
    commodity_name: str
    price: int  # market valuation (last strike, carried forward)
    volume_30d: float  # mean daily volume over the last 30 turns
    scarcity: float  # scarcity pressure, 0 when well-served


@dataclass(frozen=True)
class TradeRow:
    """One recently completed transaction on a planet's market."""

    turn: int
    commodity_name: str
    quantity: int
    price: int
    buyer: str
    seller: str


@dataclass(frozen=True)
class PlanetDetail:
    """Drill-down snapshot of one planet for the overlay panel."""

    name: str
    population: int
    wellbeing: float
    total_wealth: int  # money held by regular actors
    drives: Tuple[DriveStat, ...]
    market: Tuple[MarketRow, ...]
    docked_ships: Tuple[str, ...]
    recent_trades: Tuple[TradeRow, ...]


@dataclass(frozen=True)
class CargoRow:
    commodity_name: str
    quantity: int


@dataclass(frozen=True)
class ShipDetail:
    """Drill-down snapshot of one ship for the overlay panel."""

    name: str
    status: str  # human label, e.g. "docked at Vesper"
    money: int
    fuel: int
    cargo: Tuple[CargoRow, ...]
    cargo_used: int
    cargo_capacity: int
    route: str  # "Vesper -> Kael (42%)" while traveling, "" otherwise
    last_action: str


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


def _drive_stats(planet: Planet) -> Tuple[DriveStat, ...]:
    """Per-drive mean and worst score across the planet's regular actors.

    Grouped by drive name so the panel shows one row per need (Food, Clothing,
    ...) regardless of how many actors carry it.
    """
    scores_by_name: dict[str, List[float]] = {}
    for actor in planet.actors:
        if actor.actor_type == ActorType.MARKET_MAKER:
            continue
        for drive in actor.drives:
            score = max(0.0, min(1.0, drive.metrics.get_score()))
            scores_by_name.setdefault(drive.metrics.get_name(), []).append(score)
    return tuple(
        DriveStat(name=name, mean_score=sum(s) / len(s), worst_score=min(s))
        for name, s in sorted(scores_by_name.items())
    )


def _market_rows(planet: Planet, sim: Simulation) -> Tuple[MarketRow, ...]:
    market = planet.market
    rows = []
    for commodity in sim.commodity_registry.all_commodities():
        if not commodity.transportable:
            continue
        rows.append(
            MarketRow(
                commodity_id=commodity.id,
                commodity_name=commodity.name,
                price=market.get_avg_price(commodity),
                volume_30d=market.get_30_day_average_volume(commodity),
                scarcity=market.scarcity_pressure_for(commodity),
            )
        )
    return tuple(rows)


def _recent_trades(planet: Planet, limit: int) -> Tuple[TradeRow, ...]:
    """The newest ``limit`` transactions, newest first."""
    transactions = planet.market.transaction_history[-limit:]
    return tuple(
        TradeRow(
            turn=t.turn,
            commodity_name=t.commodity_type.name,
            quantity=t.quantity,
            price=t.price,
            buyer=t.buyer.name,
            seller=t.seller.name,
        )
        for t in reversed(transactions)
    )


def planet_detail(
    planet: Planet, sim: Simulation, trade_limit: int = 8
) -> PlanetDetail:
    """Build the drill-down snapshot the planet overlay renders each frame."""
    total_wealth = sum(
        a.money for a in planet.actors if a.actor_type != ActorType.MARKET_MAKER
    )
    return PlanetDetail(
        name=planet.name,
        population=_regular_population(planet),
        wellbeing=planet_wellbeing(planet),
        total_wealth=total_wealth,
        drives=_drive_stats(planet),
        market=_market_rows(planet, sim),
        docked_ships=tuple(s.name for s in planet.ships),
        recent_trades=_recent_trades(planet, trade_limit),
    )


def ship_detail(ship: Ship, sim: Simulation) -> ShipDetail:
    """Build the drill-down snapshot the ship overlay renders each frame."""
    fuel_commodity = sim.commodity_registry.get_commodity(FUEL_COMMODITY_ID)
    fuel = ship.cargo.get_quantity(fuel_commodity) if fuel_commodity else 0

    cargo_rows = tuple(
        CargoRow(commodity_name=c.name, quantity=q)
        for c, q in sorted(ship.cargo.commodities.items(), key=lambda cq: cq[0].name)
        if q > 0
    )

    if ship.status == ShipStatus.TRAVELING and ship.destination is not None:
        origin_name = ship.planet.name if ship.planet else "?"
        status = "traveling"
        route = f"{origin_name} -> {ship.destination.name} ({ship.travel_progress:.0%})"
    elif ship.status == ShipStatus.NEEDS_MAINTENANCE:
        status = f"needs maintenance at {ship.planet.name}" if ship.planet else "adrift"
        route = ""
    else:
        status = f"docked at {ship.planet.name}" if ship.planet else "adrift"
        route = ""

    return ShipDetail(
        name=ship.name,
        status=status,
        money=ship.money,
        fuel=fuel,
        cargo=cargo_rows,
        cargo_used=ship.cargo.get_total_quantity(),
        cargo_capacity=ship.cargo_capacity,
        route=route,
        last_action=ship.last_action,
    )


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

    def planet_detail(self, name: str) -> Optional[PlanetDetail]:
        """Drill-down snapshot for the named planet, or None if it vanished."""
        for planet in self._sim.planets:
            if planet.name == name:
                return planet_detail(planet, self._sim)
        return None

    def ship_detail(self, name: str) -> Optional[ShipDetail]:
        """Drill-down snapshot for the named ship, or None if it vanished."""
        for ship in self._sim.ships:
            if ship.name == name:
                return ship_detail(ship, self._sim)
        return None
