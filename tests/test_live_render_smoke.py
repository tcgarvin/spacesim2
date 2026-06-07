"""Headless render smoke test for the live galaxy view.

Uses SDL's dummy video driver so it runs in CI with no display. Drives the app
through real frames (director steps turns, scene renders) and asserts the output
is non-blank and exception-free.
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import numpy as np  # noqa: E402
import pygame  # noqa: E402

from spacesim2.core.simulation import Simulation  # noqa: E402
from spacesim2.ui.live.app import LiveGalaxyApp  # noqa: E402


def _sim() -> Simulation:
    sim = Simulation()
    sim.setup_simple(
        num_planets=3,
        num_regular_actors=10,
        num_market_makers=1,
        num_ships=2,
    )
    return sim


def test_app_renders_non_blank_frames_over_several_turns() -> None:
    app = LiveGalaxyApp(_sim(), speed=4.0, size=(400, 300))
    try:
        app.initialize()
        # ~30 frames at 50ms each -> a handful of simulation turns.
        for _ in range(30):
            app.update(0.05)
            app.render()

        assert app._screen is not None
        frame = pygame.surfarray.array3d(app._screen)
        # The backdrop alone has nebula/star variation, so the frame must not be
        # a single flat colour.
        assert frame.std() > 1.0
        # And it must contain something brighter than the deep void background.
        assert int(np.max(frame.sum(axis=2))) > 30
    finally:
        pygame.quit()


def test_charts_panel_renders_and_cycles_commodities() -> None:
    app = LiveGalaxyApp(_sim(), speed=4.0, size=(900, 600))
    try:
        app.initialize()
        assert app._scene is not None
        # Panel is visible by default; cycling commodities must not raise even
        # before/while trades accumulate.
        for _ in range(10):
            app.update(0.05)
            app._scene.charts.cycle_commodity(1)
            app.render()
        # Toggle off and confirm rendering still succeeds.
        app._scene.charts.toggle()
        assert app._scene.charts.visible is False
        app.render()

        assert app._screen is not None
        frame = pygame.surfarray.array3d(app._screen)
        assert frame.std() > 1.0
    finally:
        pygame.quit()


def test_app_handles_quit_event() -> None:
    app = LiveGalaxyApp(_sim(), size=(320, 200))
    try:
        app.initialize()
        quit_event = pygame.event.Event(pygame.QUIT)
        assert app.handle_event(quit_event) is False
    finally:
        pygame.quit()
