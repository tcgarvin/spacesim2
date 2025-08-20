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
                
                # Display market status
                print(f"  Market Status:")
                market_status = turn_log.market_status
                
                # Currently open orders
                current_orders = market_status.get("current_orders", {})
                if current_orders:
                    print(f"    Currently Open Orders:")
                    for order_id, order_info in current_orders.items():
                        order_type = order_info["type"]
                        commodity = order_info["commodity"]
                        quantity = order_info["quantity"]
                        price = order_info["price"]
                        print(f"      {order_id}: {order_type.upper()} {quantity} {commodity} @ {price}")
                else:
                    print(f"    Currently Open Orders: None")
                
                # Recently closed orders (filled or cancelled)
                events_this_turn = market_status.get("events_this_turn", [])
                closed_events = [event for event in events_this_turn if event["event_type"] in ["filled", "cancelled"]]
                if closed_events:
                    print(f"    Recently Closed Orders:")
                    for event in closed_events:
                        order_details = event["order_details"]
                        status = event["event_type"].upper()
                        order_type = order_details["type"]
                        commodity = order_details["commodity"]
                        quantity = order_details["quantity"]
                        price = order_details["price"]
                        print(f"      {event['order_id']}: {status} - {order_type.upper()} {quantity} {commodity} @ {price}")
                else:
                    print(f"    Recently Closed Orders: None")
                
                # Transactions this turn
                transactions = market_status.get("transactions_this_turn", [])
                if transactions:
                    print(f"    Transactions This Turn:")
                    for tx in transactions:
                        role = tx["role"].upper()
                        commodity = tx["commodity"]
                        quantity = tx["quantity"]
                        price = tx["price"]
                        counterparty = tx["counterparty"]
                        print(f"      {role} {quantity} {commodity} @ {price} (with {counterparty})")
                else:
                    print(f"    Transactions This Turn: None")

        print("Simulation complete!")
