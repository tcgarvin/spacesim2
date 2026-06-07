"""House palette, wellbeing colour ramp, and font loading for the live view.

This consolidates the bits worth salvaging from the deleted ``ui/utils``: the
restrained space palette and the ``pygame.font.SysFont`` loading pattern. When
the offline asset pipeline lands (later build steps), committed sprites will be
loaded here too; for now everything is procedural.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

import pygame

Color = Tuple[int, int, int]

_ASSET_ROOT = Path(__file__).resolve().parent / "assets"

# Restrained, moody space palette (MOO-II-ish: dark void, cool chrome).
BACKGROUND: Color = (6, 7, 16)
STARFIELD_TINTS: Tuple[Color, ...] = (
    (180, 190, 220),  # cool white
    (140, 170, 230),  # blue
    (230, 210, 180),  # warm
)
NEBULA_TINTS: Tuple[Color, ...] = (
    (40, 30, 80),  # violet
    (20, 50, 90),  # teal-blue
    (70, 25, 55),  # magenta
)
TRADE_LANE: Color = (90, 110, 150)
SHIP_BODY: Color = (200, 210, 235)
SHIP_ENGINE: Color = (120, 180, 255)
HUD_TEXT: Color = (190, 200, 225)

# Wellbeing ramp endpoints: famine red -> neutral amber -> thriving green.
_RAMP_LOW: Color = (210, 60, 50)
_RAMP_MID: Color = (220, 190, 90)
_RAMP_HIGH: Color = (90, 210, 120)


def _lerp_color(a: Color, b: Color, t: float) -> Color:
    t = max(0.0, min(1.0, t))
    return (
        int(round(a[0] + (b[0] - a[0]) * t)),
        int(round(a[1] + (b[1] - a[1]) * t)),
        int(round(a[2] + (b[2] - a[2]) * t)),
    )


def wellbeing_color(wellbeing: float) -> Color:
    """Map a wellbeing score in [0, 1] to a famine->thriving colour."""
    w = max(0.0, min(1.0, wellbeing))
    if w < 0.5:
        return _lerp_color(_RAMP_LOW, _RAMP_MID, w / 0.5)
    return _lerp_color(_RAMP_MID, _RAMP_HIGH, (w - 0.5) / 0.5)


class PlanetSprites:
    """Baked planet sprites promoted from the offline asset pipeline.

    Loads every PNG listed in ``assets/planets/index.json`` once (after the
    display is initialised so ``convert_alpha`` works) and hands one out per
    planet by a stable hash, so a given world always keeps the same look. When no
    assets are promoted yet the set is empty and callers fall back to the
    procedural placeholder sphere.
    """

    def __init__(self) -> None:
        self._sprites: List[pygame.Surface] = []
        index_path = _ASSET_ROOT / "planets" / "index.json"
        if not index_path.exists():
            return
        ids = json.loads(index_path.read_text()).get("ids", [])
        for asset_id in ids:
            png = _ASSET_ROOT / "planets" / f"{asset_id}.png"
            if png.exists():
                self._sprites.append(pygame.image.load(str(png)).convert_alpha())

    def __bool__(self) -> bool:
        return bool(self._sprites)

    def for_name(self, name: str) -> pygame.Surface:
        """Return the stable sprite for ``name``. Caller must check truthiness."""
        return self._sprites[abs(hash(name)) % len(self._sprites)]


class Fonts:
    """Lazily-built font set. Must be created after ``pygame.font.init()``."""

    def __init__(self) -> None:
        self._fonts: Dict[str, pygame.font.Font] = {
            "small": pygame.font.SysFont(None, 18),
            "normal": pygame.font.SysFont(None, 24),
            "large": pygame.font.SysFont(None, 32),
        }

    def render(
        self, text: str, size: str = "normal", color: Color = HUD_TEXT
    ) -> pygame.Surface:
        font = self._fonts.get(size, self._fonts["normal"])
        return font.render(text, True, color)
