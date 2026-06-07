"""Camera mapping map-space (0..100) to screen pixels, with zoom and pan.

The galaxy lives in a fixed 0..100 square (matches ``Simulation`` planet
positions). The camera centers on a map point and scales by ``zoom`` pixels per
map unit, so panning/zooming never touches entity state.
"""

from __future__ import annotations

from typing import Tuple

MAP_SIZE = 100.0


class Camera:
    def __init__(self, screen_size: Tuple[int, int]) -> None:
        self._screen_w, self._screen_h = screen_size
        # Center on the middle of the map.
        self.center_x = MAP_SIZE / 2.0
        self.center_y = MAP_SIZE / 2.0
        # Fit the whole map with a small margin at startup.
        self.zoom = self._fit_zoom()
        self._min_zoom = self._fit_zoom() * 0.5
        self._max_zoom = self._fit_zoom() * 8.0

    def _fit_zoom(self) -> float:
        return min(self._screen_w, self._screen_h) / (MAP_SIZE * 1.1)

    def resize(self, screen_size: Tuple[int, int]) -> None:
        self._screen_w, self._screen_h = screen_size
        self._min_zoom = self._fit_zoom() * 0.5
        self._max_zoom = self._fit_zoom() * 8.0
        self.zoom = max(self._min_zoom, min(self._max_zoom, self.zoom))

    def world_to_screen(self, pos: Tuple[float, float]) -> Tuple[int, int]:
        x, y = pos
        sx = (x - self.center_x) * self.zoom + self._screen_w / 2.0
        sy = (y - self.center_y) * self.zoom + self._screen_h / 2.0
        return int(round(sx)), int(round(sy))

    def scale(self, map_length: float) -> float:
        """Convert a length in map units to pixels at the current zoom."""
        return map_length * self.zoom

    def zoom_at(self, screen_pos: Tuple[int, int], factor: float) -> None:
        """Zoom by ``factor`` while keeping the map point under the cursor fixed."""
        before = self.screen_to_world(screen_pos)
        self.zoom = max(self._min_zoom, min(self._max_zoom, self.zoom * factor))
        after = self.screen_to_world(screen_pos)
        # Shift center so the cursor stays over the same world point.
        self.center_x += before[0] - after[0]
        self.center_y += before[1] - after[1]

    def screen_to_world(self, screen_pos: Tuple[int, int]) -> Tuple[float, float]:
        sx, sy = screen_pos
        x = (sx - self._screen_w / 2.0) / self.zoom + self.center_x
        y = (sy - self._screen_h / 2.0) / self.zoom + self.center_y
        return x, y

    def pan_pixels(self, dx: int, dy: int) -> None:
        """Drag the view by a pixel delta (mouse drag)."""
        self.center_x -= dx / self.zoom
        self.center_y -= dy / self.zoom
