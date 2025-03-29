from typing import Optional

from spacesim2.core.planet import Planet


class Actor:
    """Represents an economic actor in the simulation."""

    def __init__(self, name: str, planet: Optional[Planet] = None) -> None:
        self.name = name
        self.money = 0
        self.planet = planet

    def take_turn(self) -> None:
        """Perform actions for this turn.

        Each turn consists of:
        1. One economic action (e.g., government work)
        2. Optional market actions (not implemented in Task 2)
        """
        # Step 1: Perform economic action
        self._do_economic_action()

        # Step 2: Perform market actions
        self._do_market_actions()

    def _do_economic_action(self) -> None:
        """Perform a single economic action for this turn.

        For Task 2, the only economic action is government work.
        """
        self._do_government_work()

    def _do_government_work(self) -> None:
        """Perform government work to earn a fixed wage."""
        wage = 10  # Fixed wage for government work
        self.money += wage

    def _do_market_actions(self) -> None:
        """Perform optional market actions for this turn.

        This is a placeholder for Task 2, will be implemented in Task 3.
        """
        # No market actions for Task 2
        pass
