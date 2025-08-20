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

    def get_actor_turn_log(self, actor:Actor, turn:int = None) -> ActorTurnLog:
        if turn is None:
            turn = self.current_turn
        turn_log_key = (turn, self._get_actor_sim_log_key(actor))
        return self._actor_sim_log[turn_log_key]


