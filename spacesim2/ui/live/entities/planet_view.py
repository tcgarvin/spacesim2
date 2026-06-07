"""Draws a planet: shaded placeholder sphere + wellbeing-tinted glow ring + label."""

from __future__ import annotations

import pygame

from spacesim2.ui.live import assets
from spacesim2.ui.live.assets import Fonts
from spacesim2.ui.live.camera import Camera
from spacesim2.ui.live.procgen.placeholders import planet_sprite
from spacesim2.ui.live.view_model import PlanetSnapshot

# Planet visual radius in map units (independent of population for now).
_PLANET_MAP_RADIUS = 2.2


def _stable_seed(name: str) -> int:
    return abs(hash(name)) % 100_000


def draw_planet(
    surface: pygame.Surface,
    planet: PlanetSnapshot,
    camera: Camera,
    fonts: Fonts,
) -> None:
    screen_pos = camera.world_to_screen(planet.pos)
    radius = max(4, int(camera.scale(_PLANET_MAP_RADIUS)))

    glow_color = assets.wellbeing_color(planet.wellbeing)

    # Wellbeing glow ring: a soft halo whose colour reads at a glance.
    glow_r = int(radius * 1.8)
    glow = pygame.Surface((glow_r * 2, glow_r * 2), pygame.SRCALPHA)
    for i in range(3):
        alpha = 40 - i * 12
        pygame.draw.circle(
            glow,
            (*glow_color, max(0, alpha)),
            (glow_r, glow_r),
            glow_r - i * (glow_r // 4),
        )
    surface.blit(glow, (screen_pos[0] - glow_r, screen_pos[1] - glow_r))

    # The body. Base colour is a muted version of the glow so worlds differ.
    body = (
        (glow_color[0] + 60) // 2,
        (glow_color[1] + 60) // 2,
        (glow_color[2] + 80) // 2,
    )
    sprite = planet_sprite(radius, body, _stable_seed(planet.name))
    surface.blit(sprite, (screen_pos[0] - radius, screen_pos[1] - radius))

    # Label below the world.
    label = fonts.render(planet.name, "small", assets.HUD_TEXT)
    surface.blit(
        label,
        (screen_pos[0] - label.get_width() // 2, screen_pos[1] + radius + 4),
    )
