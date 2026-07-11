"""Composes a full galaxy frame and owns map interaction state.

Layering order is deliberate: backdrop -> trade lanes/ships -> planets on top so
worlds read as the focal points, then selection chrome, charts, the drill-down
panel, and a quiet HUD. The scene also owns picking: hovering highlights a
planet or ship, clicking selects it and opens a live detail panel, and the
charts strip scopes itself to the selected planet's market.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

import pygame

from spacesim2.ui.live.assets import Fonts, GoodIcons, PlanetSprites, ShipSprites
from spacesim2.ui.live.camera import Camera
from spacesim2.ui.live.director import Director
from spacesim2.ui.live.entities.planet_view import PLANET_MAP_RADIUS, draw_planet
from spacesim2.ui.live.entities.ship_view import SHIP_MAP_LENGTH, draw_ship
from spacesim2.ui.live.procgen.nebula import Nebula
from spacesim2.ui.live.view_model import GalaxyViewModel
from spacesim2.ui.live.widgets import hud, info_panel
from spacesim2.ui.live.widgets.charts_panel import ChartsPanel

# (kind, name) where kind is "planet" or "ship".
Selection = Tuple[str, str]

_PICK_SLOP_PX = 8  # extra grab room around small targets
_HOVER_RING = (160, 175, 210)
_SELECT_RING = (235, 220, 160)


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
        # Baked sprite sets are loaded once here (after the display exists so
        # convert_alpha works) and threaded down; never per-frame or via globals.
        self._planet_sprites = PlanetSprites()
        self._ship_sprites = ShipSprites()
        self._good_icons = GoodIcons()
        self.charts = ChartsPanel(director.history)
        self.selection: Optional[Selection] = None
        self.hover: Optional[Selection] = None
        self._panel_rect: Optional[pygame.Rect] = None

    def resize(self, size: tuple[int, int]) -> None:
        self._nebula.resize(size)
        self._camera.resize(size)

    # -- Picking ---------------------------------------------------------

    def pick(self, pos: Tuple[int, int]) -> Optional[Selection]:
        """The planet or ship under ``pos``, planets taking priority."""
        planet_r = max(4, int(self._camera.scale(PLANET_MAP_RADIUS)))
        for planet in self._vm.planets():
            px, py = self._camera.world_to_screen(planet.pos)
            if math.hypot(pos[0] - px, pos[1] - py) <= planet_r + _PICK_SLOP_PX:
                return ("planet", planet.name)
        ship_r = max(8, int(self._camera.scale(SHIP_MAP_LENGTH)))
        for rendered in self._director.rendered_ships():
            sx, sy = self._camera.world_to_screen(rendered.pos)
            if math.hypot(pos[0] - sx, pos[1] - sy) <= ship_r + _PICK_SLOP_PX:
                return ("ship", rendered.snapshot.name)
        return None

    def handle_click(self, pos: Tuple[int, int]) -> None:
        """Select what's under the cursor; a void click clears the selection.

        Clicks landing on the open detail panel are swallowed so interacting
        with (or just touching) the panel doesn't deselect through it.
        """
        if self._panel_rect is not None and self._panel_rect.collidepoint(pos):
            return
        self.selection = self.pick(pos)

    def update_hover(self, pos: Tuple[int, int]) -> None:
        if self._panel_rect is not None and self._panel_rect.collidepoint(pos):
            self.hover = None
            return
        self.hover = self.pick(pos)

    def clear_selection(self) -> bool:
        """Drop the current selection. Returns True if there was one."""
        if self.selection is None:
            return False
        self.selection = None
        return True

    @property
    def selected_planet(self) -> Optional[str]:
        if self.selection and self.selection[0] == "planet":
            return self.selection[1]
        return None

    # -- Drawing ---------------------------------------------------------

    def draw(self, surface: pygame.Surface) -> None:
        # Parallax keys off the camera center so panning drifts the starfield.
        self._nebula.draw(surface, (self._camera.center_x, self._camera.center_y))

        # Ships and lanes under the worlds.
        for rendered in self._director.rendered_ships():
            draw_ship(surface, rendered, self._camera, self._ship_sprites)

        # Wall-clock time drives the distress pulse on suffering worlds.
        time_s = pygame.time.get_ticks() / 1000.0
        for planet in self._vm.planets():
            draw_planet(
                surface, planet, self._camera, self._fonts, self._planet_sprites, time_s
            )

        self._draw_rings(surface)
        # Shrink the chart strip so the drill-down panel never covers it.
        reserve = info_panel.PANEL_W + info_panel.MARGIN if self.selection else 0
        self.charts.draw(surface, self._fonts, self.selected_planet, reserve)
        self._panel_rect = self._draw_detail_panel(surface)
        hud.draw_status_strip(surface, self._fonts, self._vm, self._director)
        hud.draw_help_line(surface, self._fonts, self.selection is not None)

    def _ring_center(self, target: Selection) -> Optional[Tuple[int, int, int]]:
        """Screen (x, y, radius) for a selection ring, or None if it vanished."""
        kind, name = target
        if kind == "planet":
            for planet in self._vm.planets():
                if planet.name == name:
                    x, y = self._camera.world_to_screen(planet.pos)
                    r = max(4, int(self._camera.scale(PLANET_MAP_RADIUS))) + 6
                    return (x, y, r)
            return None
        for rendered in self._director.rendered_ships():
            if rendered.snapshot.name == name:
                x, y = self._camera.world_to_screen(rendered.pos)
                r = max(8, int(self._camera.scale(SHIP_MAP_LENGTH))) + 4
                return (x, y, r)
        return None

    def _draw_rings(self, surface: pygame.Surface) -> None:
        if self.hover is not None and self.hover != self.selection:
            ring = self._ring_center(self.hover)
            if ring is not None:
                pygame.draw.circle(surface, _HOVER_RING, ring[:2], ring[2], 1)
        if self.selection is not None:
            ring = self._ring_center(self.selection)
            if ring is not None:
                pygame.draw.circle(surface, _SELECT_RING, ring[:2], ring[2], 2)

    def _draw_detail_panel(self, surface: pygame.Surface) -> Optional[pygame.Rect]:
        if self.selection is None:
            return None
        kind, name = self.selection
        if kind == "planet":
            planet = self._vm.planet_detail(name)
            if planet is None:
                self.selection = None
                return None
            return info_panel.draw_planet_panel(
                surface, self._fonts, planet, self._good_icons
            )
        ship = self._vm.ship_detail(name)
        if ship is None:
            self.selection = None
            return None
        return info_panel.draw_ship_panel(surface, self._fonts, ship, self._good_icons)
