from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Tuple

from spacesim2.core.commodity import CommodityRegistry
from spacesim2.core.planet_attributes import PlanetAttributes
from spacesim2.core.process import ProcessRegistry

if TYPE_CHECKING:
    from spacesim2.core.actor import Actor
    from spacesim2.core.market import Market
    from spacesim2.core.ship import Ship


class Planet:
    """Represents a planet in the simulation.

    Each planet owns a private copy of the read-only economy data
    (``commodity_registry`` / ``process_registry``). Actors on the planet use
    these copies (via ``Actor.commodity_registry``) so that worker threads in
    the parallel actor phase don't contend on one shared set of definition
    objects (refcount traffic on shared objects is the free-threaded scaling
    bottleneck; see docs/performance.md). Definitions hash/compare by ``id``,
    so copies from different registries are interchangeable — cross-planet
    code (ships, navigation, export) keeps using the sim-level registries.

    By default each planet loads its own copy from the standard data files;
    this re-parse is deliberate — it gives every copy its own ``id`` string
    objects, so hot dict lookups don't all touch one shared string either.
    """

    def __init__(
        self,
        name: str,
        market: "Market",
        x: float = 0.0,
        y: float = 0.0,
        attributes: Optional[PlanetAttributes] = None,
        commodity_registry: Optional[CommodityRegistry] = None,
        process_registry: Optional[ProcessRegistry] = None,
    ) -> None:
        self.name = name
        self.x = x
        self.y = y
        self.actors: List["Actor"] = []
        self.ships: List["Ship"] = []  # Ships docked at this planet
        self.market: "Market" = market
        # Default: no resource penalties (all availabilities 1.0).
        self.attributes = attributes if attributes is not None else PlanetAttributes()

        if commodity_registry is None:
            commodity_registry = CommodityRegistry()
            commodity_registry.load_from_file(Path("data") / "commodities.yaml")
        self.commodity_registry = commodity_registry
        if process_registry is None:
            # Built on this planet's commodity registry so process inputs/
            # outputs reference the planet-local commodity objects.
            process_registry = ProcessRegistry(self.commodity_registry)
            process_registry.load_from_file(Path("data") / "processes.yaml")
        self.process_registry = process_registry

    def add_actor(self, actor: "Actor") -> None:
        """Add an actor to this planet."""
        self.actors.append(actor)
        actor.planet = self

    def add_ship(self, ship: "Ship") -> None:
        """Add a ship to this planet."""
        self.ships.append(ship)
        ship.planet = self

    def get_position(self) -> Tuple[float, float]:
        """Get the position of the planet as a tuple."""
        return (self.x, self.y)
