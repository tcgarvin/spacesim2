import random
from typing import List

from spacesim2.core.actor import Actor
from spacesim2.core.market import Market
from spacesim2.core.planet import Planet


class Simulation:
    """Main simulation controller."""

    def __init__(self) -> None:
        self.planets: List[Planet] = []
        self.actors: List[Actor] = []
        self.current_turn = 0

    def setup_simple(self, num_actors: int = 5) -> None:
        """Set up a simple simulation with one planet and multiple actors.

        Args:
            num_actors: Number of actors to create on the planet.
        """
        # Create a planet
        planet = Planet("Earth")
        self.planets.append(planet)

        # Create and initialize the market for the planet
        market = Market()
        planet.market = market

        # Create specified number of actors
        for i in range(1, num_actors + 1):
            actor = Actor(f"Colonist-{i}", planet)
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

        # Process markets (placeholder for Task 2)
        self._process_markets()

        # Print status after the turn
        self._print_status()

    def _process_markets(self) -> None:
        """Process all markets at the end of the turn.

        For Task 2, this is just a placeholder.
        """
        for planet in self.planets:
            if planet.market:
                # This will be expanded in Task 3
                planet.market.match_orders()
                planet.market.clear_orders()

    def run_simulation(self, num_turns: int) -> None:
        """Run the simulation for a specified number of turns."""
        for _ in range(num_turns):
            self.run_turn()

    def _print_status(self) -> None:
        """Print the current status of the simulation."""
        for planet in self.planets:
            print(f"Planet: {planet.name}")
            for actor in planet.actors:
                print(f"  {actor.name} has {actor.money} credits")
