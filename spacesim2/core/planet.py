from typing import TYPE_CHECKING, List, Dict, Optional, Tuple

if TYPE_CHECKING:
    from spacesim2.core.actor import Actor
    from spacesim2.core.market import Market
    from spacesim2.core.planet_attributes import PlanetAttributes
    from spacesim2.core.ship import Ship


class Planet:
    """Represents a planet in the simulation."""

    def __init__(
        self,
        name: str,
        market: "Market",
        x: float = 0.0,
        y: float = 0.0,
        attributes: Optional["PlanetAttributes"] = None,
    ) -> None:
        self.name = name
        self.x = x
        self.y = y
        self.actors: List["Actor"] = []
        self.ships: List["Ship"] = []  # Ships docked at this planet
        self.market: "Market" = market
        self.attributes = attributes  # None = planet attributes feature disabled

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