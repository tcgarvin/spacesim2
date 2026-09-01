"""Turn pacing and anti-slideshow ship interpolation.

The simulation advances in discrete turns, but we render at ~60fps. The director
converts real elapsed time into turn advances (``turns_per_second``) and, between
turns, interpolates each ship's *map position* so ships glide smoothly instead of
teleporting.

Interpolating position (rather than ``travel_progress``) is deliberate: when a
ship arrives, the core resets progress to 0, so interpolating progress would slide
the ship backwards. Positions go origin->along-route->dest monotonically, so a
position lerp always reads as forward motion.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from spacesim2.core.simulation import Simulation
from spacesim2.ui.live.history import HistoryRecorder
from spacesim2.ui.live.view_model import GalaxyViewModel, ShipSnapshot

MIN_SPEED = 0.1
MAX_SPEED = 30.0


def polyline_point(
    waypoints: Sequence[Tuple[float, float]], fraction: float
) -> Tuple[Tuple[float, float], float]:
    """Point at ``fraction`` (0..1) of a polyline's arc length, and its heading.

    Heading is the direction (radians) of the segment the point lies on, so a
    ship visibly turns at each waypoint. A single-point polyline (a docked
    ship) yields that point with heading 0; a degenerate zero-length polyline
    likewise reports heading 0.
    """
    if not waypoints:
        raise ValueError("polyline needs at least one waypoint")
    if len(waypoints) == 1:
        return waypoints[0], 0.0
    fraction = max(0.0, min(1.0, fraction))
    seg_lengths = [
        math.hypot(b[0] - a[0], b[1] - a[1])
        for a, b in zip(waypoints[:-1], waypoints[1:])
    ]
    total = sum(seg_lengths)
    if total == 0.0:
        return waypoints[0], 0.0
    target = fraction * total
    walked = 0.0
    for (ax, ay), (bx, by), length in zip(waypoints[:-1], waypoints[1:], seg_lengths):
        heading = math.atan2(by - ay, bx - ax)
        if walked + length >= target and length > 0.0:
            t = (target - walked) / length
            return (ax + (bx - ax) * t, ay + (by - ay) * t), heading
        walked += length
    # Floating-point slack past the last segment: sit on the destination.
    (ax, ay), (bx, by) = waypoints[-2], waypoints[-1]
    return waypoints[-1], math.atan2(by - ay, bx - ax)


def _route_position(ship: ShipSnapshot) -> Tuple[float, float]:
    return polyline_point(ship.waypoints, ship.progress)[0]


@dataclass(frozen=True)
class RenderedShip:
    snapshot: ShipSnapshot
    pos: Tuple[float, float]  # interpolated map position this frame
    heading: float  # radians, 0 when stationary


class Director:
    def __init__(
        self,
        simulation: Simulation,
        view_model: GalaxyViewModel,
        turns_per_second: float = 1.0,
        paused: bool = False,
    ) -> None:
        self._sim = simulation
        self._vm = view_model
        # Records a turn-0 baseline on construction; updated after each run_turn.
        self.history = HistoryRecorder(simulation)
        self.turns_per_second = max(MIN_SPEED, min(MAX_SPEED, turns_per_second))
        self.paused = paused
        self._accumulator = 0.0
        # Per-ship map position at the start of the current inter-turn interval.
        self._prev_pos: Dict[str, Tuple[float, float]] = {
            s.name: _route_position(s) for s in view_model.ships()
        }

    @property
    def alpha(self) -> float:
        """Fraction [0, 1) through the current inter-turn interval."""
        if self.paused:
            return 0.0
        return min(1.0, self._accumulator * self.turns_per_second)

    def toggle_pause(self) -> None:
        self.paused = not self.paused

    def change_speed(self, factor: float) -> None:
        self.turns_per_second = max(
            MIN_SPEED, min(MAX_SPEED, self.turns_per_second * factor)
        )

    def update(self, dt: float) -> None:
        """Advance real time by ``dt`` seconds, stepping turns as needed."""
        if self.paused:
            return
        self._accumulator += dt
        seconds_per_turn = 1.0 / self.turns_per_second
        # Step at most a few turns per frame so a hitch can't run away.
        steps = 0
        while self._accumulator >= seconds_per_turn and steps < 4:
            self._accumulator -= seconds_per_turn
            self._snapshot_positions()
            self._sim.run_turn()
            self.history.sample()
            steps += 1

    def _snapshot_positions(self) -> None:
        self._prev_pos = {s.name: _route_position(s) for s in self._vm.ships()}

    def rendered_ships(self) -> List[RenderedShip]:
        """Ships at their interpolated positions for this frame."""
        a = self.alpha
        out: List[RenderedShip] = []
        for ship in self._vm.ships():
            curr, heading = polyline_point(ship.waypoints, ship.progress)
            prev = self._prev_pos.get(ship.name, curr)
            pos = (prev[0] + (curr[0] - prev[0]) * a, prev[1] + (curr[1] - prev[1]) * a)
            if not ship.traveling:
                heading = 0.0
            out.append(RenderedShip(snapshot=ship, pos=pos, heading=heading))
        return out
