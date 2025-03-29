from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from spacesim2.core.actor import Actor

class Planet:
    """Represents a planet in the simulation."""

    def __init__(self, name: str, x: float = 0.0, y: float = 0.0) -> None:
        self.name = name
        self.x = x
        self.y = y
        self.actors: List["Actor"] = []

    def add_actor(self, actor: "Actor") -> None:
        """Add an actor to this planet."""
        self.actors.append(actor)
        actor.planet = self
