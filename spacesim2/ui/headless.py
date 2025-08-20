from spacesim2.core.simulation import Simulation


class HeadlessUI:
    """Simple text-based interface for running the simulation without graphics."""

    def __init__(self, simulation: Simulation) -> None:
        self.simulation = simulation

    def run(self, num_turns: int) -> None:
        """Run the simulation for the specified number of turns."""
        print(f"Starting simulation for {num_turns} turns...")
        for _ in range(num_turns):
            self.simulation.run_turn()
            for actor in self.simulation.data_logger.get_all_logged_actors():
                turn_log = self.simulation.data_logger.get_actor_turn_log(
                    actor=actor
                )
                print(f"Turn {self.simulation.current_turn} log for actor {actor.name}:")
                print(f"  Inventory:")
                for commodity in sorted(turn_log.inventory.keys()):
                    quantity = turn_log.inventory[commodity]
                    if quantity > 0:
                        print(f"    {commodity}: {quantity}")
                print(f"  Notes: {turn_log.notes}")
                print(f"  Commands: {turn_log.commands}")
                print(f"  Metrics:")
                for metric in turn_log.metrics:
                    print(f"    {metric.get_name()}: Health={metric.health:.2f}, Debt={metric.debt:.2f}, Buffer={metric.buffer:.2f}, Urgency={metric.urgency:.2f}")

        print("Simulation complete!")
