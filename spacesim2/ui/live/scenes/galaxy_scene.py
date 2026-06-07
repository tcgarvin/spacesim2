"""Composes a full galaxy frame: nebula backdrop, planets, ships, minimal HUD.

Layering order is deliberate: backdrop -> trade lanes/ships -> planets on top so
worlds read as the focal points, with a quiet status line at the bottom.
"""

from __future__ import annotations

import pygame

from spacesim2.ui.live import assets
from spacesim2.ui.live.assets import Fonts, PlanetSprites
from spacesim2.ui.live.camera import Camera
from spacesim2.ui.live.director import Director
from spacesim2.ui.live.entities.planet_view import draw_planet
from spacesim2.ui.live.entities.ship_view import draw_ship
from spacesim2.ui.live.procgen.nebula import Nebula
from spacesim2.ui.live.view_model import GalaxyViewModel
from spacesim2.ui.live.widgets.charts_panel import ChartsPanel


class GalaxyScene:
    def __init__(
        self,
        view_model: GalaxyViewModel,
        director: Director,
        camera: Camera,
        size: tuple[int, int],
    ) -> None:
        self._vm = view_model
        self._director = director
        self._camera = camera
        self._nebula = Nebula(size)
        self._fonts = Fonts()
        self._planet_sprites = PlanetSprites()
        self.charts = ChartsPanel(director.history)

    def resize(self, size: tuple[int, int]) -> None:
        self._nebula.resize(size)
        self._camera.resize(size)

    def draw(self, surface: pygame.Surface) -> None:
        # Parallax keys off the camera center so panning drifts the starfield.
        self._nebula.draw(surface, (self._camera.center_x, self._camera.center_y))

        # Ships and lanes under the worlds.
        for rendered in self._director.rendered_ships():
            draw_ship(surface, rendered, self._camera)

        for planet in self._vm.planets():
            draw_planet(
                surface, planet, self._camera, self._fonts, self._planet_sprites
            )

        self.charts.draw(surface, self._fonts)
        self._draw_hud(surface)

    def _draw_hud(self, surface: pygame.Surface) -> None:
        state = "paused" if self._director.paused else "playing"
        line = (
            f"turn {self._vm.current_turn}    "
            f"{self._director.turns_per_second:.1f} turns/s ({state})    "
            f"[space] pause  [+/-] speed  [tab] charts  [wheel] zoom  "
            f"[drag] pan  [esc] quit"
        )
        text = self._fonts.render(line, "small", assets.HUD_TEXT)
        height = surface.get_height()
        surface.blit(text, (12, height - text.get_height() - 10))
