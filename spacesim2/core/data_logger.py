"""
Data logging interface for actors and the simulation.  Should in general be attached to the simulation
"""

from collections import defaultdict
from dataclasses import dataclass, field, replace

from spacesim2.core.actor import Actor
from spacesim2.core.drives.actor_drive import DriveMetrics
from spacesim2.core.commands import Command

@dataclass
class ActorTurnLog:
    notes: list[str] = field(default_factory=list)
    metrics: list[DriveMetrics] = field(default_factory=list)
    commands: list[Command] = field(default_factory=list)
    inventory: dict[str, int] = field(default_factory=dict)
    market_status: dict = field(default_factory=dict)


class DataLogger:
    def __init__(self):
        self._actor_sim_log:dict[str, ActorTurnLog] = defaultdict(ActorTurnLog)
        self.current_turn:int = 0
        self._actors_to_log: dict[str, Actor] = {}

    def set_turn(self, turn:int):
        self.current_turn = turn

    def _get_actor_sim_log_key(self, actor:Actor):
        return f"actor-{actor.name}"

    def is_actor_logged(self, actor:Actor):
        return actor.name in self._actors_to_log

    def get_all_logged_actors(self) -> list[Actor]:
        return list(self._actors_to_log.values())

    def add_actor_to_log(self, actor:Actor):
        self._actors_to_log[actor.name] = actor

    def log_actor_metrics(self,actor:Actor):
        if not self.is_actor_logged(actor):
            return

        turn_log = self._actor_sim_log[(self.current_turn, self._get_actor_sim_log_key(actor))]
        turn_log.metrics = [replace(d.metrics) for d in actor.drives]

    def log_actor_note(self,actor:Actor, note:str):
        if not self.is_actor_logged(actor):
            return

        turn_log = self._actor_sim_log[(self.current_turn, self._get_actor_sim_log_key(actor))]
        turn_log.notes.append(note)

    def log_actor_command(self,actor:Actor, action:Command):
        if not self.is_actor_logged(actor):
            return

        turn_log = self._actor_sim_log[(self.current_turn, self._get_actor_sim_log_key(actor))]
        turn_log.commands.append(action)

    def log_actor_inventory(self, actor:Actor):
        if not self.is_actor_logged(actor):
            return

        turn_log = self._actor_sim_log[(self.current_turn, self._get_actor_sim_log_key(actor))]
        # Convert inventory to dict with commodity names as keys
        turn_log.inventory = {commodity.id: quantity for commodity, quantity in actor.inventory.commodities.items()}

    def log_actor_market_status(self, actor: Actor):
        if not self.is_actor_logged(actor):
            return
        
        # Use actor's method to get this turn's market activity
        market_data = actor.get_market_activity_this_turn()
        
        # Serialize the data for logging
        turn_log = self._actor_sim_log[(self.current_turn, self._get_actor_sim_log_key(actor))]
        turn_log.market_status = {
            "current_orders": market_data.get("current_orders", {}),
            "events_this_turn": [self._serialize_order_event(event) for event in market_data.get("events_this_turn", [])],
            "transactions_this_turn": [self._serialize_transaction(tx, actor) for tx in market_data.get("transactions_this_turn", [])]
        }
    
    def _serialize_order_event(self, event) -> dict:
        """Convert an OrderEvent to a serializable dict."""
        return {
            "order_id": event.order_id,
            "event_type": event.event_type,
            "turn": event.turn,
            "order_details": {
                "commodity": event.order.commodity_type.id,
                "quantity": event.order.quantity,
                "price": event.order.price,
                "type": "buy" if event.order.is_buy else "sell"
            }
        }
    
    def _serialize_transaction(self, transaction, actor) -> dict:
        """Convert a Transaction to a serializable dict."""
        role = "buyer" if transaction.buyer == actor else "seller"
        counterparty = transaction.seller.name if transaction.buyer == actor else transaction.buyer.name
        
        return {
            "commodity": transaction.commodity_type.id,
            "quantity": transaction.quantity,
            "price": transaction.price,
            "total_amount": transaction.total_amount,
            "counterparty": counterparty,
            "role": role,
            "turn": transaction.turn
        }

    def get_actor_turn_log(self, actor:Actor, turn:int = None) -> ActorTurnLog:
        if turn is None:
            turn = self.current_turn
        turn_log_key = (turn, self._get_actor_sim_log_key(actor))
        return self._actor_sim_log[turn_log_key]


