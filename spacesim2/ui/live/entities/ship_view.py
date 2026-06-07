"""Draws ships and their trade lanes.

A traveling ship gets a faint origin->dest lane, an engine-glow trail behind it,
and an arrow glyph facing its heading. Docked ships are drawn as a small mark at
their planet.
"""

from __future__ import annotations

import math

import pygame

from spacesim2.ui.live import assets
from spacesim2.ui.live.camera import Camera
from spacesim2.ui.live.director import RenderedShip
from spacesim2.ui.live.procgen.placeholders import ship_glyph

_SHIP_MAP_LENGTH = 1.6  # ship glyph length in map units


def draw_ship(
    surface: pygame.Surface,
    rendered: RenderedShip,
    camera: Camera,
) -> None:
    ship = rendered.snapshot
    screen_pos = camera.world_to_screen(rendered.pos)

    if ship.traveling:
        origin = camera.world_to_screen(ship.origin)
        dest = camera.world_to_screen(ship.dest)
        # Trade lane: a quiet line along the route.
        pygame.draw.line(surface, assets.TRADE_LANE, origin, dest, 1)
        # Engine trail: a short fading segment behind the ship.
        trail_len = int(camera.scale(_SHIP_MAP_LENGTH * 2.5))
        if trail_len > 1:
            heading = rendered.heading
            tx = screen_pos[0] - int(math.cos(heading) * trail_len)
            ty = screen_pos[1] - int(math.sin(heading) * trail_len)
            trail = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
            pygame.draw.line(trail, (*assets.SHIP_ENGINE, 90), (tx, ty), screen_pos, 2)
            surface.blit(trail, (0, 0))

    length = max(6, int(camera.scale(_SHIP_MAP_LENGTH)))
    glyph = ship_glyph(length, rendered.heading, assets.SHIP_BODY, assets.SHIP_ENGINE)
    surface.blit(
        glyph,
        (
            screen_pos[0] - glyph.get_width() // 2,
            screen_pos[1] - glyph.get_height() // 2,
        ),
    )
