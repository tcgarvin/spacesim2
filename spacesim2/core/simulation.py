import random
from typing import List

from spacesim2.core.actor import Actor
from spacesim2.core.planet import Planet


class Simulation:
    """Main simulation controller."""

    def __init__(self) -> None:
        self.planets: List[Planet] = []
        self.actors: List[Actor] = []
        self.current_turn = 0

    def setup_simple(self) -> None:
        """Set up a simple simulation with one planet and one actor."""
        planet = Planet("Earth")
        self.planets.append(planet)

        actor = Actor("Colonist-1", planet)
        self.actors.append(actor)
        planet.add_actor(actor)

    def run_turn(self) -> None:
        """Run a single turn of the simulation."""
        self.current_turn += 1
        print(f"\n=== Turn {self.current_turn} ===")

        # Randomize actor order
        random.shuffle(self.actors)

        # Each actor takes their turn
        for actor in self.actors:
            actor.take_turn()

        # Print status after the turn
        self._print_status()

    def run_simulation(self, num_turns: int) -> None:
        """Run the simulation for a specified number of turns."""
        for _ in range(num_turns):
            self.run_turn()

    def _print_status(self) -> None:
        """Print the current status of the simulation."""
        for actor in self.actors:
            print(f"{actor.name} has {actor.money} credits")
