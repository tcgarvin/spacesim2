from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from spacesim2.core.actor import Actor
    from spacesim2.core.market import Market


class Planet:
    """Represents a planet in the simulation."""

    def __init__(self, name: str, x: float = 0.0, y: float = 0.0) -> None:
        self.name = name
        self.x = x
        self.y = y
        self.actors: List["Actor"] = []
        self.market: Optional["Market"] = None  # Will be set by the simulation

    def add_actor(self, actor: "Actor") -> None:
        """Add an actor to this planet."""
        self.actors.append(actor)
        actor.planet = self
