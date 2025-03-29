from spacesim2.core.simulation import Simulation


class HeadlessUI:
    """Simple text-based interface for running the simulation without graphics."""

    def __init__(self, simulation: Simulation) -> None:
        self.simulation = simulation

    def run(self, num_turns: int) -> None:
        """Run the simulation for the specified number of turns."""
        print(f"Starting simulation for {num_turns} turns...")
        self.simulation.run_simulation(num_turns)
        print("Simulation complete!")
