from typing import Optional

from spacesim2.core.planet import Planet


class Actor:
    """Represents an economic actor in the simulation."""

    def __init__(self, name: str, planet: Optional[Planet] = None) -> None:
        self.name = name
        self.money = 0
        self.planet = planet

    def take_turn(self) -> None:
        """Perform actions for this turn."""
        self._do_government_work()

    def _do_government_work(self) -> None:
        """Perform government work to earn a fixed wage."""
        wage = 10  # Fixed wage for government work
        self.money += wage
